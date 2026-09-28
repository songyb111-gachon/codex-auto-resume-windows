"""v0.6.11: the Custom retry ladder, a time ceiling, jitter and a named Retry-After; the task-changed
and context-cost guards; and a budget shown as it is ("19/6"), with a notice when limits are high.

Every one is off - or, for the Custom waits, inert - at the defaults, and then the watcher reads
nothing new and waits exactly as v0.6.10 waited (tests/test_defaults_golden.py holds the defaults,
and DefaultTests below the reads). Each can only hold a recovery back, lengthen a wait or stop a task
sooner; none sends, skips a gate or makes anything sooner, and the engine floor of A20 - a
continuation to one conversation at most every 15 minutes, five in 24 hours - binds whatever is
chosen: the Custom lists start at it, and the engine keeps it as it always did.
"""
from __future__ import annotations

from contextlib import closing
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codexsim import CodexHome  # noqa: E402
from codex_auto_resume import failures, guards, ladder, machine, notifier, notify, settings  # noqa: E402
from codex_auto_resume.codex import LocalSource, normalize, workspace  # noqa: E402
from codex_auto_resume.mcp import tools as mcp_tools  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_control import THREAD, ControlTestCase, detection  # noqa: E402
from test_engine import T1  # noqa: E402
from test_observe_and_admission import Spy  # noqa: E402
from test_recovery import Base, ChainBase, dispatch_and_fail  # noqa: E402


class Fixed:
    """A draw that is always the same, for jitter."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def policy(h, **values):
    h.engine.apply_policy(dict(settings.defaults(), **values))


def named_wait(seconds, code="serverOverloaded"):
    """A temporary failure whose structured error names a wait (a Retry-After)."""
    return json.dumps({"codexErrorInfo": {code: {"retryAfterSeconds": seconds}}})


def columns(h, **declared):
    """Give Codex's threads table the columns a newer Codex has, once each."""
    with h.home._db("state_5.sqlite") as db:
        found = {row[1] for row in db.execute("PRAGMA table_info(threads)")}
        for name, kind in declared.items():
            if name not in found:
                db.execute("ALTER TABLE threads ADD COLUMN %s %s" % (name, kind))


def set_thread(h, thread_id=T1, **values):
    with h.home._db("state_5.sqlite") as db:
        for name, value in values.items():
            db.execute("UPDATE threads SET %s=? WHERE id=?" % name, (value, thread_id))


def checkout(folder: Path, head: str = "ref: refs/heads/main\n") -> Path:
    (folder / ".git").mkdir(parents=True, exist_ok=True)
    (folder / ".git" / "HEAD").write_text(head, encoding="utf-8")
    return folder


