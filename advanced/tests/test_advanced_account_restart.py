"""account_switch's button ends with a Codex restart the person agrees to (v0.6.20 final, the owner: ask, then restart).

Measured on codex-cli 0.166 (2026-11-01, MAL failed partial): an outside `codex login` does not reach the running Codex
app - its long-lived app server never reads the sign-in again - and only a full restart of the app brings it up signed
in. So a sign-in from the card leaves it asking "Restart Codex now so it uses the new account?": Restart - only while no
turn runs, no recovery waits or runs and nothing is queued in Codex - asks Windows to close the app, ends its main
process only if that did not end it, starts it again through its own codex: link and reads the account afresh
(codex/restart.py); Not now leaves the card saying Codex needs a restart (control/account.restart). The button rests on
MALR, this route measured, whose probe drives the same restart (measure._malr).

Every process, link, session and read here is a fake, and every home a temporary folder: nothing is ended, started or
asked of a real Codex.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_account_switch import CardCase  # noqa: E402
from test_advanced_measure_mal import CachedSession, Disk, signed  # noqa: E402
from test_advanced_measure_stage4 import THREAD, VERSIONS, Backend  # noqa: E402
from codex_auto_resume_advanced import measure, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import account, protocol, restart  # noqa: E402
from codex_auto_resume_advanced.control import account as card  # noqa: E402
from codex_auto_resume_advanced.registry import ACCOUNT_SWITCH  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement, Refusal, Verdict  # noqa: E402

CONVERSATION = "00000000-0000-7000-8000-00000000000a"
ADDRESS = "someone@example.com"


def app_path(name="ChatGPT.exe"):
    root = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
    return str(Path(root) / "WindowsApps" / "OpenAI.Codex_26.1101.0.0_x64__2p2nqsd0c76g0" / "app" / name)


class World:
    """The Codex app as Windows shows it: its main process (pid, creation time) or none, and what a request to close
    it, an end of its process and a link handed to Windows do. Each knob says how this app behaves."""

    def __init__(self, *, running=True, closes=True, ends=True, starts=True, comes_back=True, conversation=CONVERSATION,
                 signed_in=True):
        self.main = (4100, 1111) if running else None
        self.closes, self.ends, self.starts, self.comes_back = closes, ends, starts, comes_back
        self.conversation, self.signed_in = conversation, signed_in
        self.calls = []
        self.time = 0.0

    # Hands
    def inventory(self):
        if self.main is None:
            return []
        pid = self.main[0]
        return [{"pid": pid, "parent": 1, "path": app_path()},
                {"pid": pid + 1, "parent": pid, "path": app_path("ChatGPT.exe")},
                {"pid": pid + 2, "parent": pid, "path": str(Path(app_path()).parent / "resources" / "codex.exe")}]

    def created(self, pid):
        return self.main[1] if self.main is not None and self.main[0] == pid else None

    def ask_close(self, pid, created):
        self.calls.append(("ask_close", pid, created))
        if self.closes:
            self.main = None
            return True
        return False

    def end_process(self, pid, created):
        self.calls.append(("end_process", pid, created))
        if self.ends and self.main == (pid, created):
            self.main = None
            return True
        return False

    def newest_conversation(self):
        return self.conversation

    def open(self, link):
        self.calls.append(("open", link))
        if self.starts and self.comes_back:
            self.main = (4200, 2222)
        return self.starts

    def read(self):
        self.calls.append(("read",))
        return account.parse({"account": {"type": "chatgpt", "email": ADDRESS, "planType": "pro"}}
                             if self.signed_in else {"account": None})

    def now(self):
        return self.time

    def sleep(self, seconds):
        self.time += max(seconds, 1.0)

    def kinds(self):
        return [call[0] for call in self.calls]


class RestartRouteTests(unittest.TestCase):
    def test_closed_on_windows_request_started_again_and_read_afresh(self):
        world = World()
        self.assertEqual(restart.restart(None, hands=world), (restart.RESTARTED, restart.CLOSED))
        self.assertEqual(world.kinds(), ["ask_close", "open", "read"])
        self.assertEqual(world.calls[0], ("ask_close", 4100, 1111))
        self.assertEqual(world.calls[1], ("open", "codex://threads/" + CONVERSATION))

    def test_its_process_is_ended_only_when_the_request_did_not_end_it(self):
        world = World(closes=False)
        self.assertEqual(restart.restart(None, hands=world), (restart.RESTARTED, restart.ENDED))
        self.assertEqual(world.kinds(), ["ask_close", "end_process", "open", "read"])
        self.assertEqual(world.calls[1], ("end_process", 4100, 1111), "the same process, by its creation time")

    def test_an_app_that_neither_closes_nor_ends_is_not_started_again(self):
        world = World(closes=False, ends=False)
        self.assertEqual(restart.restart(None, hands=world), (restart.NOT_ENDED, None))
        self.assertNotIn("open", world.kinds())

    def test_no_app_running_is_nothing_to_restart(self):
        world = World(running=False)
        self.assertEqual(restart.restart(None, hands=world), (restart.NOT_RUNNING, None))
        self.assertEqual(world.calls, [])

    def test_two_mains_are_never_guessed_between(self):
        world = World()
        rows = world.inventory() + [{"pid": 9000, "parent": 1, "path": app_path()}]
        world.inventory = lambda: rows
        self.assertEqual(restart.restart(None, hands=world), (restart.FAILED, None))
        self.assertEqual(world.calls, [])

    def test_no_conversation_to_open_or_no_app_after_it_is_not_started(self):
        world = World(conversation=None)
        self.assertEqual(restart.restart(None, hands=world), (restart.NOT_STARTED, restart.CLOSED))
        world = World(comes_back=False)
        self.assertEqual(restart.restart(None, hands=world), (restart.NOT_STARTED, restart.CLOSED))
        self.assertNotIn("read", world.kinds())

    def test_restarted_signed_out_says_so(self):
        self.assertEqual(restart.restart(None, hands=World(signed_in=False)), (restart.SIGNED_OUT, restart.CLOSED))

    def test_the_waits_are_bounded(self):
        self.assertEqual((restart.END_SECONDS, restart.KILL_SECONDS, restart.START_SECONDS), (30, 15, 60))


class Turns:
    def __init__(self, running=(), queued=0, broken=False):
        self._running, self._queued, self.broken = list(running), queued, broken

    def running(self):
        if self.broken:
            raise RuntimeError("unread")
        return self._running

    def queued(self):
        return self._queued


class Store:
    def __init__(self, *rows):
        self.rows = list(rows)

    def pending(self):
        return self.rows


class BusyTests(unittest.TestCase):
    def test_clear_only_when_nothing_runs_waits_or_is_queued(self):
        self.assertEqual(restart.busy(None, turns=Turns(), store=Store()), ())
        self.assertEqual(restart.busy(None, turns=Turns(running=[CONVERSATION]), store=Store()), (restart.TURN_RUNNING,))
        self.assertEqual(restart.busy(None, turns=Turns(queued=1), store=Store()), (restart.QUEUED,))
        self.assertEqual(restart.busy(None, turns=Turns(), store=Store({"hold": None, "cancel_requested": 0})),
                         (restart.RECOVERY,))

    def test_a_recovery_a_hold_keeps_for_the_person_does_not_block(self):
        """A change of account holds waiting recoveries for the person (engine/account.py): they wait on them, not on
        Codex, and a restart does not touch them."""
        self.assertEqual(restart.busy(None, turns=Turns(), store=Store({"hold": "account_changed"})), ())

    def test_a_reading_that_fails_is_busy(self):
        self.assertEqual(restart.busy(None, turns=Turns(broken=True), store=Store()), (restart.UNKNOWN,))


class RestartCardCase(CardCase):
    def setUp(self):
        super().setUp()
        self.busy = ()
        patcher = patch.object(restart, "busy", lambda paths, **unused: self.busy)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.restarts = []

    def measure(self):
        self.measured[Measurement.MALR] = (Verdict.PASS, ac.ENGINE)

    def signed_in(self):
        self.on()
        self.measure()
        self.outcome = account.SIGNED_IN
        self.start()
        self.jobs.pop()()

    def press(self, now, outcome=(restart.RESTARTED, restart.CLOSED)):
        return card.restart(self.rt, {"now": now}, start=self.jobs.append,
                            run=lambda paths: self.restarts.append(paths) or outcome)


class RestartCardTests(RestartCardCase):
    def test_a_sign_in_leaves_the_restart_asked_and_the_card_unread_meanwhile(self):
        self.signed_in()
        reads = len(self.reads)
        answer = card.view(self.rt, reader=self.reader)
        self.assertEqual((answer["switch"], answer["restart"], answer["busy"], answer["present"], answer["plan"]),
                         (account.SIGNED_IN, card.ASK, [], True, "plus"))
        self.assertEqual(len(self.reads), reads, "the account is not read again while the restart is asked")
        self.assertNotIn(ADDRESS, str(answer))

    def test_not_now_says_codex_needs_a_restart_and_still_offers_it(self):
        self.signed_in()
        self.assertEqual(self.press(False), {"done": True, "refusal": None, "restart": card.NOT_NOW})
        self.assertEqual(card.view(self.rt, reader=self.reader)["restart"], card.NOT_NOW)
        self.assertEqual(self.press(True)["restart"], card.RESTARTING)

    def test_never_under_a_running_turn_and_offered_again_when_clear(self):
        self.signed_in()
        self.busy = (restart.TURN_RUNNING,)
        self.assertEqual(self.press(True)["refusal"], Refusal.RESTART_BUSY)
        self.assertEqual(self.jobs, [])
        answer = card.view(self.rt, reader=self.reader)
        self.assertEqual((answer["restart"], answer["busy"]), (card.ASK, [restart.TURN_RUNNING]))
        self.busy = ()
        self.assertEqual(card.view(self.rt, reader=self.reader)["busy"], [])
        self.assertEqual(self.press(True)["restart"], card.RESTARTING)

    def test_a_restart_runs_once_says_how_it_ended_and_is_counted(self):
        self.signed_in()
        self.assertEqual(self.press(True)["restart"], card.RESTARTING)
        self.assertEqual(self.press(True)["refusal"], Refusal.RESTART_RUNNING)
        self.assertEqual(card.view(self.rt, reader=self.reader)["restart"], card.RESTARTING)
        self.jobs.pop()()
        reads = len(self.reads)
        answer = card.view(self.rt, reader=self.reader)
        self.assertEqual(answer["restart"], restart.RESTARTED)
        self.assertEqual(len(self.reads), reads + 1, "read afresh once it has ended")
        codes = self.codes()
        for code in ("account.restart_asked", "account.codex_closed", "account.restarted"):
            self.assertIn(code, codes)
        self.assertEqual(self.press(True)["refusal"], Refusal.NOTHING_TO_RESTART)

    def test_a_restart_that_did_not_end_codex_may_be_pressed_again(self):
        self.signed_in()
        self.press(True, outcome=(restart.NOT_ENDED, None))
        self.jobs.pop()()
        self.assertIn("account.restart_failed", self.codes())
        self.assertEqual(self.press(True)["restart"], card.RESTARTING)

    def test_no_sign_in_nothing_to_restart_and_a_bad_answer_is_refused(self):
        self.on()
        self.measure()
        self.assertEqual(self.press(True)["refusal"], Refusal.NOTHING_TO_RESTART)
        self.assertEqual(card.restart(self.rt, {"now": "yes"})["refusal"], Refusal.INVALID_REQUEST)
        self.assertEqual(card.restart(self.rt, {})["refusal"], Refusal.INVALID_REQUEST)

    def test_refused_off_and_before_malr_passed(self):
        self.assertEqual(self.press(True)["refusal"], Refusal.NOT_ON)
        self.on()
        self.assertEqual(self.press(True)["refusal"], Refusal.SWITCH_UNMEASURED)
        self.measured[Measurement.MAL] = (Verdict.PASS, ac.ENGINE)
        self.assertEqual(self.press(True)["refusal"], Refusal.SWITCH_UNMEASURED, "MAL alone no longer offers it")

    def test_the_bridge_answers_for_the_dashboard_alone(self):
        self.assertEqual(surfaces.bridge(self.rt, "advanced-account-restart", {"now": True})["refusal"], Refusal.NOT_ON)
        self.assertEqual(surfaces.bridge(self.rt, "advanced-account-restart", {"x": 1})["refusal"],
                         Refusal.INVALID_REQUEST)
        self.assertFalse([tool["name"] for tool in surfaces.TOOLS if "restart" in tool["name"]])

    def test_the_statement_says_it_may_restart_codex_after_asking_and_departs_from_e8(self):
        self.assertIn("E8", ACCOUNT_SWITCH.departs_from)
        self.assertEqual(ACCOUNT_SWITCH.narrowed_by, (Measurement.MALR,))
        from codex_auto_resume_advanced import statement
        words = statement.CATALOGS["en"] if isinstance(statement.CATALOGS, dict) and "en" in statement.CATALOGS else None
        if words is None:
            words = json.loads((Path(statement.__file__).parent / "locales" / "en.json").read_text(encoding="utf-8"))
        does = words["statement.account_switch.does"]
        self.assertIn("Restart Codex now so it uses the new account?", does)
        self.assertIn("ends its process", does)
        self.assertIn("E8", words["statement.account_switch.departs"])


class MalrTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        for name, value in (("_MAL_SECONDS", 0.5), ("_MAL_POLL_SECONDS", 0.0)):
            patcher = patch.object(measure, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sessions, self.restarted = [], []

    def run_malr(self, disk, answer):
        def factory(measured):
            self.sessions.append(CachedSession(disk))
            return self.sessions[-1]

        def codex_restart(home, read):
            self.restarted.append(home)
            found = dict(answer)
            if found.get("outcome") in ("restarted", "restarted_signed_out"):
                read()
            return found
        summary = measure.run(Measurement.MALR, session_factory=factory, backend=Backend(), versions=VERSIONS,
                              thread=THREAD, clock=lambda: 1_800_000_000.0, directory=self.dir,
                              hands={"codex_restart": codex_restart})
        text = Path(summary["recorded"]).read_text(encoding="utf-8")
        self.assertNotIn(ADDRESS, text)
        self.assertNotIn(THREAD, text)
        self.assertNotIn("\\", json.loads(text)["note"] or "")
        return json.loads(text)

    def test_after_the_sign_in_it_restarts_codex_as_the_card_does_and_reads_afresh(self):
        disk = Disk(signed("plus"), {"account": None}, signed("pro"))
        record = self.run_malr(disk, {"outcome": "restarted", "how": "closed"})
        observed = record["observed"]
        self.assertEqual(record["verdict"], "blocked", record)
        self.assertEqual((observed["signed_out_seen"], observed["signed_in_again_seen"], observed["restart_outcome"],
                          observed["codex_ended_by"], observed["signed_in_after_restart"]),
                         (True, True, "restarted", "closed", True))
        self.assertEqual(len(self.restarted), 1)
        self.assertIn("without its own sign-in page", record["note"])

    def test_no_sign_in_after_the_sign_out_restarts_nothing(self):
        record = self.run_malr(Disk(signed("plus")), {"outcome": "restarted"})
        self.assertEqual((record["verdict"], self.restarted), ("blocked", []))

    def test_busy_codex_is_not_restarted(self):
        record = self.run_malr(Disk(signed("plus"), {"account": None}, signed("plus")), {"busy": ["turn_running"]})
        self.assertEqual((record["verdict"], record["observed"]["busy_turn_running"],
                          record["observed"]["restart_outcome"]), ("blocked", True, None))

    def test_a_route_that_does_not_end_or_start_codex_fails(self):
        for outcome in ("not_ended", "not_started"):
            with self.subTest(outcome):
                record = self.run_malr(Disk(signed("plus"), {"account": None}, signed("plus")), {"outcome": outcome})
                self.assertEqual((record["verdict"], record["observed"]["restart_outcome"]), ("fail", outcome))

    def test_it_calls_what_mal_calls_and_has_a_probe(self):
        self.assertIn(Measurement.MALR, measure.PROBES)
        self.assertEqual(protocol.methods_for(Measurement.MALR), protocol.methods_for(Measurement.MAL))

    def test_the_live_hand_is_the_products_restart(self):
        """The probe's hand runs codex/restart.busy and codex/restart.restart with the product's own hands, the probe's
        home and read given in."""
        hands = measure.live_hands(backend=Backend(), paths=None)
        seen = {}

        def fake_restart(paths, hands=None):
            seen["hands"] = hands
            return restart.RESTARTED, restart.CLOSED
        with patch.object(restart, "busy", lambda paths, **kw: ()), patch.object(restart, "restart", fake_restart):
            answered = hands["codex_restart"](Path("home"), lambda: {"present": True})
        self.assertEqual(answered, {"outcome": "restarted", "how": "closed"})
        self.assertIsInstance(seen["hands"], restart.Hands)
        self.assertEqual(seen["hands"].read(), {"present": True})


if __name__ == "__main__":
    unittest.main()
