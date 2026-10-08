"""真实本地 HTTP 协议验证 SaaS 适配器，不需要外部账号。"""

import ipaddress
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, unquote
from dataclasses import replace

import pytest
from test.integration.services.test_connector_service import (
    service_scope as service_scope,
    vault as vault,
    vault_configuration as vault_configuration,
    fernet_key as fernet_key,
    ensure_live_api_schema as ensure_live_api_schema,
    cleanup_test_knowledge_resources as cleanup_test_knowledge_resources,
    cleanup_test_sandboxes as cleanup_test_sandboxes,
)
from yuxi.services.connectors.service import ConnectorAuthorizationError
from yuxi.repositories.connector_repository import ConnectorRepository

from yuxi.services.connectors.adapters import feishu_bitable_crm
from yuxi.services.connectors.adapters.salesforce import SalesforceAdapter
from yuxi.services.connectors.base import ConnectorExecution, FrozenOperation
from yuxi.services.connectors.http_client import ConnectorHTTPConfig

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.mark.parametrize(
    "kind,page",
    [
        ("salesforce", {}),
        ("salesforce", {"records": "BAD", "done": True, "totalSize": 3}),
        ("salesforce", {"records": [{"Id": str(index)} for index in range(201)], "done": True, "totalSize": 201}),
        ("salesforce", {"records": [], "done": False, "totalSize": 0}),
        ("salesforce", {"records": [], "done": "true", "totalSize": 0}),
        ("feishu", {}),
        ("feishu", {"items": [], "has_more": True}),
        ("feishu", {"items": [], "has_more": "no"}),
        ("feishu", {"items": "BAD", "has_more": False}),
    ],
)
async def test_provider_query_rejects_malformed_page_envelope(provider, kind, page):
    """HTTP 200 不能证明空对象、错误列表或失去游标的分页查询正确。"""
    provider[0]["page_reply"] = page
    result = await invoke(provider, kind, "query_customer", {})
    assert not result.success and result.error_code == "provider_error" and result.remote_outcome == "failed"


@pytest.mark.parametrize(
    "kind,page",
    [("salesforce", {"records": [], "done": True, "totalSize": 0}), ("feishu", {"items": [], "has_more": False})],
)
async def test_provider_query_accepts_explicit_valid_empty_page(provider, kind, page):
    """真实空页与不明响应具有不同结构，合法空结果仍可成功。"""
    provider[0]["page_reply"] = page
    assert (await invoke(provider, kind, "query_customer", {})).success


@pytest.mark.parametrize("kind", ["salesforce", "feishu"])
@pytest.mark.parametrize("literal", ["NaN", "1e999"])
async def test_provider_record_rejects_nonfinite_wire_json(provider, kind, literal):
    """非有限 JSON 不能进入持久结果或 ToolMessage。"""
    provider[0]["nonfinite"] = True
    provider[0]["nonfinite_literal"] = literal
    params = {"account_id": "synthetic"} if kind == "salesforce" else {"record_id": "recSynthetic"}
    result = await invoke(provider, kind, "get_customer", params)
    assert not result.success and result.remote_outcome == "failed"


@pytest.mark.parametrize("code", [False, 0.0])
async def test_feishu_business_code_requires_an_integer(provider, code):
    """布尔或浮点 code 不是整型成功码，不继续交付查询结果。"""
    provider[0]["business_code"] = code
    result = await invoke(provider, "feishu", "query_customer", {})
    assert not result.success and result.error_code == "provider_error"


