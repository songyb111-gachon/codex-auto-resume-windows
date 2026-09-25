"""A compatibility report from someone else, read as the untrusted document it is.

Three readers share this file: the pull-request check that judges a report as it arrives
(build/community_check.py, which .github/workflows/community-report.yml runs from main's own
copy), the tests that hold the reports already filed (tests/test_reported_data.py), and the
truth table the maintainer's tool runs too (tests/fixtures/reported_cases.json). It is not
shipped: build/ never enters a release (build/make_release.py), so nothing here runs on anyone's
machine, and it has no network code.

The format is `codex-auto-resume-compat-evidence/1`, the maintainer's own evidence format, as
codex-compat-reporter writes it. A report is refused whole for anything outside it: a missing or
unknown key, a word outside the product's own vocabularies, a time that cannot be true, a count
that cannot be, or a fingerprint that is not plausible. What it concludes - each capability's
level and the verdict - is not refused but worked out again from its records (`recompute`), and
the filed copy holds that recomputation with our own sentences in place of the sender's
(`filed_copy`), so a hand-edited conclusion does not survive and no sentence is shown as written.

The fingerprint. A report names the setup that measured: the Codex version the product read from
the engine (`codex_version`), and the product's, the reporter's and Windows' own versions
(`reporter.product_version`, `.tool_version`, `.windows`). Each has to be one that could have
written this file: a Codex version in the grammar the product itself names engines by; a product
version that is one of this repository's releases, v0.6.0 or later, published before the report
was written; a plain release number for the reporter; Windows 10 or later. It names the setup, not
the binary. The format carries no digest of codex.exe, and the product's own digest is of the
path, which holds the Windows user name and never leaves the machine. A SHA-256 of codex.exe's
bytes - the same on every machine with that build, and naming nobody - is the stronger check; it
needs a new format version in both programs, and docs/ROADMAP.md records it as the next step.

Counting (docs/ROADMAP.md): a report is worked when at least one delivered record ended in
`recovered`; failed when at least one delivered record ended in `recovery_turn_failed`, `failed`
or `terminal_failure`; neither when no delivered record ended in either, which includes a report
with nothing delivered; and both when it is worked and failed at once. Only filed reports count,
and a report's own levels and verdict never do.
"""
from __future__ import annotations

import calendar
import copy
import json
from pathlib import Path
import re
import sys
import time

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from codex_auto_resume import compat, machine  # noqa: E402
from codex_auto_resume.compat import reported as product_reported  # noqa: E402
from codex_auto_resume.domain import vocabulary as words  # noqa: E402

FORMAT = "codex-auto-resume-compat-evidence/1"
INDEX_FORMAT = "codex-auto-resume-compat-community/1"
COMMUNITY = "docs/evidence/community"
MAX_BYTES, MAX_RECORDS = 1_000_000, 500
MAX_COUNT = 10 ** 6
MAX_PROSE = 1000
SKEW = 86400                                     # a clock a day ahead is still believed
# Nothing a report can say happened before the project's first commit, 2026-09-06.
FLOOR = calendar.timegm((2026, 9, 6, 0, 0, 0))

OTHER = "other"                                  # what the reporter writes for a word it does not know
CATEGORIES = frozenset(words.FailureCategory) | {OTHER}
STATES = frozenset(words.RecordState) | {OTHER}
REASONS = frozenset(words.ReasonCode) | {OTHER}
TURN_STATUSES = frozenset(words.TurnStatus) | {OTHER}
PROGRESS = ("agentMessage", "commandExecution", "fileChange", "mcpToolCall")
GATES = len(words.GateName)                       # a record cannot pass more gates than there are

# The ten capabilities a recovery a record shows can exercise: a report names these and no
# others. The watcher judges sixteen; the other six are not something a record can show.
REPORTABLE = ("engine_present", "exact_thread_recovery", "loaded_state_detection",
              "outcome_observation", "projection_freshness", "recovery_turn_tracking",
              "thread_eligibility", "usage_limit_detection", "usage_probe", "usage_reset_hint")
GATE = tuple(compat.SEND_GATE)
# An outcome the product observed. `outcome_unverified` says it could not observe one.
OUTCOMES = frozenset(machine.OUTCOMES) - {"outcome_unverified"}
WORKED = frozenset({"recovered"})
FAILED = frozenset({"recovery_turn_failed", "failed", "terminal_failure"})
VERIFIED, CHECKED = compat.VERIFIED, compat.CHECKED
LEVELS = (VERIFIED, CHECKED, None)
VERDICTS = ("PASS", "CHECKED", "NONE")

