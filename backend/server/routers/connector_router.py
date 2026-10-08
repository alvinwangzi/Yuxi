"""连接器管理 API 与消费 API。

管理端（管理员）：``/api/system/connectors`` — 配置、凭据、操作、测试、用量与核对。
消费端（登录用户）：``/api/connectors`` — 可见目录、操作 schema、调用结果与审批决定。

路由不持有 session 或 service；每次请求通过 ``get_db`` 获取短事务，
调用服务或 repository 完成后 commit。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Header
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.storage.postgres.models_business import User
from yuxi.utils import logger
from yuxi.services.connectors.dto import connector_response, operation_response, invocation_response

connectors_admin = APIRouter(prefix="/system/connectors", tags=["connectors-admin"])
connectors_user = APIRouter(prefix="/connectors", tags=["connectors"])

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_SLUG_LENGTH = 64


def _validate_slug(slug: str) -> str:
    if not slug or not _SLUG_PATTERN.match(slug):
        raise HTTPException(422, detail=f"slug 格式无效: {slug}")
    return slug


# ── Pydantic 请求体 ──


class ConnectorCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    connector_type: str = Field(..., min_length=1, max_length=64)
    enabled: bool = True
    description: str | None = None
    config: dict | None = None
    read_scope: dict | None = None
    write_scope: dict | None = None
    operations: list[dict] | None = None
    credentials: dict[str, str] | None = None


class CredentialChangesBody(BaseModel):
    """配置保存可附带同事务凭据变更，响应始终不回填秘密值。"""

    model_config = ConfigDict(extra="forbid")
    upsert: dict[str, str] | None = None
    delete_keys: list[str] | None = None


class ConnectorPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    config: dict | None = None
    read_scope: dict | None = None
    write_scope: dict | None = None
    enabled: bool | None = None
    credential_patch: CredentialChangesBody = Field(default_factory=CredentialChangesBody)


class CredentialPatchBody(CredentialChangesBody):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(..., ge=1)
    enabled: bool | None = None


class OperationCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(..., ge=1)
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
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(..., pattern="^(approve|reject)$")
    expected_digest: str = Field(..., min_length=1, max_length=128)


class ReconcileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(..., pattern="^(succeeded|failed)$")
    reason: str = Field(..., min_length=1, max_length=2000)
    result: Any = None


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
    from yuxi.services.connectors.vault_readiness import get_connector_vault_status

    return {"success": True, "data": types, "vault": await get_connector_vault_status()}


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
        if search and all(search.lower() not in (value or "").lower() for value in (c.name, c.slug, c.description)):
            continue
        filtered.append(c)

    total = len(filtered)
    page = filtered[offset : offset + limit]
    return {
        "success": True,
        "data": [connector_response(c) for c in page],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@connectors_admin.post("")
async def create_connector(
    body: ConnectorCreateBody,
    admin: User = Depends(get_admin_user),
):
    """管理事务与校验由共用服务拥有。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().create_connector(body.model_dump(exclude_unset=True), actor=admin.uid)
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        code = {"not_found": 404, "conflict": 409, "authorization_error": 403}.get(exc.code, 422)
        raise HTTPException(
            code, detail={"code": exc.code, "message": "连接器管理请求未通过校验，请刷新配置后重试"}
        ) from None


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

    data = connector_response(connector, include_credentials=True)
    data["operations"] = [
        operation_response(op, connector_type=connector.connector_type) for op in (connector.operations or [])
    ]
    return {"success": True, "data": data}


@connectors_admin.patch("/{slug}")
async def update_connector(
    slug: str,
    body: ConnectorPatchBody,
    admin: User = Depends(get_admin_user),
):
    """管理事务与校验由共用服务拥有。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().update_connector(
            slug, body.model_dump(exclude_unset=True), actor=admin.uid
        )
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        code = {"not_found": 404, "conflict": 409, "authorization_error": 403}.get(exc.code, 422)
        raise HTTPException(
            code, detail={"code": exc.code, "message": "连接器管理请求未通过校验，请刷新配置后重试"}
        ) from None


@connectors_admin.post("/{slug}/metadata")
async def discover_metadata(slug: str, admin: User = Depends(get_admin_user)):
    """配置消费者只读发现当前 Base 的表和字段，授权仍由服务复核。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().discover_connector_metadata(slug, actor=admin.uid)
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        raise HTTPException(
            {"not_found": 404, "authorization_error": 403, "timeout": 504}.get(exc.code, 422), detail=exc.code
        ) from None


