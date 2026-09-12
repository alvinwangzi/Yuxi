"""resolve_image_gen_env 单元测试。

验证从模型缓存解析 image 类型模型并构造沙盒环境变量的逻辑。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import pytest

import yuxi.models.providers.cache as cache_module
from yuxi.models.providers.cache import REDIS_CACHE_KEY

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_model_cache_local_ttl():
    """每个测试前清除 model_cache 的本地 TTL 缓存，避免测试间数据残留。"""
    from yuxi.models.providers.cache import model_cache

    model_cache._invalidate_local()
    yield
    model_cache._invalidate_local()


class _FakeRedis:
    def __init__(self, data: dict[str, str] | None = None):
        self.data: dict[str, str] = data or {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> bool:
        self.data[key] = value
        return True


def _patch_redis(monkeypatch: pytest.MonkeyPatch, redis: _FakeRedis) -> None:
    @contextmanager
    def fake_sync_redis_client(*args, **kwargs):
        del args, kwargs
        yield redis

    monkeypatch.setattr(cache_module, "sync_redis_client", fake_sync_redis_client)


def _seed_image_model(redis: _FakeRedis, **overrides: Any) -> None:
    """向 fake Redis 写入一个 image 类型模型。"""
    base: dict[str, Any] = {
        "provider_id": "test-provider",
        "model_id": "test-image-model",
        "model_type": "image",
        "display_name": "Test Image",
        "api_key": "sk-image-key",
        "base_url": "https://image.example.com/v1",
        "provider_type": "openai",
    }
    base.update(overrides)
    redis.data[REDIS_CACHE_KEY] = json.dumps({f"{base['provider_id']}:{base['model_id']}": base})


def test_resolve_image_gen_env_returns_image_model_config(monkeypatch: pytest.MonkeyPatch):
    """存在 image 模型时返回 IMAGE_GEN_* 环境变量和 IMAGE_GEN_MODELS 列表。"""
    redis = _FakeRedis()
    _patch_redis(monkeypatch, redis)
    _seed_image_model(redis)

    from yuxi.models.providers.cache import resolve_image_gen_env

    env = resolve_image_gen_env()

    assert env["IMAGE_GEN_API_KEY"] == "sk-image-key"
    assert env["IMAGE_GEN_BASE_URL"] == "https://image.example.com/v1"
    assert env["IMAGE_GEN_MODEL"] == "test-image-model"

    models = json.loads(env["IMAGE_GEN_MODELS"])
    assert len(models) == 1
    assert models[0]["model"] == "test-image-model"
    assert models[0]["base_url"] == "https://image.example.com/v1"
    assert models[0]["api_key"] == "sk-image-key"
    assert models[0]["display_name"] == "Test Image"


def test_resolve_image_gen_env_returns_empty_when_no_image_models(monkeypatch: pytest.MonkeyPatch):
    """缓存中没有 image 模型时返回空字典。"""
    redis = _FakeRedis()
    _patch_redis(monkeypatch, redis)
    redis.data[REDIS_CACHE_KEY] = json.dumps(
        {
            "provider:chat-model": {
                "provider_id": "provider",
                "model_id": "chat-model",
                "model_type": "chat",
                "display_name": "Chat",
                "api_key": "sk-chat",
                "base_url": "https://example.com/v1",
                "provider_type": "openai",
            }
        }
    )

    from yuxi.models.providers.cache import resolve_image_gen_env

    assert resolve_image_gen_env() == {}


def test_resolve_image_gen_env_returns_empty_when_cache_unavailable(monkeypatch: pytest.MonkeyPatch):
    """Redis 不可用时优雅返回空字典。"""

    @contextmanager
    def failing_redis(*args, **kwargs):
        raise ConnectionError("Redis unavailable")
        yield  # noqa: unreachable

    monkeypatch.setattr(cache_module, "sync_redis_client", failing_redis)

    from yuxi.models.providers.cache import resolve_image_gen_env

    assert resolve_image_gen_env() == {}


def test_resolve_image_gen_env_omits_empty_api_key(monkeypatch: pytest.MonkeyPatch):
    """API Key 为空时不包含 IMAGE_GEN_API_KEY。"""
    redis = _FakeRedis()
    _patch_redis(monkeypatch, redis)
    _seed_image_model(redis, api_key="")

    from yuxi.models.providers.cache import resolve_image_gen_env

    env = resolve_image_gen_env()

    assert "IMAGE_GEN_API_KEY" not in env
    assert env["IMAGE_GEN_BASE_URL"] == "https://image.example.com/v1"
    assert env["IMAGE_GEN_MODEL"] == "test-image-model"


def test_resolve_image_gen_env_includes_all_image_models(monkeypatch: pytest.MonkeyPatch):
    """多个 image 模型时 IMAGE_GEN_MODELS 包含全部条目，默认取第一个。"""
    redis = _FakeRedis()
    _patch_redis(monkeypatch, redis)

    models_data = {
        "provider-a:model-lite": {
            "provider_id": "provider-a",
            "model_id": "model-lite",
            "model_type": "image",
            "display_name": "Lite Image",
            "api_key": "sk-a",
            "base_url": "https://a.example.com/v1",
            "provider_type": "openai",
        },
        "provider-b:model-hd": {
            "provider_id": "provider-b",
            "model_id": "model-hd",
            "model_type": "image",
            "display_name": "HD Image",
            "api_key": "sk-b",
            "base_url": "https://b.example.com/v1",
            "provider_type": "openai",
        },
    }
    redis.data[REDIS_CACHE_KEY] = json.dumps(models_data)

    from yuxi.models.providers.cache import resolve_image_gen_env

    env = resolve_image_gen_env()

    # 默认取第一个（按 Redis 字典序，provider-a 在前）
    assert env["IMAGE_GEN_MODEL"] in ("model-lite", "model-hd")

    models = json.loads(env["IMAGE_GEN_MODELS"])
    assert len(models) == 2
    model_ids = {m["model"] for m in models}
    assert model_ids == {"model-lite", "model-hd"}

    # 每个模型保留各自的 base_url 和 api_key
    for m in models:
        if m["model"] == "model-lite":
            assert m["base_url"] == "https://a.example.com/v1"
            assert m["api_key"] == "sk-a"
        elif m["model"] == "model-hd":
            assert m["base_url"] == "https://b.example.com/v1"
            assert m["api_key"] == "sk-b"
