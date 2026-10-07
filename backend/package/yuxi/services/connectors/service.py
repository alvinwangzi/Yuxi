"""连接器共用调用服务 — prepare/execute/decide/reconcile 全生命周期。

服务不持有 AsyncSession；每次操作通过 session_context_factory 获取短事务。
事务成功退出后才会发起 HTTP 或 interrupt；失败路径在 rollback 后用新事务保存结局。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.services.connectors.base import (
    BaseConnectorAdapter,
    ConnectorExecution,
    ConnectorResult,
    FrozenOperation,
)
from yuxi.services.connectors.credential_vault import CredentialVault, CredentialVaultError, ensure_vault_available
from yuxi.services.connectors.http_client import ConnectorHTTPConfig
from yuxi.services.connectors.registry import get_adapter_class
from yuxi.services.connectors.schemas import (
    validate_params,
    resolve_template,
    resolve_body_template,
    apply_response_mapping,
    validate_static_headers,
    validate_concurrency_limit,
)
from yuxi.utils import logger

SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

DEFAULT_APPROVAL_TTL_SECONDS = 1800
DEFAULT_LEASE_SECONDS = 120


class ConnectorServiceError(Exception):
    """连接器服务业务错误。"""

    def __init__(self, message: str, *, code: str = "connector_error"):
        super().__init__(message)
        self.code = code


class ConnectorAuthorizationError(ConnectorServiceError):
    def __init__(self, message: str = "无权执行此操作"):
        super().__init__(message, code="authorization_error")


class ConnectorConflictError(ConnectorServiceError):
    def __init__(self, message: str):
        super().__init__(message, code="conflict")


class ConnectorApprovalRequired(ConnectorServiceError):
    """写操作需要审批；携带 invocation_id 供 interrupt 使用。"""

    def __init__(self, invocation_id: str, digest: str, expires_at: Any):
        super().__init__("写操作需要审批", code="approval_required")
        self.invocation_id = invocation_id
        self.digest = digest
        self.expires_at = expires_at


class ConnectorService:
    """连接器调用全生命周期管理。

    管理方法和执行入口均使用 session_context_factory 获取短事务。
    """

    def __init__(
        self,
        *,
        session_context_factory: SessionContextFactory,
        vault_provider: Callable[[], CredentialVault | None],
        http_client_provider: Callable[[], Any] | None = None,
    ):
        self._session_context_factory = session_context_factory
        self._vault_provider = vault_provider
        self._http_client_provider = http_client_provider

    def _get_vault(self) -> CredentialVault:
        return ensure_vault_available(self._vault_provider())

    def _get_adapter(self, connector_type: str) -> BaseConnectorAdapter:
        adapter_class = get_adapter_class(connector_type)
        return adapter_class()

    async def prepare_invocation(
        self,
        connector_slug: str,
        operation_slug: str,
        params: dict[str, Any],
        *,
        execution: ConnectorExecution,
    ) -> dict[str, Any]:
        """校验、授权、去重、冻结参数，创建调用记录。

        返回调用元数据；写操作若需审批则抛出 ConnectorApprovalRequired。
        """
        vault = self._get_vault()

        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_repository import ConnectorRepository
            from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

            repo = ConnectorRepository(db)
            exec_repo = ConnectorExecutionRepository(db)

            connector = await repo.get_by_slug_for_execution(connector_slug)
            if connector is None:
                raise ConnectorServiceError("连接器不存在", code="not_found")
            if not connector.enabled:
                raise ConnectorServiceError("连接器已停用", code="connector_disabled")

            operation = await repo.get_operation(connector.id, operation_slug)
            if operation is None or not operation.enabled:
                raise ConnectorServiceError("操作不存在或已停用", code="operation_not_found")

            validated_params = validate_params(params, operation.request_schema)
            digest = _compute_digest(validated_params, connector.revision, operation.revision, execution)

            existing = await exec_repo.get_by_logical_call_key(execution.logical_call_key)
            if existing is not None:
                if existing.request_digest == digest:
                    return _invocation_summary(existing)
                raise ConnectorConflictError(
                    f"logical_call_key 已存在但 digest 不匹配: {execution.logical_call_key}"
                )

            running_count = await exec_repo.get_running_count_for_connector(connector.id)
            concurrency_limit = validate_concurrency_limit(
                (connector.config or {}).get("concurrency_limit")
            )
            if running_count >= concurrency_limit:
                raise ConnectorServiceError("连接器并发数已达上限", code="capacity_exceeded")

            params_json = json.dumps(validated_params, ensure_ascii=False, default=str).encode("utf-8")
            params_encrypted = vault.encrypt(params_json)

            snapshot = {
                "connector_slug": connector.slug,
                "connector_revision": connector.revision,
                "operation_slug": operation.slug,
                "operation_revision": operation.revision,
                "params": validated_params,
            }
            snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str).encode("utf-8")
            snapshot_encrypted = vault.encrypt(snapshot_json)

            approval_policy = operation.approval_policy if operation.operation_type == "write" else None

            invocation = await exec_repo.create_invocation(
                connector_id=connector.id,
                operation_id=operation.id,
                connector_slug=connector.slug,
                operation_slug=operation.slug,
                operation_type=operation.operation_type,
                actor_uid=execution.actor_uid,
                consumer_type=execution.consumer_type,
                logical_call_key=execution.logical_call_key,
                connector_revision=connector.revision,
                operation_revision=operation.revision,
                request_digest=digest,
                approval_policy=approval_policy,
                params_ciphertext=params_encrypted.ciphertext,
                execution_snapshot_ciphertext=snapshot_encrypted.ciphertext,
                key_id=params_encrypted.key_id,
                request_summary=_build_request_summary(connector, operation, validated_params),
                agent_slug=execution.agent_slug,
                agent_request_id=execution.agent_request_id,
                agent_run_id=execution.agent_run_id,
                workflow_id=execution.workflow_id,
                workflow_run_id=execution.workflow_run_id,
                step_id=execution.step_id,
                step_execution_id=execution.step_execution_id,
                tool_call_id=execution.tool_call_id,
            )

            if approval_policy == "required":
                raise ConnectorApprovalRequired(
                    invocation_id=invocation.id,
                    digest=digest,
                    expires_at=None,
                )

            return _invocation_summary(invocation)

    async def execute_invocation(
        self,
        invocation_id: str,
        *,
        execution: ConnectorExecution,
    ) -> ConnectorResult:
        """claim → 解密快照 → HTTP 执行 → 保存结果。

        每个阶段使用独立短事务；HTTP 期间不持有 DB session。
        """
        vault = self._get_vault()
        owner_attempt = str(uuid.uuid4())

        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
            exec_repo = ConnectorExecutionRepository(db)

            invocation = await exec_repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("调用不存在", code="not_found")
            if invocation.status not in ("prepared",):
                raise ConnectorServiceError(
                    f"调用状态不允许执行: {invocation.status}", code="invalid_state"
                )

            claimed = await exec_repo.claim_invocation(
                invocation, owner_id=execution.actor_uid, owner_attempt=owner_attempt,
            )
            if not claimed:
                raise ConnectorServiceError("调用已被其他执行者领取", code="claim_failed")

            snapshot_json = vault.decrypt(invocation.execution_snapshot_ciphertext, invocation.key_id)
            snapshot = json.loads(snapshot_json)

            attempt = await exec_repo.create_attempt(
                invocation_id, attempt_no=1, owner_attempt=owner_attempt,
            )

        try:
            result = await self._do_http_execution(snapshot, execution)

            async with self._session_context_factory() as db:
                from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
                exec_repo = ConnectorExecutionRepository(db)

                invocation = await exec_repo.get_invocation(invocation_id)
                await exec_repo.finalize_attempt(
                    attempt,
                    send_state="response_received",
                    response_status=result.response_status,
                    provider_request_id=result.provider_request_id,
                    error_code=result.error_code,
                    duration_ms=int(result.duration_ms),
                )

                status = "succeeded" if result.success else "failed"
                remote_outcome = result.remote_outcome

                result_data = None
                if result.mapped_result:
                    result_json = json.dumps(result.mapped_result, ensure_ascii=False, default=str).encode("utf-8")
                    result_encrypted = vault.encrypt(result_json)
                    result_data = result_encrypted.ciphertext

                await exec_repo.finalize_invocation(
                    invocation,
                    owner_attempt=owner_attempt,
                    status=status,
                    remote_outcome=remote_outcome,
                    result_ciphertext=result_data,
                    response_summary=_build_response_summary(result),
                    response_status=result.response_status,
                    provider_request_id=result.provider_request_id,
                    error_code=result.error_code,
                    error_summary=result.error_message,
                    duration_ms=int(result.duration_ms),
                )

            return result

        except Exception as exc:
            logger.warning(f"连接器执行失败 invocation_id={invocation_id}: {exc}")

            async with self._session_context_factory() as db:
                from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
                exec_repo = ConnectorExecutionRepository(db)

                invocation = await exec_repo.get_invocation(invocation_id)
                if invocation and invocation.status == "running":
                    await exec_repo.mark_unknown(
                        invocation,
                        owner_attempt=owner_attempt,
                        error_code="execution_error",
                        error_summary=str(exc)[:500],
                    )

            return ConnectorResult(
                success=False,
                error_code="execution_error",
                error_message=str(exc)[:500],
                remote_outcome="unknown",
            )

    async def _do_http_execution(
        self,
        snapshot: dict,
        execution: ConnectorExecution,
    ) -> ConnectorResult:
        """解密凭据并执行 HTTP 调用。"""
        vault = self._get_vault()

        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_repository import ConnectorRepository
            repo = ConnectorRepository(db)
            connector = await repo.get_by_slug_for_execution(snapshot["connector_slug"])
            if connector is None:
                return ConnectorResult(success=False, error_code="connector_not_found")

            operation = await repo.get_operation(connector.id, snapshot["operation_slug"])
            if operation is None:
                return ConnectorResult(success=False, error_code="operation_not_found")

            credentials: dict[str, bytes] = {}
            for cred_row in (connector.credentials or []):
                try:
                    credentials[cred_row.credential_key] = vault.decrypt(
                        cred_row.credential_value, cred_row.key_id
                    )
                except CredentialVaultError:
                    return ConnectorResult(
                        success=False, error_code="credential_decryption_failed",
                    )

        http_config = ConnectorHTTPConfig.from_dict(connector.config or {})
        adapter = self._get_adapter(connector.connector_type)

        frozen_op = FrozenOperation(
            operation_id=operation.id,
            slug=operation.slug,
            name=operation.name,
            operation_type=operation.operation_type,
            http_method=operation.http_method,
            endpoint_template=operation.endpoint_template,
            query_template=operation.query_template,
            body_template=operation.body_template,
            request_schema=operation.request_schema,
            response_mapping=operation.response_mapping,
            response_type=operation.response_type,
            approval_policy=operation.approval_policy,
            retry_policy=operation.retry_policy,
            remote_idempotency=operation.remote_idempotency,
        )

        return await adapter.execute(
            http_config=http_config,
            credentials=credentials,
            operation=frozen_op,
            params=snapshot.get("params", {}),
            execution=execution,
        )

    async def decide_invocation(
        self,
        invocation_id: str,
        decision: str,
        *,
        actor: str,
        expected_digest: str | None = None,
    ) -> dict[str, Any]:
        """审批或拒绝调用。"""
        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
            exec_repo = ConnectorExecutionRepository(db)

            invocation = await exec_repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("调用不存在", code="not_found")

            if decision == "approve":
                if expected_digest and invocation.request_digest != expected_digest:
                    raise ConnectorConflictError("调用参数已变更，请重新审批")
                expires_at = invocation.approved_at + timedelta(seconds=DEFAULT_APPROVAL_TTL_SECONDS) if invocation.approved_at else None
                await exec_repo.approve_invocation(
                    invocation,
                    approved_by=actor,
                    approval_digest=invocation.request_digest or "",
                    expires_at=expires_at,
                )
                return _invocation_summary(invocation)

            if decision == "reject":
                await exec_repo.reject_invocation(invocation, rejected_by=actor)
                return _invocation_summary(invocation)

            raise ConnectorServiceError(f"不支持的审批决定: {decision}", code="invalid_decision")

    async def reconcile_invocation(
        self,
        invocation_id: str,
        resolution: str,
        *,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """人工核对 unknown 状态的调用。"""
        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
            exec_repo = ConnectorExecutionRepository(db)

            invocation = await exec_repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("调用不存在", code="not_found")
            if invocation.status != "unknown":
                raise ConnectorServiceError(
                    f"只有 unknown 状态可核对，当前: {invocation.status}", code="invalid_state"
                )

            if resolution not in ("succeeded", "failed"):
                raise ConnectorServiceError(f"不支持的核对结果: {resolution}", code="invalid_resolution")

            await exec_repo.finalize_invocation(
                invocation,
                owner_attempt=invocation.owner_attempt or "",
                status=resolution,
                remote_outcome=resolution,
                error_summary=reason[:500] if reason else None,
            )
            return _invocation_summary(invocation)

    async def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
            exec_repo = ConnectorExecutionRepository(db)
            invocation = await exec_repo.get_invocation(invocation_id)
            if invocation is None:
                return None
            return _invocation_summary(invocation)

    async def get_connector_metadata(
        self,
        connector_slug: str,
        *,
        uid: str | None = None,
        department_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """加载连接器元数据与用户可见操作（不解密凭据）。

        供 Agent tool builder 使用；返回 None 表示不存在或已停用。
        """
        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_repository import ConnectorRepository

            repo = ConnectorRepository(db)
            connector = await repo.get_by_slug(connector_slug)
            if connector is None or not connector.enabled:
                return None

            operations = await repo.list_usable_operations(
                connector, uid=uid or "", department_ids=department_ids,
            )

            return {
                "slug": connector.slug,
                "name": connector.name,
                "connector_type": connector.connector_type,
                "revision": connector.revision,
                "operations": [
                    {
                        "slug": op.slug,
                        "name": op.name,
                        "operation_type": op.operation_type,
                        "http_method": op.http_method,
                        "request_schema": op.request_schema,
                        "response_mapping": op.response_mapping,
                        "response_type": op.response_type,
                        "approval_policy": op.approval_policy,
                        "connector_revision": connector.revision,
                        "operation_revision": op.revision,
                    }
                    for op in operations
                ],
            }

    async def test_connector(self, connector_slug: str) -> dict[str, Any]:
        """管理端连接测试：解密凭据、加载 adapter、调用 probe。"""
        vault = self._get_vault()

        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_repository import ConnectorRepository
            repo = ConnectorRepository(db)
            connector = await repo.get_by_slug_for_execution(connector_slug)
            if connector is None:
                raise ConnectorServiceError("连接器不存在", code="not_found")
            if not connector.enabled:
                raise ConnectorServiceError("连接器已停用", code="connector_disabled")

            credentials: dict[str, bytes] = {}
            for cred_row in (connector.credentials or []):
                try:
                    credentials[cred_row.credential_key] = vault.decrypt(
                        cred_row.credential_value, cred_row.key_id
                    )
                except CredentialVaultError:
                    raise ConnectorServiceError("凭据解密失败", code="credential_decryption_failed")

        http_config = ConnectorHTTPConfig.from_dict(connector.config or {})
        adapter = self._get_adapter(connector.connector_type)

        try:
            probe_result = await adapter.probe(
                http_config=http_config,
                credentials=credentials,
            )
        except Exception as exc:
            probe_result = {"status": "error", "error": str(exc)[:500]}

        return {
            "connector_slug": connector_slug,
            "connector_type": connector.connector_type,
            "probe": probe_result,
        }

    async def prepare_and_execute(
        self,
        connector_slug: str,
        operation_slug: str,
        params: dict[str, Any],
        *,
        execution: ConnectorExecution,
    ) -> dict[str, Any]:
        """prepare → execute 一体化入口，供管理测试使用。"""
        prepare_result = await self.prepare_invocation(
            connector_slug, operation_slug, params, execution=execution,
        )
        if prepare_result.get("status") in ("awaiting_approval",):
            raise ConnectorApprovalRequired(
                invocation_id=prepare_result["invocation_id"],
                digest=prepare_result.get("request_digest", ""),
                expires_at=None,
            )

        result = await self.execute_invocation(
            prepare_result["invocation_id"], execution=execution,
        )
        return {
            "invocation_id": prepare_result["invocation_id"],
            "success": result.success,
            "data": result.data,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "remote_outcome": result.remote_outcome,
            "response_status": result.response_status,
            "duration_ms": result.duration_ms,
            "mapped_result": result.mapped_result,
        }


def _compute_digest(
    params: dict, connector_revision: int, operation_revision: int, execution: ConnectorExecution,
) -> str:
    canonical = json.dumps({
        "params": params,
        "connector_revision": connector_revision,
        "operation_revision": operation_revision,
        "actor": execution.actor_uid,
        "logical_call_key": execution.logical_call_key,
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _build_request_summary(connector: Any, operation: Any, params: dict) -> dict:
    safe_keys = {"connector_slug", "operation_slug", "operation_type"}
    return {
        "connector_slug": connector.slug,
        "operation_slug": operation.slug,
        "operation_type": operation.operation_type,
        "param_keys": sorted(params.keys()),
    }


def _build_response_summary(result: ConnectorResult) -> dict:
    summary: dict[str, Any] = {"success": result.success}
    if result.error_code:
        summary["error_code"] = result.error_code
    if result.response_status:
        summary["response_status"] = result.response_status
    return summary


def _invocation_summary(invocation: Any) -> dict[str, Any]:
    return {
        "invocation_id": invocation.id,
        "status": invocation.status,
        "connector_slug": invocation.connector_slug,
        "operation_slug": invocation.operation_slug,
        "operation_type": invocation.operation_type,
        "actor_uid": invocation.actor_uid,
        "logical_call_key": invocation.logical_call_key,
        "request_digest": invocation.request_digest,
        "connector_revision": invocation.connector_revision,
        "operation_revision": invocation.operation_revision,
        "approval_policy": invocation.approval_policy,
        "approved_by": invocation.approved_by,
        "error_code": invocation.error_code,
        "error_summary": invocation.error_summary,
        "response_status": invocation.response_status,
        "provider_request_id": invocation.provider_request_id,
        "duration_ms": invocation.duration_ms,
    }
