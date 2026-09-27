"""Sleep, keeping this PC awake, and the network, as a waiting recovery meets them (v0.6.11).

Three things Windows knows that a recovery waits through. Each is off by default, and then nothing
here is asked, no Windows call is made for it and the watcher waits exactly as v0.6.10 waited:

* Sleep. While Ask after a long sleep or Keep this PC awake is on, the watcher also listens for this
  PC waking (win/power.py): it looks again at once, and forgets what it last read of the app and of
  usage. With Ask after a long sleep on, a waiting recovery that fell due while the PC slept for
  longer than the time chosen waits for a person (the `after_sleep` hold): one notice says how long
  it slept and how many wait, and Pending lets each continue, or not. How long it slept is read
  from two clocks between two ticks - the wall clock, and Windows' count of the time it was awake -
  so a tick that runs before the wake is heard still sees the sleep.
* Keeping awake. The watcher asks Windows not to let this PC sleep on its own while a task waits
  (SetThreadExecutionState, from the thread that ticks), on mains power only or always, for at most
  the hours chosen. It lets go when nothing waits, when the hours are up, when recovery is paused,
  when a tick fails and when it stops. The display may still turn off, and closing the lid or
  choosing Sleep still sleeps the PC. No setting of Windows is changed (F1).
* The network. With Wait for an internet connection on, a recovery that is due asks Windows
  (INetworkListManager, win/network.py) just before usage would be read; while Windows reports no
  internet it waits (`offline`), and no App Server is started for it. When Windows cannot be asked,
  or does not answer, it is as if it had not been: usage is read as in v0.6.10, and decides (E1).

None of them sends anything, skips a check or makes a recovery sooner than its time: waking only
runs the checks sooner, keeping awake only keeps the watcher there to run them, and the other two
only hold back. Pure: settings, records and times in, answers out.
"""
from __future__ import annotations

import math

from .domain.public import eligible_at
from .domain.vocabulary import AwakeCap, HoldKind, KeepAwake, ReasonCode, SleepWait

KEEP_AWAKE_FIELD, AWAKE_CAP_FIELD = "keep_awake", "keep_awake_hours"
SLEEP_FIELD, NETWORK_FIELD = "ask_after_sleep_minutes", "wait_for_network"
KEEP_AWAKE_MODES, AWAKE_CAPS, SLEEP_WAITS = tuple(KeepAwake), tuple(AwakeCap), tuple(SleepWait)
DEFAULT_KEEP_AWAKE, DEFAULT_AWAKE_CAP, DEFAULT_SLEEP = KeepAwake.OFF.value, AwakeCap.H6.value, SleepWait.OFF.value
# The hold a recovery that fell due during a long sleep waits under, and the reason one waits for the
# network under - both words the store and every surface already know.
HOLD = HoldKind.AFTER_SLEEP.value
OFFLINE = ReasonCode.OFFLINE.value
_SECONDS = {"m30": 1800, "h1": 3600, "h2": 7200, "h3": 3 * 3600, "h6": 6 * 3600, "h12": 12 * 3600,
            "h24": 24 * 3600}
# Less than this between the two clocks is no sleep: they drift apart by a little on their own, and a
# wall clock set right by a few seconds is not a PC that slept.
MIN_SLEEP_SECONDS = 60.0


def _values(values) -> dict:
    return values if isinstance(values, dict) else {}


def keep_awake(values) -> str:
    """off, on_ac or always - off for anything the settings layer would not store."""
    chosen = _values(values).get(KEEP_AWAKE_FIELD)
    return chosen if chosen in KEEP_AWAKE_MODES else DEFAULT_KEEP_AWAKE


def awake_cap(values) -> int:
    """For how many seconds, at most, the PC is kept awake for tasks that go on waiting."""
    chosen = _values(values).get(AWAKE_CAP_FIELD)
    return _SECONDS[chosen if chosen in AWAKE_CAPS else DEFAULT_AWAKE_CAP]


def sleep_threshold(values):
    """How long a sleep must last, in seconds, before what fell due during it waits for a person -
    None, never, at the default."""
    chosen = _values(values).get(SLEEP_FIELD)
    return _SECONDS.get(chosen) if chosen in SLEEP_WAITS else None


def waits_for_network(values) -> bool:
    """Whether a due recovery asks Windows about the internet before usage is read: not by default."""
    return _values(values).get(NETWORK_FIELD) is True


def listens(values) -> bool:
    """Whether the watcher listens for this PC waking: while Ask after a long sleep or Keep this PC
    awake is on - never at the defaults, where it waits as v0.6.10 waited."""
    return sleep_threshold(values) is not None or keep_awake(values) != KeepAwake.OFF


def asleep(before, after) -> float:
    """Seconds this PC spent asleep between two readings, each (wall clock, time awake) in seconds:
    what the wall clock moved beyond the time it was awake. 0.0 when a reading is missing or says less
    than a real sleep - including a wall clock set back, which is never a sleep."""
    try:
        slept = (float(after[0]) - float(before[0])) - (float(after[1]) - float(before[1]))
    except (TypeError, ValueError, IndexError):
        return 0.0
    return slept if math.isfinite(slept) and slept >= MIN_SLEEP_SECONDS else 0.0


def fell_due(row, since, until) -> bool:
    """Whether a waiting record fell due in (since, until]: after the last look before a sleep, and by
    the first one after it. A record held for a person has no time (eligible_at), and never did."""
    due = eligible_at(row)
    return due is not None and since < due <= until


def waiting(rows) -> int:
    """How many of these records a PC kept awake would be kept awake for: waiting unsent, not held
    for a person and not asked to stop."""
    return sum(1 for row in rows if eligible_at(row) is not None and not row.get("cancel_requested"))


def wants_awake(mode, count, mains) -> bool:
    """Whether this PC is to be kept awake now, its hours aside: something waits, and `mode` allows it
    on the power it runs on - `mains` True, False on battery, None when Windows cannot say, which
    on_ac takes as not on mains."""
    if mode not in (KeepAwake.ON_AC, KeepAwake.ALWAYS) or count <= 0:
        return False
    return mode == KeepAwake.ALWAYS or mains is True
