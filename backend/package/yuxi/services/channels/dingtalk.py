"""钉钉 Channel 实现。

通过钉钉开放平台的事件订阅接收消息，使用钉钉 API 发送回复。
支持：
- 回调 URL 验证（签名校验）
- 消息接收与去重（基于 msgId）
- Token 自动刷新（access_token）
- 文本消息发送
"""
from __future__ import annotations

import hashlib
import hmac
import base64
import json
import time
import urllib.parse
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

# 钉钉 API 端点
_DINGTALK_TOKEN_URL = "https://oapi.dingtalk.com/gettoken"
_DINGTALK_SEND_URL = "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2"
_DINGTALK_ROBOT_SEND_URL = "https://oapi.dingtalk.com/robot/send"

# Token 提前刷新时间（秒）
_TOKEN_REFRESH_BUFFER = 300


class DingTalkChannel(Channel):
    """钉钉 Channel 实现。

    配置项（credentials）：
    - app_key: 钉钉应用 AppKey
    - app_secret: 钉钉应用 AppSecret
    - robot_webhook: 群机器人 Webhook URL（可选，用于群消息）
    - robot_secret: 群机器人签名密钥（可选）
    - agent_id: 钉钉应用 AgentId（用于工作通知消息）

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
        logger.info(f"钉钉 Channel '{self.slug}' 已启动")

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
        """测试钉钉 API 连接。"""
        try:
            await self._refresh_access_token()
            return {
                "ok": True,
                "channel_type": "dingtalk",
                "app_key": self._config.get_credential("app_key"),
            }
        except Exception as e:
            return {"ok": False, "channel_type": "dingtalk", "error": str(e)}

    async def handle_webhook_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """处理钉钉事件订阅回调。

        钉钉回调包含：
        1. URL 验证（首次注册回调时）
        2. 消息事件推送
        """
        # 钉钉回调签名验证
        signature = event.get("signature", "")
        timestamp = event.get("timestamp", "")
        app_secret = self._config.get_credential("app_secret") or ""
        if signature and timestamp:
            expected = self._compute_signature(timestamp, app_secret)
            if signature != expected:
                logger.warning("钉钉回调签名验证失败")
                return {"errcode": 400, "errmsg": "signature mismatch"}

        # 事件类型分发
        event_type = event.get("EventType", "")
        if event_type == "chat_add_member" or event_type.startswith("check_"):
            # URL 验证事件
            return {"msg_signature": signature, "timeStamp": timestamp, "echoStr": event.get("echoStr", "")}

        # 消息事件
        if event_type == "message" or "MsgType" in event:
            await self._handle_message_event(event)

        return {"errcode": 0, "errmsg": "ok"}

    async def _handle_message_event(self, event: dict[str, Any]) -> None:
        """处理钉钉消息事件。"""
        msg_type = event.get("MsgType", "")
        if msg_type != "text":
            logger.debug(f"钉钉忽略非文本消息: type={msg_type}")
            return

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

        sender_id = str(event.get("From", {}).get("staffId", "") or event.get("senderStaffId", ""))
        conversation_id = str(event.get("conversationId", "") or event.get("chatId", ""))

        inbound = InboundMessage(
            channel_type="dingtalk",
            channel_chat_id=conversation_id or sender_id,
            sender_id=sender_id,
            text=text,
            message_id=msg_id or None,
            raw_event={"event": event},
        )

        if self._on_message:
            try:
                await self._on_message(inbound)
            except Exception:
                logger.exception(f"钉钉消息处理失败: msg_id={msg_id}")

    async def _send_work_notification(self, user_id: str, text: str) -> None:
        """通过工作通知发送文本消息。"""
        assert self._http_client and self._access_token
        agent_id = self._config.get_credential("agent_id")
        if not agent_id:
            raise ChannelSendError("钉钉工作通知需要 agent_id 配置")

        body = {
            "agent_id": agent_id,
            "userid_list": user_id,
            "msg": {
                "msgtype": "text",
                "text": {"content": text},
            },
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
        """通过群机器人 Webhook 发送文本消息。"""
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

        body = {
            "msgtype": "text",
            "text": {"content": text},
        }

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

    async def _ensure_valid_token(self) -> None:
        """确保 access_token 有效。"""
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER:
            return
        await self._refresh_access_token()

    async def _refresh_access_token(self) -> None:
        """获取/刷新 access_token。"""
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

    @staticmethod
    def _compute_signature(timestamp: str, app_secret: str) -> str:
        """计算钉钉回调签名。"""
        string_to_sign = f"{timestamp}\n{app_secret}"
        hmac_code = hmac.new(
            app_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")
