"""从中文版 AO 项目导入角色模板到 Yuxi。

用法:
    python scripts/import_ao_roles.py [ao_project_path]

默认路径: D:/AIProjects/agency-agents-zh
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


# 要导入的分类目录（按企业逻辑排序，排除 strategy/evals 等非角色目录）
CATEGORIES = [
    "company",
    "sales",
    "marketing",
    "paid-media",
    "hr",
    "finance",
    "legal",
    "supply-chain",
    "product",
    "project-management",
    "engineering",
    "design",
    "testing",
    "support",
    "security",
    "specialized",
    "gis",
    "spatial-computing",
    "game-development",
    "academic",
]

# 非角色模板文件（文档/指南/元数据/评测）
SKIP_FILES = {
    "README.md", "NOTICE.md", "EXECUTIVE-BRIEF.md", "QUICKSTART.md",
    "nexus-strategy.md", "SEARCH-GROWTH-STACK.md",
}


def import_roles(ao_agents_dir: Path, target_dir: Path) -> int:
    """从 AO 项目复制角色文件，保留子目录结构。

    Returns:
        复制的文件数量
    """
    if not ao_agents_dir.exists():
        print(f"错误: AO agents 目录不存在: {ao_agents_dir}")
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for category in CATEGORIES:
        src_cat = ao_agents_dir / category
        if not src_cat.exists():
            print(f"跳过不存在的分类: {category}")
            continue

        dst_cat = target_dir / category
        dst_cat.mkdir(exist_ok=True)

        # 递归扫描，保留子目录结构（如 game-development/unity/xxx.md）
        for md_file in src_cat.rglob("*.md"):
            if md_file.name.startswith("_") or md_file.name in SKIP_FILES:
                continue

            # 计算相对路径以保留子目录结构
            rel_path = md_file.relative_to(src_cat)
            dst_file = dst_cat / rel_path
            dst_file.parent.mkdir(exist_ok=True)
            shutil.copy2(md_file, dst_file)
            count += 1

        role_count = len(list(dst_cat.rglob("*.md")))
        print(f"已复制 {category}: {role_count} 个角色")

    return count


def main():
    # 默认中文版 AO 路径
    default_ao_path = Path(r"D:\AIProjects\agency-agents-zh")

    if len(sys.argv) > 1:
        ao_path = Path(sys.argv[1])
    else:
        ao_path = default_ao_path

    # 目标路径
    script_dir = Path(__file__).resolve().parent
    target_dir = script_dir.parent / "package" / "yuxi" / "agents" / "roles" / "roles"

    print(f"AO 路径: {ao_path}")
    print(f"目标路径: {target_dir}")
    print()

    count = import_roles(ao_path, target_dir)

    print()
    print(f"完成! 共导入 {count} 个角色模板")


if __name__ == "__main__":
    main()
