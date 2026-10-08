"""Bash 初始化 guard 属于根脚本原生流程，不依赖 API 容器的仓库布局。"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet


class ConnectorInitializationTests(unittest.TestCase):
    """仅操作本例临时环境，检查有效密钥、幂等与半配对拒绝。"""

    def test_fernet_key_is_valid_and_existing_configuration_is_preserved(self):
        """初始化入口在完整仓库或只读脚本挂载中同样可以执行。"""
        with tempfile.TemporaryDirectory(
            prefix="yuxi-connector-init-"
        ) as case_directory:
            script = Path(__file__).with_name("init.sh")
            local_script = Path(case_directory) / "init.sh"
            local_script.write_text(
                script.read_text(encoding="utf-8"), encoding="utf-8"
            )
            env_file = Path(case_directory) / ".env"
            env_file.write_text(
                "CREDENTIAL_ENCRYPTION_KEY=\nCREDENTIAL_ENCRYPTION_KEY_ID=\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    shutil.which("bash"),
                    str(local_script),
                    "--ensure-connector-vault-env",
                ],
                cwd=Path(case_directory),
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            first = env_file.read_bytes()
            values = dict(
                line.split("=", 1)
                for line in first.decode().splitlines()
                if "=" in line
            )
            key = values["CREDENTIAL_ENCRYPTION_KEY"]
            assert key not in result.stdout
            cipher = Fernet(key.encode())
            assert cipher.decrypt(cipher.encrypt(b"fixture")) == b"fixture"
            result = subprocess.run(
                [
                    shutil.which("bash"),
                    str(local_script),
                    "--ensure-connector-vault-env",
                ],
                cwd=Path(case_directory),
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0 and env_file.read_bytes() == first
            half = b"CREDENTIAL_ENCRYPTION_KEY=existing-do-not-replace\nCREDENTIAL_ENCRYPTION_KEY_ID=\n"
            env_file.write_bytes(half)
            result = subprocess.run(
                [
                    shutil.which("bash"),
                    str(local_script),
                    "--ensure-connector-vault-env",
                ],
                cwd=Path(case_directory),
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0 and env_file.read_bytes() == half
            assert "existing-do-not-replace" not in result.stdout + result.stderr


if __name__ == "__main__":
    unittest.main()
