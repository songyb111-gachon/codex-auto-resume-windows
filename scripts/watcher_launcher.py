"""Stable entry point for the autostarted watcher, however the product was installed.

`codex plugin add` copies a plugin into a *versioned* cache directory, so the plugin's
own path changes on every update. Registering that path for autostart would silently
break the next time the plugin is updated. Setup therefore copies this one small file
to a fixed location and registers *it*; the plugin root is resolved again at every
launch, so updates need no re-registration.

Resolution has an order rather than a fixed path, and since v0.5.2 the installed
application wins it: removing the *plugin* therefore leaves the installed copy running,
which is correct, because the installer is what put it there. `uninstall` is what stops
it. The versioned cache is only a fallback for an installation made before there was an
application directory to prefer.

This file only locates and starts the existing watcher. It contains no detection,
no scheduling and no submission logic.

Before it runs the watcher, and once the watcher it ran has ended, the installed edition's plug
is asked what the launcher should do about it (P13, `_supervise`, v0.6.19). The standard edition
has nothing to say, so the launcher runs the watcher in its own process and returns what it
returned, as ever. The advanced edition's crash restart answers SUPERVISE at the start: the
launcher then runs the watcher as a child - this same file, under pythonw.exe, with no window, and
an argument that makes it a child, which never supervises one of its own - and waits for it; once
the child ended it asks again, and starts it once more only where the answer is RESTART
(`_supervised`). What a plug answers is a closed word: nothing of it reaches the child's arguments.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

CONFIG_NAME = "runtime.json"
# The watcher exits with this when the state was written by a newer version than the
# code it is running (app.EXIT_SCHEMA_NEWER). The launcher then starts itself once more,
# so an installation that has been updated underneath a running watcher takes over.
EXIT_SCHEMA_NEWER = 4
# v0.6.11: the memory guard stopped the watcher between two ticks (app.EXIT_MEMORY_GUARD). Like every
# code but the one above it is returned as it is, and nothing is started again: a watcher the guard
# stopped stays stopped until a person starts it. The standard edition has no supervisor (F8).
EXIT_MEMORY_GUARD = 5
RELAUNCH_MARK = "CODEX_AUTO_RESUME_RELAUNCHED"
# The marketplace names this product is published under. See resolve_plugin_root.
OUR_MARKETPLACES = frozenset({"codex-auto-resume-windows"})
EXIT_ERROR = 1
# P13's two questions (v0.6.19): before the watcher runs, and once it ended.
PHASE_START, PHASE_ENDED = "start", "ended"
# And the two answers this launcher carries out: SUPERVISE, asked at the start - run the watcher as a child and stay -
# and RESTART, asked once that child ended - start it once more. Compared as they are; a plug's answer is never passed on.
SUPERVISE, RESTART = "supervise", "restart"
# The argument, after `run`, that starts the watcher as a supervised child: the launcher's own, in this process, and
# never a supervisor of its own - no grandchildren.
CHILD_ARGUMENT = "--supervised-child"


def codex_home() -> Path:
    value = os.environ.get("CODEX_HOME")
    if value:
        return Path(value).expanduser()
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(profile) / ".codex"


def _usable(root: Path) -> bool:
    """A candidate must look like this project, not merely like a directory."""
    try:
        return (root / "src" / "auto_resume.py").is_file() and (root / "src" / "codex_auto_resume" / "cli.py").is_file()
    except OSError:
        return False


def resolve_plugin_root(config: dict) -> Path | None:
    """Where the engine is, in the order that keeps one installation authoritative.

    The installed application wins. It sits beside the runtime that this launcher was
    started by and beside the state it is about to open, and it is the same copy the
    settings window talks to - so the window and the watcher can never end up running
    different versions of the code against the same database.

    That ordering matters because there is usually a second copy: `codex plugin add`
    keeps its own, in a versioned cache directory. Preferring the cache, as this used
    to, meant that installing a *newer plugin* from a marketplace silently swapped the
    engine underneath an older installation while everything else still pointed at the
    old one. Updating the plugin should update the skills and the manifest; replacing
    the engine is what the installer is for.

    The cache is still searched, last, for an installation from before there was an
    application directory to prefer.
    """
    home_app = None
    try:
        home = Path(config.get("home") or "")
        candidate = home / "app"
        if home.name and _usable(candidate):
            home_app = candidate
    except (OSError, TypeError, ValueError):
        home_app = None
    if home_app is not None:
        return home_app
    if config.get("mode") == "plugin":
        name = config.get("plugin_name") or ""
        # This product's own marketplace only. It used to be any marketplace, on the grounds
        # that a user might reinstall from a renamed source - which also meant another
        # publisher's plugin that happened to share the name was run by this launcher, at
        # sign-in, if it was the newest copy in the cache. A renamed source now fails
        # closed: the launcher reports that no engine was found and the user reinstalls.
        cache = codex_home() / "plugins" / "cache"
        candidates = []
        try:
            for marketplace in cache.iterdir():
                if marketplace.name not in OUR_MARKETPLACES:
                    continue
                versions = marketplace / name
                if not versions.is_dir():
                    continue
                for version in versions.iterdir():
                    if _usable(version):
                        candidates.append(version)
        except OSError:
            candidates = []
        if candidates:
            # Newest by mtime: version strings carry cachebuster suffixes and do not sort.
            return max(candidates, key=lambda path: path.stat().st_mtime)
    recorded = config.get("plugin_root")
    if recorded:
        root = Path(recorded)
        if _usable(root):
            return root
    return None


def _complain(home: Path, reason: str) -> None:
    # pythonw.exe has no console, so a failure has to leave a trace on disk.
    try:
        logs = home / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "errors.log").open("a", encoding="utf-8") as stream:
            stream.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + "watcher launcher: " + reason + "\n")
    except OSError:
        pass


LAUNCH_LOG = "launcher.log"
LAUNCH_LOG_LINES = 50


def _note(home: Path, text: str) -> None:
    """Record that this process ran, before anything else can fail.

    Under `pythonw.exe` there is no console and no stderr, so a failure before logging
    is configured leaves nothing at all behind - and the one question that then cannot
    be answered is the important one: did Windows start us at sign-in and we died, or
    did Windows never start us? A watcher that silently never runs looks exactly like a
    watcher that runs and finds nothing to do.

    Deliberately not the main log: this is one line per launch, written before the real
    logging exists, and it is trimmed rather than rotated because only the last few
    launches are ever interesting.
    """
    try:
        logs = home / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / LAUNCH_LOG
        lines = []
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-LAUNCH_LOG_LINES:]
        lines.append(time.strftime("[%Y-%m-%d %H:%M:%S] ") + text)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        pass


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    _note(here, "launcher started (pid %d)" % os.getpid())
    if os.environ.get(RELAUNCH_MARK):
        # Give the watcher that started this one time to release its mutex.
        time.sleep(2)
    try:
        config = json.loads((here / CONFIG_NAME).read_text(encoding="utf-8"))
        home = Path(config["home"])
    except (OSError, ValueError, KeyError, TypeError):
        _complain(here, "cannot read %s; not starting" % CONFIG_NAME)
        return EXIT_ERROR
    root = resolve_plugin_root(config)
    if root is None:
        _complain(home, "no installed codex-auto-resume engine found; not starting")
        return EXIT_ERROR
    sys.path.insert(0, str(root / "src"))
    from codex_auto_resume.cli import main as cli_main
    # Arguments select the command, defaulting to the watcher. The notification button
    # registers `activate` through this same stable path, so a plugin update cannot leave
    # the button pointing at a version directory that no longer exists.
    command = [str(argument) for argument in (argv or [])] or ["run"]
    # A supervised child runs the watcher here and asks nothing: its supervisor asks for it.
    child = command == ["run", CHILD_ARGUMENT]
    if child:
        command = ["run"]
    asks = command == ["run"] and not child
    if asks and _supervise(home, {"phase": PHASE_START}) == SUPERVISE:
        code = _supervised(here, home)
        if code is not None:
            return code
        asks = False                                # no child could be started: run it here, ask nothing more
    code = cli_main(["--home", str(home), "--quiet"] + command)
    if code == EXIT_SCHEMA_NEWER and command == ["run"]:
        _relaunch_once(here, command)
    elif asks:
        _supervise(home, {"phase": PHASE_ENDED, "exit_code": code})
    return code


def _supervised(here: Path, home: Path):
    """SUPERVISE (v0.6.19): run the watcher as a child and wait for it; once it ended, ask P13 again, and start it once
    more only where the answer is RESTART. What to return: the child's last exit code - or None where no child could be
    started at all, and the watcher is then run in this process, as with no supervisor.

    The child is this file again, under the pythonw.exe beside the interpreter that runs it (as `_relaunch_once` finds
    it), with CREATE_NO_WINDOW and nothing to read or write; its arguments are constants. A child that ended because the
    state is newer than its code has started the installed copy once itself (`_relaunch_once`, unchanged), so its code
    is returned as it is, unasked. While it waits, this process holds no lock and no state - only the child."""
    import subprocess
    interpreter = Path(sys.executable).resolve().with_name("pythonw.exe")
    if not interpreter.is_file():
        _note(here, "no pythonw.exe to run a supervised watcher under; running it here")
        return None
    arguments = [str(interpreter), str(Path(__file__).resolve()), "run", CHILD_ARGUMENT]
    started = False
    while True:
        try:
            child = subprocess.Popen(arguments, close_fds=True,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            _complain(here, "could not start a supervised watcher: %s" % exc)
            return EXIT_ERROR if started else None
        started = True
        _note(here, "watcher started as a supervised child (pid %d)" % child.pid)
        code = child.wait()
        if code == EXIT_SCHEMA_NEWER:
            return code
        if _supervise(home, {"phase": PHASE_ENDED, "exit_code": code}) != RESTART:
            return code
        _note(here, "the watcher stopped unexpectedly (exit %s); starting it again" % code)


def _supervise(home: Path, facts) -> None:
    """P13: ask the installed edition's plug about the watcher - `{"phase": "start"}` before it
    runs, `{"phase": "ended", "exit_code": n}` once it ended, and then with `clean` too: whether its
    heartbeat says it stopped on purpose (`_ended_cleanly`), read only for a plug that is not NULL.

    Asked in this process, and never about the relaunch above, which is the one restart the
    launcher makes of itself. What it returns is the answer - SUPERVISE, RESTART or DEFER - which
    the caller compares with its own words (`main`, `_supervised`); None where nothing could be
    asked. An engine from before editions has no plug to ask, and is the standard edition anyway.
    """
    try:
        from codex_auto_resume import config, edition
        from codex_auto_resume.domain.plug import guard
    except ImportError:
        return None
    try:
        plug = guard(edition.plug(config.Paths(home)))
        if isinstance(facts, dict) and facts.get("phase") == PHASE_ENDED and not plug.null:
            facts = dict(facts, clean=_ended_cleanly(config.Paths(home)))
        return plug.supervise(facts)
    except Exception:                               # noqa: BLE001 - supervision never fails a launch
        return None


def _ended_cleanly(paths):
    """Whether the watcher's heartbeat says it stopped on purpose - CLEAN or MEMORY_GUARD, as
    control/watcher.how_it_ended reads it: True; False where it still says RUNNING; None where
    there is no state, it cannot be read, or it says neither. Read on a connection of its own."""
    try:
        from codex_auto_resume.domain.vocabulary import WatcherEnd
        from codex_auto_resume.store import Store
        if not (Path(paths.state_dir) / "state.sqlite").is_file():
            return None
        store = Store(paths.state_dir, check=False)
        try:
            mark = (store.watcher_status() or {}).get("end_mark")
        finally:
            store.close()
    except Exception:                               # noqa: BLE001 - a fact not known is None
        return None
    if mark in (WatcherEnd.CLEAN, WatcherEnd.MEMORY_GUARD):
        return True
    return False if mark == WatcherEnd.RUNNING else None


def _relaunch_once(here: Path, command) -> None:
    """Start the launcher again, once, so it resolves the installation afresh.

    Only once: a relaunched watcher that finds the state still newer than its code
    exits for good, and says so, rather than restarting in a loop.
    """
    if os.environ.get(RELAUNCH_MARK):
        _note(here, "the state is newer than the installed engine; not starting again")
        return
    import subprocess
    # pythonw.exe, not sys.executable. Every registered route runs this under pythonw.exe
    # already; a launcher run by hand with python.exe would otherwise start a detached
    # python.exe, which has no console to hand down, so anything it started plainly would
    # open a window. There is no console interpreter to fall back to here, on purpose.
    interpreter = Path(sys.executable).resolve().with_name("pythonw.exe")
    if not interpreter.is_file():
        _note(here, "the state is newer than this engine, and there is no pythonw.exe to start "
                    "the installed copy under; not starting again")
        return
    _note(here, "the state is newer than this engine; starting the installed copy once")
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        subprocess.Popen([str(interpreter), str(Path(__file__).resolve())] + list(command),
                         env=dict(os.environ, **{RELAUNCH_MARK: "1"}), close_fds=True,
                         creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        _complain(here, "could not start the installed copy: %s" % exc)


def _guarded(argv=None) -> int:
    """Run, and make sure a crash says so somewhere.

    Any exception escaping `main` under `pythonw.exe` is written to a stderr that does
    not exist, so the process vanishes with no message, no log line and no event. That
    is how an autostart failure becomes unexplainable, so it is caught here and put on
    disk instead.
    """
    here = Path(__file__).resolve().parent
    try:
        return main(argv)
    except SystemExit:
        raise
    except BaseException as exc:                    # noqa: BLE001 - last resort on purpose
        import traceback
        _note(here, "launcher failed: %s: %s" % (type(exc).__name__, exc))
        _complain(here, "unhandled %s: %s" % (type(exc).__name__, exc))
        try:
            with (here / "logs" / "errors.log").open("a", encoding="utf-8") as stream:
                traceback.print_exc(file=stream)
        except OSError:
            pass
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(_guarded(sys.argv[1:]))
