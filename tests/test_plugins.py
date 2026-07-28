# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pridge_client.plugins.discovery import (
    discover_plugin_directories,
    register_third_party_renderers,
    renderer_plugins_dir,
)
from pridge_client.plugins.installer import (
    PluginInstallError,
    install_renderer_plugin,
    remove_renderer_plugin,
)
from pridge_client.plugins.manifest import ManifestError, load_manifest
from pridge_client.renderers.registry import RendererRegistry


FIXTURE_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "example_renderer_plugin"


class ManifestTests(unittest.TestCase):
    def test_loads_a_valid_manifest(self) -> None:
        manifest = load_manifest(FIXTURE_PLUGIN_DIR / "manifest.json")

        self.assertEqual(manifest.id, "org.example.pridge.renderer.example")
        self.assertEqual(manifest.category, "renderer")
        self.assertEqual(manifest.api_version, 1)
        self.assertEqual(manifest.entry_point, "plugin:ExampleRendererPlugin")
        self.assertIn(".example", manifest.supported_extensions)
        self.assertFalse(manifest.has_widget)

    def test_widget_fields_are_optional_but_reported_when_both_present(self) -> None:
        with TemporaryDirectory() as scratch:
            manifest_path = Path(scratch) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "id": "x",
                        "name": "X",
                        "entry_point": "a:B",
                        "category": "renderer",
                        "widget_title": "My Widget",
                        "widget_entry": "widget.js",
                    }
                )
            )

            manifest = load_manifest(manifest_path)

        self.assertTrue(manifest.has_widget)
        self.assertEqual(manifest.widget_title, "My Widget")
        self.assertEqual(manifest.widget_entry, "widget.js")

    def test_has_widget_is_false_when_only_one_widget_field_is_set(self) -> None:
        with TemporaryDirectory() as scratch:
            manifest_path = Path(scratch) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {"id": "x", "name": "X", "entry_point": "a:B", "category": "renderer", "widget_title": "Only Title"}
                )
            )

            manifest = load_manifest(manifest_path)

        self.assertFalse(manifest.has_widget)

    def test_rejects_missing_id(self) -> None:
        with TemporaryDirectory() as scratch:
            manifest_path = Path(scratch) / "manifest.json"
            manifest_path.write_text(json.dumps({"name": "X", "entry_point": "a:B", "category": "renderer"}))
            with self.assertRaises(ManifestError):
                load_manifest(manifest_path)

    def test_accepts_any_non_empty_category(self) -> None:
        with TemporaryDirectory() as scratch:
            manifest_path = Path(scratch) / "manifest.json"
            manifest_path.write_text(
                json.dumps({"id": "x", "name": "X", "entry_point": "a:B", "category": "BingiBongo"})
            )

            manifest = load_manifest(manifest_path)

        self.assertEqual(manifest.category, "BingiBongo")

    def test_rejects_missing_category(self) -> None:
        with TemporaryDirectory() as scratch:
            manifest_path = Path(scratch) / "manifest.json"
            manifest_path.write_text(
                json.dumps({"id": "x", "name": "X", "entry_point": "a:B"})
            )
            with self.assertRaises(ManifestError):
                load_manifest(manifest_path)

    def test_rejects_malformed_entry_point(self) -> None:
        with TemporaryDirectory() as scratch:
            manifest_path = Path(scratch) / "manifest.json"
            manifest_path.write_text(
                json.dumps({"id": "x", "name": "X", "entry_point": "no-colon", "category": "renderer"})
            )
            with self.assertRaises(ManifestError):
                load_manifest(manifest_path)

    def test_rejects_invalid_json(self) -> None:
        with TemporaryDirectory() as scratch:
            manifest_path = Path(scratch) / "manifest.json"
            manifest_path.write_text("{not json")
            with self.assertRaises(ManifestError):
                load_manifest(manifest_path)