@pytest.mark.parametrize(
    "kind,reply",
    [
        ("salesforce", {"access_token": True}),
        ("salesforce", []),
        ("salesforce", {"access_token": "synthetic", "instance_url": False}),
        ("feishu", {"code": 0, "tenant_access_token": 42}),
    ],
)
async def test_provider_authentication_json_is_typed_before_business_request(provider, kind, reply):
    """错误凭据响应不是 bearer 字符串，只允许认证请求而不发送业务请求。"""
    provider[0]["auth_reply"] = reply
    params = (
        {"opportunity_id": "synthetic", "Name": "updated"}
        if kind == "salesforce"
        else {"record_id": "recSynthetic", "name": "updated"}
    )
    slug = "update_opportunity" if kind == "salesforce" else "update_customer"
    result = await invoke(provider, kind, slug, params, write=True)
    assert not result.success and result.error_code == "credential_invalid" and result.remote_outcome == "not_sent"
    assert len(provider[0]["requests"]) == 1


async def test_salesforce_paginated_result_obeys_combined_output_budget(provider):
    """两页单独合法仍不能合并成超预算的业务结果。"""
    state, config = provider
    state["large_query"] = True
    result = await invoke((state, replace(config, max_response_bytes=65536)), "salesforce", "query_customer", {})
    assert not result.success and result.error_code == "response_too_large" and result.remote_outcome == "failed"


@pytest.mark.parametrize("actual,success", [("001AbCdEfGhIjKlIVK", True), ("001AbCdEfGhIjKlAAA", False)])
async def test_salesforce_15_and_18_character_identity_requires_correct_checksum(provider, actual, success):
    """接受合法两种身份形式，不能只靠相同前十五位放行错后缀。"""
    provider[0]["served_id"] = actual
    result = await invoke(provider, "salesforce", "get_customer", {"account_id": "001AbCdEfGhIjKl"})
    assert result.success is success


async def test_salesforce_final_protocol_metadata_is_inside_result_budget(provider):
    """合法末页元数据也计入最终投影，不能用缩小的替代对象证明预算。"""
    state, config = provider
    state["large_query"] = True
    state["query_size"] = 32723
    result = await invoke((state, replace(config, max_response_bytes=65536)), "salesforce", "query_customer", {})
    assert not result.success and result.error_code == "response_too_large"


async def test_feishu_get_rejects_response_for_another_record(provider):
    """读取 A 返回 B 必须失败，不能把替代对象输出给消费链路。"""
    provider[0]["wrong_identity"] = True
    result = await invoke(provider, "feishu", "get_customer", {"record_id": "recRequested"})
    assert not result.success and result.error_code == "provider_error" and result.remote_outcome == "failed"


@pytest.mark.parametrize(
    "slug,params,expected",
    [
        ("get_customer", {"account_id": "synthetic"}, "failed"),
        ("get_opportunity", {"opportunity_id": "synthetic"}, "failed"),
        ("update_opportunity", {"opportunity_id": "synthetic", "Name": "updated"}, "succeeded"),
        ("upsert_customer", {"external_id_value": "synthetic", "Name": "updated"}, "succeeded"),
    ],
)
async def test_salesforce_readback_rejects_a_different_record_identity(provider, slug, params, expected):
    """读到 B 不能确认目标 A；已确认的写 receipt 仍保留成功事实。"""
    provider[0]["wrong_identity"] = True
    result = await invoke(provider, "salesforce", slug, params, write=expected == "succeeded")
    assert not result.success and result.remote_outcome == expected
    assert result.error_code == ("readback_failed" if expected == "succeeded" else "provider_error")


async def test_salesforce_customer_query_binds_configured_external_business_key(provider):
    """外部业务键查询必须进入受限 SOQL，不能静默退为全表读取。"""
    state, _ = provider
    result = await invoke(provider, "salesforce", "query_customer", {"external_id_value": "business'key"})
    assert result.success
    query = state["requests"][1][2]["q"][0]
    assert "ConfiguredExternalId__c = 'business\\'key'" in query


