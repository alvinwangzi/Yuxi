"""独立审查缺陷的真实 PostgreSQL、HTTP 与工作流恢复回归。"""

import asyncio
import json
import time
from datetime import timedelta
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, text
from test.integration.services.test_connector_service import (
    service_scope as service_scope,
    vault_configuration as vault_configuration,
    vault as vault,
    fernet_key as fernet_key,
    http_provider as http_provider,
    execution,
    ensure_live_api_schema as ensure_live_api_schema,
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
)
from yuxi.repositories.connector_repository import ConnectorRepository
from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.services.connectors.factory import ConnectorServiceFactory, override_factory
from yuxi.services.connectors.service import ConnectorConflictError, ConnectorApprovalRequired, ConnectorServiceError
from yuxi.services.workflow_execution_service import execute_workflow_run
from yuxi.services.workflow_service import request_workflow_resume
from yuxi.storage.postgres.models_business import AgentRun, ConnectorUsageLog, Workflow, WorkflowRun, WorkflowStepRun

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.mark.parametrize("operation_type", ["read", "write"])
@pytest.mark.parametrize("orphan", ["null_owner", "null_lease"])
async def test_legacy_orphan_recovery_does_not_rollback_healthy_stale_batch(service_scope, operation_type, orphan):
    """缺 owner 或 lease 的存量行不伪造身份，也不能阻断同批正常过期行。"""
    from yuxi.services.connectors.recovery import recover_stale_leases
    from yuxi.utils.datetime_utils import utc_now

    service, manager = service_scope
    if operation_type == "write":
        async with manager.get_async_session_context() as db:
            repo = ConnectorRepository(db)
            connector = await repo.get_by_slug("service-test")
            connector.write_scope = {"access_level": "global"}
            await repo.create_operation(
                connector_id=connector.id,
                slug="write",
                name="write",
                operation_type="write",
                http_method="POST",
                endpoint_template="/write",
                approval_policy="preauthorized",
            )
    identifiers = []
    for key, owner in [
        ("legacy-orphan", None if orphan == "null_owner" else "orphan-owner"),
        ("normal-stale", "normal-owner"),
    ]:
        prepared = await service.prepare_invocation("service-test", operation_type, {}, execution=execution(key))
        identifiers.append(prepared["invocation_id"])
        async with manager.get_async_session_context() as db:
            repo = ConnectorExecutionRepository(db)
            invocation = await repo.get_invocation(prepared["invocation_id"])
            invocation.status = "running"
            invocation.owner_attempt = owner
            invocation.lease_expires_at = (
                None if key == "legacy-orphan" and orphan == "null_lease" else utc_now() - timedelta(seconds=1)
            )
            await repo.create_attempt(invocation.id, 1, owner_attempt=owner)
    stats = await recover_stale_leases(manager.get_async_session_context)
    assert stats["total"] == 2
    async with manager.get_async_session_context() as db:
        for identifier in identifiers:
            invocation = await ConnectorExecutionRepository(db).get_invocation(identifier)
            assert invocation.status == ("failed" if operation_type == "read" else "unknown")
            assert invocation.lease_expires_at is None and invocation.execution_snapshot_ciphertext is None
            assert invocation.error_code == (
                "lease_expired"
                if identifier == identifiers[1]
                else "owner_missing"
                if orphan == "null_owner"
                else "lease_missing"
            )
        assert (
            await db.scalar(text("SELECT count(*) FROM connector_operation_attempts WHERE completed_at IS NULL")) == 0
        )


