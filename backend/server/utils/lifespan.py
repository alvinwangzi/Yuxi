import inspect
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from yuxi.agents.mcp.service import ensure_builtin_mcp_servers_in_db
from yuxi.models.providers.service import ensure_builtin_model_providers_in_db
from yuxi.services.run_queue_service import close_queue_clients, get_redis_client
from yuxi.storage.postgres.manager import pg_manager
from yuxi.utils import logger
from yuxi.agents.backends.sandbox import init_sandbox_provider, shutdown_sandbox_provider
from yuxi import get_version
from yuxi.utils.auth_utils import AuthUtils


class RequiredStartupComponentError(RuntimeError):
    """核心启动组件失败且当前进程不得继续接流量。"""

    def __init__(self, component: str, code: str):
        self.component = component
        self.code = code
        super().__init__(f"Required startup component failed: component={component}, type={code}")


async def _initialize_startup_component(
    app: FastAPI,
    *,
    name: str,
    required: bool,
    operation: Callable[[], object],
) -> None:
    """执行启动组件并保存非敏感、可供 readiness 使用的能力状态。"""

    try:
        result = operation()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        code = type(exc).__name__
        app.state.startup_components[name] = {
            "status": "error",
            "required": required,
            "code": code,
        }
        logger.error(f"Startup component failed: component={name}, required={required}, type={code}")
        if required:
            raise RequiredStartupComponentError(name, code) from None
    else:
        app.state.startup_components[name] = {"status": "ok", "required": required}


