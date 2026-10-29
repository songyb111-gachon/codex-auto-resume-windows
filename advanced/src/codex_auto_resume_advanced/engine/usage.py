# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Proactive usage, near a limit (v0.6.16-beta.3, issue #29): the usage meter, and the wrap-up and the pause that
need it.

The standard edition reads usage only when a recovery is due (C9), so near a limit it knows nothing until a turn
fails at it. Three capabilities, each off until a person turns it on:

* usage_meter (P8) - while the Codex app runs, reads usage on its own every POLL_MINUTES the person chose (5 to
  60, 15 by default), through one finite session of its own asking account/rateLimits/read alone, and keeps the
  windows as core keeps a reading (state/meter.py). The tooltip and the popup show it (surfaces.meter_view); and
  when the five-hour or the weekly window reaches the person's warning percentage (85 by default), a notice is shown
  once for that window - once for each reset, across restarts. It never satisfies core's usage gate: core reads its
  own live usage when a recovery is due, and nothing core decides reads this.
* usage_wrap_up (P8, P2), which requires the meter - at the person's wrap-up percentage of a window (90 by default),
  each conversation switched on whose latest turn is running is sent one message of the edition's own, once for
  that window: its words the person's choice of three (short, standard, detailed), a P2 WRAP_UP record core queues
  through `codex queue` as every continuation goes, so Codex delivers it when the running turn ends - and only while
  that turn is still the latest and still running (core's engine/plugrecords.py). The key is the conversation, the
  window and its reset (continued.answer_key), kept in `continuations`, so one window is answered once.
* usage_pause (P8, P3), which requires the meter - at the person's pause percentage of a window (95 by default), no
  further continuation from this product until that window resets: core's records wait at their gates (HOLD), and
  the edition's own continuations are not handed to core (`holds`, runtime.records). A person's own messages - a
  queued prompt, a message at a reset - and anything they type in Codex are not touched, nor is a wrap-up. The pause
  is marked on the window's row, so a restart keeps it, and it lets go when the window resets - its reset time
  passed, a reading shows the window reset early and below the percentage, or (v0.6.17) a reset credit of that
  very window was spent since the reading the pause rests on: the credit empties the window there and then, and
  the meter may be hours from reading it again, or never while the Codex app is closed, so holding on would
  spend the credit for nothing (`credit_resets`, `stale`).

The five-hour window is any bucket's 300-minute window, the weekly one any bucket's 10080-minute window; each stage
reads each window on its own percentage.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER, Alternative
from codex_auto_resume.domain.plughands import RECORDS_LIMIT, Widening

from codex_auto_resume import continuation, settings

from .. import statement

from ..codex import credits, inuse
from ..codex.turns import Turns
from ..vocabulary import (ContinuationKind, ContinuationReason, OptionKey, RecordState, SpendOutcome,
                          WordingKey)
from .continued import answer_key, handed
from .wrapwords import ON, SWITCH, DEFAULT_STYLE, STYLE_KEYS, STYLES, render  # noqa: F401 - the registry's, the tests'

METER, WRAP_UP, PAUSE = "usage_meter", "usage_wrap_up", "usage_pause"
# v0.6.20: the analytics, for which the meter keeps each reading as a sample while both stand on (state/analytics.py).
ANALYTICS = "usage_analytics"
# Recover every conversation (engine/everyconversation.py): while it is on, core takes up P19's widening, and so does
# the wrap-up - never more than core would recover.
EVERY_CONVERSATION = "every_conversation"
FIVE_HOUR, WEEKLY = 300, 10080
WINDOWS = (FIVE_HOUR, WEEKLY)
# The choices a person picks from: the meter's spacing in minutes, a percentage, the wrap-up's wording.
POLL_CHOICES = (5, 10, 15, 20, 30, 45, 60)
DEFAULT_POLL = 15
PERCENTS = (50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 96, 97, 98, 99)
# v0.6.16-beta.4 (f): what a person may type in beside the choices - any whole percentage, any spacing of 5 to 60.
PERCENT_RANGE = (1, 100)
POLL_RANGE = (5, 60)
# The forced stop's own percentage (usage_pause, v0.6.16-beta.4: 97, above the 95 the wrap-up's words ask for).
DEFAULT_WARN, DEFAULT_WRAP, DEFAULT_PAUSE = 85, 90, 97
# v0.6.16-beta.4: the stop percentage the wrap-up's words ask Codex to stop at (wrapwords.py), each window its own.
DEFAULT_STOP_WORDS = 95
STOP_WORDS_OPTIONS = {FIVE_HOUR: OptionKey.STOP_WORDS_FIVE_HOUR, WEEKLY: OptionKey.STOP_WORDS_WEEKLY}
# (g): the continuation after the reset (engine/usagestop.py says it for a conversation it stopped).
AFTER_RESET_KEY = "continue.after_reset"
# (e): each window acted on or not - from v0.6.16 final each capability's own pair (the owner's request of 2026-10-18):
# the meter's decides its warnings, the wrap-up's its messages, the stop's what it holds and stops. Until then the
# meter's pair decided for all three; state/session.py carries a window switched off there over to the other two once.
WINDOW_OPTIONS = {FIVE_HOUR: OptionKey.WINDOW_FIVE_HOUR, WEEKLY: OptionKey.WINDOW_WEEKLY}
# (b): the wrap-up's Custom text for each window (state `wordings`).
CUSTOM_WORDINGS = {FIVE_HOUR: WordingKey.WRAP_CUSTOM_FIVE_HOUR, WEEKLY: WordingKey.WRAP_CUSTOM_WEEKLY}
# Each capability's percentage option for each window.
STAGE_OPTIONS = {METER: {FIVE_HOUR: OptionKey.WARN_FIVE_HOUR, WEEKLY: OptionKey.WARN_WEEKLY},
                 WRAP_UP: {FIVE_HOUR: OptionKey.WRAP_FIVE_HOUR, WEEKLY: OptionKey.WRAP_WEEKLY},
                 PAUSE: {FIVE_HOUR: OptionKey.PAUSE_FIVE_HOUR, WEEKLY: OptionKey.PAUSE_WEEKLY}}
# A reading older than this is not acted on by the wrap-up: two of the longest spacings.
FRESH = 2 * 60 * max(POLL_CHOICES)
# A window is past its reset this long after the reset time (engine/resetwatch.CLOSE_AFTER).
CLOSE_AFTER = 60
# How long after a warning its notice is shown (the tray takes it from the next tick's surface).
NOTICE_FOR = 900
# The wrap-up looks at most once a minute.
LOOK_EVERY = 60
# The outcomes of a reset credit that reset the window it was spent on - the two engine/credits.py counts as a
# reset of its own (`own_reset`). An outcome not yet known, and the three that reset nothing, leave a pause
# standing.
CREDIT_RESET = (SpendOutcome.RESET, SpendOutcome.ALREADY_REDEEMED)


def percent(options, capability, minutes) -> int | None:
    """The percentage a capability's stage acts at for a window of `minutes`, from its options, or None."""
    key = STAGE_OPTIONS.get(capability, {}).get(minutes)
    value = options.get(key) if key is not None else None
    return value if type(value) is int else None


def reached(row, threshold, now) -> bool:
    """Whether a window's row is at or over `threshold` with its reset still ahead (and known)."""
    return (threshold is not None and row["used_percent"] >= threshold and type(row["reset_at"]) is int
            and now < row["reset_at"] + CLOSE_AFTER)


def windows(rows):
    """The rows of the five-hour and the weekly windows, any bucket's."""
    return [row for row in rows.values() if row["minutes"] in WINDOWS]


def credit_resets(scoped, rows) -> dict:
    """{(bucket, minutes): when the newest reset credit of that window was answered} for the windows of
    `rows`, from the spends this edition wrote (engine/credits.py, state/resets.credit_spends). Empty
    where none can be read: a pause is never let go on something unreadable.

    Every spend is read, not those written since some time: what settles a reading is when Codex
    ANSWERED the credit (`finished_at`), and a credit written long before a reading can be answered
    after it - asked once more with its own key ten minutes on, or answered late. Reading by when it
    was written would miss exactly the case the pause is here for. The table holds one spend for each
    filling of a window, two a day and seven a week at most, and is read only where a window is held."""
    if not rows:
        return {}
    try:
        spends = scoped.resets.credit_spends()
    except Exception:
        return {}
    found = {}
    for spend in spends:
        at = spend.get("finished_at")
        if spend.get("outcome") not in CREDIT_RESET or not isinstance(at, (int, float)):
            continue
        family = (spend.get("bucket"), spend.get("minutes"))
        if at > found.get(family, 0):
            found[family] = at
    return found


def stale(row, resets) -> bool:
    """Whether `row` was read before a reset credit of that very window was answered (v0.6.17, P-8):
    what it says of the window is from before the credit, so it is not full any more, whatever it says."""
    at = resets.get((row["bucket"], row["minutes"]))
    return at is not None and at >= (row["read_at"] or 0)


def _reset_since(rows, minutes, created_at, now) -> bool:
    """Whether the window of `minutes` has reset since `created_at`: the meter's row of it shows a window begun after, or
    the reset it showed has passed. With no row of it, a window's length after."""
    found = [row for row in windows(rows) if row["minutes"] == minutes]
    if not found:
        return now - created_at >= minutes * 60
    reset = found[0]["reset_at"]
    if type(reset) is not int:
        return False
    return now >= reset + CLOSE_AFTER or reset - minutes * 60 > created_at


def acting(options) -> frozenset:
    """The windows a person lets a capability act on (v0.6.16-beta.4, item (e)), from its own options: each one
    switched on - both by default. Both off, it acts on neither (the page says so); the meter still reads and shows
    usage whatever any switch says."""
    return frozenset(minutes for minutes, key in WINDOW_OPTIONS.items() if options.get(key, ON) == ON)


def _acting(scoped) -> frozenset:
    """The windows a capability acts on, as its own choices say (v0.6.16 final); every window where they cannot be
    read."""
    try:
        return acting(scoped.options())
    except Exception:
        return frozenset(WINDOWS)


class _Errand:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def run(self, guard):
        return self.code.look()


# ---------------------------------------------------------------------------- the meter
class UsageMeter:
    """usage_meter's code: its P8 errand. `session` and `app_running` are seams a test fills."""
    __slots__ = ("paths", "_scoped", "_session", "_app_running", "_looked")

    def __init__(self, paths, *, session=None, app_running=None):
        self.paths = paths
        self._scoped = None
        self._session = session
        self._app_running = app_running
        self._looked = None

    def bind(self, scoped):
        self._scoped = scoped

    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            spacing = scoped.options().get(OptionKey.POLL_MINUTES, DEFAULT_POLL) * 60
            now = scoped.now()
            read = [row["read_at"] for row in scoped.meter.rows().values()]
        except Exception:
            return DEFER
        last = max([*read, self._looked or 0]) if (read or self._looked) else None
        if last is not None and 0 <= now - last < spacing:
            return DEFER
        return _Errand(self)

    def _running(self) -> bool:
        """Whether the Codex app runs now: the meter reads only then (core's pairing, through the backend)."""
        if self._app_running is not None:
            return self._app_running() is True
        try:
            return inuse.backend(self.paths).app_identity() is not None
        except Exception:
            return False

    def _read(self):
        """One usage read through a finite session of the meter's own: the windows core keeps, or None."""
        if self._session is not None:
            opened = self._session()
        else:
            from ..codex.protocol import Session
            opened = Session(inuse.backend(self.paths), capability=METER)
        with opened as session:
            return credits.parse(session.call(credits.READ, {}))["windows"]

    def look(self):
        scoped = self._scoped
        handle = scoped.meter
        if not handle.on():
            return None
        now = scoped.now()
        if not self._running():
            return None
        self._looked = now
        try:
            found = self._read()
        except Exception:
            found = None
        if found is None:
            self._count("unreadable")
            return None
        handle.save(found)
        self._count("read")
        # v0.6.20: while usage_analytics stands on too, each reading is also kept as a sample for its pace.
        self._sample(found)
        options = scoped.options()
        on = acting(options)
        for row in windows(handle.rows()):
            if row["minutes"] not in on:
                continue                                   # (e) a window switched off for it: shown, never warned of
            if reached(row, percent(options, METER, row["minutes"]), now) and row["warned_reset_at"] != row["reset_at"]:
                if handle.mark(row["bucket"], row["minutes"], warned_reset_at=row["reset_at"]):
                    self._count("warned")
        return None

    def _sample(self, found) -> None:
        """The reading kept as samples (state/analytics.py) where usage_analytics stands on - never otherwise, and a
        sample that cannot be kept costs the reading nothing."""
        try:
            if self._scoped.armed(ANALYTICS):
                self._scoped.analytics.sample(found, at=self._scoped.now())
        except Exception:
            pass

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass


# ---------------------------------------------------------------------------- the wrap-up
class UsageWrapUp:
    """usage_wrap_up's code: at P8 the conversations to ask, at P2 the messages waiting."""
    __slots__ = ("paths", "_scoped", "_home", "_looked", "_turn")

    def __init__(self, paths, *, home=None):
        self.paths = paths
        self._scoped = None
        self._home = home
        self._looked = None
        self._turn = 0

    def bind(self, scoped):
        self._scoped = scoped

    def _codex_home(self):
        return self._home if self._home is not None else inuse.home(self.paths)

    def _source(self):
        """Core's own reader of the Codex home, judging a conversation as core does (codex/history._eligibility): a
        person's own - or, while Recover every conversation is on, P19's widening - and never a kind Codex makes for
        itself (a subagent, a review, a memory pass, an agent-made conversation). Its `latest` is None for any other."""
        from codex_auto_resume.codex import LocalSource
        source = LocalSource(self._codex_home())
        try:
            widened = self._scoped.armed(EVERY_CONVERSATION) is True
        except Exception:
            widened = False
        source.widened = frozenset({Widening.EVERY_DESKTOP}) if widened else frozenset()
        return source

    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        now = scoped.now()
        if self._looked is not None and 0 <= now - self._looked < LOOK_EVERY:
            return DEFER
        self._looked = now
        try:
            self._look(view, now)
        except Exception:
            pass
        try:
            self._after_reset(view, now)
        except Exception:
            pass
        return DEFER

    def _look(self, view, now) -> None:
        scoped = self._scoped
        handle = scoped.continuations
        if not handle.on():
            return
        options = scoped.options()
        on = _acting(scoped)
        due = [row for row in windows(scoped.meter.rows()) if row["minutes"] in on
               and now - row["read_at"] <= FRESH and reached(row, percent(options, WRAP_UP, row["minutes"]), now)]
        if not due:
            return
        # v0.6.16-beta.4: the words of each window due - with the numbers where that wording is chosen - in the
        # continuation language, made once a look (wrapwords.render).
        try:
            locale = continuation.resolve_locale(settings.load(self.paths.settings_file))
        except Exception:
            locale = None
        try:
            custom = scoped.wordings()
        except Exception:
            custom = {}
        worded = []
        for row in due:
            words = render(style=options.get(OptionKey.WRAP_STYLE, DEFAULT_STYLE), minutes=row["minutes"],
                           used=row["used_percent"], locale=locale,
                           stop_at=options.get(STOP_WORDS_OPTIONS[row["minutes"]], DEFAULT_STOP_WORDS),
                           reset_at=row["reset_at"], include_reset=options.get(OptionKey.WRAP_RESET_TIME, ON) == ON,
                           custom=custom.get(CUSTOM_WORDINGS.get(row["minutes"])))
            if words is not None:
                worded.append((row, words))
        if not worded:
            return
        turns = Turns(self._codex_home())
        source = self._source()
        for thread in turns.running():
            try:
                if view.thread_enabled(thread) is not True or source.latest(thread) is None:
                    continue                    # switched off, or not a conversation core would recover
                turn = turns.latest(thread)
            except Exception:
                continue
            if turn is None or turn.status != "inProgress":
                continue
            for row, words in worded:
                key = answer_key(WRAP_UP, thread, row["bucket"], row["minutes"], row["reset_at"])
                # Its window's length is kept in `chain` (v0.6.16-beta.4): what Continue after the reset reads it by.
                if handle.get(key) is None and handle.add(key, ContinuationKind.WRAP_UP, thread, words,
                                                          ordinal=turn.ordinal, chain=row["minutes"]):
                    self._count("found")

    def _after_reset(self, view, now) -> None:
        """Continue after the reset (v0.6.16-beta.4, item (g), on by default): a conversation sent a wrap-up that then
        ended well - its latest turn completed - is sent one continuation once the wrap-up's window resets, through
        core's queue as every continuation goes: only while that turn is still the latest, ended, with nothing after it
        (A17), and the app holds the conversation (A11), at core's gates. One that failed is core's recovery, one
        stopped is the forced stop's (engine/usagestop.py): each is noted and left. Once for each wrap-up."""
        scoped = self._scoped
        handle = scoped.continuations
        if not handle.on() or scoped.options().get(OptionKey.WRAP_AFTER_RESET, ON) != ON:
            return
        sent = [row for row in handle.mine(pending=None) if row["kind"] == ContinuationKind.WRAP_UP
                and row["reason"] in (ContinuationReason.DELIVERED, ContinuationReason.SENT) and row["chain"] in WINDOWS]
        if not sent:
            return
        rows, turns, source, words = scoped.meter.rows(), Turns(self._codex_home()), self._source(), None
        for wrap in sent:
            key = answer_key(ContinuationKind.AFTER_RESET, wrap["thread_id"], "wrap", wrap["chain"],
                             int(wrap["created_at"]))
            if handle.get(key) is not None or not _reset_since(rows, wrap["chain"], wrap["created_at"], now):
                continue
            thread = wrap["thread_id"]
            try:
                if view.thread_enabled(thread) is not True or source.latest(thread) is None:
                    continue
                latest = turns.latest(thread)
            except Exception:
                continue
            if latest is None or latest.status == "inProgress":
                continue                                          # still working: looked at again
            newer = _after_wrap_up(turns, thread, wrap["ordinal"], latest.ordinal)
            if newer is None:
                continue                                          # not read: looked at again
            if newer:
                handle.note(key, ContinuationKind.AFTER_RESET, thread, ContinuationReason.SUPERSEDED)
                continue                                          # newer work came after the wrap-up's own turn (A17)
            if latest.status != "completed":
                handle.note(key, ContinuationKind.AFTER_RESET, thread, ContinuationReason.HANDED_OVER)
                continue                                          # a failure is core's; a stop, the forced stop's
            if words is None:
                try:
                    words = statement.CATALOGS.text(AFTER_RESET_KEY,
                                                    continuation.resolve_locale(settings.load(self.paths.settings_file)))
                except Exception:
                    words = statement.CATALOGS.text(AFTER_RESET_KEY)
            if handle.add(key, ContinuationKind.AFTER_RESET, thread, words, ordinal=latest.ordinal,
                          chain=wrap["chain"]):
                self._count("continued")

    def records(self, view):
        """P2: every wrap-up waiting, with its words. One in flight is the runtime's to hand."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            rows = scoped.continuations.mine()
        except Exception:
            return DEFER
        waiting = [row for row in rows if row["record_state"] == RecordState.WAITING]
        # The wrap-ups go only into the very turn they were made for (_still_due); a continuation after the reset is
        # core's to check as every continuation is - its turn the latest, ended, nothing after it.
        later = [row for row in waiting if row["kind"] == ContinuationKind.AFTER_RESET]
        waiting = [row for row in waiting if row["kind"] != ContinuationKind.AFTER_RESET]
        if waiting:
            waiting = self._still_due(waiting, frozenset(row["thread_id"] for row in later))
        waiting += later
        found = [record for record in (handed(row) for row in waiting) if record is not None]
        # Core tries RECORDS_LIMIT a tick: past it, those waiting are handed from a place that moves on each tick, so
        # none waits behind the others for good (as engine/resetmessage.py hands its messages).
        if len(found) > RECORDS_LIMIT:
            start = (self._turn * RECORDS_LIMIT) % len(found)
            found = found[start:] + found[:start]
            self._turn += 1
        return found or DEFER

    def _still_due(self, waiting, spared=frozenset()) -> list:
        """The waiting ones whose conversation core would still recover and whose turn is still the latest and still
        running; every other one ends superseded here - core would keep it waiting for good (not a conversation it
        takes up) or drop it (its turn moved on), and either way it would take a place among core's few a tick.
        Where Codex's files cannot be read now, each is left as it is, for the next tick."""
        try:
            source = self._source()
        except Exception:
            return waiting
        kept, ended = [], set()
        for row in waiting:
            thread = row["thread_id"]
            try:
                latest = source.latest(thread)
            except Exception:
                kept.append(row)
                continue
            if (latest is not None and latest.get("ordinal") == row["ordinal"]
                    and latest.get("status") == "inProgress"):
                kept.append(row)
            elif thread not in ended:
                ended.add(thread)
                if thread in spared:
                    continue                    # not handed; a continuation after the reset waits there, not ended
                try:
                    self._scoped.continuations.end(ContinuationReason.SUPERSEDED, thread_id=thread)
                except Exception:
                    pass
        return [row for row in kept if row["thread_id"] not in ended]

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass


def _after_wrap_up(turns, thread, made_for, latest):
    """Whether a turn came after the wrap-up's own - the turn it was made for (`made_for`), or the very next one, which
    the wrap-up started: True where `latest` is later than both, None where that cannot be read."""
    if type(made_for) is not int or type(latest) is not int:
        return None
    if latest == made_for:
        return False
    if latest < made_for:
        return True
    try:
        return turns.between(thread, made_for, latest) != 0
    except Exception:
        return None


# ---------------------------------------------------------------------------- the pause
class UsagePause:
    """usage_pause's code: at P8 the windows it holds for marked and let go, at P3 HOLD while one holds, and
    `holds` for the edition's own continuations (runtime.records)."""
    __slots__ = ("paths", "_scoped")

    def __init__(self, paths):
        self.paths = paths
        self._scoped = None

    def bind(self, scoped):
        self._scoped = scoped

    def tick(self, view):
        if self._scoped is not None:
            self._mark()
        return DEFER

    def _mark(self) -> list:
        """The windows held and let go at P8, as their readings stand; the rows newly held this tick."""
        scoped = self._scoped
        newly = []
        try:
            handle = scoped.meter
            if not handle.on():
                return newly
            now = scoped.now()
            options = scoped.options()
            on = _acting(scoped)
            rows = windows(handle.rows())
            resets = credit_resets(scoped, rows)
            for row in rows:
                # (e) a window switched off is never held, and one held lets go when it is switched off.
                acted = row["minutes"] in on
                # (v0.6.17, P-8) a reading from before a reset credit of this window says nothing of it now:
                # the window was emptied after it, so nothing is held on it and nothing newly held by it.
                fresh = not stale(row, resets)
                over = acted and fresh and reached(row, percent(options, PAUSE, row["minutes"]), now)
                held = row["paused_reset_at"]
                if over and held != row["reset_at"]:
                    if handle.mark(row["bucket"], row["minutes"], paused_reset_at=row["reset_at"]):
                        self._count("paused")
                        newly.append(row)
                elif held is not None and not over and (not acted or not fresh or held != row["reset_at"]
                                                         or now >= held + CLOSE_AFTER):
                    if handle.mark(row["bucket"], row["minutes"], clear_pause=True):
                        self._count("resumed")
        except Exception:
            pass
        return newly

    def holding(self) -> bool:
        """Whether a window the pause marked has not reset yet - its reset time not yet passed, and no reset
        credit of that window spent since it was read (v0.6.17, P-8).

        The mark is let go at P8, but only the meter's own reading moves it, and the meter reads while the
        Codex app runs and no oftener than the person's spacing. A credit spent in between resets the window
        at once and buys the whole early window (engine/credits.py, P7 EARLY), so the hold is asked here too
        - or the pause would hold every record through the fifteen minutes the credit paid for, and on to the
        reset it was spent to avoid."""
        scoped = self._scoped
        if scoped is None:
            return False
        now = scoped.now()
        held = [row for row in windows(scoped.meter.rows())
                if row["paused_reset_at"] is not None and now < row["paused_reset_at"] + CLOSE_AFTER]
        if not held:
            return False
        resets = credit_resets(scoped, held)
        return any(not stale(row, resets) for row in held)

    def gate(self, name, record, facts):
        """P3: HOLD a record of core's while a window holds; nothing for anything else."""
        if not isinstance(record, dict) or "interruption_id" not in record:
            return DEFER
        try:
            return Alternative.HOLD if self.holding() else DEFER
        except Exception:
            return DEFER

    def holds(self, record) -> bool:
        """Whether a record of the edition's own is held back from core this tick: a continuation waiting -
        never a person's message, never a wrap-up, never one already in flight."""
        if not (isinstance(record, dict) and record.get("state") == "waiting"
                and record.get("purpose") == "continuation"):
            return False
        try:
            return self.holding()
        except Exception:
            return False

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass


def touched(key) -> tuple:
    """The windows whose order an option bears on: its own window for a percentage, none for anything else."""
    return tuple(minutes for minutes in WINDOWS if key == STOP_WORDS_OPTIONS[minutes]
                 or any(key == stages[minutes] for stages in STAGE_OPTIONS.values()))


def order_problem(values, windows_=WINDOWS) -> tuple:
    """Item (j) of the owner's additions, for each window: the warning at or below the wrap-up, and the wrap-up below the
    stop the words ask for - else ("order", None); a forced stop below the words' stop only warns ("stop_before_words"),
    as it would cut Codex off before it stops itself - never refuses. `values` is {capability: its options} as they
    would be, `windows_` the windows looked at - a change, only those it touches (`touched`), so a value an older
    beta stored out of order never blocks a change to anything else; (refusal word or None, warning word or None)."""
    warning = None
    for minutes in windows_:
        warn = values.get(METER, {}).get(STAGE_OPTIONS[METER][minutes], DEFAULT_WARN)
        wrap = values.get(WRAP_UP, {}).get(STAGE_OPTIONS[WRAP_UP][minutes], DEFAULT_WRAP)
        words = values.get(WRAP_UP, {}).get(STOP_WORDS_OPTIONS[minutes], DEFAULT_STOP_WORDS)
        forced = values.get(PAUSE, {}).get(STAGE_OPTIONS[PAUSE][minutes], DEFAULT_PAUSE)
        if not warn <= wrap < words:
            return "order", None
        if forced < words:
            warning = "stop_before_words"
    return None, warning


def previews(state, now) -> dict:
    """What the wrap-up would send for each window now, exactly (v0.6.16-beta.4, item (a)): its wording, numbers,
    reset time and Custom words as they stand, in the continuation language - for the page to show under the choice.
    Of the meter's last reading of that window where there is one, else as if the window had just reached the wrap-up
    percentage, resetting a window's length from now. {minutes: words or None}."""
    try:
        options, custom = state.options(WRAP_UP), state.wordings(WRAP_UP)
        rows = {}
        for row in windows(state.meter()):
            rows.setdefault(row["minutes"], row)
    except Exception:
        return {}
    try:
        locale = continuation.resolve_locale(settings.load(state.paths.settings_file))
    except Exception:
        locale = None
    found = {}
    for minutes in WINDOWS:
        row = rows.get(minutes)
        live = row is not None and type(row["reset_at"]) is int and row["reset_at"] > now
        found[minutes] = render(
            style=options.get(OptionKey.WRAP_STYLE, DEFAULT_STYLE), minutes=minutes, locale=locale,
            used=row["used_percent"] if live else options.get(STAGE_OPTIONS[WRAP_UP][minutes], DEFAULT_WRAP),
            stop_at=options.get(STOP_WORDS_OPTIONS[minutes], DEFAULT_STOP_WORDS),
            reset_at=row["reset_at"] if live else int(now) + minutes * 60,
            include_reset=options.get(OptionKey.WRAP_RESET_TIME, ON) == ON, custom=custom.get(CUSTOM_WORDINGS[minutes]))
    return found


def make_meter(paths) -> UsageMeter:
    return UsageMeter(paths)


def make_wrap_up(paths) -> UsageWrapUp:
    return UsageWrapUp(paths)


def make_pause(paths):
    """usage_pause's code: from v0.6.16-beta.4 the forced stop (engine/usagestop.py), which holds as the pause held."""
    from .usagestop import UsageStop
    return UsageStop(paths)
