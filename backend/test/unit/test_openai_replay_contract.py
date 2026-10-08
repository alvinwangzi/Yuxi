"""确定性模型替身的协议拒绝条件。"""

import pytest
import json

from test.support.openai_replay_server import validate_request
from test.support.openai_replay_server import stream_payloads


@pytest.mark.parametrize(
    ("authorization", "change", "expected_error"),
    [
        (None, {}, "invalid_authorization"),
        ("Bearer ci-replay-key", {"model": "other-model"}, "invalid_model"),
        ("Bearer ci-replay-key", {"stream": False}, "stream_required"),
        ("Bearer ci-replay-key", {"messages": [{"role": "user", "content": "wrong"}]}, "expected_input_missing"),
        (
            "Bearer ci-replay-key",
            {"messages": [{"role": "user", "content": "DETERMINISTIC_AGENT_E2E_OK"}]},
            "preloaded_skill_missing",
        ),
        ("Bearer ci-replay-key", {"tools": []}, "preloaded_tool_missing"),
    ],
)
def test_replay_rejects_invalid_model_contract(authorization, change, expected_error):
    """模型替身必须拒绝未经过预期适配层的请求。"""
    body = {
        "model": "deterministic-chat",
        "stream": True,
        "messages": [
            {"role": "system", "content": "# 图片生成技能"},
            {"role": "user", "content": "DETERMINISTIC_AGENT_E2E_OK"},
        ],
        "tools": [{"type": "function", "function": {"name": "present_artifacts"}}],
    }
    assert validate_request(authorization, {**body, **change}) == expected_error


def test_replay_rejects_unexpected_tool_result():
    """工具结果与 replay 剧本不一致时拒绝继续。"""
    body = {
        "model": "deterministic-chat",
        "stream": True,
        "messages": [
            {"role": "system", "content": "# 图片生成技能"},
            {"role": "user", "content": "DETERMINISTIC_AGENT_E2E_OK"},
            {"role": "tool", "tool_call_id": "call-preloaded-tool", "content": "unexpected result"},
        ],
        "tools": [{"type": "function", "function": {"name": "present_artifacts"}}],
    }
    assert validate_request("Bearer ci-replay-key", body) == "tool_execution_result_missing"


def test_connector_replay_requires_requested_tool_and_actual_successful_tool_message():
    """无工具或伪造成功不能被确定性模型脚本接受。"""
    body = {
        "model": "deterministic-chat",
        "stream": True,
        "messages": [
            {
                "role": "system",
                "content": "# 图片生成技能 DETERMINISTIC_CONNECTOR_TOOL:cn_test__read "
                "CONNECTOR_RECORD:fixture CONNECTOR_VALUE:original",
            },
            {"role": "user", "content": "DETERMINISTIC_AGENT_E2E_OK"},
        ],
        "tools": [{"function": {"name": "present_artifacts"}}],
    }
    assert validate_request("Bearer ci-replay-key", body) == "connector_tool_missing"
    body["tools"].append({"function": {"name": "cn_test__read"}})
    assert validate_request("Bearer ci-replay-key", body) is None
    payloads = stream_payloads(body["model"], body["messages"])
    call = payloads[0]["choices"][0]["delta"]["tool_calls"][0]
    assert call["id"] == "call-connector" and call["function"]["name"] == "cn_test__read"
    body["messages"].append({"role": "tool", "tool_call_id": "call-connector", "content": "{}"})
    assert validate_request("Bearer ci-replay-key", body) == "connector_tool_result_missing"


@pytest.mark.parametrize(
    "expected,result,error",
    [
        (
            True,
            {"invocation_id": "owned-invocation", "error_code": "approval_rejected", "remote_outcome": "not_sent"},
            None,
        ),
        (
            False,
            {"invocation_id": "owned-invocation", "error_code": "approval_rejected", "remote_outcome": "not_sent"},
            "connector_tool_result_missing",
        ),
        (
            True,
            {"invocation_id": "owned-invocation", "error_code": "provider_error", "remote_outcome": "not_sent"},
            "connector_tool_result_missing",
        ),
        (True, {"error_code": "approval_rejected", "remote_outcome": "not_sent"}, "connector_tool_result_missing"),
    ],
)
def test_rejection_replay_accepts_only_explicit_controlled_refusal(expected, result, error):
    """独立拒绝剧本要求精确错误及未发送事实，成功剧本仍不能接受错误。"""
    body = {
        "model": "deterministic-chat",
        "stream": True,
        "tools": [{"function": {"name": "present_artifacts"}}, {"function": {"name": "cn_test__write"}}],
        "messages": [
            {
                "role": "system",
                "content": "# 图片生成技能 DETERMINISTIC_CONNECTOR_TOOL:cn_test__write "
                "CONNECTOR_RECORD:fixture CONNECTOR_VALUE:repaired"
                + (" CONNECTOR_EXPECT_ERROR:approval_rejected" if expected else ""),
            },
            {"role": "user", "content": "DETERMINISTIC_AGENT_E2E_OK"},
            {"role": "tool", "tool_call_id": "call-connector", "content": json.dumps(result)},
        ],
    }
    assert validate_request("Bearer ci-replay-key", body) == error
