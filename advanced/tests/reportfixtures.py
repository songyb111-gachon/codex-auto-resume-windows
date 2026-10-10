"""Homes for the compatibility report's reader: a product home and a Codex home, made on disk the
way the product makes them, in one temporary folder.

`Home` writes the state (schema 3 or 4, by core's own schema code), the advanced edition's spend
ledger (version 1 or 2, by its own statements) or none, the log and its rotated copies, the
watcher's report as codex-compat-reporter reads it, and Codex's history. `SCENARIOS` are the homes
advanced/tests/golden/report/ was made from: advanced/tests/reportgolden.py asks
codex-compat-reporter 1.5.0's own `build` what it writes of each, and
advanced/tests/test_advanced_report_records.py holds the reader to that.

Every time is fixed (`NOW` and before), in UTC, away from any daylight-saving change, so the logs'
local times read back to the same moments in any time zone. The made-up person is ExampleUser.
Nothing here reaches the real machine: `isolated` points every home a reader could look for
into the folder.

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import calendar
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "tests", ROOT / "advanced" / "src", ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from codex_auto_resume import compat, config  # noqa: E402
from codex_auto_resume.codex.paths import DB_KINDS  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.runtime.app import ENGINE_LOG_WORDS  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume_advanced.state import schema as ledger_schema  # noqa: E402

LOGIN = "ExampleUser"
PRODUCT_VERSION = "0.6.14"
ENGINE = "codex-cli 0.158.0"
OLDER = "codex-cli 0.157.0"
NEWER = "codex-cli 0.159.0-alpha.2"


def at(month, day, hour=8, minute=0) -> float:
    return float(calendar.timegm((2026, month, day, hour, minute, 0)))


def sep(day, hour=8, minute=0) -> float:
    return at(9, day, hour, minute)


NOW = sep(30, 12)
PASSED = {name: ["PASS", "ok"] for name in ("consent", "engine_compatible", "identity", "thread_available", "usage")}


def key(number: int) -> str:
    """An interruption id, as the product makes one: 64 hex."""
    return hashlib.sha256(b"record %d" % number).hexdigest()


def uuid_of(number: int, kind: int = 1) -> str:
    return "0a1b2c3d-%04d-7000-8000-%012d" % (kind, number)


def gates(**changes) -> str:
    vector = dict(PASSED)
    vector.update(changes)
    return json.dumps(vector)


def record(number, **fields) -> dict:
    """One record of the state: a usage limit, recovered, unless `fields` say otherwise."""
    row = {"interruption_id": key(number), "thread_id": uuid_of(number, 1), "turn_id": uuid_of(number, 2),
           "category": "usage_limit", "state": "recovered", "last_error": "progress_observed",
           "detected_at": None, "resumed_at": None, "outcome_at": None, "submitted_at": None,
           "recovery_turn_id": uuid_of(number, 3), "recovery_turn_status": "completed", "gate_eval": gates(),
           "reset_at": None, "limit_type": "codex:primary", "history_hidden_at": None,
           "recovery_client_id": None, "last_claim_at": None}
    row.update(fields)
    return row


def recovered(number, day, hour=9, **fields) -> dict:
    """A record found, sent, delivered and seen to its outcome on September `day`."""
    found = sep(day, hour)
    made = dict(detected_at=found, submitted_at=found + 1800, resumed_at=found + 1800,
                outcome_at=found + 3600, reset_at=found + 900, last_claim_at=found + 1800)
    made.update(fields)
    return record(number, **made)


# ------------------------------------------------------------------------------ the records
EARLY = recovered(1, 9, 10)                                    # before the first engine line
ON_OLDER = recovered(2, 11)                                    # between two lines naming OLDER
OLDER_THEN_ENGINE = recovered(3, 13, 9, resumed_at=None, submitted_at=None, state="waiting_reset",
                              outcome_at=None)                 # the next line names ENGINE
ACROSS = recovered(4, 13, 22, outcome_at=sep(14, 10))          # ENGINE is named while it runs
RECOVERED = recovered(5, 15)
NO_PROGRESS = recovered(6, 17, state="completed_no_progress", last_error="no_progress_observed",
                        gate_eval=gates(usage=["UNKNOWN", "usage_unknown"]))
UNKNOWN_SUBMISSION = recovered(7, 19, resumed_at=None, outcome_at=None, state="submission_unknown",
                               last_error="queue_result_unknown_do_not_resend", recovery_turn_status=None)
WAITING = record(8, detected_at=sep(20, 9), state="waiting_reset", last_error="waiting_reset",
                 recovery_turn_id=None, recovery_turn_status=None, gate_eval=gates(schedule=["WAIT", "not_due"]))
STRANGE = recovered(9, 21, category="frobnicated", state="zzz_unknown", last_error="not_a_reason",
                    recovery_turn_status="weird", gate_eval="not json")
AFTER_LAST = recovered(10, 23)                                  # after the last engine line
HIDDEN = recovered(11, 15, 11, history_hidden_at=sep(25))
CLIENT_ID = recovered(12, 16, 10, recovery_client_id=str(ids.continuation_client_id(key(12))))
PLUGGED = recovered(13, 16, 12, gate_eval=gates(thread_available=["PASS", "plugged"]))
HELD_AT_CONSENT = record(14, detected_at=sep(17, 12), state="waiting_for_app", last_error="paused",
                         recovery_turn_id=None, recovery_turn_status=None, gate_eval=gates(consent=["WAIT", "held"]))
NO_TIME = record(15, detected_at=0)
PAID = recovered(16, 18, 10)                                    # a unit was paid at its claim
UNPAID = recovered(17, 18, 11)                                  # a unit was paid, at another time
LONG_AGO = record(18, detected_at=at(6, 20), last_claim_at=at(6, 20), state="waiting_reset",
                  recovery_turn_id=None, recovery_turn_status=None)
INSIDE_REACH = record(19, detected_at=at(7, 10), last_claim_at=at(7, 10), state="waiting_reset",
                      recovery_turn_id=None, recovery_turn_status=None)

BASE = [EARLY, ON_OLDER, OLDER_THEN_ENGINE, ACROSS, RECOVERED, NO_PROGRESS, WAITING, STRANGE, AFTER_LAST,
        HIDDEN, CLIENT_ID, PLUGGED, HELD_AT_CONSENT, NO_TIME]


# ------------------------------------------------------------------------------ the logs
def stamp(when) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))


def engine_line(when, version, word) -> str:
    """A log line exactly as the product's runtime/app.py writes it."""
    return ("[%s] engine %s %s. Delivery is still proven per interruption before anything is marked "
            "resumed." % (stamp(when), version, ENGINE_LOG_WORDS[word]))


