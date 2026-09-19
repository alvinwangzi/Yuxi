"""技能市场数据访问层"""
from typing import Optional, List
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.marketplace.models import (
    SkillMarketEntry, SkillMarketVersion, SkillMarketSubmission, SkillInstallation
)


class MarketplaceRepository:
    """技能市场 Repository"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # === 市场条目 ===

    async def list_entries(
        self,
        status: str = "approved",
        source_type: Optional[str] = None,
        category_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> List[SkillMarketEntry]:
        """获取市场条目列表"""
        query = select(SkillMarketEntry).where(SkillMarketEntry.status == status)
        
        if source_type:
            query = query.where(SkillMarketEntry.source_type == source_type)
        if category_id:
            query = query.where(SkillMarketEntry.category_id == category_id)
        
        query = query.order_by(SkillMarketEntry.install_count.desc(), SkillMarketEntry.created_at.desc())
        query = query.offset(offset).limit(limit)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_entries(
        self,
        status: str = "approved",
        source_type: Optional[str] = None,
        category_id: Optional[int] = None,
    ) -> int:
        """统计市场条目数量"""
        query = select(func.count(SkillMarketEntry.id)).where(SkillMarketEntry.status == status)
        
        if source_type:
            query = query.where(SkillMarketEntry.source_type == source_type)
        if category_id:
            query = query.where(SkillMarketEntry.category_id == category_id)
        
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_entry_by_slug(self, slug: str) -> Optional[SkillMarketEntry]:
        """按 slug 获取市场条目"""
        result = await self.session.execute(
            select(SkillMarketEntry).where(SkillMarketEntry.slug == slug)
        )
        return result.scalar_one_or_none()

    async def get_entry_by_id(self, entry_id: int) -> Optional[SkillMarketEntry]:
        """按 ID 获取市场条目"""
        result = await self.session.execute(
            select(SkillMarketEntry).where(SkillMarketEntry.id == entry_id)
        )
        return result.scalar_one_or_none()

    async def create_entry(self, entry: SkillMarketEntry) -> SkillMarketEntry:
        """创建市场条目"""
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def update_entry(self, entry: SkillMarketEntry) -> SkillMarketEntry:
        """更新市场条目"""
        await self.session.flush()
        return entry

    async def increment_install_count(self, entry_id: int) -> None:
        """递增安装次数"""
        await self.session.execute(
            update(SkillMarketEntry)
            .where(SkillMarketEntry.id == entry_id)
            .values(install_count=SkillMarketEntry.install_count + 1)
        )

    # === 版本 ===

    async def list_versions(self, entry_id: int) -> List[SkillMarketVersion]:
        """获取条目的所有版本"""
        result = await self.session.execute(
            select(SkillMarketVersion)
            .where(SkillMarketVersion.entry_id == entry_id)
            .order_by(SkillMarketVersion.submitted_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest_version(self, entry_id: int) -> Optional[SkillMarketVersion]:
        """获取最新版本"""
        result = await self.session.execute(
            select(SkillMarketVersion)
            .where(
                and_(
                    SkillMarketVersion.entry_id == entry_id,
                    SkillMarketVersion.is_latest == True
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_version_by_id(self, version_id: int) -> Optional[SkillMarketVersion]:
        """按 ID 获取版本"""
        result = await self.session.execute(
            select(SkillMarketVersion).where(SkillMarketVersion.id == version_id)
        )
        return result.scalar_one_or_none()

    async def create_version(self, version: SkillMarketVersion) -> SkillMarketVersion:
        """创建版本"""
        self.session.add(version)
        await self.session.flush()
        return version

    async def update_version(self, version: SkillMarketVersion) -> SkillMarketVersion:
        """更新版本"""
        await self.session.flush()
        return version

    async def set_latest_version(self, entry_id: int, version_id: int) -> None:
        """设置最新版本"""
        # 先将所有版本设为非最新
        await self.session.execute(
            update(SkillMarketVersion)
            .where(SkillMarketVersion.entry_id == entry_id)
            .values(is_latest=False)
        )
        # 将指定版本设为最新
        await self.session.execute(
            update(SkillMarketVersion)
            .where(SkillMarketVersion.id == version_id)
            .values(is_latest=True)
        )

    # === 提交记录 ===

    async def list_pending_submissions(self) -> List[SkillMarketSubmission]:
        """获取待审批列表"""
        result = await self.session.execute(
            select(SkillMarketSubmission)
            .where(SkillMarketSubmission.status == "pending")
            .order_by(SkillMarketSubmission.submitted_at.desc())
        )
        return list(result.scalars().all())

    async def get_submission_by_id(self, submission_id: int) -> Optional[SkillMarketSubmission]:
        """按 ID 获取提交"""
        result = await self.session.execute(
            select(SkillMarketSubmission).where(SkillMarketSubmission.id == submission_id)
        )
        return result.scalar_one_or_none()

    async def create_submission(self, submission: SkillMarketSubmission) -> SkillMarketSubmission:
        """创建提交"""
        self.session.add(submission)
        await self.session.flush()
        return submission

    async def update_submission(self, submission: SkillMarketSubmission) -> SkillMarketSubmission:
        """更新提交"""
        await self.session.flush()
        return submission

    # === 安装记录 ===

    async def get_installation(self, user_uid: str, entry_id: int) -> Optional[SkillInstallation]:
        """获取用户安装记录"""
        result = await self.session.execute(
            select(SkillInstallation)
            .where(
                and_(
                    SkillInstallation.user_uid == user_uid,
                    SkillInstallation.entry_id == entry_id
                )
            )
        )
        return result.scalar_one_or_none()

    async def create_installation(self, installation: SkillInstallation) -> SkillInstallation:
        """创建安装记录"""
        self.session.add(installation)
        await self.session.flush()
        return installation

    async def update_installation(self, installation: SkillInstallation) -> SkillInstallation:
        """更新安装记录"""
        await self.session.flush()
        return installation
