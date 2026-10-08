"""管理用例在真实 PG 上验证严格配置、CAS 和加密凭据边界。"""

import asyncio
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
from yuxi.services.connectors.service import ConnectorServiceError, ConnectorAuthorizationError
from sqlalchemy import text

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def connector_data(**changes):
    """固定合法配置由测试持有，坏输入不能写入数据库。"""
    return {
        "slug": "managed",
        "name": "Managed",
        "connector_type": "generic_rest",
        "enabled": False,
        "config": {"base_url": "https://example.com", "auth_type": "none"},
        "read_scope": {"access_level": "global"},
        "write_scope": {"access_level": "deny"},
        **changes,
    }


@pytest.mark.parametrize("name", ["", "x" * 129])
async def test_connector_patch_rejects_invalid_display_name_without_changing_row(service_scope, name):
    """PATCH 名称沿创建的边界校验，不依赖 PostgreSQL 长度异常或接受空值。"""
    service, manager = service_scope
    created = await service.create_connector(connector_data(), actor="actor")
    with pytest.raises(ConnectorServiceError):
        await service.update_connector(
            "managed", {"expected_revision": created["revision"], "name": name}, actor="actor"
        )
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_id(created["id"])
        assert connector.name == created["name"] and connector.revision == created["revision"]


@pytest.mark.parametrize("initial_auth,enabled", [("none", True), ("bearer", False)])
async def test_configuration_and_credentials_can_switch_auth_and_enable_atomically(
    service_scope, fernet_key, initial_auth, enabled
):
    """同次提交认证、启用与加密凭据，不能先拒绝配置而丢失凭据意图。"""
    service, manager = service_scope
    created = await service.create_connector(
        connector_data(enabled=enabled, config={"base_url": "https://example.com", "auth_type": initial_auth}),
        actor="actor",
    )
    updated = await service.update_connector(
        "managed",
        {
            "expected_revision": created["revision"],
            "enabled": True,
            "config": {"base_url": "https://example.com", "auth_type": "bearer"},
            "credential_patch": {"upsert": {"token": "synthetic-atomic-token"}, "delete_keys": []},
        },
        actor="actor",
    )
    assert updated["enabled"] and updated["revision"] == created["revision"] + 1
    assert "synthetic-atomic-token" not in str(updated)
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_id(created["id"])
        assert connector.config["auth_type"] == "bearer"
        assert fernet_key.decrypt(connector.credentials[0].credential_value) == b"synthetic-atomic-token"


@pytest.mark.parametrize(
    "changes",
    [{"upsert": {"token": "synthetic"}, "delete_keys": ["token"]}, {"upsert": False}, {"delete_keys": ["unknown"]}],
)
async def test_combined_credentials_rejects_bad_changes_and_rolls_back_configuration(service_scope, changes):
    """无效凭据意图回滚同次配置、版本和密文，不能形成半保存状态。"""
    service, manager = service_scope
    created = await service.create_connector(connector_data(), actor="actor")
    with pytest.raises(ConnectorServiceError):
        await service.update_connector(
            "managed",
            {"expected_revision": created["revision"], "name": "must-not-save", "credential_patch": changes},
            actor="actor",
        )
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_id(created["id"])
        assert connector.name == created["name"] and connector.revision == created["revision"]
        assert connector.credentials == []


async def test_operation_enabled_null_is_rejected_before_persistence(service_scope):
    """空布尔值不能靠数据库异常承担输入校验。"""
    service, manager = service_scope
    with pytest.raises(ConnectorServiceError):
        await service.update_connector_operation(
            "service-test", "read", {"expected_revision": 1, "enabled": None}, actor="actor"
        )