TOP_KEYS = frozenset({"format", "codex_version", "verdict", "recorded_at", "recorded_by", "reporter",
                      "attribution", "local_checks", "records", "capabilities", "note"})
REPORTER_KEYS = frozenset({"github_login", "tool", "tool_version", "product_version", "windows"})
ATTRIBUTION_KEYS = frozenset({"rule", "window", "basis"})
LOCAL_KEYS = frozenset({"reports", "first", "last", "covers"})
RECORD_KEYS = frozenset({"detected_at", "delivered_at", "outcome_at", "category", "state", "reason",
                         "turn_status", "gates_passed", "progress_items"})
CAPABILITY_KEYS = frozenset({"confirmed", "missed", "last_confirmed", "level"})

LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
VERSION = re.compile(r"codex-cli \d[0-9A-Za-z.\-]{0,39}")
TOOL = "codex-compat-reporter"
TOOL_VERSION = re.compile(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})")
PRODUCT = re.compile(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-(?:alpha|beta))?")
FIRST_PRODUCT = (0, 6, 0)                        # the first release whose state the reporter reads
WINDOWS = re.compile(r"10\.0\.(\d{5})")
FIRST_WINDOWS_BUILD = 10240                      # Windows 10's first build
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

# The sentences a filed report carries: ours, never the sender's (codex-compat-admin's OURS).
OURS = {
    "recorded_by": "a contributor's Windows machine, through %s %s",
    "rule": "a record counts for this version only when the product's engine reports before and "
            "after it - or the version installed now - name this version and no other",
    "note": "Reported by someone other than the maintainer: counts, states and times from their "
            "own machine, kept apart from this project's own evidence. It does not raise any "
            "version's tier and does not change what the product allows itself to do.",
}

COUNTS_COMMENT = [
    "Reported: other people's filed compatibility reports, counted per Codex version.",
    "src/codex_auto_resume/compat/reported.py reads this file only to show the counts. Nothing",
    "that decides reads it, and it is not the compatibility data: codex_compat.json carries",
    "no counts. Written from docs/evidence/community/index.json by the maintainer's tool, and",
    "tests/test_reported_data.py holds it equal to that index. Each report counts as worked,",
    "failed, neither, or both at once, so worked + failed - both + neither = reports: one",
    "report per GitHub login per Codex version, so these are reports, not machines.",
]


# ------------------------------------------------------------------------------ small readers
def moment(value):
    """Seconds since the epoch for `2026-09-22T17:27:30Z`, or None for anything else."""
    if not isinstance(value, str) or not TIME.fullmatch(value):
        return None
    try:
        return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, OverflowError):
        return None


def iso(seconds) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def is_count(value, limit=MAX_COUNT) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and 0 <= value <= limit


def file_name(version: str) -> str:
    """codex-cli-<version>.json, the one name a report for that version has."""
    return "codex-cli-%s.json" % version[len("codex-cli "):]


def canonical_path(login: str, version: str) -> str:
    return "%s/%s/%s" % (COMMUNITY, login, file_name(version))


def engine_version(value) -> bool:
    """A Codex version the product itself names engines by, and safe as a file and branch name."""
    return (isinstance(value, str) and bool(VERSION.fullmatch(value))
            and compat.parse_version(value) is not None and ".." not in value
            and not value.endswith((".", ".lock")))


def product_key(value):
    found = PRODUCT.fullmatch(value) if isinstance(value, str) else None
    return tuple(int(part) for part in found.groups()) if found else None


# ------------------------------------------------------------------------------ the report
class _Reading:
    def __init__(self, report, now):
        self.report, self.now, self.refusals = report, now, []
        self.written = None

    def refuse(self, text):
        self.refusals.append(text)

    def when(self, value, field, *, required=False):
        """A time the report states: well formed, not before the project, not after it was written."""
        if value is None:
            if required:
                self.refuse("%s is missing" % field)
            return None
        seconds = moment(value)
        if seconds is None:
            self.refuse("%s is not a UTC time like 2026-09-22T17:27:30Z" % field)
            return None
        if seconds < FLOOR:
            self.refuse("%s is before this project existed" % field)
        elif seconds > self.now + SKEW:
            self.refuse("%s is in the future" % field)
        elif self.written is not None and seconds > self.written:
            self.refuse("%s is after the report was written" % field)
        return seconds

    def prose(self, value, field):
        if not isinstance(value, str) or len(value) > MAX_PROSE:
            self.refuse("%s is not a sentence of at most %d characters" % (field, MAX_PROSE))


