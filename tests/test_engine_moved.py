"""v0.6.13: the watcher looks for Codex's engine again when an update moves or replaces it.

It found codex.exe once, when it built its backend, and never again. On 2026-10-07 the Codex app
(26.930) restarted into a new bin/<hex> folder and emptied the old one; the watcher kept pairing
the app with a server at the old path, and every recovery waited, "ChatGPT app or its Codex
server not running", until the watcher was restarted.

The final v0.6.13 closes what the beta left open: the held file still there, but the ChatGPT app
main running its server from another official build - an update that kept the old folder - and,
once both folders hold a build that passes, the choice between them, which discovery refused as
ambiguous. Only the processes are stubs: a process list of paths and parents, as the inventory
reads it, and the identities the pairing confirms; the backend, the pairing and discovery are real.

A module of its own: test_compat_characterization.py, whose fixture these use, must stay the
file v0.6.10 had (tests/test_released_calls.py replays its scenarios against v0.6.10).
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_compat_characterization import FakeCodex, Fixture  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.codex import pairing, transport  # noqa: E402
from codex_auto_resume.domain.errors import AdapterError  # noqa: E402
from codex_auto_resume.runtime import loop  # noqa: E402

NATIVE = r"C:\Program Files"
STORE_APP = NATIVE + r"\WindowsApps\OpenAI.Codex_26.930.2377.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"


def key(path) -> str:
    return os.path.normcase(str(path))


class PerBuildCodex(FakeCodex):
    """FakeCodex, which also writes down the build each command ran, and fails `codex --version`
    for the builds in `failing`."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.failing, self.builds = set(), []

    def run(self, argv, **kwargs):
        build = key(argv[0])
        self.builds.append(build)
        if build in self.failing and tuple(argv[1:]) == ("--version",):
            return MagicMock(returncode=1, stdout="")
        return super().run(argv, **kwargs)


class EngineMovedTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0"))
        self.first = self.fixture.app.backend()

    def versions_asked(self):
        return self.fixture.codex.calls.count(("--version",))

    def test_the_same_file_is_not_looked_for_again(self):
        asked = self.versions_asked()
        self.assertFalse(self.fixture.app.engine_moved())
        self.assertIs(self.fixture.app.backend(), self.first)
        self.assertEqual(self.versions_asked(), asked)

    def test_an_engine_moved_to_another_folder_is_found_there(self):
        moved = self.fixture.exe.parent.parent / "fedcba9876543210" / "codex.exe"
        moved.parent.mkdir()
        moved.write_bytes(b"MZ-second-build")
        self.fixture.exe.unlink()
        self.assertTrue(self.fixture.app.engine_moved())
        self.assertEqual(self.fixture.app.backend().codex_exe, moved.resolve())

    def test_another_file_at_the_same_path_is_checked_again(self):
        asked = self.versions_asked()
        self.fixture.exe.write_bytes(b"MZ-a-longer-second-build")
        self.assertTrue(self.fixture.app.engine_moved())
        self.assertIsNot(self.fixture.app.backend(), self.first)
        self.assertGreater(self.versions_asked(), asked)

    def test_an_engine_gone_with_none_in_its_place_is_refused_not_kept(self):
        self.fixture.exe.unlink()
        self.assertTrue(self.fixture.app.engine_moved())
        with self.assertRaises(config.ConfigError):
            self.fixture.app.backend()

    def test_the_watcher_asks_before_every_tick_but_its_first(self):
        source = Path(loop.__file__).read_text(encoding="utf-8")
        self.assertIn("if engine is not None and self.engine_moved():\n"
                      "                        engine = None\n"
                      "                    if engine is None:", source)


class TwoBuildsCase(unittest.TestCase):
    """A watcher whose backend holds the first build, with a second official build beside it, and
    a process list it reads of the ChatGPT app main and the codex.exe children it is given."""

    def setUp(self):
        self.codex = PerBuildCodex(version="codex-cli 0.155.0")
        self.fixture = Fixture(self, codex=self.codex)
        self.app = self.fixture.app
        self.first = self.app.backend()
        other = self.fixture.exe.parent.parent / "fedcba9876543210" / "codex.exe"
        other.parent.mkdir()
        other.write_bytes(b"MZ-second-build")
        self.other = other.resolve()
        self.rows = []
        for stub in (patch.dict(os.environ, {"ProgramW6432": NATIVE}),
                     patch.object(transport, "inventory", side_effect=self.listed),
                     patch.object(pairing, "inventory", side_effect=self.listed),
                     patch.object(pairing, "process_identity", side_effect=self.identity)):
            stub.start()
            self.addCleanup(stub.stop)

    def listed(self):
        if isinstance(self.rows, BaseException):
            raise self.rows
        return [dict(row) for row in self.rows]

    def identity(self, pid):
        row = next(row for row in self.rows if row["pid"] == pid)
        return {"pid": pid, "created": 100 + pid, "path": row["path"].lower()}

    def serve(self, *engines):
        """The app main, running a child of each engine."""
        self.rows = [{"pid": 10, "parent": 1, "path": STORE_APP}]
        self.rows += [{"pid": 20 + n, "parent": 10, "path": str(engine)} for n, engine in enumerate(engines)]

    def paired(self):
        """What the app gate asks of the backend the watcher holds."""
        return self.app.backend().app_identity()


