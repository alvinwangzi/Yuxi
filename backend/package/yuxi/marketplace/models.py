"""技能市场数据模型"""
from typing import Any
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from yuxi.storage.postgres.models_business import Base
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive
class SkillMarketEntry(Base):
    """技能市场条目"""

    __tablename__ = "skill_market_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(128), nullable=False, unique=True, index=True, comment="市场唯一标识")
    title = Column(String(256), nullable=False, comment="市场展示标题")
    description = Column(Text, nullable=False, comment="市场展示描述")
    source_type = Column(
        String(16), nullable=False, default="company",
        comment="来源类型: builtin | company"
    )
    status = Column(
        String(16), nullable=False, default="pending",
        comment="状态: pending | approved | rejected | unpublished"
    )
    category_id = Column(Integer, ForeignKey("custom_categories.id"), nullable=True, index=True)
    author_uid = Column(String(64), nullable=True, comment="原始贡献者")
    publisher_uid = Column(String(64), nullable=True, comment="发布/维护管理员")
    original_skill_id = Column(Integer, ForeignKey("skills.id"), nullable=True, comment="来源个人技能 ID")
    install_count = Column(Integer, nullable=False, default=0, comment="安装次数")
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "source_type": self.source_type,
            "status": self.status,
            "category_id": self.category_id,
            "author_uid": self.author_uid,
            "publisher_uid": self.publisher_uid,
            "original_skill_id": self.original_skill_id,
            "install_count": self.install_count,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class SkillMarketVersion(Base):
    """技能市场发布版本（不可变）"""

    __tablename__ = "skill_market_versions"
    __table_args__ = (
        UniqueConstraint("entry_id", "version", name="uq_market_version"),
        Index("ix_market_version_entry_latest", "entry_id", "is_latest"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(Integer, ForeignKey("skill_market_entries.id"), nullable=False, index=True)
    version = Column(String(32), nullable=False, comment="语义化版本号")
    release_notes = Column(Text, nullable=True, comment="发布说明")
    content_snapshot = Column(JSONB, nullable=False, comment="冻结的技能包内容")
    change_type = Column(String(16), nullable=False, comment="变更类型: major | minor | patch")
    submitted_by = Column(String(64), nullable=False, comment="提交者")
    submitted_at = Column(DateTime, default=utc_now_naive)
    approved_by = Column(String(64), nullable=True, comment="审批者")
    approved_at = Column(DateTime, nullable=True)
    is_latest = Column(Boolean, nullable=False, default=False, comment="是否为最新版本")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "version": self.version,
            "release_notes": self.release_notes,
            "change_type": self.change_type,
            "submitted_by": self.submitted_by,
            "submitted_at": format_utc_datetime(self.submitted_at),
            "approved_by": self.approved_by,
            "approved_at": format_utc_datetime(self.approved_at),
            "is_latest": self.is_latest,
        }


class SkillMarketSubmission(Base):
    """技能市场提交记录（审批流程）"""

    __tablename__ = "skill_market_submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(Integer, ForeignKey("skill_market_entries.id"), nullable=False, index=True)
    version_id = Column(Integer, ForeignKey("skill_market_versions.id"), nullable=False)
    submitter_uid = Column(String(64), nullable=False, comment="提交者")
    submission_note = Column(Text, nullable=True, comment="提交说明")
    status = Column(
        String(16), nullable=False, default="pending",
        comment="状态：pending | approved | rejected"
    )
    reviewer_uid = Column(String(64), nullable=True, comment="审批者")
    review_note = Column(Text, nullable=True, comment="审批说明")
    submitted_at = Column(DateTime, default=utc_now_naive)
    reviewed_at = Column(DateTime, nullable=True)
    # 安全扫描字段
    scan_score = Column(Integer, nullable=True, comment="风险评分 0-100")
    scan_findings = Column(JSONB, nullable=True, comment="扫描发现详情")
    scanned_at = Column(DateTime, nullable=True, comment="扫描时间")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "version_id": self.version_id,
            "submitter_uid": self.submitter_uid,
            "submission_note": self.submission_note,
            "status": self.status,
            "reviewer_uid": self.reviewer_uid,
            "review_note": self.review_note,
            "submitted_at": format_utc_datetime(self.submitted_at),
            "reviewed_at": format_utc_datetime(self.reviewed_at),
            "scan_score": self.scan_score,
            "scan_findings": self.scan_findings,
            "scanned_at": format_utc_datetime(self.scanned_at),
        }


class SkillInstallation(Base):
    """技能市场安装记录"""

    __tablename__ = "skill_installations"
    __table_args__ = (
        UniqueConstraint("user_uid", "entry_id", name="uq_user_market_install"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_uid = Column(String(64), nullable=False, index=True)
    entry_id = Column(Integer, ForeignKey("skill_market_entries.id"), nullable=False, index=True)
    installed_version_id = Column(Integer, ForeignKey("skill_market_versions.id"), nullable=False)
    installed_at = Column(DateTime, default=utc_now_naive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_uid": self.user_uid,
            "entry_id": self.entry_id,
            "installed_version_id": self.installed_version_id,
            "installed_at": format_utc_datetime(self.installed_at),
        }
