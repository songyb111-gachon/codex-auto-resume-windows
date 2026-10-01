"""A person's own value beside a drop-down's choices (v0.6.11): Custom..., and Unlimited.

The owner's words: a time limit or the days of the week should be choosable as a person likes, not
only from the list. So every drop-down of a value - a wait, a time of day, the days quiet hours start
on, a number of hours, megabytes or tokens - offers its choices and, last, Custom...: a value of the
person's own, stored in the words its choices are stored in (`m45` beside `m30`, `13:15` beside
`13:00`, `mon,wed,fri` beside `weekdays`, `mb1280` beside `mb1024`, `above_300k` beside
`above_250k`), within the bounds its module gives it here. A limit that is only the person's own
also has Unlimited - how long this PC is kept awake is the one (power.py); every other such list
already starts with Off, which is no limit at all, and a second word for it would be two ways to one
result.

Never Unlimited, and never a value past its bounds, where a bound keeps recovery safe (standards
A20-A22): the engine's 15 minutes between two continuations and five a day are not settings at all,
the attempt budgets stay numbers in their ranges, and a retry wait of the person's own lies between
its list's first and last.

One rule. Whether a value is taken, and how it is written down, is answered here and nowhere else:
the settings layer coerces every such field with `coerce` and takes a write that `canonical` spells
as what it stores; the modules that read one ask `amount`; describe() publishes `published` for the
Dashboard and the panel, which compose the words from what a person typed and show the range - and
never judge a value themselves: the Dashboard asks the bridge (`check-setting`), the panel's Save
asks update_settings, and both are answered by the settings validator, which is this.

One value, one spelling. A value is kept in its shortest exact form - 60 minutes is `h1`, 90 is `m90`,
a thousand thousand tokens `above_1m` - and a set of days a choice names is that choice, so no two
stored words mean one thing. Any other exact spelling a person or a surface sends (`m60`, `7:05`,
`fri,mon`) is taken as that form, never refused for how it was written.

Pure: words in, words and numbers out.
"""
from __future__ import annotations

import re
from typing import NamedTuple

DURATION, CLOCK, DAYS, COUNT = "duration", "clock", "days", "count"
UNLIMITED = "unlimited"
MINUTE, HOUR, DAY = 60, 3600, 86400
WEEK = 7 * DAY
# A duration's units, as its words start - `s5`, `m45`, `h3` - and a count's, as its words end.
DURATION_UNITS = {"s": 1, "m": MINUTE, "h": HOUR}
COUNT_UNITS = {"": 1, "k": 1000, "m": 1000 * 1000}
# The days, as `time.struct_time.tm_wday` counts them - Monday is 0 - and the sets a choice names.
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
NAMED_DAYS = {frozenset(range(7)): "every_day", frozenset(range(5)): "weekdays", frozenset({5, 6}): "weekends"}

_DURATION = re.compile(r"([smh])([0-9]{1,7})\Z")
_CLOCK = re.compile(r"([0-9]{1,2}):([0-9]{2})\Z")
_COUNT = re.compile(r"([0-9]{1,9})([km]?)\Z")


class Own(NamedTuple):
    """What a field takes of a person's own: its kind, its bounds in the kind's own measure - seconds,
    or a count - and its units, the first of them the finest a value may be: a duration's are the ones a
    surface offers to type it in, a count's the ones its words are spelled with. A time of day and a set of
    days need neither. A count may name the catalog's words for an amount of it (`amount`, own.mb: "{n} MB") and
    for its drop-down item (`label`, own.hold_above: "Hold above {n}"); a count without them is said as a number."""
    kind: str
    low: int = 0
    high: int = 0
    units: tuple = ()
    prefix: str = ""
    amount: str = ""
    label: str = ""


def _whole(digits: str) -> int | None:
    """Digits as a number from 1 up; None for 0, or for a number written with a leading zero, which is
    no spelling this module writes and one a person does not mean."""
    return int(digits) if digits[0] != "0" else None