# ----------------------------------------------------------------------------- ladder.py
class LadderTests(unittest.TestCase):
    def test_the_presets_are_v0_6_10s(self):
        self.assertEqual(settings.RETRY_TIMING, {"conservative": (15, 45, 120, 300, 600),
                                                 "normal": (5, 15, 30, 60, 120),
                                                 "aggressive": (3, 8, 20, 45, 90)})
        self.assertEqual(settings.RETRY_TIMINGS, ("conservative", "normal", "aggressive", "custom"))
        self.assertEqual(settings.DEFAULT_TIMING, "normal")

    def test_the_floor_is_the_engines_own(self):
        """The preview and the Custom lists say the engine's constants; they are not settings."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        from test_engine import Harness
        h = Harness(Path(temp.name))
        self.addCleanup(h.close)
        self.assertEqual(ladder.SPACING, h.engine.options["thread_cooldown_seconds"])
        self.assertEqual(ladder.PER_DAY, h.engine.options["max_submissions_per_thread_per_day"])

    def test_every_later_custom_wait_starts_at_the_floor(self):
        self.assertTrue(all(ladder.WAIT_SECONDS[wait] >= ladder.SPACING for wait in ladder.LATER_WAITS))
        self.assertIn("s5", ladder.FIRST_WAITS)
        self.assertNotIn("s5", ladder.LATER_WAITS)
        self.assertTrue(all(0 < ladder.WAIT_SECONDS[wait] <= 6 * 3600 for wait in ladder.WAITS),
                        "no wait is zero or unbounded (A22)")

    def test_a_preset_waits_its_first_step_every_time_and_the_floor_does_the_rest(self):
        for name, steps in settings.RETRY_TIMING.items():
            values = dict(settings.defaults(), retry_timing=name)
            with self.subTest(name):
                self.assertFalse(ladder.walks(values))
                self.assertEqual([ladder.wait_before(values, n) for n in range(1, 7)], [steps[0]] * 6)
                self.assertEqual(ladder.preview(values), [steps[0]] + [steps[0] + ladder.SPACING] * 4)
                self.assertEqual(ladder.wait_before(values, 3, "rate_limit_transient"), 60)

    def test_custom_walks_its_steps_and_keeps_the_last(self):
        values = dict(settings.defaults(), retry_timing="custom", retry_wait_1="m2", retry_wait_2="m30",
                      retry_wait_3="h1", retry_wait_4="h2", retry_wait_5="h6")
        self.assertTrue(ladder.walks(values))
        self.assertEqual([ladder.wait_before(values, n) for n in range(1, 8)],
                         [120, 1800, 3600, 7200, 21600, 21600, 21600])
        self.assertEqual(ladder.preview(values), [120, 1800, 3600, 7200, 21600])
        self.assertEqual(ladder.wait_before(dict(values, retry_wait_1="s5"), 1, "rate_limit_transient"), 60)

    def test_left_as_it_comes_custom_is_what_normal_does(self):
        normal = ladder.preview(settings.defaults())
        custom = ladder.preview(dict(settings.defaults(), retry_timing="custom"))
        self.assertEqual([math.floor(seconds / 60) for seconds in custom], [math.floor(seconds / 60) for seconds in normal])

    def test_a_step_that_is_not_one_of_its_choices_is_its_default(self):
        values = dict(settings.defaults(), retry_timing="custom", retry_wait_2="s5", retry_wait_1="h6")
        self.assertEqual(ladder.custom_steps(values), (5, 900, 900, 900, 900))

    def test_jitter_only_lengthens_and_by_a_fifth_at_most(self):
        on = {"retry_jitter": True}
        self.assertEqual(ladder.jittered(100, {}, 0.99), 100, "off by default")
        self.assertEqual(ladder.jittered(100, on, 0.0), 100)
        self.assertEqual(ladder.jittered(100, on, 0.5), 110)
        self.assertLessEqual(ladder.jittered(100, on, 0.999999), 120)
        for bad in (-1.0, 1.0, "0.5", None):
            self.assertEqual(ladder.jittered(100, on, bad), 100)

    def test_the_ceiling(self):
        self.assertIsNone(ladder.ceiling(settings.defaults()))
        self.assertEqual(ladder.ceiling({"chain_time_ceiling": "h3"}), 3 * 3600)
        # v0.6.11: a ceiling of the person's own (Custom...), from 15 minutes to a week; nothing past it.
        self.assertEqual(ladder.ceiling({"chain_time_ceiling": "h2"}), 2 * 3600)
        self.assertEqual(ladder.ceiling({"chain_time_ceiling": "m90"}), 90 * 60)
        for outside in ("m10", "h169", "s3630", "h02", "2h"):
            self.assertIsNone(ladder.ceiling({"chain_time_ceiling": outside}), outside)


class CeilingGateTests(unittest.TestCase):
    record = {"detected_at": 10000.0, "chain_first_detected_at": 10000.0 - 3600}

    def test_a_temporary_task_past_its_ceiling_stops_under_the_chain_budget(self):
        limits = {"max_chain_continuations": 6, "max_recovery_attempts": 4, "max_no_progress": 3,
                  "max_chain_seconds": 3600}
        self.assertEqual(machine.gate_budgets(self.record, limits, False)["chain_budget"], ("BLOCK", "chain_time_cap"))
        shorter = dict(self.record, chain_first_detected_at=10000.0 - 3599)
        self.assertEqual(machine.gate_budgets(shorter, limits, False)["chain_budget"], ("PASS", "ok"))
        self.assertEqual(machine.gate_budgets(self.record, limits, True)["chain_budget"], ("PASS", "ok"),
                         "a usage limit waits for its reset and has no ceiling")
        del limits["max_chain_seconds"]
        self.assertEqual(machine.gate_budgets(self.record, limits, False)["chain_budget"], ("PASS", "ok"),
                         "no ceiling at the defaults")

    def test_what_is_a_wait_aside(self):
        """Its retries' own pacing - a retry's wait, a usage reset, the engine's floor - is what failing
        again and again is made of and counts; anything else a due record waits for is aside and never
        counts, and a vector that says nothing is none."""
        def vector(**gates):
            return machine.decode_gates(machine.encode_gates(gates))
        passed = {name: ("PASS", "ok") for name in machine.GATES}
        for gates, aside in (
                ({"consent": ("BLOCK", "paused")}, True),
                ({"consent": ("BLOCK", "observe_only")}, True),
                ({"consent": ("WAIT", "held")}, True),
                ({"consent": ("PASS", "ok"), "schedule": ("WAIT", "postponed")}, True),
                ({"consent": ("PASS", "ok"), "schedule": ("WAIT", "quiet_hours")}, True),
                ({"consent": ("PASS", "ok"), "schedule": ("WAIT", "not_due")}, False),
                ({"consent": ("PASS", "ok"), "schedule": ("WAIT", "waiting_reset")}, False),
                (dict(passed, thread_available=("WAIT", "notLoaded")), True),
                (dict(passed, engine_compatible=("UNKNOWN", "engine_unknown")), True),
                (dict(passed, attempt_budget=("WAIT", "thread_submission_cooldown")), False),
                (dict(passed, attempt_budget=("WAIT", "daily_submission_cap")), False),
                (dict(passed, chain_budget=("BLOCK", "chain_time_cap")), False),
                (dict(passed, usage=("WAIT", "usage_unavailable")), True),
                (passed, False),
                ({}, False)):
            with self.subTest(gates=gates):
                self.assertEqual(machine.waited_aside(vector(**gates)), aside)
        self.assertFalse(machine.waited_aside(machine.decode_gates(None)))

    def test_the_count_cap_is_said_first(self):
        limits = {"max_chain_continuations": 1, "max_recovery_attempts": 4, "max_no_progress": 3,
                  "max_chain_seconds": 60}
        self.assertEqual(machine.gate_budgets(dict(self.record, chain_continuations=1), limits, False)["chain_budget"],
                         ("BLOCK", "chain_cap"))


# ---------------------------------------------------------------------------- Retry-After
class RetryAfterTests(Base):
    def test_a_structured_wait_is_read_and_nothing_else_is(self):
        self.assertEqual(failures.retry_after({"rateLimitExceeded": {"retryAfterSeconds": 30}}), 30)
        self.assertEqual(failures.retry_after({"type": "serverOverloaded", "retry_after_seconds": 45}), 45)
        for info in ("rateLimitExceeded", None, {"rateLimitExceeded": {"retryAfterSeconds": "30"}},
                     {"rateLimitExceeded": {"retryAfterSeconds": 0}},
                     {"rateLimitExceeded": {"retryAfterSeconds": 86401}},
                     {"rateLimitExceeded": {"retryAfterSeconds": True}}):
            with self.subTest(info=info):
                self.assertIsNone(failures.retry_after(info))
        row = normalize({"thread_id": T1, "turn_id": T1, "status": "failed", "ordinal": 1, "started_at": 1788628000,
                         "completed_at": 1788628001, "error_json": named_wait(90)})
        self.assertEqual((row["category"], row["retry_after"]), ("server_5xx", 90))
        self.assertEqual(normalize(row)["retry_after"], 90, "normalize stays idempotent")
        usage = normalize(dict(row, category="usage_limit"))
        self.assertNotIn("retry_after", usage, "only a temporary failure keeps one")

    def test_a_named_wait_is_the_least_the_first_wait_is(self):
        h = self.harness()
        h.home.fail_transient(T1, error_json=named_wait(300))
        h.enable()
        h.tick()
        row = h.record(T1)
        self.assertEqual(row["category"], "server_5xx")
        self.assertEqual(row["next_retry_at"] - row["detected_at"], 300)

    def test_a_shorter_named_wait_changes_nothing(self):
        h = self.harness()
        h.home.fail_transient(T1, error_json=named_wait(2))
        h.enable()
        h.tick()
        row = h.record(T1)
        self.assertEqual(row["next_retry_at"] - row["detected_at"], 5)


# ------------------------------------------------------------------------ the engine's waits
class LadderEngineTests(ChainBase):
    def test_a_preset_waits_as_v0_6_10_did_for_every_attempt(self):
        h = self.harness()
        first = self.start(h)
        self.assertEqual(first["next_retry_at"] - first["detected_at"], 5)
        again = self.continuation_fails(h)
        self.assertEqual(again["next_retry_at"] - again["detected_at"], 5)

    def test_custom_gives_each_attempt_at_a_task_its_own_wait(self):
        h = self.harness()
        policy(h, retry_timing="custom", retry_wait_1="m1", retry_wait_2="m30", retry_wait_3="h1",
               max_no_progress=10)
        first = self.start(h)
        self.assertEqual(first["next_retry_at"] - first["detected_at"], 60)
        second = self.continuation_fails(h)
        self.assertEqual(second["parent_interruption_id"], first["interruption_id"])
        self.assertEqual(second["next_retry_at"] - second["detected_at"], 1800)
        third = self.continuation_fails(h)
        self.assertEqual(third["next_retry_at"] - third["detected_at"], 3600)
        self.assertEqual(len(h.backend.send_calls), 2)

    def test_jitter_lengthens_the_wait_and_only_when_on(self):
        h = self.harness()
        policy(h, retry_jitter=True)
        h.engine._random = Fixed(0.5)
        first = self.start(h)
        self.assertEqual(first["next_retry_at"] - first["detected_at"], 6, "5 s and a tenth, rounded up")

    def test_a_task_that_keeps_failing_past_its_ceiling_stops(self):
        h = self.harness()
        policy(h, chain_time_ceiling="h1", max_no_progress=10, max_recovery_attempts=10)
        self.start(h)
        rows = self.run_chain(h)
        last = rows[-1]
        self.assertEqual((last["state"], last["last_error"]), ("retry_budget_exhausted", "chain_time_cap"))
        self.assertGreaterEqual(last["detected_at"] - last["chain_first_detected_at"], 3600)
        for row in rows[:-1]:
            self.assertLess(row["detected_at"] - row["chain_first_detected_at"], 3600)
        announced = [(event, detail["interruption_id"]) for event, detail in h.notifications]
        self.assertIn(("stopped", last["interruption_id"]), announced)
        stopped = [detail for event, detail in h.notifications
                   if event == "stopped" and detail["interruption_id"] == last["interruption_id"]]
        notice = notifier.build("stopped", stopped[0])
        self.assertEqual(notice.line, notify.l10n.message("toast_time_cap_body"),
                         "said as the time it took, not as attempts it had to spare")

    def test_a_postponement_never_counts_toward_the_ceiling(self):
        """A task postponed three hours, whose one continuation then fails: the three hours were counted
        against a ceiling of one, and it stopped - after a single failure of its own."""
        h = self.harness()
        policy(h, chain_time_ceiling="h1", max_no_progress=10, max_recovery_attempts=10)
        first = self.start(h)
        self.assertTrue(h.store.postpone(first["interruption_id"], T1, h.now + 3 * 3600, h.now)[0])
        for _ in range(30):
            h.tick(advance=600)
            if h.backend.send_calls:
                break
        self.assertEqual(len(h.backend.send_calls), 1)
        dispatch_and_fail(h.home, T1, progress=False)
        h.tick(advance=1)
        child = h.records(T1)[-1]
        self.assertEqual(child["parent_interruption_id"], first["interruption_id"])
        self.assertNotEqual(child["last_error"], "chain_time_cap")
        self.assertIn(child["state"], machine.WAITING)
        self.assertLess(child["detected_at"] - child["chain_first_detected_at"], 3600)

    def test_an_objection_window_never_counts_toward_the_ceiling(self):
        """An hour's window to object before each send, under a ceiling of an hour: every task stopped at
        its first failed continuation, the window counted as failing."""
        h = self.harness()
        policy(h, chain_time_ceiling="h1", default_tier="objection_window", objection_minutes=60,
               max_no_progress=10, max_recovery_attempts=10)
        self.start(h)
        child = self.continuation_fails(h)
        self.assertNotEqual(child["last_error"], "chain_time_cap")
        self.assertLess(child["detected_at"] - child["chain_first_detected_at"], 3600)

    def test_without_a_ceiling_the_same_chain_goes_on(self):
        h = self.harness()
        policy(h, max_no_progress=10, max_recovery_attempts=10)
        self.start(h)
        rows = self.run_chain(h, rounds=4)
        self.assertNotEqual(rows[-1]["last_error"], "chain_time_cap")


class CeilingEngineTests(Base):
    def stretched(self, h, seconds):
        """The waiting record's task began failing `seconds` before its latest failure."""
        row = h.record(T1)
        with closing(sqlite3.connect(h.root / "state.sqlite")) as db, db:
            db.execute("UPDATE interruptions SET chain_first_detected_at=? WHERE interruption_id=?",
                       (row["detected_at"] - seconds, row["interruption_id"]))
        return row["interruption_id"]

    def test_a_ceiling_set_later_stops_the_task_when_it_falls_due_and_the_claim_agrees(self):
        h = self.harness()
        h.home.fail_transient(T1)
        h.enable()
        h.tick()
        key = self.stretched(h, 7200)
        limits = dict(h.engine.limits(), max_chain_seconds=3600)
        self.assertEqual(h.store.reserve_detailed(key, h.now + 10, limits=limits),
                         (False, "chain_budget", "chain_time_cap"))
        policy(h, chain_time_ceiling="h1")
        h.tick(advance=10)
        row = h.record(T1)
        self.assertEqual((row["state"], row["last_error"]), ("retry_budget_exhausted", "chain_time_cap"))
        self.assertEqual(h.backend.send_calls, [])

    def test_giving_attempts_back_gives_the_time_back(self):
        h = self.harness()
        h.home.fail_transient(T1)
        h.enable()
        policy(h, chain_time_ceiling="h1")
        h.tick()
        key = self.stretched(h, 7200)
        h.tick(advance=10)
        self.assertEqual(h.record(T1)["last_error"], "chain_time_cap")
        self.assertEqual(h.store.restore_budget_detailed(key, h.now)[0], True)
        row = h.record(T1)
        self.assertEqual(row["chain_first_detected_at"], row["detected_at"])
        h.tick(advance=10)
        self.assertEqual(len(h.backend.send_calls), 1)


