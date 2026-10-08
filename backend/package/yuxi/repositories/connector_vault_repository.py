"""保险库探针与轮换使用的有界持久化查询。"""

from sqlalchemy import func, or_, select, union_all

from yuxi.storage.postgres.models_business import Connector, ConnectorCredential, ConnectorUsageLog


class ConnectorVaultRepository:
    """查询 key 覆盖和每列/每 key 的解密样本，不读取业务明文。"""

    def __init__(self, db):
        self.db = db

    async def coverage(self) -> tuple[bool, set[str | None]]:
        """所有保留密文都参与 key 覆盖，包括终态历史结果。"""
        enabled = await self.db.scalar(
            select(Connector.id)
            .where(
                Connector.enabled.is_(True),
                Connector.deleted_at.is_(None),
            )
            .limit(1)
        )
        retained = or_(
            ConnectorUsageLog.params_ciphertext.is_not(None),
            ConnectorUsageLog.execution_snapshot_ciphertext.is_not(None),
            ConnectorUsageLog.result_ciphertext.is_not(None),
        )
        statement = union_all(
            select(ConnectorCredential.key_id), select(ConnectorUsageLog.key_id).where(retained)
        ).subquery()
        keys = set((await self.db.scalars(select(statement.c.key_id).distinct().limit(65))).all())
        return enabled is not None or bool(keys), keys

    async def decryption_samples(self) -> list[tuple[str | None, bytes]]:
        """每个存储列和 key_id 只取一个样本，探针成本有明确上界。"""
        samples = []
        for model, column in [
            (ConnectorCredential, ConnectorCredential.credential_value),
            (ConnectorUsageLog, ConnectorUsageLog.params_ciphertext),
            (ConnectorUsageLog, ConnectorUsageLog.execution_snapshot_ciphertext),
            (ConnectorUsageLog, ConnectorUsageLog.result_ciphertext),
        ]:
            ranked = select(
                model.key_id,
                column.label("ciphertext"),
                func.row_number().over(partition_by=model.key_id, order_by=model.id).label("position"),
            )
            ranked = ranked.where(column.is_not(None)).subquery()
            samples.extend(
                (
                    await self.db.execute(
                        select(ranked.c.key_id, ranked.c.ciphertext)
                        .where(
                            ranked.c.position == 1,
                        )
                        .limit(65)
                    )
                ).all()
            )
        return samples

    async def rotation_batch(self, model, *, current_key_id, cursor, batch_size, for_update):
        """keyset 避免更新谓词后 offset 跳行，行锁与发送/finalize 串行。"""
        statement = select(model).where(or_(model.key_id != current_key_id, model.key_id.is_(None)))
        if model is ConnectorUsageLog:
            statement = statement.where(
                or_(
                    model.params_ciphertext.is_not(None),
                    model.execution_snapshot_ciphertext.is_not(None),
                    model.result_ciphertext.is_not(None),
                )
            )
        if cursor is not None:
            statement = statement.where(model.id > cursor)
        statement = statement.order_by(model.id).limit(batch_size)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return list((await self.db.scalars(statement)).all())

    async def key_distribution(self) -> dict:
        """删除旧 key 前回读所有保留字段所使用的 key_id。"""
        distributions = {}
        for name, model in [("credentials_by_key", ConnectorCredential), ("invocations_by_key", ConnectorUsageLog)]:
            statement = select(model.key_id, func.count()).group_by(model.key_id)
            if model is ConnectorUsageLog:
                statement = statement.where(
                    or_(
                        model.params_ciphertext.is_not(None),
                        model.execution_snapshot_ciphertext.is_not(None),
                        model.result_ciphertext.is_not(None),
                    )
                )
            distributions[name] = dict((await self.db.execute(statement)).all())
        return distributions
