"""连接器管理查询、可见性与配置/操作/凭据行的数据访问边界。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yuxi.storage.postgres.models_business import (
    Connector,
    ConnectorCredential,
    ConnectorOperation,
)
from yuxi.utils.datetime_utils import utc_now_naive


_DENY_SCOPE = {"access_level": "deny"}


def _scope_allows_user(scope: dict | None, uid: str, department_ids: list[str] | None) -> bool:
    """沿用 yuxi.permissions 的 scope 结构判断用户是否命中。"""
    if not scope:
        return False
    level = scope.get("access_level", "deny")
    if level == "deny":
        return False
    if level == "global":
        return True
    if level == "user":
        allowed_uids = set(scope.get("user_uids") or [])
        if uid in allowed_uids:
            return True
        allowed_depts = set(scope.get("department_ids") or [])
        if department_ids and allowed_depts & set(department_ids):
            return True
    return False


class ConnectorRepository:
    """连接器的管理查询与配置维护；不解密凭据、不发起 HTTP。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self, *, include_deleted: bool = False) -> list[Connector]:
        stmt = select(Connector).order_by(Connector.created_at.desc())
        if not include_deleted:
            stmt = stmt.where(Connector.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_usable(
        self,
        uid: str,
        department_ids: list[str] | None = None,
    ) -> list[Connector]:
        """返回用户至少有一个可见操作的 enabled、未删除连接器。"""
        stmt = (
            select(Connector)
            .where(Connector.enabled.is_(True), Connector.deleted_at.is_(None))
            .order_by(Connector.created_at.desc())
        )
        result = await self.db.execute(stmt)
        connectors = list(result.scalars().all())

        usable = []
        for c in connectors:
            ops = [op for op in (c.operations or []) if op.enabled]
            for op in ops:
                if op.operation_type == "read" and _scope_allows_user(c.read_scope, uid, department_ids):
                    usable.append(c)
                    break
                if op.operation_type == "write" and _scope_allows_user(c.write_scope, uid, department_ids):
                    usable.append(c)
                    break
        return usable

    async def list_usable_operations(
        self,
        connector: Connector,
        uid: str,
        department_ids: list[str] | None = None,
        operation_type: str | None = None,
    ) -> list[ConnectorOperation]:
        """按 read/write 权限过滤操作。"""
        result = []
        for op in (connector.operations or []):
            if not op.enabled:
                continue
            if operation_type and op.operation_type != operation_type:
                continue
            scope = connector.read_scope if op.operation_type == "read" else connector.write_scope
            if _scope_allows_user(scope, uid, department_ids):
                result.append(op)
        return result

    async def get_by_id(self, connector_id: int) -> Connector | None:
        return await self.db.get(Connector, connector_id)

    async def get_by_slug(self, slug: str) -> Connector | None:
        result = await self.db.execute(
            select(Connector)
            .where(Connector.slug == slug, Connector.deleted_at.is_(None))
            .options(selectinload(Connector.credentials), selectinload(Connector.operations))
        )
        return result.scalar_one_or_none()

    async def get_by_slug_for_execution(self, slug: str) -> Connector | None:
        """执行路径使用：加载凭据行（密文）和操作。"""
        result = await self.db.execute(
            select(Connector)
            .where(Connector.slug == slug, Connector.deleted_at.is_(None))
            .options(selectinload(Connector.credentials), selectinload(Connector.operations))
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        slug: str,
        name: str,
        connector_type: str,
        description: str | None = None,
        config: dict | None = None,
        read_scope: dict | None = None,
        write_scope: dict | None = None,
        created_by: str | None = None,
    ) -> Connector:
        connector = Connector(
            slug=slug,
            name=name,
            connector_type=connector_type,
            description=description,
            config=config or {},
            read_scope=read_scope or _DENY_SCOPE.copy(),
            write_scope=write_scope or _DENY_SCOPE.copy(),
            created_by=created_by,
            updated_by=created_by,
        )
        self.db.add(connector)
        await self.db.flush()
        return connector

    async def update_config(
        self,
        connector: Connector,
        *,
        name: str | None = None,
        description: str | None = None,
        config: dict | None = None,
        read_scope: dict | None = None,
        write_scope: dict | None = None,
        enabled: bool | None = None,
        updated_by: str | None = None,
    ) -> Connector:
        if name is not None:
            connector.name = name
        if description is not None:
            connector.description = description
        if config is not None:
            connector.config = config
        if read_scope is not None:
            connector.read_scope = read_scope
        if write_scope is not None:
            connector.write_scope = write_scope
        if enabled is not None:
            connector.enabled = enabled
        connector.revision += 1
        connector.updated_by = updated_by
        connector.updated_at = utc_now_naive()
        await self.db.flush()
        return connector

    async def soft_delete(self, connector: Connector, *, updated_by: str | None = None) -> Connector:
        connector.enabled = False
        connector.deleted_at = utc_now_naive()
        connector.updated_by = updated_by
        connector.updated_at = utc_now_naive()
        await self.db.flush()
        return connector

    async def get_operation(self, connector_id: int, slug: str) -> ConnectorOperation | None:
        result = await self.db.execute(
            select(ConnectorOperation).where(
                ConnectorOperation.connector_id == connector_id,
                ConnectorOperation.slug == slug,
            )
        )
        return result.scalar_one_or_none()

    async def create_operation(
        self,
        *,
        connector_id: int,
        slug: str,
        name: str,
        operation_type: str,
        http_method: str = "GET",
        endpoint_template: str = "/",
        request_schema: dict | None = None,
        response_type: str = "json",
        approval_policy: str = "required",
        description: str | None = None,
        query_template: dict | None = None,
        body_template: dict | None = None,
        response_mapping: dict | None = None,
        retry_policy: dict | None = None,
        remote_idempotency: dict | None = None,
    ) -> ConnectorOperation:
        op = ConnectorOperation(
            connector_id=connector_id,
            slug=slug,
            name=name,
            operation_type=operation_type,
            http_method=http_method,
            endpoint_template=endpoint_template,
            request_schema=request_schema or {},
            response_type=response_type,
            approval_policy=approval_policy,
            description=description,
            query_template=query_template,
            body_template=body_template,
            response_mapping=response_mapping,
            retry_policy=retry_policy,
            remote_idempotency=remote_idempotency,
        )
        self.db.add(op)
        await self.db.flush()
        await self._increment_connector_revision(op.connector_id)
        return op

    async def update_operation(
        self,
        operation: ConnectorOperation,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        http_method: str | None = None,
        endpoint_template: str | None = None,
        request_schema: dict | None = None,
        response_type: str | None = None,
        approval_policy: str | None = None,
        query_template: dict | None = None,
        body_template: dict | None = None,
        response_mapping: dict | None = None,
        retry_policy: dict | None = None,
        remote_idempotency: dict | None = None,
    ) -> ConnectorOperation:
        if name is not None:
            operation.name = name
        if description is not None:
            operation.description = description
        if enabled is not None:
            operation.enabled = enabled
        if http_method is not None:
            operation.http_method = http_method
        if endpoint_template is not None:
            operation.endpoint_template = endpoint_template
        if request_schema is not None:
            operation.request_schema = request_schema
        if response_type is not None:
            operation.response_type = response_type
        if approval_policy is not None:
            operation.approval_policy = approval_policy
        if query_template is not None:
            operation.query_template = query_template
        if body_template is not None:
            operation.body_template = body_template
        if response_mapping is not None:
            operation.response_mapping = response_mapping
        if retry_policy is not None:
            operation.retry_policy = retry_policy
        if remote_idempotency is not None:
            operation.remote_idempotency = remote_idempotency
        operation.revision += 1
        operation.updated_at = utc_now_naive()
        await self.db.flush()
        await self._increment_connector_revision(operation.connector_id)
        return operation

    async def disable_operation(self, operation: ConnectorOperation) -> ConnectorOperation:
        operation.enabled = False
        operation.updated_at = utc_now_naive()
        await self.db.flush()
        await self._increment_connector_revision(operation.connector_id)
        return operation

    async def list_credentials(self, connector_id: int) -> list[ConnectorCredential]:
        result = await self.db.execute(
            select(ConnectorCredential).where(ConnectorCredential.connector_id == connector_id)
        )
        return list(result.scalars().all())

    async def get_credential(self, connector_id: int, key: str) -> ConnectorCredential | None:
        result = await self.db.execute(
            select(ConnectorCredential).where(
                ConnectorCredential.connector_id == connector_id,
                ConnectorCredential.credential_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_credential(
        self,
        connector_id: int,
        key: str,
        ciphertext: bytes,
        key_id: str | None,
    ) -> ConnectorCredential:
        existing = await self.get_credential(connector_id, key)
        if existing:
            existing.credential_value = ciphertext
            existing.key_id = key_id
            existing.updated_at = utc_now_naive()
            await self.db.flush()
            return existing
        cred = ConnectorCredential(
            connector_id=connector_id,
            credential_key=key,
            credential_value=ciphertext,
            key_id=key_id,
        )
        self.db.add(cred)
        await self.db.flush()
        return cred

    async def delete_credentials(self, connector_id: int, keys: list[str]) -> int:
        if not keys:
            return 0
        result = await self.db.execute(
            select(ConnectorCredential).where(
                ConnectorCredential.connector_id == connector_id,
                ConnectorCredential.credential_key.in_(keys),
            )
        )
        rows = list(result.scalars().all())
        for row in rows:
            await self.db.delete(row)
        await self.db.flush()
        return len(rows)

    async def get_category_counts(self) -> dict[str, int]:
        result = await self.db.execute(
            select(Connector.connector_type, func.count(Connector.id))
            .where(Connector.deleted_at.is_(None))
            .group_by(Connector.connector_type)
        )
        return {str(row.connector_type): row.count for row in result}

    async def _increment_connector_revision(self, connector_id: int) -> None:
        await self.db.execute(
            update(Connector)
            .where(Connector.id == connector_id)
            .values(
                revision=Connector.revision + 1,
                updated_at=utc_now_naive(),
            )
        )
