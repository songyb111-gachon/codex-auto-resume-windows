"""Words every surface writes the same way.

A remaining time is the first of them. The icon's tooltip and the popup both show one, and
they showed it through the same function - which lived in the icon, so the popup imported the
icon to draw a clock. That is one of the import cycles `tests/test_layers.py` lists.

Locale-neutral on purpose: digits and a colon read the same in every language, and a
duration that says "3 minutes" in one of them would have to be translated to say anything at
all in the others.
"""
from __future__ import annotations


def countdown(seconds: float) -> str:
    """A short, locale-neutral duration: 45s, 12:04, 3:05:00."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    if minutes:
        return "%d:%02d" % (minutes, secs)
    return "%ds" % secs


# ------------------------------------------------------------------ usage, the last reading (v0.6.11)
# Said the same way by the popup here and by the window and the panel in their own code, from the same
# catalog words (tests/test_usage_reading.py holds the three to one example): each window's length and
# share, when it resets, and how long ago the reading was made.
def age(seconds, say) -> str:
    """How long ago, in the largest unit that is not zero, as the window says it (SettingsForm.Age)."""
    total = max(0, int(seconds))
    if total < 5:
        return say("time.just_now")
    for limit, key, unit in ((60, "time.seconds", 1), (3600, "time.minutes", 60),
                             (86400, "time.hours", 3600), (None, "time.days", 86400)):
        if limit is None or total < limit:
            return say("time.ago", time=say(key, n=total // unit))
    return say("time.just_now")          # not reached


def clock_time(at, now) -> str:
    """A moment later today as the clock shows it, and any other with its date (SettingsForm.ClockTime)."""
    import time
    moment, today = time.localtime(at), time.localtime(now)
    if moment[:3] == today[:3]:
        return time.strftime("%H:%M", moment)
    return time.strftime("%Y-%m-%d %H:%M", moment)


WEEK_MINUTES = 7 * 24 * 60              # Codex's weekly window, which is named "weekly"


def window_name(minutes, say) -> str:
    """How a usage window's length is named: weekly, or in days, hours or minutes - "limit" when Codex
    gave no length. The window (SettingsForm.WindowName) and the panel (windowName) name it alike."""
    if type(minutes) is not int or minutes <= 0:
        return say("usage.limit")
    if minutes == WEEK_MINUTES:
        return say("usage.weekly")
    for size, key in ((1440, "usage.days"), (60, "usage.hours")):
        if minutes % size == 0:
            return say(key, n=minutes // size)
    return say("usage.minutes", n=minutes)


def share(window) -> int:
    """The share used as a whole number, never rounded up to 100: 99.6% is not used up."""
    used = window.get("used_percent") or 0
    return 100 if used >= 100 else int(used // 1)


def usage_windows(windows, say, now) -> str:
    """Each window of a reading: its length, its share, and when it resets where Codex said."""
    parts = []
    for window in windows or ():
        name = window_name(window.get("window_minutes"), say)
        if window.get("reset_at"):
            parts.append(say("usage.window_resets", window=name, percent=share(window),
                             time=clock_time(window["reset_at"], now)))
        else:
            parts.append(say("usage.window", window=name, percent=share(window)))
    return " · ".join(parts)


def usage_line(reading, say, now):
    """The last usage reading as one line, with its age - or None when there is none."""
    if not isinstance(reading, dict) or not reading.get("windows") or not reading.get("read_at"):
        return None
    return say("usage.line", age=age(now - reading["read_at"], say),
               windows=usage_windows(reading["windows"], say, now))
