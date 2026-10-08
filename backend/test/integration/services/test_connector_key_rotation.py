"""真实 PG 轮换所有保留列，拒绝半行 key_id 变更。"""

import uuid
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from test.integration.services.test_connector_service import (
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    ensure_live_api_schema as ensure_live_api_schema,
    fernet_key as fernet_key,
    service_scope as service_scope,
    vault as vault,
    vault_configuration as vault_configuration,
)
from yuxi.repositories.connector_repository import ConnectorRepository
from yuxi.services.connectors.credential_vault import CredentialVault, CredentialVaultError
from yuxi.storage.postgres.models_business import ConnectorCredential, ConnectorUsageLog

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_rotation_covers_all_batches_and_terminal_payloads_without_skipping(service_scope, vault, fernet_key):
    from yuxi.services.connectors.key_rotation import rotate_retained_materials

    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        for index in range(5):
            value = vault.encrypt(f"credential-{index}".encode())
            await repo.upsert_credential(connector.id, f"fixture-{index}", value.ciphertext, value.key_id)
            payload = vault.encrypt(f"payload-{index}".encode())
            db.add(
                ConnectorUsageLog(
                    id=str(uuid.uuid4()),
                    connector_id=connector.id,
                    connector_slug=connector.slug,
                    operation_slug="read",
                    operation_type="read",
                    actor_uid="actor",
                    consumer_type="admin_test",
                    logical_call_key=f"rotation-{index}",
                    connector_revision=1,
                    operation_revision=1,
                    status="succeeded" if index % 2 else "unknown",
                    key_id=payload.key_id,
                    params_ciphertext=payload.ciphertext,
                    execution_snapshot_ciphertext=payload.ciphertext,
                    result_ciphertext=payload.ciphertext,
                )
            )
    new_key = Fernet(Fernet.generate_key())
    current = CredentialVault(current_key=new_key, current_key_id="rotated", old_keys={"test-only": fernet_key})
    preview = await rotate_retained_materials(
        session_factory=manager.get_async_session_context, vault=current, dry_run=True, batch_size=2
    )
    assert preview == {"credentials": 5, "invocations": 5}
    async with manager.get_async_session_context() as db:
        assert set(await db.scalars(select(ConnectorCredential.key_id))) == {"test-only"}
    actual = await rotate_retained_materials(
        session_factory=manager.get_async_session_context, vault=current, dry_run=False, batch_size=2
    )
    assert actual == preview
    async with manager.get_async_session_context() as db:
        rows = list(await db.scalars(select(ConnectorUsageLog)))
        assert len(rows) == 5
        for row in rows:
            assert row.key_id == "rotated"
            assert (
                len(
                    {
                        new_key.decrypt(value)
                        for value in [row.params_ciphertext, row.execution_snapshot_ciphertext, row.result_ciphertext]
                    }
                )
                == 1
            )
    assert await rotate_retained_materials(
        session_factory=manager.get_async_session_context, vault=current, dry_run=False, batch_size=2
    ) == {"credentials": 0, "invocations": 0}


async def test_corrupt_payload_rolls_back_whole_row_and_never_changes_its_key_id(service_scope, vault, fernet_key):
    from yuxi.services.connectors.key_rotation import rotate_retained_materials

    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        value = vault.encrypt(b"params-original")
        row = ConnectorUsageLog(
            id=str(uuid.uuid4()),
            connector_id=connector.id,
            connector_slug=connector.slug,
            operation_slug="read",
            operation_type="read",
            actor_uid="actor",
            consumer_type="admin_test",
            logical_call_key="corrupt-rotation",
            connector_revision=1,
            operation_revision=1,
            status="unknown",
            key_id=value.key_id,
            params_ciphertext=value.ciphertext,
            execution_snapshot_ciphertext=b"broken",
        )
        db.add(row)
        row_id = row.id
    current = CredentialVault(
        current_key=Fernet(Fernet.generate_key()), current_key_id="new", old_keys={"test-only": fernet_key}
    )
    with pytest.raises(CredentialVaultError):
        await rotate_retained_materials(
            session_factory=manager.get_async_session_context, vault=current, dry_run=False, batch_size=1
        )
    async with manager.get_async_session_context() as db:
        row = await db.get(ConnectorUsageLog, row_id)
        assert row.key_id == "test-only" and fernet_key.decrypt(row.params_ciphertext) == b"params-original"
