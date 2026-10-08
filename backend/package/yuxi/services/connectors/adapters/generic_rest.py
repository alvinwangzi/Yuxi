"""通用 REST 适配器 — 支持任意 REST API 的标准化调用。

认证类型：none/bearer/basic/api_key。
支持 GET/POST/PUT/PATCH/DELETE、path/query/JSON body 参数模板、
json/text/empty 响应类型和受限字段路径映射。
"""

from __future__ import annotations

import base64
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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
    parse_provider_json,
)
from yuxi.services.connectors.schemas import (
    ConnectorSchemaError,
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
        return ["token", "username", "password", "api_key"]

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        return {"read": True, "write": True}

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
            if operation.remote_idempotency:
                key = operation.remote_idempotency["header_name"]
                all_headers = {name: value for name, value in all_headers.items() if name.lower() != key.lower()}
                all_headers[key] = execution.invocation_id

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
                return ConnectorResult(
                    success=False,
                    error_code="provider_error",
                    error_message=f"provider_http_{response.status_code}",
                    provider_evidence={"body": response.body.decode("utf-8", errors="replace")},
                    remote_outcome="unknown" if operation.operation_type == "write" else "failed",
                    provider_request_id=response.provider_request_id,
                    response_status=response.status_code,
                    duration_ms=duration_ms,
                    retry_after_seconds=_retry_after_delay(response.headers.get("retry-after")),
                )

            parsed_data = _parse_response_body(response.body, operation.response_type)

            try:
                mapped = (
                    apply_response_mapping(
                        parsed_data, operation.response_mapping, max_bytes=http_config.max_response_bytes
                    )
                    if operation.response_mapping is not None
                    else None
                )
            except ConnectorSchemaError:
                return ConnectorResult(
                    success=False,
                    error_code="mapping_error",
                    error_message="远端请求成功，但响应映射失败",
                    remote_outcome="succeeded",
                    provider_request_id=response.provider_request_id,
                    response_status=response.status_code,
                    duration_ms=duration_ms,
                    provider_evidence=parsed_data,
                )

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
                error_message=exc.code,
                remote_outcome=(
                    "not_sent"
                    if exc.code == "unsafe_target"
                    else "unknown"
                    if operation.operation_type == "write"
                    else "failed"
                ),
                response_status=exc.status_code,
                duration_ms=duration_ms,
            )
        except Exception:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning("generic_rest 协议执行异常")
            return ConnectorResult(
                success=False,
                error_code="execution_error",
                error_message="provider_protocol_error",
                remote_outcome="unknown",
                duration_ms=duration_ms,
            )

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
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
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


def _retry_after_delay(value: str | None) -> float | None:
    """接收秒数或 HTTP 日期，拒绝不明值并将 provider 等待限制在五秒。"""
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        if value.isascii() and value.isdigit():
            return min(5.0, float(int(value)))
        moment = parsedate_to_datetime(value)
        if moment.utcoffset() is None:
            return None
        return min(5.0, max(0.0, (moment - datetime.now(UTC)).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_response_body(body: bytes, response_type: str) -> Any:
    """按 response_type 解析响应体。"""
    if response_type == "empty" or not body:
        return None
    if response_type == "text":
        return body.decode("utf-8", errors="replace")
    return parse_provider_json(body, code="mapping_error")
