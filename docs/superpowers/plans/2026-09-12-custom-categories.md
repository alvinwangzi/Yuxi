# 自定义分类管理系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为租户管理员提供自定义分类管理能力（智能体/技能/角色模板），并在角色模板页面支持快速重新分类。

**Architecture:** 统一 `custom_categories` 表 + `role_templates` 表（数据库驱动替代文件系统），所有实体通过 `category_id` FK 关联。前端新增「设计」设置 Tab 管理分类，角色模板卡片支持点击重新分类。

**Tech Stack:** Python/FastAPI + SQLAlchemy + PostgreSQL 16 / Vue 3 + Ant Design Vue + Pinia

**Spec:** `docs/superpowers/specs/2026-09-12-custom-categories-design.md`

---

## 文件结构

### 后端新增/修改

| 文件 | 职责 |
|---|---|
| `backend/package/yuxi/storage/postgres/models_business.py` | 新增 `CustomCategory`、`RoleTemplate` ORM 模型 |
| `backend/package/yuxi/repositories/category_repository.py` | **新建** — 分类 CRUD |
| `backend/package/yuxi/repositories/role_template_repository.py` | **新建** — 角色模板数据库操作 |
| `backend/package/yuxi/storage/postgres/manager.py` | `ensure_business_schema()` 新增建表 + 列迁移 |
| `backend/package/yuxi/storage/postgres/seed_categories.py` | **新建** — 初始分类 seed 数据 |
| `backend/package/yuxi/storage/postgres/seed_role_templates.py` | **新建** — 从文件导入角色模板到数据库 |
| `backend/server/routers/category_router.py` | **新建** — 分类管理 API 路由 |
| `backend/server/routers/role_router.py` | 改造为从数据库读取 |
| `backend/server/routers/__init__.py` | 注册新路由 |

### 前端新增/修改

| 文件 | 职责 |
|---|---|
| `web/src/apis/category_api.js` | **新建** — 分类管理 API 封装 |
| `web/src/composables/useCategories.js` | **新建** — 分类数据 composable |
| `web/src/components/settings/DesignSettingsSection.vue` | **新建** — 设计设置面板 |
| `web/src/components/SettingsModal.vue` | 新增「设计」Tab |
| `web/src/components/roles/RoleTemplatePanel.vue` | 角色模板重新分类交互 |
| `web/src/components/model-management/AgentManagePanel.vue` | 分类标签栏改为动态 |
| `web/src/components/model-management/AgentEditModal.vue` | 分类下拉改为动态 |
| `web/src/components/extensions/SkillCardList.vue` | 分类标签栏改为动态 |

---

## Task 1: 后端 ORM 模型 — CustomCategory + RoleTemplate

**Files:**
- Modify: `backend/package/yuxi/storage/postgres/models_business.py`

- [ ] **Step 1: 在 models_business.py 末尾新增两个模型类**

在文件末尾（最后一个 class 之后）添加：

```python
class CustomCategory(Base):
    """管理员自定义分类（智能体/技能/角色模板共用）。"""

    __tablename__ = "custom_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(32), nullable=False, index=True, comment="agent|skill|role_template")
    slug = Column(String(64), nullable=False)
    label = Column(String(64), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_builtin = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now_naive)

    __table_args__ = (
        UniqueConstraint("entity_type", "slug", name="uq_custom_categories_type_slug"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "slug": self.slug,
            "label": self.label,
            "sort_order": self.sort_order,
            "is_builtin": bool(self.is_builtin),
            "created_at": format_utc_datetime(self.created_at),
        }


class RoleTemplate(Base):
    """角色模板（数据库驱动，替代文件系统扫描）。"""

    __tablename__ = "role_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_key = Column(String(255), nullable=False, unique=True, index=True, comment="业务唯一标识（原文件路径）")
    category_id = Column(Integer, ForeignKey("custom_categories.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(32), nullable=True, default="👤")
    color = Column(String(32), nullable=True, default="blue")
    content = Column(Text, nullable=False, comment="Markdown 正文")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    category = relationship("CustomCategory", foreign_keys=[category_id])

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "role_key": self.role_key,
            "category_id": self.category_id,
            "category_name": self.category.label if self.category else "",
            "category_slug": self.category.slug if self.category else "",
            "name": self.name,
            "description": self.description or "",
            "icon": self.icon or "👤",
            "color": self.color or "blue",
            "sort_order": self.sort_order,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }
        if include_content:
            result["content"] = self.content
        return result
```

- [ ] **Step 2: 验证模型无语法错误**

Run: `cd backend && uv run python -c "from yuxi.storage.postgres.models_business import CustomCategory, RoleTemplate; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/package/yuxi/storage/postgres/models_business.py
git commit -m "feat: 新增 CustomCategory 和 RoleTemplate ORM 模型"
```

