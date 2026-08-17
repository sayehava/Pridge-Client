# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Install a user-level command that always opens the terminal interface."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from pathlib import Path

from pridge_client.autostart import command
from pridge_client.build_info import BUILD_VARIANT
from pridge_client.config import default_config_dir


DEFAULT_COMMAND_NAME = "Pridge_client"
MANAGED_MARKER = "# Managed by Pridge Client."
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class TerminalCommandError(ValueError):
    pass


def validate_command_name(name: str) -> str:
    cleaned = name.strip()
    if not NAME_PATTERN.fullmatch(cleaned):
        raise TerminalCommandError("Use 1-64 letters, numbers, underscores, or hyphens; start with a letter.")
    return cleaned


def installed_terminal_command(home: Path | None = None, config_dir: Path | None = None) -> str:
    marker_path = (config_dir or default_config_dir()) / "tui-command.json"
    try:
        metadata = json.loads(marker_path.read_text(encoding="utf-8"))
        name = validate_command_name(str(metadata.get("name", "")))
        target = (home or Path.home()) / ".local" / "bin" / name
        if target.is_file() and MANAGED_MARKER in target.read_text(encoding="utf-8"):
            return name
    except (OSError, ValueError, TypeError):
        pass
    return ""


def install_terminal_command(
    name: str,
    home: Path | None = None,
    config_dir: Path | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    name = validate_command_name(name)
    home = home or Path.home()
    config_dir = config_dir or default_config_dir()
    environment = environ if environ is not None else os.environ
    bin_dir = home / ".local" / "bin"
    target = bin_dir / name
    resolved_command = shutil.which(name, path=environment.get("PATH", ""))
    if resolved_command and Path(resolved_command).resolve() != target.resolve():
        raise TerminalCommandError(f"{name} already resolves to {resolved_command}. Choose another name.")
    if target.is_symlink():
        raise TerminalCommandError(f"{target} is a symbolic link and will not be replaced.")
    if target.exists() and MANAGED_MARKER not in target.read_text(encoding="utf-8"):
        raise TerminalCommandError(f"{target} already exists and is not managed by Pridge Client.")

    bin_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(_wrapper_content(), encoding="utf-8")
    target.chmod(0o755)
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "tui-command.json").write_text(json.dumps({"name": name}) + "\n", encoding="utf-8")
    if str(bin_dir) not in environment.get("PATH", "").split(os.pathsep):
        profile = _shell_profile(home, environment.get("SHELL", ""))
        _ensure_user_bin_on_path(profile)
    return f"Installed {name}. Open a new terminal, then run {name}."


def _wrapper_content() -> str:
    launch = shlex.join(command("--tui"))
    lines = ["#!/bin/sh", MANAGED_MARKER]
    if BUILD_VARIANT == "Development":
        source_root = Path(__file__).resolve().parents[1]
        lines.append(f"export PYTHONPATH={shlex.quote(str(source_root))}:\"${{PYTHONPATH:-}}\"")
    lines.append(f'exec {launch} "$@"')
    return "\n".join(lines) + "\n"


def _shell_profile(home: Path, shell: str) -> Path:
    shell_name = Path(shell).name
    if shell_name == "zsh":
        return home / ".zshrc"
    if shell_name == "bash":
        return home / ".bashrc"
    return home / ".profile"


def _ensure_user_bin_on_path(profile: Path) -> None:
    path_line = 'export PATH="$HOME/.local/bin:$PATH"'
    existing = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if path_line in existing:
        return
    separator = "" if not existing or existing.endswith("\n") else "\n"
    profile.write_text(existing + separator + f"\n{MANAGED_MARKER}\n{path_line}\n", encoding="utf-8")
