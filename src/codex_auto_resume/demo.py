"""Show me what happens (v0.6.11): a recovery played out with made-up words, and nothing sent.

Diagnostics' button asks for it. The Dashboard then shows one made-up task on Pending, counting down
DEMO_SECONDS, and after it one made-up entry in History, and says that nothing was sent; the watcher,
asked through its demo event (win/sync.py), draws one card of the same made-up task, with the words
an interruption's card has and buttons that do nothing (notifier.build_demo).

Everything here is made up and held in memory: an obviously fake conversation and interruption, a
usage limit that "resets" in a minute. This module - the one both sides take the demo from - reads
no state and knows no engine: it imports neither the store nor the engine, and nothing it returns is
ever written anywhere (tests/test_demo.py holds all three). A row it returns carries `demo: true`, and
every surface offers no action on such a row.
"""
from __future__ import annotations

from . import machine

DEMO_SECONDS = 60
# Obviously not a real task: a conversation id of zeros ending in de30, and the same for the record.
DEMO_THREAD = "00000000-0000-4000-8000-00000000de30"
DEMO_KEY = "0" * 60 + "de30"
CATEGORY = "usage_limit"


def detail(now: float) -> dict:
    """The made-up interruption a demo card is built from, as the engine hands one to a notice."""
    return {"thread_id": DEMO_THREAD, "interruption_id": DEMO_KEY, "category": CATEGORY,
            "reset_at": float(now) + DEMO_SECONDS}


def _row(record: dict) -> dict:
    """One made-up record as a list row, in the keys a Pending or History row has (control/records.py),
    each with the value it would have: nothing counted, nothing queued, nothing seen."""
    described = machine.describe(record)
    return {
        "interruption_id": DEMO_KEY, "thread_id": DEMO_THREAD, "state": record["state"],
        "code": described["code"], "reason": described["reason"], "overlays": described["overlays"],
        "eligible_at": described["eligible_at"], "terminal": described["terminal"],
        "category": CATEGORY, "detected_at": record["detected_at"], "reset_at": record["reset_at"],
        "next_retry_at": record["next_retry_at"], "recovery_attempts": 0, "no_progress_count": 0,
        "chain_continuations": 0, "chain_origin_id": DEMO_KEY, "parent_interruption_id": None,
        "budget_resets": 0, "budget_resets_left": 0, "cancel_requested": False,
        "recovery_turn_status": None, "user_joined": False, "after_user_work": False,
        "outcome_at": record.get("outcome_at"), "first_queued_at": None, "gates": None, "gates_at": None,
        "not_before": None, "postponed_until": None, "hold": None, "would_send_at": None,
        "context_tokens": None,
        "thread_enabled": True, "tier": None, "attempt_limit": None,
        "name": None, "project": None, "cwd_basename": None,
        "demo": True,
    }


def rows(now: float) -> dict:
    """The demo as the Dashboard plays it: how long it counts down, the made-up task on Pending,
    and the made-up entry History shows once the countdown has run out. A pure function of `now`."""
    now = float(now)
    due = now + DEMO_SECONDS
    waiting = {"state": "waiting_reset", "detected_at": now, "reset_at": due, "next_retry_at": due}
    finished = dict(waiting, state="recovered", outcome_at=due)
    return {"seconds": DEMO_SECONDS, "pending": _row(waiting), "history": _row(finished)}
