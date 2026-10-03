"""The power action's closed vocabularies (v0.6.12): what it does, after what, how often, why it waits.

Once every usage-limit recovery of a batch has ended and nothing else waits or runs in Codex, the
watcher may put this PC to sleep, hibernate it or shut it down - off by default, armed only in the
Dashboard (poweraction.py says the rules). Every word it stores, shows or logs is a member of one of
these lists, out of domain/vocabulary.py, which is at its line budget; poweraction.py names each list
as a tuple, the way power.py names the keep-awake ones.

Pure: nothing here but the enums.
"""
from __future__ import annotations

from enum import StrEnum


class PowerAction(StrEnum):
    """What the PC is made to do (poweraction.ACTIONS)."""
    SLEEP = "sleep"
    HIBERNATE = "hibernate"
    SHUT_DOWN = "shut_down"


class PowerAfter(StrEnum):
    """When it may act (poweraction.AFTERS): every recovery of the batch succeeded; each succeeded or was
    handed over to a person, and at least one succeeded; or each ended, however it ended."""
    ALL_RECOVERED = "all_recovered"
    HANDED_OVER_TOO = "handed_over_too"
    ANY_END = "any_end"


class PowerRepeat(StrEnum):
    """How often (poweraction.REPEATS): for the next batch only, or for every one."""
    ONCE = "once"
    ALWAYS = "always"


class PowerPhase(StrEnum):
    """What the watcher last showed of an arming (poweraction.PHASES): waiting, or counting down."""
    WAITING = "waiting"
    GRACE = "grace"


class PowerWait(StrEnum):
    """Why an armed power action has not acted yet (poweraction.WAITS), each a line of its own."""
    NO_BATCH = "no_batch"
    RECOVERY_OPEN = "recovery_open"
    DELIVERY_UNKNOWN = "delivery_unknown"
    TURN_RUNNING = "turn_running"
    QUEUED_INPUT = "queued_input"
    CODEX_UNKNOWN = "codex_unknown"
    HISTORY_BEHIND = "history_behind"
    OTHER_PEOPLE = "other_people"
    PERSON_ACTIVE = "person_active"
    IDLE_UNKNOWN = "idle_unknown"
    PAUSED = "paused"
    WATCHER = "watcher"


class PowerEnd(StrEnum):
    """How a batch ended (poweraction.ENDS): the action was done, Windows refused it, a person stopped
    it, not every recovery ended as chosen, they had ended while nobody watched, a Once found no usage
    limit within a day, or Windows could not do it then."""
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_MET = "not_met"
    STALE = "stale"
    LAPSED = "lapsed"
    UNAVAILABLE = "unavailable"


class PowerClass(StrEnum):
    """What one finished recovery counts as (poweraction.CLASSES), by its own state and reason."""
    SUCCESS = "success"
    PERSON = "person"
    OTHER = "other"


class PowerNotice(StrEnum):
    """What a power-action notification is about (notifier.POWER_STATUS, whose kinds end notifier.STATUS after
    vocabulary.NoticeKind's): a countdown, the action now, Windows refused it, a Once ended without it, and a
    person stopped it for its batch."""
    POWER_GRACE = "power_grace"
    POWER_NOW = "power_now"
    POWER_FAILED = "power_failed"
    POWER_NOT_MET = "power_not_met"
    POWER_STOPPED = "power_stopped"


class PowerUnavailable(StrEnum):
    """Why Windows will not do an action for this account on this PC (poweraction.UNAVAILABLE)."""
    NO_PRIVILEGE = "no_privilege"
    NO_SLEEP_STATE = "no_sleep_state"
    HIBERNATE_OFF = "hibernate_off"
