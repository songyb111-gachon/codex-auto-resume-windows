# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What a watched capability would have done: the journal's first reader, and its only one.

While a capability is watched ("Watch first"), the runtime asks it as it would ask it on and takes
none of its answers: each answer it would have acted on is written to the journal as one
`would_have` line - the capability, the point, the answer's word and the time (runtime.Runtime.ask,
`_send_again`). This module shows those lines, per capability, on the Advanced features page
(`view`, the Dashboard's `advanced-watch-log`) and in a diagnostics export the person asks for
(`exported`). It changes nothing that decides, sends or arms.

What a count means. The runtime writes one line for each (recovery, point, answer) in a watcher
process (runtime.Runtime._once): a recovery looked at a hundred times counts once. A watcher that
restarts, or the runtime's memory of what it noted filling (NOTED_LIMIT) and starting again, can
count one again; a point with no recovery (the tick, the start route) counts once a process. The
page says "once for each recovery"; this is the rest of it.

What it shows is content-free. Per capability, one entry per answer word - `{"answer", "points",
"count", "first", "last"}` - with every time in whole seconds rounded down to the minute, as the
samples are. The journal holds no id of a conversation, an interruption or a turn at all, so none
can leak. The words come from a closed list (WORDS): every alternative, and the points whose answer
is a value, which the journal writes as the point's name. Anything else reads as null ("Something
else"). Entries are grouped by answer, not by (point, answer). The vocabulary lets some words be
answered at more than one point - the take-up words at gates and admission, HOLD at gates, the
schedule and the claim ledger - but while watched only HOLD reaches the journal from two (gates and
the schedule): a take-up at gates needs the capability's own admission row, which only one that is
on writes (runtime.Runtime._takes), and the claim ledger is not a point the runtime asks. So the
page needs no point words; `points` keeps them for the export.

Read-only. It reads the stored arming rows (state.arming) and the journal (state.journal), and
never Arming.current, Arming.read or Arming.listing, which can carry out a trip. It opens no write
transaction and creates nothing: with no advanced file it answers empty. (A version-2 file is
brought to version 3 by any read of it, this one's as every other's - session.py.) So "watched
since" is the stored state: a capability a policy reads down to watched (ForceShadow) shows its
answers without the since-line.

Bounds: the journal keeps at most WATCH_LIMIT `would_have` lines a capability, its newest
(state/journal.py), and this shows the last WINDOW_DAYS of them - never more than WATCH_LIMIT, so
between two prune passes it counts what a pass would keep. Where the bound let older answers of the
window go - the count is at the bound and the oldest it counts is inside the window - it says from
when it counts (`full`, `from`). (With exactly WATCH_LIMIT ever written and none let go, it says so
too: the file cannot tell the two apart.)

The journal is never read to decide anything (D4): only this module calls `journal()` in this
package, and only surfaces.py imports it (advanced/tests/test_advanced_watch_log.py).
"""
from __future__ import annotations

import math

from codex_auto_resume.domain.plug import Alternative, Point

from .state import EVENT_LIMIT, WATCH_LIMIT, StateError
from .state.choices import DAY, RECENT_DAYS
from .vocabulary import ArmingState, JournalCode, Refusal

WINDOW_DAYS = RECENT_DAYS                      # 30, as the samples and the rules' hits
# The points whose answer is a value, not a word: the journal writes the point's name instead.
VALUE_POINTS = (Point.TEXT, Point.SENDER, Point.TICK, Point.START_ROUTE, Point.UNLOADED)
# Every answer the log names; anything else reads as null.
WORDS = tuple(Alternative) + VALUE_POINTS
_WORDS = frozenset(str(word) for word in WORDS)


def minute(at):
    """`at` in whole seconds, rounded down to the minute; None for anything that is not a time."""
    if not isinstance(at, (int, float)) or isinstance(at, bool) or not math.isfinite(at):
        return None
    return int(at // 60) * 60


def _word(answer):
    return str(answer) if isinstance(answer, str) and answer in _WORDS else None


def entries(lines) -> list:
    """`lines` grouped by answer word: [{"answer", "points", "count", "first", "last"}], the most
    counted first. A word outside WORDS is null; `points` are the point words it was asked at."""
    grouped = {}
    for line in lines:
        word = _word(line.get("answer"))
        entry = grouped.setdefault(word, {"answer": word, "points": set(), "count": 0,
                                          "first": None, "last": None})
        point = line.get("point")
        if isinstance(point, str) and point in tuple(Point):
            entry["points"].add(str(point))
        entry["count"] += 1
        at = minute(line.get("at"))
        if at is not None:
            entry["first"] = at if entry["first"] is None else min(entry["first"], at)
            entry["last"] = at if entry["last"] is None else max(entry["last"], at)
    shown = [dict(entry, points=sorted(entry["points"])) for entry in grouped.values()]
    return sorted(shown, key=lambda entry: (-entry["count"], entry["answer"] or "~"))


def _of(row, lines, now) -> dict:
    """One capability's log from its stored row and its journal lines, oldest first."""
    watched = [line for line in lines if line.get("code") == JournalCode.WOULD_HAVE]
    counted = watched[-WATCH_LIMIT:]
    start = now - WINDOW_DAYS * DAY
    recent = [line for line in counted
              if isinstance(line.get("at"), (int, float)) and line["at"] >= start]
    full = len(watched) >= WATCH_LIMIT and len(recent) == len(counted)
    since = row.get("since") if row and row.get("state") == ArmingState.SHADOW else None
    return {"watched_since": minute(since), "entries": entries(recent),
            "from": minute(recent[0]["at"]) if recent else None, "full": full}


def view(runtime, capability) -> dict:
    """The Dashboard's `advanced-watch-log`: what `capability` would have done while watched, in
    the last WINDOW_DAYS. Refused for an id the registry does not hold, or a state that cannot be
    read."""
    definition = runtime.registry.get(capability) if isinstance(capability, str) else None
    if definition is None:
        return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
    try:
        row = runtime.state.arming().get(definition.id)
        lines = runtime.state.journal(capability=definition.id, limit=EVENT_LIMIT)
    except StateError:
        return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
    return dict(_of(row, lines, runtime.clock()), done=True, capability=definition.id, days=WINDOW_DAYS)


def exported(runtime) -> list:
    """What a diagnostics export carries (surfaces.diagnostics): every capability stored as watched or
    with answers in the window, in the registry's order, each as `view` shows it - ids, words, minutes
    and counts, nothing to alias and nothing quoted (D5). One read of the arming rows and one of the
    journal; [] where the state cannot be read, which costs the export nothing."""
    try:
        rows = runtime.state.arming()
        lines = runtime.state.journal(limit=EVENT_LIMIT)
    except StateError:
        return []
    now, shown = runtime.clock(), []
    for definition in runtime.registry:
        own = [line for line in lines if line.get("capability") == definition.id]
        found = _of(rows.get(definition.id), own, now)
        if found["watched_since"] is not None or found["entries"]:
            shown.append(dict(capability=definition.id, **found))
    return shown
