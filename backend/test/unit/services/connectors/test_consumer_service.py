"""HTTP 消费用例在决定已提交之后才通知工作流 Owner。"""

from unittest.mock import AsyncMock
import pytest
from yuxi.services.connectors import consumer_service


@pytest.mark.parametrize("action", ["decide", "cancel", "reconcile"])
async def test_consumer_notification_follows_committed_decision_and_keeps_queue_failure_observable(monkeypatch, action):
    """通知失败保留已提交结果，由持久恢复扫描承担补投递。"""
    committed = []
    service = AsyncMock()

    async def persist(*args, **kwargs):
        """服务返回对应已经提交的决定。"""
        committed.append(action)
        return {"invocation_id": "owned", "workflow_run_id": 7, "status": "prepared"}

    getattr(service, action + "_invocation").side_effect = persist

    async def failed_delivery(run_id):
        """只有提交之后允许通知，失败不抹掉业务结果。"""
        assert committed == [action] and run_id == 7
        raise RuntimeError("synthetic queue unavailable")

    monkeypatch.setattr(consumer_service, "request_workflow_resume", failed_delivery)
    if action == "decide":
        result = await consumer_service.decide_consumer_invocation(
            service, "owned", "approve", actor="actor", expected_digest="digest"
        )
    elif action == "cancel":
        result = await consumer_service.cancel_consumer_invocation(service, "owned", actor="actor")
    else:
        result = await consumer_service.reconcile_consumer_invocation(
            service, "owned", "succeeded", actor="actor", reason="readback", result={}
        )
    assert result["invocation_id"] == "owned"
