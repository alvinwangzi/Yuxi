"""共用服务在真实 PostgreSQL 上的授权、提交与调用契约。"""

import os
import asyncio
import json
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import text

from yuxi.repositories.connector_repository import ConnectorRepository
from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
from yuxi.services.connectors.base import ConnectorExecution
from yuxi.services.connectors.credential_vault import CredentialVault
from yuxi.services.connectors.factory import ConnectorServiceFactory
from yuxi.services.connectors.service import (
    ConnectorApprovalRequired,
    ConnectorAuthorizationError,
    ConnectorConflictError,
)
from yuxi.storage.postgres.manager import PostgresManager
from yuxi.storage.postgres.models_business import Department, User

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """本模块仅操作独立 Schema，不绑定共享 API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """本模块不创建或清理共享知识库。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """本模块不创建或清理共享沙盒。"""
    yield


@pytest.fixture
def fernet_key():
    """测试自身拥有的密钥，用于独立验证轮换后的密文。"""
    return Fernet(Fernet.generate_key())


@pytest.fixture
def vault(fernet_key):
    """只供本次隔离测试使用的内存密钥。"""
    return CredentialVault(current_key=fernet_key, current_key_id="test-only")


@pytest.fixture
def vault_configuration(vault):
    """模拟真实配置在两个短事务之间切换当前写密钥。"""
    return {"current": vault}


@pytest.fixture
async def service_scope(vault_configuration):
    """使用真实短事务与任务所属 Schema，测试后只清理该 Schema。"""
    url = os.environ.get("POSTGRES_URL")
    if not url:
        pytest.skip("POSTGRES_URL 未配置")
    schema = f"pytest_connector_service_{uuid.uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema, "application_name": schema}}
    )
    try:
        manager = object.__new__(PostgresManager)
        PostgresManager.__init__(manager)
        manager.async_engine = engine
        manager.AsyncSession = async_sessionmaker(engine, expire_on_commit=False)
        manager._initialized = True
        await manager.create_business_tables()
        async with manager.get_async_session_context() as db:
            db.add(User(uid="actor", username="service-test-actor", password_hash="non-login-test-user", role="admin"))
            repo = ConnectorRepository(db)
            connector = await repo.create(
                slug="service-test",
                name="service test",
                connector_type="generic_rest",
                config={"base_url": "https://example.com"},
                created_by="actor",
                read_scope={"access_level": "global"},
                write_scope={"access_level": "deny"},
            )
            await repo.create_operation(
                connector_id=connector.id,
                slug="read",
                name="read",
                operation_type="read",
                http_method="GET",
                endpoint_template="/read",
                request_schema={"type": "object"},
            )
        service = ConnectorServiceFactory(
            session_context_factory=manager.get_async_session_context,
            vault_provider=lambda: vault_configuration["current"],
        ).create_service()
        yield service, manager
    finally:
        await engine.dispose()
        async with admin.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


def execution(key: str = "logical-read", actor: str = "actor") -> ConnectorExecution:
    """提供测试用服务端调用身份。"""
    return ConnectorExecution(
        invocation_id=str(uuid.uuid4()),
        actor_uid=actor,
        consumer_type="admin_test",
        logical_call_key=key,
        connector_revision=1,
        operation_revision=1,
    )


