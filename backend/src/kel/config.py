"""运行配置与模型密钥。密钥只进系统钥匙串，不进 SQLite/日志/事件。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

KEYRING_SERVICE = "com.maieutic.kel"


@dataclass
class Settings:
    data_dir: Path
    log_level: str = "info"
    host: str = "127.0.0.1"
    port: int = 0
    session_token: str = ""
    offline: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kel.sqlite3"

    @property
    def checkpoint_path(self) -> Path:
        return self.data_dir / "checkpoints.sqlite3"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(
            os.environ.get("KEL_DATA_DIR", Path.home() / ".maieutic-agent")
        ).expanduser()
        return cls(
            data_dir=data_dir,
            log_level=os.environ.get("KEL_LOG_LEVEL", "info"),
            port=int(os.environ.get("KEL_PORT", "0")),
            session_token=os.environ.get("KEL_SESSION_TOKEN", ""),
            offline=os.environ.get("KEL_OFFLINE", "") == "1",
        )


@dataclass
class ModelProfile:
    provider: str = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


def get_api_key(profile_id: str = "default") -> str | None:
    """从钥匙串读取密钥。环境变量仅用于开发与测试。"""
    env_key = os.environ.get("KEL_API_KEY")
    if env_key:
        return env_key
    try:
        import keyring
    except Exception:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, profile_id)
    except Exception:
        return None


def set_api_key(key: str, profile_id: str = "default") -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, profile_id, key)


def delete_api_key(profile_id: str = "default") -> None:
    try:
        import keyring

        keyring.delete_password(KEYRING_SERVICE, profile_id)
    except Exception:
        return
