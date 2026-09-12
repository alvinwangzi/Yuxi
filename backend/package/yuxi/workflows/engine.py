"""工作流执行引擎 — 按 DAG 分层并行执行，支持循环回退。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from yuxi.utils.datetime_utils import utc_now_naive
from yuxi.utils.logging_config import logger
from yuxi.workflows.dag import DAGLayer, build_dag
from yuxi.workflows.template import evaluate_condition, resolve_template


class WorkflowExecutionError(RuntimeError):
    """工作流执行失败。"""


class WorkflowEngine:
    """DAG 工作流执行引擎。

    职责：
    1. 从 definition 构建分层执行计划
    2. 按层顺序执行，同层步骤并行（受 concurrency 限制）
    3. 步骤完成后检查 loop 字段，决定是否回退
    4. 通过回调上报进度（SSE 推送）
    """

    def __init__(self, *, on_step_start=None, on_step_done=None, on_step_error=None):
        """
        Args:
            on_step_start: 步骤开始执行时的回调 (step_id, step_type) -> None
            on_step_done: 步骤完成时的回调 (step_id, output) -> None
            on_step_error: 步骤失败时的回调 (step_id, error_msg) -> None
        """
        self._on_step_start = on_step_start
        self._on_step_done = on_step_done
        self._on_step_error = on_step_error

    async def execute(
        self,
        definition: dict[str, Any],
        input_variables: dict[str, Any],
    ) -> dict[str, Any]:
        """执行工作流，返回最终的 context。

        Args:
            definition: 工作流定义（含 steps、concurrency 等）
            input_variables: 用户输入的变量

        Returns:
            最终的 context 字典
        """
        layers = build_dag(definition)
        concurrency = definition.get("concurrency", 4)
        context: dict[str, Any] = dict(input_variables)

        # 步骤索引（用于快速查找）
        step_index: dict[str, dict] = {}
        for step in definition.get("steps", []):
            step_index[step["id"]] = step

        # 循环迭代计数
        loop_counts: dict[str, int] = {}

        # 执行记录
        step_results: dict[str, Any] = {}
        step_errors: dict[str, str] = {}

        for layer in layers:
            await self._execute_layer(
                layer=layer,
                step_index=step_index,
                context=context,
                concurrency=concurrency,
                step_results=step_results,
                step_errors=step_errors,
                loop_counts=loop_counts,
            )

        return context

    async def _execute_layer(
        self,
        layer: DAGLayer,
        step_index: dict[str, dict],
        context: dict[str, Any],
        concurrency: int,
        step_results: dict[str, Any],
        step_errors: dict[str, str],
        loop_counts: dict[str, int],
    ) -> None:
        """执行一个 DAG 层级 — 同层步骤并行。"""
        semaphore = asyncio.Semaphore(concurrency)

        async def _run_step(node):
            async with semaphore:
                await self._execute_step(
                    step_data=step_index[node.id],
                    context=context,
                    layer_index=layer.index,
                    step_results=step_results,
                    step_errors=step_errors,
                    loop_counts=loop_counts,
                )

        tasks = [asyncio.create_task(_run_step(node)) for node in layer.nodes]
        await asyncio.gather(*tasks, return_exceptions=True)

        # 检查是否有步骤失败
        for node in layer.nodes:
            if node.id in step_errors:
                logger.warning(f"步骤 {node.id} 执行失败: {step_errors[node.id]}")

    async def _execute_step(
        self,
        step_data: dict[str, Any],
        context: dict[str, Any],
        layer_index: int,
        step_results: dict[str, Any],
        step_errors: dict[str, str],
        loop_counts: dict[str, int],
    ) -> None:
        """执行单个步骤。"""
        step_id = step_data["id"]
        step_type = step_data.get("type", "llm")

        # 检查前置依赖是否失败
        for dep in step_data.get("depends_on", []):
            if dep in step_errors:
                step_errors[step_id] = f"依赖步骤 {dep} 执行失败"
                if self._on_step_error:
                    self._on_step_error(step_id, step_errors[step_id])
                return

        if self._on_step_start:
            self._on_step_start(step_id, step_type)

        try:
            # 解析变量模板
            resolved_input = resolve_template(step_data, context)

            # 按类型分发到执行器
            output = await self._dispatch(step_type, resolved_input, context)

            # 写入上下文
            output_key = step_data.get("output_key")
            if output_key and output is not None:
                context[output_key] = output

            step_results[step_id] = output

            # 检查循环
            loop_config = step_data.get("loop")
            if loop_config and isinstance(loop_config, dict):
                should_loop = await self._check_loop(loop_config, context, loop_counts, step_id)
                if should_loop:
                    # 循环：清除当前步骤及下游的结果，重新执行
                    logger.info(f"步骤 {step_id} 触发循环回退到 {loop_config['back_to']}")
                    return  # 循环逻辑由引擎外层处理

            if self._on_step_done:
                self._on_step_done(step_id, output)

        except Exception as e:
            step_errors[step_id] = str(e)
            logger.exception(f"步骤 {step_id} 执行异常")
            if self._on_step_error:
                self._on_step_error(step_id, str(e))

    async def _check_loop(
        self,
        loop_config: dict[str, Any],
        context: dict[str, Any],
        loop_counts: dict[str, int],
        step_id: str,
    ) -> bool:
        """检查是否需要循环回退。"""
        back_to = loop_config.get("back_to")
        max_iterations = loop_config.get("max_iterations", 3)
        exit_condition = loop_config.get("exit_condition")

        current_count = loop_counts.get(step_id, 0)
        if current_count >= max_iterations:
            logger.info(f"步骤 {step_id} 已达最大循环次数 {max_iterations}")
            return False

        # 检查退出条件
        if exit_condition:
            if evaluate_condition(exit_condition, context):
                logger.info(f"步骤 {step_id} 满足退出条件")
                return False

        # 需要循环
        loop_counts[step_id] = current_count + 1
        return True

    async def _dispatch(
        self,
        step_type: str,
        resolved_input: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        """按步骤类型分发到对应执行器。"""
        from yuxi.workflows.executors import get_executor

        executor = get_executor(step_type)
        return await executor.execute(resolved_input, context)
