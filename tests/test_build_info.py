# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import unittest
from unittest.mock import patch

from printbridge_client import build_info


class BuildInfoTests(unittest.TestCase):
    def test_prefers_embedded_release_metadata(self):
        metadata = {"variant": "Native", "system": "Nuitka", "version": "2.3.4"}

        with patch.object(build_info, "_embedded_metadata", return_value=metadata):
            self.assertEqual(build_info._detect_build(), ("Native", "Nuitka"))
            self.assertEqual(build_info.embedded_version("1.0.0"), "2.3.4")

    def test_uses_development_identity_without_frozen_metadata(self):
        with patch.object(build_info, "_embedded_metadata", return_value={}), patch.object(
            build_info.sys, "frozen", False, create=True
        ):
            self.assertEqual(build_info._detect_build(), ("Development", "Python"))


if __name__ == "__main__":
    unittest.main()
