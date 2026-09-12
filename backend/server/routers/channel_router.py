"""Channel 管理 API。

提供 Channel 配置的 CRUD 接口，以及连接测试。
配置持久化到 PostgreSQL channel_configs 表。
仅管理员可操作。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db
from yuxi.services.channels.base import ChannelConfig
from yuxi.services.channels.manager import ChannelManager, get_registered_channel_types
from yuxi.services.channels.repository import ChannelConfigRepository
from yuxi.utils.logging_config import logger

channel_router = APIRouter(prefix="/system/channels", tags=["channels"])

# 全局 ChannelManager 实例
_channel_manager = ChannelManager()


def get_channel_manager() -> ChannelManager:
    return _channel_manager


# 注册 Channel 类型
try:
    from yuxi.services.channels.feishu import FeishuChannel
    from yuxi.services.channels.dingtalk import DingTalkChannel
    from yuxi.services.channels.wecom import WeComChannel
    from yuxi.services.channels.manager import register_channel_type
    for _type, _cls in [("feishu", FeishuChannel), ("dingtalk", DingTalkChannel), ("wecom", WeComChannel)]:
        try:
            register_channel_type(_type, _cls)
        except ValueError:
            pass  # 已注册
except ImportError:
    pass


# ── 请求/响应模型 ──────────────────────────────────────────


class ChannelConfigCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64, description="Channel 唯一标识")
    name: str | None = Field(None, max_length=128, description="Channel 显示名称")
    channel_type: str = Field(..., min_length=1, max_length=32, description="Channel 类型（如 feishu）")
    enabled: bool = Field(True, description="是否启用")
    credentials: dict[str, Any] = Field(default_factory=dict, description="凭据配置")
    extra: dict[str, Any] = Field(default_factory=dict, description="额外配置")
    agent_slug: str | None = Field(None, description="默认目标 Agent slug")


class ChannelConfigUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    credentials: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None
    agent_slug: str | None = None


class ChannelConfigResponse(BaseModel):
    slug: str
    name: str | None = None
    channel_type: str
    enabled: bool
    agent_slug: str | None = None
    extra: dict[str, Any] = {}
    is_running: bool = False
    # 凭据只返回 key 列表，不返回实际值
    credential_keys: list[str] = []


class ChannelTypeResponse(BaseModel):
    type: str


def _db_row_to_response(row, manager: ChannelManager) -> ChannelConfigResponse:
    """将数据库行转换为 API 响应。"""
    channel = manager.get_channel(row.slug)
    credentials = row.credentials or {}
    return ChannelConfigResponse(
        slug=row.slug,
        name=row.name,
        channel_type=row.channel_type,
        enabled=row.enabled,
        agent_slug=row.agent_slug,
        extra=row.extra or {},
        is_running=channel.is_running if channel else False,
        credential_keys=sorted(credentials.keys()),
    )


def _db_row_to_channel_config(row) -> ChannelConfig:
    """将数据库行转换为 ChannelConfig 数据类。"""
    return ChannelConfig(
        slug=row.slug,
        channel_type=row.channel_type,
        enabled=row.enabled,
        credentials=row.credentials or {},
        extra=row.extra or {},
        agent_slug=row.agent_slug,
        name=row.name,
    )


# ── API 路由 ──────────────────────────────────────────────


@channel_router.get("/types")
async def list_channel_types(
    _admin=Depends(get_admin_user),
) -> list[ChannelTypeResponse]:
    """列出已注册的 Channel 类型。"""
    return [ChannelTypeResponse(type=t) for t in get_registered_channel_types()]


@channel_router.get("")
async def list_channels(
    _admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChannelConfigResponse]:
    """列出所有已配置的 Channel。"""
    manager = get_channel_manager()
    repo = ChannelConfigRepository(db)
    rows = await repo.list_all()
    return [_db_row_to_response(row, manager) for row in rows]


@channel_router.post("", status_code=201)
async def create_channel(
    payload: ChannelConfigCreate,
    admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ChannelConfigResponse:
    """创建新的 Channel 配置。"""
    repo = ChannelConfigRepository(db)
    if await repo.exists_slug(payload.slug):
        raise HTTPException(status_code=409, detail=f"Channel '{payload.slug}' 已存在")

    row = await repo.create(
        slug=payload.slug,
        name=payload.name,
        channel_type=payload.channel_type,
        enabled=payload.enabled,
        credentials=payload.credentials,
        extra=payload.extra,
        agent_slug=payload.agent_slug,
        created_by=admin.uid,
    )
    await db.commit()

    manager = get_channel_manager()
    config = _db_row_to_channel_config(row)

    if config.enabled:
        try:
            from yuxi.services.channels.message_handler import ensure_channel_message_handler
            await ensure_channel_message_handler(manager)
            await manager.create_channel(config)
            await manager.start_channel(config.slug)
        except Exception as e:
            logger.warning(f"创建 Channel '{payload.slug}' 后启动失败: {e}")

    return _db_row_to_response(row, manager)


@channel_router.post("/feishu/register")
async def start_feishu_registration(
    _admin=Depends(get_admin_user),
) -> dict[str, Any]:
    """发起飞书应用一键注册，返回扫码链接。

    基于 lark_oapi SDK 的 register_app 能力，用户扫码即可自动创建飞书应用。
    返回 registration_id 用于后续轮询结果。
    """
    from yuxi.services.channels.feishu_register import get_feishu_registration_manager

    manager = get_feishu_registration_manager()
    manager.cleanup_expired()
    try:
        reg = await manager.start_registration()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "registration_id": reg.id,
        "qr_url": reg.qr_url,
        "expire_in": reg.expire_in,
        "status": reg.status,
    }


@channel_router.get("/feishu/register/{registration_id}")
async def get_feishu_registration_status(
    registration_id: str,
    _admin=Depends(get_admin_user),
) -> dict[str, Any]:
    """查询飞书应用注册状态。

    返回 status（init/qr_ready/polling/completed/error）；
    completed 时额外返回 app_id 和 app_secret。
    """
    from yuxi.services.channels.feishu_register import get_feishu_registration_manager

    manager = get_feishu_registration_manager()
    reg = manager.get_registration(registration_id)
    if not reg:
        raise HTTPException(status_code=404, detail="注册记录不存在或已过期")

    result: dict[str, Any] = {
        "registration_id": reg.id,
        "status": reg.status,
    }
    if reg.status == "completed":
        result["app_id"] = reg.app_id
        result["app_secret"] = reg.app_secret
    elif reg.status == "error":
        result["error"] = reg.error
    return result


@channel_router.get("/{slug}")
async def get_channel(
    slug: str,
    _admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ChannelConfigResponse:
    """获取单个 Channel 配置。"""
    repo = ChannelConfigRepository(db)
    row = await repo.get_by_slug(slug)
    if not row:
        raise HTTPException(status_code=404, detail=f"Channel '{slug}' 不存在")
    manager = get_channel_manager()
    return _db_row_to_response(row, manager)


@channel_router.put("/{slug}")
async def update_channel(
    slug: str,
    payload: ChannelConfigUpdate,
    admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ChannelConfigResponse:
    """更新 Channel 配置。"""
    repo = ChannelConfigRepository(db)
    row = await repo.get_by_slug(slug)
    if not row:
        raise HTTPException(status_code=404, detail=f"Channel '{slug}' 不存在")

    row = await repo.update(
        row,
        name=payload.name,
        enabled=payload.enabled,
        credentials=payload.credentials,
        extra=payload.extra,
        agent_slug=payload.agent_slug,
        updated_by=admin.uid,
    )
    await db.commit()

    manager = get_channel_manager()
    config = _db_row_to_channel_config(row)

    # 重启 Channel 实例
    await manager.remove_channel(slug)
    if config.enabled:
        try:
            from yuxi.services.channels.message_handler import ensure_channel_message_handler
            await ensure_channel_message_handler(manager)
            await manager.create_channel(config)
            await manager.start_channel(slug)
        except Exception as e:
            logger.warning(f"更新 Channel '{slug}' 后重启失败: {e}")

    return _db_row_to_response(row, manager)


@channel_router.delete("/{slug}", status_code=204)
async def delete_channel(
    slug: str,
    _admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除 Channel。"""
    repo = ChannelConfigRepository(db)
    if not await repo.exists_slug(slug):
        raise HTTPException(status_code=404, detail=f"Channel '{slug}' 不存在")

    manager = get_channel_manager()
    await manager.remove_channel(slug)
    await repo.delete(slug)
    await db.commit()


@channel_router.post("/{slug}/test")
async def test_channel(
    slug: str,
    _admin=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """测试 Channel 连接。"""
    manager = get_channel_manager()
    channel = manager.get_channel(slug)
    if not channel:
        repo = ChannelConfigRepository(db)
        row = await repo.get_by_slug(slug)
        if not row:
            raise HTTPException(status_code=404, detail=f"Channel '{slug}' 不存在")
        config = _db_row_to_channel_config(row)
        try:
            await manager.create_channel(config)
            channel = manager.get_channel(slug)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if not channel:
        raise HTTPException(status_code=500, detail="Channel 创建失败")

    try:
        result = await channel.test_connection()
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}



