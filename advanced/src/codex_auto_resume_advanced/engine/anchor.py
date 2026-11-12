# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Start the 5-hour window early (window_anchor, v0.6.20; the owner's request of 2026-10-28), at P8.

Codex's 5-hour usage window starts at the first use, so a late first use gives a late reset. The standard edition
sends nothing on its own and opens no usage window (A25, C4). With this on, when the 5-hour window is idle, the
watcher sends one near-free request so the window starts now and its reset is fixed five hours on - at the times of
day a person picked (up to three, `anchor_at_1..3`), right after a reset it has seen (`anchor_after_reset`), or both.

What MANCHOR measured on codex-cli 0.165.0-alpha.1.2 (plans/v0620-window-anchor-measure-result.md): one
`codex exec --skip-git-repo-check --ephemeral --json -s read-only -c model_reasoning_effort="low" "Reply with OK"` from
an empty folder fixes the reset at the request plus 5 h, costs about 24k input tokens (half cached) and 5 output, and
leaves no conversation, rollout or history line; a second request in a running window does not move its reset. And an
idle window still reports a reset - always now + 5 h, never counting down - so `judge` takes two reads at least
STEADY_GAP apart: idle is 0 % in both, the reset offset ~5 h in both, and the reset moving forward with the clock.

At P8 the tick only decides, from memory and its stamps, whether there is something to do (a watched capability's
tick is journalled and its errand never run); the errand reads and acts:

1. a time picked, within SLOT_GRACE after it, once - or a reset it saw (its own start's, or a running window's it
   read) gone by, once - is an occasion; with After a reset on and no reset known ahead, usage is read every
   LEARN_EVERY to learn one;
2. an occasion is skipped, with its word, where recovery is paused (Pause, Observe only - core's settings, and core's
   errand guard again at the start), no watcher told the plug the Codex it drives (never another home or engine),
   it started a window less than five hours ago (one start a window), usage cannot be read, no account is signed in,
   the weekly window is full, the 5-hour window runs, or its own state or core's guard cannot be read or written
   (`skip_state`: a file another process holds past its timeout - never a raise, which would trip it);
3. two reads STEADY_GAP apart; idle, and the request starts inside core's errand guard - its start stamped first -
   from an empty folder of its own, windowless, and is waited for on a thread of its own for at most TIMEOUT;
4. the next tick settles it: its exit code and the token counts are kept (never what it printed), and two more
   reads say whether the window now runs; its reset is kept, shown on the Advanced page, and said in the watcher's
   log.

Every start and every skip is one journal line, `anchor.<word>` (registry WINDOW_ANCHOR.codes), nothing else.

A passing failure does not use the occasion up (v0.6.23; on the owner's PC a usage read that failed once at 01:05 left the
idle window unstarted for 29 hours: an idle window teaches no new reset, so the one seen was the only occasion there
was). PASSING words - usage or the sign-in not read, signed out, recovery paused, no Codex told, its state or folder -
leave the occasion open, looked at again every RETRY_EVERY: a time picked within SLOT_GRACE, a reset seen for five hours
after it. Only when that span is over does it end, with its skip word, in one journal line. A request that could not be
started is one of them. For a reset seen, a full weekly window or the ceiling would end the chain the same way, so it is
held too: to the weekly window's own reset, and for a day after that reset. A time picked comes back by itself, so for it
those two end at once. A window that runs (a new reset will be learned) and one start a window end it at once, as ever.

Beside account_switch (v0.6.20, the pair audit's V20-2): the window is the signed-in account's. Where account_switch
saw another account signed in (its stamp ACCOUNT_CHANGED_AT), the start, the fixed reset and the reset seen kept here
were the other account's - they go, once a change, so one start a window is counted for this account's window and a
time picked is not refused `skip_once` for a start made on the other.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import subprocess
import threading
import time

from codex_auto_resume.domain.plug import DEFER
from codex_auto_resume.win.kernel import NO_WINDOW

from ..codex import credits, inuse
from ..vocabulary import OptionKey

CAPABILITY = "window_anchor"
FIVE_HOUR, WEEKLY = 300, 10080
WINDOW_SECONDS = FIVE_HOUR * 60
# The span its ceiling of starts a day is counted over (registry: Ceilings.per_day).
DAY = 86400
# Two reads at least this far apart tell an idle window (its reset moves with the clock) from a running one.
STEADY_GAP = 20
# An idle window's reset offset is ~5 h (17,998-17,999 s were read); how far from it still counts, and how much
# slower than the clock an idle window's reset may move between two reads.
OFFSET_TOLERANCE = 120
DRIFT_TOLERANCE = 5
# A time picked is taken within this long after it (a watcher, or a PC, that wakes late still takes it).
SLOT_GRACE = 1800
# A reset seen is acted on once it is this far past (the window's own turn-over first).
AFTER_RESET = 60
# With After a reset on and no reset known ahead: how often usage is read to learn one.
LEARN_EVERY = 1800
# How often the tick looks whether an occasion is due.
LOOK_EVERY = 15
# How often an occasion a passing failure holds open is looked at again. Such a failure is mostly a moment's (a PC just
# woken, Codex restarting, the state busy), and each look opens a session of Codex: six tries for a time picked, sixty at
# the very most for a reset seen. A full weekly window is no passing failure: a reset seen under it is looked at again
# once that window resets, not every RETRY_EVERY (`_held`, the v0.6.23 second round's M6 - it was a session every five
# minutes for up to a week, about 2,000), so its looks stay within the sixty and one more after the weekly reset. A
# ceiling's hold looks every RETRY_EVERY too, but opens no session: its own check comes before any read (`_before`).
RETRY_EVERY = 300
# The request's own bound, and how long a request killed at it has to end.
TIMEOUT = 120
KILL_WAIT = 10
# A time option off, and how a time of day is held: the minute of the day plus two (whole numbers from 1).
TIME_OFF = 1
TIME_SHIFT = 2
TIME_CHOICES = (TIME_OFF,) + tuple(minute + TIME_SHIFT for minute in range(0, 1440, 30))
TIME_RANGE = (TIME_OFF, 1439 + TIME_SHIFT)
TIME_OPTIONS = (OptionKey.ANCHOR_AT_1, OptionKey.ANCHOR_AT_2, OptionKey.ANCHOR_AT_3)
# The measured request: its arguments after the product's own `codex` prefix (C10, Backend._argv), exactly as measured.
PROMPT = "Reply with OK"
EXEC_ARGUMENTS = ("exec", "--skip-git-repo-check", "--ephemeral", "--json", "-s", "read-only",
                  "-c", 'model_reasoning_effort="low"', PROMPT)
# The folder the request runs in, under this edition's own state directory.
FOLDER = "anchor-cwd"
# What two reads may come to (`judge`).
IDLE, RUNNING, WEEKLY_FULL, UNREADABLE = "idle", "running", "weekly", "unreadable"
# The journal's word for each reason an occasion is skipped. `state` (2026-11-01): its own stamps, or core's errand guard,
# could not be read or written - the advanced state or core's store busy past its timeout (StateError, StoreError) - where
# the errand used to raise and its tripwire caught it (hook_exception, the owner's journal at 2026-10-31 10:08:17).
SKIPS = {"running": "skip_running", "weekly": "skip_weekly", "paused": "skip_paused", "signed_out": "skip_signed_out",
         "unreadable": "skip_unreadable", "home": "skip_home", "once": "skip_once", "folder": "skip_folder",
         "state": "skip_state", "ceiling": "skip_ceiling"}
CODES = ("started", "fixed", "unfixed", "failed", "timed_out") + tuple(SKIPS.values())
# The reasons that say nothing lasting of the window: the occasion stays open (`_held`). `paused` too: a skip stamped the
# occasion done just as a failed read did, so a reset that fell in a pause ended the chain the same way.
PASSING = frozenset({"unreadable", "signed_out", "paused", "home", "folder", "state", "failed"})
# What an occasion is: a time picked, or a reset seen.
SLOT, RESET, VERIFY = "slot", "reset", "verify"
# account_switch, and the stamps of a window that are the account's that was signed in (V20-2).
ACCOUNT_SWITCH = "account_switch"
WINDOW_STAMPS = (OptionKey.ANCHOR_STARTED_AT, OptionKey.ANCHOR_FIXED_AT, OptionKey.ANCHOR_SEEN_RESET)
LOG_PREFIX = "window anchor: "


# ---------------------------------------------------------------------------- pure
def encode_time(hour, minute):
    """A time of day as its option holds it, or None for one that is not a time."""
    if type(hour) is not int or type(minute) is not int or not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour * 60 + minute + TIME_SHIFT


def decode_time(value):
    """The minute of the day a time option holds, or None for off or anything else."""
    if type(value) is not int or not TIME_SHIFT <= value <= TIME_RANGE[1]:
        return None
    return value - TIME_SHIFT


def clock_text(value) -> str:
    """HH:MM of a time option's value ("" for off)."""
    minute = decode_time(value)
    return "" if minute is None else "%02d:%02d" % divmod(minute, 60)


def picked(options) -> tuple:
    """The minutes of the day of the times picked, each once, in order."""
    found = {decode_time((options or {}).get(key)) for key in TIME_OPTIONS}
    return tuple(sorted(minute for minute in found if minute is not None))


def after_reset_on(options) -> bool:
    """Whether Start right after a reset is on: it is, unless a person turned it off - a missing value is on (the
    registry's default; `options` carries it, and this does not depend on that)."""
    from .wrapwords import ON
    return (options or {}).get(OptionKey.ANCHOR_AFTER_RESET, ON) == ON


def midnight(now, local=time.localtime) -> int:
    """The local midnight that began the day `now` is in, in whole seconds."""
    moment = local(int(now))
    return int(now) - (moment.tm_hour * 3600 + moment.tm_min * 60 + moment.tm_sec)


def occurrence(now, days, minute, local=time.localtime, mktime=time.mktime) -> int:
    """The time picked `minute` (minutes after midnight) on the day `days` from the one `now` is in, in whole seconds -
    by the calendar, so across a daylight-saving change it is still that time on the clock (v0.6.23 audit seatA:B-M3:
    seconds arithmetic put tomorrow's 08:00 at 09:00 after a spring change, and the wake for it missed it)."""
    moment = local(int(now))
    return int(mktime((moment.tm_year, moment.tm_mon, moment.tm_mday + days, minute // 60, minute % 60, 0, 0, 0, -1)))


def slot_due(options, now, done, local=time.localtime, mktime=time.mktime):
    """The occurrence - its time, in whole seconds - of a time picked that is due now: at or before `now`, at most
    SLOT_GRACE before it, and after `done` (the last one handled). The latest such, or None."""
    due = [found for minute in picked(options)
           for found in (occurrence(now, 0, minute, local, mktime), occurrence(now, -1, minute, local, mktime))
           if found <= now < found + SLOT_GRACE and (done is None or found > done)]
    return max(due) if due else None


def reset_due(options, now, seen, done):
    """The reset seen that is due now - After a reset on, it has gone by AFTER_RESET ago and was not handled - or None."""
    if not after_reset_on(options) or type(seen) is not int:
        return None
    if now < seen + AFTER_RESET or (done is not None and seen <= done):
        return None
    return seen


def next_due(options, now, slot_done, seen, reset_done, local=time.localtime, mktime=time.mktime):
    """The earliest occasion still to come, in whole seconds, or None - for wake_for_reset (v0.6.20, the pair audit; the
    owner's word of 2026-10-31): the next occurrence of a time picked, today's or tomorrow's, not handled already, and -
    Start right after a reset on - the reset seen not handled yet, AFTER_RESET after it. Pure."""
    found = [at for minute in picked(options)
             for at in (occurrence(now, 0, minute, local, mktime), occurrence(now, 1, minute, local, mktime))
             if at > now and (type(slot_done) is not int or at > slot_done)]
    if after_reset_on(options) and type(seen) is int and (type(reset_done) is not int or seen > reset_done):
        if seen + AFTER_RESET > now:
            found.append(seen + AFTER_RESET)
    return min(found) if found else None


def windows_of(windows):
    """(the 5-hour window, the weekly window) of one reading - the `codex` bucket's, else the `legacy` one's - each
    None where there is none."""
    rows = [window for window in windows or () if isinstance(window, dict)]
    for bucket in ("codex", "legacy"):
        mine = [window for window in rows if window.get("bucket") == bucket]
        five = next((window for window in mine if window.get("window_minutes") == FIVE_HOUR), None)
        if five is not None:
            weekly = next((window for window in mine if window.get("window_minutes") == WEEKLY), None)
            return five, weekly
    return None, None


def running_reset(reading, now):
    """The reset ahead of a 5-hour window this reading shows running - used, its reset in the future - or None."""
    five, _weekly = windows_of((reading or {}).get("windows"))
    if five is None or type(five.get("reset_at")) is not int or not five["used_percent"] > 0:
        return None
    return five["reset_at"] if five["reset_at"] > now else None


def judge(first, second) -> str:
    """What two readings `{"at", "windows"}` at least STEADY_GAP apart say of the 5-hour window: IDLE, RUNNING,
    WEEKLY_FULL or UNREADABLE. Pure.

    Idle is 0 % in both, a reset offset of ~5 h in both, and the reset moving forward with the clock between them:
    an idle window reports a reset of now + 5 h that never counts down (MANCHOR). Used, or a reset that stays put,
    is running."""
    found = []
    for reading in (first, second):
        five, weekly = windows_of((reading or {}).get("windows"))
        at = (reading or {}).get("at")
        if five is None or type(at) not in (int, float):
            return UNREADABLE
        if weekly is not None and weekly["used_percent"] >= 100:
            return WEEKLY_FULL
        found.append((at, five))
    (at1, five1), (at2, five2) = found
    if five1["used_percent"] > 0 or five2["used_percent"] > 0:
        return RUNNING
    reset1, reset2 = five1["reset_at"], five2["reset_at"]
    if type(reset1) is not int or type(reset2) is not int or at2 - at1 < STEADY_GAP:
        return UNREADABLE
    steady = all(abs((reset - at) - WINDOW_SECONDS) <= OFFSET_TOLERANCE for at, reset in ((at1, reset1), (at2, reset2)))
    moving = reset2 - reset1 >= (at2 - at1) - DRIFT_TOLERANCE
    return IDLE if steady and moving else RUNNING


def signed_in(reply):
    """Whether account/read names a signed-in account: True, False, or None where it did not answer as one."""
    if not isinstance(reply, dict) or "account" not in reply:
        return None
    return isinstance(reply.get("account"), dict)


def tokens_of(printed) -> dict:
    """The token counts of the request's `turn.completed` event - {"input", "cached", "output"}, each a whole number or
    None - from what `codex exec --json` printed. Nothing else of it is read, and the text is dropped."""
    found = {"input": None, "cached": None, "output": None}
    if isinstance(printed, bytes):
        printed = printed.decode("utf-8", "replace")
    for line in str(printed or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        usage = event.get("usage") if isinstance(event, dict) and event.get("type") == "turn.completed" else None
        if not isinstance(usage, dict):
            continue
        for key, name in (("input", "input_tokens"), ("cached", "cached_input_tokens"), ("output", "output_tokens")):
            value = usage.get(name)
            found[key] = value if type(value) is int and 0 <= value < 10 ** 9 else None
    return found


# ---------------------------------------------------------------------------- the request
def argv_for(backend) -> list:
    """The request's argument list: the product's own `codex` prefix (C10: analytics off, OTel exporters none,
    log_user_prompt off, chatgpt_base_url pinned - Backend._argv) and the measured `exec` arguments, exactly."""
    return [*backend._argv(), *EXEC_ARGUMENTS]


def folder_of(paths) -> Path:
    return Path(paths.advanced_dir) / FOLDER


def ready_folder(folder) -> bool:
    """The request's folder made where it is not, and whether it is an empty folder of its own (never a link)."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        return folder.is_dir() and not folder.is_symlink() and not any(folder.iterdir())
    except OSError:
        return False


def start_request(backend, folder):
    """The request started: the codex.exe and the Codex home of `backend` (Backend's environment), in `folder`,
    windowless, no shell, no input. The process."""
    return subprocess.Popen(argv_for(backend), cwd=str(folder), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                 stderr=subprocess.DEVNULL, env=backend._environment(), creationflags=NO_WINDOW, shell=False)


def finish_request(process, timeout=TIMEOUT) -> dict:
    """The request waited for, at most `timeout`, and killed after it: {"end": "exited" or "timed_out", "code",
    "input", "cached", "output"} - the exit code and the token counts, never what it printed."""
    try:
        printed, _errors = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.communicate(timeout=KILL_WAIT)
        except Exception:
            pass
        return {"end": "timed_out", "code": None, "input": None, "cached": None, "output": None}
    return dict(tokens_of(printed), end="exited", code=process.returncode)


# ---------------------------------------------------------------------------- the capability
class _Errand:
    __slots__ = ("code", "view")

    def __init__(self, code, view):
        self.code, self.view = code, view

    def run(self, guard):
        return self.code.look(self.view, guard)


class WindowAnchor:
    """window_anchor's code: its P8 tick and errand. Its seams are the tests': `session` opens a usage session (None:
    the advanced Session against the Codex the watcher told), `told` answers (codex.exe, Codex home) as the watcher told
    them (None: codex/inuse.told), `backend` makes core's Backend for that pair (None: codex/inuse.backend), `begin`
    starts the waiting thread (`begin(target)`), `log` writes the watcher's log line and
    `local` is the local clock (time.localtime)."""
    __slots__ = ("paths", "_scoped", "_session", "_told", "_make_backend", "_begin", "_log", "_local",
                 "_lock", "_pending", "_running", "_ended", "_looked", "_learned", "_held_open", "_shown")

    def __init__(self, paths, *, session=None, told=None, backend=None, begin=None, log=None, local=None):
        self.paths = paths
        self._scoped = None
        self._session = session
        self._told = told or (lambda: inuse.told(paths))
        self._make_backend = backend or (lambda: inuse.backend(paths))
        self._begin = begin or (lambda target: threading.Thread(target=target, daemon=True).start())
        self._log = log or _log_line
        self._local = local or time.localtime
        self._lock = threading.Lock()
        self._pending = None          # {"why", "occurrence", "first"}: an occasion between its two reads
        self._running = None          # the occasion whose request runs
        self._ended = None            # (that occasion, what finish_request answered), not yet settled
        self._looked = None
        self._learned = None
        self._held_open = {}          # {(why, occurrence): {"next", "until", "reason"}}: occasions a passing failure holds open
        self._shown = False           # the time its card was last told it tries until (False: not told yet in this process)

    def bind(self, scoped):
        self._scoped = scoped

    # ------------------------------------------------------------------ P8
    def tick(self, view):
        """An errand where there is something to do: a request that ended, an occasion between its reads, or - looked
        at every LOOK_EVERY - an occasion due or a reset to learn. Reads nothing but its own stamps."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            now = scoped.now()
            self._account_changed()
            with self._lock:
                ended, running = self._ended is not None, self._running is not None
            if ended:
                return _Errand(self, view)
            if running:
                return DEFER
            if self._pending is not None:
                first = self._pending.get("first")
                return _Errand(self, view) if first is None or now - first["at"] >= STEADY_GAP else DEFER
            if self._looked is not None and 0 <= now - self._looked < LOOK_EVERY:
                return DEFER
            self._looked = now
            due = self._span_over(now) or self._open(now) or self._learn_due(now)
            return _Errand(self, view) if due else DEFER
        except Exception:
            return DEFER

    def _account_changed(self) -> None:
        """V20-2: another account signed in since the last change taken in, as account_switch saw it - its window stamps
        go, once a change. Nothing where account_switch does not stand on, or nothing can be read."""
        scoped = self._scoped
        try:
            if scoped.armed(ACCOUNT_SWITCH) is not True:
                return
            changed = scoped.stamped_of(ACCOUNT_SWITCH, OptionKey.ACCOUNT_CHANGED_AT)
            taken = scoped.stamped(OptionKey.ANCHOR_ACCOUNT_AT)
            if type(changed) is not int or (type(taken) is int and taken >= changed):
                return
            for key in WINDOW_STAMPS:
                scoped.unstamp(key)
            scoped.stamp(OptionKey.ANCHOR_ACCOUNT_AT, changed)
        except Exception:
            return

    def _occasion(self, now):
        """(why, occurrence) of an occasion due now - a time picked first, then a reset seen - or None."""
        scoped = self._scoped
        options = scoped.options()
        slot = slot_due(options, now, scoped.stamped(OptionKey.ANCHOR_SLOT_DONE), self._local)
        if slot is not None:
            return SLOT, slot
        seen = reset_due(options, now, scoped.stamped(OptionKey.ANCHOR_SEEN_RESET),
                         scoped.stamped(OptionKey.ANCHOR_RESET_DONE))
        return (RESET, seen) if seen is not None else None

    def _open(self, now):
        """The occasion due now that is to be looked at now: `_occasion`, unless a passing failure's retry is not due yet."""
        occasion = self._occasion(now)
        held = self._held_open.get(occasion)
        return occasion if held is None or now >= held["next"] else None

    def _span_over(self, now) -> list:
        """The occasions held open whose span is over."""
        return [occasion for occasion, held in self._held_open.items() if now >= held["until"]]

    def _learn_due(self, now) -> bool:
        """Whether usage is to be read to learn a reset: After a reset on, none known ahead, none read lately, and no
        occasion held open, whose own retries read it."""
        scoped = self._scoped
        if self._held_open or not after_reset_on(scoped.options()):
            return False
        seen = scoped.stamped(OptionKey.ANCHOR_SEEN_RESET)
        if type(seen) is int and seen > now:
            return False
        return self._learned is None or not 0 <= now - self._learned < LEARN_EVERY

    # ------------------------------------------------------------------ the errand
    def look(self, view, guard):
        if self._settle():
            return None
        now = self._scoped.now()
        if self._pending is not None:
            self._second(view, guard, now)
            return None
        try:
            for over in self._span_over(now):
                self._span_ended(over, now)
            occasion = self._open(now)
            learn = occasion is None and self._learn_due(now)
        except Exception:
            return None                 # its own state unreadable now: nothing is known to be due; the tick looks again
        if occasion is not None:
            self._first(view, occasion, now)
        elif learn:
            self._learned = now
            reading = self._read(account=False)
            self._remember(reading, now)
        return None

    def _first(self, view, occasion, now) -> None:
        """An occasion's checks before any read, then its first read: skipped with its word, or held for the second."""
        why, occurrence = occasion
        reason = self._before(view, now)
        if reason is not None:
            return self._skip(why, occurrence, reason)
        reading = self._read(account=True)
        self._remember(reading, now)
        if reading is None or reading["windows"] is None:
            return self._skip(why, occurrence, "unreadable")
        if reading["signed_in"] is not True:
            return self._skip(why, occurrence, "signed_out" if reading["signed_in"] is False else "unreadable")
        five, weekly = windows_of(reading["windows"])
        if five is None:
            return self._skip(why, occurrence, "unreadable")
        if weekly is not None and weekly["used_percent"] >= 100:
            return self._skip(why, occurrence, "weekly", until=self._past_weekly(why, reading, now))
        if five["used_percent"] > 0:
            return self._skip(why, occurrence, "running")
        self._pending = {"why": why, "occurrence": occurrence, "first": reading}

    def _second(self, view, guard, now) -> None:
        pending, self._pending = self._pending, None
        why, occurrence = pending["why"], pending["occurrence"]
        reading = self._read(account=False)
        self._remember(reading, now)
        found = judge(pending["first"], reading) if reading is not None else UNREADABLE
        if why == VERIFY:
            return self._verified(found, reading, pending)
        if not 0 <= now - pending["first"]["at"] <= SLOT_GRACE:
            # A first read held past a slot's own grace - recovery paused or the capability turned off or watched
            # between the two reads - says nothing of the window now: the occasion is skipped, never started hours
            # late at a time nobody picked (v0.6.23 audit seatA:B-M1).
            return self._skip(why, occurrence, "unreadable")
        if found == WEEKLY_FULL:
            return self._skip(why, occurrence, "weekly", until=self._past_weekly(why, reading or pending["first"], now))
        if found != IDLE:
            return self._skip(why, occurrence, {RUNNING: "running"}.get(found, "unreadable"))
        reason = self._before(view, now)
        if reason is not None:
            return self._skip(why, occurrence, reason)
        self._start(why, occurrence, guard, now)

    def _before(self, view, now):
        """Why no window may be started now, before anything is read - or None: recovery paused or only observed, no
        Codex the watcher told, or a start of its own less than a window ago."""
        try:
            settings = view.settings()
        except Exception:
            settings = None
        if not isinstance(settings, dict) or settings.get("enabled") is not True or settings.get("observe_only"):
            return "paused"
        if self._told() is None:
            return "home"
        try:
            started = self._scoped.stamped(OptionKey.ANCHOR_STARTED_AT)
        except Exception:
            return "state"              # one start a window cannot be told: none is made
        if type(started) is int and 0 <= now - started < WINDOW_SECONDS:
            return "once"
        # Its ceiling, starts in any 24 hours (registry: Ceilings.per_day) - one a window keeps under it but for the
        # restarts an account change allows (v0.6.23 audit seatA:B-M2).
        from ..registry import WINDOW_ANCHOR
        try:
            made = self._scoped.counted_since("started", now - DAY)
        except Exception:
            return "state"
        if type(made) is not int or made >= WINDOW_ANCHOR.ceilings.per_day:
            return "ceiling"
        return None

    def _start(self, why, occurrence, guard, now) -> None:
        """The request, inside core's errand guard - its time stamped first - and its waiting thread."""
        folder = folder_of(self.paths)
        if not ready_folder(folder):
            return self._skip(why, occurrence, "folder")
        try:
            backend = self._backend()
        except Exception:
            return self._skip(why, occurrence, "home")
        process, refused = None, None
        try:
            with guard() as permitted:
                if permitted is not True:
                    refused = "paused"
                else:
                    stamped = self._stamp(OptionKey.ANCHOR_STARTED_AT, max(1, int(now)))
                    if stamped is None:
                        refused = "state"   # the start's stamp could not be written: one start a window not kept
                    elif stamped is True:
                        try:
                            process = start_request(backend, folder)
                        except Exception:
                            process = None
                            self._unstamp(OptionKey.ANCHOR_STARTED_AT)
        except Exception:
            if process is None:             # core's guard could not be taken (its store busy): nothing started
                refused = "state"
        if refused is not None:
            return self._skip(why, occurrence, refused)
        if process is None:
            return self._skip(why, occurrence, "failed")
        self._done(why, occurrence)
        self._unstamp(OptionKey.ANCHOR_STOPPED_AT)
        self._count("started")
        occasion = {"why": why, "occurrence": occurrence, "at": int(now)}
        with self._lock:
            self._running = occasion

        def wait():
            try:
                answered = finish_request(process)
            except Exception:
                answered = {"end": "exited", "code": None, "input": None, "cached": None, "output": None}
            with self._lock:
                self._ended, self._running = (occasion, answered), None
        try:
            self._begin(wait)
        except Exception:
            wait()

    def _settle(self) -> bool:
        """A request that ended: its counts kept, its word counted, and - exited 0 - two reads begun that say whether
        the window now runs. Whether there was one."""
        with self._lock:
            ended, self._ended = self._ended, None
        if ended is None:
            return False
        occasion, answered = ended
        scoped = self._scoped
        for key, name in ((OptionKey.ANCHOR_INPUT_TOKENS, "input"), (OptionKey.ANCHOR_OUTPUT_TOKENS, "output")):
            value = answered.get(name)
            if type(value) is int and value >= 1:
                self._stamp(key, value)
            else:
                self._unstamp(key)
        if answered.get("end") == "timed_out":
            self._count("timed_out")
            self._say("the request did not finish within %d s and was ended" % TIMEOUT)
            return True
        if answered.get("code") != 0:
            self._count("failed")
            code = answered.get("code")
            self._say("the request ended with exit code %s" % (code if type(code) is int else "unknown"))
            return True
        now = scoped.now()
        reading = self._read(account=False)
        if reading is None or reading["windows"] is None:
            self._count("unfixed")
            self._say("the request finished, but usage could not be read afterwards")
            return True
        self._pending = {"why": VERIFY, "occurrence": occasion["at"], "first": reading,
                         "tokens": {key: answered.get(key) for key in ("input", "cached", "output")}}
        self._remember(reading, now)
        return True

    def _verified(self, found, reading, pending) -> None:
        """The two reads after a request: a window that runs now has its reset kept and said; anything else is unfixed."""
        started = pending["occurrence"]
        if found == RUNNING and reading is not None:
            five, _weekly = windows_of(reading["windows"])
            reset = five["reset_at"] if five is not None else None
            if type(reset) is int and reset > self._scoped.now():
                self._stamp(OptionKey.ANCHOR_FIXED_AT, reset)
                self._stamp(OptionKey.ANCHOR_SEEN_RESET, reset)
                self._count("fixed")
                self._say("the 5-hour window started at %s; its next reset is fixed at %s (%s)"
                          % (_hhmm(started, self._local), _hhmm(reset, self._local),
                             tokens_said(pending.get("tokens"))))
                return None
        self._count("unfixed")
        self._say("the request finished, but the 5-hour window did not show as started")
        return None

    # ------------------------------------------------------------------ helpers
    def _remember(self, reading, now) -> None:
        """A running window's reset ahead, kept as the reset seen - what After a reset acts on once it has gone by. Where
        the state cannot be read or written, nothing is kept: a later read learns it again."""
        reset = running_reset(reading, now)
        try:
            if reset is not None and self._scoped.stamped(OptionKey.ANCHOR_SEEN_RESET) != reset:
                self._scoped.stamp(OptionKey.ANCHOR_SEEN_RESET, reset)
                # A new reset is the next occasion: the older one held open has nothing left to wait for.
                for occasion in [held for held in self._held_open if held[0] == RESET]:
                    del self._held_open[occasion]
                self._show_retry()
                self._unstamp(OptionKey.ANCHOR_STOPPED_AT)
        except Exception:
            pass

    def _past_weekly(self, why, reading, now):
        """When a reset seen, its window idle under a full weekly window, stops being held: a little past that weekly
        window's own reset, so a look is made after it. None - ended at once - for a time picked, or where no reset is
        read."""
        _five, weekly = windows_of((reading or {}).get("windows"))
        reset = (weekly or {}).get("reset_at")
        return reset + 2 * RETRY_EVERY if why == RESET and type(reset) is int and reset > now else None

    def _skip(self, why, occurrence, reason, until=None) -> None:
        """An occasion ends with its word - or, for a passing reason or a reset's weekly or ceiling, stays open (`_held`)."""
        if reason == "ceiling" and why == RESET:
            until = occurrence + DAY        # the starts it counts are older than a day by then
        if why in (SLOT, RESET) and (reason in PASSING or until is not None):
            return self._held(why, occurrence, reason, until)
        self._done(why, occurrence)
        self._count(_word(reason))

    def _held(self, why, occurrence, reason, longer=None) -> None:
        """A passing failure: nothing stamped done, tried again in RETRY_EVERY, while its span lasts. One line in the
        watcher's log at an occasion's first failure; the journal hears of it once, when the span is over."""
        now = self._scoped.now()
        occasion = (why, occurrence)
        until = occurrence + (SLOT_GRACE if why == SLOT else WINDOW_SECONDS)
        first = occasion not in self._held_open
        held = self._held_open.setdefault(occasion, {"until": until})
        held.update(next=now + RETRY_EVERY, reason=reason)
        if longer is not None:
            held["until"] = longer
        weekly = reason == "weekly" and longer is not None
        if weekly:
            # M6: the weekly window is full until its reset - nothing to look at before it. The one look is a little past
            # that reset (`_past_weekly` holds the occasion RETRY_EVERY beyond it), and the card says no "trying again
            # every 5 minutes" meanwhile (`_show_retry`).
            held["next"] = max(held["next"], longer - RETRY_EVERY)
        held["weekly"] = weekly
        if now >= held["until"]:
            return self._span_ended(occasion, now)
        if weekly and not held.get("said_weekly"):
            held["said_weekly"] = True
            self._say("the weekly limit is reached; looking again once it resets, at %s"
                      % time.strftime("%Y-%m-%d %H:%M", self._local(int(held["next"]))))
            self._unstamp(OptionKey.ANCHOR_STOPPED_AT)
            self._show_retry()
        elif first and not weekly:
            self._say("could not start the window now (%s); trying again every %d minutes until %s"
                      % (reason, RETRY_EVERY // 60, time.strftime("%Y-%m-%d %H:%M", self._local(int(held["until"])))))
            self._unstamp(OptionKey.ANCHOR_STOPPED_AT)
            self._show_retry()

    def _span_ended(self, occasion, now) -> None:
        """An occasion held open whose span is over: done, and its one journal line. Where its stamp cannot be written it
        is kept here, tried no more in this process, so the one line stays one."""
        why, occurrence = occasion
        reason = self._held_open[occasion]["reason"]
        kept = self._done(why, occurrence)
        self._count(_word(reason))
        self._stamp(OptionKey.ANCHOR_STOPPED_AT, max(1, int(now)))
        if kept is not True:
            self._held_open[occasion] = {"next": float("inf"), "until": float("inf"), "reason": reason}

    def _done(self, why, occurrence):
        """The occasion handled: what `_stamp` answered, True where there was nothing to stamp."""
        self._held_open.pop((why, occurrence), None)
        self._show_retry()
        key = {SLOT: OptionKey.ANCHOR_SLOT_DONE, RESET: OptionKey.ANCHOR_RESET_DONE}.get(why)
        if key is not None and type(occurrence) is int and occurrence >= 1:
            return self._stamp(key, occurrence)
        return True

    def _show_retry(self) -> None:
        """Its card's "trying again until": the stamp written only when it changes, and taken away when nothing is held open."""
        untils = [held["until"] for held in self._held_open.values()
                  if held["until"] != float("inf") and not held.get("weekly")]
        until = int(max(untils)) if untils else None
        if until == self._shown:
            return
        self._shown = until
        if until is None:
            self._unstamp(OptionKey.ANCHOR_RETRY_UNTIL)
        else:
            self._stamp(OptionKey.ANCHOR_RETRY_UNTIL, until)

    def _stamp(self, key, value):
        """Its stamp `key` kept (Scoped.stamp): True, False where it was not kept (not on), or None where the state could
        not be written - never a raise."""
        try:
            return self._scoped.stamp(key, value) is True
        except Exception:
            return None

    def _unstamp(self, key) -> None:
        try:
            self._scoped.unstamp(key)
        except Exception:
            pass

    def _backend(self):
        """Core's Backend for the codex.exe and the Codex home the watcher told - never another (inuse.backend reads
        the told pair first, and `_before` refused where there is none)."""
        if self._told() is None:
            raise LookupError("no watcher told the Codex it drives")
        return self._make_backend()

    def _read(self, *, account):
        """One usage read through a session of its own: {"at", "windows", "signed_in"}, or None where none could be made.
        Of the account, only whether one is signed in; of usage, core's windows (codex/credits.parse)."""
        try:
            if self._told() is None:
                return None
            if self._session is not None:
                opened = self._session()
            else:
                from ..codex.protocol import Session
                opened = Session(self._backend(), capability=CAPABILITY)
            with opened as session:
                found = signed_in(session.call("account/read", {})) if account else None
                windows = credits.parse(session.call(credits.READ, {}))["windows"]
        except Exception:
            return None
        return {"at": self._scoped.now(), "windows": windows, "signed_in": found}

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass

    def _say(self, line) -> None:
        try:
            self._log(LOG_PREFIX + line)
        except Exception:
            pass


def _word(reason) -> str:
    """The journal's word an occasion ends with: its skip word, or `failed`, a request that could not be started."""
    return SKIPS.get(reason, reason)


def tokens_said(tokens) -> str:
    """The request's token counts as the log line says them: numbers, "?" for one not read."""
    tokens = tokens if isinstance(tokens, dict) else {}

    def said(key):
        value = tokens.get(key)
        return str(value) if type(value) is int else "?"
    return "%s input tokens (%s cached), %s output" % (said("input"), said("cached"), said("output"))


def _hhmm(at, local=time.localtime) -> str:
    moment = local(int(at))
    return "%02d:%02d" % (moment.tm_hour, moment.tm_min)


def _log_line(line) -> None:
    """One line in the watcher's log (core's logbook), as its other lines are."""
    from codex_auto_resume.logbook import LOGGER_NAME
    logging.getLogger(LOGGER_NAME).info("%s", line)


def view(runtime) -> dict:
    """{"window_anchor": {"started_at", "fixed_at", "retry_until", "stopped_at"}} while window_anchor stands on - when it
    last started a window, the reset that start fixed, where it is still ahead, until when an occasion a passing failure
    holds open is tried again, and when the last one ended with nothing started - else {}. Whole seconds, nothing else."""
    try:
        from ..vocabulary import ArmingState
        if runtime.states().get(CAPABILITY) != ArmingState.ARMED:
            return {}
        state, now = runtime.state, runtime.clock()
        started = state.stamped(CAPABILITY, OptionKey.ANCHOR_STARTED_AT)
        fixed = state.stamped(CAPABILITY, OptionKey.ANCHOR_FIXED_AT)
        retry = state.stamped(CAPABILITY, OptionKey.ANCHOR_RETRY_UNTIL)
        stopped = state.stamped(CAPABILITY, OptionKey.ANCHOR_STOPPED_AT)
    except Exception:
        return {}
    return {CAPABILITY: {"started_at": started if type(started) is int else None,
                         "fixed_at": fixed if type(fixed) is int and fixed > now else None,
                         "retry_until": retry if type(retry) is int and retry > now else None,
                         "stopped_at": stopped if type(stopped) is int else None}}


def make(paths) -> WindowAnchor:
    """The capability's factory (registry.CapabilityDef.make)."""
    return WindowAnchor(paths)
