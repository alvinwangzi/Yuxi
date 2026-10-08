"""受限字段格式来自官方类型契约，数字、日期和关联不能当作任意 JSON。"""

import pytest
from yuxi.services.connectors.feishu_fields import field_schema, validate_field_value
from yuxi.services.connectors.http_client import ConnectorHTTPError
from yuxi.services.connectors.schemas import validate_json_schema


@pytest.mark.parametrize(
    "kind,value",
    [
        (1, "text"),
        (2, 12.5),
        (3, "open"),
        (4, ["open"]),
        (5, 1700000000000),
        (7, True),
        (18, ["recSynthetic"]),
        (21, ["recSynthetic"]),
    ],
)
def test_supported_fields_have_valid_schema_and_native_values(kind, value):
    """合法 JSON 类型通过共同 schema，输出不猜测或强制转成字符串。"""
    schema = field_schema(kind)
    validate_json_schema(schema)
    validate_field_value(value, {"type": kind, "property": {"options": [{"name": "open"}]}})


@pytest.mark.parametrize(
    "kind,value",
    [
        (1, 12),
        (2, True),
        (3, []),
        (4, "open"),
        (5, "2026-10-09"),
        (7, 1),
        (18, ["../../record"]),
        (21, {"unknown": "record"}),
    ],
)
def test_incompatible_field_values_are_rejected(kind, value):
    """错误类型、关联穿越值在业务请求前明确失败。"""
    with pytest.raises(ConnectorHTTPError):
        validate_field_value(value, {"type": kind})
