"""Channel 配置的数据库仓库。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import ChannelConfigDB
from yuxi.utils.datetime_utils import utc_now_naive


class ChannelConfigRepository:
    """Channel 配置 CRUD。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[ChannelConfigDB]:
        result = await self.db.execute(
            select(ChannelConfigDB).order_by(ChannelConfigDB.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_slug(self, slug: str) -> ChannelConfigDB | None:
        result = await self.db.execute(
            select(ChannelConfigDB).where(ChannelConfigDB.slug == slug)
        )
        return result.scalar_one_or_none()

    async def exists_slug(self, slug: str) -> bool:
        return (await self.get_by_slug(slug)) is not None

    async def create(
        self,
        *,
        slug: str,
        channel_type: str,
        enabled: bool = True,
        credentials: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        agent_slug: str | None = None,
        created_by: str | None = None,
    ) -> ChannelConfigDB:
        now = utc_now_naive()
        item = ChannelConfigDB(
            slug=slug,
            channel_type=channel_type,
            enabled=enabled,
            credentials=credentials or {},
            extra=extra or {},
            agent_slug=agent_slug,
            created_by=created_by,
            updated_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def update(
        self,
        item: ChannelConfigDB,
        *,
        enabled: bool | None = None,
        credentials: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        agent_slug: str | None = None,
        updated_by: str | None = None,
    ) -> ChannelConfigDB:
        if enabled is not None:
            item.enabled = enabled
        if credentials is not None:
            item.credentials = credentials
        if extra is not None:
            item.extra = extra
        if agent_slug is not None:
            item.agent_slug = agent_slug
        item.updated_by = updated_by
        item.updated_at = utc_now_naive()
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def delete(self, slug: str) -> bool:
        item = await self.get_by_slug(slug)
        if not item:
            return False
        await self.db.delete(item)
        await self.db.flush()
        return True
