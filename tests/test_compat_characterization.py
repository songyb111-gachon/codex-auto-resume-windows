"""What the engine gate decides for every engine case that exists today.

Written before the Compatibility Registry was switched in, and run against the code as it
was, so that each assertion here records a decision the product already made. The switch
had to leave every one of them standing: a registry that changed what happens to an
existing interruption would be a behaviour change hiding inside a refactor.

The fixture is the real composition: `App.backend()` runs the real discovery and the real
`Backend._compatible()` over a fake `%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\<hex>\\codex.exe`
whose `--version` and `queue --help` answers are scripted, and the real `Engine` makes its
decisions over a real Store and a simulated Codex home, reading the gate from
`App.engine_state` exactly as the watcher wires it. No Codex process is started, nothing is
sent anywhere, and nothing outside the test's own temporary directory is read or written.

Two words change on purpose, and only words: `codex-cli 0.153.4` was reported "verified"
and is reported "structurally_compatible" now (v0.6.5 ships no VERIFIED entry until the
evidence carries the version it was recorded on), and a refused engine is reported
"incompatible" rather than "unknown" (it used to be unable to say so at all). The gate
result - PASS - and every decision after it are the same.

Those words are what v0.6.5 and v0.6.6 bundled, so the module runs on that document, frozen
(`frozen_registry`): data published on main since can verify 0.153.4, and that must not
rewrite what this records.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from codexsim import APP, CodexHome, SimBackend  # noqa: E402
import frozen_registry  # noqa: E402
from codex_auto_resume import config, machine, windows  # noqa: E402
from codex_auto_resume.app import App  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.codex import LocalSource  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402


def setUpModule():
    frozen_registry.hold()


def tearDownModule():
    frozen_registry.release()

T1 = "11111111-1111-7111-8111-111111111111"
TURN_A = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
HELP_OK = "Usage: codex queue [OPTIONS] --thread <THREAD> --message <TEXT>\n"
HELP_CHANGED = "Usage: codex queue [OPTIONS] --session <SESSION>\n"


class FakeCodex:
    """`codex --version` and `codex queue --help`, answered from a script."""

    def __init__(self, version="codex-cli 0.153.4", help_text=HELP_OK, help_rc=0):
        self.version, self.help_text, self.help_rc = version, help_text, help_rc
        self.calls = []

    def run(self, argv, **kwargs):
        tail = tuple(argv[1:])
        self.calls.append(tail)
        if tail == ("--version",):
            return MagicMock(returncode=0, stdout=self.version + "\n")
        if tail == ("queue", "--help"):
            return MagicMock(returncode=self.help_rc, stdout=self.help_text)
        raise AssertionError("an unexpected Codex command was run: %r" % (tail,))


class ProbingBackend(SimBackend):
    """The simulated Codex processes, with the real backend's own engine check in front.

    `Backend.app_identity()` runs `_compatible()` before anything else and answers None
    when it raises; that is how a vanished or changed binary reaches the engine today.
    Everything after that check is the simulation.
    """

    def __init__(self, home, real):
        super().__init__(home)
        self.real = real

    def app_identity(self):
        try:
            self.real._compatible()
        except windows.AdapterError:
            return None
        return super().app_identity()


class Fixture:
    def __init__(self, case: unittest.TestCase, *, binary=True, codex=None):
        self.case = case
        self.folder = tempfile.TemporaryDirectory()
        case.addCleanup(self.folder.cleanup)
        # The folder's final path, never the spelling TEMP gave it. The product's location
        # check (E1) accepts a binary only if its path - resolved, by discovery and by the
        # Backend - sits under %LOCALAPPDATA% exactly as the variable is written. GitHub's
        # runner spells TEMP with an 8.3 short name (its account folder as RUNNER~1),
        # which resolve() expands, so a fake %LOCALAPPDATA% spelt the TEMP way put the fake
        # engine outside its own official location: unsupported_codex_location there, a
        # pass on any machine whose TEMP happens to be spelt canonically. The rule stays as
        # it is; the fixture meets it.
        root = self.root = Path(self.folder.name).resolve()
        self.local = root / "local"
        self.exe = self.local / "OpenAI" / "Codex" / "bin" / "abcdef0123456789" / "codex.exe"
        if binary:
            self.exe.parent.mkdir(parents=True)
            self.exe.write_bytes(b"MZ-first-build")
        self.codex = codex or FakeCodex()
        self.home = CodexHome(root / "codex-home")
        self.paths = config.Paths(root / "car-home")
        self.paths.ensure()
        # Every per-user root the product resolves - all of them from the environment - is
        # redirected into this folder, so nothing can fall back to the machine's own Codex
        # (%LOCALAPPDATA%\OpenAI, %USERPROFILE%\.codex) or this tool's own installation,
        # whatever is installed on the machine running the tests.
        self.profile = root / "profile"
        roaming = self.profile / "AppData" / "Roaming"
        roaming.mkdir(parents=True)
        environment = {"LOCALAPPDATA": str(self.local), "CODEX_HOME": str(self.home.root),
                       "USERPROFILE": str(self.profile), "APPDATA": str(roaming)}
        guard = patch.dict(os.environ, environment)
        guard.start()
        case.addCleanup(guard.stop)
        for name in (config.ENV_CODEX_EXE, config.ENV_HOME):
            os.environ.pop(name, None)
        runner = patch.object(subprocess, "run", side_effect=self.codex.run)
        runner.start()
        case.addCleanup(runner.stop)
        self.app = App(self.paths, codex_home=self.home.root, console=False, enable_logging=False)
        self.store = Store(self.paths.state_dir)
        case.addCleanup(self.store.close)
        self.now = self.home.clock()

    def backend(self):
        backend = self.app.backend()
        self.settle()
        return backend

    def settle(self):
        """Whatever the watcher does between building its backend and ticking."""
        tick = getattr(self.app, "_compatibility_tick", None)
        if tick is not None:
            tick()

    def engine(self, backend):
        self.sim = ProbingBackend(self.home, backend)
        return Engine(self.store, LocalSource(self.home.root), self.sim, clock=lambda: self.now,
                      log=lambda *args: None, notify=lambda *args: None,
                      engine_state=self.app.engine_state,
                      options={"reset_grace_seconds": 60, "state_poll_seconds": 60,
                               "conservative_poll_seconds": 900, "delivery_timeout_seconds": 180})

    def interruption_due(self, engine):
        """A usage-limit failure in an open conversation, with its reset already past."""
        self.store.set_enabled(True, self.now)
        self.home.add_thread(T1)
        self.home.fail_usage(T1, TURN_A, completed=self.now, reset=self.now + 3600)
        self.sim.loaded_map[T1] = "loaded"
        engine.tick()
        self.now += 3600 + 61

    def record(self):
        rows = self.store.all_records()
        return rows[0] if rows else None


class EngineGateCharacterizationTests(unittest.TestCase):
    def test_the_formerly_verified_build_still_sends(self):
        fixture = Fixture(self)
        backend = fixture.backend()
        self.assertEqual(backend.engine_version, "codex-cli 0.153.4")
        # The one word that changes: VERIFIED is unreachable in v0.6.5 (no evidence file
        # records the version it was captured on), so this build is COMPATIBLE through the
        # registry. Both words are a PASS at the gate.
        self.assertEqual(fixture.app.engine_state(), "structurally_compatible")
        engine = fixture.engine(backend)
        fixture.interruption_due(engine)
        engine.tick()
        self.assertEqual(len(fixture.sim.send_calls), 1)
        row = fixture.record()
        self.assertEqual(machine.decode_gates(row["gate_eval"])["engine_compatible"], ("PASS", "ok"))

    def test_an_unverified_build_that_still_offers_the_queue_flags_sends(self):
        """Today's "accepted because `codex queue` still offers --thread/--message"."""
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0-alpha.2.6"))
        backend = fixture.backend()
        self.assertFalse(backend.engine_verified)
        self.assertEqual(fixture.app.engine_state(), "structurally_compatible")
        engine = fixture.engine(backend)
        fixture.interruption_due(engine)
        engine.tick()
        self.assertEqual(len(fixture.sim.send_calls), 1)
        row = fixture.record()
        self.assertEqual(machine.decode_gates(row["gate_eval"])["engine_compatible"], ("PASS", "ok"))

    def test_a_build_without_the_queue_flags_is_refused_and_nothing_is_built(self):
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.199.0", help_text=HELP_CHANGED))
        with self.assertRaises(config.ConfigError):
            fixture.app.backend()
        fixture.settle()
        self.assertIsNone(fixture.app._backend)
        # The word changes (F1): a refusal by a failed local check is "incompatible" now,
        # where it could only ever be "unknown". No engine exists either way, so nothing
        # is decided and nothing is sent.
        self.assertEqual(fixture.app.engine_state(), "incompatible")

    def test_a_queue_help_that_exits_non_zero_is_refused_too(self):
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.199.0", help_rc=2))
        with self.assertRaises(config.ConfigError):
            fixture.app.backend()
        self.assertIsNone(fixture.app._backend)

    def test_no_engine_at_all_is_unknown(self):
        fixture = Fixture(self, binary=False)
        with self.assertRaises(config.ConfigError):
            fixture.app.backend()
        fixture.settle()
        self.assertEqual(fixture.app.engine_state(), "unknown")

    def test_a_binary_that_vanishes_after_start_waits_for_the_app_as_before(self):
        """A Codex update deletes the old content-addressed directory under a running
        watcher. The engine keeps the verdict it started with and waits at the desktop-app
        check, because the backend's own probe fails there - exactly as before."""
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0-alpha.2.6"))
        backend = fixture.backend()
        engine = fixture.engine(backend)
        fixture.interruption_due(engine)
        fixture.exe.unlink()
        fixture.settle()
        self.assertEqual(fixture.app.engine_state(), "structurally_compatible")
        engine.tick()
        self.assertEqual(fixture.sim.send_calls, [])
        row = fixture.record()
        self.assertEqual(row["state"], "waiting_for_app")
        self.assertEqual(row["last_error"], "desktop_app_unavailable")
        gates = machine.decode_gates(row["gate_eval"])
        self.assertEqual(gates["engine_compatible"], ("PASS", "ok"))
        self.assertEqual(gates["thread_available"], ("WAIT", "desktop_app_unavailable"))

    def test_an_in_place_update_that_drops_the_flags_waits_for_the_app_as_before(self):
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0-alpha.2.6"))
        backend = fixture.backend()
        engine = fixture.engine(backend)
        fixture.interruption_due(engine)
        fixture.exe.write_bytes(b"MZ-second-build-with-another-size")
        fixture.codex.version = "codex-cli 0.160.0"
        fixture.codex.help_text = HELP_CHANGED
        fixture.settle()
        self.assertEqual(fixture.app.engine_state(), "structurally_compatible")
        engine.tick()
        self.assertEqual(fixture.sim.send_calls, [])
        row = fixture.record()
        self.assertEqual(row["state"], "waiting_for_app")
        self.assertEqual(row["last_error"], "desktop_app_unavailable")

    def test_an_in_place_update_that_keeps_the_flags_keeps_sending(self):
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0-alpha.2.6"))
        backend = fixture.backend()
        engine = fixture.engine(backend)
        fixture.interruption_due(engine)
        fixture.exe.write_bytes(b"MZ-second-build-with-another-size")
        fixture.codex.version = "codex-cli 0.156.0"
        fixture.settle()
        engine.tick()
        self.assertEqual(len(fixture.sim.send_calls), 1)
        self.assertEqual(backend.engine_version, "codex-cli 0.156.0")
        self.assertEqual(fixture.app.engine_state(), "structurally_compatible")

    def test_a_missing_projection_table_still_blocks_with_its_own_reason(self):
        fixture = Fixture(self, codex=FakeCodex(version="codex-cli 0.155.0-alpha.2.6"))
        backend = fixture.backend()
        engine = fixture.engine(backend)
        fixture.interruption_due(engine)
        with fixture.home._db("thread_history_1.sqlite") as db:
            db.execute("DROP TABLE thread_history_projection_state")
        fixture.settle()
        self.assertEqual(fixture.app.engine_state(), "structurally_compatible")
        engine.tick()
        self.assertEqual(fixture.sim.send_calls, [])
        row = fixture.record()
        self.assertEqual(row["last_error"], "projection_table_missing")
        self.assertEqual(machine.decode_gates(row["gate_eval"])["engine_compatible"],
                         ("BLOCK", "projection_table_missing"))


