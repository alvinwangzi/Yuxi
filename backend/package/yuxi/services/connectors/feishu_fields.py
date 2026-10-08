"""飞书真实字段类型与模型输入采用同一有限契约。"""

from jsonschema import Draft202012Validator
from yuxi.services.connectors.http_client import ConnectorHTTPError

SUPPORTED_FIELD_TYPES = (1, 2, 3, 4, 5, 7, 18, 21)


def field_schema(field_type: int | None, options: list[str] | None = None) -> dict:
    """停用草稿可未知类型，运行时只允许文本、数值、选择、日期与关联。"""
    text = {"type": "string", "maxLength": 10000}
    if field_type is None:
        return {}
    if field_type == 1:
        return text
    if field_type == 2:
        return {"type": "number"}
    if field_type == 3:
        return {"type": "string", **({"enum": options} if options else {"maxLength": 256})}
    if field_type == 4:
        return {
            "type": "array",
            "maxItems": 100,
            "items": {"type": "string", **({"enum": options} if options else {"maxLength": 256})},
        }
    if field_type == 5:
        return {"type": "integer", "minimum": 0, "description": "日期使用 Unix 毫秒时间戳"}
    if field_type == 7:
        return {"type": "boolean"}
    if field_type in (18, 21):
        return {
            "type": "array",
            "maxItems": 100,
            "items": {"type": "string", "pattern": "^[A-Za-z0-9_-]+$", "maxLength": 256},
            "description": "关联值为 record ID 数组",
        }
    raise ConnectorHTTPError("字段类型不支持", code="invalid_params")


def validate_field_value(value, field: dict) -> None:
    """按远端实际 type/options 拒绝错误格式，不靠字段名称猜测或静默转换。"""
    if type(field.get("type")) is not int or field["type"] not in SUPPORTED_FIELD_TYPES:
        raise ConnectorHTTPError("字段类型未确认", code="invalid_params")
    options = [option["name"] for option in (field.get("property") or {}).get("options", [])]
    if not Draft202012Validator(field_schema(field["type"], options)).is_valid(value):
        raise ConnectorHTTPError("字段值格式与远端类型不符", code="invalid_params")
