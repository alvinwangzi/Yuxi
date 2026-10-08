"""工作流 Agent 桥接从真实 Request/Run/Message 读取绑定结果。"""

import pytest
from yuxi.repositories.connector_repository import ConnectorRepository
from test.integration.services.test_workflow_connector_pause import (
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    ensure_live_api_schema as ensure_live_api_schema,
    fernet_key as fernet_key,
    service_scope as service_scope,
    vault as vault,
    vault_configuration as vault_configuration,
)
from yuxi.storage.postgres.models_business import (
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
    AgentRunRequest,
    AgentRun,
    Message,
    Conversation,
    Project,
)
from yuxi.workflows.context import WorkflowExecutionContext, WorkflowStepWaiting

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_cancel_between_binding_and_submit_never_creates_orphan_child(service_scope, monkeypatch):
    """绑定已提交但父已取消时，新提交事务必须拒绝子请求。"""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from yuxi.services import workflow_agent_service
    from yuxi.repositories.workflow_repository import WorkflowRepository
    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        workflow = Workflow(slug="cancel-submit", name="cancel", definition={"steps": []}, created_by="actor")
        db.add(workflow)
        await db.flush()
        run = WorkflowRun(workflow_id=workflow.id, status="running", created_by="actor", owner_attempt="lease")
        db.add(run)
        await db.flush()
        db.add(WorkflowStepRun(workflow_run_id=run.id, step_id="agent", step_type="llm", status="running", step_execution_id="activation"))
        execution = WorkflowExecutionContext("actor", workflow.id, run.id, "worker", "lease").for_step("agent", "activation")
    entries = 0

    @asynccontextmanager
    async def cancel_after_bind():
        """精确恢复绑定和子提交之间的取消窗口。"""
        nonlocal entries
        entries += 1
        if entries == 2:
            async with manager.get_async_session_context() as db:
                await WorkflowRepository(db).cancel_for_actor(run.id, "actor")
        async with manager.get_async_session_context() as db:
            yield db

    submit = AsyncMock()
    monkeypatch.setattr(workflow_agent_service, "submit_agent_request", submit)
    with pytest.raises(PermissionError, match="workflow_owner_lost"):
        await workflow_agent_service.execute_workflow_agent_step("main", "synthetic", execution, session_factory=cancel_after_bind)
    submit.assert_not_called()
    async with manager.get_async_session_context() as db:
        from sqlalchemy import text
        assert await db.scalar(text("SELECT count(*) FROM agent_run_requests")) == 0