class FixtureHermeticityTests(unittest.TestCase):
    """The fixture decides the same on every machine: it never sees the machine's own Codex
    or this tool's own installation, and its fake engine meets the product's location rule
    however TEMP happens to be spelt."""

    def test_discovery_sees_only_the_fixtures_own_engine(self):
        fixture = Fixture(self)
        self.assertEqual(config.candidate_codex_exes(), [fixture.exe])
        for path in (config.codex_bin_dir(), config.codex_home(), Path.home(),
                     Path(os.environ["APPDATA"]), fixture.app.lock_dir):
            self.assertTrue(path.resolve().is_relative_to(fixture.root), path)

    def other_spellings(self) -> dict:
        """Second spellings of one scratch folder: its 8.3 short name - how GitHub's runner
        spells TEMP, with its account folder as RUNNER~1 - and a junction to it."""
        base = tempfile.TemporaryDirectory()
        self.addCleanup(base.cleanup)
        real = Path(base.name).resolve() / "a-folder-with-a-long-name"
        real.mkdir()
        found = {}
        kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
        if kernel32 is not None:
            buffer = ctypes.create_unicode_buffer(32768)
            if (kernel32.GetShortPathNameW(str(real), buffer, len(buffer))
                    and os.path.normcase(buffer.value) != os.path.normcase(str(real))):
                found["short name"] = buffer.value
        try:
            import _winapi
            alias = real.parent / "junction"
            _winapi.CreateJunction(str(real), str(alias))
        except (ImportError, AttributeError, OSError):
            pass
        else:
            self.addCleanup(os.rmdir, alias)          # the junction itself, never its target
            found["junction"] = str(alias)
        return found

    def test_the_fake_engine_is_official_however_temp_is_spelt(self):
        spellings = self.other_spellings()
        if not spellings:
            self.skipTest("this volume offers no second spelling of a folder")
        for kind, spelt in spellings.items():
            with self.subTest(kind):
                with patch.object(tempfile, "tempdir", spelt):
                    fixture = Fixture(self)
                self.assertEqual(Path(os.environ["LOCALAPPDATA"]), fixture.local)
                backend = fixture.backend()
                self.assertEqual(backend.codex_exe, fixture.exe)
                self.assertEqual(backend.engine_version, "codex-cli 0.153.4")
                self.assertEqual(fixture.app.engine_state(), "structurally_compatible")


if __name__ == "__main__":
    unittest.main()
