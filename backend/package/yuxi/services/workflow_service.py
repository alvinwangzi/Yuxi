"""工作流执行服务 — 连接 API 层与 ARQ Worker。"""

from __future__ import annotations

from typing import Any
import copy

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.repositories.user_repository import UserRepository
from yuxi.storage.postgres.models_business import WorkflowRun
from yuxi.services.run_queue_service import append_run_stream_event, get_arq_pool
from yuxi.utils.logging_config import logger
from yuxi.workflows.dag import validate_definition


class WorkflowSubmissionConflict(ValueError):
    """同一工作流已有活跃运行，调用方应保留其等待结局。"""


async def create_workflow_execution(db, *, workflow_id, actor_uid, input_variables) -> dict:
    """锁定可见定义并冻结后持久创建；队列不可用仍保留 pending 意图。"""
    actor = await UserRepository(db).get_by_uid(actor_uid)
    repo = WorkflowRepository(db)
    workflow = await repo.get_visible_workflow(workflow_id, actor, for_update=True)
    if workflow is None:
        raise PermissionError("workflow_not_visible")
    if await repo.get_active_run(workflow_id):
        raise WorkflowSubmissionConflict("workflow_already_active")
    definition = copy.deepcopy(workflow.definition)
    if validate_definition(definition):
        raise ValueError("workflow_definition_invalid")
    if workflow.default_model_spec:
        for step in definition.get("steps", []):
            if step.get("type", "llm") == "llm" and not step.get("agent_slug") and not step.get("model_spec"):
                step["model_spec"] = copy.deepcopy(workflow.default_model_spec)
    run = await repo.create_run(
        WorkflowRun(
            workflow_id=workflow_id,
            status="pending",
            trigger="manual",
            created_by=actor_uid,
            input_variables=input_variables,
            definition_snapshot=definition,
            dispatch_pending=True,
        )
    )
    run_id = run.id
    try:
        result = await submit_workflow_run(db, run.id)
        queued = result["queued"]
    except Exception as exc:
        logger.warning("工作流保留待投递状态: run_id=%s, type=%s", run_id, type(exc).__name__)
        await db.rollback()
        run = await repo.get_run(run_id, for_update=True)
        queued = False
    return {**run.to_dict(), "queued": queued}


async def submit_workflow_run(db: AsyncSession, run_id: int) -> dict[str, Any]:
    """将工作流运行提交到 ARQ 队列。

    Returns:
        包含 run_id 和提交状态的字典。
    """
    repo = WorkflowRepository(db)
    run = await repo.get_run(run_id)
    if not run:
        raise ValueError(f"运行记录 {run_id} 不存在")

    if run.status != "pending":
        raise ValueError(f"运行记录 {run_id} 状态为 {run.status}，不可提交")

    if not run.definition_snapshot:
        import copy

        workflow = await repo.get_workflow(run.workflow_id)
        run.definition_snapshot = copy.deepcopy(workflow.definition)
    run.dispatch_pending = True
    generation = run.resume_generation
    await db.commit()

    try:
        # 通过 ARQ 队列提交任务
        queue = await get_arq_pool()
        await queue.enqueue_job(
            "process_workflow_run",
            run_id,
            generation,
            _job_id=f"workflow_run:{run_id}:{generation}",
        )
        run = await repo.get_run(run_id, for_update=True)
        if run.resume_generation == generation:
            run.dispatch_pending = False
        await db.commit()
        logger.info(f"已提交工作流运行任务: run_id={run_id}")

        # 发布 SSE 事件通知前端
        await append_run_stream_event(
            run_id=str(run_id),
            event_type="workflow_queued",
            payload={"run_id": run_id, "message": "工作流已加入执行队列"},
        )
        return {"run_id": run_id, "queued": True}
    except Exception as exc:
        logger.error("提交工作流运行任务失败: run_id=%s, type=%s", run_id, type(exc).__name__)
        raise


