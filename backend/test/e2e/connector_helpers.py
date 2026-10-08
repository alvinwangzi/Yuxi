"""连接器完整链路使用的真实 HTTP fixture 与独立远端收包 oracle。"""

import asyncio
import os
import socket
import uuid

import httpx
import pytest

REPLAY_URL = os.getenv("CONNECTOR_E2E_REPLAY_URL", "http://api:8765")


@pytest.fixture
async def connector_case(e2e_client, e2e_headers):
    """只创建本例所属记录和连接器，保留真实远端读写收包。"""
    token = uuid.uuid4().hex
    slug = f"e2e-conn-{token[:8]}"
    async with httpx.AsyncClient(base_url=REPLAY_URL, timeout=10) as provider:
        response = await provider.post("/connector/fixtures", json={"record_id": token, "value": "original"})
        assert response.status_code == 200, response.text
        config = {
            "base_url": REPLAY_URL,
            "allowed_origins": [REPLAY_URL],
            "allowed_private_cidrs": [socket.gethostbyname("api") + "/32"],
            "auth_type": "none",
        }
        operations = [
            {
                "slug": "read",
                "name": "Read fixture",
                "operation_type": "read",
                "http_method": "GET",
                "endpoint_template": "/connector/records/{{record_id}}",
                "approval_policy": "preauthorized",
                "request_schema": {
                    "type": "object",
                    "properties": {"record_id": {"type": "string"}},
                    "required": ["record_id"],
                    "additionalProperties": False,
                },
            },
            {
                "slug": "write",
                "name": "Write fixture",
                "operation_type": "write",
                "http_method": "POST",
                "endpoint_template": "/connector/records/{{record_id}}",
                "approval_policy": "required",
                "body_template": {"value": "{{value}}"},
                "request_schema": {
                    "type": "object",
                    "properties": {
                        "record_id": {"type": "string", "x-approval-visible": True, "x-approval-target": True},
                        "value": {"type": "string", "x-approval-visible": True},
                    },
                    "required": ["record_id", "value"],
                    "additionalProperties": False,
                },
            },
        ]
        response = await e2e_client.post(
            "/api/system/connectors",
            headers=e2e_headers,
            json={
                "slug": slug,
                "name": "E2E connector",
                "connector_type": "generic_rest",
                "config": config,
                "read_scope": {"access_level": "global"},
                "write_scope": {"access_level": "global"},
                "operations": operations,
            },
        )
        assert response.status_code == 200, response.text
        try:
            yield {"slug": slug, "record_id": token, "provider": provider}
        finally:
            response = await e2e_client.delete(f"/api/system/connectors/{slug}", headers=e2e_headers)
            assert response.status_code in (200, 404), response.text
            response = await provider.delete(f"/connector/fixtures/{token}")
            assert response.status_code == 200, response.text


async def read_provider_ledger(case):
    """回读独立服务收到的实际请求和远端最终记录。"""
    response = await case["provider"].get(f"/connector/ledger/{case['record_id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def wait_for_workflow(client, headers, run_id, *, statuses=("completed", "failed", "cancelled"), timeout=120):
    """等待指定持久状态，并对失败提供当前完整运行证据。"""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/workflows/runs/{run_id}", headers=headers)
        assert response.status_code == 200, response.text
        run = response.json()["data"]
        if run["status"] in statuses:
            return run
        await asyncio.sleep(0.25)
    pytest.fail(f"workflow timeout: {run}")


async def create_connector_agent(client, headers, case, operation):
    """经 shipping API 创建确定性 provider 与拥有连接器工具的真实 Agent。"""
    uid = (await client.get("/api/auth/me", headers=headers)).json()["uid"]
    provider_id = f"conn-replay-{uuid.uuid4().hex[:8]}"
    response = await client.post(
        "/api/system/model-providers",
        headers=headers,
        json={
            "provider_id": provider_id,
            "display_name": "Connector deterministic replay",
            "provider_type": "openai",
            "base_url": REPLAY_URL + "/v1",
            "api_key": "ci-replay-key",
            "capabilities": ["chat"],
            "enabled_models": [
                {"id": "deterministic-chat", "display_name": "Deterministic chat", "type": "chat", "source": "manual"}
            ],
            "is_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    slug = f"e2e-agent-{uuid.uuid4().hex[:8]}"
    tool = f"cn_{case['slug']}__{operation}"
    value = "repaired" if operation == "write" else "original"
    response = await client.post(
        "/api/agent",
        headers=headers,
        json={
            "name": "E2E connector Agent",
            "slug": slug,
            "backend_id": "ChatbotAgent",
            "is_subagent": False,
            "config_json": {
                "context": {
                    "model": provider_id + ":deterministic-chat",
                    "connectors": [case["slug"]],
                    "system_prompt": (
                        f"DETERMINISTIC_CONNECTOR_TOOL:{tool} "
                        f"CONNECTOR_RECORD:{case['record_id']} CONNECTOR_VALUE:{value}"
                    ),
                    "tools": [],
                    "knowledges": [],
                    "mcps": [],
                    "skills": ["image-gen"],
                    "preload_skills": ["image-gen"],
                    "subagents": [],
                }
            },
            "share_config": {
                "version": 2,
                "read_scope": {"access_level": "user", "user_uids": [uid], "department_ids": []},
                "manage_scope": None,
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["agent"]["slug"] == slug
    return slug, provider_id