# ------------------------------------------------------------------------ the defaults
class DefaultTests(Base):
    def test_at_the_defaults_nothing_new_is_read_kept_or_held(self):
        h = self.harness()
        spy = Spy(h.source)
        h.engine.source = spy
        h.home.fail_transient(T1)
        h.enable()
        h.tick()
        row = h.record(T1)
        self.assertEqual((row["task_print"], row["context_tokens"], row["hold"]), (None, None, None))
        self.assertEqual(row["next_retry_at"] - row["detected_at"], 5)
        h.tick(advance=10)
        self.assertEqual(len(h.backend.send_calls), 1)
        self.assertNotIn("task_facts", spy.asked)
        self.assertNotIn("task_changed", json.dumps([detail for _event, detail in h.notifications]))

    def test_nothing_is_high_at_the_defaults(self):
        self.assertEqual(settings.high_limits(settings.defaults()), [])
        self.assertEqual(settings.high_limits(dict(settings.defaults(), max_recovery_attempts=9)),
                         ["max_recovery_attempts"])
        self.assertEqual(settings.high_limits(dict(settings.defaults(), max_chain_continuations=8)), [],
                         "the high value itself is not above it")


# ------------------------------------------------------------------------- workspace.py
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_a_folder_that_is_no_checkout(self):
        self.assertEqual(workspace.head_digest(str(self.root)), workspace.NONE)

    def test_a_checkout_is_its_head_as_a_digest(self):
        folder = checkout(self.root / "work")
        found = workspace.head_digest(str(folder))
        self.assertTrue(guards.is_print(found))
        self.assertNotIn("main", found)
        self.assertEqual(workspace.head_digest("\\\\?\\" + str(folder)), found, "the extended prefix is one folder")
        checkout(folder, "ref: refs/heads/other\n")
        self.assertNotEqual(workspace.head_digest(str(folder)), found)

    def test_a_worktree_follows_its_git_file_once(self):
        main = checkout(self.root / "main")
        holder = main / ".git" / "worktrees" / "side"
        holder.mkdir(parents=True)
        (holder / "HEAD").write_text("ref: refs/heads/side\n", encoding="utf-8")
        side = self.root / "side"
        side.mkdir()
        (side / ".git").write_text("gitdir: %s\n" % holder, encoding="utf-8")
        self.assertTrue(guards.is_print(workspace.head_digest(str(side))))
        relative = self.root / "relative"
        relative.mkdir()
        (relative / ".git").write_text("gitdir: ../main/.git/worktrees/side\n", encoding="utf-8")
        self.assertEqual(workspace.head_digest(str(relative)), workspace.head_digest(str(side)))

    def test_what_cannot_be_read_says_so(self):
        big = checkout(self.root / "big", "x" * (workspace.MAX_HEAD_BYTES + 1))
        broken = self.root / "broken"
        broken.mkdir()
        (broken / ".git").write_text("not a pointer\n", encoding="utf-8")
        shared = self.root / "shared"
        shared.mkdir()
        (shared / ".git").write_text("gitdir: \\\\server\\share\\repo\n", encoding="utf-8")
        for cwd in (str(big), str(broken), str(shared), "\\\\server\\share\\work", "\\\\?\\UNC\\server\\share",
                    "relative\\folder", "", None, 7, "a\nb"):
            with self.subTest(cwd=cwd):
                self.assertEqual(workspace.head_digest(cwd), workspace.UNREADABLE)


