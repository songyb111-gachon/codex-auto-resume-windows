"""Turning what Codex recorded into records this product owns.

Detection registers a failure once, under an id derived from the failure itself, so the same
interruption seen twice is the same record - and a record whose turn is no longer the thread's
latest is superseded rather than recovered.

v0.6.13 (stage 3b): the edition's plug is asked at P17 (domain/plug.py) about a failure core never
recovers alone - and one it does, which it may relax - once that failure has passed every check core
makes of one: its conversation on, not known, its kind not switched off, from the last hour, and not
a task core would stop the moment it was registered. Only an answer core offered is taken
(failures.takes), and only while the plug wants to be asked; otherwise this reads what it read. How
it is asked, and what is carried out of an answer, is engine/relaxed.py's.
"""
from __future__ import annotations

from .. import failures, guards, ladder, machine, needsyou
from ..machine import OBSERVING, TERMINAL, WAITING, WATCHED
from ..codex import admissible as admissible_failure, detect
from ..domain.plug import DEFER, PACED_AS, Alternative, Point
from .relaxed import UNADMITTED_SECONDS


class DetectMixin:
    def waiting_state(self, row) -> str:
        """The wait a record returns to when it goes back to waiting now."""
        return machine.waiting_state(row, self.clock())

    def valid_interruption(self, row):
        """Whether the record is still its conversation's latest failure: an identity check and only
        that. One the edition's plug took up (failures.ADMISSIBLE) is found as it was taken up, never by
        `detect`; nothing that lets it be sent rests on this (engine/dispatch.py, store/claims.py)."""
        latest = self.source.latest(row["thread_id"])
        if not latest:
            return False
        found = (admissible_failure(latest) if row["category"] in failures.ADMISSIBLE
                 else detect(latest))
        return found is not None and found["interruption_id"] == row["interruption_id"]

    def supersede_reason(self, row):
        """Why this interruption is no longer the one to recover.

        A later turn on the exact thread means work continued without us - by the user,
        or by Codex itself - so the old failure must not be resumed on top of it.
        """
        try:
            progress = self.source.progress(row["thread_id"], row["ordinal"])
        except Exception:
            progress = {}
        if progress.get("later_turn"):
            return "superseded_by_user", "later_turn_exists"
        return "superseded", "latest_turn_changed"

    # --------------------------------------------------------------- collect
    def _owner(self, thread_id, turn_id):
        """Which of our records put its continuation into this turn, if any."""
        candidates = [row for row in self.store.claimed_on_thread(thread_id)
                      if row["recovery_turn_id"] is None]
        if not candidates:
            return None
        try:
            present = set(self.source.turn_markers(thread_id, turn_id, [self.proof(row) for row in candidates]))
        except Exception:
            return None
        for row in candidates:
            if self.proof(row) in present:
                return row["interruption_id"]
        return None

    def _legacy_carry(self, detection):
        """The v0.5 no-progress carry, for a predecessor recorded before chains existed.

        When the previous delivered interruption on this thread produced no completed
        turn and no assistant reply, the count carries forward; visible progress resets
        it. Only lifecycle booleans are consulted - no message text.
        """
        previous = [row for row in self.store.claimed_on_thread(detection["thread_id"])
                    if row["state"] == "resumed" and row["interruption_id"] != detection["interruption_id"]]
        if not previous:
            return None
        last = max(previous, key=lambda row: row["ordinal"])
        try:
            progress = self.source.progress(detection["thread_id"], last["ordinal"])
        except Exception:
            return None                     # unreadable progress is not evidence of failure
        if progress.get("assistant_reply") or progress.get("later_completed"):
            return None                     # something happened; the chain starts over
        return last["no_progress_count"] + 1

    def collect(self):
        settings = self.store.settings()
        if not settings["enabled"]:
            return
        since = max(0.0, settings["armed_at"] - self.options["detection_lookback_seconds"])
        # v0.6.11: the same read also brings the failures a needs-you notice is raised for, only while
        # one is on (needsyou.kinds) - none of which `detect` takes, so none becomes a record. At the
        # defaults it is v0.6.10's read exactly.
        kinds = needsyou.kinds(self.policy_values)
        # v0.6.13: and, while the edition's plug wants P17, the failures it may take up and every
        # error's shape - never while only observing or while an administrator disables recovery (K5).
        asking = (self.plug.wants(Point.ADMISSION) and not self.observing(settings)
                  and not self.managed.disable_auto_resume)
        extra = {"admissible": True, "shapes": True} if asking else {}
        found = (self.source.latest_failures(since, needs_you=kinds, **extra) if kinds
                 else self.source.latest_failures(since, **extra))
        taken = set()
        for raw in found:
            shape, admissible = raw.pop("shape", None), raw.pop("admissible", False)
            record = detect(raw)
            admissible = record is None and admissible
            if admissible:
                record = admissible_failure(raw)
            if record is None or not self.store.thread_enabled(record["thread_id"]):
                continue
            if self.store.get(record["interruption_id"]) is not None:
                continue
            category = record["category"]
            if not self.recovers(category):
                # Logged once per interruption: the user switched this off deliberately,
                # so it is a fact worth being able to find, not a repeating complaint.
                if record["interruption_id"] not in self._declined:
                    if len(self._declined) > 512:
                        self._declined.clear()
                    self._declined.add(record["interruption_id"])
                    self.log(record["thread_id"], "category_recovery_disabled", category)
                continue
            now = self.clock()
            if admissible and (record["completed_at"] < now - ladder.ADMISSION_MAX_AGE
                               or now - self._unadmitted.get(record["interruption_id"], -1e18)
                               < UNADMITTED_SECONDS):
                continue                     # too old to take up, or put to the plug a moment ago
            usage = category == failures.USAGE_LIMIT
            # A reset timestamp only exists for a usage limit; a transient failure has
            # nothing to wait for but time, so the two schedules are computed separately.
            hint = (self.source.reset_hint(record["thread_id"], record["turn_id"]) if usage
                    else {"reset_at": None, "limit_type": category, "uncertain": False})
            # store.register accepts only these exact detection fields; detect() also
            # returns status/category which must not be forwarded as-is.
            detection = {
                "thread_id": record["thread_id"], "turn_id": record["turn_id"],
                "completed_at": record["completed_at"], "started_at": record["started_at"],
                "ordinal": record["ordinal"], "interruption_id": record["interruption_id"],
                "reset_at": hint["reset_at"], "limit_type": hint["limit_type"],
                "uncertain": bool(hint["uncertain"]), "category": category,
            }
            reset = detection["reset_at"]
            owner = self._owner(detection["thread_id"], detection["turn_id"])
            progress = self.source.turn_progress(detection["thread_id"], detection["turn_id"])
            carry = None if owner else self._legacy_carry(detection)
            answer, parent = DEFER, None
            if asking:
                decided = self._taken_up(record, shape, owner, progress, carry, admissible, now)
                if decided is None:
                    continue
                answer, parent = decided
            if usage:
                state = "waiting_reset" if reset else "waiting_poll"
                when = (max(now + 30, reset + self.options["reset_grace_seconds"]) if reset
                        else now + self.options["conservative_poll_seconds"])
            elif answer is Alternative.CAPACITY:
                state, when = "waiting_backoff", now + self._capacity_wait(parent)
            elif answer in PACED_AS:
                # Taken up as a temporary kind (P17): waited, counted and switched off as that kind.
                state = "waiting_backoff"
                when = now + self.detection_wait(PACED_AS[answer], thread_id=detection["thread_id"],
                                                 turn_id=detection["turn_id"], owner=owner)
            elif admissible:
                state = "waiting_backoff"
                when = now + self._admitted_wait(parent, detection, owner)
            else:
                # The preset's first wait, as in v0.6.10; from v0.6.11 the Custom ladder's step for
                # this attempt at the task, a Retry-After Codex named, and jitter, each only if set.
                state = "waiting_backoff"
                when = now + self.detection_wait(category, thread_id=detection["thread_id"],
                                                 turn_id=detection["turn_id"], owner=owner,
                                                 retry_after=record.get("retry_after"))
            # v0.6.11: a conversation that asks first, or only notifies, has what it detects held
            # for a person from the start - its tier as it stands now (machine.hold_for_tier) - and
            # so does one new to this state or in a project not let resume, when Settings say so
            # (admission). None at the defaults, where every conversation is resumed automatically.
            hold = self.admission(detection["thread_id"], now)
            # And what the two guards keep of it, each only while it is on (engine/guard.py): a
            # conversation already over the context-cost limit waits for a person from the start.
            facts = self.detected_facts(detection["thread_id"])
            if hold is None and guards.over(self.policy_values, facts["context_tokens"]):
                hold = guards.CONTEXT_HOLD
            # One transaction: the record can never exist without its real schedule and
            # the counters of the task it continues.
            limits = self.capacity_limits() if answer is Alternative.CAPACITY else self.limits()
            if not self.store.register(detection, now, state=state, next_retry_at=when,
                                       owner_id=owner, failed_turn_progress=progress,
                                       legacy_carry=carry, limits=limits, hold=hold, **facts):
                continue
            registered = self.store.get(detection["interruption_id"])
            if admissible:
                taken.add(detection["interruption_id"])
                self.log(detection["thread_id"], "failure_taken_up", detection["interruption_id"])
            else:
                self.log(detection["thread_id"],
                         "usageLimitExceeded_detected" if usage else "transient_failure_detected",
                         detection["interruption_id"] if usage else category)
            if registered["state"] in TERMINAL:
                # Created already stopped: the task it continues was cancelled, taken
                # over, or is out of budget. Said once, and never as "will resume".
                self.log(detection["thread_id"], registered["state"], registered["last_error"])
                self.announce("stopped", registered, state=registered["state"],
                              reason=registered["last_error"])
                continue
            if usage and reset:
                self.log(detection["thread_id"], "reset_expected", str(int(reset)))
            elif usage:
                self.log(detection["thread_id"], "reset_unknown_conservative_poll",
                         str(int(self.options["conservative_poll_seconds"])))
            if detection["uncertain"]:
                self.log(detection["thread_id"], "blocking_limit_uncertain", None)
            # The only moment a control can be offered at the time it matters: the
            # Codex turn has already failed, so nothing can be added to the app's
            # own notice, but the watcher is running right now. A held one says it waits for
            # a person, never that it will resume (notify.scheduled_content).
            held = {"hold": registered["hold"]} if registered["hold"] is not None else {}
            self.announce("interruption", registered, **held)
        # A failure being recovered needs no "needs you" notice.
        self.tell_needs_you([entry for entry in found if entry["interruption_id"] not in taken]
                            if taken else found, since)
