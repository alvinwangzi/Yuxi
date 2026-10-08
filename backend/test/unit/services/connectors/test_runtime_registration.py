"""连接器公共装配入口在新进程中提供完整内置能力。"""

import os
import subprocess
import sys

import pytest


def test_registry_rejects_conflicting_class_without_replacing_owner(monkeypatch):
    """不同实现争用同一类型时失败，原注册仍拥有行为。"""
    from yuxi.services.connectors import registry

    monkeypatch.setattr(registry, "_REGISTRY", {})
    registry.register_adapter("example", dict)
    registry.register_adapter("example", dict)
    with pytest.raises(ValueError, match="重复注册"):
        registry.register_adapter("example", list)
    assert registry.get_adapter_class("example") is dict


def test_service_composition_registers_all_builtin_adapters_in_fresh_process():
    """正常 consumer 不依赖测试或页面预先导入适配器。"""
    command = """
from yuxi.services.connectors.factory import get_connector_service
from yuxi.services.connectors.registry import list_registered_types
get_connector_service()
assert list_registered_types() == ['feishu_bitable_crm', 'generic_rest', 'salesforce']
"""
    result = subprocess.run(
        [sys.executable, "-c", command], capture_output=True, text=True, env=dict(os.environ), check=False
    )
    assert result.returncode == 0, result.stderr