async def test_concurrent_and_failed_replay_preserve_one_real_http_attempt(service_scope, http_provider):
    """真实执行在途时回报进行中，失败后回放原回执，收包始终只有一次。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
        }
        operation = await repo.get_operation(connector.id, "read")
        operation.endpoint_template = "/slow-retry"
    first = asyncio.create_task(service.prepare_and_execute("service-test", "read", {}, execution=execution()))
    try:
        async with asyncio.timeout(3):
            while not requests:
                await asyncio.sleep(0.01)
        pending = await service.prepare_and_execute("service-test", "read", {}, execution=execution())
        assert pending["status"] == "running" and pending["error_code"] == "execution_in_progress"
        result = await first
        replay = await service.prepare_and_execute("service-test", "read", {}, execution=execution())
        assert not result["success"] and replay["status"] == "failed"
        assert replay["invocation_id"] == result["invocation_id"] and replay["error_code"] == result["error_code"]
        assert replay["response_status"] == result["response_status"] == 503
        assert requests == ["/slow-retry"]
        async with manager.get_async_session_context() as db:
            assert await db.scalar(text("SELECT count(*) FROM connector_operation_attempts")) == 1
    finally:
        if not first.done():
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize("status", ["failed", "cancelled", "running"])
async def test_repeated_logical_call_returns_durable_state_without_claim_or_send(service_scope, http_provider, status):
    """同键回放保留失败、取消或进行中状态，不重新领取或发出 HTTP。"""
    service, manager = service_scope
    _, _, requests = http_provider
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        invocation = await ConnectorExecutionRepository(db).get_invocation(prepared["invocation_id"])
        invocation.status = status
        if status == "failed":
            invocation.error_code = "synthetic_failure"
            invocation.remote_outcome = "failed"
    result = await service.prepare_and_execute("service-test", "read", {}, execution=execution())
    assert result["status"] == status and result["invocation_id"] == prepared["invocation_id"]
    assert (
        result["error_code"]
        == {"failed": "synthetic_failure", "cancelled": "execution_cancelled", "running": "execution_in_progress"}[
            status
        ]
    )
    assert requests == []
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM connector_operation_attempts")) == 0


@pytest.mark.parametrize(
    "path,timeout,success,count", [("/retry-after", 5, True, 2), ("/retry-after-long", 1, False, 1)]
)
async def test_retry_after_is_respected_inside_total_operation_deadline(
    service_scope, http_provider, path, timeout, success, count
):
    """真实 Retry-After 不能被固定短 sleep 忽略，过大值也不能穿过总预算。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
            "timeout_seconds": timeout,
        }
    await service.create_connector_operation(
        "service-test",
        {
            "slug": "retry",
            "name": "retry",
            "operation_type": "read",
            "endpoint_template": path,
            "retry_policy": {"max_attempts": 3},
        },
        actor="actor",
    )
    started = time.monotonic()
    result = await service.prepare_and_execute("service-test", "retry", {}, execution=execution())
    elapsed = time.monotonic() - started
    assert result["success"] is success and requests == [path] * count
    assert 1 <= elapsed < 2.5