async def test_feishu_output_excludes_unmapped_record_fields(provider):
    """只映射 name 时，业务输出不得带入未配置私有列。"""
    state, config = provider
    path = "/open-apis/bitable/v1/apps/appSynthetic/tables/tblCustomer/records/recSynthetic"
    state["records"][path] = {
        "record_id": "recSynthetic",
        "fields": {"客户名称": "visible", "confidential": "synthetic-private-column"},
    }
    result = await invoke(provider, "feishu", "get_customer", {"record_id": "recSynthetic"})
    assert result.success and result.data["fields"] == {"客户名称": "visible"}
    assert "synthetic-private-column" not in str(result.data)


async def test_metadata_service_uses_saved_vault_credentials_and_current_admin_role(service_scope, provider):
    """真实 PG 配置和 Vault 接到 HTTP 目录；普通用户不能借管理入口读取。"""
    service, manager = service_scope
    state, http = provider
    config = {
        key: value for key, value in http.raw_config.items() if key not in {"api_version", "account_external_id_field"}
    }
    config.update(
        base_url=http.base_url,
        allowed_origins=list(http.allowed_origins),
        allowed_private_cidrs=[str(net) for net in http.allowed_private_cidrs],
    )
    await service.create_connector(
        {
            "slug": "metadata",
            "name": "Metadata",
            "connector_type": "feishu_bitable_crm",
            "enabled": False,
            "config": config,
            "credentials": {"app_id": "synthetic", "app_secret": "synthetic"},
        },
        actor="actor",
    )
    data = await service.discover_connector_metadata("metadata", actor="actor")
    assert len(data["tables"]) == 2 and data["fields"]["tblCustomer"][0]["type"] == 1
    count = len(state["requests"])
    async with manager.get_async_session_context() as db:
        user = await ConnectorRepository(db).get_active_actor("actor")
        user.role = "user"
    with pytest.raises(ConnectorAuthorizationError):
        await service.discover_connector_metadata("metadata", actor="actor")
    assert len(state["requests"]) == count


