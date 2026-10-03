"""The power action after usage-limit recoveries: what it waits for, and when it may act (v0.6.12).

Once every usage-limit recovery of a batch has ended as the person chose, and nothing else waits or
runs in Codex, the watcher puts this PC to sleep, hibernates it or shuts it down - after a notice
whose countdown a person can stop. It is off by default and armed only in the Dashboard, once or
always; everything else may only turn it off (H14). It sends nothing to Codex and changes no setting
of Windows (F15, win/powerdown.py).

The batch. An arming names the usage-limit recoveries that were open when it was made (`carried`)
and the moment it starts from (`since`); its members are those, and every usage-limit record
detected since. A child registered after a recovered turn hit the next limit is detected later, so
a batch spans further resets. A temporary error's record is never a member - the owner: only
recoveries from a usage limit decide it - but while one is open it holds the action like any other.

The order of the checks, each tick; the first that fails decides (`decide`, steps 1-10):

     1  no arming, or one that cannot be believed: off; one that could not be read just now: wait
     2  an administrator's DisablePowerAction: off, and the arming stays as it is
     3  a stop a person pressed for this batch: the batch ends skipped - before everything else,
        because the press is itself input, which would otherwise only end the countdown
     4  a tick that failed: wait
     5  recovery paused, or Observe only: wait (paused)
     6  a Once with no member a day after it was armed: it lapses
     7  no member yet: wait (no_batch)
     8  any record still open, of any kind: wait (recovery_open); an uncertain submission still
        followed: wait (delivery_unknown)
     9  every member ended: the policy is met, or the batch ends not_met
    10  a batch that ended over an hour ago, and that this watcher never saw open: stale

Then the watcher reads Codex (`judge_activity`, step 11: the history caught up, no turn running,
no input queued) and asks Windows (steps 12-14: still available, nobody else signed in for a shut
down, nobody at this PC for two minutes - `judge_presence`), and only then counts down. Anything
that cannot be read is a reason to wait, never to act (E1).

Every record is classed by its own state and reason, and nothing inherits its parent's class: a
child born exhausted is OTHER even when its parent recovered, because the task's last usage limit
was not recovered (`classify`).

Pure: the arming, the records, the times and what was read come in; a decision goes out. The file
is control/poweraction.py's, the watcher's side runtime/afterwork.py's, Windows' win/powerdown.py's.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .domain import ids
from .domain.power_vocabulary import (PowerAction, PowerAfter, PowerClass, PowerEnd, PowerPhase,
                                      PowerRepeat, PowerUnavailable, PowerWait)
from .domain.states import EPOCH_STORE, TERMINAL, epoch, still_followed
from .domain.vocabulary import FailureCategory, ReasonCode, RecordState

ACTIONS, AFTERS, REPEATS = tuple(PowerAction), tuple(PowerAfter), tuple(PowerRepeat)
PHASES, WAITS, ENDS = tuple(PowerPhase), tuple(PowerWait), tuple(PowerEnd)
CLASSES, UNAVAILABLE = tuple(PowerClass), tuple(PowerUnavailable)

# The file's format, and what it may be at most: a few ids and times.
FORMAT = "codex-auto-resume/power-action/1"
FILE_LIMIT = 32 * 1024
# How long the notice counts down, as a person chooses it in minutes, and as the file keeps it.
GRACE_MINUTES = (2, 5, 10, 15, 30)
GRACE_SECONDS = tuple(minutes * 60 for minutes in GRACE_MINUTES)
CHOICE_KEYS = ("action", "after", "repeat", "grace_minutes")
DEFAULT_CHOICE = {"action": PowerAction.SLEEP.value, "after": PowerAfter.ALL_RECOVERED.value,
                  "repeat": PowerRepeat.ONCE.value, "grace_minutes": 5}
# The open usage-limit recoveries an arming carries, at most.
MAX_CARRIED = 256
# A `since` more than this ahead of now was written while the clock was ahead: the file is refused.
SINCE_SKEW = 300.0
# A Once that no usage limit joined lapses this long after it was armed (Q4).
LAPSE_SECONDS = 24 * 3600.0
# A batch whose newest end is older than this, and which this watcher never saw open, is stale; and
# a conversation written in this last stretch must have been projected exactly (Q12).
STALE_SECONDS = RECENT_SECONDS = 3600.0
# How long an uncertain submission is followed: the engine's unknown_reconcile_window_seconds.
FOLLOW_SECONDS = 24 * 3600.0
# Nobody may have used this PC for this long before a countdown starts (Q3).
IDLE_SECONDS = 120.0
# How often the watcher looks while it counts down, and the gap between two looks that ends a
# countdown: a sleep, a stalled tick or a clock set right.
COUNTDOWN_LOOK_SECONDS = 15.0
GAP_SECONDS = 90.0

# The four answers a read of the file can give (control/poweraction.py), as seen.py's are.
READ_OK, READ_MISSING, READ_INVALID, READ_UNREADABLE = "ok", "missing", "invalid", "unreadable"
READS = (READ_OK, READ_MISSING, READ_INVALID, READ_UNREADABLE)
# What `decide` comes to: off, wait, the batch ends (with a PowerEnd), or go on to Codex and Windows.
OFF, WAIT, END, GO = "off", "wait", "end", "go"
VERDICTS = (OFF, WAIT, END, GO)
# Why it is off, beside no arming at all.
OFF_INVALID, OFF_MANAGED = "invalid", "managed"

# Each finished record's class, by its own state - and for `superseded`, its own reason: newer work
# of a person's, or a parent the person took over.
SUCCESS_STATES = frozenset({RecordState.RECOVERED})
PERSON_STATES = frozenset({RecordState.HANDED_OVER, RecordState.SUPERSEDED_BY_USER,
                           RecordState.STOPPED_BY_USER, RecordState.CANCELLED})
PERSON_SUPERSEDED = frozenset({ReasonCode.LATEST_TURN_CHANGED, ReasonCode.PARENT_HANDED_OVER})

_TOP = ("format", "armed", "shown", "last")
_ARMED = ("nonce", "action", "after", "repeat", "grace_seconds", "armed_at", "since", "carried", "stop_at")
_SHOWN = ("nonce", "phase", "waiting_for", "grace_until")
_LAST = ("action", "result", "at")
# What a surface is told of an arming: never its nonce, which only a notice's button carries.
_VIEW_ARMED = ("action", "after", "repeat", "grace_seconds", "armed_at", "since")
_VIEW_SHOWN = ("phase", "waiting_for", "grace_until")


# ------------------------------------------------------------------------------ the file
def _time(value) -> bool:
    return epoch(value, *EPOCH_STORE)


def _word(value, words) -> bool:
    return isinstance(value, str) and value in words


def _exact(value, keys) -> bool:
    return isinstance(value, dict) and set(value) == set(keys)


def _count(value) -> bool:
    return type(value) is int and value >= 0


def _armed(armed, now) -> bool:
    if not _exact(armed, _ARMED) or not ids.is_power_nonce(armed["nonce"]):
        return False
    if not (_word(armed["action"], ACTIONS) and _word(armed["after"], AFTERS)
            and _word(armed["repeat"], REPEATS)):
        return False
    if type(armed["grace_seconds"]) is not int or armed["grace_seconds"] not in GRACE_SECONDS:
        return False
    armed_at, since, stop = armed["armed_at"], armed["since"], armed["stop_at"]
    if not (_time(armed_at) and _time(since)) or since < armed_at or since > now + SINCE_SKEW:
        return False
    if stop is not None and not _time(stop):
        return False
    carried = armed["carried"]
    return (isinstance(carried, list) and len(carried) <= MAX_CARRIED
            and all(ids.is_digest(key) for key in carried) and len(set(carried)) == len(carried))


def _shown(shown, armed) -> bool:
    if not _exact(shown, _SHOWN) or armed is None or shown["nonce"] != armed["nonce"]:
        return False
    if not _word(shown["phase"], PHASES):
        return False
    if shown["waiting_for"] is not None and not _word(shown["waiting_for"], WAITS):
        return False
    until = shown["grace_until"]
    if shown["phase"] == PowerPhase.GRACE:
        return _time(until)
    return until is None


def _last(last) -> bool:
    return (_exact(last, _LAST) and _word(last["action"], ACTIONS) and _word(last["result"], ENDS)
            and _time(last["at"]))


def read_document(value, now: float):
    """The power-action file's contents as they may be believed, or None when they may not.

    Strict, as seen.py reads its file: exactly the four keys and each part's own, a nonce of 16
    lowercase hex digits, every word from its closed list, whole seconds of a grace this offers, times
    in the store's window (a boolean is never a number), `since` no earlier than the arming and no more
    than SINCE_SKEW ahead of `now`, at most MAX_CARRIED distinct interruption ids, and a `shown` only of
    the arming it names. A file refused is read as off by every caller (H14: unknown never acts)."""
    if not _exact(value, _TOP) or value["format"] != FORMAT:
        return None
    armed, shown, last = value["armed"], value["shown"], value["last"]
    if armed is not None and not _armed(armed, now):
        return None
    if shown is not None and not _shown(shown, armed):
        return None
    if last is not None and not _last(last):
        return None
    return {"format": FORMAT,
            "armed": None if armed is None else dict(armed, carried=list(armed["carried"])),
            "shown": None if shown is None else dict(shown),
            "last": None if last is None else dict(last)}


def blank() -> dict:
    """A file with nothing armed, shown or remembered: what the first arming starts from."""
    return {"format": FORMAT, "armed": None, "shown": None, "last": None}


def view(document) -> dict:
    """What every surface is told of the file (PowerView): the arming's choices and times, what the
    watcher last showed, and how the last batch ended - never the nonce. All None for no file."""
    document = document if isinstance(document, dict) else {}
    armed, shown, last = document.get("armed"), document.get("shown"), document.get("last")
    return {"armed": None if armed is None else {key: armed[key] for key in _VIEW_ARMED},
            "shown": None if shown is None else {key: shown[key] for key in _VIEW_SHOWN},
            "last": None if last is None else {key: last[key] for key in _LAST}}


def choice_problem(choice):
    """Why `choice` is not an arming a person may make, in a few words, or None when it is one: exactly
    the four keys, each word from its list, and a whole number of minutes of a grace this offers."""
    if not isinstance(choice, dict) or set(choice) != set(CHOICE_KEYS):
        return "exactly %s" % ", ".join(CHOICE_KEYS)
    for name, words in (("action", ACTIONS), ("after", AFTERS), ("repeat", REPEATS)):
        if not _word(choice[name], words):
            return "%s is one of %s" % (name, ", ".join(words))
    minutes = choice["grace_minutes"]
    if type(minutes) is not int or minutes not in GRACE_MINUTES:
        return "grace_minutes is one of %s" % ", ".join(str(value) for value in GRACE_MINUTES)
    return None


# ------------------------------------------------------------------------------ the batch
def is_member(row, armed) -> bool:
    """Whether a record is one of the arming's batch: carried by it, or a usage limit detected since."""
    if row.get("interruption_id") in armed["carried"]:
        return True
    detected = row.get("detected_at")
    return (row.get("category") == FailureCategory.USAGE_LIMIT and _time(detected)
            and detected >= armed["since"])


