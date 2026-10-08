"""连接器响应只投影允许展示的元数据，不返回加密材料或凭据值。"""

from typing import Any


def connector_response(connector: Any, *, include_credentials: bool = False) -> dict[str, Any]:
    """管理响应只呈现配置与凭据键，不返回密文或秘密值。"""
    data: dict[str, Any] = {
        "id": connector.id,
        "slug": connector.slug,
        "name": connector.name,
        "connector_type": connector.connector_type,
        "description": connector.description,
        "config": connector.config or {},
        "enabled": connector.enabled,
        "revision": connector.revision,
        "read_scope": connector.read_scope,
        "write_scope": connector.write_scope,
        "created_by": connector.created_by,
        "updated_by": connector.updated_by,
        "created_at": str(connector.created_at) if connector.created_at else None,
        "updated_at": str(connector.updated_at) if connector.updated_at else None,
        "deleted_at": str(connector.deleted_at) if connector.deleted_at else None,
    }
    if include_credentials:
        data["credential_keys"] = [
            {"key": c.credential_key, "key_id": c.key_id, "updated_at": str(c.updated_at) if c.updated_at else None}
            for c in (connector.credentials or [])
        ]
    return data


def operation_response(op: Any, *, connector_type: str = "generic_rest") -> dict[str, Any]:
    """回填可编辑操作契约和当前版本。"""
    return {
        "id": op.id,
        "slug": op.slug,
        "provider_owned_fields": []
        if connector_type == "generic_rest"
        else ["http_method", "endpoint_template", "query_template", "body_template", "response_type"],
        "name": op.name,
        "operation_type": op.operation_type,
        "http_method": op.http_method,
        "endpoint_template": op.endpoint_template,
        "request_schema": op.request_schema,
        "response_type": op.response_type,
        "approval_policy": op.approval_policy,
        "description": op.description,
        "enabled": op.enabled,
        "revision": op.revision,
        "query_template": op.query_template,
        "body_template": op.body_template,
        "response_mapping": op.response_mapping,
        "retry_policy": op.retry_policy,
        "remote_idempotency": op.remote_idempotency,
        "created_at": str(op.created_at) if op.created_at else None,
        "updated_at": str(op.updated_at) if op.updated_at else None,
    }


def invocation_response(inv: Any) -> dict[str, Any]:
    """公开调用投影只读取有界摘要与当前持久状态。"""
    return {
        "invocation_id": inv.id,
        "status": inv.status,
        "connector_slug": inv.connector_slug,
        "operation_slug": inv.operation_slug,
        "operation_type": inv.operation_type,
        "actor_uid": inv.actor_uid,
        "consumer_type": inv.consumer_type,
        "logical_call_key": inv.logical_call_key,
        "request_digest": inv.request_digest,
        "connector_revision": inv.connector_revision,
        "operation_revision": inv.operation_revision,
        "approval_policy": inv.approval_policy,
        "approved_by": inv.approved_by,
        "approved_at": str(inv.approved_at) if inv.approved_at else None,
        "approval_expires_at": str(inv.approval_expires_at) if inv.approval_expires_at else None,
        "rejected_by": inv.rejected_by,
        "rejection_reason": inv.rejection_reason,
        "error_code": inv.error_code,
        "error_summary": inv.error_summary,
        "response_status": inv.response_status,
        "provider_request_id": inv.provider_request_id,
        "duration_ms": inv.duration_ms,
        "remote_outcome": inv.remote_outcome,
        "request_summary": inv.request_summary,
        "response_summary": inv.response_summary,
        "agent_slug": inv.agent_slug,
        "agent_request_id": inv.agent_request_id,
        "agent_run_id": inv.agent_run_id,
        "tool_call_id": inv.tool_call_id,
        "workflow_id": inv.workflow_id,
        "workflow_run_id": inv.workflow_run_id,
        "step_id": inv.step_id,
        "step_execution_id": inv.step_execution_id,
        "created_at": str(inv.created_at) if inv.created_at else None,
        "started_at": str(inv.started_at) if inv.started_at else None,
        "completed_at": str(inv.completed_at) if inv.completed_at else None,
    }
