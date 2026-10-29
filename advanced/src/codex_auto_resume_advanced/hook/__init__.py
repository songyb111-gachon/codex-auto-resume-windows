# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Stop hook (stop_hook_continuation, v0.6.20): the handler Codex runs, through gui/HookLauncher.cs, when a turn
stops - its input read through an allow-list of keys (handler.py), and the format Codex declares, calls and hears it
in, in one place (format.py).

`main` is what the launcher calls: the handler, then the process ends at once with its code, so a read still blocked
on a pipe past the budget is never waited for.
"""
from __future__ import annotations


def main(argv=None) -> int:
    import os
    import sys
    from .handler import main as handle
    code = 0
    try:
        code = handle(argv)
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(code)
    return code
