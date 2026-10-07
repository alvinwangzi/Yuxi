"""连接器 Repository 在真实 PostgreSQL 上的 CRUD 与约束验收。"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
]


def _require_postgres() -> str:
    url = os.environ.get("POSTGRES_URL")
    if not url:
        pytest.skip("POSTGRES_URL 未配置，跳过集成测试")
    return url


async def _create_isolated_schema(prefix: str):
    """创建隔离 PostgreSQL Schema 用于测试。"""
    from sqlalchemy import text

    url = _require_postgres()
    schema = f"{prefix}_{uuid.uuid4().hex[:12]}"
    admin_engine = create_async_engine(url, pool_pre_ping=True)
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    return schema, admin_engine, test_engine


async def _drop_isolated_schema(schema: str, admin_engine, test_engine) -> None:
    from sqlalchemy import text

    await test_engine.dispose()
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await admin_engine.dispose()


@pytest.fixture
async def isolated_db():
    """提供隔离 Schema 中的 AsyncSession。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from yuxi.storage.postgres.manager import PostgresManager

    schema, admin_engine, test_engine = await _create_isolated_schema("pytest_connector_repo")
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = test_engine
    manager._initialized = True

    await manager.create_business_tables()

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await _drop_isolated_schema(schema, admin_engine, test_engine)


class TestConnectorRepositoryCRUD:
    """连接器基础 CRUD 与 revision 递增。"""

    async def test_create_and_get_by_slug(self, isolated_db):
        from yuxi.repositories.connector_repository import ConnectorRepository

        repo = ConnectorRepository(isolated_db)
        connector = await repo.create(
            slug="test-crm",
            name="测试 CRM",
            connector_type="generic_rest",
            description="测试用通用 REST 连接器",
            config={"base_url": "https://api.example.com"},
            created_by="test-admin",
        )
        await isolated_db.commit()

        assert connector.id > 0
        assert connector.revision == 1

        fetched = await repo.get_by_slug("test-crm")
        assert fetched is not None
        assert fetched.name == "测试 CRM"
        assert fetched.connector_type == "generic_rest"

    async def test_update_increments_revision(self, isolated_db):
        from yuxi.repositories.connector_repository import ConnectorRepository

        repo = ConnectorRepository(isolated_db)
        connector = await repo.create(
            slug="test-rev",
            name="版本测试",
            connector_type="generic_rest",
            created_by="admin",
        )
        await isolated_db.commit()
        assert connector.revision == 1

        updated = await repo.update_config(
            connector,
            name="版本测试-更新",
            description="新增描述",
            updated_by="admin",
        )
        await isolated_db.commit()
        assert updated.revision == 2
        assert updated.name == "版本测试-更新"

    async def test_soft_delete_sets_tombstone(self, isolated_db):
        from yuxi.repositories.connector_repository import ConnectorRepository

        repo = ConnectorRepository(isolated_db)
        connector = await repo.create(
            slug="test-del",
            name="删除测试",
            connector_type="generic_rest",
            created_by="admin",
        )
        await isolated_db.commit()

        deleted = await repo.soft_delete(connector, updated_by="admin")
        await isolated_db.commit()
        assert deleted.deleted_at is not None
        assert deleted.revision == 1

        active = await repo.get_by_slug("test-del")
        assert active is None

        all_with_deleted = await repo.list_all(include_deleted=True)
        assert any(c.slug == "test-del" for c in all_with_deleted)

    async def test_list_usable_filters_disabled_and_deleted(self, isolated_db):
        from yuxi.repositories.connector_repository import ConnectorRepository

        repo = ConnectorRepository(isolated_db)
        await repo.create(slug="usable-1", name="可用1", connector_type="generic_rest", created_by="admin")
        await repo.create(slug="usable-2", name="可用2", connector_type="generic_rest", created_by="admin")
        disabled = await repo.create(slug="usable-3", name="禁用", connector_type="generic_rest", created_by="admin")
        await repo.soft_delete(disabled, updated_by="admin")
        await isolated_db.commit()

        usable = await repo.list_all(include_deleted=False)
        slugs = {c.slug for c in usable}
        assert "usable-1" in slugs
        assert "usable-2" in slugs
        assert "usable-3" not in slugs


class TestConnectorOperationCRUD:
    """操作 CRUD 与约束。"""

    async def test_create_operation(self, isolated_db):
        from yuxi.repositories.connector_repository import ConnectorRepository

        repo = ConnectorRepository(isolated_db)
        connector = await repo.create(
            slug="op-test",
            name="操作测试",
            connector_type="generic_rest",
            created_by="admin",
        )
        await isolated_db.commit()

        operation = await repo.create_operation(
            connector_id=connector.id,
            slug="query_users",
            name="查询用户",
            operation_type="read",
            http_method="GET",
            endpoint_template="/v1/users",
        )
        await isolated_db.commit()

        assert operation.id > 0
        assert operation.revision == 1
        assert operation.operation_type == "read"

        fetched = await repo.get_operation(connector.id, "query_users")
        assert fetched is not None
        assert fetched.name == "查询用户"

    async def test_update_operation_increments_revision(self, isolated_db):
        from yuxi.repositories.connector_repository import ConnectorRepository

        repo = ConnectorRepository(isolated_db)
        connector = await repo.create(
            slug="op-rev",
            name="操作版本",
            connector_type="generic_rest",
            created_by="admin",
        )
        await isolated_db.commit()

        operation = await repo.create_operation(
            connector_id=connector.id,
            slug="update_user",
            name="更新用户",
            operation_type="write",
            http_method="PUT",
            endpoint_template="/v1/users/{{id}}",
        )
        await isolated_db.commit()
        assert operation.revision == 1

        updated = await repo.update_operation(operation, name="更新用户-修改")
        await isolated_db.commit()
        assert updated.revision == 2


class TestConnectorCredentials:
    """凭据事务与加密存储。"""

    async def test_upsert_and_get_credential(self, isolated_db):
        from yuxi.repositories.connector_repository import ConnectorRepository

        repo = ConnectorRepository(isolated_db)
        connector = await repo.create(
            slug="cred-test",
            name="凭据测试",
            connector_type="generic_rest",
            created_by="admin",
        )
        await isolated_db.commit()

        ciphertext = b"encrypted_token_data"
        cred = await repo.upsert_credential(connector.id, "access_token", ciphertext, "key-v1")
        await isolated_db.commit()

        assert cred.credential_key == "access_token"
        assert cred.credential_value == ciphertext
        assert cred.key_id == "key-v1"

        fetched = await repo.get_credential(connector.id, "access_token")
        assert fetched is not None
        assert fetched.credential_value == ciphertext

    async def test_delete_credentials(self, isolated_db):
        from yuxi.repositories.connector_repository import ConnectorRepository

        repo = ConnectorRepository(isolated_db)
        connector = await repo.create(
            slug="cred-del",
            name="凭据删除",
            connector_type="generic_rest",
            created_by="admin",
        )
        await isolated_db.commit()

        await repo.upsert_credential(connector.id, "token_a", b"data_a", "v1")
        await repo.upsert_credential(connector.id, "token_b", b"data_b", "v1")
        await isolated_db.commit()

        deleted_count = await repo.delete_credentials(connector.id, ["token_a"])
        await isolated_db.commit()
        assert deleted_count == 1

        remaining = await repo.list_credentials(connector.id)
        assert len(remaining) == 1
        assert remaining[0].credential_key == "token_b"
