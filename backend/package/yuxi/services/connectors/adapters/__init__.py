"""连接器适配器 — 各类型业务系统的具体调用实现。"""

from yuxi.services.connectors.adapters.feishu_bitable_crm import FeishuBitableCRMAdapter
from yuxi.services.connectors.adapters.generic_rest import GenericRESTAdapter
from yuxi.services.connectors.adapters.salesforce import SalesforceAdapter
from yuxi.services.connectors.registry import register_adapter


def register_builtin_adapters() -> None:
    """显式装配 API、worker 与工具共享的内置适配器。"""
    for adapter in (GenericRESTAdapter, SalesforceAdapter, FeishuBitableCRMAdapter):
        register_adapter(adapter.connector_type, adapter)


__all__ = ["GenericRESTAdapter", "SalesforceAdapter", "FeishuBitableCRMAdapter", "register_builtin_adapters"]
