import unittest

from printbridge_endpoint.api import parse_server_instructions
from printbridge_endpoint.worker import decode_payload


class DecodePayloadTests(unittest.TestCase):
    def test_decodes_base64_payload(self) -> None:
        self.assertEqual(decode_payload("SGVsbG8="), b"Hello")

    def test_rejects_invalid_base64(self) -> None:
        with self.assertRaises(ValueError):
            decode_payload("not-valid")

    def test_rejects_empty_payload(self) -> None:
        with self.assertRaises(ValueError):
            decode_payload("")


class ServerInstructionTests(unittest.TestCase):
    def test_reads_top_level_intervals(self) -> None:
        instructions = parse_server_instructions(
            {
                "polling_interval_seconds": 12,
                "heartbeat_interval_seconds": 45,
            }
        )

        self.assertEqual(instructions.polling_interval_seconds, 12)
        self.assertEqual(instructions.heartbeat_interval_seconds, 45)

    def test_reads_nested_settings_intervals(self) -> None:
        instructions = parse_server_instructions(
            {
                "settings": {
                    "next_poll_seconds": 7,
                    "heartbeat_seconds": 20,
                }
            }
        )

        self.assertEqual(instructions.polling_interval_seconds, 7)
        self.assertEqual(instructions.heartbeat_interval_seconds, 20)


if __name__ == "__main__":
    unittest.main()
