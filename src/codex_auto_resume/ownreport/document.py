"""The compatibility report's body held to the project's rules, and this PC's own report as a file.

`check_parts` is the self-check of what every report this product writes says of its records -
`local_checks`, `records` and `capabilities`, the part codex-compat-reporter's `build` writes of
them: exactly the format's keys at every level, every string a time or one of the product's closed
words, every count a count, at most 500 records. A record set larger than the project takes is a
refusal with a closed code (`DocumentRefusal`); anything else would be a fault of this code, and is
an error (`DocumentError`). The advanced edition's report, which a person can send, checks its
envelope around the same parts.

`assemble` is the Dashboard's own report (v0.6.19, both editions): this PC's records for every
Codex version its own log names, each version's body exactly as the reporter writes one, counted
by the project's rule (evidence.graded), in an envelope that names nobody - no GitHub login, no
path, no id - because it is sent nowhere. It is shown whole with its SHA-256 and goes into the
diagnostics export; the person who wants it counted sends it the reporter's or the web's way.

The Windows version is the one Windows reports to this process (sys.getwindowsversion), never
`platform`, which can start a console program to ask (tests/test_no_console_windows.py).
"""
from __future__ import annotations

from enum import StrEnum
import hashlib
import json
import re
import sys
import time

from codex_auto_resume import compat, config

from . import evidence

FORMAT = "codex-auto-resume-own-report/1"
# codex-compat-reporter's own sentence (codex_compat_report.py build, 1.5.0), word for word.
RULE = ("a record counts for this version only when the product's engine reports before and after it - or "
        "the version installed now - name this version and no other")
COUNTING = ("a version is worked when at least one delivered record ended recovered, failed when at least one "
            "ended in a failed recovery, neither when no delivered record ended either way, and both when it is "
            "worked and failed at once")
NOTE = ("Written on this PC from its own records and sent nowhere: counts, states and times, with no conversation "
        "text, identifiers, paths or names. progress_items are null: the Dashboard does not read Codex's history.")
