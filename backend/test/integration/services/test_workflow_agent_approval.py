"""真实 PG 与正式 Agent resume 创建路径的审批恢复和取消契约。"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, func
from test.integration.services.test_connector_service import (
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    ensure_live_api_schema as ensure_live_api_schema,
    fernet_key as fernet_key,
    service_scope as service_scope,
    vault as vault,
    vault_configuration as vault_configuration,
)
from yuxi.repositories.connector_repository import ConnectorRepository
from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.services.connectors.service import ConnectorApprovalRequired
from yuxi.storage.postgres.models_business import (
    Agent,
    AgentRun,
    AgentRunRequest,
    Conversation,
    Message,
    Project,
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
    ConnectorUsageLog,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.mark.parametrize("child_status", ["completed", "interrupted"])
async def test_unknown_child_write_blocks_parent_until_reconciliation(interrupted_agent, child_status):
    """模型完成或等待都不能覆盖同一激活的 unknown 写；只有独立核对释放。"""
    service, manager, parent_id, conversation_id, approval = interrupted_agent
    async with manager.get_async_session_context() as db:
        invocation = await db.get(ConnectorUsageLog, approval.invocation_id)
        invocation.status = "unknown"
        invocation.remote_outcome = "unknown"
        invocation.approval_policy = "preauthorized"
        child = await db.get(AgentRun, "approval-child")
        child.status = child_status
        output = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="unverified model claim",
            run_id=child.id,
            request_id=child.request_id,
        )
        db.add(output)
        await db.flush()
        child.output_message_id = output.id
        state = await WorkflowRepository(db).bound_agent_state(parent_id, "agent", "actor")
        assert state["status"] == "approval_wait" and state["invocation_ids"] == [approval.invocation_id]
        assert not await WorkflowRepository(db).queue_resume_if_ready(parent_id)
        assert (await db.get(WorkflowRun, parent_id)).status == "waiting_agent"


@pytest.mark.parametrize("rejected_step", ["aaa", "zzzzzzzz"])
@pytest.mark.parametrize("active_resume", [False, True])
async def test_rejected_parallel_sibling_fails_parent_and_durably_cancels_waiting_child(
    interrupted_agent, rejected_step, active_resume
):
    """拒绝不受 JSONB 排序遮蔽；失败父保留清理责任，手动 resume 不能复活子。"""
    from fastapi import HTTPException
    from yuxi.services.workflow_service import request_workflow_resume, recover_workflow_runs
    from yuxi.services.agent_run_service import create_resume_run_view

    service, manager, parent_id, _, approval = interrupted_agent
    child_id = "approval-child"
    if active_resume:
        from yuxi.services.workflow_agent_service import resume_workflow_agent_steps

        await service.decide_invocation(
            approval.invocation_id, "approve", actor="actor", expected_digest=approval.digest
        )
        queue = AsyncMock()
        with patch("yuxi.services.agent_run_service.get_arq_pool", new=AsyncMock(return_value=queue)):
            await resume_workflow_agent_steps(parent_id, session_factory=manager.get_async_session_context)
        async with manager.get_async_session_context() as db:
            child_id = (await db.scalar(select(AgentRun).where(AgentRun.run_type == "resume"))).id
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        db.add(
            ConnectorUsageLog(
                id="rejected-sibling",
                connector_id=connector.id,
                connector_slug=connector.slug,
                operation_slug="write",
                operation_type="write",
                actor_uid="actor",
                consumer_type="workflow",
                logical_call_key="rejected-sibling",
                connector_revision=connector.revision,
                operation_revision=1,
                status="rejected",
                workflow_run_id=parent_id,
            )
        )
        db.add(
            WorkflowStepRun(
                workflow_run_id=parent_id,
                step_id=rejected_step,
                step_type="connector",
                status="waiting_approval",
                pending_connector_invocation_id="rejected-sibling",
            )
        )
        parent = await db.get(WorkflowRun, parent_id)
        parent.resume_state = {
            "pending": {
                rejected_step: {"status": "waiting_approval", "invocation_id": "rejected-sibling"},
                "agent": {"status": "waiting_agent"},
            }
        }
    assert not await request_workflow_resume(parent_id, session_factory=manager.get_async_session_context)
    async with manager.get_async_session_context() as db:
        parent = await db.get(WorkflowRun, parent_id)
        assert parent.status == "failed" and parent.resume_state["cancel_propagation_pending"]
        assert parent_id in await WorkflowRepository(db).recovery_candidates()
        if active_resume:
            from yuxi.repositories.agent_run_repository import AgentRunRepository

            _, claimed = await AgentRunRepository(db).mark_running(
                child_id, worker_id="forbidden-worker", lease_seconds=120
            )
            assert not claimed, "failed 父的排队子任务不能开始执行"
        with pytest.raises(HTTPException) as blocked:
            await create_resume_run_view(
                db=db,
                current_uid="actor",
                agent_slug="bridge-agent",
                thread_id="approval-thread",
                meta={"request_id": "forbidden-resume"},
                created_by_run_id="approval-child",
                resume={"invocation_ids": []},
            )
        assert blocked.value.status_code == 409
    with patch(
        "yuxi.services.agent_run_service.publish_cancel_signals",
        new=AsyncMock(side_effect=ConnectionError("synthetic queue outage")),
    ):
        await recover_workflow_runs(session_factory=manager.get_async_session_context)
    async with manager.get_async_session_context() as db:
        parent = await db.get(WorkflowRun, parent_id)
        assert parent.status == "failed" and parent.resume_state["cancel_propagation_pending"]
        assert (await db.get(AgentRun, child_id)).status == "cancelled"
    with patch("yuxi.services.agent_run_service.publish_cancel_signals", new=AsyncMock()):
        await recover_workflow_runs(session_factory=manager.get_async_session_context)
    async with manager.get_async_session_context() as db:
        parent = await db.get(WorkflowRun, parent_id)
        assert parent.status == "failed" and not parent.resume_state["cancel_propagation_pending"]
        assert parent_id not in await WorkflowRepository(db).recovery_candidates()


@pytest.fixture
async def interrupted_agent(service_scope):
    """建立真实工作流、Agent 请求、模型快照和待批准调用。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        db.add(
            Agent(
                slug="bridge-agent",
                name="bridge agent",
                backend_id="ChatbotAgent",
                created_by="actor",
                share_config={"version": 2, "read_scope": {"access_level": "global"}, "manage_scope": None},
            )
        )
        db.add(
            Project(
                id="approval-project",
                uid="actor",
                selection_status="implicit",
                directory_mode="managed",
                workdir_path="projects/approval-project",
            )
        )
        workflow = Workflow(slug="agent-approval", name="agent approval", definition={"steps": []}, created_by="actor")
        db.add(workflow)
        await db.flush()
        parent = WorkflowRun(
            workflow_id=workflow.id,
            created_by="actor",
            status="waiting_agent",
            resume_state={"pending": {"agent": {"status": "waiting_agent"}}},
        )
        db.add(parent)
        conversation = Conversation(
            thread_id="approval-thread", uid="actor", agent_id="bridge-agent", project_id="approval-project"
        )
        db.add(conversation)
        await db.flush()
        metadata = {
            "workflow_id": workflow.id,
            "workflow_run_id": parent.id,
            "step_id": "agent",
            "step_execution_id": "activation",
        }
        child = AgentRun(
            id="approval-child",
            request_id="approval-request",
            uid="actor",
            agent_slug="bridge-agent",
            conversation_thread_id=conversation.thread_id,
            runtime_scope_id=conversation.thread_id,
            conversation_id=conversation.id,
            status="running",
            input_payload={"model_spec": "test/model"},
            source="workflow",
            channel="internal",
            origin_metadata=metadata,
        )
        db.add(child)
        await db.flush()
        message = Message(conversation_id=conversation.id, role="user", content="update CRM", run_id=child.id)
        db.add(message)
        await db.flush()
        child.input_message_id = message.id
        db.add(
            AgentRunRequest(
                request_id=child.request_id,
                uid="actor",
                agent_slug=child.agent_slug,
                conversation_thread_id=child.conversation_thread_id,
                input_message_id=message.id,
                dispatched_run_id=child.id,
                status="dispatched",
                source="workflow",
                channel="internal",
                origin_metadata=metadata,
            )
        )
        db.add(
            WorkflowStepRun(
                workflow_run_id=parent.id,
                step_id="agent",
                step_type="llm",
                status="waiting_agent",
                step_execution_id="activation",
                agent_request_id=child.request_id,
                agent_thread_id=child.conversation_thread_id,
                agent_run_id=child.id,
            )
        )
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/write",
            approval_policy="required",
        )
        parent_id, conversation_id = parent.id, conversation.id
        bound_connector_revision = connector.revision
    execution = await service.resolve_agent_execution(
        actor_uid="actor",
        current_run_id="approval-child",
        request_id="approval-request",
        tool_call_id="crm-call",
        connector_revision=bound_connector_revision,
        operation_revision=1,
    )
    with pytest.raises(ConnectorApprovalRequired) as approval:
        await service.prepare_invocation("service-test", "write", {}, execution=execution)
    async with manager.get_async_session_context() as db:
        child = await db.get(AgentRun, "approval-child")
        child.status = "interrupted"
        child.error_type = "connector_approval_required"
    return service, manager, parent_id, conversation_id, approval.value


