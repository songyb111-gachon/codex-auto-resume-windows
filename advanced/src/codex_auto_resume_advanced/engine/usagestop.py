# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The forced stop near a usage limit (v0.6.16-beta.4, item (h) of the owner's additions to issue #29) - usage_pause.

At the stop percentage a person chose for a window (97 by default, each window its own, apart from the stop the
wrap-up's words ask for), the window is held until it resets, as the plain pause held it: core's records wait (HOLD)
and the edition's own continuations are not handed to core. And now each conversation switched on whose turn is
running is stopped - through the Codex app's own channel, the IPC pipe the app's Stop button uses (codex/ipc.py,
measurement MIPC): the stop the person would make, once for that window. It works only for a conversation the app has
open; where it cannot stop one - the app does not hold it, the app is not running, its build checks another version of
the request, it does not answer - it falls back to holding, and a notice says the turn could not be stopped.

A stopped conversation's queue is paused by the app, and the pause survives the app's restart. When the window resets, a conversation it stopped is continued once - Continue after the reset,
the wrap-up's choice, on by default - by a turn started through the same channel (ipc.start_turn), which goes past the
paused queue; only while that turn of the stop is still the conversation's latest, ended, with nothing after it (A17)
and the app holds the conversation (A11). It is kept in `continuations` (ContinuationKind.AFTER_RESET, its window's
length in minutes in `chain`), so a restart forgets nothing; where the app does not hold the conversation it waits, and
a notice says to open it in Codex. That turn is also what lets the queue go: once it completes, the app sends what was
queued and the pause is gone (measured 2026-10-16). Where Continue after the reset is off, nothing will, and a notice
asks the person to press Resume in Codex.

Every outcome is one closed word, journalled (registry codes); never a conversation's words.
"""
from __future__ import annotations

from codex_auto_resume import continuation, settings
from codex_auto_resume.domain import ids
from codex_auto_resume.domain.plug import DEFER
from codex_auto_resume.domain.plughands import Widening

from .. import statement
from ..codex import inuse, ipc
from ..codex.turns import Turns
from ..vocabulary import ContinuationKind, ContinuationReason, OptionKey, RecordState
from .continued import answer_key, words_pass
from .usage import AFTER_RESET_KEY, EVERY_CONVERSATION, NOTICE_FOR, ON, WRAP_UP, UsagePause, _reset_since
FINAL = frozenset({"completed", "failed", "interrupted"})
# How many notices the stop keeps for the icon to show (each once in a watcher's life, by its key).
NOTICES_KEPT = 16
# A start after the reset that failed is asked again after this long, doubled at each failure up to BACKOFF_MOST - never
# every tick, each of which may wait for the app's answers.
BACKOFF_SECONDS = 300
BACKOFF_MOST = 3600


class _StopErrand:
    """P8's errand, run by core last in the tick with its guards (domain/plughands.Errand): the stops due and the
    continuations after a reset, each request to the app written inside one of core's errand guards - so a Pause,
    Observe only, an administrator's DisableAutoResume and quiet hours hold both, as they hold every send."""
    __slots__ = ("code", "view", "targets", "window")

    def __init__(self, code, view, targets, window):
        self.code, self.view, self.targets, self.window = code, view, targets, window

    def run(self, guard):
        if self.targets:
            self.code.stop_all(self.targets, self.window, guard)
        try:
            self.code.after_reset(self.view, guard)
        except Exception:
            pass
        return None


class UsageStop(UsagePause):
    """usage_pause's code from v0.6.16-beta.4: the pause's holding, and the forced stop and its continuation after
    the reset. `stop`, `start` and `home` are seams a test fills (ipc.stop_turn, ipc.start_turn, the Codex home)."""
    __slots__ = ("_stop", "_start", "_home", "_notices", "_backoff", "_stopped")

    def __init__(self, paths, *, stop=None, start=None, home=None):
        super().__init__(paths)
        self._stop = stop
        self._start = start
        self._home = home
        self._notices = []
        self._backoff = {}                   # {continuation: (failures, when it is asked again)}, in this process
        self._stopped = []                   # the windows stopped, (bucket, minutes, reset_at): once each per reset

    # ---------------------------------------------------------------- reading Codex
    def _codex_home(self):
        return self._home if self._home is not None else inuse.home(self.paths)

    def _source(self):
        """Core's reader, judging a conversation as core does - a person's own, or P19's widening while Recover every
        conversation is on - and never a kind Codex makes for itself (as the wrap-up judges one)."""
        from codex_auto_resume.codex import LocalSource
        source = LocalSource(self._codex_home())
        try:
            widened = self._scoped.armed(EVERY_CONVERSATION) is True
        except Exception:
            widened = False
        source.widened = frozenset({Widening.EVERY_DESKTOP}) if widened else frozenset()
        return source

    def _locale(self):
        try:
            return continuation.resolve_locale(settings.load(self.paths.settings_file))
        except Exception:
            return None

    # ---------------------------------------------------------------- P8
    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        newly, targets = self._once(self._mark()), []
        if newly:
            try:
                targets = self._running(view)
            except Exception:
                targets = []
        if not targets and not self._waiting():
            return DEFER
        return _StopErrand(self, view, targets, newly[0] if newly else None)

    def _once(self, newly) -> list:
        """The windows newly held that were not stopped already for this reset: a window switched off and on again
        is held again, but a turn the person resumed in it is not stopped a second time."""
        fresh = []
        for row in newly:
            key = (row["bucket"], row["minutes"], row["reset_at"])
            if key not in self._stopped:
                self._stopped.append(key)
                fresh.append(row)
        del self._stopped[:-NOTICES_KEPT]
        return fresh

    def _running(self, view) -> list:
        """(thread, turn) of each conversation switched on, of the kind core recovers, whose latest turn runs."""
        turns, source, found = Turns(self._codex_home()), self._source(), []
        for thread in turns.running():
            try:
                if view.thread_enabled(thread) is not True or source.latest(thread) is None:
                    continue
                turn = turns.latest(thread)
            except Exception:
                continue
            if turn is not None and turn.status == "inProgress":
                found.append((thread, turn))
        return found

    def stop_all(self, targets, window, guard=None):
        """The errand: each running turn stopped through the app, inside one of core's guards (`guard`); what came of
        each journalled and, where it matters, said in a notice; each one stopped remembered for its continuation after
        the reset. One the guard refused is not asked, and nothing is said of it."""
        stop = self._stop or ipc.stop_turn
        for thread, turn in targets:
            try:
                word = stop(thread, turn.turn_id, gate=guard)
            except Exception:
                word = ipc.Stop.BROKEN
            if word == ipc.Stop.HELD:
                self._count("held")
                continue
            if word not in (ipc.Stop.STOPPED, ipc.Stop.UNCONFIRMED):
                self._count("not_stopped")
                self._notice("not_stopped", window)
                continue
            # A stop with no answer in time may have been made: kept as one, so the queue the app may have paused is
            # let go by the continuation after the reset, or the person asked to press Resume.
            self._count("stopped" if word == ipc.Stop.STOPPED else "stop_unconfirmed")
            if not self._remember(thread, turn, window):
                # No continuation after the reset will start a turn there, which is what lets the paused queue go.
                self._count("resume_unproven")
                self._notice("press_resume", window)
        return None

    def _remember(self, thread, turn, window) -> bool:
        """A conversation it stopped, kept for one continuation after its window resets - where Continue after the
        reset (the wrap-up's choice) is on. Whether one is kept."""
        scoped = self._scoped
        try:
            if scoped.options_of(WRAP_UP).get(OptionKey.WRAP_AFTER_RESET, ON) != ON:
                return False
            words = statement.CATALOGS.text(AFTER_RESET_KEY, self._locale())
            if not words_pass(words):
                return False
            key = answer_key(ContinuationKind.AFTER_RESET, thread, window["bucket"], window["minutes"],
                             window["reset_at"])
            if scoped.continuations.get(key) is None:
                scoped.continuations.add(key, ContinuationKind.AFTER_RESET, thread, words, ordinal=turn.ordinal,
                                         chain=window["minutes"])
            return True
        except Exception:
            return False

    def _waiting(self) -> list:
        """The continuations after a reset that wait."""
        try:
            return [row for row in self._scoped.continuations.mine() if row["record_state"] == RecordState.WAITING
                    and row["kind"] == ContinuationKind.AFTER_RESET and row["words"]]
        except Exception:
            return []

    def after_reset(self, view, guard=None) -> None:
        """Each conversation it stopped whose window has reset: continued once by a turn the app starts - its request
        written inside one of core's guards (`guard`), and waiting while that refuses - while the stopped turn is still
        its latest, ended, with nothing after it, and the app holds it; ended where newer work came; waiting, with a
        notice, where the app does not hold it."""
        scoped = self._scoped
        handle = scoped.continuations
        waiting = self._waiting()
        if not waiting:
            return
        try:
            # v0.6.18: while any window it holds has not reset - the weekly one still held when the five-hour one
            # resets - no continuation of its own starts either: the pause's own promise (holding()), which holds the
            # wrap-up's continuation after the reset the same way (`holds`).
            if self.holding():
                return
        except Exception:
            return
        now, rows = scoped.now(), scoped.meter.rows()
        turns, source, start = Turns(self._codex_home()), self._source(), self._start or ipc.start_turn
        for row in waiting:
            if not _reset_since(rows, row["chain"], row["created_at"], now):
                continue
            thread = row["thread_id"]
            try:
                if view.thread_enabled(thread) is not True:
                    continue
                if source.latest(thread) is None:
                    continue
                latest = turns.latest(thread)
            except Exception:
                continue
            if latest is None or latest.ordinal != row["ordinal"]:
                handle.end(ContinuationReason.SUPERSEDED, thread_id=thread)          # newer work came (A17)
                continue
            if latest.status not in FINAL:
                continue
            failures, again = self._backoff.get(row["record_id"], (0, 0))
            if now < again:
                continue                                                # failed lately: asked again later
            word = start(thread, row["words"] + "\n\n" + ids.short_marker(row["record_id"]), gate=guard)
            if word == ipc.Stop.HELD:
                continue                                                # held by core: asked again when it lets go
            if word == ipc.Stop.UNCONFIRMED:
                # v0.6.18: written, no answer in time - it may have started. Nothing is said of a failure: the next look
                # after the backoff finds a newer turn (ended SUPERSEDED, nothing sent twice) or starts it again.
                self._backoff[row["record_id"]] = (failures + 1,
                                                   now + min(BACKOFF_SECONDS * 2 ** failures, BACKOFF_MOST))
                continue
            if word == ipc.Start.STARTED:
                self._backoff.pop(row["record_id"], None)
                handle.end(ContinuationReason.SENT, thread_id=thread)
                self._count("continued")
            else:
                self._backoff[row["record_id"]] = (failures + 1,
                                                   now + min(BACKOFF_SECONDS * 2 ** failures, BACKOFF_MOST))
                self._count("not_continued")
                self._notice("not_continued", {"minutes": row["chain"], "reset_at": None, "bucket": "codex"})

    # ---------------------------------------------------------------- the icon's notices
    def _notice(self, kind, window) -> None:
        now = self._scoped.now()
        key = "%s:%s:%s" % (kind, window.get("minutes"), window.get("reset_at") or int(now // NOTICE_FOR))
        if any(notice["key"] == key for notice in self._notices):
            return
        self._notices.append({"key": key, "kind": kind, "window_minutes": window.get("minutes"), "at": now,
                              "reset_at": window.get("reset_at")})
        del self._notices[:-NOTICES_KEPT]

    def notices(self, now) -> list:
        """What the stop has to say to the icon now: the notices of the last NOTICE_FOR seconds - its key, kind
        (not_stopped, press_resume, not_continued), the window and its reset. Codes and numbers only."""
        return [{key: notice[key] for key in ("key", "kind", "window_minutes", "reset_at")}
                for notice in self._notices if 0 <= now - notice["at"] < NOTICE_FOR]


def make_stop(paths) -> UsageStop:
    return UsageStop(paths)
