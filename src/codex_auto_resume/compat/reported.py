"""Reported: what other people's filed reports add up to, per Codex version. Read, never acted on.

Reported is a grade of its own beside the ladder - verified, checked, compatible, failed here -
and never on it (docs/ROADMAP.md, "Compatibility reports from others"). A report someone else
sends is kept in docs/evidence/community/<login>/ and never in the compatibility data. What this
module reads is only their counts per version, from a file of their own that each release
carries: data/reported.json, written from docs/evidence/community/index.json by
build/community_report.py whenever a report is filed - by .github/workflows/community-file.yml or by
the maintainer's tool - and held equal to it by tests/test_reported_data.py.

What keeps it from deciding anything is structure, not care:

* it is a file of its own with a format of its own. The registry's validator never sees it, and
  the registry file on main carries no counts, so no installed release reads them either;
* nothing that decides imports this module. tests/test_reported_isolation.py holds that only
  compat/views.py may, and scans the modules that decide for its words;
* a bad file only makes Reported read `rejected`. It can never refuse the registry, and no
  request fetches it: it arrives with a release, and the refresh a person asks for still
  fetches the compatibility data and nothing else.

Counts, not machines: the path rule allows one report per GitHub login per Codex version, so
`reports` is a number of reports. Each report counts as worked, failed, neither, or both at
once, so worked + failed - both + neither = reports.
"""
from __future__ import annotations

from pathlib import Path

from ..domain.vocabulary import BundledState, ReportedState
from .files import _read_capped, _stamp
from .model import DocumentError, decode, parse_version, safe_version

FORMAT = "codex-auto-resume-reported/1"
BUNDLED = Path(__file__).resolve().parent.parent / "data" / "reported.json"
# 500 versions of five small counts each is under 60 KiB; the cap is checked before parsing.
MAX_BYTES = 128 * 1024
MAX_VERSIONS = 500
MAX_COUNT = 100_000
MAX_COMMENT_LINES, MAX_COMMENT_CHARS = 40, 200
COUNTS = ("reports", "worked", "failed", "neither", "both")
ENTRY_KEYS = frozenset(("version",) + COUNTS)
TOP_KEYS = frozenset(("_comment", "format", "versions"))
STATES = tuple(ReportedState)
PREFIX = "codex-cli "


# ------------------------------------------------------------------------------ the file
def parse(raw) -> dict:
    """{version: {count: int}} from the file's bytes, or DocumentError. Refused whole: a
    duplicate key, a number that is not a count, or counts that do not add up refuse all of it."""
    document = decode(raw, MAX_BYTES)
    if not isinstance(document, dict):
        raise DocumentError("not_an_object")
    if document.get("format") != FORMAT:
        raise DocumentError("unknown_format")
    if not set(document) <= TOP_KEYS or "versions" not in document:
        raise DocumentError("invalid_field")
    comment = document.get("_comment", [])
    if (not isinstance(comment, list) or len(comment) > MAX_COMMENT_LINES
            or not all(isinstance(line, str) and len(line) <= MAX_COMMENT_CHARS for line in comment)):
        raise DocumentError("invalid_field")
    entries = document["versions"]
    if not isinstance(entries, list):
        raise DocumentError("invalid_field")
    if len(entries) > MAX_VERSIONS:
        raise DocumentError("too_many")
    table = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise DocumentError("invalid_field")
        version = entry["version"]
        if safe_version(version) is None or parse_version(version) is None or version in table:
            raise DocumentError("invalid_field")
        counts = {}
        for name in COUNTS:
            value = entry[name]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_COUNT:
                raise DocumentError("invalid_field")
            counts[name] = value
        reports, worked, failed, neither, both = (counts[name] for name in COUNTS)
        # Every report is in exactly one of worked-only, failed-only, both, or neither.
        if (reports < 1 or max(worked, failed, neither) > reports
                or both != worked + failed + neither - reports or not 0 <= both <= min(worked, failed)):
            raise DocumentError("invalid_field")
        table[version] = counts
    return table


_held = {}      # str(path) -> (stamp, (standing, table))


def read(path=None):
    """(standing, table): standing is `ok`, `missing` or `rejected`, as the bundled registry's is.

    Parsed once per version of the file: a reader that asks on every poll pays a stat, not a
    parse, so the v0.6.9 lag work does not come back through here."""
    path = BUNDLED if path is None else path
    key, stamp = str(path), _stamp(path)
    if stamp is None:
        return BundledState.MISSING, {}
    held = _held.get(key)
    if held is not None and held[0] == stamp:
        return held[1]
    try:
        result = (BundledState.OK, parse(_read_capped(path, MAX_BYTES)))
    except DocumentError:
        result = (BundledState.REJECTED, {})
    _held[key] = (stamp, result)
    return result


# ------------------------------------------------------------------------------ one version
def _named(version):
    """`codex-cli X` for an engine version given with or without its prefix, or None."""
    if not isinstance(version, str):
        return None
    version = version.strip()
    if not version.startswith(PREFIX):
        version = PREFIX + version
    return version if safe_version(version) and parse_version(version) else None


def lookup(version, *, path=None) -> dict:
    """{"state", "reports", "worked", "failed", "neither", "both"} for one engine version.

    Always the same keys. The counts are 0 unless the state is `reported`, and they are counts
    of reports, never a tier: nothing here is a word a capability can have."""
    answer = {"state": ReportedState.UNAVAILABLE, **dict.fromkeys(COUNTS, 0)}
    name = _named(version)
    if name is None:
        return answer
    standing, table = read(path)
    if standing == BundledState.MISSING:
        return answer
    if standing == BundledState.REJECTED:
        return dict(answer, state=ReportedState.REJECTED)
    counts = table.get(name)
    if counts is None:
        return dict(answer, state=ReportedState.NONE_YET)
    return dict(answer, state=ReportedState.REPORTED, **counts)
