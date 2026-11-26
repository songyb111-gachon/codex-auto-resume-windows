"""The compatibility report's reader and document against the tag, case by case (seat S7.3c, car-adv `report/`).

Every case is one question put to the tag's own advanced edition (`report/records.py`, `report/document.py` and the core
`ownreport/*` they read through) and to car-adv's `advreport` example, over homes the tag's own fixtures make (a product
home and a Codex home in a scratch folder, `advanced/tests/reportfixtures.py`), hand-edited where a fixture cannot say
what a damaged one would. Both answer as JSON and every answer must be the same, the refusal's class and its code
included:

* ReadDiff - `records.read` over the six scenarios of the goldens, each asked for every version it could be (the
  version in use, the older, a spelling of either, a version no log names, an invalid one) and under each watcher's
  report a reader may be handed (valid, stale, none, one for another version); and over homes that refuse in each way
  the reader knows (no state, a state newer or older or damaged or with a column gone or locked, a ledger newer, damaged,
  marked readable from this version or not, a junction in place of a folder, no engine anywhere, more records than a
  report holds), that pause, that have no history or a history whose schema moved.
* DamagedDiff - rows hand-edited to what a person or a bug could leave: wrong types in every column, blobs, huge and
  negative times, gate evaluations that are not what the product writes, logs that are huge, not UTF-8, cut by every
  line break Python knows, with engine lines in odd spellings.
* LedgerDiff - the spend ledger read in every shape (versions 1 and 2, units pruned, a count kept or not, ids of the
  wrong type, a full ledger), and `ledger_reach`, `by_route` over generated records with paid times.
* EvidenceDiff - `place`, `body` and `current_engine` over generated records, logs and watchers' reports.
* DocumentDiff - `check_login`, `assemble` and `check` over the six bodies, each document broken in every way the tag's
  own tests break one (and a few more), at its limits (500 and 501 records, one byte under and over a megabyte).
"""
from __future__ import annotations

import unittest

from rustdiff import advreport

RECORD = []

PRELUDE = r'''
import calendar, copy, json, os, random, sqlite3, sys, time
import reportfixtures as fixtures
from codex_auto_resume import compat, config
from codex_auto_resume.domain import ids
from codex_auto_resume.ownreport import evidence, reading
from codex_auto_resume_advanced.report import document, records
from codex_auto_resume_advanced.state import journal, schema as ledger_schema

NOW = fixtures.NOW
HOMES = []

def make(rows=(), **given):
    home = fixtures.Home(rows, **given)
    HOMES.append(home)
    return home

def read_case(home, asked=None, view="raw", now=NOW):
    seen = home.raw_view() if view == "raw" else view
    def ref():
        with fixtures.isolated(home):
            return records.read(home.paths, home.codex, asked, now=now, view=lambda: seen)
    case("records.read", str(home.paths.home), str(home.codex), asked, now, seen, ref=ref)

def rows_of(found):
    return [{name: (list(value) if isinstance(value, bytes) else value) for name, value in row.items()} for row in found]

def sql(home, statement, *arguments, ledger=False):
    path = (home.paths.advanced_dir / ledger_schema.FILE_NAME) if ledger else (home.paths.state_dir / "state.sqlite")
    db = sqlite3.connect(path)
    try:
        db.execute(statement, arguments)
        db.commit()
    finally:
        db.close()

def state_cases(home):
    with fixtures.isolated(home):
        case("reading.state", str(home.paths.home), ref=lambda: (lambda found: [found[0], rows_of(found[1]), found[2], found[3]])(reading.state(home.paths)))
        case("reading.paused", str(home.paths.home), ref=lambda: reading.paused(home.paths))
        case("reading.log_lines", str(home.paths.home), ref=lambda: [list(line) for line in reading.log_lines(home.paths)])
        case("records.ledger", str(home.paths.home), NOW, ref=lambda: (lambda found: {"schema": found[0], "paid": {key: sorted(times) for key, times in sorted(found[1].items())}, "reach": found[2]})(records.ledger(home.paths, NOW)))
'''


