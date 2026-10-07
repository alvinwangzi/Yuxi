"""连接器 HTTP 客户端 — 严格的 origin、DNS 和响应边界。

每个连接器配置自己的 allowed_origins 和 allowed_private_cidrs；
共享 ``yuxi.utils.outbound_http`` 的 DNS 解析与传输层，
但注入更严格的 origin 校验策略。
"""

from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from yuxi.utils import logger
from yuxi.utils.outbound_http import (
    OutboundSecurityPolicy,
    SSRFGuardBackend,
    SSRFGuardTransport,
    assert_no_blocked_address,
    resolve_hostname_addresses,
    validate_endpoint_template,
)
from yuxi.services.connectors.schemas import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    validate_max_response_bytes,
    validate_timeout,
)


class ConnectorHTTPError(Exception):
    """连接器 HTTP 请求失败。"""

    def __init__(self, message: str, *, code: str = "provider_error", status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ConnectorUnsafeTargetError(ConnectorHTTPError):
    """请求目标不在允许的 origin 或 CIDR 范围。"""

    def __init__(self, message: str):
        super().__init__(message, code="unsafe_target")


class ConnectorResponseTooLargeError(ConnectorHTTPError):
    """响应超过配置的大小限制。"""

    def __init__(self, limit: int):
        super().__init__(f"响应大小超过 {limit} 字节限制", code="response_too_large")


class ConnectorTimeoutError(ConnectorHTTPError):
    """请求超时。"""

    def __init__(self, timeout: float):
        super().__init__(f"请求超时 ({timeout}s)", code="timeout")


@dataclass(frozen=True)
class ConnectorHTTPConfig:
    """连接器 HTTP 层配置。"""

    base_url: str
    allowed_origins: tuple[str, ...] = ()
    allowed_private_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    allow_redirects: bool = False
    max_redirects: int = 0
    trust_env: bool = False
    raw_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, config: dict) -> ConnectorHTTPConfig:
        base_url = str(config.get("base_url", "")).strip()
        if not base_url:
            raise ConnectorHTTPError("base_url 不能为空")
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ConnectorHTTPError(f"base_url 仅支持 http/https: {base_url}")
        if not parsed.hostname:
            raise ConnectorHTTPError(f"base_url 缺少主机名: {base_url}")
        if parsed.scheme == "http" and not config.get("allowed_origins"):
            raise ConnectorHTTPError("HTTP base_url 必须显式配置 allowed_origins")

        raw_origins = config.get("allowed_origins") or []
        origins: list[str] = []
        for origin in raw_origins:
            if not isinstance(origin, str) or not origin.strip():
                raise ConnectorHTTPError(f"allowed_origins 必须为非空字符串列表")
            parsed_origin = urlparse(origin)
            if parsed_origin.scheme not in ("http", "https") or not parsed_origin.hostname:
                raise ConnectorHTTPError(f"allowed_origins 格式无效: {origin}")
            origins.append(origin.rstrip("/"))

        raw_cidrs = config.get("allowed_private_cidrs") or []
        cidrs: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for cidr_str in raw_cidrs:
            if not isinstance(cidr_str, str):
                raise ConnectorHTTPError("allowed_private_cidrs 必须为字符串列表")
            try:
                cidrs.append(ipaddress.ip_network(cidr_str, strict=False))
            except ValueError as exc:
                raise ConnectorHTTPError(f"无效的 CIDR: {cidr_str}: {exc}") from exc

        return cls(
            base_url=base_url,
            allowed_origins=tuple(origins),
            allowed_private_cidrs=tuple(cidrs),
            timeout_seconds=validate_timeout(config.get("timeout_seconds")),
            max_response_bytes=validate_max_response_bytes(config.get("max_response_bytes")),
            allow_redirects=bool(config.get("allow_redirects", False)),
            max_redirects=int(config.get("max_redirects", 0)),
            trust_env=False,
            raw_config=dict(config),
        )


def build_security_policy(http_config: ConnectorHTTPConfig) -> OutboundSecurityPolicy:
    """从连接器 HTTP 配置构造安全策略。"""
    return OutboundSecurityPolicy(allow_private_cidrs=http_config.allowed_private_cidrs)


