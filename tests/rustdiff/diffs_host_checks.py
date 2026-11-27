"""Diagnostics' check and Rescan's judge through the real host (seat S6.2b4): `detection-check` and `rescan` answered
by the watcher's own rules - car-watcher `checkup::run`, `rescan::judge_for`, behind `checkhost::WatcherHost` as
car-bin's bridge and the host's `car_bridge` wrap their host - against the tag's `checkup.run` and
`rescan.judge_for`, both over the same scratch installation and the same world (bridgeworld's and actworld's: the
clock, the mutex, the registry's view, the tokens, ...). Nothing of either check is a stand-in here: only what Windows
says of a notice's route (`checkup._presence`, the world's `presence`) and, for the goldens, the aliases' key
(`checkup.Redactor`, as tests/wiregolden.py pins it).

* GoldenChecksDiff - the wire goldens' own cases (tests/golden/bridge/detection-check.json and rescan.json): the
                     reference over the world equals the golden file, and car-watcher equals the golden file.
* CheckupDiff      - detection-check over the golden home and its edges: paused, an administrator's pause, a
                     conversation switched off, unreadable and damaged settings, a missing or unreadable Codex home, a
                     second home, every route answer and a raising probe, the registry's view of every shape, another
                     Interface language, an empty and a fresh home; replies, files, the state and the Host calls.
* RescanDiff       - rescan over the golden home and its edges: a person's later turn (retired), a record of a home
                     Settings do not know, a missing Codex home, a second home, a record whose turn is gone.

Run by run.py; never by the lanes' discovery.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from rustdiff import actworld as aw
from rustdiff.diffs import RECORD
from rustdiff.diffs_bridge_acting import ActingBase, now, stream, with_store, write_file

import wiregolden as wg

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden" / "bridge"
PRESENCE = {"route": "toast", "do_not_disturb": False, "app_allowed": True}
GOLDEN_KEY = b"wire-golden-check"

# The reference's checkup and rescan put back after actworld's stand-ins, `_presence` and (where the world names one)
# the aliases' key pinned as wiregolden pins them.
KEEP = r'''
from codex_auto_resume import checkup as _real_checkup, rescan as _real_rescan, diagnostics as _real_diagnostics
_kept = (_real_checkup.run, _real_checkup.for_bundle, _real_rescan.judge_for)
'''
REAL = r'''
_real_checkup.run, _real_checkup.for_bundle, _real_rescan.judge_for = _kept
def _world_presence():
    found = world.get("presence")
    if isinstance(found, dict) and "raise" in found:
        raise _exception(found["raise"])
    return found
_real_checkup._presence = _world_presence
if world.get("check_key"):
    class _Pinned(_real_diagnostics.Redactor):
        def __init__(self):
            super().__init__()
            self._key = bytes.fromhex(world["check_key"])
    _real_checkup.Redactor = _Pinned
'''


def real(**changes) -> dict:
    found = {"real_checks": True, "presence": PRESENCE}
    found.update(changes)
    return found


def golden_compat() -> dict:
    """The registry's view the goldens' installation gives before any watcher wrote a report (compatibility.json)."""
    document = json.loads((GOLDEN / "compatibility.json").read_text(encoding="utf-8"))
    return document["cases"][0]["reply"]["compatibility"]


def check_pinned(workspace: Path):
    """wiregolden's `_check_pinned` files: a usage limit, a subagent's failure, a split conversation."""
    with wg._check_pinned(workspace):
        pass


def settings_edit(**values):
    def tune(workspace: Path):
        path = workspace / "home" / "config" / "settings.json"
        document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        document.update(values)
        path.write_text(json.dumps(document), encoding="utf-8")
    return tune


def chained(*tunes):
    def tune(workspace):
        for each in tunes:
            each(workspace)
    return tune


def second_home(workspace: Path):
    """A second Codex home in Settings: a copy of the first."""
    import shutil
    shutil.copytree(workspace / "codex", workspace / "codex2", dirs_exist_ok=True)
    settings_edit(codex_homes=[{"path": str(workspace / "codex2"), "alias": "Second"},
                               {"path": 7}, "not a home", {"path": str(workspace / "missing")}])(workspace)


def history_gone(workspace: Path):
    for path in (workspace / "codex").glob("thread_history*.sqlite*"):
        path.unlink()


def history_damaged(workspace: Path):
    for path in sorted((workspace / "codex").glob("thread_history*.sqlite")):
        path.write_bytes(b"not a database")


def later_turn(workspace: Path):
    """A turn a person started after record 7's failure (T1's)."""
    from test_continuation_split import SplitHome

    sim = SplitHome.__new__(SplitHome)
    sim.root, sim._items, sim.clock, sim.split, sim.current = workspace / "codex", 5000, lambda: now(), {}, {}
    sim.fail_transient(wg.T1, "0a1b2c3d-0301-7000-8000-000000000077", completed=int(now() - 30))


def unknown_home(workspace: Path):
    for path in (workspace / "home").rglob("state.sqlite"):
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute("UPDATE interruptions SET home_key=? WHERE interruption_id=?",
                                   ("f" * 64, wg.WAITING_RESET))
        finally:
            connection.close()


class ChecksBase(ActingBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        kept = aw.HOOK
        aw.HOOK = KEEP + kept + REAL
        cls.addClassCleanup(setattr, aw, "HOOK", kept)

    def golden_case(self, command, index):
        document = json.loads((GOLDEN / ("%s.json" % command)).read_text(encoding="utf-8"))
        return document["cases"][index]["reply"]

    def replies(self, out: bytes) -> list:
        return [json.loads(line)["reply"] for line in out.decode("utf-8").splitlines() if line.strip()]


class GoldenChecksDiff(ChecksBase):
    def test_detection_check_golden(self):
        world = real(watcher_running=True, compat_view=golden_compat(), check_key=GOLDEN_KEY.hex())
        out, _ = self.run_both("acts", requests=stream("detection-check", None), world=world, tune=check_pinned,
                               label="detection-check: the golden case")
        self.assertEqual(self.replies(out), [self.golden_case("detection-check", 0)],
                         "the reference over this world is not the golden; so neither is car-watcher")
        RECORD.append("host checks: detection-check's golden case equal through the real host")

    def test_rescan_golden(self):
        for running in (True, False):
            with self.subTest(running=running):
                out, _ = self.run_both("acts", requests=stream("rescan", None, None),
                                       world=real(watcher_running=running), label="rescan: the golden cases")
                if running is False:
                    self.assertEqual(self.replies(out), [self.golden_case("rescan", 0), self.golden_case("rescan", 1)])
        RECORD.append("host checks: rescan's two golden cases equal through the real host")


class CheckupDiff(ChecksBase):
    def check(self, label, world=None, tune=None, kind="acts", requests=None):
        if callable(world):
            made = (lambda ws: real(**world(ws)))
        else:
            made = real(**(world or {}))
        self.run_both(kind, requests=requests or stream("detection-check", None), world=made, tune=tune,
                      label="detection-check: " + label)

    def test_edges(self):
        cases = [
            ("the golden home", {}, check_pinned),
            ("the golden home, watcher running", {"watcher_running": True}, check_pinned),
            ("the golden home, no pinned files", {}, None),
            ("paused", {}, chained(check_pinned, with_store(lambda store: store.set_enabled(False, now() - 60)))),
            ("an administrator's pause", {"managed": {"disable_auto_resume": True}}, check_pinned),
            ("a conversation switched off", {}, chained(check_pinned, with_store(
                lambda store: store.set_thread_enabled(wg.T2, False, actor="gui", at=now() - 60)))),
            ("a category switched off", {}, chained(check_pinned, settings_edit(recover_server_5xx=False))),
            ("settings that hold no JSON", {}, chained(check_pinned, write_file("home/config/settings.json",
                                                                                b"{not json"))),
            ("settings of the wrong kind", {}, chained(check_pinned, write_file("home/config/settings.json",
                                                                                b"[1, 2]"))),
            ("the Interface language Korean", {}, chained(check_pinned, settings_edit(interface_language="ko"))),
            ("the Interface language unknown", {}, chained(check_pinned, settings_edit(interface_language=17))),
            ("the Codex home missing", lambda ws: {"codex_home": str(ws / "nowhere")}, check_pinned),
            ("the history gone", {}, chained(check_pinned, history_gone)),
            ("the history damaged", {}, chained(check_pinned, history_damaged)),
            ("a second home and refused entries", {}, chained(check_pinned, second_home)),
            ("presence: a card", {"presence": {"route": "card", "do_not_disturb": None, "app_allowed": None}},
             check_pinned),
            ("presence raises", {"presence": {"raise": "OSError"}}, check_pinned),
            ("the registry's view", {"compat_view": golden_compat()}, check_pinned),
            ("the registry's view, an engine found",
             {"compat_view": {"overall": "verified", "engine": {"found": True, "version": "0.130.0"}}}, check_pinned),
            ("the registry's view, not a dict", {"compat_view": ["x"]}, check_pinned),
            ("the registry's view, an engine of text", {"compat_view": {"overall": "x", "engine": "text"}},
             check_pinned),
            ("the registry's view, an empty engine", {"compat_view": {"overall": 3, "engine": {}}}, check_pinned),
            ("twice", {}, check_pinned, stream("detection-check", None, None)),
        ]
        for case in cases:
            label, world, tune = case[:3]
            requests = case[3] if len(case) > 3 else None
            with self.subTest(label):
                self.check(label, world=world, tune=tune, requests=requests)
        RECORD.append("host checks: detection-check over %d worlds equal - replies, files, state, Host calls"
                      % len(cases))

    def test_empty_homes(self):
        for kind in ("empty", "fresh"):
            with self.subTest(kind):
                self.run_both(kind, requests=stream("detection-check", None), world=real(),
                              label="detection-check on a %s home" % kind)

    def test_the_bundle(self):
        self.run_both("acts", requests=lambda ws: stream("diagnostics", {"path": str(ws / "bundle.json")}),
                      world=real(), tune=check_pinned, label="diagnostics: the bundle's check")


class RescanDiff(ChecksBase):
    def test_edges(self):
        cases = [
            ("a person's later turn", {}, later_turn),
            ("a record of a home Settings do not know", {}, unknown_home),
            ("a second home", {}, second_home),
            ("the history gone", {}, history_gone),
            ("the history damaged", {}, history_damaged),
            ("the split conversation", {}, check_pinned),
            ("the watcher running", {"watcher_running": True, "signals": {"wake": True}}, check_pinned),
        ]
        for label, world, tune in cases:
            with self.subTest(label):
                self.run_both("acts", requests=stream("rescan", None, None) + [aw_history()], world=real(**world),
                              tune=tune, label="rescan: " + label)
        with self.subTest("the Codex home missing"):
            self.run_both("acts", requests=stream("rescan", None), world=lambda ws: real(codex_home=str(ws / "no")),
                          label="rescan: the Codex home missing")
        for kind in ("empty", "fresh"):
            with self.subTest(kind):
                self.run_both(kind, requests=stream("rescan", None), world=real(), label="rescan on a %s home" % kind)
        RECORD.append("host checks: rescan over %d worlds equal - replies, files, state, Host calls" % (len(cases) + 3))


def aw_history():
    from rustdiff.diffs_bridge import request
    return request("history", ident=9)
