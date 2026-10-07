"""连接器 schema 校验、模板解析与响应映射单元测试。"""

from __future__ import annotations

import pytest

from yuxi.services.connectors.schemas import (
    DEFAULT_CONCURRENCY_LIMIT,
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ConnectorSchemaError,
    apply_response_mapping,
    resolve_body_template,
    resolve_template,
    validate_concurrency_limit,
    validate_json_schema,
    validate_max_response_bytes,
    validate_params,
    validate_static_headers,
    validate_timeout,
)


class TestValidateJsonSchema:
    """JSON Schema 受限子集校验。"""

    def test_none_returns_none(self):
        assert validate_json_schema(None) is None

    def test_valid_simple_schema(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer", "minimum": 0},
            },
            "required": ["name"],
        }
        result = validate_json_schema(schema)
        assert result == schema

    def test_non_dict_raises(self):
        with pytest.raises(ConnectorSchemaError, match="必须是对象"):
            validate_json_schema("not_a_dict")

    def test_remote_ref_rejected(self):
        schema = {"$ref": "https://evil.com/schema.json"}
        with pytest.raises(ConnectorSchemaError, match="远程"):
            validate_json_schema(schema)

    def test_internal_ref_allowed(self):
        schema = {
            "type": "object",
            "$defs": {"name": {"type": "string"}},
            "properties": {"name": {"$ref": "#/$defs/name"}},
        }
        validate_json_schema(schema)

    def test_deeply_nested_schema_rejected(self):
        deep = {"type": "object"}
        for _ in range(12):
            deep = {"type": "object", "properties": {"child": deep}}
        with pytest.raises(ConnectorSchemaError, match="嵌套深度"):
            validate_json_schema(deep)

    def test_dollar_sign_keyword_rejected(self):
        schema = {"$evil": True}
        with pytest.raises(ConnectorSchemaError, match="关键字"):
            validate_json_schema(schema)

    def test_schema_with_enum_and_format(self):
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive"]},
                "email": {"type": "string", "format": "email"},
            },
        }
        validate_json_schema(schema)


