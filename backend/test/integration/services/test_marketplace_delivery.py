"""真实事务与个人技能文件发布的一致性回归。"""

import pytest
import asyncio
from sqlalchemy import select

from test.integration.services.test_connector_service import (
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    ensure_live_api_schema as ensure_live_api_schema,
    fernet_key as fernet_key,
    vault as vault,
    vault_configuration as vault_configuration,
)
from test.integration.services import test_connector_service as connector_tests
from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.services.skills.personal import materialize_personal_skill_snapshot
from yuxi.storage.postgres.models_business import Department, User, Workflow
from yuxi.storage.postgres.models_business import Skill
from yuxi.marketplace.service import MarketplaceService
from yuxi.marketplace.repository import MarketplaceRepository
from yuxi.workspace.paths import user_workspace_dir

delivery_scope = connector_tests.service_scope

MARKDOWN = "---\nslug: market-test\nname: Test\ndescription: Test\n---\n"

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.mark.parametrize("existing", [False, True])
async def test_rollback_restores_previous_skill(delivery_scope, tmp_path, monkeypatch, existing):
    """真实数据库回滚删除新目录或恢复旧文件。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    _, manager = delivery_scope
    target = user_workspace_dir("actor") / "agents" / "skills" / "market-test"
    if existing:
        await materialize_personal_skill_snapshot("actor", "market-test", {"skill_md": MARKDOWN + "old"})
    with pytest.raises(RuntimeError, match="abort"):
        async with manager.get_async_session_context() as db:
            await materialize_personal_skill_snapshot(
                "actor", "market-test", {"skill_md": MARKDOWN + "new"}, replace_existing=existing, db=db
            )
            await db.execute(select(User))
            raise RuntimeError("abort")
    assert target.exists() == existing
    if existing:
        assert (target / "SKILL.md").read_text().endswith("old")
    assert not list(target.parent.glob(".market-*"))


async def test_commit_keeps_new_files(delivery_scope, tmp_path, monkeypatch):
    """真实事务提交保留完整文件并清除备份。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    _, manager = delivery_scope
    await materialize_personal_skill_snapshot("actor", "market-test", {"skill_md": MARKDOWN + "old"})
    async with manager.get_async_session_context() as db:
        await materialize_personal_skill_snapshot(
            "actor",
            "market-test",
            {"skill_md": MARKDOWN + "new", "files": {"templates/a.txt": "template"}},
            replace_existing=True,
            db=db,
        )
        await db.execute(select(User))
    target = user_workspace_dir("actor") / "agents" / "skills" / "market-test"
    assert (target / "SKILL.md").read_text().endswith("new")
    assert (target / "templates/a.txt").read_text() == "template"
    assert not list(target.parent.glob(".market-*"))


async def test_cancel_after_publication_restores_old_files(delivery_scope, tmp_path, monkeypatch):
    """发布后取消进入会话关闭分支，仍恢复旧文件。"""
    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    _, manager = delivery_scope
    await materialize_personal_skill_snapshot("actor", "market-test", {"skill_md": MARKDOWN + "old"})
    with pytest.raises(asyncio.CancelledError):
        async with manager.get_async_session_context() as db:
            await db.execute(select(User))
            await materialize_personal_skill_snapshot(
                "actor", "market-test", {"skill_md": MARKDOWN + "new"}, replace_existing=True, db=db
            )
            raise asyncio.CancelledError
    target = user_workspace_dir("actor") / "agents" / "skills" / "market-test"
    assert (target / "SKILL.md").read_text().endswith("old")
    assert not list(target.parent.glob(".market-*"))


async def test_personal_market_snapshot_can_be_installed(delivery_scope, tmp_path, monkeypatch):
    """逻辑 dir_path 的个人包经市场快照生成后可被另一用户消费。"""
    from yuxi.services.skills.personal import list_personal_skills

    monkeypatch.setenv("YUXI_USER_DATA_DIR", str(tmp_path))
    _, manager = delivery_scope
    await materialize_personal_skill_snapshot(
        "actor", "market-test", {"skill_md": MARKDOWN + "body", "scripts": {"run.sh": "echo test"}}
    )
    async with manager.get_async_session_context() as db:
        skill = Skill(
            slug="market-test",
            name="Test",
            description="Test",
            source_type="personal",
            source_scope="personal",
            owner_uid="actor",
            dir_path="market-test",
        )
        snapshot = await MarketplaceService(MarketplaceRepository(db), db)._build_content_snapshot(skill)
        await materialize_personal_skill_snapshot("reader", "market-copy", snapshot, db=db)
        await db.execute(select(User))
    result = await list_personal_skills(uid="reader")
    assert {item.slug for item in result} == {"market-copy"}
    target = user_workspace_dir("reader") / "agents" / "skills" / "market-copy"
    assert (target / "scripts/run.sh").read_text() == "echo test"


async def test_selectable_workflows_keep_department_visibility(delivery_scope):
    """部门成员可选本部门流程，不能选择其他部门或其他人的个人流程。"""
    _, manager = delivery_scope
    async with manager.get_async_session_context() as db:
        db.add(Department(id=42, name="delivery-test"))
        await db.flush()
        actor = await db.scalar(select(User).where(User.uid == "actor"))
        actor.role = "user"
        actor.department_id = 42
        for slug, scope, department, owner in [
            ("company", "company", None, "other"),
            ("department-own", "department", 42, "other"),
            ("department-other", "department", 43, "other"),
            ("personal-own", "personal", None, "actor"),
            ("personal-other", "personal", None, "other"),
            ("platform", "platform", None, "actor"),
        ]:
            db.add(
                Workflow(slug=slug, name=slug, definition={}, scope=scope, department_id=department, created_by=owner)
            )
        await db.flush()
        result = await WorkflowRepository(db).list_selectable_for_user(actor)
        assert {item.slug for item in result} == {"company", "department-own", "personal-own"}
