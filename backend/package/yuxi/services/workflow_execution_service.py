"""工作流运行的领取、检查点、等待与终态只由此用例拥有。"""

import asyncio
import copy
import uuid

from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.storage.postgres.models_business import WorkflowStepRun
from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.workflows.context import WorkflowExecutionContext, WorkflowPaused
from yuxi.workflows.engine import WorkflowEngine


class WorkflowOwnershipLost(RuntimeError):
    """迟到执行者已经不能更新当前运行。"""


async def execute_workflow_run(run_id, *, session_factory, owner_id, event_publisher, generation=0):
    """在短事务间运行引擎，等待时保存进度并释放 worker。"""
    owner_attempt = str(uuid.uuid4())
    async with session_factory() as db:
        repo = WorkflowRepository(db)
        run = await repo.claim_run(run_id, generation, owner_id, owner_attempt)
        if run is None:
            return
        workflow = await repo.get_workflow(run.workflow_id)
        if workflow is None or not run.created_by:
            await repo.transition_owned_run(
                run_id,
                owner_attempt,
                "failed",
                error_message="workflow_identity_missing",
                completed_at=utc_now_naive(),
            )
            return
        if not run.definition_snapshot:
            run.definition_snapshot = copy.deepcopy(workflow.definition)
        definition = copy.deepcopy(run.definition_snapshot)
        inputs = copy.deepcopy(run.input_variables or {})
        resume_state = copy.deepcopy(run.resume_state or {})
        execution = WorkflowExecutionContext(run.created_by, run.workflow_id, run_id, owner_id, owner_attempt)
        for step in definition.get("steps", []):
            if await repo.get_step_run(run_id, step["id"]) is None:
                await repo.create_step_run(
                    WorkflowStepRun(
                        workflow_run_id=run_id,
                        step_id=step["id"],
                        step_type=step.get("type", "llm"),
                        status="pending",
                    )
                )

    checkpoint_lock = asyncio.Lock()

    async def checkpoint(state):
        """持久化激活先于 dispatch；检查点更新必须仍拥有运行。"""
        async with checkpoint_lock:
            async with session_factory() as db:
                repo = WorkflowRepository(db)
                run = await repo.get_run(run_id, for_update=True)
                if run.status != "running" or run.owner_attempt != owner_attempt:
                    raise WorkflowOwnershipLost()
                run.resume_state = state
                run.context = state["context"]
                for step_id, activation in state["activations"].items():
                    step = await repo.get_step_run(run_id, step_id)
                    if step.step_execution_id != activation:
                        step.step_execution_id = activation
                        step.execution_count = (step.execution_count or 0) + 1
                        step.status = "pending"
                        step.output_payload = {}
                        step.completed_at = None
                        step.pending_connector_invocation_id = None
                        step.agent_request_id = step.agent_run_id = step.agent_thread_id = None
                        step.input_payload = {}
                    if step_id in state["step_results"]:
                        step.status = "completed"
                        step.output_payload = state["step_results"][step_id]
                        step.completed_at = utc_now_naive()
                    elif step_id in state["pending"]:
                        binding = state["pending"][step_id]
                        step.status = binding["status"]
                        step.pending_connector_invocation_id = binding.get("invocation_id")

    async def step_started(step_id, _step_type):
        """步骤可见运行状态仍受父运行 owner 保护。"""
        async with checkpoint_lock:
            async with session_factory() as db:
                repo = WorkflowRepository(db)
                run = await repo.get_run(run_id, for_update=True)
                if run.status != "running" or run.owner_attempt != owner_attempt:
                    raise WorkflowOwnershipLost()
                step = await repo.get_step_run(run_id, step_id)
                step.status = "running"
                step.started_at = utc_now_naive()

    async def step_failed(step_id, _error):
        """错误不包含远端正文，迟到 owner 不能覆盖取消。"""
        async with checkpoint_lock:
            async with session_factory() as db:
                repo = WorkflowRepository(db)
                run = await repo.get_run(run_id, for_update=True)
                if run.status != "running" or run.owner_attempt != owner_attempt:
                    return
                step = await repo.get_step_run(run_id, step_id)
                step.status = "failed"
                step.error_message = "workflow_step_failed"
                step.completed_at = utc_now_naive()

    engine = WorkflowEngine(on_step_start=step_started, on_step_error=step_failed, on_checkpoint=checkpoint)
    execution_task = asyncio.create_task(
        engine.execute(
            definition,
            inputs,
            execution_context=execution,
            resume_state=resume_state,
        )
    )

    async def renew_lease():
        """及时发现取消并停止模型或 HTTP；失联后的最终状态由恢复用例拥有。"""
        while True:
            await asyncio.sleep(10)
            async with session_factory() as db:
                owned = await WorkflowRepository(db).renew_owned_lease(run_id, owner_attempt)
            if not owned:
                execution_task.cancel()
                return

    lease_task = asyncio.create_task(renew_lease())
    try:
        await event_publisher(run_id, "workflow_started", {"run_id": run_id})
        context = await execution_task
    except WorkflowPaused as paused:
        status = (
            "waiting_approval"
            if any(binding["status"] == "waiting_approval" for binding in paused.state["pending"].values())
            else "waiting_agent"
        )
        async with session_factory() as db:
            changed = await WorkflowRepository(db).transition_owned_run(
                run_id,
                owner_attempt,
                status,
                resume_state=paused.state,
                context=paused.state["context"],
            )
        if changed:
            await event_publisher(run_id, "workflow_" + status, {"run_id": run_id})
    except WorkflowOwnershipLost:
        return
    except Exception as exc:
        async with session_factory() as db:
            changed = await WorkflowRepository(db).transition_owned_run(
                run_id,
                owner_attempt,
                "failed",
                error_message=type(exc).__name__,
                completed_at=utc_now_naive(),
            )
        if changed:
            await event_publisher(run_id, "workflow_failed", {"run_id": run_id, "error": type(exc).__name__})
    else:
        async with session_factory() as db:
            changed = await WorkflowRepository(db).transition_owned_run(
                run_id,
                owner_attempt,
                "completed",
                context=context,
                completed_at=utc_now_naive(),
            )
        if changed:
            await event_publisher(run_id, "workflow_completed", {"run_id": run_id})
    finally:
        execution_task.cancel()
        lease_task.cancel()
        await asyncio.gather(execution_task, lease_task, return_exceptions=True)