async def request_workflow_resume(run_id: int, *, session_factory=None) -> bool:
    """决定已提交后准备恢复，队列失败保留可补投递事实。"""
    if session_factory is None:
        from yuxi.storage.postgres.manager import pg_manager

        session_factory = pg_manager.get_async_session_context
    from yuxi.services.workflow_agent_service import resume_workflow_agent_steps

    await resume_workflow_agent_steps(run_id, session_factory=session_factory)
    async with session_factory() as db:
        ready = await WorkflowRepository(db).queue_resume_if_ready(run_id)
    if ready:
        async with session_factory() as db:
            await submit_workflow_run(db, run_id)
    return ready


async def recover_workflow_runs(*, session_factory=None) -> None:
    """重查持久等待和 pending，队列不可用时保留下一轮恢复事实。"""
    if session_factory is None:
        from yuxi.storage.postgres.manager import pg_manager

        session_factory = pg_manager.get_async_session_context
    async with session_factory() as db:
        candidates = await WorkflowRepository(db).recovery_candidates()
    for run_id in candidates:
        async with session_factory() as db:
            current = await WorkflowRepository(db).get_run(run_id)
            cancelled_actor = (
                current.created_by
                if current.status in ("cancelled", "failed")
                and (current.resume_state or {}).get("cancel_propagation_pending")
                else None
            )
        if cancelled_actor:
            try:
                await cancel_workflow_execution(run_id, actor_uid=cancelled_actor, session_factory=session_factory)
            except Exception as exc:
                logger.warning("工作流子取消重试失败: run_id=%s, type=%s", run_id, type(exc).__name__)
            continue
        from yuxi.services.workflow_agent_service import resume_workflow_agent_steps

        await resume_workflow_agent_steps(run_id, session_factory=session_factory)
        async with session_factory() as db:
            repo = WorkflowRepository(db)
            if await repo.fail_expired_owner(run_id):
                continue
            await repo.queue_resume_if_ready(run_id)
            run = await repo.get_run(run_id)
            dispatch = run is not None and run.status == "pending"
        if dispatch:
            try:
                async with session_factory() as db:
                    await submit_workflow_run(db, run_id)
            except Exception as exc:
                logger.warning("工作流补投递失败: run_id=%s, type=%s", run_id, type(exc).__name__)


async def cancel_workflow_execution(run_id: int, *, actor_uid: str, session_factory=None) -> None:
    """提交取消事实后传播到步骤绑定的真实 Agent 请求。"""
    if session_factory is None:
        from yuxi.storage.postgres.manager import pg_manager

        session_factory = pg_manager.get_async_session_context
    async with session_factory() as db:
        child_requests = await WorkflowRepository(db).cancel_for_actor(run_id, actor_uid)
    from yuxi.repositories.agent_run_request_repository import AgentRunRequestRepository
    from yuxi.services.agent_request_queue_service import cancel_queued_request
    from yuxi.services.agent_run_service import request_cancel_agent_run

    for child in child_requests:
        request_id = child["request_id"]
        async with session_factory() as db:
            if child["run_id"]:
                await request_cancel_agent_run(
                    run_id=child["run_id"], current_uid=actor_uid, db=db, cascade_children=True, close_interrupted=True
                )
                continue
            request = await AgentRunRequestRepository(db).get_by_request_id(request_id)
            if request is None or request.uid != actor_uid:
                continue
            if request.dispatched_run_id:
                await request_cancel_agent_run(
                    run_id=request.dispatched_run_id,
                    current_uid=actor_uid,
                    db=db,
                    cascade_children=True,
                    close_interrupted=True,
                )
            else:
                await cancel_queued_request(request_id=request_id, current_uid=actor_uid, db=db)

    async with session_factory() as db:
        await WorkflowRepository(db).mark_cancel_propagated(run_id)


async def publish_workflow_event(run_id: int, event: str, data: dict[str, Any]) -> None:
    """发布工作流运行事件到 SSE 流。"""
    try:
        await append_run_stream_event(
            run_id=str(run_id),
            event_type=event,
            payload=data,
        )
    except Exception as exc:
        logger.warning(f"发布工作流事件失败: {event} - {exc}")
