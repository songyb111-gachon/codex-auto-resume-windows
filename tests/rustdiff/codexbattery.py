"""The questions the product asks of a Codex home, asked of every conversation, turn and marker one holds.

`battery(home)` is a list of `LocalSource` calls (`codexdiff.CodexBase.script` runs them through the reference and
through car-codex): the home's own read (the three databases, when it was written, its cloud tasks), every read of the
failures (`latest_failures`, `passed_over`, `stalled_turns`, `activity` with every kind of argument), and for each
conversation the id of the home has - and a few it has not - the eligibility, the chain of its ids, its latest turn,
its labels, its guards' facts, its projection, and for each turn its reset hint, its observation and its markers.
Not a test module (no `test` in its name, and not `diffs_*`).
"""
from __future__ import annotations

import sqlite3

from rustdiff.codexdiff import A, BASE, Home, marker, short_marker


def _rows(home: Home, database: str, sql: str) -> list:
    path = home.root / database
    if not path.exists():
        return []
    try:
        connection = sqlite3.connect(path)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []


def op(method: str, *args, **kwargs) -> dict:
    found = {"method": method}
    if args:
        found["args"] = list(args)
    if kwargs:
        found["kwargs"] = kwargs
    return found


def battery(home: Home, *, markers=(), plug: bool = True, light: bool = False) -> list:
    threads = [row[0] for row in _rows(home, "state_5.sqlite", "SELECT id FROM threads ORDER BY rowid")
               if isinstance(row[0], str)]
    turns = [(row[0], row[1], row[2]) for row in _rows(
        home, "thread_history_1.sqlite", "SELECT thread_id, turn_id, rollout_ordinal FROM thread_turns ORDER BY rowid")
        if isinstance(row[0], str) and isinstance(row[1], str)]
    queued = [(row[0], row[1]) for row in _rows(home, "queue_1.sqlite", "SELECT id, thread_id FROM queued_items")
              if isinstance(row[0], str) and isinstance(row[1], str)]
    proofs = list(markers) + [marker("a"), marker("b"), short_marker("c")] + [item for item, _thread in queued]
    calls = [op("resolve", "state"), op("resolve", "history"), op("resolve", "queue"), op("resolve", "bogus"),
             op("written"), op("cloud_tasks")]
    for since in (BASE - 3600, 0, BASE + 1.5, None, True, "x", 4_200_000_000, float(BASE - 100)):
        calls.append(op("latest_failures", since))
    for needs in ([], ["terminal_auth"], ["unknown", "timeout"]):
        calls.append(op("latest_failures", BASE - 3600, needs_you=needs, admissible=True, shapes=True))
        calls.append(op("latest_failures", BASE - 3600, needs_you=needs, shapes=True))
    known = [turn for _thread, turn, _ordinal in turns[:2]]
    for kwargs in ({}, {"every_status": True}, {"every_status": True, "newest": 2}, {"newest": 1},
                   {"known": known}, {"every_status": True, "known": known, "newest": 3},
                   {"every_status": True, "deadline_in": -5}, {"deadline_in": 100000}):
        calls.append(op("passed_over", BASE - 3600, BASE - 3600, **kwargs))
        calls.append(op("passed_over", 0, BASE - 7200, **kwargs))
    calls.append(op("passed_over", None, BASE))
    calls.append(op("passed_over", BASE, 1.0))
    for quiet in (60, 0, -1, 1.5, True, None, 1):
        calls.append(op("stalled_turns", BASE - 100000, quiet, BASE + 3600))
    calls.append(op("stalled_turns", BASE - 100000, 600, None))
    calls.append(op("stalled_turns", BASE - 100000, 600, BASE + 3600.5))
    calls.append(op("stalled_turns", 5, 600, BASE + 3600))
    everyone = list(dict.fromkeys(threads + [thread for thread, _turn, _ordinal in turns]))
    for kwargs in ({"now": BASE, "booted": BASE - 5}, {"now": BASE + 5000, "booted": BASE + 100},
                   {"now": BASE, "recent": 10}, {"now": BASE, "recent": -1}, {"now": BASE, "recent": None},
                   {"now": None}, {"now": BASE, "booted": 5}, {"now": BASE + 99999, "recent": 0, "booted": BASE},
                   {"now": BASE, "recent": 1e9, "booted": BASE - 100.5}):
        calls.append(op("activity", [], **kwargs))
        calls.append(op("activity", everyone, **kwargs))
    for thread in everyone + ["not-a-uuid", "0a1b2c3d-0001-7000-8000-0000000000ff"]:
        calls += [op("_eligibility", thread), op("_eligibility", thread, strict=True), op("_chain", thread),
                  op("_chain", thread, strict=True), op("_ids", thread), op("turn_chain", thread), op("latest", thread),
                  op("identity", thread), op("project_key", thread), op("projection", thread), op("owner_of", thread),
                  op("_owner", thread), op("_rollout_path", thread), op("taken", thread, []),
                  op("taken", thread, ["cli", "ide"]), op("rescan_evidence", thread, A),
                  op("task_facts", thread), op("task_facts", thread, fingerprint=True),
                  op("task_facts", thread, tokens=True), op("task_facts", thread, fingerprint=True, tokens=True),
                  op("written_by", thread, ["cli", "ide"]), op("written_by", thread, []),
                  op("newer_than_engine", thread, ["cli"], "codex-cli 0.1.0"),
                  op("newer_than_engine", thread, ["cli", "ide"], "codex-cli 99.0.0")]
        if light:
            continue
        for ordinal in (0, 5, 6, 100, -1, 1 << 40, (1 << 40) + 5, 2 << 40, -(1 << 40), 3 * (1 << 40) + 1, True, None, 1.5):
            calls.append(op("progress", thread, ordinal))
        for proof in proofs[:4]:
            calls += [op("marker_rows", thread, proof), op("queued_rows", thread, proof),
                      op("foreign_queued", thread, proof), op("marker_presence", thread, proof),
                      op("later_turns", thread, 0, proof), op("later_turns", thread, 5, proof),
                      op("later_turns", thread, 1 << 40, proof), op("later_turns", thread, None, proof)]
        calls.append(op("turn_markers", thread, A, proofs))
    for item, thread in queued:
        for proof in proofs[:4]:
            calls.append(op("queue_row", thread, item, proof))
        calls.append(op("queue_row", thread, "not-a-uuid", proofs[0]))
    for thread, turn, _ordinal in turns:
        calls += [op("reset_hint", thread, turn), op("turn_progress", thread, turn), op("turn_item_counts", thread, turn),
                  op("_owner", thread, turn_id=turn), op("_owner", turn, turn_id=turn), op("owner_of", turn),
                  op("_chain", thread, turn_id=turn), op("_eligibility", thread, turn_id=turn),
                  op("_eligibility", thread, strict=True, turn_id=turn), op("rescan_evidence", thread, turn),
                  op("turn_markers", thread, turn, proofs)]
        for proof in proofs[:5]:
            calls.append(op("turn_observation", thread, turn, proof))
    if plug:
        for kinds, widened in ((["cli"], []), (["ide"], []), (["cli", "ide"], ["every_desktop"]), ([], ["every_desktop"]),
                               (["bogus"], ["every_desktop", "x"])):
            calls.append(op("@plug", kinds=kinds, widened=widened))
            for thread in everyone[:12]:
                calls += [op("_eligibility", thread), op("_chain", thread), op("latest", thread),
                          op("taken", thread, kinds, widened=widened or None)]
            calls += [op("latest_failures", BASE - 3600), op("latest_failures", BASE - 3600, admissible=True, shapes=True),
                      op("passed_over", BASE - 3600, BASE - 3600, every_status=True)]
        calls.append(op("@plug"))
    return calls