async def test_embedded_disabled_operation_preserves_explicit_enabled_value(service_scope):
    """创建配置里的停用操作必须落库，不能丢失值或出现参数异常。"""
    service, manager = service_scope
    result = await service.create_connector(
        connector_data(
            operations=[
                {
                    "slug": "disabled",
                    "name": "disabled",
                    "operation_type": "read",
                    "endpoint_template": "/read",
                    "enabled": False,
                }
            ]
        ),
        actor="actor",
    )
    async with manager.get_async_session_context() as db:
        operation = await ConnectorRepository(db).get_operation(result["id"], "disabled")
        assert operation.enabled is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint_template", "/different-target"),
        ("query_template", {"wrong": "target"}),
        ("body_template", {"wrong": "target"}),
        ("response_type", "text"),
    ],
)
async def test_provider_owned_request_fields_cannot_misrepresent_actual_execution(service_scope, field, value):
    """SaaS 请求归属不能保存与真实 adapter 行为不同的显示定义。"""
    service, manager = service_scope
    await service.create_connector(
        connector_data(connector_type="salesforce", config={"base_url": "https://example.com", "api_version": "v59.0"}),
        actor="actor",
    )
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("managed")
        operation = await ConnectorRepository(db).get_operation(connector.id, "get_customer")
        revision = operation.revision
    with pytest.raises(ConnectorServiceError):
        await service.update_connector_operation(
            "managed", "get_customer", {"expected_revision": revision, field: value}, actor="actor"
        )
    async with manager.get_async_session_context() as db:
        operation = await ConnectorRepository(db).get_operation(connector.id, "get_customer")
        assert operation.revision == revision
    updated = await service.update_connector_operation(
        "managed", "get_customer", {"expected_revision": revision, "name": "允许修改显示名称"}, actor="actor"
    )
    assert set(updated["provider_owned_fields"]) == {
        "http_method",
        "endpoint_template",
        "query_template",
        "body_template",
        "response_type",
    }


@pytest.mark.parametrize("auth,credentials", [("bearer", {}), ("basic", {"username": "synthetic"}), ("api_key", {})])
async def test_enabled_connector_requires_complete_authentication_pair(service_scope, auth, credentials):
    """启用配置不能只保存认证标签而缺少实际凭据。"""
    service, manager = service_scope
    with pytest.raises(ConnectorServiceError):
        await service.create_connector(
            connector_data(
                enabled=True, config={"base_url": "https://example.com", "auth_type": auth}, credentials=credentials
            ),
            actor="actor",
        )
    async with manager.get_async_session_context() as db:
        assert await ConnectorRepository(db).get_by_slug("managed") is None


async def test_required_credential_deletion_needs_atomic_disable_and_overlap_is_rejected(service_scope):
    """缺配删除与矛盾意图回滚，明确同时停用才可以撤销必需凭据。"""
    service, manager = service_scope
    created = await service.create_connector(
        connector_data(
            enabled=True,
            config={"base_url": "https://example.com", "auth_type": "bearer"},
            credentials={"token": "synthetic"},
        ),
        actor="actor",
    )
    with pytest.raises(ConnectorServiceError):
        await service.update_connector_credentials(
            "managed", {"expected_revision": created["revision"], "delete_keys": ["token"]}, actor="actor"
        )
    with pytest.raises(ConnectorServiceError):
        await service.update_connector_credentials(
            "managed",
            {"expected_revision": created["revision"], "upsert": {"token": "replacement"}, "delete_keys": ["token"]},
            actor="actor",
        )
    disabled = await service.update_connector_credentials(
        "managed", {"expected_revision": created["revision"], "enabled": False, "delete_keys": ["token"]}, actor="actor"
    )
    assert disabled["enabled"] is False and disabled["credential_keys"] == []
    with pytest.raises(ConnectorServiceError):
        await service.update_connector(
            "managed", {"expected_revision": disabled["revision"], "enabled": True}, actor="actor"
        )


@pytest.mark.parametrize(
    "kind,config,count",
    [
        ("salesforce", {"base_url": "https://example.com", "api_version": "v59.0"}, 5),
        (
            "feishu_bitable_crm",
            {
                "base_url": "https://open.feishu.cn",
                "app_token": "synthetic",
                "customer_table_id": "syntheticCustomer",
                "opportunity_table_id": "syntheticOpportunity",
                "customer_fields": {"name": "客户名称"},
            },
            7,
        ),
    ],
)
async def test_standard_provider_operations_are_persisted_on_management_create(service_scope, kind, config, count):
    """可发现操作必须成为可选持久定义，不能仅存在 adapter 方法。"""
    service, manager = service_scope
    created = await service.create_connector(connector_data(connector_type=kind, config=config), actor="actor")
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_id(created["id"])
        operations = connector.operations
        assert len(operations) == count
        assert any(op.slug == "query_customer" for op in operations)
        assert all(op.approval_policy == "required" for op in operations if op.operation_type == "write")


