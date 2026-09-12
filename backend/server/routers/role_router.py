"""角色模板库 API 路由（数据库驱动）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.repositories.agent_repository import AgentRepository
from yuxi.repositories.category_repository import CategoryRepository
from yuxi.repositories.role_template_repository import RoleTemplateRepository
from yuxi.storage.postgres.models_business import User
from yuxi.utils.logging_config import logger

role_router = APIRouter(prefix="/roles", tags=["roles"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class UpdateCategoryRequest(BaseModel):
    category_id: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@role_router.get("")
async def get_roles(
    category_id: int | None = None,
    offset: int = 0,
    limit: int = 50,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取角色模板列表（支持分页，可选分类过滤）。"""
    repo = RoleTemplateRepository(db)
    deleted_keys = await repo.get_deleted_role_keys()

    templates, total = await repo.list_all(category_id=category_id, offset=offset, limit=limit)

    # 过滤已软删除的模板（分页后总数需排除已删除项）
    items = [t.to_dict() for t in templates if t.role_key not in deleted_keys]

    # 各分类的角色数（排除已删除，基于全量数据计算）
    all_templates, _ = await repo.list_all()
    category_counts: dict[int, int] = {}
    for t in all_templates:
        if t.role_key not in deleted_keys:
            category_counts[t.category_id] = category_counts.get(t.category_id, 0) + 1

    return {
        "success": True,
        "data": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "category_counts": category_counts,
    }


@role_router.get("/categories")
async def get_categories(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取角色模板分类列表（含各分类下的模板数量）。"""
    cat_repo = CategoryRepository(db)
    tpl_repo = RoleTemplateRepository(db)

    categories = await cat_repo.list_by_entity_type("role_template")
    counts = await tpl_repo.get_category_counts()

    data = [
        {
            "id": c.id,
            "slug": c.slug,
            "label": c.label,
            "sort_order": c.sort_order,
            "is_builtin": c.is_builtin,
            "count": counts.get(c.id, 0),
        }
        for c in categories
    ]

    return {
        "success": True,
        "data": data,
    }


@role_router.get("/{category}/{role_id:path}")
async def get_role_detail(
    category: str,
    role_id: str = Path(..., description="角色模板标识"),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取角色模板详情。"""
    role_key = f"{category}/{role_id}"

    repo = RoleTemplateRepository(db)
    if await repo.is_role_deleted(role_key):
        raise HTTPException(status_code=404, detail="角色不存在")

    template = await repo.get_by_role_key(role_key)
    if not template:
        raise HTTPException(status_code=404, detail="角色不存在")

    return {
        "success": True,
        "data": template.to_dict(include_content=True),
    }


@role_router.post("/{category}/{role_id:path}/import")
async def import_role_as_agent(
    category: str,
    role_id: str = Path(..., description="角色模板标识"),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """将角色导入为 Agent。

    所有登录用户均可导入，创建一个使用 ChatbotAgent 后端的 Agent，
    系统 prompt 为角色的完整内容，归属当前用户。
    """
    role_key = f"{category}/{role_id}"

    repo = RoleTemplateRepository(db)
    if await repo.is_role_deleted(role_key):
        raise HTTPException(status_code=404, detail="角色不存在")

    template = await repo.get_by_role_key(role_key)
    if not template:
        raise HTTPException(status_code=404, detail="角色不存在")

    prompt = template.content
    if not prompt:
        raise HTTPException(status_code=500, detail="无法读取角色 prompt")

    # 生成每用户唯一的 slug，避免多用户导入同一角色冲突
    slug = f"role-{role_key.replace('/', '-')}-{user.uid}"

    role_data = template.to_dict()

    agent_repo = AgentRepository(db)
    try:
        agent = await agent_repo.create(
            name=template.name,
            slug=slug,
            backend_id="ChatbotAgent",
            description=template.description or f"从角色模板导入: {template.name}",
            icon=template.icon or "👤",
            config_json={"context": {"system_prompt": prompt}},
            created_by=str(user.uid),
            creator=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    logger.info(f"已导入角色为 Agent: {slug} (by user {user.uid})")

    return {
        "success": True,
        "data": {
            "id": agent.id,
            "slug": agent.slug,
            "name": agent.name,
            "role": role_data,
        },
    }


@role_router.delete("/{category}/{role_id:path}")
async def delete_role_template(
    category: str,
    role_id: str = Path(..., description="角色模板标识"),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """逻辑删除角色模板（仅管理员）。

    在 role_template_deletions 表中插入记录，使该角色在列表和详情接口中不再返回。
    底层数据库记录不受影响，如需恢复可删除对应记录。
    """
    role_key = f"{category}/{role_id}"

    repo = RoleTemplateRepository(db)
    template = await repo.get_by_role_key(role_key)
    if not template:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 检查是否已被删除
    if await repo.is_role_deleted(role_key):
        raise HTTPException(status_code=409, detail="该角色已被删除")

    await repo.mark_role_deleted(role_key, user.uid)
    await db.commit()

    logger.info(f"已逻辑删除角色模板: {role_key} (by admin {user.uid})")

    return {"success": True}


@role_router.put("/{role_key}/category")
async def update_role_category(
    role_key: str,
    body: UpdateCategoryRequest,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """更新角色模板所属分类（仅管理员）。"""
    # 校验分类是否存在
    cat_repo = CategoryRepository(db)
    category = await cat_repo.get_by_id(body.category_id)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")

    repo = RoleTemplateRepository(db)
    template = await repo.get_by_role_key(role_key)
    if not template:
        raise HTTPException(status_code=404, detail="角色模板不存在")

    updated = await repo.update_category(template.id, body.category_id)
    await db.commit()

    logger.info(f"已更新角色模板 {role_key} 的分类为 {body.category_id} (by admin {user.uid})")

    return {
        "success": True,
        "data": updated.to_dict(),
    }
