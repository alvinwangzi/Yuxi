"""工作流 Agent 桥接在完整 Compose 的单执行槽位中运行真实工具图。"""

import json
import uuid

import asyncpg
import pytest
from connector_helpers import (
    connector_case as connector_case,
    create_connector_agent,
    read_provider_ledger,
    wait_for_workflow,
)
from e2e_helpers import postgres_dsn

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.e2e_smoke]


@pytest.mark.parametrize("operation", ["read", "write", "write_unknown"])
async def test_workflow_agent_bridge_releases_worker_and_waits_for_real_agent_output(
    e2e_client,
    e2e_headers,
    connector_case,
    operation,
):
    """Agent 节点必须产生 Request/Run/ToolMessage，批准不能当父节点完成。"""
    case = connector_case
    is_write = operation.startswith("write")
    if operation == "write_unknown":
        configured = (await e2e_client.get(f"/api/system/connectors/{case['slug']}", headers=e2e_headers)).json()[
            "data"
        ]
        patched = await e2e_client.patch(
            f"/api/system/connectors/{case['slug']}",
            headers=e2e_headers,
            json={
                "expected_revision": configured["revision"],
                "config": {**configured["config"], "timeout_seconds": 1},
            },
        )
        assert patched.status_code == 200
        write = next(row for row in configured["operations"] if row["slug"] == "write")
        patched = await e2e_client.patch(
            f"/api/system/connectors/{case['slug']}/operations/write",
            headers=e2e_headers,
            json={"expected_revision": write["revision"], "approval_policy": "preauthorized"},
        )
        assert patched.status_code == 200
        seeded = await case["provider"].post(
            "/connector/fixtures",
            json={"record_id": case["record_id"], "value": "original", "response_delay_seconds": 2},
        )
        assert seeded.status_code == 200
    agent, provider_id = await create_connector_agent(e2e_client, e2e_headers, case, "write" if is_write else "read")
    response = await e2e_client.post(
        "/api/workflows",
        headers=e2e_headers,
        json={
            "name": "E2E real workflow Agent",
            "slug": f"e2e-agent-wf-{uuid.uuid4().hex[:8]}",
            "definition": {
                "steps": [
                    {
                        "id": "agent",
                        "type": "llm",
                        "agent_slug": agent,
                        "prompt": "DETERMINISTIC_AGENT_E2E_OK",
                        "output_key": "agent_reply",
                    },
                    {"id": "end", "type": "end", "depends_on": ["agent"], "template": "{agent_reply}"},
                ]
            },
        },
    )
    assert response.status_code == 200, response.text
    workflow_id = response.json()["data"]["id"]
    run_id = None
    try:
        response = await e2e_client.post(
            f"/api/workflows/{workflow_id}/run",
            headers=e2e_headers,
            json={"input_variables": {"__actor_uid__": "forged", "__workflow_run_id__": -1}},
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["data"]["id"]
        if is_write:
            waiting = await wait_for_workflow(
                e2e_client, e2e_headers, run_id, statuses=("waiting_approval", "completed", "failed")
            )
            assert waiting["status"] == "waiting_approval" and waiting["owner_attempt"] is None, waiting
            assert {s["step_id"]: s["status"] for s in waiting["step_runs"]} == {
                "agent": "waiting_approval",
                "end": "pending",
            }
            ledger = await read_provider_ledger(case)
            assert ledger["requests"] == (["POST"] if operation == "write_unknown" else [])
            pending = waiting["resume_state"]["pending"]["agent"]
            assert len(pending["invocation_ids"]) == 1
            invocation_id = pending["invocation_ids"][0]
            response = await e2e_client.get(f"/api/connectors/invocations/{invocation_id}", headers=e2e_headers)
            assert response.status_code == 200, response.text
            if operation == "write_unknown":
                assert response.json()["data"]["status"] == "unknown"
                assert ledger["record"]["value"] == "repaired"
                response = await e2e_client.post(
                    f"/api/system/connectors/invocations/{invocation_id}/reconcile",
                    headers=e2e_headers,
                    json={
                        "resolution": "succeeded",
                        "reason": "独立 provider ledger 回读同一记录，POST 一次",
                        "result": {"record": ledger["record"]},
                    },
                )
            else:
                response = await e2e_client.post(
                    f"/api/connectors/invocations/{invocation_id}/decision",
                    headers=e2e_headers,
                    json={"decision": "approve", "expected_digest": response.json()["data"]["request_digest"]},
                )
            assert response.status_code == 200, response.text
        final = await wait_for_workflow(e2e_client, e2e_headers, run_id)
        assert final["status"] == "completed", final
        assert final["context"]["agent_reply"] == "DETERMINISTIC_AGENT_E2E_OK"
        step = next(s for s in final["step_runs"] if s["step_id"] == "agent")
        assert step["output_payload"] == "DETERMINISTIC_AGENT_E2E_OK"
        assert step["execution_count"] == 1 and step["agent_request_id"] and step["agent_run_id"]
        binding = step["input_payload"]["agent_binding"]
        assert binding["origin_request_id"] == step["agent_request_id"]
        assert binding["active_run_id"] == step["agent_run_id"]
        if is_write:
            assert binding["active_request_id"] != binding["origin_request_id"]
        response = await e2e_client.get(f"/api/system/connectors/{case['slug']}/usage", headers=e2e_headers)
        assert response.status_code == 200, response.text
        invocations = response.json()["data"]
        assert len(invocations) == 1 and invocations[0]["status"] == "succeeded", invocations
        invocation = invocations[0]
        assert invocation["workflow_run_id"] == run_id and invocation["step_execution_id"] == step["step_execution_id"]
        assert invocation["agent_request_id"] == step["agent_request_id"]
        assert invocation["agent_run_id"] == binding["origin_run_id"]
        connection = await asyncpg.connect(postgres_dsn())
        try:
            child = await connection.fetchrow(
                "SELECT status, uid, request_id, output_message_id FROM agent_runs WHERE id=$1", step["agent_run_id"]
            )
            assert child["status"] == "completed" and child["uid"] == final["created_by"]
            output = await connection.fetchrow(
                "SELECT run_id, content FROM messages WHERE id=$1", child["output_message_id"]
            )
            assert output["run_id"] == step["agent_run_id"] and output["content"] == "DETERMINISTIC_AGENT_E2E_OK"
            audit = await connection.fetchval(
                "SELECT content FROM messages WHERE run_id=$1 AND message_type='tool_audit' "
                "AND operation_id='call-connector'",
                step["agent_run_id"],
            )
            assert json.loads(audit)["invocation_id"] == invocation["invocation_id"]
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM agent_run_requests WHERE request_id=$1", step["agent_request_id"]
                )
                == 1
            )
        finally:
            await connection.close()
        ledger = await read_provider_ledger(case)
        assert ledger["requests"] == ["POST" if is_write else "GET"]
        assert ledger["record"]["value"] == ("repaired" if is_write else "original")
    finally:
        if run_id:
            response = await e2e_client.get(f"/api/workflows/runs/{run_id}", headers=e2e_headers)
            if response.status_code == 200:
                if response.json()["data"]["status"] not in ("completed", "failed", "cancelled"):
                    cancelled = await e2e_client.post(f"/api/workflows/runs/{run_id}/cancel", headers=e2e_headers)
                    assert cancelled.status_code == 200, cancelled.text
                for step in response.json()["data"]["step_runs"]:
                    if step.get("agent_thread_id"):
                        deleted = await e2e_client.delete(
                            f"/api/chat/thread/{step['agent_thread_id']}", headers=e2e_headers
                        )
                        assert deleted.status_code in (200, 404), deleted.text
        response = await e2e_client.delete(f"/api/workflows/{workflow_id}", headers=e2e_headers)
        assert response.status_code in (200, 404), response.text
        response = await e2e_client.delete(f"/api/agent/{agent}", headers=e2e_headers)
        assert response.status_code in (200, 404), response.text
        response = await e2e_client.delete(f"/api/system/model-providers/{provider_id}", headers=e2e_headers)
        assert response.status_code in (200, 404), response.text