---

## Task 2: 后端 Repository — CategoryRepository

**Files:**
- Create: `backend/package/yuxi/repositories/category_repository.py`
- Create: `backend/test/unit/repositories/test_category_repository.py`

- [ ] **Step 1: 编写测试**

```python
"""CategoryRepository 单元测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from yuxi.repositories.category_repository import CategoryRepository


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def repo(mock_db):
    return CategoryRepository(mock_db)


def test_init(repo, mock_db):
    assert repo.db is mock_db
```

- [ ] **Step 2: 实现 CategoryRepository**

```python
"""分类管理数据访问层。"""

from __future__ import annotations

from sqlalchemy import select, delete, func
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
        from yuxi.storage.postgres.models_business import Agent, Skill, RoleTemplate

        counts = {}
        for model, entity_type in [
            (Agent, "agent"),
            (Skill, "skill"),
            (RoleTemplate, "role_template"),
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
```

- [ ] **Step 3: 运行测试**

Run: `cd backend && uv run pytest test/unit/repositories/test_category_repository.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/package/yuxi/repositories/category_repository.py backend/test/unit/repositories/test_category_repository.py
git commit -m "feat: 新增 CategoryRepository 分类数据访问层"
```

---

## Task 3: 后端 Repository — RoleTemplateRepository

**Files:**
- Create: `backend/package/yuxi/repositories/role_template_repository.py`

- [ ] **Step 1: 实现 RoleTemplateRepository**

```python
"""角色模板数据访问层（数据库驱动）。"""

from __future__ import annotations

from sqlalchemy import select, func, update
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/package/yuxi/repositories/role_template_repository.py
git commit -m "feat: 新增 RoleTemplateRepository 角色模板数据访问层"
```

---

## Task 4: 数据库迁移 — ensure_business_schema + Seed

**Files:**
- Modify: `backend/package/yuxi/storage/postgres/manager.py`
- Create: `backend/package/yuxi/storage/postgres/seed_categories.py`
- Create: `backend/package/yuxi/storage/postgres/seed_role_templates.py`

- [ ] **Step 1: 创建 seed_categories.py**

```python
"""初始分类 seed 数据。"""

# 智能体/技能共用分类（来自 itemCategory.js）
AGENT_SKILL_CATEGORIES = [
    {"slug": "office", "label": "办公协同", "sort_order": 1},
    {"slug": "dev", "label": "开发工具", "sort_order": 2},
    {"slug": "data", "label": "数据分析", "sort_order": 3},
    {"slug": "content", "label": "内容创作", "sort_order": 4},
    {"slug": "info", "label": "信息资讯", "sort_order": 5},
    {"slug": "business", "label": "商业运营", "sort_order": 6},
    {"slug": "enterprise", "label": "企业管理", "sort_order": 7},
    {"slug": "productivity", "label": "效率工具", "sort_order": 8},
    {"slug": "other", "label": "其他", "sort_order": 9},
]

# 角色模板分类（来自 CATEGORY_MAP）
ROLE_TEMPLATE_CATEGORIES = [
    {"slug": "company", "label": "公司经营部", "sort_order": 1},
    {"slug": "sales", "label": "销售部", "sort_order": 2},
    {"slug": "marketing", "label": "营销部", "sort_order": 3},
    {"slug": "paid-media", "label": "付费媒体部", "sort_order": 4},
    {"slug": "hr", "label": "人力资源部", "sort_order": 5},
    {"slug": "finance", "label": "金融部", "sort_order": 6},
    {"slug": "legal", "label": "法务部", "sort_order": 7},
    {"slug": "supply-chain", "label": "供应链部", "sort_order": 8},
    {"slug": "product", "label": "产品部", "sort_order": 9},
    {"slug": "project-management", "label": "项目管理部", "sort_order": 10},
    {"slug": "engineering", "label": "工程部", "sort_order": 11},
    {"slug": "design", "label": "设计部", "sort_order": 12},
    {"slug": "testing", "label": "测试部", "sort_order": 13},
    {"slug": "support", "label": "支持部", "sort_order": 14},
    {"slug": "security", "label": "安全部", "sort_order": 15},
    {"slug": "specialized", "label": "专项部", "sort_order": 16},
    {"slug": "gis", "label": "GIS 空间信息部", "sort_order": 17},
    {"slug": "spatial-computing", "label": "空间计算部", "sort_order": 18},
    {"slug": "game-development", "label": "游戏开发部", "sort_order": 19},
    {"slug": "academic", "label": "学术部", "sort_order": 20},
]
```

- [ ] **Step 2: 创建 seed_role_templates.py**

