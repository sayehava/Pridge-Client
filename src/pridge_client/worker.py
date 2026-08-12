# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import base64
import binascii
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pridge_client.api import ApiError, PridgeClient, ReservedJob
from pridge_client.archive import ArchiveStore
from pridge_client.config import ClientConfig, PrinterMapping, PrinterProfile, ServerConfig, mapping_scope_key
from pridge_client.logging_setup import log_detailed_error
from pridge_client.models import JobHistoryEntry
from pridge_client.printers import PrinterError, PrinterManager


logger = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 50 * 1024 * 1024
MAX_BACKOFF_SECONDS = 60


StatusCallback = Callable[[str], None]
JobCallback = Callable[[JobHistoryEntry], None]
ConfigCallback = Callable[[ClientConfig], None]


@dataclass
class WorkerState:
    running: bool = False
    status: str = "Stopped"
    last_heartbeat_at: datetime | None = None
    last_error: str = ""
    compatibility_warning: str = ""


class PollingWorker:
    def __init__(
        self,
        config: ClientConfig,
        client_token: str,
        printer_manager: PrinterManager | None = None,
        archive_store: ArchiveStore | None = None,
        on_status: StatusCallback | None = None,
        on_job: JobCallback | None = None,
        on_config: ConfigCallback | None = None,
    ) -> None:
        self.config = config
        self.client_token = client_token
        self.printer_manager = printer_manager or PrinterManager()
        self.archive_store = archive_store or ArchiveStore()
        self.on_status = on_status
        self.on_job = on_job
        self.on_config = on_config
        self.state = WorkerState()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.state.running = True
        self._thread = threading.Thread(target=self._run, name="pridge-polling-worker", daemon=True)
        self._thread.start()
        self._set_status("Running")

    def stop(self) -> None:
        self._stop_event.set()
        self.state.running = False
        self._set_status("Stopped")

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        client = PridgeClient(self.config.server_url, self.client_token)
        next_heartbeat = datetime.min.replace(tzinfo=timezone.utc)
        backoff_seconds = self.config.polling_interval_seconds

        while not self._stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if now >= next_heartbeat:
                    client.heartbeat(self.config.selected_printer or None)
                    self._apply_server_instructions(client)
                    self.state.last_heartbeat_at = now
                    next_heartbeat = now + timedelta(seconds=self.config.heartbeat_interval_seconds)

                job = client.reserve_job(self.config.selected_printer or None)
                self._apply_server_instructions(client)
                self.state.compatibility_warning = client.compatibility_warning or ""
                if self.state.status != "Running":
                    self.state.last_error = ""
                    self._set_status("Running")
                if job is None:
                    backoff_seconds = self.config.polling_interval_seconds
                    self._stop_event.wait(self.config.polling_interval_seconds)
                    continue

                self._process_job(client, job)
                backoff_seconds = self.config.polling_interval_seconds
            except Exception as exc:
                safe_message = _safe_error_message(exc)
                self.state.last_error = safe_message
                logger.warning("Polling worker error: %s", safe_message)
                log_detailed_error("Polling worker error", exc)
                self._set_status(f"Retrying after error: {safe_message}")
                self._stop_event.wait(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, MAX_BACKOFF_SECONDS)

        self.state.running = False
        self._set_status("Stopped")

    def _process_job(self, client: PridgeClient, job: ReservedJob) -> None:
        server = self.config.servers[0] if self.config.servers else None
        mapping = _find_printer_mapping(server, job)
        printer_name = resolve_printer_name(server, job, self.config.selected_printer)
        override = server.printer_profiles.get(printer_name) if server else None
        profile = override or self.config.printer_profiles.get(printer_name, PrinterProfile())
        self._record_job(job.job_id, "reserved", printer_name=printer_name)
        payload: bytes | None = None
        try:
            payload = decode_payload(job.payload_base64)
            client.report_printing(job.job_id)
            self._record_job(job.job_id, "printing", printer_name=printer_name)
            submission_method = profile.submission_method or None
            # Receipt Composer content (template, paper width, counters) is
            # scoped to the specific mapping a job arrived through, not to
            # whichever local printer that mapping happens to target today -
            # a job with no matching mapping (default_printer/legacy fallback)
            # simply gets no template, since there's no mapping for it to have
            # a Composer entry in the first place. A mapping can also have its
            # design explicitly turned off (composer_enabled=False) to print
            # the server's original data unmodified without losing the design.
            composer_active = bool(mapping and mapping.composer_enabled)
            receipt_scope_key = mapping_scope_key(server.id, mapping.remote_printer_id) if server and mapping else ""
            raw_template = mapping.raw_template if composer_active else ""
            raw_paper_width_dots = mapping.raw_paper_width_dots if mapping else 384
            raw_chars_per_line = mapping.raw_chars_per_line if mapping else 32
            for copy_number in range(job.copies):
                logger.info("Printing job %s copy %s of %s", job.job_id, copy_number + 1, job.copies)
                self.printer_manager.print_job(
                    printer_name,
                    payload,
                    mode=profile.mode,
                    driver_settings=profile.driver_settings,
                    content_type=job.content_type or None,
                    filename=job.filename or None,
                    job_name=f"Pridge {job.job_id}",
                    submission_method=submission_method,
                    explicit_renderer=job.renderer or None,
                    fit_mode=profile.fit_mode,
                    raw_template=raw_template,
                    raw_paper_width_dots=raw_paper_width_dots,
                    raw_chars_per_line=raw_chars_per_line,
                    receipt_scope_key=receipt_scope_key,
                )
            client.report_printed(job.job_id)
            self._record_job(job.job_id, "printed", printer_name=printer_name)
            self._archive_job(
                job,
                printer_name,
                "printed",
                payload,
                profile,
                submission_method,
                raw_template,
                raw_paper_width_dots,
                raw_chars_per_line,
                receipt_scope_key,
            )
        except (ApiError, PrinterError, ValueError) as exc:
            message = _safe_error_message(exc)
            logger.warning("Job %s failed: %s", job.job_id, message)
            log_detailed_error(f"Job {job.job_id} failed on printer {printer_name}", exc)
            try:
                client.report_failed(job.job_id, message)
            except ApiError as report_exc:
                logger.warning("Could not report failed job %s: %s", job.job_id, _safe_error_message(report_exc))
            self._record_job(job.job_id, "failed", message, printer_name=printer_name)
            # A payload that never decoded isn't a job that can be resent
            # from history - there's nothing meaningful to archive for it.
            if payload is not None:
                self._archive_job(
                    job,
                    printer_name,
                    "failed",
                    payload,
                    profile,
                    submission_method,
                    raw_template,
                    raw_paper_width_dots,
                    raw_chars_per_line,
                    receipt_scope_key,
                    detail=message,
                )

    def _archive_job(
        self,
        job: ReservedJob,
        printer_name: str,
        status: str,
        payload: bytes,
        profile: PrinterProfile,
        submission_method: str | None,
        raw_template: str,
        raw_paper_width_dots: int,
        raw_chars_per_line: int,
        receipt_scope_key: str,
        detail: str = "",
    ) -> None:
        try:
            self.archive_store.record_job(
                job.job_id,
                printer_name,
                status,
                payload,
                detail=detail,
                mode=profile.mode,
                driver_settings=dict(profile.driver_settings),
                content_type=job.content_type or "",
                filename=job.filename or "",
                submission_method=submission_method or "",
                explicit_renderer=job.renderer or "",
                fit_mode=profile.fit_mode,
                raw_template=raw_template,
                raw_paper_width_dots=raw_paper_width_dots,
                raw_chars_per_line=raw_chars_per_line,
                receipt_scope_key=receipt_scope_key,
                copies=job.copies,
            )
            if not self.config.archive.retention_forever:
                self.archive_store.prune(self.config.archive.retention_days)
        except Exception as exc:  # noqa: BLE001 - archiving must never break the print pipeline
            logger.warning("Could not archive job %s: %s", job.job_id, _safe_error_message(exc))

    def _set_status(self, status: str) -> None:
        self.state.status = status
        if self.on_status:
            self.on_status(status)

    def _record_job(self, job_id: str, status: str, detail: str = "", printer_name: str = "") -> None:
        entry = JobHistoryEntry(job_id=job_id, status=status, detail=detail, printer_name=printer_name)
        if self.on_job:
            self.on_job(entry)

    def _apply_server_instructions(self, client: PridgeClient) -> None:
        instructions = client.last_instructions
        changed = False
        if instructions.polling_interval_seconds and instructions.polling_interval_seconds != self.config.polling_interval_seconds:
            self.config.polling_interval_seconds = instructions.polling_interval_seconds
            changed = True
        if instructions.heartbeat_interval_seconds and instructions.heartbeat_interval_seconds != self.config.heartbeat_interval_seconds:
            self.config.heartbeat_interval_seconds = instructions.heartbeat_interval_seconds
            changed = True
        if changed:
            logger.info(
                "Server updated intervals: polling=%s heartbeat=%s",
                self.config.polling_interval_seconds,
                self.config.heartbeat_interval_seconds,
            )
            if self.on_config:
                self.on_config(self.config)


