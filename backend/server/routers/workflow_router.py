"""工作流 API 路由。"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.repositories.category_repository import CategoryRepository
from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.repositories.agent_repository import AgentRepository, DEFAULT_SHARE_CONFIG
from yuxi.services.workflow_service import submit_workflow_run
from yuxi.storage.postgres.models_business import Agent, User, Workflow, WorkflowRun, WorkflowStepRun
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.utils.logging_config import logger
from yuxi.workflows import STEP_TYPES
from yuxi.workflows.dag import validate_definition

workflow_router = APIRouter(prefix="/workflows", tags=["workflows"])


def _is_normalized_role_slug(slug: str) -> bool:
    """判断 slug 是否为角色模板的规范化格式（分类名重复，如 product-product-manager）。"""
    parts = slug.split('-', 2)
    return len(parts) >= 2 and parts[0] == parts[1]


def _slug_to_role_key(slug: str) -> str:
    """将规范化 slug 转换为角色模板 role_key（product-product-manager → product/product-manager）。"""
    parts = slug.split('-', 2)
    if len(parts) >= 2 and parts[0] == parts[1]:
        # 分类名重复：product-product-manager → product/product-manager
        return f"{parts[0]}/{parts[1]}-{parts[2]}" if len(parts) == 3 else f"{parts[0]}/{parts[1]}"
    return slug


async def _resolve_agent_category_id(agent_slug: str, db: AsyncSession) -> int | None:
    """从 agent slug 提取分类 slug 并查找对应的 agent 分类 ID。
    
    支持两种格式：
    - 角色模板格式：product/product-manager → category_slug = 'product'
    - 规范化格式：product-product-manager → category_slug = 'product'（取第一段）
    """
    category_slug = None
    if '/' in agent_slug:
        # 角色模板原始格式：product/product-manager
        category_slug = agent_slug.split('/', 1)[0]
    else:
        # 规范化格式：product-product-manager（分类名重复一次）
        parts = agent_slug.split('-', 2)
        if len(parts) >= 2 and parts[0] == parts[1]:
            # 分类名重复：product-product-manager → product
            category_slug = parts[0]
        elif len(parts) >= 1:
            # 兜底：取第一段
            category_slug = parts[0]
    
    if not category_slug:
        return None
    
    cat_repo = CategoryRepository(db)
    cat = await cat_repo.get_by_slug('agent', category_slug)
    return cat.id if cat else None


# ── 请求/响应模型 ──


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = None
    description: str = ""
    icon: str = "workflow"
    category: str | None = None
    category_id: int | None = None
    definition: dict[str, Any] = Field(default_factory=dict)
    default_model_spec: dict[str, Any] | None = None
    scope: str = "personal"
    department_id: int | None = None


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    category: str | None = None
    category_id: int | None = None
    definition: dict[str, Any] | None = None
    default_model_spec: dict[str, Any] | None = None
    scope: str | None = None
    department_id: int | None = None


class WorkflowCategoryUpdate(BaseModel):
    category_id: int | None = None


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
    category_id: int | None = None,
    scope: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取工作流列表。"""
    repo = WorkflowRepository(db)
    workflows = await repo.list_workflows(category=category, category_id=category_id, scope=scope, limit=limit, offset=offset)
    total = await repo.count_workflows(category=category, category_id=category_id, scope=scope)
    return {
        "success": True,
        "data": [w.to_dict() for w in workflows],
        "total": total,
    }


