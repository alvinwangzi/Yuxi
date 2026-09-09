from __future__ import annotations

from types import SimpleNamespace

import pytest
import yuxi.agents.backends.sandbox.provider as provider_module

from yuxi.agents.backends.sandbox.provider import sandbox_provisioner_token
from yuxi.agents.backends.sandbox.provisioner_client import ProvisionerClient


def test_provisioner_client_sends_bearer_token(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"sandboxes": [], "count": 0})

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    client.health()

    assert calls == [
        {
            "method": "GET",
            "url": "http://sandbox-provisioner:8002/health",
            "timeout": client._timeout,
            "headers": {"Authorization": "Bearer test-provisioner-token-that-is-long-enough"},
        }
    ]


def test_provisioner_client_can_disable_sandbox_environment(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"sandbox_id": "sandbox-1", "sandbox_url": "http://sandbox"},
        )

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    client.create("sandbox-1", "thread-1", "user-1", {"SECRET": "value"}, inherit_env=False)

    assert calls[0]["json"]["inherit_env"] is False
    create_timeout = calls[0]["timeout"]
    assert create_timeout is client._create_timeout
    assert create_timeout.connect == 20
    assert create_timeout.write == 20
    assert create_timeout.pool == 20
    assert create_timeout.read is None


def test_provisioner_client_sends_project_workdir_contract(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "sandbox_id": "sandbox-1",
                "sandbox_url": "http://sandbox",
                "generation": "generation-1",
                "workdir_path": "projects/11111111-1111-4111-8111-111111111111",
            },
        )

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    record = client.create(
        "sandbox-1", "root-thread", "user-1", workdir_path="projects/11111111-1111-4111-8111-111111111111"
    )

    assert calls[0]["json"]["workdir_path"] == "projects/11111111-1111-4111-8111-111111111111"
    assert record.generation == "generation-1"
    assert record.workdir_path == "projects/11111111-1111-4111-8111-111111111111"


def test_provisioner_client_delete_sends_expected_generation(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    client.delete("sandbox-1", expected_generation="generation-1")

    assert calls[0]["params"] == {"expected_generation": "generation-1"}
    assert calls[0]["timeout"] is client._delete_timeout
    assert client._delete_timeout.read == 120


def test_sandbox_provider_uses_configured_delete_timeout(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, _url, *, token, delete_timeout_seconds):
            captured.update(token=token, delete_timeout_seconds=delete_timeout_seconds)

        def verify_credentials(self):
            pass

    monkeypatch.setenv(
        "SANDBOX_PROVISIONER_TOKEN",
        "test-provisioner-token-that-is-long-enough",
    )
    monkeypatch.setenv("SANDBOX_PROVISIONER_DELETE_TIMEOUT_SECONDS", "90")
    monkeypatch.setattr(provider_module, "ProvisionerClient", _FakeClient)

    provider_module.ProvisionerSandboxProvider()

    assert captured == {
        "token": "test-provisioner-token-that-is-long-enough",
        "delete_timeout_seconds": 90,
    }


def test_sandbox_provider_init_fails_on_credential_mismatch(monkeypatch):
    class _FakeClient:
        def __init__(self, _url, *, token, delete_timeout_seconds):
            pass

        def verify_credentials(self):
            raise RuntimeError("sandbox provisioner rejected credentials (401)")

    monkeypatch.setenv(
        "SANDBOX_PROVISIONER_TOKEN",
        "test-provisioner-token-that-is-long-enough",
    )
    monkeypatch.setattr(provider_module, "ProvisionerClient", _FakeClient)

    with pytest.raises(RuntimeError, match="rejected credentials"):
        provider_module.ProvisionerSandboxProvider()


def test_sandbox_provisioner_token_reads_environment(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVISIONER_TOKEN", "test-provisioner-token-that-is-long-enough")

    assert sandbox_provisioner_token() == "test-provisioner-token-that-is-long-enough"


def test_sandbox_provisioner_token_is_required(monkeypatch):
    monkeypatch.delenv("SANDBOX_PROVISIONER_TOKEN", raising=False)

    with pytest.raises(ValueError, match="at least 32 characters"):
        sandbox_provisioner_token()


def test_verify_credentials_sends_authenticated_request(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"sandboxes": [], "count": 0})

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    client.verify_credentials()

    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "http://sandbox-provisioner:8002/api/sandboxes"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-provisioner-token-that-is-long-enough"


def test_verify_credentials_raises_on_401(monkeypatch):
    def fake_request(**kwargs):
        return SimpleNamespace(status_code=401, text='{"detail":"invalid provisioner credentials"}')

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="stale-token-value-that-is-at-least-32-chars",
    )

    with pytest.raises(RuntimeError, match="rejected credentials.*force-recreate"):
        client.verify_credentials()


def test_verify_credentials_raises_on_server_error(monkeypatch):
    def fake_request(**kwargs):
        return SimpleNamespace(status_code=503, text="service unavailable")

    monkeypatch.setattr("yuxi.agents.backends.sandbox.provisioner_client.httpx.request", fake_request)
    client = ProvisionerClient(
        "http://sandbox-provisioner:8002",
        token="test-provisioner-token-that-is-long-enough",
    )

    with pytest.raises(RuntimeError, match="credential probe failed.*503"):
        client.verify_credentials()
