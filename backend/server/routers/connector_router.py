"""连接器管理 API 与消费 API。

管理端（管理员）：``/api/system/connectors`` — 配置、凭据、操作、测试、用量与核对。
消费端（登录用户）：``/api/connectors`` — 可见目录、操作 schema、调用结果与审批决定。

路由不持有 session 或 service；每次请求通过 ``get_db`` 获取短事务，
调用服务或 repository 完成后 commit。
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.storage.postgres.models_business import User
from yuxi.utils import logger

connectors_admin = APIRouter(prefix="/system/connectors", tags=["connectors-admin"])
connectors_user = APIRouter(prefix="/connectors", tags=["connectors"])

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_SLUG_LENGTH = 64


def _validate_slug(slug: str) -> str:
    if not slug or not _SLUG_PATTERN.match(slug):
        raise HTTPException(422, detail=f"slug 格式无效: {slug}")
    return slug


def _connector_to_dict(connector: Any, *, include_credentials: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": connector.id,
        "slug": connector.slug,
        "name": connector.name,
        "connector_type": connector.connector_type,
        "description": connector.description,
        "config": connector.config or {},
        "enabled": connector.enabled,
        "revision": connector.revision,
        "read_scope": connector.read_scope,
        "write_scope": connector.write_scope,
        "created_by": connector.created_by,
        "updated_by": connector.updated_by,
        "created_at": str(connector.created_at) if connector.created_at else None,
        "updated_at": str(connector.updated_at) if connector.updated_at else None,
        "deleted_at": str(connector.deleted_at) if connector.deleted_at else None,
    }
    if include_credentials:
        data["credential_keys"] = [
            {"key": c.credential_key, "key_id": c.key_id, "updated_at": str(c.updated_at) if c.updated_at else None}
            for c in (connector.credentials or [])
        ]
    return data


def _operation_to_dict(op: Any) -> dict[str, Any]:
    return {
        "id": op.id,
        "slug": op.slug,
        "name": op.name,
        "operation_type": op.operation_type,
        "http_method": op.http_method,
        "endpoint_template": op.endpoint_template,
        "request_schema": op.request_schema,
        "response_type": op.response_type,
        "approval_policy": op.approval_policy,
        "description": op.description,
        "enabled": op.enabled,
        "revision": op.revision,
        "query_template": op.query_template,
        "body_template": op.body_template,
        "response_mapping": op.response_mapping,
        "retry_policy": op.retry_policy,
        "remote_idempotency": op.remote_idempotency,
        "created_at": str(op.created_at) if op.created_at else None,
        "updated_at": str(op.updated_at) if op.updated_at else None,
    }


def _invocation_to_dict(inv: Any) -> dict[str, Any]:
    return {
        "invocation_id": inv.id,
        "status": inv.status,
        "connector_slug": inv.connector_slug,
        "operation_slug": inv.operation_slug,
        "operation_type": inv.operation_type,
        "actor_uid": inv.actor_uid,
        "consumer_type": inv.consumer_type,
        "logical_call_key": inv.logical_call_key,
        "request_digest": inv.request_digest,
        "connector_revision": inv.connector_revision,
        "operation_revision": inv.operation_revision,
        "approval_policy": inv.approval_policy,
        "approved_by": inv.approved_by,
        "approved_at": str(inv.approved_at) if inv.approved_at else None,
        "approval_expires_at": str(inv.approval_expires_at) if inv.approval_expires_at else None,
        "rejected_by": inv.rejected_by,
        "rejection_reason": inv.rejection_reason,
        "error_code": inv.error_code,
        "error_summary": inv.error_summary,
        "response_status": inv.response_status,
        "provider_request_id": inv.provider_request_id,
        "duration_ms": inv.duration_ms,
        "remote_outcome": inv.remote_outcome,
        "request_summary": inv.request_summary,
        "response_summary": inv.response_summary,
        "agent_slug": inv.agent_slug,
        "workflow_id": inv.workflow_id,
        "workflow_run_id": inv.workflow_run_id,
        "step_id": inv.step_id,
        "created_at": str(inv.created_at) if inv.created_at else None,
        "started_at": str(inv.started_at) if inv.started_at else None,
        "completed_at": str(inv.completed_at) if inv.completed_at else None,
    }


# ── Pydantic 请求体 ──


class ConnectorCreateBody(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    connector_type: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    config: dict | None = None
    read_scope: dict | None = None
    write_scope: dict | None = None
    operations: list[dict] | None = None
    credentials: dict[str, str] | None = None


class ConnectorPatchBody(BaseModel):
    expected_revision: int | None = None
    name: str | None = None
    description: str | None = None
    config: dict | None = None
    read_scope: dict | None = None
    write_scope: dict | None = None
    enabled: bool | None = None


class CredentialPatchBody(BaseModel):
    expected_revision: int | None = None
    upsert: dict[str, str] | None = None
    delete_keys: list[str] | None = None


class OperationCreateBody(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    operation_type: str = Field(..., pattern="^(read|write)$")
    http_method: str = Field("GET", pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    endpoint_template: str = "/"
    request_schema: dict | None = None
    response_type: str = Field("json", pattern="^(json|text|empty)$")
    approval_policy: str = Field("required", pattern="^(required|preauthorized)$")
    description: str | None = None
    query_template: dict | None = None
    body_template: dict | None = None
    response_mapping: dict | None = None
    retry_policy: dict | None = None
    remote_idempotency: dict | None = None


class OperationPatchBody(BaseModel):
    expected_revision: int | None = None
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    http_method: str | None = None
    endpoint_template: str | None = None
    request_schema: dict | None = None
    response_type: str | None = None
    approval_policy: str | None = None
    query_template: dict | None = None
    body_template: dict | None = None
    response_mapping: dict | None = None
    retry_policy: dict | None = None
    remote_idempotency: dict | None = None


class DecisionBody(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    expected_digest: str | None = None


class ReconcileBody(BaseModel):
    resolution: str = Field(..., pattern="^(succeeded|failed)$")
    reason: str | None = None


# ══════════════════════════════════════════════════════════════
# 管理端 /api/system/connectors
# ══════════════════════════════════════════════════════════════


@connectors_admin.get("/types")
async def list_connector_types(admin: User = Depends(get_admin_user)):
    """已注册的连接器类型、config/credential 元数据与能力声明。"""
    from yuxi.services.connectors.registry import list_registered_types, get_adapter_manifest

    types = []
    for t in list_registered_types():
        manifest = get_adapter_manifest(t)
        types.append(manifest)
    return {"success": True, "data": types}


@connectors_admin.get("")
async def list_connectors(
    search: str | None = None,
    connector_type: str | None = None,
    enabled: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """分页列表，支持搜索、类型和启用状态过滤。"""
    from yuxi.repositories.connector_repository import ConnectorRepository

    repo = ConnectorRepository(db)
    all_connectors = await repo.list_all(include_deleted=False)

    filtered = []
    for c in all_connectors:
        if connector_type and c.connector_type != connector_type:
            continue
        if enabled is not None and c.enabled != enabled:
            continue
        if search and search.lower() not in (c.name or "").lower() and search.lower() not in (c.slug or "").lower():
            continue
        filtered.append(c)

    total = len(filtered)
    page = filtered[offset: offset + limit]
    return {
        "success": True,
        "data": [_connector_to_dict(c) for c in page],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@connectors_admin.post("")
async def create_connector(
    body: ConnectorCreateBody,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """创建连接器、初始操作和凭据，同事务提交。"""
    from yuxi.repositories.connector_repository import ConnectorRepository
    from yuxi.services.connectors.credential_vault import CredentialVault, ensure_vault_available
    from yuxi.services.connectors.schemas import validate_json_schema

    slug = _validate_slug(body.slug)
    repo = ConnectorRepository(db)

    existing = await repo.get_by_slug(slug)
    if existing is not None:
        raise HTTPException(409, detail=f"slug 已存在: {slug}")

    connector = await repo.create(
        slug=slug,
        name=body.name,
        connector_type=body.connector_type,
        description=body.description,
        config=body.config,
        read_scope=body.read_scope,
        write_scope=body.write_scope,
        created_by=admin.uid,
    )

    if body.operations:
        for op_def in body.operations:
            op_slug = _validate_slug(op_def.get("slug", ""))
            if op_def.get("request_schema"):
                validate_json_schema(op_def.get("request_schema"))
            await repo.create_operation(
                connector_id=connector.id,
                slug=op_slug,
                name=op_def.get("name", ""),
                operation_type=op_def.get("operation_type", "read"),
                http_method=op_def.get("http_method", "GET"),
                endpoint_template=op_def.get("endpoint_template", "/"),
                request_schema=op_def.get("request_schema"),
                response_type=op_def.get("response_type", "json"),
                approval_policy=op_def.get("approval_policy", "required"),
                description=op_def.get("description"),
                query_template=op_def.get("query_template"),
                body_template=op_def.get("body_template"),
                response_mapping=op_def.get("response_mapping"),
                retry_policy=op_def.get("retry_policy"),
                remote_idempotency=op_def.get("remote_idempotency"),
            )

    if body.credentials:
        vault = ensure_vault_available(CredentialVault.from_environment())
        for key, value in body.credentials.items():
            encrypted = vault.encrypt(value.encode("utf-8"))
            await repo.upsert_credential(connector.id, key, encrypted.ciphertext, encrypted.key_id)

    await db.commit()
    await db.refresh(connector)

    connector = await repo.get_by_slug(slug)
    return {"success": True, "data": _connector_to_dict(connector, include_credentials=True)}


@connectors_admin.get("/{slug}")
async def get_connector(
    slug: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """管理详情：credential_keys 与完整操作定义。"""
    from yuxi.repositories.connector_repository import ConnectorRepository

    _validate_slug(slug)
    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    data = _connector_to_dict(connector, include_credentials=True)
    data["operations"] = [_operation_to_dict(op) for op in (connector.operations or [])]
    return {"success": True, "data": data}


@connectors_admin.patch("/{slug}")
async def update_connector(
    slug: str,
    body: ConnectorPatchBody,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """乐观锁更新名称/config/scope/enabled；禁止修改 slug/type。"""
    from yuxi.repositories.connector_repository import ConnectorRepository

    _validate_slug(slug)
    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    if body.expected_revision is not None and connector.revision != body.expected_revision:
        raise HTTPException(409, detail=f"revision 冲突: 期望 {body.expected_revision}，实际 {connector.revision}")

    await repo.update_config(
        connector,
        name=body.name,
        description=body.description,
        config=body.config,
        read_scope=body.read_scope,
        write_scope=body.write_scope,
        enabled=body.enabled,
        updated_by=admin.uid,
    )
    await db.commit()
    await db.refresh(connector)
    return {"success": True, "data": _connector_to_dict(connector)}


@connectors_admin.delete("/{slug}")
async def delete_connector(
    slug: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """tombstone 删除；在途/unknown 写调用时拒绝。"""
    from yuxi.repositories.connector_repository import ConnectorRepository
    from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

    _validate_slug(slug)
    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    exec_repo = ConnectorExecutionRepository(db)
    running = await exec_repo.get_running_count_for_connector(connector.id)
    if running > 0:
        raise HTTPException(409, detail=f"有 {running} 个在途调用，无法删除")

    await repo.soft_delete(connector, updated_by=admin.uid)
    await db.commit()
    return {"success": True, "data": {"slug": slug, "deleted": True}}


@connectors_admin.patch("/{slug}/credentials")
async def update_credentials(
    slug: str,
    body: CredentialPatchBody,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """upsert/delete 凭据行；不回显值。"""
    from yuxi.repositories.connector_repository import ConnectorRepository
    from yuxi.services.connectors.credential_vault import CredentialVault, ensure_vault_available

    _validate_slug(slug)
    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    if body.expected_revision is not None and connector.revision != body.expected_revision:
        raise HTTPException(409, detail=f"revision 冲突: 期望 {body.expected_revision}，实际 {connector.revision}")

    vault = ensure_vault_available(CredentialVault.from_environment())

    if body.upsert:
        for key, value in body.upsert.items():
            encrypted = vault.encrypt(value.encode("utf-8"))
            await repo.upsert_credential(connector.id, key, encrypted.ciphertext, encrypted.key_id)

    if body.delete_keys:
        await repo.delete_credentials(connector.id, body.delete_keys)

    await repo._increment_connector_revision(connector.id)
    await db.commit()
    return {"success": True, "data": {"updated": True}}


@connectors_admin.post("/{slug}/test")
async def test_connector(
    slug: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """执行 healthcheck 只读操作，分层返回网络/认证/操作结果。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    _validate_slug(slug)
    service = get_connector_service()
    try:
        result = await service.test_connector(slug)
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        raise HTTPException(400, detail=exc.code)
    except Exception as exc:
        logger.warning(f"连接器测试失败 slug={slug}: {exc}")
        raise HTTPException(500, detail="测试执行失败")