@pytest.mark.parametrize("recover", [True, False])
async def test_capacity_wait_releases_transaction_and_claims_when_slot_recovers(service_scope, http_provider, recover):
    """容量恢复后只发一次，等待期间不占用 owning 事务的锁。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
            "concurrency_limit": 1,
        }
    occupying = await service.prepare_invocation("service-test", "read", {}, execution=execution("occupying"))
    async with manager.get_async_session_context() as db:
        row = await ConnectorExecutionRepository(db).get_invocation(occupying["invocation_id"])
        row.status = "running"
    pending = await service.prepare_invocation("service-test", "read", {}, execution=execution("waiting"))
    started = time.monotonic()
    task = asyncio.create_task(service.execute_invocation(pending["invocation_id"], execution=execution("waiting")))
    await asyncio.sleep(0.2)
    assert not task.done() and requests == []
    if not recover:
        with pytest.raises(ConnectorServiceError) as blocked:
            await asyncio.wait_for(task, timeout=6)
        assert blocked.value.code == "capacity_exceeded" and 4.9 <= time.monotonic() - started < 6
        async with manager.get_async_session_context() as db:
            assert await db.scalar(text("SELECT count(*) FROM connector_operation_attempts")) == 0
            assert (
                await ConnectorExecutionRepository(db).get_invocation(pending["invocation_id"])
            ).status == "prepared"
        assert requests == []
        return
    async with manager.get_async_session_context() as db:
        row = await ConnectorExecutionRepository(db).get_invocation(occupying["invocation_id"])
        row.status = "failed"
    result = await asyncio.wait_for(task, timeout=3)
    assert result.success and requests == ["/read"]


async def test_usage_date_range_filters_rows_and_total(service_scope):
    """日期上下界同时约束实际记录与分页总数。"""
    service, manager = service_scope
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        repo = ConnectorExecutionRepository(db)
        invocation = await repo.get_invocation(prepared["invocation_id"])
        moment = invocation.created_at
        rows, total = await repo.list_usage(created_from=moment, created_to=moment)
        assert total == 1 and [row.id for row in rows] == [invocation.id]
        rows, total = await repo.list_usage(created_from=moment + timedelta(seconds=1))
        assert rows == [] and total == 0
        rows, total = await repo.list_usage(created_to=moment - timedelta(seconds=1))
        assert rows == [] and total == 0


async def test_user_invocation_read_rechecks_current_scope_and_bound_run_owner(service_scope):
    """自己的历史调用也不能借旧范围读取，失去可见 Run 绑定同样拒绝。"""
    from yuxi.services.connectors.service import ConnectorAuthorizationError

    service, manager = service_scope
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    result = await service.get_user_invocation(prepared["invocation_id"], actor="actor")
    assert result["invocation_id"] == prepared["invocation_id"] and result["attempts"] == []
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.read_scope = {"access_level": "deny"}
    with pytest.raises(ConnectorAuthorizationError):
        await service.get_user_invocation(prepared["invocation_id"], actor="actor")
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.read_scope = {"access_level": "global"}
        invocation = await ConnectorExecutionRepository(db).get_invocation(prepared["invocation_id"])
        invocation.agent_run_id = "missing-run"
        invocation.agent_request_id = "missing-request"
        invocation.agent_slug = "missing-agent"
    with pytest.raises(ConnectorAuthorizationError):
        await service.get_user_invocation(prepared["invocation_id"], actor="actor")


async def test_unrelated_public_target_cannot_hide_actual_dynamic_record(service_scope):
    """无关标签公开也不能让真实路径目标被隐藏后获得批准。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/records/{{record_id}}",
            request_schema={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string"},
                    "label": {"type": "string", "x-approval-visible": True, "x-approval-target": True},
                },
            },
            approval_policy="required",
        )
    with pytest.raises(ConnectorApprovalRequired) as waiting:
        await service.prepare_invocation(
            "service-test", "write", {"record_id": "real-private-target", "label": "decoy"}, execution=execution()
        )
    with pytest.raises(ConnectorServiceError):
        await service.decide_invocation(
            waiting.value.invocation_id, "approve", actor="actor", expected_digest=waiting.value.digest
        )


