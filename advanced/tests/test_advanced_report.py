"""The compatibility report as a capability (registry.COMPAT_REPORT, report/flow.py): an action, off until
the Dashboard turns it on, written and saved while it is watched or on, checked and sent only while it is
on, never while recovery is paused, one check or send at a time per home across processes - and every
job's status readable whatever happened since.

Every home is reportfixtures' (a product home with records, a Codex home, the profile and LOCALAPPDATA
pointed into a temporary folder), every gh is ghfake's stand-in, and every policy and compatibility view
is the test's own, so nothing here reads this machine's installation, registry, Codex or GitHub. The
one real process is a python.exe helper of these tests' own that holds the report mutex.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import advancedcase as ac  # noqa: E402
import ghfake  # noqa: E402
from ghfake import LOGIN, FakeGh, pull  # noqa: E402
import reportfixtures as fixtures  # noqa: E402

from codex_auto_resume import control, controlcli  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Surface  # noqa: E402
from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced import plug as advanced, policy, registry, surfaces  # noqa: E402
from codex_auto_resume_advanced.registry import Registry, problems  # noqa: E402
from codex_auto_resume_advanced.report import document, flow, github, records  # noqa: E402
from codex_auto_resume_advanced.runtime import Runtime  # noqa: E402
from codex_auto_resume_advanced.statement import CATALOGS  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (BridgeCommand, CapabilityKind, ReportRefusal,  # noqa: E402
                                                   ReportStatus)

VERSION = "0.6.14-beta"
WINDOWS = "10.0.26200"
EXE = r"C:\Tools\gh\gh.exe"
ENGINE = "0.158.0"                                 # the watcher's report of reportfixtures names codex-cli 0.158.0
REPORT = "compat_report"
BUILD, SAVE, CHECK, SEND, JOB = (str(BridgeCommand.ADVANCED_REPORT_BUILD), str(BridgeCommand.ADVANCED_REPORT_SAVE),
                                 str(BridgeCommand.ADVANCED_REPORT_CHECK), str(BridgeCommand.ADVANCED_REPORT_SEND),
                                 str(BridgeCommand.ADVANCED_REPORT_JOB))


def receiver():
    spec = importlib.util.spec_from_file_location("community_report_for_flow_tests",
                                                  fixtures.ROOT / "build" / "community_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportCase(unittest.TestCase):
    """A product home with records, its advanced runtime and the Dashboard's long-lived bridge to it."""

    home_options = {}

    def setUp(self):
        self.fixture = fixtures.Home(fixtures.BASE, state=4, watcher_report=fixtures.watcher(), **self.home_options)
        self.addCleanup(self.fixture.close)
        isolated = fixtures.isolated(self.fixture)
        isolated.__enter__()
        self.addCleanup(isolated.__exit__, None, None, None)
        self.paths = self.fixture.paths
        self.gh = FakeGh()
        self.policy = policy.NONE
        self.view = ac.view(version=ENGINE)
        self.flows = []
        self.definition = dataclasses.replace(registry.COMPAT_REPORT, make=self.make)
        options = dict(registry=Registry((self.definition,)), clock=time.time, policy=lambda: self.policy,
                       view=lambda: self.view, measured=dict, catalogs=CATALOGS)
        self.plug = advanced.AdvancedPlug(self.paths, **options)
        self.addCleanup(lambda: self.plug._runtime and self.plug._runtime.state.close())
        self.control = control.Control(self.paths, plug=self.plug)

    def make(self, paths, **changes):
        options = dict(runner=lambda *a, **k: self.gh(*a, **k), find_gh=lambda: EXE, sleep=lambda _s: None,
                       product_version=VERSION, windows=WINDOWS, codex_home=self.fixture.codex,
                       view=self.fixture.raw_view)
        options.update(changes)
        made = flow.Flow(paths, **options)
        self.flows.append(made)
        return made

    @property
    def runtime(self) -> Runtime:
        return self.plug.runtime

    def bridge(self, command, argument=None) -> dict:
        request = {"id": 1, "command": command, "argument": argument or {}}
        out = __import__("io").StringIO()
        controlcli.serve(self.control, __import__("io").StringIO(json.dumps(request) + "\n"), out)
        reply = json.loads(out.getvalue())["reply"]
        self.assertTrue(reply["ok"], reply)
        return reply["result"]

    def turn(self, state):
        """The capability on (armed) or watched (shadow), as the Dashboard turns it."""
        shown = self.bridge("advanced-statement", {"capability": REPORT, "locale": "en"})
        done = self.bridge("advanced-arm", {"capability": REPORT, "state": state, "revision": shown["revision"],
                                            "generation": self.bridge("advanced-list")["generation"],
                                            "engine_version": shown["engine_version"],
                                            "warnings": [item["warning"] for item in shown["warnings"]["items"]]})
        self.assertTrue(done["done"], done)

    def finished(self, started) -> dict:
        self.assertTrue(started.get("done"), started)
        found = self.flows[-1].wait(started["job"])
        self.assertNotEqual(found["status"], "running")
        return found

    def written(self, login=LOGIN) -> dict:
        return self.finished(self.bridge(BUILD, {"login": login}))

    def checked(self, built) -> dict:
        return self.finished(self.bridge(CHECK, {"sha256": built["sha256"]}))

    def send(self, built, checked, word="send") -> dict:
        return self.bridge(SEND, {"sha256": built["sha256"], "writes": checked["writes"], "word": word})

    def set_enabled(self, value):
        """The recovery switch: 1 on, 0 paused, None gone - a switch nothing can read."""
        db = sqlite3.connect(self.paths.state_dir / "state.sqlite")
        try:
            if value is None:
                db.execute("DELETE FROM settings")
            else:
                db.execute("UPDATE settings SET enabled = ?", (value,))
            db.commit()
        finally:
            db.close()

    def refused(self, answer, code):
        self.assertEqual(answer, {"done": False, "refusal": str(code)})