READ_SCRIPT = PRELUDE + r'''
ENGINE, OLDER, NEWER = fixtures.ENGINE, fixtures.OLDER, fixtures.NEWER
ASKS = [None, ENGINE, OLDER, "0.158.0", "0.157.0", NEWER, "codex-cli 0.150.0", "0.01.0", "00.158.0", "codex-cli 1.2",
        "banana", "", "0.158.0 ", 158, True, ["0.158.0"], "0.158.0-alpha.2", "0.1.0-alpha.2.0"]
stale = compat.unusable_view("stale", engine={"found": True, "version": NEWER})
absent = compat.unusable_view("absent")
VIEWS = ["raw", None, stale, absent, {"status": "ok", "engine": {"version": "0.157.0"}, "capabilities": {}},
         {"status": "ok", "engine": {"version": "  "}, "capabilities": {}},
         {"status": "ok", "engine": {"version": "codex-cli 0.158.0"}, "capabilities": {"usage_probe": {"reason": "registry_checked"}, "loaded_state_detection": 7, "queue_withdraw": {"reason": "local_checks_passed"}}},
         {"status": "ok", "engine": {"version": 7}}, {"status": "ok", "engine": "x"}, {"status": "ok"}, {"status": "ok", "engine": {"version": "codex-cli 0.158.0"}, "capabilities": [1]}, [1], "ok"]

# the six homes, asked every way
for name in sorted(fixtures.SCENARIOS):
    home, asked = fixtures.scenario(name)
    HOMES.append(home)
    for one in ASKS:
        read_case(home, one)
    for seen in VIEWS:
        read_case(home, asked, seen)
    read_case(home, asked, now=NOW + 86400 * 400)
    read_case(home, asked, now=1.0)
    read_case(home, asked, now=fixtures.at(6, 1))

# refusals, one by one
plain = fixtures.BASE
refusing = [
    make(plain, state=None),
    make(plain, state=6),
    make(plain, state=2),
    make(plain, state=0),
    make(plain, columns=["gate_eval"]),
    make(plain, columns=["reset_at"]),
    make(plain, columns=["limit_type", "history_hidden_at"]),
    make(plain, ledger=ledger_schema.SCHEMA_VERSION + 1),
    make(plain, ledger=ledger_schema.SCHEMA_VERSION + 1, ledger_readable=ledger_schema.SCHEMA_VERSION),
    make(plain, ledger=ledger_schema.SCHEMA_VERSION + 1, ledger_readable=ledger_schema.READABLE_FROM),
    make(plain, ledger=ledger_schema.SCHEMA_VERSION + 1, ledger_readable=ledger_schema.SCHEMA_VERSION + 1),
    make(plain, ledger=ledger_schema.SCHEMA_VERSION + 3, ledger_readable=ledger_schema.SCHEMA_VERSION + 2),
    make(plain, ledger=0),
    make(plain, ledger=1), make(plain, ledger=2),
    make(plain, log_files={"auto-resume.log": [fixtures.line(fixtures.sep(9), "tick ok")]}),
    make(plain, log_files={}),
    make(plain, enabled=False), make(plain, history=False),
    make((), ledger=ledger_schema.SCHEMA_VERSION + 1, watcher_report=fixtures.watcher()),
    make((), ledger=0, watcher_report=fixtures.watcher()),
    make((), watcher_report=fixtures.watcher()),
]
damaged = make(state=None)
(damaged.paths.state_dir / "state.sqlite").write_bytes(b"not a database, whatever its name says")
refusing.append(damaged)
empty_file = make(state=None)
(empty_file.paths.state_dir / "state.sqlite").write_bytes(b"")
refusing.append(empty_file)
bare = make(plain)
bare.paths.advanced_dir.mkdir()
db = sqlite3.connect(bare.paths.advanced_dir / ledger_schema.FILE_NAME)
db.execute("CREATE TABLE spend (spend_id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL)")
db.execute("PRAGMA user_version = 2")
db.commit(); db.close()
refusing.append(bare)
junk_ledger = make(plain, ledger=2)
(junk_ledger.paths.advanced_dir / ledger_schema.FILE_NAME).write_bytes(b"not a database")
refusing.append(junk_ledger)
many = [fixtures.recovered(100 + number, 23, 9, detected_at=fixtures.sep(23, 9) + number) for number in range(evidence.MAX_RECORDS + 1)]
refusing.append(make(many, watcher_report=fixtures.watcher()))
refusing.append(make(many[:-1], watcher_report=fixtures.watcher()))
for home in refusing:
    read_case(home)
    read_case(home, OLDER)
    read_case(home, "0.158.0")
    state_cases(home)

# a junction in place of a folder (Windows): never followed
if sys.platform == "win32":
    import _winapi
    linked = make(plain, ledger=2)
    elsewhere = linked.root / "elsewhere"
    linked.paths.advanced_dir.rename(elsewhere)
    _winapi.CreateJunction(str(elsewhere), str(linked.paths.advanced_dir))
    read_case(linked)
    state_cases(linked)
    moved_state = make(plain)
    moved = moved_state.root / "moved"
    moved_state.paths.state_dir.rename(moved)
    _winapi.CreateJunction(str(moved), str(moved_state.paths.state_dir))
    read_case(moved_state)
    state_cases(moved_state)
    logged = make(plain, watcher_report=fixtures.watcher())
    held = logged.root / "logs-held"
    logged.paths.logs_dir.rename(held)
    _winapi.CreateJunction(str(held), str(logged.paths.logs_dir))
    read_case(logged)
    state_cases(logged)

# history: a newer generation whose schema moved, none, the codex home gone, a file in its place
moved = make(plain, watcher_report=fixtures.watcher())
db = sqlite3.connect(moved.codex / "thread_history_11.sqlite")
db.execute("CREATE TABLE thread_items (thread_id, turn_id, item_type)")
db.commit(); db.close()
read_case(moved)
gone = make(plain, watcher_report=fixtures.watcher(), history=False)
import shutil
shutil.rmtree(gone.codex)
read_case(gone)
filed = make(plain, watcher_report=fixtures.watcher(), history=False)
shutil.rmtree(filed.codex)
filed.codex.write_text("a file, not a folder")
read_case(filed)
case("records.progress", str(gone.codex), rows_of(plain), ref=lambda: (lambda found: [str(found[0]), found[1]])(records.progress(gone.codex, plain)))
good = make(plain, watcher_report=fixtures.watcher())
case("records.progress", str(good.codex), rows_of(fixtures.BASE), ref=lambda: (lambda found: [str(found[0]), found[1]])(records.progress(good.codex, fixtures.BASE)))
odd_rows = [fixtures.record(3, thread_id="x", recovery_turn_id=fixtures.uuid_of(3, 3)), fixtures.record(4, recovery_turn_id=None), fixtures.record(5, thread_id=7)]
case("records.progress", str(good.codex), odd_rows, ref=lambda: (lambda found: [str(found[0]), found[1]])(records.progress(good.codex, odd_rows)))
finish()
'''


