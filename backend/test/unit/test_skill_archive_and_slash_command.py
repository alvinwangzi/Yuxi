"""斜杠命令过滤逻辑测试（复现 SlashCommandMenu.vue 的模糊过滤）。

Skill 归档包导出（export_skill_zip）的行为已由 main 的加固实现拥有，
其安全性与路由权限覆盖见 test/unit/services/skills/test_skill_edit_service.py
与 test/unit/routers/test_skill_router.py，此处不再重复旧实现的往返测试。
"""
from __future__ import annotations


def _filter_skills(skills: list[dict], query: str) -> list[dict]:
    """复现 SlashCommandMenu.vue 的模糊过滤逻辑。"""
    q = query.lower().strip()
    if not q:
        return skills[:10]
    return [
        s for s in skills
        if q in (s.get("slug") or "").lower()
        or q in (s.get("name") or "").lower()
        or q in (s.get("description") or "").lower()
    ][:10]


_SKILL_LIST = [
    {"slug": "chart-renderer", "name": "图表渲染", "description": "将数据渲染为可视化图表"},
    {"slug": "data-analysis", "name": "数据分析", "description": "对数据进行统计分析"},
    {"slug": "web-search", "name": "网络搜索", "description": "搜索互联网获取信息"},
    {"slug": "markdown-report", "name": "Markdown 报告", "description": "生成结构化研究报告"},
    {"slug": "slide-deck", "name": "幻灯片", "description": "生成演示幻灯片"},
]


def test_slash_filter_empty_query_returns_all():
    result = _filter_skills(_SKILL_LIST, "")
    assert len(result) == 5


def test_slash_filter_by_slug():
    result = _filter_skills(_SKILL_LIST, "chart")
    assert len(result) == 1
    assert result[0]["slug"] == "chart-renderer"


def test_slash_filter_by_name():
    result = _filter_skills(_SKILL_LIST, "数据分析")
    assert len(result) == 1
    assert result[0]["slug"] == "data-analysis"


def test_slash_filter_by_description():
    result = _filter_skills(_SKILL_LIST, "互联网")
    assert len(result) == 1
    assert result[0]["slug"] == "web-search"


def test_slash_filter_no_match():
    result = _filter_skills(_SKILL_LIST, "zzz-not-found")
    assert result == []


def test_slash_filter_max_ten():
    big_list = _SKILL_LIST * 5  # 25 items
    result = _filter_skills(big_list, "")
    assert len(result) == 10


def test_slash_filter_case_insensitive():
    result = _filter_skills(_SKILL_LIST, "CHART")
    assert len(result) == 1
    assert result[0]["slug"] == "chart-renderer"
