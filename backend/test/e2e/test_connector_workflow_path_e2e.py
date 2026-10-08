"""真实 API、单槽 worker、PG 和独立 provider 的连接器工作流链路。"""

import os
import uuid
import asyncpg
import pytest
from connector_helpers import (
    connector_case as connector_case, read_provider_ledger, wait_for_workflow,
)
from e2e_helpers import postgres_dsn
from yuxi.storage.redis import create_arq_redis_pool, RedisConfig

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.e2e_smoke]


@pytest.mark.parametrize("operation", ["read", "write"])
async def test_workflow_connector_read_or_approved_write_is_bound_and_never_replayed(
    e2e_client, e2e_headers, connector_case, operation,
):
    """真暂停、批准、结果与重复 ARQ job 都回读数据库和远端收包。"""
    case = connector_case
    params = {"record_id": case["record_id"]}
    if operation == "write":
        params["value"] = "repaired"
    definition = {"steps": [
        {"id": "connector", "type": "connector", "connector_slug": case["slug"],
         "operation_slug": operation, "params": params, "output_key": "record"},
        {"id": "end", "type": "end", "depends_on": ["connector"], "template": "{record}"},
    ]}
    response = await e2e_client.post("/api/workflows", headers=e2e_headers,
        json={"name": "E2E connector workflow", "slug": f"e2e-workflow-{uuid.uuid4().hex[:8]}", "definition": definition})
    assert response.status_code == 200, response.text
    workflow_id = response.json()["data"]["id"]
    try:
        response = await e2e_client.post(f"/api/workflows/{workflow_id}/run", headers=e2e_headers, json={"input_variables": {}})
        assert response.status_code == 200, response.text
        run_id = response.json()["data"]["id"]
        if operation == "write":
            waiting = await wait_for_workflow(e2e_client, e2e_headers, run_id,
                statuses=("waiting_approval", "failed", "completed"))
            assert waiting["status"] == "waiting_approval", waiting
            assert (await read_provider_ledger(case))["requests"] == []
            assert {s["step_id"]: s["status"] for s in waiting["step_runs"]} == {"connector": "waiting_approval", "end": "pending"}
            invocation_id = waiting["step_runs"][0]["pending_connector_invocation_id"]
            response = await e2e_client.get(f"/api/connectors/invocations/{invocation_id}", headers=e2e_headers)
            assert response.status_code == 200, response.text
            digest = response.json()["data"]["request_digest"]
            response = await e2e_client.post(f"/api/connectors/invocations/{invocation_id}/decision", headers=e2e_headers,
                json={"decision": "approve", "expected_digest": digest})
            assert response.status_code == 200, response.text
        final = await wait_for_workflow(e2e_client, e2e_headers, run_id)
        assert final["status"] == "completed", final
        step = next(s for s in final["step_runs"] if s["step_id"] == "connector")
        expected_value = "repaired" if operation == "write" else "original"
        assert step["output_payload"]["result"]["record"] == {"id": case["record_id"], "value": expected_value}
        invocation_id = step["output_payload"]["invocation_id"]
        response = await e2e_client.get(f"/api/system/connectors/{case['slug']}/usage", headers=e2e_headers)
        assert response.status_code == 200, response.text
        invocations = response.json()["data"]
        assert len(invocations) == 1
        invocation = invocations[0]
        assert invocation["invocation_id"] == invocation_id
        assert invocation["consumer_type"] == "workflow" and invocation["workflow_run_id"] == run_id
        assert invocation["step_execution_id"] == step["step_execution_id"] and invocation["status"] == "succeeded"
        queue = await create_arq_redis_pool(RedisConfig(url=os.environ["REDIS_URL"]))
        try:
            job = await queue.enqueue_job("process_workflow_run", run_id, 0, _job_id=f"duplicate-workflow:{uuid.uuid4()}")
            await job.result(timeout=20)
        finally:
            await queue.aclose()
        ledger = await read_provider_ledger(case)
        assert ledger["requests"] == ["POST" if operation == "write" else "GET"]
        assert ledger["record"]["value"] == expected_value
        connection = await asyncpg.connect(postgres_dsn())
        try:
            assert await connection.fetchval("SELECT count(*) FROM connector_operation_attempts WHERE invocation_id=$1", invocation_id) == 1
            assert await connection.fetchval("SELECT execution_count FROM workflow_step_runs WHERE workflow_run_id=$1 AND step_id='connector'", run_id) == 1
        finally:
            await connection.close()
    finally:
        response = await e2e_client.delete(f"/api/workflows/{workflow_id}", headers=e2e_headers)
        assert response.status_code in (200, 404), response.text