def line(when, text) -> str:
    return "[%s] %s" % (stamp(when), text)


def logs(last=ENGINE) -> dict:
    """The log and three of its rotated copies: OLDER, then ENGINE, the last line naming `last`."""
    return {
        "auto-resume.log.3": [line(sep(9, 6), "watcher started"),
                              "[2026-13-40 99:99:99] engine codex-cli 0.150.0 is verified: a line no clock can read",
                              "not a log line at all"],
        "auto-resume.log.2": [line(sep(10), "engine %s accepted because `codex queue` still offers "
                                            "--thread/--message." % OLDER),
                              engine_line(sep(12), OLDER, "structurally_compatible")],
        "auto-resume.log.1": [engine_line(sep(14), ENGINE, "structurally_compatible"),
                              engine_line(sep(16), ENGINE, "incompatible")],
        "auto-resume.log": [engine_line(sep(18), ENGINE, "verified"), line(sep(19), "tick ok"),
                            engine_line(sep(22), last, "checked")],
    }


def watcher(version=ENGINE) -> dict:
    """The watcher's compatibility report, as codex-compat-reporter reads it: the raw file."""
    return {"engine": {"found": True, "version": version},
            "capabilities": {"usage_probe": {"state": "compatible", "reason": "local_checks_passed"},
                             "loaded_state_detection": {"state": "verified", "reason": "registry_verified"},
                             "queue_withdraw": {"state": "compatible", "reason": "local_checks_passed"},
                             "usage_reset_hint": {"state": "incompatible", "reason": "local_check_failed"}}}