```python
"""从文件系统导入角色模板到数据库（一次性迁移）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from yuxi.utils.logging_config import logger

ROLES_DIR = Path(__file__).parent.parent.parent / "agents" / "roles" / "roles"

# 旧分类目录名 → slug 映射
OLD_CATEGORY_MAP = {
    "company": "company", "sales": "sales", "marketing": "marketing",
    "paid-media": "paid-media", "hr": "hr", "finance": "finance",
    "legal": "legal", "supply-chain": "supply-chain", "product": "product",
    "project-management": "project-management", "engineering": "engineering",
    "design": "design", "testing": "testing", "support": "support",
    "security": "security", "specialized": "specialized", "gis": "gis",
    "spatial-computing": "spatial-computing", "game-development": "game-development",
    "academic": "academic",
}

SKIP_FILES = {"README.md", "NOTICE.md", "EXECUTIVE-BRIEF.md", "QUICKSTART.md", "nexus-strategy.md"}


def scan_role_files() -> list[dict]:
    """扫描角色文件目录，返回待插入的数据列表（不含 category_id）。"""
    templates = []
    if not ROLES_DIR.exists():
        logger.warning(f"角色目录不存在: {ROLES_DIR}")
        return templates

    for cat_dir_name in OLD_CATEGORY_MAP:
        cat_dir = ROLES_DIR / cat_dir_name
        if not cat_dir.is_dir():
            continue
        for role_file in sorted(cat_dir.rglob("*.md")):
            if role_file.name.startswith("_") or role_file.name in SKIP_FILES:
                continue
            try:
                content = role_file.read_text(encoding="utf-8")
                metadata = {}
                body = content
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        frontmatter = content[3:end].strip()
                        try:
                            metadata = yaml.safe_load(frontmatter) or {}
                        except yaml.YAMLError:
                            pass
                        body = content[end + 3:].strip()

                role_key = role_file.relative_to(ROLES_DIR).with_suffix("").as_posix()
                slug = OLD_CATEGORY_MAP[cat_dir_name]

                templates.append({
                    "role_key": role_key,
                    "old_category_slug": slug,
                    "name": metadata.get("name", role_key.replace("-", " ").replace("/", " - ").title()),
                    "description": (metadata.get("description", "") or "")[:200],
                    "icon": metadata.get("emoji", "👤"),
                    "color": metadata.get("color", "blue"),
                    "content": body,
                })
            except Exception as exc:
                logger.warning(f"解析角色文件失败 {role_file}: {exc}")

    return templates
```

- [ ] **Step 3: 在 manager.py 的 ensure_business_schema() 中添加建表语句**

在 `ensure_business_schema` 方法的 `stmts` 列表末尾追加：

```python
            # ── 自定义分类系统 ──
            """
            CREATE TABLE IF NOT EXISTS custom_categories (
                id SERIAL PRIMARY KEY,
                entity_type VARCHAR(32) NOT NULL,
                slug VARCHAR(64) NOT NULL,
                label VARCHAR(64) NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_builtin BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_custom_categories_type_slug UNIQUE (entity_type, slug)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_custom_categories_entity_type ON custom_categories(entity_type)",
            """
            CREATE TABLE IF NOT EXISTS role_templates (
                id SERIAL PRIMARY KEY,
                role_key VARCHAR(255) NOT NULL UNIQUE,
                category_id INTEGER NOT NULL REFERENCES custom_categories(id),
                name VARCHAR(128) NOT NULL,
                description TEXT,
                icon VARCHAR(32) DEFAULT '👤',
                color VARCHAR(32) DEFAULT 'blue',
                content TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_role_templates_category_id ON role_templates(category_id)",
            "ALTER TABLE IF EXISTS agents ADD COLUMN IF NOT EXISTS category_id INTEGER",
            "ALTER TABLE IF EXISTS skills ADD COLUMN IF NOT EXISTS category_id INTEGER",
```

- [ ] **Step 4: 在 manager.py 中添加 seed 逻辑**

在 `ensure_business_schema()` 方法末尾（`for stmt in stmts` 循环之后），添加 seed 逻辑：

```python
        # Seed 初始分类数据（仅当表为空时）
        await self._seed_custom_categories()
        # 从文件导入角色模板（仅当表为空时）
        await self._seed_role_templates()
        # 回填 agents/skills 的 category_id
        await self._backfill_category_ids()
```

并添加三个私有方法：

```python
    async def _seed_custom_categories(self):
        """当 custom_categories 表为空时，seed 初始分类。"""
        from yuxi.storage.postgres.seed_categories import AGENT_SKILL_CATEGORIES, ROLE_TEMPLATE_CATEGORIES

        async with self.async_engine.begin() as conn:
            count = await conn.scalar(text("SELECT COUNT(*) FROM custom_categories"))
            if count and count > 0:
                return

            for entity_type, categories in [
                ("agent", AGENT_SKILL_CATEGORIES),
                ("skill", AGENT_SKILL_CATEGORIES),
                ("role_template", ROLE_TEMPLATE_CATEGORIES),
            ]:
                for cat in categories:
                    await conn.execute(
                        text(
                            "INSERT INTO custom_categories (entity_type, slug, label, sort_order, is_builtin) "
                            "VALUES (:entity_type, :slug, :label, :sort_order, TRUE) "
                            "ON CONFLICT (entity_type, slug) DO NOTHING"
                        ),
                        {"entity_type": entity_type, **cat},
                    )

    async def _seed_role_templates(self):
        """当 role_templates 表为空时，从文件系统导入角色模板。"""
        from yuxi.storage.postgres.seed_role_templates import scan_role_files

        async with self.async_engine.begin() as conn:
            count = await conn.scalar(text("SELECT COUNT(*) FROM role_templates"))
            if count and count > 0:
                return

            templates = scan_role_files()
            if not templates:
                return

            # 构建 old_category_slug → category_id 映射
            cat_rows = await conn.execute(
                text("SELECT id, slug FROM custom_categories WHERE entity_type = 'role_template'")
            )
            slug_to_id = {row[1]: row[0] for row in cat_rows.fetchall()}

            for t in templates:
                category_id = slug_to_id.get(t.pop("old_category_slug"))
                if category_id is None:
                    continue
                t["category_id"] = category_id
                await conn.execute(
                    text(
                        "INSERT INTO role_templates (role_key, category_id, name, description, icon, color, content) "
                        "VALUES (:role_key, :category_id, :name, :description, :icon, :color, :content) "
                        "ON CONFLICT (role_key) DO NOTHING"
                    ),
                    t,
                )

    async def _backfill_category_ids(self):
        """根据 agents.category 旧 slug 回填 category_id。"""
        async with self.async_engine.begin() as conn:
            # 检查是否需要回填（agents 有 category 值但 category_id 为空）
            needs_backfill = await conn.scalar(
                text("SELECT COUNT(*) FROM agents WHERE category IS NOT NULL AND category_id IS NULL")
            )
            if not needs_backfill:
                return

            cat_rows = await conn.execute(
                text("SELECT id, slug FROM custom_categories WHERE entity_type = 'agent'")
            )
            slug_to_id = {row[1]: row[0] for row in cat_rows.fetchall()}

            for slug, cat_id in slug_to_id.items():
                await conn.execute(
                    text("UPDATE agents SET category_id = :cat_id WHERE category = :slug AND category_id IS NULL"),
                    {"cat_id": cat_id, "slug": slug},
                )
```

- [ ] **Step 5: 验证迁移无语法错误**

Run: `cd backend && uv run python -c "from yuxi.storage.postgres.manager import pg_manager; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/package/yuxi/storage/postgres/manager.py backend/package/yuxi/storage/postgres/seed_categories.py backend/package/yuxi/storage/postgres/seed_role_templates.py
git commit -m "feat: 数据库迁移 — custom_categories/role_templates 建表 + seed + 回填"
```

---

## Task 5: 后端 API — 分类管理路由

**Files:**
- Create: `backend/server/routers/category_router.py`
- Modify: `backend/server/routers/__init__.py`

- [ ] **Step 1: 创建 category_router.py**

