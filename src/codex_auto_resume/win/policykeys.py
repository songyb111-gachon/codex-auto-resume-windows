r"""The administrator's policy keys, read and never written (v0.6.11; managed.py says what they mean).

Two places are asked, HKEY_LOCAL_MACHINE's first and then HKEY_CURRENT_USER's, each at
`Software\Policies\CodexAutoResume`, and only for the seven values managed.VALUES names, each opened
for reading alone. It is a content-free question - a switch, a number, two times of day - and the
answer is handed to managed.parse as it came, data and type together, for it to judge.

A place that is not there, or does not hold a value, is an empty answer for it, never an error: most
PCs have no key at all. A place or a value that is there and cannot be read - access is denied, say -
is never taken for one that is not there, which would lift what an administrator set: it is handed on
as UNREADABLE, and managed.parse holds the most such a value could hold. A 64-bit view is asked for,
so a 32-bit Python reads the place an administrator's tools write.

`_winreg` is the one way in, so a test can stand in for the registry (tests/test_managed.py) - and
the suite never reads this machine's: control/policy.py asks here only for an installed copy, and
the suite runs from a checkout.
"""
from __future__ import annotations

import os

# Imported by name only, so this module needs nothing of the package at import.
KEY = r"Software\Policies\CodexAutoResume"
NAMES = ("DisableAutoResume", "ForceObserveOnly", "DisableUpdateCheck", "DisableStatusFile",
         "MaxRecoveryAttempts", "QuietHours", "DisablePowerAction")
# A value that is there and could not be read, as (data, type): no registry type is negative, and
# managed.REG_UNREADABLE is this one.
UNREADABLE = (None, -1)


def _winreg():
    """The registry module, or None where there is none (not Windows)."""
    if os.name != "nt":
        return None
    import winreg  # noqa: WPS433 - Windows-only module
    return winreg


def read() -> list:
    """[HKEY_LOCAL_MACHINE's, HKEY_CURRENT_USER's]: each a mapping of a value's name to its
    (data, type), holding only the values that are there - and UNREADABLE for each one that is there
    and could not be read, or for all seven where the place is there and could not be opened. Only
    "not there" (FileNotFoundError) is an empty answer. Never raises."""
    winreg = _winreg()
    if winreg is None:
        return []
    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    places = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        found = {}
        try:
            with winreg.OpenKey(root, KEY, 0, access) as key:
                for name in NAMES:
                    try:
                        data, kind = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    except OSError:
                        found[name] = UNREADABLE
                        continue
                    found[name] = (data, kind)
        except FileNotFoundError:
            pass
        except OSError:
            found = dict.fromkeys(NAMES, UNREADABLE)
        places.append(found)
    return places