async def test_agent_bridge_waits_without_holding_worker_and_reads_only_bound_output(service_scope):
    """队列请求不会被当成结果；完成只读取绑定 Run 的输出消息。"""
    from yuxi.services.workflow_agent_service import execute_workflow_agent_step
    from yuxi.repositories.workflow_repository import WorkflowRepository

    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        workflow = Workflow(slug="agent-bridge", name="agent bridge", definition={"steps": []}, created_by="actor")
        db.add(workflow)
        await db.flush()
        run = WorkflowRun(workflow_id=workflow.id, status="running", created_by="actor", owner_attempt="lease")
        db.add(run)
        await db.flush()
        run_id, workflow_id = run.id, workflow.id
        project = Project(
            id="bridge-project",
            uid="actor",
            selection_status="implicit",
            directory_mode="managed",
            workdir_path="projects/bridge-project",
        )
        db.add(project)
        await db.flush()
        conversation = Conversation(thread_id="bridge-thread", uid="actor", agent_id="main", project_id=project.id)
        db.add(conversation)
        await db.flush()
        conversation_id = conversation.id
        message = Message(conversation_id=conversation_id, role="user", content="input")
        db.add(message)
        await db.flush()
        request = AgentRunRequest(
            request_id="bridge-request",
            uid="actor",
            agent_slug="main",
            conversation_thread_id="bridge-thread",
            input_message_id=message.id,
            source="workflow",
            channel="internal",
            origin_metadata={
                "workflow_run_id": run_id,
                "step_id": "agent",
                "step_execution_id": "activation",
            },
        )
        db.add(request)
        db.add(
            WorkflowStepRun(
                workflow_run_id=run_id,
                step_id="agent",
                step_type="llm",
                status="running",
                step_execution_id="activation",
                agent_request_id=request.request_id,
                agent_thread_id="bridge-thread",
            )
        )
    execution = WorkflowExecutionContext("actor", workflow_id, run_id, "worker", "lease").for_step(
        "agent", "activation"
    )
    with pytest.raises(WorkflowStepWaiting) as wait:
        await execute_workflow_agent_step("main", "input", execution, session_factory=manager.get_async_session_context)
    assert wait.value.status == "waiting_agent"
    assert wait.value.binding["agent_request_id"] == "bridge-request"
    async with manager.get_async_session_context() as db:
        run = await db.get(WorkflowRun, run_id)
        run.status = "waiting_agent"
        run.resume_state = {"pending": {"agent": {"status": "waiting_agent", **wait.value.binding}}}
        assert not await WorkflowRepository(db).queue_resume_if_ready(run_id)
        child = AgentRun(
            id="bridge-child",
            request_id="bridge-request",
            uid="actor",
            agent_slug="main",
            conversation_thread_id="bridge-thread",
            runtime_scope_id="bridge-thread",
            status="completed",
            conversation_id=conversation_id,
            source="workflow",
            channel="internal",
        )
        db.add(child)
        await db.flush()
        output = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="bound result",
            run_id=child.id,
            request_id="bridge-request",
        )
        neighbor = Message(conversation_id=conversation_id, role="assistant", content="neighbor result")
        db.add_all([output, neighbor])
        await db.flush()
        child.output_message_id = output.id
        request = await db.get(AgentRunRequest, request.id)
        request.status = "dispatched"
        request.dispatched_run_id = child.id
    async with manager.get_async_session_context() as db:
        assert await WorkflowRepository(db).queue_resume_if_ready(run_id)
        run = await WorkflowRepository(db).claim_run(run_id, 1, "worker", "new-lease")
        assert run
    resumed = WorkflowExecutionContext("actor", workflow_id, run_id, "worker", "new-lease").for_step(
        "agent", "activation"
    )
    assert (
        await execute_workflow_agent_step("main", "input", resumed, session_factory=manager.get_async_session_context)
        == "bound result"
    )
    async with manager.get_async_session_context() as db:
        child = await db.get(AgentRun, "bridge-child")
        child.output_message_id = neighbor.id
    with pytest.raises(ValueError, match="agent_output_binding_invalid"):
        await execute_workflow_agent_step("main", "input", resumed, session_factory=manager.get_async_session_context)


async def test_llm_agent_mode_requires_trusted_workflow_context():
    """业务变量中的 actor/thread 不能开启模型或 Agent 执行。"""
    from yuxi.workflows.executors.llm_executor import LLMStepExecutor

    with pytest.raises(ValueError, match="execution_context"):
        await LLMStepExecutor().execute(
            {"id": "agent", "agent_slug": "main", "prompt": "hi"}, {"__actor_uid__": "forged"}
        )


async def test_agent_resume_uses_original_logical_identity_but_rechecks_current_run(service_scope):
    """恢复不生成新的逻辑调用，伪造请求或取消后的 Run 均不能 dispatch。"""
    from yuxi.services.connectors.service import ConnectorAuthorizationError
    from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository

    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        db.add(
            AgentRun(
                id="origin-run",
                request_id="original-request",
                uid="actor",
                agent_slug="main",
                conversation_thread_id="origin-thread",
                runtime_scope_id="origin-thread",
                status="interrupted",
            )
        )
        db.add(
            AgentRun(
                id="resume-run",
                request_id="resume-request",
                uid="actor",
                agent_slug="main",
                conversation_thread_id="origin-thread",
                runtime_scope_id="origin-thread",
                status="running",
                run_type="resume",
                created_by_run_id="origin-run",
            )
        )
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        bound_connector_revision = connector.revision
    execution = await service.resolve_agent_execution(
        actor_uid="actor",
        current_run_id="resume-run",
        request_id="resume-request",
        tool_call_id="call",
        connector_revision=bound_connector_revision,
        operation_revision=1,
    )
    assert execution.logical_call_key == "agent:original-request:call"
    assert execution.agent_run_id == "origin-run" and execution.current_agent_run_id == "resume-run"
    with pytest.raises(ConnectorAuthorizationError):
        await service.resolve_agent_execution(
            actor_uid="actor",
            current_run_id="resume-run",
            request_id="forged-request",
            tool_call_id="call",
            connector_revision=1,
            operation_revision=1,
        )
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution)
    async with manager.get_async_session_context() as db:
        (await db.get(AgentRun, "resume-run")).status = "cancelled"
    with pytest.raises(ConnectorAuthorizationError):
        await service.execute_invocation(prepared["invocation_id"], execution=execution)
    async with manager.get_async_session_context() as db:
        invocation = await ConnectorExecutionRepository(db).get_invocation(prepared["invocation_id"])
        assert invocation.status == "prepared" and invocation.attempts == []
