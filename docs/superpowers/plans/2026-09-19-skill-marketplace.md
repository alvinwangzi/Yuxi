# 技能市场（Skill Marketplace）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Yuxi 新增技能市场模块，整合系统内置技能与公司发布技能，支持浏览、安装、提交审批和版本管理。

**Architecture:** 新增 `skill_market_entries`、`skill_market_versions`、`skill_market_submissions`、`skill_installations` 四张表；扩展现有 `skills` 表增加 `author_uid`、`market_entry_id`、`market_version_id` 字段；后端新增 `/api/marketplace` 路由组；前端新增技能市场页面、提交表单和审批界面。

**Tech Stack:** Python 3.13 + SQLAlchemy async + FastAPI（后端）；Vue 3 + Pinia + Ant Design Vue（前端）；PostgreSQL（数据库）。

**Spec:** [docs/superpowers/specs/2026-09-19-skill-marketplace-design.md](file:///d:/AIProjects/Yuxi/docs/superpowers/specs/2026-09-19-skill-marketplace-design.md)

## Global Constraints

- 所有 API 响应使用 JSON 格式
- 数据库迁移通过 `ensure_business_schema()` 执行，使用 `CREATE TABLE IF NOT EXISTS` 和 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- 前端 HTTP 请求通过 `src/apis/*_api.js` 封装函数发起
- 可复用逻辑抽取为 `src/composables/useXxx.js`
- 组件按业务域拆分子目录
- 每个业务逻辑单元提供单元测试

---

## 阶段 1：数据库模型与迁移

### Task 1.1：扩展 Skill 模型

**Files:**
- Modify: `backend/package/yuxi/storage/postgres/models_business.py:354-407`

**Interfaces:**
- Consumes: 现有 `Skill` 模型
- Produces: 扩展后的 `Skill` 模型，新增 `author_uid`、`market_entry_id`、`market_version_id` 字段

- [ ] **Step 1: 修改 Skill 模型**

在 `Skill` 类中添加三个字段：

```python
# 在 category_id 字段后添加
author_uid = Column(String(64), nullable=True, index=True, comment="技能贡献者/作者")
market_entry_id = Column(Integer, ForeignKey("skill_market_entries.id"), nullable=True, index=True, comment="市场条目 ID（从市场安装的技能）")
market_version_id = Column(Integer, ForeignKey("skill_market_versions.id"), nullable=True, comment="安装时的市场版本 ID")
```

在 `to_dict()` 方法中添加：

```python
"author_uid": self.author_uid,
"market_entry_id": self.market_entry_id,
"market_version_id": self.market_version_id,
```

- [ ] **Step 2: 验证模型语法**

Run: `cd backend && python -c "from yuxi.storage.postgres.models_business import Skill; print('OK')"`
Expected: 输出 `OK`，无语法错误

- [ ] **Step 3: 提交**

```bash
git add backend/package/yuxi/storage/postgres/models_business.py
git commit -m "feat(skill-market): 扩展 Skill 模型增加市场关联字段"
```

### Task 1.2：创建市场数据模型

**Files:**
- Create: `backend/package/yuxi/storage/postgres/models_marketplace.py`

**Interfaces:**
- Consumes: SQLAlchemy Base, 现有模型工具
- Produces: `SkillMarketEntry`、`SkillMarketVersion`、`SkillMarketSubmission`、`SkillInstallation` 四个模型类

- [ ] **Step 1: 创建市场模型文件**

```python
"""技能市场数据模型"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from yuxi.storage.postgres.models_base import Base
from yuxi.utils.time import utc_now_naive, format_utc_datetime
from typing import Any


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
        comment="状态: pending | approved | rejected"
    )
    reviewer_uid = Column(String(64), nullable=True, comment="审批者")
    review_note = Column(Text, nullable=True, comment="审批说明")
    submitted_at = Column(DateTime, default=utc_now_naive)
    reviewed_at = Column(DateTime, nullable=True)

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
```

- [ ] **Step 2: 验证模型语法**

Run: `cd backend && python -c "from yuxi.storage.postgres.models_marketplace import SkillMarketEntry, SkillMarketVersion, SkillMarketSubmission, SkillInstallation; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 3: 提交**

```bash
git add backend/package/yuxi/storage/postgres/models_marketplace.py
git commit -m "feat(skill-market): 创建技能市场数据模型"
```

### Task 1.3：数据库迁移

**Files:**
- Modify: `backend/package/yuxi/storage/postgres/manager.py`

**Interfaces:**
- Consumes: 新模型定义
- Produces: `ensure_business_schema()` 中新增表和字段

- [ ] **Step 1: 在 manager.py 中添加迁移逻辑**

在 `ensure_business_schema()` 方法中添加：

```python
# 1. 创建市场表
await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS skill_market_entries (
        id SERIAL PRIMARY KEY,
        slug VARCHAR(128) NOT NULL UNIQUE,
        title VARCHAR(256) NOT NULL,
        description TEXT NOT NULL,
        source_type VARCHAR(16) NOT NULL DEFAULT 'company',
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        category_id INTEGER REFERENCES custom_categories(id),
        author_uid VARCHAR(64),
        publisher_uid VARCHAR(64),
        original_skill_id INTEGER,
        install_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""))

