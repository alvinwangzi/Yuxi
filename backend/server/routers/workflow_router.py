"""工作流 API 路由。"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.services.workflow_service import submit_workflow_run
from yuxi.storage.postgres.models_business import User, Workflow, WorkflowRun, WorkflowStepRun
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.utils.logging_config import logger
from yuxi.workflows import STEP_TYPES
from yuxi.workflows.dag import validate_definition

workflow_router = APIRouter(prefix="/workflows", tags=["workflows"])


# ── 请求/响应模型 ──


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = None
    description: str = ""
    icon: str = "workflow"
    category: str | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    default_model_spec: dict[str, Any] | None = None


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    category: str | None = None
    definition: dict[str, Any] | None = None
    default_model_spec: dict[str, Any] | None = None


class WorkflowRunRequest(BaseModel):
    input_variables: dict[str, Any] = Field(default_factory=dict)


# ── 工具函数 ──


def _generate_slug(name: str) -> str:
    """从名称生成 URL 友好的 slug。"""
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "-", name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "workflow"


# ── CRUD ──


@workflow_router.get("")
async def list_workflows(
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取工作流列表。"""
    repo = WorkflowRepository(db)
    workflows = await repo.list_workflows(category=category, limit=limit, offset=offset)
    total = await repo.count_workflows(category=category)
    return {
        "success": True,
        "data": [w.to_dict() for w in workflows],
        "total": total,
    }


@workflow_router.post("")
async def create_workflow(
    payload: WorkflowCreateRequest,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """创建工作流。"""
    # 校验定义
    if payload.definition:
        errors = validate_definition(payload.definition)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})

    slug = payload.slug or _generate_slug(payload.name)

    repo = WorkflowRepository(db)
    existing = await repo.get_workflow_by_slug(slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"slug '{slug}' 已存在")

    workflow = Workflow(
        slug=slug,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        category=payload.category,
        definition=payload.definition or {"steps": [], "variables": [], "concurrency": 4},
        default_model_spec=payload.default_model_spec,
        created_by=str(user.uid),
    )
    await repo.create_workflow(workflow)
    return {"success": True, "data": workflow.to_dict()}


# ── 元信息（必须在 /{workflow_id} 之前注册，避免 "meta" 被当作 workflow_id） ──


@workflow_router.get("/meta/step-types")
async def get_step_types(
    user: User = Depends(get_required_user),
):
    """获取支持的步骤类型列表。"""
    return {
        "success": True,
        "data": [
            {"type": t, "description": desc}
            for t, desc in STEP_TYPES.items()
        ],
    }


# ── 执行（/runs/{run_id} 必须在 /{workflow_id} 之前注册） ──


@workflow_router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: int,
    payload: WorkflowRunRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """触发工作流执行。"""
    repo = WorkflowRepository(db)
    workflow = await repo.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    # 创建运行记录
    run = WorkflowRun(
        workflow_id=workflow.id,
        status="pending",
        trigger="manual",
        input_variables=payload.input_variables,
        created_by=str(user.uid),
    )
    await repo.create_run(run)

    # 提交到 ARQ 队列执行
    try:
        result = await submit_workflow_run(db, run.id)
        return {"success": True, "data": {**run.to_dict(), "queued": result.get("queued", False)}}
    except Exception as exc:
        logger.error(f"提交工作流执行失败: {exc}")
        # 标记为失败
        run.status = "failed"
        run.error_message = f"提交执行失败: {exc}"
        await repo.update_run(run)
        return {"success": True, "data": run.to_dict()}


@workflow_router.get("/runs/{run_id}")
async def get_workflow_run(
    run_id: int,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取运行详情。"""
    repo = WorkflowRepository(db)
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    step_runs = await repo.list_step_runs(run_id)
    return {
        "success": True,
        "data": {
            **run.to_dict(),
            "step_runs": [s.to_dict() for s in step_runs],
        },
    }


# ── 单条 CRUD（含路径参数，必须在固定路径之后注册） ──


@workflow_router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: int,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取工作流详情。"""
    repo = WorkflowRepository(db)
    workflow = await repo.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"success": True, "data": workflow.to_dict()}


@workflow_router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: int,
    payload: WorkflowUpdateRequest,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """更新工作流。"""
    repo = WorkflowRepository(db)
    workflow = await repo.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    # 校验新定义
    if payload.definition is not None:
        errors = validate_definition(payload.definition)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})

    if payload.name is not None:
        workflow.name = payload.name
    if payload.description is not None:
        workflow.description = payload.description
    if payload.icon is not None:
        workflow.icon = payload.icon
    if payload.category is not None:
        workflow.category = payload.category
    if payload.definition is not None:
        workflow.definition = payload.definition
    if payload.default_model_spec is not None:
        workflow.default_model_spec = payload.default_model_spec

    workflow.updated_by = str(user.uid)
    await repo.update_workflow(workflow)
    return {"success": True, "data": workflow.to_dict()}


@workflow_router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """删除工作流。"""
    repo = WorkflowRepository(db)
    workflow = await repo.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    if workflow.is_builtin:
        raise HTTPException(status_code=403, detail="内置工作流不可删除")

    await repo.delete_workflow(workflow)
    return {"success": True}
