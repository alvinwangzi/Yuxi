"""技能市场业务逻辑"""
import json
from typing import Optional, Dict, Any
from pathlib import Path
from yuxi.marketplace.repository import MarketplaceRepository
from yuxi.marketplace.models import (
    SkillMarketEntry, SkillMarketVersion, SkillMarketSubmission, SkillInstallation
)
from yuxi.marketplace.scanner import scan_skill_content
from yuxi.storage.postgres.models_business import Skill
from yuxi.repositories.user_repository import UserRepository
from yuxi.utils.datetime_utils import utc_now_naive
from sqlalchemy.ext.asyncio import AsyncSession


async def _build_author_nickname_map(session: AsyncSession, author_uids: list[str]) -> dict[str, str]:
    """批量获取作者昵称映射。"""
    if not author_uids:
        return {}
    user_repo = UserRepository(session)
    users = await user_repo.list_by_uids(author_uids)
    return {u.uid: (u.nickname or u.username) for u in users}


class MarketplaceService:
    """技能市场服务"""

    def __init__(self, repo: MarketplaceRepository, session: AsyncSession):
        self.repo = repo
        self.session = session

    async def list_market_entries(
        self,
        source_type: Optional[str] = None,
        category_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取市场条目列表"""
        offset = (page - 1) * page_size
        entries = await self.repo.list_entries(
            status="approved",
            source_type=source_type,
            category_id=category_id,
            offset=offset,
            limit=page_size,
        )
        total = await self.repo.count_entries(
            status="approved",
            source_type=source_type,
            category_id=category_id,
        )
        # 批量获取作者昵称
        author_uids = [e.author_uid for e in entries if e.author_uid]
        author_nickname_map = await _build_author_nickname_map(self.session, author_uids)
        items = []
        for e in entries:
            item = e.to_dict()
            if e.author_uid and e.author_uid in author_nickname_map:
                item["author_nickname"] = author_nickname_map[e.author_uid]
            items.append(item)
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_market_entry_detail(self, slug: str) -> Optional[Dict[str, Any]]:
        """获取市场条目详情"""
        entry = await self.repo.get_entry_by_slug(slug)
        if not entry:
            return None
        
        versions = await self.repo.list_versions(entry.id)
        latest = await self.repo.get_latest_version(entry.id)
        
        result = {
            **entry.to_dict(),
            "versions": [v.to_dict() for v in versions],
            "latest_version": latest.to_dict() if latest else None,
        }
        # 添加作者昵称
        if entry.author_uid:
            author_nickname_map = await _build_author_nickname_map(self.session, [entry.author_uid])
            if entry.author_uid in author_nickname_map:
                result["author_nickname"] = author_nickname_map[entry.author_uid]
        return result

    async def install_skill(
        self, user_uid: str, slug: str
    ) -> Dict[str, Any]:
        """安装市场技能到个人空间"""
        entry = await self.repo.get_entry_by_slug(slug)
        if not entry:
            raise ValueError(f"市场条目不存在: {slug}")
        
        if entry.status != "approved":
            raise ValueError(f"技能未上架或已下架: {slug}")
        
        latest = await self.repo.get_latest_version(entry.id)
        if not latest:
            raise ValueError(f"技能无可用版本: {slug}")
        
        # 检查是否已安装
        existing = await self.repo.get_installation(user_uid, entry.id)
        
        if existing:
            if existing.installed_version_id == latest.id:
                # 已安装最新版本，仍计数
                await self.repo.increment_install_count(entry.id)
                return {"status": "already_installed", "version": latest.version}
            else:
                # 更新到最新版本
                existing.installed_version_id = latest.id
                await self.repo.update_installation(existing)
                await self.repo.increment_install_count(entry.id)
                
                # 更新个人技能内容
                await self._update_personal_skill_from_snapshot(user_uid, entry, latest)
                
                return {"status": "updated", "version": latest.version}
        else:
            # 首次安装：创建个人技能
            await self._create_personal_skill_from_snapshot(user_uid, entry, latest)
            
            # 创建安装记录
            installation = SkillInstallation(
                user_uid=user_uid,
                entry_id=entry.id,
                installed_version_id=latest.id,
            )
            await self.repo.create_installation(installation)
            
            # 递增安装次数
            await self.repo.increment_install_count(entry.id)
            
            return {"status": "installed", "version": latest.version}

    async def _create_personal_skill_from_snapshot(
        self, user_uid: str, entry: SkillMarketEntry, version: SkillMarketVersion
    ) -> Skill:
        """从快照创建个人技能"""
        snapshot = version.content_snapshot
        
        # 生成个人技能 slug
        personal_slug = f"market-{entry.slug}-{user_uid[:8]}"
        
        # 创建数据库记录
        skill = Skill(
            slug=personal_slug,
            name=entry.title,
            description=entry.description,
            source_type="market",
            source_scope="personal",
            owner_uid=user_uid,
            author_uid=entry.author_uid,
            dir_path=f"market/{entry.slug}",  # 简化处理
            market_entry_id=entry.id,
            market_version_id=version.id,
            version=version.version,
            tool_dependencies=snapshot.get("tool_dependencies", []),
            mcp_dependencies=snapshot.get("mcp_dependencies", []),
            skill_dependencies=snapshot.get("skill_dependencies", []),
            share_config={"access_level": "user", "user_uids": [user_uid]},
            enabled=True,
            created_by=user_uid,
            updated_by=user_uid,
        )
        
        self.session.add(skill)
        await self.session.flush()
        
        return skill

    async def _update_personal_skill_from_snapshot(
        self, user_uid: str, entry: SkillMarketEntry, version: SkillMarketVersion
    ) -> None:
        """从快照更新个人技能"""
        from sqlalchemy import select, and_
        
        # 查找用户的个人技能
        result = await self.session.execute(
            select(Skill).where(
                and_(
                    Skill.source_scope == "personal",
                    Skill.owner_uid == user_uid,
                    Skill.market_entry_id == entry.id
                )
            )
        )
        skill = result.scalar_one_or_none()
        
        if skill:
            snapshot = version.content_snapshot
            skill.name = entry.title
            skill.description = entry.description
            skill.version = version.version
            skill.market_version_id = version.id
            skill.tool_dependencies = snapshot.get("tool_dependencies", [])
            skill.mcp_dependencies = snapshot.get("mcp_dependencies", [])
            skill.skill_dependencies = snapshot.get("skill_dependencies", [])
            skill.updated_by = user_uid
            await self.session.flush()

    async def submit_skill_to_market(
        self,
        original_skill_id: int,
        title: str,
        description: str,
        category_id: Optional[int],
        submission_note: str,
        change_type: str,
        submitter_uid: str,
    ) -> Dict[str, Any]:
        """提交个人技能到市场"""
        # 获取原始技能
        from sqlalchemy import select
        result = await self.session.execute(
            select(Skill).where(Skill.id == original_skill_id)
        )
        original_skill = result.scalar_one_or_none()
        
        if not original_skill:
            raise ValueError(f"技能不存在: {original_skill_id}")
        
        if original_skill.source_scope != "personal":
            raise ValueError("只能提交个人技能到市场")
        
        if original_skill.owner_uid != submitter_uid:
            raise ValueError("只能提交自己的技能")
        
        # 检查是否已有市场条目
        existing_entry = await self.repo.get_entry_by_slug(f"company-{original_skill.slug}")
        
        if existing_entry:
            # 提交新版本
            return await self._submit_new_version(
                entry=existing_entry,
                original_skill=original_skill,
                submission_note=submission_note,
                change_type=change_type,
                submitter_uid=submitter_uid,
            )
        else:
            # 首次提交
            return await self._submit_first_version(
                original_skill=original_skill,
                title=title,
                description=description,
                category_id=category_id,
                submission_note=submission_note,
                change_type=change_type,
                submitter_uid=submitter_uid,
            )

    async def _submit_first_version(
        self,
        original_skill: Skill,
        title: str,
        description: str,
        category_id: Optional[int],
        submission_note: str,
        change_type: str,
        submitter_uid: str,
    ) -> Dict[str, Any]:
        """首次提交到市场"""
        # 创建市场条目
        entry = SkillMarketEntry(
            slug=f"company-{original_skill.slug}",
            title=title,
            description=description,
            source_type="company",
            status="pending",
            category_id=category_id,
            author_uid=original_skill.author_uid or submitter_uid,
            publisher_uid=submitter_uid,
            original_skill_id=original_skill.id,
        )
        entry = await self.repo.create_entry(entry)

        # 创建首个版本（商城无已有版本，初始为 1.0.0）
        snapshot = await self._build_content_snapshot(original_skill)
        initial_version = "1.0.0"
        version = SkillMarketVersion(
            entry_id=entry.id,
            version=initial_version,
            release_notes=submission_note,
            content_snapshot=snapshot,
            change_type=change_type,
            submitted_by=submitter_uid,
            is_latest=True,
        )
        version = await self.repo.create_version(version)

        # 执行安全扫描
        scan_result = scan_skill_content(
            skill_md=snapshot.get("skill_md", ""),
            scripts=snapshot.get("scripts"),
        )

        # 创建提交记录
        submission = SkillMarketSubmission(
            entry_id=entry.id,
            version_id=version.id,
            submitter_uid=submitter_uid,
            submission_note=submission_note,
            status="pending",
            scan_score=scan_result.score,
            scan_findings=scan_result.to_dict()["findings"],
            scanned_at=utc_now_naive(),
        )
        submission = await self.repo.create_submission(submission)

        return {
            "entry": entry.to_dict(),
            "version": version.to_dict(),
            "submission": submission.to_dict(),
            "scan_result": scan_result.to_dict(),
        }

    async def _submit_new_version(
        self,
        entry: SkillMarketEntry,
        original_skill: Skill,
        submission_note: str,
        change_type: str,
        submitter_uid: str,
    ) -> Dict[str, Any]:
        """提交新版本"""
        if entry.status == "unpublished":
            raise ValueError("技能已下架，无法提交新版本")

        # 获取当前最新版本
        latest = await self.repo.get_latest_version(entry.id)
        current_version = latest.version if latest else "1.0.0"

        # 计算新版本
        new_version = self._calculate_next_version(current_version, change_type)

        # 创建新版本
        snapshot = await self._build_content_snapshot(original_skill)
        version = SkillMarketVersion(
            entry_id=entry.id,
            version=new_version,
            release_notes=submission_note,
            content_snapshot=snapshot,
            change_type=change_type,
            submitted_by=submitter_uid,
            is_latest=False,  # 审批通过后才设为最新
        )
        version = await self.repo.create_version(version)

        # 执行安全扫描
        scan_result = scan_skill_content(
            skill_md=snapshot.get("skill_md", ""),
            scripts=snapshot.get("scripts"),
        )

        # 创建提交记录
        submission = SkillMarketSubmission(
            entry_id=entry.id,
            version_id=version.id,
            submitter_uid=submitter_uid,
            submission_note=submission_note,
            status="pending",
            scan_score=scan_result.score,
            scan_findings=scan_result.to_dict()["findings"],
            scanned_at=utc_now_naive(),
        )
        submission = await self.repo.create_submission(submission)

        return {
            "entry": entry.to_dict(),
            "version": version.to_dict(),
            "submission": submission.to_dict(),
            "scan_result": scan_result.to_dict(),
        }

    async def approve_submission(
        self, submission_id: int, reviewer_uid: str, review_note: str
    ) -> Dict[str, Any]:
        """审批通过"""
        submission = await self.repo.get_submission_by_id(submission_id)
        if not submission:
            raise ValueError(f"提交不存在：{submission_id}")
    
        if submission.status != "pending":
            raise ValueError(f"提交已处理：{submission_id}")
    
        # 检查安全风险评分，高风险禁止通过
        if submission.scan_score is not None and submission.scan_score >= 76:
            raise ValueError(
                f"安全风险评分过高 ({submission.scan_score}/100)，禁止审批通过。"
                f"请先处理高风险问题后再提交审批。"
            )
    
        # 更新提交状态
        submission.status = "approved"
        submission.reviewer_uid = reviewer_uid
        submission.review_note = review_note
        submission.reviewed_at = utc_now_naive()
        await self.repo.update_submission(submission)
    
        # 更新条目状态
        entry = await self.repo.get_entry_by_id(submission.entry_id)
        if entry.status == "pending":
            entry.status = "approved"
            await self.repo.update_entry(entry)
    
        # 设置版本为最新
        await self.repo.set_latest_version(entry.id, submission.version_id)
    
        # 更新版本的审批信息
        version = await self.repo.get_version_by_id(submission.version_id)
        version.approved_by = reviewer_uid
        version.approved_at = utc_now_naive()
        await self.repo.update_version(version)
    
        return {
            "submission": submission.to_dict(),
            "entry": entry.to_dict(),
            "version": version.to_dict(),
        }

    async def reject_submission(
        self, submission_id: int, reviewer_uid: str, review_note: str
    ) -> Dict[str, Any]:
        """审批驳回"""
        submission = await self.repo.get_submission_by_id(submission_id)
        if not submission:
            raise ValueError(f"提交不存在: {submission_id}")
        
        if submission.status != "pending":
            raise ValueError(f"提交已处理: {submission_id}")
        
        submission.status = "rejected"
        submission.reviewer_uid = reviewer_uid
        submission.review_note = review_note
        submission.reviewed_at = utc_now_naive()
        await self.repo.update_submission(submission)
        
        return {"submission": submission.to_dict()}

    async def unpublish_entry(self, slug: str, admin_uid: str) -> Dict[str, Any]:
        """下架技能"""
        entry = await self.repo.get_entry_by_slug(slug)
        if not entry:
            raise ValueError(f"市场条目不存在: {slug}")
        
        entry.status = "unpublished"
        entry.publisher_uid = admin_uid
        await self.repo.update_entry(entry)
        
        return entry.to_dict()

    def _calculate_next_version(self, current: str, change_type: str) -> str:
        """计算下一个版本号"""
        parts = current.split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        
        if change_type == "major":
            return f"{major + 1}.0.0"
        elif change_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:  # patch
            return f"{major}.{minor}.{patch + 1}"

    async def _build_content_snapshot(self, skill: Skill) -> Dict[str, Any]:
        """构建内容快照"""
        snapshot = {
            "skill_id": skill.id,
            "slug": skill.slug,
            "name": skill.name,
            "description": skill.description,
            "version": skill.version,
            "content_hash": skill.content_hash,
            "tool_dependencies": skill.tool_dependencies or [],
            "mcp_dependencies": skill.mcp_dependencies or [],
            "skill_dependencies": skill.skill_dependencies or [],
            "files": {},  # 存储技能文件内容（简化处理）
            "skill_md": "",  # SKILL.md 内容，用于安全扫描
            "scripts": {},  # 脚本内容，用于安全扫描
        }

        # 读取 SKILL.md 和脚本内容用于安全扫描
        if skill.dir_path:
            skill_dir = Path(skill.dir_path)
            skill_md_path = skill_dir / "SKILL.md"
            if skill_md_path.exists():
                snapshot["skill_md"] = skill_md_path.read_text(encoding="utf-8")

            scripts_dir = skill_dir / "scripts"
            if scripts_dir.is_dir():
                for py_file in scripts_dir.glob("*.py"):
                    snapshot["scripts"][py_file.name] = py_file.read_text(encoding="utf-8")

        return snapshot