class ServedElsewhereTests(TwoBuildsCase):
    """The held file is still there, but the app main runs its server from another official build:
    the watcher looks for its engine again, once per change, and logs it without a path."""

    def test_an_app_serving_from_another_official_engine_is_looked_for_again(self):
        self.serve(self.other)
        self.assertIsNone(self.paired())
        with self.assertLogs(self.app.logger, "INFO") as logged:
            self.assertTrue(self.app.engine_moved())
        self.assertIsNone(self.app._backend)
        self.assertEqual(len(logged.output), 1)
        self.assertIn("another official Codex engine", logged.output[0])
        self.assertNotRegex(logged.output[0].split(":", 2)[2], r"[\\/:]|codex\.exe|fedcba|abcdef",
                            "a path in the log")
        asked = len(self.codex.builds)
        with contextlib.suppress(config.ConfigError):
            self.app.backend()
        self.assertEqual(set(self.codex.builds[asked:]), {key(self.first.codex_exe), key(self.other)},
                         "every official build is checked again")

    def test_the_same_change_is_looked_for_once(self):
        self.codex.failing.add(key(self.other))
        self.serve(self.other)
        self.paired()
        self.assertTrue(self.app.engine_moved())
        # The other build fails its checks, so discovery finds the first one again.
        self.assertEqual(self.app.backend().codex_exe, self.first.codex_exe)
        for _ in range(3):
            self.assertIsNone(self.paired())
            self.assertFalse(self.app.engine_moved())
        self.other.write_bytes(b"MZ-a-longer-second-build")         # another file there now
        self.paired()
        self.assertTrue(self.app.engine_moved())

    def test_an_app_serving_from_the_held_engine_changes_nothing(self):
        self.serve(self.other)
        self.paired()
        self.serve(self.first.codex_exe, self.other)
        self.assertIsNotNone(self.paired())
        self.assertFalse(self.app.engine_moved())
        self.assertIs(self.app.backend(), self.first)

    def test_a_pairing_refused_at_the_held_engine_changes_nothing(self):
        # Two children of the held engine, neither holding Codex's state: the pairing is refused,
        # but it is refused at the held path, and a build the app also runs beside it is no move.
        self.serve(self.first.codex_exe, self.first.codex_exe, self.other)
        with patch.object(pairing, "resource_users", return_value=[]):
            self.assertIsNone(self.paired())
        self.assertFalse(self.app.engine_moved())
        self.assertIs(self.app.backend(), self.first)

    def test_a_codex_exe_that_is_no_official_engine_changes_nothing(self):
        bin_dir = self.fixture.exe.parent.parent
        stray = self.fixture.root / "elsewhere" / "codex.exe"
        unnamed = bin_dir / "not-a-build" / "codex.exe"
        for made in (stray, unnamed):
            made.parent.mkdir()
            made.write_bytes(b"MZ")
        for path in (stray, unnamed, bin_dir / "0123456789abcdef" / "codex.exe"):
            with self.subTest(path.parent.name):
                self.serve(path)
                self.assertIsNone(self.paired())
                self.assertFalse(self.app.engine_moved())
        self.assertIs(self.app.backend(), self.first)

    def test_no_one_app_main_or_no_process_list_changes_nothing(self):
        child = {"pid": 20, "parent": 10, "path": str(self.other)}
        mains = [{"pid": 10, "parent": 1, "path": STORE_APP}, {"pid": 11, "parent": 1, "path": STORE_APP}]
        for name, rows in (("no main", [child]), ("two mains", mains + [child]),
                           ("no process list", AdapterError("process_inventory_unavailable"))):
            with self.subTest(name):
                self.rows = rows
                self.assertIsNone(self.paired())
                self.assertFalse(self.app.engine_moved())
        self.assertIs(self.app.backend(), self.first)

    def test_a_named_engine_is_never_second_guessed(self):
        self.serve(self.other)
        self.paired()
        with patch.dict(os.environ, {config.ENV_CODEX_EXE: str(self.first.codex_exe)}):
            self.assertFalse(self.app.engine_moved())
        with patch.object(self.app, "_codex_exe_override", str(self.first.codex_exe)):
            self.assertFalse(self.app.engine_moved())
        self.assertIs(self.app.backend(), self.first)


if __name__ == "__main__":
    unittest.main()
