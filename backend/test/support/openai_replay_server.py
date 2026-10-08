"""为 assembled-path E2E 提供最小 OpenAI 兼容确定性响应。"""

from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock
from urllib.parse import parse_qs, urlparse

EXPECTED_OUTPUT = "DETERMINISTIC_AGENT_E2E_OK"
EXPECTED_AUTHORIZATION = "Bearer ci-replay-key"
EXPECTED_MODEL = "deterministic-chat"
EXPECTED_PRELOADED_SKILL_MARKER = "# 图片生成技能"
EXPECTED_PRELOADED_TOOL = "present_artifacts"
EXPECTED_TOOL_CALL_ID = "call-preloaded-tool"
EXPECTED_TOOL_RESULT_MARKER = "已将交付物展示给用户"
BLOCK_BEFORE_RESPONSE_MARKER = "DETERMINISTIC_BLOCK_BEFORE_RESPONSE"
TOOL_ERROR_MARKER = "DETERMINISTIC_TOOL_ERROR"
LARGE_TOOL_RESULT_MARKER = "DETERMINISTIC_LARGE_TOOL_RESULT"
LARGE_TOOL_CALL_ID = "call-large-tool-result"
BLOCKING_REQUEST_TOKENS: set[str] = set()
BLOCKING_REQUEST_TOKENS_LOCK = Lock()
SUBAGENT_GATES: dict[str, Event] = {}
CONNECTOR_RECORDS: dict[str, dict] = {}
CONNECTOR_RECEIPTS: dict[str, list[str]] = {}
CONNECTOR_RESPONSE_DELAYS: dict[str, float] = {}
CONNECTOR_LOCK = Lock()


def validate_request(authorization: str | None, request: dict) -> str | None:
    """拒绝没有走预期模型适配契约的 replay 请求。"""

    if authorization != EXPECTED_AUTHORIZATION:
        return "invalid_authorization"
    if request.get("model") != EXPECTED_MODEL:
        return "invalid_model"
    if request.get("stream") is not True:
        return "stream_required"
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        return "messages_required"
    serialized_messages = json.dumps(messages, ensure_ascii=False)
    if EXPECTED_OUTPUT not in serialized_messages:
        return "expected_input_missing"
    if EXPECTED_PRELOADED_SKILL_MARKER not in serialized_messages:
        return "preloaded_skill_missing"
    tools = request.get("tools")
    tool_names = {
        item.get("function", {}).get("name")
        for item in tools or []
        if isinstance(item, dict) and isinstance(item.get("function"), dict)
    }
    subagent_child = "DETERMINISTIC_SUBAGENT_CHILD" in serialized_messages
    subagent_parent = "DETERMINISTIC_SUBAGENT_PARENT:" in serialized_messages
    if subagent_child:
        trusted = "SUBAGENT_MODE:always_trust" in serialized_messages
        if ("write_file" in tool_names) != trusted or "task" in tool_names:
            return "subagent_tool_policy_mismatch"
    elif EXPECTED_PRELOADED_TOOL not in tool_names:
        return "preloaded_tool_missing"
    if LARGE_TOOL_RESULT_MARKER in serialized_messages and "execute" not in tool_names:
        return "execute_tool_missing"
    tool_messages = [message for message in messages if isinstance(message, dict) and message.get("role") == "tool"]
    connector_tool = re.search(r"DETERMINISTIC_CONNECTOR_TOOL:([\w-]+)", serialized_messages)
    if connector_tool:
        if connector_tool.group(1) not in tool_names:
            return "connector_tool_missing"
        expected_value = re.search(r"CONNECTOR_VALUE:([\w-]+)", serialized_messages).group(1)
        for message in tool_messages:
            if message.get("tool_call_id") != "call-connector":
                continue
            try:
                result = json.loads(message["content"])
                expected_error = re.search(r"CONNECTOR_EXPECT_ERROR:([\w-]+)", serialized_messages)
                if expected_error:
                    if (
                        result.get("invocation_id")
                        and result.get("error_code") == expected_error.group(1) == "approval_rejected"
                        and result.get("remote_outcome") == "not_sent"
                    ):
                        return None
                    return "connector_tool_result_missing"
                if (
                    result.get("invocation_id")
                    and result.get("result", {}).get("record", {}).get("value") == expected_value
                ):
                    return None
            except (TypeError, ValueError):
                pass
            return "connector_tool_result_missing"
        return "connector_tool_result_missing" if tool_messages else None
    if subagent_child or subagent_parent:
        expected_call = "call-subagent-write" if subagent_child else "call-subagent-start"
        if (
            subagent_parent
            and not subagent_child
            and ("task" in tool_names or not {"subagent_start", "subagent_await"} <= tool_names)
        ):
            return "subagent_lifecycle_tools_missing"
        if tool_messages and not any(message.get("tool_call_id") == expected_call for message in tool_messages):
            return "subagent_tool_result_missing"
        return None
    if tool_messages and not any(
        (
            message.get("tool_call_id") == EXPECTED_TOOL_CALL_ID
            and (
                EXPECTED_TOOL_RESULT_MARKER in str(message.get("content", ""))
                or TOOL_ERROR_MARKER in serialized_messages
            )
        )
        or (
            LARGE_TOOL_RESULT_MARKER in serialized_messages
            and message.get("tool_call_id") == LARGE_TOOL_CALL_ID
            and "Tool result too large" in str(message.get("content", ""))
        )
        for message in tool_messages
    ):
        return "tool_execution_result_missing"
    return None


