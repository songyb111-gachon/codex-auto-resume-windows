"""v0.6.19: this PC's own compatibility report (ownreport/), as the Dashboard and the diagnostics export get it.

Held here, in the standard edition and with nothing of the advanced one on the path: the report lists every Codex
version the product's own log names, newest first, each with the body codex-compat-reporter writes and the project's
count of it (worked, failed, neither, both); its SHA-256 is of the very text shown; nothing is written beside the
records it reads, Codex's history is never opened, and a home that held the advanced edition's state counts no
claimed record it cannot tell apart; the bridge answers `own-report` and the export carries the report whole.

The homes are made on disk in a temporary folder, by core's own schema code, with log lines exactly as the watcher
writes them; the watcher's report is handed in through the reader's `view` seam, so this machine's Codex is never
asked. The made-up person is ExampleUser.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from codex_auto_resume import compat, config, controlcli, diagnostics, ownreport  # noqa: E402
from codex_auto_resume.ownreport import document, evidence, reading  # noqa: E402
from codex_auto_resume.runtime.app import ENGINE_LOG_WORDS  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402

ENGINE = "codex-cli 0.163.0"
OLDER = "codex-cli 0.162.0"
PASSED = json.dumps({name: ["PASS", "ok"] for name in ("consent", "engine_compatible", "identity",
                                                       "thread_available", "usage")})


def sep(day, hour=8, minute=0) -> float:
    return float(calendar.timegm((2026, 9, day, hour, minute, 0)))


def key(number):
    return hashlib.sha256(b"own %d" % number).hexdigest()


def uuid_of(number, kind=1):
    return "0a1b2c3d-%04d-7000-8000-%012d" % (kind, number)


def record(number, day, **fields):
    """A usage limit found on September `day`, sent, delivered and seen recovered, unless `fields` say otherwise."""
    found = sep(day, 9)
    row = {"interruption_id": key(number), "thread_id": uuid_of(number), "turn_id": uuid_of(number, 2),
           "category": "usage_limit", "state": "recovered", "last_error": "progress_observed",
           "detected_at": found, "submitted_at": found + 1800, "resumed_at": found + 1800, "outcome_at": found + 3600,
           "recovery_turn_id": uuid_of(number, 3), "recovery_turn_status": "completed", "gate_eval": PASSED,
           "reset_at": found + 900, "limit_type": "codex:primary", "history_hidden_at": None,
           "recovery_client_id": None, "last_claim_at": found + 1800}
    row.update(fields)
    return row


def engine_line(when, version, word="verified"):
    """A log line exactly as runtime/app.py writes it."""
    return ("[%s] engine %s %s. Delivery is still proven per interruption before anything is marked resumed."
            % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when)), version, ENGINE_LOG_WORDS[word]))


# OLDER from the 10th, ENGINE from the 20th; the last line names ENGINE, the version in use now.
LOG = [engine_line(sep(10), OLDER), engine_line(sep(15), OLDER), engine_line(sep(20), ENGINE),
       engine_line(sep(28), ENGINE)]
ROWS = [record(1, 11),                                                  # OLDER: worked
        record(2, 12, state="recovery_turn_failed", last_error="recovery_turn_failed"),   # OLDER: failed too
        record(3, 21),                                                  # ENGINE: worked
        record(4, 22, state="waiting_reset", resumed_at=None, outcome_at=None, submitted_at=None,
               last_claim_at=None),                                     # ENGINE: not delivered
        record(5, 23, history_hidden_at=sep(25))]                       # hidden with Clear history


def view(version=ENGINE):
    return lambda: {"status": "ok", "engine": {"found": True, "version": version},
                    "capabilities": {"usage_probe": {"state": "compatible", "reason": "local_checks_passed"}}}


class Home:
    def __init__(self, rows=ROWS, log=LOG, *, state=True, advanced=False):
        self.temporary = tempfile.TemporaryDirectory(prefix="own-report-")
        self.root = Path(self.temporary.name)
        self.paths = config.Paths(self.root / "product")
        self.paths.state_dir.mkdir(parents=True)
        self.paths.logs_dir.mkdir()
        if state:
            db = sqlite3.connect(self.paths.state_dir / "state.sqlite")
            try:
                Store._create_schema(db)
                info = list(db.execute("PRAGMA table_info(interruptions)"))
                for row in rows:
                    values = dict(row)
                    for _cid, name, kind, notnull, default, _pk in info:
                        if name not in values and notnull and default is None:
                            values[name] = "x" if kind.upper() == "TEXT" else 0
                    names = [name for _cid, name, *_rest in info if name in values]
                    db.execute("INSERT INTO interruptions (%s) VALUES (%s)"
                               % (", ".join(names), ", ".join("?" * len(names))), [values[name] for name in names])
                db.commit()
            finally:
                db.close()
        if log is not None:
            (self.paths.logs_dir / "auto-resume.log").write_text("\n".join(log) + "\n", encoding="utf-8")
        if advanced:
            # The advanced edition's folder as that edition leaves it: its marker, and a file core does not name.
            self.paths.advanced_dir.mkdir()
            (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
            (self.paths.advanced_dir / "something.sqlite").write_bytes(b"")

    def close(self):
        self.temporary.cleanup()

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
                if path.is_file() else "folder" for path in sorted(self.root.rglob("*"))}


class Case(unittest.TestCase):
    def home(self, *args, **kwargs):
        home = Home(*args, **kwargs)
        self.addCleanup(home.close)
        return home

    def written(self, home, version=ENGINE):
        return ownreport.write(home.paths, now=sep(30, 12), view=view(version))


class ReportTests(Case):
    def test_every_version_the_log_names_is_listed_newest_first_and_counted_by_the_projects_rule(self):
        found = self.written(self.home())
        self.assertEqual([entry["codex_version"] for entry in found["versions"]], [ENGINE, OLDER])
        on_engine, on_older = found["versions"]
        self.assertEqual((on_engine["records"], on_engine["delivered"]), (2, 1))
        self.assertEqual((on_engine["worked"], on_engine["failed"], on_engine["neither"], on_engine["both"]),
                         (True, False, False, False))
        self.assertEqual((on_older["records"], on_older["delivered"]), (2, 2))
        self.assertEqual((on_older["worked"], on_older["failed"], on_older["neither"], on_older["both"]),
                         (True, True, False, True))
        self.assertEqual(found["left_out"]["hidden"], 1)
        self.assertEqual(found["engine"], {"current": ENGINE, "from": "watcher_report"})

    def test_the_sha256_is_of_the_text_shown_and_the_text_passes_its_own_check(self):
        found = self.written(self.home())
        raw = found["text"].encode("ascii")
        self.assertEqual(found["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(found["bytes"], len(raw))
        made = json.loads(found["text"])
        self.assertEqual(document.check(made), raw)
        self.assertEqual(made["format"], document.FORMAT)
        self.assertEqual(made["rule"], document.RULE)

    def test_each_body_is_the_reporters_body_with_no_progress_counts(self):
        home = self.home()
        made = json.loads(self.written(home)["text"])
        for entry in made["versions"]:
            with self.subTest(entry["codex_version"]):
                self.assertEqual(tuple(entry["body"]), document.BODY_KEYS)
                self.assertEqual(entry["counted"], evidence.graded(entry["body"]["records"]))
                self.assertTrue(all(row["progress_items"] is None for row in entry["body"]["records"]))
        # The version in use now carries what the watcher's own report checked; an older one does not.
        self.assertIn("usage_probe", made["versions"][0]["body"]["local_checks"]["covers"])

    def test_it_names_nobody_and_nothing_of_this_pc(self):
        text = self.written(self.home())["text"]
        for row in ROWS:
            for name in ("interruption_id", "thread_id", "turn_id", "recovery_turn_id"):
                self.assertNotIn(row[name], text)
        for word in ("ExampleUser", "github_login", "Users", "\\\\", "C:"):
            self.assertNotIn(word, text)

    def test_reading_writes_nothing_beside_the_records(self):
        home = self.home()
        before = home.snapshot()
        self.written(home)
        self.assertEqual(home.snapshot(), before)

    def test_a_home_that_held_the_advanced_editions_state_counts_no_claimed_record_it_cannot_tell_apart(self):
        found = self.written(self.home(advanced=True))
        # Every record but the one never claimed is left out: the ledger that would tell them apart is not read here.
        self.assertEqual(found["left_out"]["beyond_reach"], 3)
        self.assertEqual([entry["records"] for entry in found["versions"]], [1, 0])
        self.assertEqual(self.written(self.home())["left_out"]["beyond_reach"], 0)

    def test_another_route_is_told_by_the_states_own_marks(self):
        from codex_auto_resume.domain import ids
        rows = ROWS + [record(6, 24, recovery_client_id=str(ids.continuation_client_id(key(6))))]
        self.assertEqual(self.written(self.home(rows))["left_out"]["another_route"], 1)

    def test_a_version_with_more_records_than_a_report_holds_is_said_and_not_written(self):
        with mock.patch.object(evidence, "MAX_RECORDS", 1):
            found = self.written(self.home())
        self.assertEqual([entry["refusal"] for entry in found["versions"]], ["too_many_records"] * 2)
        made = json.loads(found["text"])
        self.assertTrue(all(entry["body"] is None and entry["counted"] is None for entry in made["versions"]))


class RefusalTests(Case):
    def test_no_records_and_no_engine_are_refusals_by_code(self):
        self.assertEqual(self.written(self.home(state=False)), {"refusal": "no_state"})
        home = self.home(log=None)
        self.assertEqual(ownreport.write(home.paths, view=lambda: compat.unusable_view("absent")),
                         {"refusal": "no_engine_version"})

    def test_with_no_watcher_report_the_log_names_the_version(self):
        home = self.home()
        found = ownreport.write(home.paths, now=sep(30, 12), view=lambda: compat.unusable_view("absent"))
        self.assertEqual(found["engine"], {"current": ENGINE, "from": "log"})


class SelfCheckTests(Case):
    def test_anything_but_the_format_is_a_fault(self):
        made = json.loads(self.written(self.home())["text"])
        broken = [("an extra key", lambda d: d.update(extra=1)),
                  ("a sentence changed", lambda d: d.update(note="hello")),
                  ("a count changed", lambda d: d["versions"][0]["counted"].update(worked=False)),
                  ("a word not the product's", lambda d: d["versions"][0]["body"]["records"][0].update(state="x y")),
                  ("a version twice", lambda d: d["versions"].append(d["versions"][0]))]
        for name, change in broken:
            with self.subTest(name):
                copy = json.loads(json.dumps(made))
                change(copy)
                with self.assertRaises(document.DocumentError):
                    document.check(copy)


class SourceTests(unittest.TestCase):
    def test_the_progress_kinds_are_codexs_own(self):
        from codex_auto_resume.codex.values import PROGRESS_ITEM_TYPES
        self.assertEqual(evidence.PROGRESS, tuple(sorted(PROGRESS_ITEM_TYPES)))

    def test_codexs_own_files_are_never_opened(self):
        """B17: the Dashboard's bridge never imports Codex's readers; the report reads only this product's files."""
        import srcscan
        paths = srcscan.files_of("codex_auto_resume.ownreport")
        self.assertEqual(len(paths), 4)
        for path in paths:
            source = srcscan.read(path)
            with self.subTest(srcscan.relative(path)):
                for word in ("LocalSource", "codex.history", "codex.schema", "thread_items", "newest_generation",
                             "codex_home", "_db("):
                    self.assertNotIn(word, source)
                self.assertNotIn("codex_auto_resume_advanced", source)


