"""实际连接器服务与工作流引擎共同验证审批等待，不用返回字典冒充暂停。"""

import pytest
from unittest.mock import patch, AsyncMock

from test.integration.services.test_connector_service import (
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
    ensure_live_api_schema as ensure_live_api_schema,
    fernet_key as fernet_key,
    service_scope as service_scope,
    vault as vault,
    vault_configuration as vault_configuration,
    http_provider as http_provider,
)
from yuxi.repositories.connector_repository import ConnectorRepository
from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
from yuxi.services.connectors.factory import ConnectorServiceFactory, override_factory
from yuxi.services.connectors.factory import get_connector_service
from yuxi.workflows.context import WorkflowExecutionContext, WorkflowPaused
from yuxi.workflows.engine import WorkflowEngine
from yuxi.storage.postgres.models_business import Workflow, WorkflowRun, WorkflowStepRun
from yuxi.services import run_worker
from yuxi.storage.postgres import manager as manager_module

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def persisted_engine_context(manager, definition):
    """直接引擎测试也使用真实父运行与 dispatch 前步骤激活。"""
    async with manager.get_async_session_context() as db:
        workflow = Workflow(slug="engine-test", name="engine test", definition=definition, created_by="actor")
        db.add(workflow)
        await db.flush()
        run = WorkflowRun(workflow_id=workflow.id, created_by="actor", status="running", owner_attempt="lease")
        db.add(run)
        await db.flush()
        context = WorkflowExecutionContext("actor", workflow.id, run.id, "worker", "lease")
        for step in definition["steps"]:
            db.add(WorkflowStepRun(workflow_run_id=run.id, step_id=step["id"], step_type=step["type"]))

    async def checkpoint(state):
        from yuxi.repositories.workflow_repository import WorkflowRepository

        async with manager.get_async_session_context() as db:
            for step_id, activation in state["activations"].items():
                step = await WorkflowRepository(db).get_step_run(context.workflow_run_id, step_id)
                step.step_execution_id = activation

    return context, checkpoint


@pytest.mark.parametrize("mode", ["parallel", "loop"])
async def test_parallel_approvals_and_loop_activations_preserve_distinct_calls(service_scope, vault_configuration, http_provider, mode):
    """并行待项全部保存；循环新激活才生成新调用，恢复不重复旧写。"""
    from sqlalchemy import text
    _, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {"base_url": base, "allowed_origins": [base], "allowed_private_cidrs": [host + "/32"], "auth_type": "none"}
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(connector_id=connector.id, slug="write", name="write", operation_type="write", http_method="POST", endpoint_template="/write", approval_policy="required")
    write = {"id": "write", "type": "connector", "connector_slug": "service-test", "operation_slug": "write", "params": {}}
    definition = {"steps": [write, {**write, "id": "second"}]} if mode == "parallel" else {"steps": [{**write, "loop": {"back_to": "write", "max_iterations": 1}}]}
    context, checkpoint = await persisted_engine_context(manager, definition)
    override_factory(ConnectorServiceFactory(session_context_factory=manager.get_async_session_context, vault_provider=lambda: vault_configuration["current"]))
    try:
        with pytest.raises(WorkflowPaused) as paused:
            await WorkflowEngine(on_checkpoint=checkpoint).execute(definition, {}, execution_context=context)
        state = paused.value.state
        assert len(state["pending"]) == (2 if mode == "parallel" else 1) and requests == []
        original_ids = {pending["invocation_id"] for pending in state["pending"].values()}
        for pending in state["pending"].values():
            await get_connector_service().decide_invocation(pending["invocation_id"], "approve", actor="actor", expected_digest=pending["digest"])
        if mode == "loop":
            with pytest.raises(WorkflowPaused) as next_iteration:
                await WorkflowEngine(on_checkpoint=checkpoint).execute(definition, {}, execution_context=context, resume_state=state)
            state = next_iteration.value.state
            next_pending = state["pending"]["write"]
            assert next_pending["invocation_id"] not in original_ids
            assert requests == ["/write"]
            await get_connector_service().decide_invocation(next_pending["invocation_id"], "approve", actor="actor", expected_digest=next_pending["digest"])
        await WorkflowEngine(on_checkpoint=checkpoint).execute(definition, {}, execution_context=context, resume_state=state)
        assert requests == ["/write", "/write"]
        async with manager.get_async_session_context() as db:
            assert await db.scalar(text("SELECT count(DISTINCT step_execution_id) FROM connector_usage_logs")) == 2
            assert await db.scalar(text("SELECT count(*) FROM connector_operation_attempts")) == 2
            assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs WHERE status='succeeded'")) == 2
    finally:
        override_factory(None)