def validate_request_origin(
    url: str,
    http_config: ConnectorHTTPConfig,
) -> None:
    """校验请求 URL 的 origin 在允许范围内。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ConnectorUnsafeTargetError(f"不支持的 URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ConnectorUnsafeTargetError("URL 缺少主机名")

    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port and parsed.port not in (80, 443):
        origin = f"{origin}:{parsed.port}"

    if not http_config.allowed_origins:
        if parsed.scheme != "https":
            raise ConnectorUnsafeTargetError("未配置 allowed_origins 时仅允许 HTTPS")
        return

    for allowed in http_config.allowed_origins:
        parsed_allowed = urlparse(allowed)
        allowed_origin = f"{parsed_allowed.scheme}://{parsed_allowed.hostname}"
        if parsed_allowed.port and parsed_allowed.port not in (80, 443):
            allowed_origin = f"{allowed_origin}:{parsed_allowed.port}"
        if origin == allowed_origin:
            return
        if parsed.hostname == parsed_allowed.hostname and parsed.scheme == parsed_allowed.scheme:
            return

    raise ConnectorUnsafeTargetError(f"请求目标不在允许的 origin 范围: {origin}")


def build_full_url(base_url: str, endpoint_template: str, params: dict | None = None) -> str:
    """拼接 base_url 和 endpoint_template，拒绝绝对 URL 覆盖。"""
    validate_endpoint_template(endpoint_template)
    resolved = endpoint_template
    if params:
        from yuxi.services.connectors.schemas import resolve_template
        resolved = resolve_template(endpoint_template, params)
    full_url = urljoin(base_url.rstrip("/") + "/", resolved.lstrip("/"))
    parsed = urlparse(full_url)
    if parsed.hostname != urlparse(base_url).hostname:
        raise ConnectorUnsafeTargetError("endpoint 解析后主机名与 base_url 不一致")
    return full_url


@dataclass
class ConnectorHTTPResponse:
    """HTTP 响应结果。"""

    status_code: int
    headers: dict[str, str]
    body: bytes
    provider_request_id: str | None = None
    duration_ms: float = 0.0


async def execute_http_request(
    method: str,
    url: str,
    *,
    http_config: ConnectorHTTPConfig,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    content: bytes | None = None,
) -> ConnectorHTTPResponse:
    """执行受安全策略约束的 HTTP 请求。"""
    validate_request_origin(url, http_config)

    policy = build_security_policy(http_config)
    transport = SSRFGuardTransport(policy=policy)

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(http_config.timeout_seconds),
        "follow_redirects": http_config.allow_redirects,
        "transport": transport,
        "trust_env": http_config.trust_env,
    }
    if http_config.allow_redirects and http_config.max_redirects > 0:
        client_kwargs["max_redirects"] = http_config.max_redirects

    request_kwargs: dict[str, Any] = {"method": method.upper(), "url": url}
    if headers:
        request_kwargs["headers"] = headers
    if params:
        request_kwargs["params"] = {k: v for k, v in params.items() if v is not None}
    if json_body is not None:
        request_kwargs["json"] = json_body
    elif content is not None:
        request_kwargs["content"] = content

    start_time = time.monotonic()
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.send(
                client.build_request(**request_kwargs),
                stream=False,
            )
    except httpx.TimeoutException:
        raise ConnectorTimeoutError(http_config.timeout_seconds)
    except httpx.HTTPError as exc:
        raise ConnectorHTTPError(f"HTTP 请求失败: {exc}") from exc

    duration_ms = (time.monotonic() - start_time) * 1000

    body = response.content
    if len(body) > http_config.max_response_bytes:
        raise ConnectorResponseTooLargeError(http_config.max_response_bytes)

    if response.status_code >= 300 and not http_config.allow_redirects:
        raise ConnectorHTTPError(
            f"远端返回 {response.status_code}，连接器默认禁止自动重定向",
            code="provider_error",
            status_code=response.status_code,
        )

    provider_request_id = response.headers.get("x-request-id") or response.headers.get("x-amz-request-id")

    return ConnectorHTTPResponse(
        status_code=response.status_code,
        headers=dict(response.headers),
        body=body,
        provider_request_id=provider_request_id,
        duration_ms=duration_ms,
    )
