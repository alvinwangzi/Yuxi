"""连接器类型注册表单元测试。"""

from __future__ import annotations

import pytest

from yuxi.services.connectors.registry import (
    _REGISTRY,
    get_adapter_class,
    get_adapter_manifest,
    list_registered_types,
    register_adapter,
)
from yuxi.services.connectors.base import BaseConnectorAdapter, ConnectorResult


class _StubAdapter(BaseConnectorAdapter):
    connector_type = "test_stub"

    async def execute(self, **kwargs):
        return ConnectorResult(success=True)


class TestRegistry:
    """注册表基础操作。"""

    def setup_method(self):
        self._saved = dict(_REGISTRY)

    def teardown_method(self):
        _REGISTRY.clear()
        _REGISTRY.update(self._saved)

    def test_register_and_get(self):
        register_adapter("test_type", _StubAdapter)
        assert get_adapter_class("test_type") is _StubAdapter

    def test_unregistered_type_raises(self):
        with pytest.raises(KeyError, match="未注册"):
            get_adapter_class("nonexistent_type_xyz")

    def test_list_registered_types_sorted(self):
        _REGISTRY.clear()
        register_adapter("beta", _StubAdapter)
        register_adapter("alpha", _StubAdapter)
        assert list_registered_types() == ["alpha", "beta"]

    def test_duplicate_registration_same_class_no_warning(self):
        register_adapter("dup", _StubAdapter)
        register_adapter("dup", _StubAdapter)
        assert get_adapter_class("dup") is _StubAdapter

    def test_get_adapter_manifest_delegates(self):
        register_adapter("manifest_test", _StubAdapter)
        manifest = get_adapter_manifest("manifest_test")
        assert manifest["type"] == "test_stub"

    def test_get_adapter_manifest_unregistered_raises(self):
        with pytest.raises(KeyError):
            get_adapter_manifest("no_such_type")
