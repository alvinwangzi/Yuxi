"""连接器类型配置、参数校验与响应映射的类型契约。

JSON Schema 校验仅支持 Draft 2020-12 的受限子集：
object/properties/required、基本类型、enum、长度/数值范围、数组及内部 $defs/$ref。
禁止远程 $ref、代码执行、模板表达式和递归深度失控。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import jsonschema
from jsonschema import Draft202012Validator

ALLOWED_JSON_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "pattern",
        "enum",
        "const",
        "default",
        "description",
        "title",
        "$defs",
        "$ref",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "format",
        "nullable",
        "x-approval-visible",
        "x-approval-target",
    }
)

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

FORBIDDEN_STATIC_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "proxy-connection",
    }
)

DEFAULT_TIMEOUT_SECONDS = 30
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 120

DEFAULT_MAX_RESPONSE_BYTES = 1 * 1024 * 1024
MIN_MAX_RESPONSE_BYTES = 1 * 1024
MAX_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

DEFAULT_CONCURRENCY_LIMIT = 4
MIN_CONCURRENCY_LIMIT = 1
MAX_CONCURRENCY_LIMIT = 32


def validate_delivery_policy(connector_type, operation_type, retry_policy, remote_idempotency) -> int:
    """REST 读最多三次，写仅发送一次；幂等头只绑定持久 invocation。"""
    policy = {} if retry_policy is None else retry_policy
    if not isinstance(policy, dict) or set(policy) - {"max_attempts"}:
        raise ConnectorSchemaError("retry_policy_invalid")
    budget = policy.get("max_attempts", 1)
    maximum = 3 if connector_type == "generic_rest" and operation_type == "read" else 1
    if type(budget) is not int or not 1 <= budget <= maximum:
        raise ConnectorSchemaError("retry_budget_invalid")
    if remote_idempotency is not None and remote_idempotency != {}:
        if (
            connector_type != "generic_rest"
            or operation_type != "write"
            or remote_idempotency
            not in (
                {"header_name": "Idempotency-Key"},
                {"header_name": "X-Idempotency-Key"},
            )
        ):
            raise ConnectorSchemaError("remote_idempotency_invalid")
    return budget


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
    try:
        serialized = json.dumps(schema, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise ConnectorSchemaError("schema 不是有界 JSON") from None
    if len(serialized.encode("utf-8")) > MAX_SCHEMA_SIZE_BYTES:
        raise ConnectorSchemaError(f"schema 大小超过 {MAX_SCHEMA_SIZE_BYTES} 字节限制")
    _check_schema_nodes(schema, schema, depth=0, ancestors=frozenset())
    try:
        Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError:
        raise ConnectorSchemaError("JSON Schema 不合法") from None
    return schema


def validate_params(params: dict, schema: dict | None) -> dict:
    """按操作 schema 校验业务参数，返回冻结副本。"""
    if not isinstance(params, dict):
        raise ConnectorSchemaError("参数必须是对象")
    try:
        serialized = json.dumps(params, ensure_ascii=False, default=str, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise ConnectorSchemaError("参数不是有界 JSON") from None
    if len(serialized.encode("utf-8")) > MAX_PARAMS_SIZE_BYTES:
        raise ConnectorSchemaError(f"参数大小超过 {MAX_PARAMS_SIZE_BYTES} 字节限制")
    if schema is None:
        if params:
            raise ConnectorSchemaError("操作未声明参数 schema，不接受任何输入")
        return dict(params)
    validate_json_schema(schema)
    effective_schema = dict(schema)
    effective_schema.setdefault("additionalProperties", False)
    validator = Draft202012Validator(effective_schema)
    errors = sorted(validator.iter_errors(params), key=lambda e: list(e.path))
    if errors:
        messages = [str(e.validator) for e in errors[:5]]
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
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
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
        ensure_result_budget(result, max_bytes)
    return result


def ensure_result_budget(value: Any, max_bytes: int) -> None:
    """序列化前逐块计数，映射重复引用也不能放大有界业务输出。"""
    size = 0
    try:
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > max_bytes:
                raise ConnectorSchemaError("结果超过输出预算")
    except (TypeError, ValueError, RecursionError):
        raise ConnectorSchemaError("结果不是有界 JSON") from None


_MISSING = object()


def validate_static_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """校验静态 headers 不包含认证头或冲突项。"""
    if not headers:
        return {}
    if not isinstance(headers, dict):
        raise ConnectorSchemaError("静态 headers 必须是对象")
    if len(headers) > 100:
        raise ConnectorSchemaError("静态 headers 超过上限")
    result: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConnectorSchemaError("静态 headers 键值必须为字符串")
        if key.lower() in FORBIDDEN_STATIC_HEADERS:
            raise ConnectorSchemaError(f"静态 headers 禁止认证相关头: {key}")
        if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", key) or any(c in value for c in "\r\n\x00"):
            raise ConnectorSchemaError("静态 header 格式无效")
        result[key] = value
    if sum(len(key.encode()) + len(value.encode()) for key, value in result.items()) > 32768:
        raise ConnectorSchemaError("静态 headers 超过上限")
    return result


def validate_timeout(seconds: int | float | None) -> float:
    if seconds is None:
        return float(DEFAULT_TIMEOUT_SECONDS)
    value = float(seconds)
    if value < MIN_TIMEOUT_SECONDS or value > MAX_TIMEOUT_SECONDS:
        raise ConnectorSchemaError(f"timeout 必须在 {MIN_TIMEOUT_SECONDS}~{MAX_TIMEOUT_SECONDS} 秒之间")
    return value


def validate_connector_config(connector_type: str, config: dict) -> dict:
    """按实际适配器和共享网络契约验证完整配置，未知字段直接拒绝。"""
    import copy

    from yuxi.services.connectors.http_client import ConnectorHTTPConfig, ConnectorHTTPError
    from yuxi.services.connectors.registry import get_adapter_class

    try:
        schema = copy.deepcopy(get_adapter_class(connector_type).config_schema())
    except KeyError:
        raise ConnectorSchemaError("connector_type_invalid") from None
    schema["properties"].update(
        {
            "base_url": {"type": "string", "minLength": 1},
            "allowed_origins": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "allowed_private_cidrs": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            "allow_redirects": {"const": False},
            "trust_env": {"const": False},
            "max_redirects": {"const": 0},
            "healthcheck_operation_slug": {"type": "string", "minLength": 1, "maxLength": 64},
        }
    )
    schema["additionalProperties"] = False
    try:
        Draft202012Validator(schema).validate(config)
        ConnectorHTTPConfig.from_dict(config)
        validate_static_headers(config.get("static_headers"))
        header = config.get("api_key_header", "X-API-Key")
        if header.lower() in FORBIDDEN_STATIC_HEADERS or not re.fullmatch(r"[A-Za-z0-9-]+", header):
            raise ConnectorSchemaError("api_key_header_invalid")
    except (jsonschema.ValidationError, ValueError, TypeError, ConnectorHTTPError):
        raise ConnectorSchemaError("connector_config_invalid") from None
    return copy.deepcopy(config)


def validate_operation_namespace(connector_slug: str, operation_slug: str) -> str:
    """工具名无截断且可逆，双下划线保留为名称分隔符。"""
    name = f"cn_{connector_slug}__{operation_slug}"
    for slug in (connector_slug, operation_slug):
        validate_connector_slug(slug)
    if "__" in connector_slug or "__" in operation_slug or len(name) > 64:
        raise ConnectorSchemaError("tool_namespace_invalid")
    return name


def validate_connector_slug(slug: str) -> str:
    """标识只使用协议允许字符，创建后由 tombstone 保留。"""
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", slug) or "__" in slug:
        raise ConnectorSchemaError("connector_slug_invalid")
    return slug


def validate_response_mapping(mapping: dict | None) -> None:
    """保存前校验输出字段路径，不依赖远端样本或执行表达式。"""
    if mapping is None:
        return
    if not isinstance(mapping, dict) or len(mapping) > MAX_SCHEMA_PROPERTIES:
        raise ConnectorSchemaError("response_mapping_invalid")
    for key, path in mapping.items():
        if not isinstance(key, str) or not key or not isinstance(path, str):
            raise ConnectorSchemaError("response_mapping_invalid")
        _validate_field_path(path)


def validate_max_response_bytes(value: int | None) -> int:
    if value is None:
        return DEFAULT_MAX_RESPONSE_BYTES
    if value < MIN_MAX_RESPONSE_BYTES or value > MAX_MAX_RESPONSE_BYTES:
        raise ConnectorSchemaError(f"max_response_bytes 必须在 {MIN_MAX_RESPONSE_BYTES}~{MAX_MAX_RESPONSE_BYTES} 之间")
    return value


def validate_concurrency_limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_CONCURRENCY_LIMIT
    if value < MIN_CONCURRENCY_LIMIT or value > MAX_CONCURRENCY_LIMIT:
        raise ConnectorSchemaError(f"并发限制必须在 {MIN_CONCURRENCY_LIMIT}~{MAX_CONCURRENCY_LIMIT} 之间")
    return value


def _check_schema_nodes(node: Any, root: dict, *, depth: int, ancestors: frozenset) -> None:
    """仅 schema 节点检查关键字，展开本地引用并拒绝环与过深链。"""
    if depth > MAX_SCHEMA_DEPTH:
        raise ConnectorSchemaError(f"schema 嵌套深度超过 {MAX_SCHEMA_DEPTH} 层")
    if isinstance(node, bool):
        return
    if not isinstance(node, dict):
        raise ConnectorSchemaError("schema 节点必须是对象或布尔值")
    if id(node) in ancestors:
        raise ConnectorSchemaError("schema 引用不能形成循环")
    unknown = set(node) - ALLOWED_JSON_SCHEMA_KEYWORDS
    if unknown:
        raise ConnectorSchemaError("不支持的 schema 关键字")
    ancestors = ancestors | {id(node)}
    for annotation in ("x-approval-visible", "x-approval-target"):
        if annotation in node and type(node[annotation]) is not bool:
            raise ConnectorSchemaError("审批摘要标记必须是布尔值")
    if node.get("x-approval-target") and not node.get("x-approval-visible"):
        raise ConnectorSchemaError("审批目标必须显式允许展示")
    if "$ref" in node:
        from urllib.parse import unquote

        ref = node["$ref"]
        if not isinstance(ref, str) or not (ref == "#" or ref.startswith("#/")):
            raise ConnectorSchemaError("$ref 必须为内部引用，禁止远程 $ref")
        target = root
        try:
            for segment in unquote(ref[2:]).split("/") if ref != "#" else []:
                key = segment.replace("~1", "/").replace("~0", "~")
                target = target[int(key)] if isinstance(target, list) else target[key]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ConnectorSchemaError("schema 引用不存在") from None
        _check_schema_nodes(target, root, depth=depth + 1, ancestors=ancestors)
    for key in ("properties", "$defs"):
        if key in node:
            if not isinstance(node[key], dict):
                raise ConnectorSchemaError("schema 字段目录必须是对象")
            for field, child in node[key].items():
                if (
                    key == "properties"
                    and isinstance(child, dict)
                    and child.get("x-approval-visible")
                    and re.search(r"secret|password|token|authorization|cookie", field, re.I)
                ):
                    raise ConnectorSchemaError("凭据字段不能进入审批摘要")
                _check_schema_nodes(child, root, depth=depth + 1, ancestors=ancestors)
    for key in ("items", "additionalProperties", "not"):
        if key in node:
            _check_schema_nodes(node[key], root, depth=depth + 1, ancestors=ancestors)
    for key in ("allOf", "anyOf", "oneOf"):
        if key in node:
            if not isinstance(node[key], list):
                raise ConnectorSchemaError("schema 组合必须是数组")
            for child in node[key]:
                _check_schema_nodes(child, root, depth=depth + 1, ancestors=ancestors)


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
