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


APP_DIR_NAME = "Pridge Client"
CONFIG_DIR_NAME = "pridge-client"
CONFIG_FILE_NAME = "config.json"
KEYRING_SERVICE = "pridge-client"
KEYRING_USERNAME = "client-token"
LEGACY_APP_DIR_NAMES = ("PrintBridge Client", "PrintBridge Endpoint")
LEGACY_CONFIG_DIR_NAMES = ("printbridge-client", "printbridge-endpoint")
LEGACY_KEYRING_SERVICES = ("printbridge-client", "printbridge-endpoint")
DARKNESS_GRADES = ("Quartz", "Moonstone", "Labradorite", "Onyx", "Obsidian", "Jet")
PRINT_MODES = ("raw", "system_driver")


@dataclass
class PrinterMapping:
    remote_printer_id: str
    local_printer_name: str
    remote_printer_name: str = ""


@dataclass
class PrinterProfile:
    mode: str = "system_driver"
    driver_settings: dict[str, str] = field(default_factory=dict)


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
class ClientConfig:
    server_url: str = ""
    servers: list[ServerConfig] = field(default_factory=list)
    selected_printer: str = ""
    printer_profiles: dict[str, PrinterProfile] = field(default_factory=dict)
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
        self.legacy_config_paths = legacy_config_paths() if config_path is None else ()

    def load(self) -> ClientConfig:
        source_path = self.config_path
        migrate_legacy = False
        if not source_path.exists():
            source_path = next((path for path in self.legacy_config_paths if path.exists()), None)
            if source_path is None:
                return ClientConfig()
            migrate_legacy = True

        with source_path.open("r", encoding="utf-8") as file:
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
        config = ClientConfig(
            server_url=str(raw.get("server_url", "")),
            servers=servers,
            selected_printer=str(raw.get("selected_printer", "")),
            printer_profiles=_parse_printer_profiles(raw.get("printer_profiles", {})),
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
        if migrate_legacy:
            self.save(config)
        return config

    def save(self, config: ClientConfig) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(config)
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True)
            file.write("\n")


class ClientTokenStore:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or default_config_dir()
        self.legacy_config_dirs = legacy_config_dirs() if config_dir is None else ()

    def get(self, server_id: str = "default") -> str:
        keyring = _load_keyring()
        if keyring is not None:
            token = keyring.get_password(KEYRING_SERVICE, _token_username(server_id))
            for service in LEGACY_KEYRING_SERVICES:
                if token:
                    break
                token = keyring.get_password(service, _token_username(server_id))
                if token:
                    keyring.set_password(KEYRING_SERVICE, _token_username(server_id), token)
            return token or ""

        fallback_path = self._fallback_path(server_id)
        if fallback_path.exists():
            return fallback_path.read_text(encoding="utf-8").strip()
        legacy_path = next((path for path in self._legacy_fallback_paths(server_id) if path.exists()), None)
        if legacy_path is None:
            return ""
        token = legacy_path.read_text(encoding="utf-8").strip()
        if token:
            self._write_fallback(token, server_id)
        return token

    def set(self, token: str, server_id: str = "default") -> None:
        token = token.strip()
        keyring = _load_keyring()
        if keyring is not None:
            keyring.set_password(KEYRING_SERVICE, _token_username(server_id), token)
            self._delete_fallback(server_id)
            return

        self._write_fallback(token, server_id)

    def clear(self, server_id: str = "default") -> None:
        keyring = _load_keyring()
        if keyring is not None:
            for service in (KEYRING_SERVICE, *LEGACY_KEYRING_SERVICES):
                try:
                    keyring.delete_password(service, _token_username(server_id))
                except Exception:
                    pass
        self._delete_fallback(server_id, include_legacy=True)

    def _fallback_path(self, server_id: str) -> Path:
        return _fallback_path(self.config_dir, server_id)

    def _legacy_fallback_paths(self, server_id: str) -> tuple[Path, ...]:
        return tuple(_fallback_path(directory, server_id) for directory in self.legacy_config_dirs)

    def _write_fallback(self, token: str, server_id: str) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = self._fallback_path(server_id)
        fallback_path.write_text(token, encoding="utf-8")
        try:
            os.chmod(fallback_path, 0o600)
        except OSError:
            pass

    def _delete_fallback(self, server_id: str, include_legacy: bool = False) -> None:
        paths = [self._fallback_path(server_id)]
        if include_legacy:
            paths.extend(self._legacy_fallback_paths(server_id))
        for path in paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def default_config_dir() -> Path:
    return _config_dir(APP_DIR_NAME, CONFIG_DIR_NAME)


def legacy_config_dirs() -> tuple[Path, ...]:
    return tuple(
        _config_dir(app_dir_name, config_dir_name)
        for app_dir_name, config_dir_name in zip(LEGACY_APP_DIR_NAMES, LEGACY_CONFIG_DIR_NAMES)
    )


def _config_dir(app_dir_name: str, config_dir_name: str) -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / app_dir_name
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / app_dir_name
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / config_dir_name


def default_log_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_DIR_NAME / "Logs"
    if system == "Darwin":
        return Path.home() / "Library" / "Logs" / APP_DIR_NAME
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / CONFIG_DIR_NAME


def default_config_path() -> Path:
    return default_config_dir() / CONFIG_FILE_NAME


def legacy_config_paths() -> tuple[Path, ...]:
    return tuple(directory / CONFIG_FILE_NAME for directory in legacy_config_dirs())


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


def _parse_printer_profiles(raw: Any) -> dict[str, PrinterProfile]:
    if not isinstance(raw, dict):
        return {}

    profiles: dict[str, PrinterProfile] = {}
    for raw_name, raw_profile in raw.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_profile, dict):
            continue
        mode = str(raw_profile.get("mode", "system_driver")).strip().lower()
        if mode not in PRINT_MODES:
            mode = "system_driver"
        raw_settings = raw_profile.get("driver_settings", {})
        if not isinstance(raw_settings, dict):
            raw_settings = {}
        settings = {
            str(option_id).strip(): str(value_id).strip()
            for option_id, value_id in raw_settings.items()
            if str(option_id).strip()
            and isinstance(value_id, (str, int, float, bool))
            and str(value_id).strip()
        }
        profiles[name] = PrinterProfile(mode=mode, driver_settings=settings)
    return profiles


def _token_username(server_id: str) -> str:
    if server_id == "default":
        return KEYRING_USERNAME
    return f"{KEYRING_USERNAME}:{_safe_id(server_id)}"


def _fallback_path(directory: Path, server_id: str) -> Path:
    if server_id == "default":
        return directory / "client-token"
    return directory / f"client-token-{_safe_id(server_id)}"


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return safe or "server"


def _load_keyring() -> Any | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring
