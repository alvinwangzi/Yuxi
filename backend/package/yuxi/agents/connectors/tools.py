"""连接器动态 LangChain Tool 生成 — Agent 消费路径。

根据 context.connectors（已解析的 connector slug 列表）为每个可见操作
生成一个 StructuredTool。Tool 名采用 cn_<connector_slug>__<operation_slug>
命名空间；args_schema 来自 operation.request_schema；闭包只绑定不可变的
connector/operation 标识，执行时从 runtime 获取 uid/run_id/request_id。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import create_model

from yuxi.utils import logger

_MAX_SLUG_LEN = 40

_JSON_SCHEMA_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _sanitize_slug(slug: str, max_len: int = _MAX_SLUG_LEN) -> str:
    return slug.replace("-", "_").replace(".", "_")[:max_len]


def _build_args_schema(request_schema: dict | None) -> type:
    """从 operation 的 JSON Schema 动态构建 Pydantic model。"""
    if not request_schema:
        return create_model("ConnectorParamsEmpty")

    properties = request_schema.get("properties", {})
    required_fields = set(request_schema.get("required", []))
    field_definitions: dict[str, Any] = {}

    for name, prop in properties.items():
        json_type = prop.get("type", "string")
        python_type = _JSON_SCHEMA_TYPE_MAP.get(json_type, Any)
        description = prop.get("description", "")
        if name in required_fields:
            field_definitions[name] = (python_type, ...)
        else:
            field_definitions[name] = (python_type | None, None)

    return create_model("ConnectorParams", **field_definitions)


def _format_tool_result(result: dict) -> str:
    output: dict[str, Any] = {"invocation_id": result.get("invocation_id")}
    if result.get("mapped_result"):
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
        try:
            connector_meta = await service.get_connector_metadata(connector_slug, uid=uid)
        except Exception as exc:
            logger.warning(f"连接器 '{connector_slug}' 加载失败: {exc}")
            continue

        if connector_meta is None:
            logger.warning(f"连接器 '{connector_slug}' 不存在或已停用")
            continue

        operations = connector_meta.get("operations", [])
        for op in operations:
            tool = _build_single_tool(service, connector_slug, op, context)
            tools.append(tool)

    return tools


def _build_single_tool(
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
        tool_call_id: str = "",
        **params: Any,
    ) -> str:
        runtime_ctx = getattr(runtime, "context", None)
        uid = str(getattr(runtime_ctx, "uid", "") or "")
        run_id = str(getattr(runtime_ctx, "run_id", "") or "")
        request_id = str(getattr(runtime_ctx, "request_id", "") or "")

        from yuxi.services.connectors.base import ConnectorExecution
        from yuxi.services.connectors.service import (
            ConnectorApprovalRequired,
            ConnectorServiceError,
        )

        execution = ConnectorExecution(
            invocation_id=str(uuid.uuid4()),
            actor_uid=uid,
            consumer_type="agent",
            logical_call_key=f"agent:{request_id}:{tool_call_id or uuid.uuid4()}",
            connector_revision=bound_connector_revision,
            operation_revision=bound_operation_revision,
            agent_slug=None,
            agent_request_id=request_id,
            agent_run_id=run_id,
            tool_call_id=tool_call_id,
        )

        try:
            result = await service.prepare_and_execute(
                bound_connector_slug,
                bound_operation_slug,
                params,
                execution=execution,
            )
            return _format_tool_result(result)
        except ConnectorApprovalRequired as exc:
            return json.dumps({
                "invocation_id": exc.invocation_id,
                "status": "awaiting_approval",
                "message": "写操作需要审批，已提交审批请求。",
            }, ensure_ascii=False)
        except ConnectorServiceError as exc:
            return json.dumps({
                "error": True, "error_code": exc.code, "error_message": str(exc),
            }, ensure_ascii=False)
        except Exception as exc:
            logger.warning(f"连接器工具执行异常: {exc}")
            return json.dumps({
                "error": True, "error_code": "execution_error",
                "error_message": str(exc)[:500],
            }, ensure_ascii=False)

    op_type_label = "写入" if operation_type == "write" else "查询"
    description = f"{operation_name}（{http_method} {op_type_label}操作）"

    safe_conn = _sanitize_slug(bound_connector_slug)
    safe_op = _sanitize_slug(bound_operation_slug)
    tool_name = f"cn_{safe_conn}__{safe_op}"

    return StructuredTool.from_function(
        name=tool_name,
        description=description,
        coroutine=_tool_func,
        args_schema=args_schema,
    )
