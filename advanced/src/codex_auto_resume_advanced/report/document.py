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

import re
import time

from codex_auto_resume import config
from codex_auto_resume.ownreport import evidence
# The body's self-check, its refusals and errors, the reporter's rule sentence and the bytes a report is, as every
# report of this PC's records has them (v0.6.19: core's since the Dashboard's own report).
from codex_auto_resume.ownreport.document import (ISO, MAX_BYTES, PRODUCT_VERSION, RULE, WINDOWS,  # noqa: F401
                                                  CAPABILITY_KEYS, DocumentError, DocumentRefusal, DocumentRefused,
                                                  LEVELS, LOCAL_KEYS, RECORD_KEYS, VERDICTS, check_parts, encode,
                                                  keys as _keys, moment as _time, windows_version)

FORMAT = "codex-auto-resume-compat-evidence/1"
TOOL = "codex-auto-resume"
EDITION = "advanced"
# The repository a report is sent to. Its owner adds evidence with the maintainer's tool, into the
# compatibility data itself, and GitHub cannot fork a repository into the account that owns it.
REPOSITORY = "songyb111-gachon/codex-auto-resume-windows"
RECORDED_BY = "Codex Auto Resume %s (advanced edition), on a contributor's Windows machine"
NOTE = ("Content-free: counts, states and times from this machine's own records, with no conversation text, "
        "identifiers or paths, counted only towards the Reported grade beside the version and never towards a "
        "version's tier.")
# A GitHub login (GitHub's own rule), and the names Windows keeps for devices, which no folder can
# have: the project files a report under docs/evidence/community/<login>/.
LOGIN = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}\Z")
RESERVED = frozenset({"con", "prn", "aux", "nul"} | {"com%d" % n for n in range(10)}
                     | {"lpt%d" % n for n in range(10)})
TOP_KEYS = ("format", "codex_version", "verdict", "recorded_at", "recorded_by", "reporter", "attribution",
            "local_checks", "records", "capabilities", "note")
REPORTER_KEYS = ("github_login", "tool", "tool_version", "product_version", "windows")
ATTRIBUTION_KEYS = ("rule", "window", "basis")


def check_login(login) -> str:
    """`login` as a report may be filed under, or DocumentRefused."""
    if not isinstance(login, str) or not LOGIN.match(login):
        raise DocumentRefused(DocumentRefusal.LOGIN_INVALID)
    if login.casefold() in RESERVED:
        raise DocumentRefused(DocumentRefusal.LOGIN_RESERVED)
    if login.casefold() == REPOSITORY.split("/")[0].casefold():
        raise DocumentRefused(DocumentRefusal.LOGIN_OWNER)
    return login


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


# ------------------------------------------------------------------------------ the self-check
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

    check_parts(document)

    raw = encode(document)
    if len(raw) > MAX_BYTES:
        raise DocumentRefused(DocumentRefusal.TOO_LARGE)
    return raw
