"""car-control's quiet bridge commands, one by one (seat S5.1a): the same requests through the reference tag's
`controlcli` and through car-control over the same scratch installation and the same world; the replies, the exit
codes and the files the commands wrote must be equal byte for byte. See diffs_bridge.py for the framing and
bridgeworld.py for the world.

* GoldenCasesDiff - every case the wire goldens ask of each quiet command (`wiregolden.BRIDGE_CASES`), in order, on
  the golden installation, as one `serve` stream per command (the stand-ins of the cases that need one are the
  world's, below).
* WorldDiff - the world varied: the watcher's mutex, the Run value, the administrator's keys, the install lock,
  languages and the environment, who may open the state folder, where the watcher runs, the compatibility view.
* DamagedDiff - damaged, empty and huge homes: no home at all, no state, a state that is not SQLite or is newer,
  older schemas under the install lock, a settings file that is garbage or huge or deep, a failure-seen file of every
  kind, a log of every kind, a once-words file of every kind.
* WriterDiff - the commands that write (update, defaults, failure-seen, conversation-message, home-dismiss): the
  files they leave equal.

Run by run.py with diffs.py; never by the lanes' discovery.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from rustdiff import bridgeworld as bw
from rustdiff import core, reference
from rustdiff.diffs import RECORD
from rustdiff.diffs_bridge import BridgeBase, lines, request

ROOT = core.ROOT
for entry in (ROOT / "tests", ROOT / "build", ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

# The commands this seat answers: read from the state, the settings, the store, Codex's files and the vocabulary.
QUIET = ("status", "settings", "describe", "defaults", "pending", "pending-all", "strings", "history", "dashboard",
         "failure-seen", "plugin-copy", "state-access", "host-app", "home-suggestion", "update", "timeline",
         "statistics", "check-setting", "preview-continuation", "conversation-message", "logs", "once-words",
         "home-dismiss")
KEY = "%x" % 7 * 64
THREAD = "11111111-1111-7111-8111-111111111111"


def golden_now() -> float:
    import make_screenshots

    return float(make_screenshots.ENVELOPE_NOW)


class QuietBase(BridgeBase):
    def asked(self, kind: str, requests, *, world=None, tune=None, label="", files=True):
        """One `serve` stream of `requests` (JSON objects, or a function of the workspace giving them) on both sides."""
        asked_world = world
        if kind == "golden":
            def world(workspace, asked_world=asked_world):
                made = dict((asked_world(workspace) if callable(asked_world) else asked_world) or {})
                made.setdefault("now", golden_now())
                return made

        def stream(workspace: Path) -> bytes:
            made = requests(workspace) if callable(requests) else requests
            return lines(*made)

        return self.same(kind, stream, world=world, tune=tune, label=label, files=files)


class GoldenCasesDiff(QuietBase):
    def test_every_golden_case(self):
        import wiregolden

        total = 0
        for command in QUIET:
            cases = list(wiregolden.BRIDGE_CASES.get(command, []))
            if command == "once-words":
                # Setting words is control.actions' (S5.1b): the read form is this seat's.
                cases = [case for case in cases if "text" not in (case.argument or {})]
            if not cases:
                continue
            for watching in (True, False):
                group = [case for case in cases]

                def build(workspace, group=group, command=command):
                    made = []
                    for index, case in enumerate(group, 1):
                        made.append(request(command, case.value(workspace), ident=index))
                    return made

                with self.subTest(command=command, watching=watching):
                    self.asked("golden", build, world={"watcher_running": watching},
                               label="%s (watcher %s)" % (command, "running" if watching else "not running"))
                total += len(group)
        RECORD.append("bridge: %d of the wire goldens' cases (%d quiet commands) equal, the watcher running and not"
                      % (total, len(QUIET)))


def managed_worlds() -> list:
    return [
        {"disable_auto_resume": True},
        {"force_observe_only": True},
        {"max_recovery_attempts": 2},
        {"disable_status_file": True, "disable_update_check": True},
        {"disable_power_action": True},
        {"quiet_hours": [{"quiet_hours_start": "22:00", "quiet_hours_end": "07:00", "quiet_hours_days": "weekdays"}]},
        {"disable_auto_resume": True, "force_observe_only": True, "max_recovery_attempts": 3,
         "quiet_hours": [{"quiet_hours_start": "23:30", "quiet_hours_end": "06:30", "quiet_hours_days": "every_day"},
                         {"quiet_hours_start": "01:00", "quiet_hours_end": "02:00", "quiet_hours_days": "weekends"}]},
    ]


class WorldDiff(QuietBase):
    READS = ("status", "settings", "describe", "dashboard", "host-app", "state-access", "plugin-copy", "strings",
             "home-suggestion")

    def reads(self):
        return [request(command, ident=index) for index, command in enumerate(self.READS, 1)]

    def test_the_watcher_and_the_run_value(self):
        for running in (True, False, None):
            for value in (None, "", "pythonw.exe C:\\elsewhere\\watcher.py run"):
                with self.subTest(running=running, value=value):
                    self.asked("golden", [request("status", ident=1), request("dashboard", ident=2)],
                               world={"watcher_running": running, "startup_value": value},
                               label="watcher %s, Run value %r" % (running, value))

    def test_the_run_value_that_belongs_here(self):
        def build(workspace):
            return [request("status", ident=1)]

        for form in ("pythonw.exe {home}\\watcher-launcher.py run", "pythonw.exe -X x {home}\\watcher-launcher.py run",
                     "{home}\\runtime\\pythonw.exe {home}\\app\\src\\auto_resume.py --home {home} run",
                     "pythonw.exe C:\\somewhere\\auto_resume.py --home {home}\\ run"):
            with self.subTest(form=form):
                self.asked("golden", build, label="Run value %r" % form, world=lambda workspace, form=form: {
                    "watcher_running": True, "now": golden_now(),
                    "startup_value": form.format(home=str(workspace / "home"))})

    def test_managed_keys(self):
        for held in managed_worlds():
            with self.subTest(held=held):
                self.asked("golden", [
                    request("status", ident=1), request("settings", ident=2), request("describe", ident=3),
                    request("dashboard", ident=4),
                    request("update", {"observe_only": True, "notifications": True}, ident=5),
                    request("update", {"max_recovery_attempts": 9}, ident=6),
                    request("update", {"max_recovery_attempts": 1}, ident=7),
                    request("update", {"quiet_hours_start": "21:00"}, ident=8),
                    request("check-setting", {"name": "max_recovery_attempts", "value": 4}, ident=9),
                    request("defaults", ident=10), request("status", ident=11)],
                    world={"managed": held, "watcher_running": True}, label="managed %r" % held)

    def test_install_lock_and_superseded(self):
        for lock in (True, False, None):
            for superseded in (False, True):
                with self.subTest(lock=lock, superseded=superseded):
                    self.asked("golden", [request("status", ident=1), request("pending", ident=2),
                                          request("timeline", {"interruption_id": KEY}, ident=3),
                                          request("statistics", {"days": 7}, ident=4),
                                          request("host-app", ident=5)],
                               world={"install_in_progress": lock, "superseded": superseded})

    def test_languages_and_environment(self):
        worlds = [{"languages": ["ko-KR"]}, {"languages": ["ja", "en"]}, {"languages": ["zh-Hant-TW"]},
                  {"languages": ["pt-BR"]}, {"languages": ["xx-YY"]}, {"languages": []},
                  {"environ": {"CODEX_AUTO_RESUME_LANG": "de"}}, {"environ": {"CODEX_AUTO_RESUME_LANG": " fr "}},
                  {"environ": {"LANG": "ru_RU.UTF-8"}}, {"environ": {"LC_ALL": "C", "LANG": "es_ES.UTF-8"}},
                  {"languages": ["he"], "environ": {"LANG": "ar_SA.UTF-8"}}]
        for world in worlds:
            with self.subTest(world=world):
                self.asked("golden", [request("strings", ident=1), request("describe", ident=2),
                                      request("preview-continuation", {"category": "usage_limit"}, ident=3),
                                      request("update", {"interface_language": "ko"}, ident=4),
                                      request("strings", ident=5),
                                      request("update", {"interface_language": "system"}, ident=6),
                                      request("strings", ident=7),
                                      request("update", {"interface_language": "xx"}, ident=8),
                                      request("strings", ident=9),
                                      request("update", {"continuation_language": "ja"}, ident=10),
                                      request("preview-continuation", {"category": "network_transient"}, ident=11)],
                           world=world)

    def test_host_app_and_access(self):
        inside = {"state": "inside", "family": "OpenAI.Codex_2p2nqsd0c76g0", "app": "OpenAI.Codex"}
        outside = {"state": "outside", "family": None, "app": None}
        unknown = {"state": "unknown", "family": None, "app": None}
        for running in (True, False, None):
            for apps in ({"default": outside, "pids": {}}, {"default": inside, "pids": {}},
                         {"default": unknown, "pids": {"4242": inside}}):
                for word in ("owner_only", "shared", "codex_sandbox", "unknown"):
                    with self.subTest(running=running, apps=apps, word=word):
                        self.asked("golden", [request("host-app", ident=1), request("state-access", ident=2)],
                                   world={"watcher_running": running, "host_app": apps, "state_access": word})

    def test_homes_and_the_compatibility_view(self):
        views = [None, {"status": "ok", "engine": {"version": "0.130.0", "found": True}},
                 {"engine": {"version": "9.9"}}, {"engine": {"found": False}}, {"engine": 5}, 7]
        for view in views:
            with self.subTest(view=view):
                def build(workspace, view=view):
                    other = workspace / "other-codex"
                    other.mkdir(exist_ok=True)
                    (other / "state_5.sqlite").write_bytes(b"")
                    return [request("update", {"codex_homes": [{"path": str(other), "alias": "work"}]}, ident=1),
                            request("status", ident=2), request("dashboard", ident=3),
                            request("update", {"codex_homes": []}, ident=4), request("status", ident=5)]

                self.asked("golden", build, world={"compat_view": view, "watcher_running": True},
                           label="compat view %r" % (view,))

    def test_home_suggestion_in_an_installed_copy(self):
        def build(workspace):
            other = workspace / "other-codex"
            other.mkdir(exist_ok=True)
            (other / "state_5.sqlite").write_bytes(b"")
            third = workspace / "third-codex"
            third.mkdir(exist_ok=True)
            (third / "state_9.sqlite").write_bytes(b"")
            return [request("home-suggestion", ident=1),
                    request("home-dismiss", {"path": str(other)}, ident=2),
                    request("home-suggestion", ident=3),
                    request("home-dismiss", {"path": str(other) + "\\"}, ident=4),
                    request("home-dismiss", {"path": "  "}, ident=5), request("home-dismiss", {}, ident=6),
                    request("home-dismiss", {"path": 5}, ident=7),
                    request("update", {"home_suggestions": False}, ident=8), request("home-suggestion", ident=9),
                    request("update", {"home_suggestions": True}, ident=10),
                    request("update", {"codex_homes": [{"path": str(third), "alias": "third"}]}, ident=11),
                    request("home-suggestion", ident=12)]

        def worlds(workspace):
            other, third = workspace / "other-codex", workspace / "third-codex"
            return {"installed": True, "account_codex_home": str(other),
                    "app_homes": [str(workspace / "codex"), str(other) + "\\", str(third), "relative\\path",
                                  "\\\\server\\share\\home", str(workspace / "missing")]}

        for case in ("installed", "checkout"):
            with self.subTest(case=case):
                self.asked("golden", build, label="home suggestion, " + case,
                           world=lambda workspace, case=case: dict(
                               {"now": golden_now()}, **(worlds(workspace) if case == "installed" else {})))


def settings_file(data):
    def tune(workspace: Path):
        target = workspace / "home" / "config" / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            target.unlink(missing_ok=True)
        elif data == "directory":
            target.unlink(missing_ok=True)
            target.mkdir()
        else:
            target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return tune


def state_file(data):
    def tune(workspace: Path):
        target = workspace / "home" / "config" / "state.sqlite"
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        if data is not None:
            target.write_bytes(data)
    return tune


def seen_file(data):
    def tune(workspace: Path):
        target = workspace / "home" / "config" / "failure-seen.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        if data is not None:
            target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return tune


def words_file(data):
    def tune(workspace: Path):
        target = workspace / "home" / "config" / "once-words.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        if data is not None:
            target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return tune


def log_file(text, *, rotated=None):
    def tune(workspace: Path):
        folder = workspace / "home" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "auto-resume.log").write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        for number, body in (rotated or {}).items():
            (folder / ("auto-resume.log.%d" % number)).write_bytes(
                body if isinstance(body, bytes) else body.encode("utf-8"))
    return tune


READS_ALL = [request(command, ident=index) for index, command in enumerate(
    ("status", "settings", "describe", "pending", "pending-all", "history", "dashboard", "failure-seen",
     "plugin-copy", "state-access", "host-app", "home-suggestion", "strings"), 1)]


class DamagedDiff(QuietBase):
    def every(self, kind, tune, *, label, world=None, extra=()):
        requests = READS_ALL + [request("timeline", {"interruption_id": KEY}, ident=40),
                                request("statistics", {"days": 3}, ident=41), request("statistics", {}, ident=42),
                                request("logs", {}, ident=43),
                                request("once-words", {"interruption_id": KEY}, ident=44),
                                request("update", {"notifications": False}, ident=45),
                                request("defaults", ident=46), request("status", ident=47), *extra]
        self.asked(kind, requests, tune=tune, label=label, world=world)

    def test_no_home_and_no_state(self):
        for kind in ("fresh", "empty"):
            for running in (True, False, None):
                with self.subTest(kind=kind, running=running):
                    self.every(kind, None, label="%s, watcher %s" % (kind, running), world={"watcher_running": running})

    def test_states_that_cannot_be_opened(self):
        newer = b"SQLite format 3\x00" + b"\x00" * 84
        cases = {"garbage": state_file(b"this is not a database" * 50), "empty file": state_file(b""),
                 "a header only": state_file(newer), "a folder": None}
        for name, tune in cases.items():
            if tune is None:
                continue
            with self.subTest(name):
                self.every("golden", tune, label=name)

    def test_states_of_other_schemas(self):
        import sqlite3

        def schema(version, *, mark=False):
            def tune(workspace: Path):
                path = workspace / "home" / "config" / "state.sqlite"
                connection = sqlite3.connect(path)
                try:
                    connection.execute("PRAGMA user_version=%d" % version)
                    if mark:
                        connection.execute("PRAGMA application_id=%d" % 0x43410505)
                    connection.commit()
                finally:
                    connection.close()
            return tune

        for name, tune in (("schema 6, unmarked", schema(6)), ("schema 99", schema(99)), ("schema 0", schema(0)),
                           ("schema 4 of the golden installation", schema(4))):
            with self.subTest(name):
                self.every("golden", tune, label=name)

    def test_older_watchers_states(self):
        from rustdiff.diffs_store import THREAD as T, OTHER, _released_store

        for tag in ("v0.6.10", "v0.6.13"):
            for lock in (True, False):
                with self.subTest(tag=tag, lock=lock):
                    def tune(workspace: Path, tag=tag):
                        fixtures = workspace / "fixtures"
                        fixtures.mkdir(exist_ok=True)
                        made = _released_store(tag, fixtures, workspace / "profile")
                        target = workspace / "home" / "config"
                        target.mkdir(parents=True, exist_ok=True)
                        import shutil

                        for suffix in ("", "-wal", "-shm", "-journal"):
                            Path(str(target / "state.sqlite") + suffix).unlink(missing_ok=True)
                        shutil.copyfile(made, target / "state.sqlite")

                    self.every("golden", tune, label="%s under the install lock=%s" % (tag, lock),
                               world={"install_in_progress": lock, "watcher_running": not lock})

    def test_settings_files(self):
        cases = {
            "garbage": settings_file(b"{not json"), "empty": settings_file(b""),
            "a list": settings_file(b"[1, 2]"), "null": settings_file(b"null"),
            "a folder": settings_file("directory"), "missing": settings_file(None),
            "nested 100": settings_file("[" * 100 + "]" * 100),
            "nested 100000": settings_file("[" * 100000),
            "huge": settings_file(b'{"x": "' + b"a" * (5 * 1024 * 1024) + b'"}'),
            "NaN": settings_file(b'{"max_recovery_attempts": NaN, "notifications": Infinity}'),
            "a lone surrogate": settings_file(b'{"custom_message": "\\ud800"}'),
            "wrong types": settings_file(json.dumps({"notifications": "yes", "max_recovery_attempts": "3",
                                                     "interface_language": 5, "codex_homes": 7})),
            "an older config_version": settings_file(json.dumps({"config_version": 1, "notifications": False})),
            "a newer config_version": settings_file(json.dumps({"config_version": 99, "notifications": False})),
            "unknown fields": settings_file(json.dumps({"no_such": 1, "notifications": False})),
            "not UTF-8": settings_file(b'{"x": "\xff\xfe"}'),
            "a byte order mark": settings_file(b'\xef\xbb\xbf{"notifications": false}'),
        }
        for name, tune in cases.items():
            with self.subTest(name):
                self.asked("golden", [request("settings", ident=1), request("status", ident=2),
                                      request("describe", ident=3), request("strings", ident=4),
                                      request("update", {"notifications": False}, ident=5),
                                      request("settings", ident=6), request("defaults", ident=7),
                                      request("settings", ident=8), request("defaults", ident=9)],
                           tune=tune, label=name)

    def test_failure_seen_files(self):
        cases = {"missing": None, "a number": '{"seen_at": 1700000000.5}', "an integer": '{"seen_at": 5}',
                 "negative": '{"seen_at": -1}', "NaN": '{"seen_at": NaN}', "a bool": '{"seen_at": true}',
                 "text": '{"seen_at": "5"}', "a list": "[1]", "garbage": "{", "empty": "",
                 "far ahead": '{"seen_at": 99999999999.0}', "huge int": '{"seen_at": %s}' % ("9" * 400),
                 "past the limit": '{"seen_at": 1, "pad": "%s"}' % ("a" * 5000),
                 "nested 4096": "[" * 4096, "not UTF-8": b'{"seen_at": "\xff"}'}
        for name, data in cases.items():
            with self.subTest(name):
                self.asked("golden", [request("status", ident=1), request("failure-seen", ident=2),
                                      request("status", ident=3), request("failure-seen", ident=4)],
                           tune=seen_file(data), label="failure-seen file: " + name)

    def test_logs(self):
        good = "".join("[2026-09-27 10:%02d:00] line %d about thread and usage\n" % (index % 60, index)
                       for index in range(300))
        body = good + "not a log line\n[2026-09-27 99:99:99] odd but shaped\n[٢٠٢٦-٠٩-٢٧ ١٠:٠٠:٠٠] arabic digits\n"
        cases = {"none": None, "small": "[2026-09-27 10:00:00] a\n", "mixed": body,
                 "empty text after the time": "[2026-09-27 10:00:00] \n[2026-09-27 10:00:01] x\n",
                 "a long line": "[2026-09-27 10:00:00] %s\n[2026-09-27 10:00:01] %s\n" % ("a" * 2000, "b" * 2001),
                 "CRLF and odd separators": "[2026-09-27 10:00:00] a\r\n[2026-09-27 10:00:01] b\x0bc\x1d[2026-09-27 10:00:02] d\n",
                 "unicode": "[2026-09-27 10:00:00] Stra\u00dfe \u0130stanbul \u1e9e\n",
                 "not UTF-8": b"[2026-09-27 10:00:00] caf\xe9 \xff\n[2026-09-27 10:00:01] ok\n",
                 "past two megabytes": "[2026-09-27 10:00:00] first\n" + ("[2026-09-27 10:00:01] filler line\n" * 150000)
                 + "[2026-09-27 10:00:02] last\n"}
        queries = [{}, {"query": "thread"}, {"query": "  USAGE "}, {"query": "STRASSE"}, {"query": "\u0131"},
                   {"query": "x" * 100}, {"query": "x" * 101}, {"query": "a\nb"}, {"query": 5},
                   {"query": None, "limit": 3}, {"limit": 0}, {"limit": 501}, {"limit": True}, {"limit": 2.0},
                   {"limit": 500}, {"query": "line", "limit": 7}, {"query": ""}]
        for name, text in cases.items():
            with self.subTest(name):
                tune = None if text is None else log_file(
                    text, rotated={1: "[2026-09-26 09:00:00] rotated one\n", 5: "[2026-09-25 09:00:00] rotated five\n"})
                self.asked("golden", [request("logs", argument, ident=index) for index, argument in
                                      enumerate(queries, 1)], tune=tune, label="logs: " + name)

    def test_once_words_files(self):
        entry = lambda written="1700000000.5", text="go on": {  # noqa: E731
            KEY: {"text": text, "written_at": json.loads(written)}}
        cases = {"missing": None, "good": json.dumps(entry()), "garbage": "{", "a list": "[]",
                 "an entry with no text": json.dumps({KEY: {"written_at": 1.0}}),
                 "a text that is refused": json.dumps(entry(text="{prompt}")),
                 "a text of spaces": json.dumps(entry(text="   ")),
                 "a bool time": json.dumps({KEY: {"text": "go", "written_at": True}}),
                 "a negative time": json.dumps(entry("-1")),
                 "a huge time": '{"%s": {"text": "go", "written_at": %s}}' % (KEY, "9" * 400),
                 "NaN time": '{"%s": {"text": "go", "written_at": NaN}}' % KEY,
                 "an id in capitals": json.dumps({KEY.upper(): {"text": "go", "written_at": 1.0}}),
                 "an id too short": json.dumps({"abc": {"text": "go", "written_at": 1.0}}),
                 "51 entries": json.dumps({("%064x" % index): {"text": "go", "written_at": 1.0} for index in range(51)}),
                 "50 entries": json.dumps({("%064x" % index): {"text": "go", "written_at": 1.0} for index in range(50)}),
                 "2000 characters": json.dumps(entry(text="a" * 2000)),
                 "2001 characters": json.dumps(entry(text="a" * 2001)),
                 "past the limit": json.dumps(entry(text="a")) + " " * (512 * 1024),
                 "not UTF-8": b'{"x": "\xff"}', "nested": "[" * 5000}
        for name, data in cases.items():
            with self.subTest(name):
                keys = [KEY, "%064x" % 3, "%064x" % 49, "%064x" % 50]
                self.asked("golden", [request("once-words", {"interruption_id": key}, ident=index)
                                      for index, key in enumerate(keys, 1)]
                           + [request("pending", ident=10), request("history", ident=11),
                              request("once-words", {"interruption_id": "nope"}, ident=12),
                              request("once-words", {}, ident=13)],
                           tune=words_file(data), label="once-words file: " + name)

    def test_a_huge_home(self):
        script = r'''
import sqlite3, sys
from pathlib import Path
from codex_auto_resume import machine
from codex_auto_resume.store import Store
root = Path(sys.argv[1])
states = sorted(machine.STATES)
categories = ["usage_limit", "server_5xx", "network_transient", "rate_limit_transient"]
with Store(root, clock=lambda: 1_700_000_000.0) as store:
    store.set_enabled(True, 1_700_000_000.0)
    for index in range(1500):
        thread = "0a1b2c3d-0010-7000-8000-%012d" % (index % 40)
        store.register({"thread_id": thread, "turn_id": "0a1b2c3d-0011-7000-8000-%012d" % index,
                        "completed_at": 1_700_000_000.0 + index, "started_at": 1_700_000_000.0 + index - 5,
                        "ordinal": index, "interruption_id": "%064x" % (index + 1000), "reset_at": None,
                        "limit_type": "x", "uncertain": False, "category": categories[index % 4]},
                       1_700_000_000.0 + index)
db = sqlite3.connect(root / "state.sqlite")
for index in range(1500):
    state = states[index % len(states)]
    db.execute("UPDATE interruptions SET state=? WHERE interruption_id=?", (state, "%064x" % (index + 1000)))
db.commit()
db.close()
'''

        def tune(workspace: Path):
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(str(workspace / "home" / "config" / "state.sqlite") + suffix).unlink(missing_ok=True)
            done = reference.run(script, workspace / "home" / "config", profile=workspace / "profile")
            if done.returncode != 0:
                raise AssertionError(done.stderr[-2000:])

        self.every("golden", tune, label="1,500 records",
                   extra=[request("timeline", {"interruption_id": "%064x" % 1003}, ident=60),
                          request("statistics", {"days": 3650}, ident=61)])


class WriterDiff(QuietBase):
    def test_update_in_every_shape(self):
        updates = [{"notifications": False}, {"notifications": "no"}, {"max_recovery_attempts": 5},
                   {"max_recovery_attempts": 5.0}, {"max_recovery_attempts": True}, {"max_recovery_attempts": 21},
                   {"retry_preset": "patient"}, {"stall_after": "m60"}, {"quiet_hours_start": "22:00",
                                                                          "quiet_hours_end": "07:00"},
                   {"quiet_hours_days": "fri,mon"}, {"keep_awake_hours": "unlimited"},
                   {"continuation_style": "custom", "custom_message_mode": "global", "custom_message": "keep going"},
                   {"custom_message": "x" * 2001}, {"custom_message": "{prompt}"}, {"custom_message": "\ud800"},
                   {"custom_message_by_thread": {THREAD: "hello"}}, {"codex_exe": "C:\\x\\codex.exe"},
                   {"codex_exe": "x" * 40000}, {"codex_homes": [{"path": "C:\\nowhere", "alias": "a"}]},
                   {"codex_homes": [{"path": "relative", "alias": "a"}]}, {"codex_homes": "x"},
                   {"notice_kinds": ["recovery_failed"]}, {"notice_kinds_stay": ["x"]},
                   {"interface_language": "ko"}, {"theme": "dark"}, {"design": "soft"},
                   {"no_such": 1}, {}, {"notifications": None}, {"config_version": 5},
                   {"stay_on_screen": ["a", "b"]}, {"observe_only": True}, {"observe_only": False}]
        for index, changes in enumerate(updates):
            with self.subTest(index=index, changes=str(changes)[:60]):
                self.asked("golden", [request("update", changes, ident=1), request("settings", ident=2),
                                      request("status", ident=3), request("describe", ident=4)],
                           label="update %r" % (changes,))

    def test_check_setting_and_conversation_message(self):
        checks = [("stall_after", "m60"), ("stall_after", "h0"), ("stall_after", 5), ("quiet_hours_days", "fri,mon"),
                  ("keep_awake_hours", "unlimited"), ("retry_wait_2", "m5"), ("retry_wait_3", "h2"),
                  ("custom_message", "hello {reset_time}"), ("custom_message", "{prompt}"), ("custom_message", 5),
                  (5, "x"), (None, None), ("max_recovery_attempts", 7), ("max_recovery_attempts", "7"),
                  ("codex_homes", []), ("notifications", "yes"), ("no_such", 1), ("custom_message_mode", "x")]
        requests = [request("check-setting", {"name": name, "value": value}, ident=index)
                    for index, (name, value) in enumerate(checks, 1)]
        requests += [request("check-setting", {}, ident=40), request("check-setting", {"name": "stall_after"}, ident=41)]
        self.asked("golden", requests, label="check-setting")
        messages = [(THREAD, "Carry on."), (THREAD, None), (THREAD, "   "), (THREAD, "{prompt}"), (THREAD, 5),
                    (THREAD, "x" * 2001), ("latest", "go"), (THREAD.upper(), "go"), (5, "go"), (None, "go"),
                    ("0a1b2c3d-0001-7000-8000-%012d" % 1, "one"), (THREAD, "again")]
        requests = [request("conversation-message", {"thread_id": thread, "text": text}, ident=index)
                    for index, (thread, text) in enumerate(messages, 1)]
        requests += [request("conversation-message", {"thread_id": THREAD}, ident=40), request("settings", ident=41)]
        for number in range(2, 54):
            requests.append(request("conversation-message", {"thread_id": "0a1b2c3d-0001-7000-8000-%012d" % number,
                                                              "text": "m%d" % number}, ident=100 + number))
        self.asked("golden", requests, label="conversation-message")

    def test_preview_continuation(self):
        reasons = ["usage_limit", "server_5xx", "network_transient", "rate_limit_transient", "timeout", "stream_interrupted", "unclassified", "nonsense", None, 5]
        requests = []
        for index, category in enumerate(reasons):
            requests.append(request("preview-continuation", {"category": category}, ident=index + 1))
        for index, argument in enumerate((
                {"category": "usage_limit", "changes": {"continuation_style": "custom", "custom_message_mode": "global",
                                                        "custom_message": "Back at {reset_time}."}},
                {"category": "usage_limit", "changes": {"continuation_style": "custom", "custom_message_mode": "per_reason",
                                                        "custom_message_usage_limit": "limit {reset_time}"}},
                {"category": "usage_limit", "changes": {"custom_message": "{prompt}"}},
                {"category": "usage_limit", "changes": {"custom_message": None}},
                {"category": "usage_limit", "changes": {"custom_message": "   "}},
                {"category": "usage_limit", "changes": {"custom_message_by_thread": {THREAD: "hi", "x": "{prompt}"}},
                 "thread_id": THREAD},
                {"category": "usage_limit", "changes": {"custom_message_by_thread": None}, "thread_id": THREAD},
                {"category": "usage_limit", "changes": {"custom_message_by_thread": "hi"}},
                {"category": "usage_limit", "changes": []}, {"category": "usage_limit", "changes": {"a": 1, "b": 2}},
                {"category": "usage_limit", "thread_id": "latest"}, {"category": "usage_limit", "thread_id": 5},
                {"category": "usage_limit", "once_words": "Then run the tests."},
                {"category": "usage_limit", "once_words": "   "}, {"category": "usage_limit", "once_words": 5},
                {"category": "usage_limit", "once_words": "{prompt}", "changes": {"custom_message": "{prompt}"}},
                {"category": "network_transient", "once_words": "after {reset_time}"},
                {"category": "usage_limit", "changes": {"continuation_language": "ko", "continuation_style": "detailed"}},
                {"category": "usage_limit", "changes": {"continuation_language": "zz"}},
                {"category": "usage_limit", "changes": {"max_recovery_attempts": 3}},
                {"category": "server_5xx", "changes": {"max_recovery_attempts": "x"}},
                {"category": "usage_limit", "changes": {"continuation_style": "minimal"}},
                {"category": "usage_limit", "changes": {"continuation_style": "nope"}}), 20):
            requests.append(request("preview-continuation", argument, ident=index))
        for language in ("ko", "ja", "de", "ar", "zh-TW", "pt-BR", "ru"):
            requests.append(request("update", {"continuation_language": language}, ident=100))
            requests.append(request("preview-continuation", {"category": "usage_limit"}, ident=101))
            requests.append(request("preview-continuation", {"category": "server_5xx"}, ident=102))
        self.asked("golden", requests, label="preview-continuation")


class EdgesDiff(QuietBase):
    def test_statistics_days(self):
        days = [1, 3650, 3651, 0, -1, 1.5, 0.5, 7.0, True, False, "7", None, [7], {"a": 1}, 10 ** 400, float("nan"),
                1e400, -1e400, 3649.999, 2]
        requests = [request("statistics", {"days": value}, ident=index) for index, value in enumerate(days, 1)]
        requests.append(request("statistics", {}, ident=100))
        requests.append(request("statistics", None, ident=101))
        self.asked("golden", requests, label="statistics days")

    def test_timeline_ids(self):
        ids = [KEY, KEY.upper(), "  " + KEY + "\n", KEY[:-1], KEY + "0", "", None, 5, True, [KEY], {"a": KEY},
               "١" * 64, "%x" % 6 * 64, "%x" % 1 * 64, "g" * 64]
        requests = [request("timeline", {"interruption_id": value}, ident=index) for index, value in enumerate(ids, 1)]
        for number in range(1, 10):
            requests.append(request("timeline", {"interruption_id": "%x" % number * 64}, ident=100 + number))
        self.asked("golden", requests, label="timeline ids")

    def test_two_watchers_states_for_the_lists(self):
        for running in (True, False, None):
            self.asked("golden", [request("pending", ident=1), request("pending-all", ident=2),
                                  request("history", ident=3), request("dashboard", ident=4)],
                       world={"watcher_running": running}, label="lists, watcher %s" % running)

    def test_the_one_shot_form(self):
        read = ["settings"]
        shapes = [(["settings"], b""), (["update", "-"],
                  b'{"notifications": false}'), (["update", '{"notifications": true}'], b""),
                  (["update", "-"], b"not json"), (["update", "-"], b"[1]"), (["update", "-"], b"\xff"),
                  (["update", "-"], b""), (["update"], b""), (["statistics", "-"], b'{"days": 7}'),
                  (["timeline", "-"], ('{"interruption_id": "%s"}' % KEY).encode()),
                  (["timeline", "-"], b'{"interruption_id": "x"}'), (["check-setting", '{"name": "stall_after", '
                  '"value": "m60"}'], b""), (["logs"], b""), (["preview-continuation", "-"],
                  b'{"category": "usage_limit"}'), (["strings"], b""), (["describe"], b""),
                  (["failure-seen"], b""), (["status"], b""), (["dashboard"], b""), (["pending-all"], b""),
                  (["update", "-"], b"\xef\xbb\xbf{}")]
        for argv, stdin in shapes:
            with self.subTest(argv=argv, stdin=stdin[:30]):
                self.same("golden", stdin, mode="main", argv=argv, label="one-shot %r" % (argv,),
                          world={"now": golden_now(), "watcher_running": True})
        self.assertTrue(read)
