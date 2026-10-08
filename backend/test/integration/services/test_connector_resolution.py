"""调用取消与人工核对的授权、审计、不可重放契约。"""

import json
import uuid
import pytest
from sqlalchemy import text
from test.integration.services.test_connector_service import (
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    ensure_live_api_schema as ensure_live_api_schema,
    fernet_key as fernet_key,
    service_scope as service_scope,
    vault as vault,
    vault_configuration as vault_configuration,
    execution,
)
from yuxi.repositories.connector_repository import ConnectorRepository
from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
from yuxi.services.connectors.service import ConnectorServiceError, ConnectorAuthorizationError
from yuxi.storage.postgres.models_business import ConnectorUsageLog, User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture
async def unknown_invocation(service_scope, vault):
    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.write_scope = {"access_level": "global"}
        operation = await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="Write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/write",
        )
        encrypted = vault.encrypt(
            b'{"result_version":1,"success":false,"data":null,"provider_evidence":{"receipt":"retained"}}'
        )
        row = ConnectorUsageLog(
            id=str(uuid.uuid4()),
            connector_id=connector.id,
            operation_id=operation.id,
            connector_slug=connector.slug,
            operation_slug=operation.slug,
            operation_type="write",
            actor_uid="actor",
            consumer_type="admin_test",
            logical_call_key="resolution-fixture",
            connector_revision=connector.revision,
            operation_revision=operation.revision,
            owner_attempt="old-owner",
            status="unknown",
            result_ciphertext=encrypted.ciphertext,
            key_id=encrypted.key_id,
        )
        db.add(row)
        db.add(User(uid="ordinary", username="ordinary", password_hash="not-a-login", role="user"))
    return row.id


async def test_resolution_requires_current_admin_scope_and_nonempty_evidence(service_scope, unknown_invocation):
    service, manager = service_scope
    with pytest.raises(ConnectorAuthorizationError):
        await service.reconcile_invocation(
            unknown_invocation, "succeeded", actor="ordinary", reason="readback", result={"id": "record"}
        )
    with pytest.raises(ConnectorServiceError):
        await service.reconcile_invocation(
            unknown_invocation, "succeeded", actor="actor", reason="", result={"id": "record"}
        )
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.write_scope = {"access_level": "deny"}
    with pytest.raises(ConnectorAuthorizationError):
        await service.reconcile_invocation(
            unknown_invocation, "succeeded", actor="actor", reason="readback", result={"id": "record"}
        )


async def test_resolution_preserves_private_evidence_and_binds_supplied_readback_result(
    service_scope, unknown_invocation, fernet_key
):
    service, manager = service_scope
    resolved = await service.reconcile_invocation(
        unknown_invocation,
        "succeeded",
        actor="actor",
        reason="provider receipt checked",
        result={"id": "record", "value": "saved"},
    )
    assert resolved["status"] == "succeeded"
    async with manager.get_async_session_context() as db:
        row = await ConnectorExecutionRepository(db).get_invocation(unknown_invocation)
        payload = json.loads(fernet_key.decrypt(row.result_ciphertext))
        assert payload["provider_evidence"] == {"receipt": "retained"}
        assert payload["data"] == {"id": "record", "value": "saved"} and payload["success"]
        assert payload["resolution"]["actor_uid"] == "actor"
        assert payload["resolution"]["reason"] == "provider receipt checked"
        assert "provider receipt" not in (row.error_summary or "")
    with pytest.raises(ConnectorServiceError):
        await service.reconcile_invocation(unknown_invocation, "failed", actor="actor", reason="opposite decision")


async def test_cancel_rejects_cross_actor_and_never_turns_unknown_into_cancelled(service_scope, unknown_invocation):
    service, manager = service_scope
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution("cancel-fixture"))
    with pytest.raises(ConnectorAuthorizationError):
        await service.cancel_invocation(prepared["invocation_id"], actor="ordinary")
    cancelled = await service.cancel_invocation(prepared["invocation_id"], actor="actor")
    assert cancelled["status"] == "cancelled"
    with pytest.raises(ConnectorServiceError):
        await service.cancel_invocation(unknown_invocation, actor="actor")
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM connector_operation_attempts")) == 0
