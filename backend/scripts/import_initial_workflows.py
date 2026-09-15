"""首批导入 5 个 AO 工作流到 Yuxi。"""
import asyncio, json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "package"))

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from yuxi.storage.postgres.models_business import CustomCategory, Workflow

# AO 步骤 id → 中文显示名
STEP_NAME_ZH = {
    "analyze": "需求分析", "analysis": "现状分析",
    "tech_review": "技术评审", "design_review": "设计评审",
    "final_summary": "最终总结", "research": "主题研究",
    "financial": "财务分析", "risk": "风险识别",
    "forecast": "前景预测", "facts": "事实梳理",
    "review": "审查", "opinion": "法律意见书",
    "draft": "初稿撰写", "finalize": "定稿",
    "spec": "需求规格", "codex": "Codex 生成",
    "claude": "Claude 审查", "test": "测试验证",
    "kr-breakdown": "KR 拆解", "q1-plan": "Q1 行动方案",
    "okr-doc": "OKR 文档",
}

AO_DIR = os.environ.get("AO_DIR", "/tmp/agency-orchestrator")

WORKFLOWS_TO_IMPORT = [
    "okr-decomposition.yaml",
    "content-pipeline.yaml",
    "codex-cc-loop.yaml",
    "investment-analysis.yaml",
    "legal-consultation.yaml",
]

DIR_TO_CATEGORY_SLUG = {
    "data": "data", "department-collab": "department-collab",
    "design": "design", "dev": "dev", "en": "content",
    "hr": "hr", "legal": "legal", "marketing": "marketing",
    "ops": "ops", "strategy": "strategy",
}

def convert_ao_to_yuxi(ao_wf, yaml_filename):
    steps = ao_wf.get("steps", [])
    inputs = ao_wf.get("inputs", [])
    concurrency = ao_wf.get("concurrency", 4)
    yuxi_steps = []

    start_step = {"id": "start", "type": "start", "name": "输入"}
    variables = [{"name": inp.get("name", ""), "default": inp.get("default", "")} for inp in inputs]
    if variables:
        start_step["variables"] = variables
    yuxi_steps.append(start_step)

    for idx, ao_step in enumerate(steps):
        step_id = ao_step.get("id", "")
        # 第一个无 depends_on 的业务步骤默认依赖 start
        deps = ao_step.get("depends_on", [])
        if not deps and idx == 0:
            deps = ["start"]
        yuxi_step = {
            "id": step_id,
            "type": "llm",
            "name": ao_step.get("name") or STEP_NAME_ZH.get(step_id, step_id),
            "prompt": ao_step.get("task", ""),
            "depends_on": deps,
        }
        if ao_step.get("output"):
            yuxi_step["output_key"] = ao_step["output"]
        if ao_step.get("emoji"):
            yuxi_step["icon"] = ao_step["emoji"]
        if ao_step.get("loop") and isinstance(ao_step["loop"], dict):
            loop = ao_step["loop"]
            yuxi_step["loop"] = {
                "back_to": loop.get("back_to"),
                "max_iterations": loop.get("max_iterations", 3),
                "exit_condition": loop.get("exit_condition"),
            }
        role = ao_step.get("role", "")
        if role:
            # / 替换为 -，与 Agent 记录 slug 一致
            yuxi_step["agent_slug"] = role.replace("/", "-")
        yuxi_steps.append(yuxi_step)

    last_step_id = steps[-1]["id"] if steps else "start"
    end_step = {"id": "end", "type": "end", "name": "输出", "output_key": "end", "depends_on": [last_step_id]}
    final_output = steps[-1].get("output", "") if steps else ""
    if final_output:
        end_step["template"] = "{{" + final_output + "}}"
    yuxi_steps.append(end_step)

    definition = {"steps": yuxi_steps, "concurrency": concurrency}
    name = ao_wf.get("name", Path(yaml_filename).stem)
    description = ao_wf.get("description", "")
    icon = "🔄"
    for s in steps:
        if s.get("emoji"):
            icon = s["emoji"]
            break

    return {"name": name, "description": description, "icon": icon, "definition": definition}

def get_category_slug(parent_dir_name):
    return DIR_TO_CATEGORY_SLUG.get(parent_dir_name, "content")

def generate_slug(name):
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "-", name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "workflow"

async def main():
    db_url = os.environ.get("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/yuxi")
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 加载分类映射
    category_cache = {}
    async with async_session() as session:
        stmt = select(CustomCategory.id, CustomCategory.slug).where(CustomCategory.entity_type == "workflow")
        result = await session.execute(stmt)
        for row in result.all():
            category_cache[row.slug] = row.id

    workflows_dir = Path(AO_DIR) / "workflows"

    for filename in WORKFLOWS_TO_IMPORT:
        # 在根目录和子目录中查找
        yf = workflows_dir / filename
        if not yf.exists():
            for sub in workflows_dir.iterdir():
                if sub.is_dir():
                    candidate = sub / filename
                    if candidate.exists():
                        yf = candidate
                        break

        if not yf.exists():
            print(f"  NOT FOUND: {filename}")
            continue

        with open(yf, "r", encoding="utf-8") as f:
            ao_wf = yaml.safe_load(f)

        converted = convert_ao_to_yuxi(ao_wf, filename)
        category_slug = get_category_slug(yf.parent.name)
        category_id = category_cache.get(category_slug)
        slug = generate_slug(converted["name"])

        async with async_session() as session:
            check = await session.execute(select(Workflow.id).where(Workflow.slug == slug))
            if check.scalar() is not None:
                print(f"  SKIP: {converted['name']} (exists)")
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
            await session.commit()
            n_steps = len(converted["definition"]["steps"])
            print(f"  OK: {converted['name']} (category={category_slug}, steps={n_steps})")

    await engine.dispose()
    print("Done")

if __name__ == "__main__":
    asyncio.run(main())
