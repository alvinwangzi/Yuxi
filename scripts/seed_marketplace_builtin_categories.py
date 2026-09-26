#!/usr/bin/env python3
"""
为系统预制技能（builtin）初始化分类。

分类依据：
1. alvin 用户已标记的个人技能分类（直接映射）
2. 技能名称语义推断（参考 alvin 的分类模式）

alvin 已分类的技能：
- consulting-analysis → 企业管理 (id=87)
- find-skills → 通用 (id=15)
- self-improving-agent → 通用 (id=15)
- skill-creator → 通用 (id=15)
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "package"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from yuxi.marketplace.models import SkillMarketEntry

# 分类映射：slug → category_id
# 基于 alvin 已标记的分类 + 技能名称语义推断
CATEGORY_MAP = {
    # alvin 已标记：企业管理
    "consulting-analysis": 87,
    # 数据分析
    "chart-renderer": 17,
    "data-analysis": 17,
    "knowledge-base": 17,
    "mysql-reporter": 17,
    # 研究
    "deep-research": 26,
    "github-deep-research": 26,
    "systematic-literature-review": 26,
    "academic-paper-review": 26,
    # 内容创作
    "image-gen": 18,
    "music-generation": 18,
    "podcast-generation": 18,
    "video-generation": 18,
    # 办公协同
    "dashi-ppt": 301,
    "newsletter-generation": 301,
    # 开发工具
    "frontend-design": 273,
    "html-preview": 273,
    # 代码助手
    "code-documentation": 19,
    # 设计
    "web-design-guidelines": 23,
}


async def main():
    db_url = os.environ.get("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi")
    engine = create_async_engine(db_url)

    async with AsyncSession(engine) as session:
        updated = 0
        skipped = 0

        for slug_suffix, category_id in CATEGORY_MAP.items():
            full_slug = f"builtin-{slug_suffix}"
            result = await session.execute(
                select(SkillMarketEntry).where(SkillMarketEntry.slug == full_slug)
            )
            entry = result.scalar_one_or_none()

            if not entry:
                print(f"  [跳过] {full_slug} 不存在")
                skipped += 1
                continue

            if entry.category_id is not None:
                print(f"  [跳过] {full_slug} 已有分类 ({entry.category_id})")
                skipped += 1
                continue

            entry.category_id = category_id
            updated += 1
            print(f"  [更新] {full_slug} → category_id={category_id}")

        await session.commit()
        print(f"\n完成：更新 {updated} 条，跳过 {skipped} 条")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