# ------------------------------------------------------------------------------ guards.py
class GuardRuleTests(unittest.TestCase):
    def test_a_print_is_a_digest_of_all_three(self):
        one = guards.fingerprint("gpt-5", "on-request", "a" * 64)
        self.assertTrue(guards.is_print(one))
        self.assertNotEqual(one, guards.fingerprint("gpt-5", "never", "a" * 64))
        self.assertNotEqual(one, guards.fingerprint("o3", "on-request", "a" * 64))
        self.assertNotEqual(one, guards.fingerprint("gpt-5", "on-request", "b" * 64))
        self.assertEqual(guards.fingerprint(None, None, "none"), guards.fingerprint(None, None, "none"))

    def test_what_counts_as_changed(self):
        before = guards.fingerprint("m", "a", "none")
        self.assertFalse(guards.changed(None, "x"), "detected while the guard was off: not judged")
        self.assertFalse(guards.changed(before, before))
        self.assertTrue(guards.changed(before, guards.fingerprint("m", "b", "none")))
        self.assertTrue(guards.changed(before, None), "readable then, not now")
        self.assertFalse(guards.changed(guards.UNREADABLE, None), "unreadable then and now: no change seen")
        self.assertTrue(guards.changed(guards.UNREADABLE, before))

    def test_the_context_limit(self):
        self.assertFalse(guards.counts_tokens(settings.defaults()))
        self.assertIsNone(guards.context_limit({"context_guard": "show"}))
        values = {"context_guard": "above_250k"}
        self.assertTrue(guards.over(values, 250001))
        self.assertFalse(guards.over(values, 250000))
        for unknown in (None, "300000", True, -1, 2 ** 60):
            self.assertFalse(guards.over(values, unknown), "an unknown count is never above it")


class TaskFactsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = CodexHome(Path(temp.name) / "codex")
        self.home.add_thread(T1)
        self.source = LocalSource(self.home.root)
        self.folder = checkout(Path(temp.name) / "work")
        with self.home._db("state_5.sqlite") as db:
            db.execute("UPDATE threads SET cwd=? WHERE id=?", (str(self.folder), T1))

    def facts(self, **asked):
        return self.source.task_facts(T1, **asked)

    def test_nothing_is_asked_for_nothing(self):
        self.assertEqual(self.facts(), {"print": None, "tokens": None})

    def test_without_the_columns_the_print_is_the_head_and_there_is_no_count(self):
        found = self.facts(fingerprint=True, tokens=True)
        self.assertTrue(guards.is_print(found["print"]))
        self.assertIsNone(found["tokens"], "left out where Codex keeps no count")
        self.assertEqual(self.facts(fingerprint=True)["print"], found["print"])
        checkout(self.folder, "0123456789abcdef0123456789abcdef01234567\n")
        self.assertNotEqual(self.facts(fingerprint=True)["print"], found["print"])

    def test_with_the_columns(self):
        with self.home._db("state_5.sqlite") as db:
            db.execute("ALTER TABLE threads ADD COLUMN model TEXT")
            db.execute("ALTER TABLE threads ADD COLUMN approval_mode TEXT")
            db.execute("ALTER TABLE threads ADD COLUMN tokens_used INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE threads SET model='gpt-5', approval_mode='on-request', tokens_used=123456")
        found = self.facts(fingerprint=True, tokens=True)
        self.assertEqual(found["tokens"], 123456)
        with self.home._db("state_5.sqlite") as db:
            db.execute("UPDATE threads SET approval_mode='never'")
        self.assertNotEqual(self.facts(fingerprint=True)["print"], found["print"])
        self.assertEqual(self.facts(tokens=True), {"print": None, "tokens": 123456})

    def test_a_count_that_is_no_number_is_left_out(self):
        with self.home._db("state_5.sqlite") as db:
            db.execute("ALTER TABLE threads ADD COLUMN tokens_used TEXT")
            db.execute("UPDATE threads SET tokens_used='123'")
        self.assertIsNone(self.facts(tokens=True)["tokens"])

    def test_an_unknown_conversation_is_nothing(self):
        self.assertEqual(self.source.task_facts("22222222-2222-7222-8222-222222222222", fingerprint=True, tokens=True),
                         {"print": None, "tokens": None})
        self.assertEqual(self.source.task_facts("not a uuid", fingerprint=True), {"print": None, "tokens": None})


