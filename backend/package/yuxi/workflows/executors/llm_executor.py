"""LLM 步骤执行器 — 两种模式：Agent 模式或轻量 model_spec 模式。"""

from __future__ import annotations

from typing import Any

from yuxi.utils.logging_config import logger
from yuxi.workflows.executors import BaseStepExecutor


class LLMStepExecutor(BaseStepExecutor):
    """调用大模型。

    两种模式：
    1. Agent 模式：引用 agent_slug，继承其 system_prompt + 知识库 + 工具
    2. 轻量模式：直接 model_spec + prompt，不依赖 Agent 配置
    """

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any]) -> Any:
        prompt = step_data.get("prompt", "")
        agent_slug = step_data.get("agent_slug")
        model_spec = step_data.get("model_spec")

        if agent_slug:
            return await self._execute_with_agent(agent_slug, prompt, context)
        elif model_spec:
            return await self._execute_with_model(model_spec, prompt, context)
        else:
            # 默认使用系统默认模型
            return await self._execute_with_model(None, prompt, context)

    async def _execute_with_agent(self, agent_slug: str, prompt: str, context: dict) -> str:
        """通过已有 Agent 执行（带 system_prompt、知识库等）。"""
        from yuxi.agents.buildin import agent_manager

        agent = agent_manager.get_agent(agent_slug)
        if agent is None:
            raise ValueError(f"Agent '{agent_slug}' 不存在")

        # 构造简单消息调用
        from langchain_core.messages import HumanMessage

        result = await agent.invoke_messages([HumanMessage(content=prompt)])

        # 提取文本输出
        if hasattr(result, "content"):
            return result.content
        return str(result)

    async def _execute_with_model(self, model_spec: dict | None, prompt: str, context: dict) -> str:
        """轻量模式：直接调用模型。"""
        from yuxi.models.chat import load_chat_model
        from langchain_core.messages import HumanMessage

        if model_spec:
            model_name = model_spec.get("model") or model_spec.get("model_id", "")
            chat_model = load_chat_model(model_name)
        else:
            # 使用系统默认模型
            chat_model = load_chat_model("default")

        result = await chat_model.ainvoke([HumanMessage(content=prompt)])
        return result.content
