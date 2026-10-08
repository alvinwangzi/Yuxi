"""连接器调用执行 Repository 在真实 PostgreSQL 上的生命周期验收。"""

from __future__ import annotations

import os
import uuid

import pytest
from test.integration.isolated_postgres_fixtures import (
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    ensure_live_api_schema as ensure_live_api_schema,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
]


def _require_postgres() -> str:
    url = os.environ.get("POSTGRES_URL")
    if not url:
        pytest.skip("POSTGRES_URL 未配置，跳过集成测试")
    return url


@pytest.fixture
async def isolated_db():
    """提供隔离 Schema 中的 AsyncSession。"""
    from sqlalchemy import text

    from yuxi.storage.postgres.manager import PostgresManager

    url = _require_postgres()
    schema = f"pytest_connector_exec_{uuid.uuid4().hex[:12]}"
    admin_engine = create_async_engine(url, pool_pre_ping=True)
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )

    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = test_engine
    manager._initialized = True
    await manager.create_business_tables()

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await test_engine.dispose()
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await admin_engine.dispose()


async def _seed_connector_and_operation(db):
    from yuxi.repositories.connector_repository import ConnectorRepository

    repo = ConnectorRepository(db)
    connector = await repo.create(
        slug="exec-test",
        name="执行测试",
        connector_type="generic_rest",
        created_by="admin",
    )
    operation = await repo.create_operation(
        connector_id=connector.id,
        slug="read_data",
        name="读取数据",
        operation_type="read",
        http_method="GET",
        endpoint_template="/v1/data",
    )
    await db.commit()
    return connector, operation


class TestInvocationLifecycle:
    """调用记录创建→claim→finalize 全流程。"""

    async def test_create_and_get_invocation(self, isolated_db):
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

        connector, operation = await _seed_connector_and_operation(isolated_db)
        exec_repo = ConnectorExecutionRepository(isolated_db)

        invocation = await exec_repo.create_invocation(
            connector_id=connector.id,
            operation_id=operation.id,
            connector_slug="exec-test",
            operation_slug="read_data",
            operation_type="read",
            actor_uid="user-1",
            consumer_type="agent",
            logical_call_key=f"test:{uuid.uuid4()}",
            connector_revision=1,
            operation_revision=1,
        )
        await isolated_db.commit()

        assert invocation.id is not None
        assert invocation.status == "prepared"

        fetched = await exec_repo.get_invocation(invocation.id)
        assert fetched is not None
        assert fetched.connector_slug == "exec-test"

    async def test_claim_and_finalize(self, isolated_db):
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

        connector, operation = await _seed_connector_and_operation(isolated_db)
        exec_repo = ConnectorExecutionRepository(isolated_db)

        invocation = await exec_repo.create_invocation(
            connector_id=connector.id,
            operation_id=operation.id,
            connector_slug="exec-test",
            operation_slug="read_data",
            operation_type="read",
            actor_uid="user-1",
            consumer_type="agent",
            logical_call_key=f"test:{uuid.uuid4()}",
            connector_revision=1,
            operation_revision=1,
        )
        await isolated_db.commit()

        claimed = await exec_repo.claim_invocation(
            invocation, owner_id="worker-1", owner_attempt="attempt-1", lease_seconds=120,
        )
        await isolated_db.commit()
        assert claimed is True

        finalized = await exec_repo.finalize_invocation(
            invocation,
            owner_attempt="attempt-1",
            status="succeeded",
            remote_outcome="succeeded",
            response_status=200,
            duration_ms=150,
        )
        await isolated_db.commit()
        assert finalized.status == "succeeded"
        assert finalized.remote_outcome == "succeeded"

    async def test_dedup_by_logical_call_key(self, isolated_db):
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

        connector, operation = await _seed_connector_and_operation(isolated_db)
        exec_repo = ConnectorExecutionRepository(isolated_db)

        key = f"dedup:{uuid.uuid4()}"
        inv1 = await exec_repo.create_invocation(
            connector_id=connector.id,
            operation_id=operation.id,
            connector_slug="exec-test",
            operation_slug="read_data",
            operation_type="read",
            actor_uid="user-1",
            consumer_type="agent",
            logical_call_key=key,
            connector_revision=1,
            operation_revision=1,
        )
        await isolated_db.commit()

        existing = await exec_repo.get_by_logical_call_key(key)
        assert existing is not None
        assert existing.id == inv1.id


