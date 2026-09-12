"""IM 渠道集成模块。"""

from yuxi.services.channels.base import (
    Channel,
    ChannelConfig,
    ChannelSendError,
    InboundMessage,
    OutboundMessage,
)
from yuxi.services.channels.manager import ChannelManager

__all__ = [
    "Channel",
    "ChannelConfig",
    "ChannelManager",
    "ChannelSendError",
    "InboundMessage",
    "OutboundMessage",
]
