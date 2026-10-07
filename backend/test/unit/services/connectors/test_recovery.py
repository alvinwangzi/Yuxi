"""连接器 lease 恢复单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yuxi.services.connectors.recovery import recover_stale_leases


class TestRecoverStaleLeases:
    """lease 过期恢复。"""

    def _make_session_ctx(self, mock_session):
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    async def test_no_stale_leases_returns_zero(self):
        mock_repo = AsyncMock()
        mock_repo.find_stale_leases = AsyncMock(return_value=[])
        mock_session = AsyncMock()

        factory = MagicMock()
        factory.return_value = self._make_session_ctx(mock_session)

        with patch(
            "yuxi.repositories.connector_execution_repository.ConnectorExecutionRepository",
            return_value=mock_repo,
        ):
            stats = await recover_stale_leases(factory)

        assert stats == {"total": 0, "read_failed": 0, "write_unknown": 0}

    async def test_read_operation_marked_failed(self):
        stale_inv = MagicMock()
        stale_inv.owner_attempt = "worker-1"
        stale_inv.operation_type = "read"

        mock_repo = AsyncMock()
        mock_repo.find_stale_leases = AsyncMock(return_value=[stale_inv])
        mock_repo.finalize_invocation = AsyncMock()
        mock_session = AsyncMock()

        factory = MagicMock()
        factory.return_value = self._make_session_ctx(mock_session)

        with patch(
            "yuxi.repositories.connector_execution_repository.ConnectorExecutionRepository",
            return_value=mock_repo,
        ):
            stats = await recover_stale_leases(factory)

        assert stats["total"] == 1
        assert stats["read_failed"] == 1
        assert stats["write_unknown"] == 0
        mock_repo.finalize_invocation.assert_called_once()
        call_kwargs = mock_repo.finalize_invocation.call_args
        assert call_kwargs.kwargs["status"] == "failed"
        assert call_kwargs.kwargs["error_code"] == "lease_expired"

    async def test_write_operation_marked_unknown(self):
        stale_inv = MagicMock()
        stale_inv.owner_attempt = "worker-2"
        stale_inv.operation_type = "write"

        mock_repo = AsyncMock()
        mock_repo.find_stale_leases = AsyncMock(return_value=[stale_inv])
        mock_repo.mark_unknown = AsyncMock()
        mock_session = AsyncMock()

        factory = MagicMock()
        factory.return_value = self._make_session_ctx(mock_session)

        with patch(
            "yuxi.repositories.connector_execution_repository.ConnectorExecutionRepository",
            return_value=mock_repo,
        ):
            stats = await recover_stale_leases(factory)

        assert stats["total"] == 1
        assert stats["read_failed"] == 0
        assert stats["write_unknown"] == 1
        mock_repo.mark_unknown.assert_called_once()
        call_kwargs = mock_repo.mark_unknown.call_args
        assert call_kwargs.kwargs["error_code"] == "lease_expired"

    async def test_mixed_read_and_write(self):
        read_inv = MagicMock()
        read_inv.owner_attempt = "w1"
        read_inv.operation_type = "read"
        write_inv = MagicMock()
        write_inv.owner_attempt = "w2"
        write_inv.operation_type = "write"

        mock_repo = AsyncMock()
        mock_repo.find_stale_leases = AsyncMock(return_value=[read_inv, write_inv])
        mock_repo.finalize_invocation = AsyncMock()
        mock_repo.mark_unknown = AsyncMock()
        mock_session = AsyncMock()

        factory = MagicMock()
        factory.return_value = self._make_session_ctx(mock_session)

        with patch(
            "yuxi.repositories.connector_execution_repository.ConnectorExecutionRepository",
            return_value=mock_repo,
        ):
            stats = await recover_stale_leases(factory)

        assert stats["total"] == 2
        assert stats["read_failed"] == 1
        assert stats["write_unknown"] == 1
