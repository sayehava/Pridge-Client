# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import json
import os
import platform
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_DIR_NAME = "PrintBridge Endpoint"
CONFIG_FILE_NAME = "config.json"
KEYRING_SERVICE = "printbridge-endpoint"
KEYRING_USERNAME = "client-token"
DARKNESS_GRADES = ("Quartz", "Moonstone", "Labradorite", "Onyx", "Obsidian", "Jet")


@dataclass
class PrinterMapping:
    remote_printer_id: str
    local_printer_name: str
    remote_printer_name: str = ""


@dataclass
class ServerConfig:
    id: str
    name: str = "Server"
    server_url: str = ""
    enabled: bool = True
    polling_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 30
    default_printer: str = ""
    printer_mappings: list[PrinterMapping] = field(default_factory=list)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file_enabled: bool = True


@dataclass
class AppearanceConfig:
    darkness_grade: str = "Onyx"


@dataclass
class EndpointConfig:
    server_url: str = ""
    servers: list[ServerConfig] = field(default_factory=list)
    selected_printer: str = ""
    polling_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 30
    start_polling_on_launch: bool = False
    start_at_login: bool = False
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)


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
        appearance_raw = raw.get("appearance", {})
        if not isinstance(appearance_raw, dict):
            appearance_raw = {}

        servers = _parse_servers(raw)
        return EndpointConfig(
            server_url=str(raw.get("server_url", "")),
            servers=servers,
            selected_printer=str(raw.get("selected_printer", "")),
            polling_interval_seconds=_positive_int(raw.get("polling_interval_seconds", 5), 5),
            heartbeat_interval_seconds=_positive_int(raw.get("heartbeat_interval_seconds", 30), 30),
            start_polling_on_launch=bool(raw.get("start_polling_on_launch", False)),
            start_at_login=bool(raw.get("start_at_login", False)),
            logging=LoggingConfig(
                level=str(logging_raw.get("level", "INFO")),
                file_enabled=bool(logging_raw.get("file_enabled", True)),
            ),
            appearance=AppearanceConfig(
                darkness_grade=_appearance_grade(appearance_raw),
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

    def get(self, server_id: str = "default") -> str:
        keyring = _load_keyring()
        if keyring is not None:
            token = keyring.get_password(KEYRING_SERVICE, _token_username(server_id))
            if token is None and server_id == "default":
                token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            return token or ""

        fallback_path = self._fallback_path(server_id)
        if not fallback_path.exists() and server_id == "default":
            fallback_path = self.config_dir / "client-token"
        if not fallback_path.exists():
            return ""
        return fallback_path.read_text(encoding="utf-8").strip()

    def set(self, token: str, server_id: str = "default") -> None:
        token = token.strip()
        keyring = _load_keyring()
        if keyring is not None:
            keyring.set_password(KEYRING_SERVICE, _token_username(server_id), token)
            self._delete_fallback(server_id)
            return

        self.config_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = self._fallback_path(server_id)
        fallback_path.write_text(token, encoding="utf-8")
        try:
            os.chmod(fallback_path, 0o600)
        except OSError:
            pass

    def clear(self, server_id: str = "default") -> None:
        keyring = _load_keyring()
        if keyring is not None:
            try:
                keyring.delete_password(KEYRING_SERVICE, _token_username(server_id))
            except Exception:
                pass
        self._delete_fallback(server_id)

    def _fallback_path(self, server_id: str) -> Path:
        if server_id == "default":
            return self.config_dir / "client-token"
        return self.config_dir / f"client-token-{_safe_id(server_id)}"

    def _delete_fallback(self, server_id: str) -> None:
        try:
            self._fallback_path(server_id).unlink()
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


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _appearance_grade(raw: dict[str, Any]) -> str:
    grade = str(raw.get("darkness_grade", "")).strip().title()
    if grade in DARKNESS_GRADES:
        return grade

    legacy_opacity = _bounded_int(
        raw.get("glass_opacity_percent", 62),
        default=62,
        minimum=25,
        maximum=95,
    )
    thresholds = ((30, "Quartz"), (42, "Moonstone"), (54, "Labradorite"), (68, "Onyx"), (82, "Obsidian"))
    return next((name for limit, name in thresholds if legacy_opacity <= limit), "Jet")


def _parse_servers(raw: dict[str, Any]) -> list[ServerConfig]:
    legacy_printer = str(raw.get("selected_printer", "")).strip()
    raw_servers = raw.get("servers", [])
    if isinstance(raw_servers, list):
        servers = [_parse_server(item, legacy_printer) for item in raw_servers if isinstance(item, dict)]
        servers = [server for server in servers if server.server_url]
        if servers:
            return servers

    legacy_url = str(raw.get("server_url", "")).strip()
    if not legacy_url:
        return []
    return [
        ServerConfig(
            id="default",
            name="Primary Server",
            server_url=legacy_url,
            enabled=True,
            polling_interval_seconds=_positive_int(raw.get("polling_interval_seconds", 5), 5),
            heartbeat_interval_seconds=_positive_int(raw.get("heartbeat_interval_seconds", 30), 30),
            default_printer=legacy_printer,
        )
    ]


def _parse_server(raw: dict[str, Any], legacy_printer: str = "") -> ServerConfig:
    server_id = str(raw.get("id", "")).strip() or _safe_id(str(raw.get("name", "server")))
    return ServerConfig(
        id=server_id,
        name=str(raw.get("name", "Server")).strip() or "Server",
        server_url=str(raw.get("server_url", "")).strip(),
        enabled=bool(raw.get("enabled", True)),
        polling_interval_seconds=_positive_int(raw.get("polling_interval_seconds", 5), 5),
        heartbeat_interval_seconds=_positive_int(raw.get("heartbeat_interval_seconds", 30), 30),
        default_printer=str(raw.get("default_printer", legacy_printer)).strip(),
        printer_mappings=_parse_printer_mappings(raw.get("printer_mappings", [])),
    )


def _parse_printer_mappings(raw: Any) -> list[PrinterMapping]:
    if not isinstance(raw, list):
        return []

    mappings: list[PrinterMapping] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        remote_printer_id = str(item.get("remote_printer_id", "")).strip()
        local_printer_name = str(item.get("local_printer_name", "")).strip()
        if not remote_printer_id or not local_printer_name:
            continue
        mappings.append(
            PrinterMapping(
                remote_printer_id=remote_printer_id,
                remote_printer_name=str(item.get("remote_printer_name", "")).strip(),
                local_printer_name=local_printer_name,
            )
        )
    return mappings


def _token_username(server_id: str) -> str:
    if server_id == "default":
        return KEYRING_USERNAME
    return f"{KEYRING_USERNAME}:{_safe_id(server_id)}"


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return safe or "server"


def _load_keyring() -> Any | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring
