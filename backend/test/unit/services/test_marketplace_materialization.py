"""市场技能安装文件物化回归测试。"""

from __future__ import annotations

from pathlib import Path
import asyncio
import threading

import pytest

from yuxi.services.skills.personal import materialize_personal_skill_snapshot

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolate_user_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """将用户数据目录指向临时目录，避免污染真实工作区。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))


SAMPLE_SNAPSHOT = {
    "skill_md": "---\nslug: demo\nname: Demo\ndescription: Test\n---\n# Test Skill\n",
    "scripts": {"helper.py": "# helper script\nprint('hello')\n"},
    "files": {"assets/icon.svg": "<svg></svg>"},
    "tool_dependencies": ["web-search"],
    "mcp_dependencies": [],
    "skill_dependencies": [],
}

UID = "test-user-001"
SLUG = "market-demo-test-abcdef"


def _skill_dir() -> Path:
    from yuxi.workspace.paths import user_workspace_dir

    return user_workspace_dir(UID) / "agents" / "skills" / SLUG


async def _materialize_skill_files(uid, slug, snapshot):
    """调用真实个人文件 Owner，使用本例已知目录作独立 oracle。"""
    await materialize_personal_skill_snapshot(uid, slug, snapshot)
    from yuxi.workspace.paths import user_workspace_dir

    return user_workspace_dir(uid) / "agents" / "skills" / slug


async def _refresh_skill_files(uid, slug, snapshot):
    """通过同一 Owner 执行更新。"""
    await materialize_personal_skill_snapshot(uid, slug, snapshot, replace_existing=True)
    from yuxi.workspace.paths import user_workspace_dir

    return user_workspace_dir(uid) / "agents" / "skills" / slug


class TestMaterializeSkillFiles:
    """_materialize_skill_files 物化测试。"""

    async def test_creates_skill_directory(self) -> None:
        skill_dir = await _materialize_skill_files(UID, SLUG, SAMPLE_SNAPSHOT)
        assert skill_dir.is_dir()
        assert str(skill_dir) == str(_skill_dir())

    async def test_writes_skill_md(self) -> None:
        skill_dir = await _materialize_skill_files(UID, SLUG, SAMPLE_SNAPSHOT)
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text(encoding="utf-8")
        assert "# Test Skill" in content

    async def test_writes_scripts(self) -> None:
        skill_dir = await _materialize_skill_files(UID, SLUG, SAMPLE_SNAPSHOT)
        helper = skill_dir / "scripts" / "helper.py"
        assert helper.exists()
        assert "print('hello')" in helper.read_text(encoding="utf-8")

    async def test_writes_asset_files(self) -> None:
        skill_dir = await _materialize_skill_files(UID, SLUG, SAMPLE_SNAPSHOT)
        icon = skill_dir / "assets" / "icon.svg"
        assert icon.exists()
        assert "<svg></svg>" in icon.read_text(encoding="utf-8")

    async def test_empty_snapshot_rejected(self) -> None:
        with pytest.raises(ValueError):
            await _materialize_skill_files(UID, SLUG, {"skill_md": ""})
        assert not _skill_dir().exists()


class TestRefreshSkillFiles:
    """_refresh_skill_files 版本更新测试。"""

    async def test_replaces_old_files(self) -> None:
        await _materialize_skill_files(UID, SLUG, SAMPLE_SNAPSHOT)
        assert (_skill_dir() / "scripts" / "helper.py").exists()

        new_snapshot = {
            "skill_md": "---\nslug: demo\nname: Demo\ndescription: Test\n---\n# Updated Skill\n",
            "scripts": {"new_helper.py": "# new script\n"},
            "files": {},
        }
        skill_dir = await _refresh_skill_files(UID, SLUG, new_snapshot)

        assert skill_dir.is_dir()
        assert (skill_dir / "SKILL.md").exists()
        assert "Updated Skill" in (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert (skill_dir / "scripts" / "new_helper.py").exists()
        # 旧文件应被清除
        assert not (skill_dir / "scripts" / "helper.py").exists()


@pytest.mark.parametrize("name", ["../escaped.txt", "/escaped.txt", "C:/escaped.txt", "..\\escaped.txt"])
async def test_snapshot_paths_cannot_escape_skill_directory(name):
    """快照文件名不能跨出所属技能目录。"""
    with pytest.raises(ValueError):
        await _materialize_skill_files(UID, SLUG, {"files": {name: "unsafe"}})


async def test_invalid_refresh_preserves_existing_files():
    """先拒绝非法新包，再保留旧文件；不能先删除旧版本。"""
    await _materialize_skill_files(UID, SLUG, SAMPLE_SNAPSHOT)
    original = (_skill_dir() / "SKILL.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        await _refresh_skill_files(UID, SLUG, {"scripts": {"../escaped.py": "unsafe"}})
    assert (_skill_dir() / "SKILL.md").read_text(encoding="utf-8") == original


async def test_invalid_slug_cannot_select_another_directory():
    """路径段来源于数据库也必须在文件 Owner 处验证。"""
    with pytest.raises(ValueError):
        await _materialize_skill_files(UID, "../different", SAMPLE_SNAPSHOT)


async def test_installed_frontmatter_matches_personal_directory():
    """个人扫描消费最终目录身份和脚本。"""
    from yuxi.services.skills.personal import list_personal_skills

    await _materialize_skill_files(UID, SLUG, SAMPLE_SNAPSHOT)
    result = await list_personal_skills(uid=UID)
    assert any(item.slug == SLUG for item in result)


async def test_cancelled_publication_restores_old_files(monkeypatch):
    """取消不能让仍在运行的线程留下未提交文件。"""
    from yuxi.services.skills import personal

    await _materialize_skill_files(UID, SLUG, SAMPLE_SNAPSHOT)
    original = (_skill_dir() / "SKILL.md").read_text(encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    publish = personal._replace_market_snapshot

    def blocked_publish(*args):
        """受控阻塞交换，复现协程取消早于线程结束。"""
        started.set()
        assert release.wait(timeout=5)
        return publish(*args)

    monkeypatch.setattr(personal, "_replace_market_snapshot", blocked_publish)
    task = asyncio.create_task(_refresh_skill_files(UID, SLUG, SAMPLE_SNAPSHOT))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (_skill_dir() / "SKILL.md").read_text(encoding="utf-8") == original
    assert not list(_skill_dir().parent.glob(".market-*"))
