# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import json
import os
import platform
import re
import uuid
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
SUBMISSION_METHODS = ("", "direct_pdf", "pdfium")
FIT_MODES = ("fit", "actual_size")
RAW_MACROS = ("", "full_cut", "partial_cut", "open_drawer", "feed", "custom")


@dataclass
class PrinterMapping:
    remote_printer_id: str
    local_printer_name: str
    remote_printer_name: str = ""
    # Receipt Composer content is scoped to this specific mapping (one server's
    # one remote endpoint), not to the local printer it happens to target today
    # - the same physical printer can be mapped from several endpoints (kitchen
    # ticket, register receipt, delivery slip) that each need their own design.
    # One unified template rather than a separate header/footer: the incoming
    # print job's own content is spliced in wherever a `[body]` shortcode
    # appears (or appended at the end if the template never uses one, so a
    # blank/decoration-only template can never silently swallow real content).
    raw_template: str = ""
    raw_paper_width_dots: int = 384
    raw_chars_per_line: int = 32
    # Lets a saved design be bypassed for real jobs without deleting it -
    # sometimes the original, unmodified data from the server is what's
    # wanted. Defaults True so existing designs keep applying unchanged.
    composer_enabled: bool = True
    # Set once by _migrate_mapping_receipt_designs on first load after this
    # field existed, so a mapping deliberately left blank is never mistaken
    # for one that hasn't been migrated yet and overwritten on a later load.
    receipt_design_migrated: bool = False


def mapping_scope_key(server_id: str, remote_printer_id: str) -> str:
    """Identity key for one mapping's Receipt Composer content (template and
    counters) - a physical printer's shared local_printer_name is deliberately
    not part of this key, since that's exactly the ambiguity being scoped away.
    """
    return f"{server_id}::{remote_printer_id}"


@dataclass
class PrinterProfile:
    mode: str = "system_driver"
    driver_settings: dict[str, str] = field(default_factory=dict)
    submission_method: str = ""
    fit_mode: str = "fit"
    # Deprecated: superseded by raw_header_template/raw_footer_template (Receipt
    # Composer). Kept so older config.json files still parse; migrated to an
    # equivalent shortcode template on load by _migrate_legacy_raw_macro and no
    # longer editable from the UI.
    raw_header_preset: str = ""
    raw_header_custom_hex: str = ""
    raw_footer_preset: str = ""
    raw_footer_custom_hex: str = ""


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
    printer_profiles: dict[str, PrinterProfile] = field(default_factory=dict)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file_enabled: bool = True
    retention_days: int = 14
    directory: str = ""


@dataclass
class AppearanceConfig:
    darkness_grade: str = "Onyx"


@dataclass
class DashboardWidget:
    id: str
    widget_type: str
    page: int = 0
    position: int = 0
    config: dict[str, Any] = field(default_factory=dict)