class DefinitionTests(unittest.TestCase):
    def test_it_is_an_action_last_in_the_registry_departing_from_exactly_nine_standards(self):
        made = registry.REGISTRY.get(REPORT)
        self.assertIs(registry.DEFINITIONS[-1], made)
        self.assertEqual(made.kind, CapabilityKind.ACTION)
        self.assertEqual(made.departs_from, ("B11", "C1", "C2", "C3", "C8", "D1", "E8", "F3", "F6"))
        self.assertEqual(list(made.departs_from), sorted(made.departs_from))
        self.assertEqual((made.points, made.compat, made.ceilings, made.measurements), (frozenset(), None, None, ()))
        self.assertEqual(problems(made), [])
        self.assertEqual(made.journal_prefix, "rpt")
        for point in __import__("codex_auto_resume.domain.plug", fromlist=["Point"]).Point:
            self.assertNotIn(made, registry.REGISTRY.at(point))

    def test_its_refusals_hold_every_word_the_reader_and_the_file_refuse_with(self):
        words = {str(word) for word in ReportRefusal}
        self.assertLessEqual({str(word) for word in records.ReadRefusal}, words)
        self.assertLessEqual({str(word) for word in document.DocumentRefusal}, words)

    def test_no_mcp_tool_reaches_it_and_a_model_asking_for_one_is_deferred(self):
        self.assertFalse([tool for tool in surfaces.TOOLS if "report" in tool["name"]])
        for name in (BUILD, CHECK, SEND, "send_compat_report", "advanced_report_send"):
            self.assertIs(surfaces.mcp(None, {"request": "call", "tool": name, "arguments": {}}), DEFER)


class OffTests(ReportCase):
    def test_off_every_command_but_a_job_s_status_is_refused_and_nothing_is_read(self):
        with mock.patch.object(records, "read") as read, mock.patch.object(records, "paused") as paused:
            for command, argument in ((BUILD, {"login": LOGIN}), (SAVE, {"sha256": "0" * 64, "path": "x"}),
                                      (CHECK, {"sha256": "0" * 64}),
                                      (SEND, {"sha256": "0" * 64, "writes": [], "word": "send"})):
                with self.subTest(command):
                    self.refused(self.bridge(command, argument), "not_on")
            self.assertEqual(self.bridge(JOB, {"job": "anything"}), {"done": True, "status": "lost"})
            read.assert_not_called()
            paused.assert_not_called()
        self.assertEqual(self.gh.calls, [])

    def test_a_policy_refuses_it_before_anything_else(self):
        self.turn("armed")
        self.policy = policy.Policy(forbid=True)
        self.refused(self.bridge(BUILD, {"login": LOGIN}), "forbidden_by_policy")
        self.policy = policy.Policy(allowed=frozenset({"start_with_codex"}))
        self.refused(self.bridge(CHECK, {"sha256": "0" * 64}), "not_allowed_by_policy")
        self.assertEqual(self.gh.calls, [])

    def test_an_argument_it_does_not_take_is_refused(self):
        self.turn("armed")
        self.refused(self.bridge(BUILD, {"login": LOGIN, "codex_version": "codex-cli 0.1.0"}), "invalid_request")