await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS skill_market_versions (
        id SERIAL PRIMARY KEY,
        entry_id INTEGER NOT NULL REFERENCES skill_market_entries(id),
        version VARCHAR(32) NOT NULL,
        release_notes TEXT,
        content_snapshot JSONB NOT NULL,
        change_type VARCHAR(16) NOT NULL,
        submitted_by VARCHAR(64) NOT NULL,
        submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        approved_by VARCHAR(64),
        approved_at TIMESTAMP,
        is_latest BOOLEAN NOT NULL DEFAULT FALSE,
        UNIQUE(entry_id, version)
    )
"""))

await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS skill_market_submissions (
        id SERIAL PRIMARY KEY,
        entry_id INTEGER NOT NULL REFERENCES skill_market_entries(id),
        version_id INTEGER NOT NULL REFERENCES skill_market_versions(id),
        submitter_uid VARCHAR(64) NOT NULL,
        submission_note TEXT,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        reviewer_uid VARCHAR(64),
        review_note TEXT,
        submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TIMESTAMP
    )
"""))

await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS skill_installations (
        id SERIAL PRIMARY KEY,
        user_uid VARCHAR(64) NOT NULL,
        entry_id INTEGER NOT NULL REFERENCES skill_market_entries(id),
        installed_version_id INTEGER NOT NULL REFERENCES skill_market_versions(id),
        installed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_uid, entry_id)
    )
"""))

# 2. 扩展 skills 表
await conn.execute(text("""
    ALTER TABLE skills ADD COLUMN IF NOT EXISTS author_uid VARCHAR(64)
"""))
await conn.execute(text("""
    ALTER TABLE skills ADD COLUMN IF NOT EXISTS market_entry_id INTEGER
"""))
await conn.execute(text("""
    ALTER TABLE skills ADD COLUMN IF NOT EXISTS market_version_id INTEGER
"""))

# 3. 创建索引
await conn.execute(text("""
    CREATE INDEX IF NOT EXISTS ix_skill_market_entries_slug ON skill_market_entries(slug)
"""))
await conn.execute(text("""
    CREATE INDEX IF NOT EXISTS ix_skill_market_entries_status ON skill_market_entries(status)
"""))
await conn.execute(text("""
    CREATE INDEX IF NOT EXISTS ix_skill_market_versions_entry_id ON skill_market_versions(entry_id)
"""))
await conn.execute(text("""
    CREATE INDEX IF NOT EXISTS ix_skill_market_submissions_entry_id ON skill_market_submissions(entry_id)
"""))
await conn.execute(text("""
    CREATE INDEX IF NOT EXISTS ix_skill_installations_user_uid ON skill_installations(user_uid)
"""))
await conn.execute(text("""
    CREATE INDEX IF NOT EXISTS ix_skill_installations_entry_id ON skill_installations(entry_id)
