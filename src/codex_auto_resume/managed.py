r"""What an administrator has set: the standard edition's policy keys (v0.6.11).

Six values under `Software\Policies\CodexAutoResume`, in HKEY_LOCAL_MACHINE for everyone who uses
the PC or in HKEY_CURRENT_USER for one person. This product reads them and never writes them
(win/policykeys.py reads them; startup.py is still the only module that writes the registry), and
each one can only hold recovery back:

    DisableAutoResume     REG_DWORD, not 0   recovery is paused, and cannot be resumed while it is set
    ForceObserveOnly      REG_DWORD, not 0   Observe only: every check runs, and nothing is sent
    DisableUpdateCheck    REG_DWORD, not 0   the Dashboard's Check for updates is not offered
    DisableStatusFile     REG_DWORD, not 0   no status file for other tools is written
    MaxRecoveryAttempts   REG_DWORD, 1-20    the most attempts a task gets: a ceiling on that setting
    QuietHours            REG_SZ             "22:00-07:00", or "22:00-07:00 weekdays" (or weekends,
                                             every_day): quiet hours that hold whatever else is set

Both places are read, and every restriction either one makes holds: a switch set in either is set,
the lower ceiling is the ceiling, and each place's quiet hours hold. A value of the wrong type, out
of its range or not in its form is ignored, as if it were not there; nothing here can be read as a
restriction lifted, because there is no value that lifts one. Times are on the hour or the half hour,
as the settings' own list of quiet hours has them; any minute and any days are a person's own Custom...
(v0.6.11, ownvalues.py), and a key's form stays what it was.

A value that is there and could not be read (REG_UNREADABLE: access denied, say) is never taken for
one that is not there - that would lift what an administrator set. It holds the most it could: a
switch is set, the ceiling is the lowest a key may give, and quiet hours whose times cannot be read
could be any hours, so nothing is sent at any of them, as ForceObserveOnly says. A place that is
there and cannot be opened is six such values.

They are applied after the settings are read and coerced (`clamp`), to the settings every part of
the product works from - never to the file, so a person's own choices are kept and are what applies
again once the key is gone. A write that would loosen what a key holds is refused (`admit`), and a
write of what the key already makes it is kept out of the file for the same reason. Quiet hours are
asked of every window at once (`quiet_sources`): the one the settings show, a person's own and each
administrator's, so a window of either never shortens the other.

Nothing here reads the registry, the clock or a file. What the keys said is handed in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from . import quiet, settings

KEY = r"Software\Policies\CodexAutoResume"

DISABLE_AUTO_RESUME = "DisableAutoResume"
FORCE_OBSERVE_ONLY = "ForceObserveOnly"
DISABLE_UPDATE_CHECK = "DisableUpdateCheck"
DISABLE_STATUS_FILE = "DisableStatusFile"
MAX_RECOVERY_ATTEMPTS = "MaxRecoveryAttempts"
QUIET_HOURS = "QuietHours"
# Every value this reads, in the order a list of them is shown (`codes`). Nothing else under the key
# is read: a value this does not name is not asked for.
VALUES = (DISABLE_AUTO_RESUME, FORCE_OBSERVE_ONLY, DISABLE_UPDATE_CHECK, DISABLE_STATUS_FILE,
          MAX_RECOVERY_ATTEMPTS, QUIET_HOURS)
_SWITCHES = (DISABLE_AUTO_RESUME, FORCE_OBSERVE_ONLY, DISABLE_UPDATE_CHECK, DISABLE_STATUS_FILE)

# The registry's own type numbers (winreg.REG_*), so this module needs no Windows module to read them.
REG_SZ, REG_EXPAND_SZ, REG_DWORD, REG_QWORD = 1, 2, 4, 11
# Not a registry type: what the reader hands on for a value that is there and could not be read
# (win/policykeys.UNREADABLE).
REG_UNREADABLE = -1

# The setting a status file for other tools is switched by (statusfile.py). While DisableStatusFile is
# set it is held at its default, which is off, like every new setting's; the watcher then writes no
# status file and removes the one it wrote before.
STATUS_FILE_FIELDS = ("status_file",)

_QUIET = re.compile(r"^\s*(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})(?:\s+([a-z_]+))?\s*$")


@dataclass(frozen=True)
class Managed:
    """What the keys hold, once both places are read: each restriction, and nothing else."""
    disable_auto_resume: bool = False
    force_observe_only: bool = False
    disable_update_check: bool = False
    disable_status_file: bool = False
    max_recovery_attempts: int | None = None
    # Each place's quiet hours, as the three settings that name a window, HKEY_LOCAL_MACHINE's first.
    quiet_hours: tuple = field(default=())

    @property
    def active(self) -> bool:
        return bool(self.codes())

    def codes(self) -> list:
        """The values in force, by their registry names, in VALUES order: what Diagnostics lists."""
        held = {DISABLE_AUTO_RESUME: self.disable_auto_resume, FORCE_OBSERVE_ONLY: self.force_observe_only,
                DISABLE_UPDATE_CHECK: self.disable_update_check, DISABLE_STATUS_FILE: self.disable_status_file,
                MAX_RECOVERY_ATTEMPTS: self.max_recovery_attempts is not None,
                QUIET_HOURS: bool(self.quiet_hours)}
        return [name for name in VALUES if held[name]]


NONE = Managed()


def _switch(entry) -> bool:
    value, kind = entry
    return kind in (REG_DWORD, REG_QWORD) and isinstance(value, int) and not isinstance(value, bool) \
        and value != 0


def _ceiling(entry):
    value, kind = entry
    if kind not in (REG_DWORD, REG_QWORD) or isinstance(value, bool) or not isinstance(value, int):
        return None
    low, high = settings.RANGES["max_recovery_attempts"]["min"], settings.RANGES["max_recovery_attempts"]["max"]
    return value if low <= value <= high else None


def quiet_window(text):
    """A QuietHours value as the three settings that name the same window, or None when it is not
    one: two different times on the hour or the half hour, and a closed word for the days."""
    if not isinstance(text, str):
        return None
    found = _QUIET.match(text)
    if found is None:
        return None
    start, end, days = found.group(1), found.group(2), found.group(3) or quiet.DEFAULT_DAYS
    if start not in quiet.TIMES or end not in quiet.TIMES or start == end or days not in quiet.DAYS:
        return None
    return {"quiet_hours_start": start, "quiet_hours_end": end, "quiet_hours_days": days}


def _unreadable(entry) -> bool:
    return isinstance(entry, tuple) and len(entry) == 2 and entry[1] == REG_UNREADABLE


def parse(places) -> Managed:
    """What `places` hold - one mapping for each place read, HKEY_LOCAL_MACHINE's first, each of a
    value's name to its (data, registry type) - with every restriction of either kept, and the most
    a value could hold kept for one that could not be read."""
    switches, ceilings, windows = set(), [], []
    for place in places or ():
        if not isinstance(place, dict):
            continue
        for name in _SWITCHES:
            entry = place.get(name)
            if _unreadable(entry) or (isinstance(entry, tuple) and len(entry) == 2 and _switch(entry)):
                switches.add(name)
        entry = place.get(MAX_RECOVERY_ATTEMPTS)
        if _unreadable(entry):
            ceilings.append(settings.RANGES["max_recovery_attempts"]["min"])
        elif isinstance(entry, tuple) and len(entry) == 2 and _ceiling(entry) is not None:
            ceilings.append(_ceiling(entry))
        entry = place.get(QUIET_HOURS)
        if _unreadable(entry):
            switches.add(FORCE_OBSERVE_ONLY)
        elif isinstance(entry, tuple) and len(entry) == 2 and entry[1] in (REG_SZ, REG_EXPAND_SZ):
            window = quiet_window(entry[0])
            if window is not None and window not in windows:
                windows.append(window)
    return Managed(disable_auto_resume=DISABLE_AUTO_RESUME in switches,
                   force_observe_only=FORCE_OBSERVE_ONLY in switches,
                   disable_update_check=DISABLE_UPDATE_CHECK in switches,
                   disable_status_file=DISABLE_STATUS_FILE in switches,
                   max_recovery_attempts=min(ceilings) if ceilings else None,
                   quiet_hours=tuple(windows))


def fields(managed: Managed) -> frozenset:
    """The settings a key decides while it is set: each surface draws them greyed, as set by your
    administrator, and a write to one is `admit`'s to judge."""
    names = set()
    if managed.force_observe_only:
        names.add("observe_only")
    if managed.max_recovery_attempts is not None:
        names.add("max_recovery_attempts")
    if managed.quiet_hours:
        names.update(("quiet_hours_start", "quiet_hours_end", "quiet_hours_days"))
    if managed.disable_status_file:
        names.update(name for name in STATUS_FILE_FIELDS if name in settings.FIELDS)
    return frozenset(names)