DAMAGED_SCRIPT = PRELUDE + r'''
rng = random.Random(20261126)
ENGINE = fixtures.ENGINE
WEIRD_TEXT = ["", " ", "x", "C:\\Users\\ExampleUser\\secret.txt", "someone@example.com", "waiting_reset", "recovered",
              "usage_limit", "completed", "progress_observed", "\u00e9\u0301", "\U0001F600", "0", "1e3", "nan"]
WEIRD_NUM = [0, 1, -1, 0.0, -0.0, 1e-9, 1.5, 3.14, 1e300, 10 ** 12, 2 ** 62, fixtures.NOW, fixtures.NOW + 1, 32536850400.5,
             32536850399.0, 2 ** 40]
GATES = ['{"engine_compatible": ["PASS", "ok"], "usage": ["WAIT", "x"]}', "{}", "[]", "null", "7", '"text"', "not json",
         '{"a": 1}', '{"a": ["PASS"]}', '{"thread_available": ["PASS", "plugged"], "consent": ["WAIT", "held"]}',
         '{"identity": ["PASS", "held"]}', '{"usage": ["PASS", 7]}', '{"usage": [["PASS"], "held"]}', "",
         json.dumps({"g%d" % n: ["PASS", "ok"] for n in range(70)}), "[" * 40 + "]" * 40, '{"a": NaN}', '{"x": Infinity}']

def rnd(options):
    return rng.choice(options)

def rnd_time(base=True):
    pick = rng.random()
    if pick < 0.4:
        return fixtures.sep(rng.randint(9, 28), rng.randint(0, 23), rng.randint(0, 59))
    if pick < 0.5:
        return rnd(WEIRD_NUM)
    if pick < 0.55 and not base:
        return None
    if pick < 0.6:
        return str(rnd(WEIRD_NUM))
    if pick < 0.65:
        return rnd(WEIRD_TEXT)
    return fixtures.sep(rng.randint(9, 28), rng.randint(0, 23)) + rng.random()

def row(number):
    made = fixtures.record(number)
    made["detected_at"] = rnd_time()
    for name in ("resumed_at", "outcome_at", "submitted_at", "reset_at", "last_claim_at"):
        made[name] = rnd_time(False)
    made["category"] = rnd(["usage_limit", "network_transient", "timeout", "server_5xx", "stream_interrupted"] + WEIRD_TEXT + [5])
    made["state"] = rnd(["recovered", "waiting_reset", "failed", "turn_started", "submission_unknown", "completed_no_progress", "recovery_turn_failed", "terminal_failure", "outcome_unverified"] + WEIRD_TEXT + [3])
    made["last_error"] = rnd(["progress_observed", "waiting_reset", "paused", "app_server_unmatched"] + WEIRD_TEXT + [None])
    made["recovery_turn_status"] = rnd(["completed", "failed", "interrupted"] + WEIRD_TEXT + [None])
    made["gate_eval"] = rnd(GATES + [None])
    made["limit_type"] = rnd(["codex:primary", "codex:secondary", "other"] + WEIRD_TEXT + [None, 4])
    made["recovery_client_id"] = rnd([None, "x", str(ids.continuation_client_id(made["interruption_id"]))])
    return made

PRELOADED = []
for number in range(1, 150):
    PRELOADED.append(row(number))

# hand-edited rows straight into the state: the reader's own columns, every type SQLite allows
for chunk in range(0, 120, 12):
    rows = PRELOADED[chunk:chunk + 12]
    home = make(rows, watcher_report=fixtures.watcher())
    read_case(home)
    read_case(home, "0.157.0")
    state_cases(home)

# logs: sizes, encodings, every line break, odd engine lines
def logs_home(files, **given):
    home = make(fixtures.BASE, log_files={}, **given)
    for name, data in files.items():
        (home.paths.logs_dir / name).write_bytes(data)
    return home

stamp, line, engine_line = fixtures.stamp, fixtures.line, fixtures.engine_line
def lines(*texts):
    return "\n".join(texts).encode("utf-8") + b"\n"
fine = [engine_line(fixtures.sep(12), fixtures.OLDER, "structurally_compatible"), engine_line(fixtures.sep(14), ENGINE, "verified"), line(fixtures.sep(15), "tick")]
log_homes = [
    {"auto-resume.log": lines(*fine)},
    {"auto-resume.log": ("\r\n".join(fine) + "\r\n").encode()},
    {"auto-resume.log": ("\r".join(fine) + "\r").encode()},
    {"auto-resume.log": ("\x0b".join(fine) + "\x0c" + line(fixtures.sep(16), "x") + "\x1c" + line(fixtures.sep(17), "y") + "\u2028" + "\u0085").encode()},
    {"auto-resume.log": lines(*fine).replace(b"tick", b"\xff\xfe bad \xc3\x28 bytes")},
    {"auto-resume.log": b"\xef\xbb\xbf" + lines(*fine)},
    {"auto-resume.log": b"A" * (8 * 1024 * 1024 + 1)},
    {"auto-resume.log": b"A" * (8 * 1024 * 1024 - 100000) + b"\n" + lines(*fine)},
    {"auto-resume.log": b""},
    {"auto-resume.log.5": lines(*fine), "auto-resume.log.4": lines(fine[1]), "auto-resume.log": lines(fine[2])},
    {"auto-resume.log.6": lines(*fine), "auto-resume.log": lines(fine[2])},
    {"auto-resume.log.1": lines(*fine)},
    {"auto-resume.log": lines(
        "[2026-09-15 10:00:00] engine codex-cli 0.158.0 is verified: its local checks pass, and the registry data in force verifies this build",
        "[2026-09-15 10:00:00]  engine codex-cli 0.158.0 passes its local checks (`codex queue` still offers --thread/--message).",
        "[2026-09-15 10:00:01] engine codex-cli 0.158.0;x", "[2026-09-15 10:00:02] engine codex-cli 0.158.0)",
        "[2026-09-15 10:00:03] engine codex-cli 0.158.0", "[2026-09-15 10:00:04] engine codex-cli 0.158.00 is checked",
        "[2026-09-15 10:00:05] engine codex-cli 0.158.0-alpha.1 is verified", "[2026-09-15 10:00:06] engine codex-cli \u0663.1.0 is verified",
        "[2026-09-15 10:00:07] engine codex-cli " + "9" * 45 + " is verified", "[2026-09-15 10:00:08] engine codex-cli 0.1.0,",
        "[2026-09-15 10:00:09] engine  codex-cli 0.158.0 is verified", "[\u0662026-09-15 10:00:10] engine codex-cli 0.9.0 is verified",
        "[2026-02-30 10:00:00] engine codex-cli 0.2.0 is verified", "[2026-09-15 24:00:00] engine codex-cli 0.3.0 is verified",
        "[2026-09-15 23:59:60] engine codex-cli 0.4.0 is verified", "[2026-09-15 23:59:61] engine codex-cli 0.5.0 is verified",
        "[0000-09-15 10:00:00] engine codex-cli 0.6.0 is verified", "[1969-12-31 23:59:59] engine codex-cli 0.7.0 is verified",
        "[3001-01-20 00:00:00] engine codex-cli 0.8.0 is verified", "[2026-09-15 10:00:00]no space", "[2026-09-15 10:00:00] ")},
]
for files in log_homes:
    home = logs_home(files, watcher_report=fixtures.watcher())
    read_case(home)
    read_case(home, "0.158.0")
    state_cases(home)
    nowatch = logs_home(files)
    read_case(nowatch, view=None)

# a log that is a link out of the home is passed over (a directory in place of a file, too)
dirlog = logs_home({})
(dirlog.paths.logs_dir / "auto-resume.log").mkdir()
read_case(dirlog, view=None)
state_cases(dirlog)
finish()
'''


