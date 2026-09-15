"""导入单个 AO 工作流到 Yuxi 平台工作流库。

用法（在 Docker 容器内执行）:
    uv run python scripts/import_one_workflow.py <yaml_filename> [--category CATEGORY_SLUG]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "package"))

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from yuxi.storage.postgres.models_business import CustomCategory, Workflow

# 复用 migrate_ao_workflows 的转换逻辑
sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_ao_workflows import convert_ao_to_yuxi, get_category_slug

AO_DIR = os.environ.get("AO_DIR", r"D:\AIProjects\agents\agency-orchestrator")


def generate_slug(name: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "-", name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "workflow"


async def main(yaml_filename: str, category_slug_override: str | None = None):
    db_url = os.environ.get(
        "POSTGRES_URL",
        "postgresql+asyncpg://postgres:postgres@postgres:5432/yuxi",
    )
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 查找 YAML 文件
    workflows_dir = Path(AO_DIR) / "workflows"
    yf = workflows_dir / yaml_filename
    if not yf.exists():
        for sub in workflows_dir.iterdir():
            if sub.is_dir():
                candidate = sub / yaml_filename
                if candidate.exists():
                    yf = candidate
                    break

    if not yf.exists():
        print(f"错误: 找不到工作流文件: {yaml_filename}")
        await engine.dispose()
        return

    # 读取并转换
    with open(yf, "r", encoding="utf-8") as f:
        ao_wf = yaml.safe_load(f)

    converted = convert_ao_to_yuxi(ao_wf, str(yf.relative_to(workflows_dir)))
    category_slug = category_slug_override or get_category_slug(str(yf.parent), yf.name)

    print(f"文件: {yf}")
    print(f"名称: {converted['name']}")
    print(f"描述: {converted['description'][:80]}...")
    print(f"步骤数: {len(converted['definition']['steps'])}")
    print(f"分类: {category_slug}")

    slug = generate_slug(converted["name"])
    print(f"Slug: {slug}")

    async with async_session() as session:
        # 加载分类
        stmt = select(CustomCategory.id, CustomCategory.slug).where(
            CustomCategory.entity_type == "workflow"
        )
        result = await session.execute(stmt)
        category_cache = {row[1]: row[0] for row in result.all()}
        category_id = category_cache.get(category_slug)

        # 检查是否已存在
        check = await session.execute(select(Workflow.id).where(Workflow.slug == slug))
        if check.scalar() is not None:
            print(f"跳过: {converted['name']} 已存在 (slug={slug})")
            await engine.dispose()
            return

        wf = Workflow(
            name=converted["name"],
            slug=slug,
            description=converted["description"],
            icon=converted["icon"],
            definition=converted["definition"],
            category_id=category_id,
            scope="platform",
            created_by="system",
        )
        session.add(wf)
        await session.commit()
        n_steps = len(converted["definition"]["steps"])
        print(f"\n✅ 导入成功: {converted['name']} (id={wf.id}, category={category_slug}, steps={n_steps})")

        # 列出使用的角色
        roles = set()
        for step in converted["definition"]["steps"]:
            if step.get("agent_slug"):
                roles.add(step["agent_slug"])
        if roles:
            print(f"使用的角色: {', '.join(sorted(roles))}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入单个 AO 工作流")
    parser.add_argument("filename", help="YAML 文件名（如 product-review.yaml）")
    parser.add_argument("--category", help="覆盖分类 slug")
    args = parser.parse_args()

    asyncio.run(main(args.filename, args.category))
