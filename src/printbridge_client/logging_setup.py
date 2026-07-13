# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from printbridge_client.config import ClientConfig, default_log_dir


TOKEN_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+|([A-Za-z0-9_-]{8})[A-Za-z0-9._~+/=-]{12,}")


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(arg)) for arg in record.args)
        return True


def configure_logging(config: ClientConfig, log_dir: Path | None = None) -> None:
    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RedactingFilter())
    root.addHandler(stream_handler)

    if config.logging.file_enabled:
        path = log_dir or default_log_dir()
        path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path / "endpoint.log",
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RedactingFilter())
        root.addHandler(file_handler)


def redact(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group(1):
            return f"{match.group(1)}[redacted]"
        prefix = match.group(2) or ""
        return f"{prefix}...[redacted]"

    return TOKEN_PATTERN.sub(replace, value)