@pytest.fixture
def provider(monkeypatch):
    """协议服务独立记录收包和 mutation，回读来自远端记录。"""
    state = {"requests": [], "records": {}, "error": None}

    class Handler(BaseHTTPRequestHandler):
        """模拟文档协议，仅使用任务合成记录和凭据。"""

        def log_message(self, *_):
            """避免 HTTP 日志泄露请求参数。"""

        def respond(self, status, payload=None):
            """发出有界 JSON 响应与 provider request ID。"""
            if "business_code" in state and "/bitable/" in self.path and isinstance(payload, dict):
                payload = {**payload, "code": state["business_code"]}
            body = json.dumps(payload).encode() if payload is not None else b""
            if state.get("nonfinite_literal") == "1e999":
                body = body.replace(b": NaN", b": 1e999")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-request-id", "synthetic-receipt")
            self.end_headers()
            self.wfile.write(body)

        def handle_protocol(self):
            """标准操作接受认证，查询分页并保存真实写入结果。"""
            parsed = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            state["requests"].append((self.command, parsed.path, parse_qs(parsed.query), body))
            if parsed.path.endswith("/oauth2/token"):
                assert parse_qs(body.decode())["client_secret"] == ["synthetic"]
                if "auth_reply" in state:
                    return self.respond(200, state["auth_reply"])
                return self.respond(200, {"access_token": "synthetic"})
            if parsed.path.endswith("/internal"):
                assert json.loads(body)["app_secret"] == "synthetic"
                if "auth_reply" in state:
                    return self.respond(200, state["auth_reply"])
                return self.respond(200, {"code": 0, "tenant_access_token": "synthetic"})
            assert self.headers.get("Authorization") == "Bearer synthetic"
            if state["error"] == "readback" and self.command == "GET" and state["records"]:
                return self.respond(403, {"code": 1254302})
            if state["error"] == "http":
                return self.respond(403, [{"errorCode": "INSUFFICIENT_ACCESS"}])
            if state["error"] == "business":
                return self.respond(200, {"code": 1254302, "msg": "synthetic refusal"})
            if parsed.path.endswith("/query"):
                if "page_reply" in state:
                    return self.respond(200, state["page_reply"])
                return self.respond(
                    200,
                    {
                        "totalSize": 2,
                        "done": False,
                        "records": [
                            {
                                "Id": "first",
                                **({"Name": "x" * state.get("query_size", 40000)} if state.get("large_query") else {}),
                            }
                        ],
                        "nextRecordsUrl": "/services/data/v59.0/query/page2",
                    },
                )
            if parsed.path.endswith("/query/page2"):
                return self.respond(
                    200,
                    {
                        "totalSize": 2,
                        "done": True,
                        "records": [
                            {
                                "Id": "second",
                                **({"Name": "y" * state.get("query_size", 40000)} if state.get("large_query") else {}),
                            }
                        ],
                    },
                )
            feishu = parsed.path.startswith("/open-apis/bitable/")
            if feishu and parsed.path.endswith("/fields"):
                return self.respond(
                    200,
                    {
                        "code": 0,
                        "data": {
                            "items": [
                                {"field_id": "fldSynthetic", "field_name": "客户名称", "type": 1},
                                {"field_id": "fldOpportunity", "field_name": "商机名称", "type": 1},
                                {
                                    "field_id": "fldStage",
                                    "field_name": "商机状态",
                                    "type": 3,
                                    "property": {"options": [{"name": "open"}, {"name": "closed"}]},
                                },
                                {
                                    "field_id": "fldCustomerLink",
                                    "field_name": "客户关联",
                                    "type": 18,
                                    "property": {"table_id": "tblCustomer"},
                                },
                            ],
                            "has_more": False,
                        },
                    },
                )
            if feishu and parsed.path.endswith("/tables"):
                return self.respond(
                    200,
                    {
                        "code": 0,
                        "data": {
                            "items": [
                                {"table_id": "tblCustomer", "name": "Customer"},
                                {"table_id": "tblOpportunity", "name": "Opportunity"},
                            ],
                            "has_more": False,
                        },
                    },
                )
            if feishu and parsed.path.endswith("/records/search"):
                assert self.command == "POST"
                return self.respond(200, {"code": 0, "data": {"items": [{"record_id": "filtered"}], "has_more": False}})
            key = parsed.path
            if self.command in {"POST", "PUT", "PATCH"}:
                state["records"][key] = json.loads(body)
                if state["error"] == "after_write":
                    return self.respond(500, {"code": 500})
                if feishu:
                    record = {"record_id": "recSynthetic", "fields": state["records"][key]["fields"]}
                    state["records"][key.rstrip("/") + "/recSynthetic" if self.command == "POST" else key] = record
                    return self.respond(200, {"code": 0, "data": {"record": record}})
                return self.respond(204)
            if feishu and parsed.path.endswith("/records"):
                if "page_reply" in state:
                    return self.respond(200, {"code": 0, "data": state["page_reply"]})
                page = parse_qs(parsed.query).get("page_token", [""])[0]
                return self.respond(
                    200,
                    {
                        "code": 0,
                        "data": {
                            "items": [{"record_id": page or "first"}],
                            "has_more": not page,
                            "page_token": "second" if not page else "",
                        },
                    },
                )
            record = state["records"].get(key, {"Id": "synthetic", "Name": "original"})
            if feishu:
                if state.get("nonfinite"):
                    record = {"record_id": "recSynthetic", "fields": {"客户名称": float("nan")}}
                if state.get("wrong_identity"):
                    record = {**record, "record_id": "recDifferent", "fields": {}}
                return self.respond(200, {"code": 0, "data": {"record": record}})
            if "/Account/ConfiguredExternalId__c/" in parsed.path:
                record = {
                    **record,
                    "ConfiguredExternalId__c": "wrong"
                    if state.get("wrong_identity")
                    else unquote(parsed.path.rsplit("/", 1)[-1]),
                }
            if state.get("nonfinite"):
                record = {**record, "Name": float("nan")}
            return self.respond(
                200,
                {
                    **record,
                    "Id": "different-record" if state.get("wrong_identity") else state.get("served_id", "synthetic"),
                },
            )

        do_GET = handle_protocol
        do_POST = handle_protocol
        do_PATCH = handle_protocol
        do_PUT = handle_protocol

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = socket.gethostbyname(socket.gethostname())
    base = f"http://{host}:{server.server_port}"
    monkeypatch.setattr(feishu_bitable_crm, "FEISHU_BASE_URL", base)
    config = ConnectorHTTPConfig(
        base_url=base,
        allowed_origins=(base,),
        allowed_private_cidrs=(ipaddress.ip_network(host + "/32"),),
        raw_config={
            "api_version": "v59.0",
            "account_external_id_field": "ConfiguredExternalId__c",
            "app_token": "appSynthetic",
            "customer_table_id": "tblCustomer",
            "opportunity_table_id": "tblOpportunity",
            "customer_fields": {"name": "客户名称"},
            "opportunity_fields": {"name": "商机名称"},
        },
    )
    try:
        yield state, config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def invoke(provider, kind, slug, params, *, write=False):
    """通过正式 adapter 和真实安全传输执行合成协议。"""
    _, config = provider
    adapter = SalesforceAdapter() if kind == "salesforce" else feishu_bitable_crm.FeishuBitableCRMAdapter()
    credentials = {
        "client_id": b"synthetic",
        "client_secret": b"synthetic",
        "app_id": b"synthetic",
        "app_secret": b"synthetic",
    }
    operation = FrozenOperation(
        operation_id=1,
        slug=slug,
        name=slug,
        operation_type="write" if write else "read",
        http_method="PATCH" if write else "GET",
        endpoint_template="/",
        query_template=None,
        body_template=None,
        request_schema=None,
        response_mapping=None,
        response_type="json",
        approval_policy="required" if write else None,
        retry_policy=None,
        remote_idempotency=None,
    )
    execution = ConnectorExecution(
        invocation_id="synthetic",
        actor_uid="synthetic",
        consumer_type="admin_test",
        logical_call_key="synthetic",
        connector_revision=1,
        operation_revision=1,
    )
    return await adapter.execute(
        http_config=config, credentials=credentials, operation=operation, params=params, execution=execution
    )