def inspect(raw, *, author=None, now=None, releases=None):
    """(report, refusals, recomputed) for a file's bytes.

    `refusals` non-empty means the file is refused; each is fixed text naming a field of the
    format, never a value from the file. `recomputed` lists what `recompute` changes: reported,
    not refused. `author` is the login that opened the pull request, when there is one.
    `releases` maps this repository's tags to when each was made; None skips that one rule.
    """
    now = time.time() if now is None else now
    if not isinstance(raw, (bytes, bytearray)):
        return None, ["the file is not bytes"], []
    raw = bytes(raw)
    if len(raw) > MAX_BYTES:
        return None, ["the file is larger than 1 MB"], []
    if raw.startswith(b"\xef\xbb\xbf"):
        return None, ["the file starts with a byte-order mark"], []
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, ["the file is not UTF-8"], []
    try:
        report = compat.decode(raw, MAX_BYTES)
    except compat.DocumentError as error:
        return None, ["the file is not JSON the product would read: %s" % error.code], []
    if not isinstance(report, dict):
        return None, ["the file is not one JSON object"], []
    missing, extra = sorted(TOP_KEYS - set(report)), set(report) - TOP_KEYS
    if missing or extra:
        said = (["missing " + ", ".join(missing)] if missing else []) + (
            ["%d the format does not have" % len(extra)] if extra else [])
        return report, ["keys: " + "; ".join(said)], []

    reading = _Reading(report, now)
    _envelope(reading, author, releases)
    _local_checks(reading)
    records = _records(reading)
    _capabilities(reading, records)
    if reading.refusals:
        return report, reading.refusals, []
    return report, [], changes(report)


def _envelope(reading, author, releases):
    report, refuse = reading.report, reading.refuse
    if report["format"] != FORMAT:
        refuse("format is not %s" % FORMAT)
    if not engine_version(report["codex_version"]):
        refuse("codex_version is not a Codex version the product names engines by")
    if report["verdict"] not in VERDICTS:
        refuse("verdict is not PASS, CHECKED or NONE")
    reading.written = None
    written = reading.when(report["recorded_at"], "recorded_at", required=True)
    reading.written = written
    reading.prose(report["recorded_by"], "recorded_by")
    reading.prose(report["note"], "note")

    attribution = report["attribution"]
    if not isinstance(attribution, dict) or set(attribution) != ATTRIBUTION_KEYS:
        refuse("attribution: its keys are not basis, rule, window")
    else:
        reading.prose(attribution["rule"], "attribution.rule")
        if attribution["window"] is not None or attribution["basis"] is not None:
            refuse("attribution.window and .basis are for a window set by hand; a report sets neither")

    sender = report["reporter"]
    if not isinstance(sender, dict) or set(sender) != REPORTER_KEYS:
        refuse("reporter: its keys are not " + ", ".join(sorted(REPORTER_KEYS)))
        return
    login = sender["github_login"]
    if not isinstance(login, str) or not LOGIN.fullmatch(login):
        refuse("reporter.github_login is not a GitHub login")
    elif author is not None and login != author:
        refuse("reporter.github_login is not the login that opened the pull request")
    # The fingerprint: the setup that measured, each part one that could have written this file.
    if sender["tool"] != TOOL:
        refuse("reporter.tool is not %s" % TOOL)
    tool = TOOL_VERSION.fullmatch(sender["tool_version"]) if isinstance(sender["tool_version"], str) else None
    if not tool or tuple(int(part) for part in tool.groups()) < (1, 0, 0):
        refuse("reporter.tool_version is not a release of %s" % TOOL)
    product = product_key(sender["product_version"])
    if product is None or product < FIRST_PRODUCT:
        refuse("reporter.product_version is not a release of this product, v0.6.0 or later")
    elif releases is not None:
        made = releases.get("v" + sender["product_version"])
        if made is None:
            refuse("reporter.product_version is not one of this repository's releases")
        elif written is not None and made > written + SKEW:
            refuse("reporter.product_version was not released yet when the report was written")
    build = WINDOWS.fullmatch(sender["windows"]) if isinstance(sender["windows"], str) else None
    if not build or int(build.group(1)) < FIRST_WINDOWS_BUILD:
        refuse("reporter.windows is not Windows 10 or later (10.0.NNNNN)")


