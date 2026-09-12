"""企业微信 Channel 实现（WebSocket 长连接模式）。

通过企业微信智能机器人长连接协议接收消息，使用 REST API 发送回复。
协议参考：https://developer.work.weixin.qq.com/document/path/101463
优势：
- 无需公网回调地址
- 内置身份校验与加密
- 支持流式消息回复
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Callable, Awaitable

import httpx
import websockets

from yuxi.services.channels.base import (
    Channel,
    ChannelConfig,
    ChannelSendError,
    InboundMessage,
    OutboundMessage,
)
from yuxi.utils.logging_config import logger

# 企业微信 WebSocket 端点
_WECOM_WS_URL = "wss://openws.work.weixin.qq.com"

# 企业微信 REST API（备用主动发送）
_WECOM_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
_WECOM_SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

_TOKEN_REFRESH_BUFFER = 300
_HEARTBEAT_INTERVAL = 30  # 秒


class WeComChannel(Channel):
    """企业微信 Channel —— WebSocket 长连接模式。

    配置项（credentials）：
    - bot_id: 智能机器人 BotID
    - bot_secret: 智能机器人 Secret
    - corp_id: 企业 CorpID（可选，用于 REST API 主动发送）
    - corp_secret: 应用 Secret（可选，用于 REST API 主动发送）
    - agent_id: 应用 AgentId（可选，用于 REST API 主动发送）
    """

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._on_message: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._ws: Any = None  # websockets connection
        self._ws_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._access_token: str | None = None
        self._token_expires_at: float = 0

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self, on_message: Any) -> None:
        if self._running:
            return
        self._on_message = on_message
        self._http_client = httpx.AsyncClient(timeout=30.0)

        bot_id = self._config.get_credential("bot_id")
        bot_secret = self._config.get_credential("bot_secret")
        if not bot_id or not bot_secret:
            raise ChannelSendError("企业微信 Channel 缺少 bot_id 或 bot_secret 配置")

        # 可选：初始化 REST API token
        corp_id = self._config.get_credential("corp_id")
        corp_secret = self._config.get_credential("corp_secret")
        if corp_id and corp_secret:
            await self._refresh_access_token()

        # 启动 WebSocket 连接循环
        self._ws_task = asyncio.create_task(
            self._ws_connection_loop(bot_id, bot_secret),
            name=f"wecom-ws-{self.slug}",
        )
        self._running = True
        logger.info(f"企业微信 Channel '{self.slug}' 已启动（WebSocket 长连接）")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._on_message = None

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._access_token = None
        logger.info(f"企业微信 Channel '{self.slug}' 已停止")

    async def send(self, message: OutboundMessage) -> None:
        if not self._running:
            raise ChannelSendError("企业微信 Channel 未运行")

        # 优先通过 WebSocket 回复（aibot_respond_msg）
        if self._ws and message.reply_to_message_id:
            await self._ws_respond(message)
        else:
            # 回退到 REST API 主动发送
            await self._ensure_valid_token()
            await self._send_text_message(
                user_id=message.channel_chat_id,
                text=message.text,
            )

    async def test_connection(self) -> dict[str, Any]:
        bot_id = self._config.get_credential("bot_id")
        bot_secret = self._config.get_credential("bot_secret")
        if not bot_id or not bot_secret:
            return {"ok": False, "channel_type": "wecom", "error": "缺少 bot_id 或 bot_secret"}
        try:
            # 尝试建立连接验证
            ws = await websockets.connect(_WECOM_WS_URL)
            await ws.close()
            return {"ok": True, "channel_type": "wecom", "bot_id": bot_id}
        except Exception as e:
            return {"ok": False, "channel_type": "wecom", "error": str(e)}

    # ── WebSocket 连接循环 ────────────────────────────────

    async def _ws_connection_loop(self, bot_id: str, bot_secret: str) -> None:
        """维持 WebSocket 长连接，自动重连。"""
        while self._running:
            try:
                async with websockets.connect(_WECOM_WS_URL) as ws:
                    self._ws = ws
                    logger.info(f"企业微信 '{self.slug}' WebSocket 已连接")

                    # 发送订阅请求
                    subscribe_msg = {
                        "cmd": "aibot_subscribe",
                        "headers": {"req_id": str(uuid.uuid4())},
                        "body": {"bot_id": bot_id, "secret": bot_secret},
                    }
                    await ws.send(json.dumps(subscribe_msg))

                    # 启动心跳
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

                    # 消息接收循环
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(raw)
                            await self._handle_ws_message(data, ws)
                        except json.JSONDecodeError:
                            logger.warning(f"企业微信 '{self.slug}' 收到非 JSON 消息: {raw[:200]}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"企业微信 '{self.slug}' WebSocket 断开: {e}，3 秒后重连")
                self._ws = None
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                    self._heartbeat_task = None
                if self._running:
                    await asyncio.sleep(3)

    async def _heartbeat_loop(self, ws: Any) -> None:
        """定期发送 ping 保持连接。"""
        try:
            while self._running:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                if ws.open:
                    await ws.ping()
        except asyncio.CancelledError:
            pass

    async def _handle_ws_message(self, data: dict[str, Any], ws: Any) -> None:
        """处理 WebSocket 推送的消息。"""
        cmd = data.get("cmd", "")

        if cmd == "aibot_msg_callback":
            await self._handle_inbound_message(data)
        elif cmd == "aibot_subscribe_response":
            # 订阅结果
            body = data.get("body", {})
            if body.get("errcode") != 0:
                logger.error(f"企业微信订阅失败: {body}")
        # 其他 cmd（如心跳响应）忽略

    async def _handle_inbound_message(self, data: dict[str, Any]) -> None:
        """处理 aibot_msg_callback 推送的消息。"""
        body = data.get("body", {})
        msg_type = body.get("msg_type", "")
        if msg_type != "text":
            logger.debug(f"企业微信忽略非文本消息: type={msg_type}")
            return

        text = body.get("text", {}).get("content", "").strip()
        if not text:
            return

        from_user = body.get("from", {}).get("user_id", "")
        msg_id = body.get("msg_id", "")
        chat_id = body.get("chat_id", "") or from_user

        inbound = InboundMessage(
            channel_type="wecom",
            channel_chat_id=chat_id,
            sender_id=from_user,
            text=text,
            message_id=msg_id or None,
            raw_event=data,
            channel_slug=self.slug,
            agent_slug=self._config.agent_slug or "",
        )

        if self._on_message:
            try:
                await self._on_message(inbound)
            except Exception:
                logger.exception(f"企业微信消息处理失败: msg_id={msg_id}")

    async def _ws_respond(self, message: OutboundMessage) -> None:
        """通过 WebSocket 回复消息（aibot_respond_msg）。"""
        if not self._ws:
            raise ChannelSendError("WebSocket 未连接")

        respond_msg = {
            "cmd": "aibot_respond_msg",
            "headers": {"req_id": str(uuid.uuid4())},
            "body": {
                "msg_id": message.reply_to_message_id,
                "text": {"content": message.text},
                "finish": True,
            },
        }
        try:
            await self._ws.send(json.dumps(respond_msg))
        except Exception as e:
            raise ChannelSendError(f"企业微信 WebSocket 回复失败: {e}") from e

    # ── REST 发送（回退路径）──────────────────────────────

    async def _send_text_message(self, user_id: str, text: str) -> None:
        assert self._http_client and self._access_token

        agent_id = self._config.get_credential("agent_id")
        if not agent_id:
            raise ChannelSendError("企业微信 REST 发送需要 agent_id 配置")

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

    # ── Token 管理 ────────────────────────────────────────

    async def _ensure_valid_token(self) -> None:
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER:
            return
        await self._refresh_access_token()

    async def _refresh_access_token(self) -> None:
        assert self._http_client

        corp_id = self._config.get_credential("corp_id")
        corp_secret = self._config.get_credential("corp_secret")
        if not corp_id or not corp_secret:
            raise ChannelSendError("企业微信 REST 发送需要 corp_id 和 corp_secret")

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
