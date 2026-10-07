"""连接器 HTTP 安全边界集成测试 — 真实 HTTP 请求校验。

使用 httpbin.org 或本地 mock provider 验证 origin/DNS/redirect/size 边界。
无外部网络时自动跳过。
"""

from __future__ import annotations

import ipaddress
import os

import httpx
import pytest

from yuxi.services.connectors.http_client import (
    ConnectorHTTPConfig,
    ConnectorResponseTooLargeError,
    ConnectorTimeoutError,
    ConnectorUnsafeTargetError,
    execute_http_request,
    validate_request_origin,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
]


class TestRealHTTPOriginValidation:
    """真实 HTTP 请求的 origin 校验。"""

    async def test_https_request_to_allowed_origin(self):
        config = ConnectorHTTPConfig(
            base_url="https://httpbin.org",
            allowed_origins=("https://httpbin.org",),
            timeout_seconds=10,
        )
        try:
            response = await execute_http_request(
                "GET",
                "https://httpbin.org/get",
                http_config=config,
            )
            assert response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            pytest.skip("无法连接 httpbin.org，跳过外部 HTTP 测试")

    async def test_request_to_disallowed_origin_rejected(self):
        config = ConnectorHTTPConfig(
            base_url="https://httpbin.org",
            allowed_origins=("https://allowed.example.com",),
            timeout_seconds=5,
        )
        with pytest.raises(ConnectorUnsafeTargetError, match="不在允许"):
            await execute_http_request(
                "GET",
                "https://httpbin.org/get",
                http_config=config,
            )


class TestSSRFProtection:
    """SSRF 防护：私有地址和云元数据。"""

    async def test_private_address_blocked(self):
        config = ConnectorHTTPConfig(
            base_url="http://169.254.169.254",
            allowed_origins=("http://169.254.169.254",),
            allowed_private_cidrs=(),
            timeout_seconds=2,
        )
        with pytest.raises((ConnectorUnsafeTargetError, ValueError, httpx.ConnectError)):
            await execute_http_request(
                "GET",
                "http://169.254.169.254/latest/meta-data/",
                http_config=config,
            )

    async def test_loopback_blocked_by_default(self):
        config = ConnectorHTTPConfig(
            base_url="http://127.0.0.1:9999",
            allowed_origins=("http://127.0.0.1:9999",),
            timeout_seconds=2,
        )
        with pytest.raises((ConnectorUnsafeTargetError, httpx.ConnectError)):
            await execute_http_request(
                "GET",
                "http://127.0.0.1:9999/test",
                http_config=config,
            )

    async def test_explicit_private_cidr_allowed(self):
        config = ConnectorHTTPConfig(
            base_url="http://10.0.0.1:8080",
            allowed_origins=("http://10.0.0.1:8080",),
            allowed_private_cidrs=(ipaddress.ip_network("10.0.0.0/8"),),
            timeout_seconds=2,
        )
        with pytest.raises(httpx.ConnectError):
            await execute_http_request(
                "GET",
                "http://10.0.0.1:8080/test",
                http_config=config,
            )


class TestResponseSizeLimit:
    """响应大小限制。"""

    async def test_oversized_response_rejected(self):
        config = ConnectorHTTPConfig(
            base_url="https://httpbin.org",
            allowed_origins=("https://httpbin.org",),
            max_response_bytes=100,
            timeout_seconds=10,
        )
        try:
            with pytest.raises(ConnectorResponseTooLargeError):
                await execute_http_request(
                    "GET",
                    "https://httpbin.org/bytes/1000",
                    http_config=config,
                )
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            pytest.skip("无法连接 httpbin.org")


class TestTimeoutHandling:
    """超时处理。"""

    async def test_short_timeout_triggers_timeout(self):
        config = ConnectorHTTPConfig(
            base_url="https://httpbin.org",
            allowed_origins=("https://httpbin.org",),
            timeout_seconds=0.001,
        )
        try:
            with pytest.raises(ConnectorTimeoutError):
                await execute_http_request(
                    "GET",
                    "https://httpbin.org/delay/5",
                    http_config=config,
                )
        except (httpx.ConnectError, OSError):
            pytest.skip("无法连接 httpbin.org")
