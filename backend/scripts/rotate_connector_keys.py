"""密钥轮换脚本 — 分批重加密凭据与调用 payload。

操作顺序：
1. 所有 API/worker 加载旧+新 keys（受控旧 key ring）
2. 切换当前写 key
3. 本脚本重加密 credential、非终态 snapshot/params 和仍保留的 result
4. 回读 key_id 与抽样解密验证
5. 确认无旧 key 使用后移除旧 key

使用方式：
  python rotate_connector_keys.py --dry-run          # 预览
  python rotate_connector_keys.py --batch-size 50    # 执行
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from yuxi.services.connectors.credential_vault import CredentialVault, CredentialVaultError
from yuxi.storage.postgres.models_business import (
    ConnectorCredential,
    ConnectorUsageLog,
)
from yuxi.utils import logger

BATCH_SIZE = 100

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "rejected", "cancelled"})


async def rotate_credentials(session, vault: CredentialVault, *, dry_run: bool, batch_size: int) -> int:
    """重加密所有仍使用旧 key_id 的凭据行。"""
    from sqlalchemy import select

    offset = 0
    rotated = 0

    while True:
        stmt = (
            select(ConnectorCredential)
            .where(ConnectorCredential.key_id != vault.current_key_id)
            .limit(batch_size)
            .offset(offset)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            break

        for row in rows:
            if not row.credential_value or not row.key_id:
                continue
            try:
                plaintext = vault.decrypt(row.credential_value, row.key_id)
            except CredentialVaultError:
                logger.warning(f"跳过无法解密的凭据行 id={row.id} key_id={row.key_id}")
                continue

            if dry_run:
                rotated += 1
                continue

            encrypted = vault.encrypt(plaintext)
            row.credential_value = encrypted.ciphertext
            row.key_id = encrypted.key_id
            rotated += 1

        if not dry_run:
            await session.flush()

        offset += batch_size

    return rotated


async def rotate_invocation_payloads(session, vault: CredentialVault, *, dry_run: bool, batch_size: int) -> int:
    """重加密非终态调用的加密 payload（params、snapshot、result）。"""
    from sqlalchemy import select

    offset = 0
    rotated = 0

    while True:
        stmt = (
            select(ConnectorUsageLog)
            .where(
                ConnectorUsageLog.status.notin_(TERMINAL_STATUSES),
                ConnectorUsageLog.key_id.isnot(None),
                ConnectorUsageLog.key_id != vault.current_key_id,
            )
            .limit(batch_size)
            .offset(offset)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            break

        for row in rows:
            old_key_id = row.key_id
            reencrypted_fields = False

            if row.params_ciphertext:
                try:
                    plaintext = vault.decrypt(row.params_ciphertext, old_key_id)
                    encrypted = vault.encrypt(plaintext)
                    if not dry_run:
                        row.params_ciphertext = encrypted.ciphertext
                    reencrypted_fields = True
                except CredentialVaultError:
                    logger.warning(f"跳过 params 解密失败 invocation_id={row.id}")

            if row.execution_snapshot_ciphertext:
                try:
                    plaintext = vault.decrypt(row.execution_snapshot_ciphertext, old_key_id)
                    encrypted = vault.encrypt(plaintext)
                    if not dry_run:
                        row.execution_snapshot_ciphertext = encrypted.ciphertext
                    reencrypted_fields = True
                except CredentialVaultError:
                    logger.warning(f"跳过 snapshot 解密失败 invocation_id={row.id}")

            if row.result_ciphertext:
                try:
                    plaintext = vault.decrypt(row.result_ciphertext, old_key_id)
                    encrypted = vault.encrypt(plaintext)
                    if not dry_run:
                        row.result_ciphertext = encrypted.ciphertext
                    reencrypted_fields = True
                except CredentialVaultError:
                    logger.warning(f"跳过 result 解密失败 invocation_id={row.id}")

            if reencrypted_fields and not dry_run:
                row.key_id = vault.current_key_id

            if reencrypted_fields:
                rotated += 1

        if not dry_run:
            await session.flush()

        offset += batch_size

    return rotated


async def verify_rotation(session, vault: CredentialVault) -> dict[str, int]:
    """回读抽样验证：统计各 key_id 的剩余行数。"""
    from sqlalchemy import select, func

    cred_stmt = select(ConnectorCredential.key_id, func.count()).group_by(ConnectorCredential.key_id)
    cred_result = await session.execute(cred_stmt)
    cred_counts = dict(cred_result.all())

    inv_stmt = select(ConnectorUsageLog.key_id, func.count()).group_by(ConnectorUsageLog.key_id)
    inv_result = await session.execute(inv_stmt)
    inv_counts = dict(inv_result.all())

    return {"credentials_by_key": cred_counts, "invocations_by_key": inv_counts}


async def run_rotation(*, dry_run: bool, batch_size: int) -> None:
    vault = CredentialVault.from_environment()
    if vault is None:
        logger.error("凭据保险库未配置，无法执行密钥轮换")
        sys.exit(1)

    from yuxi.storage.postgres.manager import pg_manager

    mode = "dry-run" if dry_run else "execute"
    logger.info(f"开始密钥轮换 ({mode})，当前 key_id={vault.current_key_id}")

    async with pg_manager.get_async_session_context() as session:
        cred_count = await rotate_credentials(session, vault, dry_run=dry_run, batch_size=batch_size)
        logger.info(f"凭据行处理: {cred_count}")

        inv_count = await rotate_invocation_payloads(session, vault, dry_run=dry_run, batch_size=batch_size)
        logger.info(f"调用 payload 处理: {inv_count}")

        if not dry_run:
            await session.commit()

        stats = await verify_rotation(session, vault)
        logger.info(f"轮换后分布: {stats}")

    if dry_run:
        logger.info("dry-run 完成，未做任何修改")
    else:
        logger.info("密钥轮换完成")


def main() -> None:
    parser = argparse.ArgumentParser(description="连接器密钥轮换")
    parser.add_argument("--dry-run", action="store_true", help="只预览不修改")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="每批处理行数")
    args = parser.parse_args()

    asyncio.run(run_rotation(dry_run=args.dry_run, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
