"""The core audit's minor findings, each held where it was found (v0.6.18, plans/v0620-audit/core.md M1-M7).

M1 a watch with no default engine logs nothing every second; M2 `codex --version` output that is not UTF-8 is read,
not raised; M3 a queue delete that worked stays reported as worked when the helper is slow to go; M4 a clock set back
ends the usage and loaded caches; M5 a Codex home whose key changes with its folder's reach (a mapped network drive) is
never retired, nor its waiting records cancelled, on that alone; M6 every write that cancels a record gives it its
outcome time; M7 a resend's claim reads the conversation's day and spacing again, as a first claim does.

Its own module: the scenario modules are frozen (tests/neutral.py MODULES). Scratch folders, a scratch LOCALAPPDATA and
simulated Codex homes only; no process is started.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from codexsim import BASE, CodexHome
from codex_auto_resume import homes as configured
from codex_auto_resume.codex import appserver, transport
from codex_auto_resume.engine.freshness import FreshnessMixin
from codex_auto_resume.runtime import homes as runtime_homes
from codex_auto_resume.runtime.loop import WatchLoop
from codex_auto_resume.store import Store

from test_homes import App as HomesApp, T1, TURN
import test_plug_points as plug_points  # its cases are not bound here, so they run in their own module alone

THREAD = "11111111-1111-7111-8111-111111111111"
QUEUED = "22222222-2222-7222-8222-222222222222"


def failure(turn=TURN, key="d" * 64, thread=T1):
    return {"thread_id": thread, "turn_id": turn, "completed_at": BASE, "started_at": BASE - 5, "ordinal": 1,
            "interruption_id": key, "reset_at": None, "limit_type": "x", "uncertain": False,
            "category": "server_5xx"}


class Scratch(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()   # the backend resolves its exe; a runner's TEMP is an 8.3 short name


class WatchWithNoEngineTests(unittest.TestCase):
    def test_no_default_engine_is_no_failure_and_the_homes_are_still_watched(self):
        failures, watched, fired = [], [], iter([None, None, "stop"])
        homes = types.SimpleNamespace(watch_needed=lambda: True, watch=lambda: watched.append(1))
        loop = types.SimpleNamespace(_homes=homes, _wait_for=lambda stop, wake, seconds: next(fired),
                                     _record_failure=failures.append)
        self.assertEqual(WatchLoop._between_ticks(loop, None, None, None, 60, 0.0), "stop")
        self.assertEqual(failures, [], "nothing logged every second while the engine is rebuilt")
        self.assertEqual(len(watched), 2)


class VersionDecodeTests(Scratch):
    def test_a_version_that_is_not_utf8_is_read_not_raised(self):
        local = self.root / "local"
        exe = local / "OpenAI" / "Codex" / "bin" / "0abc" / "codex.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")

        def run(args, **options):
            output = b"codex-cli 0.163.0 \xff\n".decode(options["encoding"], options.get("errors", "strict"))
            return subprocess.CompletedProcess(args, 0, stdout=output)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}), patch.object(transport.S, "run", run), \
                patch.object(transport.Backend, "_queue_interface_ok", return_value=True):
            backend = transport.Backend(self.root / "codex", exe)
            checks = backend.engine_checks()
        self.assertEqual(checks["version_runs"], transport.PASS)
        self.assertTrue(checks["version"].startswith("codex-cli 0.163.0"))


class SlowHelperTests(Scratch):
    def test_a_delete_that_worked_stays_reported_as_worked(self):
        ended = []

        class Helper:
            stdin, stdout = None, None

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("codex", timeout)

            def terminate(self):
                ended.append(True)

        def enter(client):
            client.process = Helper()
            return client
        with patch.object(appserver.Protocol, "__enter__", enter), \
                patch.object(appserver.Protocol, "call", return_value={"deleted": True}):
            backend = transport.Backend(self.root / "codex", self.root / "codex.exe")
            self.assertIs(backend.delete_queue(THREAD, QUEUED), True)
        self.assertEqual(ended, [True], "ended once, as before; the second wait running out is not a failed delete")


class ClockSetBackTests(unittest.TestCase):
    class Reader(FreshnessMixin):
        def __init__(self):
            self.now, self.asked = 10_000.0, []
            self.clock = lambda: self.now
            self._usage_cache, self._loaded_cache = None, {}
            self.options = {"loaded_check_seconds": 5}
            self.backend = types.SimpleNamespace(
                usage=lambda: self.asked.append("usage") or {"available": True},
                app_identity=lambda: {"pid": 1},
                loaded=lambda thread, app: self.asked.append("loaded") or "loaded")

    def test_a_clock_set_back_ends_both_caches(self):
        reader = self.Reader()
        reader.usage(), reader.loaded(THREAD)
        reader.usage(), reader.loaded(THREAD)
        self.assertEqual(reader.asked, ["usage", "loaded"], "kept while fresh")
        reader.now -= 3600
        reader.usage(), reader.loaded(THREAD)
        self.assertEqual(reader.asked, ["usage", "loaded", "usage", "loaded"], "read again after the step back")


class HomeKeyTests(Scratch):
    def setUp(self):
        super().setUp()
        self.now = [BASE + 61]
        self.store = Store(self.root / "state")
        self.addCleanup(self.store.close)
        self.store.set_enabled(True, BASE)
        self.app = HomesApp(self.root, self.store, self.now)
        self.addCleanup(self.app._home_lock.__exit__, None, None, None)
        self.homes = runtime_homes.Homes(self.app, clock=lambda: self.now[0])
        self.addCleanup(self.homes.close)

    def configure(self, *paths):
        self.app.settings = {configured.FIELD: [{"path": str(path), "alias": "home %d" % index}
                                                for index, path in enumerate(paths)]}

    def test_a_key_that_changes_with_the_folder_s_reach_retires_nothing(self):
        path = self.root / "home-b"
        self.app.homes = {str(path): CodexHome(path)}
        self.configure(path)
        self.homes.sync(self.store)
        key = configured.key(path)
        self.assertIn(key, self.homes.runs)
        self.store.register(failure(), BASE, home_key=key)
        real = configured.key
        offline = "e" * 64
        with patch.object(configured, "key", lambda value: offline if Path(value) == path else real(value)):
            self.homes.sync(self.store)
        self.assertNotEqual(self.store.get("d" * 64)["state"], "cancelled", "its waiting record is kept")
        self.assertIn(key, self.homes.runs)
        self.assertFalse(self.homes.runs[key].retiring)
        self.homes.sync(self.store)
        self.assertFalse(self.homes.runs[key].retiring, "the same key again once the drive is back")

    def test_the_start_s_sweep_waits_while_a_named_home_is_out_of_reach(self):
        self.store.register(failure(), BASE, home_key="c" * 64)
        self.configure(self.root / "offline-drive")
        self.homes.sync(self.store)
        self.assertNotEqual(self.store.get("d" * 64)["state"], "cancelled", "that home may hold it under another key")
        self.configure()
        self.homes.sync(self.store)
        row = self.store.get("d" * 64)
        self.assertEqual((row["state"], row["last_error"]), ("cancelled", "home_removed"))


class OutcomeTimeTests(Scratch):
    def setUp(self):
        super().setUp()
        self.store = Store(self.root / "state")
        self.addCleanup(self.store.close)
        self.store.set_enabled(True, BASE)

    def register(self, key="d" * 64, turn=TURN, **options):
        self.store.register(failure(turn, key), BASE, **options)
        return key

    def test_a_cancelled_recovery_has_its_outcome_time(self):
        key = self.register()
        self.store.cancel_interruption(key, BASE + 10)
        self.assertEqual((self.store.get(key)["state"], self.store.get(key)["outcome_at"]), ("cancelled", BASE + 10))

    def test_a_conversation_switched_off_gives_its_records_their_outcome_time(self):
        key = self.register()
        self.store.cancel_thread(T1, BASE + 20)
        self.assertEqual((self.store.get(key)["state"], self.store.get(key)["outcome_at"]), ("cancelled", BASE + 20))

    def test_a_claim_released_to_an_end_has_its_outcome_time_and_one_released_to_wait_has_none(self):
        for target, expected in (("cancelled", BASE + 30), ("waiting_retry", None)):
            with self.subTest(target):
                key = self.register(key=("a" if expected else "b") * 64,
                                    turn="cccccccc-cccc-7ccc-8ccc-%012d" % len(target),
                                    state="waiting_retry", next_retry_at=BASE)
                claimed = self.store.reserve_detailed(key, BASE + 1)
                self.assertTrue(claimed[0], claimed)
                self.assertTrue(self.store.release_claim(key, target, "released_before_send", BASE + 30))
                row = self.store.get(key)
                self.assertEqual((row["state"], row["outcome_at"]), (target, expected))
                self.store.cancel_interruption(key, BASE + 40)


class ResendSpacingTests(plug_points.PluggedCase):
    uncertain = plug_points.ResendTests.uncertain

    def test_a_claim_committed_after_the_gate_holds_the_resend(self):
        h = self.h
        first, _plug = self.uncertain()
        key = first["interruption_id"]
        h.tick(advance=1)
        h.tick(advance=898)
        real = h.store.reserve_detailed

        def reserve(interruption_id, at, **options):
            if options.get("resend") is not None:
                # Another engine, or a worker settling, claims in this conversation between the gate and the claim.
                h.store.register(failure("bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb", "f" * 64, thread=first["thread_id"]),
                                 at)
                with h.store._transaction() as connection:
                    connection.execute("UPDATE interruptions SET last_claim_at=? WHERE interruption_id=?",
                                       (at, "f" * 64))
            return real(interruption_id, at, **options)
        h.store.reserve_detailed = reserve
        h.tick(advance=2)
        self.assertEqual(len(h.backend.send_calls), 1, "the spacing is read again in the claim")
        self.assertEqual(h.store.get(key)["state"], "submission_unknown", "a refused resend stays as it was")


if __name__ == "__main__":
    unittest.main()