async def test_claim_checks_current_workflow_state_after_earlier_owner_validation(service_scope):
    """取消在验证之后提交，最终 SQL claim 仍必须拒绝。"""
    from yuxi.services.connectors.base import ConnectorExecution
    from yuxi.repositories.workflow_repository import WorkflowRepository

    service, manager = service_scope
    definition = {"steps": [{"id": "read", "type": "connector"}]}
    context, checkpoint = await persisted_engine_context(manager, definition)
    await checkpoint({"activations": {"read": "activation"}})
    execution = ConnectorExecution(
        invocation_id="unused",
        actor_uid="actor",
        consumer_type="workflow",
        logical_call_key="claim-cancel-race",
        connector_revision=1,
        operation_revision=1,
        workflow_id=context.workflow_id,
        workflow_run_id=context.workflow_run_id,
        step_id="read",
        step_execution_id="activation",
        workflow_owner_attempt=context.owner_attempt,
    )
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution)
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        await repo.validate_execution_owner(execution, await repo.get_active_actor("actor"))
    async with manager.get_async_session_context() as db:
        parent = await WorkflowRepository(db).get_run(context.workflow_run_id, for_update=True)
        parent.status = "cancelled"
    async with manager.get_async_session_context() as db:
        repo = ConnectorExecutionRepository(db)
        invocation = await repo.get_invocation(prepared["invocation_id"])
        assert not await repo.claim_invocation(
            invocation, owner_id="worker", owner_attempt="attempt", execution=execution
        )
        assert invocation.status == "prepared"


async def test_required_write_pauses_before_recording_completion_or_running_downstream(
    service_scope,
    vault_configuration,
):
    """账本持久等待批准，完成回调和依赖节点均不得继续。"""
    _, manager = service_scope
    async with manager.get_async_session_context() as db:
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
    completed = []

    async def on_completed(step_id, _output):
        completed.append(step_id)

    definition = {
        "steps": [
            {
                "id": "write",
                "type": "connector",
                "connector_slug": "service-test",
                "operation_slug": "write",
                "params": {},
                "output_key": "write_result",
            },
            {"id": "end", "type": "end", "depends_on": ["write"]},
        ]
    }
    execution, checkpoint = await persisted_engine_context(manager, definition)
    override_factory(
        ConnectorServiceFactory(
            session_context_factory=manager.get_async_session_context,
            vault_provider=lambda: vault_configuration["current"],
        )
    )
    try:
        with pytest.raises(WorkflowPaused) as paused:
            await WorkflowEngine(on_step_done=on_completed, on_checkpoint=checkpoint).execute(
                definition,
                {},
                execution_context=execution,
            )
        assert completed == []
        invocation_id = paused.value.state["pending"]["write"]["invocation_id"]
        async with manager.get_async_session_context() as db:
            invocation = await ConnectorExecutionRepository(db).get_invocation(invocation_id)
            assert invocation.status == "awaiting_approval"
            assert invocation.workflow_run_id == execution.workflow_run_id
    finally:
        override_factory(None)


