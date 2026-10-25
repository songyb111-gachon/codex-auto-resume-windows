"""What a person asks for, and nothing that sends.

Every method here changes a flag, a schedule or a budget. None of them hands anything to
Codex: the watcher is the only thing that does, and it stays the only thing that does.
"""
from __future__ import annotations

import time

from .. import homes, machine, oncewords, power, projects, quiet, settings
from ..machine import CLAIMED, OBSERVING, WAITING
from ..store import TERMINAL, StoreError
from ..store.actions import CHANGED, RECHECKED, RETIRED, UNRESOLVED
from ..store.schedule import USAGE_BY_RESCAN
from ..win import network
from ..windows import WakeEvent
from .errors import (ControlError,
                     _REFUSALS_POSTPONE,
                     _REFUSALS_RELEASE,
                     _REFUSALS_RESTORE,
                     _REFUSALS_RETRY,
                     _REFUSALS_UNPOSTPONE,
                     _identifier,
                     _refusal,
                     _thread_id)
from .records import _other_homes, _reader

# v0.6.19 (the review of 2026-10-24): why Retry now asked for no usage reading, in the reply's note (store/schedule.py
# NOT_CHECKED's first five words, which the Dashboard says in its own words).
_NOT_CHECKED_NOTES = {"paused": "recovery is paused", "conversation_off": "recovery is off for this conversation",
                      "observe_only": "Observe only is on", "quiet_hours": "it is quiet hours",
                      "offline": "Windows reports no internet"}




