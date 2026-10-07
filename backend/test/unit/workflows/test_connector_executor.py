"""连接器步骤执行器单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from yuxi.workflows.executors.connector_executor import ConnectorStepExecutor


class TestConnectorStepExecutor:
    """ConnectorStepExecutor 测试。"""

    @pytest.fixture
    def executor(self):
        return ConnectorStepExecutor()

    async def test_missing_connector_slug_raises(self, executor):
        """缺少 connector_slug 抛异常。"""
        with pytest.raises(ValueError, match="connector_slug"):
            await executor.execute(
                {"operation_slug": "query"},
                {},
            )

    async def test_missing_operation_slug_raises(self, executor):
        """缺少 operation_slug 抛异常。"""
        with pytest.raises(ValueError, match="operation_slug"):
            await executor.execute(
                {"connector_slug": "salesforce"},
                {},
            )

    async def test_params_must_be_dict(self, executor):
        """params 非 dict 抛异常。"""
        with pytest.raises(ValueError, match="params"):
            await executor.execute(
                {
                    "connector_slug": "salesforce",
                    "operation_slug": "query_customer",
                    "params": "not_a_dict",
                },
                {},
            )

    async def test_successful_read_execution(self, executor):
        """读操作成功执行返回结果。"""
        mock_result = {
            "invocation_id": "inv-123",
            "success": True,
            "mapped_result": {"accounts": [{"id": "001", "name": "Acme"}]},
            "remote_outcome": "success",
        }

        with patch(
            "yuxi.services.connectors.factory.get_connector_service"
        ) as mock_factory:
            mock_service = AsyncMock()
            mock_service.prepare_and_execute = AsyncMock(return_value=mock_result)
            mock_factory.return_value = mock_service

            result = await executor.execute(
                {
                    "id": "crm_query",
                    "connector_slug": "salesforce",
                    "operation_slug": "query_customer",
                    "params": {"name": "Acme"},
                },
                {
                    "__workflow_id__": 1,
                    "__workflow_run_id__": 42,
                    "__actor_uid__": "user-abc",
                },
            )

        assert result["success"] is True
        assert result["invocation_id"] == "inv-123"
        assert result["result"] == {"accounts": [{"id": "001", "name": "Acme"}]}
        mock_service.prepare_and_execute.assert_called_once()

    async def test_approval_required_returns_waiting(self, executor):
        """写操作需审批时返回 waiting_approval。"""
        from yuxi.services.connectors.service import ConnectorApprovalRequired

        with patch(
            "yuxi.services.connectors.factory.get_connector_service"
        ) as mock_factory:
            mock_service = AsyncMock()
            mock_service.prepare_and_execute = AsyncMock(
                side_effect=ConnectorApprovalRequired(
                    invocation_id="inv-456",
                    digest="abc123",
                    expires_at=None,
                )
            )
            mock_factory.return_value = mock_service

            result = await executor.execute(
                {
                    "id": "crm_update",
                    "connector_slug": "salesforce",
                    "operation_slug": "update_opportunity",
                    "params": {"id": "001", "stage": "Closed Won"},
                },
                {
                    "__workflow_id__": 1,
                    "__workflow_run_id__": 42,
                    "__actor_uid__": "user-abc",
                },
            )

        assert result["status"] == "waiting_approval"
        assert result["invocation_id"] == "inv-456"
        assert result["step_id"] == "crm_update"

    async def test_service_error_raises_runtime_error(self, executor):
        """服务错误转为 RuntimeError。"""
        from yuxi.services.connectors.service import ConnectorServiceError

        with patch(
            "yuxi.services.connectors.factory.get_connector_service"
        ) as mock_factory:
            mock_service = AsyncMock()
            mock_service.prepare_and_execute = AsyncMock(
                side_effect=ConnectorServiceError("连接器不存在", code="not_found")
            )
            mock_factory.return_value = mock_service

            with pytest.raises(RuntimeError, match="连接器调用失败"):
                await executor.execute(
                    {
                        "id": "crm_query",
                        "connector_slug": "nonexistent",
                        "operation_slug": "query",
                        "params": {},
                    },
                    {},
                )

    async def test_execution_context_built_correctly(self, executor):
        """验证 ConnectorExecution 上下文正确构建。"""
        mock_result = {
            "invocation_id": "inv-789",
            "success": True,
            "data": {"ok": True},
        }

        with patch(
            "yuxi.services.connectors.factory.get_connector_service"
        ) as mock_factory:
            mock_service = AsyncMock()
            mock_service.prepare_and_execute = AsyncMock(return_value=mock_result)
            mock_factory.return_value = mock_service

            await executor.execute(
                {
                    "id": "step_1",
                    "connector_slug": "my_crm",
                    "operation_slug": "get_customer",
                    "params": {"id": "123"},
                },
                {
                    "__workflow_id__": 5,
                    "__workflow_run_id__": 99,
                    "__actor_uid__": "user-xyz",
                    "__step_execution_id__": "exec-abc",
                },
            )

        call_kwargs = mock_service.prepare_and_execute.call_args
        execution = call_kwargs.kwargs["execution"]
        assert execution.consumer_type == "workflow"
        assert execution.actor_uid == "user-xyz"
        assert execution.workflow_id == 5
        assert execution.workflow_run_id == 99
        assert execution.step_id == "step_1"
        assert execution.step_execution_id == "exec-abc"
        assert "workflow:99:step_1:exec-abc" in execution.logical_call_key