@pytest.mark.parametrize(
    "record_type,fields,filters,expected",
    [
        (
            "customer",
            {"name": "fldSynthetic"},
            {"name": "query-needle"},
            [{"field_name": "客户名称", "operator": "is", "value": ["query-needle"]}],
        ),
        (
            "opportunity",
            {"customer": "客户关联", "stage": "商机状态"},
            {"customer": "recCustomer", "stage": "open"},
            [
                {"field_name": "客户关联", "operator": "is", "value": ["recCustomer"]},
                {"field_name": "商机状态", "operator": "is", "value": ["open"]},
            ],
        ),
    ],
)
async def test_feishu_query_uses_only_mapped_finite_filter_conditions(provider, record_type, fields, filters, expected):
    """有限字段过滤经真实 HTTP 传递，不能静默降成全表读取。"""
    state, config = provider
    config.raw_config[record_type + "_fields"] = fields
    result = await invoke(provider, "feishu", "query_" + record_type, {"filters": filters, "page_size": 1})
    assert result.success and result.data["items"] == [{"record_id": "filtered", "fields": {}}]
    request = state["requests"][-1]
    assert request[0] == "POST" and request[1].endswith("/records/search")
    assert json.loads(request[3]) == {"filter": {"conjunction": "and", "conditions": expected}}
    assert request[2] == {"page_size": ["1"]}


