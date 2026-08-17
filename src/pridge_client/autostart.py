# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import os
import platform
import shlex
import sys
from pathlib import Path

from pridge_client.build_info import BUILD_VARIANT


APP_ID = "com.pridge.client"
LEGACY_APP_IDS = ("com.printbridge.client", "com.printbridge.endpoint")


class AutoStartError(RuntimeError):
    pass


def set_start_at_login(enabled: bool) -> None:
    system = platform.system()
    if system == "Darwin":
        _set_macos_launch_agent(enabled)
    elif system == "Linux":
        _set_linux_desktop_entry(enabled)
    elif system == "Windows":
        _set_windows_run_key(enabled)
    else:
        raise AutoStartError(f"Unsupported platform: {system}")


def command(*extra_args: str) -> list[str]:
    # In a packaged build (PyInstaller/Nuitka), sys.executable *is* the app's
    # own binary - there is no separate Python interpreter to hand "-m
    # pridge_client" to. Passing that literal module flag to the frozen exe
    # made it exit immediately on unrecognized arguments, which is why the
    # login item silently failed to start the app in packaged builds.
    if BUILD_VARIANT == "Development":
        return [sys.executable, "-m", "pridge_client", *extra_args]
    return [sys.executable, *extra_args]


def independent_child_environment() -> dict[str, str]:
    """Return an environment for a new long-lived application instance."""
    environment = os.environ.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def _set_macos_launch_agent(enabled: bool) -> None:
    directory = Path.home() / "Library" / "LaunchAgents"
    path = directory / f"{APP_ID}.plist"
    legacy_paths = tuple(directory / f"{app_id}.plist" for app_id in LEGACY_APP_IDS)
    if not enabled:
        _unlink_if_exists(path)
        for legacy_path in legacy_paths:
            _unlink_if_exists(legacy_path)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    args = "\n".join(f"    <string>{_xml_escape(part)}</string>" for part in command("--headless"))
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{APP_ID}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    for legacy_path in legacy_paths:
        _unlink_if_exists(legacy_path)


def _set_linux_desktop_entry(enabled: bool) -> None:
    autostart_directory = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
    path = autostart_directory / "pridge-client.desktop"
    legacy_paths = tuple(
        autostart_directory / name for name in ("printbridge-client.desktop", "printbridge-endpoint.desktop")
    )
    if not enabled:
        _unlink_if_exists(path)
        for legacy_path in legacy_paths:
            _unlink_if_exists(legacy_path)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    exec_line = " ".join(shlex.quote(part) for part in command("--headless"))
    path.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Pridge Client",
                f"Exec={exec_line}",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    for legacy_path in legacy_paths:
        _unlink_if_exists(legacy_path)


def _set_windows_run_key(enabled: bool) -> None:
    try:
        import winreg
    except ImportError as exc:
        raise AutoStartError("Windows auto-start requires winreg.") from exc

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "Pridge Client"
    legacy_value_names = ("PrintBridge Client", "PrintBridge Client Agent", "PrintBridge Endpoint Agent")
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
    except OSError as exc:
        raise AutoStartError(f"Could not open the Windows Run registry key: {exc}") from exc
    with key:
        if enabled:
            value = " ".join(f'"{part}"' if " " in part else part for part in command("--headless"))
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)
        else:
            try:
                winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass
        for legacy_value_name in legacy_value_names:
            try:
                winreg.DeleteValue(key, legacy_value_name)
            except FileNotFoundError:
                pass


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
