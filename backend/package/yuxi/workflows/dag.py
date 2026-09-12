"""DAG 构建与拓扑排序 — Kahn 算法分层，同层步骤可并行。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from yuxi.workflows import VALID_STEP_TYPES


class WorkflowDefinitionError(ValueError):
    """工作流定义校验失败。"""


class WorkflowCycleError(WorkflowDefinitionError):
    """工作流依赖关系存在环。"""


@dataclass
class DAGNode:
    """DAG 中的一个步骤节点。"""

    id: str
    step_type: str
    depends_on: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DAGLayer:
    """一个执行层级 — 同层步骤无相互依赖，可并行。"""

    index: int
    nodes: list[DAGNode] = field(default_factory=list)


def build_dag(definition: dict[str, Any]) -> list[DAGLayer]:
    """从工作流 definition 构建分层执行计划。

    1. 解析 steps，校验类型和依赖
    2. Kahn 算法拓扑排序
    3. 分层（同层无依赖可并行）
    4. 检测环 → 抛 WorkflowCycleError

    loop.back_to 不参与建边，DAG 保持无环。
    """
    steps = definition.get("steps", [])
    if not steps:
        raise WorkflowDefinitionError("工作流至少需要一个步骤")

    # 构建节点索引
    nodes: dict[str, DAGNode] = {}
    for step in steps:
        step_id = step.get("id")
        if not step_id:
            raise WorkflowDefinitionError("每个步骤必须有 id")
        if step_id in nodes:
            raise WorkflowDefinitionError(f"步骤 id 重复: {step_id}")

        step_type = step.get("type", "llm")
        if step_type not in VALID_STEP_TYPES:
            raise WorkflowDefinitionError(
                f"步骤 {step_id} 的类型 '{step_type}' 无效，"
                f"可选: {', '.join(sorted(VALID_STEP_TYPES))}"
            )

        depends_on = step.get("depends_on", [])
        if not isinstance(depends_on, list):
            raise WorkflowDefinitionError(f"步骤 {step_id} 的 depends_on 必须是数组")

        nodes[step_id] = DAGNode(
            id=step_id,
            step_type=step_type,
            depends_on=list(depends_on),
            data=step,
        )

    # 校验依赖引用存在
    for node in nodes.values():
        for dep in node.depends_on:
            if dep not in nodes:
                raise WorkflowDefinitionError(
                    f"步骤 {node.id} 依赖的 {dep} 不存在"
                )

    # Kahn 算法拓扑排序 + 分层
    in_degree: dict[str, int] = {nid: 0 for nid in nodes}
    children: dict[str, list[str]] = {nid: [] for nid in nodes}

    for node in nodes.values():
        for dep in node.depends_on:
            children[dep].append(node.id)
            in_degree[node.id] += 1

    # 初始层：入度为 0 的节点
    queue: deque[str] = deque()
    for nid, deg in in_degree.items():
        if deg == 0:
            queue.append(nid)

    layers: list[DAGLayer] = []
    processed = 0

    while queue:
        layer = DAGLayer(index=len(layers))
        next_queue: deque[str] = deque()

        # 当前队列中所有节点属于同一层
        while queue:
            nid = queue.popleft()
            layer.nodes.append(nodes[nid])
            processed += 1

            for child_id in children[nid]:
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    next_queue.append(child_id)

        layers.append(layer)
        queue = next_queue

    if processed < len(nodes):
        # 找出环中的节点
        remaining = [nid for nid, deg in in_degree.items() if deg > 0]
        raise WorkflowCycleError(
            f"工作流依赖关系存在环，涉及步骤: {', '.join(remaining)}"
        )

    return layers


def validate_definition(definition: dict[str, Any]) -> list[str]:
    """校验工作流定义，返回错误列表（空列表表示通过）。"""
    errors: list[str] = []

    steps = definition.get("steps")
    if not steps or not isinstance(steps, list):
        errors.append("definition.steps 必须是非空数组")
        return errors

    step_ids: set[str] = set()
    seen_boundary_types: set[str] = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"steps[{i}] 必须是对象")
            continue

        sid = step.get("id", "")
        if not sid:
            errors.append(f"steps[{i}] 缺少 id")
        elif sid in step_ids:
            errors.append(f"步骤 id 重复: {sid}")
        step_ids.add(sid)

        stype = step.get("type", "llm")
        if stype not in VALID_STEP_TYPES:
            errors.append(f"步骤 {sid or i} 的类型 '{stype}' 无效")

        # start/end 是流程边界锚点：最多一个，且 start 不依赖任何步骤
        if stype == "start":
            if step.get("depends_on"):
                errors.append(f"start 步骤 {sid} 不能有 depends_on")
            if "start" in seen_boundary_types:
                errors.append("start 类型步骤最多一个")
            seen_boundary_types.add("start")
        if stype == "end":
            if "end" in seen_boundary_types:
                errors.append("end 类型步骤最多一个")
            seen_boundary_types.add("end")

        # 校验 loop.back_to 引用
        loop = step.get("loop")
        if loop and isinstance(loop, dict):
            back_to = loop.get("back_to")
            if back_to and back_to not in {s.get("id") for s in steps}:
                errors.append(f"步骤 {sid} 的 loop.back_to '{back_to}' 不存在")

    # 校验依赖引用
    for step in steps:
        if not isinstance(step, dict):
            continue
        sid = step.get("id", "")
        for dep in step.get("depends_on", []):
            if dep not in step_ids:
                errors.append(f"步骤 {sid} 依赖的 '{dep}' 不存在")

    # 尝试构建 DAG（检测环）
    if not errors:
        try:
            build_dag(definition)
        except WorkflowCycleError as e:
            errors.append(str(e))
        except WorkflowDefinitionError as e:
            errors.append(str(e))

    return errors
