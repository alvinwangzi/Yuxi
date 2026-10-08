"""明确历史 DDL 的连接器 v20→v21 UTC、UUID 与约束迁移。"""

import pytest
from sqlalchemy import text
from test.integration.services.test_schema_migration_version import (
    ensure_live_api_schema as ensure_live_api_schema,
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    create_isolated_manager,
    drop_isolated_schema,
)
from yuxi.storage.postgres.models_business import Connector, ConnectorUsageLog, WorkflowRun

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

LEGACY_TABLES = [
    "CREATE TABLE connectors (id SERIAL PRIMARY KEY, slug VARCHAR(80), created_at TIMESTAMP, updated_at TIMESTAMP, deleted_at TIMESTAMP)",
    "CREATE TABLE connector_credentials (id SERIAL PRIMARY KEY, key_id VARCHAR(64), updated_at TIMESTAMP)",
    "CREATE TABLE connector_operations (id SERIAL PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP)",
    "CREATE TABLE connector_usage_logs (id VARCHAR(36) PRIMARY KEY, actor_uid VARCHAR(64), operation_type VARCHAR(10), status VARCHAR(32), remote_outcome VARCHAR(20), approval_policy VARCHAR(20), consumer_type VARCHAR(32), approved_at TIMESTAMP, approval_expires_at TIMESTAMP, lease_expires_at TIMESTAMP, heartbeat_at TIMESTAMP, created_at TIMESTAMP, started_at TIMESTAMP, completed_at TIMESTAMP)",
    "CREATE TABLE connector_operation_attempts (id SERIAL PRIMARY KEY, started_at TIMESTAMP, completed_at TIMESTAMP, created_at TIMESTAMP)",
    "CREATE TABLE workflow_runs (id SERIAL PRIMARY KEY, status VARCHAR(20), next_dispatch_at TIMESTAMP, lease_expires_at TIMESTAMP, heartbeat_at TIMESTAMP)",
    "CREATE TABLE workflow_step_runs (id SERIAL PRIMARY KEY, pending_connector_invocation_id INTEGER)",
]


async def test_orm_uses_aware_datetime_for_connector_and_workflow_ownership():
    assert Connector.created_at.type.timezone
    assert ConnectorUsageLog.approval_expires_at.type.timezone
    assert WorkflowRun.lease_expires_at.type.timezone


@pytest.mark.parametrize("fail_version_write", [False, True])
@pytest.mark.parametrize("legacy_version", [19, 20])
async def test_legacy_naive_utc_and_uuid_column_upgrade_is_atomic_and_repeatable(fail_version_write, legacy_version):
    schema, admin, engine, manager = await create_isolated_manager("pytest_connector_v20")
    try:
        await manager.create_schema_version_table()
        async with engine.begin() as db:
            for statement in LEGACY_TABLES:
                await db.execute(text(statement))
            await db.execute(
                text("INSERT INTO yuxi_schema_migrations(domain,version) VALUES ('business',:version)"),
                {"version": legacy_version},
            )
            await db.execute(
                text("INSERT INTO connectors(slug,created_at) VALUES ('legacy',TIMESTAMP '2026-10-01 03:04:05')")
            )
            await db.execute(text("INSERT INTO workflow_step_runs(pending_connector_invocation_id) VALUES (7)"))
            if fail_version_write:
                await db.execute(text("ALTER TABLE yuxi_schema_migrations ADD CONSTRAINT reject_v21 CHECK(version<21)"))
        if fail_version_write:
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                await manager.upgrade_connector_schema_v21()
            async with engine.connect() as db:
                assert (
                    await db.scalar(
                        text(
                            "SELECT data_type FROM information_schema.columns WHERE table_schema=:schema AND table_name='connectors' AND column_name='created_at'"
                        ),
                        {"schema": schema},
                    )
                    == "timestamp without time zone"
                )
                assert (
                    await db.scalar(text("SELECT version FROM yuxi_schema_migrations WHERE domain='business'"))
                    == legacy_version
                )
            return
        await manager.upgrade_connector_schema_v21()
        await manager.upgrade_connector_schema_v21()
        async with engine.begin() as db:
            await db.execute(text("SET LOCAL TIME ZONE 'Asia/Shanghai'"))
            assert await db.scalar(
                text("SELECT created_at AT TIME ZONE 'UTC' FROM connectors WHERE slug='legacy'")
            ) == __import__("datetime").datetime(2026, 10, 1, 3, 4, 5)
            assert await db.scalar(text("SELECT pending_connector_invocation_id FROM workflow_step_runs")) == "7"
            assert await db.scalar(text("SELECT version FROM yuxi_schema_migrations WHERE domain='business'")) == 21
        from sqlalchemy.exc import IntegrityError

        async with engine.begin() as db:
            with pytest.raises(IntegrityError):
                await db.execute(
                    text(
                        "INSERT INTO connector_usage_logs(id,actor_uid,status,operation_type,consumer_type) VALUES ('bad','', 'not-a-state','read','agent')"
                    )
                )
    finally:
        await drop_isolated_schema(schema, admin, engine)