class WatchedTests(ReportCase):
    def test_watched_it_is_written_read_and_saved_and_never_checked_or_sent(self):
        self.turn("shadow")
        built = self.written()
        self.assertEqual(built["status"], "built")
        target = self.fixture.root / "saved.json"
        self.assertEqual(self.bridge(SAVE, {"sha256": built["sha256"], "path": str(target)}),
                         {"done": True, "status": "saved"})
        self.assertEqual(target.read_bytes(), built["text"].encode("ascii"))
        self.refused(self.bridge(CHECK, {"sha256": built["sha256"]}), "watched")
        self.refused(self.send(built, {"writes": []}), "watched")
        self.assertEqual(self.gh.calls, [])

    def test_on_under_force_shadow_it_is_watched_by_policy(self):
        self.turn("armed")
        built = self.written()
        self.policy = policy.Policy(force_shadow=True)
        self.refused(self.bridge(CHECK, {"sha256": built["sha256"]}), "shadow_forced_by_policy")
        self.assertEqual(self.written()["status"], "built", "written and saved under ForceShadow still")
        self.assertEqual(self.gh.calls, [])


class WriteTests(ReportCase):
    def test_the_file_is_the_reporter_s_report_the_project_takes(self):
        self.turn("armed")
        built = self.written()
        raw = built["text"].encode("ascii")
        self.assertEqual(built["sha256"], __import__("hashlib").sha256(raw).hexdigest())
        self.assertEqual((built["bytes"], built["codex_version"], built["login"]), (len(raw), "codex-cli 0.158.0", LOGIN))
        self.assertEqual(built["file_name"], "codex-cli-0.158.0.json")
        report, refused, recomputed = receiver().inspect(raw, author=LOGIN, now=time.time() + 60)
        self.assertEqual((refused, recomputed), ([], []))
        self.assertEqual(json.loads(raw)["reporter"]["tool"], "codex-auto-resume")
        self.assertEqual(set(built["left_out"]), {"hidden", "another_route", "beyond_reach", "elsewhere", "unplaced"})

    def test_a_login_the_project_cannot_take_is_refused_before_anything_is_read(self):
        self.turn("armed")
        with mock.patch.object(records, "read") as read:
            for login, code in (("not a login", "login_invalid"), ("-dash", "login_invalid"), (None, "login_invalid"),
                                ("COM1", "login_reserved"), ("nul", "login_reserved"),
                                ("songyb111-gachon", "login_owner")):
                with self.subTest(login):
                    self.refused(self.bridge(BUILD, {"login": login}), code)
            read.assert_not_called()

    def test_records_that_cannot_be_read_are_a_refused_job(self):
        self.turn("armed")
        (self.paths.state_dir / "state.sqlite").write_bytes(b"not a database")
        self.assertEqual(self.written(), {"done": True, "job": mock.ANY, "status": "refused",
                                          "refusal": "state_unreadable"})

    def test_saving_never_writes_over_a_file_and_needs_a_report_this_process_wrote(self):
        self.turn("armed")
        built = self.written()
        target = self.fixture.root / "there.json"
        target.write_text("mine", encoding="utf-8")
        self.refused(self.bridge(SAVE, {"sha256": built["sha256"], "path": str(target)}), "file_exists")
        self.assertEqual(target.read_text(encoding="utf-8"), "mine")
        self.refused(self.bridge(SAVE, {"sha256": "f" * 64, "path": str(self.fixture.root / "new.json")}),
                     "unknown_build")
        self.refused(self.bridge(SAVE, {"sha256": built["sha256"], "path": "relative.json"}), "save_failed")

    def test_the_journal_holds_its_codes_and_nothing_else(self):
        self.turn("armed")
        self.written()
        lines = [line["code"] for line in self.runtime.state.journal(capability=REPORT)]
        self.assertIn("rpt.built", lines)
        self.assertTrue(all(code.startswith("rpt.") or code in ("armed", "watched", "disarmed") for code in lines))


