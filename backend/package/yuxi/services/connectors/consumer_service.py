"""连接器决定提交后通知拥有该调用的工作流，失败由持久恢复扫描补投递。"""

from yuxi.services.workflow_service import request_workflow_resume
from yuxi.utils.logging_config import logger


async def decide_consumer_invocation(service, invocation_id, decision, *, actor, expected_digest):
    """先提交审批决定，再通知工作流 Owner。"""
    result = await service.decide_invocation(invocation_id, decision, actor=actor, expected_digest=expected_digest)
    await _resume_workflow(result)
    return result


async def cancel_consumer_invocation(service, invocation_id, *, actor):
    """先提交本地取消事实，再请求工作流收敛。"""
    result = await service.cancel_invocation(invocation_id, actor=actor)
    await _resume_workflow(result)
    return result


async def reconcile_consumer_invocation(service, invocation_id, resolution, *, actor, reason, result):
    """核对结果提交后恢复原工作流，不重发第三方请求。"""
    summary = await service.reconcile_invocation(invocation_id, resolution, actor=actor, reason=reason, result=result)
    await _resume_workflow(summary)
    return summary


async def _resume_workflow(result):
    """补投递错误不能抹掉已提交决定，恢复扫描拥有后续拒绝后果。"""
    if not result.get("workflow_run_id"):
        return
    try:
        await request_workflow_resume(result["workflow_run_id"])
    except Exception as exc:
        logger.warning(f"连接器决定已提交，工作流等待恢复扫描: type={type(exc).__name__}")