def _reads_usage(record, now) -> bool:
    """Whether a person's click reads Codex's usage for `record` (v0.6.19, issue #50; A12 amended by the owner on
    2026-10-24): a usage limit's reset still ahead, waiting unsent and uncancelled, nothing held, no postponement of the
    person's own ahead. The one rule of Retry now ("check one") and Rescan ("check all"), and the window's CanRetryNow
    offers Retry now on exactly these where nothing else in view stops it (tests/test_usage_clicks_window.py)."""
    return (record["category"] == "usage_limit" and record["state"] in WAITING and not record["cancel_requested"]
            and record["submitted_at"] is None and (record["reset_at"] or 0) > now
            and (record["not_before"] or 0) <= now and not record.get("hold"))


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
        # v0.6.11: DisableAutoResume keeps recovery paused (managed.py); a pause is always taken.
        if enabled and self.managed().disable_auto_resume:
            raise ControlError("recovery is paused by your administrator", code="managed_by_policy")
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
            found = {"thread_id": thread, "enabled": store.thread_enabled(thread)}
        if not enabled:
            self.plug.conversation_off(thread)
        return found

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
        # What the edition's plug holds there of its own ends too, at once (H5; domain/plug.py).
        self.plug.conversation_off(thread)
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
        bypass the loaded-thread requirement and does not skip revalidation: the watcher
        still runs the entire pipeline. From v0.6.19 (issue #50; A12 amended by the owner on
        2026-10-24), for a usage limit whose reset is still ahead, it also asks the watcher to
        read usage once, at the look it brings forward: if Codex says the limit has lifted, the
        reset is the newer one and every gate runs as usual; still limited, unknown or a failed
        read changes nothing. With no watcher running, nothing is read, and it says so
        (`usage_check`: asked, not_running, or None where no reading was asked for). Only a person's
        click in the Dashboard asks (actor "gui"); MCP's retry_now reads nothing, as before. Under a
        Pause, the conversation's recovery off, Observe only, quiet hours or no internet while the
        watcher waits for one, nothing is asked and `usage_check` says which (the review of
        2026-10-24: the click and the watcher agree).
        """
        key = _identifier(interruption_id)
        with self._open() as store:
            record = store.get(key)
            if record is None:
                raise ControlError("no such interruption", code="no_such_interruption")
            accepted, detail = store.request_retry_now(key, time.time(), actor=actor)
            now = time.time()
            # Only a person's click, and only where the watcher would read: a usage limit's reset still ahead, nothing
            # held, no postponement of the person's own. What would stop the watcher reading is said, not asked.
            wanted = accepted and actor == "gui" and _reads_usage(record, now)
            blocked = self._not_checked(store, record, now) if wanted else None
            check = wanted and blocked is None and store.ask_usage_check(key, now)
        if not accepted:
            message, code = _refusal(_REFUSALS_RETRY, detail)
            raise ControlError(message, code=code)
        woke = False
        try:
            woke = WakeEvent(str(self.paths.state_dir)).signal()
        except Exception:
            woke = False
        usage_check = blocked
        if check and not woke:
            # Asked now or not at all: a watcher that starts later reads usage when the recovery is due, as always.
            with self._open() as store:
                store.usage_check_taken(key)
            usage_check = "not_running"
        elif check:
            usage_check = "asked"
        now = time.time()
        if blocked is not None:
            note = "usage was not checked: %s; it waits for the reset Codex gave" % _NOT_CHECKED_NOTES[blocked]
        elif usage_check == "asked":
            note = ("checking usage now: if Codex says the limit has lifted, the recovery goes on through "
                    "every safety check; otherwise it waits for the reset Codex gave")
        elif usage_check == "not_running":
            note = "the watcher is not running, so usage was not checked; it waits for the reset Codex gave"
        elif detail > now + 1 and (record["reset_at"] or 0) >= detail:
            note = ("the usage reset is at a later time; the watcher checks then, and every "
                    "safety check still applies")
        elif detail > now + 1:
            # v0.6.11: a postponement, or an objection window, which Retry now never shortens.
            note = ("it is postponed to a later time, which this does not shorten; the watcher "
                    "checks then, and every safety check still applies")
        elif woke:
            note = "checking now; every safety check still applies"
        else:
            note = "the watcher checks at its next poll; every safety check still applies"
        return {"interruption_id": key, "state": record["state"], "eligible_at": detail,
                "woke": woke, "note": note, "usage_check": usage_check}

    def _not_checked(self, store, record, now):
        """What would stop the watcher reading usage for `record` now, in store/schedule.NOT_CHECKED's words, or None:
        a Pause, the conversation's recovery off, Observe only, quiet hours, or no internet while the watcher waits for
        one - each as the watcher reads it, so the click never promises a reading the watcher will not make."""
        stored = store.settings()
        if not stored["enabled"]:
            return "paused"
        if not store.thread_enabled(record["thread_id"]):
            return "conversation_off"
        try:
            values = self.get_settings()
        except Exception:
            values = {}
        if stored.get("observe_only") or values.get("observe_only"):
            return "observe_only"
        if quiet.quiet_until(now, values) is not None:
            return "quiet_hours"
        if power.waits_for_network(values):
            try:
                if network.internet() is False:
                    return "offline"
            except Exception:
                pass
        return None


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
            found = {"interruption_id": key, "thread_id": thread,
                     "enabled": store.thread_enabled(thread), "state": record["state"]}
        if not enabled:
            self.plug.conversation_off(thread)
        return found

    # --------------------------------------------------- postponing and holding (v0.6.11)
    @staticmethod
    def _postpone_until(now, until, preset, minutes):
        """The one time a postponement asks for, from exactly one of its three ways to say it: a
        time, one of the offered choices (quiet.PRESETS), or a number of minutes."""
        given = [value for value in (until, preset, minutes) if value is not None]
        if len(given) != 1:
            raise ControlError("that is not a time to postpone a recovery to", code="invalid_time")
        if preset is not None:
            when = quiet.postpone_time(now, preset) if isinstance(preset, str) else None
        elif minutes is not None:
            # A count of whole minutes; how far ahead it may go is the store's to say (too_far).
            when = (now + 60.0 * minutes if isinstance(minutes, int) and not isinstance(minutes, bool)
                    and minutes >= 1 else None)
        else:
            when = until
        if when is None:
            raise ControlError("that is not a time to postpone a recovery to", code="invalid_time")
        return when

    def postpone(self, interruption_id, thread_id, *, until=None, preset=None, minutes=None,
                 actor: str = "gui") -> dict:
        """Postpone one exact waiting recovery: it is not sent before the time asked for.

        Bound to both identities, as the per-task switch is, and checked against the record as it
        is now. It only ever makes a record later - never earlier than now, or than a postponement
        it already has, and never more than a week ahead - and it writes that time and nothing
        else: it sends nothing and skips no gate. Retry now never shortens it (store.request_retry_now); Don't
        postpone (unpostpone) is how a person takes it away."""
        key = _identifier(interruption_id)
        thread = _thread_id(thread_id)
        now = time.time()
        when = self._postpone_until(now, until, preset, minutes)
        with self._open() as store:
            accepted, detail = store.postpone(key, thread, when, now, actor=actor)
            state = (store.get(key) or {}).get("state")
        if not accepted:
            message, code = _refusal(_REFUSALS_POSTPONE, detail)
            raise ControlError(message, code=code)
        return {"interruption_id": key, "thread_id": thread, "state": state, "not_before": detail,
                "note": "not sent before then; every safety check still applies"}

    def unpostpone(self, interruption_id, thread_id, *, actor: str = "gui") -> dict:
        """Don't postpone: take away one exact record's postponement, a person's own (v0.6.11).

        Retry now never shortens a postponement, so this is how a person undoes their own. Bound to
        both identities, as postponing is, and only ever back to what the schedule says without it:
        an objection window still ahead stays, and so do the retry's wait, a usage reset and quiet
        hours. It sends nothing and skips no gate. Offered in the Dashboard and the popup, never to
        a model (it brings a send nearer, and MCP has no tool for it)."""
        key = _identifier(interruption_id)
        thread = _thread_id(thread_id)
        with self._open() as store:
            accepted, detail = store.unpostpone(key, thread, time.time(), actor=actor)
            record = store.get(key) if accepted else None
        if not accepted:
            message, code = _refusal(_REFUSALS_UNPOSTPONE, detail)
            raise ControlError(message, code=code)
        try:
            woke = bool(WakeEvent(str(self.paths.state_dir)).signal())
        except Exception:
            woke = False
        eligible = machine.eligible_at(record) if record else None
        return {"interruption_id": key, "thread_id": thread, "state": record["state"] if record else None,
                "not_before": detail, "eligible_at": eligible, "woke": woke,
                "note": "no longer postponed; every safety check still applies"}

    def release_hold(self, interruption_id, thread_id, *, actor: str = "gui") -> dict:
        """Let one exact held recovery continue: the one thing that takes a hold away.

        A conversation that asks first, or only notifies, holds what it detects for a person;
        this is that person saying continue, for this record and no other. Bound to both
        identities. It sends nothing and skips no gate: the watcher still checks everything,
        and a postponement or quiet hours still hold it."""
        key = _identifier(interruption_id)
        thread = _thread_id(thread_id)
        with self._open() as store:
            released, detail = store.release_hold(key, thread, time.time(), actor=actor)
        if not released:
            message, code = _refusal(_REFUSALS_RELEASE, detail)
            raise ControlError(message, code=code)
        try:
            woke = bool(WakeEvent(str(self.paths.state_dir)).signal())
        except Exception:
            woke = False
        return {"interruption_id": key, "thread_id": thread, "state": detail, "woke": woke,
                "note": "nothing is sent now; every safety check still applies"}

    # ------------------------------------------------------- words for this time (v0.6.16-beta.3)
    def once_words(self, interruption_id) -> dict:
        """One interruption's words for this time, as they are read and checked again (oncewords.py), for the
        Dashboard's dialog alone: no MCP tool reads them and the panel never shows them."""
        key = _identifier(interruption_id)
        text = oncewords.OnceWords.of(self.paths).words(key)
        return {"interruption_id": key, "set": text is not None, "text": text}

    def set_once_words(self, interruption_id, thread_id, text) -> dict:
        """Words for this time for one exact waiting recovery (v0.6.16-beta.3): `text`, added once after the next
        continuation it sends - or None, or nothing but spaces, to take them away (always allowed: it only reduces).

        A Custom message in every way (A27): refused, if it is, in the Custom message's validator's own words, and
        only for a record that still waits - bound to its conversation as a row's click is. The Dashboard's alone,
        from a row of Pending: no MCP tool calls this and update_settings has no such field, because words a model
        set would be sent later, on the person's behalf. Nothing is sent now, and nothing is woken: adding words
        starts, speeds and skips nothing."""
        key = _identifier(interruption_id)
        thread = _thread_id(thread_id)
        held = oncewords.OnceWords.of(self.paths)
        if text is None or (isinstance(text, str) and not text.strip()):
            if not held.remove(key):
                raise ControlError("the state is busy", code="state_busy")
            return {"interruption_id": key, "thread_id": thread, "set": False}
        self.validated_text(text)

        def still_waiting():
            # Under the file's lock (oncewords.put): the watcher looks at the words again under the same lock after
            # its claim (engine/delivery.py), so a claim can never fall between this check and the write - words
            # written here either go with the next continuation or are refused now, never deleted unsent.
            with self._open() as store:
                record = self._bound_record(store, key, thread)
            state = record["state"]
            if record["cancel_requested"]:
                raise ControlError("that recovery was cancelled", code="cancel_requested")
            if state in CLAIMED:
                raise ControlError("that recovery is being sent now", code="being_sent")
            if state in OBSERVING:
                raise ControlError("that recovery is already running in Codex", code="observing")
            if state not in WAITING:
                raise ControlError("that recovery is already in Codex", code="in_flight")

        still_waiting()                 # refused before the lock, as before, for a record that plainly does not wait
        try:
            held.put(key, text, guard=still_waiting)
        except oncewords.OnceWordsError as exc:
            if exc.code == "too_many_messages":
                raise ControlError(str(exc), code="too_many_messages") from None
            if exc.code == "state_busy":
                raise ControlError("the state is busy", code="state_busy") from None
            raise ControlError(str(exc), code="request_failed") from None
        return {"interruption_id": key, "thread_id": thread, "set": True}

    def set_thread_tier(self, thread_id, tier, *, interruption_id=None, actor: str = "gui") -> dict:
        """How much one conversation asks before it is resumed: a tier of its own, or None for
        the default in Settings.

        A tier that asks a person - Ask me first, Only notify me - also holds what the
        conversation has waiting and unsent. One that asks less lets nothing go that is already
        held. Chosen from a task's row, the click carries that row's interruption too, and is
        refused if the record has gone, finished or is another conversation's."""
        thread = _thread_id(thread_id)
        if tier is not None and tier not in settings.TIERS:
            raise ControlError("invalid tier", code="invalid_tier")
        with self._open() as store:
            if interruption_id is not None:
                record = store.get(_identifier(interruption_id))
                if record is None:
                    raise ControlError("no such interruption", code="no_such_interruption")
                if record["thread_id"] != thread:
                    raise ControlError("that recovery belongs to a different conversation",
                                       code="thread_mismatch")
                if record["state"] in TERMINAL:
                    raise ControlError("that recovery has already finished", code="already_finished")
            result = store.set_thread_tier(thread, tier, time.time(), actor=actor)
        return {"thread_id": thread, "tier": result["tier"], "held": result["held"]}

    def set_project_rule(self, interruption_id, thread_id, always, *, source=None,
                         actor: str = "gui") -> dict:
        """Always, or Never, for the project one exact task's conversation is filed under (v0.6.11).

        Chosen from the task's row, so the click carries its interruption and its conversation and is
        refused if the record has gone, finished or is another conversation's. The project is read
        through `source` - Codex's own state, read-only - as a key and nothing more (projects.py),
        and the key is written into Settings' Always or Never list. Never also holds, for a person,
        what waits unsent in that project; Always lets nothing go that is held. Nothing is sent."""
        key, thread = _identifier(interruption_id), _thread_id(thread_id)
        if not isinstance(always, bool):
            raise ControlError("always must be true or false", code="invalid_enabled")
        with self._open() as store:
            record = self._bound_record(store, key, thread)
        # v0.6.18: each record's project read through its own Codex home's reader, as Pending labels it
        # (control/records.py) - the default home's state has no conversation of a home Settings added.
        others, readers, seen = _other_homes(self.get_settings().get(homes.FIELD)), {}, {}

        def project_of(row):
            home, reader = others.get(row.get("home_key") or ""), source
            if home is not None and source is not None:
                if home[1] not in readers:
                    readers[home[1]] = _reader(source, home[1])
                reader = readers[home[1]]
            mark = (row.get("home_key") or "", row["thread_id"])
            if mark not in seen:
                seen[mark] = self._project_of(reader, row["thread_id"])
            return seen[mark]
        project = project_of(record)
        if project is None:
            raise ControlError("the project of that conversation cannot be read",
                               code="project_unreadable")
        try:
            changes = projects.rule(self.get_settings(), project, always)
        except ValueError:
            raise ControlError("at most %d projects can be listed" % projects.MAX_KEYS,
                               code="too_many_projects") from None
        saved = self.update_settings(changes)
        allowed, held = projects.allows(saved, project), 0
        if not allowed:
            with self._open() as store:
                keys = []
                for row in store.pending():
                    if row["hold"] is not None or row["state"] not in WAITING:
                        continue
                    if project_of(row) == project:
                        keys.append(row["interruption_id"])
                held = store.hold_waiting(keys, projects.hold_for(saved, project), time.time(), actor=actor)
        return {"thread_id": thread, "always": always, "project_policy": saved["project_policy"],
                "allowed": allowed, "held": held}

    @staticmethod
    def _bound_record(store, key, thread) -> dict:
        """The record a row's click names, refused if it is gone, finished or another conversation's."""
        record = store.get(key)
        if record is None:
            raise ControlError("no such interruption", code="no_such_interruption")
        if record["thread_id"] != thread:
            raise ControlError("that recovery belongs to a different conversation", code="thread_mismatch")
        if record["state"] in TERMINAL:
            raise ControlError("that recovery has already finished", code="already_finished")
        return record

    @staticmethod
    def _project_of(source, thread_id):
        """A conversation's project key, read through `source`, or None when it cannot be read."""
        try:
            return None if source is None else source.project_key(thread_id)
        except Exception:
            return None

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

    def rescan_pending(self, judge, *, actor: str = "gui", read_usage: bool = False) -> dict:
        """Rescan and reconcile (v0.6.16, issue #39): every waiting recovery looked at again, on a person's word, each
        by its own interruption id.

        `judge(row, kin)` answers (outcome, reason) for one waiting record - `kin` is every record this product holds
        of its conversation - by the watcher's own rules (rescan.judge_for, handed in by the bridge: this layer builds
        no reader and no engine of its own). Only a record that still waits, unsent and not cancelled, is asked about;
        one claimed, in Codex, followed or cancelled is left exactly as it is, and so is every finished record and
        all of History. Each finding is applied in a transaction of its own that reads the record again and skips it
        if it changed meanwhile (store.rescan_apply): retired - superseded by a person's newer work, final - or left
        to wait as it was, rechecked or unresolved. Nothing is sent, nothing is written to Codex, no budget is given
        back and no schedule is brought forward: this is no Retry now for everything, which the layer deliberately
        does not offer (cancel_all_pending). The watcher is woken once after a recheck, to look now at whatever is
        due anyway.

        v0.6.19 (the owner's decision of 2026-10-24, "check all"): with `read_usage` - the Dashboard's click alone, its
        bridge's `rescan`; nothing else asks it - Codex's usage is read once for every recovery that still waits for a
        usage reset ahead after the reconcile (_reads_usage, Retry now's own rule): one request each, served at each
        one's next look and all answered by one reading (engine/freshness.py), none of their schedules brought forward.
        A recovery whose limit Codex says lifted goes on through every gate, as with Retry now. Under a Pause, Observe
        only, quiet hours or no internet while the watcher waits for one nothing is asked, and `usage_check` says why;
        a conversation switched off is passed over (said where it is the only one); with no watcher running nothing
        stays asked and it says so. `usage_check` (asked, not_running, one of store/schedule.NOT_CHECKED, or None where
        nothing waits for a usage reset) and `usage_asked` (how many) are in the reply."""
        with self._open() as store:
            everything = store.all_records()
        waiting = [row for row in everything if row["state"] in WAITING and not row["cancel_requested"]
                   and row["submitted_at"] is None and row["queue_id"] is None]
        counts = {RETIRED: 0, RECHECKED: 0, UNRESOLVED: 0, CHANGED: 0}
        found = []
        for row in waiting:
            kin = [other for other in everything if other["thread_id"] == row["thread_id"]]
            try:
                outcome, reason = judge(row, kin)
            except Exception:
                outcome, reason = UNRESOLVED, "unreadable"
            if outcome not in (RETIRED, RECHECKED):
                outcome = UNRESOLVED            # whatever else a judge answers decides nothing
            try:
                with self._open() as store:
                    applied = store.rescan_apply(row["interruption_id"], row, outcome, time.time(),
                                                 reason=reason, actor=actor)
            except Exception as failed:
                # Nothing was applied - the transaction was rolled back - and the scan goes on to the next record.
                # This one is unresolved, and said so in its journal if the store can still write that much.
                busy = isinstance(failed, (ControlError, StoreError))
                applied, outcome, reason = None, UNRESOLVED, "state_busy" if busy else "apply_failed"
                try:
                    with self._open() as store:
                        if not store.rescan_apply(row["interruption_id"], row, UNRESOLVED, time.time(), actor=actor):
                            outcome, reason = CHANGED, None
                except Exception:
                    pass
            if applied is False:
                outcome, reason = CHANGED, None
            counts[outcome] += 1
            found.append({"interruption_id": row["interruption_id"], "thread_id": row["thread_id"],
                          "outcome": outcome, "reason": reason})
        read_usage = read_usage is True and actor == "gui"
        usage_check, asked = self._ask_usage_for_all() if read_usage else (None, [])
        woke = False
        if counts[RECHECKED] or asked:
            try:
                woke = bool(WakeEvent(str(self.paths.state_dir)).signal())
            except Exception:
                woke = False
        if asked and not woke:
            # Asked now or not at all, as Retry now: a watcher that starts later reads usage when each recovery is due.
            with self._open() as store:
                for key in asked:
                    store.usage_check_taken(key)
            usage_check = "not_running"
        reply = {"scanned": len(waiting),
                 "not_waiting": sum(1 for row in everything if row["state"] not in TERMINAL) - len(waiting),
                 "retired": counts[RETIRED], "rechecked": counts[RECHECKED], "unresolved": counts[UNRESOLVED],
                 "changed": counts[CHANGED], "records": found, "woke": woke}
        if read_usage:
            reply.update(usage_check=usage_check, usage_asked=len(asked) if usage_check == "asked" else 0)
        return reply

    def _ask_usage_for_all(self):
        """Rescan's reading (v0.6.19): (usage_check, the ids asked for). One request for each recovery that waits for a
        usage reset ahead (_reads_usage) and that nothing stops the watcher reading for; what stops it said where none is
        asked - a reason every one shares (paused, observe only, quiet hours, offline) before one of its own."""
        now = time.time()
        with self._open() as store:
            rows = [row for row in store.all_records() if _reads_usage(row, now)]
            if not rows:
                return None, []
            blocked = {row["interruption_id"]: self._not_checked(store, row, now) for row in rows}
            open_ = [row["interruption_id"] for row in rows if blocked[row["interruption_id"]] is None]
            if not open_:
                shared = [why for why in blocked.values() if why != "conversation_off"]
                return (shared[0] if shared else "conversation_off"), []
            asked = [key for key in open_ if store.ask_usage_check(key, now, source=USAGE_BY_RESCAN)]
        return ("asked" if asked else "held"), asked

    def clear_history(self, *, actor: str = "gui") -> dict:
        """Hide finished recoveries from the History view. Deletes nothing, cancels
        nothing, and never hides a recovery that may still change."""
        with self._open() as store:
            return store.hide_history(time.time(), actor=actor)
