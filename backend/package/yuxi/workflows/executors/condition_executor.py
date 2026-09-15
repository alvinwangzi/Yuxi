"""条件步骤执行器 — 表达式求值分支。"""

from __future__ import annotations

from typing import Any

from yuxi.workflows.executors import BaseStepExecutor
from yuxi.workflows.template import evaluate_condition


class ConditionStepExecutor(BaseStepExecutor):
    """条件分支 — 求值后返回 "then" 或 "else"。"""

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any], **kwargs) -> Any:
        condition = step_data.get("condition", "")
        if not condition:
            raise ValueError("condition 步骤必须指定 condition 表达式")

        result = evaluate_condition(condition, context)

        then_step = step_data.get("then_step")
        else_step = step_data.get("else_step")

        # 返回分支结果，引擎根据此决定后续执行路径
        return {
            "condition_result": result,
            "branch": then_step if result else else_step,
        }
