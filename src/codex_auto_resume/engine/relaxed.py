"""What the edition's plug may relax (v0.6.14 stage 3b), and the bounds core holds every answer to.

Two gates core keeps, each asked of the plug: P17 (domain/plug.py), whether a failure core never
recovers alone is taken up when it is detected (engine/detect.py); and known_failure, whether such a
record goes on when it falls due (engine/dispatch.py). An answer is taken only if core offered it
(failures.takes, failures.readmits), and is carried out within core's own bounds (ladder.py): what was
taken up waits core's own waits, ends a day on the clock after it was detected, and is claimed only as
a relaxation the plug's ledger pays for (store/ledger.py); a capacity error retried sooner (CAPACITY)
counts against core's capacity bounds, for twelve hours on the clock from its task's first failure.
And P7 (EARLY): a record that waits for a usage limit to reset may be looked at before its time, once a
window, where every wait it meets is its gate vector alone - it keeps its state, reason and next look; from
v0.6.14 so may one a usage read found waiting for usage (waiting_for_usage), as the claim takes it too.
And P7 (SEND_NOW): a waiting record a person asked to send now passes its retry's wait, a postponement,
the spacing between two continuations, the objection window and an attempt budget of the person's own -
never a reset ahead, quiet hours or an administrator's MaxRecoveryAttempts - and every other gate holds,
in the engine and again in the claim. The standard edition's plug is asked nothing here: a record taken
up under another edition ends unsent at its next look, and that is all.
"""
from __future__ import annotations

from .. import failures, ladder, machine
from ..domain.plug import DEFER, PACED_AS, Alternative, Point

# How often a failure P17 did not take up is put to it again, at most.
UNADMITTED_SECONDS = 60
# What the claim's ledger pays for of each relaxation (P11's `carried`).
RELAXED_POINTS = {"admitted": frozenset({Point.GATES}), "capacity": frozenset({Point.GATES}),
                  "early": frozenset({Point.SCHEDULE}), "resend": frozenset({Point.SCHEDULE}),
                  "forced": frozenset({Point.SCHEDULE})}
# The waits a record may be looked at early in: a usage limit's, and (v0.6.14) a wait for usage a usage
# read found unavailable - the claim's own list (ladder.EARLY_STATES), so a look early is claimed too.
EARLY_STATES = ladder.EARLY_STATES
# How many records of a task are read back, at most, for the kinds of failure it has had (v0.6.14): more
# than any task's continuations (ladder.CAPACITY_PER_DAY), so only a broken chain reaches it.
CHAIN_WALK = 64


