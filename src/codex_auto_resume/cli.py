"""Command-line interface: enable / disable / status / pending / cancel / logs / run / stop / install / uninstall."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from . import config, notify, settings, shortcut, startup
from .app import EXIT_BUSY, EXIT_ERROR, EXIT_OK, App
from .logbook import format_local, tail
from .store import TERMINAL, StoreError
from .windows import AdapterError

PROG = "auto_resume"


class CliError(RuntimeError):
    pass


def canonical_thread_id(value: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise CliError("thread id must be a canonical UUID (never --last or a name)") from None
    if str(parsed) != value:
        raise CliError("thread id must be lowercase canonical UUID text")
    return value


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

    p = sub.add_parser("uninstall", help="remove autostart, stop watcher, delete owned state and logs")
    p.add_argument("--keep-logs", action="store_true")

    sub.add_parser("doctor", help="verify official engine, desktop app pairing and adapters (read-only)")

    p = sub.add_parser("activate", help="handle a codex-auto-resume: URI (used by the notification button)")
    p.add_argument("uri")
    return parser


def _now() -> float:
    return time.time()


def _print(text: str = "") -> None:
    print(text)


def _app(args) -> App:
    paths = config.Paths(args.home)
    return App(paths, codex_exe=args.codex_exe, codex_home=args.codex_home, console=not args.quiet)


def cmd_enable(args) -> int:
    app = _app(args)
    if args.lookback_hours is not None:
        # An update, not a save: naming one field must never rewrite the other fifteen.
        app.settings = config.update_settings(app.paths, {"detection_lookback_hours": args.lookback_hours})
    with app.open_store() as store:
        if args.thread_id:
            thread_id = canonical_thread_id(args.thread_id)
            store.set_thread_enabled(thread_id, True)
            app.logger.info("thread %s: enabled by user", thread_id)
            _print("thread %s enabled" % thread_id)
        else:
            store.set_enabled(True, _now())
            app.logger.info("auto-resume enabled by user (lookback %.1fh)", app.settings["detection_lookback_hours"])
            _print("auto-resume enabled (lookback %.1f h). Start the watcher with: run" % app.settings["detection_lookback_hours"])
            if app.watcher_running() is False:
                _print("note: no watcher is running; nothing will be resumed until `run` is started")
    return EXIT_OK


def cmd_disable(args) -> int:
    app = _app(args)
    with app.open_store() as store:
        if args.thread_id:
            thread_id = canonical_thread_id(args.thread_id)
            store.set_thread_enabled(thread_id, False)
            app.logger.info("thread %s: disabled by user", thread_id)
            _print("thread %s disabled (pending records kept, never submitted while disabled)" % thread_id)
        else:
            store.set_enabled(False, _now())
            app.logger.info("auto-resume DISABLED by user (kill switch)")
            _print("auto-resume disabled: no continuation will be queued until `enable`")
    return EXIT_OK


def _record_view(row: dict) -> dict:
    return {
        "thread_id": row["thread_id"],
        "interruption_id": row["interruption_id"],
        "state": row["state"],
        "detected_at": format_local(row["detected_at"]),
        "reset_at": format_local(row["reset_at"]) if row["reset_at"] else None,
        "limit_type": row["limit_type"],
        "uncertain": row["uncertain"],
        "next_retry_at": format_local(row["next_retry_at"]) if row["next_retry_at"] else None,
        "retry_count": row["retry_count"],
        "attempt_count": row["attempt_count"],
        "resumed_at": format_local(row["resumed_at"]) if row["resumed_at"] else None,
        "last_error": row["last_error"],
        "queue_id": row["queue_id"],
        "cancel_requested": row["cancel_requested"],
    }


def cmd_pending(args) -> int:
    app = _app(args)
    with app.open_store() as store:
        rows = store.all_records() if args.all else store.pending()
        enabled = {row["thread_id"]: store.thread_enabled(row["thread_id"]) for row in rows}
    views = [dict(_record_view(row), thread_enabled=enabled[row["thread_id"]]) for row in rows]
    if args.json:
        _print(json.dumps(views, indent=2, ensure_ascii=False))
        return EXIT_OK
    if not views:
        _print("no pending interruptions")
        return EXIT_OK
    for view in views:
        _print("thread %s" % view["thread_id"])
        _print("  state        : %s%s" % (view["state"], "" if view["thread_enabled"] else "  (thread disabled)"))
        _print("  detected     : %s" % view["detected_at"])
        _print("  reset        : %s  [%s%s]" % (view["reset_at"] or "unknown", view["limit_type"] or "unknown", ", uncertain" if view["uncertain"] else ""))
        _print("  next check   : %s" % (view["next_retry_at"] or "-"))
        _print("  retries      : %d launch retries, %d reservations" % (view["retry_count"], view["attempt_count"]))
        if view["resumed_at"]:
            _print("  resumed      : %s" % view["resumed_at"])
        if view["last_error"]:
            _print("  last reason  : %s" % view["last_error"])
        _print("  interruption : %s" % view["interruption_id"][:16])
    return EXIT_OK


def cmd_cancel(args) -> int:
    app = _app(args)
    thread_id = canonical_thread_id(args.thread_id)
    with app.open_store() as store:
        store.cancel(thread_id, _now())
        rows = [row for row in store.all_records() if row["thread_id"] == thread_id]
    app.logger.info("thread %s: cancel requested by user", thread_id)
    in_flight = [row for row in rows if row["state"] not in TERMINAL]
    _print("thread %s cancelled and disabled" % thread_id)
    if in_flight:
        _print("note: %d submission(s) already in flight will be reconciled and not resent" % len(in_flight))
    return EXIT_OK


def cmd_logs(args) -> int:
    paths = config.Paths(args.home)
    for line in tail(paths.log_file, args.lines):
        _print(line)
    return EXIT_OK


def cmd_status(args) -> int:
    app = _app(args)
    with app.open_store() as store:
        settings = store.settings()
        counts = store.status_counts()
        pending = store.pending()
    running = app.watcher_running()
    _print("auto-resume      : %s" % ("ENABLED" if settings["enabled"] else "disabled"))
    if settings["enabled"]:
        _print("enabled since    : %s" % format_local(settings["armed_at"]))
    _print("watcher          : %s" % {True: "running", False: "not running", None: "unknown"}[running])
    try:
        value = startup.current_value()
        _print("login autostart  : %s" % ("registered" if value else "not registered"))
    except startup.StartupError:
        _print("login autostart  : unavailable")
    try:
        backend = app.backend()
        _print("codex engine     : %s" % backend.codex_exe)
        _print("engine version   : %s%s" % (backend.engine_version,
               "" if backend.engine_verified else "  (unverified build; interface probe passed)"))
        identity = backend.app_identity()
        _print("ChatGPT app      : %s" % ("running (pid %d, codex server pid %d)" % (identity["pid"], identity["server"]["pid"]) if identity else "not running / not paired"))
    except (config.ConfigError, AdapterError) as exc:
        _print("codex engine     : unavailable (%s)" % exc)
    _print("pending          : %d" % len(pending))
    for state in sorted(counts):
        _print("  %-22s %d" % (state, counts[state]))
    _print("lookback         : %.1f h" % app.settings["detection_lookback_hours"])
    _print("state file       : %s" % (app.paths.state_dir / "state.sqlite"))
    _print("log file         : %s" % app.paths.log_file)
    return EXIT_OK


def cmd_doctor(args) -> int:
    app = _app(args)
    ok = True
    try:
        backend = app.backend()
        _print("codex.exe        : %s" % backend.codex_exe)
        _print("engine version   : %s" % (
            "%s (verified)" % backend.engine_version if backend.engine_verified
            else "%s (NOT a verified version; accepted because `codex queue` still "
                 "offers --thread/--message)" % backend.engine_version))
    except (config.ConfigError, AdapterError) as exc:
        _print("codex.exe        : FAIL (%s)" % exc)
        return EXIT_ERROR
    _print("codex home       : %s" % app.codex_home)
    identity = backend.app_identity()
    if identity:
        _print("ChatGPT app      : main pid %d, codex app-server pid %d" % (identity["pid"], identity["server"]["pid"]))
    else:
        ok = False
        _print("ChatGPT app      : not running or not paired with the configured engine")
    running = app.watcher_running()
    _print("watcher mutex    : %s" % {True: "held by a running watcher", False: "free", None: "unavailable"}[running])
    try:
        from .windows import resource_users
        lock_dir = app.codex_home / "thread-writer-locks"
        probe = lock_dir / ".coordination.lock"
        if probe.exists():
            resource_users(probe)
            _print("restart manager  : ok")
        else:
            _print("restart manager  : skipped (no coordination lock file)")
    except AdapterError as exc:
        ok = False
        _print("restart manager  : FAIL (%s)" % exc)
    try:
        app.source().latest_failures(_now() - 60)
        _print("local history    : readable")
    except Exception as exc:
        ok = False
        _print("local history    : FAIL (%s)" % type(exc).__name__)
    return EXIT_OK if ok else EXIT_ERROR


def cmd_run(args) -> int:
    app = _app(args)
    return app.run(once=args.once, poll=args.poll)


def cmd_stop(args) -> int:
    app = _app(args)
    if app.stop_event().signal():
        for _ in range(40):
            if app.watcher_running() is False:
                break
            time.sleep(0.25)
        _print("stop requested" + ("; watcher exited" if app.watcher_running() is False else "; watcher still finishing"))
        return EXIT_OK
    _print("no running watcher found")
    return EXIT_OK


def cmd_activate(args) -> int:
    """Handle the notification button. Reached from Windows, never from a terminal.

    The only action a URI can request is *cancelling* a resume, so a hostile URI can at
    worst stop something from happening. The interruption id is validated as opaque hex
    and must match a real record; nothing is looked up by thread, name or recency.
    """
    app = _app(args)
    interruption_id = notify.parse_cancel_uri(args.uri)
    if interruption_id is None:
        app.logger.info("activation ignored: malformed or unsupported URI")
        return EXIT_ERROR
    with app.open_store() as store:
        record = store.get(interruption_id)
        if record is None:
            app.logger.info("activation ignored: no record for that interruption")
            return EXIT_ERROR
        thread_id = record["thread_id"]
        store.cancel(thread_id, _now())
    app.logger.info("thread %s: cancelled from the notification", thread_id)
    notify.cancelled(thread_id)
    _print("thread %s cancelled" % thread_id)
    return EXIT_OK


def cmd_install(args) -> int:
    app = _app(args)
    with app.open_store() as store:
        enabled = store.settings()["enabled"]
    _print("owned state directory : %s" % app.paths.state_dir)
    _print("owned log directory   : %s" % app.paths.logs_dir)
    if args.startup:
        # Always register the home actually in effect. Passing it only when it came from
        # --home would let CODEX_AUTO_RESUME_HOME silently drop out at login, pointing the
        # autostarted watcher at a different state DB *and* a different single-instance mutex.
        command = startup.command_line(app.paths.entry_script, app.paths.home)
        changed = startup.install(command)
        app.logger.info("login autostart %s", "registered" if changed else "already registered")
        _print("login autostart       : %s" % ("registered" if changed else "already registered (unchanged)"))
        _print("  %s" % command)
    else:
        _print("login autostart       : not requested (use install --startup to opt in)")
    if app.settings.get("notifications", True):
        try:
            icon = app.paths.icon_file if app.paths.icon_file.is_file() else None
            startup.register_aumid(icon)
            # Windows will not DISPLAY a toast from an unpackaged application until a
            # Start Menu shortcut carries the same AppUserModelID - without it the
            # platform accepts and logs the toast and then draws nothing. Measured, not
            # assumed. The same entry is how a user opens settings from Windows.
            # Prefer the settings window: the Start Menu entry should open something a
            # person can use, not a headless command. It also carries the AUMID that
            # makes Windows display our notifications at all.
            window = app.paths.home / "CodexAutoResumeSettings.exe"
            if window.is_file():
                shortcut.install(target=window, icon=icon,
                                 description="Codex Auto Resume Settings")
            else:
                launcher = app.paths.home / "watcher-launcher.py"
                target = launcher if launcher.is_file() else app.paths.entry_script
                arguments = " ".join(startup.quote_argument(argument) for argument in
                                     (str(target), "--home", str(app.paths.home), "status"))
                shortcut.install(target=startup.python_launcher(), arguments=arguments,
                                 icon=icon, description="Codex Auto Resume")
            _print("notification sender   : %s" % startup.AUMID_DISPLAY_NAME)
            _print("start menu entry      : %s" % shortcut.shortcut_path().name)
        except (startup.StartupError, shortcut.ShortcutError) as exc:
            _print("notification sender   : unavailable (%s)" % exc)
        # Without this the notification's "Don't resume" button has no handler. It is a
        # per-user class registration only, and uninstall removes it again.
        try:
            command = startup.protocol_command_line(app.paths.entry_script, app.paths.home)
            changed = startup.install_protocol(command)
            _print("notification action   : %s" % ("registered" if changed else "already registered (unchanged)"))
        except startup.StartupError as exc:
            _print("notification action   : unavailable (%s)" % exc)
    else:
        _print("notification action   : notifications are disabled in settings")
    _print("auto-resume is %s; use `enable` then `run`." % ("enabled" if enabled else "disabled"))
    return EXIT_OK


def cmd_uninstall(args) -> int:
    paths = config.Paths(args.home)
    removed = []
    foreign_autostart = None
    try:
        # Only ever unregister OUR OWN autostart. A second installation (a different
        # checkout, or the Codex plugin) registers a different command, and deleting
        # that one would silently stop a watcher this uninstall does not own.
        value = startup.current_value()
        if value is None:
            pass
        elif startup.belongs_to(value, paths.home):
            if startup.uninstall():
                removed.append("login autostart value")
        else:
            foreign_autostart = value
    except startup.StartupError as exc:
        _print("warning: %s" % exc)
    try:
        if startup.unregister_aumid():
            removed.append("notification sender identity")
    except startup.StartupError as exc:
        _print("warning: %s" % exc)
    if shortcut.uninstall():
        removed.append("start menu entry")
    try:
        registered = startup.protocol_value()
        if registered and startup.belongs_to(registered, paths.home):
            if startup.uninstall_protocol():
                removed.append("notification action registration")
        elif registered:
            _print("kept the codex-auto-resume: protocol: it points at a different installation")
    except startup.StartupError as exc:
        _print("warning: %s" % exc)
    app = App(paths, console=False, enable_logging=False)
    if app.stop_event().signal():
        for _ in range(60):
            if app.watcher_running() is False:
                break
            time.sleep(0.25)
    # Tri-state probe: only a definite False permits deletion. 'unknown' fails CLOSED.
    running = app.watcher_running()
    if running is not False:
        _print("a watcher is still running" if running else "watcher state could not be verified")
        _print("uninstall aborted before deleting any state; stop the watcher and retry")
        return EXIT_ERROR
    # Any file handlers from an earlier command in this process must be closed first.
    import logging
    for logger_name in ("codex_auto_resume",):
        for handler in list(logging.getLogger(logger_name).handlers):
            logging.getLogger(logger_name).removeHandler(handler)
            handler.close()
    considered = ([] if args.keep_logs else [paths.logs_dir]) + [paths.state_dir]
    owned_dirs = [d for d in considered if paths.owns(d)]
    skipped = [d for d in considered if d.is_dir() and not paths.owns(d)]
    targets = list(paths.owned_state_files()) + ([] if args.keep_logs else list(paths.owned_log_files()))
    for path in targets:
        try:
            # Never follow a link/junction out of the owned home when deleting.
            if path.is_file() and not path.is_symlink() and paths.confined(path):
                path.unlink()
                removed.append(str(path))
        except OSError:
            _print("warning: could not delete %s" % path)
    for directory in owned_dirs:
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            pass
    _print("removed: %s" % (", ".join(removed) if removed else "nothing (already clean)"))
    for directory in skipped:
        _print("skipped %s (no provenance marker; not created by this tool, nothing deleted there)" % directory)
    if foreign_autostart:
        _print("kept the login autostart value: it starts a different installation, not this one")
        _print("  %s" % foreign_autostart)
    _print("ChatGPT/Codex files and repositories were not touched")
    return EXIT_OK


COMMANDS = {
    "enable": cmd_enable, "disable": cmd_disable, "status": cmd_status, "pending": cmd_pending,
    "cancel": cmd_cancel, "logs": cmd_logs, "run": cmd_run, "stop": cmd_stop,
    "install": cmd_install, "uninstall": cmd_uninstall, "doctor": cmd_doctor,
    "activate": cmd_activate,
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
