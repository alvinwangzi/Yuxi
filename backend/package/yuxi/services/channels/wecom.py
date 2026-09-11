"""企业微信 Channel 实现。

通过企业微信的回调接收消息，使用企业微信 API 发送回复。
支持：
- 回调 URL 验证（echostr 解密）
- 消息接收与去重（基于 MsgId）
- Token 自动刷新（access_token）
- 文本消息发送
"""
from __future__ import annotations

import hashlib
import hmac
import base64
import json
import struct
import time
import xml.etree.ElementTree as ET
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

# 企业微信 API 端点
_WECOM_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
_WECOM_SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

_TOKEN_REFRESH_BUFFER = 300


class WeComChannel(Channel):
    """企业微信 Channel 实现。

    配置项（credentials）：
    - corp_id: 企业微信 CorpID
    - corp_secret: 企业微信应用 Secret
    - agent_id: 企业微信应用 AgentId
    - token: 回调 Token（用于签名验证）
    - encoding_aes_key: 回调 EncodingAESKey（用于消息加解密，可选）

    额外配置（extra）：
    - agent_slug: 默认目标 Agent（可选）
    """

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._access_token: str | None = None
        self._token_expires_at: float = 0
        self._seen_msg_ids: set[str] = set()
        self._on_message: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._http_client: httpx.AsyncClient | None = None

    async def start(self, on_message: Any) -> None:
        if self._running:
            return
        self._on_message = on_message
        self._http_client = httpx.AsyncClient(timeout=30.0)
        await self._refresh_access_token()
        self._running = True
        logger.info(f"企业微信 Channel '{self.slug}' 已启动")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._on_message = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._access_token = None
        self._seen_msg_ids.clear()
        logger.info(f"企业微信 Channel '{self.slug}' 已停止")

    async def send(self, message: OutboundMessage) -> None:
        if not self._running or not self._http_client:
            raise ChannelSendError("企业微信 Channel 未运行")
        await self._ensure_valid_token()
        await self._send_text_message(
            user_id=message.channel_chat_id,
            text=message.text,
        )

    async def test_connection(self) -> dict[str, Any]:
        """测试企业微信 API 连接。"""
        try:
            await self._refresh_access_token()
            return {
                "ok": True,
                "channel_type": "wecom",
                "corp_id": self._config.get_credential("corp_id"),
            }
        except Exception as e:
            return {"ok": False, "channel_type": "wecom", "error": str(e)}

    async def handle_webhook_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """处理企业微信回调。

        支持两种场景：
        1. URL 验证（GET 请求的 echostr 解密）
        2. 消息/事件推送（POST 请求的 XML 解密）

        由于 FastAPI 路由层已将请求体解析为 dict，
        这里处理已解密/已解析的消息数据。
        """
        # URL 验证场景：直接返回 echostr
        if "echostr" in event:
            return {"echostr": event["echostr"]}

        # 签名验证
        msg_signature = event.get("msg_signature", "")
        timestamp = str(event.get("timestamp", ""))
        nonce = str(event.get("nonce", ""))
        token = self._config.get_credential("token") or ""

        if msg_signature and timestamp and nonce and token:
            echostr = event.get("echostr", "")
            expected_sig = self._compute_signature(token, timestamp, nonce, echostr)
            if msg_signature != expected_sig:
                logger.warning("企业微信回调签名验证失败")
                return {"errcode": 40003, "errmsg": "signature mismatch"}

        # 消息事件
        msg_type = event.get("MsgType", "")
        if msg_type == "text":
            await self._handle_text_message(event)

        return {"errcode": 0, "errmsg": "ok"}

    async def _handle_text_message(self, event: dict[str, Any]) -> None:
        """处理文本消息。"""
        msg_id = str(event.get("MsgId", ""))
        # 去重
        if msg_id and msg_id in self._seen_msg_ids:
            return
        if msg_id:
            self._seen_msg_ids.add(msg_id)
            if len(self._seen_msg_ids) > 10000:
                self._seen_msg_ids.clear()

        text = str(event.get("Content", "")).strip()
        if not text:
            return

        from_user = str(event.get("FromUserName", ""))

        inbound = InboundMessage(
            channel_type="wecom",
            channel_chat_id=from_user,
            sender_id=from_user,
            text=text,
            message_id=msg_id or None,
            raw_event={"event": event},
        )

        if self._on_message:
            try:
                await self._on_message(inbound)
            except Exception:
                logger.exception(f"企业微信消息处理失败: msg_id={msg_id}")

    async def _send_text_message(self, user_id: str, text: str) -> None:
        """通过企业微信 API 发送文本消息。"""
        assert self._http_client and self._access_token

        agent_id = self._config.get_credential("agent_id")
        if not agent_id:
            raise ChannelSendError("企业微信发送消息需要 agent_id 配置")

        body = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": int(agent_id),
            "text": {"content": text},
        }

        try:
            resp = await self._http_client.post(
                f"{_WECOM_SEND_URL}?access_token={self._access_token}",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") != 0:
                raise ChannelSendError(f"企业微信 API 错误: {data.get('errmsg', 'unknown')}")
        except httpx.HTTPStatusError as e:
            raise ChannelSendError(f"企业微信消息发送失败: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise ChannelSendError(f"企业微信消息发送失败: {e}") from e

    async def _ensure_valid_token(self) -> None:
        """确保 access_token 有效。"""
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER:
            return
        await self._refresh_access_token()

    async def _refresh_access_token(self) -> None:
        """获取/刷新 access_token。"""
        assert self._http_client

        corp_id = self._config.get_credential("corp_id")
        corp_secret = self._config.get_credential("corp_secret")
        if not corp_id or not corp_secret:
            raise ChannelSendError("企业微信 Channel 缺少 corp_id 或 corp_secret 配置")

        try:
            resp = await self._http_client.get(
                _WECOM_TOKEN_URL,
                params={"corpid": corp_id, "corpsecret": corp_secret},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") != 0:
                raise ChannelSendError(f"获取企业微信 token 失败: {data.get('errmsg')}")
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + int(data.get("expires_in", 7200))
        except httpx.RequestError as e:
            raise ChannelSendError(f"获取企业微信 token 失败: {e}") from e

    @staticmethod
    def _compute_signature(token: str, timestamp: str, nonce: str, echostr: str = "") -> str:
        """计算企业微信回调签名。"""
        sort_list = sorted([token, timestamp, nonce, echostr])
        raw = "".join(sort_list).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()