async def test_approval_summary_distinguishes_frozen_targets_and_changes_without_private_values(service_scope):
    """同字段的两个写请求必须显示不同冻结目标和变更，私人字段仍隐藏。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/records/{{record_id}}",
            request_schema={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "x-approval-visible": True, "x-approval-target": True},
                    "value": {"type": "string", "x-approval-visible": True},
                    "private_note": {"type": "string"},
                },
            },
            approval_policy="required",
        )
    summaries = []
    for index in ("A", "B"):
        with pytest.raises(ConnectorApprovalRequired) as waiting:
            await service.prepare_invocation(
                "service-test",
                "write",
                {
                    "record_id": "record-" + index,
                    "value": "change-" + index,
                    "private_note": "synthetic-sensitive-note",
                },
                execution=execution("approval-" + index),
            )
        async with manager.get_async_session_context() as db:
            invocation = await ConnectorExecutionRepository(db).get_invocation(waiting.value.invocation_id)
            summary = invocation.request_summary
            assert "record-" + index in str(summary) and "change-" + index in str(summary)
            assert "synthetic-sensitive-note" not in str(summary)
            summaries.append(summary)
    assert summaries[0] != summaries[1]


async def test_payload_purge_visits_all_shrinking_batches_and_retains_tombstones(service_scope):
    """执行分页清理五行不跳批，unknown 不删除，去重身份保留。"""
    from scripts.purge_connector_payloads import purge_payloads
    from yuxi.utils.datetime_utils import utc_now

    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        operation = await ConnectorRepository(db).get_operation(connector.id, "read")
        for index in range(6):
            row = await ConnectorExecutionRepository(db).create_invocation(
                connector_id=connector.id,
                operation_id=operation.id,
                connector_slug=connector.slug,
                operation_slug="read",
                operation_type="read",
                actor_uid="actor",
                consumer_type="admin_test",
                logical_call_key="purge-" + str(index),
                connector_revision=connector.revision,
                operation_revision=operation.revision,
                params_ciphertext=b"synthetic-payload",
            )
            row.status = "succeeded" if index < 5 else "unknown"
            row.completed_at = utc_now() - timedelta(days=91)
    async with manager.get_async_session_context() as db:
        assert await purge_payloads(db, dry_run=True, batch_size=2, older_than=timedelta(days=90)) == 5
    async with manager.get_async_session_context() as db:
        assert await purge_payloads(db, dry_run=False, batch_size=2, older_than=timedelta(days=90)) == 5
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs")) == 6
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM connector_usage_logs "
                    "WHERE params_ciphertext IS NOT NULL AND status='succeeded'"
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM connector_usage_logs WHERE params_ciphertext IS NOT NULL AND status='unknown'"
                )
            )
            == 1
        )


async def test_read_retries_share_one_total_operation_deadline(service_scope, http_provider):
    """慢响应不会为后续 attempt 重置预算，超时关闭账本并停止发送。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
            "timeout_seconds": 1,
        }
    await service.create_connector_operation(
        "service-test",
        {
            "slug": "retry",
            "name": "retry",
            "operation_type": "read",
            "http_method": "GET",
            "endpoint_template": "/slow-retry",
            "retry_policy": {"max_attempts": 3},
        },
        actor="actor",
    )
    identity = execution()
    prepared = await service.prepare_invocation("service-test", "retry", {}, execution=identity)
    started = time.monotonic()
    result = await service.execute_invocation(prepared["invocation_id"], execution=identity)
    assert time.monotonic() - started < 1.8
    assert not result.success and result.error_code == "timeout" and len(requests) == 2
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT status FROM connector_usage_logs")) == "failed"
        assert (
            await db.scalar(text("SELECT count(*) FROM connector_operation_attempts WHERE completed_at IS NULL")) == 0
        )


@pytest.mark.parametrize("path,success", [("/retry", True), ("/budget", False)])
async def test_read_retry_budget_has_one_durable_attempt_per_actual_request(
    service_scope, http_provider, path, success
):
    """瞬时读错误最多三次，每次发送前的 attempt 已提交，耗尽不继续。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
        }
    await service.create_connector_operation(
        "service-test",
        {
            "slug": "retry",
            "name": "retry",
            "operation_type": "read",
            "http_method": "GET",
            "endpoint_template": path,
            "retry_policy": {"max_attempts": 3},
        },
        actor="actor",
    )
    result = await service.prepare_and_execute("service-test", "retry", {}, execution=execution())
    assert result["success"] is success and requests == [path] * 3
    async with manager.get_async_session_context() as db:
        attempts = (
            await db.execute(
                text(
                    "SELECT attempt_no, completed_at, response_status "
                    "FROM connector_operation_attempts ORDER BY attempt_no"
                )
            )
        ).all()
        assert [row[0] for row in attempts] == [1, 2, 3]
        assert all(row[1] is not None for row in attempts)
        assert [row[2] for row in attempts] == ([503, 503, 200] if success else [503, 503, 503])


async def test_remote_idempotency_uses_frozen_invocation_identity_without_automatic_write_retry(
    service_scope, http_provider
):
    """显式远端幂等头绑定持久 invocation，相同逻辑调用只发送一次写。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
        }
        connector.write_scope = {"access_level": "global"}
    await service.create_connector_operation(
        "service-test",
        {
            "slug": "write",
            "name": "write",
            "operation_type": "write",
            "http_method": "POST",
            "endpoint_template": "/idempotent",
            "approval_policy": "preauthorized",
            "remote_idempotency": {"header_name": "Idempotency-Key"},
        },
        actor="actor",
    )
    first = await service.prepare_and_execute("service-test", "write", {}, execution=execution("stable-write"))
    replay = await service.prepare_and_execute("service-test", "write", {}, execution=execution("stable-write"))
    assert first["success"] and replay["success"]
    assert first["data"]["idempotency_key"] == first["invocation_id"] == replay["invocation_id"]
    assert requests == ["/idempotent"]


