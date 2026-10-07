"""连接器服务工厂 — 统一装配入口。

所有 consumer（管理 router、Agent tools、workflow executor、recovery）
通过 ``get_connector_service()`` 获取轻量服务实例。
服务保存 factory/provider 引用，不保存 AsyncSession、ORM 行或解密凭据。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.services.connectors.credential_vault import CredentialVault

SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _default_session_context_factory() -> AbstractAsyncContextManager[AsyncSession]:
    from yuxi.storage.postgres.manager import pg_manager
    return pg_manager.get_async_session_context()


def _default_vault_provider() -> CredentialVault | None:
    return CredentialVault.from_environment()


class ConnectorServiceFactory:
    """连接器服务的装配与依赖注入。

    测试可覆盖 session_context_factory、vault_provider 和 http_client_provider。
    """

    def __init__(
        self,
        *,
        session_context_factory: SessionContextFactory | None = None,
        vault_provider: Callable[[], CredentialVault | None] | None = None,
        http_client_provider: Callable[[], Any] | None = None,
    ):
        self._session_context_factory = session_context_factory or _default_session_context_factory
        self._vault_provider = vault_provider or _default_vault_provider
        self._http_client_provider = http_client_provider

    @property
    def session_context_factory(self) -> SessionContextFactory:
        return self._session_context_factory

    @property
    def vault_provider(self) -> Callable[[], CredentialVault | None]:
        return self._vault_provider

    def create_service(self) -> "ConnectorService":
        from yuxi.services.connectors.service import ConnectorService
        return ConnectorService(
            session_context_factory=self._session_context_factory,
            vault_provider=self._vault_provider,
            http_client_provider=self._http_client_provider,
        )


_default_factory: ConnectorServiceFactory | None = None


def get_connector_service_factory() -> ConnectorServiceFactory:
    global _default_factory
    if _default_factory is None:
        _default_factory = ConnectorServiceFactory()
    return _default_factory


def get_connector_service() -> "ConnectorService":
    return get_connector_service_factory().create_service()


def override_factory(factory: ConnectorServiceFactory | None) -> None:
    """测试用：覆盖全局 factory。传 None 恢复默认。"""
    global _default_factory
    _default_factory = factory
