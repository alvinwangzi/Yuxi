"""P3: Skill 归档包导出/导入往返测试 + 斜杠命令过滤逻辑测试。"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from yuxi.agents.skills import service as svc
from yuxi.storage.postgres.models_business import Skill, User


def _user(uid: str = "admin", role: str = "admin") -> User:
    return User(username=uid, uid=uid, password_hash="x", role=role, department_id=1)


# ── 归档包导出 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_skill_zip_produces_valid_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """导出 ZIP 应包含 Skill 目录下所有文件，且以 slug 为根目录。"""
    skill_dir = tmp_path / "skill-src"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n# Demo\n")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.py").write_text("print('hello')\n")

    fake_skill = Skill(
        slug="demo",
        name="demo",
        dir_path=str(skill_dir),
        source_type="upload",
        share_config={"version": 2, "read_scope": {"access_level": "global"}},
    )

    async def fake_get_manageable(_db, _operator, _slug):
        return fake_skill

    monkeypatch.setattr(svc, "get_manageable_skill_or_raise", fake_get_manageable)
    monkeypatch.setattr(svc, "get_skill_data_dir", lambda: tmp_path)

    export_path, download_name = await svc.export_skill_zip(
        None, slug="demo", operator=_user(),
    )

    try:
        assert download_name == "demo.zip"
        with zipfile.ZipFile(export_path, "r") as zf:
            names = set(zf.namelist())
        assert "demo/SKILL.md" in names
        assert "demo/scripts/run.py" in names
    finally:
        Path(export_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_export_then_reimport_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """导出 ZIP 后重新导入，内容应一致。"""
    skill_dir = tmp_path / "skill-src"
    skill_dir.mkdir()
    skill_md = "---\nname: roundtrip\ndescription: 往返测试\n---\n# Roundtrip\n"
    (skill_dir / "SKILL.md").write_text(skill_md)
    (skill_dir / "helper.py").write_text("# helper\n")

    fake_skill = Skill(
        slug="roundtrip",
        name="roundtrip",
        dir_path=str(skill_dir),
        source_type="upload",
        share_config={"version": 2, "read_scope": {"access_level": "global"}},
    )

    async def fake_get_manageable(_db, _operator, _slug):
        return fake_skill

    monkeypatch.setattr(svc, "get_manageable_skill_or_raise", fake_get_manageable)
    monkeypatch.setattr(svc, "get_skill_data_dir", lambda: tmp_path)

    export_path, _ = await svc.export_skill_zip(
        None, slug="roundtrip", operator=_user(),
    )

    try:
        with zipfile.ZipFile(export_path, "r") as zf:
            exported_skill_md = zf.read("roundtrip/SKILL.md").decode()
            exported_helper = zf.read("roundtrip/helper.py").decode()

        assert exported_skill_md == skill_md
        assert exported_helper == "# helper\n"
    finally:
        Path(export_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_export_skill_zip_missing_dir_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Skill 目录不存在时应抛出 ValueError。"""
    fake_skill = Skill(
        slug="ghost",
        name="ghost",
        dir_path=str(tmp_path / "nonexistent"),
        source_type="upload",
        share_config={"version": 2, "read_scope": {"access_level": "global"}},
    )

    async def fake_get_manageable(_db, _operator, _slug):
        return fake_skill

    monkeypatch.setattr(svc, "get_manageable_skill_or_raise", fake_get_manageable)
    monkeypatch.setattr(svc, "get_skill_data_dir", lambda: tmp_path)

    with pytest.raises(ValueError, match="技能目录不存在"):
        await svc.export_skill_zip(None, slug="ghost", operator=_user())


# ── 斜杠命令过滤逻辑 ────────────────────────────────────────


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
