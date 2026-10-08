"""连接器 key ring 轮换入口；先装配新旧 keys，再 dry-run 与分批执行。"""

import argparse
import asyncio
from yuxi.services.connectors.credential_vault import CredentialVault, ensure_vault_available
from yuxi.services.connectors.key_rotation import rotate_retained_materials, verify_retained_keys
from yuxi.storage.postgres.manager import pg_manager
from yuxi.utils import logger


async def run_rotation(*, dry_run: bool, batch_size: int) -> None:
    """脚本只编排公开用例，SQL 与事务由 owning 模块维护。"""
    vault = ensure_vault_available(CredentialVault.from_environment())
    pg_manager.initialize()
    await pg_manager.require_current_schema()
    try:
        counts = await rotate_retained_materials(
            session_factory=pg_manager.get_async_session_context, vault=vault, dry_run=dry_run, batch_size=batch_size
        )
        distribution = await verify_retained_keys(session_factory=pg_manager.get_async_session_context, vault=vault)
        logger.info(
            "连接器轮换: mode={}, counts={}, key_distribution={}",
            "dry-run" if dry_run else "execute",
            counts,
            distribution,
        )
    finally:
        await pg_manager.close()


def main() -> None:
    """处理 CLI 参数，失败返回非零退出而不吞掉不可解密行。"""
    parser = argparse.ArgumentParser(description="连接器 key ring 轮换")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run_rotation(dry_run=args.dry_run, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
