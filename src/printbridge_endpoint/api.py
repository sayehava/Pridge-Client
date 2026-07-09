from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin


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
    copies: int = 1


class PrintBridgeClient:
    def __init__(self, server_url: str, client_token: str, timeout_seconds: int = 15) -> None:
        self.server_url = _normalize_server_url(server_url)
        self.client_token = client_token.strip()
        self.timeout_seconds = timeout_seconds
        self.session_token = ""
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
            self._url("/api/endpoint/auth"),
            json={"client_token": self.client_token},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise AuthenticationError(f"Authentication failed with HTTP {response.status_code}.")

        body = _json_object(response)
        session_token = body.get("session_token")
        if not isinstance(session_token, str) or not session_token.strip():
            raise AuthenticationError("Authentication response did not include a session token.")

        self.session_token = session_token.strip()
        logger.info("Endpoint authenticated successfully")

    def heartbeat(self, printer_name: str | None = None) -> None:
        payload: dict[str, Any] = {}
        if printer_name:
            payload["printer_name"] = printer_name
        self._request("POST", "/api/endpoint/heartbeat", json=payload)
        logger.debug("Heartbeat sent")

    def reserve_job(self, printer_name: str | None = None) -> ReservedJob | None:
        payload: dict[str, Any] = {}
        if printer_name:
            payload["printer_name"] = printer_name
        response = self._request("POST", "/api/endpoint/jobs/reserve", json=payload)
        if response.status_code == 204:
            return None

        body = _json_object(response)
        if body.get("job") is None:
            return None
        if not isinstance(body.get("job"), dict):
            raise ApiError("Reserve job response contains an invalid job object.")

        return _parse_reserved_job(body["job"])

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
        payload: dict[str, Any] = {"status": status}
        if message:
            payload["message"] = message
        self._request("POST", f"/api/endpoint/jobs/{job_id}/status", json=payload)
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
    if not isinstance(job_id, str) or not job_id:
        raise ApiError("Reserved job is missing an id.")
    if not isinstance(payload_base64, str) or not payload_base64:
        raise ApiError("Reserved job is missing a Base64 payload.")
    if not isinstance(content_type, str) or not content_type:
        content_type = "application/octet-stream"

    printer_name = raw.get("printer_name")
    copies = raw.get("copies", 1)
    try:
        copies = int(copies)
    except (TypeError, ValueError):
        copies = 1

    return ReservedJob(
        job_id=job_id,
        payload_base64=payload_base64,
        content_type=content_type,
        printer_name=printer_name if isinstance(printer_name, str) else None,
        copies=max(copies, 1),
    )


def _load_requests() -> Any:
    try:
        import requests
    except ImportError as exc:
        raise ApiError("The requests package is required for server communication.") from exc
    return requests
