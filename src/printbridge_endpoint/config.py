from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_DIR_NAME = "PrintBridge Endpoint"
CONFIG_FILE_NAME = "config.json"
KEYRING_SERVICE = "printbridge-endpoint"
KEYRING_USERNAME = "client-token"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file_enabled: bool = True


@dataclass
class EndpointConfig:
    server_url: str = ""
    selected_printer: str = ""
    polling_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 30
    start_polling_on_launch: bool = False
    start_at_login: bool = False
    logging: LoggingConfig = field(default_factory=LoggingConfig)


class ConfigError(ValueError):
    pass


class ConfigStore:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or default_config_path()

    def load(self) -> EndpointConfig:
        if not self.config_path.exists():
            return EndpointConfig()

        with self.config_path.open("r", encoding="utf-8") as file:
            raw = json.load(file)

        if not isinstance(raw, dict):
            raise ConfigError("Configuration file must contain a JSON object.")

        logging_raw = raw.get("logging", {})
        if not isinstance(logging_raw, dict):
            logging_raw = {}

        return EndpointConfig(
            server_url=str(raw.get("server_url", "")),
            selected_printer=str(raw.get("selected_printer", "")),
            polling_interval_seconds=_positive_int(raw.get("polling_interval_seconds", 5), 5),
            heartbeat_interval_seconds=_positive_int(raw.get("heartbeat_interval_seconds", 30), 30),
            start_polling_on_launch=bool(raw.get("start_polling_on_launch", False)),
            start_at_login=bool(raw.get("start_at_login", False)),
            logging=LoggingConfig(
                level=str(logging_raw.get("level", "INFO")),
                file_enabled=bool(logging_raw.get("file_enabled", True)),
            ),
        )

    def save(self, config: EndpointConfig) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(config)
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True)
            file.write("\n")


class ClientTokenStore:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or default_config_dir()

    def get(self) -> str:
        keyring = _load_keyring()
        if keyring is not None:
            token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            return token or ""

        fallback_path = self._fallback_path
        if not fallback_path.exists():
            return ""
        return fallback_path.read_text(encoding="utf-8").strip()

    def set(self, token: str) -> None:
        token = token.strip()
        keyring = _load_keyring()
        if keyring is not None:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token)
            self._delete_fallback()
            return

        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_path.write_text(token, encoding="utf-8")
        try:
            os.chmod(self._fallback_path, 0o600)
        except OSError:
            pass

    def clear(self) -> None:
        keyring = _load_keyring()
        if keyring is not None:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
            except Exception:
                pass
        self._delete_fallback()

    @property
    def _fallback_path(self) -> Path:
        return self.config_dir / "client-token"

    def _delete_fallback(self) -> None:
        try:
            self._fallback_path.unlink()
        except FileNotFoundError:
            pass


def default_config_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_DIR_NAME
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "printbridge-endpoint"


def default_log_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_DIR_NAME / "Logs"
    if system == "Darwin":
        return Path.home() / "Library" / "Logs" / APP_DIR_NAME
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "printbridge-endpoint"


def default_config_path() -> Path:
    return default_config_dir() / CONFIG_FILE_NAME


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _load_keyring() -> Any | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring
