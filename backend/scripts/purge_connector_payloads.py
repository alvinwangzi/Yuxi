"""过期敏感 payload 清理脚本 — 清理已终态调用的加密 payload。

保留 logical_call_key 和摘要字段以防重放，只清除不再需要的加密内容。
终态调用在保留足够核对信息后，可安全移除 params_ciphertext、
execution_snapshot_ciphertext 和 result_ciphertext。

使用方式：
  python purge_connector_payloads.py --dry-run
  python purge_connector_payloads.py --older-than-days 90 --batch-size 100
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

from yuxi.storage.postgres.models_business import ConnectorUsageLog
from yuxi.utils import logger
from yuxi.utils.datetime_utils import utc_now

BATCH_SIZE = 100
DEFAULT_OLDER_THAN_DAYS = 90

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "rejected", "cancelled"})


async def purge_payloads(
    session,
    *,
    dry_run: bool,
    batch_size: int,
    older_than: timedelta,
) -> int:
    """清理已终态且超过保留期的调用加密 payload。"""
    from sqlalchemy import select

    if not 1 <= batch_size <= 1000 or older_than <= timedelta(0):
        raise ValueError("清理批量和保留期必须为正数且批量不超过1000")
    cutoff = utc_now() - older_than
    offset = 0
    purged = 0

    while True:
        stmt = (
            select(ConnectorUsageLog)
            .where(
                ConnectorUsageLog.status.in_(TERMINAL_STATUSES),
                ConnectorUsageLog.completed_at.isnot(None),
                ConnectorUsageLog.completed_at < cutoff,
            )
            .where(
                (ConnectorUsageLog.params_ciphertext.isnot(None))
                | (ConnectorUsageLog.execution_snapshot_ciphertext.isnot(None))
                | (ConnectorUsageLog.result_ciphertext.isnot(None))
            )
            .limit(batch_size)
            .order_by(ConnectorUsageLog.id)
            .offset(offset)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            break

        for row in rows:
            if dry_run:
                purged += 1
                continue

            row.params_ciphertext = None
            row.execution_snapshot_ciphertext = None
            row.result_ciphertext = None
            row.key_id = None
            purged += 1

        if not dry_run:
            await session.flush()

        # 执行模式会缩小过滤集，下一页仍从头读取；dry-run 才前进游标。
        if dry_run:
            offset += batch_size

    return purged


async def run_purge(*, dry_run: bool, batch_size: int, older_than_days: int) -> None:
    from yuxi.storage.postgres.manager import pg_manager

    older_than = timedelta(days=older_than_days)
    mode = "dry-run" if dry_run else "execute"
    logger.info(f"开始 payload 清理 ({mode})，保留期 {older_than_days} 天")

    async with pg_manager.get_async_session_context() as session:
        count = await purge_payloads(session, dry_run=dry_run, batch_size=batch_size, older_than=older_than)
        logger.info(f"处理行数: {count}")

        if not dry_run:
            await session.commit()

    if dry_run:
        logger.info("dry-run 完成，未做任何修改")
    else:
        logger.info("payload 清理完成")


def main() -> None:
    parser = argparse.ArgumentParser(description="连接器过期 payload 清理")
    parser.add_argument("--dry-run", action="store_true", help="只预览不修改")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="每批处理行数")
    parser.add_argument("--older-than-days", type=int, default=DEFAULT_OLDER_THAN_DAYS, help="清理超过此天数的终态记录")
    args = parser.parse_args()

    asyncio.run(run_purge(dry_run=args.dry_run, batch_size=args.batch_size, older_than_days=args.older_than_days))


if __name__ == "__main__":
    main()
