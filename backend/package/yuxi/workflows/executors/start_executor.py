"""开始步骤执行器 — 工作流输入入口。

输入变量由引擎在启动时直接注入 context，本步骤自身无需产生输出。
保留独立执行器使 start 成为真实 DAG 节点：拓扑序以它为第一层，
下游步骤通过 depends_on 引用它来表达"从输入之后开始"。
"""

from __future__ import annotations

from typing import Any

from yuxi.workflows.executors import BaseStepExecutor


class StartStepExecutor(BaseStepExecutor):
    """输入入口步骤：no-op，返回 None（变量已在 context 中）。"""

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any]) -> Any:
        return None
