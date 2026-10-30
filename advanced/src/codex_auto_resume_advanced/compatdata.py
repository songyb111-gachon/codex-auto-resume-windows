# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The advanced edition's compatibility data: the owner's measurement verdicts for each Codex engine, between releases.

What a release knows of the measurements is measured.py, a table fixed when it was built. A Codex that updates the day
after a release would show every capability "not measured on this Codex" until the next one, even once the owner has
measured it. So the owner's records also go out in a file of their own (v0.6.20, docs/ROADMAP.md "Compatibility data for
the advanced edition"), published by the maintainer's admin program from docs/evidence/live/ into
data/codex_compat_advanced.json on the product's main - never into the standard data
(src/codex_auto_resume/data/codex_compat.json), whose validators older releases run and must never see change.

    {"format": "codex-auto-resume-compat-advanced/1", "sequence": 1,
     "published_at": "2026-10-30T00:00:00Z", "expires_at": "2027-01-28T00:00:00Z", "min_product": "0.6.20",
     "engines": [{"version": "codex-cli 0.165.0-alpha.1.2",
                  "measurements": {"mopen": {"verdict": "pass", "recorded_at": "2026-10-29T12:06Z",
                                   "evidence": "docs/evidence/advanced/codex-cli-0.165.0-alpha.1.2/measurement-mopen.json"}}}]}

Where it comes from on an installation: the copy this release carries (BUNDLED), and the one fetched from main - only
when a person asks, at the two moments the standard data is fetched (scripts/bootstrap.ps1: -Compatibility, which the
Diagnostics refresh runs, and an update check that reached github.com), for an installation of this edition only, saved
unread to config/compat-advanced.download.json (DOWNLOAD). This module is the only thing that reads it: at the next
read it is judged whole and adopted into config/compat-advanced.json (ADOPTED) only when it is valid, unexpired and of a
higher sequence than both what is adopted and what is bundled; then the download is removed, whatever it was.

The trust rules (`overlay`), each held by advanced/tests/test_advanced_compat_data.py:

1. a fail in this build's own table (measured.MEASURED) always wins: data never turns it into a pass;
2. only the entry for the EXACT engine in force counts; every other engine's is passed over;
3. a data fail on that engine narrows - the statement warns MEASUREMENT_FAILED, as a fail in the table does;
4. a data pass on that engine stands in only where this build has no verdict for that engine (none at all, or one made
   on another engine, which is UNMEASURED today); a pass the build made there stays;
5. a document that is expired, malformed in any part, meant for a newer product, or older than what is in force is
   ignored whole - never partly - and the table alone stands, as it always did.

The hidden capabilities (registry.WAITING) are let out by the build's table alone: letting one out would widen what this
PC may arm, which data never does.
"""
from __future__ import annotations

import calendar
import json
import os
from pathlib import Path
import re
import time

from codex_auto_resume.compat.model import DocumentError, decode, parse_version

from .measured import MEASURED
from .vocabulary import Measurement, Verdict

FORMAT = "codex-auto-resume-compat-advanced/1"
BUNDLED = Path(__file__).resolve().parent / "data" / "codex_compat_advanced.json"
DOWNLOAD = "compat-advanced.download.json"        # in core's state directory (config/), as the bootstrap saves it
ADOPTED = "compat-advanced.json"
MAX_BYTES = 256 * 1024                             # the bootstrap's cap, and the standard data's
MAX_ENGINES = 64
MAX_MEASUREMENTS = 128
TOP_KEYS = frozenset({"format", "sequence", "published_at", "expires_at", "min_product", "engines"})
# The line every shipped file of the advanced tree carries near its top (tests/editions.py SENTINEL), as the catalogs carry
# it: a document may carry it, first, and only in these words.
EDITION_KEY = "_edition"
EDITION_MARK = "ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's."
ENGINE_KEYS = frozenset({"version", "measurements"})
ENTRY_KEYS = frozenset({"verdict", "recorded_at", "evidence"})
VERDICTS = (Verdict.PASS, Verdict.FAIL)
ID = re.compile(r"m[a-z0-9]{1,15}")
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
MINUTE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\dZ")
PRODUCT = re.compile(r"(\d{1,6})\.(\d{1,6})\.(\d{1,6})")
EVIDENCE = "docs/evidence/advanced/%s/measurement-%s.json"

# The parsed documents by (path, size, modified): an unchanged file is not parsed again at every read.
_SEEN = {}


class Refused(ValueError):
    """A document that is not read at all, with one closed code."""


def slug(version) -> str:
    """The folder an engine's frozen records are kept in: `codex-cli 0.165.0` is `codex-cli-0.165.0`."""
    return version.replace(" ", "-")


def evidence_path(version, measurement) -> str:
    return EVIDENCE % (slug(version), measurement)


def _moment(text, pattern=TIME, form="%Y-%m-%dT%H:%M:%SZ"):
    if not isinstance(text, str) or not pattern.fullmatch(text):
        raise Refused("invalid_time")
    try:
        return float(calendar.timegm(time.strptime(text, form)))
    except (ValueError, OverflowError):
        raise Refused("invalid_time") from None


def _product(text):
    match = PRODUCT.match(text) if isinstance(text, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def this_product():
    try:
        from codex_auto_resume import __version__
        return _product(__version__)
    except Exception:
        return None


def validate(raw, *, product=None) -> dict:
    """A document's bytes, judged whole: {"sequence", "published_at", "expires_at", "engines": {version: {Measurement:
    (Verdict, recorded_at)}}}, or Refused. Nothing is half read: one bad part refuses all of it. A measurement id this
    build does not know is passed over (a newer build's measurement), but it must still be shaped as one."""
    try:
        document = decode(raw, MAX_BYTES)
    except DocumentError as error:
        raise Refused(error.code if hasattr(error, "code") else "not_json") from None
    if not isinstance(document, dict) or set(document) - {EDITION_KEY} != TOP_KEYS:
        raise Refused("keys")
    if EDITION_KEY in document and document[EDITION_KEY] != EDITION_MARK:
        raise Refused("keys")
    if document["format"] != FORMAT:
        raise Refused("unknown_format")
    sequence = document["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 1 <= sequence <= 2 ** 31 - 1:
        raise Refused("invalid_sequence")
    published, expires = _moment(document["published_at"]), _moment(document["expires_at"])
    if expires <= published:
        raise Refused("invalid_time")
    minimum = _product(document["min_product"])
    if minimum is None or not PRODUCT.fullmatch(document["min_product"]):
        raise Refused("invalid_product")
    product = this_product() if product is None else product
    if product is None or minimum > product:
        raise Refused("newer_product")
    engines_in = document["engines"]
    if not isinstance(engines_in, list) or len(engines_in) > MAX_ENGINES:
        raise Refused("invalid_engines")
    known = {str(measurement): measurement for measurement in Measurement}
    engines = {}
    for engine in engines_in:
        if not isinstance(engine, dict) or set(engine) != ENGINE_KEYS:
            raise Refused("invalid_engine")
        version = engine["version"]
        if not isinstance(version, str) or parse_version(version) is None or version != version.strip() \
                or not version.startswith("codex-cli ") or len(version) > 60:
            raise Refused("invalid_version")
        if version in engines:
            raise Refused("duplicate_engine")
        measurements = engine["measurements"]
        if not isinstance(measurements, dict) or len(measurements) > MAX_MEASUREMENTS:
            raise Refused("invalid_measurements")
        found = {}
        for name, entry in measurements.items():
            if not isinstance(name, str) or not ID.fullmatch(name):
                raise Refused("invalid_measurement")
            if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
                raise Refused("invalid_entry")
            if entry["verdict"] not in [str(verdict) for verdict in VERDICTS]:
                raise Refused("invalid_verdict")
            recorded = _moment(entry["recorded_at"], MINUTE, "%Y-%m-%dT%H:%MZ")
            if recorded > published:
                raise Refused("invalid_time")
            if entry["evidence"] != evidence_path(version, name):
                raise Refused("invalid_evidence")
            if name in known:
                found[known[name]] = (Verdict(entry["verdict"]), recorded)
        engines[version] = found
    return {"sequence": sequence, "published_at": published, "expires_at": expires, "engines": engines}


def _read(path, *, product=None):
    """The document at `path`, validated, or None where there is none or it is refused - never a part of one."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (str(path), stat.st_size, stat.st_mtime_ns, product)
    if key in _SEEN:
        return _SEEN[key]
    try:
        if stat.st_size > MAX_BYTES:
            raise Refused("too_large")
        found = validate(Path(path).read_bytes(), product=product)
    except (OSError, Refused):
        found = None
    if len(_SEEN) > 16:
        _SEEN.clear()
    _SEEN[key] = found
    return found


def _fresh(document, now):
    return document is not None and document["published_at"] <= now + 86400 and now < document["expires_at"]


def adopt(state_dir, *, bundled=BUNDLED, now=None, product=None) -> None:
    """Judge a download the bootstrap left, if there is one: adopted (an atomic replace of ADOPTED) only when valid,
    unexpired and newer than both what is adopted and what is bundled; then removed, whatever it was."""
    folder = Path(state_dir)
    download = folder / DOWNLOAD
    if not download.is_file():
        return
    now = time.time() if now is None else now
    try:
        found = _read(download, product=product)
        floor = max([document["sequence"] for document in (_read(folder / ADOPTED, product=product),
                                                           _read(bundled, product=product)) if document] or [0])
        if _fresh(found, now) and found["sequence"] > floor:
            os.replace(download, folder / ADOPTED)
            return
    except OSError:
        pass
    try:
        download.unlink()
    except OSError:
        pass


def in_force(state_dir=None, *, bundled=BUNDLED, now=None, product=None):
    """The document in force now - the adopted one or the bundled one, whichever valid and unexpired one has the higher
    sequence - or None, where neither is: then the build's table alone stands."""
    now = time.time() if now is None else now
    if state_dir is not None:
        adopt(state_dir, bundled=bundled, now=now, product=product)
    candidates = [_read(bundled, product=product)]
    if state_dir is not None:
        candidates.append(_read(Path(state_dir) / ADOPTED, product=product))
    fresh = [document for document in candidates if _fresh(document, now)]
    return max(fresh, key=lambda document: document["sequence"]) if fresh else None


def overlay(table, document, engine) -> dict:
    """measured.MEASURED's shape, {Measurement: (Verdict, engine)}, with `document`'s verdicts for exactly `engine` laid
    over it by the trust rules (the module's 1 to 5). Pure."""
    found = dict(table) if isinstance(table, dict) else {}
    if not document or not isinstance(engine, str):
        return found
    for measurement, (verdict, _recorded) in document["engines"].get(engine, {}).items():
        built = found.get(measurement)
        built_verdict, built_on = built if isinstance(built, tuple) and len(built) == 2 else (None, None)
        if built_verdict == Verdict.FAIL:
            continue                                    # 1. a fail in the build's own table always wins
        if verdict == Verdict.FAIL:
            found[measurement] = (Verdict.FAIL, engine)  # 3. data can narrow
        elif built_verdict is None or built_on != engine:
            found[measurement] = (Verdict.PASS, engine)  # 4. a pass stands in only where the build has none here
    return found


def table_for(paths, engine, *, table=None, now=None) -> dict:
    """The one seam: what the measurements found, for the Codex `engine` in force on the installation at `paths` -
    this build's table with the data in force laid over it. A failure anywhere is the build's table alone."""
    table = MEASURED if table is None else table
    try:
        state_dir = getattr(paths, "state_dir", None) if paths is not None else None
        return overlay(table, in_force(state_dir, now=now), engine)
    except Exception:
        return dict(table)


def summary(document) -> dict:
    """What the Dashboard may say of the data in force: its sequence and dates, and how many engines it names."""
    if not document:
        return {"sequence": None}
    return {"sequence": document["sequence"], "published_at": document["published_at"],
            "expires_at": document["expires_at"], "engines": len(document["engines"])}


def dumps(document) -> str:
    """A document as the admin program writes it: two-space JSON, ASCII, keys in order, one newline at the end."""
    return json.dumps(document, indent=2, ensure_ascii=True, sort_keys=False) + "\n"
