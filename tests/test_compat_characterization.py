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
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from codexsim import APP, CodexHome, SimBackend  # noqa: E402
from codex_auto_resume import config, machine, windows  # noqa: E402
from codex_auto_resume.app import App  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.source import LocalSource  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402

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
        root = Path(self.folder.name)
        self.local = root / "local"
        self.exe = self.local / "OpenAI" / "Codex" / "bin" / "abcdef0123456789" / "codex.exe"
        if binary:
            self.exe.parent.mkdir(parents=True)
            self.exe.write_bytes(b"MZ-first-build")
        self.codex = codex or FakeCodex()
        self.home = CodexHome(root / "codex-home")
        self.paths = config.Paths(root / "car-home")
        self.paths.ensure()
        environment = {"LOCALAPPDATA": str(self.local), "CODEX_HOME": str(self.home.root)}
        guard = patch.dict(os.environ, environment)
        guard.start()
        case.addCleanup(guard.stop)
        os.environ.pop(config.ENV_CODEX_EXE, None)
        runner = patch.object(windows.S, "run", side_effect=self.codex.run)
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


if __name__ == "__main__":
    unittest.main()
