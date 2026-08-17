# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

from collections.abc import Callable

from pridge_client.tui import SETTING_ITEMS, TuiController


class HeadlessTuiController:
    """Expose TUI data while sharing one worker set with the browser API."""

    def __init__(self, api: object, browser_toggle: Callable[[bool], None]) -> None:
        self.api = api
        self.browser_toggle = browser_toggle
        self.delegate = TuiController(
            config_store=api.config_store,
            token_store=api.token_store,
            printer_manager=api.printer_manager,
            archive_store=api.archive_store,
        )
        self._sync()

    def _sync(self) -> None:
        self.delegate.config = self.api.config
        self.delegate.workers = self.api.workers

    def start(self) -> None:
        self.api.start_workers()
        self._sync()

    def stop_all(self) -> None:
        self.api.stop_workers()

    def dashboard_data(self) -> dict:
        self._sync()
        return self.delegate.dashboard_data()

    def servers_data(self) -> list[dict]:
        self._sync()
        return self.delegate.servers_data()

    def printers_data(self) -> list[dict]:
        self._sync()
        return self.delegate.printers_data()

    def plugins_data(self) -> list[dict]:
        self._sync()
        return self.delegate.plugins_data()

    def settings_data(self) -> list[dict]:
        self._sync()
        return self.delegate.settings_data()

    def about_data(self) -> dict:
        return self.delegate.about_data()

    def toggle_server(self, index: int) -> None:
        self._sync()
        self.delegate.toggle_server(index)

    def toggle_plugin(self, index: int) -> None:
        self._sync()
        self.delegate.toggle_plugin(index)

    def toggle_setting(self, index: int) -> str:
        self._sync()
        message = self.delegate.toggle_setting(index)
        self.api.start_polling_on_launch = self.delegate.config.start_polling_on_launch
        self.api.start_at_login = self.delegate.config.start_at_login
        self.api.restart_on_crash = self.delegate.config.restart_on_crash
        if 0 <= index < len(SETTING_ITEMS) and SETTING_ITEMS[index][0] == "web_gui_enabled":
            self.browser_toggle(self.delegate.config.web_gui_enabled)
        return message
