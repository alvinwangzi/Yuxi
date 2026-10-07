"""连接器类型配置、参数校验与响应映射的类型契约。

JSON Schema 校验仅支持 Draft 2020-12 的受限子集：
object/properties/required、基本类型、enum、长度/数值范围、数组及内部 $defs/$ref。
禁止远程 $ref、代码执行、模板表达式和递归深度失控。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import jsonschema
from jsonschema import Draft202012Validator

from yuxi.utils import logger

ALLOWED_JSON_SCHEMA_KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties",
    "items", "minItems", "maxItems", "uniqueItems",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "enum", "const",
    "default", "description", "title", "$defs", "$ref",
    "allOf", "anyOf", "oneOf", "not",
    "format", "nullable",
})

MAX_SCHEMA_DEPTH = 8
MAX_SCHEMA_SIZE_BYTES = 64 * 1024
MAX_SCHEMA_PROPERTIES = 100
MAX_PARAMS_SIZE_BYTES = 4 * 1024 * 1024

PLACEHOLDER_PATTERN = re.compile(r"\{\{(\w+)\}\}")

AuthType = Literal["none", "bearer", "basic", "api_key"]
OperationType = Literal["read", "write"]
ApprovalPolicy = Literal["required", "preauthorized"]
ResponseType = Literal["json", "text", "empty"]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

FORBIDDEN_STATIC_HEADERS = frozenset({
    "authorization", "cookie", "proxy-authorization",
})

DEFAULT_TIMEOUT_SECONDS = 30
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 120

DEFAULT_MAX_RESPONSE_BYTES = 1 * 1024 * 1024
MIN_MAX_RESPONSE_BYTES = 1 * 1024
MAX_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

DEFAULT_CONCURRENCY_LIMIT = 4
MIN_CONCURRENCY_LIMIT = 1
MAX_CONCURRENCY_LIMIT = 32


@dataclass(frozen=True)
class ConnectorValidationError:
    """校验失败的结构化描述。"""

    code: str
    message: str
    field: str | None = None


class ConnectorSchemaError(Exception):
    """操作 schema 或配置 schema 不合法。"""


def validate_json_schema(schema: dict | None) -> dict | None:
    """校验 JSON Schema 仅使用允许子集，拒绝远程 $ref 和过深嵌套。"""
    if schema is None:
        return None
    if not isinstance(schema, dict):
        raise ConnectorSchemaError("request_schema 必须是对象")
    serialized = json.dumps(schema, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > MAX_SCHEMA_SIZE_BYTES:
        raise ConnectorSchemaError(f"schema 大小超过 {MAX_SCHEMA_SIZE_BYTES} 字节限制")
    _check_schema_depth(schema, depth=0)
    _check_schema_keywords(schema)
    _check_refs_are_local(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise ConnectorSchemaError(f"JSON Schema 不合法: {exc.message}") from exc
    return schema


def _check_schema_depth(node: Any, depth: int) -> None:
    if depth > MAX_SCHEMA_DEPTH:
        raise ConnectorSchemaError(f"schema 嵌套深度超过 {MAX_SCHEMA_DEPTH} 层")
    if isinstance(node, dict):
        for value in node.values():
            _check_schema_depth(value, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _check_schema_depth(item, depth + 1)


def _check_schema_keywords(node: Any) -> None:
    if isinstance(node, dict):
        for key in node:
            if key.startswith("$") and key not in {"$ref", "$defs"}:
                raise ConnectorSchemaError(f"不允许的 schema 关键字: {key}")
            _check_schema_keywords(node[key])
    elif isinstance(node, list):
        for item in node:
            _check_schema_keywords(item)


def _check_refs_are_local(node: Any) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref.startswith("http://") or ref.startswith("https://"):
                raise ConnectorSchemaError("禁止远程 $ref")
            if not ref.startswith("#") and not ref.startswith("#/"):
                raise ConnectorSchemaError(f"$ref 必须为内部引用: {ref}")
        for value in node.values():
            _check_refs_are_local(value)
    elif isinstance(node, list):
        for item in node:
            _check_refs_are_local(item)


def validate_params(params: dict, schema: dict | None) -> dict:
    """按操作 schema 校验业务参数，返回冻结副本。"""
    if not isinstance(params, dict):
        raise ConnectorSchemaError("参数必须是对象")
    serialized = json.dumps(params, ensure_ascii=False, default=str)
    if len(serialized.encode("utf-8")) > MAX_PARAMS_SIZE_BYTES:
        raise ConnectorSchemaError(f"参数大小超过 {MAX_PARAMS_SIZE_BYTES} 字节限制")
    if schema is None:
        if params:
            raise ConnectorSchemaError("操作未声明参数 schema，不接受任何输入")
        return dict(params)
    effective_schema = dict(schema)
    effective_schema.setdefault("additionalProperties", False)
    validator = Draft202012Validator(effective_schema)
    errors = sorted(validator.iter_errors(params), key=lambda e: list(e.path))
    if errors:
        messages = [f"{'.'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors[:5]]
        raise ConnectorSchemaError(f"参数校验失败: {'; '.join(messages)}")
    return dict(params)


def resolve_template(template: str, params: dict) -> str:
    """替换 ``{{identifier}}`` 占位符；未定义变量报错。"""
    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in params:
            raise ConnectorSchemaError(f"模板变量未定义: {key}")
        value = params[key]
        if not isinstance(value, (str, int, float, bool)):
            raise ConnectorSchemaError(f"模板变量 {key} 必须是标量值")
        return str(value)

    return PLACEHOLDER_PATTERN.sub(_replace, template)


def resolve_body_template(template: dict | list | str | None, params: dict) -> Any:
    """递归替换 JSON body 模板中的占位符，保留数字/布尔/对象类型。"""
    if template is None:
        return None
    if isinstance(template, str):
        match = PLACEHOLDER_PATTERN.fullmatch(template.strip())
        if match:
            key = match.group(1)
            if key not in params:
                raise ConnectorSchemaError(f"模板变量未定义: {key}")
            return params[key]
        return resolve_template(template, params)
    if isinstance(template, dict):
        return {k: resolve_body_template(v, params) for k, v in template.items()}
    if isinstance(template, list):
        return [resolve_body_template(item, params) for item in template]
    return template


def apply_response_mapping(
    response_data: Any,
    mapping: dict[str, str] | None,
) -> dict[str, Any]:
    """按受限字段路径白名单映射响应，不执行脚本或表达式。"""
    if mapping is None:
        return {}
    if not isinstance(mapping, dict):
        raise ConnectorSchemaError("response_mapping 必须是对象")
    result: dict[str, Any] = {}
    for output_key, source_path in mapping.items():
        if not isinstance(source_path, str):
            raise ConnectorSchemaError(f"映射路径必须是字符串: {source_path}")
        _validate_field_path(source_path)
        value = _extract_field_path(response_data, source_path)
        if value is _MISSING:
            raise ConnectorSchemaError(f"映射路径缺失: {source_path}")
        result[output_key] = value
    return result


_MISSING = object()


def _validate_field_path(path: str) -> None:
    if not path:
        raise ConnectorSchemaError("映射路径不能为空")
    for segment in path.split("."):
        if not segment:
            raise ConnectorSchemaError(f"映射路径含空段: {path}")
        clean = segment
        if "[" in clean:
            clean = clean.split("[", 1)[0]
        if clean and not clean.isidentifier():
            raise ConnectorSchemaError(f"映射路径含非法段: {segment}")


def _extract_field_path(data: Any, path: str) -> Any:
    current = data
    for segment in path.split("."):
        if not segment:
            return _MISSING
        index_match = re.match(r"^(\w+)\[(\d+)\]$", segment)
        if index_match:
            field_name = index_match.group(1)
            index = int(index_match.group(2))
            if not isinstance(current, dict) or field_name not in current:
                return _MISSING
            current = current[field_name]
            if not isinstance(current, list) or index >= len(current):
                return _MISSING
            current = current[index]
        elif isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return _MISSING
    return current


def validate_static_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """校验静态 headers 不包含认证头或冲突项。"""
    if not headers:
        return {}
    if not isinstance(headers, dict):
        raise ConnectorSchemaError("静态 headers 必须是对象")
    result: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConnectorSchemaError("静态 headers 键值必须为字符串")
        if key.lower() in FORBIDDEN_STATIC_HEADERS:
            raise ConnectorSchemaError(f"静态 headers 禁止认证相关头: {key}")
        result[key] = value
    return result


def validate_timeout(seconds: int | float | None) -> float:
    if seconds is None:
        return float(DEFAULT_TIMEOUT_SECONDS)
    value = float(seconds)
    if value < MIN_TIMEOUT_SECONDS or value > MAX_TIMEOUT_SECONDS:
        raise ConnectorSchemaError(
            f"timeout 必须在 {MIN_TIMEOUT_SECONDS}~{MAX_TIMEOUT_SECONDS} 秒之间"
        )
    return value


def validate_max_response_bytes(value: int | None) -> int:
    if value is None:
        return DEFAULT_MAX_RESPONSE_BYTES
    if value < MIN_MAX_RESPONSE_BYTES or value > MAX_MAX_RESPONSE_BYTES:
        raise ConnectorSchemaError(
            f"max_response_bytes 必须在 {MIN_MAX_RESPONSE_BYTES}~{MAX_MAX_RESPONSE_BYTES} 之间"
        )
    return value


def validate_concurrency_limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_CONCURRENCY_LIMIT
    if value < MIN_CONCURRENCY_LIMIT or value > MAX_CONCURRENCY_LIMIT:
        raise ConnectorSchemaError(
            f"并发限制必须在 {MIN_CONCURRENCY_LIMIT}~{MAX_CONCURRENCY_LIMIT} 之间"
        )
    return value
