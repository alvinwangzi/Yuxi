"""ExecutionModeMiddleware 单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from yuxi.agents.middlewares.execution_mode import (
    _DEEP_THINK_SYSTEM_SUFFIX,
    _FAST_SYSTEM_SUFFIX,
    ExecutionModeMiddleware,
)


def _make_request(*, execution_mode: str, system_message: str = "You are a helpful assistant.") -> ModelRequest:
    context = SimpleNamespace(execution_mode=execution_mode)
    return ModelRequest(
        model=SimpleNamespace(),
        messages=[HumanMessage(content="hello")],
        system_message=system_message,
        tools=[],
        runtime=SimpleNamespace(context=context),
    )


async def _capture_handler(request: ModelRequest) -> ModelResponse:
    """记录 handler 收到的 request，用于断言。"""
    _capture_handler.captured = request
    return ModelResponse(result=[AIMessage(content="ok")])


@pytest.mark.parametrize(
    ("mode", "expected_suffix"),
    [
        ("fast", _FAST_SYSTEM_SUFFIX),
        ("deep_think", _DEEP_THINK_SYSTEM_SUFFIX),
    ],
)
async def test_non_balanced_modes_inject_suffix(mode: str, expected_suffix: str) -> None:
    middleware = ExecutionModeMiddleware()
    request = _make_request(execution_mode=mode)
    await middleware.awrap_model_call(request, _capture_handler)

    captured = _capture_handler.captured
    assert captured.system_message.endswith(expected_suffix)
    assert captured.system_message.startswith("You are a helpful assistant.")


async def test_balanced_mode_does_not_modify_system_message() -> None:
    middleware = ExecutionModeMiddleware()
    request = _make_request(execution_mode="balanced")
    await middleware.awrap_model_call(request, _capture_handler)

    captured = _capture_handler.captured
    assert captured.system_message == "You are a helpful assistant."


async def test_unknown_mode_treated_as_balanced() -> None:
    middleware = ExecutionModeMiddleware()
    request = _make_request(execution_mode="nonsense")
    await middleware.awrap_model_call(request, _capture_handler)

    captured = _capture_handler.captured
    assert captured.system_message == "You are a helpful assistant."


async def test_suffix_not_duplicated_on_repeated_calls() -> None:
    middleware = ExecutionModeMiddleware()
    request = _make_request(execution_mode="fast", system_message="base" + _FAST_SYSTEM_SUFFIX)
    await middleware.awrap_model_call(request, _capture_handler)

    captured = _capture_handler.captured
    assert captured.system_message.count(_FAST_SYSTEM_SUFFIX) == 1


async def test_missing_execution_mode_attribute_defaults_to_balanced() -> None:
    middleware = ExecutionModeMiddleware()
    context = SimpleNamespace()  # 没有 execution_mode 属性
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[HumanMessage(content="hello")],
        system_message="base",
        tools=[],
        runtime=SimpleNamespace(context=context),
    )
    await middleware.awrap_model_call(request, _capture_handler)

    captured = _capture_handler.captured
    assert captured.system_message == "base"
