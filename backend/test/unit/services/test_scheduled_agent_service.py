from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from yuxi.services import scheduled_agent_service as service
from yuxi.services.scheduled_agent_service import next_run_at, validate_schedule


def test_next_run_at_uses_timezone_and_returns_utc_naive_datetime():
    result = next_run_at("0 9 * * *", "Asia/Shanghai", datetime(2026, 8, 26, 0, 0))

    assert result == datetime(2026, 8, 26, 1, 0)
    assert result.tzinfo is None


@pytest.mark.parametrize(
    ("expression", "timezone"),
    [("every day", "Asia/Shanghai"), ("0 9 * * * *", "Asia/Shanghai"), ("0 9 * * *", "Mars/Olympus")],
)
def test_validate_schedule_rejects_invalid_expression_or_timezone(expression, timezone):
    with pytest.raises(HTTPException) as exc_info:
        validate_schedule(expression, timezone)

    assert exc_info.value.status_code == 422


def test_validate_schedule_accepts_five_field_cron_and_iana_timezone():
    assert validate_schedule("*/15 * * * *", "UTC") == ("*/15 * * * *", "UTC")


def test_validate_schedule_rejects_expression_without_future_occurrence():
    with pytest.raises(HTTPException) as exc_info:
        validate_schedule("0 0 31 2 *", "UTC")

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_validate_project_rejects_project_owned_by_another_user(monkeypatch):
    class ProjectRepository:
        def __init__(self, db):
            del db

        async def lock_active_for_user(self, project_id, uid):
            assert (project_id, uid) == ("project-1", "user-2")
            return None

    monkeypatch.setattr(service, "ProjectRepository", ProjectRepository)

    with pytest.raises(HTTPException) as exc_info:
        await service._validate_project("project-1", SimpleNamespace(uid="user-2"), object())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_validate_agent_rejects_agent_outside_user_visibility(monkeypatch):
    class AgentRepository:
        def __init__(self, db):
            del db

        async def get_visible_by_slug(self, *, slug, user, kind):
            assert (slug, user.uid, kind) == ("private-agent", "user-2", "main")
            return None

    monkeypatch.setattr(service, "AgentRepository", AgentRepository)

    with pytest.raises(HTTPException) as exc_info:
        await service._validate_agent("private-agent", SimpleNamespace(uid="user-2"), object())

    assert exc_info.value.status_code == 404


def test_scheduled_run_model_owns_execution_configuration_snapshot():
    from yuxi.storage.postgres.models_business import ScheduledAgentRun

    assert {"project_id", "agent_slug", "conversation_title", "prompt", "tool_approval_mode", "model_spec"}.issubset(
        ScheduledAgentRun.__table__.c.keys()
    )