```python
"""分类管理 API 路由（管理员权限）。"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.repositories.category_repository import CategoryRepository
from yuxi.storage.postgres.models_business import User

category_router = APIRouter(prefix="/system/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    entity_type: str
    slug: str
    label: str
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    slug: str | None = None
    label: str | None = None
    sort_order: int | None = None


VALID_ENTITY_TYPES = {"agent", "skill", "role_template"}


@category_router.get("")
async def list_categories(
    entity_type: str | None = None,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取分类列表（所有登录用户可见）。"""
    repo = CategoryRepository(db)
    if entity_type:
        if entity_type not in VALID_ENTITY_TYPES:
            raise HTTPException(status_code=400, detail=f"无效的 entity_type: {entity_type}")
        items = await repo.list_by_entity_type(entity_type)
    else:
        items = []
        for et in sorted(VALID_ENTITY_TYPES):
            items.extend(await repo.list_by_entity_type(et))
    return {"success": True, "data": [item.to_dict() for item in items]}


@category_router.post("")
async def create_category(
    payload: CategoryCreate,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """新增分类（管理员）。"""
    if payload.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的 entity_type: {payload.entity_type}")

    repo = CategoryRepository(db)
    if await repo.slug_exists(payload.entity_type, payload.slug):
        raise HTTPException(status_code=409, detail=f"分类 slug '{payload.slug}' 已存在")

    item = await repo.create(
        entity_type=payload.entity_type,
        slug=payload.slug,
        label=payload.label,
        sort_order=payload.sort_order,
        is_builtin=False,
    )
    await db.commit()
    return {"success": True, "data": item.to_dict()}


@category_router.put("/{category_id}")
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑分类（管理员）。"""
    repo = CategoryRepository(db)
    item = await repo.get_by_id(category_id)
    if not item:
        raise HTTPException(status_code=404, detail="分类不存在")

    updates = payload.model_dump(exclude_unset=True)
    if "slug" in updates and updates["slug"] != item.slug:
        if await repo.slug_exists(item.entity_type, updates["slug"], exclude_id=category_id):
            raise HTTPException(status_code=409, detail=f"分类 slug '{updates['slug']}' 已存在")

    item = await repo.update(item, **updates)
    await db.commit()
    return {"success": True, "data": item.to_dict()}


@category_router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """删除分类（管理员）。已关联实体需先迁移。"""
    repo = CategoryRepository(db)
    item = await repo.get_by_id(category_id)
    if not item:
        raise HTTPException(status_code=404, detail="分类不存在")

    entity_counts = await repo.count_entities_for_category(category_id)
    total = sum(entity_counts.values())
    if total > 0:
        detail_parts = [f"{et}: {n}" for et, n in entity_counts.items() if n > 0]
        raise HTTPException(
            status_code=409,
            detail=f"该分类下有 {total} 个关联实体（{', '.join(detail_parts)}），请先迁移",
        )

    await repo.delete(item)
    await db.commit()
    return {"success": True}
```

- [ ] **Step 2: 在 `__init__.py` 注册路由**

在 `backend/server/routers/__init__.py` 中添加：

```python
from server.routers.category_router import category_router
```

并在 `router.include_router(system)` 之后添加：

```python
router.include_router(category_router)  # /api/system/categories/* 自定义分类管理
```

- [ ] **Step 3: Commit**

```bash
git add backend/server/routers/category_router.py backend/server/routers/__init__.py
git commit -m "feat: 新增分类管理 API 路由 /api/system/categories"
```

---

## Task 6: 后端 API — 角色模板改造为数据库驱动

**Files:**
- Modify: `backend/server/routers/role_router.py`

- [ ] **Step 1: 重写 role_router.py 从数据库读取**

核心变更：
- `get_roles` 改为查询 `RoleTemplate` 表 + JOIN `CustomCategory`
- `get_categories` 改为查询 `custom_categories` WHERE `entity_type='role_template'`
- `get_role_detail` 改为按 `id` 查询（保留旧的 `/{category}/{role_id}` 路径做兼容）
- 新增 `PUT /{id}/category` 更新分类
- `import_role_as_agent` 改为从数据库读取 content

```python
"""角色模板库 API 路由（数据库驱动）。"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user
from yuxi.repositories.category_repository import CategoryRepository
from yuxi.repositories.role_template_repository import RoleTemplateRepository
from yuxi.repositories.agent_repository import AgentRepository
from yuxi.storage.postgres.models_business import User
from yuxi.utils.logging_config import logger

role_router = APIRouter(prefix="/roles", tags=["roles"])


class UpdateRoleCategory(BaseModel):
    category_id: int


@role_router.get("")
async def get_roles(
    category: int | None = None,
    offset: int = 0,
    limit: int = 50,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取角色列表（支持分页，从数据库读取）。"""
    repo = RoleTemplateRepository(db)
    items, total = await repo.list_all(category_id=category, offset=offset, limit=limit)
    category_counts = await repo.get_category_counts()

    return {
        "success": True,
        "data": [item.to_dict() for item in items],
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
    """获取角色分类列表（从 custom_categories 读取）。"""
    repo = CategoryRepository(db)
    items = await repo.list_by_entity_type("role_template")
    return {
        "success": True,
        "data": [{"id": item.id, "name": item.label, "slug": item.slug} for item in items],
    }


@role_router.get("/{template_id}")
async def get_role_detail(
    template_id: int,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """获取角色详情（按数据库 ID）。"""
    repo = RoleTemplateRepository(db)
    item = await repo.get_by_id(template_id)
    if not item:
        raise HTTPException(status_code=404, detail="角色不存在")
    return {
        "success": True,
        "data": item.to_dict(include_content=True),
    }


@role_router.post("/{template_id}/import")
async def import_role_as_agent(
    template_id: int,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """将角色导入为 Agent。"""
    repo = RoleTemplateRepository(db)
    item = await repo.get_by_id(template_id)
    if not item:
        raise HTTPException(status_code=404, detail="角色不存在")

    slug = f"role-{item.role_key.replace('/', '-')}-{user.uid}"

    agent_repo = AgentRepository(db)
    try:
        agent = await agent_repo.create(
            name=item.name,
            slug=slug,
            backend_id="ChatbotAgent",
            description=item.description or f"从角色模板导入: {item.name}",
            icon=item.icon or "👤",
            config_json={"context": {"system_prompt": item.content}},
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
            "role": item.to_dict(),
        },
    }


@role_router.put("/{template_id}/category")
async def update_role_category(
    template_id: int,
    payload: UpdateRoleCategory,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """更新角色模板分类（管理员）。"""
    cat_repo = CategoryRepository(db)
    cat = await cat_repo.get_by_id(payload.category_id)
    if not cat or cat.entity_type != "role_template":
        raise HTTPException(status_code=400, detail="无效的分类 ID")

    repo = RoleTemplateRepository(db)
    item = await repo.update_category(template_id, payload.category_id)
    if not item:
        raise HTTPException(status_code=404, detail="角色不存在")

    await db.commit()
    return {"success": True, "data": item.to_dict()}
```