def amount(spec, value):
    """What `value` measures under `spec` - seconds, a minute of the day, a frozenset of weekdays or a
    count - or None when it is none: not this kind's words, finer than its first unit, or out of bounds.
    A named choice of days is its set; every other choice is for the module that lists it."""
    if spec is None or not isinstance(value, str):
        return None
    if spec.kind == DAYS:
        if value in NAMED_DAYS.values():
            return next(days for days, name in NAMED_DAYS.items() if name == value)
        names = value.split(",")
        if not all(name in DAY_NAMES for name in names):
            return None
        return frozenset(DAY_NAMES.index(name) for name in names)
    if spec.kind == CLOCK:
        found = _CLOCK.match(value)
        if found is None or int(found.group(1)) > 23 or int(found.group(2)) > 59:
            return None
        return int(found.group(1)) * 60 + int(found.group(2))
    if spec.kind == DURATION:
        found = _DURATION.match(value)
        number = _whole(found.group(2)) if found else None
        if number is None:
            return None
        seconds = number * DURATION_UNITS[found.group(1)]
        finest = DURATION_UNITS[spec.units[0]] if spec.units else 1
        return seconds if spec.low <= seconds <= spec.high and seconds % finest == 0 else None
    if spec.kind == COUNT:
        found = _COUNT.match(value[len(spec.prefix):]) if value.startswith(spec.prefix) else None
        number = _whole(found.group(1)) if found else None
        if number is None or (found.group(2) and found.group(2) not in spec.units):
            return None
        count = number * COUNT_UNITS[found.group(2)]
        finest = COUNT_UNITS[spec.units[0]] if spec.units else 1
        return count if spec.low <= count <= spec.high and count % finest == 0 else None
    return None


def spell(spec, measured) -> str:
    """`measured` in its one spelling: the largest of the kind's units that measures it exactly, a clock's
    two digits each, and a set of days as the choice that names it or as its days in the week's order."""
    if spec.kind == DAYS:
        return NAMED_DAYS.get(frozenset(measured)) or ",".join(DAY_NAMES[day] for day in sorted(measured))
    if spec.kind == CLOCK:
        return "%02d:%02d" % divmod(measured, 60)
    table = DURATION_UNITS if spec.kind == DURATION else COUNT_UNITS
    unit = max((name for name in spec.units or tuple(table) if measured % table[name] == 0), key=table.get)
    number = str(measured // table[unit])
    return unit + number if spec.kind == DURATION else spec.prefix + number + unit


def canonical(spec, value, choices=()):
    """`value` as it is stored, or None when this field does not take it: one of its `choices` as it is,
    and a value of the person's own in its one spelling. An empty set of days is none - it would be quiet
    hours that never start, which quiet hours off already are."""
    if isinstance(value, str) and value in choices:
        return value
    measured = amount(spec, value)
    if measured is None or measured == frozenset():
        return None
    return spell(spec, measured)


def coerce(value, default, choices, spec):
    """The settings layer's coercer for a field with choices and, when `spec` is given, a value of the
    person's own: what is stored, or `default` for anything it does not take."""
    found = canonical(spec, value, choices)
    return default if found is None else found


def pattern(spec) -> str:
    """The words `spec` takes, as a JSON Schema pattern: the form, never the bounds, which `published`
    says beside it and the validator holds."""
    if spec.kind == DAYS:
        return r"^(%s)(,(%s))*$" % (("|".join(DAY_NAMES),) * 2)
    if spec.kind == CLOCK:
        return r"^[0-9]{1,2}:[0-9]{2}$"
    if spec.kind == DURATION:
        return r"^[smh][1-9][0-9]*$"
    suffixes = "|".join(unit for unit in spec.units if unit)
    return r"^%s[1-9][0-9]*%s$" % (re.escape(spec.prefix), "(%s)?" % suffixes if suffixes else "")


def published(spec) -> dict:
    """What describe() says of a field's own values, for the surfaces to draw an editor from: the kind,
    the bounds and units where it has them, a count's prefix and words, and the pattern."""
    said = {"kind": spec.kind, "pattern": pattern(spec)}
    if spec.kind in (DURATION, COUNT):
        said.update(min=spec.low, max=spec.high, units=list(spec.units))
    for name in ("prefix", "amount", "label"):
        if getattr(spec, name):
            said[name] = getattr(spec, name)
    if spec.kind == DAYS:
        said["days"] = list(DAY_NAMES)
        said["named"] = {name: [DAY_NAMES[day] for day in sorted(days)] for days, name in NAMED_DAYS.items()}
    return said


def coercer(choices, spec):
    """`coerce` for one field, as the settings layer's table of fields holds a coercer: (value, default)."""
    return lambda value, default: coerce(value, default, choices, spec)
