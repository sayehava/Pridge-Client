# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Identify the tool that produced the running application."""

from __future__ import annotations

import sys


def _detect_build() -> tuple[str, str]:
    if "__compiled__" in globals():
        return "Native", "Nuitka"
    if bool(getattr(sys, "frozen", False)):
        return "PyInstaller", "PyInstaller"
    return "Development", "Python"


BUILD_VARIANT, BUILD_SYSTEM = _detect_build()
