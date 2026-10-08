"""连接器 HTTP 客户端 — 严格的 origin、DNS 和响应边界。

每个连接器配置自己的 allowed_origins 和 allowed_private_cidrs；
共享 ``yuxi.utils.outbound_http`` 的 DNS 解析与传输层，
但注入更严格的 origin 校验策略。
"""

from __future__ import annotations

import ipaddress
import json
import math
import asyncio
import re
import time
import zlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from yuxi.services.connectors.schemas import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    validate_max_response_bytes,
    validate_timeout,
)
from yuxi.utils.outbound_http import (
    OutboundSecurityPolicy,
    SSRFGuardTransport,
    validate_endpoint_template,
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


class ConnectorReadbackError(ConnectorHTTPError):
    """远端已确认写成功，但独立读回不可用；保留加密 receipt。"""

    def __init__(self, *, response_status, provider_request_id, provider_evidence):
        super().__init__("provider_readback_failed", code="readback_failed", status_code=response_status)
        self.provider_request_id = provider_request_id
        self.provider_evidence = provider_evidence


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
        if config.get("allow_redirects"):
            raise ConnectorHTTPError("连接器不支持自动重定向")
        base_url = str(config.get("base_url", "")).strip()
        if not base_url:
            raise ConnectorHTTPError("base_url 不能为空")
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ConnectorHTTPError(f"base_url 仅支持 http/https: {base_url}")
        if not parsed.hostname:
            raise ConnectorHTTPError(f"base_url 缺少主机名: {base_url}")
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ConnectorHTTPError("base_url 不能包含凭据、query 或 fragment")
        if parsed.scheme == "http" and not config.get("allowed_origins"):
            raise ConnectorHTTPError("HTTP base_url 必须显式配置 allowed_origins")

        raw_origins = config.get("allowed_origins") or []
        origins: list[str] = []
        for origin in raw_origins:
            if not isinstance(origin, str) or not origin.strip():
                raise ConnectorHTTPError("allowed_origins 必须为非空字符串列表")
            parsed_origin = urlparse(origin)
            if parsed_origin.scheme not in ("http", "https") or not parsed_origin.hostname:
                raise ConnectorHTTPError(f"allowed_origins 格式无效: {origin}")
            if (
                parsed_origin.username is not None
                or parsed_origin.password is not None
                or parsed_origin.query
                or parsed_origin.fragment
                or parsed_origin.path not in ("", "/")
            ):
                raise ConnectorHTTPError("allowed_origins 必须为不含凭据或路径的 origin")
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
    if parsed.username is not None or parsed.password is not None:
        raise ConnectorUnsafeTargetError("请求 URL 不允许 userinfo")

    origin = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))

    if not http_config.allowed_origins:
        if parsed.scheme != "https":
            raise ConnectorUnsafeTargetError("未配置 allowed_origins 时仅允许 HTTPS")

    for allowed in http_config.allowed_origins or (http_config.base_url,):
        parsed_allowed = urlparse(allowed)
        allowed_origin = (
            parsed_allowed.scheme,
            parsed_allowed.hostname,
            parsed_allowed.port or (443 if parsed_allowed.scheme == "https" else 80),
        )
        if origin == allowed_origin:
            return

    raise ConnectorUnsafeTargetError(f"请求目标不在允许的 origin 范围: {origin}")


def build_full_url(base_url: str, endpoint_template: str, params: dict | None = None) -> str:
    """拼接 base_url 和 endpoint_template，拒绝绝对 URL 覆盖。"""
    validate_endpoint_template(endpoint_template)
    resolved = endpoint_template
    if params:
        from yuxi.services.connectors.schemas import resolve_template

        def replace_segment(match):
            """单个路径参数不能经编码改变路径边界。"""
            value = str(resolve_template(match.group(), params))
            decoded = value
            for _ in range(3):
                decoded = unquote(decoded)
                if "/" in decoded or "\\" in decoded or decoded in (".", "..") or "\x00" in decoded:
                    raise ConnectorUnsafeTargetError("路径参数不能包含路径跳转或分隔符")
            return quote(value, safe="")

        resolved = re.sub(r"\{\{[^{}]+\}\}", replace_segment, endpoint_template)
    validate_endpoint_template(resolved)
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


