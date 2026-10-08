"""工作流业务变量不能充当连接器的服务端执行身份。"""

import pytest

from yuxi.workflows.executors.connector_executor import ConnectorStepExecutor


async def test_business_variables_cannot_supply_a_workflow_execution_identity():
    """没有受信任上下文时，伪造的特殊变量仍须被拒绝。"""
    with pytest.raises(ValueError, match="执行上下文"):
        await ConnectorStepExecutor().execute(
            {"id": "read", "connector_slug": "crm", "operation_slug": "read", "params": {}},
            {"__actor_uid__": "admin", "__workflow_run_id__": 42, "__step_execution_id__": "forged"},
        )
