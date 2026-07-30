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


# The bare-token alternative deliberately excludes "/" from its continuation
# class: this app's own tokens are plain hex/urlsafe (never contain "/"), but
# file paths do - and without excluding it, a long file path or traceback
# frame ("File "/Users/.../pridge_client/worker.py"") reads as one giant
# token-like run and gets redacted into unreadable mush. "Bearer ..." stays
# unrestricted since a Bearer header value must be fully redacted regardless.
TOKEN_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+|([A-Za-z0-9_-]{8})[A-Za-z0-9._~+=-]{12,}")
TRACEBACK_FRAME_PATTERN = re.compile(r'^\s*File ".*", line \d+, in .*$')
LOG_FILE_NAME = "client.log"
ERROR_LOG_FILE_NAME = "errors.log"
ERROR_LOGGER_NAME = "pridge_client.errors"
DATE_SUFFIX_PATTERN = re.compile(r"\.(\d{4}-\d{2}-\d{2})$")
LOG_LINE_DATE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]\d{2}:\d{2}:\d{2}")

_active_handler: TimedRotatingFileHandler | None = None
_active_error_handler: TimedRotatingFileHandler | None = None

# Isolation from the root logger (and so from the main Logs/Status widget)
# must not depend on configure_logging() having run first - set it here,
# at import time, so log_detailed_error() is always isolated even if it's
# ever called before the app's normal logging setup.
logging.getLogger(ERROR_LOGGER_NAME).propagate = False


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(arg)) for arg in record.args)
        return True


class RedactingFormatter(logging.Formatter):
    """Redacts the message and the traceback, not the whole formatted line:
    RedactingFilter only scrubs record.msg/args, which never covers the
    exception text a handler appends after formatting, and detailed error
    entries are exactly where a token is most likely to show up (e.g. inside
    an HTTP client's exception message). Redacting the *entire* line instead
    would also catch %(name)s - a dotted module path like
    "pridge_client.worker" is exactly as "token-like" as a real secret, and
    stripping the logger name out of every entry defeats the point of a
    detailed log.
    """

    def format(self, record: logging.LogRecord) -> str:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(arg)) for arg in record.args)
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(self.formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return super().format(record)


def log_directory_for(config: ClientConfig) -> Path:
    directory = (config.logging.directory or "").strip()
    return Path(directory) if directory else default_log_dir()


def configure_logging(config: ClientConfig, log_dir: Path | None = None) -> None:
    global _active_handler, _active_error_handler
    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RedactingFilter())
    root.addHandler(stream_handler)

    _active_handler = None
    path = log_dir or log_directory_for(config)
    retention_days = max(1, config.logging.retention_days)
    if config.logging.file_enabled:
        path.mkdir(parents=True, exist_ok=True)
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

    # The error logger never propagates to the root logger, so its detailed,
    # full-traceback entries never reach the ordinary Logs/Status widget -
    # they only ever go to their own file and their own dedicated widget.
    _active_error_handler = None
    error_logger = logging.getLogger(ERROR_LOGGER_NAME)
    for handler in error_logger.handlers[:]:
        handler.close()
    error_logger.handlers.clear()
    error_logger.propagate = False
    error_logger.setLevel(logging.ERROR)
    if config.logging.file_enabled:
        path.mkdir(parents=True, exist_ok=True)
        error_file_handler = TimedRotatingFileHandler(
            path / ERROR_LOG_FILE_NAME,
            when="midnight",
            backupCount=retention_days,
            encoding="utf-8",
        )
        error_file_handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        error_logger.addHandler(error_file_handler)
        _active_error_handler = error_file_handler
        prune_old_logs(path, retention_days, file_name=ERROR_LOG_FILE_NAME)


def prune_old_logs(directory: Path, retention_days: int, file_name: str = LOG_FILE_NAME) -> None:
    if not directory.is_dir():
        return
    cutoff = date.today() - timedelta(days=max(1, retention_days))
    for path in directory.glob(f"{file_name}.*"):
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


def _clear_log_handler(handler: TimedRotatingFileHandler | None) -> bool:
    if handler is None:
        return False
    handler.acquire()
    try:
        base_path = Path(handler.baseFilename)
        if handler.stream:
            handler.stream.close()
            handler.stream = None
        base_path.write_text("", encoding="utf-8")
        for sibling in base_path.parent.glob(f"{base_path.name}.*"):
            try:
                sibling.unlink()
            except OSError:
                pass
        handler.stream = handler._open()
    finally:
        handler.release()
    return True


def clear_log_files() -> bool:
    return _clear_log_handler(_active_handler)


def clear_error_log_files() -> bool:
    return _clear_log_handler(_active_error_handler)


def log_detailed_error(context: str, exc: BaseException) -> None:
    """Logs the full exception detail (type, message, traceback) to the
    dedicated error log only - never to the root logger, so it never shows
    up in the ordinary Logs/Status widget, only in its own Error Details
    widget and its own export.
    """
    logging.getLogger(ERROR_LOGGER_NAME).error(context, exc_info=exc)


def parse_log_export_date(value: str) -> date | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _log_files_in(directory: Path, file_name: str = LOG_FILE_NAME) -> list[Path]:
    if not directory.is_dir():
        return []
    dated = sorted(directory.glob(f"{file_name}.*"))
    current = directory / file_name
    return dated + ([current] if current.is_file() else [])


def export_logs_to(
    directory: Path,
    destination: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    file_name: str = LOG_FILE_NAME,
) -> bool:
    files = _log_files_in(directory, file_name)
    if not files:
        return False

    wrote_any = False
    with destination.open("w", encoding="utf-8") as out:
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            except OSError:
                continue
            include = start_date is None and end_date is None
            for line in lines:
                match = LOG_LINE_DATE_PATTERN.match(line)
                if match:
                    try:
                        line_date = date.fromisoformat(match.group(1))
                    except ValueError:
                        line_date = None
                    if line_date is not None:
                        include = (start_date is None or line_date >= start_date) and (
                            end_date is None or line_date <= end_date
                        )
                if include:
                    out.write(line)
                    wrote_any = True
    return wrote_any


def has_log_files(directory: Path, file_name: str = LOG_FILE_NAME) -> bool:
    return bool(_log_files_in(directory, file_name))


def redact(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group(1):
            return f"{match.group(1)}[redacted]"
        prefix = match.group(2) or ""
        return f"{prefix}...[redacted]"

    # Excluding "/" from TOKEN_PATTERN keeps a match from spanning a whole
    # path, but a single long segment - a filename, a module name - still
    # reads as "token-like" on its own. Traceback frame lines have a fixed,
    # predictable shape from Python's own formatter and essentially never
    # carry a secret, so they're exempt entirely rather than tuning the
    # length/charset heuristic further and further.
    return "\n".join(
        line if TRACEBACK_FRAME_PATTERN.match(line) else TOKEN_PATTERN.sub(replace, line)
        for line in value.split("\n")
    )
