"""出站 HTTP 连接安全原语 — DNS 解析、IP 分类与 SSRF 防护传输层。

知识库 URL 抓取与连接器 HTTP 客户端共享同一套连接边界：
DNS 解析一次完成、校验绑定实际连接、TLS SNI 保持原主机名。
本模块不依赖任何业务层（知识库、连接器 repository 或权限）。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import typing
from dataclasses import dataclass, field

import httpcore
import httpx
from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkStream

from yuxi.utils import logger

ResolvedAddresses = list[ipaddress.IPv4Address | ipaddress.IPv6Address]

CLOUD_METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(ip)
    for ip in (
        "169.254.169.254",
        "100.100.200.200",
        "fd00:ec2::254",
    )
)


@dataclass(frozen=True)
class OutboundSecurityPolicy:
    """连接前安全策略。

    ``allow_private_cidrs`` 仅用于连接器显式配置的可控内网目标；
    知识库等公网消费者保持默认空集，此时全部非公网地址均被拒绝。
    """

    allow_private_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
    extra_blocked_addresses: frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address] = field(
        default_factory=lambda: CLOUD_METADATA_ADDRESSES
    )

    def is_blocked(self, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            return self.is_blocked(address.ipv4_mapped)
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
            return True
        if address in self.extra_blocked_addresses:
            return True
        if address.is_global:
            return False
        for network in self.allow_private_cidrs:
            if address in network:
                return False
        return True


PUBLIC_ONLY_POLICY = OutboundSecurityPolicy()


def is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """兼容公网消费者的地址判断，策略仍由共享原语拥有。"""
    return PUBLIC_ONLY_POLICY.is_blocked(address)


async def resolve_hostname_addresses(hostname: str) -> ResolvedAddresses:
    """解析主机名为去重 IP 列表，失败时关闭连接。"""
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
    except Exception as exc:
        raise ValueError(f"DNS resolution failed for {hostname}: {exc}") from exc

    addresses: ResolvedAddresses = []
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise ValueError(f"DNS resolution returned no usable address for {hostname}")
    return addresses


def assert_no_blocked_address(
    addresses: ResolvedAddresses,
    policy: OutboundSecurityPolicy = PUBLIC_ONLY_POLICY,
) -> None:
    """校验全部解析地址均符合安全策略。"""
    blocked = [str(addr) for addr in addresses if policy.is_blocked(addr)]
    if blocked:
        raise ValueError(f"Access to private IP or otherwise disallowed addresses is forbidden: {', '.join(blocked)}")


class SSRFGuardBackend(httpcore.AsyncNetworkBackend):
    """只连接已校验 IP 的网络后端，关闭 DNS 重绑定窗口。"""

    def __init__(
        self,
        default_backend: httpcore.AsyncNetworkBackend | None = None,
        policy: OutboundSecurityPolicy = PUBLIC_ONLY_POLICY,
    ):
        self._default = default_backend or _create_default_backend()
        self._policy = policy

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        addresses = await resolve_hostname_addresses(host)
        assert_no_blocked_address(addresses, self._policy)

        per_attempt_timeout = timeout / len(addresses) if timeout is not None else None
        last_error: OSError | None = None
        for address in addresses:
            try:
                return await self._default.connect_tcp(
                    str(address),
                    port,
                    timeout=per_attempt_timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except OSError as exc:
                last_error = exc

        assert last_error is not None
        raise last_error


def _create_default_backend() -> httpcore.AsyncNetworkBackend:
    from httpcore._backends.auto import AutoBackend

    return AutoBackend()


class SSRFGuardTransport(httpx.AsyncHTTPTransport):
    """使用 SSRFGuardBackend 替换连接池网络层的 httpx 传输。"""

    def __init__(
        self,
        backend: SSRFGuardBackend | None = None,
        policy: OutboundSecurityPolicy = PUBLIC_ONLY_POLICY,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._pool._network_backend = backend or SSRFGuardBackend(policy=policy)


def build_safe_transport(
    policy: OutboundSecurityPolicy = PUBLIC_ONLY_POLICY,
) -> SSRFGuardTransport:
    """构造绑定安全策略的 httpx 传输实例。"""
    return SSRFGuardTransport(policy=policy)


def validate_endpoint_template(template: str) -> str:
    """校验 endpoint_template 仅为相对路径，拒绝绝对 URL 和路径穿越。"""
    if not template:
        raise ValueError("endpoint_template 不能为空")
    if "\\" in template:
        raise ValueError("endpoint_template 不允许反斜杠")
    stripped = template.lstrip("/")
    for segment in stripped.split("/"):
        if segment in {"", ".", ".."} or segment.startswith("."):
            raise ValueError(f"endpoint_template 不允许路径穿越段: {segment!r}")
    try:
        from urllib.parse import urlparse

        parsed = urlparse(template)
    except Exception as exc:
        raise ValueError(f"endpoint_template 解析失败: {exc}") from exc
    if parsed.scheme or parsed.netloc or parsed.params or parsed.fragment:
        raise ValueError("endpoint_template 仅允许相对路径，禁止 scheme/authority/fragment")
    if "@" in template.split("?", 1)[0]:
        raise ValueError("endpoint_template 不允许 userinfo")
    return template