@pytest.mark.parametrize(
    "slug,operation_type,method", [("arbitrary", "read", "GET"), ("get_customer", "write", "PATCH")]
)
async def test_provider_catalog_cannot_be_replaced_with_an_arbitrary_or_misclassified_operation(
    service_scope, slug, operation_type, method
):
    """SaaS 操作类别与固定 provider 合约一致，不能借配置绕过审批分类。"""
    service, manager = service_scope
    with pytest.raises(ConnectorServiceError, match="connector_configuration_invalid"):
        await service.create_connector(
            connector_data(
                connector_type="salesforce",
                config={"base_url": "https://example.com", "api_version": "v59.0"},
                operations=[
                    {
                        "slug": slug,
                        "name": "synthetic",
                        "operation_type": operation_type,
                        "http_method": method,
                        "endpoint_template": "/services/data",
                    }
                ],
            ),
            actor="actor",
        )
    async with manager.get_async_session_context() as db:
        assert await ConnectorRepository(db).get_by_slug("managed") is None


async def test_feishu_mapping_patch_updates_only_unmodified_standard_schemas(service_scope):
    """逻辑键变化与标准 schema 同事务同步，不覆盖管理员自定义限制。"""
    service, manager = service_scope
    config = {
        "base_url": "https://open.feishu.cn",
        "app_token": "synthetic",
        "customer_table_id": "syntheticCustomer",
        "opportunity_table_id": "syntheticOpportunity",
        "customer_fields": {"name": "Customer Name"},
    }
    created = await service.create_connector(
        connector_data(connector_type="feishu_bitable_crm", config=config), actor="actor"
    )
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("managed")
        operation = await ConnectorRepository(db).get_operation(connector.id, "update_customer")
        operation.request_schema = {**operation.request_schema, "required": ["record_id", "name"]}
        custom_schema = operation.request_schema
    changed = await service.update_connector(
        "managed",
        {
            "expected_revision": created["revision"],
            "config": {**config, "customer_fields": {"name": "Customer Name", "phone": "Phone"}},
        },
        actor="actor",
    )
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("managed")
        create = await repo.get_operation(connector.id, "create_customer")
        update = await repo.get_operation(connector.id, "update_customer")
        assert "phone" in create.request_schema["properties"] and create.revision == 2
        assert update.request_schema == custom_schema
        assert connector.revision == changed["revision"] and connector.revision > created["revision"]


async def test_soft_delete_clears_live_credentials_and_keeps_connector_tombstone(service_scope):
    """已冻结调用保留自身证据，删除连接器不继续保留活凭据。"""
    service, manager = service_scope
    await service.create_connector(
        connector_data(
            config={"base_url": "https://example.com", "auth_type": "bearer"},
            credentials={"token": "synthetic-retained-only-in-frozen-history"},
        ),
        actor="actor",
    )
    await service.delete_connector("managed", actor="actor")
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("managed", include_deleted=True)
        assert connector.deleted_at is not None and not connector.enabled
        assert await db.scalar(text("SELECT count(*) FROM connector_credentials")) == 0


async def test_connector_patch_clears_nullable_description_but_preserves_omitted_fields(service_scope):
    """PATCH 的显式 null 必须写入 SQL NULL，省略字段保持原值。"""
    service, manager = service_scope
    await service.create_connector(connector_data(description="original"), actor="actor")
    updated = await service.update_connector("managed", {"expected_revision": 1, "description": None}, actor="actor")
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("managed")
        assert connector.description is None and connector.name == "Managed"
    with pytest.raises(ConnectorServiceError):
        await service.update_connector(
            "managed", {"expected_revision": updated["revision"], "enabled": None}, actor="actor"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"connector_type": "unknown"},
        {"config": {"base_url": "https://example.com", "auth_type": "made-up"}},
        {"config": {"base_url": "https://user:secret@example.com", "auth_type": "none"}},
        {"config": {"base_url": "https://example.com", "auth_type": "none", "unexpected": 1}},
        {"write_scope": {"level": "public"}},
        {
            "config": {
                "base_url": "https://example.com",
                "auth_type": "none",
                "static_headers": {"Host": "other.example"},
            }
        },
    ],
)
async def test_invalid_management_configuration_is_rejected_before_persistence(service_scope, changes):
    service, manager = service_scope
    with pytest.raises(ConnectorServiceError):
        await service.create_connector(connector_data(**changes), actor="actor")
    async with manager.get_async_session_context() as db:
        assert await ConnectorRepository(db).get_by_slug("managed") is None