async def test_management_test_consumer_cannot_be_used_by_ordinary_user(service_scope):
    """管理测试入口的类型标签不能替代实际管理员权限。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        user = await ConnectorRepository(db).get_active_actor("actor")
        user.role = "user"
    with pytest.raises(ConnectorAuthorizationError):
        await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs")) == 0


async def test_adapter_exception_closes_attempt_as_well_as_invocation(service_scope, monkeypatch):
    """异常补写终态时 attempt 也结束，不能永久保留无 owner 的尝试。"""
    service, manager = service_scope
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())

    async def fail_adapter(*_):
        """模拟远端发送之后 adapter 崩溃。"""
        raise RuntimeError("synthetic adapter crash")

    monkeypatch.setattr(service, "_do_http_execution", fail_adapter)
    result = await service.execute_invocation(prepared["invocation_id"], execution=execution())
    assert not result.success
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT status FROM connector_usage_logs")) == "unknown"
        assert await db.scalar(text("SELECT completed_at FROM connector_operation_attempts")) is not None


async def test_result_commit_failure_retains_unknown_and_closes_owned_attempt(service_scope, http_provider, monkeypatch):
    """真实 provider 已收包后结果事务失败，两张表在新事务一起收敛。"""
    from contextlib import asynccontextmanager
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {"base_url": base, "allowed_origins": [base], "allowed_private_cidrs": [host + "/32"]}
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    transactions = 0

    @asynccontextmanager
    async def fail_result_commit():
        """只让结果事务在提交前失败，保留正常 claim 和补偿事务。"""
        nonlocal transactions
        transactions += 1
        current = transactions
        async with manager.get_async_session_context() as db:
            yield db
            if current == 2:
                raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(service, "_session_context_factory", fail_result_commit)
    result = await service.execute_invocation(prepared["invocation_id"], execution=execution())
    assert not result.success and requests == ["/read"]
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT status FROM connector_usage_logs")) == "unknown"
        assert await db.scalar(text("SELECT completed_at FROM connector_operation_attempts")) is not None


async def test_probe_management_role_does_not_override_read_deny(service_scope, monkeypatch):
    """管理权限不能借 probe 绕过最终执行 read scope。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.read_scope = {"access_level": "deny"}
    with pytest.raises(ConnectorAuthorizationError):
        await service.test_connector("service-test", actor="actor")


async def test_persisted_invalid_configuration_cannot_be_frozen_or_dispatched(service_scope):
    """旧持久数据同样校验 typed config，管理保存不是唯一信任边界。"""
    from yuxi.services.connectors.service import ConnectorServiceError
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {"base_url": "https://example.com", "auth_type": "unknown"}
    with pytest.raises(ConnectorServiceError, match="connector_configuration_invalid"):
        await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs")) == 0


async def test_probe_executes_only_declared_read_operation_and_persists_receipt(service_scope, http_provider):
    """真实 healthcheck 必须经过共用执行账本，不能把 Base URL 当业务可用。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {"base_url": base, "allowed_origins": [base], "allowed_private_cidrs": [host + "/32"]}
    missing = await service.test_connector("service-test", actor="actor")
    assert missing["probe"]["error"] == "readonly_healthcheck_not_configured" and requests == []
    async with manager.get_async_session_context() as db:
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {**connector.config, "healthcheck_operation_slug": "read"}
    probe = await service.test_connector("service-test", actor="actor")
    assert probe["probe"]["operation"] and requests == ["/read"]
    async with manager.get_async_session_context() as db:
        row = await ConnectorExecutionRepository(db).get_invocation(probe["probe"]["invocation_id"])
        assert row.status == "succeeded" and row.consumer_type == "admin_test"


async def test_provider_error_body_is_encrypted_and_absent_from_public_projections(service_scope, http_provider, fernet_key):
    """真实 provider 哨兵仅进入加密证据，不进入明文摘要/API/工具输出。"""
    from yuxi.services.connectors.dto import invocation_response
    from yuxi.agents.connectors.tools import format_connector_tool_result
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {"base_url": base, "allowed_origins": [base], "allowed_private_cidrs": [host + "/32"]}
        operation = await repo.get_operation(connector.id, "read")
        operation.endpoint_template = "/error"
    result = await service.prepare_and_execute("service-test", "read", {}, execution=execution())
    assert requests == ["/error"] and not result["success"]
    assert "synthetic-sensitive-sentinel" not in format_connector_tool_result(result)
    async with manager.get_async_session_context() as db:
        row = await ConnectorExecutionRepository(db).get_invocation(result["invocation_id"])
        assert "synthetic-sensitive-sentinel" not in json.dumps(invocation_response(row), default=str)
        assert "synthetic-sensitive-sentinel" in fernet_key.decrypt(row.result_ciphertext).decode()


async def test_agent_cancel_commit_cannot_overtake_claim_transaction(service_scope, http_provider, monkeypatch):
    """真实 PG 行锁证明取消与 claim 共用提交边界，关闭快照竞态。"""
    from sqlalchemy import update
    from yuxi.storage.postgres.models_business import AgentRun, Conversation, Project
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        db.add(Project(id="claim-project", uid="actor", name="claim", selection_status="implicit", directory_mode="managed", workdir_path="projects/claim-project"))
        await db.flush()
        conversation = Conversation(thread_id="claim-thread", uid="actor", agent_id="claim-agent", project_id="claim-project")
        db.add(conversation)
        await db.flush()
        db.add(AgentRun(id="claim-run", request_id="claim-request", uid="actor", agent_slug="claim-agent",
                        conversation_thread_id="claim-thread", runtime_scope_id="claim-thread", conversation_id=conversation.id,
                        status="running", input_payload={}))
        connector = await ConnectorRepository(db).get_by_slug("service-test")
        connector.config = {"base_url": base, "allowed_origins": [base], "allowed_private_cidrs": [host + "/32"]}
        bound_revision = connector.revision
    identity = await service.resolve_agent_execution(actor_uid="actor", current_run_id="claim-run", request_id="claim-request",
                                                     tool_call_id="claim-call", connector_revision=bound_revision, operation_revision=1)
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=identity)
    claim_written, release_claim, cancel_committed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    real_claim = ConnectorExecutionRepository.claim_invocation

    async def pause_claim(repo, *args, **kwargs):
        """只在真实 claim SQL 成功后、owning commit 前设置屏障。"""
        claimed = await real_claim(repo, *args, **kwargs)
        claim_written.set()
        await release_claim.wait()
        return claimed

    async def cancel_parent():
        """独立会话执行正常父 Run 取消持久变更。"""
        async with manager.get_async_session_context() as db:
            await db.execute(update(AgentRun).where(AgentRun.id == "claim-run").values(status="cancel_requested"))
        cancel_committed.set()

    monkeypatch.setattr(ConnectorExecutionRepository, "claim_invocation", pause_claim)
    dispatch = asyncio.create_task(service.execute_invocation(prepared["invocation_id"], execution=identity))
    await asyncio.wait_for(claim_written.wait(), 5)
    cancel = asyncio.create_task(cancel_parent())
    try:
        await asyncio.sleep(0.15)
        assert not cancel_committed.is_set(), "取消不能在已经 claim 的事务 commit 前独立提交"
    finally:
        release_claim.set()
        result, _ = await asyncio.gather(dispatch, cancel)
    assert result.success and requests == ["/read"]


async def test_parallel_recovery_claims_expired_invocation_once_and_fences_late_heartbeat(service_scope):
    """真实行锁让恢复只形成一次结局，迟到 heartbeat 不延长终态。"""
    from datetime import timedelta
    from yuxi.services.connectors.recovery import recover_stale_leases
    from yuxi.utils.datetime_utils import utc_now

    service, manager = service_scope
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        repo = ConnectorExecutionRepository(db)
        invocation = await repo.get_invocation(prepared["invocation_id"])
        await repo.claim_invocation(invocation, owner_id="worker", owner_attempt="expired-owner")
        await repo.create_attempt(invocation.id, 1, owner_attempt="expired-owner")
        invocation.lease_expires_at = utc_now() - timedelta(seconds=1)
    results = await asyncio.gather(*(recover_stale_leases(manager.get_async_session_context) for _ in range(2)))
    assert sum(result["total"] for result in results) == 1
    async with manager.get_async_session_context() as db:
        repo = ConnectorExecutionRepository(db)
        invocation = await repo.get_invocation(prepared["invocation_id"])
        assert invocation.status == "failed" and invocation.lease_expires_at is None
        assert not await repo.heartbeat(invocation.id, owner_attempt="expired-owner")
        attempt = (await db.execute(text("SELECT completed_at, error_code FROM connector_operation_attempts"))).one()
        assert attempt[0] is not None and attempt[1] == "lease_expired"


@pytest.fixture
def http_provider():
    """独立 HTTP 服务记录实际收包，不从被测服务推导副作用。"""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == "/slow-retry":
                time.sleep(0.65)
            body = b'{"message":"synthetic-sensitive-sentinel"}' if self.path == "/error" else b'{"ok": true}'
            status = 503 if self.path in ("/budget", "/slow-retry") or (self.path == "/retry" and requests.count("/retry") < 3) else 403 if self.path == "/error" else 200
            if self.path == "/retry-after-long" or (self.path == "/retry-after" and requests.count(self.path) == 1):
                status = 503
            self.send_response(status)
            if self.path in ("/retry-after", "/retry-after-long"):
                self.send_header("Retry-After", "1" if self.path == "/retry-after" else "9999")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            requests.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/idempotent":
                body = json.dumps({"idempotency_key": self.headers.get("Idempotency-Key")}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            time.sleep(1.25)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    host = socket.gethostbyname(socket.gethostname())
    server = ThreadingHTTPServer((host, 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{server.server_port}", host, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def test_read_prepare_commits_ledger_for_existing_authorized_user(service_scope):
    """授权用户准备只读调用后，其账本在独立会话可见。"""
    service, manager = service_scope
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        row = (
            await db.execute(
                text("SELECT actor_uid, status FROM connector_usage_logs WHERE id = :id"),
                {"id": prepared["invocation_id"]},
            )
        ).one()
    assert tuple(row) == ("actor", "prepared")


async def test_denied_actor_cannot_prepare_a_connector_call(service_scope):
    """deny 权限不能生成可执行的账本记录。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        await db.execute(text('UPDATE connectors SET read_scope = \'{"access_level":"deny"}\'::jsonb'))
    with pytest.raises(ConnectorAuthorizationError):
        await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM connector_usage_logs")) == 0


