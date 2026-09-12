"""分类管理 API 路由（CRUD + 排序）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db
from yuxi.repositories.category_repository import CategoryRepository
from yuxi.storage.postgres.models_business import User
from yuxi.utils.logging_config import logger

VALID_ENTITY_TYPES = {"agent", "skill", "role_template"}

router = APIRouter(prefix="/admin/categories", tags=["categories"])


# ── Pydantic 模型 ─────────────────────────────────────────────


class CategoryCreate(BaseModel):
    entity_type: str  # agent | skill | role_template
    slug: str
    label: str
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    slug: str | None = None
    label: str | None = None
    sort_order: int | None = None


class CategoryReorder(BaseModel):
    items: list[dict]  # [{"id": 1, "sort_order": 0}, ...]


# ── 辅助函数 ───────────────────────────────────────────────────


def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"entity_type 必须为 {', '.join(sorted(VALID_ENTITY_TYPES))} 之一",
        )


# ── 端点 ───────────────────────────────────────────────────────


@router.get("")
async def list_categories(
    entity_type: str,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """按 entity_type 列出所有分类。"""
    _validate_entity_type(entity_type)
    repo = CategoryRepository(db)
    items = await repo.list_by_entity_type(entity_type)
    return {"success": True, "data": [item.to_dict() for item in items]}


@router.post("")
async def create_category(
    body: CategoryCreate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """新建分类。"""
    _validate_entity_type(body.entity_type)

    repo = CategoryRepository(db)

    # 同一 entity_type 下 slug 必须唯一
    if await repo.slug_exists(body.entity_type, body.slug):
        raise HTTPException(
            status_code=409,
            detail=f"entity_type={body.entity_type} 下 slug='{body.slug}' 已存在",
        )

    item = await repo.create(
        entity_type=body.entity_type,
        slug=body.slug,
        label=body.label,
        sort_order=body.sort_order,
        is_builtin=False,
    )
    await db.commit()

    logger.info(f"管理员 {admin.uid} 新建分类: {body.entity_type}/{body.slug} (id={item.id})")
    return {"success": True, "data": item.to_dict()}


@router.put("/reorder")
async def reorder_categories(
    body: CategoryReorder,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """批量更新分类排序。"""
    repo = CategoryRepository(db)
    for entry in body.items:
        category_id = entry.get("id")
        sort_order = entry.get("sort_order")
        if category_id is None or sort_order is None:
            raise HTTPException(status_code=400, detail="每项必须包含 id 和 sort_order")
        item = await repo.get_by_id(int(category_id))
        if item is None:
            raise HTTPException(status_code=404, detail=f"分类 id={category_id} 不存在")
        await repo.update(item, sort_order=int(sort_order))

    await db.commit()
    logger.info(f"管理员 {admin.uid} 批量更新分类排序，共 {len(body.items)} 项")
    return {"success": True}


@router.put("/{category_id}")
async def update_category(
    category_id: int,
    body: CategoryUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """更新分类。"""
    repo = CategoryRepository(db)
    item = await repo.get_by_id(category_id)
    if item is None:
        raise HTTPException(status_code=404, detail="分类不存在")

    update_kwargs: dict = {}
    if body.slug is not None:
        if await repo.slug_exists(item.entity_type, body.slug, exclude_id=category_id):
            raise HTTPException(
                status_code=409,
                detail=f"entity_type={item.entity_type} 下 slug='{body.slug}' 已存在",
            )
        update_kwargs["slug"] = body.slug
    if body.label is not None:
        update_kwargs["label"] = body.label
    if body.sort_order is not None:
        update_kwargs["sort_order"] = body.sort_order

    if not update_kwargs:
        raise HTTPException(status_code=400, detail="未提供任何更新字段")

    await repo.update(item, **update_kwargs)
    await db.commit()

    logger.info(f"管理员 {admin.uid} 更新分类 id={category_id}: {update_kwargs}")
    return {"success": True, "data": item.to_dict()}


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """删除分类（内置分类不可删除，有实体引用时不可删除）。"""
    repo = CategoryRepository(db)
    item = await repo.get_by_id(category_id)
    if item is None:
        raise HTTPException(status_code=404, detail="分类不存在")

    if item.is_builtin:
        raise HTTPException(status_code=400, detail="内置分类不可删除")

    # 检查是否有实体引用该分类
    entity_counts = await repo.count_entities_for_category(category_id)
    total_refs = sum(entity_counts.values())
    if total_refs > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该分类下仍有 {total_refs} 个实体引用，不可删除",
        )

    await repo.delete(item)
    await db.commit()

    logger.info(f"管理员 {admin.uid} 删除分类 id={category_id} ({item.entity_type}/{item.slug})")
    return {"success": True}