@pytest.mark.parametrize(
    "params", [{"filter": "arbitrary DSL"}, {"filters": {"unmapped": "value"}}, {"filters": {"name": ["not-a-scalar"]}}]
)
async def test_feishu_query_rejects_unsupported_filter_instead_of_ignoring_it(provider, params):
    """自定义 schema 放宽也不能绕过 adapter 字段和操作边界。"""
    state, _ = provider
    result = await invoke(provider, "feishu", "query_customer", params)
    assert not result.success and result.error_code == "invalid_params"
    assert not any("/records" in request[1] for request in state["requests"])


async def test_salesforce_query_consumes_bounded_next_records_url(provider):
    result = await invoke(provider, "salesforce", "query_customer", {"name": "O'Reilly\\", "page_size": 20})
    assert result.success
    assert [record["Id"] for record in result.data["records"]] == ["first", "second"]
    assert result.provider_request_id == "synthetic-receipt"


@pytest.mark.parametrize(
    "slug,params",
    [
        ("get_customer", {"account_id": "synthetic"}),
        ("get_opportunity", {"opportunity_id": "synthetic"}),
        ("query_customer", {}),
    ],
)
async def test_salesforce_read_http_error_is_not_success(provider, slug, params):
    provider[0]["error"] = "http"
    result = await invoke(provider, "salesforce", slug, params)
    assert not result.success
    assert result.remote_outcome == "failed"
    assert result.response_status == 403


@pytest.mark.parametrize(
    "slug,params",
    [
        ("upsert_customer", {"external_id_value": "synthetic", "Name": "updated"}),
        ("update_opportunity", {"opportunity_id": "synthetic", "Name": "updated"}),
    ],
)
async def test_salesforce_empty_write_response_still_reads_remote_record(provider, slug, params):
    result = await invoke(provider, "salesforce", slug, params, write=True)
    assert result.success
    assert result.data["Name"] == "updated"
    assert [request[0] for request in provider[0]["requests"]] == ["POST", "PATCH", "GET"]
    if slug == "upsert_customer":
        assert "/Account/ConfiguredExternalId__c/" in provider[0]["requests"][1][1]


@pytest.mark.parametrize("missing", [False, True])
async def test_salesforce_upsert_external_field_is_owned_by_configuration(provider, missing):
    """模型不能选择外部键字段，未配置时也不能猜默认字段并写入。"""
    state, config = provider
    params = {"external_id_value": "synthetic", "Name": "updated"}
    if missing:
        config.raw_config.pop("account_external_id_field")
    else:
        params["external_id_field"] = "ArbitraryField__c"
    result = await invoke(provider, "salesforce", "upsert_customer", params, write=True)
    assert not result.success
    assert not any(request[0] == "PATCH" for request in state["requests"])


async def test_feishu_readonly_metadata_discovers_owned_tables_and_real_field_types(provider):
    """配置目录来自实际 HTTP 表/字段响应，类型与字段 ID 均回读。"""
    _, config = provider
    result = await feishu_bitable_crm.FeishuBitableCRMAdapter().discover_metadata(
        config, {"app_id": b"synthetic", "app_secret": b"synthetic"}
    )
    assert {table["table_id"] for table in result["tables"]} == {"tblCustomer", "tblOpportunity"}
    assert result["fields"]["tblCustomer"][0]["field_id"] == "fldSynthetic"
    assert result["fields"]["tblCustomer"][0]["type"] == 1


@pytest.mark.parametrize("value", [12, True, {"unexpected": "object"}])
async def test_feishu_write_rejects_wrong_actual_field_type_before_business_send(provider, value):
    """字段元数据确认文本后，数字等错误格式不能直接传给写接口。"""
    state, _ = provider
    result = await invoke(provider, "feishu", "create_customer", {"name": value}, write=True)
    assert not result.success and result.error_code == "invalid_params" and result.remote_outcome == "not_sent"
    assert not any(request[0] == "POST" and request[1].endswith("/records") for request in state["requests"])