async def test_write_approval_signal_refers_to_a_committed_invocation(service_scope):
    """等待批准的调用在控制信号返回后仍然持久可见。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/write",
            approval_policy="required",
        )
    with pytest.raises(ConnectorApprovalRequired) as waiting:
        await service.prepare_invocation("service-test", "write", {}, execution=execution("logical-write"))
    async with manager.get_async_session_context() as db:
        row = (
            await db.execute(
                text("SELECT actor_uid, status FROM connector_usage_logs WHERE id = :id"),
                {"id": waiting.value.invocation_id},
            )
        ).one_or_none()
    assert row is not None
    assert tuple(row) == ("actor", "awaiting_approval")


async def test_another_authorized_user_cannot_approve_the_owners_invocation(service_scope):
    """执行 scope 可用也不能批准另一个运行用户的调用。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        db.add(User(uid="other", username="service-test-other", password_hash="non-login-test-user", role="admin"))
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/write",
            approval_policy="required",
        )
    with pytest.raises(ConnectorApprovalRequired) as waiting:
        await service.prepare_invocation("service-test", "write", {}, execution=execution("logical-write"))
    with pytest.raises(ConnectorAuthorizationError):
        await service.decide_invocation(
            waiting.value.invocation_id,
            "approve",
            actor="other",
            expected_digest=waiting.value.digest,
        )
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT status FROM connector_usage_logs")) == "awaiting_approval"


async def test_revoked_scope_is_rejected_before_dispatch(service_scope, http_provider):
    """prepare 后撤权不得让真实 HTTP provider 收到请求。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        await db.execute(
            text("UPDATE connectors SET config = CAST(:config AS jsonb)"),
            {
                "config": json.dumps(
                    {
                        "base_url": base,
                        "allowed_origins": [base],
                        "allowed_private_cidrs": [host + "/32"],
                        "auth_type": "none",
                    }
                )
            },
        )
    context = execution()
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=context)
    async with manager.get_async_session_context() as db:
        await db.execute(text('UPDATE connectors SET read_scope = \'{"access_level":"deny"}\'::jsonb'))
    with pytest.raises(ConnectorAuthorizationError):
        await service.execute_invocation(prepared["invocation_id"], execution=context)
    assert requests == []


async def test_prepared_invocation_contains_a_complete_encrypted_execution_snapshot(service_scope, fernet_key):
    """准备事实包含实际请求定义，执行不能从 slug 猜最新配置。"""
    service, manager = service_scope
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        encrypted, key_id = (
            await db.execute(
                text("SELECT execution_snapshot_ciphertext, key_id FROM connector_usage_logs WHERE id=:id"),
                {"id": prepared["invocation_id"]},
            )
        ).one()
    assert key_id == "test-only"
    snapshot = json.loads(fernet_key.decrypt(encrypted))
    assert snapshot["snapshot_version"] == 1
    assert snapshot["connector_type"] == "generic_rest"
    assert snapshot["config"]["base_url"] == "https://example.com"
    assert snapshot["operation"]["http_method"] == "GET"
    assert snapshot["operation"]["endpoint_template"] == "/read"


async def test_write_then_timeout_persists_unknown_in_the_call_ledger(service_scope, http_provider):
    """真实远端已接收写请求时，账本不能误存 failed。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.config = {
            "base_url": base,
            "allowed_origins": [base],
            "allowed_private_cidrs": [host + "/32"],
            "auth_type": "none",
            "timeout_seconds": 1,
        }
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/write-timeout",
            approval_policy="preauthorized",
        )
    result = await service.prepare_and_execute("service-test", "write", {}, execution=execution("write-timeout"))
    assert requests == ["/write-timeout"]
    assert result["remote_outcome"] == "unknown"
    async with manager.get_async_session_context() as db:
        row = (await db.execute(text("SELECT status, remote_outcome FROM connector_usage_logs"))).one()
    assert tuple(row) == ("unknown", "unknown")


