"""根据执行模式调整模型行为的中间件。"""

from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from yuxi.utils.logging_config import logger

_FAST_SYSTEM_SUFFIX = "\n\n[执行模式：快速] 请简洁作答，直接给出结论，减少不必要的分析和推理步骤。"
_DEEP_THINK_SYSTEM_SUFFIX = (
    "\n\n[执行模式：深度思考] 请对问题进行深入、全面的分析，"
    "考虑多种角度和可能性，给出详尽的推理过程和结论。"
)


class ExecutionModeMiddleware(AgentMiddleware):
    """根据 runtime context 的 execution_mode 注入对应的系统提示引导。"""

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        mode = getattr(request.runtime.context, "execution_mode", "balanced")
        if mode == "balanced" or mode not in ("fast", "deep_think"):
            return await handler(request)

        suffix = _FAST_SYSTEM_SUFFIX if mode == "fast" else _DEEP_THINK_SYSTEM_SUFFIX
        system_message = request.system_message or ""
        if suffix not in system_message:
            request = request.override(system_message=system_message + suffix)
            logger.debug(f"Execution mode '{mode}' system prompt suffix injected")

        return await handler(request)