def decode_payload(payload_base64: str) -> bytes:
    try:
        payload = base64.b64decode(payload_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Print payload is not valid Base64.") from exc
    if not payload:
        raise ValueError("Print payload is empty.")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("Print payload is larger than the configured safety limit.")
    return payload


def _find_printer_mapping(server: ServerConfig | None, job: ReservedJob) -> PrinterMapping | None:
    if server is None:
        return None
    if job.remote_printer_id:
        for mapping in server.printer_mappings:
            if mapping.remote_printer_id == job.remote_printer_id:
                return mapping
    if job.remote_printer_name:
        remote_name = job.remote_printer_name.casefold()
        for mapping in server.printer_mappings:
            if mapping.remote_printer_name and mapping.remote_printer_name.casefold() == remote_name:
                return mapping
    return None


def resolve_printer_name(server: ServerConfig | None, job: ReservedJob, legacy_printer: str = "") -> str:
    mapping = _find_printer_mapping(server, job)
    if mapping is not None:
        return mapping.local_printer_name
    if server is not None and server.default_printer:
        return server.default_printer
    if legacy_printer:
        return legacy_printer

    remote_label = job.remote_printer_name or job.remote_printer_id
    if remote_label:
        raise PrinterError(f"No local printer is mapped to remote printer {remote_label}.")
    raise PrinterError("No local printer is configured for this server.")


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__
