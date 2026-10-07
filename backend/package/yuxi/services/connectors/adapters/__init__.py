"""连接器适配器 — 各类型业务系统的具体调用实现。"""

from yuxi.services.connectors.adapters.generic_rest import GenericRESTAdapter
from yuxi.services.connectors.adapters.salesforce import SalesforceAdapter
from yuxi.services.connectors.adapters.feishu_bitable_crm import FeishuBitableCRMAdapter

__all__ = ["GenericRESTAdapter", "SalesforceAdapter", "FeishuBitableCRMAdapter"]
