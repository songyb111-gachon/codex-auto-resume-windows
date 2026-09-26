"""How long a temporary failure waits before its continuation: the ladders, and what a person is shown.

A ladder is five waits. The three presets are v0.6.10's, unchanged, and so is what the watcher does
with them: every interruption of a temporary kind waits the preset's first step once it is detected
(a rate limit at least a minute, standard A22), and the engine's own floor - a continuation to one
conversation at most every 15 minutes, five in any 24 hours (A20) - does the rest.

Custom (v0.6.11) is five waits a person picks, each from a closed list - never a number a person or a
model types, so no wait can be zero or unbounded. The n-th attempt at a task waits the n-th of them,
and the fifth again after that. The engine floor is not a setting and binds whatever is picked, which
is why the second to fifth waits start at 15 minutes: a shorter one would be the floor anyway, and a
list that offered it would show a person a wait the watcher never keeps (`preview`).

Three more things only ever lengthen a wait. A wait Codex names in a structured error (a Retry-After)
is the least the first wait may be (failures.retry_after). Jitter, off by default, adds up to a fifth
to each wait. And the time ceiling, off by default, stops a task whose temporary failures have gone on
for longer than it, measured from its first failure to its latest - so a postponement, quiet hours or
a closed app never count against it.

Pure: nothing here reads a clock, a file or Codex. The engine asks it (engine/options.py), the settings
publish what the surfaces draw from it (settings.describe), and the preview is the same function for
the Dashboard, the panel and the tests.
"""
from __future__ import annotations

import math

from .domain.vocabulary import ChainCeiling, RetryTiming, RetryWait

# The presets, v0.6.10's own (settings.RETRY_TIMING is this table).
PRESETS = {
    RetryTiming.CONSERVATIVE.value: (15, 45, 120, 300, 600),
    RetryTiming.NORMAL.value: (5, 15, 30, 60, 120),
    RetryTiming.AGGRESSIVE.value: (3, 8, 20, 45, 90),
}
CUSTOM = RetryTiming.CUSTOM.value
TIMINGS = tuple(RetryTiming)
DEFAULT_TIMING = RetryTiming.NORMAL.value

# The engine's floor for one conversation (engine/options.py: thread_cooldown_seconds and
# max_submissions_per_thread_per_day). Constants of the engine, never settings; said here for the
# preview and the choice lists, and held equal to the engine's by tests/test_ladder_and_guards.py.
SPACING = 900
PER_DAY = 5
# A rate limit's first wait is never shorter (A22): Codex already retried it several times.
RATE_LIMIT_FIRST = 60

WAIT_SECONDS = {
    RetryWait.S5: 5, RetryWait.S15: 15, RetryWait.S30: 30, RetryWait.M1: 60, RetryWait.M2: 120,
    RetryWait.M5: 300, RetryWait.M10: 600, RetryWait.M15: 900, RetryWait.M30: 1800,
    RetryWait.H1: 3600, RetryWait.H2: 7200, RetryWait.H3: 10800, RetryWait.H6: 21600,
}
WAITS = tuple(RetryWait)
# The first wait comes before a task's first continuation, so it may be short; every later one comes
# after a continuation of the same task, where the floor is 15 minutes whatever is chosen.
FIRST_WAITS = tuple(wait.value for wait in WAITS if WAIT_SECONDS[wait] <= 7200)
LATER_WAITS = tuple(wait.value for wait in WAITS if WAIT_SECONDS[wait] >= SPACING)
STEP_FIELDS = tuple("retry_wait_%d" % number for number in range(1, 6))
# Custom, left as it comes: Normal's own sequence when each continuation fails at once - five
# seconds, then the 15 minutes the floor makes of every later wait (`preview`).
DEFAULT_STEPS = ("s5", "m15", "m15", "m15", "m15")

CEILINGS = tuple(ChainCeiling)
DEFAULT_CEILING = ChainCeiling.OFF.value
CEILING_SECONDS = {ChainCeiling.OFF: None, ChainCeiling.H1: 3600, ChainCeiling.H3: 3 * 3600,
                   ChainCeiling.H6: 6 * 3600, ChainCeiling.H12: 12 * 3600, ChainCeiling.H24: 24 * 3600}
# Jitter: up to this share of a wait added to it, never taken off.
JITTER_SHARE = 0.2


def choices_for(field: str) -> tuple:
    """The waits one step of the Custom ladder may be."""
    return FIRST_WAITS if field == STEP_FIELDS[0] else LATER_WAITS


def _values(values) -> dict:
    return values if isinstance(values, dict) else {}


def timing(values) -> str:
    """The timing chosen, read as the settings layer reads it: anything else is Normal."""
    chosen = _values(values).get("retry_timing")
    return chosen if chosen in TIMINGS else DEFAULT_TIMING


def custom_steps(values) -> tuple:
    """The five Custom waits in seconds; a step that is not one of its own choices is its default."""
    found = []
    for field, default in zip(STEP_FIELDS, DEFAULT_STEPS):
        chosen = _values(values).get(field)
        found.append(WAIT_SECONDS[RetryWait(chosen if chosen in choices_for(field) else default)])
    return tuple(found)


def ladder(values) -> tuple:
    """The five waits in effect: a preset's, or the Custom ones."""
    chosen = timing(values)
    return custom_steps(values) if chosen == CUSTOM else PRESETS[chosen]


def walks(values) -> bool:
    """Whether the n-th attempt at a task waits the n-th wait: Custom only. A preset keeps v0.6.10's
    first wait for every interruption, and the floor spaces the rest."""
    return timing(values) == CUSTOM


def wait_before(values, attempt: int, category=None) -> int:
    """The wait between an interruption being detected and its continuation, for the `attempt`-th
    attempt at its task (1 for a task's first). A rate limit's first wait is at least a minute."""
    steps = ladder(values)
    index = max(0, min(int(attempt), len(steps)) - 1) if walks(values) else 0
    delay = steps[index]
    if category == "rate_limit_transient" and (index == 0 or not walks(values)):
        delay = max(RATE_LIMIT_FIRST, delay)
    return delay


def preview(values) -> list:
    """What a person is shown: the wait before each of five attempts at a task, in seconds, if each
    continuation fails at once. The floor is in it - a preset's later waits are its first plus the 15
    minutes that must pass after a continuation - so it is the sequence the watcher keeps, not the one
    it was asked for. Not a rate limit (whose first wait is a minute at least) and without jitter,
    which each surface says in words beside it."""
    steps = ladder(values)
    if walks(values):
        return [steps[0]] + [max(step, SPACING) for step in steps[1:]]
    return [steps[0]] + [steps[0] + SPACING] * (len(steps) - 1)


def previews() -> dict:
    """Every preset's preview, for the surfaces to look up (settings.describe): Custom's is the steps."""
    return {name: preview({"retry_timing": name}) for name in PRESETS}


def jittered(delay, values, draw) -> int:
    """`delay`, lengthened by up to a fifth when jitter is on; `draw` is a number in [0, 1)."""
    if _values(values).get("retry_jitter") is not True:
        return delay
    share = draw if isinstance(draw, float) and 0.0 <= draw < 1.0 else 0.0
    # Rounded before it is rounded up, so 100 s and a tenth is 110 s and never 111 for a float's last digit.
    return int(math.ceil(round(delay * (1.0 + JITTER_SHARE * share), 6)))


def ceiling(values):
    """The time ceiling in seconds, or None: off, the default."""
    chosen = _values(values).get("chain_time_ceiling")
    return CEILING_SECONDS[ChainCeiling(chosen)] if chosen in CEILINGS else None
