"""Command-line interface: enable / disable / status / pending / cancel / logs / run / stop / install / uninstall.

Since v0.6.10-alpha the command bodies are `commands/`, and this is the parser, the table it
dispatches through, and `main`. They are the control layer's work done a second way - the
entry `tests/test_stack.py` carries for this file - and splitting them is what makes that
visible one command at a time. Everything is re-exported here, so `cli.cmd_status` reads as
it did.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from . import compat, compatio, config, edition, machine, notify, settings, shortcut, startup
from .app import EXIT_ERROR, EXIT_OK, App
from .domain import ids
from .logbook import format_local, tail
from .openstate import open_state
from .store import TERMINAL, LegacyStore, StoreError, downgrade_to_v2
from .windows import AdapterError, WakeEvent, resource_users  # noqa: F401
from .commands.base import (CliError, PROG, _app, _now, _open_state, _print,
                            canonical_thread_id)  # noqa: F401
from .commands.records import (_record_view, cmd_cancel, cmd_disable, cmd_enable, cmd_logs,
                               cmd_pending)  # noqa: F401
from .commands.status import (_ENGINE_CHECKS_ONLY, _ENGINE_WORDS, _capability_lines,
                              _engine_words, _view_status, cmd_compat, cmd_doctor,
                              cmd_status)  # noqa: F401
from .commands.watcher import (cmd_activate, cmd_run, cmd_stop)  # noqa: F401
from .commands.install import (cmd_diagnostics, cmd_downgrade_state, cmd_install,
                               cmd_uninstall)  # noqa: F401



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Local-only Codex usage-limit auto-resume for loaded Windows ChatGPT app threads.")
    parser.add_argument("--home", help="root for owned config/ and logs/ (default: project directory or %s)" % config.ENV_HOME)
    parser.add_argument("--codex-exe", help="explicit official codex.exe (default: discovered under %%LOCALAPPDATA%%\\OpenAI\\Codex\\bin)")
    parser.add_argument("--codex-home", help="Codex state directory (default: CODEX_HOME or %%USERPROFILE%%\\.codex)")
    parser.add_argument("--quiet", action="store_true", help="do not mirror log lines to stderr")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("enable", help="enable automatic resume globally, or for one thread")
    p.add_argument("thread_id", nargs="?")
    p.add_argument("--lookback-hours", type=float, help="failures up to this old at enable time stay eligible (default %.0f)" % settings.DEFAULTS["detection_lookback_hours"])

    p = sub.add_parser("disable", help="kill switch: stop all automatic resumes (or one thread)")
    p.add_argument("thread_id", nargs="?")

    sub.add_parser("status", help="show enablement, watcher, autostart, engine and record counts")

    p = sub.add_parser("pending", help="list interruptions waiting for resume")
    p.add_argument("--all", action="store_true", help="include terminal records")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("cancel", help="cancel pending resumes for one thread (also disables that thread)")
    p.add_argument("thread_id")

    p = sub.add_parser("logs", help="print the last log lines")
    p.add_argument("-n", "--lines", type=int, default=50)

    p = sub.add_parser("run", help="run the watcher in the foreground (single instance)")
    p.add_argument("--once", action="store_true", help="execute one tick and exit")
    p.add_argument("--poll", type=int, help="seconds between ticks (runtime override)")

    sub.add_parser("stop", help="ask a running watcher to exit")

    p = sub.add_parser("install", help="create owned directories/state; optionally register login autostart")
    p.add_argument("--startup", action="store_true", help="register per-user autostart (HKCU Run, no admin)")
    # The installer passes it only when it has just replaced one edition with the other.
    p.add_argument("--edition-from", choices=edition.EDITIONS, metavar="EDITION",
                   help="the edition the installer replaced (standard or advanced), so this one "
                        "can set itself up for the change")

    p = sub.add_parser("uninstall", help="remove autostart, stop watcher, delete owned state and logs")
    p.add_argument("--keep-logs", action="store_true")
    p.add_argument("--keep-state", action="store_true",
                   help="keep settings and pending recoveries, so re-installing picks them up")

    sub.add_parser("doctor", help="verify official engine, desktop app pairing and adapters (read-only)")

    p = sub.add_parser("compat", help="what the Codex Compatibility Registry says about this engine")
    p.add_argument("--live", action="store_true",
                   help="check now (runs codex --version and codex queue --help) instead of "
                        "reading the watcher's report; nothing is written")
    p.add_argument("--import", dest="import_file", metavar="FILE",
                   help="validate a registry document and, if it passes, make it the local "
                        "cache (the offline way to do what the Diagnostics refresh does)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("activate", help="handle a codex-auto-resume: URI (used by the notification button)")
    p.add_argument("uri")

    p = sub.add_parser("diagnostics", help="write a redacted diagnostics file to read before sharing")
    p.add_argument("--out", help="file to write (default: a new file in the current directory)")

    p = sub.add_parser("downgrade-state",
                       help="rewrite the state for an older release (stop the watcher first)")
    p.add_argument("--to", type=int, required=True, choices=[2],
                   help="the schema to write: 2 is what v0.5.x reads")
    return parser



COMMANDS = {
    "downgrade-state": cmd_downgrade_state, "diagnostics": cmd_diagnostics,
    "enable": cmd_enable, "disable": cmd_disable, "status": cmd_status, "pending": cmd_pending,
    "cancel": cmd_cancel, "logs": cmd_logs, "run": cmd_run, "stop": cmd_stop,
    "install": cmd_install, "uninstall": cmd_uninstall, "doctor": cmd_doctor,
    "activate": cmd_activate, "compat": cmd_compat,
}


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (CliError, config.ConfigError, StoreError, startup.StartupError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