class SendTests(ReportCase):
    def test_on_it_is_checked_and_sent_as_shown_with_exactly_the_word(self):
        self.turn("armed")
        built = self.written()
        checked = self.checked(built)
        self.assertEqual(checked["status"], "checked")
        self.assertEqual((checked["gh"], checked["who"], checked["interrupted"]), (EXE, LOGIN, False))
        self.assertEqual([write["kind"] for write in checked["writes"]], ["fork_new", "branch_new", "file", "pr"])
        self.assertEqual(self.gh.writes(), [], "a check only reads")
        for word in ("Send", " send", "send ", "SEND", "send\n", "", None, "yes"):
            with self.subTest(word=word):
                self.refused(self.send(built, checked, word), "word")
        self.assertEqual(self.gh.writes(), [])
        sent = self.finished(self.send(built, checked))
        self.assertEqual(sent["status"], "sent")
        self.assertEqual((sent["url"], sent["already"]), ("https://github.com/%s/pull/42" % github.REPOSITORY, False))
        (put,) = [call for call in self.gh.calls if "PUT" in call["argv"]]
        self.assertEqual(ghfake.uploaded(put), built["text"].encode("ascii"))
        self.assertTrue(all(call["creationflags"] & NO_WINDOW for call in self.gh.calls))
        self.assertTrue(all(call["cwd"] == str(self.paths.advanced_dir) for call in self.gh.calls))
        codes = [line["code"] for line in self.runtime.state.journal(capability=REPORT)]
        self.assertEqual([code for code in codes if code.startswith("rpt.")], ["rpt.built", "rpt.checked", "rpt.sent"])

    def test_a_changed_report_or_writes_list_writes_nothing(self):
        self.turn("armed")
        built = self.written()
        checked = self.checked(built)
        self.refused(self.bridge(SEND, {"sha256": "e" * 64, "writes": checked["writes"], "word": "send"}),
                     "unknown_build")
        self.refused(self.bridge(SEND, {"sha256": built["sha256"], "writes": checked["writes"][:3], "word": "send"}),
                     "changed")
        self.refused(self.bridge(SEND, {"sha256": built["sha256"], "writes": "all of them", "word": "send"}),
                     "changed")
        # GitHub changed after the check: a fork now exists, so the writes are not the ones read.
        self.gh.fork = "fork"
        self.assertEqual(self.finished(self.send(built, checked))["refusal"], "changed")
        self.assertEqual(self.gh.writes(), [])

    def test_a_report_written_but_never_checked_cannot_be_sent(self):
        self.turn("armed")
        built = self.written()
        self.refused(self.send(built, {"writes": []}), "changed")
        self.assertEqual(self.gh.calls, [])

    def test_an_open_pull_request_of_the_same_file_is_sent_already(self):
        self.turn("armed")
        built = self.written()
        branch = "compat-report/codex-cli-0.158.0"
        target = "docs/evidence/community/%s/codex-cli-0.158.0.json" % LOGIN
        self.gh = FakeGh(fork="fork", branch=True, pulls=[pull(ref=branch, number=5)],
                         contents={(target, branch): github.blob_sha(built["text"].encode("ascii"))})
        checked = self.checked(built)
        self.assertEqual(checked, {"done": True, "job": mock.ANY, "status": "sent",
                                   "url": "https://github.com/%s/pull/5" % github.REPOSITORY, "already": True})
        self.assertEqual(self.gh.writes(), [])

    def test_no_gh_or_another_sign_in_is_the_web(self):
        self.turn("armed")
        built = self.written()
        self.gh = FakeGh(who="SomeoneElse")
        web = self.checked(built)
        self.assertEqual((web["status"], web["why"], web["who"], web["login"]), ("web", "gh_other_login", "SomeoneElse",
                                                                              LOGIN))
        self.assertEqual((web["branch"], web["file_name"], web["project_page"]),
                         ("compat-report/codex-cli-0.158.0", "codex-cli-0.158.0.json", github.PROJECT_PAGE))

    def test_a_hung_gh_is_ended_and_refused(self):
        self.turn("armed")
        built = self.written()
        self.gh = FakeGh(hang=("user",))
        self.assertEqual(self.checked(built)["refusal"], "gh_timeout")

    def test_the_spend_ledger_is_untouched_by_a_send(self):
        self.turn("armed")
        built = self.written()

        def ledger():
            db = sqlite3.connect(self.paths.advanced_dir / "advanced.sqlite")
            try:
                return (db.execute("SELECT * FROM spend").fetchall(),
                        db.execute("SELECT * FROM sqlite_sequence WHERE name = 'spend'").fetchall())
            finally:
                db.close()
        before = ledger()
        self.finished(self.send(built, self.checked(built)))
        self.assertEqual(ledger(), before)

    def test_a_new_codex_version_turns_it_off_and_refuses_the_send(self):
        self.turn("armed")
        built = self.written()
        checked = self.checked(built)
        self.view = ac.view(version="0.159.0")
        self.refused(self.send(built, checked), "not_on")
        item = next(entry for entry in self.bridge("advanced-list")["capabilities"] if entry["id"] == REPORT)
        self.assertEqual((item["stored"], item["reason"]), ("off", "engine_changed"))
        self.assertEqual(self.gh.writes(), [])


