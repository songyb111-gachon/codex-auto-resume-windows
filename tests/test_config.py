"""Where the installation is, and which version it is.

`config.PROJECT_ROOT` anchors the default home, the entry script a Run value names, the
bootstrap the Diagnostics refresh starts and the plugin manifest the version is read from.
It was `Path(__file__).resolve().parents[2]`: a count, true only while `config.py` sits one
package below `src/`. v0.6.5 moves modules into packages, and with `config.py` one level
lower the count named `src/`, the manifest was not there, and `version()` - which swallowed
the error - said "unknown" on every surface at once. Nothing failed for the reason.

So the root is now searched for (the nearest directory above the module holding the
manifest, whose `src/` holds the module), and a manifest that is present but unreadable is
no longer passed off as a missing one without a word.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import config

ROOT = Path(__file__).resolve().parents[1]
LOGGER = "codex_auto_resume.config"


def layout(root: Path, module: str, *manifests: str) -> Path:
    """A module file at `module` under `root`, and a plugin manifest in each of `manifests`."""
    path = root / module
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# a module\n", encoding="utf-8")
    for directory in manifests:
        manifest = root / directory / config.PLUGIN_MANIFEST
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
    return path.resolve()


class ProjectRootTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()

    def test_the_root_is_this_checkout(self):
        self.assertEqual(config.PROJECT_ROOT, ROOT)
        self.assertTrue((config.PROJECT_ROOT / config.PLUGIN_MANIFEST).is_file())
        self.assertEqual(config.Paths(self.root).entry_script, ROOT / "src" / "auto_resume.py")

    def test_the_root_is_found_where_the_module_is_today(self):
        module = layout(self.root, "app/src/codex_auto_resume/config.py", "app")
        self.assertEqual(config._project_root(module), self.root / "app")
        self.assertEqual(config._project_root(module), module.parents[2], "the old answer, today")

    def test_the_root_is_still_found_when_the_module_moves_into_a_package(self):
        for depth, module in ((1, "src/codex_auto_resume/core/config.py"),
                              (2, "src/codex_auto_resume/core/paths/config.py")):
            with self.subTest(depth=depth):
                path = layout(self.root / str(depth), module, ".")
                self.assertEqual(config._project_root(path), self.root / str(depth))
                self.assertNotEqual(path.parents[2], self.root / str(depth),
                                    "the count the root used to be names another directory")

    def test_without_a_manifest_the_answer_is_the_old_one(self):
        module = layout(self.root, "copy/src/codex_auto_resume/config.py")
        self.assertEqual(config._project_root(module), module.parents[2])

    def test_a_manifest_that_is_not_this_installations_is_never_taken(self):
        """One further up (another plugin's directory) or in the wrong place (inside `src/`)
        is not the root of these sources, and is passed over."""
        module = layout(self.root, "plugin/inner/src/codex_auto_resume/config.py",
                        "plugin", "plugin/inner/src")
        self.assertEqual(config._project_root(module), self.root / "plugin" / "inner")
        with_ours = layout(self.root, "other/inner/src/codex_auto_resume/config.py",
                           "other", "other/inner/src", "other/inner")
        self.assertEqual(config._project_root(with_ours), self.root / "other" / "inner")

    def test_the_search_is_bounded(self):
        deep = "src/" + "/".join("level%d" % n for n in range(config.ROOT_SEARCH_LEVELS)) + "/config.py"
        module = layout(self.root, deep, ".")
        self.assertEqual(config._project_root(module), module.parents[2])


class VersionTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.manifest = self.root / config.PLUGIN_MANIFEST
        for patcher in (patch.object(config, "PROJECT_ROOT", self.root),
                        patch.object(config, "_reported", set())):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, content: bytes) -> None:
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_bytes(content)

    def test_the_version_the_manifest_declares(self):
        self.write(b'{"name": "codex-auto-resume", "version": "0.6.5"}')
        self.assertEqual(config.version(), "0.6.5")
        self.assertEqual(config.read_version(self.manifest), "0.6.5")

    def test_a_byte_order_mark_is_accepted(self):
        self.write(b'\xef\xbb\xbf{"version": "0.6.5"}')
        self.assertEqual(config.version(), "0.6.5")

    def test_no_manifest_is_unknown_and_says_nothing(self):
        """A copy of the sources without a manifest has no version to report; that is not a fault."""
        with self.assertNoLogs(LOGGER, "WARNING"):
            self.assertEqual(config.version(), "unknown")
        with self.assertRaisesRegex(config.ConfigError, "^the plugin manifest is missing$"):
            config.read_version(self.manifest)

    def test_a_damaged_manifest_is_unknown_and_says_why(self):
        """Still "unknown", so no surface and no heartbeat breaks on it, but no longer silent:
        the reason is logged, and the strict reader raises it."""
        cases = {
            b"{": "the plugin manifest is not JSON",
            b"[]": "the plugin manifest is not a JSON object",
            b'{"name": "codex-auto-resume"}': "the plugin manifest has no version string",
            b'{"version": ""}': "the plugin manifest has no version string",
            b'{"version": 6}': "the plugin manifest has no version string",
            b'\xff\xfe{"version": "0.6.5"}': "the plugin manifest could not be read",
        }
        for content, reason in cases.items():
            with self.subTest(content=content):
                self.write(content)
                config._reported.clear()
                with self.assertLogs(LOGGER, "WARNING") as logged:
                    self.assertEqual(config.version(), "unknown")
                self.assertEqual(len(logged.records), 1)
                self.assertIn(reason, logged.output[0])
                self.assertNotIn(str(self.root), logged.output[0], "a path is not a reason")
                with self.assertRaisesRegex(config.ConfigError, "^%s$" % reason):
                    config.read_version(self.manifest)

    def test_a_manifest_that_cannot_be_opened_is_unknown_and_says_why(self):
        self.manifest.mkdir(parents=True)             # something is there, and it is not a file
        with self.assertLogs(LOGGER, "WARNING") as logged:
            self.assertEqual(config.version(), "unknown")
        self.assertIn("the plugin manifest could not be read", logged.output[0])

    def test_the_reason_is_logged_once_per_process(self):
        """The watcher writes the version into its heartbeat every tick."""
        self.write(b"{")
        with self.assertLogs(LOGGER, "WARNING") as logged:
            for _ in range(3):
                self.assertEqual(config.version(), "unknown")
        self.assertEqual(len(logged.records), 1)


class ShippedManifestTests(unittest.TestCase):
    def test_the_shipped_manifest_reads_strictly(self):
        """The strict reader and `version()` agree on this checkout, so a manifest that stopped
        being readable could not hide behind "unknown" here."""
        declared = config.read_version(config.PROJECT_ROOT / config.PLUGIN_MANIFEST)
        self.assertEqual(config.version(), declared)
        self.assertNotEqual(declared, "unknown")


if __name__ == "__main__":
    unittest.main()