@workflow_router.get("/selectable")
async def list_selectable_workflows(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户可选择的工作流列表（用于定时任务等下拉选择）。
    
    管理员：返回所有非平台工作流
    普通用户：返回公司级 + 自己的个人级工作流
    """
    from sqlalchemy import or_
    
    repo = WorkflowRepository(db)
    
    if user.role in ("admin", "superadmin"):
        # 管理员看所有非平台工作流
        workflows = await repo.list_workflows(limit=200)
        # 过滤掉平台工作流
        workflows = [w for w in workflows if w.scope != "platform"]
    else:
        # 普通用户：公司级 + 自己的个人级
        stmt = select(Workflow).where(
            or_(
                Workflow.scope == "company",
                (Workflow.scope == "personal") & (Workflow.created_by == str(user.uid))
            )
        ).order_by(Workflow.updated_at.desc()).limit(200)
        result = await db.execute(stmt)
        workflows = list(result.scalars().all())
    
    return {
        "success": True,
        "data": [w.to_dict() for w in workflows],
    }


@workflow_router.get("/stats")
async def get_workflow_stats(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取工作流统计数据（用于页面头部徽章）。"""
    from sqlalchemy import select, func

    repo = WorkflowRepository(db)
    # 管理员看全部，非管理员只看公司级 + 个人级（自己的）
    if user.role in ("admin", "superadmin"):
        total = await repo.count_workflows()
        platform_q = select(func.count(Workflow.id)).where(Workflow.scope == "platform")
        platform = (await db.execute(platform_q)).scalar() or 0
        company_q = select(func.count(Workflow.id)).where(Workflow.scope == "company")
        company = (await db.execute(company_q)).scalar() or 0
        personal_q = select(func.count(Workflow.id)).where(Workflow.scope == "personal")
        personal = (await db.execute(personal_q)).scalar() or 0
    else:
        # 非管理员：公司级 + 自己的个人级
        company_q = select(func.count(Workflow.id)).where(Workflow.scope == "company")
        company = (await db.execute(company_q)).scalar() or 0
        personal_q = select(func.count(Workflow.id)).where(
            Workflow.scope == "personal", Workflow.created_by == str(user.uid)
        )
        personal = (await db.execute(personal_q)).scalar() or 0
        total = company + personal
        platform = 0

    return {
        "success": True,
        "data": {
            "total": total,
            "platform": platform,
            "company": company,
            "personal": personal,
        },
    }


@workflow_router.get("/platform")
async def list_platform_workflows(
    category_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取平台工作流库（scope=platform 的工作流）。"""
    from sqlalchemy import select, func
    from yuxi.storage.postgres.models_business import CustomCategory

    repo = WorkflowRepository(db)
    workflows = await repo.list_workflows(category_id=category_id, limit=limit, offset=offset)
    # 过滤出平台工作流（scope='platform'）
    platform_wfs = [w for w in workflows if w.scope == 'platform']
    total = len(platform_wfs)
    return {
        "success": True,
        "data": [w.to_dict() for w in platform_wfs],
        "total": total,
    }


@workflow_router.post("")
async def create_workflow(
    payload: WorkflowCreateRequest,
    user: User = Depends(get_required_user),
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
        category_id=payload.category_id,
        scope=payload.scope,
        department_id=payload.department_id,
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


# ── 脚本测试（必须在 /{workflow_id} 之前注册） ──


class ScriptTestRequest(BaseModel):
    code: str = Field(..., min_length=1)
    language: str = "javascript"
    test_context: dict[str, Any] = Field(default_factory=dict)


@workflow_router.post("/test-script")
async def test_script(
    payload: ScriptTestRequest,
    user: User = Depends(get_required_user),
):
    """测试运行 JavaScript 脚本（不持久化，纯沙盒执行）。"""
    from yuxi.workflows.executors.script_executor import ScriptStepExecutor

    executor = ScriptStepExecutor()
    step_data = {
        "code": payload.code,
        "language": payload.language,
        "timeout": 10,
    }
    try:
        result = await executor.execute(step_data, payload.test_context)
        return {"success": True, "data": {"result": result}}
    except Exception as exc:
        return {"success": True, "data": {"error": str(exc)}}


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

    # 防止并发运行：检查是否已有 pending/running 状态的运行记录
    active_run = await repo.get_active_run(workflow.id)
    if active_run:
        raise HTTPException(
            status_code=409,
            detail=f"工作流正在运行中（run_id={active_run.id}，状态={active_run.status}），请等待完成后再次提交",
        )

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


@workflow_router.post("/runs/{run_id}/cancel")
async def cancel_workflow_run(
    run_id: int,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """强制终止卡住的工作流运行。

    仅当运行处于非终态（pending / running）时允许操作；
    将运行记录和所有未完成的步骤运行标记为 failed。
    """
    repo = WorkflowRepository(db)
    run = await repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"运行已终结（当前状态: {run.status}），无法取消")

    # 标记所有未完成的 step_runs 为 failed
    step_runs = await repo.list_step_runs(run_id)
    for sr in step_runs:
        if sr.status in ("pending", "running"):
            sr.status = "failed"
            sr.error_message = "用户手动强制关闭"
            await repo.update_step_run(sr)

    # 标记主运行为 failed
    run.status = "failed"
    run.error_message = "用户手动强制关闭"
    run.completed_at = utc_now_naive()
    await repo.update_run(run)
    await db.commit()

    return {"success": True, "data": {"id": run.id, "status": run.status}}


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


@workflow_router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: int,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取工作流运行历史。"""
    repo = WorkflowRepository(db)
    workflow = await repo.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    runs = await repo.list_runs(workflow_id, limit=50)
    return {
        "success": True,
        "data": [r.to_dict() for r in runs],
    }


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
    if payload.category_id is not None:
        workflow.category_id = payload.category_id
    if payload.scope is not None:
        workflow.scope = payload.scope
    if payload.department_id is not None:
        workflow.department_id = payload.department_id
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
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """删除工作流。"""
    repo = WorkflowRepository(db)
    workflow = await repo.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    # 平台工作流不可删除
    if workflow.scope == 'platform':
        raise HTTPException(status_code=403, detail="平台工作流不可删除")

    # 公司工作流仅管理员可删除
    if workflow.scope == 'company' and user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="无权限删除公司工作流")

    # 个人工作流仅创建者可删除
    if workflow.scope == 'personal' and workflow.created_by != str(user.uid):
        raise HTTPException(status_code=403, detail="无权限删除他人的工作流")

    await repo.delete_workflow(workflow)
    return {"success": True}


@workflow_router.put("/{workflow_id}/category")
async def update_workflow_category(
    workflow_id: int,
    payload: WorkflowCategoryUpdate,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """更新工作流所属分类（仅管理员）。"""
    cat_repo = CategoryRepository(db)
    if payload.category_id is not None:
        category = await cat_repo.get_by_id(payload.category_id)
        if not category:
            raise HTTPException(status_code=404, detail="分类不存在")

    repo = WorkflowRepository(db)
    workflow = await repo.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    workflow.category_id = payload.category_id
    await repo.update_workflow(workflow)
    return {"success": True, "data": workflow.to_dict()}


# ── Agent 自动检测与创建 ─


class WorkflowAgentCheckRequest(BaseModel):
    """检查工作流定义中引用的 Agent 是否存在。"""
    definition: dict[str, Any] = Field(default_factory=dict)


class WorkflowAgentCreateRequest(BaseModel):
    """批量创建工作流中缺失的 Agent。"""
    definition: dict[str, Any] = Field(default_factory=dict)
    agent_slugs: list[str] = Field(default_factory=list)


@workflow_router.post("/check-agents")
async def check_workflow_agents(
    payload: WorkflowAgentCheckRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """检查工作流 definition 中引用的 agent_slug，返回缺失列表。"""
    from yuxi.repositories.role_template_repository import RoleTemplateRepository

    steps = payload.definition.get("steps", [])
    referenced_slugs = []
    for step in steps:
        slug = step.get("agent_slug", "")
        if slug and slug not in referenced_slugs:
            referenced_slugs.append(slug)

    if not referenced_slugs:
        return {"success": True, "data": {"missing": [], "existing": []}}

    agent_repo = AgentRepository(db)
    role_repo = RoleTemplateRepository(db)
    missing = []
    existing = []
    for slug in referenced_slugs:
        # 判断是否为角色模板格式（含 / 或分类名重复的 - 格式）
        is_role_template = '/' in slug or _is_normalized_role_slug(slug)
        
        if is_role_template:
            # 规范化 slug（/ → -）
            normalized = slug.replace('/', '-') if '/' in slug else slug
            agent = await agent_repo.get_by_slug(normalized)
            if agent:
                existing.append({"slug": slug, "name": agent.name})
                continue
            # 尝试用原始 role_key 查找（含 / 的格式）
            role_key = slug if '/' in slug else _slug_to_role_key(slug)
            role_template = await role_repo.get_by_role_key(role_key)
            if role_template:
                missing.append({"slug": slug, "name": role_template.name, "reason": "Agent 未创建"})
            else:
                missing.append({"slug": slug, "name": slug, "reason": "角色模板不存在"})
            continue

        agent = await agent_repo.get_by_slug(slug)
        if agent:
            existing.append({"slug": slug, "name": agent.name})
        else:
            # 从 slug 生成友好名称
            name = slug.replace("-", " ").replace("_", " ").title()
            missing.append({"slug": slug, "name": name})

    return {"success": True, "data": {"missing": missing, "existing": existing}}


@workflow_router.post("/create-missing-agents")
async def create_missing_agents(
    payload: WorkflowAgentCreateRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """批量创建工作流中缺失的 Agent。"""
    from yuxi.repositories.role_template_repository import RoleTemplateRepository

    created = []
    skipped = []
    failed = []
    agent_repo = AgentRepository(db)
    role_repo = RoleTemplateRepository(db)

    for slug in payload.agent_slugs:
        # 判断是否为角色模板格式
        is_role_template = '/' in slug or _is_normalized_role_slug(slug)
        
        if is_role_template:
            # 规范化 slug（/ → -）
            normalized_slug = slug.replace('/', '-') if '/' in slug else slug
            # 获取 role_key（用于查找角色模板）
            role_key = slug if '/' in slug else _slug_to_role_key(slug)
            role_template = await role_repo.get_by_role_key(role_key)
            if not role_template:
                failed.append({"slug": slug, "name": slug, "reason": "角色模板不存在"})
                continue

            # 检查是否已存在（用规范化后的 slug）
            existing = await agent_repo.get_by_slug(normalized_slug)
            if existing:
                skipped.append({"slug": slug, "reason": f"已存在（{role_template.name}）"})
                continue

            try:
                category_id = await _resolve_agent_category_id(slug, db)
                agent = Agent(
                    slug=normalized_slug,
                    backend_id="ChatbotAgent",
                    name=role_template.name,
                    description="从角色模板自动创建的 Agent",
                    config_json={"context": {"system_prompt": role_template.content or ""}},
                    share_config=DEFAULT_SHARE_CONFIG.copy(),
                    pics=[],
                    category_id=category_id,
                    created_by=str(user.uid),
                    updated_by=str(user.uid),
                    created_at=utc_now_naive(),
                    updated_at=utc_now_naive(),
                )
                db.add(agent)
                await db.commit()
                created.append({"slug": normalized_slug, "name": role_template.name, "id": agent.id})
            except Exception as e:
                logger.warning(f"从角色模板创建 Agent {slug} 失败：{e}")
                failed.append({"slug": slug, "name": role_template.name, "reason": str(e)})
            continue

        # 普通 slug：检查是否已存在
        existing = await agent_repo.get_by_slug(slug)
        if existing:
            skipped.append({"slug": slug, "reason": "已存在"})
            continue

        # 从 slug 生成名称
        name = slug.replace("-", " ").replace("_", " ").title()

        try:
            agent = Agent(
                slug=slug,
                backend_id="ChatbotAgent",
                name=name,
                description=f"从工作流自动创建的 Agent（{name}）",
                share_config=DEFAULT_SHARE_CONFIG.copy(),
                pics=[],
                created_by=str(user.uid),
                updated_by=str(user.uid),
                created_at=utc_now_naive(),
                updated_at=utc_now_naive(),
            )
            db.add(agent)
            await db.commit()
            created.append({"slug": slug, "name": name, "id": agent.id})
        except Exception as e:
            logger.warning(f"创建 Agent {slug} 失败：{e}")
            failed.append({"slug": slug, "name": name, "reason": str(e)})

    return {"success": True, "data": {"created": created, "skipped": skipped, "failed": failed}}


class WorkflowImportRequest(BaseModel):
    """从平台工作流库导入工作流。"""
    workflow_id: int


# 平台工作流名称中英文映射（导入时自动翻译为中文）
WORKFLOW_NAME_CN_MAP = {
    "OKR Decomposition": "OKR 拆解",
    "Content Creation Pipeline": "内容创作流水线",
    "Codex + Claude Code Collaboration": "Codex + Claude Code 协作编程",
    "Investment Target Analysis": "投资标的分析",
    "Legal Consultation Opinion": "法律咨询意见书",
    "Test Workflow": "测试工作流",
}


def _translate_workflow_name(name: str) -> str:
    """将工作流名称翻译为中文（如有映射），否则保持原名。"""
    # 如果名称已经是中文，直接返回
    if any('\u4e00' <= c <= '\u9fff' for c in name):
        return name
    # 尝试从映射表查找
    return WORKFLOW_NAME_CN_MAP.get(name, name)


@workflow_router.post("/import")
async def import_platform_workflow(
    payload: WorkflowImportRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """从平台工作流库导入一个工作流为用户的个人副本。导入时自动创建工作流引用的 Agent。"""
    from yuxi.repositories.role_template_repository import RoleTemplateRepository

    repo = WorkflowRepository(db)
    source = await repo.get_workflow(payload.workflow_id)
    if not source:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if source.scope != 'platform':
        raise HTTPException(status_code=400, detail="只能导入平台工作流")

    # 生成新 slug（加用户 uid 后缀避免冲突）
    base_slug = _generate_slug(source.name)
    slug = f"{base_slug}-{str(user.uid)[:8]}"

    # 检查 slug 是否已存在
    existing = await repo.get_workflow_by_slug(slug)
    if existing:
        raise HTTPException(status_code=409, detail="该工作流已导入过")

    # 翻译名称为中文
    cn_name = _translate_workflow_name(source.name)

    # 自动创建工作流引用的 Agent（从角色模板）
    agent_repo = AgentRepository(db)
    role_repo = RoleTemplateRepository(db)
    created_agents = []
    definition = source.definition if isinstance(source.definition, dict) else {}
    for step in definition.get('steps', []):
        agent_slug = step.get('agent_slug', '')
        if not agent_slug:
            continue
        # 判断是否为角色模板格式
        is_role_template = '/' in agent_slug or _is_normalized_role_slug(agent_slug)
        if not is_role_template:
            continue
        # 规范化 slug（/ → -）
        normalized_slug = agent_slug.replace('/', '-') if '/' in agent_slug else agent_slug
        # 检查是否已存在
        if await agent_repo.get_by_slug(normalized_slug):
            continue
        # 获取 role_key（用于查找角色模板）
        role_key = agent_slug if '/' in agent_slug else _slug_to_role_key(agent_slug)
        role_template = await role_repo.get_by_role_key(role_key)
        if not role_template:
            continue
        try:
            category_id = await _resolve_agent_category_id(agent_slug, db)
            agent = Agent(
                slug=normalized_slug,
                backend_id="ChatbotAgent",
                name=role_template.name,
                description="从工作流导入时自动创建的 Agent",
                config_json={"context": {"system_prompt": role_template.content or ""}},
                share_config=DEFAULT_SHARE_CONFIG.copy(),
                pics=[],
                category_id=category_id,
                created_by=str(user.uid),
                updated_by=str(user.uid),
                created_at=utc_now_naive(),
                updated_at=utc_now_naive(),
            )
            db.add(agent)
            await db.commit()
            created_agents.append({"slug": normalized_slug, "name": role_template.name})
        except Exception as e:
            logger.warning(f"导入工作流时自动创建 Agent {agent_slug} 失败：{e}")

    workflow = Workflow(
        slug=slug,
        name=cn_name,
        description=source.description,
        icon=source.icon,
        definition=source.definition,
        category_id=source.category_id,
        scope="personal",
        is_builtin=False,
        created_by=str(user.uid),
    )
    await repo.create_workflow(workflow)
    return {"success": True, "data": workflow.to_dict(), "created_agents": created_agents}
