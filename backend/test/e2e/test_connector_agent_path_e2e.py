"""真实 Agent 工具图必须产生精确绑定的 invocation 和 ToolMessage。"""

import asyncio
import json
import uuid
import asyncpg
import pytest
from connector_helpers import connector_case as connector_case, create_connector_agent, read_provider_ledger
from e2e_helpers import postgres_dsn, wait_for_run, consume_events
from test.live_api_cleanup import make_test_conversation_metadata, make_test_conversation_title

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.e2e_smoke]


@pytest.mark.parametrize("operation", ["read", "write"])
async def test_agent_connector_tool_creates_exact_run_bound_invocation_and_tool_message(
    e2e_client, e2e_headers, connector_case, operation,
):
    """模型不会调用工具、Run 失败或错误绑定时必须失败，禁止 vacuous pass。"""
    case = connector_case
    agent, provider_id = await create_connector_agent(e2e_client, e2e_headers, case, operation)
    thread_id = None
    try:
        response = await e2e_client.post("/api/chat/thread", headers=e2e_headers, json={"agent_id": agent,
            "title": make_test_conversation_title("connector-real-agent"),
            "metadata": make_test_conversation_metadata("connector-real-agent", e2e=True)})
        assert response.status_code == 200, response.text
        thread_id = response.json()["id"]
        request_id = str(uuid.uuid4())
        response = await e2e_client.post("/api/agent/runs", headers=e2e_headers, json={
            "agent_slug": agent, "thread_id": thread_id, "query": "DETERMINISTIC_AGENT_E2E_OK",
            "tool_approval_mode": "always_trust", "meta": {"request_id": request_id}})
        assert response.status_code == 200, response.text
        origin_run_id = response.json()["run_id"]
        final = await wait_for_run(e2e_client, e2e_headers, origin_run_id)
        response = await e2e_client.get(f"/api/system/connectors/{case['slug']}/usage", headers=e2e_headers)
        assert response.status_code == 200, response.text
        invocations = response.json()["data"]
        assert len(invocations) == 1, (final, invocations)
        invocation = invocations[0]
        assert invocation["agent_run_id"] == origin_run_id
        assert invocation["agent_request_id"] == request_id and invocation["tool_call_id"] == "call-connector"
        current_run_id = origin_run_id
        if operation == "write":
            assert final["status"] == "interrupted" and final["error_type"] == "connector_approval_required", final
            assert invocation["status"] == "awaiting_approval"
            assert (await read_provider_ledger(case))["requests"] == []
            response = await e2e_client.post(f"/api/connectors/invocations/{invocation['invocation_id']}/decision",
                headers=e2e_headers, json={"decision": "approve", "expected_digest": invocation["request_digest"]})
            assert response.status_code == 200, response.text
            connection = await asyncpg.connect(postgres_dsn())
            try:
                for _ in range(100):
                    if not await connection.fetchval("SELECT runtime_cleanup_pending FROM agent_runs WHERE id=$1", origin_run_id):
                        break
                    await asyncio.sleep(0.1)
            finally:
                await connection.close()
            response = await e2e_client.post("/api/agent/runs", headers=e2e_headers, json={
                "agent_slug": agent, "thread_id": thread_id, "created_by_run_id": origin_run_id,
                "resume": {"invocation_id": invocation["invocation_id"]}})
            assert response.status_code == 200, response.text
            current_run_id = response.json()["run_id"]
            final = await wait_for_run(e2e_client, e2e_headers, current_run_id)
        assert final["status"] == "completed", final
        response = await e2e_client.get(f"/api/agent/runs/{current_run_id}/result", headers=e2e_headers)
        assert response.status_code == 200 and response.json()["output"] == "DETERMINISTIC_AGENT_E2E_OK", response.text
        events = await consume_events(e2e_client, e2e_headers, current_run_id)
        assert events.get("end", 0) >= 1
        ledger = await read_provider_ledger(case)
        assert ledger["requests"] == ["POST" if operation == "write" else "GET"]
        assert ledger["record"]["value"] == ("repaired" if operation == "write" else "original")
        connection = await asyncpg.connect(postgres_dsn())
        try:
            message = await connection.fetchrow("SELECT content, request_id, execution_status FROM messages "
                "WHERE run_id=$1 AND message_type='tool_audit' AND operation_id='call-connector'", current_run_id)
            assert message and message["execution_status"] == "completed", message
            result = json.loads(message["content"])
            assert result["invocation_id"] == invocation["invocation_id"]
            assert result["result"]["record"]["id"] == case["record_id"]
            assert await connection.fetchval("SELECT count(*) FROM connector_operation_attempts WHERE invocation_id=$1",
                invocation["invocation_id"]) == 1
        finally:
            await connection.close()
    finally:
        if thread_id:
            response = await e2e_client.delete(f"/api/chat/thread/{thread_id}", headers=e2e_headers)
            assert response.status_code in (200, 404), response.text
        response = await e2e_client.delete(f"/api/agent/{agent}", headers=e2e_headers)
        assert response.status_code in (200, 404), response.text
        response = await e2e_client.delete(f"/api/system/model-providers/{provider_id}", headers=e2e_headers)
        assert response.status_code in (200, 404), response.text
