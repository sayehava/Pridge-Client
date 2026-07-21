# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin


logger = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


class AuthenticationError(ApiError):
    pass


@dataclass
class ReservedJob:
    job_id: str
    payload_base64: str
    content_type: str
    printer_name: str | None = None
    remote_printer_id: str = ""
    remote_printer_name: str = ""
    copies: int = 1


@dataclass
class ServerInstructions:
    polling_interval_seconds: int | None = None
    heartbeat_interval_seconds: int | None = None


@dataclass(frozen=True)
class RemotePrinter:
    printer_id: str
    name: str
    enabled: bool = True
    assigned: bool = False


class PridgeClient:
    def __init__(self, server_url: str, client_token: str, timeout_seconds: int = 15) -> None:
        self.server_url = _normalize_server_url(server_url)
        self.client_token = client_token.strip()
        self.timeout_seconds = timeout_seconds
        self.session_token = ""
        self.last_instructions = ServerInstructions()
        self.requests = _load_requests()
        self.session = self.requests.Session()

    @property
    def is_authenticated(self) -> bool:
        return bool(self.session_token)

    def authenticate(self) -> None:
        if not self.server_url:
            raise AuthenticationError("Server URL is not configured.")
        if not self.client_token:
            raise AuthenticationError("Client token is not configured.")

        response = self.session.post(
            self._url("/api/client/auth"),
            json={"token": self.client_token},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise AuthenticationError(f"Authentication failed with HTTP {response.status_code}.")

        body = _json_object(response)
        session_token = body.get("token")
        if session_token is None:
            session_token = body.get("session_token")
        if not isinstance(session_token, str) or not session_token.strip():
            raise AuthenticationError("Authentication response did not include a session token.")

        self.session_token = session_token.strip()
        logger.info("Client authenticated successfully")

    def heartbeat(self, printer_name: str | None = None) -> None:
        payload: dict[str, Any] = {}
        if printer_name:
            payload["printer_name"] = printer_name
        response = self._request("POST", "/api/client/heartbeat", json=payload)
        self._update_instructions_from_response(response)
        logger.debug("Heartbeat sent")

    def reserve_job(self, printer_name: str | None = None) -> ReservedJob | None:
        payload: dict[str, Any] = {}
        if printer_name:
            payload["printer_name"] = printer_name
        response = self._request("POST", "/api/client/jobs/reserve", json=payload)
        if response.status_code == 204:
            return None

        body = _json_object(response)
        self._update_instructions(body)
        if body.get("job") is None:
            return None
        if not isinstance(body.get("job"), dict):
            raise ApiError("Reserve job response contains an invalid job object.")

        return _parse_reserved_job(body["job"])

    def list_remote_printers(self) -> list[RemotePrinter]:
        try:
            response = self._request("GET", "/api/client/endpoints")
        except ApiError as exc:
            if "HTTP 404" not in str(exc):
                raise
            return self._list_remote_printers_from_jobs()
        body = _json_object(response)
        endpoints = body.get("endpoints", [])
        if not isinstance(endpoints, list):
            raise ApiError("Endpoint list response contains an invalid endpoints array.")

        printers: list[RemotePrinter] = []
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                continue
            endpoint_id = endpoint.get("id")
            if not isinstance(endpoint_id, (str, int)) or isinstance(endpoint_id, bool):
                continue
            printer_id = str(endpoint_id).strip()
            if not printer_id:
                continue
            endpoint_name = endpoint.get("name")
            name = endpoint_name.strip() if isinstance(endpoint_name, str) else ""
            printers.append(
                RemotePrinter(
                    printer_id=printer_id,
                    name=name or f"Remote printer {printer_id}",
                    enabled=bool(endpoint.get("enabled", True)),
                    assigned=bool(endpoint.get("assigned", False)),
                )
            )
        return sorted(printers, key=lambda printer: (printer.name.casefold(), printer.printer_id))

    def sync_remote_printers(self, printer_ids: list[str]) -> None:
        endpoint_ids = []
        for printer_id in printer_ids:
            value = str(printer_id).strip()
            if value and value not in endpoint_ids:
                endpoint_ids.append(value)
        response = self._request("PUT", "/api/client/endpoints", json={"endpoint_ids": endpoint_ids})
        body = _json_object(response)
        if not isinstance(body.get("endpoints"), list):
            raise ApiError("Endpoint assignment response contains an invalid endpoints array.")

    def _list_remote_printers_from_jobs(self) -> list[RemotePrinter]:
        response = self._request("GET", "/api/client/jobs")
        body = _json_object(response)
        jobs = body.get("jobs", [])
        if not isinstance(jobs, list):
            raise ApiError("Job list response contains an invalid jobs array.")

        printers: dict[str, RemotePrinter] = {}
        for job in jobs:
            if not isinstance(job, dict):
                continue
            endpoint_id = job.get("endpoint_id")
            if not isinstance(endpoint_id, (str, int)) or isinstance(endpoint_id, bool):
                continue
            printer_id = str(endpoint_id).strip()
            if not printer_id:
                continue
            endpoint_name = job.get("endpoint_name")
            name = endpoint_name.strip() if isinstance(endpoint_name, str) else ""
            printers[printer_id] = RemotePrinter(printer_id=printer_id, name=name or f"Remote printer {printer_id}")
        return sorted(printers.values(), key=lambda printer: (printer.name.casefold(), printer.printer_id))

    def report_printing(self, job_id: str) -> None:
        self.report_job_status(job_id, "printing")

    def report_printed(self, job_id: str) -> None:
        self.report_job_status(job_id, "printed")

    def report_failed(self, job_id: str, message: str) -> None:
        safe_message = message[:500]
        self.report_job_status(job_id, "failed", safe_message)

    def report_job_status(self, job_id: str, status: str, message: str | None = None) -> None:
        if status not in {"printing", "printed", "failed"}:
            raise ValueError(f"Unsupported job status: {status}")
        safe_job_id = quote(str(job_id), safe="")
        payload: dict[str, Any] = {}
        if status == "failed" and message:
            payload["error"] = message
        self._request("POST", f"/api/client/jobs/{safe_job_id}/{status}", json=payload)
        logger.info("Reported job %s as %s", job_id, status)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.session_token:
            self.authenticate()

        response = self.session.request(
            method,
            self._url(path),
            headers={"Authorization": f"Bearer {self.session_token}"},
            timeout=self.timeout_seconds,
            **kwargs,
        )
        if response.status_code == 401:
            logger.info("Session expired; authenticating again")
            self.session_token = ""
            self.authenticate()
            response = self.session.request(
                method,
                self._url(path),
                headers={"Authorization": f"Bearer {self.session_token}"},
                timeout=self.timeout_seconds,
                **kwargs,
            )

        if response.status_code >= 400:
            raise ApiError(f"HTTP {response.status_code} returned for {path}.")
        return response

    def _url(self, path: str) -> str:
        return urljoin(f"{self.server_url}/", path.lstrip("/"))

    def _update_instructions_from_response(self, response: Any) -> None:
        if response.status_code == 204 or not getattr(response, "content", b""):
            return
        self._update_instructions(_json_object(response))

    def _update_instructions(self, body: dict[str, Any]) -> None:
        instructions = parse_server_instructions(body)
        if instructions.polling_interval_seconds is not None:
            self.last_instructions.polling_interval_seconds = instructions.polling_interval_seconds
        if instructions.heartbeat_interval_seconds is not None:
            self.last_instructions.heartbeat_interval_seconds = instructions.heartbeat_interval_seconds


def _normalize_server_url(server_url: str) -> str:
    return server_url.strip().rstrip("/")


def _json_object(response: Any) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise ApiError("Server response was not valid JSON.") from exc
    if not isinstance(body, dict):
        raise ApiError("Server response must be a JSON object.")
    return body


def _parse_reserved_job(raw: dict[str, Any]) -> ReservedJob:
    job_id = raw.get("id")
    payload_base64 = raw.get("payload_base64")
    content_type = raw.get("content_type", "application/octet-stream")
    if not isinstance(job_id, (str, int)) or isinstance(job_id, bool) or str(job_id).strip() == "":
        raise ApiError("Reserved job is missing an id.")
    if not isinstance(payload_base64, str) or not payload_base64:
        raise ApiError("Reserved job is missing a Base64 payload.")
    if not isinstance(content_type, str) or not content_type:
        content_type = "application/octet-stream"

    printer_name = raw.get("printer_name")
    remote_printer_id = raw.get("endpoint_id", raw.get("printer_id", ""))
    remote_printer_name = raw.get("endpoint_name", printer_name)
    copies = raw.get("copies", 1)
    try:
        copies = int(copies)
    except (TypeError, ValueError):
        copies = 1

    return ReservedJob(
        job_id=str(job_id),
        payload_base64=payload_base64,
        content_type=content_type,
        printer_name=printer_name if isinstance(printer_name, str) else None,
        remote_printer_id=str(remote_printer_id).strip() if isinstance(remote_printer_id, (str, int)) else "",
        remote_printer_name=remote_printer_name.strip() if isinstance(remote_printer_name, str) else "",
        copies=max(copies, 1),
    )


def parse_server_instructions(body: dict[str, Any]) -> ServerInstructions:
    settings = body.get("settings")
    if isinstance(settings, dict):
        source = {**body, **settings}
    else:
        source = body

    return ServerInstructions(
        polling_interval_seconds=_optional_interval(
            source,
            "polling_interval_seconds",
            "poll_interval_seconds",
            "next_poll_seconds",
        ),
        heartbeat_interval_seconds=_optional_interval(
            source,
            "heartbeat_interval_seconds",
            "heartbeat_seconds",
        ),
    )


def _optional_interval(source: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return min(parsed, 3600)
    return None


def _load_requests() -> Any:
    try:
        import requests
    except ImportError as exc:
        raise ApiError("The requests package is required for server communication.") from exc
    return requests
