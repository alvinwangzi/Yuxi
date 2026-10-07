"""连接器 × 工作流 E2E：验证 connector step 从定义到执行结果的全链路。

不依赖外部 SaaS 账号；使用 CONNECTOR_E2E_TARGET_URL 环境变量指定的 HTTP 目标
（默认指向 Docker Compose 内的 api 容器 health endpoint）。
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import pytest

from e2e_helpers import E2E_TIMEOUT, postgres_dsn

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow, pytest.mark.timeout(300)]

TARGET_URL = os.getenv("CONNECTOR_E2E_TARGET_URL", "http://api:5050/api/system/health")
CONNECTOR_SLUG_PREFIX = "e2e-wf-conn-"


async def _create_connector(client: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    slug = f"{CONNECTOR_SLUG_PREFIX}{uuid.uuid4().hex[:8]}"
    body = {
        "slug": slug,
        "name": f"E2E workflow connector {uuid.uuid4().hex[:6]}",
        "connector_type": "generic_rest",
        "description": "E2E workflow connector test",
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
    return response.json()


async def _delete_connector(client: httpx.AsyncClient, headers: dict[str, str], slug: str) -> None:
    response = await client.delete(f"/api/system/connectors/{slug}", headers=headers)
    assert response.status_code in {200, 404}, response.text


async def _create_workflow(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    connector_slug: str,
) -> int:
    definition = {
        "nodes": [
            {
                "id": "step-connector",
                "type": "connector",
                "data": {
                    "connector_slug": connector_slug,
                    "operation_slug": "health-check",
                    "params": {},
                    "output_key": "health_result",
                },
            },
        ],
        "edges": [],
    }
    response = await client.post(
        "/api/workflows",
        json={
            "name": f"E2E Connector Workflow {uuid.uuid4().hex[:6]}",
            "definition": definition,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


async def _delete_workflow(client: httpx.AsyncClient, headers: dict[str, str], workflow_id: int) -> None:
    response = await client.delete(f"/api/workflows/{workflow_id}", headers=headers)
    assert response.status_code in {200, 404}, response.text


async def _wait_for_workflow_run(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    run_id: int,
    timeout: int = 120,
) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    last_payload: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/workflows/runs/{run_id}", headers=headers)
        assert response.status_code == 200, response.text
        last_payload = response.json().get("data") or {}
        status = last_payload.get("status", "")
        if status in {"completed", "failed", "cancelled"}:
            return last_payload
        await asyncio.sleep(2)
    pytest.fail(f"Workflow run {run_id} timed out: {json.dumps(last_payload or {}, ensure_ascii=False)}")


@pytest.mark.e2e_smoke
async def test_workflow_connector_read_step_produces_invocation_and_output(
    e2e_client: httpx.AsyncClient,
    e2e_headers: dict[str, str],
):
    """工作流 connector 读步骤：创建→运行→完成→step_runs 含 invocation_id 和结果。"""
    connector = await _create_connector(e2e_client, e2e_headers)
    connector_slug = connector["data"]["slug"]
    workflow_id = None
    try:
        workflow_id = await _create_workflow(e2e_client, e2e_headers, connector_slug)

        run_response = await e2e_client.post(
            f"/api/workflows/{workflow_id}/run",
            json={"input_variables": {}},
            headers=e2e_headers,
        )
        assert run_response.status_code == 200, run_response.text
        run_data = run_response.json()["data"]
        run_id = run_data["id"]

        final = await _wait_for_workflow_run(e2e_client, e2e_headers, run_id)

        assert final["status"] == "completed", (
            f"Workflow run failed: {final.get('error_message', 'unknown')}"
        )

        step_runs = final.get("step_runs", [])
        connector_steps = [s for s in step_runs if s.get("step_type") == "connector"]
        assert len(connector_steps) >= 1, f"No connector step runs found in: {step_runs}"

        step_output = connector_steps[0].get("output") or {}
        if isinstance(step_output, str):
            step_output = json.loads(step_output)
        assert step_output.get("invocation_id"), "Connector step output missing invocation_id"
        assert step_output.get("success") is True, f"Connector step not successful: {step_output}"

    finally:
        if workflow_id:
            await _delete_workflow(e2e_client, e2e_headers, workflow_id)
        await _delete_connector(e2e_client, e2e_headers, connector_slug)


@pytest.mark.e2e_smoke
async def test_workflow_connector_step_binds_to_run_and_records_invocation(
    e2e_client: httpx.AsyncClient,
    e2e_headers: dict[str, str],
):
    """工作流 connector 步骤的 invocation 绑定到 workflow run，可通过管理 API 回读。"""
    connector = await _create_connector(e2e_client, e2e_headers)
    connector_slug = connector["data"]["slug"]
    workflow_id = None
    try:
        workflow_id = await _create_workflow(e2e_client, e2e_headers, connector_slug)

        run_response = await e2e_client.post(
            f"/api/workflows/{workflow_id}/run",
            json={"input_variables": {}},
            headers=e2e_headers,
        )
        assert run_response.status_code == 200, run_response.text
        run_id = run_response.json()["data"]["id"]

        final = await _wait_for_workflow_run(e2e_client, e2e_headers, run_id)
        assert final["status"] == "completed", final.get("error_message")

        step_runs = final.get("step_runs", [])
        connector_steps = [s for s in step_runs if s.get("step_type") == "connector"]
        assert connector_steps, "No connector step run found"

        step_output = connector_steps[0].get("output") or {}
        if isinstance(step_output, str):
            step_output = json.loads(step_output)
        invocation_id = step_output.get("invocation_id")
        assert invocation_id, "Missing invocation_id in step output"

        usage_response = await e2e_client.get(
            f"/api/system/connectors/{connector_slug}/usage",
            headers=e2e_headers,
        )
        assert usage_response.status_code == 200, usage_response.text
        invocations = usage_response.json().get("data", {}).get("invocations", [])
        invocation_ids = [inv["id"] for inv in invocations]
        assert invocation_id in invocation_ids, (
            f"Invocation {invocation_id} not found in usage: {invocation_ids}"
        )

        matched = [inv for inv in invocations if inv["id"] == invocation_id][0]
        assert matched.get("consumer_type") == "workflow"
        assert matched.get("workflow_run_id") == run_id

    finally:
        if workflow_id:
            await _delete_workflow(e2e_client, e2e_headers, workflow_id)
        await _delete_connector(e2e_client, e2e_headers, connector_slug)
