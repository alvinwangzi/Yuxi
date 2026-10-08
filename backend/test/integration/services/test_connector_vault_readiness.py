"""真实密文 key_id 覆盖与 readiness 的受控解密样本。"""

import pytest
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

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_empty_disabled_connector_allows_product_ready_without_vault(service_scope):
    from yuxi.services.connectors.vault_readiness import check_connector_vault

    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        (await ConnectorRepository(db).get_by_slug("service-test")).enabled = False
    status = await check_connector_vault(session_factory=manager.get_async_session_context, vault=None)
    assert status == {"status": "unavailable", "required": False, "code": "vault_unconfigured"}


async def test_required_vault_checks_key_coverage_and_actual_decryption(service_scope, vault):
    from yuxi.services.connectors.vault_readiness import check_connector_vault

    _, manager = service_scope
    status = await check_connector_vault(session_factory=manager.get_async_session_context, vault=None)
    assert status["required"] and status["status"] == "error"
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        await repo.upsert_credential(connector.id, "token", b"broken-ciphertext", "unknown-key")
    status = await check_connector_vault(session_factory=manager.get_async_session_context, vault=vault)
    assert status["status"] == "error" and status["code"] == "vault_key_missing"
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        await repo.upsert_credential(connector.id, "token", b"broken-ciphertext", vault.current_key_id)
    status = await check_connector_vault(session_factory=manager.get_async_session_context, vault=vault)
    assert status["status"] == "error" and status["code"] == "vault_decryption_failed"
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        encrypted = vault.encrypt(b"controlled-fixture")
        await repo.upsert_credential(connector.id, "token", encrypted.ciphertext, encrypted.key_id)
    assert await check_connector_vault(session_factory=manager.get_async_session_context, vault=vault) == {
        "status": "ok",
        "required": True,
    }
