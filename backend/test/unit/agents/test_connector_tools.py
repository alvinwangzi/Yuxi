"""Agent 连接器工具生成单元测试。"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Windows 缺少 os.O_DIRECTORY，导致 yuxi.agents 导入链失败
if sys.platform == "win32":
    pytest.skip(
        "yuxi.agents 导入链依赖 Linux-only os.O_DIRECTORY",
        allow_module_level=True,
    )

from yuxi.agents.connectors.tools import (
    _build_args_schema,
    _format_tool_result,
    _sanitize_slug,
    get_connector_tools,
)


class TestSanitizeSlug:
    def test_hyphen_to_underscore(self):
        assert _sanitize_slug("my-connector") == "my_connector"

    def test_dot_to_underscore(self):
        assert _sanitize_slug("my.connector") == "my_connector"

    def test_truncation(self):
        long_slug = "a" * 100
        assert len(_sanitize_slug(long_slug)) == 40

    def test_mixed_characters(self):
        assert _sanitize_slug("crm-v2.0") == "crm_v2_0"


class TestBuildArgsSchema:
    def test_none_schema_returns_empty_model(self):
        model = _build_args_schema(None)
        instance = model()
        assert instance is not None

    def test_empty_schema_returns_empty_model(self):
        model = _build_args_schema({})
        instance = model()
        assert instance is not None

    def test_string_property(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "客户名称"}},
            "required": ["name"],
        }
        model = _build_args_schema(schema)
        instance = model(name="Acme")
        assert instance.name == "Acme"

    def test_integer_property(self):
        schema = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
        model = _build_args_schema(schema)
        instance = model(count=42)
        assert instance.count == 42

    def test_optional_property_defaults_none(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["name"],
        }
        model = _build_args_schema(schema)
        instance = model(name="Acme")
        assert instance.note is None

    def test_boolean_property(self):
        schema = {
            "type": "object",
            "properties": {"active": {"type": "boolean"}},
        }
        model = _build_args_schema(schema)
        instance = model(active=True)
        assert instance.active is True


class TestFormatToolResult:
    def test_success_with_mapped_result(self):
        result = {
            "invocation_id": "inv-1",
            "mapped_result": {"accounts": [{"id": "001"}]},
            "remote_outcome": "success",
        }
        output = json.loads(_format_tool_result(result))
        assert output["invocation_id"] == "inv-1"
        assert output["result"] == {"accounts": [{"id": "001"}]}
        assert output["remote_outcome"] == "success"

    def test_error_result(self):
        result = {
            "invocation_id": "inv-2",
            "error_code": "not_found",
            "error_message": "连接器不存在",
        }
        output = json.loads(_format_tool_result(result))
        assert output["error_code"] == "not_found"
        assert output["error_message"] == "连接器不存在"

    def test_data_fallback_when_no_mapped(self):
        result = {
            "invocation_id": "inv-3",
            "data": {"raw": True},
        }
        output = json.loads(_format_tool_result(result))
        assert output["result"] == {"raw": True}


class TestGetConnectorTools:
    """Agent 工具生成集成测试。"""

    async def test_empty_connectors_returns_empty(self):
        context = SimpleNamespace(connectors=[])
        tools = await get_connector_tools(context)
        assert tools == []

    async def test_none_connectors_returns_empty(self):
        context = SimpleNamespace(connectors=None)
        tools = await get_connector_tools(context)
        assert tools == []

    async def test_tool_generated_per_operation(self):
        context = SimpleNamespace(connectors=["my_crm"], uid="user-1")
        metadata = {
            "slug": "my_crm",
            "operations": [
                {
                    "slug": "query_customer",
                    "name": "查询客户",
                    "operation_type": "read",
                    "http_method": "GET",
                    "request_schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                    "connector_revision": 1,
                    "operation_revision": 2,
                },
                {
                    "slug": "update_customer",
                    "name": "更新客户",
                    "operation_type": "write",
                    "http_method": "PUT",
                    "request_schema": None,
                    "connector_revision": 1,
                    "operation_revision": 1,
                },
            ],
        }

        with patch(
            "yuxi.agents.connectors.tools.get_connector_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(return_value=metadata)
            mock_get_service.return_value = mock_service

            tools = await get_connector_tools(context)

        assert len(tools) == 2
        assert tools[0].name == "cn_my_crm__query_customer"
        assert tools[1].name == "cn_my_crm__update_customer"

    async def test_tool_name_namespace_pattern(self):
        context = SimpleNamespace(connectors=["sales-force"], uid="user-1")
        metadata = {
            "slug": "sales-force",
            "operations": [{
                "slug": "get-opp",
                "name": "获取商机",
                "operation_type": "read",
                "http_method": "GET",
                "request_schema": None,
                "connector_revision": 1,
                "operation_revision": 1,
            }],
        }

        with patch(
            "yuxi.agents.connectors.tools.get_connector_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(return_value=metadata)
            mock_get_service.return_value = mock_service

            tools = await get_connector_tools(context)

        assert tools[0].name == "cn_sales_force__get_opp"

    async def test_connector_not_found_skipped(self):
        context = SimpleNamespace(connectors=["missing"], uid="user-1")

        with patch(
            "yuxi.agents.connectors.tools.get_connector_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_service

            tools = await get_connector_tools(context)

        assert tools == []

    async def test_connector_load_error_skipped(self):
        context = SimpleNamespace(connectors=["broken"], uid="user-1")

        with patch(
            "yuxi.agents.connectors.tools.get_connector_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(
                side_effect=Exception("DB error")
            )
            mock_get_service.return_value = mock_service

            tools = await get_connector_tools(context)

        assert tools == []

    async def test_tool_description_contains_operation_info(self):
        context = SimpleNamespace(connectors=["crm"], uid="user-1")
        metadata = {
            "slug": "crm",
            "operations": [{
                "slug": "query",
                "name": "查询客户",
                "operation_type": "read",
                "http_method": "GET",
                "request_schema": None,
                "connector_revision": 1,
                "operation_revision": 1,
            }],
        }

        with patch(
            "yuxi.agents.connectors.tools.get_connector_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(return_value=metadata)
            mock_get_service.return_value = mock_service

            tools = await get_connector_tools(context)

        assert "查询客户" in tools[0].description
        assert "GET" in tools[0].description
        assert "查询" in tools[0].description

    async def test_write_operation_description(self):
        context = SimpleNamespace(connectors=["crm"], uid="user-1")
        metadata = {
            "slug": "crm",
            "operations": [{
                "slug": "update",
                "name": "更新商机",
                "operation_type": "write",
                "http_method": "PUT",
                "request_schema": None,
                "connector_revision": 1,
                "operation_revision": 1,
            }],
        }

        with patch(
            "yuxi.agents.connectors.tools.get_connector_service"
        ) as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(return_value=metadata)
            mock_get_service.return_value = mock_service

            tools = await get_connector_tools(context)

        assert "写入" in tools[0].description