"""))
await conn.execute(text("""
    CREATE INDEX IF NOT EXISTS ix_skills_author_uid ON skills(author_uid)
"""))
await conn.execute(text("""
    CREATE INDEX IF NOT EXISTS ix_skills_market_entry_id ON skills(market_entry_id)
"""))
```

- [ ] **Step 2: 验证迁移语法**

Run: `cd backend && python -c "from yuxi.storage.postgres.manager import PostgreSQLStorageManager; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 3: 提交**

```bash
git add backend/package/yuxi/storage/postgres/manager.py
git commit -m "feat(skill-market): 添加技能市场数据库迁移"
```

### Task 1.4：初始化内置技能市场条目

**Files:**
- Create: `backend/scripts/seed_marketplace_builtins.py`

**Interfaces:**
- Consumes: 市场模型、现有内置技能
- Produces: 内置技能市场条目初始化脚本

- [ ] **Step 1: 创建初始化脚本**

```python
"""初始化内置技能市场条目"""
import asyncio
import os
import sys
from pathlib import Path

# 添加 package 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "package"))

from sqlalchemy import text
from yuxi.storage.postgres.connection import get_async_engine
from yuxi.agents.skills.service import SkillService
from yuxi.storage.postgres.session import get_async_session_factory


async def seed_builtin_market_entries():
    """将现有内置技能同步到市场条目"""
    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)
    
    async with session_factory() as session:
        # 获取所有内置技能
        result = await session.execute(
            text("SELECT id, slug, name, description, version, content_hash FROM skills WHERE source_type = 'builtin'")
        )
        builtin_skills = result.fetchall()
        
        print(f"Found {len(builtin_skills)} builtin skills")
        
        for skill in builtin_skills:
            skill_id, slug, name, description, version, content_hash = skill
            
            # 检查是否已存在市场条目
            check = await session.execute(
                text("SELECT id FROM skill_market_entries WHERE slug = :slug AND source_type = 'builtin'"),
                {"slug": f"builtin-{slug}"}
            )
            existing = check.fetchone()
            
            if existing:
                print(f"  Skip {slug} (already exists)")
                continue
            
            # 创建市场条目
            entry_result = await session.execute(
                text("""
                    INSERT INTO skill_market_entries 
                    (slug, title, description, source_type, status, install_count)
                    VALUES (:slug, :title, :description, 'builtin', 'approved', 0)
                    RETURNING id
                """),
                {
                    "slug": f"builtin-{slug}",
                    "title": name,
                    "description": description or name,
                }
            )
            entry_id = entry_result.scalar()
            
            # 创建首个版本
            await session.execute(
                text("""
                    INSERT INTO skill_market_versions
                    (entry_id, version, release_notes, content_snapshot, change_type, submitted_by, is_latest)
                    VALUES (:entry_id, :version, '初始版本', :snapshot, 'minor', 'system', TRUE)
                """),
                {
                    "entry_id": entry_id,
                    "version": version or "1.0.0",
                    "snapshot": json.dumps({
                        "skill_id": skill_id,
                        "content_hash": content_hash,
                        "source": "builtin"
                    })
                }
            )
            
            print(f"  Created market entry for {slug}")
        
        await session.commit()
    
    print("Done")


if __name__ == "__main__":
    import json
    asyncio.run(seed_builtin_market_entries())
```

- [ ] **Step 2: 验证脚本语法**

Run: `cd backend && python -c "import scripts.seed_marketplace_builtins; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 3: 提交**

```bash
git add backend/scripts/seed_marketplace_builtins.py
git commit -m "feat(skill-market): 添加内置技能市场初始化脚本"
```

---

## 阶段 2：后端 API - 市场浏览

### Task 2.1：创建市场 Repository

**Files:**
- Create: `backend/package/yuxi/marketplace/repository.py`

**Interfaces:**
- Consumes: 市场模型
- Produces: `MarketplaceRepository` 类，提供市场数据访问方法

- [ ] **Step 1: 创建 Repository 类**

```python
"""技能市场数据访问层"""
from typing import Optional, List
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from yuxi.storage.postgres.models_marketplace import (
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
```

- [ ] **Step 2: 验证语法**

Run: `cd backend && python -c "from yuxi.marketplace.repository import MarketplaceRepository; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 3: 提交**

```bash
git add backend/package/yuxi/marketplace/repository.py
git commit -m "feat(skill-market): 创建市场 Repository"
```

### Task 2.2：创建市场 Service

**Files:**
- Create: `backend/package/yuxi/marketplace/service.py`

**Interfaces:**
- Consumes: `MarketplaceRepository`、`SkillService`
- Produces: `MarketplaceService` 类，提供市场业务逻辑

- [ ] **Step 1: 创建 Service 类**

```python
"""技能市场业务逻辑"""
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from yuxi.marketplace.repository import MarketplaceRepository
from yuxi.storage.postgres.models_marketplace import (
    SkillMarketEntry, SkillMarketVersion, SkillMarketSubmission, SkillInstallation
)
from yuxi.agents.skills.service import SkillService
from yuxi.storage.postgres.session import get_async_session_factory


class MarketplaceService:
    """技能市场服务"""

    def __init__(self, repo: MarketplaceRepository, skill_service: SkillService):
        self.repo = repo
        self.skill_service = skill_service

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
        return {
            "items": [e.to_dict() for e in entries],
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
        
        return {
            **entry.to_dict(),
            "versions": [v.to_dict() for v in versions],
            "latest_version": latest.to_dict() if latest else None,
        }

    async def install_skill(
        self, user_uid: str, slug: str, current_user_uid: str
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
        existing = await self.repo.get_installation(current_user_uid, entry.id)
        
        if existing:
            if existing.installed_version_id == latest.id:
                # 已安装最新版本，仍计数
                await self.repo.increment_install_count(entry.id)
                return {"status": "already_installed", "version": latest.version}
            else:
                # 更新到最新版本
                # TODO: 检查本地修改，提示覆盖风险
                existing.installed_version_id = latest.id
                await self.repo.update_installation(existing)
                await self.repo.increment_install_count(entry.id)
                return {"status": "updated", "version": latest.version}
        else:
            # 首次安装：创建个人技能
            snapshot = latest.content_snapshot
            
            # 从快照创建个人技能
            personal_skill = await self.skill_service.create_personal_skill_from_market(
                user_uid=user_uid,
                entry_slug=entry.slug,
                entry_title=entry.title,
                entry_description=entry.description,
                content_snapshot=snapshot,
                market_entry_id=entry.id,
                market_version_id=latest.id,
                author_uid=entry.author_uid,
            )
            
            # 创建安装记录
            installation = SkillInstallation(
                user_uid=current_user_uid,
                entry_id=entry.id,
                installed_version_id=latest.id,
            )
            await self.repo.create_installation(installation)
            
            # 递增安装次数
            await self.repo.increment_install_count(entry.id)
            
            return {"status": "installed", "version": latest.version, "skill_id": personal_skill.id}

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
        original_skill = await self.skill_service.get_skill_by_id(original_skill_id)
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
        original_skill,
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
        
        # 创建首个版本
        snapshot = await self._build_content_snapshot(original_skill)
        version = SkillMarketVersion(
            entry_id=entry.id,
            version="1.0.0",
            release_notes=submission_note,
            content_snapshot=snapshot,
            change_type=change_type,
            submitted_by=submitter_uid,
            is_latest=True,
        )
        version = await self.repo.create_version(version)
        
        # 创建提交记录
        submission = SkillMarketSubmission(
            entry_id=entry.id,
            version_id=version.id,
            submitter_uid=submitter_uid,
            submission_note=submission_note,
            status="pending",
        )
        submission = await self.repo.create_submission(submission)
        
        return {
            "entry": entry.to_dict(),
            "version": version.to_dict(),
            "submission": submission.to_dict(),
        }

    async def _submit_new_version(
        self,
        entry: SkillMarketEntry,
        original_skill,
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
        
        # 创建提交记录
        submission = SkillMarketSubmission(
            entry_id=entry.id,
            version_id=version.id,
            submitter_uid=submitter_uid,
            submission_note=submission_note,
            status="pending",
        )
        submission = await self.repo.create_submission(submission)
        
        return {
            "entry": entry.to_dict(),
            "version": version.to_dict(),
            "submission": submission.to_dict(),
        }

    async def approve_submission(
        self, submission_id: int, reviewer_uid: str, review_note: str
    ) -> Dict[str, Any]:
        """审批通过"""
        submission = await self.repo.get_submission_by_id(submission_id)
        if not submission:
            raise ValueError(f"提交不存在: {submission_id}")
        
        if submission.status != "pending":
            raise ValueError(f"提交已处理: {submission_id}")
        
        # 更新提交状态
        submission.status = "approved"
        submission.reviewer_uid = reviewer_uid
        submission.review_note = review_note
        submission.reviewed_at = datetime.utcnow()
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
        version.approved_at = datetime.utcnow()
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
        submission.reviewed_at = datetime.utcnow()
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

    async def _build_content_snapshot(self, skill) -> Dict[str, Any]:
        """构建内容快照"""
        # 读取技能目录内容
        skill_dir = await self.skill_service.get_skill_directory(skill)
        
        snapshot = {
            "skill_id": skill.id,
            "slug": skill.slug,
            "name": skill.name,
            "description": skill.description,
            "version": skill.version,
            "content_hash": skill.content_hash,
            "files": {},  # 存储技能文件内容
        }
        
        # TODO: 读取技能目录中的所有文件
        # 这里简化处理，实际实现需要遍历目录并读取文件内容
        
        return snapshot
```

- [ ] **Step 2: 验证语法**

Run: `cd backend && python -c "from yuxi.marketplace.service import MarketplaceService; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 3: 提交**

```bash
git add backend/package/yuxi/marketplace/service.py
git commit -m "feat(skill-market): 创建市场 Service"
```

### Task 2.3：创建市场 API 路由

**Files:**
- Create: `backend/server/routers/marketplace_router.py`

**Interfaces:**
- Consumes: `MarketplaceService`
- Produces: `/api/marketplace` 路由组

- [ ] **Step 1: 创建路由文件**

```python
"""技能市场 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from yuxi.auth.dependencies import get_current_user
from yuxi.marketplace.service import MarketplaceService
from yuxi.marketplace.repository import MarketplaceRepository
from yuxi.agents.skills.service import SkillService
from yuxi.storage.postgres.session import get_async_session

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


