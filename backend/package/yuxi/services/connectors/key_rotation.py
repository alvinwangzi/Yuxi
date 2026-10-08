"""保留材料的分批事务轮换；不会输出明文或修改调用业务状态。"""

from yuxi.repositories.connector_vault_repository import ConnectorVaultRepository
from yuxi.services.connectors.credential_vault import CredentialVaultError
from yuxi.storage.postgres.models_business import ConnectorCredential, ConnectorUsageLog


async def rotate_retained_materials(*, session_factory, vault, dry_run, batch_size=100) -> dict:
    """一批一事务、整行同 key、失败可重跑，终态结果也参与轮换。"""
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError("batch_size 必须在 1~100 之间")
    counts = {"credentials": 0, "invocations": 0}
    for name, model, fields in [
        ("credentials", ConnectorCredential, ("credential_value",)),
        ("invocations", ConnectorUsageLog, ("params_ciphertext", "execution_snapshot_ciphertext", "result_ciphertext")),
    ]:
        cursor = None
        while True:
            async with session_factory() as db:
                rows = await ConnectorVaultRepository(db).rotation_batch(
                    model,
                    current_key_id=vault.current_key_id,
                    cursor=cursor,
                    batch_size=batch_size,
                    for_update=not dry_run,
                )
                if not rows:
                    break
                for row in rows:
                    # 先完整解密与重新加密所有列；任何一列失败，当前批次不写入。
                    replacements = {}
                    for field in fields:
                        value = getattr(row, field)
                        if value is not None:
                            plaintext = vault.decrypt(value, row.key_id)
                            replacements[field] = vault.encrypt(plaintext).ciphertext
                    if not replacements:
                        raise CredentialVaultError("保留密文的 key 绑定不可轮换")
                    if not dry_run:
                        for field, ciphertext in replacements.items():
                            setattr(row, field, ciphertext)
                        row.key_id = vault.current_key_id
                    counts[name] += 1
                cursor = rows[-1].id
    return counts


async def verify_retained_keys(*, session_factory, vault) -> dict:
    """回读 key 分布与受控解密，不用处理计数替代轮换验证。"""
    from yuxi.services.connectors.vault_readiness import check_connector_vault

    async with session_factory() as db:
        distribution = await ConnectorVaultRepository(db).key_distribution()
    readiness = await check_connector_vault(session_factory=session_factory, vault=vault)
    if readiness["status"] != "ok":
        raise CredentialVaultError("轮换回读未通过 key 覆盖或解密验证")
    return distribution