MAX_BYTES = 1_000_000                            # the receiving side's limit (build/community_report.py)
ISO = re.compile(r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")
PRODUCT_VERSION = re.compile(r"\A\d{1,4}\.\d{1,4}\.\d{1,4}(?:-(?:alpha|beta)(?:\.\d{1,3})?)?\Z")
WINDOWS = re.compile(r"\A10\.0\.\d{5}\Z")

LOCAL_KEYS = ("reports", "first", "last", "covers")
RECORD_KEYS = ("detected_at", "delivered_at", "outcome_at", "category", "state", "reason", "turn_status",
               "gates_passed", "progress_items")
CAPABILITY_KEYS = ("confirmed", "missed", "last_confirmed", "level")
BODY_KEYS = ("codex_version", "verdict", "local_checks", "records", "capabilities")
VERDICTS = ("PASS", "CHECKED", "NONE")
LEVELS = (compat.VERIFIED, compat.CHECKED, None)
COUNTED = ("worked", "failed", "neither", "both")
TOP_KEYS = ("format", "recorded_at", "product_version", "windows", "engine", "rule", "counting", "left_out",
            "versions", "note")
ENGINE_KEYS = ("current", "from")
LEFT_OUT_KEYS = ("hidden", "another_route", "beyond_reach", "unplaced")
VERSION_KEYS = ("codex_version", "counted", "refusal", "body")


class DocumentRefusal(StrEnum):
    """Why a report could not be written as a file the project would take."""
    LOGIN_INVALID = "login_invalid"              # not a GitHub login
    LOGIN_RESERVED = "login_reserved"            # a name Windows keeps for a device
    LOGIN_OWNER = "login_owner"                  # the repository's owner, whose evidence is the project's own
    TOO_MANY_RECORDS = "too_many_records"        # more records than the project takes
    TOO_LARGE = "too_large"                      # larger than the project takes


class DocumentRefused(Exception):
    """No document: `code` says why, and nothing else does."""

    def __init__(self, code):
        self.code = DocumentRefusal(code)
        super().__init__(str(self.code))


class DocumentError(RuntimeError):
    """A document that breaks the format in a way only a fault could: a static reason, no value."""


def windows_version():
    """The Windows build this process runs on, as `10.0.26200`, or None off Windows."""
    getter = getattr(sys, "getwindowsversion", None)
    if getter is None:
        return None
    found = getter()
    return "%d.%d.%d" % (found.major, found.minor, found.build)


def encode(document) -> bytes:
    """The bytes a report is: two-space JSON, ASCII, one newline at the end - the reporter's, and
    the project's own (build/community_report.py encode)."""
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("ascii")


# ------------------------------------------------------------------------------ the self-check
def keys(value, wanted, where) -> None:
    if not isinstance(value, dict) or tuple(value) != tuple(wanted):
        raise DocumentError("%s does not hold exactly the format's keys, in its order" % where)


def word(value, words, where) -> None:
    if value is not None and (not isinstance(value, str) or value not in words):
        raise DocumentError("%s is not one of the product's closed words" % where)


def moment(value, where, *, required=False) -> None:
    if (value is None and required) or (value is not None and not (isinstance(value, str) and ISO.match(value))):
        raise DocumentError("%s is not a UTC time" % where)


def count(value, where, limit=10 ** 6) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
        raise DocumentError("%s is not a count" % where)


def check_parts(part, where="") -> None:
    """`part`'s local_checks, records and capabilities - a body's, or a whole report's - held to the
    format: DocumentRefused when it holds more records than the project takes, DocumentError when
    anything in it is not a time, a count or a closed word. `where` prefixes the field named."""
    checks = part["local_checks"]
    keys(checks, LOCAL_KEYS, where + "local_checks")
    count(checks["reports"], where + "local_checks.reports")
    moment(checks["first"], where + "local_checks.first")
    moment(checks["last"], where + "local_checks.last")
    if (not isinstance(checks["covers"], list) or len(set(checks["covers"])) != len(checks["covers"])
            or not set(checks["covers"]) <= set(evidence.REPORTABLE)):
        raise DocumentError("%slocal_checks.covers names something that is not one of the ten capabilities" % where)

    records = part["records"]
    if not isinstance(records, list):
        raise DocumentError("%srecords is not a list" % where)
    if len(records) > evidence.MAX_RECORDS:
        raise DocumentRefused(DocumentRefusal.TOO_MANY_RECORDS)
    for number, record in enumerate(records):
        at = "%srecords[%d]" % (where, number)
        keys(record, RECORD_KEYS, at)
        moment(record["detected_at"], at + ".detected_at", required=True)
        moment(record["delivered_at"], at + ".delivered_at")
        moment(record["outcome_at"], at + ".outcome_at")
        for field, words in (("category", evidence.CATEGORIES), ("state", evidence.STATES),
                             ("reason", evidence.REASONS), ("turn_status", evidence.TURN_STATUSES)):
            word(record[field], words | {evidence.OTHER}, "%s.%s" % (at, field))
        count(record["gates_passed"], at + ".gates_passed", limit=64)
        items = record["progress_items"]
        if items is not None:
            keys(items, evidence.PROGRESS, at + ".progress_items")
            for kind, many in items.items():
                count(many, "%s.progress_items.%s" % (at, kind))

    capabilities = part["capabilities"]
    keys(capabilities, evidence.REPORTABLE, where + "capabilities")
    for name, entry in capabilities.items():
        at = where + "capabilities." + name
        keys(entry, CAPABILITY_KEYS, at)
        count(entry["confirmed"], at + ".confirmed", evidence.MAX_RECORDS)
        count(entry["missed"], at + ".missed", evidence.MAX_RECORDS)
        moment(entry["last_confirmed"], at + ".last_confirmed")
        if entry["level"] not in LEVELS:
            raise DocumentError("%s.level is not VERIFIED, CHECKED or null" % at)


# ------------------------------------------------------------------------------ this PC's own report
def assemble(found, *, product_version=None, windows=None, now=None) -> dict:
    """The Dashboard's own report of what reading.read_all found, checked (`check`)."""
    product_version = config.version() if product_version is None else product_version
    windows = windows_version() if windows is None else windows
    now = time.time() if now is None else now
    versions = []
    for entry in found["versions"]:
        body = entry.get("body")
        versions.append({"codex_version": entry["codex_version"],
                         "counted": evidence.graded(body["records"]) if body else None,
                         "refusal": entry.get("refusal"),
                         "body": body})
    document = {
        "format": FORMAT,
        "recorded_at": evidence.iso(now),
        "product_version": product_version,
        "windows": windows,
        "engine": {"current": found["engine"]["current"], "from": found["engine"]["from"]},
        "rule": RULE,
        "counting": COUNTING,
        "left_out": {key: found["left_out"][key] for key in LEFT_OUT_KEYS},
        "versions": versions,
        "note": NOTE,
    }
    check(document)
    return document


def check(document) -> bytes:
    """The own report's bytes, once it is the format exactly and nothing in it can be anything but a
    time, a version, a count, a closed word or one of the format's own sentences; DocumentError when
    it is anything else, DocumentRefused when it is larger than the project would take."""
    keys(document, TOP_KEYS, "the report")
    if (document["format"] != FORMAT or document["rule"] != RULE or document["counting"] != COUNTING
            or document["note"] != NOTE):
        raise DocumentError("the format or one of its sentences is not the format's")
    moment(document["recorded_at"], "recorded_at", required=True)
    version = document["product_version"]
    # "unknown" is what config.version says of a damaged manifest: the report of the records still stands.
    if not isinstance(version, str) or not (version == "unknown" or PRODUCT_VERSION.match(version)):
        raise DocumentError("product_version is not this product's version as a release names it")
    if document["windows"] is not None and not (isinstance(document["windows"], str)
                                                and WINDOWS.match(document["windows"])):
        raise DocumentError("windows is not Windows 10 or later as it reports itself")
    engine = document["engine"]
    keys(engine, ENGINE_KEYS, "engine")
    if not isinstance(engine["current"], str) or not evidence.VERSION.match(engine["current"]):
        raise DocumentError("engine.current is not a Codex version")
    word(engine["from"], {"watcher_report", "log"}, "engine.from")
    left = document["left_out"]
    keys(left, LEFT_OUT_KEYS, "left_out")
    for name in ("hidden", "another_route", "beyond_reach"):
        count(left[name], "left_out." + name)
    keys(left["unplaced"], tuple(str(code) for code in evidence.Unplaced), "left_out.unplaced")
    for code, many in left["unplaced"].items():
        count(many, "left_out.unplaced." + code)
    if not isinstance(document["versions"], list) or len(document["versions"]) > 64:
        raise DocumentError("versions is not a list of at most 64")
    seen = set()
    for number, entry in enumerate(document["versions"]):
        at = "versions[%d]" % number
        keys(entry, VERSION_KEYS, at)
        version = entry["codex_version"]
        if evidence.canonical_version(version) != version or version in seen:
            raise DocumentError("%s.codex_version is not a Codex version in the product's one spelling, once" % at)
        seen.add(version)
        body = entry["body"]
        if body is None:
            word(entry["refusal"], {str(DocumentRefusal.TOO_MANY_RECORDS)}, at + ".refusal")
            if entry["refusal"] is None or entry["counted"] is not None:
                raise DocumentError("%s has neither a body nor the refusal that stands for one" % at)
            continue
        if entry["refusal"] is not None:
            raise DocumentError("%s has a body and a refusal" % at)
        keys(body, BODY_KEYS, at + ".body")
        if body["codex_version"] != version or body["verdict"] not in VERDICTS:
            raise DocumentError("%s.body names another version or no verdict of the format's" % at)
        check_parts(body, at + ".body.")
        if entry["counted"] != evidence.graded(body["records"]):
            raise DocumentError("%s.counted is not what its records say by the counting rule" % at)
    raw = encode(document)
    if len(raw) > MAX_BYTES:
        raise DocumentRefused(DocumentRefusal.TOO_LARGE)
    return raw


def written(document) -> dict:
    """What the Dashboard and the diagnostics export are given of one report: its text, its SHA-256 and
    its size, and per version what the dialog says - counted, how many records, how many delivered."""
    raw = check(document)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "text": raw.decode("ascii"),
            "engine": dict(document["engine"]),
            "versions": [{"codex_version": entry["codex_version"],
                          "refusal": entry["refusal"],
                          "verdict": entry["body"]["verdict"] if entry["body"] else None,
                          "records": len(entry["body"]["records"]) if entry["body"] else None,
                          "delivered": (sum(1 for record in entry["body"]["records"] if record["delivered_at"])
                                        if entry["body"] else None),
                          **({name: entry["counted"][name] for name in COUNTED} if entry["counted"]
                             else {name: None for name in COUNTED})}
                         for entry in document["versions"]],
            "left_out": dict(document["left_out"])}