async def test_read_retry_rechecks_current_scope_before_second_send(service_scope, http_provider, monkeypatch):
    """首次响应后撤销权限，已提交 attempt 保留，第二次 HTTP 必须被拒绝。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
        }
    await service.create_connector_operation(
        "service-test",
        {
            "slug": "retry",
            "name": "retry",
            "operation_type": "read",
            "http_method": "GET",
            "endpoint_template": "/budget",
            "retry_policy": {"max_attempts": 3},
        },
        actor="actor",
    )
    send = service._do_http_execution

    async def revoke_after_response(*args):
        """独立真实响应回来后修改当前执行范围。"""
        response = await send(*args)
        async with manager.get_async_session_context() as db:
            connector = await ConnectorRepository(db).get_by_slug("service-test")
            connector.read_scope = {"access_level": "deny"}
        return response

    monkeypatch.setattr(service, "_do_http_execution", revoke_after_response)
    result = await service.prepare_and_execute("service-test", "retry", {}, execution=execution())
    assert not result["success"] and requests == ["/budget"]
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM connector_operation_attempts")) == 1
        assert await db.scalar(text("SELECT response_status FROM connector_operation_attempts")) == 503


async def test_rejected_write_returns_controlled_result_without_http(service_scope, http_provider):
    """审批拒绝是受控工具结果，恢复不崩溃也不发送第三方写入。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
        }
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/write",
            approval_policy="required",
        )
    identity = execution("rejected-write")
    with pytest.raises(ConnectorApprovalRequired) as waiting:
        await service.prepare_and_execute("service-test", "write", {}, execution=identity)
    await service.decide_invocation(
        waiting.value.invocation_id, "reject", actor="actor", expected_digest=waiting.value.digest
    )
    result = await service.prepare_and_execute("service-test", "write", {}, execution=identity)
    assert result["error_code"] == "approval_rejected" and result["success"] is False
    assert result["invocation_id"] == waiting.value.invocation_id and result["remote_outcome"] == "not_sent"
    assert requests == []
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs")) == 1
        assert await db.scalar(text("SELECT count(*) FROM connector_operation_attempts")) == 0


