"""工作流的 PostgreSQL 访问边界。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import (
    Workflow,
    WorkflowRun,
    WorkflowStepRun,
)
from yuxi.utils.datetime_utils import utc_now_naive


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
    ) -> list[Workflow]:
        stmt = select(Workflow).order_by(Workflow.updated_at.desc())
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
    ) -> int:
        stmt = select(func.count(Workflow.id))
        if category:
            stmt = stmt.where(Workflow.category == category)
        if category_id is not None:
            stmt = stmt.where(Workflow.category_id == category_id)
        if scope:
            stmt = stmt.where(Workflow.scope == scope)
        return await self.db.scalar(stmt) or 0

    async def get_workflow(self, workflow_id: int) -> Workflow | None:
        return await self.db.get(Workflow, workflow_id)

    async def get_workflow_by_slug(self, slug: str) -> Workflow | None:
        return await self.db.scalar(
            select(Workflow).where(Workflow.slug == slug)
        )

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

    # ── 运行记录 ──

    async def create_run(self, run: WorkflowRun) -> WorkflowRun:
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run(self, run_id: int) -> WorkflowRun | None:
        return await self.db.get(WorkflowRun, run_id)

    async def get_active_run(self, workflow_id: int) -> WorkflowRun | None:
        """检查工作流是否有正在执行中的运行记录（pending/running）。"""
        result = await self.db.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status.in_(["pending", "running"]),
            )
            .order_by(WorkflowRun.created_at.desc())
        )
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        workflow_id: int | None = None,
        *,
        limit: int = 50,
    ) -> list[WorkflowRun]:
        stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc())
        if workflow_id:
            stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
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
