"""连接器 v21 的 UTC、UUID 与拒绝约束在一个版本事务内升级。"""

from sqlalchemy import text

from yuxi.utils import logger

TIME_COLUMNS = {
    "connectors": ("created_at", "updated_at", "deleted_at"),
    "connector_credentials": ("updated_at",),
    "connector_operations": ("created_at", "updated_at"),
    "connector_usage_logs": (
        "approved_at",
        "approval_expires_at",
        "lease_expires_at",
        "heartbeat_at",
        "created_at",
        "started_at",
        "completed_at",
    ),
    "connector_operation_attempts": ("started_at", "completed_at", "created_at"),
    "workflow_runs": ("next_dispatch_at", "lease_expires_at", "heartbeat_at"),
}

CONSTRAINTS = {
    "ck_connector_logs_status": (
        "status IN ('awaiting_approval','prepared','running','succeeded','failed','rejected','cancelled','unknown')"
    ),
    "ck_connector_logs_outcome": (
        "remote_outcome IS NULL OR remote_outcome IN ('not_sent','succeeded','failed','unknown')"
    ),
    "ck_connector_logs_actor": "actor_uid IS NOT NULL AND actor_uid <> ''",
    "ck_connector_logs_operation_type": "operation_type IN ('read','write')",
    "ck_connector_logs_consumer": "consumer_type IN ('agent','workflow','admin_test')",
    "ck_connector_logs_approval": "approval_policy IS NULL OR approval_policy IN ('required','preauthorized')",
}


async def upgrade_connector_schema(connection, *, version_table, version):
    """历史 naive 按原 UTC clock 转换；异常会回滚类型、约束及版本。"""
    if await connection.scalar(text("SELECT to_regclass('connector_operation_attempts') IS NOT NULL")):
        await connection.execute(
            text(
                "ALTER TABLE connector_operation_attempts ADD COLUMN IF NOT EXISTS "
                "created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
            )
        )
    for table, columns in TIME_COLUMNS.items():
        for column in columns:
            data_type = await connection.scalar(
                text(
                    "SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() "
                    "AND table_name=:table AND column_name=:column"
                ),
                {"table": table, "column": column},
            )
            if data_type == "timestamp without time zone":
                await connection.execute(
                    text(
                        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TIMESTAMPTZ USING {column} AT TIME ZONE 'UTC'"
                    )
                )
    exists = await connection.scalar(text("SELECT to_regclass('workflow_step_runs') IS NOT NULL"))
    if exists:
        await connection.execute(
            text(
                "ALTER TABLE workflow_step_runs ALTER COLUMN pending_connector_invocation_id "
                "TYPE VARCHAR(36) USING pending_connector_invocation_id::text"
            )
        )
    exists = await connection.scalar(text("SELECT to_regclass('connector_usage_logs') IS NOT NULL"))
    if exists:
        for name, expression in CONSTRAINTS.items():
            defined = await connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE "
                    "conrelid='connector_usage_logs'::regclass AND conname=:name)"
                ),
                {"name": name},
            )
            if not defined:
                # 不改写旧的不可恢复事实；新写入仍必须满足约束。
                await connection.execute(
                    text(f"ALTER TABLE connector_usage_logs ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
                )
            invalid = await connection.scalar(
                text(f"SELECT count(*) FROM connector_usage_logs WHERE NOT ({expression})")
            )
            if invalid:
                logger.warning(f"连接器历史约束待处理: constraint={name}, invalid_rows={invalid}")
            else:
                await connection.execute(text(f"ALTER TABLE connector_usage_logs VALIDATE CONSTRAINT {name}"))
    await connection.execute(
        text(
            f"INSERT INTO {version_table}(domain,version,applied_at) "
            "VALUES ('business',:version,CURRENT_TIMESTAMP) ON CONFLICT(domain) "
            "DO UPDATE SET version=EXCLUDED.version,applied_at=EXCLUDED.applied_at"
        ),
        {"version": version},
    )
