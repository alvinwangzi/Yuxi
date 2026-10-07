"""Salesforce 适配器 — Server-to-server client credentials 认证。

通过 OAuth client credentials 流程获取 access token，
支持 SOQL 查询（字段白名单）和受限字段更新。
预置操作：query_customer、get_customer、get_opportunity、update_opportunity、upsert_customer。
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote as url_quote

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
    validate_request_origin,
)
from yuxi.services.connectors.registry import register_adapter
from yuxi.services.connectors.schemas import apply_response_mapping
from yuxi.utils import logger

ALLOWED_SOBJECTS = frozenset({"Account", "Opportunity", "Contact", "Lead"})

DEFAULT_READ_FIELDS: dict[str, list[str]] = {
    "Account": ["Id", "Name", "Industry", "AnnualRevenue", "BillingCity", "BillingState", "Phone", "Website"],
    "Opportunity": ["Id", "Name", "StageName", "Amount", "CloseDate", "AccountId"],
    "Contact": ["Id", "FirstName", "LastName", "Email", "Phone", "AccountId"],
    "Lead": ["Id", "FirstName", "LastName", "Company", "Status"],
}

WRITABLE_FIELDS: dict[str, list[str]] = {
    "Account": ["Name", "Industry", "AnnualRevenue", "BillingCity", "BillingState", "Phone", "Website"],
    "Opportunity": ["Name", "StageName", "Amount", "CloseDate"],
}


class SalesforceAdapter(BaseConnectorAdapter):
    """Salesforce REST API 适配器。

    使用 client credentials 获取 access token；
    SOQL 查询字段来自白名单，写操作字段同样受限。
    """

    connector_type: str = "salesforce"

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "format": "uri", "description": "Salesforce My Domain URL"},
                "api_version": {"type": "string", "pattern": "^v\\d+\\.\\d+$"},
                "client_id": {"type": "string"},
                "allowed_objects": {"type": "array", "items": {"type": "string"}},
                "read_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "array", "items": {"type": "string"}},
                },
                "writable_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "array", "items": {"type": "string"}},
                },
                "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 120},
                "max_response_bytes": {"type": "integer", "minimum": 1024, "maximum": 10485760},
                "allowed_origins": {"type": "array", "items": {"type": "string"}},
                "concurrency_limit": {"type": "integer", "minimum": 1, "maximum": 32},
            },
            "required": ["base_url", "api_version"],
        }

    @classmethod
    def credential_keys(cls) -> list[str]:
        return ["client_id", "client_secret"]

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        return {"read": True, "write": True}

    async def _get_access_token(
        self,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
    ) -> str:
        """通过 client credentials 流程获取 access token。"""
        client_id = credentials.get("client_id", b"").decode("utf-8")
        client_secret = credentials.get("client_secret", b"").decode("utf-8")
        if not client_id or not client_secret:
            raise ConnectorHTTPError("Salesforce 需要 client_id 和 client_secret", code="credential_invalid")

        token_url = f"{http_config.base_url.rstrip('/')}/services/oauth2/token"
        validate_request_origin(token_url, http_config)

        body = (
            f"grant_type=client_credentials"
            f"&client_id={url_quote(client_id)}"
            f"&client_secret={url_quote(client_secret)}"
        )

        response = await execute_http_request(
            "POST",
            token_url,
            http_config=http_config,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=body.encode("utf-8"),
        )

        if response.status_code != 200:
            raise ConnectorHTTPError(
                f"Salesforce token 获取失败: HTTP {response.status_code}",
                code="credential_invalid",
                status_code=response.status_code,
            )

        try:
            token_data = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ConnectorHTTPError(f"token 响应解析失败: {exc}", code="provider_error")

        access_token = token_data.get("access_token", "")
        if not access_token:
            raise ConnectorHTTPError("token 响应缺少 access_token", code="credential_invalid")

        instance_url = token_data.get("instance_url", "")
        if instance_url:
            validate_request_origin(instance_url, http_config)

        return access_token

    def _build_soql(
        self,
        sobject: str,
        fields: list[str],
        where_clause: str | None = None,
        limit: int | None = None,
    ) -> str:
        """构造受限 SOQL 查询。"""
        if sobject not in ALLOWED_SOBJECTS:
            raise ConnectorHTTPError(f"不允许查询的对象: {sobject}", code="invalid_params")
        for field in fields:
            if not field.isidentifier():
                raise ConnectorHTTPError(f"非法字段名: {field}", code="invalid_params")

        field_list = ", ".join(fields)
        query = f"SELECT {field_list} FROM {sobject}"
        if where_clause:
            query += f" WHERE {where_clause}"
        if limit:
            query += f" LIMIT {min(limit, 200)}"
        return query

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
            access_token = await self._get_access_token(http_config, credentials)
            auth_headers = {"Authorization": f"Bearer {access_token}"}
            api_version = _extract_api_version(http_config)

            result_data: Any = None
            provider_request_id: str | None = None
            response_status: int | None = None

            op_slug = operation.slug

            if op_slug == "query_customer":
                result_data, provider_request_id, response_status = await self._query_accounts(
                    http_config, auth_headers, api_version, params,
                )
            elif op_slug == "get_customer":
                result_data, provider_request_id, response_status = await self._get_account(
                    http_config, auth_headers, api_version, params,
                )
            elif op_slug == "get_opportunity":
                result_data, provider_request_id, response_status = await self._get_opportunity(
                    http_config, auth_headers, api_version, params,
                )
            elif op_slug == "update_opportunity":
                result_data, provider_request_id, response_status = await self._update_opportunity(
                    http_config, auth_headers, api_version, params,
                )
            elif op_slug == "upsert_customer":
                result_data, provider_request_id, response_status = await self._upsert_account(
                    http_config, auth_headers, api_version, params,
                )
            else:
                url = build_full_url(http_config.base_url, operation.endpoint_template, params)
                response = await execute_http_request(
                    operation.http_method, url,
                    http_config=http_config, headers=auth_headers,
                )
                response_status = response.status_code
                provider_request_id = response.provider_request_id
                if response.status_code >= 400:
                    duration_ms = (time.monotonic() - start_time) * 1000
                    return ConnectorResult(
                        success=False, error_code="provider_error",
                        error_message=f"Salesforce API 错误: HTTP {response.status_code}",
                        remote_outcome="failed",
                        provider_request_id=provider_request_id,
                        response_status=response_status, duration_ms=duration_ms,
                    )
                result_data = json.loads(response.body) if response.body else None

            duration_ms = (time.monotonic() - start_time) * 1000
            mapped = apply_response_mapping(result_data, operation.response_mapping) if operation.response_mapping else {}

            return ConnectorResult(
                success=True, data=result_data,
                provider_request_id=provider_request_id,
                response_status=response_status, duration_ms=duration_ms,
                mapped_result=mapped, remote_outcome="succeeded",
            )

        except ConnectorHTTPError as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            return ConnectorResult(
                success=False, error_code=exc.code,
                error_message=str(exc)[:500], remote_outcome="failed",
                response_status=exc.status_code, duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning(f"salesforce 执行异常: {exc}")
            return ConnectorResult(
                success=False, error_code="execution_error",
                error_message=str(exc)[:500], remote_outcome="unknown",
                duration_ms=duration_ms,
            )

    async def _query_accounts(
        self, http_config: ConnectorHTTPConfig, headers: dict, api_version: str, params: dict,
    ) -> tuple[Any, str | None, int | None]:
        fields = DEFAULT_READ_FIELDS["Account"]
        where_parts: list[str] = []
        if params.get("name"):
            name = str(params["name"]).replace("'", "\\'")
            where_parts.append(f"Name LIKE '{name}%'")
        if params.get("industry"):
            industry = str(params["industry"]).replace("'", "\\'")
            where_parts.append(f"Industry = '{industry}'")

        where_clause = " AND ".join(where_parts) if where_parts else None
        limit = min(int(params.get("page_size", 20)), 200)
        soql = self._build_soql("Account", fields, where_clause, limit)

        query_url = f"{http_config.base_url.rstrip('/')}/services/data/{api_version}/query?q={url_quote(soql)}"
        validate_request_origin(query_url, http_config)

        response = await execute_http_request("GET", query_url, http_config=http_config, headers=headers)
        data = json.loads(response.body) if response.body else {}
        return data, response.provider_request_id, response.status_code

    async def _get_account(
        self, http_config: ConnectorHTTPConfig, headers: dict, api_version: str, params: dict,
    ) -> tuple[Any, str | None, int | None]:
        account_id = str(params.get("account_id", ""))
        if not account_id:
            raise ConnectorHTTPError("缺少 account_id", code="invalid_params")
        fields = DEFAULT_READ_FIELDS["Account"]
        url = f"{http_config.base_url.rstrip('/')}/services/data/{api_version}/sobjects/Account/{url_quote(account_id)}?fields={','.join(fields)}"
        validate_request_origin(url, http_config)
        response = await execute_http_request("GET", url, http_config=http_config, headers=headers)
        data = json.loads(response.body) if response.body else {}
        return data, response.provider_request_id, response.status_code

    async def _get_opportunity(
        self, http_config: ConnectorHTTPConfig, headers: dict, api_version: str, params: dict,
    ) -> tuple[Any, str | None, int | None]:
        opp_id = str(params.get("opportunity_id", ""))
        if not opp_id:
            raise ConnectorHTTPError("缺少 opportunity_id", code="invalid_params")
        fields = DEFAULT_READ_FIELDS["Opportunity"]
        url = f"{http_config.base_url.rstrip('/')}/services/data/{api_version}/sobjects/Opportunity/{url_quote(opp_id)}?fields={','.join(fields)}"
        validate_request_origin(url, http_config)
        response = await execute_http_request("GET", url, http_config=http_config, headers=headers)
        data = json.loads(response.body) if response.body else {}
        return data, response.provider_request_id, response.status_code

    async def _update_opportunity(
        self, http_config: ConnectorHTTPConfig, headers: dict, api_version: str, params: dict,
    ) -> tuple[Any, str | None, int | None]:
        opp_id = str(params.get("opportunity_id", ""))
        if not opp_id:
            raise ConnectorHTTPError("缺少 opportunity_id", code="invalid_params")

        allowed = WRITABLE_FIELDS["Opportunity"]
        update_fields = {k: v for k, v in params.items() if k in allowed and k != "opportunity_id"}
        if not update_fields:
            raise ConnectorHTTPError("没有可更新的字段", code="invalid_params")

        url = f"{http_config.base_url.rstrip('/')}/services/data/{api_version}/sobjects/Opportunity/{url_quote(opp_id)}"
        validate_request_origin(url, http_config)

        response = await execute_http_request(
            "PATCH", url, http_config=http_config,
            headers={**headers, "Content-Type": "application/json"},
            json_body=update_fields,
        )

        if response.status_code >= 400:
            raise ConnectorHTTPError(
                f"更新 Opportunity 失败: HTTP {response.status_code}",
                code="provider_error", status_code=response.status_code,
            )

        read_fields = DEFAULT_READ_FIELDS["Opportunity"]
        read_url = f"{http_config.base_url.rstrip('/')}/services/data/{api_version}/sobjects/Opportunity/{url_quote(opp_id)}?fields={','.join(read_fields)}"
        validate_request_origin(read_url, http_config)
        read_response = await execute_http_request("GET", read_url, http_config=http_config, headers=headers)
        data = json.loads(read_response.body) if read_response.body else {}
        return data, read_response.provider_request_id, read_response.status_code

    async def _upsert_account(
        self, http_config: ConnectorHTTPConfig, headers: dict, api_version: str, params: dict,
    ) -> tuple[Any, str | None, int | None]:
        external_id_field = str(params.get("external_id_field", "External_Id__c"))
        external_id_value = str(params.get("external_id_value", ""))
        if not external_id_value:
            raise ConnectorHTTPError("缺少 external_id_value", code="invalid_params")
        if not external_id_field.isidentifier():
            raise ConnectorHTTPError(f"非法 external_id_field: {external_id_field}", code="invalid_params")

        allowed = WRITABLE_FIELDS["Account"]
        upsert_fields = {k: v for k, v in params.items() if k in allowed and k not in ("external_id_field", "external_id_value")}
        if not upsert_fields:
            raise ConnectorHTTPError("没有可写入的字段", code="invalid_params")

        url = (
            f"{http_config.base_url.rstrip('/')}/services/data/{api_version}"
            f"/sobjects/Account/{url_quote(external_id_field)}/{url_quote(external_id_value)}"
        )
        validate_request_origin(url, http_config)

        response = await execute_http_request(
            "PATCH", url, http_config=http_config,
            headers={**headers, "Content-Type": "application/json"},
            json_body=upsert_fields,
        )

        if response.status_code >= 400:
            raise ConnectorHTTPError(
                f"upsert Account 失败: HTTP {response.status_code}",
                code="provider_error", status_code=response.status_code,
            )

        result_data = json.loads(response.body) if response.body else {}
        record_id = result_data.get("id", "")
        if record_id:
            read_fields = DEFAULT_READ_FIELDS["Account"]
            read_url = f"{http_config.base_url.rstrip('/')}/services/data/{api_version}/sobjects/Account/{url_quote(record_id)}?fields={','.join(read_fields)}"
            validate_request_origin(read_url, http_config)
            read_response = await execute_http_request("GET", read_url, http_config=http_config, headers=headers)
            result_data = json.loads(read_response.body) if read_response.body else {}
            return result_data, read_response.provider_request_id, read_response.status_code

        return result_data, response.provider_request_id, response.status_code

    async def probe(
        self,
        *,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
        healthcheck_operation_slug: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"network": False, "auth": False, "operation": False}
        try:
            access_token = await self._get_access_token(http_config, credentials)
            result["network"] = True
            result["auth"] = True
        except ConnectorHTTPError as exc:
            result["error"] = f"认证失败: {exc}"
            return result
        except Exception as exc:
            result["error"] = f"连接失败: {exc}"
            return result

        try:
            api_version = _extract_api_version(http_config)
            versions_url = f"{http_config.base_url.rstrip('/')}/services/data/{api_version}/sobjects/Account/describe"
            validate_request_origin(versions_url, http_config)
            response = await execute_http_request(
                "GET", versions_url,
                http_config=http_config,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code < 400:
                result["operation"] = True
            else:
                result["operation"] = False
                result["operation_error"] = f"Account describe 失败: HTTP {response.status_code}"
        except Exception as exc:
            result["operation_error"] = str(exc)[:500]

        return result


def _extract_api_version(http_config: ConnectorHTTPConfig) -> str:
    """从 http_config 原始配置获取 api_version；默认 v59.0。"""
    return http_config.raw_config.get("api_version", "v59.0")


register_adapter("salesforce", SalesforceAdapter)
