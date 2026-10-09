# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What a compatibility report says of records already read: pure, and counted as
codex-compat-reporter counts it.

The report's format is the maintainer's own (`codex-auto-resume-compat-evidence/1`), and
codex-compat-reporter 1.5.0 writes it today (codex_compat_report.py, `build`). The in-app report
writes the same file of the same records, so every rule here is that program's, in its order and
to the letter: which engine a record belongs to (`placement`), which route carried it
(`another_route`, `beyond_reach`), what its words may be (`known`), and how its capabilities and
its verdict are counted (`body`). advanced/tests/golden/report/ holds what 1.5.0's own `build`
writes of the fixtures, and advanced/tests/test_advanced_report_records.py holds this to it.

Where the reporter copies a word from the product, this takes it from the product: the record's
vocabularies, the progress kinds, the send gate, the client id a marker-free continuation is
queued under, the gate words only the edition's plug writes, and the engine lines the watcher
logs (runtime/app.py, imported only when a report is written: it is the composition root). What
a report leaves out is told in closed codes (`Unplaced`), never in a sentence.

Nothing here opens a file, and nothing here imports the rest of the advanced package: records.py
reads, and hands this what it read. So both could move into core unchanged if a standard export
is ever approved (docs: the design's option X).
"""
from __future__ import annotations

import collections
import datetime as dt
from enum import StrEnum
import functools
import json
import math
import re
import time

from codex_auto_resume import compat, machine
from codex_auto_resume.codex.values import PROGRESS_ITEM_TYPES
from codex_auto_resume.domain import gates, ids
from codex_auto_resume.domain import vocabulary as words
from codex_auto_resume.domain.compat_vocabulary import Capability, ResolutionReason

# The receiving side's limit (build/community_report.py MAX_RECORDS), which it refuses past.
MAX_RECORDS = 500
TIME = "%Y-%m-%dT%H:%M:%SZ"
OTHER = "other"                                  # a word the report may not carry, as the reporter writes it

# `codex-cli <version>` as the product names engines (the reporter's VERSION and GRAMMAR): the project
# reads 0.1.0, 00.1.0 and 0.01.0 as one engine and takes only the spelling the product writes back.
VERSION = re.compile(r"\Acodex-cli \d[0-9A-Za-z.\-]{0,39}\Z")
GRAMMAR = re.compile(r"\Acodex-cli (\d{1,6})\.(\d{1,6})\.(\d{1,6})(?:-alpha\.(\d{1,9})(?:\.(\d{1,9}))?)?\Z")
# A line of the product's log (logbook.py: "[%(asctime)s] %(message)s", local time), and the engine a
# line names (runtime/app.py: "engine <version> <words>.").
LOG_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$")
ENGINE = re.compile(r"engine (codex-cli \d[0-9A-Za-z.\-]*?)[\s;,)]")
# What v0.6.0 to v0.6.4 logged of an engine they accepted; a rotated log may still hold it.
ENGINE_LOG_BEFORE_0_6_5 = "accepted because `codex queue` still offers"

# The product's own words, which a record may carry; any other becomes OTHER (as the receiving side
# reads them, build/community_report.py).
CATEGORIES = frozenset(str(word) for word in words.FailureCategory)
STATES = frozenset(str(word) for word in words.RecordState)
REASONS = frozenset(str(word) for word in words.ReasonCode)
TURN_STATUSES = frozenset(str(word) for word in words.TurnStatus)
PROGRESS = tuple(sorted(PROGRESS_ITEM_TYPES))
GATE = tuple(str(name) for name in compat.SEND_GATE)
# An outcome the product observed; `outcome_unverified` says it could not observe one.
OUTCOMES = frozenset(machine.OUTCOMES) - {str(words.RecordState.OUTCOME_UNVERIFIED)}
# The reasons the watcher's own compatibility report gives a capability whose local checks passed
# (compat/standing.py resolve: a registry_* reason is given only on a local PASS).
LOCAL_PASS_REASONS = frozenset({str(ResolutionReason.LOCAL_CHECKS_PASSED), str(ResolutionReason.REGISTRY_VERIFIED),
                                str(ResolutionReason.REGISTRY_CHECKED)})
# Gate words only the edition's plug writes, at any gate but consent (domain/gates.py, HELD and PLUGGED).
PLUG_WORDS = frozenset({gates.PLUGGED, gates.HELD})
CONSENT = str(words.GateName.CONSENT)


class Unplaced(StrEnum):
    """Why a record cannot be placed on one engine version (the reporter's four sentences, as codes)."""
    NO_ENGINE_LINE_BEFORE = "no_engine_line_before"        # no engine line before it in the logs kept
    ENGINE_CHANGED_DURING = "engine_changed_during"        # another version was named while it ran
    NEXT_LINE_OTHER_VERSION = "next_line_other_version"    # the next engine line after it names another
    ENGINE_CHANGED_AFTER = "engine_changed_after"          # no line after it, and the engine now is another


# ------------------------------------------------------------------------------ small readers
def moment(value):
    """A stored time as a number, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def iso(when) -> str:
    return dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime(TIME)


def known(value, vocabulary):
    """The word itself when the report is allowed to carry it, OTHER when it is not."""
    if value is None:
        return None
    return value if isinstance(value, str) and value in vocabulary else OTHER


def full(version: str) -> str:
    version = version.strip()
    return version if version.startswith("codex-cli ") else "codex-cli " + version


def canonical_version(value):
    """`codex-cli <version>` in the one spelling the product writes, or None: 0.158.0 and
    codex-cli 0.158.0 alike, never 00.158.0 or an alpha's .0."""
    if not isinstance(value, str):
        return None
    version = full(value)
    found = GRAMMAR.match(version)
    if not found or not VERSION.match(version):
        return None
    major, minor, patch, alpha, sub = found.groups()
    written = "codex-cli %d.%d.%d" % (int(major), int(minor), int(patch))
    if alpha is not None:
        written += "-alpha.%d" % int(alpha) + (".%d" % int(sub) if sub is not None and int(sub) else "")
    return version if written == version else None


# ------------------------------------------------------------------------------ one record
def gate_vector(row) -> dict:
    """The record's gate evaluation, or {} when it is missing or not what the product writes."""
    try:
        found = json.loads(row["gate_eval"] or "{}")
    except (ValueError, TypeError, RecursionError):
        return {}
    return found if isinstance(found, dict) else {}


def gate_passed(row, name):
    """True or False for one gate; None when the evaluation is not the JSON object the product writes."""
    try:
        found = json.loads(row["gate_eval"] or "{}")
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(found, dict):
        return None
    gate = found.get(name)
    return isinstance(gate, list) and bool(gate) and gate[0] == gates.PASS


def delivered(row) -> bool:
    """The product proved its message arrived: resumed_at is set (the report's delivered_at)."""
    return bool(row["resumed_at"])


def _settled(row):
    return (row["state"] in OUTCOMES) if delivered(row) and row["state"] != "turn_started" else None


# What each of the ten capabilities a record can exercise makes of one record: True confirmed,
# False missed, None not exercised - the reporter's EXERCISED, by the product's own names.
EXERCISED = {
    str(Capability.USAGE_LIMIT_DETECTION): lambda r: True if r["category"] == "usage_limit" else None,
    str(Capability.USAGE_RESET_HINT): lambda r: (bool(r["reset_at"]) and str(r["limit_type"] or "").startswith("codex:"))
                                                if r["category"] == "usage_limit" else None,
    str(Capability.ENGINE_PRESENT): lambda r: gate_passed(r, "engine_compatible") if r["gate_eval"] else None,
    str(Capability.PROJECTION_FRESHNESS): lambda r: gate_passed(r, "identity") if r["gate_eval"] else None,
    str(Capability.LOADED_STATE_DETECTION): lambda r: gate_passed(r, "thread_available") if r["gate_eval"] else None,
    str(Capability.USAGE_PROBE): lambda r: gate_passed(r, "usage") if r["gate_eval"] else None,
    str(Capability.THREAD_ELIGIBILITY): lambda r: True if r["submitted_at"] else None,
    str(Capability.EXACT_THREAD_RECOVERY): lambda r: True if delivered(r) else (
        False if r["submitted_at"] and r["state"] in ("submission_unknown", "failed") else None),
    str(Capability.RECOVERY_TURN_TRACKING): _settled,
    str(Capability.OUTCOME_OBSERVATION): _settled,
}
REPORTABLE = tuple(sorted(EXERCISED))


# ------------------------------------------------------------------------------ the logs
def log_lines(texts) -> list:
    """(time, text) for every line of the logs' texts, given oldest file first, sorted by time.
    The time is the line's local time (logbook.py), read back on this PC as the reporter reads it."""
    lines = []
    for text in texts:
        for line in text.splitlines():
            found = LOG_LINE.match(line)
            if not found:
                continue
            try:
                when = time.mktime(time.strptime(found.group(1), "%Y-%m-%d %H:%M:%S"))
            except (ValueError, OverflowError):
                continue
            lines.append((when, found.group(2)))
    lines.sort(key=lambda line: line[0])
    return lines


def engine_version_of(text: str):
    found = ENGINE.search(text + " ")
    return found.group(1) if found else None


def engine_timeline(lines) -> list:
    return [(when, version) for when, text in lines for version in [engine_version_of(text)] if version]


def latest_engine(lines):
    """The engine the last engine line names, or None."""
    for _when, text in reversed(lines):
        found = engine_version_of(text)
        if found and VERSION.match(found):
            return found
    return None


@functools.cache
def _passes() -> tuple:
    """The words of an engine line that says the local checks passed and the engine was used: every
    one the watcher writes but "incompatible", whose engine is sent nothing, and v0.6.0-v0.6.4's."""
    from codex_auto_resume.runtime.app import ENGINE_LOG_CHECKS_ONLY, ENGINE_LOG_WORDS
    return tuple(words for word, words in ENGINE_LOG_WORDS.items() if word != "incompatible") + (
        ENGINE_LOG_CHECKS_ONLY, ENGINE_LOG_BEFORE_0_6_5)


def passes_checks(text: str, version: str) -> bool:
    """A log line saying the product's local checks passed on exactly this engine version."""
    return engine_version_of(text) == version and any(said in text for said in _passes())


# ------------------------------------------------------------------------------ which engine
def span(row):
    start = moment(row["resumed_at"]) or moment(row["detected_at"])
    return start, moment(row["outcome_at"]) or start


def placement(timeline, start, end, current):
    """(version, None) for the engine version a record belongs to, or (None, Unplaced) when the
    product's own lines cannot say: the last line before must name it, no line between may name
    another, and the first line after must name it too - or there is none yet and it is the
    version in use now."""
    before = [version for when, version in timeline if when <= start]
    if not before:
        return None, Unplaced.NO_ENGINE_LINE_BEFORE
    version = before[-1]
    if {other for when, other in timeline if start < when < end} - {version}:
        return None, Unplaced.ENGINE_CHANGED_DURING
    after = [other for when, other in timeline if when >= end]
    if after:
        if after[0] == version:
            return version, None
        return None, Unplaced.NEXT_LINE_OTHER_VERSION
    return (version, None) if version == current else (None, Unplaced.ENGINE_CHANGED_AFTER)


def place(rows, timeline, current, version):
    """(the records on `version`, oldest first; how many are on another; how many could not be
    placed, by code)."""
    placed, elsewhere, unplaced = [], 0, collections.Counter()
    for row in rows:
        found, why = placement(timeline, *span(row), current)
        if found == version:
            placed.append(row)
        elif found:
            elsewhere += 1
        else:
            unplaced[why] += 1
    placed.sort(key=lambda row: moment(row["detected_at"]))
    return placed, elsewhere, unplaced


# ------------------------------------------------------------------------------ which route
def ledger_reach(units, oldest, given, now, *, max_age, limit):
    """The earliest claim time a spend ledger holding `units` units, the oldest at `oldest`, and
    given `given` in all, can still tell at `now`; None when it has pruned none and tells every
    claim. `max_age` and `limit` are the ledger's own bounds (state/journal.py), which prune a unit
    older than `max_age`, then the oldest beyond `limit`."""
    if isinstance(given, int) and not isinstance(given, bool) and given <= units:
        return None
    bounds = []
    if units and moment(oldest) is not None:
        bounds.append(moment(oldest))                  # every unit pruned is older than every unit kept
    if units < limit:
        bounds.append(now - max_age)                   # then only age pruned one, and only an older one
    return min(bounds) if bounds else math.inf


def another_route(row, paid) -> bool:
    """Whether an advanced feature carried this record by a route of its own, by the product's own
    marks: the marker-free continuation's client id, a gate word only the edition's plug writes,
    or a unit the spend ledger paid at the claim the record was last sent from."""
    key = row["interruption_id"]
    if isinstance(key, str) and row["recovery_client_id"] == str(ids.continuation_client_id(key)):
        return True
    if any(name != CONSENT and isinstance(gate, list) and len(gate) == 2 and isinstance(gate[1], str)
           and gate[1] in PLUG_WORDS for name, gate in gate_vector(row).items()):
        return True
    claim = moment(row["last_claim_at"])
    return claim is not None and claim in paid.get(key, ())


def beyond_reach(row, reach) -> bool:
    """Whether the record was last claimed before its ledger can tell which route it went by."""
    claim = moment(row["last_claim_at"])
    return reach is not None and claim is not None and claim < reach


def by_route(rows, paid, reach):
    """(the records the standard route carried, how many another route did, how many were claimed
    before the ledger can tell); a report leaves out the last two."""
    kept, routed, unknown = [], 0, 0
    for row in rows:
        if another_route(row, paid):
            routed += 1
        elif beyond_reach(row, reach):
            unknown += 1
        else:
            kept.append(row)
    return kept, routed, unknown


# ------------------------------------------------------------------------------ the body
def body(version, rows, lines, watcher, progress) -> dict:
    """What the records show for one engine version: the report's codex_version, verdict,
    local_checks, records and capabilities, as the reporter writes them.

    `rows` are the records placed on `version`, oldest first; `lines` the logs' lines; `watcher`
    the capabilities of the watcher's own report while it is in force for this very version, or
    None; `progress` each record's counts of the four kinds, or None, in the order of `rows`."""
    reports = [(when, text) for when, text in lines if passes_checks(text, version)]
    checked = set(GATE) if reports else set()
    if isinstance(watcher, dict):
        # Only the ten a report may name: the watcher judges sixteen, and a name outside these
        # would get the whole report refused on arrival.
        checked |= {name for name, capability in watcher.items()
                    if name in EXERCISED and isinstance(capability, dict)
                    and capability.get("reason") in LOCAL_PASS_REASONS}

    capabilities = {}
    for name, judge in EXERCISED.items():
        verdicts = [judge(row) for row in rows]
        last = max((moment(row["outcome_at"]) or moment(row["detected_at"])
                    for row, verdict in zip(rows, verdicts) if verdict), default=None)
        capabilities[name] = {"confirmed": verdicts.count(True), "missed": verdicts.count(False),
                              "last_confirmed": iso(last) if last else None}
    seen = any(delivered(row) and row["state"] in OUTCOMES for row in rows)
    for name in sorted(capabilities):
        entry = capabilities[name]
        if seen and entry["confirmed"] and not entry["missed"]:
            entry["level"] = compat.VERIFIED
        elif name in checked:
            entry["level"] = compat.CHECKED
        else:
            entry["level"] = None
    # A recovery that did not clear the gate verifies nothing, as the maintainer's tool has it.
    if seen and not all(capabilities[name]["level"] == compat.VERIFIED for name in GATE):
        for name, entry in capabilities.items():
            if entry["level"] == compat.VERIFIED:
                entry["level"] = compat.CHECKED if name in checked else None
    levels = [entry["level"] for entry in capabilities.values() if entry["level"]]

    return {
        "codex_version": version,
        "verdict": "PASS" if compat.VERIFIED in levels else ("CHECKED" if levels else "NONE"),
        "local_checks": {"reports": len(reports),
                         "first": iso(reports[0][0]) if reports else None,
                         "last": iso(reports[-1][0]) if reports else None,
                         "covers": sorted(checked)},
        "records": [{
            "detected_at": iso(moment(row["detected_at"])),
            "delivered_at": iso(moment(row["resumed_at"])) if moment(row["resumed_at"]) else None,
            "outcome_at": iso(moment(row["outcome_at"])) if moment(row["outcome_at"]) else None,
            "category": known(row["category"], CATEGORIES), "state": known(row["state"], STATES),
            "reason": known(row["last_error"], REASONS),
            "turn_status": known(row["recovery_turn_status"], TURN_STATUSES),
            "gates_passed": sum(1 for gate in gate_vector(row).values()
                                if isinstance(gate, list) and gate and gate[0] == gates.PASS),
            "progress_items": counts,
        } for row, counts in zip(rows, progress)],
        "capabilities": {name: capabilities[name] for name in sorted(capabilities)},
    }
