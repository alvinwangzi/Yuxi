"""工作流调度器生成的受信任执行身份，与业务变量分离。"""

from dataclasses import dataclass, replace


class WorkflowPaused(RuntimeError):
    """工作流已在层边界保存等待状态，调度器应释放 worker。"""

    def __init__(self, state: dict):
        super().__init__("工作流等待外部决定或子运行")
        self.state = state


class WorkflowStepWaiting(RuntimeError):
    """步骤等待持久调用或子运行，不能当作普通输出。"""

    def __init__(self, status: str, binding: dict):
        super().__init__("步骤等待外部决定或子运行")
        self.status = status
        self.binding = binding


@dataclass(frozen=True)
class WorkflowExecutionContext:
    """绑定一次真实工作流运行及其步骤激活。"""

    actor_uid: str
    workflow_id: int
    workflow_run_id: int
    owner_id: str
    owner_attempt: str
    step_id: str | None = None
    step_execution_id: str | None = None

    def for_step(self, step_id: str, step_execution_id: str) -> "WorkflowExecutionContext":
        """从同一运行身份派生具体步骤，不从业务参数取身份。"""
        return replace(self, step_id=step_id, step_execution_id=step_execution_id)