class TestValidateParams:
    """业务参数校验。"""

    def test_valid_params_pass(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        result = validate_params({"name": "Acme"}, schema)
        assert result == {"name": "Acme"}

    def test_missing_required_field(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        with pytest.raises(ConnectorSchemaError, match="参数校验失败"):
            validate_params({}, schema)

    def test_wrong_type_rejected(self):
        schema = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
        with pytest.raises(ConnectorSchemaError, match="参数校验失败"):
            validate_params({"count": "not_int"}, schema)

    def test_additional_properties_rejected(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        with pytest.raises(ConnectorSchemaError, match="参数校验失败"):
            validate_params({"name": "ok", "extra": "field"}, schema)

    def test_no_schema_rejects_any_params(self):
        with pytest.raises(ConnectorSchemaError, match="未声明参数"):
            validate_params({"unexpected": "value"}, None)

    def test_no_schema_accepts_empty_params(self):
        result = validate_params({}, None)
        assert result == {}

    def test_non_dict_params_raises(self):
        with pytest.raises(ConnectorSchemaError, match="必须是对象"):
            validate_params("string", {"type": "object"})


class TestResolveTemplate:
    """endpoint_template 占位符替换。"""

    def test_simple_replacement(self):
        assert resolve_template("/api/{{id}}", {"id": "123"}) == "/api/123"

    def test_multiple_placeholders(self):
        result = resolve_template("/api/{{org}}/{{id}}", {"org": "acme", "id": "42"})
        assert result == "/api/acme/42"

    def test_undefined_variable_raises(self):
        with pytest.raises(ConnectorSchemaError, match="未定义"):
            resolve_template("/api/{{missing}}", {})

    def test_non_scalar_value_raises(self):
        with pytest.raises(ConnectorSchemaError, match="标量"):
            resolve_template("/api/{{ids}}", {"ids": [1, 2]})

    def test_no_placeholders_returns_unchanged(self):
        assert resolve_template("/api/list", {}) == "/api/list"

    def test_integer_value_converted(self):
        assert resolve_template("/api/{{id}}", {"id": 42}) == "/api/42"


class TestResolveBodyTemplate:
    """JSON body 模板递归替换。"""

    def test_none_returns_none(self):
        assert resolve_body_template(None, {}) is None

    def test_string_full_placeholder_preserves_type(self):
        assert resolve_body_template("{{data}}", {"data": [1, 2]}) == [1, 2]

    def test_string_full_placeholder_int(self):
        assert resolve_body_template("{{count}}", {"count": 42}) == 42

    def test_nested_dict_template(self):
        template = {"name": "{{name}}", "nested": {"value": "{{val}}"}}
        result = resolve_body_template(template, {"name": "Acme", "val": 10})
        assert result == {"name": "Acme", "nested": {"value": 10}}

    def test_list_template(self):
        template = ["{{a}}", "{{b}}"]
        result = resolve_body_template(template, {"a": 1, "b": 2})
        assert result == [1, 2]

    def test_undefined_in_body_raises(self):
        with pytest.raises(ConnectorSchemaError, match="未定义"):
            resolve_body_template({"key": "{{missing}}"}, {})

    def test_plain_string_without_full_match(self):
        result = resolve_body_template("hello {{name}}", {"name": "world"})
        assert result == "hello world"


class TestApplyResponseMapping:
    """响应字段映射。"""

    def test_none_mapping_returns_empty(self):
        assert apply_response_mapping({"a": 1}, None) == {}

    def test_simple_field_mapping(self):
        data = {"records": [{"id": "1"}, {"id": "2"}], "total": 2}
        mapping = {"items": "records", "count": "total"}
        result = apply_response_mapping(data, mapping)
        assert result == {"items": [{"id": "1"}, {"id": "2"}], "count": 2}

    def test_nested_field_path(self):
        data = {"response": {"data": {"value": 42}}}
        result = apply_response_mapping(data, {"result": "response.data.value"})
        assert result == {"result": 42}

    def test_array_index_access(self):
        data = {"items": [{"name": "first"}, {"name": "second"}]}
        result = apply_response_mapping(data, {"first": "items[0].name"})
        assert result == {"first": "first"}

    def test_missing_path_raises(self):
        with pytest.raises(ConnectorSchemaError, match="缺失"):
            apply_response_mapping({"a": 1}, {"result": "b.c"})

    def test_non_string_path_raises(self):
        with pytest.raises(ConnectorSchemaError, match="字符串"):
            apply_response_mapping({}, {"result": 123})

    def test_empty_path_raises(self):
        with pytest.raises(ConnectorSchemaError, match="不能为空"):
            apply_response_mapping({}, {"result": ""})

    def test_non_dict_mapping_raises(self):
        with pytest.raises(ConnectorSchemaError, match="必须是对象"):
            apply_response_mapping({}, "not_dict")


class TestValidateStaticHeaders:
    """静态 headers 校验。"""

    def test_none_returns_empty(self):
        assert validate_static_headers(None) == {}

    def test_valid_headers_pass(self):
        result = validate_static_headers({"X-Custom": "value", "Accept": "application/json"})
        assert result == {"X-Custom": "value", "Accept": "application/json"}

    def test_authorization_header_rejected(self):
        with pytest.raises(ConnectorSchemaError, match="认证"):
            validate_static_headers({"Authorization": "Bearer xxx"})

    def test_cookie_header_rejected(self):
        with pytest.raises(ConnectorSchemaError, match="认证"):
            validate_static_headers({"Cookie": "session=abc"})

    def test_proxy_authorization_rejected(self):
        with pytest.raises(ConnectorSchemaError, match="认证"):
            validate_static_headers({"Proxy-Authorization": "Basic xxx"})

    def test_non_string_values_rejected(self):
        with pytest.raises(ConnectorSchemaError, match="字符串"):
            validate_static_headers({"X-Num": 123})


class TestValidateTimeout:
    def test_none_returns_default(self):
        assert validate_timeout(None) == DEFAULT_TIMEOUT_SECONDS

    def test_valid_value(self):
        assert validate_timeout(60) == 60.0

    def test_too_low_raises(self):
        with pytest.raises(ConnectorSchemaError, match="timeout"):
            validate_timeout(0)

    def test_too_high_raises(self):
        with pytest.raises(ConnectorSchemaError, match="timeout"):
            validate_timeout(999)


class TestValidateMaxResponseBytes:
    def test_none_returns_default(self):
        assert validate_max_response_bytes(None) == DEFAULT_MAX_RESPONSE_BYTES

    def test_valid_value(self):
        assert validate_max_response_bytes(2 * 1024 * 1024) == 2 * 1024 * 1024

    def test_too_small_raises(self):
        with pytest.raises(ConnectorSchemaError, match="max_response_bytes"):
            validate_max_response_bytes(100)

    def test_too_large_raises(self):
        with pytest.raises(ConnectorSchemaError, match="max_response_bytes"):
            validate_max_response_bytes(100 * 1024 * 1024)


class TestValidateConcurrencyLimit:
    def test_none_returns_default(self):
        assert validate_concurrency_limit(None) == DEFAULT_CONCURRENCY_LIMIT

    def test_valid_value(self):
        assert validate_concurrency_limit(8) == 8

    def test_too_low_raises(self):
        with pytest.raises(ConnectorSchemaError, match="并发限制"):
            validate_concurrency_limit(0)

    def test_too_high_raises(self):
        with pytest.raises(ConnectorSchemaError, match="并发限制"):
            validate_concurrency_limit(100)
