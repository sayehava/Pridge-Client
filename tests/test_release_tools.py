# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from release_common import ROOT, default_release_dir, ensure_release_dir, write_build_metadata  # noqa: E402


class ReleaseToolTests(unittest.TestCase):
    def test_defaults_output_to_project_build_directory(self):
        with patch.dict(os.environ, {"PRIDGE_RELEASE_DIR": ""}):
            self.assertEqual(default_release_dir(), ROOT / "build")
            self.assertEqual(ensure_release_dir(), (ROOT / "build").resolve())

    def test_writes_build_metadata_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_build_metadata(Path(directory) / "_build.json", "PyInstaller", "PyInstaller", "2.0.0")

            self.assertIn('"variant": "PyInstaller"', path.read_text(encoding="utf-8"))
            self.assertIn('"version": "2.0.0"', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