@pytest.mark.parametrize("conflicting_params", [False, True])
async def test_same_key_concurrent_prepare_returns_same_invocation(service_scope, monkeypatch, conflicting_params):
    """两个首次准备同时读空账本，数据库唯一性仍返回同一调用。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        operation = await repo.get_operation(connector.id, "read")
        await repo.patch_operation(
            operation,
            {
                "request_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "additionalProperties": False,
                },
            },
        )
    original = ConnectorExecutionRepository.get_by_logical_call_key
    arrived, gate = 0, asyncio.Event()

    async def barrier(self, key):
        """确保两个事务首次查重都在插入前返回。"""
        nonlocal arrived
        value = await original(self, key)
        arrived += 1
        if arrived == 2:
            gate.set()
        await asyncio.wait_for(gate.wait(), 5)
        return value

    monkeypatch.setattr(ConnectorExecutionRepository, "get_by_logical_call_key", barrier)
    results = await asyncio.gather(
        *(
            service.prepare_invocation(
                "service-test",
                "read",
                {"value": index if conflicting_params else 0},
                execution=execution("review-same-key"),
            )
            for index in range(2)
        ),
        return_exceptions=True,
    )
    print("SAME_KEY_TYPES=" + ",".join(type(result).__name__ for result in results))
    async with manager.get_async_session_context() as db:
        count = await db.scalar(text("SELECT count(*) FROM connector_usage_logs"))
    print("SAME_KEY_ROWS=" + str(count))
    assert count == 1
    if conflicting_params:
        assert sum(isinstance(result, dict) for result in results) == 1
        assert sum(isinstance(result, ConnectorConflictError) for result in results) == 1
        return
    assert all(isinstance(result, dict) for result in results), (
        "same key/digest must return same durable invocation to both callers"
    )
    assert results[0]["invocation_id"] == results[1]["invocation_id"]


async def test_stale_agent_tool_revision_is_rejected(service_scope):
    """已装配工具的版本变化不能静默刷新成新的请求。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        db.add(
            AgentRun(
                id="review-run",
                request_id="review-request",
                uid="actor",
                agent_slug="review-agent",
                conversation_thread_id="review-thread",
                runtime_scope_id="review-thread",
                status="running",
                input_payload={},
            )
        )
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        operation = await ConnectorRepository(db).get_operation(connector.id, "read")
        old_connector_revision, old_operation_revision = connector.revision, operation.revision
    identity = await service.resolve_agent_execution(
        actor_uid="actor",
        current_run_id="review-run",
        request_id="review-request",
        tool_call_id="review-call",
        connector_revision=old_connector_revision,
        operation_revision=old_operation_revision,
    )
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        operation = await ConnectorRepository(db).get_operation(connector.id, "read")
        await ConnectorRepository(db).patch_operation(operation, {"endpoint_template": "/different-read"})
    try:
        result = await service.prepare_invocation("service-test", "read", {}, execution=identity)
    except ConnectorConflictError:
        return
    async with manager.get_async_session_context() as db:
        row = await ConnectorExecutionRepository(db).get_invocation(result["invocation_id"])
        frozen = json.loads(service._get_vault().decrypt(row.execution_snapshot_ciphertext, row.key_id))
    print("STALE_TOOL_PREPARED_NEW_PATH=" + frozen["operation"]["endpoint_template"])
    assert False, "stale Agent tool revision was silently refreshed during prepare"