# ------------------------------------------------------------------ the task-changed guard
class TaskGuardEngineTests(Base):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)

    def detected(self, mode):
        h = self.harness()
        h.home.add_thread(T1)
        columns(h, model="TEXT", approval_mode="TEXT")
        self.folder = checkout(self.temp / "work")
        set_thread(h, cwd=str(self.folder), model="gpt-5", approval_mode="on-request")
        policy(h, task_changed_guard=mode)
        h.home.fail_transient(T1)
        h.enable()
        h.tick()
        row = h.record(T1)
        self.assertTrue(guards.is_print(row["task_print"]))
        self.assertNotEqual(row["task_print"], guards.UNREADABLE)
        return h, row

    def test_unchanged_it_is_sent_as_before(self):
        h, _row = self.detected("hold")
        h.tick(advance=10)
        self.assertEqual(len(h.backend.send_calls), 1)
        self.assertIsNone(h.record(T1)["hold"])

    def test_a_change_holds_it_for_a_person_once_and_let_go_it_is_sent(self):
        h, row = self.detected("hold")
        checkout(self.folder, "ref: refs/heads/other\n")
        h.tick(advance=10)
        held = h.record(T1)
        self.assertEqual(held["hold"], "workspace_changed")
        self.assertNotEqual(held["task_print"], row["task_print"], "what was found is its digest now")
        self.assertEqual(machine.decode_gates(held["gate_eval"])["consent"], ("WAIT", "held"))
        self.assertEqual(h.backend.send_calls, [])
        told = [detail for event, detail in h.notifications if event == "interruption" and detail.get("hold")]
        self.assertEqual([detail["hold"] for detail in told], ["workspace_changed"])
        h.tick(advance=120)
        self.assertEqual(h.backend.send_calls, [], "a hold waits for a person")
        self.assertEqual(h.store.release_hold(row["interruption_id"], T1, h.now)[0], True)
        h.tick(advance=60)
        self.assertEqual(len(h.backend.send_calls), 1, "let go, the same change does not hold it again")

    def test_a_folder_that_cannot_be_read_any_more_has_changed(self):
        h, _row = self.detected("hold")
        shutil.rmtree(self.folder)
        h.tick(advance=10)
        self.assertEqual(h.record(T1)["hold"], "workspace_changed")
        self.assertEqual(h.backend.send_calls, [])

    def test_tell_sends_and_its_notice_says_the_task_changed(self):
        h, _row = self.detected("tell")
        set_thread(h, model="another-model")
        h.tick(advance=10)
        self.assertEqual(len(h.backend.send_calls), 1)
        self.assertIsNone(h.record(T1)["hold"])
        starting = [detail for event, detail in h.notifications if event == "starting"]
        self.assertEqual([detail.get("task_changed") for detail in starting], [True])
        self.assertIn("task_changed_told", h.codes(T1))
        notice = notifier.build("starting", starting[0])
        self.assertIn(notify.l10n.message("toast_task_changed"), notice.line)

    def test_turned_on_after_detection_it_judges_nothing(self):
        h = self.harness()
        h.home.add_thread(T1)
        self.folder = checkout(self.temp / "work")
        set_thread(h, cwd=str(self.folder))
        h.home.fail_transient(T1)
        h.enable()
        h.tick()
        self.assertIsNone(h.record(T1)["task_print"])
        policy(h, task_changed_guard="hold")
        checkout(self.folder, "ref: refs/heads/other\n")
        h.tick(advance=10)
        self.assertEqual(len(h.backend.send_calls), 1)


