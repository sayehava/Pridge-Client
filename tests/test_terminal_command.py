# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pridge_client.terminal_command import (
    MANAGED_MARKER,
    TerminalCommandError,
    install_terminal_command,
    installed_terminal_command,
    validate_command_name,
)


class TerminalCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name) / "home"
        self.config_dir = Path(self.directory.name) / "config"
        self.home.mkdir()

    def test_accepts_safe_custom_names(self) -> None:
        self.assertEqual(validate_command_name("Pridge_client"), "Pridge_client")
        self.assertEqual(validate_command_name("office-print"), "office-print")

    def test_rejects_names_that_can_escape_or_inject_shell_code(self) -> None:
        for name in ("../pridge", "two words", "pridge;rm", "1pridge", ""):
            with self.subTest(name=name), self.assertRaises(TerminalCommandError):
                validate_command_name(name)

    @patch("pridge_client.terminal_command.BUILD_VARIANT", "Development")
    @patch("pridge_client.terminal_command.command", return_value=["python3", "-m", "pridge_client", "--tui"])
    def test_installs_executable_tui_wrapper_and_shell_path(self, _command) -> None:
        message = install_terminal_command(
            "Pridge_client",
            home=self.home,
            config_dir=self.config_dir,
            environ={"SHELL": "/bin/zsh"},
        )

        target = self.home / ".local" / "bin" / "Pridge_client"
        wrapper = target.read_text(encoding="utf-8")
        self.assertIn("python3 -m pridge_client --tui", wrapper)
        self.assertIn("PYTHONPATH=", wrapper)
        self.assertTrue(target.stat().st_mode & 0o100)
        self.assertIn(".local/bin", (self.home / ".zshrc").read_text(encoding="utf-8"))
        self.assertEqual(installed_terminal_command(self.home, self.config_dir), "Pridge_client")
        self.assertIn("Open a new terminal", message)

    def test_does_not_replace_an_unmanaged_command(self) -> None:
        target = self.home / ".local" / "bin" / "Pridge_client"
        target.parent.mkdir(parents=True)
        target.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

        with self.assertRaises(TerminalCommandError):
            install_terminal_command("Pridge_client", self.home, self.config_dir, {"SHELL": "/bin/zsh"})

        self.assertEqual(target.read_text(encoding="utf-8"), "#!/bin/sh\necho mine\n")

    def test_rejects_a_name_that_already_resolves_on_path(self) -> None:
        commands = Path(self.directory.name) / "commands"
        commands.mkdir()
        existing_command = commands / "Pridge_client"
        existing_command.write_text("existing", encoding="utf-8")
        existing_command.chmod(0o755)

        with self.assertRaises(TerminalCommandError):
            install_terminal_command(
                "Pridge_client",
                self.home,
                self.config_dir,
                {"SHELL": "/bin/zsh", "PATH": str(commands)},
            )

    def test_reinstall_updates_a_managed_command_without_repeating_path_line(self) -> None:
        target = self.home / ".local" / "bin" / "Pridge_client"
        target.parent.mkdir(parents=True)
        target.write_text(f"#!/bin/sh\n{MANAGED_MARKER}\nold\n", encoding="utf-8")
        profile = self.home / ".profile"
        profile.write_text('export PATH="$HOME/.local/bin:$PATH"\n', encoding="utf-8")

        install_terminal_command("Pridge_client", self.home, self.config_dir, {"SHELL": "/bin/sh"})

        self.assertEqual(profile.read_text(encoding="utf-8").count(".local/bin"), 1)


if __name__ == "__main__":
    unittest.main()
