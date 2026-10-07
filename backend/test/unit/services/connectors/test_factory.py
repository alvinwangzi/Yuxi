"""连接器服务工厂单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from yuxi.services.connectors.credential_vault import CredentialVault
from yuxi.services.connectors.factory import (
    ConnectorServiceFactory,
    get_connector_service,
    get_connector_service_factory,
    override_factory,
)


class TestConnectorServiceFactory:
    """工厂 DI 与覆盖。"""

    def test_default_factory_creates_service(self):
        mock_session = AsyncMock()
        mock_vault = CredentialVault.__new__(CredentialVault)
        factory = ConnectorServiceFactory(
            session_context_factory=mock_session,
            vault_provider=lambda: mock_vault,
        )
        service = factory.create_service()
        assert service is not None

    def test_factory_preserves_session_context_factory(self):
        mock_session = AsyncMock()
        factory = ConnectorServiceFactory(session_context_factory=mock_session)
        assert factory.session_context_factory is mock_session

    def test_factory_preserves_vault_provider(self):
        vault_fn = lambda: None
        factory = ConnectorServiceFactory(vault_provider=vault_fn)
        assert factory.vault_provider is vault_fn

    def test_override_and_restore(self):
        original = get_connector_service_factory()
        try:
            custom = ConnectorServiceFactory(
                session_context_factory=AsyncMock(),
                vault_provider=lambda: None,
            )
            override_factory(custom)
            assert get_connector_service_factory() is custom
        finally:
            override_factory(original)

    def test_override_none_resets(self):
        override_factory(None)
        factory = get_connector_service_factory()
        assert factory is not None
        override_factory(None)