class StoppedTests(ReportCase):
    """A send stopped part way: by a turn-off, a policy or a pause committed while it writes. It stops
    before its next write, and its status - what was written - is read whatever stands after."""

    def stopped(self, change, code):
        self.turn("armed")
        built = self.written()
        checked = self.checked(built)
        answer = self.gh.answer

        def answering(words):
            if words[:1] == ["api"] and "repos/%s/forks" % github.REPOSITORY in words:
                change()
            return answer(words)
        self.gh.answer = answering
        status = self.finished(self.send(built, checked))
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["written"], [{"kind": "fork_new", "name": "%s/%s" % (LOGIN, github.NAME)}])
        self.assertEqual(status["refusal"], code)
        self.assertEqual(self.gh.writes(), [("POST", "repos/%s/forks" % github.REPOSITORY)], "nothing after the stop")
        calls = len(self.gh.calls)
        with mock.patch.object(sqlite3, "connect", side_effect=AssertionError("a file was opened")), \
                mock.patch.object(records, "paused", side_effect=AssertionError("the pause was read")):
            self.assertEqual(self.bridge(JOB, {"job": status["job"]}), status)
        self.assertEqual(len(self.gh.calls), calls, "reading a status starts nothing")

    def test_turned_off_mid_send(self):
        self.stopped(lambda: self.runtime.arming.disarm(REPORT, actor="mcp"), "not_on")

    def test_force_shadow_mid_send(self):
        self.stopped(lambda: setattr(self, "policy", policy.Policy(force_shadow=True)), "shadow_forced_by_policy")

    def test_forbid_advanced_mid_send(self):
        self.stopped(lambda: setattr(self, "policy", policy.Policy(forbid=True)), "forbidden_by_policy")

    def test_paused_mid_send(self):
        self.stopped(lambda: self.set_enabled(0), "paused")

    def test_a_fault_of_its_own_turns_it_off(self):
        self.turn("armed")
        built = self.written()
        checked = self.checked(built)
        with mock.patch.object(github, "publish", side_effect=KeyError("a fault")):
            status = self.finished(self.send(built, checked))
        self.assertEqual((status["status"], status["refusal"]), ("refused", "not_on"))
        item = next(entry for entry in self.bridge("advanced-list")["capabilities"] if entry["id"] == REPORT)
        self.assertEqual((item["stored"], item["reason"]), ("off", "hook_exception"))

    def test_a_job_this_process_does_not_hold_is_lost(self):
        self.turn("armed")
        for job in ("0" * 16, "", None, 7):
            with self.subTest(job=job):
                self.assertEqual(self.bridge(JOB, {"job": job}), {"done": True, "status": "lost"})


class PausedTests(ReportCase):
    home_options = {"enabled": False}

    def test_paused_it_is_written_and_saved_and_never_checked_or_sent(self):
        self.turn("armed")
        built = self.written()
        self.assertEqual(built["status"], "built")
        target = self.fixture.root / "paused.json"
        self.assertEqual(self.bridge(SAVE, {"sha256": built["sha256"], "path": str(target)})["status"], "saved")
        self.refused(self.bridge(CHECK, {"sha256": built["sha256"]}), "paused")
        self.refused(self.send(built, {"writes": []}), "paused")
        self.assertEqual(self.gh.calls, [])

    def test_a_switch_that_cannot_be_read_refuses_the_check_and_the_send(self):
        self.turn("armed")
        built = self.written()
        self.set_enabled(1)
        checked = self.checked(built)
        self.set_enabled(None)
        self.refused(self.send(built, checked), "state_unreadable")
        self.refused(self.bridge(CHECK, {"sha256": built["sha256"]}), "state_unreadable")
        self.assertEqual(self.gh.writes(), [])


