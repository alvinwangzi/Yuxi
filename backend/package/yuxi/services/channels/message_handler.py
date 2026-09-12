"""Channel 消息处理服务。

将 InboundMessage 转换为 RunSubmissionCommand 进入主链路，
流式读取 AgentRun 事件并通过 Channel 发送回复。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.services.agent_run_service import stream_agent_run_events
from yuxi.services.channels.base import (
    ChannelSendError,
    InboundMessage,
    OutboundMessage,
)
from yuxi.services.channels.manager import ChannelManager
from yuxi.services.input_message_service import build_chat_input_message
from yuxi.services.run_submission_service import RunOrigin, RunSubmissionCommand, submit_run_command
from yuxi.storage.postgres.models_business import User
from yuxi.utils.hash_utils import hash_id
from yuxi.utils.logging_config import logger

# 流式输出：每积累 N 个字符或 N 秒更新一次飞书消息
_STREAM_UPDATE_CHARS = 200
_STREAM_UPDATE_INTERVAL = 3.0


async def handle_channel_message(
    message: InboundMessage,
    *,
    channel_slug: str,
    agent_slug: str,
    user: User,
    db: AsyncSession,
    channel_manager: ChannelManager,
) -> dict[str, Any]:
    """处理来自 IM Channel 的一条消息。

    1. 生成稳定的 thread_id 和 request_id
    2. 提交到 Agent 运行队列
    3. 等待运行完成
    4. 将回复发送到 IM
    """
    thread_id = _resolve_thread_id(
        uid=str(user.uid),
        channel_type=message.channel_type,
        channel_slug=channel_slug,
        chat_id=message.channel_chat_id,
    )
    external_id = message.stable_message_id
    request_id = hash_id(
        "channel_msg_",
        f"{user.uid}:{channel_slug}:{message.channel_chat_id}:{external_id}",
        length=64,
    )

    origin_metadata: dict[str, Any] = {
        "account_id": message.sender_id,
        "chat_id": message.channel_chat_id,
    }
    if message.sender_name:
        origin_metadata["sender_name"] = message.sender_name

    result = await submit_run_command(
        command=RunSubmissionCommand(
            agent_slug=agent_slug,
            thread_id=thread_id,
            request_id=request_id,
            input_message=build_chat_input_message(message.text),
            origin=RunOrigin(
                source="channel",
                channel=message.channel_type,
                external_id=external_id,
                metadata=origin_metadata,
            ),
            request_metadata={"message_type": "text", "channel_slug": channel_slug},
            create_conversation=True,
            conversation_title=f"{channel_slug} ({message.channel_type})",
        ),
        current_user=user,
        db=db,
    )

    run_id = result.get("run_id")
    logger.info(f"Channel '{channel_slug}' 提交 Run: run_id={run_id}, status={result.get('status')}")
    if not run_id:
        logger.warning(f"Channel 消息提交后无 run_id: channel={channel_slug}")
        return result

    # 即时发送"已收到"反馈，让用户知道消息已被接收
    ack_text = "✅ 已收到，正在处理中…"
    try:
        ack_reply = OutboundMessage(
            channel_type=message.channel_type,
            channel_chat_id=message.channel_chat_id,
            text=ack_text,
            reply_to_message_id=message.message_id,
        )
        feishu_msg_id = await channel_manager.send_message(channel_slug, ack_reply)
        logger.info(f"Channel '{channel_slug}' 已发送即时反馈")
    except Exception:
        logger.debug(f"Channel '{channel_slug}' 发送即时反馈失败")
        feishu_msg_id = None

    # 流式读取 AgentRun 事件，边生成边发送到飞书
    output_parts: list[str] = []
    last_update_len = 0
    last_update_time = time.monotonic()
    status = "unknown"

    try:
        async for raw_event in stream_agent_run_events(
            run_id=run_id,
            after_seq="0-0",
            current_uid=str(user.uid),
            verbose=False,
        ):
            try:
                event = json.loads(raw_event) if isinstance(raw_event, str) else raw_event
            except (json.JSONDecodeError, TypeError):
                continue

            event_type = event.get("event", "")
            payload = event.get("data") or event.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    payload = {}

            # 提取文本增量
            chunk = payload.get("chunk") or {}
            stream_event = chunk.get("stream_event") or {}
            delta_text = ""

            if stream_event.get("type") == "message_delta":
                delta_text = stream_event.get("content") or ""
            elif chunk.get("status") == "completed":
                status = "completed"
            elif chunk.get("status") in ("failed", "error"):
                status = chunk.get("status", "failed")

            if delta_text:
                output_parts.append(delta_text)

            # 定期更新飞书消息
            current_text = "".join(output_parts)
            now = time.monotonic()
            should_update = (
                len(current_text) - last_update_len >= _STREAM_UPDATE_CHARS
                or now - last_update_time >= _STREAM_UPDATE_INTERVAL
            )
            if should_update and current_text.strip():
                try:
                    if feishu_msg_id:
                        await channel_manager.update_message(channel_slug, feishu_msg_id, current_text)
                    else:
                        reply = OutboundMessage(
                            channel_type=message.channel_type,
                            channel_chat_id=message.channel_chat_id,
                            text=current_text,
                            reply_to_message_id=message.message_id,
                        )
                        feishu_msg_id = await channel_manager.send_message(channel_slug, reply)
                    last_update_len = len(current_text)
                    last_update_time = now
                except Exception:
                    logger.debug(f"Channel '{channel_slug}' 流式更新失败")

            if event_type == "end":
                status = payload.get("status") or chunk.get("status") or status
                break

    except Exception:
        logger.exception(f"Channel '{channel_slug}' 流式读取 Run 事件失败: run_id={run_id}")

    # 发送最终完整消息
    final_text = "".join(output_parts).strip()
    if final_text:
        try:
            if feishu_msg_id:
                await channel_manager.update_message(channel_slug, feishu_msg_id, final_text)
            else:
                reply = OutboundMessage(
                    channel_type=message.channel_type,
                    channel_chat_id=message.channel_chat_id,
                    text=final_text,
                    reply_to_message_id=message.message_id,
                )
                await channel_manager.send_message(channel_slug, reply)
            logger.info(f"Channel '{channel_slug}' 回复已发送: {len(final_text)} 字符")
        except ChannelSendError:
            logger.exception(f"通过 Channel '{channel_slug}' 发送回复失败")
    else:
        logger.warning(f"Channel '{channel_slug}' Run 输出为空: status={status}")

    result["output"] = final_text
    result["run_status"] = status
    return result


def _resolve_thread_id(
    *,
    uid: str,
    channel_type: str,
    channel_slug: str,
    chat_id: str,
) -> str:
    """为 Channel 会话生成稳定的 Yuxi Thread ID。"""
    return hash_id(
        "channel_thread_",
        f"{uid}:{channel_type}:{channel_slug}:{chat_id}",
        length=64,
    )


async def ensure_channel_message_handler(
    manager: ChannelManager,
) -> None:
    """确保 ChannelManager 已设置消息处理器。

    为每个 Channel 创建独立的闭包处理器，
    将 InboundMessage 路由到 handle_channel_message 进入 Agent 主链路。
    重复调用安全——已有 handler 时直接返回。
    """
    if manager._message_handler is not None:
        return

    from yuxi.storage.postgres.manager import pg_manager
    from yuxi.storage.postgres.models_business import User

    async def _get_system_user(db: AsyncSession) -> User | None:
        """获取系统用户（superadmin 优先）用于渠道消息的身份。"""
        from sqlalchemy import select as sa_select

        result = await db.execute(
            sa_select(User).where(User.role == "superadmin").limit(1)
        )
        user = result.scalar_one_or_none()
        if user:
            return user
        result = await db.execute(sa_select(User).limit(1))
        return result.scalar_one_or_none()

    async def handler(message: InboundMessage) -> None:
        channel_slug = message.channel_slug
        agent_slug = message.agent_slug or "default-chatbot"

        logger.info(
            f"处理 Channel '{channel_slug}' 消息: sender={message.sender_id}, "
            f"text={message.text[:50]}…"
        )

        try:
            async with pg_manager.get_async_session_context() as db:
                user = await _get_system_user(db)
                if not user:
                    logger.error("Channel 消息处理失败：系统中无可用用户")
                    return
                await handle_channel_message(
                    message,
                    channel_slug=channel_slug,
                    agent_slug=agent_slug,
                    user=user,
                    db=db,
                    channel_manager=manager,
                )
        except Exception:
            logger.exception(f"处理 Channel '{channel_slug}' 消息异常")

    manager.set_message_handler(handler)