class RelaxedMixin:
    def chain_started_at(self, row):
        """When a record's task first failed, on the clock (v0.6.14): its chain's origin's detected_at,
        or None once that record is gone - never chain_first_detected_at, which each wait aside moves."""
        if row["chain_origin_id"] == row["interruption_id"]:
            return row["detected_at"]
        origin = self.store.get(row["chain_origin_id"])
        return origin["detected_at"] if origin is not None else None

    def chain_categories(self, row):
        """Every kind of failure a record's task has had, up to and with `row` (v0.6.14): the records
        from `row` back to its chain's origin, each its parent's child, as a sorted tuple - or None
        where one of them is gone, or the chain never reaches its origin, so nothing says it is all."""
        found, seen = set(), set()
        while row is not None and row["interruption_id"] not in seen and len(seen) < CHAIN_WALK:
            found.add(row["category"])
            if row["interruption_id"] == row["chain_origin_id"]:
                return tuple(sorted(found))
            seen.add(row["interruption_id"])
            parent = row.get("parent_interruption_id")
            row = self.store.get(parent) if isinstance(parent, str) else None
        return None

    def _unadmit(self, key, now):
        """A failure P17 did not take up: asked again a minute from now at the soonest."""
        if len(self._unadmitted) > 512:
            self._unadmitted.clear()
        self._unadmitted[key] = now

    def _taken_up(self, record, shape, owner, progress, carry, admissible, now):
        """P17 for one failure: (the answer core carries out, the record of its task it continues), or
        None for a failure core never recovers alone that is left alone. DEFER is core's own way.

        Asked only with an answer core would carry out (failures.takes), and never for a failure of
        that kind core would register already stopped - a cancelled or handed-over task, a budget
        spent (domain/gates.py, birth_stop) - so nothing is taken up to be stopped at birth."""
        facts = dict(shape or {}, category=record["category"])
        offered = failures.takes(facts, self.recovers) if shape is not None else frozenset()
        if not offered:
            return None if admissible else (DEFER, None)
        parent = self.store.chain_parent(record["thread_id"], record["turn_id"], owner)
        if admissible and machine.birth_stop(parent, progress, self.limits(), False, now=now,
                                             legacy_carry=carry) is not None:
            self._unadmit(record["interruption_id"], now)
            return None
        chain = None if parent is None else {
            **{name: parent[name] for name in ("interruption_id", "category", "recovery_attempts",
                                               "chain_continuations", "detected_at")},
            "chain_started_at": self.chain_started_at(parent), "categories": self.chain_categories(parent)}
        if chain is not None and not self.capacity_open(chain["chain_started_at"], now):
            offered -= {Alternative.CAPACITY}        # twelve hours on the clock from its first failure
        if not offered:
            return None if admissible else (DEFER, parent)
        answer = self.plug.admission({
            **{name: record[name] for name in ("interruption_id", "thread_id", "turn_id", "category",
                                               "started_at", "completed_at", "ordinal")},
            **facts, "takes": offered, "chain": chain})
        if answer is not DEFER and answer not in offered:
            answer = DEFER
        if admissible and answer is DEFER:
            self._unadmit(record["interruption_id"], now)
            return None
        return answer, parent

    @staticmethod
    def capacity_open(started_at, now) -> bool:
        """Whether a task's capacity retries may go on (CAPACITY): its first failure, on the clock, less
        than twelve hours ago (ladder.CAPACITY_MAX_SECONDS). One whose first failure is gone may not."""
        return started_at is not None and now - started_at < ladder.CAPACITY_MAX_SECONDS

    def _capacity_wait(self, parent) -> int:
        """How long a capacity error the plug vouches for waits: core's own step for the attempt at its
        task (ladder.CAPACITY_WAITS), always lengthened by up to a fifth, never shortened."""
        steps = ladder.CAPACITY_WAITS
        wait = steps[min(parent["recovery_attempts"], len(steps) - 1) if parent is not None else 0]
        return ladder.jittered(wait, {"retry_jitter": True}, self.draw())

    def _admitted_wait(self, parent, detection, owner) -> int:
        """How long a failure taken up with ADMIT waits: core's own wait for the attempt at its task
        (ladder.ADMITTED_WAITS), never less than an unknown failure's first wait, jitter as set."""
        steps = ladder.ADMITTED_WAITS
        wait = steps[min(parent["recovery_attempts"], len(steps) - 1) if parent is not None else 0]
        if self.policy_values.get("retry_jitter") is True:
            wait = ladder.jittered(wait, self.policy_values, self.draw())
        return max(wait, self.detection_wait(failures.UNKNOWN, thread_id=detection["thread_id"],
                                             turn_id=detection["turn_id"], owner=owner))

    def _known_failure(self, row, vector, now):
        """The known_failure gate: None to go on as core goes on, the relaxation core carries out
        for this record ("admitted", "capacity"), or False once it waits or has ended.

        A kind core recovers goes on as it always did while its switch is on, and is then put to
        the plug like any gate core passed: CAPACITY relaxes a server error's retries, within core's
        capacity bounds and for twelve hours on the clock from its task's first failure, after which
        the standard edition's budgets hold it again. A kind it never recovers alone is a record P17
        took up (failures.ADMISSIBLE): it goes on only while the plug takes it up again with a word
        that kind takes (failures.readmits), and for a day on the clock at most (ladder.py). Without
        such a word it ends unsent - NULL's answer, a hook that failed, a capability turned off -
        except under Observe only, when no plug may be asked and it waits, ended by nothing."""
        category = row["category"]
        poll = self.options["conservative_poll_seconds"]
        if failures.is_recoverable(category):
            if not self.recovers(category):
                vector["known_failure"] = machine.gate(machine.BLOCK, "category_disabled")
                self._wait(row, row["state"], "category_disabled", poll, vector)
                return False
            vector["known_failure"] = machine.gate(machine.PASS)
            if vector["consent"][0] != machine.PASS:
                return None
            answer = self.plug.gate("known_failure", self._chained(row), dict(vector))
            if self._held("known_failure", row, vector, answer):
                return False
            if (answer is Alternative.CAPACITY and failures.readmits(category, answer)
                    and self.capacity_open(self.chain_started_at(row), now)):
                vector["known_failure"] = machine.gate(machine.PASS, machine.PLUGGED)
                return "capacity"
            return None
        if vector["consent"][0] != machine.PASS:
            vector["known_failure"] = machine.gate(machine.UNKNOWN, machine.OBSERVE_ONLY)
            self._wait(row, row["state"], row.get("last_error"), poll, vector)
            return False
        if self.plug.null or category not in failures.ADMISSIBLE:
            return self._not_recovered(row, vector, "not_recoverable")
        if now - row["detected_at"] >= ladder.ADMITTED_MAX_SECONDS:
            return self._not_recovered(row, vector, "admission_expired")
        answer = self.plug.gate("known_failure", self._chained(row), dict(vector))
        if self._held("known_failure", row, vector, answer):
            return False
        if not failures.readmits(category, answer):
            return self._not_recovered(row, vector, "not_recoverable")
        if answer in PACED_AS and not self.recovers(PACED_AS[answer]):
            vector["known_failure"] = machine.gate(machine.BLOCK, "category_disabled")
            self._wait(row, row["state"], "category_disabled", poll, vector)
            return False
        vector["known_failure"] = machine.gate(machine.PASS, machine.PLUGGED)
        return "admitted"

    @staticmethod
    def relaxed_points(relaxed) -> frozenset:
        """The points a relaxation's send carries, for the ledger to pay (RELAXED_POINTS)."""
        return RELAXED_POINTS.get(relaxed, frozenset())

    def _early(self, row, vector, now, quiet_until) -> bool:
        """P7 asked early (EARLY): whether a record that waits for a usage limit to reset is looked at
        now. Only with consent, only while the plug wants the schedule, never past a postponement or
        quiet hours, and only while core's early window is open: one every five minutes for every
        record together, as long as one usage reading lasts (ladder.EARLY_SPACING, EARLY_WINDOW)."""
        if (self.plug.null or vector["consent"][0] != machine.PASS
                or row["category"] != failures.USAGE_LIMIT or row["state"] not in EARLY_STATES
                or vector["schedule"][1] not in ("not_due", "waiting_reset")
                or machine.gate_schedule(row, now, quiet_until=quiet_until, early=True)[0] != machine.PASS):
            return False
        opened = self._early_at
        inside = opened is not None and 0 <= now - opened < ladder.EARLY_WINDOW
        if not inside and opened is not None and 0 <= now - opened < ladder.EARLY_SPACING:
            return False
        if not self.plug.wants(Point.SCHEDULE):
            return False
        self._schedule_said = self.plug.schedule(row, machine.eligible_at(row))
        if self._schedule_said is not Alternative.EARLY:
            return False
        if not inside:
            self._early_at = now
        self._early_look = row["interruption_id"]
        vector["schedule"] = machine.gate(machine.PASS, machine.PLUGGED)
        return True

    def _send_now(self, row, vector, now, quiet_until) -> bool:
        """P7 at a schedule core refused (SEND_NOW): whether a person's Send now passes it, for this
        look. Only with consent, only while the plug wants the schedule, and only where the refusal is
        the retry's wait or a postponement and the schedule passes without them - so a record a reset
        still ahead or quiet hours hold is not asked about at all, and waits exactly as it would have.
        Asked once a look: the early look's answer is the one taken, where it asked."""
        if (self.plug.null or vector["consent"][0] != machine.PASS
                or vector["schedule"][1] not in machine.FORCEABLE
                or machine.gate_schedule(row, now, quiet_until=quiet_until, forced=True)[0] != machine.PASS
                or not self.plug.wants(Point.SCHEDULE)):
            return False
        said = self._schedule_said
        if said is None:
            said = self._schedule_said = self.plug.schedule(row, machine.eligible_at(row))
        if said is not Alternative.SEND_NOW:
            return False
        vector["schedule"] = machine.gate(machine.PASS, machine.SEND_NOW)
        return True

    def _own_budget(self, row, vector):
        """A person's Send now passes an attempt budget spent under their own setting alone - never
        one an administrator's MaxRecoveryAttempts holds (machine.own_budget_only)."""
        if (vector["attempt_budget"] == (machine.BLOCK, "recovery_budget")
                and machine.own_budget_only(row, self.managed.max_recovery_attempts)):
            vector["attempt_budget"] = machine.gate(machine.PASS, machine.SEND_NOW)

    def forced_limits(self, limits) -> dict:
        """`limits` as a Send now's claim is told them: with the administrator's MaxRecoveryAttempts,
        which the claim holds it to as the engine does (store/claims.py)."""
        return dict(limits, managed_max_recovery_attempts=self.managed.max_recovery_attempts)

    def _parked(self, row, vector) -> bool:
        """While `row` is looked at early, a wait is its gate vector alone: True, and it keeps its
        state, its reason and its next look. False for every other record, which waits as it would."""
        if self._early_look is None or self._early_look != row["interruption_id"]:
            return False
        self.store.record_gates(row["interruption_id"], vector, self.clock())
        return True

    def _chained(self, row):
        """A record as known_failure is put to the plug: with when its task first failed, on the
        clock (`chain_started_at`), read only while the plug wants the gates."""
        if not self.plug.wants(Point.GATES):
            return row
        return dict(row, chain_started_at=self.chain_started_at(row))

    def _not_recovered(self, row, vector, reason):
        """End a record P17 took up that nothing takes up any more: nothing is sent."""
        vector["known_failure"] = machine.gate(machine.BLOCK, reason)
        self.store.record_gates(row["interruption_id"], vector, self.clock())
        self.transition(row, "terminal_failure", reason)
        return False