# ------------------------------------------------------------------------------ a home
class _SchemaThree(Store):
    """Core's own schema, stopped where v0.6.10 stopped: schema 3."""

    @staticmethod
    def _add_schema_4(connection) -> None:
        return None


class Home:
    """A product home (`paths`) and a Codex home (`codex`), on disk, in one temporary folder."""

    def __init__(self, rows=(), *, state=4, ledger=None, spends=(), pruned=(), watcher_report=None,
                 log_files=None, enabled=True, history=True, columns=None):
        self.temporary = tempfile.TemporaryDirectory(prefix="report-records-")
        self.root = Path(self.temporary.name)
        self.paths = config.Paths(self.root / "product")
        self.codex = self.root / "codex-home"
        self.paths.state_dir.mkdir(parents=True)
        self.paths.logs_dir.mkdir()
        self.codex.mkdir()
        manifest = self.paths.home / "app" / ".codex-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "codex-auto-resume", "version": PRODUCT_VERSION}), encoding="utf-8")
        if state is not None:
            self.write_state(rows, state, enabled=enabled, columns=columns)
        if ledger is not None:
            self.write_ledger(ledger, spends, pruned)
        for name, lines in (logs() if log_files is None else log_files).items():
            (self.paths.logs_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        if watcher_report is not None:
            self.paths.compat_report_file.write_text(json.dumps(watcher_report), encoding="utf-8")
        if history:
            self.write_history()

    def close(self):
        self.temporary.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # -------------------------------------------------------------------- the files
    def write_state(self, rows, version, *, enabled=True, columns=None):
        path = self.paths.state_dir / "state.sqlite"
        db = sqlite3.connect(path)
        try:
            if version in (3, 4):
                (Store if version == 4 else _SchemaThree)._create_schema(db)
            else:
                Store._create_schema(db)
            db.execute("UPDATE settings SET enabled = ?", (int(enabled),))
            info = list(db.execute("PRAGMA table_info(interruptions)"))
            for row in rows:
                values = dict(row)
                for _cid, name, kind, notnull, default, _pk in info:
                    if name not in values and notnull and default is None:
                        values[name] = "x" if kind.upper() == "TEXT" else 0
                names = [name for _cid, name, *_rest in info if name in values]
                db.execute("INSERT INTO interruptions (%s) VALUES (%s)" % (", ".join(names), ", ".join("?" * len(names))),
                           [values[name] for name in names])
            for name in columns or ():
                db.execute("ALTER TABLE interruptions DROP COLUMN %s" % name)
            db.execute("PRAGMA user_version = %d" % version)
            db.commit()
        finally:
            db.close()

    def write_ledger(self, version, spends=(), pruned=()):
        """The spend ledger, made by the edition's own statements (version 1: without the column
        version 2 added), holding `spends` - (interruption id, time) - after the `pruned` ones,
        which it was given first and has pruned since, as the product prunes its oldest."""
        folder = self.paths.advanced_dir
        folder.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(folder / ledger_schema.FILE_NAME)
        try:
            for statement in ledger_schema.STATEMENTS:
                if version == 1:
                    statement = statement.replace(",\n        %s\n" % ledger_schema.WARNINGS_COLUMN, "\n")
                db.execute(statement)
            for interruption, when in (*pruned, *spends):
                db.execute("INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (?, ?, ?, ?)",
                           (when, "goal_continuation", uuid_of(1), interruption))
            if pruned:
                db.execute("DELETE FROM spend WHERE spend_id IN (SELECT spend_id FROM spend ORDER BY spend_id LIMIT ?)",
                           (len(pruned),))
            db.execute("PRAGMA user_version = %d" % version)
            db.commit()
        finally:
            db.close()

    def write_history(self):
        """Codex's history, in two generations: the newest (10) is the one read, the older (9)
        holds counts that would differ. The items' own text is a person's, and must never travel."""
        for generation, many in ((9, 7), (10, 2)):
            db = sqlite3.connect(self.codex / ("thread_history_%d.sqlite" % generation))
            try:
                for table, columns in DB_KINDS["history"][1].items():
                    db.execute("CREATE TABLE %s (%s)" % (table, ", ".join(sorted(columns | {"text"}))))
                items = [(RECOVERED, "agentMessage", "a private sentence")] * many + [
                    (RECOVERED, "fileChange", "C:\\Users\\ExampleUser\\secret.txt"),
                    (RECOVERED, "reasoning", "thinking"),
                    (ON_OLDER, "commandExecution", "dir"),
                    (UNKNOWN_SUBMISSION, "agentMessage", "x")]
                for number, (row, kind, text) in enumerate(items):
                    db.execute("INSERT INTO thread_items (thread_id, turn_id, item_id, item_type, item_json, text) "
                               "VALUES (?, ?, ?, ?, ?, ?)",
                               (row["thread_id"], row["recovery_turn_id"], "item-%d" % number, kind, "{}", text))
                db.commit()
            finally:
                db.close()

    # -------------------------------------------------------------------- reading it
    def raw_view(self):
        """The watcher's report as codex-compat-reporter reads it - the raw file, in force while it
        is there - in the shape of the view a reader takes: the seam that lets the two agree."""
        try:
            raw = json.loads(self.paths.compat_report_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return compat.unusable_view("absent")
        return {"status": "ok", "engine": raw.get("engine") or {}, "capabilities": raw.get("capabilities") or {}}

    def snapshot(self) -> dict:
        """Every file and folder under both homes: its size, its modification time and its bytes'
        SHA-256, so that reading can be shown to have changed, made or left nothing."""
        found = {}
        for path in sorted(self.root.rglob("*")):
            name = path.relative_to(self.root).as_posix()
            if path.is_dir():
                found[name] = "folder"
            else:
                status = path.stat()
                found[name] = (status.st_size, status.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        return found


@contextlib.contextmanager
def isolated(home: Home):
    """Every home a reader could look for, pointed into the fixture's folder; none of it made."""
    values = {"CODEX_HOME": str(home.codex), "USERPROFILE": str(home.root / "profile"),
              "LOCALAPPDATA": str(home.root / "local"), "APPDATA": str(home.root / "roaming")}
    with mock.patch.dict(os.environ, values):
        for name in (config.ENV_HOME, config.ENV_CODEX_EXE):
            os.environ.pop(name, None)
        yield


# ------------------------------------------------------------------------------ the scenarios
# name -> (what Home is given, the Codex version asked or None). Each is one golden file.
SCENARIOS = {
    # Everything at once, with a version 2 ledger that has lost nothing: the verdict is PASS.
    "state4_ledger2": (dict(rows=BASE + [PAID, UNPAID], state=4, ledger=2, watcher_report=watcher(),
                            spends=[(key(16), PAID["last_claim_at"]), (key(17), UNPAID["last_claim_at"] + 1800)]),
                       None),
    # Schema 3 and no ledger, no watcher's report (the version is the log's), and a send whose
    # delivery is unknown: exact_thread_recovery is missed, so nothing is verified.
    "state3_no_ledger": (dict(rows=BASE + [UNKNOWN_SUBMISSION], state=3), None),
    # A version 1 ledger that has pruned units: a claim before its reach is left out.
    "state4_ledger1_pruned": (dict(rows=BASE + [LONG_AGO, INSIDE_REACH, UNPAID], state=4, ledger=1,
                                   watcher_report=watcher(),
                                   pruned=[(key(90), sep(1)), (key(91), sep(2)), (key(92), sep(3))],
                                   spends=[(key(93), sep(12)), (key(17), UNPAID["last_claim_at"] + 1800)]),
                              None),
    # The older version, asked for by name: the watcher's report is about another, so it counts nothing.
    "state3_ledger2_asked_older": (dict(rows=BASE, state=3, ledger=2, watcher_report=watcher()), OLDER),
    # The watcher names a newer Codex than the log's last line: nothing is on it yet.
    "state4_watcher_newer": (dict(rows=BASE, state=4, watcher_report=watcher(NEWER)), None),
    # No records at all.
    "state4_empty": (dict(rows=(), state=4, watcher_report=watcher()), None),
}


def scenario(name) -> tuple:
    """(Home, the version asked) for one of SCENARIOS; the caller closes the home."""
    given, asked = SCENARIOS[name]
    return Home(**given), asked
