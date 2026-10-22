r"""The Windows account's own CODEX_HOME, read and never written (v0.6.18; homefind.py says what it is for).

One value is asked, `CODEX_HOME` under HKEY_CURRENT_USER\Environment - where Windows keeps the variables a
person sets for their own account, and from which it hands them to every program started after - opened for
reading alone. It is a content-free question: a folder Codex is told to keep its state in. A value of the
string types alone is taken; one to expand (REG_EXPAND_SZ) is expanded as Windows would for a new program.
Not there, unreadable, or of another type: no answer, never an error.

`_winreg` is the one way in, so a test can stand in for the registry (tests/test_home_suggestions.py) - and
the suite never reads this machine's: homefind.py asks here only for an installed copy, and the suite runs
from a checkout.
"""
from __future__ import annotations

import os

KEY = "Environment"
NAME = "CODEX_HOME"


def _winreg():
    """The registry module, or None where there is none (not Windows)."""
    if os.name != "nt":
        return None
    import winreg  # noqa: WPS433 - Windows-only module
    return winreg


def codex_home(registry=None) -> str | None:
    """The account's CODEX_HOME as Windows holds it, expanded - or None. Never raises."""
    registry = registry if registry is not None else _winreg()
    if registry is None:
        return None
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, KEY, 0, registry.KEY_READ) as key:
            data, kind = registry.QueryValueEx(key, NAME)
        if kind == registry.REG_EXPAND_SZ and isinstance(data, str):
            data = registry.ExpandEnvironmentStrings(data)
        elif kind != registry.REG_SZ:
            return None
    except (OSError, ValueError, TypeError):
        return None
    return data.strip() if isinstance(data, str) and data.strip() else None
