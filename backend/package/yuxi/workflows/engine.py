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
        *,
        db_session=None,
    ) -> dict[str, Any]:
        """执行工作流，返回最终的 context。

        Args:
            definition: 工作流定义（含 steps、concurrency 等）
            input_variables: 用户输入的变量
            db_session: 数据库会话（LLM Agent 模式需要）

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

        # 当前执行起始层索引（支持循环回退）
        start_layer_idx = 0

        while start_layer_idx < len(layers):
            await self._execute_layer(
                layer=layers[start_layer_idx],
                step_index=step_index,
                context=context,
                concurrency=concurrency,
                step_results=step_results,
                step_errors=step_errors,
                loop_counts=loop_counts,
                db_session=db_session,
            )
            # 当前层有步骤失败，立即停止后续层
            if step_errors:
                break

            # 检查是否有步骤触发了循环回退
            loop_back_to = None
            for node in layers[start_layer_idx].nodes:
                step_data = step_index[node.id]
                loop_config = step_data.get("loop")
                if loop_config and isinstance(loop_config, dict):
                    back_to = loop_config.get("back_to")
                    if back_to and back_to in step_index:
                        should_loop = await self._check_loop(
                            loop_config, context, loop_counts, node.id
                        )
                        if should_loop:
                            loop_back_to = back_to
                            logger.info(f"步骤 {node.id} 触发循环回退到 {back_to}")
                            break

            if loop_back_to:
                # 找到回退目标所在的层
                target_layer_idx = None
                for i, layer in enumerate(layers):
                    if any(n.id == loop_back_to for n in layer.nodes):
                        target_layer_idx = i
                        break

                if target_layer_idx is not None and target_layer_idx <= start_layer_idx:
                    # 清除从目标层开始的所有步骤结果
                    for i in range(target_layer_idx, len(layers)):
                        for node in layers[i].nodes:
                            sid = node.id
                            if sid in step_results:
                                del step_results[sid]
                            if sid in step_errors:
                                del step_errors[sid]
                    # 回退到目标层重新执行
                    start_layer_idx = target_layer_idx
                    continue
                else:
                    # 无法回退（目标层不存在或在当前层之后），继续正常执行
                    pass

            # 正常推进到下一层
            start_layer_idx += 1

        # 标记未执行的步骤为 skipped（因上游失败）
        for step in definition.get("steps", []):
            sid = step["id"]
            if sid not in step_results and sid not in step_errors:
                # 找出具体哪个依赖步骤失败了
                failed_deps = [dep for dep in step.get("depends_on", []) if dep in step_errors]
                if failed_deps:
                    step_errors[sid] = f"上游步骤 {', '.join(failed_deps)} 执行失败，跳过执行"
                else:
                    # 没有失败的依赖，但步骤仍未执行（可能是所在层未执行）
                    step_errors[sid] = "步骤未执行（所在执行层未运行）"
                    logger.warning(f"步骤 {sid} 未执行，且无失败的依赖步骤，可能是所在执行层未运行")
                if self._on_step_error:
                    await self._on_step_error(sid, step_errors[sid])

        # 有步骤失败时抛出异常，由 run_worker 标记 workflow 为 failed
        if step_errors:
            failed_steps = "; ".join(f"{sid}: {err}" for sid, err in step_errors.items())
            raise WorkflowExecutionError(f"工作流执行失败: {failed_steps}")

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
        db_session=None,
    ) -> None:
        """执行一个 DAG 层级 — 同层步骤并行。"""
        if not layer.nodes:
            return

        logger.info(f"开始执行第 {layer.index} 层，共 {len(layer.nodes)} 个步骤: {[n.id for n in layer.nodes]}")

        semaphore = asyncio.Semaphore(concurrency)

        async def _run_step(node):
            try:
                async with semaphore:
                    await self._execute_step(
                        step_data=step_index[node.id],
                        context=context,
                        layer_index=layer.index,
                        step_results=step_results,
                        step_errors=step_errors,
                        loop_counts=loop_counts,
                        db_session=db_session,
                    )
            except Exception as e:
                # 捕获任务级别的异常，确保不影响同层其他步骤
                if node.id not in step_errors:
                    step_errors[node.id] = f"任务执行异常: {str(e)}"
                    logger.exception(f"步骤 {node.id} 任务级别异常")
                if self._on_step_error:
                    try:
                        await self._on_step_error(node.id, str(e))
                    except Exception:
                        pass

        tasks = [asyncio.create_task(_run_step(node)) for node in layer.nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 检查 gather 返回的异常（任务创建失败等）
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                node_id = layer.nodes[i].id
                if node_id not in step_errors:
                    step_errors[node_id] = f"任务异常: {str(result)}"
                    logger.error(f"步骤 {node_id} 任务返回异常: {result}")

        # 检查是否有步骤未执行（既无结果也无错误）
        for node in layer.nodes:
            if node.id not in step_results and node.id not in step_errors:
                step_errors[node.id] = "步骤未执行（任务未启动）"
                logger.warning(f"步骤 {node.id} 在第 {layer.index} 层未执行，可能是任务调度失败")
                if self._on_step_error:
                    try:
                        await self._on_step_error(node.id, step_errors[node.id])
                    except Exception:
                        pass

        # 记录层执行结果
        completed = [n.id for n in layer.nodes if n.id in step_results]
        failed = [n.id for n in layer.nodes if n.id in step_errors]
        logger.info(f"第 {layer.index} 层执行完成: 成功={completed}, 失败={failed}")

    async def _execute_step(
        self,
        step_data: dict[str, Any],
        context: dict[str, Any],
        layer_index: int,
        step_results: dict[str, Any],
        step_errors: dict[str, str],
        loop_counts: dict[str, int],
        db_session=None,
    ) -> None:
        """执行单个步骤。"""
        step_id = step_data["id"]
        step_type = step_data.get("type", "llm")

        # 检查前置依赖是否失败
        for dep in step_data.get("depends_on", []):
            if dep in step_errors:
                step_errors[step_id] = f"依赖步骤 {dep} 执行失败"
                logger.warning(f"步骤 {step_id} 跳过执行：依赖步骤 {dep} 失败 ({step_errors[dep]})")
                if self._on_step_error:
                    await self._on_step_error(step_id, step_errors[step_id])
                return

        if self._on_step_start:
            await self._on_step_start(step_id, step_type)

        try:
            # 解析变量模板
            resolved_input = resolve_template(step_data, context)

            # 按类型分发到执行器
            output = await self._dispatch(step_type, resolved_input, context, db_session=db_session)

            # 写入上下文
            output_key = step_data.get("output_key")
            if output_key and output is not None:
                context[output_key] = output

            step_results[step_id] = output

            if self._on_step_done:
                await self._on_step_done(step_id, output)

        except Exception as e:
            step_errors[step_id] = str(e)
            logger.exception(f"步骤 {step_id} 执行异常")
            if self._on_step_error:
                await self._on_step_error(step_id, str(e))

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
        *,
        db_session=None,
    ) -> Any:
        """按步骤类型分发到对应执行器。"""
        from yuxi.workflows.executors import get_executor

        executor = get_executor(step_type)
        return await executor.execute(resolved_input, context, db_session=db_session)
