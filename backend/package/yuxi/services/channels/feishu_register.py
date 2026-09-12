"""飞书一键应用注册服务。

基于 lark_oapi SDK 的 aregister_app 能力，用户扫码即可自动创建飞书应用并获取凭据，
无需手动前往开发者后台配置权限、事件订阅等。

注意：aregister_app 是一个完整的异步流程（获取设备码 → 回调 QR URL → 轮询等待扫码 → 返回凭据），
因此必须作为单个后台任务运行，通过回调通知 QR URL，任务完成时获取凭据。
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from yuxi.utils.logging_config import logger


@dataclass
class FeishuRegistration:
    """一次飞书应用注册流程的状态。"""

    id: str
    qr_url: str = ""
    expire_in: int = 0
    status: str = "init"  # init | qr_ready | polling | completed | error | cancelled
    app_id: str = ""
    app_secret: str = ""
    error: str = ""
    _task: asyncio.Task | None = field(default=None, repr=False)


# ── 飞书智能体应用预置权限/事件/回调 ─────────────────────
# 参考: https://open.feishu.cn/document/mcp_open_tools/integrating-agents-with-feishu/overview

_FEISHU_AGENT_ADDONS: dict[str, Any] = {
    "scopes": {
        "tenant": [
            "im:message:send_as_bot",
            "im:message:readonly",
            "im:message.p2p_msg:readonly",
            "im:message.group_at_msg:readonly",
            "im:message.group_at_msg.include_bot:bot:readonly",
            "im:chat:read",
            "im:resource",
            "contact:contact.base:readonly",
            "application:bot.basic_info:read",
        ],
    },
    "events": {
        "items": {
            "tenant": [
                "im.message.receive_v1",
                "im.chat.member.bot.added_v1",
                "im.chat.member.bot.deleted_v1",
            ],
        },
    },
}


class FeishuRegistrationManager:
    """管理飞书应用注册流程（内存存储，进程生命周期内有效）。"""

    def __init__(self) -> None:
        self._registrations: dict[str, FeishuRegistration] = {}

    async def start_registration(self) -> FeishuRegistration:
        """发起一次新的飞书应用注册流程。

        aregister_app 是完整流程（获取设备码 → 回调 QR → 等待扫码 → 返回凭据），
        因此直接作为后台任务运行，通过 on_qr_code 回调获取 QR URL。
        """
        try:
            import lark_oapi as lark
        except ImportError as e:
            raise RuntimeError("lark_oapi 未安装，无法发起飞书应用注册") from e

        reg_id = uuid.uuid4().hex
        reg = FeishuRegistration(id=reg_id)
        self._registrations[reg_id] = reg

        qr_ready_event = asyncio.Event()

        def on_qr_code(info: dict) -> None:
            reg.qr_url = info["url"]
            reg.expire_in = info.get("expire_in", 600)
            reg.status = "qr_ready"
            # 通知等待 QR 的就绪事件
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(qr_ready_event.set)
            except RuntimeError:
                qr_ready_event.set()

        def on_status_change(info: dict) -> None:
            status = info.get("status", "")
            if status in ("polling", "slow_down"):
                reg.status = "polling"

        async def _run() -> None:
            """后台任务：运行完整的 aregister_app 流程。"""
            try:
                result = await lark.aregister_app(
                    on_qr_code=on_qr_code,
                    on_status_change=on_status_change,
                    source="yuxi",
                    addons=_FEISHU_AGENT_ADDONS,
                    app_preset={
                        "name": "Yuxi AI Agent",
                        "desc": "由 Yuxi 智能体平台创建的飞书应用",
                    },
                )
                reg.app_id = result["client_id"]
                reg.app_secret = result["client_secret"]
                reg.status = "completed"
                logger.info(f"飞书应用注册成功: {reg.app_id}")
            except Exception as e:
                error_name = type(e).__name__
                if "AppAccessDenied" in error_name:
                    reg.status = "error"
                    reg.error = "用户拒绝授权"
                elif "AppExpired" in error_name:
                    reg.status = "error"
                    reg.error = "二维码已过期"
                else:
                    reg.status = "error"
                    reg.error = str(e)
                logger.warning(f"飞书应用注册失败: {e}")
                # 如果 QR 还未就绪就出错了，通知等待者
                qr_ready_event.set()

        # 启动后台任务（aregister_app 会先获取设备码，触发 on_qr_code 回调）
        reg._task = asyncio.create_task(_run(), name=f"feishu-register-{reg_id}")

        # 等待 QR URL 就绪（aregister_app 内部会先获取设备码再调用 on_qr_code）
        try:
            await asyncio.wait_for(qr_ready_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            if reg.status not in ("error", "completed"):
                reg.status = "error"
                reg.error = "获取二维码超时"

        return reg

    def get_registration(self, reg_id: str) -> FeishuRegistration | None:
        return self._registrations.get(reg_id)

    def cleanup_expired(self) -> None:
        """清理已完成的或出错的注册记录。"""
        expired = [
            rid
            for rid, reg in self._registrations.items()
            if reg.status in ("completed", "error", "cancelled")
        ]
        for rid in expired:
            self._registrations.pop(rid, None)


# 全局单例
_registration_manager = FeishuRegistrationManager()


def get_feishu_registration_manager() -> FeishuRegistrationManager:
    return _registration_manager
