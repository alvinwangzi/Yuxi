"""飞书 Channel 实现（WebSocket 长连接模式）。

通过飞书 SDK 的 WebSocket 长连接接收消息事件，使用飞书 REST API 发送回复。
优势：
- 无需公网 IP / 域名 / 内网穿透
- 内置加密传输，无需额外加解密逻辑
- SDK 自动管理心跳与重连
"""
from __future__ import annotations

import asyncio
import json
import threading
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

# 飞书 API 端点（发送消息仍需 REST）
_FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_FEISHU_SEND_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
_FEISHU_REPLY_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"

_TOKEN_REFRESH_BUFFER = 300


class FeishuChannel(Channel):
    """飞书 Channel —— WebSocket 长连接模式。

    配置项（credentials）：
    - app_id: 飞书应用 App ID
    - app_secret: 飞书应用 App Secret

    长连接模式不再需要 verification_token / encrypt_key。
    """

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._tenant_access_token: str | None = None
        self._token_expires_at: float = 0
        self._on_message: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._ws_client: Any = None  # lark.ws.Client
        self._ws_thread: threading.Thread | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None  # 主事件循环引用
        self._ws_loop: asyncio.AbstractEventLoop | None = None  # WS 线程事件循环引用

    # ── 生命周期 ──────────────────────────────────────────

    async def start(self, on_message: Any) -> None:
        if self._running:
            return
        self._on_message = on_message
        self._http_client = httpx.AsyncClient(timeout=30.0)
        await self._refresh_tenant_token()
        # 捕获当前（主）事件循环，供 WS 线程回调调度使用
        self._main_loop = asyncio.get_running_loop()

        app_id = self._config.get_credential("app_id")
        app_secret = self._config.get_credential("app_secret")
        if not app_id or not app_secret:
            raise ChannelSendError("飞书 Channel 缺少 app_id 或 app_secret 配置")

        # 构建事件处理器
        import lark_oapi as lark

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_ws_message)
            .build()
        )

        self._ws_client = lark.ws.Client(
            app_id,
            app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        # SDK 的 start() 是阻塞调用，放入后台线程。
        # SDK 在模块级捕获了 asyncio event loop（lark_oapi.ws.client.loop），
        # 在主进程中该 loop 是 uvloop 且已在运行。daemon 线程必须创建独立 loop
        # 并猴子补丁 SDK 的模块级变量，否则 run_until_complete 会报
        # "this event loop is already running"。
        ws_loop_ready = threading.Event()

        def _run_ws_in_thread() -> None:
            import lark_oapi.ws.client as ws_module
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            ws_module.loop = new_loop
            self._ws_loop = new_loop
            ws_loop_ready.set()  # 通知主线程 loop 已就绪
            try:
                self._ws_client.start()
            except Exception:
                logger.exception(f"飞书 Channel '{self.slug}' WebSocket 线程异常")
            finally:
                try:
                    new_loop.close()
                except Exception:
                    pass
                self._ws_loop = None

        self._ws_thread = threading.Thread(
            target=_run_ws_in_thread,
            name=f"feishu-ws-{self.slug}",
            daemon=True,
        )
        self._ws_thread.start()
        # 等待 WS 线程的 event loop 就绪
        ws_loop_ready.wait(timeout=5.0)
        self._running = True
        logger.info(f"飞书 Channel '{self.slug}' 已启动（WebSocket 长连接）")

    async def stop(self) -> None:
        """停止 Channel 并释放所有资源。

        通过向 WS 线程的 event loop 调度 _disconnect() 来关闭 WebSocket 连接，
        然后等待线程退出。
        """
        self._running = False
        self._on_message = None
        self._main_loop = None

        # 1. 通过 WS 线程的 loop 调度 _disconnect() 关闭 WebSocket 连接
        ws_loop = self._ws_loop
        if ws_loop and not ws_loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._ws_client._disconnect(), ws_loop
                )
                future.result(timeout=3.0)
            except Exception:
                logger.debug(f"调度飞书 Channel '{self.slug}' _disconnect 超时或失败")

        # 2. 等待 WS 线程退出
        ws_thread = self._ws_thread
        if ws_thread and ws_thread.is_alive():
            ws_thread.join(timeout=5.0)
            if ws_thread.is_alive():
                logger.warning(f"飞书 Channel '{self.slug}' WS 线程未能在 5s 内退出")

        # 3. 清理资源
        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None
        self._tenant_access_token = None
        self._ws_client = None
        self._ws_thread = None
        self._ws_loop = None
        logger.info(f"飞书 Channel '{self.slug}' 已停止")

    async def send(self, message: OutboundMessage) -> str | None:
        """发送消息并返回飞书 message_id（用于后续更新）。"""
        if not self._running or not self._http_client:
            raise ChannelSendError("飞书 Channel 未运行")
        await self._ensure_valid_token()
        return await self._send_text_message(
            chat_id=message.channel_chat_id,
            text=message.text,
            reply_to_message_id=message.reply_to_message_id,
        )

    async def update_message(self, message_id: str, text: str) -> None:
        """更新已发送的飞书消息内容（用于流式输出）。"""
        if not self._running or not self._http_client:
            raise ChannelSendError("飞书 Channel 未运行")
        await self._ensure_valid_token()

        post_content = self._markdown_to_post(text)
        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
        body = {
            "msg_type": "post",
            "content": json.dumps(post_content, ensure_ascii=False),
        }
        headers = {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        try:
            resp = await self._http_client.put(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.debug(f"飞书消息更新失败: {data.get('msg', 'unknown')}")
        except Exception:
            logger.debug(f"飞书消息更新异常: message_id={message_id}")

    async def test_connection(self) -> dict[str, Any]:
        """测试飞书 API 连接。"""
        try:
            await self._refresh_tenant_token()
            return {"ok": True, "channel_type": "feishu", "app_id": self._config.get_credential("app_id")}
        except Exception as e:
            return {"ok": False, "channel_type": "feishu", "error": str(e)}

    # ── WebSocket 事件回调 ────────────────────────────────

    def _on_ws_message(self, data: Any) -> None:
        """SDK 长连接推送的 im.message.receive_v1 事件回调（在 WS 线程中执行）。

        需要将异步处理调度到事件循环。
        """
        try:
            import lark_oapi as lark

            # 从 SDK 数据对象中提取事件信息
            event_data = json.loads(lark.JSON.marshal(data))
            logger.info(f"飞书 WS 收到事件: {json.dumps(event_data, ensure_ascii=False)[:500]}")
            # SDK 推送的事件结构：{schema, header, event: {sender, message}}
            event = event_data.get("event", event_data)
            message = event.get("message", {})
            sender = event.get("sender", {})

            # 只处理文本消息
            if message.get("message_type") != "text":
                return

            # 忽略机器人自身消息
            if sender.get("sender_type") == "app":
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
                raw_event=event_data,
                channel_slug=self.slug,
                agent_slug=self._config.agent_slug or "",
            )

            # 调度到主 asyncio 事件循环（WS 线程不能用自己的 loop）
            if self._on_message and self._main_loop:
                asyncio.run_coroutine_threadsafe(self._on_message(inbound), self._main_loop)

        except Exception:
            logger.exception("飞书 WebSocket 消息处理异常")

    # ── REST 发送 ─────────────────────────────────────────

    @staticmethod
    def _markdown_to_post(md: str) -> dict[str, Any]:
        """将 Markdown 文本转换为飞书 post 富文本格式。

        支持：标题（#）、粗体（**）、斜体（*）、无序列表（-）、
        行内代码（`）、分隔线（---）、普通段落。
        """
        paragraphs: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []

        def _flush() -> None:
            if current:
                paragraphs.append(current)

        def _parse_inline(line: str) -> list[dict[str, Any]]:
            """解析行内 Markdown 元素（粗体、斜体、行内代码）。"""
            elements: list[dict[str, Any]] = []
            i = 0
            while i < len(line):
                # 行内代码 `...`
                if line[i] == "`":
                    end = line.find("`", i + 1)
                    if end != -1:
                        elements.append({"tag": "text", "text": line[i + 1 : end]})
                        i = end + 1
                        continue
                # 粗体 **...**
                if line[i : i + 2] == "**":
                    end = line.find("**", i + 2)
                    if end != -1:
                        inner = line[i + 2 : end]
                        elements.append({"tag": "text", "text": inner, "style": ["bold"]})
                        i = end + 2
                        continue
                # 斜体 *...*（排除 ** 开头）
                if line[i] == "*" and (i + 1 >= len(line) or line[i + 1] != "*"):
                    end = line.find("*", i + 1)
                    if end != -1 and (end + 1 >= len(line) or line[end + 1] != "*"):
                        inner = line[i + 1 : end]
                        elements.append({"tag": "text", "text": inner, "style": ["italic"]})
                        i = end + 1
                        continue
                # 普通文本，收集到下一个特殊字符
                j = i
                while j < len(line) and line[j] not in ("`", "*"):
                    j += 1
                if j > i:
                    elements.append({"tag": "text", "text": line[i:j]})
                i = j if j > i else i + 1
            return elements if elements else [{"tag": "text", "text": line}]

        for raw_line in md.split("\n"):
            line = raw_line.rstrip()

            # 分隔线
            if line.strip() in ("---", "***", "___"):
                _flush()
                current = [{"tag": "text", "text": "─" * 30}]
                _flush()
                continue

            # 标题 # ## ###
            if line.startswith("#"):
                _flush()
                stripped = line.lstrip("#").strip()
                level = len(line) - len(line.lstrip("#"))
                prefix = "【" + "■" * max(1, 4 - level) + "】 "
                current = [{"tag": "text", "text": prefix + stripped, "style": ["bold"]}]
                _flush()
                continue

            # 无序列表 - 或 *
            if line.startswith("- ") or line.startswith("* "):
                item_text = line[2:].strip()
                current = [{"tag": "text", "text": "• "}] + _parse_inline(item_text)
                _flush()
                continue

            # 空行
            if not line.strip():
                _flush()
                continue

            # 普通段落
            current = _parse_inline(line)
            _flush()

        return {"zh_cn": {"title": "", "content": paragraphs}}

    async def _send_text_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> None:
        """通过飞书 REST API 发送富文本消息（post 格式，支持 Markdown 渲染）。"""
        assert self._http_client and self._tenant_access_token

        post_content = self._markdown_to_post(text)

        body = {
            "receive_id": chat_id,
            "msg_type": "post",
            "content": json.dumps(post_content, ensure_ascii=False),
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
            return data.get("data", {}).get("message_id")
        except httpx.HTTPStatusError as e:
            raise ChannelSendError(f"飞书消息发送失败: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise ChannelSendError(f"飞书消息发送失败: {e}") from e

    # ── Token 管理 ────────────────────────────────────────

    async def _ensure_valid_token(self) -> None:
        if self._tenant_access_token and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER:
            return
        await self._refresh_tenant_token()

    async def _refresh_tenant_token(self) -> None:
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