- [ ] **Step 2: Commit**

```bash
git add backend/server/routers/role_router.py
git commit -m "feat: 角色模板 API 改造为数据库驱动"
```

---

## Task 7: 前端 API 层 — categoryApi + useCategories

**Files:**
- Create: `web/src/apis/category_api.js`
- Create: `web/src/composables/useCategories.js`

- [ ] **Step 1: 创建 category_api.js**

```javascript
import { apiGet, apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

const BASE_URL = '/api/system/categories'

export const categoryApi = {
  /** 获取分类列表 */
  list(entityType = null) {
    const params = entityType ? `?entity_type=${entityType}` : ''
    return apiGet(`${BASE_URL}${params}`)
  },

  /** 新增分类 */
  create(data) {
    return apiAdminPost(BASE_URL, data)
  },

  /** 编辑分类 */
  update(id, data) {
    return apiAdminPut(`${BASE_URL}/${id}`, data)
  },

  /** 删除分类 */
  delete(id) {
    return apiAdminDelete(`${BASE_URL}/${id}`)
  }
}
```

- [ ] **Step 2: 创建 useCategories.js**

```javascript
import { ref, watch } from 'vue'
import { categoryApi } from '@/apis/category_api'

const cache = new Map()

export function useCategories(entityType) {
  const categories = ref([])
  const loading = ref(false)
  const loaded = ref(false)

  const load = async (force = false) => {
    if (!force && loaded.value) return
    loading.value = true
    try {
      const res = await categoryApi.list(entityType)
      categories.value = res.data || []
      loaded.value = true
    } catch (error) {
      console.warn(`加载 ${entityType} 分类失败:`, error)
    } finally {
      loading.value = false
    }
  }

  const refresh = () => load(true)

  const getLabel = (id) => {
    const cat = categories.value.find((c) => c.id === id)
    return cat ? cat.label : ''
  }

  return { categories, loading, loaded, load, refresh, getLabel }
}
```

- [ ] **Step 3: Commit**

```bash
git add web/src/apis/category_api.js web/src/composables/useCategories.js
git commit -m "feat: 新增 categoryApi 和 useCategories composable"
```

---

## Task 8: 前端 — DesignSettingsSection.vue

**Files:**
- Create: `web/src/components/settings/DesignSettingsSection.vue`

- [ ] **Step 1: 创建设计设置面板组件**