def _local_checks(reading):
    checks, refuse = reading.report["local_checks"], reading.refuse
    if not isinstance(checks, dict) or set(checks) != LOCAL_KEYS:
        refuse("local_checks: its keys are not covers, first, last, reports")
        return
    if not is_count(checks["reports"]):
        refuse("local_checks.reports is not a count")
    first = reading.when(checks["first"], "local_checks.first")
    last = reading.when(checks["last"], "local_checks.last")
    passed = checks["reports"] != 0 if is_count(checks["reports"]) else None
    if ((passed is not None and passed == (checks["first"] is None))
            or (checks["first"] is None) != (checks["last"] is None)):
        refuse("local_checks: first and last are set exactly when a check passed")
    if first is not None and last is not None and first > last:
        refuse("local_checks: first is after last")
    covers = checks["covers"]
    if (not isinstance(covers, list) or not all(isinstance(name, str) for name in covers)
            or len(set(covers)) != len(covers) or not set(covers) <= set(REPORTABLE)):
        refuse("local_checks.covers names something that is not one of the ten capabilities, or twice")


def _records(reading):
    records, refuse = reading.report["records"], reading.refuse
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        refuse("records is not a list of at most %d" % MAX_RECORDS)
        return []
    for number, record in enumerate(records, 1):
        where = "records[%d]" % number
        if not isinstance(record, dict) or set(record) != RECORD_KEYS:
            refuse("%s: its keys are not %s" % (where, ", ".join(sorted(RECORD_KEYS))))
            continue
        found = reading.when(record["detected_at"], where + ".detected_at", required=True)
        delivered = reading.when(record["delivered_at"], where + ".delivered_at")
        ended = reading.when(record["outcome_at"], where + ".outcome_at")
        for earlier, later, names in ((found, delivered, "detected_at, delivered_at"),
                                      (delivered, ended, "delivered_at, outcome_at"),
                                      (found, ended, "detected_at, outcome_at")):
            if earlier is not None and later is not None and later < earlier:
                refuse("%s: %s are out of order" % (where, names))
        for field, vocabulary in (("category", CATEGORIES), ("state", STATES),
                                  ("reason", REASONS), ("turn_status", TURN_STATUSES)):
            value = record[field]
            if value is not None and (not isinstance(value, str) or value not in vocabulary):
                refuse("%s.%s is not one of the product's own words" % (where, field))
        if not is_count(record["gates_passed"], GATES):
            refuse("%s.gates_passed is not a count of the product's %d gates" % (where, GATES))
        items = record["progress_items"]
        if items is not None and (not isinstance(items, dict) or not set(items) <= set(PROGRESS)
                                  or not all(is_count(many) for many in items.values())):
            refuse("%s.progress_items is not a count of what the product counts" % where)
    return records


def _capabilities(reading, records):
    capabilities, refuse = reading.report["capabilities"], reading.refuse
    if not isinstance(capabilities, dict) or set(capabilities) != set(REPORTABLE):
        refuse("capabilities: its keys are not the ten capabilities a report names")
        return
    for name in REPORTABLE:
        entry = capabilities[name]
        where = "capabilities." + name
        if not isinstance(entry, dict) or set(entry) != CAPABILITY_KEYS:
            refuse("%s: its keys are not %s" % (where, ", ".join(sorted(CAPABILITY_KEYS))))
            continue
        counted = [entry[field] for field in ("confirmed", "missed")]
        if not all(is_count(value, MAX_RECORDS) for value in counted):
            refuse("%s: confirmed and missed are not counts" % where)
        elif sum(counted) > len(records):
            refuse("%s counts more judgements than the report has records" % where)
        reading.when(entry["last_confirmed"], where + ".last_confirmed")
        if entry["level"] not in LEVELS:
            refuse("%s.level is not VERIFIED, CHECKED or null" % where)


# ------------------------------------------------------------------------------ recomputed
def recompute(report) -> dict:
    """The report with each level and the verdict worked out again from its own records.

    It only ever lowers: a VERIFIED the records do not support (confirmed, nothing missed, a
    delivered recovery seen to an outcome, and the two gate capabilities verified with it)
    becomes CHECKED where the local checks cover it and null where they do not; a CHECKED the
    local checks do not cover becomes null. Nothing is raised, and it is idempotent."""
    kept = copy.deepcopy(report)
    covers = set(report["local_checks"]["covers"])
    delivered = any(record["delivered_at"] and record["state"] in OUTCOMES for record in report["records"])

    def fallback(name):
        return CHECKED if name in covers else None

    levels = {}
    for name, entry in report["capabilities"].items():
        level = entry["level"]
        if level == VERIFIED and not (entry["confirmed"] and not entry["missed"] and delivered):
            level = fallback(name)
        if level == CHECKED and name not in covers:
            level = None
        levels[name] = level
    if VERIFIED in levels.values() and not all(levels.get(name) == VERIFIED for name in GATE):
        levels = {name: fallback(name) if level == VERIFIED else level for name, level in levels.items()}
    for name, level in levels.items():
        kept["capabilities"][name]["level"] = level
    present = [level for level in levels.values() if level]
    kept["verdict"] = "PASS" if VERIFIED in present else (CHECKED if present else "NONE")
    return kept