def _default_dashboard_widgets() -> list[DashboardWidget]:
    return [
        DashboardWidget(id="recent-jobs", widget_type="recent_jobs", page=0, position=0),
        DashboardWidget(id="logs-status", widget_type="logs", page=0, position=1),
    ]


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
    dashboard_widgets: list[DashboardWidget] = field(default_factory=_default_dashboard_widgets)


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

        global_printer_profiles, global_legacy_designs = _parse_printer_profiles(raw.get("printer_profiles", {}))
        servers = _parse_servers(raw, global_legacy_designs)
        config = ClientConfig(
            server_url=str(raw.get("server_url", "")),
            servers=servers,
            selected_printer=str(raw.get("selected_printer", "")),
            printer_profiles=global_printer_profiles,
            polling_interval_seconds=_positive_int(raw.get("polling_interval_seconds", 5), 5),
            heartbeat_interval_seconds=_positive_int(raw.get("heartbeat_interval_seconds", 30), 30),
            start_polling_on_launch=bool(raw.get("start_polling_on_launch", False)),
            start_at_login=bool(raw.get("start_at_login", False)),
            logging=LoggingConfig(
                level=str(logging_raw.get("level", "INFO")),
                file_enabled=bool(logging_raw.get("file_enabled", True)),
                retention_days=_positive_int(logging_raw.get("retention_days", 14), 14),
                directory=str(logging_raw.get("directory", "")),
            ),
            appearance=AppearanceConfig(
                darkness_grade=_appearance_grade(appearance_raw),
            ),
            dashboard_widgets=_parse_dashboard_widgets(raw.get("dashboard_widgets")),
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


def _parse_servers(raw: dict[str, Any], global_legacy_designs: dict[str, "LegacyReceiptDesign"]) -> list[ServerConfig]:
    legacy_printer = str(raw.get("selected_printer", "")).strip()
    raw_servers = raw.get("servers", [])
    if isinstance(raw_servers, list):
        servers = [
            _parse_server(item, legacy_printer, global_legacy_designs)
            for item in raw_servers
            if isinstance(item, dict)
        ]
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


def _parse_server(
    raw: dict[str, Any],
    legacy_printer: str = "",
    global_legacy_designs: dict[str, "LegacyReceiptDesign"] | None = None,
) -> ServerConfig:
    server_id = str(raw.get("id", "")).strip() or _safe_id(str(raw.get("name", "server")))
    printer_profiles, server_legacy_designs = _parse_printer_profiles(raw.get("printer_profiles", {}))
    printer_mappings = _parse_printer_mappings(raw.get("printer_mappings", []))
    _migrate_mapping_receipt_designs(printer_mappings, server_legacy_designs, global_legacy_designs or {})
    return ServerConfig(
        id=server_id,
        name=str(raw.get("name", "Server")).strip() or "Server",
        server_url=str(raw.get("server_url", "")).strip(),
        enabled=bool(raw.get("enabled", True)),
        polling_interval_seconds=_positive_int(raw.get("polling_interval_seconds", 5), 5),
        heartbeat_interval_seconds=_positive_int(raw.get("heartbeat_interval_seconds", 30), 30),
        default_printer=str(raw.get("default_printer", legacy_printer)).strip(),
        printer_mappings=printer_mappings,
        printer_profiles=printer_profiles,
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
        raw_paper_width_dots = _bounded_int(item.get("raw_paper_width_dots", 384), 384, 8, 4096)
        raw_paper_width_dots = max(8, (raw_paper_width_dots // 8) * 8)
        raw_template = str(item.get("raw_template", "")).strip()
        if not raw_template:
            # Brief intermediate format (separate header/footer per mapping,
            # before the unified [body]-shortcode template) - combine them
            # the same way they were always concatenated around the real job.
            legacy_header = str(item.get("raw_header_template", "")).strip()
            legacy_footer = str(item.get("raw_footer_template", "")).strip()
            if legacy_header or legacy_footer:
                raw_template = f"{legacy_header}[body]{legacy_footer}"
        mappings.append(
            PrinterMapping(
                remote_printer_id=remote_printer_id,
                remote_printer_name=str(item.get("remote_printer_name", "")).strip(),
                local_printer_name=local_printer_name,
                raw_template=raw_template,
                raw_paper_width_dots=raw_paper_width_dots,
                raw_chars_per_line=_bounded_int(item.get("raw_chars_per_line", 32), 32, 8, 128),
                composer_enabled=bool(item.get("composer_enabled", True)),
                receipt_design_migrated=bool(item.get("receipt_design_migrated", False)),
            )
        )
    return mappings


# (header_template, footer_template, paper_width_dots, chars_per_line) captured from
# a pre-mapping-scoping config.json's printer_profiles entry, purely to seed
# _migrate_mapping_receipt_designs - never stored anywhere itself.
LegacyReceiptDesign = tuple[str, str, int, int]


def _migrate_mapping_receipt_designs(
    mappings: list[PrinterMapping],
    server_legacy_designs: dict[str, "LegacyReceiptDesign"],
    global_legacy_designs: dict[str, "LegacyReceiptDesign"],
) -> None:
    """One-time migration for configs saved before Receipt Composer content
    moved from PrinterProfile (shared by every mapping pointing at a local
    printer) to PrinterMapping (one copy per mapping). Every mapping that
    shared a printer's old template starts from an identical copy of it -
    the same content the whole printer used to show - then diverges
    independently as each mapping is edited from that point on.
    """
    for mapping in mappings:
        if mapping.receipt_design_migrated:
            continue
        design = server_legacy_designs.get(mapping.local_printer_name) or global_legacy_designs.get(
            mapping.local_printer_name
        )
        if design is not None:
            header, footer, paper_width_dots, chars_per_line = design
            mapping.raw_template = f"{header}[body]{footer}" if (header or footer) else ""
            mapping.raw_paper_width_dots = paper_width_dots
            mapping.raw_chars_per_line = chars_per_line
        mapping.receipt_design_migrated = True


def _migrate_legacy_raw_macro(preset: str, custom_hex: str) -> str:
    """Translate a legacy raw_header_preset/raw_footer_preset (+ custom hex)
    into the equivalent Receipt Composer shortcode, so profiles saved before
    that feature existed keep behaving the same way after loading.
    """
    if preset == "full_cut":
        return "[cut:full]"
    if preset == "partial_cut":
        return "[cut:partial]"
    if preset == "open_drawer":
        return "[drawer]"
    if preset == "feed":
        return "[feed:4]"
    if preset == "custom":
        cleaned = re.sub(r"[\s:-]", "", custom_hex)
        return f"[hex:{cleaned}]" if cleaned else ""
    return ""


def _parse_printer_profiles(raw: Any) -> tuple[dict[str, PrinterProfile], dict[str, "LegacyReceiptDesign"]]:
    if not isinstance(raw, dict):
        return {}, {}

    profiles: dict[str, PrinterProfile] = {}
    legacy_designs: dict[str, "LegacyReceiptDesign"] = {}
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
        raw_method = str(raw_profile.get("submission_method", "")).strip().lower()
        if raw_method not in SUBMISSION_METHODS:
            raw_method = ""
        fit_mode = str(raw_profile.get("fit_mode", "fit")).strip().lower()
        if fit_mode not in FIT_MODES:
            fit_mode = "fit"
        raw_header_preset = str(raw_profile.get("raw_header_preset", "")).strip().lower()
        if raw_header_preset not in RAW_MACROS:
            raw_header_preset = ""
        raw_header_custom_hex = str(raw_profile.get("raw_header_custom_hex", "")).strip()
        raw_footer_preset = str(raw_profile.get("raw_footer_preset", "")).strip().lower()
        if raw_footer_preset not in RAW_MACROS:
            raw_footer_preset = ""
        raw_footer_custom_hex = str(raw_profile.get("raw_footer_custom_hex", "")).strip()

        raw_header_template = str(raw_profile.get("raw_header_template", "")).strip()
        if not raw_header_template and raw_header_preset:
            raw_header_template = _migrate_legacy_raw_macro(raw_header_preset, raw_header_custom_hex)
        raw_footer_template = str(raw_profile.get("raw_footer_template", "")).strip()
        if not raw_footer_template and raw_footer_preset:
            raw_footer_template = _migrate_legacy_raw_macro(raw_footer_preset, raw_footer_custom_hex)

        raw_paper_width_dots = _bounded_int(raw_profile.get("raw_paper_width_dots", 384), 384, 8, 4096)
        raw_paper_width_dots = max(8, (raw_paper_width_dots // 8) * 8)
        raw_chars_per_line = _bounded_int(raw_profile.get("raw_chars_per_line", 32), 32, 8, 128)

        profiles[name] = PrinterProfile(
            mode=mode,
            driver_settings=settings,
            submission_method=raw_method,
            fit_mode=fit_mode,
            raw_header_preset=raw_header_preset,
            raw_header_custom_hex=raw_header_custom_hex,
            raw_footer_preset=raw_footer_preset,
            raw_footer_custom_hex=raw_footer_custom_hex,
        )
        legacy_designs[name] = (raw_header_template, raw_footer_template, raw_paper_width_dots, raw_chars_per_line)
    return profiles, legacy_designs


def _parse_dashboard_widgets(raw: Any) -> list[DashboardWidget]:
    if not isinstance(raw, list):
        return _default_dashboard_widgets()

    widgets: list[DashboardWidget] = []
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        widget_type = str(item.get("widget_type", "")).strip()
        if not widget_type:
            continue
        widget_id = str(item.get("id", "")).strip() or uuid.uuid4().hex
        if widget_id in seen_ids:
            widget_id = uuid.uuid4().hex
        seen_ids.add(widget_id)
        raw_config = item.get("config", {})
        widgets.append(
            DashboardWidget(
                id=widget_id,
                widget_type=widget_type,
                page=_positive_int(item.get("page", 0), 0),
                position=_positive_int(item.get("position", 0), 0),
                config=dict(raw_config) if isinstance(raw_config, dict) else {},
            )
        )
    return widgets


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
