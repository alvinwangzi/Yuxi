"""HTTP 步骤执行器 — 外部 API 调用。"""

from __future__ import annotations

from typing import Any

import aiohttp

from yuxi.utils.logging_config import logger
from yuxi.workflows.executors import BaseStepExecutor


class HTTPStepExecutor(BaseStepExecutor):
    """HTTP API 调用。"""

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any], **kwargs) -> Any:
        url = step_data.get("url")
        if not url:
            raise ValueError("http 步骤必须指定 url")

        method = step_data.get("method", "GET").upper()
        headers = step_data.get("headers", {})
        body = step_data.get("body")
        timeout = step_data.get("timeout", 30)

        logger.info(f"HTTP {method} {url}")

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                json=body if body and method in ("POST", "PUT", "PATCH") else None,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                response.raise_for_status()

                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return await response.json()
                else:
                    return await response.text()