LEDGER_SCRIPT = PRELUDE + r'''
ENGINE = fixtures.ENGINE
rng = random.Random(7)
BASE = fixtures.BASE

def ledger_home(rows, **given):
    home = make(rows, watcher_report=fixtures.watcher(), **given)
    return home

def paid_of(rows, share):
    return [(row["interruption_id"], row["last_claim_at"]) for row in rows if row["last_claim_at"] and rng.random() < share]

rows = BASE + [fixtures.PAID, fixtures.UNPAID, fixtures.LONG_AGO, fixtures.INSIDE_REACH]
for version in (1, 2):
    for share in (0.0, 0.5, 1.0):
        for pruned in (0, 2, 7):
            spends = paid_of(rows, share)
            home = ledger_home(rows, ledger=version, spends=spends, pruned=[(fixtures.key(900 + n), fixtures.sep(1 + n)) for n in range(pruned)])
            read_case(home)
            read_case(home, "0.157.0")
            state_cases(home)

# hand-edited ledgers: ids of the wrong type, times of the wrong type, no count kept, a full ledger
home = ledger_home(rows, ledger=2, spends=paid_of(rows, 1.0))
sql(home, "INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (?, 'goal_continuation', ?, ?)", "x", fixtures.uuid_of(1), fixtures.key(1), ledger=True)
sql(home, "INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (?, 'goal_continuation', ?, ?)", 5.5, fixtures.uuid_of(1), 12345, ledger=True)
sql(home, "INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (?, 'goal_continuation', ?, ?)", -3, fixtures.uuid_of(1), fixtures.key(3), ledger=True)
sql(home, "INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (?, 'goal_continuation', ?, ?)", 1e300, fixtures.uuid_of(1), fixtures.key(4), ledger=True)
read_case(home)
state_cases(home)
nocount = ledger_home(rows, ledger=2, spends=paid_of(rows, 1.0))
sql(nocount, "DELETE FROM sqlite_sequence", ledger=True)
read_case(nocount)
state_cases(nocount)
# a ledger that keeps no count at all: its table is not AUTOINCREMENT
nosequence = make(rows, watcher_report=fixtures.watcher())
nosequence.paths.advanced_dir.mkdir()
db = sqlite3.connect(nosequence.paths.advanced_dir / ledger_schema.FILE_NAME)
db.execute("CREATE TABLE spend (spend_id INTEGER PRIMARY KEY, at REAL, capability TEXT, thread_id TEXT, interruption_id TEXT)")
for key, at in paid_of(rows, 1.0):
    db.execute("INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (?, 'goal_continuation', ?, ?)", (at, fixtures.uuid_of(1), key))
db.execute("PRAGMA user_version = 2")
db.commit(); db.close()
read_case(nosequence)
state_cases(nosequence)
full = ledger_home(rows, ledger=2, spends=paid_of(rows, 1.0), pruned=[(fixtures.key(7000 + n), fixtures.sep(1)) for n in range(journal.EVENT_LIMIT)])
read_case(full)
state_cases(full)
exact = ledger_home(rows, ledger=2, spends=[(fixtures.key(8000 + n), fixtures.sep(1) + n) for n in range(journal.EVENT_LIMIT)])
read_case(exact)
state_cases(exact)

# ledger_reach, over the cases the tag's own tests name and a grid around them
now = fixtures.NOW
bounds = dict(max_age=journal.EVENT_MAX_AGE, limit=journal.EVENT_LIMIT)
for units in (0, 1, 3, journal.EVENT_LIMIT - 1, journal.EVENT_LIMIT, journal.EVENT_LIMIT + 1):
    for oldest in (None, 0, -5, fixtures.sep(1), fixtures.at(5, 1), "x", 1e300, 0.0, True, [1]):
        for given in (None, 0, 1, 3, 5, units, units + 1, units - 1, True, "x", 2.0, 10 ** 12):
            def ref(units=units, oldest=oldest, given=given):
                found = evidence.ledger_reach(units, oldest, given, now, **bounds)
                return found
            case("evidence.ledger_reach", units, oldest, given, now, journal.EVENT_MAX_AGE, journal.EVENT_LIMIT, ref=ref)

# by_route: generated records, paid times, every reach
def generated(count):
    out = []
    for number in range(count):
        made = fixtures.recovered(300 + number, 12 + number % 10, 9)
        pick = rng.random()
        if pick < 0.15:
            made["recovery_client_id"] = str(ids.continuation_client_id(made["interruption_id"]))
        elif pick < 0.3:
            made["gate_eval"] = fixtures.gates(thread_available=["PASS", rng.choice(["plugged", "held", "ok"])])
        elif pick < 0.4:
            made["gate_eval"] = fixtures.gates(consent=["WAIT", "held"])
        made["last_claim_at"] = rng.choice([made["last_claim_at"], None, 0, "x", made["last_claim_at"] + 1, -4])
        if rng.random() < 0.1:
            made["interruption_id"] = rng.choice([None, 5, "short"])
        out.append(made)
    return out

for repeat in range(40):
    sample = generated(rng.randint(0, 25))
    paid = {}
    for made in sample:
        key = made["interruption_id"]
        if isinstance(key, str) and rng.random() < 0.5 and isinstance(made["last_claim_at"], (int, float)):
            paid.setdefault(key, []).append(made["last_claim_at"] + rng.choice([0, 0, 1]))
    paid["unrelated"] = [1.0, 2.0]
    for reach in (None, 0, fixtures.sep(15), fixtures.NOW, float("inf"), -1.0):
        case("evidence.by_route", sample, paid, reach, ref=lambda sample=sample, paid=paid, reach=reach: (
            lambda found: [rows_of(found[0]), found[1], found[2]])(evidence.by_route(copy.deepcopy(sample), {key: set(times) for key, times in paid.items()}, reach)))
finish()
'''


