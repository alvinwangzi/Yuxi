"""连接器动态 LangChain Tool 生成 — Agent 消费路径。

根据 context.connectors（已解析的 connector slug 列表）为每个可见操作
生成一个 StructuredTool。Tool 名采用 cn_<connector_slug>__<operation_slug>
命名空间；args_schema 来自 operation.request_schema；闭包只绑定不可变的
connector/operation 标识，执行时从 runtime 获取 uid/run_id/request_id。
"""

from __future__ import annotations

import json
import copy
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import interrupt


async def get_connector_tools(context: Any) -> list[StructuredTool]:
    """根据 context.connectors 为每个可见操作生成 LangChain StructuredTool。

    context.connectors 是已解析的 connector slug 列表（由
    prepare_agent_runtime_context 按用户权限过滤后赋值）。
    生成阶段不解密凭据；执行时通过 ConnectorService 的短事务获取。
    """
    connector_slugs: list[str] = list(getattr(context, "connectors", None) or [])
    if not connector_slugs:
        return []

    from yuxi.services.connectors.factory import get_connector_service

    service = get_connector_service()
    tools: list[StructuredTool] = []
    uid = str(getattr(context, "uid", "") or "")

    for connector_slug in connector_slugs:
        connector_meta = await service.get_connector_metadata(connector_slug, uid=uid)

        if connector_meta is None:
            raise ValueError("configured_connector_unavailable")

        operations = connector_meta.get("operations", [])
        for op in operations:
            if (
                getattr(context, "is_subagent_runtime", False)
                and op.get("operation_type") == "write"
                and op.get("approval_policy", "required") == "required"
            ):
                continue
            tool = build_connector_operation_tool(service, connector_slug, op, context)
            tools.append(tool)

    return tools


def build_connector_operation_tool(
    service: Any,
    connector_slug: str,
    op: dict[str, Any],
    context: Any,
) -> StructuredTool:
    """为单个操作构建 StructuredTool；闭包绑定不可变标识。"""
    operation_slug: str = op["slug"]
    operation_name: str = op.get("name", operation_slug)
    operation_type: str = op.get("operation_type", "read")
    http_method: str = op.get("http_method", "GET")
    request_schema: dict | None = op.get("request_schema")
    connector_revision: int = op.get("connector_revision", 0)
    operation_revision: int = op.get("operation_revision", 0)

    args_schema = _build_args_schema(request_schema)

    bound_connector_slug = connector_slug
    bound_operation_slug = operation_slug
    bound_connector_revision = connector_revision
    bound_operation_revision = operation_revision

    async def _tool_func(
        runtime: ToolRuntime,
        **params: Any,
    ) -> str:
        runtime_ctx = getattr(runtime, "context", None)
        if (
            getattr(runtime_ctx, "is_subagent_runtime", False)
            and operation_type == "write"
            and op.get("approval_policy", "required") == "required"
        ):
            raise ValueError("subagent_connector_approval_unavailable")
        uid = str(getattr(runtime_ctx, "uid", "") or "")
        run_id = str(getattr(runtime_ctx, "run_id", "") or "")
        request_id = str(getattr(runtime_ctx, "request_id", "") or "")
        tool_call_id = runtime.tool_call_id
        if not uid or not run_id or not request_id or not tool_call_id:
            raise ValueError("connector_runtime_identity_required")

        from yuxi.services.connectors.service import (
            ConnectorApprovalRequired,
            ConnectorServiceError,
        )

        execution = await service.resolve_agent_execution(
            actor_uid=uid,
            current_run_id=run_id,
            request_id=request_id,
            tool_call_id=tool_call_id,
            connector_revision=bound_connector_revision,
            operation_revision=bound_operation_revision,
        )

        try:
            result = await service.prepare_and_execute(
                bound_connector_slug,
                bound_operation_slug,
                params,
                execution=execution,
            )
        except ConnectorApprovalRequired as exc:
            interrupt(
                {
                    "type": "connector_approval",
                    "invocation_id": exc.invocation_id,
                    "digest": exc.digest,
                    "status": "awaiting_approval",
                    "message": "写操作需要审批，已提交审批请求。",
                    "request_summary": exc.summary,
                }
            )
            result = await service.prepare_and_execute(
                bound_connector_slug,
                bound_operation_slug,
                params,
                execution=execution,
            )
        except ConnectorServiceError as exc:
            return json.dumps(
                {
                    "error": True,
                    "error_code": exc.code,
                    "error_message": str(exc),
                },
                ensure_ascii=False,
            )
        while result.get("remote_outcome") == "unknown" and operation_type == "write":
            invocation = await service.get_user_invocation(result["invocation_id"], actor=uid)
            interrupt(
                {
                    "type": "connector_approval",
                    "invocation_id": result["invocation_id"],
                    "digest": invocation["request_digest"],
                    "status": "unknown",
                    "message": "远端写入结果未知，需要人工核对后恢复。",
                    "request_summary": invocation["request_summary"],
                }
            )
            result = await service.prepare_and_execute(
                bound_connector_slug, bound_operation_slug, params, execution=execution
            )
        return format_connector_tool_result(result)

    op_type_label = "写入" if operation_type == "write" else "查询"
    description = f"{operation_name}（{http_method} {op_type_label}操作）"

    from yuxi.services.connectors.schemas import validate_operation_namespace

    tool_name = validate_operation_namespace(bound_connector_slug, bound_operation_slug)

    return StructuredTool.from_function(
        name=tool_name,
        description=description,
        coroutine=_tool_func,
        args_schema=args_schema,
    )


def format_connector_tool_result(result: dict) -> str:
    """将绑定调用结果转换为稳定工具 JSON，不交付私有 provider evidence。"""
    output: dict[str, Any] = {"invocation_id": result.get("invocation_id")}
    if result.get("mapped_result") is not None:
        output["result"] = result["mapped_result"]
    elif result.get("data") is not None:
        output["result"] = result["data"]
    if result.get("error_code"):
        output["error_code"] = result["error_code"]
    if result.get("error_message"):
        output["error_message"] = result["error_message"]
    if result.get("remote_outcome"):
        output["remote_outcome"] = result["remote_outcome"]
    return json.dumps(output, ensure_ascii=False, default=str)


def _build_args_schema(request_schema: dict | None) -> dict:
    """保留完整约束和原始类型；runtime 由 ToolNode 独立注入。"""
    if request_schema and "runtime" in request_schema.get("properties", {}):
        raise ValueError("runtime 是受信任工具注入的保留参数")
    return copy.deepcopy(request_schema or {"type": "object", "properties": {}})
