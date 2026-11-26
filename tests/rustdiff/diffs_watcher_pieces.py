"""S6.1, car-watcher: the watcher's smaller pieces, case by case, on the reference and through `watcher.batch`.

* SweepDiff - setaside.sweep over fixture homes made twice, one copy for each side: set-aside folders and files by
  name (every digit count, `.sweep` twins, case, a name that only looks like one), the installer's journal, an
  installation running or not known, a home that is not provably ours, a folder a running program's file lies in,
  a list of programs that cannot be made, a read-only file deep inside, a junction and a symbolic link among the
  candidates. Equal: (swept, left), the log line, and every name left in the home afterwards.
* PlugNoticesDiff - an edition plug's surface answers in turn: DEFER, no notice, Open Codex and the chat, the
  meter's, the update check's, the account's and the automatic switch's notices, a key seen again, one gone and back,
  past the 64 keys a part remembers, keys that are not text, notices that are not dicts.
* AfterWorkDiff - the power action's looks over a store of its own, the control layer, powerdown and the engine
  answered by each step: a file missing, invalid or unreadable, an arming for tasks counted down to the end and the
  action taken or refused, input and a gap that end a countdown, another person signed in, an action not available,
  the batch not met, an administrator's key, a pause, a failed tick, the watcher stopping mid-countdown.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from rustdiff import core, diffs, reference

PRELUDE = r'''
import json, sys
from pathlib import Path
cases = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
results = []
'''

SWEEP = PRELUDE + r'''
from codex_auto_resume import config, setaside
for home, installing, running in cases:
    lines = []
    try:
        swept, left = setaside.sweep(config.Paths(home), lambda text, *args: lines.append(text % args),
                                     installing=lambda: installing, running=(lambda: running) if running is not None
                                     else (lambda: (_ for _ in ()).throw(OSError("no list"))))
        results.append({"ok": [swept, left, lines]})
    except Exception as error:
        results.append({"error": type(error).__name__})
sys.stdout.write(json.dumps(results, ensure_ascii=False))
'''

NOTICES = PRELUDE + r'''
from codex_auto_resume.domain.plug import DEFER
from codex_auto_resume.runtime.plugnotices import PlugNotices
for (steps,) in cases:
    class Owner(PlugNotices):
        pass
    owner = Owner()
    out = []
    for step in steps:
        raised = []
        owner._watcher_notice = lambda event, detail, final=False: raised.append([event, detail])
        added = DEFER if isinstance(step, dict) and "$defer" in step else step
        owner._edition_notices(added)
        out.append([owner._open_codex, owner._chat, raised])
    results.append({"ok": out})
sys.stdout.write(json.dumps(results, ensure_ascii=False))
'''

AFTERWORK = PRELUDE + r'''
import types
from codex_auto_resume.runtime.afterwork import AfterWork
from codex_auto_resume.store import Store
for state_dir, steps in cases:
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    store = Store(state_dir)
    current, calls, clock = {}, [], {"now": 0.0}

    class Control:
        def read_power_action(self, now):
            calls.append(["read", now])
            found = current.get("read")
            return (found[0], found[1]) if isinstance(found, list) and len(found) == 2 else ("missing", None)

        def power_batch_end(self, nonce, result, now):
            calls.append(["batch_end", nonce, str(result), now])
            return current.get("batch_end") is not False

        def power_batch_finish(self, nonce, now):
            calls.append(["batch_finish", nonce, now])
            return current["finish"] if "finish" in current else "done"

        def power_refused(self, now):
            calls.append(["refused", now])
            return True

        def power_show(self, nonce, shown):
            calls.append(["show", nonce, shown])
            return True

        @property
        def plug(self):
            def power(facts):
                calls.append(["plug_power", facts])
                return current.get("power")
            return types.SimpleNamespace(power=power)

    class Port:
        @staticmethod
        def available(action):
            calls.append(["available", action])
            return (False, "no_privilege") if current.get("available") is False else (True, None)

        @staticmethod
        def other_sessions():
            calls.append(["others"])
            return current["others"] if "others" in current else 0

        @staticmethod
        def idle_seconds():
            calls.append(["idle"])
            return current["idle"] if "idle" in current else 600.0

        @staticmethod
        def act(action):
            calls.append(["act", action])
            return current["act"] if "act" in current else True

        @staticmethod
        def last_error():
            calls.append(["last_error"])
            return current.get("last_error")

    class Engine:
        options = {}

        def activity(self, threads):
            calls.append(["activity", list(threads)])
            return current["activity"] if "activity" in current else {"history": True, "running": 0, "queued": 0}

    lines, notices = [], []
    work = AfterWork(control=Control(), log=lines.append,
                     notice=lambda event, detail, final=False: notices.append([event, detail, final]), port=Port,
                     clock=lambda: clock["now"])
    out = []
    for step in steps:
        current.clear()
        current.update(step)
        clock["now"] = float(step.get("now", 0.0))
        del calls[:], lines[:], notices[:]
        managed = types.SimpleNamespace(disable_power_action=step.get("held") is True,
                                        disable_auto_resume=step.get("paused_by_policy") is True)
        raised = None
        try:
            if step.get("op") == "stop":
                work.stop()
            elif step.get("op") == "halt":
                work.halt()
            else:
                work.look(store, None if step.get("no_engine") else Engine(), ok=step.get("ok") is not False,
                          settings=step.get("settings"), managed=managed)
        except Exception as error:
            raised = type(error).__name__
        out.append({"raised": raised, "calls": list(calls), "lines": list(lines), "notices": list(notices),
                    "counting": work.counting, "cap": float(work.cap(30.0))})
    store.close()
    results.append({"ok": out})
sys.stdout.write(json.dumps(results, ensure_ascii=False))
'''


class Pieces(diffs.Base):
    def both(self, script: str, cases_py: list, cases_rs: list, label: str) -> tuple[list, list]:
        listing = self.profile("cases-%s" % label) / "cases.json"
        listing.write_text(json.dumps(cases_py, ensure_ascii=False), encoding="utf-8")
        made = reference.run(script, str(listing), profile=self.profile("reference-%s" % label))
        self.assertEqual(made.returncode, 0, made.stderr[-4000:].decode("utf-8", "replace"))
        expected = json.loads(made.stdout.decode("utf-8"))
        with core.Harness(reference.scratch_environment(self.profile("rust-%s" % label))) as harness:
            _id, line = harness.call("watcher.batch", cases=cases_rs)
        reply = json.loads(line.decode("utf-8"))
        self.assertTrue(reply["reply"].get("ok"), line[:600])
        return expected, reply["reply"]["value"]

    def same(self, expected, actual, cases, label):
        self.assertEqual(len(expected), len(actual), label)
        for index, (want, got) in enumerate(zip(expected, actual)):
            if diffs.encode(want) != diffs.encode(got):
                self.fail("%s: case %d differs\n  case      %s\n  reference %s\n  rust      %s" % (
                    label, index, json.dumps(cases[index], ensure_ascii=False)[:800],
                    json.dumps(want, ensure_ascii=False)[:1500], json.dumps(got, ensure_ascii=False)[:1500]))


# -------------------------------------------------------------------------------------------------- setaside
STAMP = "20261126010203"
MARKER = ".owned-by-codex-auto-resume"


def fixture(home: Path, shape: dict) -> None:
    home.mkdir(parents=True)
    if shape.get("ours", True):
        (home / MARKER).write_text("ours\n", encoding="utf-8")
    if shape.get("journal"):
        (home / ".codex-auto-resume-install-journal.json").write_text("{}", encoding="utf-8")
    for name in shape.get("folders", []):
        folder = home / name
        (folder / "inner" / "deeper").mkdir(parents=True)
        (folder / "inner" / "deeper" / "file.txt").write_text("x", encoding="utf-8")
        (folder / "top.bin").write_bytes(b"\0" * 10)
    for name in shape.get("files", []):
        (home / name).write_bytes(b"old")
    for name in shape.get("readonly", []):
        target = home / name / "inner" / "locked.txt"
        target.write_text("ro", encoding="utf-8")
        os.chmod(target, 0o444)
    for name in shape.get("junctions", []):
        (home / "elsewhere").mkdir(exist_ok=True)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(home / name), str(home / "elsewhere")], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)


def listing(home: Path) -> list:
    found = []
    for root, folders, files in os.walk(home):
        for name in folders + files:
            found.append(os.path.relpath(os.path.join(root, name), home))
    return sorted(found)


def unlock(home: Path) -> None:
    for root, _folders, files in os.walk(home):
        for name in files:
            try:
                os.chmod(os.path.join(root, name), 0o666)
            except OSError:
                pass


SHAPES = [
    ({"folders": ["app.old-" + STAMP, "runtime.old-" + STAMP]}, False, []),
    ({"folders": ["app.old-" + STAMP, "app.old-" + STAMP + ".sweep"], "files": ["Dashboard.exe.old-" + STAMP]}, False, []),
    ({"folders": ["app.old-2026112601020", "app.OLD-" + STAMP, ".old-" + STAMP, "app.old-" + STAMP + "1"],
      "files": ["x.old-" + STAMP + ".sweep.sweep"]}, False, []),
    ({"folders": ["app.old-" + STAMP]}, True, []),
    ({"folders": ["app.old-" + STAMP]}, None, []),
    ({"folders": ["app.old-" + STAMP], "journal": True}, False, []),
    ({"folders": ["app.old-" + STAMP], "ours": False}, False, []),
    ({"folders": ["app.old-" + STAMP, "runtime.old-" + STAMP]}, False, ["runtime.old-" + STAMP + "\\pythonw.exe"]),
    ({"folders": ["app.old-" + STAMP, "runtime.old-" + STAMP]}, False, None),
    ({"folders": ["app.old-" + STAMP], "readonly": ["app.old-" + STAMP]}, False, []),
    ({"folders": ["app.old-" + STAMP], "junctions": ["link.old-" + STAMP]}, False, []),
    ({"files": ["a.old-" + STAMP, "b.old-" + STAMP + ".sweep"]}, False, ["unrelated\\a.exe"]),
    ({}, False, []),
]


class SweepDiff(Pieces):
    def test_sweep(self):
        base = self.profile("sweep-homes").resolve()
        cases_py, cases_rs = [], []
        for number, (shape, installing, running) in enumerate(SHAPES):
            sides = []
            for side in ("py", "rs"):
                home = base / ("%s-%d" % (side, number))
                fixture(home, shape)
                images = None if running is None else [str(home / each) for each in running]
                sides.append([str(home), installing, images])
            cases_py.append(sides[0])
            cases_rs.append(["sweep"] + sides[1])
        expected, actual = self.both(SWEEP, cases_py, cases_rs, "sweep")
        self.same(expected, actual, cases_py, "sweep")
        for number in range(len(SHAPES)):
            self.assertEqual(listing(base / ("py-%d" % number)), listing(base / ("rs-%d" % number)),
                             "sweep %d: what is left" % number)
        unlock(base)
        shutil.rmtree(base, ignore_errors=True)


# -------------------------------------------------------------------------------------------------- plug notices
def meter(*keys, **fields):
    return {"meter": {"notices": [dict({"key": key, "window_minutes": 300, "used_percent": 91.5, "reset_at": 1.8e9},
                                       **fields) for key in keys]}}


NOTICE_STEPS = [
    [{"$defer": True}, {}, {"notice": {"open_codex": True, "chat": True}}, {"notice": {"open_codex": 1, "chat": "yes"}},
     {"notice": ["open_codex"]}, None, [1, 2], "text"],
    [meter("a", "b"), meter("a", "b"), meter("b", "c", kind="stopped"), meter("a"), {"$defer": True}, meter("a")],
    [{"update": {"notices": [{"key": "v1", "version": "0.6.27", "prerelease": True},
                             {"key": "v2", "version": "0.6.28", "prerelease": "yes"}, {"key": 5}, "nope", None]}},
     {"update": {"notices": [{"key": "v1"}, {"key": "v3"}]}, "account": {"notices": [{"key": "x", "count": 2}]},
      "autoswitch": {"notices": [{"key": "y", "why": "all_limited"}, {"key": "y"}]}},
     {"meter": {"notices": "not a list"}, "update": ["not", "a", "dict"], "account": {"notices": [{"no": "key"}]}}],
    [meter(*["k%d" % n for n in range(70)]), meter("k0", "k5", "k69"), meter(*["n%d" % n for n in range(64)]),
     meter("k69", "k6")],
]


class PlugNoticesDiff(Pieces):
    def test_plug_notices(self):
        cases_py = [[steps] for steps in NOTICE_STEPS]
        cases_rs = [["plug_notices", steps] for steps in NOTICE_STEPS]
        expected, actual = self.both(NOTICES, cases_py, cases_rs, "notices")
        self.same(expected, actual, cases_py, "plug notices")


# -------------------------------------------------------------------------------------------------- afterwork
NOW = 1_800_000_000.0


def armed(**fields):
    base = {"nonce": "0123456789abcdef", "action": "sleep", "since": NOW - 100, "armed_at": NOW - 100,
            "carried": [], "grace_seconds": 120, "repeat": "once", "after": "all_recovered", "stop_at": None,
            "tasks": True}
    base.update(fields)
    return base


def document(**fields):
    return {"format": "codex-auto-resume/power-action/1", "armed": armed(**fields)}


MET = {"tasks": "met", "threads": ["t2", "t1"]}
GO = {"read": ["ok", document()], "power": MET}

AFTERWORK_STEPS = [
    # A file missing, invalid, unreadable; nothing armed.
    [dict(now=NOW, read=["missing", None]), dict(now=NOW + 15, read=["invalid", None]),
     dict(now=NOW + 30, read=["invalid", None]), dict(now=NOW + 45, read=["unreadable", None]),
     dict(now=NOW + 60, read=["ok", {"armed": None}])],
    # Counted down to the end, the action taken.
    [dict(GO, now=NOW), dict(GO, now=NOW + 15, idle=615.0), dict(GO, now=NOW + 120, idle=720.0),
     dict(GO, now=NOW + 135, idle=735.0)],
    # Refused at the end: the error said, the refusal written, the failure raised.
    [dict(GO, now=NOW), dict(GO, now=NOW + 121, idle=721.0, act=False, last_error=1314)],
    [dict(GO, now=NOW), dict(GO, now=NOW + 121, idle=721.0, act=False, last_error=-1)],
    [dict(GO, now=NOW), dict(GO, now=NOW + 121, idle=721.0, finish=None), dict(GO, now=NOW + 140, finish="skipped")],
    # Input, then a gap, end a countdown.
    [dict(GO, now=NOW), dict(GO, now=NOW + 15, idle=3.0), dict(GO, now=NOW + 30), dict(GO, now=NOW + 200, idle=800.0)],
    # Somebody is in the way, Codex is busy, the action is not available, idle unknown.
    [dict(GO, now=NOW, idle=30.0), dict(GO, now=NOW + 15, activity={"history": False}),
     dict(GO, now=NOW + 30, activity={"history": True, "running": 1, "queued": 0}),
     dict(GO, now=NOW + 45, idle=None), dict(GO, now=NOW + 60, available=False)],
    [dict(now=NOW, read=["ok", document(action="shut_down")], power=MET, others=1),
     dict(now=NOW + 15, read=["ok", document(action="shut_down")], power=MET, others=None),
     dict(now=NOW + 30, read=["ok", document(action="shut_down")], power=MET, others=0)],
    # The tasks: running, unknown, not met (said once), not met with the end refused.
    [dict(GO, now=NOW, power={"tasks": "running", "threads": []}), dict(GO, now=NOW + 15, power=None),
     dict(GO, now=NOW + 30, power={"tasks": "not_met", "threads": []}, batch_end=False),
     dict(GO, now=NOW + 45, power={"tasks": "not_met", "threads": []})],
    # An administrator's key, a pause, a failed tick, a stop pressed.
    [dict(GO, now=NOW, held=True), dict(GO, now=NOW + 15, held=True), dict(GO, now=NOW + 30, paused_by_policy=True),
     dict(GO, now=NOW + 45, settings={"observe_only": True}), dict(GO, now=NOW + 60, ok=False),
     dict(now=NOW + 75, read=["ok", document(stop_at=NOW + 70)], power=MET)],
    # The watcher stops mid-countdown; a halt; armed again with another nonce.
    [dict(GO, now=NOW), dict(op="stop", now=NOW + 5), dict(GO, now=NOW + 20), dict(op="halt", now=NOW + 25),
     dict(GO, now=NOW + 40), dict(now=NOW + 55, read=["ok", document(nonce="fedcba9876543210")], power=MET),
     dict(now=NOW + 70, read=["ok", None])],
    # An arming that is not for tasks, over an empty store: no batch, then lapsed.
    [dict(now=NOW, read=["ok", document(tasks=None)]), dict(now=NOW + 86_400, read=["ok", document(tasks=None)])],
    # No engine to ask.
    [dict(GO, now=NOW, no_engine=True)],
]


class AfterWorkDiff(Pieces):
    def test_afterwork(self):
        base = self.profile("afterwork").resolve()
        cases_py = [[str(base / ("py-%d" % n)), steps] for n, steps in enumerate(AFTERWORK_STEPS)]
        cases_rs = [["afterwork", str(base / ("rs-%d" % n)), steps] for n, steps in enumerate(AFTERWORK_STEPS)]
        expected, actual = self.both(AFTERWORK, cases_py, cases_rs, "afterwork")
        self.same(expected, actual, cases_py, "afterwork")
