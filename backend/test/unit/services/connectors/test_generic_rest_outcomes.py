"""适配器依据可观察协议事实区分写失败和结果未知。"""

import httpx
import json
import pytest

from yuxi.services.connectors.adapters.generic_rest import GenericRESTAdapter
from yuxi.services.connectors.base import ConnectorExecution, FrozenOperation
from yuxi.services.connectors.http_client import ConnectorHTTPConfig


@pytest.mark.parametrize("failure", ["timeout", "server_error", "nonfinite"])
async def test_remote_write_with_an_indeterminate_response_remains_unknown(monkeypatch, failure):
    """远端已经接受写入、响应丢失时不能报告无副作用的失败。"""
    mutations = []

    def provider(request):
        mutations.append(request.method)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic response lost", request=request)
        if failure == "nonfinite":
            return httpx.Response(200, stream=httpx.ByteStream(b'{"value":NaN}'))
        return httpx.Response(
            500, stream=httpx.ByteStream(json.dumps({"message": "synthetic failure after write"}).encode())
        )

    client_type = httpx.AsyncClient

    def provider_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(provider)
        return client_type(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", provider_client)
    operation = FrozenOperation(
        operation_id=1,
        slug="write",
        name="write",
        operation_type="write",
        http_method="POST",
        endpoint_template="/write",
        query_template=None,
        body_template={},
        request_schema=None,
        response_mapping=None,
        response_type="json",
        approval_policy="preauthorized",
        retry_policy=None,
        remote_idempotency=None,
    )
    execution = ConnectorExecution(
        invocation_id="test",
        actor_uid="actor",
        consumer_type="admin_test",
        logical_call_key="test",
        connector_revision=1,
        operation_revision=1,
    )
    result = await GenericRESTAdapter().execute(
        http_config=ConnectorHTTPConfig(base_url="https://api.example.com", raw_config={"auth_type": "none"}),
        operation=operation,
        credentials={},
        params={},
        execution=execution,
    )
    assert mutations == ["POST"]
    assert result.remote_outcome == "unknown"
    assert (
        result.error_code
        == {"timeout": "timeout", "server_error": "provider_error", "nonfinite": "mapping_error"}[failure]
    )


async def test_mapping_failure_preserves_a_successful_write_receipt(monkeypatch):
    """成功响应之后的本地映射失败不能把远端写结局改为未知。"""
    mutations = []

    def provider(request):
        mutations.append(request.method)
        return httpx.Response(200, stream=httpx.ByteStream(b'{"created":true}'))

    client_type = httpx.AsyncClient

    def provider_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(provider)
        return client_type(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", provider_client)
    operation = FrozenOperation(
        operation_id=1,
        slug="write",
        name="write",
        operation_type="write",
        http_method="POST",
        endpoint_template="/write",
        query_template=None,
        body_template={},
        request_schema=None,
        response_mapping={"result": "missing.required"},
        response_type="json",
        approval_policy="preauthorized",
        retry_policy=None,
        remote_idempotency=None,
    )
    result = await GenericRESTAdapter().execute(
        http_config=ConnectorHTTPConfig(base_url="https://api.example.com", raw_config={"auth_type": "none"}),
        operation=operation,
        credentials={},
        params={},
        execution=ConnectorExecution(
            invocation_id="test",
            actor_uid="actor",
            consumer_type="admin_test",
            logical_call_key="test",
            connector_revision=1,
            operation_revision=1,
        ),
    )
    assert mutations == ["POST"]
    assert result.remote_outcome == "succeeded"
    assert result.error_code == "mapping_error"
    assert result.success is False