def changes(report) -> list:
    """What recompute() changes, as fixed text naming only fields of the format."""
    again = recompute(report)
    said = ["capabilities.%s: %s is more than its records show; kept as %s"
            % (name, report["capabilities"][name]["level"], again["capabilities"][name]["level"] or "null")
            for name in REPORTABLE if again["capabilities"][name]["level"] != report["capabilities"][name]["level"]]
    if again["verdict"] != report["verdict"]:
        said.append("verdict: %s is more than its records show; kept as %s" % (report["verdict"], again["verdict"]))
    return said


def filed_copy(report) -> dict:
    """The file as it is kept: recomputed, with every sentence in it one of ours."""
    kept = recompute(report)
    kept["recorded_by"] = OURS["recorded_by"] % (report["reporter"]["tool"], report["reporter"]["tool_version"])
    kept["attribution"]["rule"] = OURS["rule"]
    kept["note"] = OURS["note"]
    return kept


def encode(report) -> bytes:
    """The bytes a filed report has: two-space JSON, ASCII, one newline at the end."""
    return (json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode("ascii")


# ------------------------------------------------------------------------------ counted
def graded(report) -> dict:
    """What one report says, in the two words the Reported grade counts (docs/ROADMAP.md).

    Only delivered records speak. Neither is neither of them - nothing delivered, or every
    delivered record ended some other way - and both is both at once, shown, not resolved."""
    delivered = [record for record in report["records"] if record["delivered_at"]]
    worked = any(record["state"] in WORKED for record in delivered)
    failed = any(record["state"] in FAILED for record in delivered)
    return {"worked": worked, "failed": failed, "neither": not (worked or failed), "both": worked and failed}


def tally(graded_reports) -> dict:
    """reports, worked, failed, neither and both, from what each report said."""
    said = list(graded_reports)
    return {"reports": len(said), **{word: sum(1 for one in said if one[word])
                                     for word in ("worked", "failed", "neither", "both")}}


def index_entry(path, report) -> dict:
    """One filed report as the index lists it, from its recomputed reading."""
    again = recompute(report)
    levels = [entry["level"] for entry in again["capabilities"].values() if entry["level"]]
    says = graded(report)
    return {"reported_by": report["reporter"]["github_login"], "path": path,
            "recorded_at": report["recorded_at"], "verdict": again["verdict"],
            "records": len(report["records"]),
            "delivered": sum(1 for record in report["records"] if record["delivered_at"]),
            "verified": levels.count(VERIFIED), "checked": levels.count(CHECKED),
            "product_version": report["reporter"]["product_version"],
            "worked": says["worked"], "failed": says["failed"]}


def build_index(reports, *, generated_at=None) -> dict:
    """docs/evidence/community/index.json for the filed reports, {path: report}.

    A listing, not a claim: the Reported grade and nothing else."""
    versions = {}
    for path, report in sorted(reports.items()):
        versions.setdefault(report["codex_version"], []).append(index_entry(path, report))
    listing = {}
    for version, entries in sorted(versions.items()):
        listing[version] = {"reported": tally(graded_of_entry(entry) for entry in entries),
                            "reports": entries}
    return {"format": INDEX_FORMAT,
            "generated_at": iso(time.time() if generated_at is None else generated_at),
            "grade": "REPORTED",
            "grants": "nothing: Reported is a grade of its own beside VERIFIED, CHECKED and "
                      "COMPATIBLE and never becomes one of them; no version's tier comes from a "
                      "report, and a version whose own evidence says nothing stays compatible "
                      "however many arrive",
            "versions": listing}


def graded_of_entry(entry) -> dict:
    worked, failed = bool(entry["worked"]), bool(entry["failed"])
    return {"worked": worked, "failed": failed, "neither": not (worked or failed), "both": worked and failed}


def project(index) -> dict:
    """The counts file a release carries (src/codex_auto_resume/data/reported.json)."""
    return {"_comment": list(COUNTS_COMMENT), "format": product_reported.FORMAT,
            "versions": [dict(version=version, **{name: held["reported"][name]
                                                  for name in product_reported.COUNTS})
                         for version, held in sorted((index or {}).get("versions", {}).items())]}