class DiscoveryTests(unittest.TestCase):
    def test_finds_only_directories_containing_a_manifest(self) -> None:
        with TemporaryDirectory() as scratch:
            root = Path(scratch)
            plugin_dir = root / "good-plugin"
            shutil.copytree(FIXTURE_PLUGIN_DIR, plugin_dir)
            (root / "not-a-plugin").mkdir()

            found = discover_plugin_directories(root)

            self.assertEqual([path.name for path in found], ["good-plugin"])

    def test_returns_empty_list_for_a_missing_directory(self) -> None:
        self.assertEqual(discover_plugin_directories(Path("/nonexistent/pridge/plugins")), [])

    def test_registers_a_valid_third_party_renderer(self) -> None:
        with TemporaryDirectory() as scratch:
            config_dir = Path(scratch)
            plugin_dir = renderer_plugins_dir(config_dir) / "example"
            shutil.copytree(FIXTURE_PLUGIN_DIR, plugin_dir)
            registry = RendererRegistry()

            registered_ids = register_third_party_renderers(registry, config_dir)

            self.assertEqual(registered_ids, ["org.example.pridge.renderer.example"])
            entry = registry.get_entry("org.example.pridge.renderer.example")
            self.assertIsNotNone(entry)
            self.assertFalse(entry.is_builtin)
            self.assertEqual(entry.source_path, str(plugin_dir))
            self.assertEqual(entry.load_error, "")
            self.assertEqual(entry.category, "renderer")

    def test_preserves_a_plugin_s_own_freeform_category(self) -> None:
        with TemporaryDirectory() as scratch:
            config_dir = Path(scratch)
            plugin_dir = renderer_plugins_dir(config_dir) / "example"
            shutil.copytree(FIXTURE_PLUGIN_DIR, plugin_dir)
            manifest_path = plugin_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["category"] = "BingiBongo"
            manifest_path.write_text(json.dumps(manifest))
            registry = RendererRegistry()

            register_third_party_renderers(registry, config_dir)

            entry = registry.get_entry("org.example.pridge.renderer.example")
            self.assertEqual(entry.category, "BingiBongo")

    def test_isolates_a_broken_plugin_instead_of_raising(self) -> None:
        with TemporaryDirectory() as scratch:
            config_dir = Path(scratch)
            plugin_dir = renderer_plugins_dir(config_dir) / "broken"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "org.example.broken",
                        "name": "Broken",
                        "api_version": 1,
                        "category": "renderer",
                        "entry_point": "plugin:Missing",
                    }
                )
            )
            (plugin_dir / "plugin.py").write_text("# no Missing class here\n")
            registry = RendererRegistry()

            registered_ids = register_third_party_renderers(registry, config_dir)

            self.assertEqual(registered_ids, [])
            entry = registry.get_entry("broken")
            self.assertIsNotNone(entry)
            self.assertNotEqual(entry.load_error, "")

    def test_incompatible_api_version_is_isolated_as_an_error(self) -> None:
        with TemporaryDirectory() as scratch:
            config_dir = Path(scratch)
            plugin_dir = renderer_plugins_dir(config_dir) / "future"
            shutil.copytree(FIXTURE_PLUGIN_DIR, plugin_dir)
            manifest_path = plugin_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["api_version"] = 99
            manifest_path.write_text(json.dumps(manifest))
            registry = RendererRegistry()

            registered_ids = register_third_party_renderers(registry, config_dir)

            self.assertEqual(registered_ids, [])
            entry = registry.get_entry("future")
            self.assertIsNotNone(entry)
            self.assertIn("API version", entry.load_error)


class InstallerTests(unittest.TestCase):
    def test_installs_a_plugin_folder_and_returns_its_id(self) -> None:
        with TemporaryDirectory() as scratch:
            config_dir = Path(scratch)

            plugin_id = install_renderer_plugin(FIXTURE_PLUGIN_DIR, config_dir)

            self.assertEqual(plugin_id, "org.example.pridge.renderer.example")
            installed_path = renderer_plugins_dir(config_dir) / plugin_id
            self.assertTrue((installed_path / "manifest.json").is_file())
            self.assertTrue((installed_path / "plugin.py").is_file())

    def test_rejects_a_duplicate_plugin_id(self) -> None:
        with TemporaryDirectory() as scratch:
            config_dir = Path(scratch)
            install_renderer_plugin(FIXTURE_PLUGIN_DIR, config_dir)

            with self.assertRaises(PluginInstallError):
                install_renderer_plugin(FIXTURE_PLUGIN_DIR, config_dir)

    def test_rejects_a_folder_without_a_manifest(self) -> None:
        with TemporaryDirectory() as scratch:
            source = Path(scratch) / "source"
            source.mkdir()
            (source / "plugin.py").write_text("# no manifest\n")

            with self.assertRaises(PluginInstallError):
                install_renderer_plugin(source, Path(scratch) / "config")

    def test_rejects_a_non_directory_source(self) -> None:
        with TemporaryDirectory() as scratch:
            source = Path(scratch) / "not-a-dir.txt"
            source.write_text("nope")

            with self.assertRaises(PluginInstallError):
                install_renderer_plugin(source, Path(scratch) / "config")

    def test_removes_an_installed_plugin(self) -> None:
        with TemporaryDirectory() as scratch:
            config_dir = Path(scratch)
            plugin_id = install_renderer_plugin(FIXTURE_PLUGIN_DIR, config_dir)

            remove_renderer_plugin(plugin_id, config_dir)

            self.assertFalse((renderer_plugins_dir(config_dir) / plugin_id).exists())

    def test_removing_an_uninstalled_plugin_raises(self) -> None:
        with TemporaryDirectory() as scratch:
            with self.assertRaises(PluginInstallError):
                remove_renderer_plugin("nothing.here", Path(scratch))


if __name__ == "__main__":
    unittest.main()