def members(rows, armed) -> list:
    return [row for row in rows if is_member(row, armed)]


def is_open(row) -> bool:
    """Still waiting or running: any state that is not a stop, and a state this does not know too."""
    return row.get("state") not in TERMINAL


def classify(row):
    """A finished record's PowerClass, by its own state and reason; None while it has not finished."""
    state = row.get("state")
    if state not in TERMINAL:
        return None
    if state in SUCCESS_STATES:
        return PowerClass.SUCCESS
    if state in PERSON_STATES or (state == RecordState.SUPERSEDED
                                  and row.get("last_error") in PERSON_SUPERSEDED):
        return PowerClass.PERSON
    return PowerClass.OTHER


def met(after, classes) -> bool:
    """Whether a batch whose members ended as `classes` meets the policy `after`. Never for none."""
    classes = list(classes)
    if not classes or any(found is None for found in classes):
        return False
    if after == PowerAfter.ALL_RECOVERED:
        return all(found == PowerClass.SUCCESS for found in classes)
    if after == PowerAfter.HANDED_OVER_TOO:
        return (all(found in (PowerClass.SUCCESS, PowerClass.PERSON) for found in classes)
                and PowerClass.SUCCESS in classes)
    return after == PowerAfter.ANY_END


def newest(rows):
    """When the newest of `rows` last moved: its outcome, or its detection; None when none says."""
    times = [row.get("outcome_at") if _time(row.get("outcome_at")) else row.get("detected_at")
             for row in rows]
    times = [value for value in times if _time(value)]
    return max(times) if times else None


