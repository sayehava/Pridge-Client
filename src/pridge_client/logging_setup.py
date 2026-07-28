# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from pridge_client.config import ClientConfig, default_log_dir


TOKEN_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+|([A-Za-z0-9_-]{8})[A-Za-z0-9._~+/=-]{12,}")
LOG_FILE_NAME = "client.log"
DATE_SUFFIX_PATTERN = re.compile(r"\.(\d{4}-\d{2}-\d{2})$")
LOG_LINE_DATE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]\d{2}:\d{2}:\d{2}")

_active_handler: TimedRotatingFileHandler | None = None


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(arg)) for arg in record.args)
        return True


def log_directory_for(config: ClientConfig) -> Path:
    directory = (config.logging.directory or "").strip()
    return Path(directory) if directory else default_log_dir()


def configure_logging(config: ClientConfig, log_dir: Path | None = None) -> None:
    global _active_handler
    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RedactingFilter())
    root.addHandler(stream_handler)

    _active_handler = None
    if config.logging.file_enabled:
        path = log_dir or log_directory_for(config)
        path.mkdir(parents=True, exist_ok=True)
        retention_days = max(1, config.logging.retention_days)
        file_handler = TimedRotatingFileHandler(
            path / LOG_FILE_NAME,
            when="midnight",
            backupCount=retention_days,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RedactingFilter())
        root.addHandler(file_handler)
        _active_handler = file_handler
        prune_old_logs(path, retention_days)


def prune_old_logs(directory: Path, retention_days: int) -> None:
    if not directory.is_dir():
        return
    cutoff = date.today() - timedelta(days=max(1, retention_days))
    for path in directory.glob(f"{LOG_FILE_NAME}.*"):
        match = DATE_SUFFIX_PATTERN.search(path.name)
        if not match:
            continue
        try:
            file_date = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                path.unlink()
            except OSError:
                pass


def redact(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group(1):
            return f"{match.group(1)}[redacted]"
        prefix = match.group(2) or ""
        return f"{prefix}...[redacted]"

    return TOKEN_PATTERN.sub(replace, value)