EVIDENCE_SCRIPT = PRELUDE + r'''
rng = random.Random(1126)
ENGINE, OLDER, NEWER = fixtures.ENGINE, fixtures.OLDER, fixtures.NEWER
VERSIONS = [ENGINE, OLDER, NEWER, "codex-cli 0.100.0", "codex-cli 0.158.0-alpha.3"]

def timeline(count):
    when = fixtures.sep(9)
    out = []
    for _ in range(count):
        when += rng.choice([0, 1, 3600, 86400, 86400 * 3])
        out.append([when, rng.choice(VERSIONS)])
    return out

def row(number, spread):
    made = fixtures.recovered(number, 9 + rng.randint(0, spread), rng.randint(0, 23))
    for name in ("resumed_at", "outcome_at"):
        if rng.random() < 0.3:
            made[name] = None
    if rng.random() < 0.2:
        made["outcome_at"] = made["detected_at"] - rng.choice([0, 5, 100000])
    return made

# place / placement
for repeat in range(150):
    line_up = timeline(rng.randint(0, 9))
    rows = [row(500 + n, 18) for n in range(rng.randint(0, 12))]
    current = rng.choice(VERSIONS)
    version = rng.choice(VERSIONS)
    case("evidence.place", rows, line_up, current, version, ref=lambda rows=rows, line_up=line_up, current=current, version=version: (
        lambda found: [rows_of(found[0]), found[1], {str(code): many for code, many in sorted(found[2].items(), key=lambda each: str(each[0]))}])(
            evidence.place(copy.deepcopy(rows), [tuple(each) for each in line_up], current, version)))

# body: records, lines, watchers, progress
CAPS = ["usage_limit_detection", "usage_reset_hint", "engine_present", "projection_freshness", "loaded_state_detection", "usage_probe",
        "thread_eligibility", "exact_thread_recovery", "recovery_turn_tracking", "outcome_observation"]
def watcher():
    pick = rng.random()
    if pick < 0.2:
        return None
    if pick < 0.3:
        return {}
    out = {}
    for name in rng.sample(CAPS + ["queue_withdraw", "x"], rng.randint(0, 6)):
        out[name] = rng.choice([{"reason": "local_checks_passed"}, {"reason": "registry_verified"}, {"reason": "registry_checked"},
                                {"reason": "nope"}, {"reason": 7}, {}, 5, None, {"state": "verified"}])
    return out

def lines_for(version):
    out = []
    when = fixtures.sep(9)
    for _ in range(rng.randint(0, 6)):
        when += rng.choice([1, 3600, 86400])
        word = rng.choice(["verified", "structurally_compatible", "checked", "incompatible"])
        out.append([when, fixtures.engine_line(when, rng.choice([version, ENGINE, OLDER]), word).split("] ", 1)[1]])
    return out

for repeat in range(120):
    version = rng.choice(VERSIONS)
    rows = [row(700 + n, 15) for n in range(rng.randint(0, 14))]
    for made in rows:
        if rng.random() < 0.25:
            made["state"] = rng.choice(["failed", "submission_unknown", "turn_started", "recovered", "completed_no_progress", "waiting_reset"])
        if rng.random() < 0.15:
            made["gate_eval"] = rng.choice(['{"engine_compatible": ["WAIT", "x"]}', "{}", "bad", None, '{"identity": ["PASS", "ok"], "thread_available": ["WAIT", "x"]}'])
        if rng.random() < 0.15:
            made["resumed_at"] = None
        if rng.random() < 0.1:
            made["category"] = rng.choice(["network_transient", "timeout", "frob"])
    lines = lines_for(version)
    progress = [rng.choice([None, {"agentMessage": rng.randint(0, 9), "commandExecution": 0, "fileChange": rng.randint(0, 3), "mcpToolCall": 0}]) for _ in rows]
    given = watcher()
    case("evidence.body", version, rows, lines, given, progress, ref=lambda version=version, rows=rows, lines=lines, given=given, progress=progress:
         evidence.body(version, copy.deepcopy(rows), [tuple(each) for each in lines], copy.deepcopy(given), copy.deepcopy(progress)))

# the real fixture rows and one that holds a time Windows cannot write
rows = [row(900 + n, 5) for n in range(3)]
rows[1]["detected_at"] = 1e18
case("evidence.body", ENGINE, rows, [], None, [None] * 3, ref=lambda: evidence.body(ENGINE, copy.deepcopy(rows), [], None, [None] * 3))
rows = [row(910, 5)]
rows[0]["detected_at"] = 1e300
case("evidence.body", ENGINE, rows, [], None, [None], ref=lambda: evidence.body(ENGINE, copy.deepcopy(rows), [], None, [None]))
rows = [row(920, 5)]
rows[0]["outcome_at"] = 32536850400.2
case("evidence.body", ENGINE, rows, [[32536850400.2, "x"]], None, [None], ref=lambda: evidence.body(ENGINE, copy.deepcopy(rows), [(32536850400.2, "x")], None, [None]))

# current_engine
LINES = [[1.0, "engine codex-cli 0.150.0 is verified"], [2.0, "engine codex-cli 0.158.0 is checked"], [3.0, "tick"]]
for view in (None, {"status": "ok", "engine": {"version": "codex-cli 0.9.0"}, "capabilities": {"a": 1}}, {"status": "ok", "engine": {"version": "0.9.0"}},
             {"status": "ok", "engine": {"version": " 0.9.0 "}}, {"status": "ok", "engine": {"version": "\t"}}, {"status": "stale"}, {"status": "ok", "engine": {"version": "x y"}},
             {"status": "ok", "engine": {"version": "codex-cli 0.1.0-beta"}}, {"status": "ok", "engine": {"version": "codex-cli " + "9" * 45}},
             {"status": "ok", "engine": {"version": "\u0663.1.0"}}, {"status": True}, {"status": "ok", "engine": {"version": "codex-cli 0.9.0"}, "capabilities": None}):
    for given in (LINES, LINES[2:], []):
        case("reading.current_engine", view, given, ref=lambda view=view, given=given: (
            lambda found: [found[0], str(found[1]), found[2]])(reading.current_engine(view, [tuple(each) for each in given])))

for text in ("0.158.0", "codex-cli 0.158.0", " 0.158.0 ", "00.1.0", "0.01.0", "0.1.0-alpha.0", "0.1.0-alpha.3.0", "0.1.0-alpha.3.4", "codex-cli  0.1.0",
             "\u0660.1.0", "0.1.0-ALPHA.1", "1.2", "1.2.3.4", "999999.999999.999999", "1000000.0.0", "0.0.0-alpha.123456789", "0.0.0-alpha.1234567890", None, 7, True, [], "", "\n"):
    case("evidence.canonical_version", text, ref=lambda text=text: evidence.canonical_version(text))
finish()
'''