@dataclass(frozen=True)
class Facts:
    """What one tick knows before it reads Codex or asks Windows.

    `rows` must hold every record that is not finished, every uncertain submission and every member
    of the batch; more does no harm. `saw_open` is this watcher's memory that it saw a member of this
    arming's batch open, kept for the nonce it was seen under."""
    now: float
    read: str = READ_MISSING
    document: dict | None = None
    managed: bool = False
    ok: bool = True
    paused: bool = False
    rows: tuple = field(default=())
    saw_open: bool = False
    follow_window: float = FOLLOW_SECONDS


@dataclass(frozen=True)
class Decision:
    """`verdict` is OFF, WAIT, END or GO; `word` says why - OFF_INVALID or OFF_MANAGED for off, a
    PowerWait to show for a wait (None: keep what is shown), a PowerEnd for an end. `saw_open` is
    what the watcher keeps for this nonce."""
    verdict: str
    word: str | None = None
    saw_open: bool = False


def decide(facts: Facts) -> Decision:
    """Steps 1 to 10 of the order above, the first that fails deciding."""
    if facts.read == READ_UNREADABLE:
        return Decision(WAIT, None, facts.saw_open)
    if facts.read == READ_INVALID:
        return Decision(OFF, OFF_INVALID)
    armed = (facts.document or {}).get("armed") if facts.read == READ_OK else None
    if armed is None:
        return Decision(OFF)
    if facts.managed:
        return Decision(OFF, OFF_MANAGED)
    if armed["stop_at"] is not None:
        return Decision(END, PowerEnd.SKIPPED)
    saw = facts.saw_open
    if not facts.ok:
        return Decision(WAIT, None, saw)
    if facts.paused:
        return Decision(WAIT, PowerWait.PAUSED, saw)
    batch = members(facts.rows, armed)
    if not batch:
        if armed["repeat"] == PowerRepeat.ONCE and facts.now > armed["armed_at"] + LAPSE_SECONDS:
            return Decision(END, PowerEnd.LAPSED)
        return Decision(WAIT, PowerWait.NO_BATCH, saw)

    def followed(row):
        return still_followed(row, facts.now, facts.follow_window)

    saw = saw or any(is_open(row) or followed(row) for row in batch)
    if any(is_open(row) for row in facts.rows):
        return Decision(WAIT, PowerWait.RECOVERY_OPEN, saw)
    if any(followed(row) for row in facts.rows):
        return Decision(WAIT, PowerWait.DELIVERY_UNKNOWN, saw)
    if not met(armed["after"], (classify(row) for row in batch)):
        return Decision(END, PowerEnd.NOT_MET, saw)
    ended = newest(batch)
    if not saw and (ended is None or facts.now - ended > STALE_SECONDS):
        return Decision(END, PowerEnd.STALE, saw)
    return Decision(GO, None, saw)


