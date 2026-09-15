"""工具步骤执行器 — 调用 @tool 注册表中的工具（含 MCP 工具）。"""

from __future__ import annotations

from typing import Any

from yuxi.utils.logging_config import logger
from yuxi.workflows.executors import BaseStepExecutor


class ToolStepExecutor(BaseStepExecutor):
    """调用已注册工具。

    工具来源：
    - 普通工具：@tool 装饰器注册的内置工具
    - MCP 工具：通过 langchain_mcp_adapters 转换的 MCP Server 工具
    """

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any], **kwargs) -> Any:
        tool_name = step_data.get("tool_name")
        if not tool_name:
            raise ValueError("tool 步骤必须指定 tool_name")

        tool_params = step_data.get("tool_params", {})

        # 查找工具
        tool = self._find_tool(tool_name)
        if tool is None:
            available = self._list_available_tools()
            raise ValueError(
                f"工具 '{tool_name}' 不存在。可用工具: {', '.join(available[:20])}"
            )

        # 调用工具
        logger.info(f"调用工具: {tool_name}, 参数: {tool_params}")
        result = await tool.ainvoke(tool_params)
        return result

    def _find_tool(self, tool_name: str):
        """从注册表中查找工具。"""
        from yuxi.agents.toolkits.registry import get_all_tool_instances

        for tool in get_all_tool_instances():
            if tool.name == tool_name:
                return tool
        return None

    def _list_available_tools(self) -> list[str]:
        """列出所有可用工具名称。"""
        from yuxi.agents.toolkits.registry import get_all_tool_instances

        return [t.name for t in get_all_tool_instances()]
