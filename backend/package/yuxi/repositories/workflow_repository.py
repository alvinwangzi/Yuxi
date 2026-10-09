"""工作流的 PostgreSQL 访问边界。"""

from __future__ import annotations

from sqlalchemy import select, func, update, or_, false, true
from datetime import timedelta, UTC
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    User,
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
    ConnectorUsageLog,
    AgentRunRequest,
    AgentRun,
    Message,
)
from yuxi.utils.datetime_utils import utc_now_naive, utc_now


class WorkflowRepository:
    """读写工作流定义和运行记录。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 工作流定义 ──

    async def list_workflows(
        self,
        *,
        category: str | None = None,
        category_id: int | None = None,
        scope: str | None = None,
        limit: int = 100,
        offset: int = 0,
        actor=None,
    ) -> list[Workflow]:
        stmt = select(Workflow).order_by(Workflow.updated_at.desc())
        if actor is not None:
            stmt = stmt.where(_workflow_visibility(actor))
        if category:
            stmt = stmt.where(Workflow.category == category)
        if category_id is not None:
            stmt = stmt.where(Workflow.category_id == category_id)
        if scope:
            stmt = stmt.where(Workflow.scope == scope)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_workflows(
        self,
        *,
        category: str | None = None,
        category_id: int | None = None,
        scope: str | None = None,
        actor=None,
    ) -> int:
        stmt = select(func.count(Workflow.id))
        if actor is not None:
            stmt = stmt.where(_workflow_visibility(actor))
        if category:
            stmt = stmt.where(Workflow.category == category)
        if category_id is not None:
            stmt = stmt.where(Workflow.category_id == category_id)
        if scope:
            stmt = stmt.where(Workflow.scope == scope)
        return await self.db.scalar(stmt) or 0

    async def get_workflow(self, workflow_id: int) -> Workflow | None:
        return await self.db.get(Workflow, workflow_id)

    async def get_visible_workflow(self, workflow_id: int, actor, *, for_update=False) -> Workflow | None:
        """按模板可见范围查询；运行结果仍只允许创建人读取。"""
        stmt = select(Workflow).where(Workflow.id == workflow_id, _workflow_visibility(actor))
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(stmt)

    async def get_workflow_by_slug(self, slug: str) -> Workflow | None:
        return await self.db.scalar(select(Workflow).where(Workflow.slug == slug))

    async def create_workflow(self, workflow: Workflow) -> Workflow:
        self.db.add(workflow)
        await self.db.flush()
        return workflow

    async def update_workflow(self, workflow: Workflow) -> Workflow:
        workflow.updated_at = utc_now_naive()
        await self.db.flush()
        return workflow

    async def delete_workflow(self, workflow: Workflow) -> None:
        await self.db.delete(workflow)
        await self.db.flush()

    async def list_selectable_for_user(self, user: User, *, limit: int = 200) -> list[Workflow]:
        """列出用户可选择的工作流：管理员返回所有非平台工作流，普通用户返回公司级 + 自己的个人级。"""
        stmt = select(Workflow).where(Workflow.scope != "platform", _workflow_visibility(user)).order_by(Workflow.updated_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_scope(self, user: User | None = None) -> dict[str, int]:
        """按 scope 分组统计工作流数量；非管理员只统计可见范围（公司级 + 自己的个人级）。"""
        is_admin = user is not None and user.role in ("admin", "superadmin")
        base = select(Workflow.scope, func.count(Workflow.id))
        if user is not None and not is_admin:
            base = base.where(
                or_(
                    Workflow.scope == "company",
                    (Workflow.scope == "personal") & (Workflow.created_by == str(user.uid)),
                )
            )
        result = await self.db.execute(base.group_by(Workflow.scope))
        counts = {row[0]: row[1] for row in result.fetchall()}
        if is_admin:
            return {
                "total": sum(counts.values()),
                "platform": counts.get("platform", 0),
                "company": counts.get("company", 0),
                "personal": counts.get("personal", 0),
            }
        company = counts.get("company", 0)
        personal = counts.get("personal", 0)
        return {
            "total": company + personal,
            "platform": 0,
            "company": company,
            "personal": personal,
        }

    # ── 运行记录 ──

    async def create_run(self, run: WorkflowRun) -> WorkflowRun:
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run(self, run_id: int, *, for_update: bool = False) -> WorkflowRun | None:
        """运行转换在行锁内刷新当前事实。"""
        statement = select(WorkflowRun).where(WorkflowRun.id == run_id)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(statement)

    async def get_run_for_actor(self, run_id: int, actor_uid: str) -> WorkflowRun | None:
        """源查询即约束创建人，管理模板可见性不授权读取别人输出。"""
        return await self.db.scalar(
            select(WorkflowRun).where(
                WorkflowRun.id == run_id,
                WorkflowRun.created_by == actor_uid,
            )
        )

    async def claim_run(self, run_id: int, generation: int, owner_id: str, owner_attempt: str) -> WorkflowRun | None:
        """只领取当前代数的 pending 运行，拒绝重复 job。"""
        run = await self.get_run(run_id, for_update=True)
        if run is None or run.status != "pending" or run.resume_generation != generation:
            return None
        run.status = "running"
        run.owner_id = owner_id
        run.owner_attempt = owner_attempt
        run.started_at = run.started_at or utc_now_naive()
        run.heartbeat_at = utc_now()
        run.lease_expires_at = utc_now() + timedelta(seconds=120)
        run.dispatch_pending = False
        await self.db.flush()
        return run

    async def transition_owned_run(self, run_id: int, owner_attempt: str, status: str, **values) -> bool:
        """只有仍运行的当前 owner 能发布等待或终态。"""
        if status == "failed":
            run = await self.get_run(run_id, for_update=True)
            if run is None:
                return False
            values["resume_state"] = {**(run.resume_state or {}), "cancel_propagation_pending": True}
        result = await self.db.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == run_id,
                WorkflowRun.owner_attempt == owner_attempt,
                WorkflowRun.status == "running",
            )
            .values(status=status, owner_id=None, owner_attempt=None, lease_expires_at=None, **values)
        )
        await self.db.flush()
        return result.rowcount == 1

    async def queue_resume_if_ready(self, run_id: int) -> bool:
        """等待项已被持久决定后仅生成一次新的投递代数。"""
        run = await self.get_run(run_id, for_update=True)
        if run is None or run.status not in ("waiting_approval", "waiting_agent"):
            return False
        pending = (run.resume_state or {}).get("pending", {})
        if not pending:
            return False
        ready = True
        for step_id, binding in pending.items():
            if binding["status"] == "waiting_agent":
                state = await self.bound_agent_state(run_id, step_id, run.created_by)
                if state["status"] in ("waiting", "approval_wait", "resume_ready", "missing"):
                    ready = False
                    continue
                if state["status"] == "completed":
                    continue
                run.resume_state = {**(run.resume_state or {}), "cancel_propagation_pending": True}
                run.status = "failed"
                run.error_message = state["error"]
                run.completed_at = utc_now_naive()
                step = await self.get_step_run(run_id, step_id)
                step.status = "failed"
                step.error_message = run.error_message
                return False
            if binding["status"] != "waiting_approval":
                return False
            invocation = await self.db.get(ConnectorUsageLog, binding["invocation_id"])
            if invocation is None or invocation.status in ("rejected", "cancelled", "failed"):
                run.resume_state = {**(run.resume_state or {}), "cancel_propagation_pending": True}
                run.status = "failed"
                run.error_message = "connector_approval_rejected_or_unavailable"
                run.completed_at = utc_now_naive()
                step = await self.get_step_run(run_id, step_id)
                step.status = "failed"
                step.error_message = run.error_message
                return False
            if invocation.status not in ("prepared", "succeeded"):
                ready = False
        if not ready:
            return False
        run.status = "pending"
        run.resume_generation += 1
        run.dispatch_pending = True
        run.next_dispatch_at = utc_now()
        await self.db.flush()
        return True

    async def bind_agent_step(self, execution, agent_slug: str) -> WorkflowStepRun:
        """在父运行 owner 锁内持久化每次激活唯一的 Request 和线程。"""
        import uuid

        run = await self.get_run(execution.workflow_run_id, for_update=True)
        if (
            run is None
            or run.created_by != execution.actor_uid
            or run.status != "running"
            or run.owner_attempt != execution.owner_attempt
        ):
            raise PermissionError("workflow_owner_lost")
        step = await self.get_step_run(run.id, execution.step_id)
        if step is None or step.step_execution_id != execution.step_execution_id:
            raise ValueError("workflow_step_activation_invalid")
        if not step.agent_request_id:
            step.agent_request_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"workflow:{run.id}:{step.step_id}:{step.step_execution_id}")
            )
            step.agent_thread_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow:{run.id}:{step.step_id}:{agent_slug}"))
        return step

    async def require_agent_resume_owner(self, source_run, actor_uid: str, request_id: str) -> None:
        """正式 resume 先锁工作流父，再锁 Conversation；终态父不能复活子任务。"""
        metadata = source_run.origin_metadata or {}
        if type(metadata.get("workflow_run_id")) is not int:
            raise PermissionError("workflow_agent_resume_unavailable")
        run = await self.get_run(metadata.get("workflow_run_id"), for_update=True)
        if (
            run is None
            or run.created_by != actor_uid
            or run.status not in ("running", "waiting_agent", "waiting_approval")
        ):
            raise PermissionError("workflow_agent_resume_unavailable")
        step = await self.get_step_run(run.id, metadata.get("step_id"))
        if step is None or step.step_execution_id != metadata.get("step_execution_id"):
            raise PermissionError("workflow_agent_resume_unavailable")
        state = await self.bound_agent_state(run.id, step.step_id, actor_uid)
        active_id = state.get("binding", {}).get("active_run_id")
        if active_id == source_run.id:
            return
        active = await self.db.get(AgentRun, active_id) if active_id else None
        if active is None or active.request_id != request_id or active.created_by_run_id != source_run.id:
            raise PermissionError("workflow_agent_resume_unavailable")

    async def bound_agent_state(self, run_id: int, step_id: str, actor_uid: str) -> dict:
        """只沿持久 Request、resume 意图与父子关系读取当前结果。"""
        step = await self.get_step_run(run_id, step_id)
        if step is None or not step.agent_request_id:
            return {"status": "missing"}
        request = await self.db.scalar(
            select(AgentRunRequest).where(AgentRunRequest.request_id == step.agent_request_id)
        )
        if request is None:
            return {"status": "missing"}
        origin = request.origin_metadata or {}
        if (
            request.uid != actor_uid
            or request.conversation_thread_id != step.agent_thread_id
            or (origin.get("workflow_run_id"), origin.get("step_id"), origin.get("step_execution_id"))
            != (run_id, step_id, step.step_execution_id)
        ):
            raise ValueError("agent_request_binding_invalid")
        if request.status in ("failed", "cancelled", "rejected"):
            return {"status": "failed", "error": "agent_request_" + request.status}
        if not request.dispatched_run_id:
            return {"status": "waiting"}
        binding = dict((step.input_payload or {}).get("agent_binding", {}))
        child_id = binding.get("active_run_id") or step.agent_run_id or request.dispatched_run_id
        child = await self.db.get(AgentRun, child_id)
        intent = binding.get("resume_intent")
        if intent and child is not None and intent["parent_run_id"] == child.id:
            resumed = await self.db.scalar(select(AgentRun).where(AgentRun.request_id == intent["request_id"]))
            if resumed is not None:
                if resumed.run_type != "resume" or resumed.created_by_run_id != child.id:
                    raise ValueError("agent_resume_binding_invalid")
                child = resumed
        if child is None:
            raise ValueError("agent_run_binding_invalid")
        ancestor = child
        seen = set()
        while True:
            if (ancestor.uid, ancestor.conversation_thread_id, ancestor.agent_slug) != (
                actor_uid,
                step.agent_thread_id,
                request.agent_slug,
            ) or ancestor.id in seen:
                raise ValueError("agent_run_binding_invalid")
            seen.add(ancestor.id)
            if ancestor.id == request.dispatched_run_id:
                if ancestor.request_id != request.request_id:
                    raise ValueError("agent_run_binding_invalid")
                break
            if ancestor.run_type != "resume" or not ancestor.created_by_run_id:
                raise ValueError("agent_resume_binding_invalid")
            ancestor = await self.db.get(AgentRun, ancestor.created_by_run_id)
            if ancestor is None:
                raise ValueError("agent_resume_binding_invalid")
        binding.update(
            {
                "origin_request_id": request.request_id,
                "origin_run_id": request.dispatched_run_id,
                "active_request_id": child.request_id,
                "active_run_id": child.id,
                "agent_slug": request.agent_slug,
                "thread_id": step.agent_thread_id,
            }
        )
        step.agent_run_id = child.id
        step.input_payload = {**(step.input_payload or {}), "agent_binding": binding}
        unresolved = list(
            (
                await self.db.scalars(
                    select(ConnectorUsageLog)
                    .where(
                        ConnectorUsageLog.agent_request_id == request.request_id,
                        ConnectorUsageLog.workflow_run_id == run_id,
                        ConnectorUsageLog.step_execution_id == step.step_execution_id,
                        ConnectorUsageLog.operation_type == "write",
                        ConnectorUsageLog.status == "unknown",
                    )
                    .order_by(ConnectorUsageLog.created_at)
                )
            ).all()
        )
        if unresolved:
            return {"status": "approval_wait", "invocation_ids": [inv.id for inv in unresolved], "binding": binding}
        if child.status == "interrupted" and child.error_type == "connector_approval_required":
            invocations = list(
                (
                    await self.db.scalars(
                        select(ConnectorUsageLog)
                        .where(
                            ConnectorUsageLog.agent_request_id == request.request_id,
                            ConnectorUsageLog.workflow_run_id == run_id,
                            ConnectorUsageLog.step_execution_id == step.step_execution_id,
                            ConnectorUsageLog.operation_type == "write",
                            ConnectorUsageLog.status.in_(
                                (
                                    "awaiting_approval",
                                    "prepared",
                                    "succeeded",
                                    "rejected",
                                    "failed",
                                    "cancelled",
                                    "unknown",
                                )
                            ),
                        )
                        .order_by(ConnectorUsageLog.created_at)
                    )
                ).all()
            )
            if not invocations:
                return {"status": "failed", "error": "agent_approval_binding_missing", "binding": binding}
            if any(inv.status in ("rejected", "failed", "cancelled", "unknown") for inv in invocations):
                return {"status": "failed", "error": "agent_connector_unavailable", "binding": binding}
            expired = any(
                inv.status == "prepared"
                and (
                    inv.approval_expires_at is None
                    or (
                        inv.approval_expires_at.replace(tzinfo=UTC)
                        if inv.approval_expires_at.tzinfo is None
                        else inv.approval_expires_at
                    ).astimezone(UTC)
                    <= utc_now()
                )
                for inv in invocations
            )
            if expired:
                return {"status": "failed", "error": "agent_connector_approval_expired", "binding": binding}
            return {
                "status": "approval_wait"
                if any(inv.status == "awaiting_approval" for inv in invocations)
                else "resume_ready",
                "invocation_ids": [inv.id for inv in invocations],
                "binding": binding,
            }
        if child.status in ("failed", "cancelled", "interrupted"):
            return {"status": "failed", "error": "agent_run_" + child.status, "binding": binding}
        if child.status != "completed":
            return {"status": "waiting", "run_status": child.status, "binding": binding}
        output = await self.db.get(Message, child.output_message_id) if child.output_message_id else None
        if (
            output is None
            or output.run_id != child.id
            or output.conversation_id != child.conversation_id
            or output.role != "assistant"
            or output.request_id != child.request_id
        ):
            raise ValueError("agent_output_binding_invalid")
        return {"status": "completed", "output": output.content, "binding": binding}

    async def prepare_agent_resumes(self, run_id: int) -> list[dict]:
        """在父运行锁内投影全部待项并提交确定的子恢复意图。"""
        import copy
        import uuid

        run = await self.get_run(run_id, for_update=True)
        if run is None or run.status not in ("waiting_agent", "waiting_approval"):
            return []
        state = copy.deepcopy(run.resume_state or {})
        intents = []
        waiting_approval = False
        for step_id, pending in state.get("pending", {}).items():
            if pending.get("status") == "waiting_approval":
                invocation = await self.db.get(ConnectorUsageLog, pending["invocation_id"])
                waiting_approval |= invocation is not None and invocation.status in ("awaiting_approval", "unknown")
            if pending.get("status") != "waiting_agent":
                continue
            child = await self.bound_agent_state(run_id, step_id, run.created_by)
            binding = child.get("binding", {})
            pending.update(binding)
            step = await self.get_step_run(run_id, step_id)
            if child["status"] == "approval_wait":
                pending["invocation_ids"] = child["invocation_ids"]
                step.status = "waiting_approval"
                step.pending_connector_invocation_id = child["invocation_ids"][0]
                waiting_approval = True
                continue
            if child["status"] in ("waiting", "resume_ready"):
                step.status = "waiting_agent"
                step.pending_connector_invocation_id = None
            intent = binding.get("resume_intent")
            if (
                child["status"] == "waiting"
                and child.get("run_status") == "pending"
                and intent
                and intent.get("dispatch_pending")
            ):
                pass
            elif child["status"] != "resume_ready":
                continue
            elif intent is None or intent["parent_run_id"] != binding["active_run_id"]:
                pending["invocation_ids"] = child["invocation_ids"]
                intent = {
                    "parent_run_id": binding["active_run_id"],
                    "invocation_ids": child["invocation_ids"],
                    "request_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, "workflow-agent-resume:" + binding["active_run_id"])
                    ),
                    "dispatch_pending": True,
                }
                binding["resume_intent"] = intent
                step.input_payload = {**(step.input_payload or {}), "agent_binding": binding}
                pending["resume_intent"] = intent
            intents.append(
                {
                    **intent,
                    "actor_uid": run.created_by,
                    "step_id": step_id,
                    "agent_slug": binding["agent_slug"],
                    "thread_id": binding["thread_id"],
                }
            )
        run.resume_state = state
        run.status = "waiting_approval" if waiting_approval else "waiting_agent"
        return intents

    async def mark_agent_resume_dispatched(self, run_id: int, step_id: str, request_id: str) -> None:
        """仅清理同一恢复意图，重复通知不能生成新的子运行。"""
        import copy

        step = await self.get_step_run(run_id, step_id)
        payload = copy.deepcopy(step.input_payload)
        intent = payload["agent_binding"].get("resume_intent")
        if intent and intent["request_id"] == request_id:
            intent["dispatch_pending"] = False
            step.input_payload = payload

    async def renew_owned_lease(self, run_id: int, owner_attempt: str) -> bool:
        """续租只允许当前运行 owner，取消和终态立即使续租失败。"""
        now = utc_now()
        result = await self.db.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == run_id,
                WorkflowRun.status == "running",
                WorkflowRun.owner_attempt == owner_attempt,
            )
            .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=120))
        )
        return result.rowcount == 1

    async def recovery_candidates(self) -> list[int]:
        """返回需要补投递、等待重查或失联收敛的运行。"""
        return list(
            (
                await self.db.scalars(
                    select(WorkflowRun.id)
                    .where(
                        WorkflowRun.status.in_(("pending", "waiting_agent", "waiting_approval"))
                        | ((WorkflowRun.status == "running") & (WorkflowRun.lease_expires_at < utc_now()))
                        | (
                            (WorkflowRun.status.in_(("cancelled", "failed")))
                            & WorkflowRun.resume_state["cancel_propagation_pending"].as_boolean().is_(True)
                        ),
                    )
                    .order_by(WorkflowRun.id)
                )
            ).all()
        )

    async def fail_expired_owner(self, run_id: int) -> bool:
        """未知副作用不自动重跑，失联 owner 统一形成显式失败。"""
        run = await self.get_run(run_id, for_update=True)
        if run is None or run.status != "running" or run.lease_expires_at is None or run.lease_expires_at >= utc_now():
            return False
        await self.transition_owned_run(
            run_id, run.owner_attempt, "failed", error_message="workflow_owner_lost", completed_at=utc_now_naive()
        )
        for step in await self.list_step_runs(run_id):
            if step.status not in ("completed", "failed", "skipped", "cancelled"):
                step.status = "failed"
                step.error_message = "workflow_owner_lost"
                step.completed_at = utc_now_naive()
        return True

    async def cancel_for_actor(self, run_id: int, actor_uid: str) -> list[dict]:
        """提交父取消及重试意图，并沿真实绑定找到当前恢复 Run。"""
        run = await self.get_run(run_id, for_update=True)
        if run is None or run.created_by != actor_uid:
            raise PermissionError("workflow_not_visible")
        if run.status == "completed" or (
            run.status == "failed" and not (run.resume_state or {}).get("cancel_propagation_pending")
        ):
            return []
        if run.status != "failed":
            run.status = "cancelled"
        run.owner_id = run.owner_attempt = run.lease_expires_at = None
        run.dispatch_pending = False
        run.completed_at = run.completed_at or utc_now_naive()
        run.resume_state = {**(run.resume_state or {}), "cancel_propagation_pending": True}
        children = []
        for step in await self.list_step_runs(run_id):
            if step.agent_request_id:
                state = await self.bound_agent_state(run_id, step.step_id, actor_uid)
                children.append(
                    {"request_id": step.agent_request_id, "run_id": state.get("binding", {}).get("active_run_id")}
                )
            if step.status in ("completed", "failed", "skipped", "cancelled"):
                continue
            step.status = "cancelled"
            step.completed_at = utc_now_naive()
        await self.db.execute(
            update(ConnectorUsageLog)
            .where(
                ConnectorUsageLog.workflow_run_id == run_id,
                ConnectorUsageLog.status.in_(("prepared", "awaiting_approval")),
            )
            .values(status="cancelled", completed_at=utc_now(), execution_snapshot_ciphertext=None)
        )
        return children

    async def mark_cancel_propagated(self, run_id: int) -> None:
        """仅取消父状态可以结束持久子取消重试。"""
        run = await self.get_run(run_id, for_update=True)
        if run.status in ("cancelled", "failed"):
            run.resume_state = {**(run.resume_state or {}), "cancel_propagation_pending": False}

    async def get_active_run(self, workflow_id: int) -> WorkflowRun | None:
        """检查工作流是否有正在执行中的运行记录（含等待状态）。"""
        result = await self.db.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status.in_(["pending", "running", "waiting_agent", "waiting_approval"]),
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        workflow_id: int | None = None,
        *,
        limit: int = 50,
        actor_uid: str | None = None,
    ) -> list[WorkflowRun]:
        stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc())
        if workflow_id:
            stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
        if actor_uid is not None:
            stmt = stmt.where(WorkflowRun.created_by == actor_uid)
        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_run(self, run: WorkflowRun) -> WorkflowRun:
        await self.db.flush()
        return run

    # ── 步骤运行记录 ──

    async def create_step_run(self, step_run: WorkflowStepRun) -> WorkflowStepRun:
        self.db.add(step_run)
        await self.db.flush()
        return step_run

    async def list_step_runs(self, workflow_run_id: int) -> list[WorkflowStepRun]:
        result = await self.db.execute(
            select(WorkflowStepRun)
            .where(WorkflowStepRun.workflow_run_id == workflow_run_id)
            .order_by(WorkflowStepRun.id)
        )
        return list(result.scalars().all())

    async def update_step_run(self, step_run: WorkflowStepRun) -> WorkflowStepRun:
        await self.db.flush()
        return step_run

    async def get_step_run(
        self,
        workflow_run_id: int,
        step_id: str,
    ) -> WorkflowStepRun | None:
        # 当存在重复记录时（ARQ 重试导致），返回最新的记录（ID 最大）
        return await self.db.scalar(
            select(WorkflowStepRun)
            .where(
                WorkflowStepRun.workflow_run_id == workflow_run_id,
                WorkflowStepRun.step_id == step_id,
            )
            .order_by(WorkflowStepRun.id.desc())
        )


def _workflow_visibility(actor):
    """工作流模板沿既有公司、部门、个人与管理员管理可见性过滤。"""
    if actor is None or actor.is_deleted:
        return false()
    if actor.role in ("admin", "superadmin"):
        return true()
    return or_(
        Workflow.scope == "company",
        Workflow.created_by == actor.uid,
        ((Workflow.scope == "department") & (Workflow.department_id == actor.department_id))
        if actor.department_id is not None
        else false(),
    )
