"""Turning what Codex recorded into records this product owns.

Detection registers a failure once, under an id derived from the failure itself, so the same
interruption seen twice is the same record - and a record whose turn is no longer the thread's
latest is superseded rather than recovered.

v0.6.14 (stage 3b): the edition's plug is asked at P17 (domain/plug.py) about a failure core never
recovers alone - and one it does, which it may relax - once that failure has passed every check core
makes of one: its conversation on, not known, its kind not switched off, from the last hour, and not
a task core would stop the moment it was registered. Only an answer core offered is taken
(failures.takes), and only while the plug wants to be asked; otherwise this reads what it read. How
it is asked, and what is carried out of an answer, is engine/relaxed.py's.
"""
from __future__ import annotations

from .. import failures, guards, ladder, machine, needsyou
from ..machine import OBSERVING, TERMINAL, WAITING, WATCHED
from ..codex import HistoryNotYet, admissible as admissible_failure, detect
from ..domain import ids, skips
from ..domain.plug import DEFER, PACED_AS, Alternative, Point
from .compaction import COMPACTED
from .relaxed import UNADMITTED_SECONDS

# v0.6.16-beta.3 (issue #27): how far before the look-back window failed turns are still read, to say once
# that each came before it (A16) - the longest look-back Settings allow.
PASSED_OVER_SECONDS = 7 * 86400
# The most (turn, reason) pairs and explained turns kept, the oldest let go first; and the most skip lines one
# check writes - the rest are counted in one line, so a watcher never floods its log (a start over a home with
# hundreds of failed turns, say). What a watcher before this one already wrote is not written again
# (logbook.EngineLog reads it back).
SKIPS_KEPT = 20000
SKIPS_AT_ONCE = 20


def _keep(held: dict, key) -> bool:
    """Whether `key` is new to `held`, which it joins - the oldest let go past SKIPS_KEPT, never all at once."""
    if key in held:
        return False
    if len(held) >= SKIPS_KEPT:
        held.pop(next(iter(held)))
    held[key] = True
    return True


