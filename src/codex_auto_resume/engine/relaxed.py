"""What the edition's plug may relax (v0.6.13 stage 3b), and the bounds core holds every answer to.

Two gates core keeps, each asked of the plug: P17 (domain/plug.py), whether a failure core never
recovers alone is taken up when it is detected (engine/detect.py); and known_failure, whether such a
record goes on when it falls due (engine/dispatch.py). An answer is taken only if core offered it
(failures.takes, failures.readmits), and is carried out within core's own bounds (ladder.py): what was
taken up waits core's own waits, ends a day on the clock after it was detected, and is claimed only as
a relaxation the plug's ledger pays for (store/ledger.py); a capacity error retried sooner (CAPACITY)
counts against core's capacity bounds, for twelve hours on the clock from its task's first failure. The
standard edition's plug is asked nothing here: a record taken up under another edition ends unsent at
its next look, and that is all.
"""
from __future__ import annotations

from .. import failures, ladder, machine
from ..domain.plug import DEFER, PACED_AS, Alternative, Point

# How often a failure P17 did not take up is put to it again, at most.
UNADMITTED_SECONDS = 60


class RelaxedMixin:
    def chain_started_at(self, row):
        """When a record's task first failed, on the clock (v0.6.13): its chain's origin's detected_at,
        or None once that record is gone - never chain_first_detected_at, which each wait aside moves."""
        if row["chain_origin_id"] == row["interruption_id"]:
            return row["detected_at"]
        origin = self.store.get(row["chain_origin_id"])
        return origin["detected_at"] if origin is not None else None

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
            "chain_started_at": self.chain_started_at(parent)}
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
