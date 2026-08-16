# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

"""Local archive of print jobs this client has sent to a printer.

The server already keeps its own history; this is a separate, client-side
copy of everything needed to resend a job's exact bytes to the exact same
printer without contacting the server again - the point being that a job
that failed at the printer (out of paper, offline, jammed) can still be
reprinted from here even after it's fallen out of the server's queue.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from pridge_client.config import default_archive_path


ARCHIVABLE_STATUSES = ("printed", "failed", "reprinted")


@dataclass
class ArchivedJob:
    id: str
    job_id: str
    printer_name: str
    status: str
    detail: str
    created_at: datetime
    payload: bytes
    mode: str = "system_driver"
    driver_settings: dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    filename: str = ""
    submission_method: str = ""
    explicit_renderer: str = ""
    fit_mode: str = "fit"
    raw_template: str = ""
    raw_paper_width_dots: int = 384
    raw_chars_per_line: int = 32
    receipt_scope_key: str = ""
    copies: int = 1


class ArchiveStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_archive_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS archived_jobs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    printer_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'system_driver',
                    driver_settings TEXT NOT NULL DEFAULT '{}',
                    content_type TEXT NOT NULL DEFAULT '',
                    filename TEXT NOT NULL DEFAULT '',
                    submission_method TEXT NOT NULL DEFAULT '',
                    explicit_renderer TEXT NOT NULL DEFAULT '',
                    fit_mode TEXT NOT NULL DEFAULT 'fit',
                    raw_template TEXT NOT NULL DEFAULT '',
                    raw_paper_width_dots INTEGER NOT NULL DEFAULT 384,
                    raw_chars_per_line INTEGER NOT NULL DEFAULT 32,
                    receipt_scope_key TEXT NOT NULL DEFAULT '',
                    copies INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS archived_jobs_created_at ON archived_jobs (created_at)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record_job(
        self,
        job_id: str,
        printer_name: str,
        status: str,
        payload: bytes,
        detail: str = "",
        mode: str = "system_driver",
        driver_settings: dict[str, str] | None = None,
        content_type: str = "",
        filename: str = "",
        submission_method: str = "",
        explicit_renderer: str = "",
        fit_mode: str = "fit",
        raw_template: str = "",
        raw_paper_width_dots: int = 384,
        raw_chars_per_line: int = 32,
        receipt_scope_key: str = "",
        copies: int = 1,
    ) -> str:
        entry_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO archived_jobs (
                    id, job_id, printer_name, status, detail, created_at, payload,
                    mode, driver_settings, content_type, filename, submission_method,
                    explicit_renderer, fit_mode, raw_template, raw_paper_width_dots,
                    raw_chars_per_line, receipt_scope_key, copies
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    job_id,
                    printer_name,
                    status,
                    detail,
                    datetime.now(timezone.utc).isoformat(),
                    payload,
                    mode,
                    json.dumps(driver_settings or {}),
                    content_type,
                    filename,
                    submission_method,
                    explicit_renderer,
                    fit_mode,
                    raw_template,
                    raw_paper_width_dots,
                    raw_chars_per_line,
                    receipt_scope_key,
                    copies,
                ),
            )
        return entry_id

    def list_jobs(self, limit: int = 500) -> list[ArchivedJob]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM archived_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def get_job(self, entry_id: str) -> ArchivedJob | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM archived_jobs WHERE id = ?", (entry_id,)).fetchone()
        return _row_to_job(row) if row else None

    def prune(self, retention_days: int) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))).isoformat()
        with self._connect() as connection:
            connection.execute("DELETE FROM archived_jobs WHERE created_at < ?", (cutoff,))

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM archived_jobs")


def _row_to_job(row: sqlite3.Row) -> ArchivedJob:
    return ArchivedJob(
        id=row["id"],
        job_id=row["job_id"],
        printer_name=row["printer_name"],
        status=row["status"],
        detail=row["detail"],
        created_at=datetime.fromisoformat(row["created_at"]),
        payload=row["payload"],
        mode=row["mode"],
        driver_settings=json.loads(row["driver_settings"] or "{}"),
        content_type=row["content_type"],
        filename=row["filename"],
        submission_method=row["submission_method"],
        explicit_renderer=row["explicit_renderer"],
        fit_mode=row["fit_mode"],
        raw_template=row["raw_template"],
        raw_paper_width_dots=row["raw_paper_width_dots"],
        raw_chars_per_line=row["raw_chars_per_line"],
        receipt_scope_key=row["receipt_scope_key"],
        copies=row["copies"],
    )