def stream_payloads(model: str, messages: list[dict]) -> list[dict]:
    serialized_messages = json.dumps(messages, ensure_ascii=False)
    common = {
        "id": "chatcmpl-yuxi-deterministic",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
    }
    tool_results = {
        message.get("tool_call_id"): message.get("content") for message in messages if message.get("role") == "tool"
    }
    parent = (
        "DETERMINISTIC_SUBAGENT_PARENT:" in serialized_messages
        and "DETERMINISTIC_SUBAGENT_CHILD" not in serialized_messages
    )
    observation = "SUBAGENT_OBSERVATION_GATE:" in serialized_messages
    waiting_call = None
    if parent and tool_results:
        starts = ["call-subagent-slow", "call-subagent-start"] if observation else ["call-subagent-start"]
        waiting_call = next((call for call in starts if f"await-{call}" not in tool_results), None)
    if tool_results and waiting_call is None:
        return [
            {
                **common,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": EXPECTED_OUTPUT},
                        "finish_reason": None,
                    }
                ],
            },
            {
                **common,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            },
        ]

    large_result = LARGE_TOOL_RESULT_MARKER in serialized_messages
    tool_call_id = LARGE_TOOL_CALL_ID if large_result else EXPECTED_TOOL_CALL_ID
    tool_name = "execute" if large_result else EXPECTED_PRELOADED_TOOL
    connector_tool = re.search(r"DETERMINISTIC_CONNECTOR_TOOL:([\w-]+)", serialized_messages)
    if connector_tool:
        tool_call_id, tool_name = "call-connector", connector_tool.group(1)
        params = {"record_id": re.search(r"CONNECTOR_RECORD:([\w-]+)", serialized_messages).group(1)}
        if tool_name.endswith("__write"):
            params["value"] = re.search(r"CONNECTOR_VALUE:([\w-]+)", serialized_messages).group(1)
        tool_arguments = json.dumps(params)
    elif waiting_call:
        started = json.loads(tool_results[waiting_call])
        tool_call_id, tool_name = f"await-{waiting_call}", "subagent_await"
        tool_arguments = json.dumps({"run_id": started["run_id"]})
    elif "DETERMINISTIC_SUBAGENT_CHILD" in serialized_messages:
        tool_call_id, tool_name = "call-subagent-write", "write_file"
        path = re.search(r'SUBAGENT_PATH:(/[^\s"\\]+)', serialized_messages).group(1)
        tool_arguments = json.dumps({"file_path": path, "content": "subagent write verified"})
    elif "DETERMINISTIC_SUBAGENT_PARENT:" in serialized_messages:
        tool_call_id, tool_name = "call-subagent-start", "subagent_start"
        slug = re.search(r"DETERMINISTIC_SUBAGENT_PARENT:([\w-]+)", serialized_messages).group(1)
        description = next(message["content"] for message in reversed(messages) if message.get("role") == "user")
        tool_arguments = json.dumps({"subagent_slug": slug, "description": description})
    elif large_result:
        tool_arguments = json.dumps({"command": "yes X | head -c 13000"})
    elif TOOL_ERROR_MARKER in serialized_messages:
        tool_arguments = "{}"
    else:
        tool_arguments = '{"filepaths": []}'

    payloads = [
        {
            **common,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": tool_arguments,
                                },
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            **common,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        },
    ]

    if parent and observation and not tool_results:
        args = json.loads(tool_arguments)
        args["description"] += " SUBAGENT_SLOW"
        payloads[0]["choices"][0]["delta"]["tool_calls"].append(
            {
                "index": 1,
                "id": "call-subagent-slow",
                "type": "function",
                "function": {"name": "subagent_start", "arguments": json.dumps(args)},
            }
        )
    return payloads