DOCUMENT_SCRIPT = PRELUDE + r'''
import hashlib
WINDOWS = "10.0.26200"
VERSION = "0.6.14-beta"
BODIES = {}
for name in sorted(fixtures.SCENARIOS):
    home, asked = fixtures.scenario(name)
    HOMES.append(home)
    with fixtures.isolated(home):
        BODIES[name] = records.read(home.paths, home.codex, asked, now=NOW, view=home.raw_view)["body"]
logins = ["ExampleUser", "a", "a-b", "com10", "x" * 39, "x" * 40, "-bad-", "", "two words", None, 7, "dou--ble", "nul", "COM1", "lpt0", "LPT9", "con", "Prn",
          "aux", "songyb111-gachon", "SongYB111-Gachon", "SONGYB111-GACHON", "a-", "-a", "a_b", "caf\u00e9", "\u0661abc", "abc\n", "a b", ["a"], True, "com", "lpt10",
          "Kelvin\u212A", "ExampleUser" + "\u200b", "0", "9-9"]
for login in logins:
    case("document.check_login", login, ref=lambda login=login: document.check_login(login))

def assembled(name, login="ExampleUser", **options):
    options = dict(dict(product_version=VERSION, windows=WINDOWS, now=NOW), **options)
    return document.assemble(BODIES[name], login, **options)

for name in BODIES:
    for login in ("ExampleUser", "nul", "a" * 39):
        for version, windows, now in ((VERSION, WINDOWS, NOW), ("0.6.26", "10.0.19045", 1.0), ("1.2.3-alpha", WINDOWS, NOW), ("0.6.14-beta.12", WINDOWS, 1e12),
                                       ("12345.1.1", WINDOWS, NOW), ("0.6.14-gamma", WINDOWS, NOW), ("unknown", WINDOWS, NOW), (VERSION, "6.1.7601", NOW), (VERSION, "10.0.261000", NOW),
                                       (VERSION, WINDOWS, 32536850400.0), (VERSION, WINDOWS, 1e300), (VERSION, WINDOWS, -1.0), (VERSION, WINDOWS, 0.0)):
            case("document.assemble", BODIES[name], login, version, windows, now,
                 ref=lambda name=name, login=login, version=version, windows=windows, now=now:
                 document.assemble(BODIES[name], login, product_version=version, windows=windows, now=now))
        case("document.check", assembled(name), ref=lambda name=name: document.check(assembled(name)).decode("ascii"))
        case("document.encode", assembled(name), ref=lambda name=name: document.encode(assembled(name)).decode("ascii"))

written = assembled("state4_ledger2")
def broken(change):
    copy_of = copy.deepcopy(written)
    change(copy_of)
    return copy_of
FAULTS = [
    lambda r: r.update(extra=1), lambda r: r.pop("note"), lambda r: r.update(note="Sent by me"),
    lambda r: r.update(format="codex-auto-resume-compat-evidence/2"), lambda r: r.update(codex_version="codex-cli 00.158.0"),
    lambda r: r.update(codex_version=None), lambda r: r.update(codex_version=7), lambda r: r.update(codex_version="0.158.0"),
    lambda r: r.update(verdict="GREAT"), lambda r: r.update(verdict=None), lambda r: r.update(verdict=["PASS"]),
    lambda r: r.update(recorded_at="yesterday"), lambda r: r.update(recorded_at=None), lambda r: r.update(recorded_at="2026-09-30T12:00:00+00:00"),
    lambda r: r.update(recorded_at="\u0662026-09-30T12:00:00Z"), lambda r: r.update(recorded_at="2026-09-30T12:00:00Z\n"),
    lambda r: r.update(recorded_by="someone else"), lambda r: r.update(recorded_by=None),
    lambda r: r["reporter"].update(tool="codex-compat-reporter"), lambda r: r["reporter"].update(tool_version="1.5.0"),
    lambda r: r["reporter"].update(windows="6.1.7601"), lambda r: r["reporter"].update(windows=None), lambda r: r["reporter"].update(windows=10),
    lambda r: r["reporter"].update(windows="10.0.26200\n"), lambda r: r["reporter"].update(windows="10.0.\u0662\u0662\u0662\u0662\u0662"),
    lambda r: r["reporter"].update(product_version="C:\\Users\\ExampleUser"), lambda r: r["reporter"].update(product_version=None),
    lambda r: r["reporter"].update(github_login="nul"), lambda r: r["reporter"].update(github_login="songyb111-gachon"),
    lambda r: r["reporter"].update(github_login="-x"), lambda r: r["reporter"].update(github_login=3),
    lambda r: r["reporter"].update(machine="x"), lambda r: r.update(reporter=None), lambda r: r.update(reporter=[]),
    lambda r: r["attribution"].update(window=["a", "b"]), lambda r: r["attribution"].update(rule="x"), lambda r: r["attribution"].update(basis=1),
    lambda r: r.update(attribution=None), lambda r: r.update(attribution={"basis": None, "window": None, "rule": r["attribution"]["rule"]}),
    lambda r: r["local_checks"].update(covers=["queue_withdraw"]), lambda r: r["local_checks"].update(covers=["usage_probe", "usage_probe"]),
    lambda r: r["local_checks"].update(covers=None), lambda r: r["local_checks"].update(covers="usage_probe"), lambda r: r["local_checks"].update(reports=-1),
    lambda r: r["local_checks"].update(reports=True), lambda r: r["local_checks"].update(reports=10 ** 6), lambda r: r["local_checks"].update(reports=10 ** 6 + 1),
    lambda r: r["local_checks"].update(first="x"), lambda r: r["local_checks"].update(last=5), lambda r: r.update(local_checks=None),
    lambda r: r.update(records=None), lambda r: r.update(records={}), lambda r: r["records"].append(None), lambda r: r["records"][0].update(category=None),
    lambda r: r["records"][0].update(state="C:\\Users\\ExampleUser\\secret.txt"), lambda r: r["records"][0].update(reason="Hello, world"),
    lambda r: r["records"][0].update(turn_status=3), lambda r: r["records"][0].update(state="other"), lambda r: r["records"][0].update(reason=None),
    lambda r: r["records"][0].update(detected_at=1790000000), lambda r: r["records"][0].update(detected_at=None),
    lambda r: r["records"][0].update(delivered_at="x"), lambda r: r["records"][0].update(outcome_at=0),
    lambda r: r["records"][0].update(gates_passed=True), lambda r: r["records"][0].update(gates_passed=65), lambda r: r["records"][0].update(gates_passed=64),
    lambda r: r["records"][0].update(gates_passed=-1), lambda r: r["records"][0].update(gates_passed=1.0),
    lambda r: r["records"][0].update(text="a private sentence"), lambda r: r["records"][0].pop("state"),
    lambda r: r["records"][0].update(progress_items={"agentMessage": 1}), lambda r: r["records"][0].update(progress_items=[]),
    lambda r: r["records"][0].update(progress_items={"agentMessage": 1, "commandExecution": 2, "fileChange": 3, "mcpToolCall": 4}),
    lambda r: r["records"][0].update(progress_items={"agentMessage": -1, "commandExecution": 2, "fileChange": 3, "mcpToolCall": 4}),
    lambda r: r["records"][0].update(progress_items={"commandExecution": 2, "agentMessage": 1, "fileChange": 3, "mcpToolCall": 4}),
    lambda r: r["records"][0].update(progress_items={"agentMessage": 10 ** 6, "commandExecution": 2, "fileChange": 3, "mcpToolCall": 10 ** 6 + 1}),
    lambda r: r["capabilities"].pop("usage_probe"), lambda r: r["capabilities"]["usage_probe"].update(level="GREAT"),
    lambda r: r["capabilities"]["usage_probe"].update(level="CHECKED"), lambda r: r["capabilities"]["usage_probe"].update(level=None),
    lambda r: r["capabilities"]["usage_probe"].update(level=1), lambda r: r["capabilities"]["usage_probe"].update(confirmed=-1),
    lambda r: r["capabilities"]["usage_probe"].update(confirmed=501), lambda r: r["capabilities"]["usage_probe"].update(confirmed=500),
    lambda r: r["capabilities"]["usage_probe"].update(missed=501), lambda r: r["capabilities"]["usage_probe"].update(last_confirmed="x"),
    lambda r: r["capabilities"]["usage_probe"].update(extra=1), lambda r: r.update(capabilities=None),
    lambda r: r["capabilities"].update(queue_withdraw=r["capabilities"]["usage_probe"]),
    lambda r: r.update(records=r["records"][:1] * evidence.MAX_RECORDS), lambda r: r.update(records=r["records"][:1] * (evidence.MAX_RECORDS + 1)),
    lambda r: r.update(records=[]),
    lambda r: r["records"][0].update(state=float("nan")), lambda r: r.update(codex_version="codex-cli 0.158.0", verdict="NONE"),
]
for number, change in enumerate(FAULTS):
    case("document.check", broken(change), ref=lambda change=change: document.check(broken(change)).decode("ascii"))

# the size: one byte under and over a megabyte, by padding a report with the one thing a record may be - a time
base_bytes = len(document.encode(written))
many = broken(lambda r: r.update(records=r["records"][:1] * evidence.MAX_RECORDS))
case("document.check", many, ref=lambda: document.check(many).decode("ascii"))
case("document.check", written, ref=lambda: document.check(written).decode("ascii"))
finish()
'''