HOLDER = """
import sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from codex_auto_resume.win.sync import Mutex
lock = Mutex(sys.argv[3], timeout=5)
lock.__enter__()
print("held", flush=True)
sys.stdin.read()
"""
# The Dashboard's only service, taking the home's report mutex as a send does and ending while it holds
# it - the window closed or reopened, or a call passed thirty seconds - with no other process holding
# the mutex open.
DIES_HOLDING = """
import os, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from codex_auto_resume import config
from codex_auto_resume_advanced.report import flow
flow.ReportMutex(config.Paths(sys.argv[3])).take()
os._exit(7)
"""


@unittest.skipUnless(os.name == "nt", "the report mutex is Windows'")
class MutexTests(ReportCase):
    def test_another_process_holding_the_report_makes_it_busy_and_its_death_is_told(self):
        self.turn("armed")
        built = self.written()
        before = self.checked(built)
        self.gh.calls.clear()
        name = str(self.paths.advanced_dir / flow.MUTEX_NAME)
        holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(fixtures.ROOT / "advanced" / "src"),
                                   str(fixtures.ROOT / "src"), name], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=dict(os.environ), creationflags=NO_WINDOW)
        try:
            self.assertEqual(holder.stdout.readline().strip(), b"held")
            self.refused(self.bridge(CHECK, {"sha256": built["sha256"]}), "busy")
            self.refused(self.send(built, before), "busy")
            self.assertEqual(self.gh.calls, [], "nothing was asked of GitHub while another held it")
            self.assertEqual(self.bridge(JOB, {"job": "x"})["status"], "lost")
        finally:
            holder.kill()                                  # dies holding it: Windows hands it on as abandoned
            holder.wait()
            holder.stdin.close()
            holder.stdout.close()
        checked = self.checked(built)
        self.assertEqual((checked["status"], checked["interrupted"]), ("checked", True))
        self.assertIn("rpt.lost", [line["code"] for line in self.runtime.state.journal(capability=REPORT)])
        self.assertFalse(self.checked(built)["interrupted"], "said once, by the check that found it")

    def test_a_send_whose_only_service_ended_part_way_is_told_from_what_github_holds(self):
        """No other process had the mutex open, so Windows hands nothing on: the branch the send left on
        the fork with no pull request open is what tells the next check. A fork alone tells nothing."""
        self.turn("armed")
        built = self.written()                             # writing takes no mutex: this process never opened it
        died = subprocess.run([sys.executable, "-c", DIES_HOLDING, str(fixtures.ROOT / "advanced" / "src"),
                               str(fixtures.ROOT / "src"), str(self.paths.home)], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=dict(os.environ),
                              creationflags=NO_WINDOW, timeout=60)
        self.assertEqual(died.returncode, 7, died.stderr[-2000:])
        self.gh = FakeGh(fork="fork")
        checked = self.checked(built)
        self.assertEqual((checked["status"], checked["interrupted"]), ("checked", False),
                         "the mutex alone told it: Windows handed it on although nobody else had it open")
        self.gh = FakeGh(fork="fork", branch=True)         # GitHub as a send cut off after its branch leaves it
        checked = self.checked(built)
        self.assertEqual((checked["status"], checked["interrupted"]), ("checked", True))
        self.assertEqual([write["kind"] for write in checked["writes"]], ["fork_kept", "branch_reset", "file", "pr"])
        self.assertEqual(self.gh.writes(), [], "a check only reads")
        sent = self.finished(self.send(built, checked))
        self.assertEqual(sent["status"], "sent", "sending again is safe")

    def test_one_job_at_a_time_in_this_process(self):
        self.turn("armed")
        built = self.written()
        gate = __import__("threading").Event()
        answer = self.gh.answer

        def slow(words):
            gate.wait(10)
            return answer(words)
        self.gh.answer = slow
        started = self.bridge(CHECK, {"sha256": built["sha256"]})
        self.assertTrue(started["done"])
        self.refused(self.bridge(BUILD, {"login": LOGIN}), "busy")
        self.refused(self.bridge(CHECK, {"sha256": built["sha256"]}), "busy")
        self.assertEqual(self.bridge(JOB, {"job": started["job"]})["status"], "running")
        gate.set()
        self.assertEqual(self.finished(started)["status"], "checked")


if __name__ == "__main__":
    unittest.main()