async def test_successful_http_attempt_is_persisted_after_its_preparation_session_closes(service_scope, http_provider):
    """不同事务间的 attempt 不能只在脱离 session 的对象上变终态。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        await db.execute(
            text("UPDATE connectors SET config=CAST(:config AS jsonb)"),
            {
                "config": json.dumps(
                    {
                        "base_url": base,
                        "allowed_origins": [base],
                        "allowed_private_cidrs": [host + "/32"],
                        "auth_type": "none",
                    }
                )
            },
        )
    result = await service.prepare_and_execute("service-test", "read", {}, execution=execution())
    assert result["success"] is True
    assert requests == ["/read"]
    async with manager.get_async_session_context() as db:
        row = (
            await db.execute(
                text("SELECT send_state, response_status, completed_at IS NOT NULL FROM connector_operation_attempts")
            )
        ).one()
    assert tuple(row) == ("response_received", 200, True)


async def test_late_owner_cannot_finalize_a_cancelled_invocation(service_scope):
    """即使 attempt token 相同，取消后的迟到完成也不能覆盖终态。"""
    service, manager = service_scope
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    async with manager.get_async_session_context() as db:
        repo = ConnectorExecutionRepository(db)
        invocation = await repo.get_invocation(prepared["invocation_id"])
        assert await repo.claim_invocation(invocation, owner_id="worker", owner_attempt="lease-token")
        await repo.cancel_invocation(invocation)
    with pytest.raises(ValueError, match="owner"):
        async with manager.get_async_session_context() as db:
            repo = ConnectorExecutionRepository(db)
            invocation = await repo.get_invocation(prepared["invocation_id"])
            await repo.finalize_invocation(invocation, owner_attempt="lease-token", status="succeeded")
    async with manager.get_async_session_context() as db:
        assert await db.scalar(text("SELECT status FROM connector_usage_logs")) == "cancelled"


async def test_repeated_completed_call_returns_its_result_without_another_http_request(service_scope, http_provider):
    """同一逻辑调用的重放返回已提交结果，不失败也不再次发送。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        await db.execute(
            text("UPDATE connectors SET config=CAST(:config AS jsonb)"),
            {
                "config": json.dumps(
                    {
                        "base_url": base,
                        "allowed_origins": [base],
                        "allowed_private_cidrs": [host + "/32"],
                        "auth_type": "none",
                    }
                )
            },
        )
    first = await service.prepare_and_execute("service-test", "read", {}, execution=execution())
    repeated = await service.prepare_and_execute("service-test", "read", {}, execution=execution())
    assert repeated["invocation_id"] == first["invocation_id"]
    assert repeated["success"] is True
    assert repeated["mapped_result"] == {"ok": True}
    assert requests == ["/read"]


async def test_rotation_preserves_the_key_binding_of_every_retained_payload(
    service_scope,
    http_provider,
    vault_configuration,
    fernet_key,
):
    """结果不能用新密钥写入却继续声明旧 key_id。"""
    service, manager = service_scope
    base, host, _ = http_provider
    async with manager.get_async_session_context() as db:
        await db.execute(
            text("UPDATE connectors SET config=CAST(:config AS jsonb)"),
            {
                "config": json.dumps(
                    {
                        "base_url": base,
                        "allowed_origins": [base],
                        "allowed_private_cidrs": [host + "/32"],
                        "auth_type": "none",
                    }
                )
            },
        )
    context = execution()
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=context)
    new_key = Fernet(Fernet.generate_key())
    current = CredentialVault(
        current_key=new_key,
        current_key_id="new-key",
        old_keys={"test-only": fernet_key},
    )
    vault_configuration["current"] = current
    result = await service.execute_invocation(prepared["invocation_id"], execution=context)
    assert result.success
    async with manager.get_async_session_context() as db:
        row = (
            await db.execute(
                text(
                    "SELECT key_id, params_ciphertext, execution_snapshot_ciphertext, result_ciphertext "
                    "FROM connector_usage_logs"
                )
            )
        ).one()
    assert row[0] == "new-key"
    assert row[2] is None  # 已结束调用不再保留含凭据的 dispatch 快照。
    for ciphertext in (row[1], row[3]):
        assert new_key.decrypt(ciphertext)