class ReadDiff(advreport.ReportDiff):
    def test_the_six_scenarios_and_every_refusal(self):
        found = self.family(READ_SCRIPT, label="read", expect_cases=300, readonly=True)
        refusals = {result.get("code") for result in found["results"] if "error" in result}
        for code in ("no_state", "state_newer", "state_older", "state_unreadable", "ledger_newer", "ledger_unreadable",
                     "no_engine_version", "version_invalid", "too_many_records"):
            self.assertIn(code, refusals, "no case of the corpus is refused as %s" % code)
        self.assertTrue(any("ok" in result for result in found["results"]))
        RECORD.append("records: %d cases - the six scenarios asked %d ways, every refusal, junctions, a locked state, "
                      "the history absent, moved or gone; the homes left untouched" % (len(found["cases"]), 18 + 13 + 3))


LOCKED_MAKE = PRELUDE + r'''
home = make(fixtures.BASE)
case("reading.paused", str(home.paths.home), ref=lambda: None)
finish()
'''

LOCKED_READ = PRELUDE + r'''
home = fixtures.Home.__new__(fixtures.Home)
from codex_auto_resume import config
root = Path(sys.argv[3])
home.paths, home.codex = config.Paths(root / "product"), root / "codex-home"
home.root = root
read_case(home)
state_cases(home)
finish()
'''


