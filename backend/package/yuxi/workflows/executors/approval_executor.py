"""审批步骤执行器 — 暂停等待用户确认。"""

from __future__ import annotations

from typing import Any

from yuxi.utils.logging_config import logger
from yuxi.workflows.executors import BaseStepExecutor


class ApprovalStepExecutor(BaseStepExecutor):
    """人工审批 — 暂停执行，等待用户在前端审批后恢复。

    实际实现：
    1. 将审批请求写入 Redis
    2. 通过 SSE 通知前端
    3. 等待审批结果（通过 Redis pub/sub 或轮询）
    4. 返回审批决策
    """

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any], **kwargs) -> Any:
        prompt = step_data.get("approval_prompt") or step_data.get("prompt", "请审批")
        step_id = step_data.get("id", "unknown")

        logger.info(f"审批步骤 {step_id}: {prompt}")

        # TODO: 实现完整的审批暂停/恢复机制
        # 目前先返回待审批状态，由引擎层处理
        return {
            "status": "waiting_approval",
            "prompt": prompt,
            "step_id": step_id,
        }
