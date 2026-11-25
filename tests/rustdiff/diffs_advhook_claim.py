"""The Stop hook's shared claim (car-adv `engine/hookclaims.rs`) held to the tag's `engine/hookclaims.py` on real files.

One case is one home - core's `state.sqlite` made by the tag's own store with records registered in it, this edition's
`advanced.sqlite` with the capability armed or not, a settings file - made once and copied twice, one for the tag and one for
car-adv. The same claims, in order, run on each (the administrator's policy keys given by the case, never read from the
registry), and both must answer the same and leave the same files: every table of both, row for row.

* what is granted and written (`blocked` with its unit of spend, the answered turn and interruption refused or passed over),
* what holds it back: the capability not armed, recovery paused or observe only, the conversation's own switch, the
  administrator's keys and quiet hours (theirs and the person's), core's own record in flight, in its spacing, past the caps of
  a day, cancelled, held, postponed or past its budgets, the ceilings of this edition's own units, a lock that is not had,
* what is not there: no core file, no advanced file, an id that is no interruption id.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import unittest

from rustdiff import advreport, advstore
from rustdiff import diffs_advstore as store
from rustdiff.advstore import CLOCK, THREAD, key

RECORD = []
ARMED = "INSERT INTO arming (capability, state, since, actor) VALUES ('stop_hook_continuation', 'armed', %r, 'dashboard')" % (
    CLOCK - 100,)
SHADOW = ARMED.replace("'armed'", "'shadow'")

RUNNER = r'''
import json, sys
from pathlib import Path
from codex_auto_resume import config, managed as admin
from codex_auto_resume.control import policy as control
from codex_auto_resume_advanced.engine import hookclaims

home = Path(sys.argv[1])
ops = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
paths = config.Paths(str(home))
out = []
for op in ops:
    if op[0] == "claim":
        _kind, failure, turn_key, now, managed, busy = op
        held = admin.NONE if not managed else admin.Managed(
            disable_auto_resume=bool(managed.get("disable_auto_resume")), force_observe_only=bool(managed.get("force_observe_only")),
            max_recovery_attempts=managed.get("max_recovery_attempts"), quiet_hours=tuple(managed.get("quiet_hours") or ()))
        control.managed_policy = lambda held=held: held
        found = hookclaims.claim(paths, failure, turn_key, now, busy=busy)
        out.append({"ok": None if found is None else str(found)})
    elif op[0] == "blocked_at":
        out.append({"ok": hookclaims.blocked_at(paths, op[1])})
    elif op[0] == "sql":
        import sqlite3
        db = sqlite3.connect(home / "config" / "state.sqlite")
        db.executescript(op[1])
        db.commit()
        db.close()
        out.append(None)
sys.stdout.write(json.dumps(out))
'''


def failure_of(index, thread=THREAD):
    record = store.core_record(index, thread)
    return {"interruption_id": record["interruption_id"], "thread_id": thread, "turn_id": record["turn_id"],
            "category": "network_transient"}


def record_of(index, thread=THREAD, **more):
    return dict(store.core_record(index, thread), category="network_transient", **more)


def claim(index, turn="a" * 64, now=CLOCK, managed=None, busy=0.5, thread=THREAD):
    return ["claim", failure_of(index, thread), turn, now, managed, busy]


def digest(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


class ClaimDiff(advreport.ReportDiff):
    EXAMPLE = "advhook"

    def run_case(self, label, records, ops, advanced=(ARMED,), changes=(), settings=None, core=True):
        def setup(home: Path) -> None:
            if core:
                store.core_home(records, changes, advanced)(home)
            elif advanced:
                store.historic("STATEMENTS", *advanced)(home)
            if settings is not None:
                (home / "config").mkdir(exist_ok=True)
                (home / "config" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        twin = advstore.Twin(setup)
        try:
            file = twin.folder / "ops.json"
            file.write_text(json.dumps(ops), encoding="utf-8")
            profile = twin.folder / "python" / "profile"
            ran = advreport.advref.run(RUNNER, str(twin.python), str(file), profile=profile)
            self.assertEqual(ran.returncode, 0, ran.stderr[-3000:].decode("utf-8", "replace"))
            expected = json.loads(ran.stdout.decode("utf-8"))
            request = json.dumps({"cases": [["claim.run", str(twin.rust), ops]]}).encode("utf-8")
            done = advreport.subprocess.run([str(advreport.binary("advhook"))], input=request, capture_output=True,
                                            env=advreport.advref.environment(twin.rust.parent / "profile"),
                                            creationflags=advreport.NO_WINDOW, timeout=600)
            self.assertEqual(done.returncode, 0, done.stderr[-3000:].decode("utf-8", "replace"))
            actual = json.loads(done.stdout.decode("utf-8"))["results"][0]
            self.assertIn("ok", actual, actual)
            self.assertEqual(actual["ok"], expected, "%s: the answers" % label)
            python_files, rust_files = advstore.dump_home(twin.python), advstore.dump_home(twin.rust)
            for name in sorted(set(python_files) | set(rust_files)):
                self.assertEqual(python_files.get(name), rust_files.get(name), "%s: %s differs" % (label, name))
            return expected
        finally:
            twin.close()

    def test_every_way_the_claim_goes(self):
        count = 0
        # granted, then answered, then once a turn
        got = self.run_case("grant", [record_of(0), record_of(1), record_of(2)],
                            [claim(0), claim(0), claim(1), claim(2, turn="b" * 64), ["blocked_at", key(100)], ["blocked_at", key(101)],
                             ["blocked_at", "nope"], ["blocked_at", None], ["blocked_at", key(999)]])
        self.assertEqual(got[0], {"ok": "blocked"})
        count += 1
        # the capability not armed
        for label, advanced in (("shadow", (SHADOW,)), ("no row", ()), ("off", (SHADOW.replace("'shadow'", "'off'"),))):
            self.run_case(label, [record_of(0)], [claim(0)], advanced=advanced)
            count += 1
        # recovery's own switches
        for label, change in (("paused", "UPDATE settings SET enabled = 0"), ("observe", "UPDATE settings SET observe_only = 1"),
                              ("thread off", "INSERT OR REPLACE INTO threads (thread_id, enabled) VALUES ('%s', 0)" % THREAD),
                              ("thread on", "INSERT OR REPLACE INTO threads (thread_id, enabled) VALUES ('%s', 1)" % THREAD)):
            self.run_case(label, [record_of(0)], [["sql", change + ";"], claim(0)])
            count += 1
        # the administrator's keys and the quiet hours, theirs and the person's
        quiet = {"quiet_hours_start": 0, "quiet_hours_end": 1439, "quiet_hours_days": 127}
        for label, managed, settings in (("disable", {"disable_auto_resume": True}, None), ("force observe", {"force_observe_only": True}, None),
                                         ("max attempts", {"max_recovery_attempts": 1}, None),
                                         ("their quiet hours", {"quiet_hours": [quiet]}, None), ("our quiet hours", None, quiet),
                                         ("their quiet hours, off", {"quiet_hours": [{"quiet_hours_start": 5, "quiet_hours_end": 5}]}, None),
                                         ("observe in settings", None, {"observe_only": True}),
                                         ("settings damaged", None, "not an object"), ("settings with a ceiling", None, {"chain_time_ceiling": "1h"}),
                                         ("budgets", None, {"max_chain_continuations": 1, "max_recovery_attempts": 1, "max_no_progress": 1})):
            self.run_case(label, [record_of(0)], [claim(0, managed=managed)], settings=settings)
            count += 1
        # core's own record in the way
        for label, change in (("in flight", "UPDATE interruptions SET state='submitted'"), ("failed", "UPDATE interruptions SET state='failed'"),
                              ("resumed", "UPDATE interruptions SET state='recovered'"), ("cancel", "UPDATE interruptions SET cancel_requested=1"),
                              ("hold", "UPDATE interruptions SET hold='a person'"), ("postponed", "UPDATE interruptions SET not_before=%r" % (CLOCK + 60)),
                              ("not postponed", "UPDATE interruptions SET not_before=%r" % (CLOCK - 60)),
                              ("attempts", "UPDATE interruptions SET recovery_attempts=99"), ("chain", "UPDATE interruptions SET chain_continuations=99"),
                              ("no progress", "UPDATE interruptions SET no_progress_count=99"),
                              ("recent claim", "UPDATE interruptions SET last_claim_at=%r, submitted_at=%r WHERE interruption_id='%s'" % (CLOCK - 5, CLOCK - 5, key(100))),
                              ("old claim", "UPDATE interruptions SET last_claim_at=%r WHERE interruption_id='%s'" % (CLOCK - 86400 * 3, key(100))),
                              ("usage", "UPDATE interruptions SET category='usage_limit', recovery_attempts=99")):
            self.run_case(label, [record_of(0), record_of(1)], [["sql", change + ";"], claim(0), claim(1, turn="c" * 64)])
            count += 1
        # another record of the conversation in flight, a day's caps
        self.run_case("sibling in flight", [record_of(0), record_of(1)],
                      [["sql", "UPDATE interruptions SET state='submitted' WHERE interruption_id='%s';" % key(101)], claim(0)])
        many = [record_of(index) for index in range(7)]
        self.run_case("daily cap", many, [["sql", "UPDATE interruptions SET attempt_count=1, submitted_at=%r WHERE interruption_id!='%s';" % (CLOCK - 4000, key(100))],
                                          claim(0)])
        count += 2
        # this edition's own units against its ceilings
        units = ["INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (%r, 'stop_hook_continuation', '%s', '%s')" % (CLOCK - 100 - n, THREAD, key(500 + n))
                 for n in range(3)]
        self.run_case("units spent", [record_of(0)], [claim(0)], advanced=(ARMED, *units))
        many_units = ["INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (%r, 'stop_hook_continuation', '%s', '%s')" % (CLOCK - 100 - n, THREAD, key(600 + n))
                      for n in range(60)]
        self.run_case("units past the ceilings", [record_of(0)], [claim(0)], advanced=(ARMED, *many_units))
        other = ["INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (%r, 'send_now', '%s', '%s')" % (CLOCK - 100 - n, THREAD, key(700 + n))
                 for n in range(60)]
        self.run_case("other units past the hour", [record_of(0)], [claim(0)], advanced=(ARMED, *other))
        count += 3
        # what is not there, and what is not an id
        self.run_case("no core file", [], [claim(0)], core=False)
        self.run_case("no advanced file", [record_of(0)], [claim(0)], advanced=())
        for label, bad in (("bad id", dict(failure_of(0), interruption_id="nope")), ("no id", {"thread_id": THREAD}), ("no thread", {"interruption_id": key(100)}),
                           ("odd thread", dict(failure_of(0), thread_id="not-a-uuid")), ("unknown id", dict(failure_of(0), interruption_id=key(7777)))):
            self.run_case(label, [record_of(0)], [["claim", bad, "d" * 64, CLOCK, None, 0.5]])
            count += 1
        self.run_case("times", [record_of(0), record_of(1), record_of(2)],
                      [claim(0, now=CLOCK), claim(1, turn="e" * 64, now=CLOCK), claim(2, turn="f" * 64, now=CLOCK + 1000),
                       claim(0, now=CLOCK + 10 ** 6), claim(1, now=0.0), claim(2, now=-5.0, turn="g" * 64)])
        count += 3
        RECORD.append("hook claim: %d homes - granted, answered, once a turn, not armed, paused, observe only, the thread's switch, "
                      "the administrator's keys and quiet hours, core's record in flight / cancelled / held / postponed / over "
                      "its budgets, the day's caps, this edition's ceilings, no file, no id; every answer and every table "
                      "equal" % count)


class LockedClaimDiff(advreport.ReportDiff):
    EXAMPLE = "advhook"

    def test_a_lock_that_is_not_had_in_time_passes(self):
        """Another connection holds core's file under BEGIN IMMEDIATE: the hook waits its half second and writes nothing."""
        twin = advstore.Twin(store.core_home([record_of(0)], (), (ARMED,)))
        try:
            ops = [claim(0, busy=0.3)]
            file = twin.folder / "ops.json"
            file.write_text(json.dumps(ops), encoding="utf-8")
            holders = []
            for home in (twin.python, twin.rust):
                holder = sqlite3.connect(home / "config" / "state.sqlite", timeout=0, isolation_level=None)
                holder.execute("BEGIN IMMEDIATE")
                holders.append(holder)
            ran = advreport.advref.run(RUNNER, str(twin.python), str(file), profile=twin.folder / "python" / "profile")
            self.assertEqual(ran.returncode, 0, ran.stderr[-2000:].decode("utf-8", "replace"))
            request = json.dumps({"cases": [["claim.run", str(twin.rust), ops]]}).encode("utf-8")
            done = advreport.subprocess.run([str(advreport.binary("advhook"))], input=request, capture_output=True,
                                            env=advreport.advref.environment(twin.rust.parent / "profile"),
                                            creationflags=advreport.NO_WINDOW, timeout=600)
            for holder in holders:
                holder.rollback()
                holder.close()
            self.assertEqual(json.loads(done.stdout.decode("utf-8"))["results"][0]["ok"], json.loads(ran.stdout.decode("utf-8")))
            self.assertEqual(json.loads(ran.stdout.decode("utf-8")), [{"ok": None}])
            RECORD.append("hook claim, locked: core's file held under BEGIN IMMEDIATE - both wait their busy time and write nothing")
        finally:
            twin.close()


if __name__ == "__main__":
    unittest.main()