def test_scheduled_run_model_uses_unique_thread_per_execution_and_preserves_history():
    from yuxi.storage.postgres.models_business import ScheduledAgentJob, ScheduledAgentRun

    project_fk = next(
        constraint
        for constraint in ScheduledAgentJob.__table__.foreign_key_constraints
        if constraint.name == "fk_scheduled_agent_jobs_project_uid"
    )
    assert project_fk.ondelete == "CASCADE"
    foreign_key = next(iter(ScheduledAgentRun.__table__.c.job_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in ScheduledAgentRun.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("thread_id",) in unique_columns


def test_execution_projection_reads_terminal_status_from_agent_run():
    scheduled_run = SimpleNamespace(
        status="submitted",
        target_type="agent",
        to_dict=lambda: {
            "status": "submitted",
            "run_id": None,
            "error_message": None,
            "completed_at": None,
        },
    )
    request = SimpleNamespace(status="dispatched", dispatched_run_id="run-1", error_message=None)
    run = SimpleNamespace(
        status="failed",
        error_message="模型不可用",
        finished_at=datetime(2026, 8, 27, 10, 0),
        started_at=datetime(2026, 8, 27, 9, 55),
    )

    result = service._execution_to_dict(scheduled_run, request, run)

    assert result == {
        "status": "failed",
        "run_id": "run-1",
        "error_message": "模型不可用",
        "completed_at": "2026-08-27T10:00:00Z",
        "started_at": "2026-08-27T09:55:00Z",
        "conversation_available": True,
    }


def test_execution_projection_does_not_offer_conversation_before_request_exists():
    scheduled_run = SimpleNamespace(
        status="failed",
        target_type="agent",
        to_dict=lambda: {"status": "failed", "thread_id": "reserved-thread"},
    )

    result = service._execution_to_dict(scheduled_run, None, None)

    assert result["conversation_available"] is False


@pytest.mark.asyncio
async def test_enabling_paused_job_schedules_from_current_time(monkeypatch):
    now = datetime(2026, 8, 27, 10, 0)
    next_time = datetime(2026, 8, 28, 1, 0)
    job = SimpleNamespace(
        cron_expression="0 9 * * *",
        timezone="Asia/Shanghai",
        enabled=False,
        next_run_at=datetime(2026, 8, 20, 1, 0),
        updated_at=None,
        to_dict=lambda: {"enabled": job.enabled, "next_run_at": job.next_run_at},
    )

    class Repository:
        async def get_job(self, job_id, uid, *, lock):
            assert (job_id, uid, lock) == ("job-1", "user-1", True)
            return job

    class Db:
        async def commit(self):
            return None

    monkeypatch.setattr(service, "ScheduledAgentRepository", lambda _db: Repository())
    monkeypatch.setattr(service, "utc_now_naive", lambda: now)
    monkeypatch.setattr(service, "next_run_at", lambda expression, timezone, after: next_time)

    result = await service.update_scheduled_job(
        job_id="job-1",
        user=SimpleNamespace(uid="user-1"),
        db=Db(),
        data={"enabled": True},
    )

    assert result == {"enabled": True, "next_run_at": next_time}


@pytest.mark.asyncio
async def test_run_now_rejects_request_id_reused_for_another_job(monkeypatch):
    job = SimpleNamespace(id="job-2")
    existing_run = SimpleNamespace(job_id="job-1")

    class Repository:
        async def get_job(self, job_id, uid, *, lock):
            assert (job_id, uid, lock) == ("job-2", "user-1", True)
            return job

        async def get_run(self, run_id):
            assert run_id == service.build_request_id("scheduled-run", "user-1:manual:manual-request-1")
            return existing_run

    monkeypatch.setattr(service, "ScheduledAgentRepository", lambda _db: Repository())

    with pytest.raises(HTTPException) as exc_info:
        await service.run_scheduled_job_now(
            job_id="job-2",
            request_id="manual-request-1",
            user=SimpleNamespace(uid="user-1"),
            db=object(),
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_recovery_continues_after_one_dispatch_fails(monkeypatch):
    records = [SimpleNamespace(id="run-failing"), SimpleNamespace(id="run-success")]
    dispatched = []

    class Repository:
        def __init__(self, db):
            del db

        async def list_dispatching_runs(self, *, before, limit):
            del before
            assert limit == 10
            return records

    @asynccontextmanager
    async def session_context():
        yield object()

    async def dispatch(*, scheduled_run_id):
        dispatched.append(scheduled_run_id)
        if scheduled_run_id == "run-failing":
            raise RuntimeError("持续失败")
        return {"status": "submitted"}

    monkeypatch.setattr(service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(service, "ScheduledAgentRepository", Repository)
    monkeypatch.setattr(service, "dispatch_scheduled_run", dispatch)

    assert await service.recover_scheduled_dispatches(limit=10) == 1
    assert dispatched == ["run-failing", "run-success"]


@pytest.mark.asyncio
async def test_due_job_claiming_continues_after_one_dispatch_fails(monkeypatch):
    runs = iter(
        [
            SimpleNamespace(id="run-failing", status="dispatching"),
            SimpleNamespace(id="run-success", status="dispatching"),
            None,
        ]
    )
    dispatched = []

    @asynccontextmanager
    async def session_context():
        yield object()

    async def claim(*, db, now):
        del db, now
        return next(runs)

    async def dispatch(*, scheduled_run_id):
        dispatched.append(scheduled_run_id)
        if scheduled_run_id == "run-failing":
            raise RuntimeError("持续失败")
        return {"status": "submitted"}

    monkeypatch.setattr(service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(service, "_claim_due_run", claim)
    monkeypatch.setattr(service, "dispatch_scheduled_run", dispatch)

    assert await service.claim_and_dispatch_due_jobs(limit=3) == 2
    assert dispatched == ["run-failing", "run-success"]


@pytest.mark.asyncio
async def test_claim_disables_invalid_schedule_and_continues_to_next_job(monkeypatch):
    invalid = SimpleNamespace(
        id="job-invalid",
        cron_expression="0 9 * * *",
        timezone="Mars/Olympus",
        next_run_at=datetime(2026, 8, 27, 1, 0),
        enabled=True,
        updated_at=None,
    )
    valid = SimpleNamespace(
        id="job-valid",
        cron_expression="0 9 * * *",
        timezone="UTC",
        next_run_at=datetime(2026, 8, 27, 9, 0),
        enabled=True,
        updated_at=None,
    )
    jobs = iter([invalid, valid])
    commits = 0

    class Repository:
        async def claim_due_job(self, *, now):
            assert now == datetime(2026, 8, 27, 10, 0)
            return next(jobs)

    class Db:
        async def commit(self):
            nonlocal commits
            commits += 1

    run = SimpleNamespace(id="run-valid")

    async def create_run_record(**kwargs):
        assert kwargs["job"] is valid
        return run

    monkeypatch.setattr(service, "ScheduledAgentRepository", lambda _db: Repository())
    monkeypatch.setattr(service, "_create_run_record", create_run_record)

    result = await service._claim_due_run(db=Db(), now=datetime(2026, 8, 27, 10, 0))

    assert result is run
    assert invalid.enabled is False
    assert valid.next_run_at == datetime(2026, 8, 28, 9, 0)
    assert commits == 2


def test_execution_to_dict_workflow_path_with_workflow_run():
    """工作流类型且有 workflow_run 时，从 workflow_run 投影状态。"""
    scheduled_run = SimpleNamespace(
        status="submitted",
        target_type="workflow",
        to_dict=lambda: {
            "status": "submitted",
            "run_id": None,
            "error_message": None,
            "completed_at": None,
        },
    )
    workflow_run = SimpleNamespace(
        status="completed",
        error_message=None,
        started_at=datetime(2026, 9, 17, 10, 0),
        completed_at=datetime(2026, 9, 17, 10, 5),
    )

    result = service._execution_to_dict(scheduled_run, None, None, workflow_run)

    assert result["status"] == "completed"
    assert result["error_message"] is None
    assert result["started_at"] == "2026-09-17T10:00:00Z"
    assert result["completed_at"] == "2026-09-17T10:05:00Z"
    assert result["conversation_available"] is False


def test_execution_to_dict_workflow_path_old_record_unknown():
    """工作流类型但无 workflow_run（旧记录）时，状态为 unknown。"""
    scheduled_run = SimpleNamespace(
        status="submitted",
        target_type="workflow",
        to_dict=lambda: {
            "status": "submitted",
            "run_id": None,
            "error_message": None,
            "completed_at": None,
        },
    )

    result = service._execution_to_dict(scheduled_run, None, None, None)

    assert result["status"] == "unknown"
    assert result["conversation_available"] is False


@pytest.mark.asyncio
async def test_has_active_run_workflow_branch():
    """工作流类型检查 WorkflowRun 状态判断是否有活动执行。"""
    from unittest.mock import AsyncMock, MagicMock
    from yuxi.repositories.scheduled_agent_repository import ScheduledAgentRepository

    db = MagicMock()
    repo = ScheduledAgentRepository(db)

    # Mock: 无 dispatching 记录
    db.scalar = AsyncMock(side_effect=[
        None,  # dispatching check
        None,  # agent check
        "wf-run-id",  # workflow check: 有活动工作流
    ])

    result = await repo.has_active_run("job-1")
    assert result is True


@pytest.mark.asyncio
async def test_list_job_runs_pagination_offset_beyond_total():
    """offset >= total 时返回空列表但保留正确 total。"""
    from unittest.mock import AsyncMock, MagicMock
    from yuxi.repositories.scheduled_agent_repository import ScheduledAgentRepository

    db = MagicMock()
    repo = ScheduledAgentRepository(db)

    # Mock: job 存在，total=5，但 offset=10 超出范围
    job = SimpleNamespace(id="job-1")
    # 第一次 scalar 返回 job，第二次返回 total count
    db.scalar = AsyncMock(side_effect=[job, 5])

    rows, total = await repo.list_runs_paginated(
        job_id="job-1", uid="user-1", limit=20, offset=10
    )

    assert rows == []
    assert total == 5


@pytest.mark.asyncio
async def test_list_job_runs_returns_none_for_nonexistent_job(monkeypatch):
    """任务不存在时 list_job_runs 返回 None。"""
    from unittest.mock import AsyncMock, MagicMock

    db = MagicMock()

    class Repository:
        async def list_runs_paginated(self, *, job_id, uid, limit, offset):
            return [], 0

        async def get_job(self, job_id, uid):
            return None

    monkeypatch.setattr(service, "ScheduledAgentRepository", lambda _db: Repository())

    result = await service.list_job_runs(
        job_id="nonexistent", user=SimpleNamespace(uid="user-1"), db=db, limit=20, offset=0
    )

    assert result is None
