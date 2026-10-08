"""LLM 步骤执行器 — 两种模式：Agent 模式或轻量 model_spec 模式。"""

from __future__ import annotations

from typing import Any

from yuxi.workflows.executors import BaseStepExecutor


class LLMStepExecutor(BaseStepExecutor):
    """调用大模型。

    两种模式：
    1. Agent 模式：引用 agent_slug，继承其 system_prompt + 知识库 + 工具
    2. 轻量模式：直接 model_spec + prompt，不依赖 Agent 配置
    """

    async def execute(
        self,
        step_data: dict[str, Any],
        context: dict[str, Any],
        *,
        db_session=None,
        execution_context=None,
    ) -> Any:
        prompt = step_data.get("prompt", "")
        agent_slug = step_data.get("agent_slug")
        model_spec = step_data.get("model_spec")

        if agent_slug:
            return await self._execute_with_agent(agent_slug, prompt, execution_context)
        elif model_spec:
            return await self._execute_with_model(model_spec, prompt, context, db_session=db_session)
        else:
            # 默认使用系统默认模型
            return await self._execute_with_model(None, prompt, context, db_session=db_session)

    async def _execute_with_agent(self, agent_slug: str, prompt: str, execution_context) -> str:
        """通过工作流桥接提交真实 Agent 图，等待时不占用 worker。"""
        from yuxi.services.workflow_agent_service import execute_workflow_agent_step

        return await execute_workflow_agent_step(agent_slug.replace("/", "-"), prompt, execution_context)

    async def _execute_with_model(
        self, model_spec: dict | None, prompt: str, context: dict, *, db_session=None,
    ) -> str:
        """轻量模式：直接调用模型。"""
        from yuxi.models.chat import load_chat_model
        from langchain_core.messages import HumanMessage

        if model_spec:
            model_name = model_spec.get("model") or model_spec.get("model_id", "")
        else:
            model_name = ""

        # 未指定模型时使用系统默认模型
        if not model_name and db_session is not None:
            from yuxi.config.options import system_options

            opts = await system_options.get(db_session)
            model_name = opts.get("default_model", "")

        if not model_name and db_session is None:
            from yuxi.config.options import system_options
            from yuxi.storage.postgres.manager import pg_manager

            async with pg_manager.get_async_session_context() as db:
                model_name = (await system_options.get(db)).get("default_model", "")

        chat_model = load_chat_model(model_name)
        result = await chat_model.ainvoke([HumanMessage(content=prompt)])
        return result.content
