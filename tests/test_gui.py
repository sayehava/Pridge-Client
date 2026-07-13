import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from printbridge_endpoint.config import ConfigStore
from printbridge_endpoint.gui import EndpointApi


class MemoryTokenStore:
    def __init__(self):
        self.tokens = {}

    def get(self, server_id="default"):
        return self.tokens.get(server_id, "")

    def set(self, token, server_id="default"):
        self.tokens[server_id] = token

    def clear(self, server_id="default"):
        self.tokens.pop(server_id, None)


class NoPrinters:
    def list_printers(self):
        return []


class EndpointApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_handlers = list(logging.getLogger().handlers)
        self.temporary_directory = tempfile.TemporaryDirectory()
        config_path = Path(self.temporary_directory.name) / "config.json"
        self.api = EndpointApi(
            config_store=ConfigStore(config_path),
            token_store=MemoryTokenStore(),
            printer_manager=NoPrinters(),
        )

    def tearDown(self):
        logging.getLogger().handlers = self.previous_handlers
        self.temporary_directory.cleanup()

    def test_adds_multiple_server_profiles(self):
        first = self.api.add_server(
            {"name": "Office", "server_url": "https://office.example.test", "token": "office-token"}
        )
        second = self.api.add_server(
            {"name": "Warehouse", "server_url": "https://warehouse.example.test", "token": "warehouse-token"}
        )

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual([server["name"] for server in second["state"]["servers"]], ["Office", "Warehouse"])

    @patch("printbridge_endpoint.gui.webview.create_window")
    def test_opens_add_server_in_separate_window(self, create_window):
        create_window.return_value = Mock()

        result = self.api.open_server_window()

        self.assertTrue(result["ok"])
        self.assertEqual(create_window.call_args.args[0], "Add Server")
        self.assertIn("server.html?", create_window.call_args.kwargs["url"])
        self.assertEqual(len(self.api.server_windows), 1)


if __name__ == "__main__":
    unittest.main()
