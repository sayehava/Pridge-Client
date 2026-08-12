# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Pure ANSI rendering for the terminal (TUI) mode.

Ported from the reviewed design prototype at pandoras-box/Pridge-Client/
cli-design-demo/pridge_cli_demo.py - same palette (lifted from styles.css's
"Onyx" theme), same layout, same full 24-bit truecolor approach. Every
function here takes plain data (dicts/lists) as parameters instead of the
prototype's hardcoded fake globals; tui.py's TuiController is what supplies
real data. Nothing in this module touches the real backend, a terminal, or
any I/O - it only turns data into strings, which is what keeps it trivially
unit-testable.
"""

from __future__ import annotations


def rgb_fg(hex_color: str) -> str:
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"\x1b[38;2;{r};{g};{b}m"


def rgb_bg(hex_color: str) -> str:
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"\x1b[48;2;{r};{g};{b}m"


RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"

BG = rgb_bg("0A0E1A")
PANEL_BG = rgb_bg("111A2E")
TEXT = rgb_fg("F3F7FF")
MUTED = rgb_fg("91A0B8")
DIM_MUTED = rgb_fg("5B6981")
ACCENT = rgb_fg("4F8CFF")
ACCENT_BG = rgb_bg("1B3A6B")
SUCCESS = rgb_fg("22C55E")
DANGER = rgb_fg("EF4444")
WARNING = rgb_fg("F59E0B")
BORDER = rgb_fg("2C3B57")
PRIDGE_BLUE = rgb_fg("22D3EE")

CLEAR_SCREEN = "\x1b[2J\x1b[H"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def lerp_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


BORDER_RGB = hex_to_rgb("2C3B57")
ACCENT_RGB = hex_to_rgb("4F8CFF")
CYAN_RGB = hex_to_rgb("22D3EE")


def gradient_rule(width: int, ch: str = "─", peak: tuple[int, int, int] = ACCENT_RGB) -> str:
    """A horizontal rule that brightens from BORDER color to `peak` at its
    center and fades back out - the "shimmer" used on every box top/bottom
    so the full-truecolor point of this design shows up even on plain rules.
    """
    if width <= 0:
        return ""
    out = []
    for i in range(width):
        t = 1 - abs((i / max(1, width - 1)) * 2 - 1)
        r, g, b = lerp_rgb(BORDER_RGB, peak, t)
        out.append(f"\x1b[38;2;{r};{g};{b}m{ch}")
    out.append(RESET)
    return "".join(out)


def chip(key: str, action: str) -> str:
    return f"{ACCENT_BG}{BOLD}{TEXT} {key} {RESET} {MUTED}{action}{RESET}"


