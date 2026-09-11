"""飞书 Channel 实现。

通过飞书开放平台的事件订阅接收消息，使用飞书 API 发送回复。
支持：
- 事件订阅验证（challenge）
- 消息接收与去重（基于 event_id）
- Token 自动刷新（tenant_access_token）
- 文本消息发送
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Callable, Awaitable

import httpx

from yuxi.services.channels.base import (
    Channel,
    ChannelConfig,
    ChannelSendError,
    InboundMessage,
    OutboundMessage,
)
from yuxi.utils.logging_config import logger

# 飞书 API 端点
_FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_FEISHU_SEND_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
_FEISHU_REPLY_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"

# Token 提前刷新时间（秒）
_TOKEN_REFRESH_BUFFER = 300


class FeishuChannel(Channel):
    """飞书 Channel 实现。

    配置项（credentials）：
    - app_id: 飞书应用 App ID
    - app_secret: 飞书应用 App Secret
    - verification_token: 事件订阅的 Verification Token（可选，用于验证请求来源）
    - encrypt_key: 事件订阅的 Encrypt Key（可选，用于解密）

    额外配置（extra）：
    - agent_slug: 默认目标 Agent（可选）
    """

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._tenant_access_token: str | None = None
        self._token_expires_at: float = 0
        self._seen_event_ids: set[str] = set()
        self._on_message: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._http_client: httpx.AsyncClient | None = None

    async def start(self, on_message: Any) -> None:
        if self._running:
            return
        self._on_message = on_message
        self._http_client = httpx.AsyncClient(timeout=30.0)
        await self._refresh_tenant_token()
        self._running = True
        logger.info(f"飞书 Channel '{self.slug}' 已启动")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._on_message = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._tenant_access_token = None
        self._seen_event_ids.clear()
        logger.info(f"飞书 Channel '{self.slug}' 已停止")

    async def send(self, message: OutboundMessage) -> None:
        if not self._running or not self._http_client:
            raise ChannelSendError("飞书 Channel 未运行")
        await self._ensure_valid_token()
        await self._send_text_message(
            chat_id=message.channel_chat_id,
            text=message.text,
            reply_to_message_id=message.reply_to_message_id,
        )

    async def test_connection(self) -> dict[str, Any]:
        """测试飞书 API 连接。"""
        try:
            await self._refresh_tenant_token()
            return {"ok": True, "channel_type": "feishu", "app_id": self._config.get_credential("app_id")}
        except Exception as e:
            return {"ok": False, "channel_type": "feishu", "error": str(e)}

    async def handle_webhook_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """处理飞书事件订阅回调。

        支持两种事件格式：
        1. URL 验证（challenge）
        2. 消息事件（im.message.receive_v1）
        """
        # URL 验证 challenge
        if "challenge" in event:
            return {"challenge": event["challenge"]}

        # v2.0 事件格式
        header = event.get("header", {})
        event_type = header.get("event_type", "")
        event_id = header.get("event_id", "")

        # 去重
        if event_id and event_id in self._seen_event_ids:
            return {"code": 0, "msg": "duplicate event"}
        if event_id:
            self._seen_event_ids.add(event_id)
            # 限制去重集合大小
            if len(self._seen_event_ids) > 10000:
                self._seen_event_ids.clear()

        if event_type == "im.message.receive_v1":
            await self._handle_message_event(event.get("event", {}))

        return {"code": 0, "msg": "ok"}

    async def _handle_message_event(self, event: dict[str, Any]) -> None:
        """处理 im.message.receive_v1 事件。"""
        message = event.get("message", {})
        sender = event.get("sender", {})

        # 只处理文本消息
        message_type = message.get("message_type", "")
        if message_type != "text":
            logger.debug(f"飞书忽略非文本消息: type={message_type}")
            return

        # 忽略机器人自己发的消息
        sender_type = sender.get("sender_type", "")
        if sender_type == "app":
            return

        try:
            content = json.loads(message.get("content", "{}"))
            text = content.get("text", "").strip()
        except (json.JSONDecodeError, AttributeError):
            text = ""

        if not text:
            return

        chat_id = message.get("chat_id", "")
        message_id = message.get("message_id", "")
        sender_id = sender.get("sender_id", {}).get("open_id", "")

        inbound = InboundMessage(
            channel_type="feishu",
            channel_chat_id=chat_id,
            sender_id=sender_id,
            text=text,
            message_id=message_id,
            raw_event={"event": event},
        )

        if self._on_message:
            try:
                await self._on_message(inbound)
            except Exception:
                logger.exception(f"飞书消息处理失败: message_id={message_id}")

    async def _send_text_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> None:
        """通过飞书 API 发送文本消息。"""
        assert self._http_client and self._tenant_access_token

        body = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }

        if reply_to_message_id:
            url = _FEISHU_REPLY_MESSAGE_URL.format(message_id=reply_to_message_id)
        else:
            url = f"{_FEISHU_SEND_MESSAGE_URL}?receive_id_type=chat_id"

        headers = {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            resp = await self._http_client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise ChannelSendError(f"飞书 API 返回错误: {data.get('msg', 'unknown')}")
        except httpx.HTTPStatusError as e:
            raise ChannelSendError(f"飞书消息发送失败: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise ChannelSendError(f"飞书消息发送失败: {e}") from e

    async def _ensure_valid_token(self) -> None:
        """确保 tenant_access_token 有效。"""
        if self._tenant_access_token and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER:
            return
        await self._refresh_tenant_token()

    async def _refresh_tenant_token(self) -> None:
        """获取/刷新 tenant_access_token。"""
        assert self._http_client

        app_id = self._config.get_credential("app_id")
        app_secret = self._config.get_credential("app_secret")
        if not app_id or not app_secret:
            raise ChannelSendError("飞书 Channel 缺少 app_id 或 app_secret 配置")

        try:
            resp = await self._http_client.post(
                _FEISHU_TOKEN_URL,
                json={"app_id": app_id, "app_secret": app_secret},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise ChannelSendError(f"获取飞书 token 失败: {data.get('msg')}")
            self._tenant_access_token = data["tenant_access_token"]
            expire = int(data.get("expire", 7200))
            self._token_expires_at = time.time() + expire
        except httpx.RequestError as e:
            raise ChannelSendError(f"获取飞书 token 失败: {e}") from e