```vue
<script setup>
import { ref, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { Plus, Pencil, Trash2 } from '@lucide/vue'
import { useCategories } from '@/composables/useCategories'
import { categoryApi } from '@/apis/category_api'

const ENTITY_TYPES = [
  { key: 'agent', label: '智能体分类', description: '管理智能体的分类标签，影响智能体管理页的分类筛选。' },
  { key: 'skill', label: '技能分类', description: '管理技能的分类标签，影响技能市场的分类筛选。' },
  { key: 'role_template', label: '角色模板分类', description: '管理角色模板的分类标签，影响角色模板页的分类筛选和卡片展示。' },
]

const sections = ENTITY_TYPES.map(({ key }) => {
  const { categories, loading, load } = useCategories(key)
  return { key, categories, loading, load }
})

const modalVisible = ref(false)
const modalTitle = ref('')
const modalMode = ref<'create' | 'edit'>('create')
const currentEntityType = ref('')
const editingId = ref(null)
const formState = ref({ slug: '', label: '', sort_order: 0 })
const saving = ref(false)

const openCreate = (entityType) => {
  currentEntityType.value = entityType
  modalMode.value = 'create'
  modalTitle.value = `新增${ENTITY_TYPES.find(e => e.key === entityType)?.label || ''}`
  formState.value = { slug: '', label: '', sort_order: 0 }
  modalVisible.value = true
}

const openEdit = (entityType, item) => {
  currentEntityType.value = entityType
  modalMode.value = 'edit'
  editingId.value = item.id
  modalTitle.value = `编辑分类`
  formState.value = { slug: item.slug, label: item.label, sort_order: item.sort_order }
  modalVisible.value = true
}

const handleSave = async () => {
  if (!formState.value.slug || !formState.value.label) {
    message.warning('请填写完整信息')
    return
  }
  saving.value = true
  try {
    if (modalMode.value === 'create') {
      await categoryApi.create({ entity_type: currentEntityType.value, ...formState.value })
      message.success('分类已创建')
    } else {
      await categoryApi.update(editingId.value, formState.value)
      message.success('分类已更新')
    }
    modalVisible.value = false
    const section = sections.find(s => s.key === currentEntityType.value)
    if (section) section.load(true)
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || '操作失败')
  } finally {
    saving.value = false
  }
}

const handleDelete = (entityType, item) => {
  Modal.confirm({
    title: '确认删除',
    content: `确定要删除分类「${item.label}」吗？`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await categoryApi.delete(item.id)
        message.success('分类已删除')
        const section = sections.find(s => s.key === entityType)
        if (section) section.load(true)
      } catch (error) {
        message.error(error.response?.data?.detail || error.message || '删除失败')
      }
    },
  })
}

onMounted(() => {
  sections.forEach(s => s.load())
})
</script>

<template>
  <div class="design-settings-section">
    <div class="header-section">
      <h3 class="section-title">设计</h3>
      <p class="section-description">管理智能体、技能和角色模板的分类体系。修改分类后，相关页面的分类筛选将同步更新。</p>
    </div>

    <div class="content-section">
      <div v-for="section in sections" :key="section.key" class="category-block">
        <div class="block-header">
          <div>
            <h4 class="block-title">{{ ENTITY_TYPES.find(e => e.key === section.key)?.label }}</h4>
            <p class="block-desc">{{ ENTITY_TYPES.find(e => e.key === section.key)?.description }}</p>
          </div>
          <button type="button" class="add-btn" @click="openCreate(section.key)">
            <Plus :size="14" />
            <span>新增</span>
          </button>
        </div>

        <a-table
          :data-source="section.categories"
          :loading="section.loading.value"
          :pagination="false"
          size="small"
          :columns="[
            { title: '名称', dataIndex: 'label', key: 'label' },
            { title: '标识', dataIndex: 'slug', key: 'slug' },
            { title: '排序', dataIndex: 'sort_order', key: 'sort_order', width: 80 },
            { title: '操作', key: 'actions', width: 100 },
          ]"
          row-key="id"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'actions'">
              <button type="button" class="icon-btn" @click="openEdit(section.key, record)" title="编辑">
                <Pencil :size="14" />
              </button>
              <button type="button" class="icon-btn danger" @click="handleDelete(section.key, record)" title="删除">
                <Trash2 :size="14" />
              </button>
            </template>
          </template>
        </a-table>
      </div>
    </div>

    <a-modal
      v-model:open="modalVisible"
      :title="modalTitle"
      :confirm-loading="saving"
      @ok="handleSave"
      ok-text="保存"
      cancel-text="取消"
    >
      <a-form layout="vertical" style="margin-top: 16px">
        <a-form-item label="标识 (slug)">
          <a-input v-model:value="formState.slug" placeholder="如: office" :disabled="modalMode === 'edit'" />
        </a-form-item>
        <a-form-item label="显示名称">
          <a-input v-model:value="formState.label" placeholder="如: 办公协同" />
        </a-form-item>
        <a-form-item label="排序">
          <a-input-number v-model:value="formState.sort_order" :min="0" style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style lang="less" scoped>
.design-settings-section {
  padding: 20px 24px;
  overflow-y: auto;
  height: 100%;
}

.header-section {
  margin-bottom: 20px;
}

.section-title {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 600;
  color: var(--gray-2000);
}

.section-description {
  margin: 0;
  font-size: 13px;
  color: var(--gray-600);
}

.category-block {
  margin-bottom: 28px;
  padding: 16px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
}

.block-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}

.block-title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
  color: var(--gray-900);
}

.block-desc {
  margin: 0;
  font-size: 12px;
  color: var(--gray-500);
}

.add-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-700);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    border-color: var(--main-color);
    color: var(--main-color);
  }
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--gray-500);
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--gray-50);
    color: var(--gray-900);
  }

  &.danger:hover {
    background: #fff1f0;
    color: #ff4d4f;
  }
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add web/src/components/settings/DesignSettingsSection.vue
git commit -m "feat: 新建设计设置面板 DesignSettingsSection"
```

