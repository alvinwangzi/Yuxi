"""管理写测试的真实 HTTP 幂等与审批恢复不产生额外远端副作用。"""

import uuid
import pytest
from connector_helpers import connector_case as connector_case, read_provider_ledger

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.e2e_smoke]


@pytest.mark.parametrize("policy", ["preauthorized", "required"])
async def test_management_write_probe_reuses_client_key_and_required_decision(
    e2e_client, e2e_headers, connector_case, policy
):
    """同键响应丢失重试复用调用，required 先批准再同键恢复，POST恰好一次。"""
    case = connector_case
    root = "/api/system/connectors/" + case["slug"] + "/operations/write"
    operations = (
        await e2e_client.get("/api/system/connectors/" + case["slug"] + "/operations", headers=e2e_headers)
    ).json()["data"]
    operation = next(row for row in operations if row["slug"] == "write")
    changed = await e2e_client.patch(
        root, headers=e2e_headers, json={"expected_revision": operation["revision"], "approval_policy": policy}
    )
    assert changed.status_code == 200
    headers = {**e2e_headers, "Idempotency-Key": str(uuid.uuid4())}
    params = {"record_id": case["record_id"], "value": "repaired"}
    response = await e2e_client.post(root + "/test", headers=headers, json=params)
    if policy == "required":
        assert response.status_code == 409
        pending = response.json()["detail"]
        assert pending["code"] == "approval_required" and pending["invocation_id"] and pending["request_digest"]
        assert (await read_provider_ledger(case))["requests"] == []
        approved = await e2e_client.post(
            "/api/connectors/invocations/" + pending["invocation_id"] + "/decision",
            headers=e2e_headers,
            json={"decision": "approve", "expected_digest": pending["request_digest"]},
        )
        assert approved.status_code == 200
        response = await e2e_client.post(root + "/test", headers=headers, json=params)
    assert response.status_code == 200, response.text
    first = response.json()["data"]
    repeated = await e2e_client.post(root + "/test", headers=headers, json=params)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["invocation_id"] == first["invocation_id"]
    ledger = await read_provider_ledger(case)
    assert ledger["requests"] == ["POST"] and ledger["record"]["value"] == "repaired"
    mismatch = await e2e_client.post(root + "/test", headers=headers, json={**params, "value": "different"})
    assert mismatch.status_code == 409 and (await read_provider_ledger(case))["requests"] == ["POST"]