class SurfaceTests(Case):
    def test_the_bridge_answers_own_report(self):
        self.assertIn("own-report", controlcli.PLAIN)
        home = self.home()
        control = mock.Mock()
        control.paths = home.paths
        with mock.patch.object(reading, "watcher_view", lambda paths: view()()):
            reply = controlcli.dispatch(control, "own-report", {})
        self.assertTrue(reply["ok"])
        self.assertEqual([entry["codex_version"] for entry in reply["result"]["versions"]], [ENGINE, OLDER])

    def test_the_diagnostics_export_carries_the_report_whole(self):
        home = self.home()
        report = ownreport.for_bundle(home.paths)
        with mock.patch.object(reading, "watcher_view", lambda paths: view()()):
            carried = report()
        made = carried["report"]
        self.assertEqual(carried["sha256"], hashlib.sha256(document.encode(made)).hexdigest())
        self.assertEqual(carried["bytes"], len(document.encode(made)))
        control = mock.MagicMock()
        control.paths = home.paths
        control.get_settings.return_value = {}
        control.plug.surface.return_value = diagnostics.DEFER
        bundle = diagnostics.collect(control, now=sep(30), report=lambda: carried)
        self.assertEqual(bundle["compatibility_report"], carried)
        self.assertNotIn("compatibility_report", diagnostics.collect(control, now=sep(30)))
        failing = diagnostics.collect(control, now=sep(30), report=lambda: 1 / 0)
        self.assertEqual(failing["compatibility_report"], {"error": "ZeroDivisionError"})

    def test_both_export_routes_ask_for_it(self):
        for name in ("controlcli.py", "commands/install.py"):
            source = (ROOT / "src" / "codex_auto_resume" / name).read_text(encoding="utf-8")
            with self.subTest(name):
                self.assertIn("report=ownreport.for_bundle(", source)


if __name__ == "__main__":
    unittest.main()
