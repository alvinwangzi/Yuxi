"""工作流执行服务 — 连接 API 层与 ARQ Worker。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.repositories.workflow_repository import WorkflowRepository
from yuxi.services.run_queue_service import append_run_stream_event, get_arq_pool
from yuxi.utils.logging_config import logger


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

    try:
        # 通过 ARQ 队列提交任务
        queue = await get_arq_pool()
        await queue.enqueue_job(
            "process_workflow_run",
            run_id,
            _job_id=f"workflow_run:{run_id}",
        )
        logger.info(f"已提交工作流运行任务: run_id={run_id}")

        # 发布 SSE 事件通知前端
        await append_run_stream_event(
            run_id=str(run_id),
            event_type="workflow_queued",
            payload={"run_id": run_id, "message": "工作流已加入执行队列"},
        )
        return {"run_id": run_id, "queued": True}
    except Exception as exc:
        logger.error(f"提交工作流运行任务失败: {exc}")
        raise


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
