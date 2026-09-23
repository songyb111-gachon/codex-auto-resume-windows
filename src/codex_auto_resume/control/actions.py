"""What a person asks for, and nothing that sends.

Every method here changes a flag, a schedule or a budget. None of them hands anything to
Codex: the watcher is the only thing that does, and it stays the only thing that does.
"""
from __future__ import annotations

import time

from ..store import TERMINAL, StoreError
from ..windows import WakeEvent
from .errors import (ControlError,
                     _REFUSALS_RESTORE,
                     _REFUSALS_RETRY,
                     _identifier,
                     _refusal,
                     _thread_id)


# A cancel must not fail because the watcher happens to be writing. The store already
# waits ten seconds for a lock; the cancel tries again for this long in total.
CANCEL_RETRY_SECONDS = 30.0


class ActionsMixin:
    """Enabling, cancelling, resetting and asking for a retry."""

    # ------------------------------------------------------------------ mutations
    def set_enabled(self, enabled: bool) -> dict:
        """Global pause/resume. Reuses the existing kill switch rather than adding a
        second concept, so there is only ever one answer to "is recovery running".
        Pending records are preserved either way."""
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false", code="invalid_enabled")
        with self._open(legacy_ok=True) as store:
            store.set_enabled(enabled, time.time())
            return {"enabled": bool(store.settings()["enabled"])}

    def set_thread_enabled(self, thread_id: str, enabled: bool, *, actor: str = "gui") -> dict:
        """Switch automatic recovery on or off for one conversation."""
        thread = _thread_id(thread_id)
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false", code="invalid_enabled")
        with self._open(legacy_ok=True) as store:
            store.set_thread_enabled(thread, enabled, actor=actor)
            return {"thread_id": thread, "enabled": store.thread_enabled(thread)}

    def cancel_interruption(self, interruption_id: str, *, actor: str = "gui") -> dict:
        """Stop recovering one exact interruption, and anything that continues it.

        Always available: cancelling only ever reduces automation, so it never needs
        Codex to be running, and it is retried rather than lost when the watcher is
        busy writing. A continuation that may already be in Codex is only marked; the
        watcher takes it back if it is still queued.
        """
        key = _identifier(interruption_id)
        deadline = time.monotonic() + CANCEL_RETRY_SECONDS
        while True:
            try:
                with self._open() as store:
                    result = store.cancel_interruption(key, time.time(), actor=actor)
                    if result is None:
                        raise ControlError("no such interruption", code="no_such_interruption")
                    record = store.get(key)
                break
            except ControlError:
                raise
            except StoreError:
                if time.monotonic() >= deadline:
                    raise ControlError("the state is busy; the cancel was not recorded",
                                       code="state_busy") from None
                time.sleep(0.5)
        effects = result["effects"]
        if not result["changed"]:
            message = "already finished; nothing to stop"
        elif any(effect == "cancel_requested" for effect in effects.values()):
            message = ("cancelled; a continuation already handed to Codex is withdrawn if it is "
                       "still queued, and one already running is not stopped")
        else:
            message = "cancelled"
        return {"interruption_id": key, "thread_id": record["thread_id"], "state": record["state"],
                "changed": result["changed"], "effects": effects, "message": message}

    def cancel_thread(self, thread_id: str, *, actor: str = "gui") -> dict:
        """Turn automatic recovery off for one conversation and stop what it has."""
        thread = _thread_id(thread_id)
        with self._open(legacy_ok=True) as store:
            store.cancel_thread(thread, time.time(), actor=actor)
        return {"thread_id": thread}

    def reset_recovery_budget(self, interruption_id: str, *, actor: str = "gui") -> dict:
        """Give an exhausted interruption its attempts back.

        Deliberately explicit, and deliberately not a send: the record re-enters the
        wait its kind of failure needs and every gate runs again from the top. It does
        not switch a conversation back on, and it can be done a few times per task, not
        without limit.
        """
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption", code="no_such_interruption")
            restored, detail = store.restore_budget_detailed(key, time.time(), actor=actor)
            if not restored:
                # The store checks "is it one of the two exhausted states" before it checks
                # anything else, so it calls a cancelled or recovered record "not_exhausted"
                # - which would tell a person their cancelled recovery still has attempts
                # left. This layer has the record in hand and can say which it really is.
                if detail == "not_exhausted" and record["state"] in TERMINAL:
                    detail = "cancel_requested" if record["cancel_requested"] else "finished"
                message, code = _refusal(_REFUSALS_RESTORE, detail)
                raise ControlError(message, code=code)
            thread_on = store.thread_enabled(record["thread_id"])
            note = None if thread_on else ("automatic recovery is off for this conversation; "
                                           "switch it on for this recovery to run")
            return {"interruption_id": key, "state": store.get(key)["state"], "note": note}

    def request_retry_now(self, interruption_id: str, *, actor: str = "gui") -> dict:
        """Make a waiting interruption eligible immediately.

        This brings the *schedule* forward and nothing else. It does not send, does not
        bypass the loaded-thread requirement, does not bypass a usage window and does
        not skip revalidation: the watcher still runs the entire pipeline, and if usage
        is still exhausted the record simply goes back to waiting.
        """
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption", code="no_such_interruption")
            accepted, detail = store.request_retry_now(key, time.time(), actor=actor)
        if not accepted:
            message, code = _refusal(_REFUSALS_RETRY, detail)
            raise ControlError(message, code=code)
        woke = False
        try:
            woke = WakeEvent(str(self.paths.state_dir)).signal()
        except Exception:
            woke = False
        now = time.time()
        if detail > now + 1:
            note = ("the usage reset is at a later time; the watcher checks then, and every "
                    "safety check still applies")
        elif woke:
            note = "checking now; every safety check still applies"
        else:
            note = "the watcher checks at its next poll; every safety check still applies"
        return {"interruption_id": key, "state": record["state"], "eligible_at": detail,
                "woke": woke, "note": note}


    def set_interruption_recovery(self, interruption_id, thread_id, enabled, *,
                                    actor: str = "gui") -> dict:
        """The per-task checkbox: automatic recovery on or off for this exact task.

        A click carries both identities, and both are checked against the record as it is
        now, not as it was when the row was drawn. A list that re-sorted between drawing
        and clicking must never turn a click on one task into a change to another, so a
        record that no longer exists, has finished, or belongs to a different conversation
        is refused and nothing is changed.

        What the switch changes is the conversation's policy, which is the thing that
        survives: turning it off keeps this recovery - and anything that later interrupts
        the same conversation - from being continued until it is turned back on. It never
        sends anything, and turning it on still leaves every gate to run.
        """
        key = _identifier(interruption_id)
        thread = _thread_id(thread_id)
        if not isinstance(enabled, bool):
            raise ControlError("enabled must be true or false", code="invalid_enabled")
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption", code="no_such_interruption")
            # Nothing is changed by either refusal.
            if record["thread_id"] != thread:
                raise ControlError("that recovery belongs to a different conversation",
                                   code="thread_mismatch")
            if record["state"] in TERMINAL:
                raise ControlError("that recovery has already finished", code="already_finished")
            store.set_thread_enabled(thread, enabled, actor=actor)
            return {"interruption_id": key, "thread_id": thread,
                    "enabled": store.thread_enabled(thread), "state": record["state"]}

    def cancel_all_pending(self, *, actor: str = "gui") -> dict:
        """Stop every pending recovery, one exact interruption at a time.

        Only cancelling is offered in bulk. It can only reduce what the tool does, so
        doing it to everything at once cannot cause a send. "Retry now" is deliberately
        not offered in bulk: one record at a time under one lock is what keeps the argument
        that nothing is ever sent twice short enough to check.
        """
        with self._open() as store:
            keys = [row["interruption_id"] for row in store.pending()]
        cancelled = finished = failed = 0
        for key in keys:
            try:
                result = self.cancel_interruption(key, actor=actor)
            except ControlError:
                failed += 1
                continue
            if result["changed"]:
                cancelled += 1
            else:
                # Cancelling a chain's parent also stops its child, which is then found
                # already finished when its own turn comes.
                finished += 1
        return {"requested": len(keys), "cancelled": cancelled,
                "already_finished": finished, "failed": failed}

    def clear_history(self, *, actor: str = "gui") -> dict:
        """Hide finished recoveries from the History view. Deletes nothing, cancels
        nothing, and never hides a recovery that may still change."""
        with self._open() as store:
            return store.hide_history(time.time(), actor=actor)
