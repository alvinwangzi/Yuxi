"""Channel 抽象基类与消息数据模型。

Channel 是 Yuxi 与外部 IM 平台之间的桥梁：
- 接收 IM 消息 → 转换为 InboundMessage → 调用 intake_request 进入主链路
- 等待 AgentRun 完成 → 提取回复 → 转换为 OutboundMessage → 发送到 IM
"""
from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from typing import Any


class ChannelSendError(RuntimeError):
    """发送消息到 IM 平台失败。"""


@dataclass(frozen=True)
class InboundMessage:
    """从 IM 平台接收到的消息。"""

    channel_type: str
    channel_chat_id: str
    sender_id: str
    text: str
    message_id: str | None = None
    sender_name: str | None = None
    raw_event: dict[str, Any] = field(default_factory=dict)
    channel_slug: str = ""
    agent_slug: str = ""

    @property
    def stable_message_id(self) -> str:
        return self.message_id or str(uuid.uuid4())


@dataclass(frozen=True)
class OutboundMessage:
    """待发送到 IM 平台的回复。"""

    channel_type: str
    channel_chat_id: str
    text: str
    reply_to_message_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelConfig:
    """Channel 的持久化配置。"""

    slug: str
    channel_type: str
    enabled: bool = True
    credentials: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    agent_slug: str | None = None
    name: str | None = None

    def get_credential(self, key: str, default: str | None = None) -> str | None:
        val = self.credentials.get(key, default)
        return str(val) if val is not None else None


class Channel(abc.ABC):
    """IM 渠道抽象基类。

    子类必须实现 start/stop/send 三个生命周期方法。
    """

    def __init__(self, config: ChannelConfig) -> None:
        self._config = config
        self._running = False

    @property
    def config(self) -> ChannelConfig:
        return self._config

    @property
    def slug(self) -> str:
        return self._config.slug

    @property
    def channel_type(self) -> str:
        return self._config.channel_type

    @property
    def is_running(self) -> bool:
        return self._running

    @abc.abstractmethod
    async def start(self, on_message: Any) -> None:
        """启动 Channel 监听。

        ``on_message`` 是一个异步回调 ``(InboundMessage) -> None``，
        Channel 收到 IM 消息时调用它。
        """

    @abc.abstractmethod
    async def stop(self) -> None:
        """优雅停止 Channel。"""

    @abc.abstractmethod
    async def send(self, message: OutboundMessage) -> None:
        """将回复消息发送到 IM 平台。"""

    async def test_connection(self) -> dict[str, Any]:
        """测试 Channel 连接是否正常，子类可覆盖。"""
        return {"ok": True, "channel_type": self.channel_type}
