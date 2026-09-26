"""A JSON bridge over the shared control layer.

The standalone Windows window and the MCP server both drive the product through this,
so neither of them re-implements validation, defaults or persistence.

Two ways to call it, one set of commands:

* one command per process - `controlcli <command> [json]` writes exactly one JSON object
  on stdout. The argument may be `-` instead, which reads it from stdin; that is how the
  window's one-shot bridge sends it, so a Custom message never sits on a command line;
* `controlcli serve` - one long-lived process for a window that stays open. Each request
  is one line, `{"id": n, "command": "...", "argument": {...}}`, and each reply is one
  line, `{"id": n, "reply": {...}}`, where `reply` is exactly what the one-shot form
  would have printed. Starting an interpreter per call cost a noticeable pause on every
  click and made a live view impossible; this costs one start.

The surface is deliberately narrow and typed. There is no command that runs an arbitrary
program, writes the registry directly or executes SQL, and every identifier is validated
before it reaches the store. The programs it can start are fixed: the watcher, and - for the
Diagnostics page's compatibility refresh, only when a person presses it - this installation's
own `scripts/bootstrap.ps1 -Compatibility`. The one file it reads by name is a Compatibility
Registry document handed to `compat-import`, which is size-capped, parsed by the hardened
validator and never echoed: the answer is a code.

A command the bridge has none of its own for is put to the edition's plug (P10), in the long-lived
form only: the one-shot form's parser knows the bridge's own commands and nothing else. The
standard edition's plug answers none, so such a command is refused as it always was.

A rejected request always answers `{"ok": false, "error": "...", "error_code": "..."}`:
the English sentence, which the command line prints and a bug report quotes, and beside it
the stable code from `control.ERROR_CODES` that a front end turns into its own language.
Both, because neither is enough on its own - the window takes every other word it shows
from `interface.py` in the machine's language, and used to put this one reason on screen in
English underneath a Korean sentence. Nothing else is ever added to a rejection: no
traceback, no path, no identifier.

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

from . import config, l10n
# Read at the top since v0.6.10-alpha: `windows` is the front of the Codex adapter now, and
# the adapter and this reader are one package, so this module was loaded here either way. It
# was deferred when the two were apart and it was a cost.
from .codex import LocalSource
from .control import FALLBACK_CODE, Control, ControlError
from .domain.plug import DEFER, Surface
from .windows import WakeEvent

# Commands with no argument, and commands that take one JSON object.
PLAIN = ("status", "settings", "describe", "defaults", "pending", "pending-all", "start-watcher",
         "stop-watcher", "strings", "history", "clear-history", "dashboard", "cancel-all",
         # v0.6.8: the Dashboard in front has seen any failure (control.acknowledge_failure).
         "failure-seen")
WITH_ARGUMENT = ("update", "enabled", "startup", "cancel", "reset-budget", "retry-now",
                 "timeline", "statistics", "thread-enabled", "cancel-thread", "diagnostics",
                 "preview-continuation", "interruption-recovery",
                 # The Compatibility Registry: read the report (or check live), import a
                 # document the bootstrap downloaded, and the Diagnostics refresh.
                 "compatibility", "compat-import", "compat-refresh")
# Big enough for the largest Save the settings layer accepts: eight Custom messages of 2000
# characters each, and the window writes every line break as a six-character escape, so a
# valid Save can come to nearly 100 KiB. At 64 KiB such a Save was refused as "request too
# large" although every message in it was one the settings layer would have stored.
MAX_LINE = 1024 * 1024
# The one-shot form's argument that means "the JSON argument is on stdin". It is not JSON
# itself, so it can never be an argument somebody meant literally.
STDIN_ARGUMENT = "-"
# What a rejection says when nothing more precise is known. Both the sentence and the code
# are the generic ones: the log holds the detail, and a front end that shows this has still
# shown it in the user's own language.
GENERIC_ERROR = "the request could not be completed"


def use_utf8(stream, newline=chr(10)) -> None:
    """Say UTF-8 on one of this process's streams: the one place a front end's wire states
    its encoding, for the bridge and the MCP server alike.

    `reconfigure` wins over `PYTHONIOENCODING` because it happens at runtime, which is the
    point: the contract belongs to the protocol, not to the environment that started it.
    `newline=None` leaves the stream's own line handling as it is. What `reconfigure` raises
    is raised; each caller decides what it tolerates.
    """
    stream.reconfigure(encoding="utf-8", **({} if newline is None else {"newline": newline}))


def _use_utf8() -> None:
    """State the protocol's encoding on both streams, whatever the machine's code page is.

    Guarded stream by stream, because a replaced stream - a test's StringIO, a pytest
    capture - has no `reconfigure`, and the protocol is a string protocol at that level
    anyway.
    """
    for stream in (sys.stdout, sys.stdin):
        try:
            use_utf8(stream)
        except (AttributeError, ValueError, OSError):
            pass


def _rejected(message: str, code: str = FALLBACK_CODE) -> dict:
    """The only shape a refusal leaves here in: the English sentence and its code.

    The sentence is what the command line prints and what a bug report quotes; the code is
    the same refusal as a stable value, so the window and the panel can say it in the
    language they say everything else in rather than showing a Korean lead sentence over an
    English explanation. Nothing else goes in - no traceback, no path, no identifier -
    which is why every rejection is built here instead of at each `return`.
    """
    return {"ok": False, "error": message, "error_code": code}


# What `json.dumps` raises for something it cannot write as strict JSON: a value that is not
# JSON, a NaN or an infinity, a structure that refers to itself or nests too deep.
UNWRITABLE = (TypeError, ValueError, RecursionError)


def encode(*candidates) -> str:
    """The first of `candidates` that can be written as strict JSON, as one line.

    Strict: no NaN and no infinity, which the settings window's parser and serde_json both
    refuse, and nothing that is not JSON - there is no `default`, so such a value raises
    rather than reaching a front end as its str(). The bridge and the MCP server write every
    line through this and pass their own structured refusal as the last candidate, so a
    reply that cannot be written is still answered and the loop lives. The last candidate is
    written unguarded: it is the caller's plain refusal, and if even that fails it should.
    """
    for candidate in candidates[:-1]:
        try:
            return json.dumps(candidate, ensure_ascii=False, allow_nan=False)
        except UNWRITABLE:
            continue
    return json.dumps(candidates[-1], ensure_ascii=False, allow_nan=False)


def _emit(payload) -> int:
    """Write one reply object as one line. The one-shot form's only way out."""
    try:
        line = encode(payload)
    except UNWRITABLE:
        payload = _rejected(GENERIC_ERROR)
        line = encode(payload)
    sys.stdout.write(line + "\n")
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


