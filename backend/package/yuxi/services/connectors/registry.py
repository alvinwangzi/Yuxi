"""连接器类型注册表 — 按 type 查找 adapter 工厂。

注册表在 import 时不执行 IO；adapter 通过 ``register_adapter`` 主动注册，
factory 通过 ``get_adapter_class`` 查找。未注册类型返回明确错误。
"""

from __future__ import annotations

from typing import Any

from yuxi.utils import logger

_REGISTRY: dict[str, type] = {}


def register_adapter(connector_type: str, adapter_class: type) -> None:
    """注册适配器类型；重复注册覆盖并发出警告。"""
    if connector_type in _REGISTRY and _REGISTRY[connector_type] is not adapter_class:
        logger.warning(f"连接器类型 {connector_type} 重复注册，覆盖旧实现")
    _REGISTRY[connector_type] = adapter_class


def get_adapter_class(connector_type: str) -> type:
    """按类型查找适配器；未注册时抛出 KeyError。"""
    if connector_type not in _REGISTRY:
        raise KeyError(f"未注册的连接器类型: {connector_type}")
    return _REGISTRY[connector_type]


def list_registered_types() -> list[str]:
    """返回已注册的所有连接器类型。"""
    return sorted(_REGISTRY.keys())


def get_adapter_manifest(connector_type: str) -> dict[str, Any]:
    """返回适配器的声明元数据（config_schema、credential_keys、capabilities）。"""
    adapter_class = get_adapter_class(connector_type)
    if hasattr(adapter_class, "manifest"):
        return adapter_class.manifest()
    return {"type": connector_type}
