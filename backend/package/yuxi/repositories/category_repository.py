"""分类管理数据访问层。"""

from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import CustomCategory


class CategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_entity_type(self, entity_type: str) -> list[CustomCategory]:
        stmt = (
            select(CustomCategory)
            .where(CustomCategory.entity_type == entity_type)
            .order_by(CustomCategory.sort_order, CustomCategory.id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, category_id: int) -> CustomCategory | None:
        return await self.db.get(CustomCategory, category_id)

    async def get_by_slug(self, entity_type: str, slug: str) -> CustomCategory | None:
        stmt = select(CustomCategory).where(
            CustomCategory.entity_type == entity_type,
            CustomCategory.slug == slug,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        entity_type: str,
        slug: str,
        label: str,
        sort_order: int = 0,
        is_builtin: bool = True,
    ) -> CustomCategory:
        item = CustomCategory(
            entity_type=entity_type,
            slug=slug,
            label=label,
            sort_order=sort_order,
            is_builtin=is_builtin,
        )
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def update(self, category: CustomCategory, **kwargs) -> CustomCategory:
        for key, value in kwargs.items():
            if hasattr(category, key):
                setattr(category, key, value)
        await self.db.flush()
        await self.db.refresh(category)
        return category

    async def delete(self, category: CustomCategory) -> None:
        await self.db.delete(category)
        await self.db.flush()

    async def count_entities_for_category(self, category_id: int) -> dict[str, int]:
        """统计各实体类型下引用该分类的数量。"""
        from yuxi.storage.postgres.models_business import Agent, Skill, RoleTemplate, Workflow

        counts = {}
        for model, entity_type in [
            (Agent, "agent"),
            (Skill, "skill"),
            (RoleTemplate, "role_template"),
            (Workflow, "workflow"),
        ]:
            if hasattr(model, "category_id"):
                stmt = select(func.count()).select_from(model).where(model.category_id == category_id)
                result = await self.db.execute(stmt)
                counts[entity_type] = result.scalar() or 0
        return counts

    async def slug_exists(self, entity_type: str, slug: str, exclude_id: int | None = None) -> bool:
        stmt = select(CustomCategory.id).where(
            CustomCategory.entity_type == entity_type,
            CustomCategory.slug == slug,
        )
        if exclude_id is not None:
            stmt = stmt.where(CustomCategory.id != exclude_id)
        result = await self.db.execute(stmt)
        return result.scalar() is not None
