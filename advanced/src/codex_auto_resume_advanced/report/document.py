# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The compatibility report as a file: records.py's body, in the envelope codex-compat-reporter
writes around it, held to the project's rules before anyone reads it.

The format is the maintainer's own (`codex-auto-resume-compat-evidence/1`), and the keys come in
the order the reporter writes them (its `build`), so the two programs write the same file of the
same records but for who wrote it: `recorded_by` and `reporter` name this product, its version as
the tool's, as build/community_report.py takes a report the product wrote itself. The rule and the
note are the reporter's sentences, word for word; the project replaces every sentence with its own
when it files a report anyway.

`check` is the self-check every document passes before it is shown, saved or sent: exactly the
format's keys at every level, every string a time, a version, one of the product's closed words or
one of the envelope's own fixed values, at most 500 records and at most 1 MB as written. What a
person can change - the login, or a report too big to send - is a refusal with a closed code
(`DocumentRefusal`); anything else would be a fault of this code, and is an error.

The Windows version is the one Windows reports to this process (sys.getwindowsversion), never
`platform`, which can start a console program to ask (tests/test_no_console_windows.py).
"""
from __future__ import annotations

from enum import StrEnum
import json
import re
import sys
import time

from codex_auto_resume import compat, config

from . import evidence

FORMAT = "codex-auto-resume-compat-evidence/1"
TOOL = "codex-auto-resume"
EDITION = "advanced"
# The repository a report is sent to. Its owner adds evidence with the maintainer's tool, into the
# compatibility data itself, and GitHub cannot fork a repository into the account that owns it.
REPOSITORY = "songyb111-gachon/codex-auto-resume-windows"
MAX_BYTES = 1_000_000                            # the receiving side's limit (build/community_report.py)
RECORDED_BY = "Codex Auto Resume %s (advanced edition), on a contributor's Windows machine"
# codex-compat-reporter's own sentences (codex_compat_report.py build, 1.5.0), word for word.
RULE = ("a record counts for this version only when the product's engine reports before and after it - or "
        "the version installed now - name this version and no other")
NOTE = ("Content-free: counts, states and times from this machine's own records, with no conversation text, "
        "identifiers or paths, counted only towards the Reported grade beside the version and never towards a "
        "version's tier.")
# A GitHub login (GitHub's own rule), and the names Windows keeps for devices, which no folder can
# have: the project files a report under docs/evidence/community/<login>/.
LOGIN = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}\Z")
RESERVED = frozenset({"con", "prn", "aux", "nul"} | {"com%d" % n for n in range(10)}
                     | {"lpt%d" % n for n in range(10)})
# The product's version as a release names it, and Windows' as it reports itself (10.0.26200).
PRODUCT_VERSION = re.compile(r"\A\d{1,4}\.\d{1,4}\.\d{1,4}(?:-(?:alpha|beta)(?:\.\d{1,3})?)?\Z")
WINDOWS = re.compile(r"\A10\.0\.\d{5}\Z")
ISO = re.compile(r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")

TOP_KEYS = ("format", "codex_version", "verdict", "recorded_at", "recorded_by", "reporter", "attribution",
            "local_checks", "records", "capabilities", "note")
REPORTER_KEYS = ("github_login", "tool", "tool_version", "product_version", "windows")
ATTRIBUTION_KEYS = ("rule", "window", "basis")
LOCAL_KEYS = ("reports", "first", "last", "covers")
RECORD_KEYS = ("detected_at", "delivered_at", "outcome_at", "category", "state", "reason", "turn_status",
               "gates_passed", "progress_items")
CAPABILITY_KEYS = ("confirmed", "missed", "last_confirmed", "level")
VERDICTS = ("PASS", "CHECKED", "NONE")
LEVELS = (compat.VERIFIED, compat.CHECKED, None)


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


def check_login(login) -> str:
    """`login` as a report may be filed under, or DocumentRefused."""
    if not isinstance(login, str) or not LOGIN.match(login):
        raise DocumentRefused(DocumentRefusal.LOGIN_INVALID)
    if login.casefold() in RESERVED:
        raise DocumentRefused(DocumentRefusal.LOGIN_RESERVED)
    if login.casefold() == REPOSITORY.split("/")[0].casefold():
        raise DocumentRefused(DocumentRefusal.LOGIN_OWNER)
    return login


def windows_version():
    """The Windows build this process runs on, as `10.0.26200`, or None off Windows."""
    getter = getattr(sys, "getwindowsversion", None)
    if getter is None:
        return None
    found = getter()
    return "%d.%d.%d" % (found.major, found.minor, found.build)


def assemble(body, login, *, product_version=None, windows=None, now=None) -> dict:
    """The whole report for `body` (records.read's), filed under `login`, checked (`check`)."""
    login = check_login(login)
    product_version = config.version() if product_version is None else product_version
    windows = windows_version() if windows is None else windows
    now = time.time() if now is None else now
    document = {
        "format": FORMAT,
        "codex_version": body["codex_version"],
        "verdict": body["verdict"],
        "recorded_at": evidence.iso(now),
        "recorded_by": RECORDED_BY % product_version,
        "reporter": {"github_login": login, "tool": TOOL, "tool_version": product_version,
                     "product_version": product_version, "windows": windows},
        "attribution": {"rule": RULE, "window": None, "basis": None},
        "local_checks": body["local_checks"],
        "records": body["records"],
        "capabilities": body["capabilities"],
        "note": NOTE,
    }
    check(document)
    return document


def encode(document) -> bytes:
    """The bytes a report is: two-space JSON, ASCII, one newline at the end - the reporter's, and
    the project's own (build/community_report.py encode)."""
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("ascii")


# ------------------------------------------------------------------------------ the self-check
def _keys(value, keys, where) -> None:
    if not isinstance(value, dict) or tuple(value) != tuple(keys):
        raise DocumentError("%s does not hold exactly the format's keys, in its order" % where)


def _word(value, words, where) -> None:
    if value is not None and (not isinstance(value, str) or value not in words):
        raise DocumentError("%s is not one of the product's closed words" % where)


def _time(value, where, *, required=False) -> None:
    if (value is None and required) or (value is not None and not (isinstance(value, str) and ISO.match(value))):
        raise DocumentError("%s is not a UTC time" % where)


def _count(value, where, limit=10 ** 6) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
        raise DocumentError("%s is not a count" % where)


def check(document) -> bytes:
    """The document's bytes, once it is the format exactly and nothing in it can be anything but a
    time, a version, a count or a closed word; DocumentRefused when it is more than the project
    takes, DocumentError when it is anything else."""
    _keys(document, TOP_KEYS, "the report")
    if document["format"] != FORMAT or document["verdict"] not in VERDICTS:
        raise DocumentError("the format or the verdict is not the format's")
    if evidence.canonical_version(document["codex_version"]) != document["codex_version"]:
        raise DocumentError("codex_version is not a Codex version in the product's one spelling")
    _time(document["recorded_at"], "recorded_at", required=True)
    reporter = document["reporter"]
    _keys(reporter, REPORTER_KEYS, "reporter")
    check_login(reporter["github_login"])
    version = reporter["product_version"]
    if (reporter["tool"] != TOOL or not isinstance(version, str) or not PRODUCT_VERSION.match(version)
            or reporter["tool_version"] != version or document["recorded_by"] != RECORDED_BY % version):
        raise DocumentError("the report does not name this product as its writer, by its own version")
    if not isinstance(reporter["windows"], str) or not WINDOWS.match(reporter["windows"]):
        raise DocumentError("reporter.windows is not Windows 10 or later as it reports itself")
    if document["attribution"] != {"rule": RULE, "window": None, "basis": None} or document["note"] != NOTE:
        raise DocumentError("the rule or the note is not the format's sentence")
    _keys(document["attribution"], ATTRIBUTION_KEYS, "attribution")

    checks = document["local_checks"]
    _keys(checks, LOCAL_KEYS, "local_checks")
    _count(checks["reports"], "local_checks.reports")
    _time(checks["first"], "local_checks.first")
    _time(checks["last"], "local_checks.last")
    if (not isinstance(checks["covers"], list) or len(set(checks["covers"])) != len(checks["covers"])
            or not set(checks["covers"]) <= set(evidence.REPORTABLE)):
        raise DocumentError("local_checks.covers names something that is not one of the ten capabilities")

    records = document["records"]
    if not isinstance(records, list):
        raise DocumentError("records is not a list")
    if len(records) > evidence.MAX_RECORDS:
        raise DocumentRefused(DocumentRefusal.TOO_MANY_RECORDS)
    for number, record in enumerate(records):
        where = "records[%d]" % number
        _keys(record, RECORD_KEYS, where)
        _time(record["detected_at"], where + ".detected_at", required=True)
        _time(record["delivered_at"], where + ".delivered_at")
        _time(record["outcome_at"], where + ".outcome_at")
        for field, words in (("category", evidence.CATEGORIES), ("state", evidence.STATES),
                             ("reason", evidence.REASONS), ("turn_status", evidence.TURN_STATUSES)):
            _word(record[field], words | {evidence.OTHER}, "%s.%s" % (where, field))
        _count(record["gates_passed"], where + ".gates_passed", limit=64)
        items = record["progress_items"]
        if items is not None:
            _keys(items, evidence.PROGRESS, where + ".progress_items")
            for kind, many in items.items():
                _count(many, "%s.progress_items.%s" % (where, kind))

    capabilities = document["capabilities"]
    _keys(capabilities, evidence.REPORTABLE, "capabilities")
    for name, entry in capabilities.items():
        where = "capabilities." + name
        _keys(entry, CAPABILITY_KEYS, where)
        _count(entry["confirmed"], where + ".confirmed", evidence.MAX_RECORDS)
        _count(entry["missed"], where + ".missed", evidence.MAX_RECORDS)
        _time(entry["last_confirmed"], where + ".last_confirmed")
        if entry["level"] not in LEVELS:
            raise DocumentError("%s.level is not VERIFIED, CHECKED or null" % where)

    raw = encode(document)
    if len(raw) > MAX_BYTES:
        raise DocumentRefused(DocumentRefusal.TOO_LARGE)
    return raw
