"""输出步骤执行器 — 模板渲染 + 委托已有工具完成文件生成/消息推送。"""

from __future__ import annotations

from typing import Any

from yuxi.utils.logging_config import logger
from yuxi.workflows.executors import BaseStepExecutor
from yuxi.workflows.template import resolve_template


class OutputStepExecutor(BaseStepExecutor):
    """格式化输出 + 交付。

    职责：
    1. 模板渲染（轻量，自己做）
    2. 文件生成 — 委托给 @tool 注册表中的工具（如 generate_pdf）
    3. 消息推送 — 委托给 @tool 注册表中的工具（如 send_dingtalk）

    不自造 PDF/Excel/IM 发送代码，复用已有工具。
    """

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any], **kwargs) -> Any:
        fmt = step_data.get("format", "markdown")
        template = step_data.get("template", "")
        delivery = step_data.get("delivery", [])

        # 1. 模板渲染
        rendered = resolve_template(template, context)
        if not isinstance(rendered, str):
            rendered = str(rendered)

        result: dict[str, Any] = {
            "format": fmt,
            "content": rendered,
            "delivery_results": [],
        }

        # 2. 执行交付动作
        for action_config in delivery:
            if not isinstance(action_config, dict):
                continue

            action = action_config.get("action")
            action_result = await self._execute_delivery_action(action, action_config, context)
            result["delivery_results"].append({
                "action": action,
                "result": action_result,
            })

        return result

    async def _execute_delivery_action(
        self,
        action: str | None,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        """执行单个交付动作。"""
        if action == "show":
            # 页面展示 — 直接返回内容，前端处理
            return {"status": "ok", "display": True}

        elif action == "file":
            # 文件生成 — 委托给指定工具
            tool_name = config.get("tool")
            if not tool_name:
                return {"status": "error", "message": "file 交付必须指定 tool"}

            return await self._call_tool(tool_name, config, context)

        elif action == "message":
            # 消息推送 — 委托给指定工具
            tool_name = config.get("tool")
            if not tool_name:
                return {"status": "error", "message": "message 交付必须指定 tool"}

            return await self._call_tool(tool_name, config, context)

        else:
            logger.warning(f"未知的交付动作: {action}")
            return {"status": "error", "message": f"未知的交付动作: {action}"}

    async def _call_tool(self, tool_name: str, config: dict[str, Any], context: dict[str, Any]) -> Any:
        """调用已有工具。"""
        from yuxi.agents.toolkits.registry import get_all_tool_instances

        # 查找工具
        tool = None
        for t in get_all_tool_instances():
            if t.name == tool_name:
                tool = t
                break

        if tool is None:
            return {"status": "error", "message": f"工具 '{tool_name}' 不存在"}

        # 构造参数（从 config 中解析变量）
        params = resolve_template(config.get("params", {}), context)

        try:
            result = await tool.ainvoke(params)
            return {"status": "ok", "result": result}
        except Exception as e:
            logger.exception(f"调用工具 {tool_name} 失败")
            return {"status": "error", "message": str(e)}