async def test_a_logical_call_key_cannot_be_reused_for_another_operation(service_scope):
    """相同参数与版本不能让第二个操作复用第一个操作的冻结请求。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        await repo.create_operation(
            connector_id=connector.id,
            slug="other",
            name="other",
            operation_type="read",
            endpoint_template="/different",
            request_schema={"type": "object"},
        )
    await service.prepare_invocation("service-test", "read", {}, execution=execution())
    with pytest.raises(ConnectorConflictError):
        await service.prepare_invocation("service-test", "other", {}, execution=execution())


async def test_dispatch_rejects_a_different_logical_binding_before_http(service_scope, http_provider):
    """同用户也不能用另一调用的上下文领取当前调用。"""
    service, manager = service_scope
    base, host, requests = http_provider
    async with manager.get_async_session_context() as db:
        await db.execute(
            text("UPDATE connectors SET config=CAST(:config AS jsonb)"),
            {
                "config": json.dumps(
                    {
                        "base_url": base,
                        "allowed_origins": [base],
                        "allowed_private_cidrs": [host + "/32"],
                        "auth_type": "none",
                    }
                )
            },
        )
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    with pytest.raises(ConnectorAuthorizationError):
        await service.execute_invocation(prepared["invocation_id"], execution=execution("unrelated-call"))
    assert requests == []


async def test_concurrent_opposite_approval_decisions_cannot_both_commit(service_scope):
    """两事务都先观察 awaiting 后，只有一个决定能生效。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        repo = ConnectorRepository(db)
        connector = await repo.get_by_slug("service-test")
        connector.write_scope = {"access_level": "global"}
        await repo.create_operation(
            connector_id=connector.id,
            slug="write",
            name="write",
            operation_type="write",
            http_method="POST",
            endpoint_template="/write",
            approval_policy="required",
        )
    with pytest.raises(ConnectorApprovalRequired) as waiting:
        await service.prepare_invocation("service-test", "write", {}, execution=execution("logical-write"))
    tasks = []
    try:
        async with manager.get_async_session_context() as blocker:
            await blocker.execute(text("SELECT uid FROM users WHERE uid='actor' FOR UPDATE"))
            for decision in ("approve", "reject"):
                tasks.append(
                    asyncio.create_task(
                        service.decide_invocation(
                            waiting.value.invocation_id,
                            decision,
                            actor="actor",
                            expected_digest=waiting.value.digest,
                        )
                    )
                )
            deadline = asyncio.get_running_loop().time() + 5
            async with manager.get_async_session_context() as observer:
                while True:
                    for task in tasks:
                        if task.done() and task.exception() is not None:
                            raise task.exception()
                    await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                    count = await observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name=current_setting('application_name') "
                            "AND wait_event_type='Lock'"
                        )
                    )
                    if count == 2:
                        break
                    if asyncio.get_running_loop().time() >= deadline:
                        pytest.fail("两个独立审批事务未到达数据库锁边界")
                    await asyncio.sleep(0.02)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert sum(isinstance(result, dict) for result in results) == 1
        assert sum(isinstance(result, ConnectorConflictError) for result in results) == 1
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_metadata_directory_uses_the_same_actual_department_as_execution(service_scope):
    """数据库部门授权同时允许目录和执行，不能依赖调用方传部门。"""
    service, manager = service_scope
    async with manager.get_async_session_context() as db:
        db.add(Department(id=7, name="synthetic department"))
        await db.flush()
        await db.execute(text("UPDATE users SET department_id=7 WHERE uid='actor'"))
        await db.execute(
            text('UPDATE connectors SET read_scope=\'{"access_level":"department","department_ids":[7]}\'::jsonb')
        )
    metadata = await service.get_connector_metadata("service-test", uid="actor")
    assert [operation["slug"] for operation in metadata["operations"]] == ["read"]
    prepared = await service.prepare_invocation("service-test", "read", {}, execution=execution())
    assert prepared["status"] == "prepared"
