"""Salesforce 适配器 — Server-to-server client credentials 认证。

通过 OAuth client credentials 流程获取 access token，
支持 SOQL 查询（字段白名单）和受限字段更新。
预置操作：query_customer、get_customer、get_opportunity、update_opportunity、upsert_customer。
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
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
    ConnectorReadbackError,
    build_full_url,
    execute_http_request,
    parse_provider_json,
    validate_request_origin,
)
from yuxi.services.connectors.schemas import ConnectorSchemaError, apply_response_mapping
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
    def standard_operations(cls, config: dict) -> list[dict]:
        """声明固定 Salesforce 对象和字段操作。"""
        from yuxi.services.connectors.standard_operations import salesforce_operations

        return salesforce_operations()

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "format": "uri", "description": "Salesforce My Domain URL"},
                "api_version": {"type": "string", "pattern": "^v\\d+\\.\\d+$"},
                "account_external_id_field": {
                    "type": "string",
                    "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
                    "maxLength": 128,
                },
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
        authenticated = False
        try:
            access_token, instance_url = await self._get_access_token(http_config, credentials)
            http_config = replace(http_config, base_url=instance_url)
            authenticated = True
            auth_headers = {"Authorization": f"Bearer {access_token}"}
            api_version = _extract_api_version(http_config)

            result_data: Any = None
            provider_request_id: str | None = None
            response_status: int | None = None

            op_slug = operation.slug

            if op_slug == "query_customer":
                result_data, provider_request_id, response_status = await self._query_accounts(
                    http_config,
                    auth_headers,
                    api_version,
                    params,
                )
            elif op_slug == "get_customer":
                result_data, provider_request_id, response_status = await self._get_account(
                    http_config,
                    auth_headers,
                    api_version,
                    params,
                )
            elif op_slug == "get_opportunity":
                result_data, provider_request_id, response_status = await self._get_opportunity(
                    http_config,
                    auth_headers,
                    api_version,
                    params,
                )
            elif op_slug == "update_opportunity":
                result_data, provider_request_id, response_status = await self._update_opportunity(
                    http_config,
                    auth_headers,
                    api_version,
                    params,
                )
            elif op_slug == "upsert_customer":
                result_data, provider_request_id, response_status = await self._upsert_account(
                    http_config,
                    auth_headers,
                    api_version,
                    params,
                )
            else:
                raise ConnectorHTTPError("不支持的操作", code="invalid_params")

            duration_ms = (time.monotonic() - start_time) * 1000
            try:
                mapped = (
                    apply_response_mapping(
                        result_data, operation.response_mapping, max_bytes=http_config.max_response_bytes
                    )
                    if operation.response_mapping is not None
                    else None
                )
            except ConnectorSchemaError:
                return ConnectorResult(
                    success=False,
                    error_code="mapping_error",
                    error_message="mapping_error",
                    remote_outcome="succeeded",
                    response_status=response_status,
                    provider_request_id=provider_request_id,
                    provider_evidence=result_data,
                    duration_ms=duration_ms,
                )

            return ConnectorResult(
                success=True,
                data=result_data,
                provider_request_id=provider_request_id,
                response_status=response_status,
                duration_ms=duration_ms,
                mapped_result=mapped,
                remote_outcome="succeeded",
            )

        except ConnectorHTTPError as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            if isinstance(exc, ConnectorReadbackError):
                return ConnectorResult(
                    success=False,
                    error_code=exc.code,
                    error_message=exc.code,
                    remote_outcome="succeeded",
                    response_status=exc.status_code,
                    provider_request_id=exc.provider_request_id,
                    provider_evidence=exc.provider_evidence,
                    duration_ms=duration_ms,
                )
            return ConnectorResult(
                success=False,
                error_code=exc.code,
                error_message=exc.code,
                remote_outcome=(
                    "not_sent"
                    if not authenticated or exc.code in {"invalid_params", "unsafe_target", "credential_invalid"}
                    else "unknown"
                    if operation.operation_type == "write"
                    and (
                        exc.code in {"timeout", "response_too_large"}
                        or exc.status_code is None
                        and exc.code == "provider_error"
                        or exc.status_code is not None
                        and exc.status_code >= 500
                    )
                    else "failed"
                ),
                response_status=exc.status_code,
                duration_ms=duration_ms,
            )
        except Exception:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning("salesforce 协议执行异常")
            return ConnectorResult(
                success=False,
                error_code="execution_error",
                error_message="provider_protocol_error",
                remote_outcome="unknown" if operation.operation_type == "write" else "failed",
                duration_ms=duration_ms,
            )

    async def _get_access_token(
        self,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
    ) -> tuple[str, str]:
        """通过 client credentials 流程获取 access token。"""
        client_id = credentials.get("client_id", b"").decode("utf-8")
        client_secret = credentials.get("client_secret", b"").decode("utf-8")
        if not client_id or not client_secret:
            raise ConnectorHTTPError("Salesforce 需要 client_id 和 client_secret", code="credential_invalid")

        token_url = f"{http_config.base_url.rstrip('/')}/services/oauth2/token"
        validate_request_origin(token_url, http_config)

        body = (
            f"grant_type=client_credentials&client_id={url_quote(client_id)}&client_secret={url_quote(client_secret)}"
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

        token_data = parse_provider_json(response.body)
        if not isinstance(token_data, dict):
            raise ConnectorHTTPError("provider_token_invalid", code="credential_invalid")
        access_token = token_data.get("access_token", "")
        if not isinstance(access_token, str) or not access_token:
            raise ConnectorHTTPError("token 响应缺少 access_token", code="credential_invalid")

        instance_url = token_data.get("instance_url", "")
        if not isinstance(instance_url, str):
            raise ConnectorHTTPError("provider_instance_url_invalid", code="credential_invalid")
        if instance_url:
            validate_request_origin(instance_url, http_config)

        return access_token, instance_url or http_config.base_url

    async def _query_accounts(
        self,
        http_config: ConnectorHTTPConfig,
        headers: dict,
        api_version: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        fields = self._configured_fields(http_config, "Account")
        if set(params) - {"name", "industry", "page_size", "external_id_value"}:
            raise ConnectorHTTPError("不支持的客户查询参数", code="invalid_params")
        where_parts: list[str] = []
        if params.get("external_id_value"):
            field = http_config.raw_config.get("account_external_id_field", "")
            if not isinstance(field, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field):
                raise ConnectorHTTPError("外部业务键字段未配置", code="invalid_configuration")
            value = str(params["external_id_value"]).replace("\\", "\\\\").replace("'", "\\'")
            where_parts.append(f"{field} = '{value}'")
        if params.get("name"):
            name = str(params["name"]).replace("\\", "\\\\").replace("'", "\\'")
            where_parts.append(f"Name LIKE '{name}%'")
        if params.get("industry"):
            industry = str(params["industry"]).replace("\\", "\\\\").replace("'", "\\'")
            where_parts.append(f"Industry = '{industry}'")

        where_clause = " AND ".join(where_parts) if where_parts else None
        limit = min(int(params.get("page_size", 20)), 200)
        soql = self._build_soql("Account", fields, where_clause, limit)

        query_url = f"{http_config.base_url.rstrip('/')}/services/data/{api_version}/query?q={url_quote(soql)}"
        validate_request_origin(query_url, http_config)

        response = await execute_http_request("GET", query_url, http_config=http_config, headers=headers)
        self._require_success(response)
        data = parse_provider_json(response.body) if response.body else {}
        records = list(self._validated_query_page(data))
        self._check_query_budget({**data, "records": records}, http_config)
        seen = set()
        while not data.get("done", True):
            next_path = data.get("nextRecordsUrl")
            if (
                not isinstance(next_path, str)
                or not next_path.startswith(f"/services/data/{api_version}/query/")
                or next_path in seen
                or len(seen) >= 10
            ):
                raise ConnectorHTTPError("Salesforce 分页游标无效或超过上限", code="provider_error")
            seen.add(next_path)
            next_url = build_full_url(http_config.base_url, next_path, {})
            response = await execute_http_request("GET", next_url, http_config=http_config, headers=headers)
            self._require_success(response)
            data = parse_provider_json(response.body)
            records.extend(self._validated_query_page(data))
            self._check_query_budget({**data, "records": records}, http_config)
            if len(records) > 200:
                raise ConnectorHTTPError("Salesforce 查询记录超过上限", code="provider_error")
        data["records"] = records
        return data, response.provider_request_id, response.status_code

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

    async def _get_account(
        self,
        http_config: ConnectorHTTPConfig,
        headers: dict,
        api_version: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        account_id = str(params.get("account_id", ""))
        if not account_id:
            raise ConnectorHTTPError("缺少 account_id", code="invalid_params")
        fields = self._configured_fields(http_config, "Account")
        url = self._record_url(http_config, api_version, "Account", account_id) + "?fields=" + ",".join(fields)
        validate_request_origin(url, http_config)
        response = await execute_http_request("GET", url, http_config=http_config, headers=headers)
        self._require_success(response)
        data = parse_provider_json(response.body) if response.body else {}
        self._check_record_identity(data, expected_id=account_id)
        return data, response.provider_request_id, response.status_code

    async def _get_opportunity(
        self,
        http_config: ConnectorHTTPConfig,
        headers: dict,
        api_version: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        opp_id = str(params.get("opportunity_id", ""))
        if not opp_id:
            raise ConnectorHTTPError("缺少 opportunity_id", code="invalid_params")
        fields = self._configured_fields(http_config, "Opportunity")
        url = self._record_url(http_config, api_version, "Opportunity", opp_id) + "?fields=" + ",".join(fields)
        validate_request_origin(url, http_config)
        response = await execute_http_request("GET", url, http_config=http_config, headers=headers)
        self._require_success(response)
        data = parse_provider_json(response.body) if response.body else {}
        self._check_record_identity(data, expected_id=opp_id)
        return data, response.provider_request_id, response.status_code

    async def _update_opportunity(
        self,
        http_config: ConnectorHTTPConfig,
        headers: dict,
        api_version: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        opp_id = str(params.get("opportunity_id", ""))
        if not opp_id:
            raise ConnectorHTTPError("缺少 opportunity_id", code="invalid_params")

        read_fields = self._configured_fields(http_config, "Opportunity")
        allowed = self._configured_fields(http_config, "Opportunity", writable=True)
        if set(params) - set(allowed) - {"opportunity_id"}:
            raise ConnectorHTTPError("写字段不在白名单", code="invalid_params")
        update_fields = {k: v for k, v in params.items() if k in allowed and k != "opportunity_id"}
        if not update_fields:
            raise ConnectorHTTPError("没有可更新的字段", code="invalid_params")

        url = self._record_url(http_config, api_version, "Opportunity", opp_id)
        validate_request_origin(url, http_config)

        response = await execute_http_request(
            "PATCH",
            url,
            http_config=http_config,
            headers={**headers, "Content-Type": "application/json"},
            json_body=update_fields,
        )

        if response.status_code >= 400:
            raise ConnectorHTTPError(
                f"更新 Opportunity 失败: HTTP {response.status_code}",
                code="provider_error",
                status_code=response.status_code,
            )

        read_url = url + "?fields=" + ",".join(read_fields)
        validate_request_origin(read_url, http_config)
        return await self._read_written_record(read_url, http_config, headers, response, expected_id=opp_id)

    async def _upsert_account(
        self,
        http_config: ConnectorHTTPConfig,
        headers: dict,
        api_version: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        external_id_field = str(http_config.raw_config.get("account_external_id_field", ""))
        external_id_value = str(params.get("external_id_value", ""))
        if not external_id_value:
            raise ConnectorHTTPError("缺少 external_id_value", code="invalid_params")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", external_id_field):
            raise ConnectorHTTPError("管理员未配置合法外部键字段", code="invalid_configuration")

        read_fields = self._configured_fields(http_config, "Account")
        allowed = self._configured_fields(http_config, "Account", writable=True)
        if set(params) - set(allowed) - {"external_id_value"}:
            raise ConnectorHTTPError("写字段不在白名单", code="invalid_params")
        upsert_fields = {k: v for k, v in params.items() if k in allowed and k != "external_id_value"}
        if not upsert_fields:
            raise ConnectorHTTPError("没有可写入的字段", code="invalid_params")

        url = self._record_url(http_config, api_version, "Account", external_id_value, external_field=external_id_field)
        validate_request_origin(url, http_config)

        response = await execute_http_request(
            "PATCH",
            url,
            http_config=http_config,
            headers={**headers, "Content-Type": "application/json"},
            json_body=upsert_fields,
        )

        if response.status_code >= 400:
            raise ConnectorHTTPError(
                f"upsert Account 失败: HTTP {response.status_code}",
                code="provider_error",
                status_code=response.status_code,
            )

        read_fields = list(dict.fromkeys([*read_fields, external_id_field]))
        return await self._read_written_record(
            url + "?fields=" + ",".join(read_fields),
            http_config,
            headers,
            response,
            external_field=external_id_field,
            external_value=external_id_value,
        )

    @staticmethod
    def _record_url(config, version, sobject, record_id, *, external_field=None):
        """所有记录标识复用共享 segment 编码与多重解码路径拒绝。"""
        template = f"/services/data/{version}/sobjects/{sobject}/"
        params = {"record_id": record_id}
        if external_field is not None:
            template += "{{external_field}}/"
            params["external_field"] = external_field
        return build_full_url(config.base_url, template + "{{record_id}}", params)

    async def _read_written_record(
        self, url, config, headers, receipt, *, expected_id=None, external_field=None, external_value=None
    ):
        """确认成功的写 receipt 与后续读取失败不能互相覆盖。"""
        try:
            response = await execute_http_request("GET", url, http_config=config, headers=headers)
            self._require_success(response)
            data = parse_provider_json(response.body)
            self._check_record_identity(
                data, expected_id=expected_id, external_field=external_field, external_value=external_value
            )
            if receipt.body:
                acknowledged = parse_provider_json(receipt.body)
                if isinstance(acknowledged, dict) and acknowledged.get("id") is not None:
                    self._check_record_identity(data, expected_id=acknowledged["id"])
            return data, response.provider_request_id, response.status_code
        except Exception:
            raise ConnectorReadbackError(
                response_status=receipt.status_code,
                provider_request_id=receipt.provider_request_id,
                provider_evidence={
                    "status": receipt.status_code,
                    "body": receipt.body.decode("utf-8", errors="replace"),
                },
            ) from None

    @staticmethod
    def _validated_query_page(data):
        """查询页必须有明确列表、终止标志、总数与继续游标，首批同样受限。"""
        if not isinstance(data, dict) or type(data.get("done")) is not bool or type(data.get("totalSize")) is not int:
            raise ConnectorHTTPError("provider_query_page_invalid", code="provider_error")
        records = data.get("records")
        if (
            not isinstance(records, list)
            or len(records) > 200
            or data["totalSize"] < len(records)
            or any(not isinstance(record, dict) or not record for record in records)
        ):
            raise ConnectorHTTPError("provider_query_records_invalid", code="provider_error")
        cursor = data.get("nextRecordsUrl")
        if ("nextRecordsUrl" in data and (not isinstance(cursor, str) or len(cursor) > 2048)) or (
            not data["done"] and not cursor
        ):
            raise ConnectorHTTPError("provider_query_cursor_invalid", code="provider_error")
        return records

    @staticmethod
    def _check_query_budget(data, config):
        """分页业务投影遵守总输出预算，不能以单页合法代替合并结果合法。"""
        from yuxi.services.connectors.schemas import ensure_result_budget

        try:
            ensure_result_budget(data, config.max_response_bytes)
        except ConnectorSchemaError:
            raise ConnectorHTTPError("salesforce_result_too_large", code="response_too_large") from None

    @staticmethod
    def _check_record_identity(data, *, expected_id=None, external_field=None, external_value=None):
        """回查必须证明相同记录或相同外部业务键，模型与相邻记录不能补猜。"""
        if not isinstance(data, dict) or not isinstance(data.get("Id"), str) or not data["Id"]:
            raise ConnectorHTTPError("provider_record_missing", code="provider_error")
        if expected_id is not None and not _same_record_id(data["Id"], expected_id):
            raise ConnectorHTTPError("provider_record_identity_mismatch", code="provider_error")
        if external_field is not None and (
            type(data.get(external_field)) not in (str, int, float) or str(data[external_field]) != external_value
        ):
            raise ConnectorHTTPError("provider_external_identity_mismatch", code="provider_error")

    @staticmethod
    def _configured_fields(config, sobject, *, writable=False):
        """管理员对象/字段配置只能收窄标准白名单，不暗中扩大权限。"""
        if sobject not in config.raw_config.get("allowed_objects", ALLOWED_SOBJECTS):
            raise ConnectorHTTPError("对象不在白名单", code="invalid_params")
        defaults = WRITABLE_FIELDS if writable else DEFAULT_READ_FIELDS
        fields = config.raw_config.get("writable_fields" if writable else "read_fields", {}).get(
            sobject, defaults[sobject]
        )
        if not fields or not set(fields).issubset(defaults[sobject]):
            raise ConnectorHTTPError("字段不在白名单", code="invalid_params")
        return fields

    @staticmethod
    def _require_success(response) -> None:
        """对象、查询与回读统一拒绝错误响应，避免 4xx 成功投影。"""
        if response.status_code >= 400:
            raise ConnectorHTTPError("Salesforce API 拒绝请求", code="provider_error", status_code=response.status_code)


def _same_record_id(actual, expected) -> bool:
    """仅接受相同 ID 或校验后缀正确的 Salesforce 15/18 位等价形式。"""
    if not isinstance(expected, str):
        return False
    if actual == expected:
        return True
    short, long = (actual, expected) if len(actual) == 15 else (expected, actual)
    if len(short) != 15 or len(long) != 18 or not short.isascii() or not short.isalnum():
        return False
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    suffix = "".join(
        alphabet[sum(1 << index for index, char in enumerate(short[start : start + 5]) if char.isupper())]
        for start in (0, 5, 10)
    )
    return long == short + suffix


def _extract_api_version(http_config: ConnectorHTTPConfig) -> str:
    """从 http_config 原始配置获取 api_version；默认 v59.0。"""
    return http_config.raw_config.get("api_version", "v59.0")