class ReplayHandler(BaseHTTPRequestHandler):
    """只实现测试所需的 health 与 chat completions 协议。"""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/connector/"):
            record_id = parsed.path.rsplit("/", 1)[-1]
            with CONNECTOR_LOCK:
                if parsed.path.startswith("/connector/ledger/"):
                    payload = {
                        "requests": list(CONNECTOR_RECEIPTS.get(record_id, [])),
                        "record": CONNECTOR_RECORDS.get(record_id),
                    }
                elif record_id in CONNECTOR_RECORDS:
                    CONNECTOR_RECEIPTS.setdefault(record_id, []).append("GET")
                    payload = {"record": dict(CONNECTOR_RECORDS[record_id])}
                else:
                    self._write_json(404, {"error": "fixture_missing"})
                    return
            self._write_json(200, payload)
            return
        if parsed.path == "/release-subagent":
            token = parse_qs(parsed.query).get("token", [""])[0]
            with BLOCKING_REQUEST_TOKENS_LOCK:
                SUBAGENT_GATES.setdefault(token, Event()).set()
            self._write_json(200, {"released": True})
            return
        if parsed.path == "/health":
            self._write_json(200, {"status": "ok"})
            return
        if parsed.path == "/blocking-started":
            token = (parse_qs(parsed.query).get("token") or [""])[0]
            with BLOCKING_REQUEST_TOKENS_LOCK:
                started = token in BLOCKING_REQUEST_TOKENS
            self._write_json(200, {"started": started})
            return
        self._write_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/connector/"):
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            record_id = str(body.get("record_id") or self.path.rsplit("/", 1)[-1])
            delay = body.get("response_delay_seconds", 0)
            if type(delay) not in (int, float) or not 0 <= delay <= 3:
                self._write_json(400, {"error": "fixture_delay_invalid"})
                return
            with CONNECTOR_LOCK:
                if self.path == "/connector/fixtures":
                    CONNECTOR_RECORDS[record_id] = {"id": record_id, "value": body["value"]}
                    CONNECTOR_RECEIPTS[record_id] = []
                    CONNECTOR_RESPONSE_DELAYS[record_id] = delay
                else:
                    if record_id not in CONNECTOR_RECORDS:
                        self._write_json(404, {"error": "fixture_missing"})
                        return
                    CONNECTOR_RECEIPTS[record_id].append("POST")
                    CONNECTOR_RECORDS[record_id]["value"] = body["value"]
                payload = {"record": dict(CONNECTOR_RECORDS[record_id])}
                response_delay = (
                    0 if self.path == "/connector/fixtures" else CONNECTOR_RESPONSE_DELAYS.get(record_id, 0)
                )
            if response_delay:
                time.sleep(response_delay)
            self._write_json(200, payload)
            return
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._write_json(404, {"error": "not_found"})
            return

        try:
            length = int(self.headers.get("content-length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._write_json(400, {"error": "invalid_json"})
            return

        request_error = validate_request(self.headers.get("authorization"), request)
        if request_error:
            self._write_json(422, {"error": request_error})
            return

        messages = request["messages"]
        serialized_messages = json.dumps(messages, ensure_ascii=False)
        if "DETERMINISTIC_RATE_LIMIT" in serialized_messages:
            last_user = max(index for index, message in enumerate(messages) if message.get("role") == "user")
            messages = [message for message in messages[:last_user] if message.get("role") == "system"] + messages[
                last_user:
            ]
            is_parent = (
                "DETERMINISTIC_SUBAGENT_PARENT:" in serialized_messages
                and "DETERMINISTIC_SUBAGENT_CHILD" not in serialized_messages
            )
            has_tool_result = any(message.get("role") == "tool" for message in messages)
            if not is_parent and (has_tool_result or "RATE_LIMIT_FIRST_CALL" in serialized_messages):
                self._write_json(
                    429,
                    {"error": {"message": "DETERMINISTIC_RATE_LIMIT exhausted", "type": "rate_limit_error"}},
                )
                return
        gate = re.search(r"SUBAGENT_OBSERVATION_GATE:([0-9a-f-]+)", serialized_messages)
        if gate and "DETERMINISTIC_SUBAGENT_CHILD" in serialized_messages and "SUBAGENT_SLOW" in serialized_messages:
            with BLOCKING_REQUEST_TOKENS_LOCK:
                event = SUBAGENT_GATES.setdefault(gate.group(1), Event())
            if not event.wait(60):
                self._write_json(504, {"error": "subagent_gate_timeout"})
                return
        blocking_match = re.search(rf"{BLOCK_BEFORE_RESPONSE_MARKER}:([0-9a-f-]+)", serialized_messages)
        model = str(request["model"])
        payloads = stream_payloads(model, messages)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        if blocking_match:
            self.wfile.write(f"data: {json.dumps(payloads.pop(0))}\n\n".encode())
            self.wfile.flush()
            with BLOCKING_REQUEST_TOKENS_LOCK:
                BLOCKING_REQUEST_TOKENS.add(blocking_match.group(1))
            time.sleep(60)
        for payload in payloads:
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_DELETE(self) -> None:  # noqa: N802
        """只清理本测试显式创建的业务 fixture。"""
        if not self.path.startswith("/connector/fixtures/"):
            self._write_json(404, {"error": "not_found"})
            return
        record_id = self.path.rsplit("/", 1)[-1]
        with CONNECTOR_LOCK:
            CONNECTOR_RECORDS.pop(record_id, None)
            CONNECTOR_RECEIPTS.pop(record_id, None)
            CONNECTOR_RESPONSE_DELAYS.pop(record_id, None)
        self._write_json(200, {"deleted": True})

    def _write_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), ReplayHandler).serve_forever()


if __name__ == "__main__":
    main()