---

## Task 9: 前端 — SettingsModal.vue 集成

**Files:**
- Modify: `web/src/components/SettingsModal.vue`

- [ ] **Step 1: 添加「设计」Tab 侧边栏项**

在 Desktop 侧边栏中，「OCR 配置」和「用户管理」之间插入：

```html
<div
  class="sider-item"
  :class="{ activesec: activeTab === 'design' }"
  @click="activeTab = 'design'"
  v-if="userStore.isAdmin"
>
  <Palette class="icon" :size="18" />
  <span>设计</span>
</div>
```

在 Mobile 导航中同样添加对应项。

- [ ] **Step 2: 添加内容区域**

```html
<div v-show="activeTab === 'design'" v-if="userStore.isAdmin && loadedTabs.has('design')">
  <DesignSettingsSection />
</div>
```

- [ ] **Step 3: 注册异步组件和图标**

```javascript
import { Palette } from '@lucide/vue'
const DesignSettingsSection = createAsyncPanel(
  () => import('@/components/settings/DesignSettingsSection.vue')
)
```

并在 `availableTabs` 中添加 `'design'`。

- [ ] **Step 4: Commit**

```bash
git add web/src/components/SettingsModal.vue
git commit -m "feat: 设置面板新增「设计」Tab"
```

---

## Task 10: 前端 — RoleTemplatePanel.vue 重新分类

**Files:**
- Modify: `web/src/components/roles/RoleTemplatePanel.vue`
- Modify: `web/src/apis/workflow_api.js`（roleApi 新增 updateCategory）

- [ ] **Step 1: 在 roleApi 中新增 updateCategory 方法**

```javascript
updateCategory(templateId, categoryId) {
  return apiAdminPut(`${ROLES_URL}/${templateId}/category`, { category_id: categoryId })
}
```

- [ ] **Step 2: 改造 RoleTemplatePanel.vue**

核心变更：
- 使用 `useCategories('role_template')` 加载分类
- 管理员模式下，卡片 tag 区域的分类名渲染为可点击按钮
- 点击后弹出 `a-popover`，平铺展示所有分类
- 当前分类高亮，点击其他分类调用 `roleApi.updateCategory`
- 成功后刷新卡片显示

- [ ] **Step 3: Commit**

```bash
git add web/src/components/roles/RoleTemplatePanel.vue web/src/apis/workflow_api.js
git commit -m "feat: 角色模板卡片支持管理员快速重新分类"
```

---

## Task 11: 前端 — Agent/Skill 消费者改造

**Files:**
- Modify: `web/src/components/model-management/AgentManagePanel.vue`
- Modify: `web/src/components/model-management/AgentEditModal.vue`
- Modify: `web/src/components/extensions/SkillCardList.vue`

- [ ] **Step 1: AgentManagePanel.vue 改造**

将硬编码的 `CATEGORIES` / `CATEGORY_LABELS` 导入替换为 `useCategories('agent')`：

```javascript
import { useCategories } from '@/composables/useCategories'
const { categories: dynamicCategories, load: loadCategories } = useCategories('agent')
```

分类标签栏和 `categoryCounts` 计算属性改为从 `dynamicCategories` 获取。

- [ ] **Step 2: AgentEditModal.vue 改造**

将 `AGENT_CATEGORIES` 常量替换为从 API 动态获取的分类列表。

- [ ] **Step 3: SkillCardList.vue 改造**

同 AgentManagePanel，将硬编码分类替换为 `useCategories('skill')`。

- [ ] **Step 4: Commit**

```bash
git add web/src/components/model-management/AgentManagePanel.vue web/src/components/model-management/AgentEditModal.vue web/src/components/extensions/SkillCardList.vue
git commit -m "feat: Agent/Skill 分类标签栏改为从 API 动态加载"
```

---

## Task 12: 测试 + 验证

- [ ] **Step 1: 后端单元测试**

Run: `cd backend && uv run pytest test/unit/repositories/ -v`

- [ ] **Step 2: 后端工程契约检查**

Run: `cd backend && uv run python -c "from yuxi.storage.postgres.models_business import CustomCategory, RoleTemplate; print('Models OK')"`

- [ ] **Step 3: 前端 lint + 构建检查**

Run: `cd web && pnpm lint && pnpm build`

- [ ] **Step 4: 前端单元测试**

Run: `cd web && pnpm test:unit`

- [ ] **Step 5: 最终 Commit**

```bash
git add -A
git commit -m "feat: 自定义分类管理系统完整实现"
```