async def _startup(app: FastAPI) -> None:
    """取得 API 运行资源并发布结构化启动状态。"""

    app.state.startup_complete = False
    app.state.startup_components = {}

    await _initialize_startup_component(
        app,
        name="security_secrets",
        required=True,
        operation=AuthUtils.require_security_secrets,
    )

    # Schema 只由 Compose 中的 storage-migrator 修改；运行进程仅校验兼容版本。
    pg_manager.initialize()
    await pg_manager.require_current_schema()

    from yuxi.config.options import (
        ensure_options_in_db,
        invalidate_option_cache,
        system_options,
    )

    async with pg_manager.get_async_session_context() as session:
        await ensure_options_in_db(session)
        await session.commit()
    await invalidate_option_cache(system_options.key)

    await _initialize_startup_component(
        app,
        name="builtin_mcp_servers",
        required=False,
        operation=ensure_builtin_mcp_servers_in_db,
    )

    async def initialize_builtin_skills() -> None:
        """在独立事务中安装内置 Skills。"""

        from yuxi.agents.skills.service import init_builtin_skills

        async with pg_manager.get_async_session_context() as session:
            await init_builtin_skills(session)

    await _initialize_startup_component(
        app,
        name="builtin_skills",
        required=True,
        operation=initialize_builtin_skills,
    )

    async def initialize_default_agents() -> None:
        """确保平台至少具有可用的默认 Agent 定义。"""

        from yuxi.repositories.agent_repository import AgentRepository

        async with pg_manager.get_async_session_context() as session:
            repository = AgentRepository(session)
            await repository.ensure_default_agent()
            await repository.ensure_general_purpose_subagent()
            await repository.ensure_web_search_subagent()
            await repository.ensure_deep_research_agents()

    await _initialize_startup_component(
        app,
        name="default_agents",
        required=True,
        operation=initialize_default_agents,
    )

    # 初始化内置模型供应商配置
    async def initialize_model_providers() -> None:
        """确保内置模型供应商定义可以从数据库读取。"""

        async with pg_manager.get_async_session_context() as session:
            await ensure_builtin_model_providers_in_db(session)

    await _initialize_startup_component(
        app,
        name="model_providers",
        required=True,
        operation=initialize_model_providers,
    )

    # 初始化模型缓存（v2 模型选择使用）
    async def initialize_model_cache() -> None:
        """用 PostgreSQL 当前供应商事实重建进程内模型缓存。"""

        from yuxi.models.providers.cache import model_cache
        from yuxi.models.providers.service import get_all_model_providers

        async with pg_manager.get_async_session_context() as session:
            providers = await get_all_model_providers(session)
            model_cache.rebuild(providers)

    await _initialize_startup_component(
        app,
        name="model_cache",
        required=True,
        operation=initialize_model_cache,
    )

    # 初始化知识库管理器
    from yuxi.knowledge.runtime import knowledge_base

    await _initialize_startup_component(
        app,
        name="knowledge_base",
        required=True,
        operation=knowledge_base.initialize,
    )

    # 预热 Redis（run 队列）
    try:
        redis = await get_redis_client()
        await redis.ping()
    except Exception as e:
        logger.warning(f"Run queue redis unavailable on startup: {e}")

    await _initialize_startup_component(
        app,
        name="sandbox_provider",
        required=True,
        operation=init_sandbox_provider,
    )

    # 注册并启动 IM Channel
    async def initialize_channels() -> None:
        """注册 Channel 类型，从 DB 加载配置并启动已启用的 Channel。"""
        from yuxi.services.channels.manager import register_channel_type
        from yuxi.services.channels.feishu import FeishuChannel
        from yuxi.services.channels.dingtalk import DingTalkChannel
        from yuxi.services.channels.wecom import WeComChannel
        from yuxi.services.channels.base import ChannelConfig
        from yuxi.services.channels.repository import ChannelConfigRepository
        from server.routers.channel_router import get_channel_manager

        for _type, _cls in [("feishu", FeishuChannel), ("dingtalk", DingTalkChannel), ("wecom", WeComChannel)]:
            try:
                register_channel_type(_type, _cls)
            except ValueError:
                pass  # 已注册

        # 从数据库加载已配置的 Channel 并启动已启用的
        manager = get_channel_manager()
        async with pg_manager.get_async_session_context() as session:
            repo = ChannelConfigRepository(session)
            rows = await repo.list_all()

        for row in rows:
            if not row.enabled:
                continue
            config = ChannelConfig(
                slug=row.slug,
                channel_type=row.channel_type,
                enabled=row.enabled,
                credentials=row.credentials or {},
                extra=row.extra or {},
                agent_slug=row.agent_slug,
            )
            try:
                await manager.create_channel(config)
                await manager.start_channel(row.slug)
                logger.info(f"Channel '{row.slug}' ({row.channel_type}) 已启动")
            except Exception as e:
                logger.warning(f"启动 Channel '{row.slug}' 失败: {e}")

    await _initialize_startup_component(
        app,
        name="channels",
        required=False,
        operation=initialize_channels,
    )

    app.state.startup_complete = True
    logger.info(f"""

░██     ░██                       ░██
 ░██   ░██
  ░██ ░██   ░██    ░██ ░██    ░██ ░██
   ░████    ░██    ░██  ░██  ░██  ░██
    ░██     ░██    ░██   ░█████   ░██
    ░██     ░██   ░███  ░██  ░██  ░██
    ░██      ░█████░██ ░██    ░██ ░██  v{get_version()}

    """)
    logger.info("Yuxi backend startup complete")


async def _shutdown_component(name: str, operation: Callable[[], object]) -> None:
    """尽力释放一个已取得或部分取得的资源，并继续执行后续清理。"""

    try:
        result = operation()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.error(f"Shutdown component failed: component={name}, type={type(exc).__name__}")


def _close_neo4j_connection() -> object:
    """关闭共享图数据库连接。"""

    from yuxi.storage.neo4j import close_shared_neo4j_connection

    return close_shared_neo4j_connection()


async def _shutdown_channels() -> None:
    """停止所有运行中的 Channel。"""
    from server.routers.channel_router import get_channel_manager

    manager = get_channel_manager()
    await manager.stop_all()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """确保 startup 任意阶段失败时仍执行已取得资源的补偿清理。"""

    app.state.startup_complete = False
    app.state.startup_components = {}
    try:
        await _startup(app)
        yield
    finally:
        app.state.startup_complete = False
        await _shutdown_component("sandbox_provider", shutdown_sandbox_provider)
        await _shutdown_component("channels", _shutdown_channels)
        await _shutdown_component("queue_clients", close_queue_clients)
        await _shutdown_component("neo4j", _close_neo4j_connection)
        await _shutdown_component("postgres", pg_manager.close)
