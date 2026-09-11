"""Channel 生命周期管理器。

负责加载配置、实例化 Channel、启动/停止监听，以及处理消息的中枢调度。
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.services.channels.base import (
    Channel,
    ChannelConfig,
    ChannelSendError,
    InboundMessage,
    OutboundMessage,
)
from yuxi.utils.logging_config import logger

MessageHandler = Callable[[InboundMessage], Awaitable[None]]

# 已注册的 Channel 类型 → 构造器
_CHANNEL_REGISTRY: dict[str, type[Channel]] = {}


def register_channel_type(channel_type: str, cls: type[Channel]) -> None:
    """注册一个 Channel 实现类。"""
    if channel_type in _CHANNEL_REGISTRY:
        raise ValueError(f"Channel 类型 '{channel_type}' 已注册")
    _CHANNEL_REGISTRY[channel_type] = cls


def get_registered_channel_types() -> list[str]:
    return sorted(_CHANNEL_REGISTRY.keys())


class ChannelManager:
    """管理所有 Channel 实例的生命周期。"""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}
        self._message_handler: MessageHandler | None = None
        self._lock = asyncio.Lock()

    @property
    def channels(self) -> dict[str, Channel]:
        return dict(self._channels)

    def get_channel(self, slug: str) -> Channel | None:
        return self._channels.get(slug)

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._message_handler = handler

    async def create_channel(self, config: ChannelConfig) -> Channel:
        """根据配置创建并注册一个 Channel 实例（不自动启动）。"""
        cls = _CHANNEL_REGISTRY.get(config.channel_type)
        if cls is None:
            raise ValueError(
                f"未知的 Channel 类型 '{config.channel_type}'，"
                f"已注册: {get_registered_channel_types()}"
            )
        channel = cls(config)
        async with self._lock:
            self._channels[config.slug] = channel
        return channel

    async def start_channel(self, slug: str) -> Channel:
        """启动指定 Channel。"""
        channel = self._channels.get(slug)
        if channel is None:
            raise ValueError(f"Channel '{slug}' 不存在")
        if channel.is_running:
            return channel
        if self._message_handler is None:
            raise RuntimeError("未设置消息处理器，请先调用 set_message_handler")
        await channel.start(self._message_handler)
        logger.info(f"Channel '{slug}' ({channel.channel_type}) 已启动")
        return channel

    async def stop_channel(self, slug: str) -> None:
        """停止指定 Channel。"""
        channel = self._channels.get(slug)
        if channel is None:
            return
        if not channel.is_running:
            return
        await channel.stop()
        logger.info(f"Channel '{slug}' ({channel.channel_type}) 已停止")

    async def remove_channel(self, slug: str) -> None:
        """停止并移除 Channel。"""
        await self.stop_channel(slug)
        async with self._lock:
            self._channels.pop(slug, None)

    async def start_all(self) -> None:
        """启动所有已注册的启用的 Channel。"""
        for slug, channel in self._channels.items():
            if channel.config.enabled and not channel.is_running:
                try:
                    await self.start_channel(slug)
                except Exception:
                    logger.exception(f"启动 Channel '{slug}' 失败")

    async def stop_all(self) -> None:
        """停止所有运行中的 Channel。"""
        for slug in list(self._channels.keys()):
            try:
                await self.stop_channel(slug)
            except Exception:
                logger.exception(f"停止 Channel '{slug}' 失败")

    async def send_message(self, slug: str, message: OutboundMessage) -> None:
        """通过指定 Channel 发送消息。"""
        channel = self._channels.get(slug)
        if channel is None:
            raise ChannelSendError(f"Channel '{slug}' 不存在")
        if not channel.is_running:
            raise ChannelSendError(f"Channel '{slug}' 未运行")
        await channel.send(message)
