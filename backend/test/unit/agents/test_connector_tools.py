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
    format_connector_tool_result,
    get_connector_tools,
)


class TestToolNamespace:
    def test_slugs_remain_lossless_and_names_cannot_collide(self):
        from yuxi.services.connectors.schemas import validate_operation_namespace

        assert validate_operation_namespace("crm-x", "read") != validate_operation_namespace("crm_x", "read")
        assert validate_operation_namespace("crm", "read") == "cn_crm__read"

    @pytest.mark.parametrize(
        "connector, operation", [("a" * 40, "b" * 40), ("crm__read", "write"), ("crm", "read__write")]
    )
    def test_overlong_or_ambiguous_names_are_rejected(self, connector, operation):
        from yuxi.services.connectors.schemas import validate_operation_namespace, ConnectorSchemaError

        with pytest.raises(ConnectorSchemaError):
            validate_operation_namespace(connector, operation)


class TestBuildArgsSchema:
    def test_no_schema_is_explicit_empty_object(self):
        assert _build_args_schema(None) == {"type": "object", "properties": {}}

    def test_full_schema_is_preserved_without_mutating_metadata(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": ["A"], "description": "名称"}},
            "required": ["name"],
            "additionalProperties": False,
        }
        actual = _build_args_schema(schema)
        assert actual == schema and actual is not schema
        actual["properties"]["name"]["enum"].append("B")
        assert schema["properties"]["name"]["enum"] == ["A"]

    def test_runtime_cannot_be_declared_as_business_input(self):
        with pytest.raises(ValueError, match="保留参数"):
            _build_args_schema({"type": "object", "properties": {"runtime": {"type": "string"}}})


class TestFormatToolResult:
    def test_success_with_mapped_result(self):
        result = {
            "invocation_id": "inv-1",
            "mapped_result": {"accounts": [{"id": "001"}]},
            "remote_outcome": "success",
        }
        output = json.loads(format_connector_tool_result(result))
        assert output["invocation_id"] == "inv-1"
        assert output["result"] == {"accounts": [{"id": "001"}]}
        assert output["remote_outcome"] == "success"

    def test_error_result(self):
        result = {
            "invocation_id": "inv-2",
            "error_code": "not_found",
            "error_message": "连接器不存在",
        }
        output = json.loads(format_connector_tool_result(result))
        assert output["error_code"] == "not_found"
        assert output["error_message"] == "连接器不存在"

    def test_data_fallback_when_no_mapped(self):
        result = {
            "invocation_id": "inv-3",
            "data": {"raw": True},
        }
        output = json.loads(format_connector_tool_result(result))
        assert output["result"] == {"raw": True}


class TestGetConnectorTools:
    """Agent 工具生成集成测试。"""

    @pytest.mark.parametrize("always_trust", [False, True])
    async def test_subagent_never_exposes_required_write_without_approval_transfer(self, always_trust):
        """父级信任设置不能给子 Agent 提供未装配的审批转交。"""
        service = AsyncMock()
        service.get_connector_metadata.return_value = {
            "operations": [
                {"slug": "read", "operation_type": "read"},
                {"slug": "required", "operation_type": "write", "approval_policy": "required"},
                {"slug": "preauthorized", "operation_type": "write", "approval_policy": "preauthorized"},
            ]
        }
        context = SimpleNamespace(connectors=["crm"], uid="actor", is_subagent_runtime=True, always_trust=always_trust)
        with patch("yuxi.services.connectors.factory.get_connector_service", return_value=service):
            tools = await get_connector_tools(context)
        assert {tool.name for tool in tools} == {"cn_crm__read", "cn_crm__preauthorized"}

    async def test_required_tool_explicit_subagent_runtime_call_is_rejected(self):
        """即使手动取得主 Agent 工具，运行时子身份仍不能发出 required 写。"""
        from yuxi.agents.connectors.tools import build_connector_operation_tool

        service = AsyncMock()
        tool = build_connector_operation_tool(
            service,
            "crm",
            {"slug": "write", "operation_type": "write", "approval_policy": "required"},
            SimpleNamespace(),
        )
        runtime = SimpleNamespace(context=SimpleNamespace(is_subagent_runtime=True))
        with pytest.raises(ValueError, match="subagent_connector_approval_unavailable"):
            await tool.coroutine(runtime=runtime)
        service.prepare_and_execute.assert_not_called()

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

        with patch("yuxi.services.connectors.factory.get_connector_service") as mock_get_service:
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
            "operations": [
                {
                    "slug": "get-opp",
                    "name": "获取商机",
                    "operation_type": "read",
                    "http_method": "GET",
                    "request_schema": None,
                    "connector_revision": 1,
                    "operation_revision": 1,
                }
            ],
        }

        with patch("yuxi.services.connectors.factory.get_connector_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(return_value=metadata)
            mock_get_service.return_value = mock_service

            tools = await get_connector_tools(context)

        assert tools[0].name == "cn_sales-force__get-opp"

    async def test_explicit_connector_not_found_is_an_assembly_error(self):
        context = SimpleNamespace(connectors=["missing"], uid="user-1")

        with patch("yuxi.services.connectors.factory.get_connector_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_service

            with pytest.raises(ValueError, match="configured_connector_unavailable"):
                await get_connector_tools(context)

    async def test_explicit_connector_load_error_propagates(self):
        context = SimpleNamespace(connectors=["broken"], uid="user-1")

        with patch("yuxi.services.connectors.factory.get_connector_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(side_effect=Exception("DB error"))
            mock_get_service.return_value = mock_service

            with pytest.raises(Exception, match="DB error"):
                await get_connector_tools(context)

    async def test_tool_description_contains_operation_info(self):
        context = SimpleNamespace(connectors=["crm"], uid="user-1")
        metadata = {
            "slug": "crm",
            "operations": [
                {
                    "slug": "query",
                    "name": "查询客户",
                    "operation_type": "read",
                    "http_method": "GET",
                    "request_schema": None,
                    "connector_revision": 1,
                    "operation_revision": 1,
                }
            ],
        }

        with patch("yuxi.services.connectors.factory.get_connector_service") as mock_get_service:
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
            "operations": [
                {
                    "slug": "update",
                    "name": "更新商机",
                    "operation_type": "write",
                    "http_method": "PUT",
                    "request_schema": None,
                    "connector_revision": 1,
                    "operation_revision": 1,
                }
            ],
        }

        with patch("yuxi.services.connectors.factory.get_connector_service") as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_connector_metadata = AsyncMock(return_value=metadata)
            mock_get_service.return_value = mock_service

            tools = await get_connector_tools(context)

        assert "写入" in tools[0].description
