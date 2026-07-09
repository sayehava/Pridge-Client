from __future__ import annotations

import base64
import binascii
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from printbridge_endpoint.api import ApiError, PrintBridgeClient, ReservedJob
from printbridge_endpoint.config import EndpointConfig
from printbridge_endpoint.models import JobHistoryEntry
from printbridge_endpoint.printers import PrinterError, PrinterManager


logger = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 50 * 1024 * 1024
MAX_BACKOFF_SECONDS = 60


StatusCallback = Callable[[str], None]
JobCallback = Callable[[JobHistoryEntry], None]


@dataclass
class WorkerState:
    running: bool = False
    status: str = "Stopped"
    last_heartbeat_at: datetime | None = None
    last_error: str = ""


class PollingWorker:
    def __init__(
        self,
        config: EndpointConfig,
        client_token: str,
        printer_manager: PrinterManager | None = None,
        on_status: StatusCallback | None = None,
        on_job: JobCallback | None = None,
    ) -> None:
        self.config = config
        self.client_token = client_token
        self.printer_manager = printer_manager or PrinterManager()
        self.on_status = on_status
        self.on_job = on_job
        self.state = WorkerState()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.state.running = True
        self._thread = threading.Thread(target=self._run, name="printbridge-polling-worker", daemon=True)
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
        client = PrintBridgeClient(self.config.server_url, self.client_token)
        next_heartbeat = datetime.min.replace(tzinfo=timezone.utc)
        backoff_seconds = self.config.polling_interval_seconds

        while not self._stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if now >= next_heartbeat:
                    client.heartbeat(self.config.selected_printer or None)
                    self.state.last_heartbeat_at = now
                    next_heartbeat = now + timedelta(seconds=self.config.heartbeat_interval_seconds)

                job = client.reserve_job(self.config.selected_printer or None)
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
                self._set_status(f"Retrying after error: {safe_message}")
                self._stop_event.wait(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, MAX_BACKOFF_SECONDS)

        self.state.running = False
        self._set_status("Stopped")

    def _process_job(self, client: PrintBridgeClient, job: ReservedJob) -> None:
        printer_name = job.printer_name or self.config.selected_printer
        self._record_job(job.job_id, "reserved")
        try:
            payload = decode_payload(job.payload_base64)
            client.report_printing(job.job_id)
            self._record_job(job.job_id, "printing")
            for copy_number in range(job.copies):
                logger.info("Printing job %s copy %s of %s", job.job_id, copy_number + 1, job.copies)
                self.printer_manager.print_raw(printer_name, payload, f"PrintBridge {job.job_id}")
            client.report_printed(job.job_id)
            self._record_job(job.job_id, "printed")
        except (ApiError, PrinterError, ValueError) as exc:
            message = _safe_error_message(exc)
            logger.warning("Job %s failed: %s", job.job_id, message)
            try:
                client.report_failed(job.job_id, message)
            except ApiError as report_exc:
                logger.warning("Could not report failed job %s: %s", job.job_id, _safe_error_message(report_exc))
            self._record_job(job.job_id, "failed", message)

    def _set_status(self, status: str) -> None:
        self.state.status = status
        if self.on_status:
            self.on_status(status)

    def _record_job(self, job_id: str, status: str, detail: str = "") -> None:
        entry = JobHistoryEntry(job_id=job_id, status=status, detail=detail)
        if self.on_job:
            self.on_job(entry)


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


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__
