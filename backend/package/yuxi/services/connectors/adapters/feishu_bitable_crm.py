"""飞书多维表格 CRM 适配器 — 基于多维表格记录 API 的 CRM 操作。

使用企业自建应用 tenant_access_token 认证；
操作绑定配置的 app_token、table_id 和字段映射。
预置操作：query_customer、get_customer、create_customer、update_customer、
query_opportunity、create_opportunity、update_opportunity。
"""

from __future__ import annotations

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
    execute_http_request,
    validate_request_origin,
)
from yuxi.services.connectors.registry import register_adapter
from yuxi.services.connectors.schemas import apply_response_mapping
from yuxi.utils import logger

FEISHU_BASE_URL = "https://open.feishu.cn"

CUSTOMER_DEFAULT_FIELDS = ["客户名称", "行业", "规模", "联系方式", "负责人", "状态"]
OPPORTUNITY_DEFAULT_FIELDS = ["商机名称", "金额", "阶段", "关联客户", "预计成交日期", "负责人"]


class FeishuBitableCRMAdapter(BaseConnectorAdapter):
    """飞书多维表格 CRM 适配器。

    通过 tenant_access_token 访问多维表格记录 API；
    操作绑定管理员配置的 app_token、table_id 和字段映射。
    """

    connector_type: str = "feishu_bitable_crm"

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "app_token": {"type": "string", "description": "多维表格 app_token"},
                "customer_table_id": {"type": "string", "description": "客户表 table_id"},
                "opportunity_table_id": {"type": "string", "description": "商机表 table_id"},
                "customer_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "客户字段映射：逻辑名 → 飞书 field ID",
                },
                "opportunity_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "商机字段映射：逻辑名 → 飞书 field ID",
                },
                "customer_business_key_field": {"type": "string"},
                "opportunity_business_key_field": {"type": "string"},
                "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 120},
                "max_response_bytes": {"type": "integer", "minimum": 1024, "maximum": 10485760},
                "concurrency_limit": {"type": "integer", "minimum": 1, "maximum": 32},
            },
            "required": ["app_token", "customer_table_id", "opportunity_table_id"],
        }

    @classmethod
    def credential_keys(cls) -> list[str]:
        return ["app_id", "app_secret"]

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        return {"read": True, "write": True}

    async def _get_tenant_access_token(
        self,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
    ) -> str:
        """获取 tenant_access_token。"""
        app_id = credentials.get("app_id", b"").decode("utf-8")
        app_secret = credentials.get("app_secret", b"").decode("utf-8")
        if not app_id or not app_secret:
            raise ConnectorHTTPError("飞书需要 app_id 和 app_secret", code="credential_invalid")

        token_url = f"{FEISHU_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
        validate_request_origin(token_url, http_config)

        response = await execute_http_request(
            "POST", token_url, http_config=http_config,
            headers={"Content-Type": "application/json"},
            json_body={"app_id": app_id, "app_secret": app_secret},
        )

        if response.status_code != 200:
            raise ConnectorHTTPError(
                f"飞书 token 获取失败: HTTP {response.status_code}",
                code="credential_invalid", status_code=response.status_code,
            )

        try:
            data = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ConnectorHTTPError(f"token 响应解析失败: {exc}", code="provider_error")

        if data.get("code", -1) != 0:
            raise ConnectorHTTPError(
                f"飞书 token 获取失败: code={data.get('code')}, msg={data.get('msg', '')}",
                code="credential_invalid",
            )

        token = data.get("tenant_access_token", "")
        if not token:
            raise ConnectorHTTPError("token 响应缺少 tenant_access_token", code="credential_invalid")
        return token

    def _get_table_id(self, config: dict, record_type: str) -> str:
        if record_type == "customer":
            table_id = config.get("customer_table_id", "")
        elif record_type == "opportunity":
            table_id = config.get("opportunity_table_id", "")
        else:
            raise ConnectorHTTPError(f"未知记录类型: {record_type}", code="invalid_params")
        if not table_id:
            raise ConnectorHTTPError(f"未配置 {record_type} 的 table_id", code="invalid_params")
        return table_id

    def _get_field_mapping(self, config: dict, record_type: str) -> dict[str, str]:
        if record_type == "customer":
            return config.get("customer_fields") or {}
        if record_type == "opportunity":
            return config.get("opportunity_fields") or {}
        return {}

    def _map_params_to_fields(
        self, params: dict, field_mapping: dict[str, str], allowed_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """将逻辑参数名映射到飞书 field ID。"""
        fields: dict[str, Any] = {}
        for key, value in params.items():
            if allowed_keys is not None and key not in allowed_keys:
                continue
            field_id = field_mapping.get(key, key)
            fields[field_id] = value
        return fields

    async def _bitable_request(
        self,
        method: str,
        path: str,
        http_config: ConnectorHTTPConfig,
        token: str,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict, str | None, int]:
        url = f"{FEISHU_BASE_URL}/open-apis/bitable{path}"
        validate_request_origin(url, http_config)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = await execute_http_request(
            method, url, http_config=http_config,
            headers=headers, json_body=json_body, params=params,
        )
        data = json.loads(response.body) if response.body else {}
        if data.get("code", -1) != 0:
            raise ConnectorHTTPError(
                f"飞书 API 错误: code={data.get('code')}, msg={data.get('msg', '')}",
                code="provider_error", status_code=response.status_code,
            )
        return data, response.provider_request_id, response.status_code

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
            token = await self._get_tenant_access_token(http_config, credentials)
            app_token = raw_config.get("app_token", "")
            if not app_token:
                raise ConnectorHTTPError("缺少 app_token 配置", code="invalid_params")

            result_data: Any = None
            provider_request_id: str | None = None
            response_status: int | None = None
            op_slug = operation.slug

            if op_slug == "query_customer":
                result_data, provider_request_id, response_status = await self._query_records(
                    http_config, token, app_token, raw_config, "customer", params,
                )
            elif op_slug == "get_customer":
                result_data, provider_request_id, response_status = await self._get_record(
                    http_config, token, app_token, raw_config, "customer", params,
                )
            elif op_slug == "create_customer":
                result_data, provider_request_id, response_status = await self._create_record(
                    http_config, token, app_token, raw_config, "customer", params,
                )
            elif op_slug == "update_customer":
                result_data, provider_request_id, response_status = await self._update_record(
                    http_config, token, app_token, raw_config, "customer", params,
                )
            elif op_slug == "query_opportunity":
                result_data, provider_request_id, response_status = await self._query_records(
                    http_config, token, app_token, raw_config, "opportunity", params,
                )
            elif op_slug == "create_opportunity":
                result_data, provider_request_id, response_status = await self._create_record(
                    http_config, token, app_token, raw_config, "opportunity", params,
                )
            elif op_slug == "update_opportunity":
                result_data, provider_request_id, response_status = await self._update_record(
                    http_config, token, app_token, raw_config, "opportunity", params,
                )
            else:
                raise ConnectorHTTPError(f"不支持的操作: {op_slug}", code="invalid_params")

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
            logger.warning(f"feishu_bitable_crm 执行异常: {exc}")
            return ConnectorResult(
                success=False, error_code="execution_error",
                error_message=str(exc)[:500], remote_outcome="unknown",
                duration_ms=duration_ms,
            )

    async def _query_records(
        self,
        http_config: ConnectorHTTPConfig,
        token: str,
        app_token: str,
        config: dict,
        record_type: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        table_id = self._get_table_id(config, record_type)
        query_params: dict[str, Any] = {}
        page_size = min(int(params.get("page_size", 20)), 500)
        query_params["page_size"] = page_size
        if params.get("page_token"):
            query_params["page_token"] = str(params["page_token"])

        path = f"/v1/apps/{app_token}/tables/{table_id}/records"
        data, req_id, status = await self._bitable_request(
            "GET", path, http_config, token, params=query_params,
        )
        return data.get("data", {}), req_id, status

    async def _get_record(
        self,
        http_config: ConnectorHTTPConfig,
        token: str,
        app_token: str,
        config: dict,
        record_type: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        table_id = self._get_table_id(config, record_type)
        record_id = str(params.get("record_id", ""))
        if not record_id:
            raise ConnectorHTTPError("缺少 record_id", code="invalid_params")

        path = f"/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        data, req_id, status = await self._bitable_request("GET", path, http_config, token)
        return data.get("data", {}).get("record", {}), req_id, status

    async def _create_record(
        self,
        http_config: ConnectorHTTPConfig,
        token: str,
        app_token: str,
        config: dict,
        record_type: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        table_id = self._get_table_id(config, record_type)
        field_mapping = self._get_field_mapping(config, record_type)

        skip_keys = {"record_id", "page_size", "page_token"}
        fields = self._map_params_to_fields(params, field_mapping, allowed_keys=None)
        fields = {k: v for k, v in fields.items() if k not in skip_keys}
        if not fields:
            raise ConnectorHTTPError("没有可写入的字段", code="invalid_params")

        path = f"/v1/apps/{app_token}/tables/{table_id}/records"
        data, req_id, status = await self._bitable_request(
            "POST", path, http_config, token, json_body={"fields": fields},
        )

        record = data.get("data", {}).get("record", {})
        new_record_id = record.get("record_id", "")

        if new_record_id:
            read_path = f"/v1/apps/{app_token}/tables/{table_id}/records/{new_record_id}"
            read_data, read_req_id, read_status = await self._bitable_request(
                "GET", read_path, http_config, token,
            )
            return read_data.get("data", {}).get("record", {}), read_req_id, read_status

        return record, req_id, status

    async def _update_record(
        self,
        http_config: ConnectorHTTPConfig,
        token: str,
        app_token: str,
        config: dict,
        record_type: str,
        params: dict,
    ) -> tuple[Any, str | None, int | None]:
        table_id = self._get_table_id(config, record_type)
        record_id = str(params.get("record_id", ""))
        if not record_id:
            raise ConnectorHTTPError("缺少 record_id", code="invalid_params")

        field_mapping = self._get_field_mapping(config, record_type)
        skip_keys = {"record_id", "page_size", "page_token"}
        fields = self._map_params_to_fields(params, field_mapping, allowed_keys=None)
        fields = {k: v for k, v in fields.items() if k not in skip_keys}
        if not fields:
            raise ConnectorHTTPError("没有可更新的字段", code="invalid_params")

        path = f"/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        data, req_id, status = await self._bitable_request(
            "PUT", path, http_config, token, json_body={"fields": fields},
        )

        read_path = f"/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        read_data, read_req_id, read_status = await self._bitable_request(
            "GET", read_path, http_config, token,
        )
        return read_data.get("data", {}).get("record", {}), read_req_id, read_status

    async def probe(
        self,
        *,
        http_config: ConnectorHTTPConfig,
        credentials: dict[str, bytes],
        healthcheck_operation_slug: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"network": False, "auth": False, "operation": False}

        try:
            token = await self._get_tenant_access_token(http_config, credentials)
            result["network"] = True
            result["auth"] = True
        except ConnectorHTTPError as exc:
            result["error"] = f"认证失败: {exc}"
            return result
        except Exception as exc:
            result["error"] = f"连接失败: {exc}"
            return result

        try:
            raw_config = http_config.raw_config
            app_token = raw_config.get("app_token", "")
            customer_table_id = raw_config.get("customer_table_id", "")

            if app_token and customer_table_id:
                path = f"/v1/apps/{app_token}/tables/{customer_table_id}/records?page_size=1"
                data, _, status = await self._bitable_request("GET", path, http_config, token)
                if status < 400:
                    result["operation"] = True
                else:
                    result["operation"] = False
                    result["operation_error"] = f"表访问失败: HTTP {status}"
            else:
                result["operation"] = False
                result["operation_error"] = "缺少 app_token 或 table_id 配置"

        except Exception as exc:
            result["operation_error"] = str(exc)[:500]

        return result


register_adapter("feishu_bitable_crm", FeishuBitableCRMAdapter)