@connectors_admin.delete("/{slug}")
async def delete_connector(
    slug: str,
    admin: User = Depends(get_admin_user),
):
    """服务统一拥有管理校验、版本与删除证据边界。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().delete_connector(slug, actor=admin.uid)
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        code = {"not_found": 404, "conflict": 409, "authorization_error": 403}.get(exc.code, 422)
        raise HTTPException(
            code, detail={"code": exc.code, "message": "连接器管理请求未通过校验，请刷新配置后重试"}
        ) from None


@connectors_admin.patch("/{slug}/credentials")
async def update_credentials(
    slug: str,
    body: CredentialPatchBody,
    admin: User = Depends(get_admin_user),
):
    """管理事务与校验由共用服务拥有。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().update_connector_credentials(
            slug, body.model_dump(exclude_unset=True), actor=admin.uid
        )
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        code = {"not_found": 404, "conflict": 409, "authorization_error": 403}.get(exc.code, 422)
        raise HTTPException(
            code, detail={"code": exc.code, "message": "连接器管理请求未通过校验，请刷新配置后重试"}
        ) from None


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
        result = await service.test_connector(slug, actor=admin.uid)
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

    ops = [operation_response(op, connector_type=connector.connector_type) for op in (connector.operations or [])]
    return {"success": True, "data": ops}


@connectors_admin.post("/{slug}/operations")
async def create_operation(
    slug: str,
    body: OperationCreateBody,
    admin: User = Depends(get_admin_user),
):
    """服务统一拥有管理校验、版本与删除证据边界。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().create_connector_operation(
            slug, body.model_dump(exclude_unset=True), actor=admin.uid
        )
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        code = {"not_found": 404, "conflict": 409, "authorization_error": 403}.get(exc.code, 422)
        raise HTTPException(
            code, detail={"code": exc.code, "message": "连接器管理请求未通过校验，请刷新配置后重试"}
        ) from None


@connectors_admin.patch("/{slug}/operations/{operation_slug}")
async def update_operation(
    slug: str,
    operation_slug: str,
    body: OperationPatchBody,
    admin: User = Depends(get_admin_user),
):
    """服务统一拥有管理校验、版本与删除证据边界。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().update_connector_operation(
            slug, operation_slug, body.model_dump(exclude_unset=True), actor=admin.uid
        )
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        code = {"not_found": 404, "conflict": 409, "authorization_error": 403}.get(exc.code, 422)
        raise HTTPException(
            code, detail={"code": exc.code, "message": "连接器管理请求未通过校验，请刷新配置后重试"}
        ) from None


@connectors_admin.delete("/{slug}/operations/{operation_slug}")
async def delete_operation(
    slug: str,
    operation_slug: str,
    admin: User = Depends(get_admin_user),
):
    """服务统一拥有管理校验、版本与删除证据边界。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().delete_connector_operation(slug, operation_slug, actor=admin.uid)
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        code = {"not_found": 404, "conflict": 409, "authorization_error": 403}.get(exc.code, 422)
        raise HTTPException(
            code, detail={"code": exc.code, "message": "连接器管理请求未通过校验，请刷新配置后重试"}
        ) from None


@connectors_admin.post("/{slug}/operations/{operation_slug}/test")
async def test_operation(
    slug: str,
    operation_slug: str,
    params: dict = Body(default={}),
    admin: User = Depends(get_admin_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """管理执行测试，复用调用服务。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError, ConnectorApprovalRequired

    _validate_slug(slug)
    _validate_slug(operation_slug)

    service = get_connector_service()
    try:
        result = await service.test_operation_invocation(
            slug, operation_slug, params, actor=admin.uid, idempotency_key=idempotency_key
        )
        return {"success": True, "data": result}
    except ConnectorApprovalRequired as exc:
        raise HTTPException(
            409,
            detail={
                "code": "approval_required",
                "invocation_id": exc.invocation_id,
                "request_digest": exc.digest,
                "request_summary": exc.summary,
            },
        ) from None
    except ConnectorServiceError as exc:
        raise HTTPException(
            {"conflict": 409, "authorization_error": 403, "not_found": 404, "invalid_params": 422}.get(exc.code, 400),
            detail=exc.code,
        ) from None
    except Exception as exc:
        logger.warning(f"操作测试失败 slug={slug} op={operation_slug}: type={type(exc).__name__}")
        raise HTTPException(500, detail="测试执行失败")