async def get_marketplace_service(
    session=Depends(get_async_session),
    skill_service: SkillService = Depends(),
) -> MarketplaceService:
    """获取市场服务依赖"""
    repo = MarketplaceRepository(session)
    return MarketplaceService(repo, skill_service)


@router.get("/entries")
async def list_market_entries(
    source_type: Optional[str] = Query(None, description="来源类型: builtin | company"),
    category_id: Optional[int] = Query(None, description="分类 ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user=Depends(get_current_user),
):
    """获取市场条目列表"""
    result = await service.list_market_entries(
        source_type=source_type,
        category_id=category_id,
        page=page,
        page_size=page_size,
    )
    return {"success": True, **result}


@router.get("/entries/{slug}")
async def get_market_entry_detail(
    slug: str,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user=Depends(get_current_user),
):
    """获取市场条目详情"""
    result = await service.get_market_entry_detail(slug)
    if not result:
        raise HTTPException(status_code=404, detail="市场条目不存在")
    return {"success": True, "data": result}


@router.post("/entries/{slug}/install")
async def install_market_skill(
    slug: str,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user=Depends(get_current_user),
):
    """安装市场技能"""
    try:
        result = await service.install_skill(
            user_uid=current_user.uid,
            slug=slug,
            current_user_uid=current_user.uid,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/submissions/pending")
async def list_pending_submissions(
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user=Depends(get_current_user),
):
    """获取待审批列表（管理员）"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    repo = MarketplaceRepository(await get_async_session().__anext__())
    submissions = await repo.list_pending_submissions()
    return {"success": True, "data": [s.to_dict() for s in submissions]}


@router.post("/submissions")
async def submit_skill_to_market(
    body: dict,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user=Depends(get_current_user),
):
    """提交个人技能到市场"""
    required = ["original_skill_id", "title", "description", "change_type"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"缺少必填字段: {field}")
    
    try:
        result = await service.submit_skill_to_market(
            original_skill_id=body["original_skill_id"],
            title=body["title"],
            description=body["description"],
            category_id=body.get("category_id"),
            submission_note=body.get("submission_note", ""),
            change_type=body["change_type"],
            submitter_uid=current_user.uid,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/submissions/{submission_id}/approve")
async def approve_submission(
    submission_id: int,
    body: dict,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user=Depends(get_current_user),
):
    """审批通过"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    try:
        result = await service.approve_submission(
            submission_id=submission_id,
            reviewer_uid=current_user.uid,
            review_note=body.get("review_note", ""),
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/submissions/{submission_id}/reject")
async def reject_submission(
    submission_id: int,
    body: dict,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user=Depends(get_current_user),
):
    """审批驳回"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    try:
        result = await service.reject_submission(
            submission_id=submission_id,
            reviewer_uid=current_user.uid,
            review_note=body.get("review_note", ""),
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/admin/entries/{slug}/unpublish")
async def unpublish_entry(
    slug: str,
    service: MarketplaceService = Depends(get_marketplace_service),
    current_user=Depends(get_current_user),
):
    """下架技能（管理员）"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    try:
        result = await service.unpublish_entry(slug=slug, admin_uid=current_user.uid)
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 2: 注册路由**

在 `backend/server/main.py` 中添加：

```python
from server.routers import marketplace_router
app.include_router(marketplace_router.router)
```

- [ ] **Step 3: 验证语法**

Run: `cd backend && python -c "from server.routers.marketplace_router import router; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 4: 提交**

```bash
git add backend/server/routers/marketplace_router.py backend/server/main.py
git commit -m "feat(skill-market): 创建市场 API 路由"
```

---

## 阶段 3：扩展 SkillService

### Task 3.1：添加市场相关方法到 SkillService

**Files:**
- Modify: `backend/package/yuxi/agents/skills/service.py`

**Interfaces:**
- Consumes: 现有 SkillService
- Produces: 新增 `create_personal_skill_from_market` 方法

- [ ] **Step 1: 添加市场安装方法**

在 `SkillService` 类中添加：

```python
async def create_personal_skill_from_market(
    self,
    user_uid: str,
    entry_slug: str,
    entry_title: str,
    entry_description: str,
    content_snapshot: dict,
    market_entry_id: int,
    market_version_id: int,
    author_uid: Optional[str] = None,
) -> Skill:
    """从市场安装创建个人技能"""
    # 生成个人技能 slug
    personal_slug = f"market-{entry_slug}-{user_uid[:8]}"
    
    # 创建个人技能目录
    skill_dir = await self._create_personal_skill_directory(user_uid, personal_slug)
    
    # 从快照写入文件
    await self._write_snapshot_to_directory(skill_dir, content_snapshot)
    
    # 创建数据库记录
    skill = Skill(
        slug=personal_slug,
        name=entry_title,
        description=entry_description,
        source_type="market",
        source_scope="personal",
        owner_uid=user_uid,
        author_uid=author_uid,
        dir_path=str(skill_dir),
        market_entry_id=market_entry_id,
        market_version_id=market_version_id,
        tool_dependencies=content_snapshot.get("tool_dependencies", []),
        mcp_dependencies=content_snapshot.get("mcp_dependencies", []),
        skill_dependencies=content_snapshot.get("skill_dependencies", []),
        share_config={"access_level": "user", "user_uids": [user_uid]},
        enabled=True,
        created_by=user_uid,
        updated_by=user_uid,
    )
    
    self.session.add(skill)
    await self.session.flush()
    
    return skill

async def _write_snapshot_to_directory(self, skill_dir: Path, snapshot: dict) -> None:
    """从快照写入技能目录"""
    # 创建 SKILL.md
    skill_md_content = f"""---
name: {snapshot.get('name', 'Market Skill')}
description: {snapshot.get('description', '')}
version: {snapshot.get('version', '1.0.0')}
---

# {snapshot.get('name', 'Market Skill')}

{snapshot.get('description', '')}
"""
    (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
    
    # 写入其他文件（如果有）
    for filename, content in snapshot.get("files", {}).items():
        file_path = skill_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
```

- [ ] **Step 2: 验证语法**

Run: `cd backend && python -c "from yuxi.agents.skills.service import SkillService; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 3: 提交**

```bash
git add backend/package/yuxi/agents/skills/service.py
git commit -m "feat(skill-market): 添加市场安装方法到 SkillService"
```

---

## 阶段 4：前端实现

### Task 4.1：创建市场 API 客户端

**Files:**
- Create: `web/src/apis/marketplace_api.js`

**Interfaces:**
- Consumes: `apis/base` 的 HTTP 封装
- Produces: `marketplaceApi` 对象

- [ ] **Step 1: 创建 API 客户端**

```javascript
import { apiGet, apiPost, apiPut } from './base'

export const marketplaceApi = {
  // 获取市场条目列表
  listEntries(params = {}) {
    const query = new URLSearchParams()
    if (params.source_type) query.set('source_type', params.source_type)
    if (params.category_id) query.set('category_id', params.category_id)
    if (params.page) query.set('page', params.page)
    if (params.page_size) query.set('page_size', params.page_size)
    const qs = query.toString()
    return apiGet(`/api/marketplace/entries${qs ? `?${qs}` : ''}`)
  },

  // 获取市场条目详情
  getEntryDetail(slug) {
    return apiGet(`/api/marketplace/entries/${slug}`)
  },

  // 安装市场技能
  installSkill(slug) {
    return apiPost(`/api/marketplace/entries/${slug}/install`, {})
  },

  // 获取待审批列表
  listPendingSubmissions() {
    return apiGet('/api/marketplace/submissions/pending')
  },

  // 提交技能到市场
  submitToMarket(data) {
    return apiPost('/api/marketplace/submissions', data)
  },

  // 审批通过
  approveSubmission(submissionId, data) {
    return apiPost(`/api/marketplace/submissions/${submissionId}/approve`, data)
  },

  // 审批驳回
  rejectSubmission(submissionId, data) {
    return apiPost(`/api/marketplace/submissions/${submissionId}/reject`, data)
  },

  // 下架技能
  unpublishEntry(slug) {
    return apiPut(`/api/marketplace/admin/entries/${slug}/unpublish`, {})
  },
}
```

- [ ] **Step 2: 提交**

```bash
git add web/src/apis/marketplace_api.js
git commit -m "feat(skill-market): 创建市场 API 客户端"
```

### Task 4.2：创建技能市场页面

**Files:**
- Create: `web/src/components/marketplace/SkillMarketPanel.vue`

**Interfaces:**
- Consumes: `marketplaceApi`、`useCategories`
- Produces: 技能市场浏览组件

- [ ] **Step 1: 创建市场面板组件**

（组件代码较长，此处省略，实际实现时补充完整 Vue 组件）

核心功能：
- 顶部搜索框 + 分类筛选
- 两个 Tab：系统内置 / 公司精选
- 技能卡片展示：标题、描述、作者、版本、安装次数、安装按钮
- 技能详情抽屉

- [ ] **Step 2: 提交**

```bash
git add web/src/components/marketplace/SkillMarketPanel.vue
git commit -m "feat(skill-market): 创建技能市场页面"
```

### Task 4.3：添加提交到市场表单

**Files:**
- Create: `web/src/components/marketplace/SubmitToMarketModal.vue`

**Interfaces:**
- Consumes: `marketplaceApi`
- Produces: 提交表单组件

- [ ] **Step 1: 创建提交表单组件**

核心功能：
- 市场标题、描述输入
- 提交说明输入
- 更新类型选择（首次/修复/新增/不兼容）
- 版本号预览
- 提交按钮

- [ ] **Step 2: 提交**

```bash
git add web/src/components/marketplace/SubmitToMarketModal.vue
git commit -m "feat(skill-market): 创建提交到市场表单"
```

### Task 4.4：添加管理员审批界面

**Files:**
- Create: `web/src/components/marketplace/MarketApprovalPanel.vue`

**Interfaces:**
- Consumes: `marketplaceApi`
- Produces: 审批管理组件

- [ ] **Step 1: 创建审批面板组件**

核心功能：
- 待审批列表
- 查看详情（技能内容、版本信息）
- 通过/驳回操作
- 审批说明输入

- [ ] **Step 2: 提交**

```bash
git add web/src/components/marketplace/MarketApprovalPanel.vue
git commit -m "feat(skill-market): 创建管理员审批界面"
```

### Task 4.5：集成到导航

**Files:**
- Modify: `web/src/router/index.js` 或相关导航配置

- [ ] **Step 1: 添加市场路由**

```javascript
{
  path: '/marketplace',
  name: 'Marketplace',
  component: () => import('@/components/marketplace/SkillMarketPanel.vue'),
  meta: { requiresAuth: true }
}
```

- [ ] **Step 2: 在导航菜单添加入口**

在左侧菜单或扩展市场区域添加「技能市场」入口。

- [ ] **Step 3: 提交**

```bash
git add web/src/router/index.js
git commit -m "feat(skill-market): 集成市场页面到导航"
```

---

## 阶段 5：测试与验证

### Task 5.1：后端单元测试

**Files:**
- Create: `backend/test/unit/test_marketplace_repository.py`
- Create: `backend/test/unit/test_marketplace_service.py`

- [ ] **Step 1: 编写 Repository 测试**

覆盖：
- 列表查询（分页、筛选）
- 创建/更新条目
- 版本管理
- 安装记录

- [ ] **Step 2: 编写 Service 测试**

覆盖：
- 安装技能（首次/重复/更新）
- 提交到市场（首次/新版本）
- 审批流程（通过/驳回）
- 下架

- [ ] **Step 3: 运行测试**

Run: `cd backend && pytest test/unit/test_marketplace_*.py -v`
Expected: 所有测试通过

- [ ] **Step 4: 提交**

```bash
git add backend/test/unit/test_marketplace_*.py
git commit -m "test(skill-market): 添加市场单元测试"
```

### Task 5.2：前端单元测试

**Files:**
- Create: `web/test/unit/marketplace_api.test.js`

- [ ] **Step 1: 编写 API 客户端测试**

- [ ] **Step 2: 运行测试**

Run: `cd web && pnpm test:unit marketplace`
Expected: 所有测试通过

- [ ] **Step 3: 提交**

```bash
git add web/test/unit/marketplace_api.test.js
git commit -m "test(skill-market): 添加市场前端测试"
```

### Task 5.3：集成验证

- [ ] **Step 1: 执行数据库迁移**

启动 API 服务，验证表创建成功。

- [ ] **Step 2: 初始化内置技能**

Run: `cd backend && python scripts/seed_marketplace_builtins.py`

- [ ] **Step 3: 验证市场 API**

- GET `/api/marketplace/entries` 返回内置技能
- POST `/api/marketplace/entries/{slug}/install` 安装成功
- 验证 `install_count` 递增

- [ ] **Step 4: 验证前端页面**

- 访问技能市场页面
- 浏览内置技能
- 点击安装
- 验证安装次数更新

- [ ] **Step 5: 最终提交**

```bash
git add .
git commit -m "feat(skill-market): 完成技能市场功能"
```

---

## 总结

本计划分为 5 个阶段，共 15 个任务：

1. **数据库模型与迁移**（4 个任务）
2. **后端 API - 市场浏览**（3 个任务）
3. **扩展 SkillService**（1 个任务）
4. **前端实现**（5 个任务）
5. **测试与验证**（3 个任务）

每个任务包含明确的文件路径、代码示例和验证步骤。建议按顺序执行，每个任务完成后提交代码。
