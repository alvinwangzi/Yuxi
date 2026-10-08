"""连接器管理查询、可见性与配置/操作/凭据行的数据访问边界。"""

from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yuxi.permissions import connector_scope_matches
from yuxi.storage.postgres.models_business import (
    AgentRun,
    Connector,
    ConnectorCredential,
    ConnectorOperation,
    User,
    WorkflowRun,
    WorkflowStepRun,
)
from yuxi.utils.datetime_utils import utc_now

_DENY_SCOPE = {"access_level": "deny"}


class ConnectorRepository:
    """连接器的管理查询与配置维护；不解密凭据、不发起 HTTP。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_actor(self, uid: str, *, for_update: bool = False) -> User | None:
        """在最终授权事务内读取有效用户和真实部门。"""
        statement = select(User).where(User.uid == uid, User.is_deleted == 0)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(statement)

    async def get_agent_origin(self, uid: str, run_id: str, request_id: str | None = None) -> tuple:
        """核实当前 Run，沿持久恢复关系找到稳定的原始调用身份。"""
        current = await self.db.get(AgentRun, run_id)
        if (
            current is None
            or current.uid != uid
            or current.status != "running"
            or (request_id is not None and current.request_id != request_id)
        ):
            raise PermissionError("agent_run_not_owned")
        origin = current
        seen = set()
        while origin.run_type == "resume":
            if origin.id in seen or not origin.created_by_run_id:
                raise PermissionError("agent_resume_binding_invalid")
            seen.add(origin.id)
            parent = await self.db.get(AgentRun, origin.created_by_run_id)
            if parent is None or (parent.uid, parent.agent_slug, parent.conversation_thread_id) != (
                current.uid,
                current.agent_slug,
                current.conversation_thread_id,
            ):
                raise PermissionError("agent_resume_binding_invalid")
            origin = parent
        return current, origin

    async def lock_execution_owner(self, execution) -> None:
        """claim 前按父工作流→Agent 顺序锁 owner，与取消提交串行。"""
        if execution.workflow_run_id is not None:
            await self.db.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.id == execution.workflow_run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        if execution.consumer_type == "agent":
            await self.db.scalar(
                select(AgentRun)
                .where(AgentRun.id == (execution.current_agent_run_id or execution.agent_run_id))
                .with_for_update()
                .execution_options(populate_existing=True)
            )

    async def validate_execution_owner(self, execution, actor, operation=None) -> None:
        """副作用之前核实真实运行/步骤归属，业务参数不能提供身份。"""
        if execution.consumer_type == "admin_test":
            if actor is None or actor.role not in ("admin", "superadmin"):
                raise PermissionError("connector_admin_required")
            return
        if execution.consumer_type == "agent":
            current, origin = await self.get_agent_origin(
                execution.actor_uid, execution.current_agent_run_id or execution.agent_run_id
            )
            if (
                current.run_type == "subagent"
                and operation is not None
                and operation.operation_type == "write"
                and operation.approval_policy == "required"
            ):
                raise PermissionError("subagent_connector_approval_unavailable")
            if (origin.id, origin.request_id, origin.agent_slug) != (
                execution.agent_run_id,
                execution.agent_request_id,
                execution.agent_slug,
            ) or not execution.tool_call_id:
                raise PermissionError("agent_origin_binding_invalid")
        elif execution.consumer_type != "workflow":
            raise PermissionError("connector_consumer_invalid")
        if execution.consumer_type == "workflow" or execution.workflow_run_id is not None:
            run = await self.db.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.id == execution.workflow_run_id)
                .execution_options(populate_existing=True)
            )
            step = await self.db.scalar(
                select(WorkflowStepRun).where(
                    WorkflowStepRun.workflow_run_id == execution.workflow_run_id,
                    WorkflowStepRun.step_id == execution.step_id,
                )
            )
            if (
                run is None
                or step is None
                or run.created_by != execution.actor_uid
                or run.workflow_id != execution.workflow_id
                or (step.step_execution_id != execution.step_execution_id)
                or run.status in ("cancelled", "failed", "completed")
            ):
                raise PermissionError("workflow_execution_not_owned")
            if execution.consumer_type == "workflow" and (
                run.status != "running" or run.owner_attempt != execution.workflow_owner_attempt
            ):
                raise PermissionError("workflow_owner_lost")
            if execution.consumer_type == "agent" and step.agent_request_id != execution.agent_request_id:
                raise PermissionError("workflow_agent_binding_invalid")

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
        actor = await self.get_active_actor(uid)
        if actor is None:
            return []
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
                if op.operation_type == "read" and connector_scope_matches(actor, c.read_scope):
                    usable.append(c)
                    break
                if op.operation_type == "write" and connector_scope_matches(actor, c.write_scope):
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
        actor = await self.get_active_actor(uid)
        result = []
        for op in connector.operations or []:
            if not op.enabled:
                continue
            if operation_type and op.operation_type != operation_type:
                continue
            scope = connector.read_scope if op.operation_type == "read" else connector.write_scope
            if connector_scope_matches(actor, scope):
                result.append(op)
        return result

    async def get_by_id(self, connector_id: int, *, for_update: bool = False) -> Connector | None:
        """按稳定身份读取连接器，必要时锁定授权事实。"""
        statement = select(Connector).where(Connector.id == connector_id)
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(statement)

    async def get_by_slug(
        self, slug: str, *, for_update: bool = False, include_deleted: bool = False
    ) -> Connector | None:
        """管理写入刷新并锁定版本，创建检查包含删除 tombstone。"""
        statement = select(Connector).where(Connector.slug == slug)
        if not include_deleted:
            statement = statement.where(Connector.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        result = await self.db.execute(
            statement.options(selectinload(Connector.credentials), selectinload(Connector.operations))
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
        enabled: bool = True,
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
            enabled=enabled,
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
        clear_description: bool = False,
    ) -> Connector:
        if name is not None:
            connector.name = name
        if description is not None or clear_description:
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
        connector.updated_at = utc_now()
        await self.db.flush()
        return connector

    async def soft_delete(self, connector: Connector, *, updated_by: str | None = None) -> Connector:
        """保留 tombstone/调用历史，删除不再允许消费的活凭据。"""
        await self.db.execute(delete(ConnectorCredential).where(ConnectorCredential.connector_id == connector.id))
        connector.enabled = False
        connector.deleted_at = utc_now()
        connector.updated_by = updated_by
        connector.updated_at = utc_now()
        await self.db.flush()
        return connector

    async def get_operation(
        self, connector_id: int, slug: str, *, for_update: bool = False
    ) -> ConnectorOperation | None:
        """读取操作版本，dispatch 与审批可锁定同一事实。"""
        statement = select(ConnectorOperation).where(
            ConnectorOperation.connector_id == connector_id,
            ConnectorOperation.slug == slug,
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(statement)

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
        enabled: bool = True,
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
            enabled=enabled,
        )
        self.db.add(op)
        await self.db.flush()
        await self.increment_connector_revision(op.connector_id)
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
        operation.updated_at = utc_now()
        await self.db.flush()
        await self.increment_connector_revision(operation.connector_id)
        return operation

    async def disable_operation(self, operation: ConnectorOperation) -> ConnectorOperation:
        operation.enabled = False
        operation.revision += 1
        operation.updated_at = utc_now()
        await self.db.flush()
        await self.increment_connector_revision(operation.connector_id)
        return operation

    async def patch_operation(self, operation: ConnectorOperation, changes: dict) -> ConnectorOperation:
        """显式提交的 nullable 字段可以清空，缺省字段保留原值。"""
        for key, value in changes.items():
            setattr(operation, key, value)
        operation.revision += 1
        operation.updated_at = utc_now()
        await self.db.flush()
        await self.increment_connector_revision(operation.connector_id)
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
            existing.updated_at = utc_now()
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

    async def increment_connector_revision(self, connector_id: int) -> None:
        """同一管理事务内推进连接器版本，使旧快照和批准失效。"""
        await self.db.execute(
            update(Connector)
            .where(Connector.id == connector_id)
            .values(
                revision=Connector.revision + 1,
                updated_at=utc_now(),
            )
        )
