"""The watcher's side of the power action after usage-limit recoveries (v0.6.12; poweraction.py decides).

Asked by the loop on the thread that ticks, right after it has kept this PC awake or let it go, so it
runs after the tick has observed, collected and attempted everything. Each look follows poweraction's
order: the file first - with none, or nothing armed, nothing else is read and Windows is asked nothing
(H14) - then the records, then Codex's history and counts (engine.activity), then Windows: whether the
action is still available, whether anybody else is signed in for a shut down, and whether anybody has
used this PC for two minutes. Only then does a countdown start, with its notice, and the loop looks
every 15 seconds while it runs (`cap`).

A countdown ends at the first look that finds anything in the way: a check that waits, input since it
began, a gap of over 90 seconds between two looks, a stop, a pause, a tick that failed, the watcher
stopping. A stop a person pressed is read first, at every look and in any phase, and ends the batch
skipped: pressing the button is itself input, which would otherwise only end the countdown and let
the next one start. When the countdown runs out, the batch is ended done in the file under its lock
before anything is done - a write that fails does nothing - and only then is the keep-awake request let
go, the line logged, the last notice raised and Windows asked, once. A refusal is logged and said; the
batch is spent, so nothing is retried.

Nothing here sends anything to Codex, changes a record, or changes a setting of Windows'. A failure
inside a look costs that look, as keeping awake's does: the loop records it and ends any countdown.
"""
from __future__ import annotations

import time

from .. import poweraction as decision
from ..domain.power_vocabulary import PowerAction, PowerEnd, PowerPhase, PowerRepeat, PowerWait
from ..logbook import render
from ..win import powerdown

# The notices this raises, by their event names (notifier.POWER_EVENTS).
GRACE, NOW, FAILED, NOT_MET = "power_grace", "power_now", "power_failed", "power_not_met"
# Why a countdown ended, beside a PowerWait or a PowerEnd: input since it began, a gap between two
# looks, the arming gone or held by an administrator, a look that failed, the watcher stopping.
INPUT, GAP, TURNED_OFF, FAILED_LOOK, STOPPING = "input", "gap", "turned_off", "failed", "watcher_stopped"


