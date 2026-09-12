"""角色模板库 — 从文件系统加载预定义角色 prompt。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from yuxi.utils.logging_config import logger

# 角色文件根目录
ROLES_DIR = Path(__file__).parent / "roles"

# 分类映射（按企业逻辑排序：经营决策→业务增长→支撑职能→交付执行→专业领域）
CATEGORY_MAP = {
    "company": "公司经营部",
    "sales": "销售部",
    "marketing": "营销部",
    "paid-media": "付费媒体部",
    "hr": "人力资源部",
    "finance": "金融部",
    "legal": "法务部",
    "supply-chain": "供应链部",
    "product": "产品部",
    "project-management": "项目管理部",
    "engineering": "工程部",
    "design": "设计部",
    "testing": "测试部",
    "support": "支持部",
    "security": "安全部",
    "specialized": "专项部",
    "gis": "GIS 空间信息部",
    "spatial-computing": "空间计算部",
    "game-development": "游戏开发部",
    "academic": "学术部",
}

# 非角色模板文件
SKIP_FILES = {"README.md", "NOTICE.md", "EXECUTIVE-BRIEF.md", "QUICKSTART.md", "nexus-strategy.md"}

# 角色列表内存缓存（角色文件是静态资源，仅部署时变化）
_roles_cache: list[dict[str, Any]] | None = None


def _load_roles_from_disk() -> list[dict[str, Any]]:
    """从磁盘扫描并解析所有角色文件。"""
    roles = []

    if not ROLES_DIR.exists():
        logger.warning(f"角色目录不存在: {ROLES_DIR}")
        return roles

    for cat_name in CATEGORY_MAP:
        cat_dir = ROLES_DIR / cat_name
        if not cat_dir.is_dir():
            continue

        for role_file in sorted(cat_dir.rglob("*.md")):
            if role_file.name.startswith("_") or role_file.name in SKIP_FILES:
                continue
            try:
                role = _parse_role_file(role_file, cat_name)
                if role:
                    roles.append(role)
            except Exception as exc:
                logger.warning(f"解析角色文件失败 {role_file}: {exc}")

    return roles


def list_roles(category: str | None = None) -> list[dict[str, Any]]:
    """列出所有可用角色（带内存缓存）。

    Args:
        category: 可选分类过滤

    Returns:
        角色元数据列表
    """
    global _roles_cache
    if _roles_cache is None:
        _roles_cache = _load_roles_from_disk()

    if category:
        return [r for r in _roles_cache if r["category"] == category]
    return list(_roles_cache)


def invalidate_roles_cache() -> None:
    """清除角色缓存（用于开发模式或角色文件更新后）。"""
    global _roles_cache
    _roles_cache = None


def get_role(category: str, role_id: str) -> dict[str, Any] | None:
    """获取指定角色详情。

    Args:
        category: 分类目录名
        role_id: 角色文件相对路径（不含 .md），可含子目录如 "unity/unity-architect"

    Returns:
        角色详情或 None
    """
    role_file = ROLES_DIR / category / f"{role_id}.md"
    if not role_file.exists():
        return None

    try:
        return _parse_role_file(role_file, category, include_content=True)
    except Exception as exc:
        logger.warning(f"解析角色文件失败 {role_file}: {exc}")
        return None


def get_role_prompt(category: str, role_id: str) -> str | None:
    """获取角色的 prompt 内容（用于导入为 Agent）。

    Args:
        category: 分类目录名
        role_id: 角色文件相对路径（不含 .md），可含子目录
    """
    role_file = ROLES_DIR / category / f"{role_id}.md"
    if not role_file.exists():
        return None

    try:
        content = role_file.read_text(encoding="utf-8")
        # 跳过 frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:].strip()
        return content
    except Exception as exc:
        logger.warning(f"读取角色 prompt 失败 {role_file}: {exc}")
        return None


def list_categories() -> list[dict[str, str]]:
    """列出所有角色分类（按 CATEGORY_MAP 顺序）。"""
    categories = []
    if not ROLES_DIR.exists():
        return categories

    for cat_name, cat_label in CATEGORY_MAP.items():
        cat_dir = ROLES_DIR / cat_name
        if cat_dir.is_dir():
            categories.append({
                "id": cat_name,
                "name": cat_label,
            })
    return categories


def _parse_role_file(
    file_path: Path,
    category: str,
    include_content: bool = False,
) -> dict[str, Any] | None:
    """解析角色 Markdown 文件。"""
    content = file_path.read_text(encoding="utf-8")

    # 解析 frontmatter
    metadata: dict[str, Any] = {}
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            frontmatter = content[3:end].strip()
            try:
                metadata = yaml.safe_load(frontmatter) or {}
            except yaml.YAMLError:
                pass

    role_id = file_path.relative_to(ROLES_DIR / category).with_suffix("").as_posix()
    name = metadata.get("name", role_id.replace("-", " ").replace("/", " - ").title())
    description = metadata.get("description", "")

    result = {
        "id": role_id,
        "category": category,
        "category_name": CATEGORY_MAP.get(category, category),
        "name": name,
        "description": description[:200] if description else "",
        "icon": metadata.get("emoji", "👤"),
        "color": metadata.get("color", "blue"),
    }

    if include_content:
        # 提取正文内容
        body = content
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                body = content[end + 3:].strip()
        result["content"] = body

    return result
