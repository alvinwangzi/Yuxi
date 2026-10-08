"""飞书多维表格 CRM 适配器 — 基于多维表格记录 API 的 CRM 操作。

使用企业自建应用 tenant_access_token 认证；
操作绑定配置的 app_token、table_id 和字段映射。
预置操作：query_customer、get_customer、create_customer、update_customer、
query_opportunity、create_opportunity、update_opportunity。
"""

from __future__ import annotations

import time
import asyncio
from typing import Any
from urllib.parse import urlsplit

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
from yuxi.services.connectors.schemas import ConnectorSchemaError, apply_response_mapping, ensure_result_budget
from yuxi.services.connectors.feishu_fields import SUPPORTED_FIELD_TYPES, validate_field_value
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
    def standard_operations(cls, config: dict) -> list[dict]:
        """按当前字段映射生成可落库的标准操作。"""
        from yuxi.services.connectors.standard_operations import feishu_operations

        return feishu_operations(config)

    @classmethod
    def config_schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "app_token": {"type": "string", "pattern": "^[A-Za-z0-9_-]+$", "description": "多维表格 app_token"},
                "customer_table_id": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9_-]+$",
                    "description": "客户表 table_id",
                },
                "opportunity_table_id": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9_-]+$",
                    "description": "商机表 table_id",
                },
                "customer_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "客户字段映射：逻辑名 → 飞书字段名称或 field ID",
                },
                "opportunity_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "商机字段映射：逻辑名 → 飞书 field ID",
                },
                "customer_field_types": {
                    "type": "object",
                    "additionalProperties": {"type": "integer", "enum": list(SUPPORTED_FIELD_TYPES)},
                },
                "opportunity_field_types": {
                    "type": "object",
                    "additionalProperties": {"type": "integer", "enum": list(SUPPORTED_FIELD_TYPES)},
                },
                "customer_business_key_field": {"type": "string"},
                "opportunity_business_key_field": {"type": "string"},
                "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 120},
                "max_response_bytes": {"type": "integer", "minimum": 1024, "maximum": 10485760},
                "concurrency_limit": {"type": "integer", "minimum": 1, "maximum": 32},
            },
            "required": ["app_token"],
        }

    @classmethod
    def credential_keys(cls) -> list[str]:
        return ["app_id", "app_secret"]

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
            raw_config = http_config.raw_config
            token = await self._get_tenant_access_token(http_config, credentials)
            authenticated = True
            app_token = raw_config.get("app_token", "")
            if not app_token:
                raise ConnectorHTTPError("缺少 app_token 配置", code="invalid_params")

            result_data: Any = None
            provider_request_id: str | None = None
            response_status: int | None = None
            op_slug = operation.slug

            if op_slug == "query_customer":
                result_data, provider_request_id, response_status = await self._query_records(
                    http_config,
                    token,
                    app_token,
                    raw_config,
                    "customer",
                    params,
                )
            elif op_slug == "get_customer":
                result_data, provider_request_id, response_status = await self._get_record(
                    http_config,
                    token,
                    app_token,
                    raw_config,
                    "customer",
                    params,
                )
            elif op_slug == "create_customer":
                result_data, provider_request_id, response_status = await self._create_record(
                    http_config,
                    token,
                    app_token,
                    raw_config,
                    "customer",
                    params,
                )
            elif op_slug == "update_customer":
                result_data, provider_request_id, response_status = await self._update_record(
                    http_config,
                    token,
                    app_token,
                    raw_config,
                    "customer",
                    params,
                )
            elif op_slug == "query_opportunity":
                result_data, provider_request_id, response_status = await self._query_records(
                    http_config,
                    token,
                    app_token,
                    raw_config,
                    "opportunity",
                    params,
                )
            elif op_slug == "create_opportunity":
                result_data, provider_request_id, response_status = await self._create_record(
                    http_config,
                    token,
                    app_token,
                    raw_config,
                    "opportunity",
                    params,
                )
            elif op_slug == "update_opportunity":
                result_data, provider_request_id, response_status = await self._update_record(
                    http_config,
                    token,
                    app_token,
                    raw_config,
                    "opportunity",
                    params,
                )
            else:
                raise ConnectorHTTPError(f"不支持的操作: {op_slug}", code="invalid_params")

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
                    if not authenticated
                    or getattr(exc, "before_write", False)
                    or exc.code in {"invalid_params", "unsafe_target", "credential_invalid"}
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
            logger.warning("feishu_bitable_crm 协议执行异常")
            return ConnectorResult(
                success=False,
                error_code="execution_error",
                error_message="provider_protocol_error",
                remote_outcome="unknown" if operation.operation_type == "write" else "failed",
                duration_ms=duration_ms,
            )

    async def discover_metadata(self, http_config, credentials) -> dict:
        """管理员只读发现同一 Base 的表和已选表字段，整体遵守一个预算。"""
        async with asyncio.timeout(http_config.timeout_seconds):
            token = await self._get_tenant_access_token(http_config, credentials)
            app = http_config.raw_config["app_token"]
            tables = await self._list_metadata(self._metadata_path(app), http_config, token)
            table_ids = {table["table_id"] for table in tables}
            fields = {}
            for kind in ("customer", "opportunity"):
                table_id = http_config.raw_config.get(kind + "_table_id")
                if not table_id:
                    continue
                if table_id not in table_ids:
                    raise ConnectorHTTPError("配置表不属于当前 Base", code="invalid_configuration")
                fields[table_id] = await self._list_metadata(self._metadata_path(app, table_id), http_config, token)
            return {"tables": [{"table_id": t["table_id"], "name": t["name"]} for t in tables], "fields": fields}

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
        if set(params) - {"page_size", "page_token", "filters"}:
            raise ConnectorHTTPError("不支持的查询参数", code="invalid_params")
        filters = params.get("filters", {})
        mapping = self._get_field_mapping(config, record_type)
        if (
            not isinstance(filters, dict)
            or len(filters) > 16
            or set(filters) - set(mapping)
            or any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in filters.values())
        ):
            raise ConnectorHTTPError("不支持的查询过滤", code="invalid_params")
        query_params: dict[str, Any] = {}
        page_size = min(int(params.get("page_size", 20)), 500)
        query_params["page_size"] = page_size
        if params.get("page_token"):
            query_params["page_token"] = str(params["page_token"])

        path = f"/v1/apps/{app_token}/tables/{table_id}/records"
        mapping = await self._resolve_field_mapping(config, record_type, http_config, token, app_token, table_id)
        if filters:
            conditions = [
                {"field_name": mapping[key], "operator": "is", "value": [value]} for key, value in filters.items()
            ]
            data, req_id, status = await self._bitable_request(
                "POST",
                path + "/search",
                http_config,
                token,
                json_body={"filter": {"conjunction": "and", "conditions": conditions}},
                params=query_params,
            )
            return self._project_page(data.get("data", {}), mapping, http_config.max_response_bytes), req_id, status
        data, req_id, status = await self._bitable_request(
            "GET",
            path,
            http_config,
            token,
            params=query_params,
        )
        return self._project_page(data.get("data", {}), mapping, http_config.max_response_bytes), req_id, status

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

        path = self._record_path(app_token, table_id, record_id)

        data, req_id, status = await self._bitable_request("GET", path, http_config, token)
        record = data.get("data", {}).get("record", {})
        if not isinstance(record, dict) or record.get("record_id") != record_id:
            raise ConnectorHTTPError("provider_record_identity_mismatch", code="provider_error")
        mapping = await self._resolve_field_mapping(config, record_type, http_config, token, app_token, table_id)
        return self._project_record(record, set(mapping.values())), req_id, status

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

        fields = await self._validated_write_fields(
            params, config, record_type, http_config, token, app_token, table_id
        )
        if not fields:
            raise ConnectorHTTPError("没有可写入的字段", code="invalid_params")

        path = f"/v1/apps/{app_token}/tables/{table_id}/records"
        data, req_id, status = await self._bitable_request(
            "POST",
            path,
            http_config,
            token,
            json_body={"fields": fields},
        )

        record = data.get("data", {}).get("record", {})
        new_record_id = record.get("record_id", "")

        try:
            read_path = self._record_path(app_token, table_id, new_record_id) if new_record_id else ""
        except ConnectorHTTPError:
            raise ConnectorReadbackError(
                response_status=status, provider_request_id=req_id, provider_evidence=data
            ) from None
        return await self._read_written_record(
            read_path, http_config, token, data, req_id, status, new_record_id, set(fields)
        )

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
        path = self._record_path(app_token, table_id, record_id)

        fields = await self._validated_write_fields(
            params, config, record_type, http_config, token, app_token, table_id
        )
        if not fields:
            raise ConnectorHTTPError("没有可更新的字段", code="invalid_params")

        data, req_id, status = await self._bitable_request(
            "PUT",
            path,
            http_config,
            token,
            json_body={"fields": fields},
        )

        return await self._read_written_record(path, http_config, token, data, req_id, status, record_id, set(fields))

    async def _validated_write_fields(self, params, config, record_type, http_config, token, app_token, table_id):
        """发送前以真实字段目录校验类型；预检错误明确没有发送业务写。"""
        try:
            descriptors = await self._resolve_field_mapping(
                config, record_type, http_config, token, app_token, table_id, with_types=True
            )
            if set(params) - set(descriptors) - {"record_id"}:
                raise ConnectorHTTPError("未配置的写字段", code="invalid_params")
            fields = {}
            for key, value in params.items():
                if key == "record_id":
                    continue
                descriptor = descriptors[key]
                validate_field_value(value, descriptor)
                fields[descriptor["field_name"]] = value
            return fields
        except ConnectorHTTPError as exc:
            exc.before_write = True
            raise

    async def _resolve_field_mapping(
        self, config, record_type, http_config, token, app_token, table_id, *, with_types=False
    ):
        """字段 ID 或旧名称都须匹配实际目录，不能将旧名称直接透传。"""
        rows = await self._list_metadata(self._metadata_path(app_token, table_id), http_config, token)
        catalog = {row["field_id"]: row for row in rows}
        names = {row["field_name"]: row for row in rows}
        resolved = {}
        for key, value in self._get_field_mapping(config, record_type).items():
            descriptor = catalog.get(value) or names.get(value)
            if descriptor is None:
                raise ConnectorHTTPError("配置字段不存在", code="invalid_params")
            resolved[key] = descriptor if with_types else descriptor["field_name"]
        return resolved

    async def _list_metadata(self, path, http_config, token):
        """目录最多十页一千项，校验所有游标与必要结构。"""
        rows = []
        page_token = None
        seen = set()
        for _ in range(10):
            data, _, _ = await self._bitable_request(
                "GET", path, http_config, token, params={"page_size": 100, "page_token": page_token}
            )
            page = data.get("data")
            if (
                not isinstance(page, dict)
                or not isinstance(page.get("items"), list)
                or type(page.get("has_more")) is not bool
            ):
                raise ConnectorHTTPError("元数据响应结构无效", code="provider_error")
            for item in page["items"]:
                if not isinstance(item, dict):
                    raise ConnectorHTTPError("元数据项无效", code="provider_error")
                required = ("field_id", "field_name") if path.endswith("/fields") else ("table_id", "name")
                if any(not isinstance(item.get(key), str) or not 1 <= len(item[key]) <= 1000 for key in required):
                    raise ConnectorHTTPError("元数据标识无效", code="provider_error")
                if path.endswith("/fields"):
                    if type(item.get("type")) is not int:
                        raise ConnectorHTTPError("字段类型无效", code="provider_error")
                    raw_property = item.get("property") or {}
                    if not isinstance(raw_property, dict):
                        raise ConnectorHTTPError("字段属性无效", code="provider_error")
                    options = raw_property.get("options", [])
                    if (
                        not isinstance(options, list)
                        or len(options) > 1000
                        or any(
                            not isinstance(o, dict)
                            or not isinstance(o.get("name"), str)
                            or not 1 <= len(o["name"]) <= 256
                            for o in options
                        )
                    ):
                        raise ConnectorHTTPError("字段选项无效", code="provider_error")
                    item = {
                        **{key: item[key] for key in ("field_id", "field_name", "type")},
                        "property": {"options": [{"name": o["name"]} for o in options]},
                    }
                rows.append(item)
            if len(rows) > 1000:
                raise ConnectorHTTPError("元数据超过上限", code="response_too_large")
            if not page["has_more"]:
                return rows
            page_token = page.get("page_token")
            if not isinstance(page_token, str) or not 1 <= len(page_token) <= 256 or page_token in seen:
                raise ConnectorHTTPError("元数据游标无效", code="provider_error")
            seen.add(page_token)
        raise ConnectorHTTPError("元数据分页超过上限", code="provider_error")

    @staticmethod
    def _metadata_path(app_token, table_id=None):
        """同一 app 的表/字段资源路径只在 owning URL boundary 拼装。"""
        template = "/v1/apps/{{app_token}}/tables" + ("/{{table_id}}/fields" if table_id is not None else "")
        return urlsplit(build_full_url(FEISHU_BASE_URL, template, {"app_token": app_token, "table_id": table_id})).path

    @staticmethod
    def _record_path(app_token, table_id, record_id):
        """不可信记录 ID 不能经多重编码改变 table/record 路径边界。"""
        return urlsplit(
            build_full_url(
                FEISHU_BASE_URL,
                "/v1/apps/{{app_token}}/tables/{{table_id}}/records/{{record_id}}",
                {"app_token": app_token, "table_id": table_id, "record_id": record_id},
            )
        ).path

    async def _read_written_record(self, path, config, token, receipt, request_id, status, record_id, allowed_fields):
        """已确认写成功后，读回失败只影响本地结果，不抹除 receipt。"""
        try:
            if not record_id:
                raise ValueError("provider_record_id_missing")
            data, read_id, read_status = await self._bitable_request("GET", path, config, token)
            record = data.get("data", {}).get("record", {})
            if record.get("record_id") != record_id:
                raise ValueError("provider_record_binding_invalid")
            return self._project_record(record, allowed_fields), read_id, read_status
        except Exception:
            raise ConnectorReadbackError(
                response_status=status, provider_request_id=request_id, provider_evidence=receipt
            ) from None

    def _project_page(self, page, mapping, budget):
        """只交付配置字段与有界分页，不能将原始私有列注入模型。"""
        if not isinstance(page, dict) or type(page.get("has_more")) is not bool:
            raise ConnectorHTTPError("provider_query_page_invalid", code="provider_error")
        token = page.get("page_token")
        if ("page_token" in page and (not isinstance(token, str) or len(token) > 256)) or (
            page["has_more"] and not token
        ):
            raise ConnectorHTTPError("provider_query_cursor_invalid", code="provider_error")
        items = page.get("items")
        if not isinstance(items, list) or len(items) > 500:
            raise ConnectorHTTPError("记录分页无效", code="provider_error")
        output = {key: page[key] for key in ("has_more", "page_token") if key in page}
        output["items"] = [self._project_record(record, set(mapping.values())) for record in items]
        ensure_result_budget(output, budget)
        return output

    def _project_record(self, record, allowed_fields):
        """字段输出拥有明确白名单，记录身份不从邻近结果猜测。"""
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("record_id"), str)
            or not 1 <= len(record["record_id"]) <= 256
        ):
            raise ConnectorHTTPError("记录响应无效", code="provider_error")
        fields = record.get("fields", {})
        if not isinstance(fields, dict):
            raise ConnectorHTTPError("记录字段响应无效", code="provider_error")
        return {
            "record_id": record["record_id"],
            "fields": {key: value for key, value in fields.items() if key in allowed_fields},
        }

    def _map_params_to_fields(
        self,
        params: dict,
        field_mapping: dict[str, str],
        allowed_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """将逻辑参数映射到当前字段名称，不改写原始 JSON 类型。"""
        if set(params) - set(field_mapping) - {"record_id", "page_size", "page_token"}:
            raise ConnectorHTTPError("字段不在当前配置中", code="invalid_params")
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
            method,
            url,
            http_config=http_config,
            headers=headers,
            json_body=json_body,
            params=params,
        )
        data = parse_provider_json(response.body) if response.body else {}
        if not isinstance(data, dict) or type(data.get("code")) is not int:
            raise ConnectorHTTPError("provider_business_code_invalid", code="provider_error")
        if response.status_code >= 400 or data.get("code", -1) != 0:
            raise ConnectorHTTPError(
                f"飞书 API 错误: code={data.get('code')}, msg={data.get('msg', '')}",
                code="provider_error",
                status_code=response.status_code,
            )
        return data, response.provider_request_id, response.status_code

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
            "POST",
            token_url,
            http_config=http_config,
            headers={"Content-Type": "application/json"},
            json_body={"app_id": app_id, "app_secret": app_secret},
        )

        if response.status_code != 200:
            raise ConnectorHTTPError(
                f"飞书 token 获取失败: HTTP {response.status_code}",
                code="credential_invalid",
                status_code=response.status_code,
            )

        data = parse_provider_json(response.body)
        if not isinstance(data, dict) or type(data.get("code")) is not int:
            raise ConnectorHTTPError("provider_token_invalid", code="credential_invalid")
        if response.status_code >= 400 or data.get("code", -1) != 0:
            raise ConnectorHTTPError(
                f"飞书 token 获取失败: code={data.get('code')}, msg={data.get('msg', '')}",
                code="credential_invalid",
            )

        token = data.get("tenant_access_token", "")
        if not isinstance(token, str) or not token:
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