async def test_reconciled_unknown_workflow_resumes_same_activation(service_scope, vault_configuration, http_provider):
    """已发送写入未知时持久等待，核对后复用结果及原激活且不重发。"""
    service, manager = service_scope
    base, host, requests = http_provider
    definition = {
        "steps": [
            {
                "id": "write",
                "type": "connector",
                "connector_slug": "service-test",
                "operation_slug": "write",
                "params": {},
                "output_key": "record",
            },
            {"id": "end", "type": "end", "depends_on": ["write"], "template": "{record}"},
        ]
    }
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "auth_type": "none",
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
            "timeout_seconds": 1,
        }
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/write",
            approval_policy="preauthorized",
        )
        workflow = Workflow(slug="review-workflow", name="review workflow", definition=definition, created_by="actor")
        db.add(workflow)
        await db.flush()
        run = WorkflowRun(
            workflow_id=workflow.id,
            created_by="actor",
            status="pending",
            definition_snapshot=definition,
            dispatch_pending=True,
        )
        db.add(run)
        await db.flush()
        run_id = run.id
    override_factory(
        ConnectorServiceFactory(
            session_context_factory=manager.get_async_session_context,
            vault_provider=lambda: vault_configuration["current"],
        )
    )
    try:
        await execute_workflow_run(
            run_id,
            session_factory=manager.get_async_session_context,
            owner_id="review-worker",
            event_publisher=AsyncMock(),
        )
        async with manager.get_async_session_context() as db:
            invocation = await db.scalar(select(ConnectorUsageLog).where(ConnectorUsageLog.workflow_run_id == run_id))
            print("AFTER_TIMEOUT=" + (await db.get(WorkflowRun, run_id)).status + "/" + invocation.status)
            assert invocation.status == "unknown"
            assert (await db.get(WorkflowRun, run_id)).status == "waiting_approval"
            assert invocation.execution_snapshot_ciphertext is None
            original_activation = invocation.step_execution_id
            invocation_id = invocation.id
            await WorkflowRepository(db).prepare_agent_resumes(run_id)
            assert (await db.get(WorkflowRun, run_id)).status == "waiting_approval"
        await service.reconcile_invocation(
            invocation_id,
            "succeeded",
            actor="actor",
            reason="independent provider request ledger checked",
            result={"ok": True},
        )
        with patch("yuxi.services.workflow_service.get_arq_pool", new=AsyncMock()):
            ready = await request_workflow_resume(run_id, session_factory=manager.get_async_session_context)
        async with manager.get_async_session_context() as db:
            run = await db.get(WorkflowRun, run_id)
            invocation = await db.get(ConnectorUsageLog, invocation_id)
            print(
                "AFTER_RECONCILE="
                + run.status
                + "/"
                + invocation.status
                + "/ready="
                + str(ready)
                + "/requests="
                + str(len(requests))
            )
            assert run.status in ("pending", "completed"), "reconciled result cannot resume original activation"
            generation = run.resume_generation
        await execute_workflow_run(
            run_id,
            session_factory=manager.get_async_session_context,
            owner_id="resumed-worker",
            event_publisher=AsyncMock(),
            generation=generation,
        )
        async with manager.get_async_session_context() as db:
            run = await db.get(WorkflowRun, run_id)
            step = await db.scalar(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.workflow_run_id == run_id, WorkflowStepRun.step_id == "write"
                )
            )
            assert run.status == "completed"
            assert step.step_execution_id == original_activation
            assert step.output_payload["result"] == {"ok": True}
            assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs")) == 1
        assert len(requests) == 1
    finally:
        override_factory(None)


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "unknown", "rejected", "cancelled"])
async def test_finished_dispatch_removes_credential_snapshot(service_scope, outcome):
    """已不允许重新发送的调用只保留去重及核对材料，不保留 dispatch 秘密。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        secret = service._get_vault().encrypt(b"synthetic-retired-credential")
        await ConnectorRepository(db).upsert_credential(connector.id, "token", secret.ciphertext, secret.key_id)
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        repo = ConnectorExecutionRepository(db)
        invocation = await repo.get_invocation(prepared["invocation_id"])
        assert invocation.execution_snapshot_ciphertext is not None
        if outcome == "rejected":
            invocation.status = "awaiting_approval"
            await repo.reject_invocation(invocation, rejected_by="actor")
        elif outcome == "cancelled":
            await repo.cancel_invocation(invocation)
        else:
            assert await repo.claim_invocation(invocation, owner_id="test-owner", owner_attempt="test-attempt")
            await repo.finalize_invocation(invocation, owner_attempt="test-attempt", status=outcome)
    async with manager.get_async_session_context() as db:
        invocation = await ConnectorExecutionRepository(db).get_invocation(prepared["invocation_id"])
        assert invocation.status == outcome
        assert invocation.execution_snapshot_ciphertext is None
        assert invocation.params_ciphertext is not None and invocation.request_digest


async def test_feishu_http_error_never_becomes_success(monkeypatch):
    """成功 business code 不能掩盖 HTTP 层失败。"""
    from types import SimpleNamespace
    from yuxi.services.connectors.adapters.feishu_bitable_crm import FeishuBitableCRMAdapter
    from yuxi.services.connectors.http_client import ConnectorHTTPConfig, ConnectorHTTPError

    adapter = FeishuBitableCRMAdapter()
    config = ConnectorHTTPConfig.from_dict({"base_url": "https://open.feishu.cn"})
    response = SimpleNamespace(
        status_code=500,
        body=b'{"code":0,"data":{"record":{"record_id":"synthetic-record"}}}',
        provider_request_id="synthetic-receipt",
    )
    monkeypatch.setattr(
        "yuxi.services.connectors.adapters.feishu_bitable_crm.execute_http_request", AsyncMock(return_value=response)
    )
    try:
        result = await adapter._bitable_request(
            "GET", "/v1/apps/synthetic/tables/synthetic/records/synthetic-record", config, "synthetic-token"
        )
    except ConnectorHTTPError:
        return
    print("FEISHU_ACCEPTED_HTTP_STATUS=" + str(result[2]))
    assert False, "HTTP 500 must not be accepted on business code 0"
