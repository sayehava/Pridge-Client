# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pridge_client.archive import ArchiveStore


class ArchiveStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = ArchiveStore(Path(self.temporary_directory.name) / "archive.sqlite3")

    def test_records_and_lists_a_job_newest_first(self) -> None:
        self.store.record_job("job-1", "Kitchen", "printed", b"first receipt")
        self.store.record_job("job-2", "Kitchen", "failed", b"second receipt", detail="no paper")

        jobs = self.store.list_jobs()

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].job_id, "job-2")
        self.assertEqual(jobs[0].status, "failed")
        self.assertEqual(jobs[0].detail, "no paper")
        self.assertEqual(jobs[1].job_id, "job-1")
        self.assertEqual(jobs[1].payload, b"first receipt")

    def test_round_trips_the_full_print_call_shape(self) -> None:
        entry_id = self.store.record_job(
            "job-1",
            "Kitchen",
            "failed",
            b"raw bytes",
            mode="raw",
            driver_settings={"paper": "80mm"},
            content_type="text/plain",
            filename="ticket.txt",
            submission_method="direct_pdf",
            explicit_renderer="org.example.renderer",
            fit_mode="actual_size",
            raw_template="[body]",
            raw_paper_width_dots=576,
            raw_chars_per_line=48,
            receipt_scope_key="server-1::printer-9",
            copies=2,
        )

        job = self.store.get_job(entry_id)

        self.assertIsNotNone(job)
        self.assertEqual(job.mode, "raw")
        self.assertEqual(job.driver_settings, {"paper": "80mm"})
        self.assertEqual(job.content_type, "text/plain")
        self.assertEqual(job.filename, "ticket.txt")
        self.assertEqual(job.submission_method, "direct_pdf")
        self.assertEqual(job.explicit_renderer, "org.example.renderer")
        self.assertEqual(job.fit_mode, "actual_size")
        self.assertEqual(job.raw_template, "[body]")
        self.assertEqual(job.raw_paper_width_dots, 576)
        self.assertEqual(job.raw_chars_per_line, 48)
        self.assertEqual(job.receipt_scope_key, "server-1::printer-9")
        self.assertEqual(job.copies, 2)

    def test_get_job_returns_none_for_an_unknown_id(self) -> None:
        self.assertIsNone(self.store.get_job("does-not-exist"))

    def test_connection_is_closed_after_use(self) -> None:
        with self.store._connect() as connection:
            connection.execute("SELECT 1")

        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_prune_removes_only_entries_older_than_the_retention_window(self) -> None:
        self.store.record_job("recent", "Kitchen", "printed", b"recent")
        old_id = self.store.record_job("old", "Kitchen", "printed", b"old")
        with self.store._connect() as connection:
            old_timestamp = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
            connection.execute("UPDATE archived_jobs SET created_at = ? WHERE id = ?", (old_timestamp, old_id))

        self.store.prune(retention_days=30)

        remaining = [job.job_id for job in self.store.list_jobs()]
        self.assertEqual(remaining, ["recent"])

    def test_clear_removes_everything(self) -> None:
        self.store.record_job("job-1", "Kitchen", "printed", b"receipt")

        self.store.clear()

        self.assertEqual(self.store.list_jobs(), [])


if __name__ == "__main__":
    unittest.main()
