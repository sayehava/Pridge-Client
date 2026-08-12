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


def visible_len(s: str) -> int:
    """Length ignoring ANSI escape sequences, for padding math."""
    out, in_esc = 0, False
    for ch in s:
        if ch == "\x1b":
            in_esc = True
        elif in_esc:
            if ch == "m":
                in_esc = False
        else:
            out += 1
    return out


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - visible_len(s))


def truncate(s: str, width: int) -> str:
    return s if len(s) <= width else s[: max(0, width - 1)] + "…"


def visible_truncate(s: str, width: int) -> str:
    """Truncates by *visible* characters, passing ANSI escapes through
    untouched and closing with RESET so color never bleeds past the cut -
    the safety net every box row and header line runs through, since a
    terminal can be resized to any width the layout code didn't plan for.
    """
    if visible_len(s) <= width or width <= 0:
        return s
    out: list[str] = []
    count = 0
    i = 0
    budget = max(0, width - 1)
    while i < len(s) and count < budget:
        if s[i] == "\x1b":
            j = s.index("m", i) + 1
            out.append(s[i:j])
            i = j
            continue
        out.append(s[i])
        count += 1
        i += 1
    out.append("…")
    out.append(RESET)
    return "".join(out)


def center(s: str, width: int) -> str:
    w = visible_len(s)
    if w >= width:
        return visible_truncate(s, width)
    return " " * ((width - w) // 2) + s


# 5x5 block glyphs, just enough letters to spell PRIDGE for the splash/about
# banner - a hand-built "font" since this is stdlib-only, no curses/figlet.
FONT5: dict[str, list[str]] = {
    "P": ["####.", "#...#", "####.", "#....", "#...."],
    "R": ["####.", "#...#", "####.", "#..#.", "#...#"],
    "I": [".###.", "..#..", "..#..", "..#..", ".###."],
    "D": ["###..", "#..#.", "#..#.", "#..#.", "###.."],
    "G": [".###.", "#....", "#.##.", "#..#.", ".###."],
    "E": ["####.", "#....", "###..", "#....", "####."],
}


def render_banner(word: str = "PRIDGE") -> list[str]:
    glyphs = [FONT5[c] for c in word]
    n = len(glyphs)
    rows = []
    for r in range(5):
        cells = []
        for i, g in enumerate(glyphs):
            fg = rgb_fg("%02x%02x%02x" % lerp_rgb(CYAN_RGB, ACCENT_RGB, i / max(1, n - 1)))
            block = "".join("██" if c == "#" else "  " for c in g[r])
            cells.append(f"{fg}{block}{RESET}")
        rows.append(" ".join(cells))
    return rows


def box_top(width: int, title: str = "") -> str:
    if title:
        label = f" {title} "
        dashes_left = 2
        dashes_right = max(0, width - 2 - dashes_left - len(label))
        return f"{PRIDGE_BLUE}╔{'═' * dashes_left}{RESET}{BOLD}{ACCENT}{label}{RESET}{PRIDGE_BLUE}{'═' * dashes_right}╗{RESET}"
    return f"{PRIDGE_BLUE}╔{'═' * (width - 2)}╗{RESET}"


def box_bottom(width: int) -> str:
    return f"{PRIDGE_BLUE}╚{'═' * (width - 2)}╝{RESET}"


def box_row(width: int, content: str = "") -> str:
    inner = width - 4
    if visible_len(content) > inner:
        content = visible_truncate(content, inner)
    return f"{PRIDGE_BLUE}║{RESET} {pad(content, inner)} {PRIDGE_BLUE}║{RESET}"


def box(width: int, title: str, rows: list[str]) -> list[str]:
    out = [box_top(width, title)]
    for row in rows:
        out.append(box_row(width, row))
    out.append(box_bottom(width))
    return out


def status_pill(status: str) -> str:
    if status == "Running":
        return f"{SUCCESS}●{RESET} {SUCCESS}{status}{RESET}"
    if status == "Stopped":
        return f"{DIM_MUTED}●{RESET} {MUTED}{status}{RESET}"
    return f"{DANGER}●{RESET} {DANGER}{status}{RESET}"


SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def sparkline(values: list[float], fg: str = ACCENT) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    chars = [SPARK_CHARS[int((v - lo) / span * (len(SPARK_CHARS) - 1))] for v in values]
    return f"{fg}{''.join(chars)}{RESET}"


def meter(pct: float, width: int, fg: str = ACCENT) -> str:
    pct = max(0.0, min(1.0, pct))
    filled = round(width * pct)
    return f"{fg}{'█' * filled}{DIM_MUTED}{'░' * (width - filled)}{RESET}"


def zip_columns(col_a: list[str], col_b: list[str], gap: str = "  ") -> list[str]:
    height = max(len(col_a), len(col_b))
    a_width = max((visible_len(r) for r in col_a), default=0)
    out = []
    for i in range(height):
        left = col_a[i] if i < len(col_a) else ""
        right = col_b[i] if i < len(col_b) else ""
        out.append(pad(left, a_width) + gap + right)
    return out


SCREENS = ["Dashboard", "Servers", "Printers", "Plugins", "Settings", "About"]


def header(width: int, screen_name: str, version: str) -> list[str]:
    title = f"{BOLD}{PRIDGE_BLUE}◆ Pridge Client{RESET} {DIM_MUTED}v{version}{RESET}"

    def build_tabs(compact: bool) -> str:
        tabs = []
        for i, name in enumerate(SCREENS, start=1):
            if name == screen_name:
                tabs.append(f"{ACCENT_BG}{BOLD}{TEXT} {i} {name} {RESET}")
            elif compact:
                tabs.append(f"{MUTED} {i} {RESET}")
            else:
                tabs.append(f"{MUTED} {i} {name} {RESET}")
        return "".join(tabs)

    # Tab labels are sized for a wide terminal; a resize can always make
    # them not fit, so fall back to number-only tabs and, as a last
    # resort, a hard truncate rather than let the line run past `width`.
    if width >= 90:
        combined = pad(title, 28) + build_tabs(compact=False)
        if visible_len(combined) > width:
            combined = pad(title, 28) + build_tabs(compact=True)
        if visible_len(combined) > width:
            combined = visible_truncate(combined, width)
        lines = [combined]
    else:
        tab_line = build_tabs(compact=False)
        if visible_len(tab_line) > width:
            tab_line = build_tabs(compact=True)
        if visible_len(tab_line) > width:
            tab_line = visible_truncate(tab_line, width)
        lines = [title, tab_line]
    lines.append(f"{BORDER}{'═' * width}{RESET}")
    return lines


def footer(width: int, message: str = "") -> list[str]:
    hints = (
        f"{MUTED}[1-6]{RESET} screen  {MUTED}[⏎]{RESET} next  "
        f"{MUTED}[⌫]{RESET} back  {MUTED}[space]{RESET} toggle  {MUTED}[q]{RESET} exit view"
    )
    short_hints = f"{MUTED}[1-6] [⏎] [⌫] [␣] [q]{RESET}"
    line = hints if not message else f"{message}   {DIM_MUTED}│{RESET}   {hints}"
    if visible_len(line) > width:
        line = short_hints if not message else f"{message}   {DIM_MUTED}│{RESET}   {short_hints}"
    if visible_len(line) > width:
        line = visible_truncate(line, width)
    return [f"{BORDER}{'═' * width}{RESET}", line]


