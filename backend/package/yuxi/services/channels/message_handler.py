"""Channel 消息处理服务。

将 InboundMessage 转换为 RunSubmissionCommand 进入主链路，
等待 AgentRun 完成后提取回复并通过 Channel 发送。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.services.agent_run_service import await_agent_run_result
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
            conversation_title=f"{message.channel_type} Channel",
        ),
        current_user=user,
        db=db,
    )

    run_id = result.get("run_id")
    if not run_id:
        logger.warning(f"Channel 消息提交后无 run_id: channel={channel_slug}")
        return result

    try:
        run_result = await await_agent_run_result(
            run_id=run_id,
            current_uid=str(user.uid),
        )
    except Exception:
        logger.exception(f"等待 Channel 消息的 AgentRun 完成失败: run_id={run_id}")
        return result

    output_text = run_result.get("output") or ""
    status = run_result.get("status", "unknown")

    if output_text.strip():
        reply = OutboundMessage(
            channel_type=message.channel_type,
            channel_chat_id=message.channel_chat_id,
            text=output_text.strip(),
            reply_to_message_id=message.message_id,
        )
        try:
            await channel_manager.send_message(channel_slug, reply)
        except ChannelSendError:
            logger.exception(f"通过 Channel '{channel_slug}' 发送回复失败")

    result["output"] = output_text
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
