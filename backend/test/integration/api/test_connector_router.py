"""连接器管理 API 集成测试 — 真实 HTTP 调用与权限验收。"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
]


class TestAdminConnectorCRUD:
    """管理员连接器管理 API。"""

    async def test_list_connector_types(self, test_client, admin_headers):
        response = await test_client.get("/api/system/connectors/types", headers=admin_headers)
        assert response.status_code == 200
        types = response.json()
        assert isinstance(types, list)
        type_slugs = {t["slug"] for t in types}
        assert "generic_rest" in type_slugs

    async def test_create_and_get_connector(self, test_client, admin_headers):
        slug = f"pytest-api-{uuid.uuid4().hex[:8]}"
        create_body = {
            "slug": slug,
            "name": f"API 测试连接器 {slug}",
            "connector_type": "generic_rest",
            "description": "集成测试创建",
            "config": {
                "base_url": "https://httpbin.org",
                "allowed_origins": ["https://httpbin.org"],
            },
        }
        create_resp = await test_client.post(
            "/api/system/connectors", json=create_body, headers=admin_headers,
        )
        assert create_resp.status_code == 200
        created = create_resp.json()
        assert created["slug"] == slug
        assert created["revision"] == 1

        get_resp = await test_client.get(
            f"/api/system/connectors/{slug}", headers=admin_headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["slug"] == slug

    async def test_update_connector_increments_revision(self, test_client, admin_headers):
        slug = f"pytest-patch-{uuid.uuid4().hex[:8]}"
        await test_client.post(
            "/api/system/connectors",
            json={
                "slug": slug,
                "name": "版本测试",
                "connector_type": "generic_rest",
                "config": {"base_url": "https://httpbin.org", "allowed_origins": ["https://httpbin.org"]},
            },
            headers=admin_headers,
        )

        patch_resp = await test_client.patch(
            f"/api/system/connectors/{slug}",
            json={"name": "版本测试-更新", "expected_revision": 1},
            headers=admin_headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["revision"] == 2

    async def test_delete_connector(self, test_client, admin_headers):
        slug = f"pytest-del-{uuid.uuid4().hex[:8]}"
        await test_client.post(
            "/api/system/connectors",
            json={
                "slug": slug,
                "name": "删除测试",
                "connector_type": "generic_rest",
                "config": {"base_url": "https://httpbin.org", "allowed_origins": ["https://httpbin.org"]},
            },
            headers=admin_headers,
        )

        del_resp = await test_client.delete(
            f"/api/system/connectors/{slug}", headers=admin_headers,
        )
        assert del_resp.status_code == 200

        get_resp = await test_client.get(
            f"/api/system/connectors/{slug}", headers=admin_headers,
        )
        assert get_resp.status_code == 404


class TestAdminOperations:
    """管理员操作管理 API。"""

    async def test_create_and_list_operations(self, test_client, admin_headers):
        slug = f"pytest-ops-{uuid.uuid4().hex[:8]}"
        await test_client.post(
            "/api/system/connectors",
            json={
                "slug": slug,
                "name": "操作测试",
                "connector_type": "generic_rest",
                "config": {"base_url": "https://httpbin.org", "allowed_origins": ["https://httpbin.org"]},
            },
            headers=admin_headers,
        )

        op_resp = await test_client.post(
            f"/api/system/connectors/{slug}/operations",
            json={
                "slug": "query_data",
                "name": "查询数据",
                "operation_type": "read",
                "http_method": "GET",
                "endpoint_template": "/get",
            },
            headers=admin_headers,
        )
        assert op_resp.status_code == 200
        assert op_resp.json()["slug"] == "query_data"

        list_resp = await test_client.get(
            f"/api/system/connectors/{slug}/operations", headers=admin_headers,
        )
        assert list_resp.status_code == 200
        ops = list_resp.json()
        assert len(ops) >= 1
        assert any(o["slug"] == "query_data" for o in ops)


class TestUserConnectorAccess:
    """普通用户连接器访问 API。"""

    async def test_user_list_connectors(self, test_client, standard_user):
        response = await test_client.get(
            "/api/connectors", headers=standard_user["headers"],
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_user_cannot_access_admin_api(self, test_client, standard_user):
        response = await test_client.get(
            "/api/system/connectors", headers=standard_user["headers"],
        )
        assert response.status_code in (401, 403)


class TestApprovalDecision:
    """审批决策 API。"""

    async def test_decision_requires_authentication(self, test_client):
        response = await test_client.post(
            "/api/connectors/invocations/fake-id/decision",
            json={"decision": "approve"},
        )
        assert response.status_code in (401, 403)