class LockedDiff(advreport.ReportDiff):
    def test_a_locked_state_is_busy_not_waited_for(self):
        """The state held under an exclusive lock by this process: both readers give up after their own three seconds
        and answer `state_busy`, and `paused` says it cannot tell."""
        import sqlite3
        folder, cases, _ = self.reference(LOCKED_MAKE, label="locked-make")
        home = next(path for path in folder.glob("*") if (path / "product").is_dir())
        blocker = sqlite3.connect(home / "product" / "config" / "state.sqlite", timeout=0)
        blocker.execute("BEGIN EXCLUSIVE")
        try:
            ran, cases, expected = self.reference(LOCKED_READ, label="locked", arguments=[home])
            actual = self.rust(ran, cases)
        finally:
            blocker.rollback()
            blocker.close()
        self.assertTrue(any(result.get("code") == "state_busy" for result in expected), expected)
        self.same("locked", cases, expected, actual)
        RECORD.append("locked: the state held under an exclusive lock - both readers answer state_busy, and paused is None")


class DamagedDiff(advreport.ReportDiff):
    def test_hand_edited_rows_and_logs(self):
        found = self.family(DAMAGED_SCRIPT, label="damaged", expect_cases=100, readonly=True)
        RECORD.append("damaged: %d cases - rows of every wrong type and time, gate evaluations that are not JSON, logs of "
                      "every size, encoding and line break" % len(found["cases"]))


class LedgerDiff(advreport.ReportDiff):
    def test_the_spend_ledger_in_every_shape(self):
        found = self.family(LEDGER_SCRIPT, label="ledger", expect_cases=300, readonly=True)
        RECORD.append("ledger: %d cases - versions 1 and 2, units pruned, a count kept or not, ids and times of the wrong "
                      "type, a full ledger, ledger_reach on a grid and by_route over generated records" % len(found["cases"]))


class EvidenceDiff(advreport.ReportDiff):
    def test_place_body_and_the_engine_in_use(self):
        found = self.family(EVIDENCE_SCRIPT, label="evidence", expect_cases=300)
        RECORD.append("evidence: %d cases - place, body (verdicts, levels, progress counts, times past Windows') and "
                      "current_engine over generated records, logs and watchers' reports" % len(found["cases"]))


class DocumentDiff(advreport.ReportDiff):
    def test_the_envelope_and_the_self_check(self):
        found = self.family(DOCUMENT_SCRIPT, label="document", expect_cases=300)
        codes = {result.get("code") for result in found["results"] if "error" in result}
        for code in ("login_invalid", "login_reserved", "login_owner", "too_many_records"):
            self.assertIn(code, codes, code)
        classes = {result["error"] for result in found["results"] if "error" in result}
        self.assertIn("DocumentError", classes)
        RECORD.append("document: %d cases - every login, assemble over the six bodies, check over %d breakages of a "
                      "report" % (len(found["cases"]), 120))


if __name__ == "__main__":
    unittest.main()
