"""通用 REST 适配器 — 支持任意 REST API 的标准化调用。

认证类型：none/bearer/basic/api_key。
支持 GET/POST/PUT/PATCH/DELETE、path/query/JSON body 参数模板、
json/text/empty 响应类型和受限字段路径映射。
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from yuxi.services.connectors.base import (
    BaseConnectorAdapter,
    ConnectorExecution,
    ConnectorResult,
    FrozenOperation,
)
from yuxi.services.connectors.http_client import (
    ConnectorHTTPConfig,
    ConnectorHTTPError,
    build_full_url,
    execute_http_request,
)
from yuxi.services.connectors.registry import register_adapter
from yuxi.services.connectors.schemas import (
    apply_response_mapping,
    resolve_body_template,
    resolve_template,
)
from yuxi.utils import logger


class GenericRESTAdapter(BaseConnectorAdapter):
    """通用 REST 适配器。

    根据连接器 config 中的 auth_type 附加认证头，
    按操作定义的 method/endpoint/query/body 构造请求，
    按 response_mapping 映射响应。
    """

    connector_type: str = "generic_rest"

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "format": "uri"},
                "auth_type": {"type": "string", "enum": ["none", "bearer", "basic", "api_key"]},
                "api_key_header": {"type": "string", "default": "X-API-Key"},
                "static_headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 120},
                "max_response_bytes": {"type": "integer", "minimum": 1024, "maximum": 10485760},
                "allowed_origins": {"type": "array", "items": {"type": "string"}},
                "allowed_private_cidrs": {"type": "array", "items": {"type": "string"}},
                "concurrency_limit": {"type": "integer", "minimum": 1, "maximum": 32},
                "healthcheck_operation_slug": {"type": "string"},
            },
            "required": ["base_url", "auth_type"],
        }

    @classmethod
    def credential_keys(cls) -> list[str]:
        return ["token"]

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        return {"read": True, "write": True}

    def _build_auth_headers(
        self,
        config: dict,
        credentials: dict[str, bytes],
    ) -> dict[str, str]:
        """按 auth_type 构造认证 headers。"""
        auth_type = config.get("auth_type", "none")
        headers: dict[str, str] = {}

        if auth_type == "none":
            return headers

        if auth_type == "bearer":
            token = credentials.get("token", b"").decode("utf-8")
            if not token:
                raise ConnectorHTTPError("bearer 认证需要 token 凭据", code="credential_invalid")
            headers["Authorization"] = f"Bearer {token}"

        elif auth_type == "basic":
            username = credentials.get("username", b"").decode("utf-8")
            password = credentials.get("password", b"").decode("utf-8")
            if not username:
                raise ConnectorHTTPError("basic 认证需要 username 凭据", code="credential_invalid")
            encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"

        elif auth_type == "api_key":
            api_key = credentials.get("api_key", b"").decode("utf-8")
            if not api_key:
                raise ConnectorHTTPError("api_key 认证需要 api_key 凭据", code="credential_invalid")
            header_name = config.get("api_key_header", "X-API-Key")
            headers[header_name] = api_key

        return headers

    def _build_static_headers(self, config: dict) -> dict[str, str]:
        """获取管理员配置的静态非认证 headers。"""
        raw = config.get("static_headers") or {}
        return {k: v for k, v in raw.items() if k.lower() not in {"authorization", "cookie", "proxy-authorization"}}

    async def execute(
        self,
        *,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
        operation: FrozenOperation,
        params: dict[str, Any],
        execution: ConnectorExecution,
    ) -> ConnectorResult:
        start_time = time.monotonic()
        try:
            raw_config = http_config.raw_config
            auth_headers = self._build_auth_headers(raw_config, credentials)
            static_headers = self._build_static_headers(raw_config)
            all_headers = {**static_headers, **auth_headers}

            url = build_full_url(http_config.base_url, operation.endpoint_template, params)

            query_params = None
            if operation.query_template:
                query_params = {}
                for key, template in operation.query_template.items():
                    if isinstance(template, str) and "{{" in template:
                        query_params[key] = resolve_template(template, params)
                    else:
                        query_params[key] = template

            json_body = None
            content_body = None
            if operation.body_template is not None:
                resolved = resolve_body_template(operation.body_template, params)
                if isinstance(resolved, (dict, list)):
                    json_body = resolved
                elif isinstance(resolved, str):
                    content_body = resolved.encode("utf-8")

            response = await execute_http_request(
                operation.http_method,
                url,
                http_config=http_config,
                headers=all_headers,
                params=query_params,
                json_body=json_body,
                content=content_body,
            )

            duration_ms = (time.monotonic() - start_time) * 1000

            if response.status_code >= 400:
                error_msg = _extract_error_message(response.body, response.status_code)
                return ConnectorResult(
                    success=False,
                    error_code="provider_error",
                    error_message=error_msg,
                    remote_outcome="failed",
                    provider_request_id=response.provider_request_id,
                    response_status=response.status_code,
                    duration_ms=duration_ms,
                )

            parsed_data = _parse_response_body(response.body, operation.response_type)

            mapped = apply_response_mapping(parsed_data, operation.response_mapping)

            return ConnectorResult(
                success=True,
                data=parsed_data,
                provider_request_id=response.provider_request_id,
                response_status=response.status_code,
                duration_ms=duration_ms,
                mapped_result=mapped,
                remote_outcome="succeeded",
            )

        except ConnectorHTTPError as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            return ConnectorResult(
                success=False,
                error_code=exc.code,
                error_message=str(exc)[:500],
                remote_outcome="failed",
                response_status=exc.status_code,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning(f"generic_rest 执行异常: {exc}")
            return ConnectorResult(
                success=False,
                error_code="execution_error",
                error_message=str(exc)[:500],
                remote_outcome="unknown",
                duration_ms=duration_ms,
            )

    async def probe(
        self,
        *,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
        healthcheck_operation_slug: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"network": False, "auth": False, "operation": False}
        try:
            raw_config = http_config.raw_config
            auth_headers = self._build_auth_headers(raw_config, credentials)
            static_headers = self._build_static_headers(raw_config)
            all_headers = {**static_headers, **auth_headers}

            probe_url = http_config.base_url.rstrip("/")
            try:
                response = await execute_http_request(
                    "GET", probe_url, http_config=http_config, headers=all_headers,
                )
                result["network"] = True
                if response.status_code < 400:
                    result["auth"] = True
                elif response.status_code in (401, 403):
                    result["auth"] = False
                    result["error"] = "认证失败"
                    return result
            except ConnectorHTTPError as exc:
                result["error"] = f"网络探测失败: {exc}"
                return result

            if healthcheck_operation_slug:
                result["healthcheck_operation"] = healthcheck_operation_slug
                result["operation"] = True

            return result

        except Exception as exc:
            result["error"] = str(exc)[:500]
            return result


def _parse_response_body(body: bytes, response_type: str) -> Any:
    """按 response_type 解析响应体。"""
    if response_type == "empty" or not body:
        return None
    if response_type == "text":
        return body.decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConnectorHTTPError(f"JSON 响应解析失败: {exc}", code="mapping_error")


def _extract_error_message(body: bytes, status_code: int) -> str:
    """从错误响应中提取可读消息。"""
    text = body.decode("utf-8", errors="replace")[:500]
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for key in ("message", "error", "detail", "error_description"):
                if key in data:
                    val = data[key]
                    if isinstance(val, str):
                        return val[:500]
                    if isinstance(val, dict) and "message" in val:
                        return str(val["message"])[:500]
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return f"HTTP {status_code}: {text}"


register_adapter("generic_rest", GenericRESTAdapter)
