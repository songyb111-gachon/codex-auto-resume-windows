"""Quiet hours, and the times a postponement may name: local clock time, worked out in one place.

Quiet hours are three settings: when they start - `off`, the default, a half hour or a minute of a
person's own - when they end, and which days they start on: a named choice, or any days a person
picks (ownvalues.py). A recovery that falls due inside them waits until they end,
and nothing else about it changes: the thirteen gates, the budgets and the caps are the ones they
were, and quiet time is a reason of the schedule gate (domain/gates.py), asked by the engine, again
inside the claim and again at the last look before the send. Off, nothing here is ever asked.

A postponement is a person's: this record, not before this time. It only ever makes a record later,
and never by more than a week - a task asked to wait longer than that is one to cancel.

Both are local wall-clock time, the time on the clock a person set them by, and both are read
through Windows' own conversion (`time.localtime`, `time.mktime`), which the tests replace with a
zone of their own to walk a window across midnight and across a change to or from summer time. A
half hour a spring change skips is taken as the clock takes it; a window never lasts past the end
the person set on the clock.
"""
from __future__ import annotations

import math
import time

from . import ownvalues
from .domain.vocabulary import QuietDays

OFF = "off"
# Every half hour of the day, as a clock shows it. A choice, not free text: a settings surface draws
# a list, and nothing a person or a model types is ever parsed.
TIMES = tuple("%02d:%02d" % divmod(minute, 60) for minute in range(0, 24 * 60, 30))
STARTS = (OFF,) + TIMES
DAYS = tuple(QuietDays)
DEFAULT_START, DEFAULT_END, DEFAULT_DAYS = OFF, "07:00", QuietDays.EVERY_DAY.value
# v0.6.11: Custom... - any minute of the day for either end, and any days (ownvalues.py). A set of days is
# read as `time.struct_time.tm_wday` counts it: Monday is 0; each choice names one (ownvalues.NAMED_DAYS).
OWN = {"quiet_hours_start": ownvalues.Own(ownvalues.CLOCK), "quiet_hours_end": ownvalues.Own(ownvalues.CLOCK),
       "quiet_hours_days": ownvalues.Own(ownvalues.DAYS)}

# A postponement: the choices every surface offers, and the furthest ahead one may be.
MAX_POSTPONE_SECONDS = 7 * 86400
PRESETS = ("30_minutes", "1_hour", "3_hours", "tomorrow_morning")
_AHEAD = {"30_minutes": 1800, "1_hour": 3600, "3_hours": 3 * 3600}
MORNING = "09:00"


def _minutes(text) -> int:
    hours, minutes = str(text).split(":")
    return int(hours) * 60 + int(minutes)


def window(values):
    """(start, end, weekdays) in minutes of the day, or None: quiet hours off, or not a window.

    Read the way the settings layer reads them, so anything it would not store is off. A window
    whose end is its start is none at all, never the whole day."""
    values = values if isinstance(values, dict) else {}
    start = ownvalues.amount(OWN["quiet_hours_start"], values.get("quiet_hours_start"))
    end = ownvalues.amount(OWN["quiet_hours_end"], values.get("quiet_hours_end"))
    days = ownvalues.amount(OWN["quiet_hours_days"], values.get("quiet_hours_days", DEFAULT_DAYS))
    if start is None or end is None or start == end or not days:
        return None
    return start, end, days


def _local(day, minute, *, mktime):
    """The moment `minute` of the day falls on the date `day` - a (year, month, day) that may run
    past the month's end, which mktime carries over - on the local clock."""
    year, month, date = day
    return float(mktime((year, month, date, minute // 60, minute % 60, 0, 0, 0, -1)))


def quiet_until(now, values, *, localtime=time.localtime, mktime=time.mktime):
    """The end of the quiet hours `now` falls in, or None when it falls in none (or they are off).

    Two windows can hold `now`: one that started yesterday and runs past midnight, and today's.
    Each counts only on a day it may start on."""
    found = window(values)
    if found is None or not isinstance(now, (int, float)) or not math.isfinite(now):
        return None
    start, end, weekdays = found
    today = localtime(now)
    for back in (1, 0):
        day = (today.tm_year, today.tm_mon, today.tm_mday - back)
        # The weekday of that date, asked at noon, where no change of the clock ever falls.
        if localtime(_local(day, 12 * 60, mktime=mktime)).tm_wday not in weekdays:
            continue
        begins = _local(day, start, mktime=mktime)
        ends = _local((day[0], day[1], day[2] + (0 if end > start else 1)), end, mktime=mktime)
        if begins <= now < ends:
            return ends
    return None


def postpone_time(now, preset, *, localtime=time.localtime, mktime=time.mktime):
    """When one of PRESETS lands from `now`: half an hour, an hour, three hours ahead, or 09:00
    on the local clock tomorrow. None for anything else."""
    if preset in _AHEAD:
        return float(now) + _AHEAD[preset]
    if preset == "tomorrow_morning":
        today = localtime(now)
        return _local((today.tm_year, today.tm_mon, today.tm_mday + 1), _minutes(MORNING), mktime=mktime)
    return None


def postponement_problem(until, now, not_before=None):
    """Why `until` cannot be a record's postponement, as an error code - or None.

    A time, later than now and than any postponement the record already has - it only ever moves
    a record later - and no more than a week ahead."""
    if (isinstance(until, bool) or not isinstance(until, (int, float))
            or not math.isfinite(until)):
        return "invalid_time"
    if until <= now or (not_before is not None and until <= not_before):
        return "not_later"
    if until > now + MAX_POSTPONE_SECONDS:
        return "too_far"
    return None
