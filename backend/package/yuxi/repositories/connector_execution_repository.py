"""连接器调用/审批/attempt 状态、唯一性、CAS/行锁、lease 与恢复查询。"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    ConnectorOperationAttempt,
    ConnectorUsageLog,
)
from yuxi.utils.datetime_utils import utc_now_naive


class ConnectorExecutionRepository:
    """调用账本、审批状态和 attempt 记录的数据访问。

    所有写操作均通过调用方管理事务边界；本类只 flush，不 commit。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 调用账本 ──

    async def get_invocation(self, invocation_id: str) -> ConnectorUsageLog | None:
        return await self.db.get(ConnectorUsageLog, invocation_id)

    async def get_by_logical_call_key(self, logical_call_key: str) -> ConnectorUsageLog | None:
        result = await self.db.execute(
            select(ConnectorUsageLog).where(
                ConnectorUsageLog.logical_call_key == logical_call_key
            )
        )
        return result.scalar_one_or_none()

    async def create_invocation(
        self,
        *,
        connector_id: int,
        operation_id: int | None,
        connector_slug: str,
        operation_slug: str,
        operation_type: str,
        actor_uid: str,
        consumer_type: str,
        logical_call_key: str,
        connector_revision: int,
        operation_revision: int,
        request_digest: str | None = None,
        approval_policy: str | None = None,
        params_ciphertext: bytes | None = None,
        execution_snapshot_ciphertext: bytes | None = None,
        key_id: str | None = None,
        request_summary: dict | None = None,
        agent_slug: str | None = None,
        agent_request_id: str | None = None,
        agent_run_id: str | None = None,
        workflow_id: int | None = None,
        workflow_run_id: int | None = None,
        step_id: str | None = None,
        step_execution_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> ConnectorUsageLog:
        invocation = ConnectorUsageLog(
            id=str(uuid.uuid4()),
            connector_id=connector_id,
            operation_id=operation_id,
            connector_slug=connector_slug,
            operation_slug=operation_slug,
            operation_type=operation_type,
            actor_uid=actor_uid,
            consumer_type=consumer_type,
            logical_call_key=logical_call_key,
            request_digest=request_digest,
            connector_revision=connector_revision,
            operation_revision=operation_revision,
            status="awaiting_approval" if approval_policy == "required" else "prepared",
            approval_policy=approval_policy,
            params_ciphertext=params_ciphertext,
            execution_snapshot_ciphertext=execution_snapshot_ciphertext,
            key_id=key_id,
            request_summary=request_summary,
            agent_slug=agent_slug,
            agent_request_id=agent_request_id,
            agent_run_id=agent_run_id,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            step_id=step_id,
            step_execution_id=step_execution_id,
            tool_call_id=tool_call_id,
        )
        self.db.add(invocation)
        await self.db.flush()
        return invocation

    async def approve_invocation(
        self,
        invocation: ConnectorUsageLog,
        *,
        approved_by: str,
        approval_digest: str,
        expires_at: Any,
    ) -> ConnectorUsageLog:
        if invocation.status != "awaiting_approval":
            raise ValueError(f"只有 awaiting_approval 状态可审批，当前: {invocation.status}")
        invocation.status = "prepared"
        invocation.approved_by = approved_by
        invocation.approved_at = utc_now_naive()
        invocation.approval_expires_at = expires_at
        invocation.approval_digest = approval_digest
        await self.db.flush()
        return invocation

    async def reject_invocation(
        self,
        invocation: ConnectorUsageLog,
        *,
        rejected_by: str,
        reason: str | None = None,
    ) -> ConnectorUsageLog:
        if invocation.status != "awaiting_approval":
            raise ValueError(f"只有 awaiting_approval 状态可拒绝，当前: {invocation.status}")
        invocation.status = "rejected"
        invocation.rejected_by = rejected_by
        invocation.rejection_reason = reason
        invocation.completed_at = utc_now_naive()
        await self.db.flush()
        return invocation

    async def cancel_invocation(self, invocation: ConnectorUsageLog) -> ConnectorUsageLog:
        if invocation.status in ("succeeded", "failed", "cancelled", "rejected"):
            raise ValueError(f"终态不可取消: {invocation.status}")
        invocation.status = "cancelled"
        invocation.completed_at = utc_now_naive()
        await self.db.flush()
        return invocation

    async def claim_invocation(
        self,
        invocation: ConnectorUsageLog,
        *,
        owner_id: str,
        owner_attempt: str,
        lease_seconds: int = 120,
    ) -> bool:
        """CAS claim：只有 prepared 状态且无其他 owner 时成功。返回是否成功。"""
        now = utc_now_naive()
        lease_expires = now + timedelta(seconds=lease_seconds)
        result = await self.db.execute(
            update(ConnectorUsageLog)
            .where(
                ConnectorUsageLog.id == invocation.id,
                ConnectorUsageLog.status == "prepared",
                ConnectorUsageLog.owner_id.is_(None),
            )
            .values(
                status="running",
                owner_id=owner_id,
                owner_attempt=owner_attempt,
                lease_expires_at=lease_expires,
                heartbeat_at=now,
                started_at=now,
            )
        )
        await self.db.flush()
        if result.rowcount == 1:
            invocation.status = "running"
            invocation.owner_id = owner_id
            invocation.owner_attempt = owner_attempt
            invocation.lease_expires_at = lease_expires
            invocation.heartbeat_at = now
            invocation.started_at = now
            return True
        return False

    async def finalize_invocation(
        self,
        invocation: ConnectorUsageLog,
        *,
        owner_attempt: str,
        status: str,
        remote_outcome: str | None = None,
        result_ciphertext: bytes | None = None,
        response_summary: dict | None = None,
        response_status: int | None = None,
        provider_request_id: str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
        duration_ms: int | None = None,
    ) -> ConnectorUsageLog:
        """按 owner_attempt CAS 保存终态。"""
        now = utc_now_naive()
        result = await self.db.execute(
            update(ConnectorUsageLog)
            .where(
                ConnectorUsageLog.id == invocation.id,
                ConnectorUsageLog.owner_attempt == owner_attempt,
            )
            .values(
                status=status,
                remote_outcome=remote_outcome,
                result_ciphertext=result_ciphertext,
                response_summary=response_summary,
                response_status=response_status,
                provider_request_id=provider_request_id,
                error_code=error_code,
                error_summary=error_summary,
                duration_ms=duration_ms,
                completed_at=now,
                owner_id=None,
                lease_expires_at=None,
            )
        )
        await self.db.flush()
        if result.rowcount == 1:
            invocation.status = status
            invocation.remote_outcome = remote_outcome
            invocation.result_ciphertext = result_ciphertext
            invocation.response_summary = response_summary
            invocation.response_status = response_status
            invocation.provider_request_id = provider_request_id
            invocation.error_code = error_code
            invocation.error_summary = error_summary
            invocation.duration_ms = duration_ms
            invocation.completed_at = now
            invocation.owner_id = None
            invocation.lease_expires_at = None
        return invocation

    async def mark_unknown(
        self,
        invocation: ConnectorUsageLog,
        *,
        owner_attempt: str,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> ConnectorUsageLog:
        return await self.finalize_invocation(
            invocation,
            owner_attempt=owner_attempt,
            status="unknown",
            remote_outcome="unknown",
            error_code=error_code,
            error_summary=error_summary,
        )

    async def heartbeat(self, invocation_id: str, *, owner_attempt: str) -> None:
        now = utc_now_naive()
        await self.db.execute(
            update(ConnectorUsageLog)
            .where(
                ConnectorUsageLog.id == invocation_id,
                ConnectorUsageLog.owner_attempt == owner_attempt,
            )
            .values(heartbeat_at=now)
        )
        await self.db.flush()

    # ── 恢复查询 ──

    async def find_stale_leases(self, now: Any) -> list[ConnectorUsageLog]:
        """查找 lease 过期但仍在 running 的调用，供恢复 worker 处理。"""
        result = await self.db.execute(
            select(ConnectorUsageLog).where(
                ConnectorUsageLog.status == "running",
                ConnectorUsageLog.lease_expires_at < now,
            )
        )
        return list(result.scalars().all())

    # ── Attempt 记录 ──

    async def create_attempt(
        self,
        invocation_id: str,
        attempt_no: int,
        *,
        owner_attempt: str | None = None,
    ) -> ConnectorOperationAttempt:
        attempt = ConnectorOperationAttempt(
            invocation_id=invocation_id,
            attempt_no=attempt_no,
            owner_attempt=owner_attempt,
        )
        self.db.add(attempt)
        await self.db.flush()
        return attempt

    async def finalize_attempt(
        self,
        attempt: ConnectorOperationAttempt,
        *,
        send_state: str,
        response_status: int | None = None,
        provider_request_id: str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
        duration_ms: int | None = None,
    ) -> ConnectorOperationAttempt:
        now = utc_now_naive()
        attempt.send_state = send_state
        attempt.response_status = response_status
        attempt.provider_request_id = provider_request_id
        attempt.error_code = error_code
        attempt.error_summary = error_summary
        attempt.duration_ms = duration_ms
        attempt.completed_at = now
        await self.db.flush()
        return attempt

    async def list_attempts(self, invocation_id: str) -> list[ConnectorOperationAttempt]:
        result = await self.db.execute(
            select(ConnectorOperationAttempt)
            .where(ConnectorOperationAttempt.invocation_id == invocation_id)
            .order_by(ConnectorOperationAttempt.attempt_no)
        )
        return list(result.scalars().all())

    async def get_running_count_for_connector(self, connector_id: int) -> int:
        """当前 connector 的 running 调用数（用于全局并发限制）。"""
        result = await self.db.execute(
            select(func.count(ConnectorUsageLog.id)).where(
                ConnectorUsageLog.connector_id == connector_id,
                ConnectorUsageLog.status == "running",
            )
        )
        return int(result.scalar() or 0)

    async def list_usage(
        self,
        *,
        connector_id: int | None = None,
        status: str | None = None,
        actor_uid: str | None = None,
        workflow_run_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ConnectorUsageLog], int]:
        """分页查询调用记录，供管理端 usage 接口使用。"""
        conditions = []
        if connector_id is not None:
            conditions.append(ConnectorUsageLog.connector_id == connector_id)
        if status is not None:
            conditions.append(ConnectorUsageLog.status == status)
        if actor_uid is not None:
            conditions.append(ConnectorUsageLog.actor_uid == actor_uid)
        if workflow_run_id is not None:
            conditions.append(ConnectorUsageLog.workflow_run_id == workflow_run_id)

        base_stmt = select(ConnectorUsageLog)
        count_stmt = select(func.count(ConnectorUsageLog.id))
        if conditions:
            base_stmt = base_stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        total_result = await self.db.execute(count_stmt)
        total = int(total_result.scalar() or 0)

        result = await self.db.execute(
            base_stmt.order_by(ConnectorUsageLog.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), total
