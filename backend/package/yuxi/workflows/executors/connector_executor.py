"""连接器步骤执行器 — 通过 ConnectorService 调用第三方业务系统操作。"""

from __future__ import annotations

import uuid
from typing import Any

from yuxi.utils.logging_config import logger
from yuxi.workflows.executors import BaseStepExecutor
from yuxi.workflows.context import WorkflowExecutionContext, WorkflowStepWaiting


class ConnectorStepExecutor(BaseStepExecutor):
    """工作流连接器步骤 — 调用已配置的第三方业务系统操作。

    step_data 字段：
    - connector_slug: 连接器标识
    - operation_slug: 操作标识
    - params: 业务参数（已模板替换）
    - output_key: 输出到 context 的 key

    写操作需要审批时发出专用等待控制信号，由引擎层持久化后暂停；
    审批通过后引擎从 pending_connector_invocation_id 恢复继续执行。
    """

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any], **kwargs) -> Any:
        connector_slug = step_data.get("connector_slug")
        operation_slug = step_data.get("operation_slug")
        if not connector_slug or not operation_slug:
            raise ValueError("connector 步骤必须指定 connector_slug 和 operation_slug")

        params = step_data.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError(f"connector 步骤 params 必须是对象，当前为 {type(params).__name__}")

        execution_context = kwargs.get("execution_context")
        if (
            not isinstance(execution_context, WorkflowExecutionContext)
            or not execution_context.actor_uid
            or not execution_context.step_execution_id
            or execution_context.step_id != step_data.get("id")
        ):
            raise ValueError("connector 步骤缺少可信执行上下文")
        workflow_id = execution_context.workflow_id
        workflow_run_id = execution_context.workflow_run_id
        step_id = execution_context.step_id
        step_execution_id = execution_context.step_execution_id
        actor_uid = execution_context.actor_uid

        from yuxi.services.connectors.base import ConnectorExecution
        from yuxi.services.connectors.factory import get_connector_service

        service = get_connector_service()

        execution = ConnectorExecution(
            invocation_id=str(uuid.uuid4()),
            actor_uid=actor_uid,
            consumer_type="workflow",
            logical_call_key=f"workflow:{workflow_run_id}:{step_id}:{step_execution_id}",
            connector_revision=0,
            operation_revision=0,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            step_id=step_id,
            step_execution_id=step_execution_id,
            workflow_owner_attempt=execution_context.owner_attempt,
        )

        logger.info(f"连接器步骤 {step_id}: {connector_slug}/{operation_slug}")

        from yuxi.services.connectors.service import ConnectorApprovalRequired, ConnectorServiceError

        try:
            result = await service.prepare_and_execute(
                connector_slug, operation_slug, params, execution=execution,
            )
        except ConnectorApprovalRequired as exc:
            raise WorkflowStepWaiting(
                "waiting_approval",
                {
                    "invocation_id": exc.invocation_id,
                    "digest": exc.digest,
                    "connector_slug": connector_slug,
                    "operation_slug": operation_slug,
                },
            ) from None
        except ConnectorServiceError as exc:
            raise RuntimeError(f"连接器调用失败 [{exc.code}]: {exc}") from exc

        if result.get("remote_outcome") == "unknown":
            raise WorkflowStepWaiting(
                "waiting_approval",
                {
                    "kind": "reconciliation",
                    "invocation_id": result["invocation_id"],
                    "connector_slug": connector_slug,
                    "operation_slug": operation_slug,
                },
            )

        if not result.get("success") and result.get("error_code"):
            raise RuntimeError(
                f"连接器调用失败 [{result['error_code']}]: {result.get('error_message', '未知错误')}"
            )

        output: dict[str, Any] = {
            "invocation_id": result.get("invocation_id"),
            "success": result.get("success", True),
        }
        if result.get("mapped_result") is not None:
            output["result"] = result["mapped_result"]
        elif result.get("data") is not None:
            output["result"] = result["data"]
        if result.get("remote_outcome"):
            output["remote_outcome"] = result["remote_outcome"]

        return output