def _argument(raw, stream):
    """The one-shot form's JSON argument: as given, or read from `stream` when given as `-`.

    The window's one-shot bridge sends every argument this way. It answers whenever the
    long-lived process has failed, and what it carries then includes every Custom message on
    the page. A command line can be read by any process the same user runs, and process
    auditing (event 4688 with command lines, Sysmon, an EDR) keeps it; a command line also
    stops at 32767 characters, which a Save of long messages could pass. The argument on the
    command line still works, for everyone else who calls this.
    """
    if raw != STDIN_ARGUMENT:
        return raw
    if stream is None:
        return ""
    try:
        return stream.read()
    except (OSError, ValueError):
        # ValueError is also what bytes that are not UTF-8 raise, and the wire is UTF-8.
        raise ControlError("argument must be JSON") from None


# How many days a statistics request may cover. The MCP tool publishes the same two numbers.
DAYS = (1, 3650)


def statistics_days(payload):
    """A statistics request's `days`: absent, or a number from 1 to 3650. The one check of it,
    for the bridge and the MCP server alike."""
    days = payload.get("days")
    if days is not None and (isinstance(days, bool) or not isinstance(days, (int, float))
                             or not DAYS[0] <= days <= DAYS[1]):
        raise ControlError("days must be a number from %d to %d" % DAYS)
    return days


def _flag(payload):
    """The `enabled` field of a switch request: a real boolean, or a refusal.

    This was `bool(payload.get("enabled"))`, and `bool` says yes to every non-empty
    string. `{"enabled": "false"}` therefore turned automatic recovery *on*, and the same
    line governed `startup`, where on means writing this product's entry into the Run key
    - so a request that meant "off" registered a watcher at sign-in instead. A missing
    field was the same accident the other way round: `bool(None)` is False, and a request
    that said nothing switched recovery off.

    The wire is JSON and JSON has `true` and `false`, which is exactly what both windows
    send. Nothing here has to guess what a string meant, so anything that is not a boolean
    is refused by name, with the code the front ends already have words for
    (`error.invalid_enabled`, in all nine catalogs) - the same sentence and the same code
    the control layer raises when it is called directly.
    """
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ControlError("enabled must be true or false", code="invalid_enabled")
    return enabled