class HoldChangedStoreTests(Base):
    def test_it_holds_only_a_record_that_waits_unsent_and_takes_the_digest(self):
        h = self.harness()
        h.home.fail_transient(T1)
        h.enable()
        policy(h, task_changed_guard="hold")
        h.tick()
        key = h.record(T1)["interruption_id"]
        with self.assertRaises(Exception):
            h.store.hold_changed(key, "not a digest", h.now)
        self.assertTrue(h.store.hold_changed(key, "c" * 64, h.now))
        self.assertEqual((h.record(T1)["hold"], h.record(T1)["task_print"]), ("workspace_changed", "c" * 64))
        self.assertFalse(h.store.hold_changed(key, "d" * 64, h.now), "held already")
        self.assertEqual(h.record(T1)["task_print"], "c" * 64)


# ------------------------------------------------------------------ the context-cost guard
class ContextGuardEngineTests(Base):
    def detected(self, mode, tokens=300000, kind="INTEGER NOT NULL DEFAULT 0"):
        h = self.harness()
        h.home.add_thread(T1)
        if kind is not None:
            columns(h, tokens_used=kind)
            set_thread(h, tokens_used=tokens)
        policy(h, context_guard=mode)
        h.home.fail_transient(T1)
        h.enable()
        h.tick()
        return h, h.record(T1)

    def test_over_the_limit_it_waits_for_a_person_from_the_start(self):
        h, row = self.detected("above_250k")
        self.assertEqual((row["hold"], row["context_tokens"]), ("context_cost", 300000))
        told = [detail for event, detail in h.notifications if event == "interruption"]
        self.assertEqual([detail.get("hold") for detail in told], ["context_cost"])
        h.tick(advance=120)
        self.assertEqual(h.backend.send_calls, [])
        self.assertEqual(h.store.release_hold(row["interruption_id"], T1, h.now)[0], True)
        h.tick(advance=60)
        self.assertEqual(len(h.backend.send_calls), 1, "let go, it is not held again for the same count")

    def test_under_the_limit_or_shown_only_it_is_kept_and_sent(self):
        for mode in ("show", "above_500k"):
            with self.subTest(mode):
                h, row = self.detected(mode)
                self.assertEqual((row["hold"], row["context_tokens"]), (None, 300000))
                h.tick(advance=10)
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_where_codex_keeps_no_count_the_guard_is_left_out(self):
        for kind in (None, "TEXT"):
            with self.subTest(kind):
                h, row = self.detected("above_100k", tokens="300000", kind=kind)
                self.assertEqual((row["hold"], row["context_tokens"]), (None, None))
                h.tick(advance=10)
                self.assertEqual(len(h.backend.send_calls), 1)