# ------------------------------------------------------------------------------ after step 10
def judge_activity(found):
    """Step 11, from what Codex's tables said (engine.activity): None when nothing runs, or why to
    wait. Codex's history comes first - a projection behind its file hides the very turn that would
    say something runs (A18) - and then the counts. Anything not read is codex_unknown."""
    if not isinstance(found, dict):
        return PowerWait.CODEX_UNKNOWN
    history = found.get("history")
    if history is False:
        return PowerWait.HISTORY_BEHIND
    if history is not True:
        return PowerWait.CODEX_UNKNOWN
    running, queued = found.get("running"), found.get("queued")
    if not (_count(running) and _count(queued)):
        return PowerWait.CODEX_UNKNOWN
    if running:
        return PowerWait.TURN_RUNNING
    if queued:
        return PowerWait.QUEUED_INPUT
    return None


def judge_presence(action, others, idle):
    """Steps 13 and 14, from what Windows said: None when nobody is in the way, or why to wait. A shut
    down never happens while another person is signed in, or when that cannot be told (Q6); and no
    action while this PC has been used in the last IDLE_SECONDS, or when Windows did not say (Q3)."""
    if action == PowerAction.SHUT_DOWN and (not _count(others) or others > 0):
        return PowerWait.OTHER_PEOPLE
    if type(idle) not in (int, float) or idle != idle or idle < 0:
        return PowerWait.IDLE_UNKNOWN
    if idle < IDLE_SECONDS:
        return PowerWait.PERSON_ACTIVE
    return None


def countdown_holds(started_at: float, last_look: float, now: float, idle) -> bool:
    """Whether a countdown that began at `started_at`, and was last looked at at `last_look`, still
    holds at `now`: no input since it began (`idle` seconds since the last), and no gap of more than
    GAP_SECONDS between two looks, either way - a sleep, a stalled tick or a clock set right."""
    if type(idle) not in (int, float) or idle != idle or idle < now - started_at:
        return False
    return abs(now - last_look) <= GAP_SECONDS
