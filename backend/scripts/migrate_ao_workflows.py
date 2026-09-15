"""Agency Orchestrator YAML 工作流 → Yuxi JSON definition 迁移脚本。

用法:
    uv run python scripts/migrate_ao_workflows.py [--ao-dir DIR] [--dry-run] [--import]

- --ao-dir: AO 项目路径（默认 D:\\AIProjects\\agents\\agency-orchestrator）
- --dry-run: 只打印转换结果，不写入数据库
- --import: 转换后直接导入到数据库
- --limit N: 只处理前 N 个工作流（用于测试）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "package"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from yuxi.storage.postgres.models_business import CustomCategory, Workflow

# AO 步骤 id → 中文显示名（用于迁移时自动翻译）
STEP_NAME_ZH = {
    "analyze": "需求分析",
    "analysis": "现状分析",
    "tech_review": "技术评审",
    "design_review": "设计评审",
    "final_summary": "最终总结",
    "research": "主题研究",
    "financial": "财务分析",
    "risk": "风险识别",
    "forecast": "前景预测",
    "facts": "事实梳理",
    "review": "审查",
    "opinion": "法律意见书",
    "draft": "初稿撰写",
    "finalize": "定稿",
    "spec": "需求规格",
    "codex": "Codex 生成",
    "claude": "Claude 审查",
    "test": "测试验证",
    "kr-breakdown": "KR 拆解",
    "q1-plan": "Q1 行动方案",
    "okr-doc": "OKR 文档",
}

# AO 目录名 → Yuxi 分类 slug
DIR_TO_CATEGORY_SLUG = {
    "data": "data",
    "department-collab": "department-collab",
    "design": "design",
    "dev": "dev",
    "en": "content",  # 英文工作流归入内容创作
    "hr": "hr",
    "legal": "legal",
    "marketing": "marketing",
    "ops": "ops",
    "strategy": "strategy",
}

# 根目录工作流默认分类
ROOT_DEFAULT_CATEGORY = "content"


def convert_ao_to_yuxi(ao_workflow: dict, yaml_filename: str) -> dict:
    """将 AO YAML 工作流转换为 Yuxi definition 格式。

    Args:
        ao_workflow: AO YAML 解析后的字典
        yaml_filename: 原始文件名（用于生成 slug）

    Returns:
        Yuxi workflow definition 字典
    """
    steps = ao_workflow.get("steps", [])
    inputs = ao_workflow.get("inputs", [])
    concurrency = ao_workflow.get("concurrency", 4)

    yuxi_steps = []

    # 1. 创建 start 步骤
    start_step = {
        "id": "start",
        "type": "start",
        "name": "输入",
    }
    # 将 AO inputs 转为 Yuxi variables
    variables = []
    for inp in inputs:
        variables.append({
            "name": inp.get("name", ""),
            "default": inp.get("default", ""),
        })
    if variables:
        start_step["variables"] = variables
    yuxi_steps.append(start_step)

    # 2. 转换业务步骤
    for idx, ao_step in enumerate(steps):
        step_id = ao_step.get("id", "")
        step_type = "llm"  # AO 步骤基本都是 LLM 类型

        # 第一个无 depends_on 的业务步骤默认依赖 start
        deps = ao_step.get("depends_on", [])
        if not deps and idx == 0:
            deps = ["start"]

        yuxi_step = {
            "id": step_id,
            "type": step_type,
            "name": ao_step.get("name") or STEP_NAME_ZH.get(step_id, step_id),
            "prompt": ao_step.get("task", ""),
            "depends_on": deps,
        }

        # output → output_key
        if ao_step.get("output"):
            yuxi_step["output_key"] = ao_step["output"]

        # emoji → icon
        if ao_step.get("emoji"):
            yuxi_step["icon"] = ao_step["emoji"]

        # loop 配置
        if ao_step.get("loop") and isinstance(ao_step["loop"], dict):
            loop = ao_step["loop"]
            yuxi_step["loop"] = {
                "back_to": loop.get("back_to"),
                "max_iterations": loop.get("max_iterations", 3),
                "exit_condition": loop.get("exit_condition"),
            }

        # role → agent_slug（/ 替换为 -，与 Agent 记录 slug 一致）
        role = ao_step.get("role", "")
        if role:
            yuxi_step["agent_slug"] = role.replace("/", "-")

        yuxi_steps.append(yuxi_step)

    # 3. 创建 end 步骤
    last_step_id = steps[-1]["id"] if steps else "start"
    end_step = {
        "id": "end",
        "type": "end",
        "name": "输出",
        "output_key": "end",
        "depends_on": [last_step_id],
    }
    # 如果有最终 output，用模板引用
    final_output = steps[-1].get("output", "") if steps else ""
    if final_output:
        end_step["template"] = f"{{{{{final_output}}}}}"
    yuxi_steps.append(end_step)

    # 4. 组装 definition
    definition = {
        "steps": yuxi_steps,
        "concurrency": concurrency,
    }

    # 5. 提取元信息
    name = ao_workflow.get("name", Path(yaml_filename).stem)
    description = ao_workflow.get("description", "")
    icon = "🔄"

    # 尝试从第一个业务步骤获取 emoji 作为工作流图标
    for s in steps:
        if s.get("emoji"):
            icon = s["emoji"]
            break

    return {
        "name": name,
        "description": description,
        "icon": icon,
        "definition": definition,
        "source_file": yaml_filename,
    }


def get_category_slug(ao_dir: str, yaml_filename: str) -> str:
    """根据 AO 目录结构确定分类 slug。"""
    # 如果在子目录中
    for dir_name, slug in DIR_TO_CATEGORY_SLUG.items():
        if ao_dir.endswith(dir_name) or f"{os.sep}{dir_name}{os.sep}" in ao_dir:
            return slug
    return ROOT_DEFAULT_CATEGORY


async def migrate_workflows(
    ao_dir: str,
    database_url: str,
    *,
    dry_run: bool = False,
    do_import: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """迁移 AO 工作流到 Yuxi 格式。"""
    ao_path = Path(ao_dir) / "workflows"
    if not ao_path.exists():
        print(f"错误: AO 工作流目录不存在: {ao_path}")
        return []

    # 收集所有 YAML 文件
    yaml_files = []
    for yf in sorted(ao_path.rglob("*.yaml")):
        yaml_files.append(yf)

    if limit:
        yaml_files = yaml_files[:limit]

    print(f"找到 {len(yaml_files)} 个工作流文件")

    results = []
    category_cache: dict[str, int] = {}  # slug → id

    for yf in yaml_files:
        try:
            with open(yf, "r", encoding="utf-8") as f:
                ao_wf = yaml.safe_load(f)

            if not ao_wf or not isinstance(ao_wf, dict):
                print(f"  跳过: {yf.name} (无效 YAML)")
                continue

            converted = convert_ao_to_yuxi(ao_wf, str(yf.relative_to(ao_path)))
            category_slug = get_category_slug(str(yf.parent), yf.name)
            converted["category_slug"] = category_slug

            results.append(converted)

            if dry_run:
                print(f"  [DRY] {converted['name']} ({category_slug}) — {len(converted['definition']['steps'])} steps")
            elif do_import:
                # 导入到数据库
                pass  # 在下方统一处理

        except Exception as e:
            print(f"  错误: {yf.name}: {e}")

    if do_import and not dry_run:
        engine = create_async_engine(database_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # 预加载分类
            stmt = select(CustomCategory.id, CustomCategory.slug).where(
                CustomCategory.entity_type == "workflow"
            )
            result = await session.execute(stmt)
            for row in result.all():
                category_cache[row.slug] = row.id

            for converted in results:
                slug = _generate_slug(converted["name"])
                category_id = category_cache.get(converted["category_slug"])

                # 检查是否已存在
                check_stmt = select(Workflow.id).where(Workflow.slug == slug)
                check_result = await session.execute(check_stmt)
                if check_result.scalar() is not None:
                    print(f"  跳过: {converted['name']} (已存在)")
                    continue

                wf = Workflow(
                    name=converted["name"],
                    slug=slug,
                    description=converted["description"],
                    icon=converted["icon"],
                    definition=converted["definition"],
                    category_id=category_id,
                    is_builtin=True,
                    created_by="system",
                )
                session.add(wf)
                await session.flush()
                print(f"  导入: {converted['name']} → category={converted['category_slug']} ({len(converted['definition']['steps'])} steps)")

            await session.commit()
            print(f"导入完成，共 {len(results)} 个工作流")

        await engine.dispose()

    return results


def _generate_slug(name: str) -> str:
    """从名称生成 URL 友好的 slug。"""
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "-", name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "workflow"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AO 工作流迁移工具")
    parser.add_argument("--ao-dir", default=r"D:\AIProjects\agents\agency-orchestrator", help="AO 项目路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印转换结果")
    parser.add_argument("--import", dest="do_import", action="store_true", help="导入到数据库")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个")
    args = parser.parse_args()

    db_url = os.environ.get("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi")

    if args.do_import:
        # 导入模式需要在 Docker 容器内运行，使用容器内的数据库 URL
        db_url = os.environ.get("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/yuxi")

    print(f"AO 目录: {args.ao_dir}")
    print(f"模式: {'DRY RUN' if args.dry_run else 'IMPORT' if args.do_import else 'CONVERT'}")
    if args.limit:
        print(f"限制: 前 {args.limit} 个")

    asyncio.run(migrate_workflows(
        args.ao_dir,
        db_url,
        dry_run=args.dry_run,
        do_import=args.do_import,
        limit=args.limit,
    ))
