"""P1: Channel 抽象层 + 飞书 Channel 单元测试。"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yuxi.services.channels.base import (
    Channel,
    ChannelConfig,
    ChannelSendError,
    InboundMessage,
    OutboundMessage,
)
from yuxi.services.channels.manager import (
    ChannelManager,
    _CHANNEL_REGISTRY,
    get_registered_channel_types,
    register_channel_type,
)


# ── 测试用 Channel 实现 ──────────────────────────────────


class DummyChannel(Channel):
    """测试用 Channel 实现。"""

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self.started = False
        self.stopped = False
        self.sent_messages: list[OutboundMessage] = []
        self._on_message = None

    async def start(self, on_message: Any) -> None:
        self._on_message = on_message
        self.started = True
        self._running = True

    async def stop(self) -> None:
        self.stopped = True
        self._running = False
        self._on_message = None

    async def send(self, message: OutboundMessage) -> None:
        self.sent_messages.append(message)

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "channel_type": "dummy"}


# ── 数据模型测试 ──────────────────────────────────────────


def test_inbound_message_stable_message_id():
    msg = InboundMessage(
        channel_type="feishu",
        channel_chat_id="chat_123",
        sender_id="user_1",
        text="hello",
        message_id="msg_abc",
    )
    assert msg.stable_message_id == "msg_abc"


def test_inbound_message_stable_message_id_generates_uuid():
    msg = InboundMessage(
        channel_type="feishu",
        channel_chat_id="chat_123",
        sender_id="user_1",
        text="hello",
    )
    assert msg.stable_message_id  # 不为空
    assert len(msg.stable_message_id) > 10  # UUID 长度


def test_channel_config_get_credential():
    config = ChannelConfig(
        slug="test",
        channel_type="feishu",
        credentials={"app_id": "cli_123", "app_secret": "secret"},
    )
    assert config.get_credential("app_id") == "cli_123"
    assert config.get_credential("missing") is None
    assert config.get_credential("missing", "default") == "default"


def test_outbound_message_defaults():
    msg = OutboundMessage(
        channel_type="feishu",
        channel_chat_id="chat_123",
        text="reply",
    )
    assert msg.reply_to_message_id is None
    assert msg.extra == {}


# ── ChannelManager 测试 ──────────────────────────────────


@pytest.fixture(autouse=True)
def _register_dummy_channel():
    """确保 DummyChannel 注册到 registry。"""
    if "dummy" not in _CHANNEL_REGISTRY:
        register_channel_type("dummy", DummyChannel)
    yield
    # 不清理，保持注册以便后续测试


@pytest.mark.asyncio
async def test_manager_create_channel():
    manager = ChannelManager()
    config = ChannelConfig(slug="test-dummy", channel_type="dummy")
    channel = await manager.create_channel(config)
    assert channel.slug == "test-dummy"
    assert channel.channel_type == "dummy"
    assert manager.get_channel("test-dummy") is channel


@pytest.mark.asyncio
async def test_manager_start_and_stop():
    manager = ChannelManager()
    config = ChannelConfig(slug="test-start", channel_type="dummy")
    await manager.create_channel(config)

    handler = AsyncMock()
    manager.set_message_handler(handler)

    channel = await manager.start_channel("test-start")
    assert channel.is_running

    await manager.stop_channel("test-start")
    assert not channel.is_running


@pytest.mark.asyncio
async def test_manager_start_without_handler_raises():
    manager = ChannelManager()
    config = ChannelConfig(slug="test-no-handler", channel_type="dummy")
    await manager.create_channel(config)

    with pytest.raises(RuntimeError, match="未设置消息处理器"):
        await manager.start_channel("test-no-handler")


@pytest.mark.asyncio
async def test_manager_send_message():
    manager = ChannelManager()
    config = ChannelConfig(slug="test-send", channel_type="dummy")
    await manager.create_channel(config)
    manager.set_message_handler(AsyncMock())
    await manager.start_channel("test-send")

    msg = OutboundMessage(channel_type="dummy", channel_chat_id="chat", text="hello")
    await manager.send_message("test-send", msg)

    channel = manager.get_channel("test-send")
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0].text == "hello"


@pytest.mark.asyncio
async def test_manager_send_to_non_running_channel_raises():
    manager = ChannelManager()
    config = ChannelConfig(slug="test-not-running", channel_type="dummy")
    await manager.create_channel(config)

    msg = OutboundMessage(channel_type="dummy", channel_chat_id="chat", text="hello")
    with pytest.raises(ChannelSendError, match="未运行"):
        await manager.send_message("test-not-running", msg)


@pytest.mark.asyncio
async def test_manager_remove_channel():
    manager = ChannelManager()
    config = ChannelConfig(slug="test-remove", channel_type="dummy")
    await manager.create_channel(config)
    manager.set_message_handler(AsyncMock())
    await manager.start_channel("test-remove")

    await manager.remove_channel("test-remove")
    assert manager.get_channel("test-remove") is None


@pytest.mark.asyncio
async def test_manager_start_all():
    manager = ChannelManager()
    for i in range(3):
        config = ChannelConfig(slug=f"batch-{i}", channel_type="dummy", enabled=True)
        await manager.create_channel(config)
    manager.set_message_handler(AsyncMock())
    await manager.start_all()

    for i in range(3):
        ch = manager.get_channel(f"batch-{i}")
        assert ch.is_running


@pytest.mark.asyncio
async def test_manager_stop_all():
    manager = ChannelManager()
    for i in range(3):
        config = ChannelConfig(slug=f"stop-{i}", channel_type="dummy", enabled=True)
        await manager.create_channel(config)
    manager.set_message_handler(AsyncMock())
    await manager.start_all()
    await manager.stop_all()

    for i in range(3):
        ch = manager.get_channel(f"stop-{i}")
        assert not ch.is_running


@pytest.mark.asyncio
async def test_manager_unknown_channel_type_raises():
    manager = ChannelManager()
    config = ChannelConfig(slug="unknown", channel_type="nonexistent")
    with pytest.raises(ValueError, match="未知的 Channel 类型"):
        await manager.create_channel(config)


# ── 飞书 Channel 测试 ────────────────────────────────────


@pytest.mark.asyncio
async def test_feishu_channel_challenge():
    """飞书 URL 验证 challenge 应原样返回。"""
    from yuxi.services.channels.feishu import FeishuChannel

    config = ChannelConfig(
        slug="feishu-test",
        channel_type="feishu",
        credentials={"app_id": "test_id", "app_secret": "test_secret"},
    )
    channel = FeishuChannel(config)

    result = await channel.handle_webhook_event({"challenge": "test_challenge_123"})
    assert result == {"challenge": "test_challenge_123"}


@pytest.mark.asyncio
async def test_feishu_channel_duplicate_event_ignored():
    """重复 event_id 应被去重。"""
    from yuxi.services.channels.feishu import FeishuChannel

    config = ChannelConfig(
        slug="feishu-dedup",
        channel_type="feishu",
        credentials={"app_id": "test_id", "app_secret": "test_secret"},
    )
    channel = FeishuChannel(config)

    event = {
        "header": {
            "event_type": "im.message.receive_v1",
            "event_id": "unique_event_001",
        },
        "event": {
            "message": {
                "message_type": "text",
                "chat_id": "chat_123",
                "message_id": "msg_001",
                "content": json.dumps({"text": "hello"}),
            },
            "sender": {
                "sender_type": "user",
                "sender_id": {"open_id": "user_1"},
            },
        },
    }

    received = []

    async def mock_handler(msg):
        received.append(msg)

    channel._on_message = mock_handler
    channel._running = True

    # 第一次应处理
    await channel.handle_webhook_event(event)
    assert len(received) == 1

    # 第二次应去重
    result = await channel.handle_webhook_event(event)
    assert result.get("msg") == "duplicate event"
    assert len(received) == 1  # 没有新增


@pytest.mark.asyncio
async def test_feishu_channel_ignores_app_messages():
    """机器人自己发的消息应被忽略。"""
    from yuxi.services.channels.feishu import FeishuChannel

    config = ChannelConfig(
        slug="feishu-app-msg",
        channel_type="feishu",
        credentials={"app_id": "test_id", "app_secret": "test_secret"},
    )
    channel = FeishuChannel(config)

    received = []

    async def mock_handler(msg):
        received.append(msg)

    channel._on_message = mock_handler
    channel._running = True

    event = {
        "header": {
            "event_type": "im.message.receive_v1",
            "event_id": "event_app_001",
        },
        "event": {
            "message": {
                "message_type": "text",
                "chat_id": "chat_123",
                "message_id": "msg_app",
                "content": json.dumps({"text": "bot reply"}),
            },
            "sender": {
                "sender_type": "app",
                "sender_id": {"open_id": "app_id"},
            },
        },
    }

    await channel.handle_webhook_event(event)
    assert len(received) == 0  # 机器人消息应被忽略


def test_registered_channel_types():
    """已注册的类型列表应包含 dummy。"""
    types = get_registered_channel_types()
    assert "dummy" in types


# ── 钉钉 Channel 测试 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_dingtalk_channel_signature_computation():
    """钉钉回调签名计算应正确。"""
    from yuxi.services.channels.dingtalk import DingTalkChannel

    sig = DingTalkChannel._compute_signature("1234567890", "test_secret")
    assert isinstance(sig, str)
    assert len(sig) > 10  # base64 编码


@pytest.mark.asyncio
async def test_dingtalk_channel_webhook_message():
    """钉钉文本消息事件应被正确解析。"""
    from yuxi.services.channels.dingtalk import DingTalkChannel

    config = ChannelConfig(
        slug="dingtalk-test",
        channel_type="dingtalk",
        credentials={"app_key": "key", "app_secret": "secret"},
    )
    channel = DingTalkChannel(config)

    received = []

    async def mock_handler(msg):
        received.append(msg)

    channel._on_message = mock_handler
    channel._running = True

    event = {
        "MsgType": "text",
        "MsgId": "ding_msg_001",
        "Content": "hello dingtalk",
        "From": {"staffId": "user_123"},
        "conversationId": "conv_456",
    }

    await channel.handle_webhook_event(event)
    assert len(received) == 1
    assert received[0].text == "hello dingtalk"
    assert received[0].channel_type == "dingtalk"
    assert received[0].sender_id == "user_123"


@pytest.mark.asyncio
async def test_dingtalk_channel_ignores_non_text():
    """钉钉非文本消息应被忽略。"""
    from yuxi.services.channels.dingtalk import DingTalkChannel

    config = ChannelConfig(slug="dingtalk-ignore", channel_type="dingtalk", credentials={})
    channel = DingTalkChannel(config)

    received = []
    channel._on_message = lambda msg: received.append(msg)
    channel._running = True

    await channel.handle_webhook_event({"MsgType": "image", "MsgId": "img_001"})
    assert len(received) == 0


# ── 企业微信 Channel 测试 ─────────────────────────────────


@pytest.mark.asyncio
async def test_wecom_channel_signature():
    """企业微信回调签名应正确计算。"""
    from yuxi.services.channels.wecom import WeComChannel

    sig = WeComChannel._compute_signature("token123", "1234567890", "nonce_abc", "echostr_xyz")
    assert isinstance(sig, str)
    assert len(sig) == 40  # SHA1 hex digest


@pytest.mark.asyncio
async def test_wecom_channel_text_message():
    """企业微信文本消息应被正确解析。"""
    from yuxi.services.channels.wecom import WeComChannel

    config = ChannelConfig(
        slug="wecom-test",
        channel_type="wecom",
        credentials={"corp_id": "corp", "corp_secret": "secret", "agent_id": "1000002"},
    )
    channel = WeComChannel(config)

    received = []

    async def mock_handler(msg):
        received.append(msg)

    channel._on_message = mock_handler
    channel._running = True

    event = {
        "MsgType": "text",
        "MsgId": "wecom_msg_001",
        "Content": "hello wecom",
        "FromUserName": "user_456",
    }

    await channel.handle_webhook_event(event)
    assert len(received) == 1
    assert received[0].text == "hello wecom"
    assert received[0].channel_type == "wecom"
    assert received[0].sender_id == "user_456"


@pytest.mark.asyncio
async def test_wecom_channel_echostr():
    """企业微信 URL 验证应返回 echostr。"""
    from yuxi.services.channels.wecom import WeComChannel

    config = ChannelConfig(slug="wecom-verify", channel_type="wecom", credentials={})
    channel = WeComChannel(config)

    result = await channel.handle_webhook_event({"echostr": "test_echo_string"})
    assert result == {"echostr": "test_echo_string"}


@pytest.mark.asyncio
async def test_wecom_channel_duplicate_ignored():
    """企业微信重复消息应被去重。"""
    from yuxi.services.channels.wecom import WeComChannel

    config = ChannelConfig(slug="wecom-dedup", channel_type="wecom", credentials={})
    channel = WeComChannel(config)

    received = []
    channel._on_message = lambda msg: received.append(msg)
    channel._running = True

    event = {"MsgType": "text", "MsgId": "dup_001", "Content": "test", "FromUserName": "u1"}
    await channel.handle_webhook_event(event)
    await channel.handle_webhook_event(event)
    assert len(received) == 1
