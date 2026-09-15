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

    async def execute(
        self,
        step_data: dict[str, Any],
        context: dict[str, Any],
        *,
        db_session=None,
    ) -> Any:
        prompt = step_data.get("prompt", "")
        agent_slug = step_data.get("agent_slug")
        model_spec = step_data.get("model_spec")

        if agent_slug:
            return await self._execute_with_agent(agent_slug, prompt, context, db_session=db_session)
        elif model_spec:
            return await self._execute_with_model(model_spec, prompt, context, db_session=db_session)
        else:
            # 默认使用系统默认模型
            return await self._execute_with_model(None, prompt, context, db_session=db_session)

    async def _execute_with_agent(
        self,
        agent_slug: str,
        prompt: str,
        context: dict,
        *,
        db_session=None,
    ) -> str:
        """通过已有 Agent 执行：提取 system_prompt + model，直接调用模型。

        不使用 agent.invoke_messages()（需要 workdir/thread_id/uid 等完整运行时上下文），
        而是从 Agent 配置中提取 system_prompt 和 model，以 SystemMessage + HumanMessage 调用。
        """
        from langchain_core.messages import SystemMessage, HumanMessage
        from yuxi.models.chat import load_chat_model

        # 查找 Agent 记录（内置 Agent 或数据库中的角色模板 Agent）
        agent_record = None
        system_prompt = ""
        model_name = "default"

        if db_session is not None:
            from yuxi.repositories.agent_repository import AgentRepository

            agent_repo = AgentRepository(db_session)
            # 规范化 slug：工作流定义中使用 role_key 格式（如 product/product-manager），
            # 但 Agent 记录的 slug 已将 / 替换为 -（product-product-manager）
            lookup_slug = agent_slug.replace("/", "-")
            agent_record = await agent_repo.get_by_slug(lookup_slug)

            # 如果 agents 表未找到，尝试从角色模板查找（agent_slug 格式为 role_key，如 "engineering/engineering-backend-architect"）
            if not agent_record and "/" in agent_slug:
                from yuxi.repositories.role_template_repository import RoleTemplateRepository

                role_repo = RoleTemplateRepository(db_session)
                role_template = await role_repo.get_by_role_key(agent_slug)
                if role_template:
                    system_prompt = role_template.content or ""
                    model_name = "default"

        if agent_record and agent_record.config_json:
            ctx_cfg = agent_record.config_json.get("context", {})
            system_prompt = ctx_cfg.get("system_prompt", "")
            model_cfg = ctx_cfg.get("model", {})
            if isinstance(model_cfg, dict):
                model_name = model_cfg.get("model") or model_cfg.get("model_id", "default")
            elif isinstance(model_cfg, str) and model_cfg:
                model_name = model_cfg

        if not system_prompt:
            raise ValueError(f"Agent '{agent_slug}' 未配置 system_prompt")

        # 解析模型：Agent 未配置 model 时使用系统默认模型
        if model_name == "default" and db_session is not None:
            from yuxi.config.options import system_options

            opts = await system_options.get(db_session)
            model_name = opts.get("default_model", "")

        chat_model = load_chat_model(model_name)
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
        result = await chat_model.ainvoke(messages)
        return result.content

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

        chat_model = load_chat_model(model_name)
        result = await chat_model.ainvoke([HumanMessage(content=prompt)])
        return result.content
