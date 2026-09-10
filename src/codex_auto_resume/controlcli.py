"""A JSON bridge over the shared control layer.

The standalone Windows settings window and the MCP server both drive the product
through this, so neither of them re-implements validation, defaults or persistence.
Every command reads JSON on stdin (where it takes an argument) and writes exactly one
JSON object on stdout.

The surface is deliberately narrow and typed. There is no command that runs a program,
reads an arbitrary file, writes the registry directly or executes SQL, and every
identifier is validated before it reaches the store.

The wire is UTF-8, stated rather than inherited. Both callers redirect these streams, and
a redirected stdout on Windows takes the machine's ANSI code page - so on a Korean install
this wrote CP949 while the settings window decoded UTF-8, and every Korean label arrived
as mojibake. It looked like a font problem and was an encoding one. The MCP server has
always said UTF-8 out loud, which is why the Codex panel was correct throughout and the
window was not.

A developer machine can hide this: `PYTHONIOENCODING=utf-8` in the environment makes the
old code work, so the bug reproduces for users and not for whoever is looking for it.
Nothing here may depend on the active code page, the console, the locale or an inherited
variable.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config
from .control import Control, ControlError


def _use_utf8() -> None:
    """State the protocol's encoding, whatever the machine's code page is.

    `reconfigure` wins over `PYTHONIOENCODING` because it happens at runtime, which is
    the point: the contract belongs to the protocol, not to the environment that started
    it. Guarded because a replaced stream - a test's StringIO, a pytest capture - has no
    `reconfigure`, and the protocol is a string protocol at that level anyway.
    """
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", newline=chr(10))
        except (AttributeError, ValueError, OSError):
            pass


def _emit(payload) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return 0


def _fail(message) -> int:
    json.dump({"ok": False, "error": str(message)}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 1


def _payload(raw) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        raise ControlError("argument must be JSON") from None
    if not isinstance(value, dict):
        raise ControlError("argument must be a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-auto-resume-control", add_help=True)
    parser.add_argument("--home", help="runtime home (default: the installed location)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "settings", "describe", "defaults", "pending", "start-watcher",
                 "strings"):
        sub.add_parser(name)
    for name in ("update", "enabled", "startup", "cancel", "reset-budget", "retry-now"):
        p = sub.add_parser(name)
        p.add_argument("json", nargs="?", default="", help="JSON object argument")
    p = sub.add_parser("pending-all")
    return parser


def main(argv=None) -> int:
    _use_utf8()
    args = build_parser().parse_args(argv)
    home = args.home
    if not home:
        # The installed layout keeps state one level above the application directory.
        root = config.PROJECT_ROOT
        home = str(root.parent) if root.name == "app" else None
    control = Control(home)
    try:
        if args.command == "status":
            return _emit({"ok": True, "status": control.get_status()})
        if args.command == "settings":
            return _emit({"ok": True, "settings": control.get_settings()})
        if args.command == "strings":
            # The interface vocabulary for the resolved language, handed over whole. The
            # window does not decide the language and does not carry its own English.
            from . import interface
            return _emit({"ok": True, "language": interface.language(),
                          "strings": interface.catalog()})
        if args.command == "describe":
            return _emit({"ok": True, "schema": control.describe_settings()})
        if args.command == "defaults":
            return _emit({"ok": True, "settings": control.restore_defaults()})
        if args.command == "pending":
            return _emit({"ok": True, "pending": control.list_pending()})
        if args.command == "pending-all":
            return _emit({"ok": True, "pending": control.list_pending(include_terminal=True)})
        if args.command == "start-watcher":
            return _emit({"ok": True, "result": control.start_watcher()})

        payload = _payload(args.json)
        if args.command == "update":
            return _emit({"ok": True, "settings": control.update_settings(payload)})
        if args.command == "enabled":
            return _emit({"ok": True, "result": control.set_enabled(bool(payload.get("enabled")))})
        if args.command == "startup":
            return _emit({"ok": True, "startup_enabled": control.set_startup_enabled(bool(payload.get("enabled")))})
        if args.command == "cancel":
            return _emit({"ok": True, "result": control.cancel_interruption(payload.get("interruption_id"))})
        if args.command == "reset-budget":
            return _emit({"ok": True, "result": control.reset_recovery_budget(payload.get("interruption_id"))})
        if args.command == "retry-now":
            return _emit({"ok": True, "result": control.request_retry_now(payload.get("interruption_id"))})
    except ControlError as exc:
        return _fail(exc)
    except Exception:
        # Never leak a traceback or a path into a front end; the log has the detail.
        return _fail("the request could not be completed")
    return _fail("unknown command")


if __name__ == "__main__":
    sys.exit(main())
