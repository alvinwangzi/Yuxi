"""角色模板数据访问层（数据库驱动）。"""

from __future__ import annotations

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yuxi.storage.postgres.models_business import RoleTemplate, CustomCategory


class RoleTemplateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(
        self,
        *,
        category_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[RoleTemplate], int]:
        base_stmt = select(RoleTemplate).options(selectinload(RoleTemplate.category))
        count_stmt = select(func.count()).select_from(RoleTemplate)

        if category_id is not None:
            base_stmt = base_stmt.where(RoleTemplate.category_id == category_id)
            count_stmt = count_stmt.where(RoleTemplate.category_id == category_id)

        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = base_stmt.order_by(RoleTemplate.sort_order, RoleTemplate.id).offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_by_id(self, template_id: int) -> RoleTemplate | None:
        stmt = (
            select(RoleTemplate)
            .options(selectinload(RoleTemplate.category))
            .where(RoleTemplate.id == template_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_role_key(self, role_key: str) -> RoleTemplate | None:
        """按业务唯一标识 role_key 查询角色模板。"""
        stmt = (
            select(RoleTemplate)
            .options(selectinload(RoleTemplate.category))
            .where(RoleTemplate.role_key == role_key)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_category(self, template_id: int, category_id: int) -> RoleTemplate | None:
        template = await self.get_by_id(template_id)
        if not template:
            return None
        template.category_id = category_id
        await self.db.flush()
        await self.db.refresh(template)
        return template

    async def get_category_counts(self) -> dict[int, int]:
        stmt = (
            select(RoleTemplate.category_id, func.count())
            .group_by(RoleTemplate.category_id)
        )
        result = await self.db.execute(stmt)
        return {row[0]: row[1] for row in result.fetchall()}

    async def bulk_upsert(self, templates: list[dict]) -> int:
        """批量插入或更新角色模板（用于初始迁移）。返回处理数量。"""
        count = 0
        for data in templates:
            existing = await self.db.execute(
                select(RoleTemplate).where(RoleTemplate.role_key == data["role_key"])
            )
            item = existing.scalar_one_or_none()
            if item:
                for key, value in data.items():
                    setattr(item, key, value)
            else:
                self.db.add(RoleTemplate(**data))
            count += 1
        await self.db.flush()
        return count

    # ------------------------------------------------------------------
    # Soft-delete helpers（role_template_deletions 表）
    # ------------------------------------------------------------------

    async def get_deleted_role_keys(self) -> set[str]:
        """查询已被逻辑删除的角色模板 role_key 集合。"""
        try:
            result = await self.db.execute(text("SELECT role_key FROM role_template_deletions"))
            return {row[0] for row in result.fetchall()}
        except Exception:
            return set()

    async def is_role_deleted(self, role_key: str) -> bool:
        deleted = await self.get_deleted_role_keys()
        return role_key in deleted

    async def mark_role_deleted(self, role_key: str, deleted_by: str) -> None:
        await self.db.execute(
            text(
                "INSERT INTO role_template_deletions (role_key, deleted_by) "
                "VALUES (:role_key, :deleted_by)"
            ),
            {"role_key": role_key, "deleted_by": deleted_by},
        )
