"""Installing, uninstalling, the diagnostics bundle, and putting the state back a version.

Each of these changes the machine rather than the state, which is why they are together and
apart from the commands that read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from .. import config, edition, notify, settings, shortcut, startup
from ..app import EXIT_ERROR, EXIT_OK, App
from ..domain.plug import DamagedPlug, Edition
from ..store import LegacyStore, StoreError, downgrade_to_v2
from ..windows import AdapterError
from .base import CliError, _app, _open_state, _print


def cmd_install(args) -> int:
    app = _app(args)
    # Reads one setting; while an older watcher still owns the state it is read through
    # that watcher's schema, and the upgrade happens when a current watcher starts.
    with _open_state(app) as store:
        enabled = store.settings()["enabled"]
    _print("owned state directory : %s" % app.paths.state_dir)
    _print("owned log directory   : %s" % app.paths.logs_dir)
    if getattr(args, "edition_from", None):
        _edition_changed(app, Edition(args.edition_from))
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


def _edition_changed(app, previous: Edition) -> None:
    """The installer has replaced an installation of edition `previous` with this one.

    Only the new edition knows what that means for it - entering the advanced edition turns
    every capability off, whatever an earlier advanced installation had left on - so its plug
    is told, once, here. The standard edition's plug has nothing to do. An advanced package
    that cannot be loaded cannot be told, and the change is refused rather than left half made:
    whatever it would have turned off would still be on the day it loads."""
    plug = edition.plug(app.paths)
    if isinstance(plug, DamagedPlug):
        raise CliError("the advanced package could not be loaded (%s); the edition change "
                       "was not completed" % plug.reason)
    if plug.edition == previous:
        _print("edition               : %s (unchanged)" % plug.edition)
        return
    try:
        plug.edition_changed(previous)
    except Exception:
        raise CliError("the %s edition could not be set up after the change" % plug.edition) from None
    app.logger.info("edition changed from %s to %s", previous, plug.edition)
    _print("edition               : %s (was %s)" % (plug.edition, previous))


def cmd_uninstall(args) -> int:
    paths = config.Paths(args.home)
    removed = []
    foreign_autostart = None

    # Stop the watcher and refuse to go on unless it is *definitely* gone. This has to
    # be the first thing, before a single registration is touched: it used to sit after
    # the autostart value, the notification identity, the Start Menu entry and the toast
    # handler had all been deleted, so the abort left an installation that still ran and
    # still had pending recoveries but no longer started at sign-in and could no longer
    # draw a notification - while printing "aborted before deleting any state", which
    # was true only of *state*, and the README promised more than that.
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
        _print("uninstall aborted before removing anything; stop the watcher and retry")
        return EXIT_ERROR

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
    # The notification identity and the Start Menu shortcut are one registration in two
    # places, and both are per-user singletons at fixed locations - so a second copy of
    # this tool overwrites them rather than adding its own. They get the same ownership
    # check the autostart gets, for the same reason: removing them would leave the other
    # installation running and silently unable to show a notification ever again.
    try:
        owner = startup.notification_identity_owner(paths.home)
    except startup.StartupError as exc:
        _print("warning: %s" % exc)
        owner = False
    if owner is False:
        _print("kept the notification identity and Start Menu entry: they belong to a "
               "different installation")
    else:
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
    # Any file handlers from an earlier command in this process must be closed first.
    import logging
    for logger_name in ("codex_auto_resume",):
        for handler in list(logging.getLogger(logger_name).handlers):
            logging.getLogger(logger_name).removeHandler(handler)
            handler.close()
    # `--keep-state` is what the installer's ordinary uninstall uses. Settings and pending
    # recoveries are the user's, not the program's: removing them by default made a plain
    # uninstall/reinstall silently lose everything that was waiting to resume, while the
    # installer said in the same breath that they had been kept.
    keep_state = getattr(args, "keep_state", False)
    # The advanced edition's directory goes before config/, which holds it, so each is empty
    # when its turn comes. It is there only in an installation that has been advanced; a link
    # in its place is not considered at all (config.owned_advanced_files).
    edition_state = [] if paths.advanced_dir.is_symlink() else [paths.advanced_dir]
    considered = (([] if args.keep_logs else [paths.logs_dir])
                  + ([] if keep_state else edition_state + [paths.state_dir]))
    owned_dirs = [d for d in considered if paths.owns(d)]
    skipped = [d for d in considered if d.is_dir() and not paths.owns(d)]
    targets = ([] if keep_state else list(paths.owned_state_files()))
    if not args.keep_logs:
        targets += list(paths.owned_log_files())
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
    if keep_state:
        _print("kept your settings and pending recoveries in %s" % paths.state_dir)
    for directory in skipped:
        _print("skipped %s (no provenance marker; not created by this tool, nothing deleted there)" % directory)
    if foreign_autostart:
        _print("kept the login autostart value: it starts a different installation, not this one")
        _print("  %s" % foreign_autostart)
    _print("ChatGPT/Codex files and repositories were not touched")
    return EXIT_OK


def cmd_diagnostics(args) -> int:
    from .. import control, diagnostics
    paths = config.Paths(args.home)
    target = Path(args.out) if args.out else Path.cwd() / diagnostics.default_name()
    try:
        written = diagnostics.write(control.Control(paths), target)
    except FileExistsError as exc:
        raise CliError(str(exc)) from None
    _print("diagnostics written to %s" % written)
    _print("ids are aliases and paths are removed; read the file before sharing it")
    return EXIT_OK


def cmd_downgrade_state(args) -> int:
    """Rewrite the state so a v0.5 release can read it, keeping every record.

    Needs the watcher stopped: it runs only while holding the watcher's mutex, so a
    watcher cannot be writing rows while their schema changes. Deleting the state is
    never the way back - it would forget which failures were already cancelled,
    exhausted or possibly sent, and which conversations were switched off.
    """
    app = _app(args)
    try:
        with app.mutex(timeout=0.0):
            result = downgrade_to_v2(app.paths.state_dir)
    except AdapterError:
        _print("the watcher is running; stop it first (stop), then run this again")
        return EXIT_ERROR
    if not result["changed"]:
        _print("the state is already schema 2; nothing to do")
        return EXIT_OK
    app.logger.info("state downgraded to schema 2 (%d records kept)", result["rows"])
    _print("state rewritten as schema 2; %d records kept, and a copy of the previous state "
           "was saved beside it" % result["rows"])
    _print("install the older release now; starting this version's watcher again upgrades "
           "the state again")
    return EXIT_OK
