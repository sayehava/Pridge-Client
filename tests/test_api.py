import unittest
from unittest.mock import patch

from printbridge_endpoint.api import PrintBridgeClient


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.body = body
        self.content = b"" if body is None else b"json"

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class FakeRequests:
    def __init__(self, session):
        self.session = session

    def Session(self):
        return self.session


class PrintBridgeClientTests(unittest.TestCase):
    def client_with_responses(self, *responses):
        session = FakeSession(responses)
        requests = FakeRequests(session)
        with patch("printbridge_endpoint.api._load_requests", return_value=requests):
            client = PrintBridgeClient("https://example.test/printbridge", "client-secret")
        return client, session

    def test_authenticates_with_server_client_contract(self):
        client, session = self.client_with_responses(FakeResponse(200, {"token": "session-secret"}))

        client.authenticate()

        self.assertEqual(client.session_token, "session-secret")
        self.assertEqual(session.calls[0][1], "https://example.test/printbridge/api/client/auth")
        self.assertEqual(session.calls[0][2]["json"], {"token": "client-secret"})

    def test_reserves_job_with_numeric_server_id(self):
        client, session = self.client_with_responses(
            FakeResponse(200, {"token": "session-secret"}),
            FakeResponse(
                200,
                {
                    "job": {
                        "id": 123,
                        "payload_base64": "SGVsbG8=",
                        "content_type": "application/octet-stream",
                    }
                },
            ),
        )

        job = client.reserve_job()

        self.assertIsNotNone(job)
        self.assertEqual(job.job_id, "123")
        self.assertEqual(session.calls[1][1], "https://example.test/printbridge/api/client/jobs/reserve")

    def test_reports_status_with_server_status_routes(self):
        client, session = self.client_with_responses(
            FakeResponse(200, {"token": "session-secret"}),
            FakeResponse(200, {"job_id": 123, "status": "printing"}),
            FakeResponse(200, {"job_id": 123, "status": "failed"}),
        )

        client.report_printing("123")
        client.report_failed("123", "Printer is offline")

        self.assertEqual(session.calls[1][1], "https://example.test/printbridge/api/client/jobs/123/printing")
        self.assertEqual(session.calls[1][2]["json"], {})
        self.assertEqual(session.calls[2][1], "https://example.test/printbridge/api/client/jobs/123/failed")
        self.assertEqual(session.calls[2][2]["json"], {"error": "Printer is offline"})

    def test_lists_all_assigned_remote_printers(self):
        client, session = self.client_with_responses(
            FakeResponse(200, {"token": "session-secret"}),
            FakeResponse(
                200,
                {
                    "endpoints": [
                        {"id": 12, "name": "Receipts", "enabled": True},
                        {"id": 20, "name": "Labels", "enabled": False},
                    ]
                },
            ),
        )

        printers = client.list_remote_printers()

        self.assertEqual(
            [(printer.printer_id, printer.name, printer.enabled) for printer in printers],
            [("20", "Labels", False), ("12", "Receipts", True)],
        )
        self.assertEqual(session.calls[1][0], "GET")
        self.assertEqual(session.calls[1][1], "https://example.test/printbridge/api/client/endpoints")

    def test_falls_back_to_job_discovery_for_older_servers(self):
        client, session = self.client_with_responses(
            FakeResponse(200, {"token": "session-secret"}),
            FakeResponse(404, {"error": "Not found"}),
            FakeResponse(
                200,
                {"jobs": [{"id": 1, "endpoint_id": 12, "endpoint_name": "Receipts"}]},
            ),
        )

        printers = client.list_remote_printers()

        self.assertEqual([(printer.printer_id, printer.name) for printer in printers], [("12", "Receipts")])
        self.assertEqual(session.calls[2][1], "https://example.test/printbridge/api/client/jobs")


if __name__ == "__main__":
    unittest.main()
