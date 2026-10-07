"""凭据加密保险库 — Fernet 对称加密与密钥轮换。

密钥通过环境变量注入，不在模块 import 时强制创建实例；
列表/类型发现可以说明 unavailable，执行和凭据写入返回明确错误。
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from yuxi.utils import logger

ENCRYPTION_KEY_ENV = "CREDENTIAL_ENCRYPTION_KEY"
ENCRYPTION_KEY_ID_ENV = "CREDENTIAL_ENCRYPTION_KEY_ID"


class CredentialVaultError(Exception):
    """凭据保险库操作失败。"""


class CredentialDecryptionError(CredentialVaultError):
    """解密失败：密钥不匹配或数据损坏。"""


@dataclass(frozen=True)
class EncryptedValue:
    """加密结果，携带 key_id 供轮换时识别。"""

    ciphertext: bytes
    key_id: str


class CredentialVault:
    """Fernet 凭据加解密，支持多 key ring 轮换。

    ``current_key_id`` 标识当前写密钥；``old_keys`` 为受控旧 key ring，
    仅用于解密历史数据，不用于新加密。
    """

    def __init__(
        self,
        *,
        current_key: Fernet,
        current_key_id: str,
        old_keys: dict[str, Fernet] | None = None,
    ):
        if not current_key_id:
            raise CredentialVaultError("current_key_id 不能为空")
        self._current_key = current_key
        self._current_key_id = current_key_id
        self._old_keys = dict(old_keys or {})

    @classmethod
    def from_environment(cls) -> CredentialVault | None:
        """从环境变量构造保险库；未配置时返回 None。"""
        raw_key = os.getenv(ENCRYPTION_KEY_ENV, "").strip()
        key_id = os.getenv(ENCRYPTION_KEY_ID_ENV, "").strip()
        if not raw_key and not key_id:
            return None
        if not raw_key or not key_id:
            raise CredentialVaultError(
                f"{ENCRYPTION_KEY_ENV} 与 {ENCRYPTION_KEY_ID_ENV} 必须同时配置"
            )
        fernet = _build_fernet(raw_key)
        return cls(current_key=fernet, current_key_id=key_id)

    @property
    def current_key_id(self) -> str:
        return self._current_key_id

    def encrypt(self, plaintext: bytes) -> EncryptedValue:
        """加密明文，返回密文和当前 key_id。"""
        if not plaintext:
            raise CredentialVaultError("明文不能为空")
        ciphertext = self._current_key.encrypt(plaintext)
        return EncryptedValue(ciphertext=ciphertext, key_id=self._current_key_id)

    def decrypt(self, ciphertext: bytes, key_id: str) -> bytes:
        """按 key_id 选择密钥解密密文。"""
        if not ciphertext:
            raise CredentialDecryptionError("密文不能为空")
        if not key_id:
            raise CredentialDecryptionError("key_id 不能为空")
        if key_id == self._current_key_id:
            fernet = self._current_key
        elif key_id in self._old_keys:
            fernet = self._old_keys[key_id]
        else:
            raise CredentialDecryptionError(f"未知 key_id: {key_id}")
        try:
            return fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise CredentialDecryptionError(f"解密失败 (key_id={key_id})") from exc


def _build_fernet(raw_key: str) -> Fernet:
    """从环境变量值构造 Fernet 实例。"""
    try:
        key_bytes = raw_key.encode("utf-8")
        if len(key_bytes) == 32:
            fernet_key = base64.urlsafe_b64encode(key_bytes)
            return Fernet(fernet_key)
        return Fernet(key_bytes)
    except Exception as exc:
        raise CredentialVaultError(f"无效的加密密钥格式: {exc}") from exc


def generate_key_bytes() -> str:
    """生成新的 32 字节随机密钥，返回 base64 编码字符串。"""
    return base64.urlsafe_b64encode(Fernet.generate_key()).decode("utf-8")


def ensure_vault_available(vault: CredentialVault | None) -> CredentialVault:
    """校验保险库已配置，未配置时抛出明确错误。"""
    if vault is None:
        raise CredentialVaultError(
            f"凭据保险库未配置；请设置 {ENCRYPTION_KEY_ENV} 和 {ENCRYPTION_KEY_ID_ENV}"
        )
    return vault