async def test_recovery_fences_expired_owner_and_republishes_pending_after_queue_failure(service_scope):
    """恢复必须保留失败投递意图，并将失联运行收敛为可观察失败。"""
    from datetime import timedelta
    from yuxi.services.workflow_service import recover_workflow_runs
    from yuxi.utils.datetime_utils import utc_now

    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        workflow = Workflow(slug="recovery-test", name="recovery", definition={"steps": []}, created_by="actor")
        db.add(workflow)
        await db.flush()
        pending = WorkflowRun(workflow_id=workflow.id, created_by="actor", status="pending", dispatch_pending=True)
        expired = WorkflowRun(
            workflow_id=workflow.id,
            created_by="actor",
            status="running",
            owner_attempt="old-owner",
            owner_id="old-worker",
            lease_expires_at=utc_now() - timedelta(seconds=1),
        )
        db.add_all([pending, expired])
        await db.flush()
        pending_id, expired_id = pending.id, expired.id
    with patch("yuxi.services.workflow_service.get_arq_pool", new=AsyncMock(side_effect=ConnectionError())):
        await recover_workflow_runs(session_factory=manager.get_async_session_context)
    async with manager.get_async_session_context() as db:
        pending = await db.get(WorkflowRun, pending_id)
        expired = await db.get(WorkflowRun, expired_id)
        assert pending.status == "pending" and pending.dispatch_pending
        assert expired.status == "failed" and expired.error_message == "workflow_owner_lost"
        assert expired.owner_attempt is None and expired.lease_expires_at is None
        from yuxi.repositories.workflow_repository import WorkflowRepository

        assert not await WorkflowRepository(db).transition_owned_run(expired_id, "old-owner", "completed")
    queued = []

    class Queue:
        async def enqueue_job(self, name, run_id, generation, **_kwargs):
            async with manager.get_async_session_context() as db:
                committed = await db.get(WorkflowRun, run_id)
                assert committed.status == "pending" and committed.dispatch_pending
            queued.append((name, run_id, generation))
            return object()

    with (
        patch("yuxi.services.workflow_service.get_arq_pool", new=AsyncMock(return_value=Queue())),
        patch(
            "yuxi.services.workflow_service.append_run_stream_event",
            new=AsyncMock(),
        ),
    ):
        await recover_workflow_runs(session_factory=manager.get_async_session_context)
    assert queued == [("process_workflow_run", pending_id, 0)]
    async with manager.get_async_session_context() as db:
        assert not (await db.get(WorkflowRun, pending_id)).dispatch_pending


async def test_cancellation_includes_waits_and_cannot_cancel_another_actor_run(service_scope):
    """取消在同一个行锁事务中终结等待步骤并撤销 owner。"""
    from yuxi.services.workflow_service import cancel_workflow_execution

    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        workflow = Workflow(slug="cancel-test", name="cancel", definition={"steps": []}, created_by="actor")
        db.add(workflow)
        await db.flush()
        run = WorkflowRun(workflow_id=workflow.id, created_by="actor", status="waiting_approval")
        db.add(run)
        await db.flush()
        run_id = run.id
        db.add(
            WorkflowStepRun(workflow_run_id=run_id, step_id="write", step_type="connector", status="waiting_approval")
        )
    with pytest.raises(PermissionError):
        await cancel_workflow_execution(run_id, actor_uid="other", session_factory=manager.get_async_session_context)
    await cancel_workflow_execution(run_id, actor_uid="actor", session_factory=manager.get_async_session_context)
    async with manager.get_async_session_context() as db:
        run = await db.get(WorkflowRun, run_id)
        assert run.status == "cancelled" and not run.dispatch_pending
        from yuxi.repositories.workflow_repository import WorkflowRepository

        assert (await WorkflowRepository(db).get_step_run(run_id, "write")).status == "cancelled"


async def test_workflow_submission_keeps_committed_pending_intent_when_queue_is_unavailable(service_scope):
    """入口不能在 commit 后把队列失败改成 failed 并丢失补投递意图。"""
    from yuxi.services.workflow_service import create_workflow_execution
    from yuxi.repositories.workflow_repository import WorkflowRepository

    _, manager = service_scope
    async with manager.get_async_session_context() as db:
        workflow = Workflow(
            slug="submit-test", name="submit", created_by="actor", definition={"steps": [{"id": "end", "type": "end"}]}
        )
        db.add(workflow)
        await db.flush()
        workflow_id = workflow.id
    with patch("yuxi.services.workflow_service.get_arq_pool", new=AsyncMock(side_effect=ConnectionError())):
        async with manager.get_async_session_context() as db:
            result = await create_workflow_execution(db, workflow_id=workflow_id, actor_uid="actor", input_variables={})
    assert result["status"] == "pending" and result["queued"] is False
    async with manager.get_async_session_context() as db:
        run = await WorkflowRepository(db).get_run(result["id"])
        assert run.dispatch_pending and run.definition_snapshot == {"steps": [{"id": "end", "type": "end"}]}
        assert run.error_message is None
        assert await WorkflowRepository(db).get_run_for_actor(run.id, "other") is None


