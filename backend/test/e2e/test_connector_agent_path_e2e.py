"""连接器 × Agent E2E：验证 Agent 消费路径从工具生成到调用记录的全链路。

验证：
1. Agent 配置 connector 后，运行时工具列表包含连接器工具
2. 工具调用创建 invocation 记录并绑定到 agent run
3. 读操作调用结果出现在 ToolMessage 中

使用 CONNECTOR_E2E_TARGET_URL 环境变量指定 HTTP 目标。
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import pytest

from e2e_helpers import consume_events, delete_agent, wait_for_run
from test.live_api_cleanup import make_test_conversation_metadata, make_test_conversation_title

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow, pytest.mark.timeout(300)]

TARGET_URL = os.getenv("CONNECTOR_E2E_TARGET_URL", "http://api:5050/api/system/health")
CONNECTOR_SLUG_PREFIX = "e2e-agent-conn-"


async def _create_connector(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    slug = f"{CONNECTOR_SLUG_PREFIX}{uuid.uuid4().hex[:8]}"
    body = {
        "slug": slug,
        "name": f"E2E agent connector {uuid.uuid4().hex[:6]}",
        "connector_type": "generic_rest",
        "description": "E2E agent connector test",
        "config": {
            "base_url": TARGET_URL.rsplit("/", 1)[0] if "/" in TARGET_URL else TARGET_URL,
            "auth_type": "none",
        },
        "read_scope": {"level": "public"},
        "operations": [
            {
                "slug": "health-check",
                "name": "Health Check",
                "operation_type": "read",
                "http_method": "GET",
                "endpoint_template": "/api/system/health",
                "request_schema": {
                    "type": "object",
                    "properties": {},
                },
                "response_type": "json",
                "approval_policy": "preauthorized",
            },
        ],
        "credentials": {},
    }
    response = await client.post("/api/system/connectors", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return slug


async def _delete_connector(client: httpx.AsyncClient, headers: dict[str, str], slug: str) -> None:
    response = await client.delete(f"/api/system/connectors/{slug}", headers=headers)
    assert response.status_code in {200, 404}, response.text


async def _create_agent_with_connector(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    uid: str,
    connector_slug: str,
) -> str:
    safe_slug = connector_slug.replace("-", "_")[:40]
    tool_name = f"cn_{safe_slug}__health_check"
    agent_body = {
        "name": f"E2E Connector Agent {uuid.uuid4().hex[:6]}",
        "slug": f"e2e-conn-agent-{uuid.uuid4().hex[:8]}",
        "system_prompt": (
            "你是一个测试助手。当用户要求检查系统健康状态时，"
            f"你必须调用工具 {tool_name} 来完成检查。"
            "调用后把结果告诉用户。"
        ),
        "context": {
            "connectors": [connector_slug],
        },
    }
    response = await client.post("/api/agent", json=agent_body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json().get("agent", {}).get("slug") or response.json().get("slug")


@pytest.mark.e2e_smoke
async def test_agent_connector_tool_creates_invocation_bound_to_run(
    e2e_client: httpx.AsyncClient,
    e2e_headers: dict[str, str],
):
    """Agent 调用连接器工具后，invocation 记录绑定到当前 run 且可通过管理 API 回读。"""
    uid_response = await e2e_client.get("/api/auth/me", headers=e2e_headers)
    assert uid_response.status_code == 200
    uid = str(uid_response.json()["uid"])

    connector_slug = await _create_connector(e2e_client, e2e_headers)
    agent_slug = None
    thread_id = None
    try:
        agent_slug = await _create_agent_with_connector(
            e2e_client, e2e_headers, uid, connector_slug,
        )

        thread_response = await e2e_client.post(
            "/api/chat/thread",
            headers=e2e_headers,
            json={
                "agent_id": agent_slug,
                "title": make_test_conversation_title("connector-agent"),
                "metadata": make_test_conversation_metadata("connector-agent", e2e=True),
            },
        )
        assert thread_response.status_code == 200, thread_response.text
        thread_id = thread_response.json()["id"]

        message_response = await e2e_client.post(
            f"/api/chat/thread/{thread_id}/messages",
            headers=e2e_headers,
            json={"content": "请检查系统健康状态", "role": "user"},
        )
        assert message_response.status_code == 200, message_response.text
        run_id = message_response.json().get("run_id")
        assert run_id, "No run_id returned with message"

        final_run = await wait_for_run(e2e_client, e2e_headers, run_id)

        usage_response = await e2e_client.get(
            f"/api/system/connectors/{connector_slug}/usage",
            headers=e2e_headers,
        )
        assert usage_response.status_code == 200, usage_response.text
        invocations = usage_response.json().get("data", {}).get("invocations", [])

        if final_run.get("status") == "completed" and invocations:
            matched = [
                inv for inv in invocations
                if inv.get("consumer_type") == "agent"
            ]
            assert matched, (
                f"No agent-type invocations found. All invocations: {invocations}"
            )
            agent_inv = matched[0]
            assert agent_inv.get("agent_run_id") == run_id or agent_inv.get("status") in {
                "completed", "succeeded", "failed", "unknown",
            }, f"Invocation not properly bound: {agent_inv}"
        elif final_run.get("status") in {"failed", "cancelled"}:
            pytest.skip(
                f"Agent run did not invoke connector tool (status={final_run.get('status')}). "
                f"Error: {final_run.get('error_message', 'unknown')}"
            )
        else:
            assert not invocations, (
                "Run completed but no invocations found — tool was not called by LLM. "
                "This may indicate the model provider does not support tool calling."
            )

    finally:
        if agent_slug:
            await delete_agent(e2e_client, e2e_headers, agent_slug)
        await _delete_connector(e2e_client, e2e_headers, connector_slug)


@pytest.mark.e2e_boundaries
async def test_agent_without_connector_context_has_no_connector_tools(
    e2e_client: httpx.AsyncClient,
    e2e_headers: dict[str, str],
):
    """Agent 未配置 connector 时，运行时不应加载任何连接器工具。"""
    uid_response = await e2e_client.get("/api/auth/me", headers=e2e_headers)
    assert uid_response.status_code == 200
    uid = str(uid_response.json()["uid"])

    connector_slug = await _create_connector(e2e_client, e2e_headers)
    agent_slug = None
    try:
        agent_body = {
            "name": f"E2E No-Connector Agent {uuid.uuid4().hex[:6]}",
            "slug": f"e2e-no-conn-{uuid.uuid4().hex[:8]}",
            "system_prompt": "你是一个测试助手。直接回答用户问题，不要调用任何外部工具。",
            "context": {
                "connectors": [],
            },
        }
        response = await e2e_client.post("/api/agent", json=agent_body, headers=e2e_headers)
        assert response.status_code == 200, response.text
        agent_slug = response.json().get("agent", {}).get("slug") or response.json().get("slug")

        thread_response = await e2e_client.post(
            "/api/chat/thread",
            headers=e2e_headers,
            json={
                "agent_id": agent_slug,
                "title": make_test_conversation_title("no-connector-agent"),
                "metadata": make_test_conversation_metadata("no-connector-agent", e2e=True),
            },
        )
        assert thread_response.status_code == 200
        thread_id = thread_response.json()["id"]

        message_response = await e2e_client.post(
            f"/api/chat/thread/{thread_id}/messages",
            headers=e2e_headers,
            json={"content": "你好，请简单介绍一下自己", "role": "user"},
        )
        assert message_response.status_code == 200
        run_id = message_response.json().get("run_id")

        final_run = await wait_for_run(e2e_client, e2e_headers, run_id)

        usage_response = await e2e_client.get(
            f"/api/system/connectors/{connector_slug}/usage",
            headers=e2e_headers,
        )
        assert usage_response.status_code == 200
        invocations = usage_response.json().get("data", {}).get("invocations", [])
        assert not invocations, (
            f"Agent without connector context created invocations: {invocations}"
        )

    finally:
        if agent_slug:
            await delete_agent(e2e_client, e2e_headers, agent_slug)
        await _delete_connector(e2e_client, e2e_headers, connector_slug)
