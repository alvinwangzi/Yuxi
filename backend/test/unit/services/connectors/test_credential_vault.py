"""凭据保险库单元测试。"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from yuxi.services.connectors.credential_vault import (
    CredentialDecryptionError,
    CredentialVault,
    CredentialVaultError,
    EncryptedValue,
    _build_fernet,
    ensure_vault_available,
    generate_key_bytes,
)


class TestCredentialVault:
    """CredentialVault 加解密与密钥轮换测试。"""

    @pytest.fixture
    def vault(self):
        key = Fernet.generate_key()
        return CredentialVault(current_key=Fernet(key), current_key_id="key-1")

    def test_encrypt_and_decrypt_roundtrip(self, vault):
        plaintext = b"my-secret-token"
        encrypted = vault.encrypt(plaintext)
        assert isinstance(encrypted, EncryptedValue)
        assert encrypted.ciphertext != plaintext
        assert encrypted.key_id == "key-1"
        decrypted = vault.decrypt(encrypted.ciphertext, encrypted.key_id)
        assert decrypted == plaintext

    def test_encrypt_empty_plaintext_raises(self, vault):
        with pytest.raises(CredentialVaultError, match="不能为空"):
            vault.encrypt(b"")

    def test_decrypt_empty_ciphertext_raises(self, vault):
        with pytest.raises(CredentialDecryptionError, match="不能为空"):
            vault.decrypt(b"", "key-1")

    def test_decrypt_empty_key_id_raises(self, vault):
        encrypted = vault.encrypt(b"data")
        with pytest.raises(CredentialDecryptionError, match="key_id"):
            vault.decrypt(encrypted.ciphertext, "")

    def test_decrypt_unknown_key_id_raises(self, vault):
        encrypted = vault.encrypt(b"data")
        with pytest.raises(CredentialDecryptionError, match="未知 key_id"):
            vault.decrypt(encrypted.ciphertext, "unknown-key")

    def test_decrypt_with_wrong_key_raises(self, vault):
        encrypted = vault.encrypt(b"secret")
        wrong_key = Fernet(Fernet.generate_key())
        wrong_vault = CredentialVault(
            current_key=wrong_key,
            current_key_id="key-2",
            old_keys={"key-1": vault._current_key},
        )
        corrupted = EncryptedValue(ciphertext=b"garbage", key_id="key-1")
        with pytest.raises(CredentialDecryptionError, match="解密失败"):
            wrong_vault.decrypt(corrupted.ciphertext, "key-1")

    def test_key_rotation_old_key_can_still_decrypt(self):
        old_key = Fernet.generate_key()
        old_vault = CredentialVault(current_key=Fernet(old_key), current_key_id="old-1")
        encrypted = old_vault.encrypt(b"rotatable-secret")

        new_key = Fernet.generate_key()
        rotated_vault = CredentialVault(
            current_key=Fernet(new_key),
            current_key_id="new-1",
            old_keys={"old-1": Fernet(old_key)},
        )
        decrypted = rotated_vault.decrypt(encrypted.ciphertext, "old-1")
        assert decrypted == b"rotatable-secret"

    def test_new_encryption_uses_current_key(self):
        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()
        vault = CredentialVault(
            current_key=Fernet(new_key),
            current_key_id="new-1",
            old_keys={"old-1": Fernet(old_key)},
        )
        encrypted = vault.encrypt(b"fresh")
        assert encrypted.key_id == "new-1"

    def test_empty_key_id_in_constructor_raises(self):
        with pytest.raises(CredentialVaultError, match="current_key_id"):
            CredentialVault(current_key=Fernet(Fernet.generate_key()), current_key_id="")


class TestBuildFernet:
    """Fernet 密钥构造测试。"""

    def test_32_byte_raw_key_produces_valid_fernet(self):
        raw = b"a" * 32
        fernet = _build_fernet(raw.decode("ascii"))
        data = fernet.encrypt(b"test")
        assert fernet.decrypt(data) == b"test"

    def test_base64_key_also_works(self):
        b64_key = Fernet.generate_key().decode("utf-8")
        fernet = _build_fernet(b64_key)
        data = fernet.encrypt(b"test")
        assert fernet.decrypt(data) == b"test"

    def test_invalid_key_raises(self):
        with pytest.raises(CredentialVaultError, match="无效的加密密钥"):
            _build_fernet("not-a-valid-key-at-all")


class TestFromEnvironment:
    """环境变量构造保险库测试。"""

    def test_no_env_vars_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CREDENTIAL_ENCRYPTION_KEY", None)
            os.environ.pop("CREDENTIAL_ENCRYPTION_KEY_ID", None)
            result = CredentialVault.from_environment()
            assert result is None

    def test_both_env_vars_present_creates_vault(self):
        key = Fernet.generate_key().decode("utf-8")
        with patch.dict(os.environ, {
            "CREDENTIAL_ENCRYPTION_KEY": key,
            "CREDENTIAL_ENCRYPTION_KEY_ID": "env-key-1",
        }):
            vault = CredentialVault.from_environment()
            assert vault is not None
            assert vault.current_key_id == "env-key-1"

    def test_partial_env_raises(self):
        with patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "something"}, clear=True):
            os.environ.pop("CREDENTIAL_ENCRYPTION_KEY_ID", None)
            with pytest.raises(CredentialVaultError, match="同时配置"):
                CredentialVault.from_environment()


class TestGenerateKeyBytes:
    def test_generates_valid_base64_key(self):
        key_str = generate_key_bytes()
        assert isinstance(key_str, str)
        assert len(key_str) > 20

    def test_generated_key_is_usable(self):
        key_str = generate_key_bytes()
        import base64
        raw = base64.urlsafe_b64decode(key_str.encode("utf-8"))
        fernet = Fernet(raw)
        data = fernet.encrypt(b"hello")
        assert fernet.decrypt(data) == b"hello"


class TestEnsureVaultAvailable:
    def test_none_raises(self):
        with pytest.raises(CredentialVaultError, match="未配置"):
            ensure_vault_available(None)

    def test_returns_vault_when_present(self):
        vault = CredentialVault(current_key=Fernet(Fernet.generate_key()), current_key_id="k")
        assert ensure_vault_available(vault) is vault