class DetectMixin:
    def waiting_state(self, row) -> str:
        """The wait a record returns to when it goes back to waiting now."""
        return machine.waiting_state(row, self.clock())

    def _records(self, states):
        """This engine's own home's records in `states` (v0.6.15-beta): never another home's."""
        return self.store.records_in(states, home_key=self.home_key)

    def _claimed(self, thread_id):
        """This home's records that may have put a continuation into `thread_id` (store.claimed_on_thread)."""
        return [row for row in self.store.claimed_on_thread(thread_id) if row["home_key"] == self.home_key]

    def _keyed(self, found):
        """A failure as this engine's home knows it (v0.6.15-beta): its id derived with the home's key, which
        the default home's never is - so the same turn in two homes is two interruptions."""
        if found is not None and self.home_key:
            found["interruption_id"] = ids.interruption_id(
                found["thread_id"], found["turn_id"], found["completed_at"], found["ordinal"], home_key=self.home_key)
        return found

    def valid_interruption(self, row):
        """Whether the record is still its conversation's latest failure: an identity check and only
        that. One the edition's plug took up (failures.ADMISSIBLE) is found as it was taken up, never by
        `detect`; nothing that lets it be sent rests on this (engine/dispatch.py, store/claims.py)."""
        latest = self.source.latest(row["thread_id"])
        if not latest:
            return False
        if self.compacted_since(row, latest):           # v0.6.16-beta.4: still the one (engine/compaction.py)
            return True
        found = self._keyed(admissible_failure(latest) if row["category"] in failures.ADMISSIBLE
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
        if progress.get("later_turn") and not self._only_wrap_ups_after(row):
            return "superseded_by_user", "later_turn_exists"
        return "superseded", "latest_turn_changed"

    def _only_wrap_ups_after(self, row) -> bool:
        """Whether every turn after this record's is one a wrap-up of this product's started (v0.6.16-beta.3): then
        the failure that follows is the one recovered, and this one is superseded - never by the person's work."""
        thread = row["thread_id"]
        if not self._wrap_up_markers().get(thread):
            return False
        try:
            later = self.source.later_turns(thread, row["ordinal"], self.proof(row))
        except Exception:
            return False
        return bool(later) and not self.persons_turns(thread, later)

    def detection_since(self, settings) -> float:
        """Where the look-back window opens (A16): automatic recovery turned on, minus the look-back."""
        return max(0.0, settings["armed_at"] - self.options["detection_lookback_seconds"])

    def not_taken_up(self, record):
        """Why a failure the history brought is still not taken up, by the engine's own records and Settings:
        (reason, kind word) of domain/skips.py, or None. The order collect asks in; the Diagnostics check
        asks the same (checkup.py)."""
        if not self.store.thread_enabled(record["thread_id"]):
            return skips.CONVERSATION_OFF, None
        if not self.recovers(record["category"]):
            return skips.CATEGORY_OFF, skips.kind(record["category"])
        return None

    def _skip(self, thread_id, turn_id, reason, kind=None):
        """One line for a failed turn not taken up, once per turn and reason (logbook.skipped)."""
        if _keep(self._skips_told, (turn_id, reason)):
            self.log(thread_id, "not_taken_up", (turn_id, reason, kind))

    def _say_passed_over(self, since, asking):
        """Why each failed turn the history did not bring was passed over (codex/history.py `passed_over`),
        once per turn; and how many failed turns the check saw, when that number changes. Never costs the
        tick: what cannot be read is said nothing about."""
        # Before the window only once each time it opens where it does (a start, a re-arm): what failed later is
        # never before it, so each check after reads the window alone.
        before = max(0.0, since - PASSED_OVER_SECONDS) if self._passed_since != since else since
        self._passed_since = since
        try:
            read = self.source.passed_over(since, before, known=frozenset(self._passed_known))
        except Exception:
            return
        said = []
        for entry in read["passed"]:
            reason = entry["reason"]
            # One the edition's plug may take up is not said to be passed over before it was asked (P17) - all but an
            # invalid request, which it takes up for one code alone (v0.6.16-beta.4): said as ever, whatever its code.
            if reason == skips.NOT_RECOVERED and asking and entry["category"] in failures.ADMISSIBLE - {COMPACTED}:
                continue
            if _keep(self._passed_known, entry["turn_id"]) and reason is not None:
                said.append(entry)
        # The newest first, SKIPS_AT_ONCE of them, and how many more in one line.
        said.sort(key=lambda entry: entry["completed_at"] or 0, reverse=True)
        for entry in said[:SKIPS_AT_ONCE]:
            self._skip(entry["thread_id"], entry["turn_id"], entry["reason"], entry["kind"])
        for entry in said[SKIPS_AT_ONCE:]:
            _keep(self._skips_told, (entry["turn_id"], entry["reason"]))
        if len(said) > SKIPS_AT_ONCE:
            self.log(None, "not_taken_up_more", str(len(said) - SKIPS_AT_ONCE))
        if read["seen"] != self._seen_failed:
            self._seen_failed = read["seen"]
            self.log(None, "failed_turns_seen", str(read["seen"]))

    # --------------------------------------------------------------- collect
    def _owner(self, thread_id, turn_id):
        """Which of our records put its continuation into this turn, if any."""
        candidates = [row for row in self._claimed(thread_id)
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
        previous = [row for row in self._claimed(detection["thread_id"])
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
        since = self.detection_since(settings)
        # v0.6.11: the same read also brings the failures a needs-you notice is raised for, only while
        # one is on (needsyou.kinds) - none of which `detect` takes, so none becomes a record. At the
        # defaults it is v0.6.10's read exactly.
        kinds = needsyou.kinds(self.policy_values)
        # v0.6.14: and, while the edition's plug wants P17, the failures it may take up and every
        # error's shape - never while only observing or while an administrator disables recovery (K5).
        asking = (self.plug.wants(Point.ADMISSION) and not self.observing(settings)
                  and not self.managed.disable_auto_resume)
        extra = {"admissible": True, "shapes": True} if asking else {}
        try:
            found = (self.source.latest_failures(since, needs_you=kinds, **extra) if kinds
                     else self.source.latest_failures(since, **extra))
        except HistoryNotYet:
            # v0.6.26 final: a fresh home - its state holds no conversation, and Codex makes its history with the first
            # one it saves - has nothing to detect yet: a detection that read nothing, not one that could not read.
            return
        for raw in found:
            shape, admissible = raw.pop("shape", None), raw.pop("admissible", False)
            record = self._keyed(detect(raw))
            admissible = record is None and admissible
            if admissible:
                record = self._keyed(admissible_failure(raw))
            if record is None:
                continue
            why = self.not_taken_up(record)
            if why is not None and why[0] == skips.CONVERSATION_OFF:
                self._skip(record["thread_id"], record["turn_id"], *why)
                continue
            if self.store.get(record["interruption_id"]) is not None:
                continue
            category = record["category"]
            if why is not None:
                # Logged once per interruption: the user switched this off deliberately,
                # so it is a fact worth being able to find, not a repeating complaint.
                if record["interruption_id"] not in self._declined:
                    if len(self._declined) > 512:
                        self._declined.clear()
                    self._declined.add(record["interruption_id"])
                    self.log(record["thread_id"], "category_recovery_disabled", category)
                self._skip(record["thread_id"], record["turn_id"], *why)
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
                                       legacy_carry=carry, limits=limits, hold=hold, home_key=self.home_key,
                                       **facts):
                continue
            registered = self.store.get(detection["interruption_id"])
            if admissible:
                self.log(detection["thread_id"], "failure_taken_up", detection["interruption_id"])
                _keep(self._passed_known, detection["turn_id"])      # never said passed over after (v0.6.16-beta.4)
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
        # v0.6.16-beta.3: and why every other failed turn of the read was passed over (issue #27).
        self._say_passed_over(since, asking)
        # A failure being recovered needs no "needs you" notice: one a record holds is left out there,
        # on this tick and every later one (engine/notices.py).
        self.tell_needs_you(found, since)
