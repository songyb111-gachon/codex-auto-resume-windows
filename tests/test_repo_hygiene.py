"""Keep local development environment metadata out of the repository.

Fixtures and documentation examples are written from a developer's machine, and a
machine's own paths and identifiers leak into them very easily: an absolute home
directory pasted into a doc, a conversation UUID copied out of real Codex state, a
process id from a real run. None of that is a credential, and none of it is dangerous
on its own - it is simply someone's environment, published by accident, and it is far
easier to keep out than to remove later.

The rules here are deliberately shape-based rather than a list of known values. A
denylist of real identifiers would have to contain those identifiers, which is exactly
what should not be in the repository; a convention for what a fixture may look like
costs nothing and cannot go stale.

The conventions:

* A home directory in an example is a placeholder - `ExampleUser`, `someone`, `<user>`
  or an environment variable - never a real account name.
* A UUID in a tracked file is obviously synthetic: the project's own fixture family, or
  a repeated-nibble pattern. Real Codex thread ids are UUIDv7 values with a timestamp
  prefix and look nothing like either.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Placeholders an example may use for a home directory.
PLACEHOLDER_HOME = re.compile(
    r"(?:ExampleUser|someone|<user>|<name>|USERNAME|%USERPROFILE%|\$HOME|\$\{HOME\}|example)",
    re.IGNORECASE)
HOME_PATH = re.compile(r"(?:[A-Za-z]:[\\/])?Users[\\/]([^\\/\s\"'`,;:*?<>|)\]]+)")
POSIX_HOME = re.compile(r"/home/([a-z0-9._-]+)/")

# A UUID is acceptable in a tracked file only if it is obviously made up.
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
SYNTHETIC_UUID = re.compile(
    r"^(?:0a1b2c3d-|(?:([0-9a-f])\1{7})-|deadbeef-|12345678-)", re.IGNORECASE)

# Windows' own published constants. These are real GUIDs that identify operating-system
# concepts - the compatibility and DPI-awareness manifest ids, and the property key for
# System.AppUserModel.ID - so they have to appear exactly as Microsoft documents them.
# Listed by file rather than by value, so a new GUID in one of these still gets a look.
GUID_ALLOWLIST = {"gui/app.manifest",
                  "src/codex_auto_resume/shortcut.py",
                  "src/codex_auto_resume/notify.py"}

TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".ps1", ".cmd", ".cs", ".yml", ".yaml",
                 ".toml", ".cfg", ".ini", ".manifest", ".gitattributes", ".gitignore"}


def tracked_text_files():
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                             capture_output=True, text=True, encoding="utf-8").stdout
    for name in listing.splitlines():
        path = ROOT / name
        if not path.is_file():
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or not path.suffix:
            yield name, path


class RepositoryHygieneTests(unittest.TestCase):
    def setUp(self):
        self.files = list(tracked_text_files())
        self.assertGreater(len(self.files), 20, "the file listing itself looks wrong")

    def read(self, path):
        try:
            return path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return ""

    def test_no_real_windows_home_directory(self):
        offenders = []
        for name, path in self.files:
            for line_number, line in enumerate(self.read(path).splitlines(), 1):
                for account in HOME_PATH.findall(line):
                    if not PLACEHOLDER_HOME.fullmatch(account):
                        offenders.append("%s:%d names a home directory: %s"
                                         % (name, line_number, account))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_real_posix_home_directory(self):
        offenders = []
        for name, path in self.files:
            for line_number, line in enumerate(self.read(path).splitlines(), 1):
                for account in POSIX_HOME.findall(line):
                    if not PLACEHOLDER_HOME.fullmatch(account) and account != "secret":
                        offenders.append("%s:%d names a home directory: %s"
                                         % (name, line_number, account))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_every_uuid_is_obviously_synthetic(self):
        offenders = []
        for name, path in self.files:
            if name in GUID_ALLOWLIST:
                continue
            for line_number, line in enumerate(self.read(path).splitlines(), 1):
                for value in UUID.findall(line):
                    if not SYNTHETIC_UUID.match(value):
                        offenders.append("%s:%d has a UUID that is not a fixture pattern: %s"
                                         % (name, line_number, value))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_copied_runtime_state_is_tracked(self):
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                                 capture_output=True, text=True, encoding="utf-8").stdout
        for name in listing.splitlines():
            lowered = name.lower()
            self.assertFalse(lowered.endswith((".sqlite", ".sqlite-wal", ".sqlite-shm", ".log")),
                             "runtime state must not be tracked: " + name)
            self.assertNotIn("/config/", "/" + lowered)
            self.assertFalse(lowered.startswith("logs/") and not lowered.endswith(".gitkeep"), name)

    def test_the_fixture_conventions_are_documented(self):
        # A rule nobody can find is a rule that gets broken. CONTRIBUTING has to say it.
        contributing = ROOT / "CONTRIBUTING.md"
        self.assertTrue(contributing.is_file(), "CONTRIBUTING.md should document the conventions")
        text = contributing.read_text(encoding="utf-8")
        self.assertIn("ExampleUser", text)
        self.assertIn("0a1b2c3d", text)


class TestFileShapeTests(unittest.TestCase):
    """A test that never runs guards nothing.

    Six files here kept their `unittest.main()` guard in the middle, where an append had
    left it. `unittest discover` imports the module and runs everything regardless, but a
    developer running one file directly got only the classes defined above the guard -
    83 of 592 tests silently absent, including every version-consistency check and every
    test of starting the watcher.
    """

    def test_the_main_guard_is_the_last_thing_in_every_test_file(self):
        # Anchored to the start of a line: the same text appears inside this very test
        # as data, and matching that instead would make the check report itself.
        guard = re.compile(r'^if __name__ == .__main__.:', re.M)
        offenders = []
        for path in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
            text = path.read_text(encoding="utf-8")
            found = guard.search(text)
            if not found:
                continue
            after = text[found.end():].strip()
            if after != "unittest.main()":
                offenders.append("%s: %d more lines follow the guard"
                                 % (path.name, len(after.splitlines()) - 1))
        self.assertEqual(offenders, [],
                         "tests defined below the guard are skipped when the file is run "
                         "directly, and nothing says so")


if __name__ == "__main__":
    unittest.main()
