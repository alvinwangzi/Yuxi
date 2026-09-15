"""初始化工作流分类 — 基于 Agency Orchestrator 项目目录结构。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 确保能 import yuxi 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "package"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from yuxi.storage.postgres.models_business import CustomCategory

# AO 工作流目录 → 中文分类名映射
WORKFLOW_CATEGORIES = [
    ("content", "内容创作", 1),
    ("data", "数据分析", 2),
    ("department-collab", "部门协作", 3),
    ("design", "设计创意", 4),
    ("dev", "开发工具", 5),
    ("hr", "人力资源", 6),
    ("legal", "法务合规", 7),
    ("marketing", "市场营销", 8),
    ("ops", "运营管理", 9),
    ("strategy", "战略规划", 10),
]


async def seed_workflow_categories(database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        for slug, label, sort_order in WORKFLOW_CATEGORIES:
            # 检查是否已存在
            stmt = select(CustomCategory.id).where(
                CustomCategory.entity_type == "workflow",
                CustomCategory.slug == slug,
            )
            result = await session.execute(stmt)
            if result.scalar() is not None:
                print(f"  跳过: {slug} ({label}) — 已存在")
                continue

            cat = CustomCategory(
                entity_type="workflow",
                slug=slug,
                label=label,
                sort_order=sort_order,
                is_builtin=True,
            )
            session.add(cat)
            await session.flush()
            print(f"  创建: {slug} → {label}")

        await session.commit()
        print("工作流分类初始化完成")

    await engine.dispose()


if __name__ == "__main__":
    import os

    db_url = os.environ.get("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi")
    print(f"数据库: {db_url.split('@')[-1]}")
    print("开始初始化工作流分类...")
    asyncio.run(seed_workflow_categories(db_url))
