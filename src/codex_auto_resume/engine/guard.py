"""The guards and the waits of v0.6.11, as the engine asks them: each reads nothing at the defaults.

When an interruption is detected, `detected_facts` takes what the two guards keep on its record (a
digest of what its task was working with, and its conversation's token count), each only while its
guard is on, and `detection_wait` says how long it waits before its first look: the preset's first
wait as in v0.6.10, or the Custom ladder's step for this attempt at the task, never less than a wait
Codex named, and a little longer with jitter on. A conversation already over the context-cost limit
is held for a person from the start (engine/detect.py); a count only grows with a new turn, and a new
turn supersedes the interruption, so it is judged once.

When the recovery falls due - every gate passed, where it would otherwise be sent now - `_guarded`
takes the task's digest again. Under Hold a change keeps the record for a person, through the store's
`hold_changed`, which holds only a record that still waits unsent and makes what it found the record's
digest in the same transaction - so Let it continue lets it go, and only a further change holds it
again. The claim and the last look before the send see the hold as they see any other (standard A8,
A9). Under Tell the record goes on, and its continuation's notice says the task changed. Neither
guard sends anything, skips a gate or makes anything sooner.
"""
from __future__ import annotations

from .. import guards, ladder, machine
from ..domain.vocabulary import TaskGuard


class GuardMixin:
    def draw(self) -> float:
        """A number in [0, 1) for jitter - asked only when jitter is on, which it is not by default."""
        return self._random.random()

    def _next_attempt(self, thread_id, turn_id, owner) -> int:
        """Which attempt at its task an interruption is: one more than the record whose own continuation
        started the turn that failed, or 1 for a task's first. Asked only under the Custom ladder."""
        for row in self.store.claimed_on_thread(thread_id):
            if row["recovery_turn_id"] == turn_id or row["interruption_id"] == owner:
                return row["recovery_attempts"] + 1
        return 1

    def detection_wait(self, category, *, thread_id=None, turn_id=None, owner=None, retry_after=None) -> int:
        """How long a temporary failure waits once detected: v0.6.10's first wait under a preset, the
        Custom step of this attempt at its task, at least a named Retry-After, and jitter on top."""
        values = self.policy_values
        if ladder.walks(values):
            delay = ladder.wait_before(values, self._next_attempt(thread_id, turn_id, owner), category)
        else:
            delay = self.first_delay(category)
        if isinstance(retry_after, int) and not isinstance(retry_after, bool) and retry_after > delay:
            delay = retry_after
        if values.get("retry_jitter") is True:
            delay = ladder.jittered(delay, values, self.draw())
        return delay

    def detected_facts(self, thread_id) -> dict:
        """What the guards keep on a new record: {"task_print", "context_tokens"}, each None while its
        guard is off - at the defaults both, and Codex is asked nothing for them."""
        values = self.policy_values
        watch, count = guards.watches_task(values), guards.counts_tokens(values)
        if not (watch or count):
            return {"task_print": None, "context_tokens": None}
        try:
            facts = self.source.task_facts(thread_id, fingerprint=watch, tokens=count)
        except Exception:
            facts = {"print": None, "tokens": None}
        found = facts.get("print")
        return {"task_print": (found if guards.is_print(found) else guards.UNREADABLE) if watch else None,
                "context_tokens": guards.tokens(facts.get("tokens")) if count else None}

    def _told_of(self, row) -> dict:
        """What the notice of a continuation just sent adds: that its task changed, under Tell; else nothing."""
        if row["interruption_id"] not in self._told:
            return {}
        self._told.discard(row["interruption_id"])
        return {"task_changed": True}

    def _guarded(self, row, vector, now) -> bool:
        """At the moment of sending: True if the task-changed guard held this record for a person."""
        values = self.policy_values
        if not guards.watches_task(values) or row.get("task_print") is None:
            return False
        try:
            found = self.source.task_facts(row["thread_id"], fingerprint=True).get("print")
        except Exception:
            found = None
        if not guards.changed(row["task_print"], found):
            return False
        key = row["interruption_id"]
        if guards.task_mode(values) == TaskGuard.TELL:
            if key not in self._told:
                if len(self._told) > 1024:          # bounded, as the announced set is
                    self._told.clear()
                self._told.add(key)
                self.log(row["thread_id"], "task_changed_told", None)
            return False
        if self.store.hold_changed(key, found if guards.is_print(found) else guards.UNREADABLE, now,
                                   actor="engine"):
            vector["consent"] = machine.gate(machine.WAIT, machine.HELD)
            self.store.record_gates(key, vector, now)
            self.log(row["thread_id"], "held_by_guard_" + guards.TASK_HOLD, None)
            self.announce("interruption", dict(row, hold=guards.TASK_HOLD), hold=guards.TASK_HOLD,
                          state="held")
        # A record that could not be held has moved - cancelled, claimed, held already - and sends
        # nothing on this tick either; the next one looks again from the top.
        return True