async def test_management_checks_actual_role_and_preserves_encrypted_credential_status(service_scope, fernet_key):
    service, manager = service_scope
    created = await service.create_connector(connector_data(), actor="actor")
    updated = await service.update_connector_credentials(
        "managed",
        {
            "expected_revision": created["revision"],
            "upsert": {"token": "fixture-secret"},
            "delete_keys": [],
        },
        actor="actor",
    )
    assert updated["revision"] == created["revision"] + 1
    assert updated["credential_keys"][0]["key"] == "token"
    assert "fixture-secret" not in str(updated)
    async with manager.get_async_session_context() as db:
        ciphertext = await db.scalar(text("SELECT credential_value FROM connector_credentials"))
        assert fernet_key.decrypt(ciphertext) == b"fixture-secret"
        (await ConnectorRepository(db).get_active_actor("actor")).role = "user"
    with pytest.raises(ConnectorAuthorizationError):
        await service.update_connector(
            "managed", {"expected_revision": updated["revision"], "name": "not allowed"}, actor="actor"
        )


async def test_concurrent_management_patch_has_one_revision_winner(service_scope):
    service, manager = service_scope
    created = await service.create_connector(connector_data(), actor="actor")
    results = await asyncio.gather(
        *(
            service.update_connector(
                "managed",
                {
                    "expected_revision": created["revision"],
                    "name": name,
                },
                actor="actor",
            )
            for name in ["first", "second"]
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ConnectorServiceError) for result in results) == 1
    async with manager.get_async_session_context() as db:
        assert (await ConnectorRepository(db).get_by_slug("managed")).revision == created["revision"] + 1


async def test_operation_patch_distinguishes_omitted_fields_from_explicit_clear(service_scope):
    """PATCH 清空映射而保留未提交正文，旧 revision 不能再覆盖。"""
    service, _ = service_scope
    await service.create_connector(connector_data(), actor="actor")
    operation = await service.create_connector_operation(
        "managed",
        {
            "slug": "read",
            "name": "Read",
            "operation_type": "read",
            "http_method": "GET",
            "endpoint_template": "/record",
            "body_template": {"keep": True},
            "response_mapping": {"result": "result"},
        },
        actor="actor",
    )
    updated = await service.update_connector_operation(
        "managed",
        "read",
        {
            "expected_revision": operation["revision"],
            "response_mapping": None,
        },
        actor="actor",
    )
    assert updated["response_mapping"] is None and updated["body_template"] == {"keep": True}
    with pytest.raises(ConnectorServiceError):
        await service.update_connector_operation(
            "managed",
            "read",
            {
                "expected_revision": operation["revision"],
                "name": "stale",
            },
            actor="actor",
        )


async def test_unknown_write_blocks_connector_and_operation_deletion(service_scope):
    """未核实远端写保留证据与恢复材料，不能通过删除绕过核对。"""
    service, manager = service_scope
    await service.create_connector(connector_data(), actor="actor")
    operation = await service.create_connector_operation(
        "managed",
        {
            "slug": "write",
            "name": "Write",
            "operation_type": "write",
            "http_method": "POST",
            "endpoint_template": "/record",
        },
        actor="actor",
    )
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("managed")
        from yuxi.storage.postgres.models_business import ConnectorUsageLog

        db.add(
            ConnectorUsageLog(
                connector_id=connector.id,
                operation_id=operation["id"],
                connector_slug="managed",
                operation_slug="write",
                operation_type="write",
                actor_uid="actor",
                consumer_type="admin_test",
                logical_call_key="unknown-write",
                connector_revision=connector.revision,
                operation_revision=operation["revision"],
                status="unknown",
            )
        )
    with pytest.raises(ConnectorServiceError):
        await service.delete_connector("managed", actor="actor")
    with pytest.raises(ConnectorServiceError):
        await service.delete_connector_operation("managed", "write", actor="actor")