async def test_approval_resumes_formal_agent_once_and_parent_waits_for_bound_final_output(interrupted_agent):
    """批准只恢复子 Agent，enqueue 失败后复用同一 resume 意图和 Run。"""
    from yuxi.services.workflow_agent_service import resume_workflow_agent_steps

    service, manager, parent_id, conversation_id, approval = interrupted_agent
    assert await resume_workflow_agent_steps(parent_id, session_factory=manager.get_async_session_context) == 0
    async with manager.get_async_session_context() as db:
        parent = await db.get(WorkflowRun, parent_id)
        assert parent.status == "waiting_approval"
        assert parent.resume_state["pending"]["agent"]["invocation_ids"] == [approval.invocation_id]
    await service.decide_invocation(approval.invocation_id, "approve", actor="actor", expected_digest=approval.digest)
    queued = []

    class Queue:
        fail = True

        async def enqueue_job(self, name, run_id, **_kwargs):
            async with manager.get_async_session_context() as db:
                run = await db.get(AgentRun, run_id)
                step = await WorkflowRepository(db).get_step_run(parent_id, "agent")
                intent = step.input_payload["agent_binding"]["resume_intent"]
                assert intent["request_id"] == run.request_id
                assert run.created_by_run_id == "approval-child" and run.run_type == "resume"
            if self.fail:
                raise ConnectionError("test queue failure")
            queued.append((name, run_id))
            return object()

    queue = Queue()
    with patch("yuxi.services.agent_run_service.get_arq_pool", new=AsyncMock(return_value=queue)):
        await resume_workflow_agent_steps(parent_id, session_factory=manager.get_async_session_context)
        queue.fail = False
        await resume_workflow_agent_steps(parent_id, session_factory=manager.get_async_session_context)
        await resume_workflow_agent_steps(parent_id, session_factory=manager.get_async_session_context)
    async with manager.get_async_session_context() as db:
        resumes = list((await db.scalars(select(AgentRun).where(AgentRun.run_type == "resume"))).all())
        assert len(resumes) == 1
        resumed = resumes[0]
        assert (await db.get(WorkflowRun, parent_id)).status == "waiting_agent"
        assert not await WorkflowRepository(db).queue_resume_if_ready(parent_id)
        resumed.status = "completed"
        output = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="final resumed output",
            run_id=resumed.id,
            request_id=resumed.request_id,
        )
        db.add(output)
        await db.flush()
        resumed.output_message_id = output.id
    assert queued == [("process_agent_run", resumed.id)]
    async with manager.get_async_session_context() as db:
        repo = WorkflowRepository(db)
        assert await repo.queue_resume_if_ready(parent_id)
        state = await repo.bound_agent_state(parent_id, "agent", "actor")
        assert state["output"] == "final resumed output"
        assert state["binding"]["origin_request_id"] == "approval-request"
        assert state["binding"]["active_request_id"] == resumed.request_id
        assert await db.scalar(select(func.count(AgentRunRequest.id))) == 1