async def test_fresh_schema_and_repeat_migration_preserve_business_datetime_contract():
    """新库重复升级后类型与约束成立，无关业务时间保持原契约。"""
    schema, admin, engine, manager = await create_isolated_manager("pytest_connector_fresh")
    try:
        await manager.create_schema_version_table()
        await manager.create_business_tables()
        await manager.upgrade_connector_schema_v21()
        await manager.upgrade_connector_schema_v21()
        async with engine.connect() as db:
            assert await db.scalar(text("SELECT version FROM yuxi_schema_migrations WHERE domain='business'")) == 21
            assert (
                await db.scalar(
                    text(
                        "SELECT data_type FROM information_schema.columns WHERE table_schema=:schema AND table_name='connector_operation_attempts' AND column_name='created_at'"
                    ),
                    {"schema": schema},
                )
                == "timestamp with time zone"
            )
            assert (
                await db.scalar(
                    text(
                        "SELECT data_type FROM information_schema.columns WHERE table_schema=:schema AND table_name='workflow_step_runs' AND column_name='started_at'"
                    ),
                    {"schema": schema},
                )
                == "timestamp without time zone"
            )
    finally:
        await drop_isolated_schema(schema, admin, engine)


async def test_real_v19_without_connector_tables_converges_through_shipping_manager():
    """v19 缺少连接器表，由真实 ensure DDL 创建后进入 v21。"""
    schema, admin, engine, manager = await create_isolated_manager("pytest_connector_v19")
    try:
        await manager.create_schema_version_table()
        await manager.create_business_tables()
        async with engine.begin() as db:
            for table in ("connector_operation_attempts", "connector_usage_logs", "connector_operations", "connector_credentials", "connectors"):
                await db.execute(text(f"DROP TABLE {table}"))
            await db.execute(text("ALTER TABLE workflow_step_runs DROP COLUMN pending_connector_invocation_id"))
        await manager.record_schema_version("business", 19)
        await manager.ensure_business_schema()
        await manager.upgrade_connector_schema_v21()
        await manager.upgrade_connector_schema_v21()
        async with engine.connect() as db:
            assert await db.scalar(text("SELECT version FROM yuxi_schema_migrations WHERE domain='business'")) == 21
            assert await db.scalar(text("SELECT to_regclass('connector_usage_logs') IS NOT NULL"))
            assert await db.scalar(text("SELECT data_type FROM information_schema.columns WHERE table_schema=:schema AND table_name='workflow_step_runs' AND column_name='pending_connector_invocation_id'"), {"schema": schema}) == "character varying"
    finally:
        await drop_isolated_schema(schema, admin, engine)


async def test_invalid_legacy_identity_is_retained_but_new_invalid_write_is_rejected():
    """迁移不伪造历史用户，约束诊断后保留证据并拒绝新坏数据。"""
    from sqlalchemy.exc import IntegrityError
    schema, admin, engine, manager = await create_isolated_manager("pytest_connector_legacy_invalid")
    try:
        await manager.create_schema_version_table()
        async with engine.begin() as db:
            for statement in LEGACY_TABLES:
                await db.execute(text(statement))
            await db.execute(text("INSERT INTO connector_usage_logs(id,actor_uid,status,operation_type,consumer_type) VALUES ('legacy','', 'prepared','read','agent')"))
        await manager.upgrade_connector_schema_v21()
        async with engine.connect() as db:
            assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs WHERE actor_uid=''")) == 1
            assert not await db.scalar(text("SELECT convalidated FROM pg_constraint WHERE conrelid='connector_usage_logs'::regclass AND conname='ck_connector_logs_actor'"))
        async with engine.begin() as db:
            with pytest.raises(IntegrityError):
                await db.execute(text("INSERT INTO connector_usage_logs(id,actor_uid,status,operation_type,consumer_type) VALUES ('new','', 'prepared','read','agent')"))
    finally:
        await drop_isolated_schema(schema, admin, engine)