class TestApprovalFlow:
    """审批流程：approve/reject 状态转换。"""

    async def test_approve_invocation(self, isolated_db):
        from datetime import timedelta

        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.utils.datetime_utils import utc_now

        connector, operation = await _seed_connector_and_operation(isolated_db)
        exec_repo = ConnectorExecutionRepository(isolated_db)

        invocation = await exec_repo.create_invocation(
            connector_id=connector.id,
            operation_id=operation.id,
            connector_slug="exec-test",
            operation_slug="read_data",
            operation_type="write",
            actor_uid="user-1",
            consumer_type="agent",
            logical_call_key=f"approve:{uuid.uuid4()}",
            connector_revision=1,
            operation_revision=1,
            approval_policy="required",
        )
        await isolated_db.commit()

        expires = utc_now() + timedelta(minutes=30)
        approved = await exec_repo.approve_invocation(
            invocation, approved_by="admin-1", approval_digest="sha256:abc", expires_at=expires,
        )
        await isolated_db.commit()
        assert approved.status == "prepared"

    async def test_reject_invocation(self, isolated_db):
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

        connector, operation = await _seed_connector_and_operation(isolated_db)
        exec_repo = ConnectorExecutionRepository(isolated_db)

        invocation = await exec_repo.create_invocation(
            connector_id=connector.id,
            operation_id=operation.id,
            connector_slug="exec-test",
            operation_slug="read_data",
            operation_type="write",
            actor_uid="user-1",
            consumer_type="agent",
            logical_call_key=f"reject:{uuid.uuid4()}",
            connector_revision=1,
            operation_revision=1,
            approval_policy="required",
        )
        await isolated_db.commit()

        rejected = await exec_repo.reject_invocation(
            invocation, rejected_by="admin-1", reason="参数不安全",
        )
        await isolated_db.commit()
        assert rejected.status == "rejected"


class TestLeaseAndRecovery:
    """Lease 过期与 stale lease 扫描。"""

    async def test_find_stale_leases(self, isolated_db):
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.utils.datetime_utils import utc_now

        connector, operation = await _seed_connector_and_operation(isolated_db)
        exec_repo = ConnectorExecutionRepository(isolated_db)

        invocation = await exec_repo.create_invocation(
            connector_id=connector.id,
            operation_id=operation.id,
            connector_slug="exec-test",
            operation_slug="read_data",
            operation_type="read",
            actor_uid="user-1",
            consumer_type="agent",
            logical_call_key=f"lease:{uuid.uuid4()}",
            connector_revision=1,
            operation_revision=1,
        )
        await isolated_db.commit()

        await exec_repo.claim_invocation(
            invocation, owner_id="worker-1", owner_attempt="attempt-1", lease_seconds=1,
        )
        await isolated_db.commit()

        import asyncio
        await asyncio.sleep(1.5)

        stale = await exec_repo.find_stale_leases(utc_now())
        assert any(i.id == invocation.id for i in stale)


class TestAttemptTracking:
    """操作尝试记录。"""

    async def test_create_and_finalize_attempt(self, isolated_db):
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

        connector, operation = await _seed_connector_and_operation(isolated_db)
        exec_repo = ConnectorExecutionRepository(isolated_db)

        invocation = await exec_repo.create_invocation(
            connector_id=connector.id,
            operation_id=operation.id,
            connector_slug="exec-test",
            operation_slug="read_data",
            operation_type="read",
            actor_uid="user-1",
            consumer_type="agent",
            logical_call_key=f"attempt:{uuid.uuid4()}",
            connector_revision=1,
            operation_revision=1,
        )
        await isolated_db.commit()

        attempt = await exec_repo.create_attempt(
            invocation.id, attempt_no=1, owner_attempt="attempt-1",
        )
        await isolated_db.commit()
        assert attempt.attempt_no == 1

        finalized = await exec_repo.finalize_attempt(
            attempt, send_state="sent", response_status=200, duration_ms=100,
        )
        await isolated_db.commit()
        assert finalized.send_state == "sent"

        attempts = await exec_repo.list_attempts(invocation.id)
        assert len(attempts) == 1
