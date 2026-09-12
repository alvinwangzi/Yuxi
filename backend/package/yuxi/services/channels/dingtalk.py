"""钉钉 Channel 实现（Stream 长连接模式）。

通过 dingtalk-stream SDK 的 WebSocket 长连接接收消息推送，
使用钉钉 REST API 发送回复。
优势：
- 无需公网回调地址
- SDK 自动管理连接、心跳和重连
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.parse
import base64
import hashlib
import hmac
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

# 钉钉 REST API 端点
_DINGTALK_TOKEN_URL = "https://oapi.dingtalk.com/gettoken"
_DINGTALK_SEND_URL = "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2"

_TOKEN_REFRESH_BUFFER = 300


class DingTalkChannel(Channel):
    """钉钉 Channel —— Stream 长连接模式。

    配置项（credentials）：
    - app_key: 钉钉应用 ClientID（AppKey）
    - app_secret: 钉钉应用 ClientSecret（AppSecret）
    - agent_id: 钉钉应用 AgentId（用于工作通知消息，可选）
    - robot_webhook: 群机器人 Webhook URL（可选，用于群消息）
    - robot_secret: 群机器人签名密钥（可选）
    """

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._token_expires_at: float = 0
        self._on_message: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._stream_client: Any = None
        self._stream_thread: threading.Thread | None = None

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self, on_message: Any) -> None:
        if self._running:
            return
        self._on_message = on_message
        self._http_client = httpx.AsyncClient(timeout=30.0)
        await self._refresh_access_token()

        app_key = self._config.get_credential("app_key")
        app_secret = self._config.get_credential("app_secret")
        if not app_key or not app_secret:
            raise ChannelSendError("钉钉 Channel 缺少 app_key 或 app_secret 配置")

        import dingtalk_stream
        from dingtalk_stream import AckMessage

        credential = dingtalk_stream.Credential(app_key, app_secret)
        self._stream_client = dingtalk_stream.DingTalkStreamClient(credential)
        self._stream_client.register_callback_handler(
            dingtalk_stream.ChatbotMessage.TOPIC,
            self._on_stream_message,
        )

        # start() 阻塞，放入后台线程
        self._stream_thread = threading.Thread(
            target=self._stream_client.start,
            name=f"dingtalk-stream-{self.slug}",
            daemon=True,
        )
        self._stream_thread.start()
        self._running = True
        logger.info(f"钉钉 Channel '{self.slug}' 已启动（Stream 长连接）")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._on_message = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._access_token = None
        self._stream_client = None
        self._stream_thread = None
        logger.info(f"钉钉 Channel '{self.slug}' 已停止")

    async def send(self, message: OutboundMessage) -> None:
        if not self._running or not self._http_client:
            raise ChannelSendError("钉钉 Channel 未运行")

        robot_webhook = self._config.get_credential("robot_webhook")
        if robot_webhook:
            await self._send_robot_message(robot_webhook, message.text)
        else:
            await self._ensure_valid_token()
            await self._send_work_notification(
                user_id=message.channel_chat_id,
                text=message.text,
            )

    async def test_connection(self) -> dict[str, Any]:
        try:
            await self._refresh_access_token()
            return {
                "ok": True,
                "channel_type": "dingtalk",
                "app_key": self._config.get_credential("app_key"),
            }
        except Exception as e:
            return {"ok": False, "channel_type": "dingtalk", "error": str(e)}

    # ── Stream 回调 ───────────────────────────────────────

    def _on_stream_message(self, message: Any) -> Any:
        """dingtalk-stream 推送的机器人消息回调（在 Stream 线程中执行）。"""
        try:
            import dingtalk_stream

            text = (message.text.content if hasattr(message, "text") and message.text else "").strip()
            if not text:
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"

            sender_id = message.sender_staff_id or message.sender_id or ""
            conversation_id = message.conversation_id or ""
            msg_id = message.msg_id or ""

            inbound = InboundMessage(
                channel_type="dingtalk",
                channel_chat_id=conversation_id or sender_id,
                sender_id=str(sender_id),
                text=text,
                message_id=str(msg_id) if msg_id else None,
                raw_event={"message_id": msg_id, "sender_id": sender_id},
                channel_slug=self.slug,
                agent_slug=self._config.agent_slug or "",
            )

            if self._on_message:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(self._on_message(inbound), loop)

            return dingtalk_stream.AckMessage.STATUS_OK, "OK"

        except Exception:
            logger.exception("钉钉 Stream 消息处理异常")
            import dingtalk_stream
            return dingtalk_stream.AckMessage.STATUS_SYSTEM_EXCEPTION, "error"

    # ── REST 发送 ─────────────────────────────────────────

    async def _send_work_notification(self, user_id: str, text: str) -> None:
        assert self._http_client and self._access_token
        agent_id = self._config.get_credential("agent_id")
        if not agent_id:
            raise ChannelSendError("钉钉工作通知需要 agent_id 配置")

        body = {
            "agent_id": agent_id,
            "userid_list": user_id,
            "msg": {"msgtype": "text", "text": {"content": text}},
        }

        try:
            resp = await self._http_client.post(
                f"{_DINGTALK_SEND_URL}?access_token={self._access_token}",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") != 0:
                raise ChannelSendError(f"钉钉 API 错误: {data.get('errmsg', 'unknown')}")
        except httpx.HTTPStatusError as e:
            raise ChannelSendError(f"钉钉消息发送失败: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise ChannelSendError(f"钉钉消息发送失败: {e}") from e

    async def _send_robot_message(self, webhook: str, text: str) -> None:
        assert self._http_client

        url = webhook
        robot_secret = self._config.get_credential("robot_secret")
        if robot_secret:
            timestamp = str(round(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{robot_secret}"
            hmac_code = hmac.new(
                robot_secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}timestamp={timestamp}&sign={sign}"

        body = {"msgtype": "text", "text": {"content": text}}

        try:
            resp = await self._http_client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") != 0:
                raise ChannelSendError(f"钉钉机器人错误: {data.get('errmsg', 'unknown')}")
        except httpx.HTTPStatusError as e:
            raise ChannelSendError(f"钉钉机器人发送失败: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise ChannelSendError(f"钉钉机器人发送失败: {e}") from e

    # ── Token 管理 ────────────────────────────────────────

    async def _ensure_valid_token(self) -> None:
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER:
            return
        await self._refresh_access_token()

    async def _refresh_access_token(self) -> None:
        assert self._http_client

        app_key = self._config.get_credential("app_key")
        app_secret = self._config.get_credential("app_secret")
        if not app_key or not app_secret:
            raise ChannelSendError("钉钉 Channel 缺少 app_key 或 app_secret 配置")

        try:
            resp = await self._http_client.get(
                _DINGTALK_TOKEN_URL,
                params={"appkey": app_key, "appsecret": app_secret},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") != 0:
                raise ChannelSendError(f"获取钉钉 token 失败: {data.get('errmsg')}")
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + int(data.get("expires_in", 7200))
        except httpx.RequestError as e:
            raise ChannelSendError(f"获取钉钉 token 失败: {e}") from e
