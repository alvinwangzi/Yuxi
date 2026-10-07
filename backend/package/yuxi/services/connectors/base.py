"""连接器适配器基类 — 定义 adapter 必须实现的接口。

adapter 接收已验证、冻结的操作定义和凭据，返回 ConnectorResult；
不接收 repository/db_session、不自己写审计。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from yuxi.services.connectors.http_client import ConnectorHTTPConfig


@dataclass(frozen=True)
class ConnectorResult:
    """适配器执行结果。"""

    success: bool
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None
    remote_outcome: str = "unknown"
    provider_request_id: str | None = None
    response_status: int | None = None
    duration_ms: float = 0.0
    mapped_result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FrozenOperation:
    """已校验并冻结的操作定义，传递给 adapter。"""

    operation_id: int | None
    slug: str
    name: str
    operation_type: str
    http_method: str
    endpoint_template: str
    query_template: dict[str, Any] | None
    body_template: dict[str, Any] | list | str | None
    request_schema: dict | None
    response_mapping: dict[str, str] | None
    response_type: str
    approval_policy: str | None
    retry_policy: dict[str, Any] | None
    remote_idempotency: dict[str, Any] | None


@dataclass(frozen=True)
class ConnectorExecution:
    """单次调用的执行上下文。"""

    invocation_id: str
    actor_uid: str
    consumer_type: str
    logical_call_key: str
    connector_revision: int
    operation_revision: int
    agent_slug: str | None = None
    agent_request_id: str | None = None
    agent_run_id: str | None = None
    workflow_id: int | None = None
    workflow_run_id: int | None = None
    step_id: str | None = None
    step_execution_id: str | None = None
    tool_call_id: str | None = None


class BaseConnectorAdapter(ABC):
    """所有连接器适配器的基类。

    子类不持有 DB session 或 repository；只接收冻结的操作定义和凭据。
    """

    connector_type: str = ""

    @classmethod
    def manifest(cls) -> dict[str, Any]:
        """返回适配器声明元数据，供管理 API 展示。"""
        return {
            "type": cls.connector_type,
            "config_schema": cls.config_schema(),
            "credential_keys": cls.credential_keys(),
            "capabilities": cls.capabilities(),
        }

    @classmethod
    def config_schema(cls) -> dict:
        """返回 typed config 的 JSON Schema。"""
        return {}

    @classmethod
    def credential_keys(cls) -> list[str]:
        """返回该类型需要的凭据 key 列表。"""
        return []

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        """返回适配器能力声明。"""
        return {"read": True, "write": False}

    @abstractmethod
    async def execute(
        self,
        *,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
        operation: FrozenOperation,
        params: dict[str, Any],
        execution: ConnectorExecution,
    ) -> ConnectorResult:
        """执行一次操作调用。

        ``credentials`` 为已解密的凭据字典，key 为 credential_key，value 为明文 bytes。
        ``params`` 为已校验的业务参数。
        """
        ...

    async def probe(
        self,
        *,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
        healthcheck_operation_slug: str | None = None,
    ) -> dict[str, Any]:
        """连接测试，分层返回网络/认证/操作结果。

        默认实现尝试执行 healthcheck 操作；子类可覆盖以提供更精细的探测。
        """
        return {"status": "not_implemented"}