@pytest.mark.parametrize(
    "kind,slug,params",
    [
        ("salesforce", "update_opportunity", {"opportunity_id": "synthetic", "Name": "updated"}),
        ("feishu", "create_customer", {"name": "updated"}),
    ],
)
async def test_provider_write_server_error_after_mutation_is_unknown(provider, kind, slug, params):
    provider[0]["error"] = "after_write"
    result = await invoke(provider, kind, slug, params, write=True)
    assert provider[0]["records"]
    assert not result.success
    assert result.remote_outcome == "unknown"


@pytest.mark.parametrize(
    "kind,slug,params",
    [
        ("salesforce", "update_opportunity", {"opportunity_id": "synthetic", "Name": "updated"}),
        ("feishu", "create_customer", {"name": "updated"}),
    ],
)
async def test_successful_write_receipt_survives_readback_refusal(provider, kind, slug, params):
    """后续 GET 失败不能抹除已确认写 receipt，也不允许盲重发。"""
    provider[0]["error"] = "readback"
    result = await invoke(provider, kind, slug, params, write=True)
    assert provider[0]["records"]
    assert not result.success and result.remote_outcome == "succeeded"
    assert result.error_code == "readback_failed" and result.provider_evidence


async def test_feishu_field_id_is_resolved_before_record_write(provider):
    """字段目录独立提供 ID→名称，记录 body 不能直接携带 field ID。"""
    provider[1].raw_config["customer_fields"] = {"name": "fldSynthetic"}
    result = await invoke(provider, "feishu", "create_customer", {"name": "updated"}, write=True)
    assert result.success and result.data["fields"] == {"客户名称": "updated"}
    assert any(path.endswith("/fields") for _, path, _, _ in provider[0]["requests"])


@pytest.mark.parametrize(
    "kind,slug,params",
    [
        ("salesforce", "update_opportunity", {"opportunity_id": "%252e%252e%252fother", "Name": "updated"}),
        ("feishu", "update_customer", {"record_id": "%252e%252e%252fother", "name": "updated"}),
    ],
)
async def test_provider_record_identifier_cannot_escape_bound_path(provider, kind, slug, params):
    """真实传输前拒绝多重编码路径逃逸，认证成功也不能产生业务收包。"""
    result = await invoke(provider, kind, slug, params, write=True)
    assert not result.success and result.remote_outcome == "not_sent"
    assert provider[0]["records"] == {}
    assert len(provider[0]["requests"]) == 1


@pytest.mark.parametrize("slug", ["query_customer", "query_opportunity"])
async def test_feishu_query_has_explicit_bounded_page_token_contract(provider, slug):
    first = await invoke(provider, "feishu", slug, {"page_size": 1})
    second = await invoke(provider, "feishu", slug, {"page_size": 1, "page_token": first.data["page_token"]})
    assert first.success and second.success
    assert first.data["has_more"] and not second.data["has_more"]
    assert second.data["items"] == [{"record_id": "second", "fields": {}}]


async def test_feishu_http_200_business_error_is_failed(provider):
    provider[0]["error"] = "business"
    result = await invoke(provider, "feishu", "get_customer", {"record_id": "recSynthetic"})
    assert not result.success and result.error_code == "provider_error"


@pytest.mark.parametrize("slug", ["create_customer", "create_opportunity", "update_customer", "update_opportunity"])
async def test_feishu_standard_write_reads_independent_remote_record(provider, slug):
    params = {"name": "updated"}
    if slug.startswith("update"):
        params["record_id"] = "recSynthetic"
    result = await invoke(provider, "feishu", slug, params, write=True)
    assert result.success
    assert result.data["fields"] == {"客户名称" if slug.endswith("customer") else "商机名称": "updated"}
    assert [request[0] for request in provider[0]["requests"]] == [
        "POST",
        "GET",
        "PUT" if slug.startswith("update") else "POST",
        "GET",
    ]