def clamp(values: dict, managed: Managed) -> dict:
    """The settings as the keys leave them: Observe only on, the attempts no higher than the
    ceiling, the quiet hours the settings show the first administrator's window, and the status
    file off. With no key set, `values` itself, untouched."""
    if not managed.active:
        return values
    held = dict(values)
    if managed.force_observe_only:
        held["observe_only"] = True
    ceiling, own = managed.max_recovery_attempts, held.get("max_recovery_attempts")
    if ceiling is not None and isinstance(own, int) and not isinstance(own, bool):
        held["max_recovery_attempts"] = min(own, ceiling)
    if managed.quiet_hours:
        held.update(managed.quiet_hours[0])
    if managed.disable_status_file:
        held.update({name: settings.DEFAULTS[name] for name in STATUS_FILE_FIELDS if name in settings.FIELDS})
    return held


def admit(changes: dict, effective: dict, managed: Managed):
    """An edit, as the keys let it be stored: (what to write, the first setting refused or None).

    A change to a setting no key decides is written as it is. One that says what a key already
    makes it - Observe only on, the ceiling, the administrator's quiet hours - is left out, so a
    surface that sends every value back does not write the key's value over the person's own. A
    lower number of attempts, or another within the ceiling, is the person's to keep. Anything
    else a key decides is refused."""
    decided, kept = fields(managed), {}
    for name, value in changes.items():
        if name not in decided:
            kept[name] = value
        elif value == effective.get(name) and type(value) is type(effective.get(name)):
            continue
        elif (name == "max_recovery_attempts" and isinstance(value, int) and not isinstance(value, bool)
              and value <= managed.max_recovery_attempts):
            kept[name] = value
        else:
            return kept, name
    return kept, None


def quiet_sources(own: dict, managed: Managed) -> tuple:
    """Every window quiet hours are asked of: the settings' own and each administrator's. The
    latest end any of them gives is when a recovery may go; with no key set, the settings' alone."""
    return (own,) + tuple(managed.quiet_hours)
