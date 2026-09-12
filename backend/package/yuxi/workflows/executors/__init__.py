"""步骤执行器注册表 — 按步骤类型获取对应执行器。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from yuxi.utils.logging_config import logger


class BaseStepExecutor(ABC):
    """步骤执行器基类。"""

    @abstractmethod
    async def execute(self, step_data: dict[str, Any], context: dict[str, Any]) -> Any:
        """执行步骤，返回输出值。

        Args:
            step_data: 已解析变量后的步骤定义
            context: 运行时变量上下文
        """
        ...


# 执行器注册表（延迟初始化）
_EXECUTORS: dict[str, BaseStepExecutor | None] = {}


def get_executor(step_type: str) -> BaseStepExecutor:
    """按步骤类型获取执行器实例。"""
    if step_type not in _EXECUTORS:
        _init_executor(step_type)
    executor = _EXECUTORS.get(step_type)
    if executor is None:
        raise ValueError(f"未知的步骤类型: {step_type}")
    return executor


def _init_executor(step_type: str) -> None:
    """延迟导入并初始化执行器。"""
    if step_type == "llm":
        from yuxi.workflows.executors.llm_executor import LLMStepExecutor
        _EXECUTORS[step_type] = LLMStepExecutor()
    elif step_type == "start":
        from yuxi.workflows.executors.start_executor import StartStepExecutor
        _EXECUTORS[step_type] = StartStepExecutor()
    elif step_type == "end":
        from yuxi.workflows.executors.end_executor import EndStepExecutor
        _EXECUTORS[step_type] = EndStepExecutor()
    elif step_type == "tool":
        from yuxi.workflows.executors.tool_executor import ToolStepExecutor
        _EXECUTORS[step_type] = ToolStepExecutor()
    elif step_type == "http":
        from yuxi.workflows.executors.http_executor import HTTPStepExecutor
        _EXECUTORS[step_type] = HTTPStepExecutor()
    elif step_type == "condition":
        from yuxi.workflows.executors.condition_executor import ConditionStepExecutor
        _EXECUTORS[step_type] = ConditionStepExecutor()
    elif step_type == "approval":
        from yuxi.workflows.executors.approval_executor import ApprovalStepExecutor
        _EXECUTORS[step_type] = ApprovalStepExecutor()
    elif step_type == "script":
        from yuxi.workflows.executors.script_executor import ScriptStepExecutor
        _EXECUTORS[step_type] = ScriptStepExecutor()
    elif step_type == "output":
        from yuxi.workflows.executors.output_executor import OutputStepExecutor
        _EXECUTORS[step_type] = OutputStepExecutor()
    else:
        logger.error(f"未知的步骤类型: {step_type}")
        _EXECUTORS[step_type] = None
