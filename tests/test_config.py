import json
import tempfile
import unittest
from pathlib import Path

from printbridge_endpoint.config import ConfigStore


class ConfigStoreTests(unittest.TestCase):
    def test_migrates_legacy_single_server_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "server_url": "https://print.example.test",
                        "polling_interval_seconds": 11,
                        "heartbeat_interval_seconds": 44,
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual(len(config.servers), 1)
        self.assertEqual(config.servers[0].id, "default")
        self.assertEqual(config.servers[0].server_url, "https://print.example.test")
        self.assertEqual(config.servers[0].polling_interval_seconds, 11)
        self.assertEqual(config.servers[0].heartbeat_interval_seconds, 44)

    def test_loads_multiple_server_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "servers": [
                            {"id": "one", "name": "One", "server_url": "https://one.example.test"},
                            {"id": "two", "name": "Two", "server_url": "https://two.example.test", "enabled": False},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = ConfigStore(path).load()

        self.assertEqual([server.id for server in config.servers], ["one", "two"])
        self.assertFalse(config.servers[1].enabled)


if __name__ == "__main__":
    unittest.main()
