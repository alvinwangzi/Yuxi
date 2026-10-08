"""连接器共用调用服务 — prepare/execute/decide/reconcile 全生命周期。

服务不持有 AsyncSession；每次操作通过 session_context_factory 获取短事务。
事务成功退出后才会发起 HTTP 或 interrupt；失败路径在 rollback 后用新事务保存结局。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import random
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.permissions import connector_scope_matches
from yuxi.services.connectors.base import (
    BaseConnectorAdapter,
    ConnectorExecution,
    ConnectorResult,
    FrozenOperation,
)
from yuxi.services.connectors.credential_vault import CredentialVault, ensure_vault_available
from yuxi.services.connectors.http_client import ConnectorHTTPConfig
from yuxi.services.connectors.registry import get_adapter_class
from yuxi.services.connectors.schemas import (
    ConnectorSchemaError,
    validate_concurrency_limit,
    validate_params,
)
from yuxi.utils import logger
from yuxi.utils.datetime_utils import utc_now

SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

DEFAULT_APPROVAL_TTL_SECONDS = 1800
DEFAULT_LEASE_SECONDS = 120
EXECUTION_BINDING_FIELDS = (
    "consumer_type",
    "logical_call_key",
    "agent_slug",
    "agent_request_id",
    "agent_run_id",
    "workflow_id",
    "workflow_run_id",
    "step_id",
    "step_execution_id",
    "tool_call_id",
)


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

    def __init__(self, invocation_id: str, digest: str, expires_at: Any, summary: dict | None = None):
        super().__init__("写操作需要审批", code="approval_required")
        self.invocation_id = invocation_id
        self.digest = digest
        self.expires_at = expires_at
        self.summary = summary or {}


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

    async def create_connector(self, data: dict, *, actor: str) -> dict:
        """在一个管理事务中校验类型、范围、操作与加密凭据。"""
        from sqlalchemy.exc import IntegrityError
        from yuxi.permissions.connector_permission import normalize_connector_scope
        from yuxi.repositories.connector_repository import ConnectorRepository
        from yuxi.services.connectors.dto import connector_response
        from yuxi.services.connectors.http_client import ConnectorHTTPError
        from yuxi.services.connectors.schemas import validate_connector_config, validate_connector_slug

        try:
            validate_connector_slug(data["slug"])
            config = validate_connector_config(data["connector_type"], data.get("config") or {})
            read_scope = normalize_connector_scope(data.get("read_scope"))
            write_scope = normalize_connector_scope(data.get("write_scope"))
            async with self._session_context_factory() as db:
                repo = ConnectorRepository(db)
                await self._require_management_actor(repo, actor)
                vault = self._get_vault()
                if await repo.get_by_slug(data["slug"], include_deleted=True):
                    raise ConnectorConflictError("connector_slug_exists")
                connector = await repo.create(
                    slug=data["slug"],
                    name=data["name"],
                    connector_type=data["connector_type"],
                    config=config,
                    description=data.get("description"),
                    enabled=data.get("enabled", True),
                    read_scope=read_scope,
                    write_scope=write_scope,
                    created_by=actor,
                )
                for operation in data.get("operations") or self._get_adapter(
                    connector.connector_type
                ).standard_operations(config):
                    self._validate_managed_operation(connector, operation)
                    await repo.create_operation(connector_id=connector.id, **operation)
                for key, value in (data.get("credentials") or {}).items():
                    self._validate_credential(connector.connector_type, key, value)
                    encrypted = vault.encrypt(value.encode("utf-8"))
                    await repo.upsert_credential(connector.id, key, encrypted.ciphertext, encrypted.key_id)
                await db.refresh(connector, attribute_names=["credentials", "operations", "revision"])
                self._validate_enabled_credentials(connector)
                response = connector_response(connector, include_credentials=True)
            return response
        except (ConnectorSchemaError, ConnectorHTTPError, ValueError, KeyError):
            raise ConnectorServiceError("connector_configuration_invalid", code="invalid_configuration") from None
        except IntegrityError:
            raise ConnectorConflictError("connector_slug_exists") from None

    async def update_connector(self, slug: str, data: dict, *, actor: str) -> dict:
        """行锁内比较版本并更新，范围/config 不接受不明格式或空值。"""
        from yuxi.permissions.connector_permission import normalize_connector_scope
        from yuxi.repositories.connector_repository import ConnectorRepository
        from yuxi.services.connectors.dto import connector_response
        from yuxi.services.connectors.http_client import ConnectorHTTPError
        from yuxi.services.connectors.schemas import validate_connector_config

        try:
            async with self._session_context_factory() as db:
                repo = ConnectorRepository(db)
                await self._require_management_actor(repo, actor)
                connector = await self._lock_management_connector(repo, slug, data)
                changes = {key: value for key, value in data.items() if key != "expected_revision"}
                if "credential_patch" in changes:
                    await self._apply_credential_changes(repo, connector, changes.pop("credential_patch"))
                    await db.refresh(connector, attribute_names=["credentials"])
                if any(key in changes and changes[key] is None for key in ("name", "enabled")):
                    raise ValueError("nonnullable_field_cannot_be_null")
                if "name" in changes and (not isinstance(changes["name"], str) or not 1 <= len(changes["name"]) <= 128):
                    raise ValueError("connector_name_invalid")
                if "config" in changes:
                    changes["config"] = validate_connector_config(connector.connector_type, changes["config"])
                    if connector.connector_type == "feishu_bitable_crm":
                        adapter = self._get_adapter(connector.connector_type)
                        old_operations = {op["slug"]: op for op in adapter.standard_operations(connector.config or {})}
                        new_operations = {op["slug"]: op for op in adapter.standard_operations(changes["config"])}
                        for operation_slug, definition in new_operations.items():
                            operation = await repo.get_operation(connector.id, operation_slug, for_update=True)
                            old_schema = old_operations[operation_slug]["request_schema"]
                            if (
                                operation
                                and operation.request_schema == old_schema
                                and old_schema != definition["request_schema"]
                            ):
                                await repo.patch_operation(operation, {"request_schema": definition["request_schema"]})
                for key in ("read_scope", "write_scope"):
                    if key in changes:
                        if changes[key] is None:
                            raise ValueError("scope_cannot_be_null")
                        changes[key] = normalize_connector_scope(changes[key])
                if changes.get("enabled"):
                    self._get_vault()
                await repo.update_config(
                    connector,
                    updated_by=actor,
                    clear_description="description" in changes and changes["description"] is None,
                    **changes,
                )
                self._validate_enabled_credentials(connector)
                response = connector_response(connector, include_credentials=True)
            return response
        except (ConnectorSchemaError, ConnectorHTTPError, ValueError, TypeError):
            raise ConnectorServiceError("connector_configuration_invalid", code="invalid_configuration") from None

    async def update_connector_credentials(self, slug: str, data: dict, *, actor: str) -> dict:
        """锁定版本后加密更新凭据，返回可回填状态和新版本而不返回值。"""
        from yuxi.repositories.connector_repository import ConnectorRepository
        from yuxi.services.connectors.dto import connector_response

        async with self._session_context_factory() as db:
            repo = ConnectorRepository(db)
            await self._require_management_actor(repo, actor)
            connector = await self._lock_management_connector(repo, slug, data)
            if "enabled" in data:
                if type(data["enabled"]) is not bool:
                    raise ConnectorServiceError("enabled_must_be_boolean", code="invalid_configuration")
                connector.enabled = data["enabled"]
            await self._apply_credential_changes(
                repo, connector, {key: data[key] for key in ("upsert", "delete_keys") if key in data}
            )
            await repo.increment_connector_revision(connector.id)
            await db.refresh(connector, attribute_names=["credentials", "revision"])
            self._validate_enabled_credentials(connector)
            response = connector_response(connector, include_credentials=True)
        return response

    async def create_connector_operation(self, slug: str, data: dict, *, actor: str) -> dict:
        """在 connector 锁内登记受限操作，并使既有批准失效。"""
        from yuxi.repositories.connector_repository import ConnectorRepository
        from yuxi.services.connectors.dto import operation_response

        try:
            async with self._session_context_factory() as db:
                repo = ConnectorRepository(db)
                await self._require_management_actor(repo, actor)
                connector = await repo.get_by_slug(slug, for_update=True)
                if connector is None:
                    raise ConnectorServiceError("connector_not_found", code="not_found")
                self._validate_managed_operation(connector, data)
                if await repo.get_operation(connector.id, data["slug"]):
                    raise ConnectorConflictError("operation_slug_exists")
                operation = await repo.create_operation(connector_id=connector.id, **data)
                result = operation_response(operation, connector_type=connector.connector_type)
            return result
        except (ConnectorSchemaError, ValueError, TypeError):
            raise ConnectorServiceError("operation_definition_invalid", code="invalid_configuration") from None

    async def update_connector_operation(self, slug: str, operation_slug: str, data: dict, *, actor: str) -> dict:
        """同一行锁内比较操作版本；PATCH 区分缺省与显式清空。"""
        from yuxi.repositories.connector_repository import ConnectorRepository
        from yuxi.services.connectors.dto import operation_response

        try:
            async with self._session_context_factory() as db:
                repo = ConnectorRepository(db)
                await self._require_management_actor(repo, actor)
                connector = await repo.get_by_slug(slug, for_update=True)
                if connector is None:
                    raise ConnectorServiceError("connector_not_found", code="not_found")
                operation = await repo.get_operation(connector.id, operation_slug, for_update=True)
                if operation is None:
                    raise ConnectorServiceError("operation_not_found", code="not_found")
                if type(data.get("expected_revision")) is not int or data["expected_revision"] != operation.revision:
                    raise ConnectorConflictError("operation_revision_conflict")
                changes = {key: value for key, value in data.items() if key != "expected_revision"}
                if set(changes) & {"slug", "operation_type"}:
                    raise ConnectorSchemaError("operation_identity_immutable")
                merged = {
                    key: getattr(operation, key)
                    for key in (
                        "slug",
                        "name",
                        "operation_type",
                        "http_method",
                        "endpoint_template",
                        "request_schema",
                        "approval_policy",
                        "response_type",
                        "query_template",
                        "body_template",
                        "response_mapping",
                        "retry_policy",
                        "remote_idempotency",
                        "description",
                        "enabled",
                    )
                }
                merged.update(changes)
                self._validate_managed_operation(connector, merged)
                if changes.get("request_schema") is None and "request_schema" in changes:
                    changes["request_schema"] = {}
                await repo.patch_operation(operation, changes)
                result = operation_response(operation, connector_type=connector.connector_type)
            return result
        except (ConnectorSchemaError, ValueError, TypeError):
            raise ConnectorServiceError("operation_definition_invalid", code="invalid_configuration") from None

    async def delete_connector(self, slug: str, *, actor: str) -> dict:
        """删除保留 slug tombstone，未核实写不能丢弃恢复入口。"""
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.repositories.connector_repository import ConnectorRepository

        async with self._session_context_factory() as db:
            repo = ConnectorRepository(db)
            await self._require_management_actor(repo, actor)
            connector = await repo.get_by_slug(slug, for_update=True, include_deleted=True)
            if connector is None:
                raise ConnectorServiceError("connector_not_found", code="not_found")
            if connector.deleted_at is not None:
                return {"slug": slug, "deleted": True}
            if await ConnectorExecutionRepository(db).has_unresolved_writes(connector.id):
                raise ConnectorConflictError("connector_write_unresolved")
            await repo.soft_delete(connector, updated_by=actor)
        return {"slug": slug, "deleted": True}

    async def delete_connector_operation(self, slug: str, operation_slug: str, *, actor: str) -> dict:
        """停用操作并推进版本，unknown 写保留核对入口。"""
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.repositories.connector_repository import ConnectorRepository

        async with self._session_context_factory() as db:
            repo = ConnectorRepository(db)
            await self._require_management_actor(repo, actor)
            connector = await repo.get_by_slug(slug, for_update=True)
            operation = await repo.get_operation(connector.id, operation_slug, for_update=True) if connector else None
            if operation is None:
                raise ConnectorServiceError("operation_not_found", code="not_found")
            if await ConnectorExecutionRepository(db).has_unresolved_writes(connector.id, operation_id=operation.id):
                raise ConnectorConflictError("operation_write_unresolved")
            if operation.enabled:
                await repo.disable_operation(operation)
        return {"slug": operation_slug, "disabled": True}

    async def test_operation_invocation(
        self, slug: str, operation_slug: str, params: dict, *, actor: str, idempotency_key: str | None
    ) -> dict:
        """管理测试重试绑定用户、操作和客户端键，required 测试沿正常审批恢复。"""
        from yuxi.repositories.connector_repository import ConnectorRepository

        async with self._session_context_factory() as db:
            repo = ConnectorRepository(db)
            await self._require_management_actor(repo, actor)
            connector = await repo.get_by_slug(slug)
            operation = await repo.get_operation(connector.id, operation_slug) if connector else None
            if operation is None:
                raise ConnectorServiceError("operation_not_found", code="not_found")
            if operation.operation_type == "write" and not idempotency_key:
                raise ConnectorServiceError("idempotency_key_required", code="invalid_params")
        if idempotency_key is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", idempotency_key):
            raise ConnectorServiceError("idempotency_key_invalid", code="invalid_params")
        identity = json.dumps([actor, slug, operation_slug, idempotency_key or str(uuid.uuid4())], ensure_ascii=False)
        execution = ConnectorExecution(
            invocation_id=str(uuid.uuid4()),
            actor_uid=actor,
            consumer_type="admin_test",
            logical_call_key="admin_test:" + hashlib.sha256(identity.encode()).hexdigest(),
            connector_revision=0,
            operation_revision=0,
        )
        return await self.prepare_and_execute(slug, operation_slug, params, execution=execution)

    async def discover_connector_metadata(self, slug: str, *, actor: str) -> dict:
        """管理角色在短事务中取配置及完整凭据，关闭会话后只读发现资源。"""
        from yuxi.repositories.connector_repository import ConnectorRepository
        from yuxi.services.connectors.http_client import ConnectorHTTPError

        async with self._session_context_factory() as db:
            repo = ConnectorRepository(db)
            await self._require_management_actor(repo, actor)
            connector = await repo.get_by_slug(slug)
            if connector is None:
                raise ConnectorServiceError("connector_not_found", code="not_found")
            if connector.connector_type != "feishu_bitable_crm":
                raise ConnectorServiceError("metadata_discovery_unsupported", code="invalid_configuration")
            vault = self._get_vault()
            credentials = {
                row.credential_key: vault.decrypt(row.credential_value, row.key_id)
                for row in connector.credentials or []
            }
            if {"app_id", "app_secret"} - set(credentials):
                raise ConnectorServiceError("authentication_credentials_incomplete", code="invalid_configuration")
            config = ConnectorHTTPConfig.from_dict(connector.config)
            adapter = self._get_adapter(connector.connector_type)
        try:
            return await adapter.discover_metadata(config, credentials)
        except TimeoutError:
            raise ConnectorServiceError("metadata_timeout", code="timeout") from None
        except ConnectorHTTPError as exc:
            raise ConnectorServiceError(exc.code, code=exc.code) from None
        except Exception:
            raise ConnectorServiceError("metadata_response_invalid", code="provider_error") from None

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
            from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
            from yuxi.repositories.connector_repository import ConnectorRepository

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

            actor = await repo.get_active_actor(execution.actor_uid)
            try:
                await repo.validate_execution_owner(execution, actor, operation)
            except PermissionError:
                raise ConnectorAuthorizationError() from None
            scope = connector.write_scope if operation.operation_type == "write" else connector.read_scope
            if not connector_scope_matches(actor, scope):
                raise ConnectorAuthorizationError()

            if execution.consumer_type == "agent" and (
                execution.connector_revision != connector.revision or execution.operation_revision != operation.revision
            ):
                raise ConnectorConflictError("connector_tool_revision_conflict")

            validated_params = validate_params(params, operation.request_schema)
            from yuxi.services.connectors.schemas import validate_delivery_policy

            validate_delivery_policy(
                connector.connector_type, operation.operation_type, operation.retry_policy, operation.remote_idempotency
            )
            digest = _compute_digest(
                validated_params,
                connector.revision,
                operation.revision,
                execution,
                connector_slug=connector.slug,
                operation_slug=operation.slug,
            )

            existing = await exec_repo.get_by_logical_call_key(execution.logical_call_key)
            if existing is not None:
                if existing.request_digest == digest:
                    return _invocation_summary(existing)
                raise ConnectorConflictError(f"logical_call_key 已存在但 digest 不匹配: {execution.logical_call_key}")

            params_json = json.dumps(validated_params, ensure_ascii=False, default=str).encode("utf-8")
            params_encrypted = vault.encrypt(params_json)

            from yuxi.services.connectors.schemas import validate_connector_config

            effective_config = dict(connector.config or {})
            if connector.connector_type == "generic_rest":
                # 历史 REST 省略认证类型时沿原 none 默认冻结，不猜测凭据用途。
                effective_config.setdefault("auth_type", "none")
            try:
                effective_config = validate_connector_config(connector.connector_type, effective_config)
            except (ConnectorSchemaError, ValueError):
                raise ConnectorServiceError("connector_configuration_invalid", code="invalid_configuration") from None
            self._validate_enabled_credentials(connector)

            snapshot = {
                "snapshot_version": 1,
                "connector_slug": connector.slug,
                "connector_revision": connector.revision,
                "connector_type": connector.connector_type,
                "config": effective_config,
                "operation_slug": operation.slug,
                "operation_revision": operation.revision,
                "operation": asdict(_freeze_operation(operation)),
                "credentials": {
                    credential.credential_key: vault.decrypt(
                        credential.credential_value,
                        credential.key_id,
                    ).decode("utf-8")
                    for credential in connector.credentials or []
                },
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

            if invocation.request_digest != digest:
                raise ConnectorConflictError("logical_call_key_digest_conflict")
            summary = _invocation_summary(invocation)

        # 等待是已持久化的业务状态，不能通过事务异常触发回滚。
        if summary["status"] == "awaiting_approval":
            raise ConnectorApprovalRequired(
                invocation_id=summary["invocation_id"],
                digest=digest,
                expires_at=None,
                summary=summary["request_summary"],
            )
        return summary

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

        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.repositories.connector_repository import ConnectorRepository

        deadline = asyncio.get_running_loop().time() + 5
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ConnectorServiceError("连接器并发数已达上限", code="capacity_exceeded")
            try:
                async with asyncio.timeout(remaining):
                    invocation, snapshot, attempt, retry_budget = await self._claim_execution(
                        invocation_id, execution, owner_attempt, vault
                    )
                break
            except TimeoutError:
                raise ConnectorServiceError("连接器容量等待超时", code="capacity_exceeded") from None
            except ConnectorServiceError as exc:
                if exc.code != "capacity_exceeded":
                    raise
                await asyncio.sleep(min(0.1, max(0, deadline - asyncio.get_running_loop().time())))

        execution = replace(execution, invocation_id=invocation_id)

        async def send_with_budget():
            """每次重试先完成旧 attempt，再重新校验当前权限并提交新 attempt。"""
            nonlocal attempt
            for attempt_no in range(1, retry_budget + 1):
                result = await self._do_http_execution(snapshot, execution)
                transient = result.response_status in (429, 502, 503, 504) or result.error_code in (
                    "timeout",
                    "http_error",
                )
                if result.success or not transient or attempt_no == retry_budget:
                    return result
                async with self._session_context_factory() as db:
                    exec_repo = ConnectorExecutionRepository(db)
                    await exec_repo.finalize_attempt(
                        attempt,
                        send_state="response_received" if result.response_status is not None else "sent_unknown",
                        response_status=result.response_status,
                        provider_request_id=result.provider_request_id,
                        error_code=result.error_code,
                        duration_ms=int(result.duration_ms),
                    )
                delay = min(5.0, (result.retry_after_seconds or 0) + random.uniform(0.05, 0.15))
                await asyncio.sleep(delay)
                async with self._session_context_factory() as db:
                    exec_repo = ConnectorExecutionRepository(db)
                    repo = ConnectorRepository(db)
                    await repo.get_active_actor(execution.actor_uid, for_update=True)
                    await repo.lock_execution_owner(execution)
                    invocation = await exec_repo.get_invocation(invocation_id)
                    invocation, _, current_operation = await self._lock_authorized_invocation(
                        repo, exec_repo, invocation, execution.actor_uid
                    )
                    await repo.validate_execution_owner(
                        execution, await repo.get_active_actor(execution.actor_uid), current_operation
                    )
                    if not await exec_repo.heartbeat(invocation_id, owner_attempt=owner_attempt):
                        raise ConnectorConflictError("retry_owner_lost")
                    attempt = await exec_repo.create_attempt(
                        invocation_id, attempt_no=attempt_no + 1, owner_attempt=owner_attempt
                    )

        http_task = asyncio.create_task(send_with_budget())

        async def renew_lease():
            """HTTP 期间短事务续租；取消或失去 owner 时停止本地发送。"""
            while True:
                await asyncio.sleep(10)
                async with self._session_context_factory() as db:
                    owned = await ConnectorExecutionRepository(db).heartbeat(invocation_id, owner_attempt=owner_attempt)
                if not owned:
                    http_task.cancel()
                    return

        lease_task = asyncio.create_task(renew_lease())
        try:
            async with asyncio.timeout(ConnectorHTTPConfig.from_dict(snapshot["config"]).timeout_seconds):
                result = await http_task

            async with self._session_context_factory() as db:
                from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

                exec_repo = ConnectorExecutionRepository(db)

                invocation = await exec_repo.get_invocation(invocation_id)
                await exec_repo.finalize_attempt(
                    attempt,
                    send_state=(
                        "response_received"
                        if result.response_status is not None
                        else "sent_unknown"
                        if result.remote_outcome == "unknown"
                        else "not_sent"
                    ),
                    response_status=result.response_status,
                    provider_request_id=result.provider_request_id,
                    error_code=result.error_code,
                    duration_ms=int(result.duration_ms),
                )

                remote_outcome = result.remote_outcome
                status = (
                    "unknown"
                    if remote_outcome == "unknown"
                    else "succeeded"
                    if result.success or remote_outcome == "succeeded"
                    else "failed"
                )

                projection = result.mapped_result if result.mapped_result is not None else result.data
                result_json = json.dumps(
                    {
                        "result_version": 1,
                        "success": result.success,
                        "data": projection,
                        "provider_evidence": result.provider_evidence,
                    },
                    ensure_ascii=False,
                    default=str,
                ).encode("utf-8")
                result_data = vault.encrypt(result_json).ciphertext
                if invocation.key_id != vault.current_key_id:
                    old_key_id = invocation.key_id
                    for field in ("params_ciphertext", "execution_snapshot_ciphertext"):
                        ciphertext = getattr(invocation, field)
                        if ciphertext is not None:
                            setattr(invocation, field, vault.encrypt(vault.decrypt(ciphertext, old_key_id)).ciphertext)
                    invocation.key_id = vault.current_key_id

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
            logger.warning(f"连接器执行失败 invocation_id={invocation_id}")
            timed_out = isinstance(exc, TimeoutError)
            error_code = "timeout" if timed_out else "execution_error"
            outcome = "failed" if timed_out and snapshot["operation"]["operation_type"] == "read" else "unknown"

            async with self._session_context_factory() as db:
                from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

                exec_repo = ConnectorExecutionRepository(db)

                invocation = await exec_repo.get_invocation(invocation_id)
                if invocation and invocation.status == "running":
                    await exec_repo.finalize_invocation(
                        invocation,
                        owner_attempt=owner_attempt,
                        status=outcome,
                        remote_outcome=outcome,
                        error_code=error_code,
                        error_summary=error_code,
                    )
                    await exec_repo.abandon_owned_attempt(invocation.id, owner_attempt, error_code=error_code)

            return ConnectorResult(
                success=False,
                error_code=error_code,
                error_message=error_code,
                remote_outcome=outcome,
            )
        finally:
            http_task.cancel()
            lease_task.cancel()
            await asyncio.gather(http_task, lease_task, return_exceptions=True)

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
            from yuxi.repositories.connector_repository import ConnectorRepository

            exec_repo = ConnectorExecutionRepository(db)
            repo = ConnectorRepository(db)

            invocation = await exec_repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("调用不存在", code="not_found")

            invocation, connector, operation = await self._lock_authorized_invocation(
                repo,
                exec_repo,
                invocation,
                actor,
            )
            if not expected_digest or expected_digest != invocation.request_digest:
                raise ConnectorConflictError("批准必须绑定调用指纹")
            if (
                invocation.approved_by == actor
                and invocation.approval_digest == invocation.request_digest
                and decision == "approve"
            ):
                return _invocation_summary(invocation)
            if invocation.status == "rejected" and decision == "reject":
                return _invocation_summary(invocation)
            if invocation.status != "awaiting_approval":
                raise ConnectorConflictError("当前调用不接受审批决定")

            if decision == "approve":
                if not (invocation.request_summary or {}).get("approval_ready", False):
                    raise ConnectorServiceError("approval_summary_incomplete", code="invalid_configuration")
                expires_at = utc_now() + timedelta(seconds=DEFAULT_APPROVAL_TTL_SECONDS)
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
        self, invocation_id: str, resolution: str, *, actor: str, reason: str | None = None, result: Any = None
    ) -> dict:
        """当前管理员在执行范围内核对，证据与回查结果加密绑定同一次调用。"""
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.repositories.connector_repository import ConnectorRepository

        if (
            resolution not in ("succeeded", "failed")
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 2000
        ):
            raise ConnectorServiceError("resolution_evidence_required", code="invalid_evidence")
        if resolution == "succeeded" and result is None:
            raise ConnectorServiceError("resolution_result_required", code="invalid_evidence")
        vault = self._get_vault()
        async with self._session_context_factory() as db:
            repo = ConnectorRepository(db)
            exec_repo = ConnectorExecutionRepository(db)
            user = await self._require_management_actor(repo, actor)
            invocation = await exec_repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("invocation_not_found", code="not_found")
            connector = await repo.get_by_id(invocation.connector_id, for_update=True)
            scope = connector.write_scope if invocation.operation_type == "write" else connector.read_scope
            if not connector_scope_matches(user, scope):
                raise ConnectorAuthorizationError()
            invocation = await exec_repo.get_invocation(invocation_id, for_update=True)
            payload = (
                json.loads(vault.decrypt(invocation.result_ciphertext, invocation.key_id))
                if invocation.result_ciphertext
                else {}
            )
            evidence = {"actor_uid": actor, "resolution": resolution, "reason": reason.strip()}
            if invocation.status != "unknown":
                if payload.get("resolution") == evidence and payload.get("data") == result:
                    return _invocation_summary(invocation)
                raise ConnectorConflictError("resolution_already_decided")
            payload.update(
                {"result_version": 1, "success": resolution == "succeeded", "data": result, "resolution": evidence}
            )
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if len(encoded) > 10 * 1024 * 1024:
                raise ConnectorServiceError("resolution_result_too_large", code="invalid_evidence")
            if invocation.key_id != vault.current_key_id:
                old_key = invocation.key_id
                for field in ("params_ciphertext", "execution_snapshot_ciphertext"):
                    if value := getattr(invocation, field):
                        setattr(invocation, field, vault.encrypt(vault.decrypt(value, old_key)).ciphertext)
                invocation.key_id = vault.current_key_id
            await exec_repo.finalize_invocation(
                invocation,
                owner_attempt=invocation.owner_attempt,
                status=resolution,
                remote_outcome=resolution,
                result_ciphertext=vault.encrypt(encoded).ciphertext,
                response_summary={"success": resolution == "succeeded", "reconciled": True},
                error_code=None if resolution == "succeeded" else "remote_failure_confirmed",
                error_summary=None if resolution == "succeeded" else "远端证据确认失败",
                expected_status="unknown",
            )
            return _invocation_summary(invocation)

    async def cancel_invocation(self, invocation_id: str, *, actor: str) -> dict:
        """调用者取消未发送调用；在途结果形成 unknown 并拒绝迟到 owner。"""
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.repositories.connector_repository import ConnectorRepository

        async with self._session_context_factory() as db:
            repo = ConnectorRepository(db)
            exec_repo = ConnectorExecutionRepository(db)
            if await repo.get_active_actor(actor, for_update=True) is None:
                raise ConnectorAuthorizationError()
            invocation = await exec_repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("invocation_not_found", code="not_found")
            if invocation.actor_uid != actor:
                raise ConnectorAuthorizationError()
            await repo.get_by_id(invocation.connector_id, for_update=True)
            invocation = await exec_repo.get_invocation(invocation_id, for_update=True)
            if invocation.status == "cancelled":
                return _invocation_summary(invocation)
            if invocation.status == "running":
                await exec_repo.mark_unknown(
                    invocation,
                    owner_attempt=invocation.owner_attempt,
                    error_code="cancelled_inflight",
                    error_summary="在途调用已取消本地等待，远端结局需核对",
                )
                await exec_repo.abandon_owned_attempt(invocation.id, invocation.owner_attempt)
            elif invocation.status in ("prepared", "awaiting_approval"):
                await exec_repo.cancel_invocation(invocation)
                invocation.remote_outcome = "not_sent"
            else:
                raise ConnectorConflictError("invocation_not_cancellable")
            return _invocation_summary(invocation)

    async def get_management_invocation(self, invocation_id: str, *, actor: str) -> dict:
        """当前管理角色可回读审计与 attempt，永不返回密文或原始私人结果。"""
        from yuxi.repositories.connector_repository import ConnectorRepository
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.services.connectors.dto import invocation_response

        async with self._session_context_factory() as db:
            await self._require_management_actor(ConnectorRepository(db), actor)
            repo = ConnectorExecutionRepository(db)
            invocation = await repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("invocation_not_found", code="not_found")
            data = invocation_response(invocation)
            data["attempts"] = [attempt.to_dict() for attempt in await repo.list_attempts(invocation_id)]
            return data

    async def get_user_invocation(self, invocation_id: str, *, actor: str) -> dict:
        """本人回读也须保留当前范围、启用状态和真实可见 Run 绑定。"""
        from yuxi.repositories.connector_repository import ConnectorRepository
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        from yuxi.repositories.agent_run_repository import AgentRunRepository
        from yuxi.repositories.workflow_repository import WorkflowRepository
        from yuxi.services.connectors.dto import invocation_response

        async with self._session_context_factory() as db:
            repo = ConnectorRepository(db)
            user = await repo.get_active_actor(actor)
            execution_repo = ConnectorExecutionRepository(db)
            invocation = await execution_repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("invocation_not_found", code="not_found")
            connector = await repo.get_by_id(invocation.connector_id)
            operation = await repo.get_operation(connector.id, invocation.operation_slug) if connector else None
            if (
                invocation.actor_uid != actor
                or user is None
                or connector is None
                or connector.deleted_at
                or not connector.enabled
                or operation is None
                or not operation.enabled
            ):
                raise ConnectorAuthorizationError()
            scope = connector.write_scope if invocation.operation_type == "write" else connector.read_scope
            if not connector_scope_matches(user, scope):
                raise ConnectorAuthorizationError()
            if invocation.agent_run_id:
                run = await AgentRunRepository(db).get_run_for_user(invocation.agent_run_id, actor)
                if (
                    run is None
                    or run.request_id != invocation.agent_request_id
                    or run.agent_slug != invocation.agent_slug
                ):
                    raise ConnectorAuthorizationError()
            if invocation.workflow_run_id:
                run = await WorkflowRepository(db).get_run_for_actor(invocation.workflow_run_id, actor)
                if run is None or run.workflow_id != invocation.workflow_id:
                    raise ConnectorAuthorizationError()
            data = invocation_response(invocation)
            data["attempts"] = [attempt.to_dict() for attempt in await execution_repo.list_attempts(invocation_id)]
            return data

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
                connector,
                uid=uid or "",
                department_ids=department_ids,
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

    async def test_connector(self, connector_slug: str, *, actor: str) -> dict[str, Any]:
        """仅执行已声明只读 healthcheck，经共用账本和最终授权发送。"""
        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_repository import ConnectorRepository

            repo = ConnectorRepository(db)
            user = await self._require_management_actor(repo, actor)
            connector = await repo.get_by_slug_for_execution(connector_slug)
            if connector is None:
                raise ConnectorServiceError("连接器不存在", code="not_found")
            if not connector.enabled or not connector_scope_matches(user, connector.read_scope):
                raise ConnectorAuthorizationError()
            adapter = self._get_adapter(connector.connector_type)
            slug = (connector.config or {}).get("healthcheck_operation_slug") or adapter.manifest().get(
                "healthcheck_operation_slug"
            )
            operation = await repo.get_operation(connector.id, slug) if slug else None
            if operation is None or not operation.enabled or operation.operation_type != "read":
                return {
                    "connector_slug": connector_slug,
                    "connector_type": connector.connector_type,
                    "probe": {
                        "network": False,
                        "auth": False,
                        "operation": False,
                        "error": "readonly_healthcheck_not_configured",
                    },
                }
            revision, operation_revision = connector.revision, operation.revision
            connector_type = connector.connector_type
        result = await self.prepare_and_execute(
            connector_slug,
            slug,
            {},
            execution=ConnectorExecution(
                invocation_id=str(uuid.uuid4()),
                actor_uid=actor,
                consumer_type="admin_test",
                logical_call_key="probe:" + str(uuid.uuid4()),
                connector_revision=revision,
                operation_revision=operation_revision,
            ),
        )
        status = result.get("response_status")
        return {
            "connector_slug": connector_slug,
            "connector_type": connector_type,
            "probe": {
                "network": status is not None,
                "auth": bool(result.get("success")),
                "operation": bool(result.get("success")),
                "invocation_id": result["invocation_id"],
                "error": result.get("error_code"),
            },
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
            connector_slug,
            operation_slug,
            params,
            execution=execution,
        )
        if prepare_result.get("status") in ("awaiting_approval",):
            raise ConnectorApprovalRequired(
                invocation_id=prepare_result["invocation_id"],
                digest=prepare_result.get("request_digest", ""),
                expires_at=None,
                summary=prepare_result.get("request_summary"),
            )

        if prepare_result["status"] in ("succeeded", "failed", "cancelled", "running"):
            return await self._read_completed_result(prepare_result["invocation_id"], execution)

        if prepare_result["status"] == "rejected":
            return {
                "invocation_id": prepare_result["invocation_id"],
                "success": False,
                "remote_outcome": "not_sent",
                "error_code": "approval_rejected",
                "error_message": "调用者已拒绝写入，未发送第三方请求",
            }

        if prepare_result["status"] == "unknown":
            return {
                "invocation_id": prepare_result["invocation_id"],
                "success": False,
                "remote_outcome": "unknown",
                "error_code": "reconciliation_required",
                "error_message": "远端结局需人工核对，禁止自动重发",
            }

        try:
            result = await self.execute_invocation(prepare_result["invocation_id"], execution=execution)
        except ConnectorServiceError as exc:
            if exc.code != "invalid_state":
                raise
            return await self._read_completed_result(prepare_result["invocation_id"], execution)
        return {
            "invocation_id": prepare_result["invocation_id"],
            "success": result.success,
            "data": result.mapped_result if result.mapped_result is not None else result.data,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "remote_outcome": result.remote_outcome,
            "response_status": result.response_status,
            "duration_ms": result.duration_ms,
            "mapped_result": result.mapped_result,
        }

    async def resolve_agent_execution(
        self, *, actor_uid, current_run_id, request_id, tool_call_id, connector_revision, operation_revision
    ) -> ConnectorExecution:
        """从运行事实派生稳定工具身份，resume 仍引用最初 Request/Run。"""
        from yuxi.repositories.connector_repository import ConnectorRepository

        if not tool_call_id:
            raise ConnectorAuthorizationError()
        async with self._session_context_factory() as db:
            try:
                current, origin = await ConnectorRepository(db).get_agent_origin(actor_uid, current_run_id, request_id)
            except PermissionError:
                raise ConnectorAuthorizationError() from None
            metadata = origin.origin_metadata or {}
            return ConnectorExecution(
                invocation_id=str(uuid.uuid4()),
                actor_uid=actor_uid,
                consumer_type="agent",
                logical_call_key=f"agent:{origin.request_id}:{tool_call_id}",
                connector_revision=connector_revision,
                operation_revision=operation_revision,
                agent_slug=origin.agent_slug,
                agent_request_id=origin.request_id,
                agent_run_id=origin.id,
                current_agent_run_id=current.id,
                tool_call_id=tool_call_id,
                workflow_id=metadata.get("workflow_id"),
                workflow_run_id=metadata.get("workflow_run_id"),
                step_id=metadata.get("step_id"),
                step_execution_id=metadata.get("step_execution_id"),
            )

    async def _apply_credential_changes(self, repo, connector, changes):
        """在 caller 已持有的管理事务内校验并加密凭据，不另开事务或变更版本。"""
        if not isinstance(changes, dict) or set(changes) - {"upsert", "delete_keys"}:
            raise ConnectorServiceError("credential_patch_invalid", code="invalid_configuration")
        upsert = changes.get("upsert")
        delete_keys = changes.get("delete_keys")
        upsert = {} if upsert is None else upsert
        delete_keys = [] if delete_keys is None else delete_keys
        allowed = set(self._get_adapter(connector.connector_type).credential_keys())
        if (
            not isinstance(upsert, dict)
            or not isinstance(delete_keys, list)
            or any(not isinstance(key, str) or key not in allowed for key in delete_keys)
        ):
            raise ConnectorServiceError("credential_patch_invalid", code="invalid_configuration")
        if set(upsert) & set(delete_keys):
            raise ConnectorServiceError("credential_patch_overlap", code="invalid_configuration")
        vault = self._get_vault()
        for key, value in upsert.items():
            self._validate_credential(connector.connector_type, key, value)
            encrypted = vault.encrypt(value.encode("utf-8"))
            await repo.upsert_credential(connector.id, key, encrypted.ciphertext, encrypted.key_id)
        if delete_keys:
            await repo.delete_credentials(connector.id, delete_keys)

    async def _do_http_execution(
        self,
        snapshot: dict,
        execution: ConnectorExecution,
    ) -> ConnectorResult:
        """解密凭据并执行 HTTP 调用。"""
        http_config = ConnectorHTTPConfig.from_dict(snapshot["config"])
        adapter = self._get_adapter(snapshot["connector_type"])
        frozen_op = FrozenOperation(**snapshot["operation"])
        credentials = {key: value.encode("utf-8") for key, value in snapshot["credentials"].items()}

        return await adapter.execute(
            http_config=http_config,
            credentials=credentials,
            operation=frozen_op,
            params=snapshot.get("params", {}),
            execution=execution,
        )

    async def _read_completed_result(self, invocation_id, execution):
        """经当前权限回读同一次调用的结局或进行中状态，不重新发送 HTTP。"""
        vault = self._get_vault()
        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
            from yuxi.repositories.connector_repository import ConnectorRepository

            repo = ConnectorRepository(db)
            exec_repo = ConnectorExecutionRepository(db)
            invocation = await exec_repo.get_invocation(invocation_id)
            invocation, _, _ = await self._lock_authorized_invocation(repo, exec_repo, invocation, execution.actor_uid)
            state = {
                "invocation_id": invocation.id,
                "status": invocation.status,
                "success": False,
                "remote_outcome": invocation.remote_outcome,
                "error_code": invocation.error_code,
                "error_message": invocation.error_summary,
            }
            if invocation.status == "running":
                return {
                    **state,
                    "remote_outcome": None,
                    "error_code": "execution_in_progress",
                    "error_message": "调用正在执行",
                }
            if invocation.status == "unknown":
                return {
                    **state,
                    "remote_outcome": "unknown",
                    "error_code": "reconciliation_required",
                    "error_message": "远端结局需人工核对，禁止自动重发",
                }
            if invocation.status == "rejected":
                return {
                    **state,
                    "remote_outcome": "not_sent",
                    "error_code": "approval_rejected",
                    "error_message": "调用者已拒绝写入",
                }
            if invocation.status in ("failed", "cancelled") and not invocation.result_ciphertext:
                code = "execution_cancelled" if invocation.status == "cancelled" else "execution_failed"
                return {
                    **state,
                    "error_code": invocation.error_code or code,
                    "error_message": invocation.error_summary or "调用已结束，未重新发送",
                }
            if invocation.status not in ("succeeded", "failed", "cancelled") or not invocation.result_ciphertext:
                raise ConnectorConflictError("历史调用结果不可用，禁止重新执行")
            payload = json.loads(vault.decrypt(invocation.result_ciphertext, invocation.key_id))
            if payload.get("result_version") != 1:
                raise ConnectorConflictError("历史结果格式不可回放，禁止重新执行")
            return {
                "invocation_id": invocation.id,
                "status": invocation.status,
                "success": payload["success"],
                "data": payload["data"],
                "mapped_result": payload["data"],
                "error_code": invocation.error_code,
                "error_message": invocation.error_summary,
                "remote_outcome": invocation.remote_outcome,
                "response_status": invocation.response_status,
                "duration_ms": invocation.duration_ms,
            }

    def _get_vault(self) -> CredentialVault:
        return ensure_vault_available(self._vault_provider())

    def _get_adapter(self, connector_type: str) -> BaseConnectorAdapter:
        adapter_class = get_adapter_class(connector_type)
        return adapter_class()

    async def _require_management_actor(self, repo, actor: str):
        """管理权从数据库当前有效角色读取，不依赖 router 或前端自述。"""
        user = await repo.get_active_actor(actor, for_update=True)
        if user is None or user.role not in ("admin", "superadmin"):
            raise ConnectorAuthorizationError()
        return user

    def _validate_enabled_credentials(self, connector) -> None:
        """停用草稿可缺配，启用状态必须具备当前认证方式的完整凭据对。"""
        if not connector.enabled:
            return
        required = {
            "salesforce": {"client_id", "client_secret"},
            "feishu_bitable_crm": {"app_id", "app_secret"},
        }.get(connector.connector_type)
        if required is None:
            required = {
                "none": set(),
                "bearer": {"token"},
                "basic": {"username", "password"},
                "api_key": {"api_key"},
            }[(connector.config or {}).get("auth_type", "none")]
        if required - {row.credential_key for row in connector.credentials or []}:
            raise ConnectorServiceError("authentication_credentials_incomplete", code="invalid_configuration")
        if connector.connector_type == "feishu_bitable_crm":
            config = connector.config or {}
            if not config.get("customer_table_id") or not config.get("opportunity_table_id"):
                raise ConnectorServiceError("crm_tables_incomplete", code="invalid_configuration")
            for kind in ("customer", "opportunity"):
                if set(config.get(kind + "_fields") or {}) - set(config.get(kind + "_field_types") or {}):
                    raise ConnectorServiceError("crm_field_types_unconfirmed", code="invalid_configuration")

    async def _lock_management_connector(self, repo, slug, data):
        """管理事务共享 actor→connector 锁顺序，禁止无版本覆盖。"""
        connector = await repo.get_by_slug(slug, for_update=True)
        if connector is None:
            raise ConnectorServiceError("connector_not_found", code="not_found")
        revision = data.get("expected_revision")
        if type(revision) is not int or connector.revision != revision:
            raise ConnectorConflictError("connector_revision_conflict")
        return connector

    def _validate_credential(self, connector_type, key, value):
        """凭据键由适配器拥有，空值和控制字符不进入发送边界。"""
        allowed = self._get_adapter(connector_type).credential_keys()
        if key not in allowed or not isinstance(value, str) or not value or len(value.encode("utf-8")) > 65536:
            raise ConnectorServiceError("credential_invalid", code="invalid_configuration")
        if any(character in value for character in "\r\n\x00"):
            raise ConnectorServiceError("credential_invalid", code="invalid_configuration")

    def _validate_managed_operation(self, connector, data):
        """限制可编辑字段、schema 和模板，拒绝无界或不明执行策略。"""
        import re

        from yuxi.services.connectors.schemas import (
            validate_json_schema,
            validate_operation_namespace,
            validate_response_mapping,
        )
        from yuxi.utils.outbound_http import validate_endpoint_template

        allowed = {
            "slug",
            "name",
            "operation_type",
            "http_method",
            "endpoint_template",
            "request_schema",
            "approval_policy",
            "response_type",
            "query_template",
            "body_template",
            "response_mapping",
            "retry_policy",
            "remote_idempotency",
            "description",
            "enabled",
        }
        if set(data) - allowed:
            raise ConnectorSchemaError("operation_field_invalid")
        if "enabled" in data and type(data["enabled"]) is not bool:
            raise ConnectorSchemaError("operation_enabled_invalid")
        if not isinstance(data.get("name"), str) or not 1 <= len(data["name"]) <= 128:
            raise ConnectorSchemaError("operation_name_invalid")
        if not isinstance(data.get("slug"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", data["slug"]):
            raise ConnectorSchemaError("operation_slug_invalid")
        validate_operation_namespace(connector.slug, data["slug"])
        validate_json_schema(data.get("request_schema"))
        validate_response_mapping(data.get("response_mapping"))
        validate_endpoint_template(data.get("endpoint_template", "/"))
        operation_type = data.get("operation_type")
        method = data.get("http_method", "GET")
        if connector.connector_type != "generic_rest":
            declared = {
                op["slug"]: op
                for op in self._get_adapter(connector.connector_type).standard_operations(connector.config or {})
            }
            standard = declared.get(data["slug"])
            if standard is None or (operation_type, method) != (standard["operation_type"], standard["http_method"]):
                raise ConnectorSchemaError("provider_operation_contract_invalid")
            for field, default in (
                ("endpoint_template", "/"),
                ("query_template", None),
                ("body_template", None),
                ("response_type", "json"),
            ):
                if data.get(field, default) != standard.get(field, default):
                    raise ConnectorSchemaError("provider_owned_field_immutable")
        if operation_type not in ("read", "write") or method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise ConnectorSchemaError("operation_type_or_method_invalid")
        if connector.connector_type == "generic_rest" and operation_type == "read" and method != "GET":
            raise ConnectorSchemaError("generic_read_requires_get")
        if data.get("approval_policy", "required") not in ("required", "preauthorized"):
            raise ConnectorSchemaError("approval_policy_invalid")
        if data.get("response_type", "json") not in ("json", "text", "empty"):
            raise ConnectorSchemaError("response_type_invalid")
        if "runtime" in (data.get("request_schema") or {}).get("properties", {}):
            raise ConnectorSchemaError("reserved_parameter_invalid")
        from yuxi.services.connectors.schemas import validate_delivery_policy

        validate_delivery_policy(
            connector.connector_type, operation_type, data.get("retry_policy"), data.get("remote_idempotency")
        )

    async def _claim_execution(self, invocation_id, execution, owner_attempt, vault):
        """每次容量检查只持有一个短事务，退出后等待，领取后提交再发送。"""
        async with self._session_context_factory() as db:
            from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
            from yuxi.repositories.connector_repository import ConnectorRepository

            exec_repo = ConnectorExecutionRepository(db)
            repo = ConnectorRepository(db)

            invocation = await exec_repo.get_invocation(invocation_id)
            if invocation is None:
                raise ConnectorServiceError("调用不存在", code="not_found")
            await repo.get_active_actor(execution.actor_uid, for_update=True)
            await repo.lock_execution_owner(execution)
            invocation, connector, operation = await self._lock_authorized_invocation(
                repo,
                exec_repo,
                invocation,
                execution.actor_uid,
            )
            self._validate_enabled_credentials(connector)
            try:
                await repo.validate_execution_owner(
                    execution, await repo.get_active_actor(execution.actor_uid), operation
                )
            except PermissionError:
                raise ConnectorAuthorizationError() from None
            if any(getattr(execution, name) != getattr(invocation, name) for name in EXECUTION_BINDING_FIELDS):
                raise ConnectorAuthorizationError()
            if invocation.approval_policy == "required":
                expiry = invocation.approval_expires_at
                if expiry is not None:
                    expiry = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry.astimezone(UTC)
                if (
                    invocation.approved_by != execution.actor_uid
                    or invocation.approval_digest != invocation.request_digest
                    or expiry is None
                    or expiry <= datetime.now(UTC)
                ):
                    raise ConnectorConflictError("批准已失效或未绑定当前调用")
            if invocation.status not in ("prepared",):
                raise ConnectorServiceError(f"调用状态不允许执行: {invocation.status}", code="invalid_state")

            snapshot_json = vault.decrypt(invocation.execution_snapshot_ciphertext, invocation.key_id)
            snapshot = json.loads(snapshot_json)
            if snapshot.get("snapshot_version") != 1:
                raise ConnectorConflictError("历史调用没有完整执行快照，请重新准备")
            ConnectorHTTPConfig.from_dict(snapshot["config"])
            from yuxi.services.connectors.schemas import validate_delivery_policy

            retry_budget = validate_delivery_policy(
                snapshot["connector_type"],
                snapshot["operation"]["operation_type"],
                snapshot["operation"].get("retry_policy"),
                snapshot["operation"].get("remote_idempotency"),
            )

            if await exec_repo.get_running_count_for_connector(connector.id) >= validate_concurrency_limit(
                (connector.config or {}).get("concurrency_limit")
            ):
                raise ConnectorServiceError("连接器并发数已达上限", code="capacity_exceeded")

            claimed = await exec_repo.claim_invocation(
                invocation,
                owner_id=(
                    execution.current_agent_run_id or execution.workflow_owner_attempt or f"admin_test:{owner_attempt}"
                ),
                owner_attempt=owner_attempt,
                execution=execution,
            )
            if not claimed:
                raise ConnectorServiceError("调用已被其他执行者领取", code="claim_failed")

            attempt = await exec_repo.create_attempt(
                invocation_id,
                attempt_no=1,
                owner_attempt=owner_attempt,
            )
        return invocation, snapshot, attempt, retry_budget

    async def _lock_authorized_invocation(self, repo, exec_repo, invocation, actor):
        """按用户、连接器、操作、调用的顺序锁定授权与版本事实。"""
        if invocation.actor_uid != actor:
            raise ConnectorAuthorizationError()
        user = await repo.get_active_actor(actor, for_update=True)
        connector = await repo.get_by_id(invocation.connector_id, for_update=True)
        if connector is None or connector.deleted_at is not None or not connector.enabled:
            raise ConnectorAuthorizationError()
        operation = await repo.get_operation(connector.id, invocation.operation_slug, for_update=True)
        if operation is None or not operation.enabled:
            raise ConnectorAuthorizationError()
        scope = connector.write_scope if operation.operation_type == "write" else connector.read_scope
        if not connector_scope_matches(user, scope):
            raise ConnectorAuthorizationError()
        invocation = await exec_repo.get_invocation(invocation.id, for_update=True)
        if (connector.revision, operation.revision) != (invocation.connector_revision, invocation.operation_revision):
            raise ConnectorConflictError("连接器或操作版本已变更，请重新准备调用")
        return invocation, connector, operation


def _freeze_operation(operation) -> FrozenOperation:
    """将准备事务中的操作行转换为可加密的完整请求定义。"""
    return FrozenOperation(
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


def _compute_digest(
    params: dict,
    connector_revision: int,
    operation_revision: int,
    execution: ConnectorExecution,
    *,
    connector_slug: str,
    operation_slug: str,
) -> str:
    canonical = json.dumps(
        {
            "params": params,
            "connector_slug": connector_slug,
            "operation_slug": operation_slug,
            "consumer_type": execution.consumer_type,
            "execution_binding": {name: getattr(execution, name) for name in EXECUTION_BINDING_FIELDS},
            "connector_revision": connector_revision,
            "operation_revision": operation_revision,
            "actor": execution.actor_uid,
            "logical_call_key": execution.logical_call_key,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _build_request_summary(connector: Any, operation: Any, params: dict) -> dict:
    """只有服务端 schema 显式公开的字段能展示值，目标绑定冻结参数。"""
    visible = {}
    targets = {}
    for key, field in (operation.request_schema or {}).get("properties", {}).items():
        if key not in params or not isinstance(field, dict) or not field.get("x-approval-visible"):
            continue
        value = params[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            rendered = str(value)[:256] if isinstance(value, str) else value
        else:
            rendered = {"type": type(value).__name__, "items": len(value)}
        visible[key] = rendered
        if field.get("x-approval-target"):
            if type(value) not in (str, int) or len(str(value)) > 256:
                raise ConnectorSchemaError("审批目标必须是完整的有界标识")
            targets[key] = rendered
    from yuxi.services.connectors.schemas import PLACEHOLDER_PATTERN

    required_targets = set(PLACEHOLDER_PATTERN.findall(operation.endpoint_template))
    for value in (operation.query_template or {}).values():
        if isinstance(value, str):
            required_targets.update(PLACEHOLDER_PATTERN.findall(value))
    if connector.connector_type == "salesforce":
        required_targets.update(
            {"upsert_customer": {"external_id_value"}, "update_opportunity": {"opportunity_id"}}.get(
                operation.slug, set()
            )
        )
    if connector.connector_type == "feishu_bitable_crm" and operation.slug.startswith("update_"):
        required_targets.add("record_id")
    return {
        "connector_slug": connector.slug,
        "operation_slug": operation.slug,
        "operation_type": operation.operation_type,
        "param_keys": sorted(params.keys()),
        "method": operation.http_method,
        "endpoint_template": operation.endpoint_template,
        "targets": targets,
        "changes": {key: value for key, value in visible.items() if key not in targets},
        "changed_fields": sorted(set(params) - set(targets)),
        "missing_target_fields": sorted(required_targets - set(targets)),
        "approval_ready": (not params or bool(visible)) and required_targets.issubset(targets),
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
        "agent_request_id": invocation.agent_request_id,
        "agent_run_id": invocation.agent_run_id,
        "workflow_run_id": invocation.workflow_run_id,
        "logical_call_key": invocation.logical_call_key,
        "request_digest": invocation.request_digest,
        "request_summary": invocation.request_summary,
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