# ------------------------------------------------------------------ settings and surfaces
class SettingsTests(unittest.TestCase):
    def test_the_new_settings_take_their_choices_and_refuse_the_rest(self):
        good = {"retry_timing": "custom", "retry_wait_1": "s5", "retry_wait_2": "h6", "retry_wait_5": "m15",
                "retry_jitter": True, "chain_time_ceiling": "h24", "task_changed_guard": "tell",
                "context_guard": "above_1m"}
        self.assertEqual(settings.validate_update(good), good)
        # v0.6.11: a value of the person's own within its bounds is taken, in its one spelling (Custom...).
        own = {"retry_wait_1": "s90", "retry_wait_2": "m45", "retry_wait_5": "h5", "chain_time_ceiling": "h2",
               "context_guard": "above_2m"}
        self.assertEqual(settings.validate_update(own), own)
        self.assertEqual(settings.validate_update({"retry_wait_3": "m120", "context_guard": "above_300000"}),
                         {"retry_wait_3": "h2", "context_guard": "above_300k"})
        for bad in ({"retry_wait_2": "s5"}, {"retry_wait_1": "h6"}, {"retry_wait_1": 5}, {"retry_timing": "fast"},
                    {"retry_wait_1": "s4"}, {"retry_wait_2": "m14"}, {"retry_wait_2": "s930"}, {"retry_wait_4": "h7"},
                    {"chain_time_ceiling": "m5"}, {"chain_time_ceiling": "h169"}, {"task_changed_guard": True},
                    {"context_guard": "above_5k"}, {"context_guard": "above_300500"}, {"context_guard": "above_11m"},
                    {"retry_jitter": 1}):
            with self.subTest(bad=bad), self.assertRaises(settings.SettingsError):
                settings.validate_update(bad)

    def test_the_schema_carries_what_the_surfaces_draw_from(self):
        described = {entry["name"]: entry for entry in settings.describe()}
        for name in ("retry_wait_1", "retry_wait_5", "retry_jitter", "chain_time_ceiling", "task_changed_guard",
                     "context_guard"):
            self.assertEqual(described[name]["group"], "limits", name)
        self.assertEqual(described["retry_timing"]["waits"], ladder.previews())
        self.assertEqual(described["retry_wait_2"]["seconds"], {"m15": 900, "m30": 1800, "h1": 3600, "h2": 7200,
                                                               "h3": 10800, "h6": 21600})
        self.assertEqual({name: described[name]["high"] for name in settings.HIGH_LIMITS}, settings.HIGH_LIMITS)
        values = dict(settings.defaults(), retry_timing="custom", retry_wait_1="m2", retry_wait_4="h3")
        seconds = [described[name]["seconds"][values[name]] for name in ladder.STEP_FIELDS]
        self.assertEqual(seconds, ladder.preview(values), "what a surface looks up is the preview")

    def test_codex_may_set_them_and_is_told_what_each_does(self):
        schema = mcp_tools.settings_schema()["properties"]
        for name in ladder.STEP_FIELDS + ("retry_jitter", "chain_time_ceiling", "task_changed_guard", "context_guard"):
            with self.subTest(name):
                self.assertIn(name, schema)
                self.assertNotEqual(schema[name]["description"], "See the settings documentation.")
        # v0.6.11: a choice, or a wait of the person's own in the same words (ownvalues.py).
        self.assertEqual(schema["retry_wait_2"]["anyOf"][0]["enum"], list(ladder.LATER_WAITS))
        self.assertIn("from 15 minutes to 6 hours", schema["retry_wait_2"]["description"])


class BudgetDisplayTests(ControlTestCase):
    def test_a_count_survives_a_lowered_limit(self):
        with Store(self.paths.state_dir) as store:
            store.register(detection(category="network_transient"), 100.0)
            store.register(detection(key="b" * 64, category="usage_limit",
                                     thread_id="0a1b2c3d-0001-7000-8000-000000000003"), 100.0)
        with closing(sqlite3.connect(self.paths.state_dir / "state.sqlite")) as db, db:
            db.execute("UPDATE interruptions SET recovery_attempts=19 WHERE interruption_id=?", ("a" * 64,))
        self.control.update_settings({"max_recovery_attempts": 6})
        rows = {row["thread_id"]: row for row in self.control.list_pending()}
        self.assertEqual((rows[THREAD]["recovery_attempts"], rows[THREAD]["attempt_limit"]), (19, 6))
        self.assertIsNone(rows["0a1b2c3d-0001-7000-8000-000000000003"]["attempt_limit"],
                          "a usage limit spends no attempt")
        self.assertIsNone(rows[THREAD]["context_tokens"])


class NoticeTests(unittest.TestCase):
    def test_a_tell_adds_to_the_one_line_and_to_nothing_else(self):
        plain = notify.starting_content(T1)
        told = notify.starting_content(T1, task_changed=True)
        self.assertEqual(len(told["extra"]), 1)
        self.assertTrue(told["extra"][0].startswith(plain["extra"][0]))
        self.assertEqual((told["title"], told["body"]), (plain["title"], plain["body"]))
        self.assertEqual(notify.starting_content(T1, task_changed="yes"), plain)

    def test_a_guards_hold_is_said_as_what_it_found(self):
        for hold in ("workspace_changed", "context_cost"):
            with self.subTest(hold):
                self.assertEqual(notify.held_message(hold), notify.l10n.message("toast_" + hold))
                content = notify.scheduled_content(T1, "a" * 64, None, "server_5xx", hold=hold)
                self.assertEqual({label for label, _uri in content["more"]},
                                 {notify.l10n.message("toast_button_open")})


if __name__ == "__main__":
    unittest.main()