class AfterWork:
    """One watcher's countdown and what it remembers between looks. `control` is the control layer (its
    power-action methods), `notice(event, detail, final=False)` raises a power notice, `port` is
    win/powerdown.py or a test's stand-in with the same names."""

    def __init__(self, *, control, log, notice, port=powerdown, clock=time.time):
        self._control, self._log, self._notice, self._port, self._clock = control, log, notice, port, clock
        # The countdown, while one runs: its nonce, action, when it began and ends, and the last look.
        self._countdown = None
        # This watcher saw a member of the batch open, for the nonce it saw it under (step 10).
        self._seen = (None, False)
        # The last wait logged and the last `shown` written, each for its nonce; the arming last seen;
        # and whether a file that cannot be believed has been logged.
        self._said, self._shown, self._known, self._invalid = None, None, None, False

    @property
    def counting(self) -> bool:
        return self._countdown is not None

    def cap(self, interval):
        """The loop's wait: at most COUNTDOWN_LOOK_SECONDS while a countdown runs, else `interval`."""
        return min(interval, decision.COUNTDOWN_LOOK_SECONDS) if self._countdown is not None else interval

    # ---------------------------------------------------------------- one look
    def look(self, store, engine, *, ok, waking=None, settings=None, managed=None):
        """One look after a tick. `ok` is whether the tick succeeded; `settings` the settings in force
        and `managed` the administrator's keys (managed.Managed), both read only once something is
        armed."""
        now = self._clock()
        why, document = self._control.read_power_action(now)
        armed = (document or {}).get("armed") if why == decision.READ_OK else None
        self._note(why, armed)
        held = bool(getattr(managed, "disable_power_action", False))
        paused, rows, follow = False, (), decision.FOLLOW_SECONDS
        if armed is not None and not held and armed["stop_at"] is None and ok:
            paused = self._paused(store, settings, managed)
            if not paused:
                rows = tuple(store.all_records())
                follow = _follow_window(engine)
        nonce = armed["nonce"] if armed is not None else None
        if self._countdown is not None and self._countdown["nonce"] != nonce:
            self._stop_countdown(TURNED_OFF)        # armed again, or ended elsewhere: not this batch
        saw = self._seen[1] if self._seen[0] == nonce and nonce is not None else False
        found = decision.decide(decision.Facts(now=now, read=why, document=document, managed=held, ok=ok,
                                               paused=paused, rows=rows, saw_open=saw, follow_window=follow))
        if nonce is not None:
            self._seen = (nonce, found.saw_open)
        if found.verdict == decision.OFF:
            return self._off(armed, found.word)
        if found.verdict == decision.WAIT:
            return self._wait(armed, found.word, now)
        if found.verdict == decision.END:
            return self._end(armed, found.word, now)
        return self._go(armed, rows, engine, waking, now)

    def _go(self, armed, rows, engine, waking, now):
        """Steps 11 to 16, once steps 1 to 10 have passed."""
        batch = decision.members(rows, armed)
        threads = sorted({row.get("thread_id") for row in batch if isinstance(row.get("thread_id"), str)})
        word = decision.judge_activity(engine.activity(threads) if engine is not None else None)
        if word is not None:
            return self._wait(armed, word, now)
        action = armed["action"]
        available, _reason = self._port.available(action)
        if not available:
            return self._end(armed, PowerEnd.UNAVAILABLE, now)
        if action == PowerAction.SHUT_DOWN:
            # Step 13 alone: idle is step 14's, asked only once nobody else is signed in.
            word = decision.judge_presence(action, self._port.other_sessions(), decision.IDLE_SECONDS)
            if word is not None:
                return self._wait(armed, word, now)
        idle = self._port.idle_seconds()
        countdown = self._countdown
        if countdown is None:
            # Step 14 alone: nobody else signed in was step 13's, asked above for a shut down only.
            word = decision.judge_presence(PowerAction.SLEEP, 0, idle)
            if word is not None:
                return self._wait(armed, word, now)
            return self._start(armed, now)
        if type(idle) not in (int, float) or idle != idle or idle < 0:
            return self._wait(armed, PowerWait.IDLE_UNKNOWN, now)
        if not decision.countdown_holds(countdown["started"], countdown["last_look"], now, idle):
            gap = abs(now - countdown["last_look"]) > decision.GAP_SECONDS
            self._stop_countdown(GAP if gap else INPUT)
            return self._wait(armed, None if gap else PowerWait.PERSON_ACTIVE, now, shown=True)
        countdown["last_look"] = now
        if now >= countdown["until"]:
            return self._finish(armed, waking, now)
        return None

    # ---------------------------------------------------------------- what a look comes to
    def _note(self, why, armed):
        """Log a file that cannot be believed once, an arming made in the Dashboard once, and an arming
        that went once - not one this watcher ended itself."""
        if why == decision.READ_INVALID:
            if not self._invalid:
                self._line("power_file_invalid")
            self._invalid = True
        elif why != decision.READ_UNREADABLE:
            self._invalid = False
        if why == decision.READ_UNREADABLE:
            return
        nonce = armed["nonce"] if armed is not None else None
        if armed is not None and nonce != self._known and armed["since"] == armed["armed_at"]:
            self._line("power_armed", armed["action"], len(armed["carried"]))
        elif armed is None and self._known is not None:
            self._line("power_off", TURNED_OFF)
        self._known = nonce

    def _off(self, armed, word):
        self._stop_countdown(word or TURNED_OFF)
        if word == decision.OFF_MANAGED and armed is not None and self._said != (armed["nonce"], word):
            self._said = (armed["nonce"], word)
            self._line("power_off", word)

    def _wait(self, armed, word, now, *, shown=False):
        """Wait: any countdown ends, and what is waited for is shown and logged once per change. A wait
        with no word of its own (a tick that failed, a file not read just now) keeps what is shown."""
        if self._countdown is not None:
            self._stop_countdown(word or FAILED_LOOK)
        if armed is None or (word is None and not shown):
            return None
        self._show(armed, {"phase": PowerPhase.WAITING.value, "waiting_for": word, "grace_until": None})
        if word is not None and self._said != (armed["nonce"], word):
            self._said = (armed["nonce"], word)
            self._line("power_waiting", word)
        return None

    def _end(self, armed, result, now):
        """The batch ends without the power action, as `result` says."""
        self._stop_countdown(result)
        if not self._control.power_batch_end(armed["nonce"], result, now):
            return None                         # not written: the next look sees the same again
        self._forget()
        self._line("power_batch_ended", result)
        if result == PowerEnd.NOT_MET and armed["repeat"] == PowerRepeat.ONCE:
            self._raise(NOT_MET, {"action": armed["action"]})
        elif result == PowerEnd.UNAVAILABLE:
            self._raise(FAILED, {"action": armed["action"]})
        return None

    def _start(self, armed, now):
        """Step 15: a countdown, shown, said once, and logged."""
        until = now + armed["grace_seconds"]
        self._countdown = {"nonce": armed["nonce"], "action": armed["action"], "started": now,
                           "last_look": now, "until": until}
        self._show(armed, {"phase": PowerPhase.GRACE.value, "waiting_for": None, "grace_until": until})
        self._said = None
        self._line("power_countdown", armed["action"], armed["grace_seconds"])
        self._raise(GRACE, {"action": armed["action"], "until": until, "nonce": armed["nonce"]})
        return None

    def _finish(self, armed, waking, now):
        """Step 16: the end written first, under the lock - skipped if a stop came meanwhile - and only
        then the keep-awake request let go, the line, the last notice, and Windows asked, once."""
        self._countdown = None
        ended = self._control.power_batch_finish(armed["nonce"], now)
        if ended is None:
            self._line("power_countdown_ended", "unwritten")
            return None
        self._forget()
        if ended != PowerEnd.DONE:
            self._line("power_batch_ended", ended)
            return None
        action = armed["action"]
        if waking is not None:
            try:
                waking.let_go()
            except Exception:
                pass                            # the request goes with the PC either way
        self._line("power_now", action)
        try:
            self._notice(NOW, {"action": action}, final=True)
        except Exception:
            pass                                # a notice never decides the action (E11)
        try:
            done = self._port.act(action) is True
        except Exception:
            done = False
        if not done:
            try:
                error = self._port.last_error()
            except Exception:
                error = None
            self._line("power_failed", None, error if type(error) is int and error >= 0 else "?")
            self._control.power_refused(self._clock())
            self._raise(FAILED, {"action": action})
        return None

    # ---------------------------------------------------------------- the rest
    def halt(self, reason=FAILED_LOOK) -> None:
        """A look that failed, or a tick that cannot look: any countdown ends, and nothing is done."""
        self._stop_countdown(reason)

    def stop(self) -> None:
        """The watcher stops: a countdown simply ends - nothing is done - and the file says the watcher
        is not watching, so the Dashboard shows no countdown that is not running."""
        countdown = self._countdown
        self._stop_countdown(STOPPING)
        if countdown is not None:
            try:
                self._control.power_show(countdown["nonce"], {"phase": PowerPhase.WAITING.value,
                                                              "waiting_for": PowerWait.WATCHER.value,
                                                              "grace_until": None})
            except Exception:
                pass

    def _stop_countdown(self, reason) -> None:
        if self._countdown is not None:
            self._countdown = None
            self._line("power_countdown_ended", reason)

    def _forget(self) -> None:
        """A batch this watcher ended: what it remembered of it goes with it."""
        self._seen, self._said, self._shown, self._known = (None, False), None, None, None

    def _show(self, armed, shown) -> None:
        """What the Dashboard shows, written only when it changed for this nonce. Display only."""
        wanted = (armed["nonce"], tuple(sorted(shown.items())))
        if wanted != self._shown:
            # Asked once per change: False is mostly "it says that already", and a write Windows
            # refused costs the display only, until the next change.
            self._control.power_show(armed["nonce"], shown)
            self._shown = wanted

    def _raise(self, event, detail) -> None:
        try:
            self._notice(event, detail)
        except Exception:
            pass                                # a notice never decides the action (E11)

    def _line(self, code, reason=None, detail=None) -> None:
        try:
            self._log(render(None, code, None if reason is None else str(reason),
                             None if detail is None else str(detail)))
        except Exception:
            pass

    @staticmethod
    def _paused(store, settings, managed) -> bool:
        """Step 5: recovery paused - the state's switch or an administrator's DisableAutoResume - or
        Observe only, in the state or in the settings."""
        stored = store.settings()
        return (not stored["enabled"] or bool(getattr(managed, "disable_auto_resume", False))
                or bool(stored.get("observe_only")) or (settings or {}).get("observe_only") is True)


def _follow_window(engine) -> float:
    """How long the engine follows an uncertain submission, so the two never disagree (still_followed)."""
    try:
        window = engine.options["unknown_reconcile_window_seconds"]
    except Exception:
        return decision.FOLLOW_SECONDS
    return float(window) if type(window) in (int, float) and window > 0 else decision.FOLLOW_SECONDS
