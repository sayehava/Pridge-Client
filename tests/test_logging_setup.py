# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest

from printbridge_client.logging_setup import redact


class RedactionTests(unittest.TestCase):
    def test_redacts_bearer_token(self) -> None:
        self.assertEqual(redact("Authorization: Bearer abcdef1234567890"), "Authorization: Bearer [redacted]")

    def test_redacts_long_token_like_value(self) -> None:
        self.assertEqual(redact("token abcdef12zzzzzzzzzzzz"), "token abcdef12...[redacted]")


if __name__ == "__main__":
    unittest.main()
