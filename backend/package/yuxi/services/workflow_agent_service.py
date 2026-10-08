"""工作流通过普通 FIFO 请求运行真实 Agent，并在等待时释放 worker。"""

from yuxi.repositories.connector_repository import ConnectorRepository
from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.services.agent_request_service import AgentRequestInput, RunOrigin, submit_agent_request
from yuxi.services.input_message_service import build_chat_input_message
from yuxi.utils.logging_config import logger
from yuxi.workflows.context import WorkflowExecutionContext, WorkflowStepWaiting


async def execute_workflow_agent_step(agent_slug, prompt, execution, *, session_factory=None):
    """先提交步骤关联，再提交真实 Agent 请求；恢复读取精确绑定的输出。"""
    if not isinstance(execution, WorkflowExecutionContext) or not execution.step_execution_id:
        raise ValueError("execution_context_required")
    if session_factory is None:
        from yuxi.storage.postgres.manager import pg_manager

        session_factory = pg_manager.get_async_session_context
    async with session_factory() as db:
        repo = WorkflowRepository(db)
        step = await repo.bind_agent_step(execution, agent_slug)
        request_id, thread_id = step.agent_request_id, step.agent_thread_id
        state = await repo.bound_agent_state(execution.workflow_run_id, execution.step_id, execution.actor_uid)
    if state["status"] == "missing":
        async with session_factory() as db:
            repo = WorkflowRepository(db)
            await repo.bind_agent_step(execution, agent_slug)
            actor = await ConnectorRepository(db).get_active_actor(execution.actor_uid)
            if actor is None:
                raise PermissionError("workflow_actor_unavailable")
            await submit_agent_request(
                db=db,
                current_user=actor,
                request_input=AgentRequestInput(
                    agent_slug=agent_slug,
                    thread_id=thread_id,
                    request_id=request_id,
                    input_message=build_chat_input_message(prompt),
                    create_conversation=True,
                    queue_policy="enqueue",
                    conversation_title="工作流 Agent 步骤",
                    origin=RunOrigin(
                        source="workflow",
                        channel="internal",
                        metadata={
                            "workflow_id": execution.workflow_id,
                            "workflow_run_id": execution.workflow_run_id,
                            "step_id": execution.step_id,
                            "step_execution_id": execution.step_execution_id,
                        },
                    ),
                ),
            )
        async with session_factory() as db:
            repo = WorkflowRepository(db)
            parent = await repo.get_run(execution.workflow_run_id)
            cancelled = parent.status == "cancelled"
            state = await repo.bound_agent_state(execution.workflow_run_id, execution.step_id, execution.actor_uid)
        if cancelled:
            from yuxi.services.workflow_service import cancel_workflow_execution

            await cancel_workflow_execution(
                execution.workflow_run_id, actor_uid=execution.actor_uid, session_factory=session_factory
            )
            raise PermissionError("workflow_cancelled")
    if state["status"] == "completed":
        return state["output"]
    if state["status"] == "failed":
        raise RuntimeError(state["error"])
    raise WorkflowStepWaiting(
        "waiting_agent",
        {
            "agent_request_id": request_id,
            "agent_thread_id": thread_id,
        },
    )


async def resume_workflow_agent_steps(run_id, *, session_factory=None):
    """提交子恢复意图后调用正式 resume，失败保留原意图供补投递。"""
    from yuxi.services.agent_run_service import create_resume_run_view

    if session_factory is None:
        from yuxi.storage.postgres.manager import pg_manager

        session_factory = pg_manager.get_async_session_context
    async with session_factory() as db:
        intents = await WorkflowRepository(db).prepare_agent_resumes(run_id)
    dispatched = 0
    for intent in intents:
        try:
            async with session_factory() as db:
                parent = await WorkflowRepository(db).get_run(run_id, for_update=True)
                if parent.status not in ("waiting_agent", "waiting_approval"):
                    continue
                await create_resume_run_view(
                    db=db,
                    current_uid=intent["actor_uid"],
                    agent_slug=intent["agent_slug"],
                    thread_id=intent["thread_id"],
                    meta={"request_id": intent["request_id"]},
                    created_by_run_id=intent["parent_run_id"],
                    source="workflow",
                    channel="internal",
                    resume={"invocation_ids": intent["invocation_ids"]},
                )
            async with session_factory() as db:
                repo = WorkflowRepository(db)
                parent = await repo.get_run(run_id, for_update=True)
                await repo.bound_agent_state(run_id, intent["step_id"], intent["actor_uid"])
                await repo.mark_agent_resume_dispatched(run_id, intent["step_id"], intent["request_id"])
                cancelled = parent.status == "cancelled"
            if cancelled:
                from yuxi.services.workflow_service import cancel_workflow_execution

                await cancel_workflow_execution(run_id, actor_uid=intent["actor_uid"], session_factory=session_factory)
            else:
                dispatched += 1
        except Exception as exc:
            logger.warning("工作流子 Agent 恢复失败: run_id=%s, type=%s", run_id, type(exc).__name__)
    return dispatched