def _labels():
    """Display names for conversations, read-only from Codex's own state.

    Decoration only - the same short name, project and folder a notification shows. A
    source that cannot be opened costs the names, never the listing, and nothing is ever
    addressed by what is shown here.
    """
    try:
        return LocalSource(config.codex_home())
    except Exception:
        return None


def _boolean(payload, name):
    """An optional flag: absent is False, a real boolean is itself, anything else refused."""
    value = payload.get(name, False)
    if not isinstance(value, bool):
        raise ControlError("%s must be true or false" % name)
    return value


def _compatibility(control: Control, payload: dict) -> dict:
    """The Compatibility Registry as the window shows it.

    Without `live` this is the watcher's report, validated and checked against the engine
    on disk - UNKNOWN for everything when it cannot be used, with the reason. With `live`
    it is a fresh check made here and returned, never written: the report has one writer,
    and it is the watcher. A live check runs `codex --version` and `codex queue --help` and
    reads Codex's schema, so the window asks for it only when a person does.
    """
    from . import compatio
    settings = control.get_settings()
    if _boolean(payload, "live"):
        explicit = settings.get("codex_exe") or None
        return compatio.live_view(control.paths, config.codex_home(), explicit=explicit)
    return compatio.reader_view(control.paths, settings=settings)


def _compat_import(control: Control, payload: dict) -> dict:
    """Validate one registry document and, only if it passes, make it the cache.

    The bootstrap's download lands in a temporary file and comes here; this is the only
    writer of `compat-cache.json`. A refusal is an answer, not an error: the command ran,
    and what it found is one code from a closed set.
    """
    from . import compatio
    target = payload.get("path")
    origin = payload.get("origin", "file")
    if not isinstance(target, str) or not target:
        raise ControlError("choose a .json file to import")
    if origin not in ("main", "file"):
        raise ControlError("origin must be main or file")
    result = compatio.import_document(control.paths, target, origin=origin)
    # Ask a running watcher to look now, so the report follows the new data within a tick
    # rather than a poll. A lost wake only delays; the watcher also sees the file change.
    woke = False
    if result.get("imported"):
        try:
            woke = bool(WakeEvent(str(control.paths.state_dir)).signal())
        except Exception:
            woke = False
    return dict(result, woke_watcher=woke)


def _compat_refresh(control: Control) -> dict:
    """The Diagnostics page's refresh: this installation's own bootstrap, asked to fetch the
    registry data from its one constant address and import it through `compat-import`.

    Only ever started by a person pressing the button. It can take a minute on a slow
    connection, so a window calls it on the one-shot bridge from a worker thread, never on
    the long-lived pipe it paints from. The reply carries the fresh view as well, checked
    live, because a watcher that is not running cannot have recomputed the report yet.
    """
    from . import compatio
    outcome = compatio.run_refresh(control.paths.home)
    try:
        view = _compatibility(control, {"live": True})
    except Exception:
        view = compatio.reader_view(control.paths)
    return dict(outcome, compatibility=view)


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
            # The Interface language is read again on every request, so a window opened after
            # it changes speaks the new one. A window that is already open asked once, when it
            # was built, and keeps that language until it is opened again; its Settings page
            # says so when a new language is saved.
            from . import interface
            l10n.set_preference(control.get_settings().get("interface_language"))
            return {"ok": True, "language": interface.language(), "strings": interface.catalog(),
                    "preference": l10n.preference(), "system_language": l10n.from_system(),
                    "endonyms": dict(l10n.ENDONYMS)}
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
        if command == "failure-seen":
            return {"ok": True, "result": control.acknowledge_failure()}
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
                    reply[key + "_error"] = GENERIC_ERROR
            return reply
        if command == "update":
            return {"ok": True, "settings": control.update_settings(payload)}
        if command == "enabled":
            return {"ok": True, "result": control.set_enabled(_flag(payload))}
        if command == "startup":
            return {"ok": True, "startup_enabled": control.set_startup_enabled(_flag(payload))}
        if command == "cancel":
            return {"ok": True, "result": control.cancel_interruption(payload.get("interruption_id"))}
        if command == "reset-budget":
            return {"ok": True, "result": control.reset_recovery_budget(payload.get("interruption_id"))}
        if command == "retry-now":
            return {"ok": True, "result": control.request_retry_now(payload.get("interruption_id"))}
        if command == "timeline":
            return {"ok": True, "result": control.timeline(payload.get("interruption_id"))}
        if command == "statistics":
            return {"ok": True, "result": control.statistics(statistics_days(payload))}
        if command == "thread-enabled":
            return {"ok": True, "result": control.set_thread_enabled(payload.get("thread_id"),
                                                                     _flag(payload))}
        if command == "cancel-thread":
            return {"ok": True, "result": control.cancel_thread(payload.get("thread_id"))}
        if command == "preview-continuation":
            changes = payload.get("changes")
            return {"ok": True, "result": control.preview_continuation(payload.get("category"),
                                                                       changes)}
        if command == "interruption-recovery":
            return {"ok": True, "result": control.set_interruption_recovery(
                payload.get("interruption_id"), payload.get("thread_id"), _flag(payload))}
        if command == "cancel-all":
            return {"ok": True, "result": control.cancel_all_pending(actor="gui")}
        if command == "compatibility":
            return {"ok": True, "compatibility": _compatibility(control, payload)}
        if command == "compat-import":
            return {"ok": True, "result": _compat_import(control, payload)}
        if command == "compat-refresh":
            return {"ok": True, "result": _compat_refresh(control)}
        if command == "diagnostics":
            from . import diagnostics
            target = payload.get("path")
            if not isinstance(target, str) or not target.lower().endswith(".json"):
                raise ControlError("choose a .json file to write")
            try:
                written = diagnostics.write(control, Path(target))
            except FileExistsError:
                raise ControlError("that file already exists; choose a new name",
                                   code="file_exists") from None
            return {"ok": True, "result": {"path": str(written)}}
    except ControlError as exc:
        return _rejected(str(exc), exc.code)
    except Exception:
        # Never leak a traceback or a path into a front end; the log has the detail. The
        # code is the generic one, because nothing here knows what went wrong.
        return _rejected(GENERIC_ERROR)
    return _rejected("unknown command")


