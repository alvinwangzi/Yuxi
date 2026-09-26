"""模型供应商配置数据访问层。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.storage.postgres.models_business import ModelProvider
from yuxi.utils.datetime_utils import utc_now_naive


async def list_model_providers(db: AsyncSession, *, include_tombstones: bool = False) -> list[ModelProvider]:
    """获取全部模型供应商配置。

    include_tombstones=True 时包含已删除的内置墓碑行，供前端展示“已删除”卡片与恢复入口。
    """
    query = select(ModelProvider)
    if not include_tombstones:
        query = query.where(ModelProvider.deleted_at.is_(None))
    query = query.order_by(ModelProvider.is_enabled.desc(), ModelProvider.provider_id.asc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_model_provider(db: AsyncSession, provider_id: str) -> ModelProvider | None:
    """按 provider_id 获取有效模型供应商配置；已删除的内置墓碑行视为不存在。"""
    result = await db.execute(
        select(ModelProvider).where(
            ModelProvider.provider_id == provider_id,
            ModelProvider.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_model_provider_with_tombstone(db: AsyncSession, provider_id: str) -> ModelProvider | None:
    """按 provider_id 获取配置，包含已删除的内置墓碑行；供 ensure 与创建复活判断使用。"""
    result = await db.execute(select(ModelProvider).where(ModelProvider.provider_id == provider_id))
    return result.scalar_one_or_none()


async def create_model_provider(db: AsyncSession, data: dict) -> ModelProvider:
    """创建模型供应商配置。"""
    provider = ModelProvider(**data)
    db.add(provider)
    await db.flush()
    await db.refresh(provider)
    return provider


async def update_model_provider(db: AsyncSession, provider: ModelProvider, data: dict) -> ModelProvider:
    """更新模型供应商配置。"""
    for key, value in data.items():
        if key != "provider_id":
            setattr(provider, key, value)
    await db.flush()
    await db.refresh(provider)
    return provider


async def delete_model_provider(db: AsyncSession, provider: ModelProvider) -> None:
    """删除模型供应商配置；内置供应商保留墓碑行，防止启动时被 ensure 重新创建。"""
    if provider.is_builtin:
        provider.deleted_at = utc_now_naive()
        await db.flush()
        return
    await db.delete(provider)
    await db.flush()


async def purge_model_provider(db: AsyncSession, provider: ModelProvider) -> None:
    """物理删除模型供应商行，仅用于清除墓碑以便同 id 重建。"""
    await db.delete(provider)
    await db.flush()


async def restore_model_provider(db: AsyncSession, provider: ModelProvider) -> ModelProvider:
    """恢复已删除的内置供应商：清除墓碑标记并禁用，等待管理员重新配置。"""
    provider.deleted_at = None
    provider.is_enabled = False
    await db.flush()
    await db.refresh(provider)
    return provider
