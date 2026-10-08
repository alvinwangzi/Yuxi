"""真实本地 HTTP 验证 origin、私网、大小和超时，不依赖公共网站。"""

import ipaddress
import socket
import threading
import time
import gzip
import zlib
import tracemalloc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from yuxi.services.connectors.http_client import (
    ConnectorHTTPConfig,
    ConnectorResponseTooLargeError,
    ConnectorTimeoutError,
    ConnectorUnsafeTargetError,
    execute_http_request,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture
def http_target():
    """独立服务返回确定字节并记录真实请求。"""
    requests = []
    compressor = zlib.compressobj(wbits=31)
    bomb = b"".join(compressor.compress(b"x" * (1024 * 1024)) for _ in range(64)) + compressor.flush()

    class Handler(BaseHTTPRequestHandler):
        """响应只含任务合成数据。"""

        def do_GET(self):
            """实际收到请求后才返回大小或超时 oracle。"""
            requests.append(self.path)
            if self.path == "/delay":
                time.sleep(0.05)
            body = b"x" * 1000 if self.path == "/large" else b'{"ok":true}'
            encoding = None
            if self.path == "/gzip_bomb":
                body, encoding = bomb, "gzip"
            elif self.path.startswith("/encoded/"):
                encoding = self.path.rsplit("/", 1)[-1]
                body = gzip.compress(body) if encoding == "gzip" else zlib.compress(body)
            elif self.path == "/truncated":
                body, encoding = gzip.compress(body)[:-3], "gzip"
            elif self.path == "/members":
                body, encoding = gzip.compress(body) + gzip.compress(body), "gzip"
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                if encoding:
                    self.send_header("Content-Encoding", encoding)
                self.end_headers()
                if self.path == "/trickle":
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.025)
                    return
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            """请求参数不进入日志。"""

    host = socket.gethostbyname(socket.gethostname())
    server = ThreadingHTTPServer((host, 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://{host}:{server.server_port}"
    config = ConnectorHTTPConfig(
        base_url=base, allowed_origins=(base,), allowed_private_cidrs=(ipaddress.ip_network(host + "/32"),)
    )
    try:
        yield base, config, requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


async def test_real_request_to_explicit_private_origin_reads_provider_bytes(http_target):
    base, config, requests = http_target
    response = await execute_http_request("GET", base + "/get", http_config=config)
    assert response.body == b'{"ok":true}' and requests == ["/get"]


async def test_compressed_bomb_is_rejected_before_unbounded_decompression(http_target):
    """64 MiB 解压结果被 1 MiB 预算拒绝，客户端分配也保持有界。"""
    base, config, requests = http_target
    await execute_http_request("GET", base + "/get", http_config=config)
    tracemalloc.start()
    try:
        with pytest.raises(ConnectorResponseTooLargeError):
            await execute_http_request("GET", base + "/gzip_bomb", http_config=config)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, f"decoded response allocated {peak} bytes before size rejection"
    assert requests == ["/get", "/gzip_bomb"]


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
async def test_supported_encoding_returns_exact_decoded_bytes(http_target, encoding):
    """允许的单层编码回读完整正文，不把压缩字节当 JSON。"""
    base, config, _ = http_target
    response = await execute_http_request("GET", base + "/encoded/" + encoding, http_config=config)
    assert response.body == b'{"ok":true}'


@pytest.mark.parametrize("path", ["/truncated", "/members", "/encoded/br"])
async def test_incomplete_composite_or_unsupported_encoding_fails_explicitly(http_target, path):
    """不能将截断、额外 gzip member 或未知编码静默当成成功正文。"""
    from yuxi.services.connectors.http_client import ConnectorHTTPError

    base, config, _ = http_target
    with pytest.raises(ConnectorHTTPError):
        await execute_http_request("GET", base + path, http_config=config)


async def test_disallowed_origin_rejected_before_provider_receives_request(http_target):
    base, _, requests = http_target
    config = ConnectorHTTPConfig(base_url=base, allowed_origins=("https://allowed.example.com",))
    with pytest.raises(ConnectorUnsafeTargetError):
        await execute_http_request("GET", base + "/get", http_config=config)
    assert requests == []


@pytest.mark.parametrize("target", ["http://169.254.169.254/latest/meta-data", "http://127.0.0.1:9999/test"])
async def test_hard_denied_target_never_connects(target):
    # 将同一 origin 显式允许也不能解除地址边界。
    from urllib.parse import urlsplit

    parsed = urlsplit(target)
    config = ConnectorHTTPConfig(base_url=target, allowed_origins=(f"{parsed.scheme}://{parsed.netloc}",))
    with pytest.raises(ValueError, match="Access to private IP"):
        await execute_http_request("GET", target, http_config=config)


async def test_private_ip_without_explicit_cidr_is_rejected(http_target):
    base, _, requests = http_target
    config = ConnectorHTTPConfig(base_url=base, allowed_origins=(base,))
    with pytest.raises(ValueError, match="Access to private IP"):
        await execute_http_request("GET", base + "/get", http_config=config)
    assert requests == []


async def test_real_oversized_response_is_rejected(http_target):
    from dataclasses import replace

    base, config, requests = http_target
    with pytest.raises(ConnectorResponseTooLargeError):
        await execute_http_request("GET", base + "/large", http_config=replace(config, max_response_bytes=100))
    assert requests == ["/large"]


async def test_real_response_timeout_is_classified(http_target):
    from dataclasses import replace

    base, config, requests = http_target
    with pytest.raises(ConnectorTimeoutError):
        await execute_http_request("GET", base + "/delay", http_config=replace(config, timeout_seconds=0.02))
    assert requests == ["/delay"]


async def test_total_timeout_stops_trickle_even_when_each_chunk_arrives_in_time(http_target):
    """单次读间隔未超时也必须服从整个响应的总 deadline。"""
    from dataclasses import replace

    base, config, requests = http_target
    started = time.monotonic()
    with pytest.raises(ConnectorTimeoutError):
        await execute_http_request("GET", base + "/trickle", http_config=replace(config, timeout_seconds=0.08))
    assert time.monotonic() - started < 0.2
    assert requests == ["/trickle"]
