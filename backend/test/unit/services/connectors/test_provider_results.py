"""预置适配器无映射时保留标准操作的业务结果。"""

import httpx
import json
import pytest

from yuxi.services.connectors.adapters.salesforce import SalesforceAdapter
from yuxi.services.connectors.adapters.feishu_bitable_crm import FeishuBitableCRMAdapter
from yuxi.services.connectors.base import ConnectorExecution, FrozenOperation
from yuxi.services.connectors.http_client import ConnectorHTTPConfig


@pytest.mark.parametrize("provider_type", ["salesforce", "feishu"])
async def test_standard_provider_result_without_mapping_is_not_replaced_with_an_empty_object(
    monkeypatch, provider_type
):
    """使用外部协议响应作 oracle，公共结果能直接用于持久回放。"""
    expected = (
        {"Id": "synthetic", "Name": "Synthetic"}
        if provider_type == "salesforce"
        else {
            "record_id": "synthetic",
            "fields": {"Name": "Synthetic"},
        }
    )

    def response(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, stream=httpx.ByteStream(b'{"access_token":"synthetic-only"}'))
        if request.url.path.endswith("/internal"):
            return httpx.Response(200, stream=httpx.ByteStream(b'{"code":0,"tenant_access_token":"synthetic-only"}'))
        if request.url.path.endswith("/fields"):
            return httpx.Response(
                200,
                stream=httpx.ByteStream(
                    b'{"code":0,"data":{"items":[{"field_id":"fldName","field_name":"Name","type":1}],"has_more":false}}'
                ),
            )
        payload = expected if provider_type == "salesforce" else {"code": 0, "data": {"record": expected}}
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(payload).encode()))

    client_type = httpx.AsyncClient

    def provider_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(response)
        return client_type(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", provider_client)
    adapter = SalesforceAdapter() if provider_type == "salesforce" else FeishuBitableCRMAdapter()
    config = ConnectorHTTPConfig(
        base_url="https://salesforce.example.com" if provider_type == "salesforce" else "https://open.feishu.cn",
        raw_config={
            "api_version": "v60.0",
            "app_token": "synthetic",
            "customer_table_id": "synthetic",
            "customer_fields": {"name": "fldName"},
        },
    )
    operation = FrozenOperation(
        operation_id=1,
        slug="get_customer",
        name="get customer",
        operation_type="read",
        http_method="GET",
        endpoint_template="/get",
        query_template=None,
        body_template=None,
        request_schema=None,
        response_mapping=None,
        response_type="json",
        approval_policy=None,
        retry_policy=None,
        remote_idempotency=None,
    )
    result = await adapter.execute(
        http_config=config,
        credentials={key: b"synthetic-only" for key in ("client_id", "client_secret", "app_id", "app_secret")},
        operation=operation,
        params={"account_id": "synthetic", "record_id": "synthetic"},
        execution=ConnectorExecution(
            invocation_id="synthetic",
            actor_uid="actor",
            consumer_type="admin_test",
            logical_call_key="synthetic",
            connector_revision=1,
            operation_revision=1,
        ),
    )
    assert result.success
    assert result.data == expected
    assert result.mapped_result is None
