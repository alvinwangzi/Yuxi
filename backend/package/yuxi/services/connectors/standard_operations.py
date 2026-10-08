"""内置 SaaS 操作目录拥有模型输入和管理落库的共同契约。"""

import re


def salesforce_operations() -> list[dict]:
    """仅暴露 Account/Opportunity 白名单操作，不接受自由 SOQL。"""
    text = {"type": "string", "minLength": 1, "maxLength": 256}
    account_fields = {key: text for key in ("Name", "Industry", "BillingCity", "BillingState", "Phone", "Website")}
    account_fields["AnnualRevenue"] = {"type": "number", "minimum": 0}
    opportunity_fields = {key: text for key in ("Name", "StageName", "CloseDate")}
    opportunity_fields["Amount"] = {"type": "number", "minimum": 0}
    return [
        _operation(
            "query_customer",
            "查询客户",
            {
                "name": text,
                "industry": text,
                "external_id_value": text,
                "page_size": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            [],
        ),
        _operation("get_customer", "读取客户", {"account_id": text}, ["account_id"]),
        _operation("get_opportunity", "读取商机", {"opportunity_id": text}, ["opportunity_id"]),
        _operation(
            "upsert_customer",
            "写入客户",
            {"external_id_value": text, **account_fields},
            ["external_id_value"],
            method="PATCH",
        ),
        _operation(
            "update_opportunity",
            "更新商机",
            {"opportunity_id": text, **opportunity_fields},
            ["opportunity_id"],
            method="PATCH",
        ),
    ]


def feishu_operations(config: dict) -> list[dict]:
    """写字段由管理员当前映射决定，关联值按原 JSON 类型传输。"""
    text = {"type": "string", "minLength": 1, "maxLength": 256}
    operations = []
    from yuxi.services.connectors.feishu_fields import field_schema

    for record_type, label in (("customer", "客户"), ("opportunity", "商机")):
        fields = {
            key: field_schema((config.get(record_type + "_field_types") or {}).get(key))
            for key in (config.get(record_type + "_fields") or {})
        }
        operations.append(
            _operation(
                "query_" + record_type,
                "查询" + label,
                {
                    "page_size": {"type": "integer", "minimum": 1, "maximum": 500},
                    "page_token": text,
                    "filters": {
                        "type": "object",
                        "properties": {key: text for key in fields},
                        "additionalProperties": False,
                    },
                },
                [],
            )
        )
        if record_type == "customer":
            operations.append(_operation("get_customer", "读取客户", {"record_id": text}, ["record_id"]))
        operations.append(_operation("create_" + record_type, "创建" + label, fields, [], method="POST"))
        operations.append(
            _operation(
                "update_" + record_type, "更新" + label, {"record_id": text, **fields}, ["record_id"], method="PUT"
            )
        )
    for operation in operations:
        operation["endpoint_template"] = "/open-apis/bitable"
    return operations


def _operation(slug, name, properties, required, *, method="GET") -> dict:
    """声明原生 JSON Schema 和审批策略，写操作默认 required。"""
    if method != "GET":
        properties = {
            key: {
                **schema,
                "x-approval-visible": not bool(re.search(r"secret|password|token|authorization|cookie", key, re.I)),
                **({"x-approval-target": True} if key in {"record_id", "opportunity_id", "external_id_value"} else {}),
            }
            for key, schema in properties.items()
        }
    return {
        "slug": slug,
        "name": name,
        "operation_type": "read" if method == "GET" else "write",
        "http_method": method,
        "endpoint_template": "/services/data",
        "approval_policy": "preauthorized" if method == "GET" else "required",
        "request_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }
