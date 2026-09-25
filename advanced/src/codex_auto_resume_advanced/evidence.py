# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""One content-free record per measurement, in the live-acceptance envelope, in docs/evidence/live/.

The measurement harness (measure.py) writes what it observed here, in the same JSON envelope
`scripts/live_evidence.py` reads and holds every committed file to: a format tag, when it was
recorded, which product build and which Codex and Windows it ran against, and the observation.
The tag is this harness's own (`MEASUREMENT_FORMAT`), so the validator does not count these
towards release acceptance and does not know their steps - but it still refuses any of them that
names a person, a path or a conversation, and so does this writer, first, by construction: a
record holds booleans, counts, the engine's own closed words, verdicts, and ids only as the
aliases the diagnostics export writes. Anything else is refused rather than written, so a
measurement can never be the thing that publishes what the whole product is careful to keep in.

The directory is the source tree's `docs/evidence/live/`, because the owner runs the harness
from the source on a throwaway conversation, never against the real install (agents never do).
An installed copy has no such directory, and the writer says so rather than inventing one.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from codex_auto_resume import failures, machine
from codex_auto_resume.diagnostics import EMAIL_RE, KEY_RE, PATH_RE, UUID_RE

from .vocabulary import Measurement, Verdict

# The same tag scripts/live_evidence.py skips these files by; tests/test_advanced_measure.py
# keeps the two spellings identical, so neither can move without the other.
MEASUREMENT_FORMAT = "codex-auto-resume-measurement/1"
# Where the records go, from the source tree: <repo>/docs/evidence/live/. This module sits at
# advanced/src/codex_auto_resume_advanced/evidence.py, four parents below the repository root.
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[3] / "docs" / "evidence" / "live"

# An id is recorded only as the alias the diagnostics export writes: a prefix and eight hex.
ALIAS_RE = re.compile(r"^(?:thread|record|chain)-[0-9a-f]{8}$")
# The closed words a measurement's observation may hold besides booleans and counts: the engine's
# own turn statuses and failure categories, and this harness's verdicts. A word outside these is
# free text, and free text is refused.
CLOSED_WORDS = (frozenset(str(word) for word in machine.TURN_STATUSES)
                | frozenset(str(word) for word in failures.CATEGORIES)
                | frozenset(str(word) for word in Verdict))


class EvidenceError(RuntimeError):
    """A record that may not be written, or a directory it may not be written to. A static
    reason only - never the value that was refused."""


def _content_free(value) -> bool:
    """Whether one observed value is one a committed record may hold: a boolean, a count, an
    alias, or one of the engine's own closed words. A free string is not, whatever it says."""
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return bool(ALIAS_RE.match(value)) or value in CLOSED_WORDS
    return False


def _no_content(text: str) -> bool:
    """Whether a string that reaches the envelope's own fields carries nothing identifying: no
    conversation id, no record id or other long hex, no path, no e-mail. The version fields and
    the note pass through here."""
    return not (UUID_RE.search(text) or KEY_RE.search(text) or PATH_RE.search(text)
                or EMAIL_RE.search(text) or "\\" in text)


def build(measurement, verdict, observed, *, product_version, codex_version, windows_build,
          recorded_at, note=None) -> dict:
    """The record for one measurement, refused unless every part of it is content-free.

    `observed` is what the probe saw, in closed words, counts, booleans and aliases; `verdict`
    is pass, fail or blocked; a verdict that is not a pass needs a `note` saying what happened
    instead, as the live-acceptance schema asks."""
    measurement = Measurement(measurement)
    verdict = Verdict(verdict)
    if not isinstance(observed, dict):
        raise EvidenceError("an observation is an object of what was seen")
    for key, value in observed.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", key):
            raise EvidenceError("an observed field's name is a plain word")
        if not _content_free(value):
            raise EvidenceError("an observed value is not a boolean, a count, an alias or a "
                                "closed word; the record holds nothing else")
    record = {"format": MEASUREMENT_FORMAT, "step": str(measurement), "verdict": str(verdict),
              "recorded_at": str(recorded_at), "product_version": str(product_version),
              "codex_version": str(codex_version), "windows_build": str(windows_build),
              "observed": dict(observed)}
    if verdict != Verdict.PASS and not (isinstance(note, str) and note.strip()):
        raise EvidenceError("a verdict that is not a pass needs a note saying what happened")
    if note is not None:
        if not isinstance(note, str):
            raise EvidenceError("a note is text")
        record["note"] = note
    for field in ("recorded_at", "product_version", "codex_version", "windows_build",
                  record.get("note") and "note"):
        if field and not _no_content(str(record[field])):
            raise EvidenceError("a field holds something that identifies a person, a path or a "
                                "conversation; a record never does")
    return record


def path_for(measurement, *, directory=None) -> Path:
    """The one file a measurement's record is written to. One per measurement, overwritten on a
    re-run, so a later reading of a Codex never sits beside an older one that disagrees."""
    directory = DEFAULT_DIRECTORY if directory is None else Path(directory)
    return directory / ("measurement-%s.json" % Measurement(measurement))


def write(record, *, directory=None) -> Path:
    """Write one record. The directory has to be there already (the source tree's), so the
    harness run from an installed copy, which has none, is refused rather than inventing one."""
    directory = DEFAULT_DIRECTORY if directory is None else Path(directory)
    if not directory.is_dir():
        raise EvidenceError("docs/evidence/live/ is not here; run the measurement from the "
                            "source tree, not an installed copy")
    target = directory / ("measurement-%s.json" % record["step"])
    text = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    target.write_text(text, encoding="utf-8")
    return target