def parse_provider_json(body: bytes | str, *, code: str = "provider_error") -> Any:
    """解析 provider wire JSON，拒绝非有限常量与无效编码，不回显原始响应。"""
    try:
        return json.loads(body, parse_constant=_reject_json_constant, parse_float=_parse_finite_float)
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        raise ConnectorHTTPError("provider_json_invalid", code=code) from None


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
    if http_config.allow_redirects:
        raise ConnectorUnsafeTargetError("连接器不支持自动重定向")
    validate_request_origin(url, http_config)

    policy = build_security_policy(http_config)
    transport = SSRFGuardTransport(policy=policy)

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(http_config.timeout_seconds),
        "follow_redirects": False,
        "transport": transport,
        "trust_env": False,
    }
    request_kwargs: dict[str, Any] = {"method": method.upper(), "url": url, "headers": {"Accept-Encoding": "identity"}}
    if headers:
        if len(headers) > 100 or sum(len(key.encode()) + len(value.encode()) for key, value in headers.items()) > 32768:
            raise ConnectorHTTPError("request header 超过上限", code="invalid_params")
        request_kwargs["headers"] = {"Accept-Encoding": "identity", **headers}
    if params:
        request_kwargs["params"] = {k: v for k, v in params.items() if v is not None}
    if json_body is not None:
        request_kwargs["json"] = json_body
    elif content is not None:
        request_kwargs["content"] = content

    start_time = time.monotonic()
    try:
        async with asyncio.timeout(http_config.timeout_seconds), httpx.AsyncClient(**client_kwargs) as client:
            response = await client.send(
                client.build_request(**request_kwargs),
                stream=True,
            )
            try:
                if (
                    len(response.headers.raw) > 100
                    or sum(len(key) + len(value) for key, value in response.headers.raw) > 32768
                ):
                    raise ConnectorHTTPError("response header 超过上限", code="response_too_large")
                if 300 <= response.status_code < 400:
                    raise ConnectorHTTPError(
                        "连接器拒绝远端重定向",
                        code="provider_error",
                        status_code=response.status_code,
                    )
                content_bytes = bytearray()
                encoding = response.headers.get("content-encoding", "identity").strip().lower()
                if encoding not in ("identity", "gzip", "deflate"):
                    raise ConnectorHTTPError("不支持的响应编码", code="provider_error")
                decoder = zlib.decompressobj(31 if encoding == "gzip" else 15) if encoding != "identity" else None
                async for chunk in response.aiter_raw(chunk_size=min(65536, http_config.max_response_bytes + 1)):
                    if decoder is not None:
                        try:
                            # max_length 在分配前生效；aiter_bytes 的解码 chunk 已可能无界。
                            chunk = decoder.decompress(chunk, http_config.max_response_bytes - len(content_bytes) + 1)
                        except zlib.error:
                            raise ConnectorHTTPError("响应压缩数据无效", code="provider_error") from None
                        if decoder.unused_data:
                            raise ConnectorHTTPError("响应包含额外压缩数据", code="provider_error")
                    if len(content_bytes) + len(chunk) > http_config.max_response_bytes:
                        raise ConnectorResponseTooLargeError(http_config.max_response_bytes)
                    content_bytes.extend(chunk)
                if decoder is not None and not decoder.eof:
                    raise ConnectorHTTPError("响应压缩数据不完整", code="provider_error")
                body = bytes(content_bytes)
            finally:
                await response.aclose()
    except (httpx.TimeoutException, TimeoutError):
        raise ConnectorTimeoutError(http_config.timeout_seconds)
    except httpx.HTTPError as exc:
        raise ConnectorHTTPError(f"HTTP 请求失败: {exc}") from exc

    duration_ms = (time.monotonic() - start_time) * 1000

    provider_request_id = (
        response.headers.get("x-request-id")
        or response.headers.get("x-amz-request-id")
        or response.headers.get("x-tt-logid")
        or response.headers.get("x-sfdc-request-id")
    )
    if provider_request_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", provider_request_id):
        provider_request_id = None

    return ConnectorHTTPResponse(
        status_code=response.status_code,
        headers=dict(response.headers),
        body=body,
        provider_request_id=provider_request_id,
        duration_ms=duration_ms,
    )


def _reject_json_constant(value):
    """非有限数不是可交付 JSON，拒绝在 wire 解码时形成浮点对象。"""
    raise ValueError("provider_nonfinite_json")


def _parse_finite_float(value):
    """指数数字也必须能表示为有限浮点值，不能由合法语法溢出成 Infinity。"""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("provider_nonfinite_json")
    return number
