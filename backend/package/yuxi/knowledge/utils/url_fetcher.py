"""知识库 URL 抓取 — 安全下载 HTML 内容。

连接安全原语（DNS 解析、IP 校验、SSRF 防护传输层）已提取到
``yuxi.utils.outbound_http``，本模块仅保留知识库特有的白名单校验、
内容类型限制和下载逻辑。
"""

from urllib.parse import urljoin

import httpx

from yuxi.knowledge.utils.url_validator import is_url_parsing_enabled, validate_url
from yuxi.utils import logger
from yuxi.utils.outbound_http import (
    PUBLIC_ONLY_POLICY,
    SSRFGuardTransport,
)

MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = ["text/html", "application/xhtml+xml"]


async def fetch_url_content(url: str, max_size: int = MAX_DOWNLOAD_SIZE) -> tuple[bytes, str]:
    """安全抓取 URL 内容，返回 (bytes, final_url)。"""
    if not is_url_parsing_enabled():
        raise ValueError("URL parsing feature is disabled")

    is_valid, error_msg = validate_url(url)
    if not is_valid:
        raise ValueError(f"Invalid URL: {error_msg}")

    current_url = url
    redirect_count = 0
    max_redirects = 5

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
            transport=SSRFGuardTransport(policy=PUBLIC_ONLY_POLICY),
        ) as client:
            while True:
                logger.info(f"Fetching URL: {current_url}")

                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/91.0.4472.124 "
                        "Safari/537.36"
                    )
                }

                async with client.stream("GET", current_url, headers=headers) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if redirect_count >= max_redirects:
                            raise ValueError("Too many redirects")

                        redirect_count += 1
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError("Redirect response missing Location header")

                        current_url = urljoin(current_url, location)

                        is_valid, error_msg = validate_url(current_url)
                        if not is_valid:
                            raise ValueError(f"Redirected to invalid URL: {error_msg}")

                        continue

                    response.raise_for_status()

                    content_type = response.headers.get("Content-Type", "").lower()
                    if not any(allowed in content_type for allowed in ALLOWED_CONTENT_TYPES):
                        raise ValueError(f"Unsupported Content-Type: {content_type}. Only HTML is supported.")

                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > max_size:
                            raise ValueError(f"Content size exceeds limit of {max_size} bytes")

                    return bytes(content), current_url

    except httpx.HTTPError as exc:
        logger.error(f"HTTP error fetching {url}: {exc}")
        raise ValueError(f"Failed to fetch URL: {exc}")
    except Exception as exc:
        logger.error(f"Error fetching {url}: {exc}")
        raise ValueError(f"Error fetching URL: {exc}")
