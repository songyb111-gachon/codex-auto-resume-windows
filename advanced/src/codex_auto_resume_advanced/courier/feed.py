# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""OpenAI's status page, read once and reduced to two words and a count (status_feed).

One GET of SUMMARY_URL - a constant, checked in a test - at most http.MAX_REPLY bytes, read as Statuspage's v2 summary
(verified 2026-10-22: the page answers in that shape and lists "Codex in ChatGPT Desktop"):

* `status.indicator`: none -> operational, minor -> degraded, major or critical -> outage, anything else unknown;
* the first component whose name starts with "Codex": operational -> operational, degraded_performance or
  partial_outage -> degraded, major_outage -> outage, anything else unknown;
* how many incidents are listed, at most 99.

Nothing else of the reply is kept, and what is kept is a word for the Overview and Why it is waiting to show - never
the input of a gate or of any decision (a test greps the dispatch, the gates and every plug answer for it). A reply that
cannot be read, an unexpected shape or a page that is too long is unknown; a page that cannot be reached leaves the
words it had, its time moved on. Only `refresh` loads http: the watcher reads the kept row through `read` without it.
"""
from __future__ import annotations

import json

from ..vocabulary import FeedWord

CAPABILITY = "status_feed"
SUMMARY_URL = "https://status.openai.com/api/v2/summary.json"
INDICATORS = {"none": FeedWord.OPERATIONAL, "minor": FeedWord.DEGRADED, "major": FeedWord.OUTAGE,
              "critical": FeedWord.OUTAGE}
COMPONENTS = {"operational": FeedWord.OPERATIONAL, "degraded_performance": FeedWord.DEGRADED,
              "partial_outage": FeedWord.DEGRADED, "major_outage": FeedWord.OUTAGE}
MOST_INCIDENTS = 99
MAX_REPLY = 65536                  # http.MAX_REPLY: a reply this long was cut, and is not read
UNKNOWN = (FeedWord.UNKNOWN, FeedWord.UNKNOWN, 0)


def parse(raw) -> tuple:
    """(word, codex_word, incidents) of a summary's bytes; UNKNOWN for anything that is not one. Pure."""
    if not isinstance(raw, bytes) or len(raw) >= MAX_REPLY:
        return UNKNOWN
    try:
        found = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return UNKNOWN
    if not isinstance(found, dict):
        return UNKNOWN
    status = found.get("status") if isinstance(found.get("status"), dict) else {}
    indicator = status.get("indicator")
    word = INDICATORS.get(indicator, FeedWord.UNKNOWN) if isinstance(indicator, str) else FeedWord.UNKNOWN
    codex = FeedWord.UNKNOWN
    for component in found.get("components") if isinstance(found.get("components"), list) else ():
        name = component.get("name") if isinstance(component, dict) else None
        if isinstance(name, str) and name.startswith("Codex"):
            said = component.get("status")
            codex = COMPONENTS.get(said, FeedWord.UNKNOWN) if isinstance(said, str) else FeedWord.UNKNOWN
            break
    incidents = found.get("incidents")
    count = min(len(incidents), MOST_INCIDENTS) if isinstance(incidents, list) else 0
    return word, codex, count


def save(state, found, now) -> None:
    """The one `feed` row: what was read and when."""
    word, codex, count = found
    with state._transaction() as connection:
        connection.execute("INSERT INTO feed (singleton, checked_at, word, codex_word, incidents) VALUES (1,?,?,?,?) "
                           "ON CONFLICT(singleton) DO UPDATE SET checked_at = excluded.checked_at, word = excluded.word, "
                           "codex_word = excluded.codex_word, incidents = excluded.incidents",
                           (float(now), str(word), str(codex), int(count)))


def touch(state, now) -> None:
    """The time moved on, the words kept: a read that could not reach the page."""
    with state._transaction() as connection:
        connection.execute("INSERT INTO feed (singleton, checked_at) VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE "
                           "SET checked_at = excluded.checked_at", (float(now),))


def read(state):
    """The `feed` row as a dict, or None."""
    with state._read() as connection:
        if connection is None:
            return None
        row = connection.execute("SELECT checked_at, word, codex_word, incidents FROM feed").fetchone()
    return dict(row) if row is not None else None


def refresh(runtime, *, opener=None, now=None):
    """One read of the page, kept and counted: `checked`, `unknown` for a reply of no known shape, `refused` for no
    reply. What was kept. The one function here that reaches the network, and the only one that loads http."""
    from . import http
    state = runtime.state
    now = runtime.clock() if now is None else now
    try:
        found = parse(http.get(SUMMARY_URL, opener=opener))
    except http.Failed:
        touch(state, now)
        state.counted(CAPABILITY, "refused")
        return None
    save(state, found, now)
    state.counted(CAPABILITY, "unknown" if found == UNKNOWN else "checked")
    return found
