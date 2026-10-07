"""连接器调用恢复 — 处理 lease 过期、失联 worker 和 unknown 收敛。

基础恢复能力纳入现有 worker startup/周期任务，不另设本地守护进程。
"""

from __future__ import annotations

from yuxi.utils import logger
from yuxi.utils.datetime_utils import utc_now_naive


async def recover_stale_leases(session_context_factory) -> dict[str, int]:
    """扫描 lease 过期的 running 调用，按操作类型收敛。

    read 操作可直接标记 failed/abandoned；write 操作标记 unknown 等待核对。
    返回处理的调用数和分类计数。
    """
    stats = {"total": 0, "read_failed": 0, "write_unknown": 0}

    async with session_context_factory() as db:
        from yuxi.repositories.connector_execution_repository import ConnectorExecutionRepository
        exec_repo = ConnectorExecutionRepository(db)

        now = utc_now_naive()
        stale = await exec_repo.find_stale_leases(now)

        for invocation in stale:
            stats["total"] += 1
            owner_attempt = invocation.owner_attempt or "recovery"

            if invocation.operation_type == "read":
                await exec_repo.finalize_invocation(
                    invocation,
                    owner_attempt=owner_attempt,
                    status="failed",
                    remote_outcome="not_sent",
                    error_code="lease_expired",
                    error_summary="读操作 lease 过期，自动标记失败",
                )
                stats["read_failed"] += 1
            else:
                await exec_repo.mark_unknown(
                    invocation,
                    owner_attempt=owner_attempt,
                    error_code="lease_expired",
                    error_summary="写操作 lease 过期，需要人工核对",
                )
                stats["write_unknown"] += 1

    if stats["total"] > 0:
        logger.info(f"连接器恢复: 处理 {stats['total']} 个过期调用 "
                     f"(读失败={stats['read_failed']}, 写未知={stats['write_unknown']})")

    return stats
