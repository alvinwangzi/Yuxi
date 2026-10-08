"""连接器能力与 required readiness 共用的保险库检查。"""

import asyncio
import time

from yuxi.repositories.connector_vault_repository import ConnectorVaultRepository
from yuxi.services.connectors.credential_vault import CredentialVaultError

_cache = {}
_inflight = {}


async def get_connector_vault_status() -> dict:
    """有界探针短缓存，配置更换立即使旧 key ring 缓存失效。"""
    from yuxi.services.connectors.factory import get_connector_service_factory

    factory = get_connector_service_factory()
    try:
        vault = factory.vault_provider()
    except CredentialVaultError:
        vault = None
        config_invalid = True
    else:
        config_invalid = False
    key = (factory.session_context_factory, vault.cache_identity if vault else None, config_invalid)
    now = time.monotonic()
    if key in _cache and _cache[key][0] > now:
        return dict(_cache[key][1])
    if key not in _inflight:
        _inflight[key] = asyncio.create_task(
            check_connector_vault(
                session_factory=factory.session_context_factory,
                vault=vault,
                config_invalid=config_invalid,
            )
        )
    task = _inflight[key]
    try:
        result = await asyncio.shield(task)
    finally:
        if task.done():
            _inflight.pop(key, None)
    _cache.clear()
    _cache[key] = (time.monotonic() + 30, result)
    return dict(result)


async def check_connector_vault(*, session_factory, vault, config_invalid=False) -> dict:
    """以持久记录决定 required，并检查 key 覆盖及真实受控解密。"""
    async with session_factory() as db:
        repository = ConnectorVaultRepository(db)
        required, key_ids = await repository.coverage()
        if vault is None:
            return {
                "status": "error" if required else "unavailable",
                "required": required,
                "code": "vault_config_invalid" if config_invalid else "vault_unconfigured",
            }
        if len(key_ids) > 64 or not key_ids.issubset(vault.supported_key_ids):
            return {"status": "error", "required": True, "code": "vault_key_missing"}
        for key_id, ciphertext in await repository.decryption_samples():
            try:
                vault.decrypt(ciphertext, key_id)
            except CredentialVaultError:
                return {"status": "error", "required": True, "code": "vault_decryption_failed"}
        return {"status": "ok", "required": required}


async def require_connector_vault_ready() -> dict:
    """启动时有必需加密业务便显式拒绝缺 key 或不可解密装配。"""
    status = await get_connector_vault_status()
    if status["required"] and status["status"] != "ok":
        raise CredentialVaultError(status.get("code", "vault_unavailable"))
    return status