@connectors_admin.get("/{slug}/operations")
async def list_operations(
    slug: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """完整操作编辑列表，含 schema 和 mapping。"""
    from yuxi.repositories.connector_repository import ConnectorRepository

    _validate_slug(slug)
    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    ops = [_operation_to_dict(op) for op in (connector.operations or [])]
    return {"success": True, "data": ops}


@connectors_admin.post("/{slug}/operations")
async def create_operation(
    slug: str,
    body: OperationCreateBody,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """新建操作，connector revision 一并增长。"""
    from yuxi.repositories.connector_repository import ConnectorRepository
    from yuxi.services.connectors.schemas import validate_json_schema

    _validate_slug(slug)
    op_slug = _validate_slug(body.slug)

    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    existing = await repo.get_operation(connector.id, op_slug)
    if existing is not None:
        raise HTTPException(409, detail=f"操作 slug 已存在: {op_slug}")

    if body.request_schema:
        validate_json_schema(body.request_schema)

    op = await repo.create_operation(
        connector_id=connector.id,
        slug=op_slug,
        name=body.name,
        operation_type=body.operation_type,
        http_method=body.http_method,
        endpoint_template=body.endpoint_template,
        request_schema=body.request_schema,
        response_type=body.response_type,
        approval_policy=body.approval_policy,
        description=body.description,
        query_template=body.query_template,
        body_template=body.body_template,
        response_mapping=body.response_mapping,
        retry_policy=body.retry_policy,
        remote_idempotency=body.remote_idempotency,
    )
    await db.commit()
    return {"success": True, "data": _operation_to_dict(op)}


@connectors_admin.patch("/{slug}/operations/{operation_slug}")
async def update_operation(
    slug: str,
    operation_slug: str,
    body: OperationPatchBody,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """expected_revision 更新操作定义。"""
    from yuxi.repositories.connector_repository import ConnectorRepository
    from yuxi.services.connectors.schemas import validate_json_schema

    _validate_slug(slug)
    _validate_slug(operation_slug)

    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    operation = await repo.get_operation(connector.id, operation_slug)
    if operation is None:
        raise HTTPException(404, detail=f"操作不存在: {operation_slug}")

    if body.expected_revision is not None and operation.revision != body.expected_revision:
        raise HTTPException(409, detail=f"revision 冲突: 期望 {body.expected_revision}，实际 {operation.revision}")

    if body.request_schema:
        validate_json_schema(body.request_schema)

    await repo.update_operation(
        operation,
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        http_method=body.http_method,
        endpoint_template=body.endpoint_template,
        request_schema=body.request_schema,
        response_type=body.response_type,
        approval_policy=body.approval_policy,
        query_template=body.query_template,
        body_template=body.body_template,
        response_mapping=body.response_mapping,
        retry_policy=body.retry_policy,
        remote_idempotency=body.remote_idempotency,
    )
    await db.commit()
    return {"success": True, "data": _operation_to_dict(operation)}


@connectors_admin.delete("/{slug}/operations/{operation_slug}")
async def delete_operation(
    slug: str,
    operation_slug: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """停用操作，保留历史；拒绝破坏在途写调用。"""
    from yuxi.repositories.connector_repository import ConnectorRepository

    _validate_slug(slug)
    _validate_slug(operation_slug)

    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    operation = await repo.get_operation(connector.id, operation_slug)
    if operation is None:
        raise HTTPException(404, detail=f"操作不存在: {operation_slug}")

    await repo.disable_operation(operation)
    await db.commit()
    return {"success": True, "data": {"slug": operation_slug, "disabled": True}}


@connectors_admin.post("/{slug}/operations/{operation_slug}/test")
async def test_operation(
    slug: str,
    operation_slug: str,
    params: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """管理执行测试，复用调用服务。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError, ConnectorApprovalRequired

    _validate_slug(slug)
    _validate_slug(operation_slug)

    service = get_connector_service()
    try:
        from yuxi.services.connectors.base import ConnectorExecution
        import uuid

        execution = ConnectorExecution(
            invocation_id=str(uuid.uuid4()),
            actor_uid=admin.uid,
            consumer_type="admin_test",
            logical_call_key=f"test:{slug}:{operation_slug}:{uuid.uuid4().hex[:8]}",
            connector_revision=0,
            operation_revision=0,
        )
        result = await service.prepare_and_execute(slug, operation_slug, params, execution=execution)
        return {"success": True, "data": result}
    except ConnectorApprovalRequired:
        raise HTTPException(403, detail="写操作需要审批，管理测试不支持审批流程")
    except ConnectorServiceError as exc:
        raise HTTPException(400, detail=exc.code)
    except Exception as exc:
        logger.warning(f"操作测试失败 slug={slug} op={operation_slug}: {exc}")
        raise HTTPException(500, detail="测试执行失败")


@connectors_admin.get("/{slug}/usage")
async def get_usage(
    slug: str,
    status: str | None = None,
    actor_uid: str | None = None,
    workflow_run_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """分页、状态/actor/run 过滤的调用记录；脱敏摘要。"""
    from yuxi.repositories.connector_repository import ConnectorRepository
    from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

    _validate_slug(slug)
    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None:
        raise HTTPException(404, detail=f"连接器不存在: {slug}")

    exec_repo = ConnectorExecutionRepository(db)
    items, total = await exec_repo.list_usage(
        connector_id=connector.id,
        status=status,
        actor_uid=actor_uid,
        workflow_run_id=workflow_run_id,
        limit=limit,
        offset=offset,
    )
    return {
        "success": True,
        "data": [_invocation_to_dict(inv) for inv in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@connectors_admin.post("/invocations/{invocation_id}/reconcile")
async def reconcile_invocation(
    invocation_id: str,
    body: ReconcileBody,
    admin: User = Depends(get_admin_user),
):
    """unknown 调用的人工核对；证据与原因必填。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    service = get_connector_service()
    try:
        result = await service.reconcile_invocation(
            invocation_id,
            body.resolution,
            actor=admin.uid,
            reason=body.reason,
        )
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        status_code = 404 if exc.code == "not_found" else 400
        raise HTTPException(status_code, detail=exc.code)


# ══════════════════════════════════════════════════════════════
# 消费端 /api/connectors
# ══════════════════════════════════════════════════════════════


@connectors_user.get("")
async def list_user_connectors(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """当前用户可用 enabled 连接器目录，仅显示必要元数据。"""
    from yuxi.repositories.connector_repository import ConnectorRepository

    repo = ConnectorRepository(db)
    connectors = await repo.list_usable(uid=current_user.uid, department_ids=None)
    data = []
    for c in connectors:
        data.append({
            "slug": c.slug,
            "name": c.name,
            "connector_type": c.connector_type,
            "description": c.description,
        })
    return {"success": True, "data": data}


@connectors_user.get("/{slug}/operations")
async def list_user_operations(
    slug: str,
    operation_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """当前用户可执行操作 schema 与审批说明。"""
    from yuxi.repositories.connector_repository import ConnectorRepository

    _validate_slug(slug)
    repo = ConnectorRepository(db)
    connector = await repo.get_by_slug(slug)
    if connector is None or not connector.enabled:
        raise HTTPException(404, detail=f"连接器不存在或已停用: {slug}")

    operations = await repo.list_usable_operations(
        connector, uid=current_user.uid, department_ids=None, operation_type=operation_type,
    )
    return {
        "success": True,
        "data": [
            {
                "slug": op.slug,
                "name": op.name,
                "operation_type": op.operation_type,
                "request_schema": op.request_schema,
                "approval_policy": op.approval_policy,
                "description": op.description,
            }
            for op in operations
        ],
    }


@connectors_user.get("/invocations/{invocation_id}")
async def get_user_invocation(
    invocation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """本人且绑定可见 run 的调用结果/审批状态。"""
    from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

    exec_repo = ConnectorExecutionRepository(db)
    invocation = await exec_repo.get_invocation(invocation_id)
    if invocation is None:
        raise HTTPException(404, detail="调用不存在")
    if invocation.actor_uid != current_user.uid:
        raise HTTPException(403, detail="无权查看此调用")

    return {"success": True, "data": _invocation_to_dict(invocation)}


@connectors_user.post("/invocations/{invocation_id}/decision")
async def decide_invocation(
    invocation_id: str,
    body: DecisionBody,
    current_user: User = Depends(get_required_user),
):
    """审批或拒绝调用。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    service = get_connector_service()
    try:
        result = await service.decide_invocation(
            invocation_id,
            body.decision,
            actor=current_user.uid,
            expected_digest=body.expected_digest,
        )
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        if exc.code == "not_found":
            raise HTTPException(404, detail=exc.code)
        if exc.code == "conflict":
            raise HTTPException(409, detail=exc.code)
        raise HTTPException(400, detail=exc.code)