def _plugged(control: Control, command, argument) -> dict:
    """A command the bridge has none of its own for, put to the edition's plug (P10).

    Refused, as every unknown command always was, unless the plug answers it with a JSON object,
    which is then the reply's `result`. The standard edition's plug is not even asked. What such
    a command does is the plug's own affair and stays in its own state: nothing here sends,
    claims or starts anything for it."""
    if not control.plug.null and isinstance(command, str):
        try:
            payload = _payload(argument)
        except Exception:
            payload = None
        if payload is not None:
            added = control.plug.surface(Surface.BRIDGE, {"command": command, "argument": payload})
            if added is not DEFER:
                return {"ok": True, "result": added}
    raise ControlError("unknown command")


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
                reply = _plugged(control, command, request.get("argument"))
            else:
                reply = dispatch(control, command, _payload(request.get("argument")))
        except ControlError as exc:
            reply = _rejected(str(exc), exc.code)
        except (ValueError, RecursionError):
            # A deeply nested line raises RecursionError rather than ValueError; it is
            # the same malformed request and gets the same answer.
            reply = _rejected("request must be JSON")
        except Exception:
            # One bad line must never end the loop: the window would be left with a dead
            # pipe and a request that is never answered. No detail, for the same reason
            # `dispatch` gives none.
            reply = _rejected(GENERIC_ERROR)
        # A reply that cannot be written is answered with the generic refusal, and an id that
        # cannot be echoed - JSON has no NaN or infinity - is answered as null.
        refusal = _rejected(GENERIC_ERROR)
        stream_out.write(encode({"id": request_id, "reply": reply}, {"id": request_id, "reply": refusal},
                                {"id": None, "reply": reply}, {"id": None, "reply": refusal}) + "\n")
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
        p.add_argument("json", nargs="?", default="",
                       help='JSON object argument, or "-" to read it from stdin')
        if name == "compat-import":
            # How the bootstrap calls it: a path as its own argument, which survives Windows
            # PowerShell 5.1's native-argument quoting and a non-ASCII profile directory,
            # where a JSON string on a command line or piped text does not.
            p.add_argument("--file", help="the registry document to validate and import")
            p.add_argument("--origin", choices=("main", "file"), default=None)
    return parser


def main(argv=None) -> int:
    _use_utf8()
    args = build_parser().parse_args(argv)
    control = Control(args.home or config.installed_home())
    if args.command == "serve":
        return serve(control, sys.stdin, sys.stdout)
    try:
        payload = _payload(_argument(getattr(args, "json", ""), sys.stdin))
        if args.command == "compat-import" and getattr(args, "file", None):
            payload = dict(payload, path=args.file)
            if args.origin:
                payload["origin"] = args.origin
    except ControlError as exc:
        reply = _rejected(str(exc), exc.code)
    else:
        reply = dispatch(control, args.command, payload)
    return _emit(reply)


if __name__ == "__main__":
    sys.exit(main())
