"""The setup window names the early "files" milestone a step of its own (v0.6.18 acceptance, 2026-10-21).

install.ps1's "Installing program files" / "Updating program files" and its later "Copying the program files into place"
both showed "Copying the program files", so the label came twice with the watcher and the Dashboard steps between
them. The early milestone is the `prepare` step now ("Preparing the program files"), in the Installing and Updating
tables (gui/InstallerFlow.cs InstallerProgress), with its words in every catalog. Pure Python: the tables are read from
the source the window compiles, and replayed as InstallerProgress.Advance does.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402

FLOW = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
LOCALES = ROOT / "src" / "codex_auto_resume" / "locales"

# A first installation over an older one, and an update through the bootstrap, as the scripts print them.
INSTALLING = ["edition: standard", "  [ok] Found Codex", "  Updating program files",
              "  Stopping the running watcher so the new version takes over",
              "  Closing the Dashboard so it opens again on the new version",
              "  Copying the program files into place", "  [ok] Bundled Python 3.13 (no system Python needed)",
              "  Registering the Codex plugin", "  Setting up the watcher", "  Checking the installation"]
UPDATING = ["  Asking github.com which release is newest", "  Downloading v9.9.9 from github.com over HTTPS.",
            "  [ok] SHA-256 matches the digest pinned in this plugin",
            "  [ok] Archive contents verified as Codex Auto Resume v9.9.9", "  Installing", "edition: standard",
            "  [ok] Found Codex", "  Updating program files",
            "  Stopping the running watcher so the new version takes over",
            "  Closing the Dashboard so it opens again on the new version",
            "  Copying the program files into place", "  Registering the Codex plugin", "  Setting up the watcher",
            "  Checking the installation"]


def table(name: str) -> list:
    """(starts, place, step) of one of InstallerProgress's tables, in its order."""
    body = guiscan.type_body("InstallerProgress", FLOW)
    body = body[body.index("Milestone[] %s =" % name):]
    body = body[:body.index("};")]
    return [(starts, float(at), step) for starts, at, step in
            re.findall(r'new Milestone\("([^"]+)", ([0-9.]+), "([a-z_]+)"\)', body)]


def step_words() -> dict:
    """InstallerWords' step table: key -> English."""
    body = guiscan.type_body("InstallerWords", FLOW)
    body = body[body.index("private static readonly string[] Steps ="):]
    body = body[:body.index("};")]
    pairs = re.findall(r'"([a-z_]+)", "([^"]+)"', body)
    return dict(pairs)


def steps(name: str, lines: list) -> list:
    """The step named after each line, as InstallerProgress.Advance moves it: forward only, on a known line."""
    at, step, named = 0.0, "starting", []
    for line in lines:
        said = line.strip()
        for starts, place, key in table(name):
            if said.startswith(starts):
                if place > at:
                    at, step = place, key
                break
        named.append(step)
    return named


def labels(name: str, lines: list) -> list:
    """The labels the window shows one after another (a label held over several lines counts once), in English."""
    english = step_words()
    shown = []
    for key in steps(name, lines):
        label = english.get(key, "Starting")
        if not shown or shown[-1] != label:
            shown.append(label)
    return shown


class PrepareStepTests(unittest.TestCase):
    def test_the_early_files_milestone_is_the_prepare_step(self):
        for name in ("Installing", "Updating"):
            named = {starts: key for starts, _at, key in table(name)}
            with self.subTest(name):
                self.assertEqual(named["Installing program files"], "prepare")
                self.assertEqual(named["Updating program files"], "prepare")
                self.assertEqual(named["[ok] Found Codex"], "prepare")
                self.assertEqual(named["Copying the program files into place"], "files")
        self.assertEqual(step_words()["prepare"], "Preparing the program files")
        self.assertEqual(step_words()["files"], "Copying the program files")

    def test_no_label_comes_twice_in_a_run(self):
        self.assertEqual(labels("Installing", INSTALLING),
                         ["Looking for Codex", "Preparing the program files", "Stopping the watcher that is running",
                          "Closing the Dashboard", "Copying the program files", "Adding the plugin to Codex",
                          "Setting up the watcher", "Checking the installation"])
        self.assertEqual(labels("Updating", UPDATING),
                         ["Asking GitHub for the newest release", "Downloading", "Verifying the download",
                          "Preparing the program files", "Stopping the watcher that is running",
                          "Closing the Dashboard", "Copying the program files", "Adding the plugin to Codex",
                          "Setting up the watcher", "Checking the installation"])
        for name, lines in (("Installing", INSTALLING), ("Updating", UPDATING)):
            shown = labels(name, lines)
            with self.subTest(name):
                self.assertEqual(len(shown), len(set(shown)), shown)

    def test_every_catalog_names_the_prepare_step_apart_from_the_copy(self):
        for locale in l10n.LOCALES:
            catalog = json.loads((LOCALES / ("%s.json" % locale)).read_text(encoding="utf-8"))
            with self.subTest(locale):
                prepare = catalog.get("installer.step.prepare", "")
                self.assertTrue(prepare.strip())
                self.assertNotEqual(prepare, catalog["installer.step.files"])
        english = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
        self.assertEqual(english["installer.step.prepare"], step_words()["prepare"])


if __name__ == "__main__":
    unittest.main()
