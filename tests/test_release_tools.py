# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from release_common import ROOT, ensure_release_dir, write_build_metadata  # noqa: E402


class ReleaseToolTests(unittest.TestCase):
    def test_rejects_output_inside_repository(self):
        with self.assertRaises(ValueError):
            ensure_release_dir(ROOT / "Release")

    def test_writes_build_metadata_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_build_metadata(Path(directory) / "_build.json", "PyInstaller", "PyInstaller", "2.0.0")

            self.assertIn('"variant": "PyInstaller"', path.read_text(encoding="utf-8"))
            self.assertIn('"version": "2.0.0"', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