async def test_approved_engine_resume_reuses_activation_and_does_not_repeat_completed_reads(
    service_scope,
    vault_configuration,
    http_provider,
):
    """恢复沿同一层游标继续，已完成 HTTP 读节点只执行一次。"""
    _, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
            "auth_type": "none",
        }
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
    definition = {
        "steps": [
            {
                "id": "read",
                "type": "connector",
                "connector_slug": "service-test",
                "operation_slug": "read",
                "params": {},
            },
            {
                "id": "write",
                "type": "connector",
                "connector_slug": "service-test",
                "operation_slug": "write",
                "depends_on": ["read"],
                "params": {},
            },
            {"id": "end", "type": "end", "depends_on": ["write"]},
        ]
    }
    context, checkpoint = await persisted_engine_context(manager, definition)
    override_factory(
        ConnectorServiceFactory(
            session_context_factory=manager.get_async_session_context,
            vault_provider=lambda: vault_configuration["current"],
        )
    )
    try:
        with pytest.raises(WorkflowPaused) as paused:
            await WorkflowEngine(on_checkpoint=checkpoint).execute(definition, {}, execution_context=context)
        binding = paused.value.state["pending"]["write"]
        await get_connector_service().decide_invocation(
            binding["invocation_id"],
            "approve",
            actor="actor",
            expected_digest=binding["digest"],
        )
        await WorkflowEngine(on_checkpoint=checkpoint).execute(
            definition, {}, execution_context=context, resume_state=paused.value.state
        )
        assert requests == ["/read", "/write"]
        async with manager.get_async_session_context() as db:
            from sqlalchemy import text

            assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs")) == 2
    finally:
        override_factory(None)


async def test_worker_persists_approval_wait_and_releases_run_ownership(
    service_scope, vault_configuration, http_provider
):
    """实际 worker 处理函数在 PG 保存等待，而非 failed/completed。"""
    _, manager = service_scope
    base, host, requests = http_provider
    definition = {
        "steps": [
            {
                "id": "write",
                "type": "connector",
                "connector_slug": "service-test",
                "operation_slug": "write",
                "params": {},
                "output_key": "write_result",
            },
            {"id": "end", "type": "end", "depends_on": ["write"]},
        ]
    }
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
            "auth_type": "none",
        }
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
        workflow = Workflow(slug="worker-test", name="worker test", definition=definition, created_by="actor")
        db.add(workflow)
        await db.flush()
        run = WorkflowRun(workflow_id=workflow.id, created_by="actor", status="pending", input_variables={})
        db.add(run)
        await db.flush()
        run_id = run.id
    override_factory(
        ConnectorServiceFactory(
            session_context_factory=manager.get_async_session_context,
            vault_provider=lambda: vault_configuration["current"],
        )
    )
    try:
        with (
            patch.object(run_worker, "pg_manager", manager),
            patch.object(manager_module, "pg_manager", manager),
            patch(
                "yuxi.services.workflow_service.publish_workflow_event",
                new=AsyncMock(),
            ),
        ):
            await run_worker.process_workflow_run({"worker_id": "worker-test"}, run_id)
        async with manager.get_async_session_context() as db:
            run = await db.get(WorkflowRun, run_id)
            assert run.status == "waiting_approval"
            assert run.owner_id is None
            assert run.owner_attempt is None
            assert run.resume_state["pending"]["write"]["invocation_id"]
            from sqlalchemy import select

            steps = list(
                (
                    await db.scalars(
                        select(WorkflowStepRun).where(
                            WorkflowStepRun.workflow_run_id == run_id,
                        )
                    )
                ).all()
            )
            assert {step.step_id: step.status for step in steps} == {"write": "waiting_approval", "end": "pending"}
            binding = run.resume_state["pending"]["write"]
        assert requests == []
        await get_connector_service().decide_invocation(
            binding["invocation_id"],
            "approve",
            actor="actor",
            expected_digest=binding["digest"],
        )
        from yuxi.repositories.workflow_repository import WorkflowRepository

        async with manager.get_async_session_context() as db:
            assert await WorkflowRepository(db).queue_resume_if_ready(run_id)
        async with manager.get_async_session_context() as db:
            assert not await WorkflowRepository(db).queue_resume_if_ready(run_id)
        with (
            patch.object(run_worker, "pg_manager", manager),
            patch.object(manager_module, "pg_manager", manager),
            patch(
                "yuxi.services.workflow_service.publish_workflow_event",
                new=AsyncMock(),
            ),
        ):
            await run_worker.process_workflow_run({"worker_id": "worker-test"}, run_id, 1)
            await run_worker.process_workflow_run({"worker_id": "worker-test"}, run_id, 0)
        assert requests == ["/write"]
        async with manager.get_async_session_context() as db:
            run = await db.get(WorkflowRun, run_id)
            assert run.status == "completed"
            assert run.resume_generation == 1
    finally:
        override_factory(None)
