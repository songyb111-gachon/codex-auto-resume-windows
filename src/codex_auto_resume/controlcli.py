"""A JSON bridge over the shared control layer.

The standalone Windows window and the MCP server both drive the product through this,
so neither of them re-implements validation, defaults or persistence.

Two ways to call it, one set of commands:

* one command per process - `controlcli <command> [json]` writes exactly one JSON object
  on stdout;
* `controlcli serve` - one long-lived process for a window that stays open. Each request
  is one line, `{"id": n, "command": "...", "argument": {...}}`, and each reply is one
  line, `{"id": n, "reply": {...}}`, where `reply` is exactly what the one-shot form
  would have printed. Starting an interpreter per call cost a noticeable pause on every
  click and made a live view impossible; this costs one start.

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
from pathlib import Path
import sys

from . import config
from .control import Control, ControlError

# Commands with no argument, and commands that take one JSON object.
PLAIN = ("status", "settings", "describe", "defaults", "pending", "pending-all", "start-watcher",
         "stop-watcher", "strings", "history", "clear-history", "dashboard")
WITH_ARGUMENT = ("update", "enabled", "startup", "cancel", "reset-budget", "retry-now",
                 "timeline", "statistics", "thread-enabled", "cancel-thread", "diagnostics")
MAX_LINE = 64 * 1024


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
    """Write one reply object as one line. The one-shot form's only way out."""
    json.dump(payload, sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return 0 if not isinstance(payload, dict) or payload.get("ok", True) else 1


def _payload(raw) -> dict:
    # Only a missing argument means "no argument". A falsy value of the wrong type - 0,
    # false, [] - is still the wrong type, and a non-string reaching `json.loads` raised
    # TypeError, which nothing above this caught.
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ControlError("argument must be a JSON object")
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        # RecursionError is what a deeply nested value raises, and it is not a ValueError.
        raise ControlError("argument must be JSON") from None
    if not isinstance(value, dict):
        raise ControlError("argument must be a JSON object")
    return value


def _days(payload):
    days = payload.get("days")
    if days is not None and (isinstance(days, bool) or not isinstance(days, (int, float))
                             or not 1 <= days <= 3650):
        raise ControlError("days must be a number from 1 to 3650")
    return days


def _labels():
    """Display names for conversations, read-only from Codex's own state.

    Decoration only - the same short name, project and folder a notification shows. A
    source that cannot be opened costs the names, never the listing, and nothing is ever
    addressed by what is shown here.
    """
    try:
        from .source import LocalSource
        return LocalSource(config.codex_home())
    except Exception:
        return None


def dispatch(control: Control, command: str, payload: dict) -> dict:
    """One command, one reply. The whole typed surface of the bridge is this function."""
    try:
        if command == "status":
            return {"ok": True, "status": control.get_status()}
        if command == "settings":
            return {"ok": True, "settings": control.get_settings()}
        if command == "strings":
            # The interface vocabulary for the resolved language, handed over whole. The
            # window does not decide the language and does not carry its own English.
            from . import interface
            return {"ok": True, "language": interface.language(), "strings": interface.catalog()}
        if command == "describe":
            return {"ok": True, "schema": control.describe_settings()}
        if command == "defaults":
            return {"ok": True, "settings": control.restore_defaults()}
        if command == "pending":
            return {"ok": True, "pending": control.list_pending(source=_labels())}
        if command == "pending-all":
            return {"ok": True, "pending": control.list_pending(include_terminal=True)}
        if command == "start-watcher":
            return {"ok": True, "result": control.start_watcher()}
        if command == "stop-watcher":
            # The other half of the upgrade-pending instruction, and the only one a window
            # or a panel can reach. It asks; it never kills, and it reports what the
            # single-instance mutex actually said rather than what was asked for.
            return {"ok": True, "result": control.stop_watcher()}
        if command == "history":
            return {"ok": True, "history": control.history(source=_labels())}
        if command == "clear-history":
            return {"ok": True, "result": control.clear_history(actor="gui")}
        if command == "dashboard":
            # What the Overview needs, in one round trip. Each part fails on its own:
            # a state that cannot be read must not also take the status away.
            reply = {"ok": True, "status": control.get_status()}
            labels = _labels()
            for key, read in (("pending", lambda: control.list_pending(source=labels)),
                              ("history", lambda: control.history(source=labels)),
                              ("week", lambda: control.statistics(7))):
                try:
                    reply[key] = read()
                except ControlError as exc:
                    reply[key + "_error"] = str(exc)
                except Exception:
                    # Any other failure is contained to its own part too, and like the
                    # whole-command case below it never carries exception text, which can
                    # hold a path, into a front end.
                    reply[key + "_error"] = "the request could not be completed"
            return reply
        if command == "update":
            return {"ok": True, "settings": control.update_settings(payload)}
        if command == "enabled":
            return {"ok": True, "result": control.set_enabled(bool(payload.get("enabled")))}
        if command == "startup":
            return {"ok": True, "startup_enabled": control.set_startup_enabled(bool(payload.get("enabled")))}
        if command == "cancel":
            return {"ok": True, "result": control.cancel_interruption(payload.get("interruption_id"))}
        if command == "reset-budget":
            return {"ok": True, "result": control.reset_recovery_budget(payload.get("interruption_id"))}
        if command == "retry-now":
            return {"ok": True, "result": control.request_retry_now(payload.get("interruption_id"))}
        if command == "timeline":
            return {"ok": True, "result": control.timeline(payload.get("interruption_id"))}
        if command == "statistics":
            return {"ok": True, "result": control.statistics(_days(payload))}
        if command == "thread-enabled":
            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                raise ControlError("enabled must be true or false")
            return {"ok": True, "result": control.set_thread_enabled(payload.get("thread_id"), enabled)}
        if command == "cancel-thread":
            return {"ok": True, "result": control.cancel_thread(payload.get("thread_id"))}
        if command == "diagnostics":
            from . import diagnostics
            target = payload.get("path")
            if not isinstance(target, str) or not target.lower().endswith(".json"):
                raise ControlError("choose a .json file to write")
            try:
                written = diagnostics.write(control, Path(target))
            except FileExistsError:
                raise ControlError("that file already exists; choose a new name") from None
            return {"ok": True, "result": {"path": str(written)}}
    except ControlError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        # Never leak a traceback or a path into a front end; the log has the detail.
        return {"ok": False, "error": "the request could not be completed"}
    return {"ok": False, "error": "unknown command"}


def serve(control: Control, stream_in, stream_out) -> int:
    """Answer requests, one line each, until the input closes.

    A request that cannot be parsed still gets exactly one reply line, so the caller can
    never be left waiting for an answer that will not come.
    """
    for line in stream_in:
        line = line.lstrip("﻿").strip()
        if not line:
            continue
        request_id = None
        try:
            if len(line) > MAX_LINE:
                raise ControlError("request too large")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ControlError("request must be a JSON object")
            request_id = request.get("id")
            if not (request_id is None or (isinstance(request_id, int) and not isinstance(request_id, bool))):
                raise ControlError("id must be an integer")
            command = request.get("command")
            if command not in PLAIN + WITH_ARGUMENT:
                raise ControlError("unknown command")
            reply = dispatch(control, command, _payload(request.get("argument")))
        except ControlError as exc:
            reply = {"ok": False, "error": str(exc)}
        except (ValueError, RecursionError):
            # A deeply nested line raises RecursionError rather than ValueError; it is
            # the same malformed request and gets the same answer.
            reply = {"ok": False, "error": "request must be JSON"}
        except Exception:
            # One bad line must never end the loop: the window would be left with a dead
            # pipe and a request that is never answered. No detail, for the same reason
            # `dispatch` gives none.
            reply = {"ok": False, "error": "the request could not be completed"}
        json.dump({"id": request_id, "reply": reply}, stream_out, ensure_ascii=False, default=str)
        stream_out.write("\n")
        stream_out.flush()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-auto-resume-control", add_help=True)
    parser.add_argument("--home", help="runtime home (default: the installed location)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in PLAIN + ("serve",):
        sub.add_parser(name)
    for name in WITH_ARGUMENT:
        p = sub.add_parser(name)
        p.add_argument("json", nargs="?", default="", help="JSON object argument")
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
    if args.command == "serve":
        return serve(control, sys.stdin, sys.stdout)
    try:
        payload = _payload(getattr(args, "json", ""))
    except ControlError as exc:
        reply = {"ok": False, "error": str(exc)}
    else:
        reply = dispatch(control, args.command, payload)
    return _emit(reply)


if __name__ == "__main__":
    sys.exit(main())
