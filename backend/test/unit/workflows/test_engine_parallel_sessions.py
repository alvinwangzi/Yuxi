"""工作流引擎并行步骤独立 session 的回归测试。

对应修复：_execute_layer 为同层每个并行步骤创建独立的 pg_manager.AsyncSession()，
主 db_session 仅由回调（已加锁）使用，避免并行步骤共享同一 async session
触发 SQLAlchemy "concurrent operations are not permitted" 冲突。
"""

import asyncio

import pytest

import yuxi.storage.postgres.manager as pg_manager_module
import yuxi.workflows.executors as executors_module
from yuxi.workflows.engine import WorkflowEngine, WorkflowExecutionError


class FakeAsyncSession:
    """模拟 SQLAlchemy async session 的单会话并发保护语义。"""

    def __init__(self, label: str):
        self.label = label
        self.closed = False
        self._in_use = 0

    async def run_query(self) -> None:
        """模拟一次数据库查询；同一 session 被并发使用时抛错（与 SQLAlchemy 行为一致）。"""
        if self._in_use > 0:
            raise RuntimeError("concurrent operations are not permitted")
        self._in_use += 1
        try:
            await asyncio.sleep(0.01)
        finally:
            self._in_use -= 1

    async def close(self) -> None:
        self.closed = True


class SessionUsingExecutor:
    """记录每个步骤收到的 db_session，并在其上执行一次查询。"""

    def __init__(self):
        self.received: list[tuple[str, FakeAsyncSession | None]] = []

    async def execute(self, step_data: dict, context: dict, *, db_session=None):
        self.received.append((step_data["id"], db_session))
        if db_session is not None:
            await db_session.run_query()
        return f"output-{step_data['id']}"


def _patch_pg_manager(monkeypatch, factory) -> None:
    """将 pg_manager.AsyncSession 替换为测试工厂（engine 内为延迟导入，patch 模块属性生效）。"""

    class _FakePgManager:
        AsyncSession = staticmethod(factory)

    monkeypatch.setattr(pg_manager_module, "pg_manager", _FakePgManager())


def _patch_executor(monkeypatch, executor) -> None:
    """将执行器分发替换为固定实例（engine._dispatch 内为延迟导入）。"""
    monkeypatch.setattr(executors_module, "get_executor", lambda step_type: executor)


# 两个无依赖步骤位于同一 DAG 层，即真实并行执行路径
_PARALLEL_DEFINITION = {
    "concurrency": 4,
    "steps": [
        {"id": "copy", "type": "tool", "name": "Copy", "output_key": "copy_result"},
        {"id": "title", "type": "tool", "name": "Title", "output_key": "title_result"},
    ],
}


class TestParallelSessionIsolation:
    """同层并行步骤的 session 隔离回归。"""

    async def test_parallel_steps_use_isolated_sessions(self, monkeypatch):
        """并行步骤各用独立 session，不触发并发冲突且结果正确。

        若回归为共享主 session：两个步骤并发 run_query 会触发模拟的
        SQLAlchemy 并发保护错误，且 session 隔离断言失败，测试因正确原因变红。
        """
        main_session = FakeAsyncSession("main")
        created: list[FakeAsyncSession] = []

        def factory() -> FakeAsyncSession:
            session = FakeAsyncSession(f"step-{len(created)}")
            created.append(session)
            return session

        executor = SessionUsingExecutor()
        _patch_pg_manager(monkeypatch, factory)
        _patch_executor(monkeypatch, executor)

        context = await WorkflowEngine().execute(
            _PARALLEL_DEFINITION, {"topic": "测试"}, db_session=main_session
        )

        # 并行执行结果正确
        assert context["copy_result"] == "output-copy"
        assert context["title_result"] == "output-title"

        # 每个步骤拿到的是独立新建的 session，而非主 session，且互不相同
        received_sessions = [s for _, s in executor.received]
        assert len(received_sessions) == 2
        assert len({id(s) for s in received_sessions}) == 2
        assert all(s is not main_session for s in received_sessions)
        assert {id(s) for s in received_sessions} == {id(s) for s in created}

        # 执行结束后每个 step session 已关闭，主 session 不受影响
        assert all(s.closed for s in created)
        assert not main_session.closed

    async def test_session_creation_failure_fails_steps_explicitly(self, monkeypatch):
        """session 创建失败时步骤显式失败，不静默成功。"""
        callback_errors: list[tuple[str, str]] = []

        async def on_step_error(step_id: str, error: str) -> None:
            callback_errors.append((step_id, error))

        def factory() -> FakeAsyncSession:
            raise RuntimeError("pg pool exhausted")

        _patch_pg_manager(monkeypatch, factory)
        _patch_executor(monkeypatch, SessionUsingExecutor())

        engine = WorkflowEngine(on_step_error=on_step_error)

        with pytest.raises(WorkflowExecutionError) as exc_info:
            await engine.execute(_PARALLEL_DEFINITION, {}, db_session=object())

        message = str(exc_info.value)
        # 两个并行步骤的失败都被记录，且错误原因可追溯到 session 创建失败
        assert "copy" in message and "title" in message
        assert "pg pool exhausted" in message
        assert len(callback_errors) == 2