async def test_parent_cancellation_reaches_active_resume_and_preserves_cancelled_parent(interrupted_agent):
    """当前 resume 单独取消，不能只取消早已 interrupted 的源 Run。"""
    from yuxi.services.workflow_agent_service import resume_workflow_agent_steps
    from yuxi.services.workflow_service import cancel_workflow_execution

    service, manager, parent_id, _, approval = interrupted_agent
    await service.decide_invocation(approval.invocation_id, "approve", actor="actor", expected_digest=approval.digest)
    queue = AsyncMock()
    with patch("yuxi.services.agent_run_service.get_arq_pool", new=AsyncMock(return_value=queue)):
        await resume_workflow_agent_steps(parent_id, session_factory=manager.get_async_session_context)
    with patch("yuxi.services.agent_run_service.publish_cancel_signals", new=AsyncMock()):
        await cancel_workflow_execution(parent_id, actor_uid="actor", session_factory=manager.get_async_session_context)
    async with manager.get_async_session_context() as db:
        resumed = await db.scalar(select(AgentRun).where(AgentRun.run_type == "resume"))
        assert resumed.status == "cancelled"
        parent = await db.get(WorkflowRun, parent_id)
        assert parent.status == "cancelled" and not parent.dispatch_pending
        assert not await WorkflowRepository(db).queue_resume_if_ready(parent_id)