@connectors_admin.get("/{slug}/usage")
async def get_usage(
    slug: str,
    status: str | None = None,
    actor_uid: str | None = None,
    workflow_run_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """按分页、状态、调用方及带时区日期范围读取脱敏调用记录。"""
    from yuxi.repositories.connector_repository import ConnectorRepository
    from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

    _validate_slug(slug)
    if any(value is not None and value.utcoffset() is None for value in (created_from, created_to)):
        raise HTTPException(422, detail="日期筛选必须包含时区")
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(422, detail="开始时间不能晚于结束时间")
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
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return {
        "success": True,
        "data": [invocation_response(inv) for inv in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@connectors_admin.get("/invocations/{invocation_id}")
async def get_management_invocation(invocation_id: str, admin: User = Depends(get_admin_user)):
    """管理详情的读授权与脱敏投影由服务拥有。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        result = await get_connector_service().get_management_invocation(invocation_id, actor=admin.uid)
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        raise HTTPException(404 if exc.code == "not_found" else 403, detail=exc.code) from None


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
        from yuxi.services.connectors.consumer_service import reconcile_consumer_invocation

        result = await reconcile_consumer_invocation(
            service,
            invocation_id,
            body.resolution,
            actor=admin.uid,
            reason=body.reason,
            result=body.result,
        )
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        status_code = {"not_found": 404, "authorization_error": 403, "conflict": 409}.get(exc.code, 422)
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
        data.append(
            {
                "slug": c.slug,
                "name": c.name,
                "connector_type": c.connector_type,
                "description": c.description,
            }
        )
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
        connector,
        uid=current_user.uid,
        department_ids=None,
        operation_type=operation_type,
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
    current_user: User = Depends(get_required_user),
):
    """本人且绑定可见 run 的调用结果/审批状态。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        data = await get_connector_service().get_user_invocation(invocation_id, actor=current_user.uid)
        return {"success": True, "data": data}
    except ConnectorServiceError as exc:
        raise HTTPException(404 if exc.code == "not_found" else 403, detail=exc.code) from None


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
        from yuxi.services.connectors.consumer_service import decide_consumer_invocation

        result = await decide_consumer_invocation(
            service,
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
        if exc.code == "authorization_error":
            raise HTTPException(403, detail=exc.code)
        raise HTTPException(403 if exc.code == "authorization_error" else 400, detail=exc.code)


@connectors_user.post("/invocations/{invocation_id}/cancel")
async def cancel_user_invocation(invocation_id: str, current_user: User = Depends(get_required_user)):
    """仅调用者取消本次调用，在途写不伪造未发送或失败。"""
    from yuxi.services.connectors.factory import get_connector_service
    from yuxi.services.connectors.service import ConnectorServiceError

    try:
        from yuxi.services.connectors.consumer_service import cancel_consumer_invocation

        result = await cancel_consumer_invocation(get_connector_service(), invocation_id, actor=current_user.uid)
        return {"success": True, "data": result}
    except ConnectorServiceError as exc:
        code = {"not_found": 404, "authorization_error": 403, "conflict": 409}.get(exc.code, 422)
        raise HTTPException(code, detail=exc.code) from None
