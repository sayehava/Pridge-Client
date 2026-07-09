import unittest

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


if __name__ == "__main__":
    unittest.main()
