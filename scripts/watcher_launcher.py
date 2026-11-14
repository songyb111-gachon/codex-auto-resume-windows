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

The same question decides which Python the watcher runs under (v0.6.23, `_on_chosen`), and is asked only where the
installation has a record of a choice (chosen_runtime.py): with none, nothing here changes. Every registered route still
starts this file under the bundled runtime. Where the advanced edition's plug answers SUPERVISE to it, the watcher runs as a
child under the Python the record names, and this process stays on the bundled runtime to see that it came up within
WATCHER_WAIT. One that did not is ended, the plug is told - it takes the record away and says so, once -
and the watcher runs here, on the bundled runtime. The standard edition answers nothing and has no record.
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
# v0.6.23 final (R10 of the second round's limits audit): a launcher started to follow a stop another process is about to
# ask - the Python choice's restart of the watcher (the advanced edition's, which keeps its own copy of this name). It
# is started before that stop, so a window closed mid-restart cannot leave the watcher stopped and none started: it waits
# for the watcher it follows to let go of its mutex, at most AFTER_STOP_WAIT, and starts the watcher as ever; one that is
# still running then is left alone, and this launcher ends. Three times control.WATCHER_STOP_TIMEOUT, the 10 s the asking
# process waits for the stop, since this one may be up before the stop is even asked. Read once and taken out of this
# process's environment, so nothing it starts inherits it.
AFTER_STOP_MARK = "CODEX_AUTO_RESUME_AFTER_STOP"
AFTER_STOP_WAIT = 30.0
AFTER_STOP_POLL = 0.25
# The marketplace names this product is published under. See resolve_plugin_root.
OUR_MARKETPLACES = frozenset({"codex-auto-resume-windows"})
EXIT_ERROR = 1
# P13's two questions (v0.6.19): before the watcher runs, and once it ended.
PHASE_START, PHASE_ENDED = "start", "ended"
# And the two answers this launcher carries out: SUPERVISE, asked at the start - run the watcher as a child and stay -
# and RESTART, asked once that child ended - start it once more. Compared as they are; a plug's answer is never passed on.
SUPERVISE, RESTART = "supervise", "restart"
# v0.6.23: which Python the watcher runs under: the question (SUPERVISE: as a child, under the chosen one), and the telling
# that a watcher started under the chosen Python did not come up. Asked only where a record of a choice exists.
PHASE_RUNTIME, PHASE_RUNTIME_FAILED = "runtime", "runtime_failed"
# How long a watcher started under the chosen Python has to take its mutex: plugin_setup's WATCHER_WAIT, kept here as
# NO_REMOTE_DEBUG is, since this file runs before any engine is found. Counted from that child's start, never from this
# launcher's: what comes before it - the plug's question, on the bundled runtime - is no part of the chosen Python's start
# (41 and 48 s on the owner's PC on 2026-11-11, before a child that then came up). The Dashboard's own wait for a
# restart it asked for, the advanced edition's own, is longer than both together.
WATCHER_WAIT = 45.0
# When this process started, on the clock a wait is measured by: the launcher's log says how long each step of a start
# under the chosen Python took after it (`_since`).
BEGAN = time.monotonic()
# The argument, after `run`, that starts the watcher as a supervised child: the launcher's own, in this process, and
# never a supervisor of its own - no grandchildren.
CHILD_ARGUMENT = "--supervised-child"
# Where the start question named no supervisor though one was asked for (the state busy, Codex's check answering badly):
# how long before it is asked once more, and what the Dashboard reads while the watcher runs here without one
# (advanced engine/supervise.UNSUPERVISED_FILE, the file's name kept here as this file finds no engine first).
ASK_AGAIN_SECONDS = 5
UNSUPERVISED_FILE = "unsupervised.txt"
# PEP 768 (Python 3.14): remote debugging off, in this process and in every one it starts - the copy of
# startup.NO_REMOTE_DEBUG this file keeps, since it runs before any engine is found. Hyphens: `-X disable_remote_debug`
# is an unknown option, kept without a word, and leaves remote debugging on.
NO_REMOTE_DEBUG = ("-X", "disable-remote-debug")


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
        # Newest by mtime: version strings carry cachebuster suffixes and do not sort. A copy a
        # plugin update removes between the listing and here is passed over, not the launch's end.
        newest = None
        for candidate in candidates:
            try:
                stamp = candidate.stat().st_mtime
            except OSError:
                continue
            if newest is None or stamp > newest[0]:
                newest = (stamp, candidate)
        if newest is not None:
            return newest[1]
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


def _since() -> str:
    """Seconds since this launcher started, for its log."""
    return "%.1f s" % (time.monotonic() - BEGAN)


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
    if os.environ.pop(AFTER_STOP_MARK, None) and not _after_stop(here, home):
        return 0
    # Arguments select the command, defaulting to the watcher. The notification button
    # registers `activate` through this same stable path, so a plugin update cannot leave
    # the button pointing at a version directory that no longer exists.
    command = [str(argument) for argument in (argv or [])] or ["run"]
    # A supervised child runs the watcher here and asks nothing: its supervisor asks for it.
    child = command == ["run", CHILD_ARGUMENT]
    if child:
        command = ["run"]
    asks = command == ["run"] and not child
    held = None
    # The start question, asked once in this process whichever Python the watcher runs under (v0.6.23: a watcher under the
    # chosen one was started with it never asked, so crash restart, which answers an end only where it was, never saw one).
    started = []

    def start_answer():
        if not started:
            started.append(_start_answer(here, home))
        return started[0]
    if asks:
        code = _on_chosen(here, home, start_answer)
        if code is not None:
            return code
    if asks:
        answer, held = start_answer()
        if answer == SUPERVISE:
            code = _supervised(here, home)
            if code is not None:
                return code
            asks = False                            # no child could be started: run it here, ask nothing more
    # Only here: a supervisor runs no watcher of its own, and the engine imported once more for nothing cost it a second
    # or more at every sign-in, before its child had even started (v0.6.23).
    from codex_auto_resume.cli import main as cli_main
    code = cli_main(["--home", str(home), "--quiet"] + command)
    if code == EXIT_SCHEMA_NEWER and command == ["run"]:
        _relaunch_once(here, command)
    elif held is not None:
        # It ran here for want of an answer. Now it has ended is the one later moment a supervisor can be had: from the
        # start, under the rules a supervised end is judged by (no end on purpose, the stop event, three an hour).
        if (_supervise(home, {"phase": PHASE_START}) == SUPERVISE
                and _supervise(home, {"phase": PHASE_ENDED, "exit_code": code}) == RESTART):
            _note(here, "the watcher that ran without crash restart stopped unexpectedly (exit %s); starting it supervised" % code)
            _unsupervised(home, None)
            restarted = _supervised(here, home)
            return code if restarted is None else restarted
    elif asks:
        _supervise(home, {"phase": PHASE_ENDED, "exit_code": code})
    return code


def _after_stop(here: Path, home: Path) -> bool:
    """Whether to go on once the watcher this launcher was started to follow has let go of its mutex (AFTER_STOP_MARK):
    True once it has, or where that cannot be told at the end - the mutex settles a race, and a second watcher exits busy;
    False where it still runs after AFTER_STOP_WAIT, and nothing is started."""
    _note(here, "started to follow a stop of the watcher; waiting up to %d s for it to end" % AFTER_STOP_WAIT)
    try:
        from codex_auto_resume import config
        from codex_auto_resume.runtime.app import App
        probe = App(config.Paths(home), console=False, enable_logging=False).watcher_running
    except Exception:                               # noqa: BLE001 - not known is not a reason to start nothing
        return True
    ends = time.monotonic() + AFTER_STOP_WAIT
    while True:
        try:
            running = probe()
        except Exception:                           # noqa: BLE001 - not known yet
            running = None
        if running is False:
            return True
        if time.monotonic() >= ends:
            if running is True:
                _note(here, "the watcher it followed still runs after %d s; not starting another" % AFTER_STOP_WAIT)
                return False
            return True
        time.sleep(AFTER_STOP_POLL)


def _unsupervised(home: Path, word) -> None:
    """The file the Dashboard reads: this process and why it has no supervisor, or none. Best effort."""
    try:
        path = home / "logs" / UNSUPERVISED_FILE
        if word is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text("%d %s\n" % (os.getpid(), word), encoding="utf-8")
    except OSError:
        pass


def _start_answer(here: Path, home: Path):
    """P13's start question: (the answer, why no supervisor was named where one was asked for, or None). Where it was, it is
    asked once more a few seconds later; where it is still not named, that is said - in the launcher's log, in errors.log
    and to the Dashboard - and the watcher runs here (v0.6.23: it did for 23 hours on 2026-11-06, and nothing said so).
    Nothing more can be done from here once it runs: a supervisor over a running watcher would mean ending that watcher
    or leaving a second process resident, which neither this launcher nor crash restart ever does."""
    answer = _supervise(home, {"phase": PHASE_START})
    held = None if answer == SUPERVISE else _why_held(home)
    if held is not None:
        _note(here, "no crash restart yet (%s); asking again in %d s" % (held, ASK_AGAIN_SECONDS))
        time.sleep(ASK_AGAIN_SECONDS)
        answer = _supervise(home, {"phase": PHASE_START})
        held = None if answer == SUPERVISE else _why_held(home)
    _unsupervised(home, held)
    if held is not None:
        _note(here, "running the watcher here, without crash restart (%s)" % held)
        _complain(home, "the watcher runs without crash restart for now (%s); its next start takes it up again" % held)
    return answer, held


def _why_held(home: Path):
    """Why the start question named no supervisor, from the installed edition's plug: a closed word, or None - nothing was
    asked for, or there is no plug to say."""
    try:
        from codex_auto_resume import config, edition
        from codex_auto_resume.domain.plug import guard
        word = guard(edition.plug(config.Paths(home))).supervise_held()
    except Exception:                               # noqa: BLE001 - a launch is never failed over what it says
        return None
    return word if isinstance(word, str) and word.replace("_", "").isalpha() else None


def _on_chosen(here: Path, home: Path, start_answer=None):
    """The watcher under the Python the person chose, with this process on the bundled one to see it come up (v0.6.23).
    What to return, or None to go on as ever in this process: nothing chosen, or a choice that did not come up.

    Supervised as the bundled one is: the start question (`start_answer`, main's, so it is asked once in this process
    whichever Python the watcher ends up under) is asked before its child starts, with its second asking and its
    unsupervised.txt where it names no supervisor, and the child's end is judged by it - RESTART where crash restart
    says so, the restart counted against its cap. Without that question crash restart never restarted a watcher under
    the chosen Python (X1 of the owner's logs of 2026-11-13: nine supervised starts, not one restart row).

    A launcher started by a program that itself runs under a chosen Python - the Dashboard's Start - starts again under
    the bundled runtime first, so whichever way the watcher is started, the process that can take a bad choice back is
    never the one that needs it."""
    try:
        if home.resolve() / "runtimes" in Path(sys.executable).resolve().parents:
            return _again_under_bundled(here, home)
    except OSError:
        return None
    # No record, no question: the launcher of an installation that chose nothing is the launcher it always was.
    if not (home / "runtimes" / "chosen.json").is_file():
        return None
    answer = _supervise(home, {"phase": PHASE_RUNTIME})
    # How long the question took, in the log: the one step of a start under the chosen Python this process makes before
    # its child starts (2026-11-11: 41 and 48 s from this launcher to its child on the owner's PC, 7 s the same evening).
    _note(here, "asked which Python to run the watcher under (%s since the launcher started)" % _since())
    if answer != SUPERVISE:
        return None
    try:
        from codex_auto_resume import chosen_runtime, config
        from codex_auto_resume.runtime.app import App
        interpreter = chosen_runtime.interpreter(home, windowless=True)
        if interpreter is None or App(config.Paths(home), console=False, enable_logging=False).watcher_running() is True:
            return None
    except Exception:                               # noqa: BLE001 - the bundled runtime is always there to go on with
        return None
    _answer, held = (start_answer or (lambda: _start_answer(here, home)))()
    return _supervised(here, home, interpreter, held)


def _again_under_bundled(here: Path, home: Path):
    """Start this launcher again under the bundled runtime: 0 once the watcher is up or the wait is over, so whoever started
    this one and watches it (control.await_watcher) sees a launcher that lived to bring the watcher up; None where it could
    not be started, and the watcher runs here. Detached, as `_relaunch_once` starts it."""
    import subprocess
    interpreter = home / "runtime" / "pythonw.exe"
    if not interpreter.is_file():
        return None
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen([str(interpreter), *NO_REMOTE_DEBUG, str(Path(__file__).resolve()), "run"], close_fds=True,
                                   creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
    except OSError as exc:
        _complain(here, "could not start again under the bundled runtime: %s" % exc)
        return None
    _note(here, "started again under the bundled runtime")
    _came_up(home, process, asks_first=True)
    return 0


def _came_up(home: Path, child, asks_first=False) -> bool:
    """Whether the watcher started as `child` under the chosen Python took its mutex within WATCHER_WAIT - with the one
    more look setup gives one that took it just as the wait ended (plugin_setup.looked_again). With `asks_first`, `child`
    is this launcher again, which asks its question before it starts the watcher's child: the question's time comes on
    top (control.start_timeout, v0.6.23), or this process would end at 45 s while the other still asks, and whoever
    started it would read that end as a start that failed."""
    try:
        from codex_auto_resume import config
        from codex_auto_resume.control.watcher import await_watcher, start_timeout
        from codex_auto_resume.runtime.app import App
        probe = App(config.Paths(home), console=False, enable_logging=False).watcher_running
        wait = start_timeout(home, WATCHER_WAIT) if asks_first else WATCHER_WAIT
        state = await_watcher(probe, child, timeout=wait)["state"]
        return state == "running" or (state == "unconfirmed" and probe() is True)
    except Exception:                               # noqa: BLE001 - not known to be up is not up
        return False


def _not_up(here: Path, home: Path, child) -> None:
    """The chosen Python did not bring the watcher up: its child ended, and the plug told, which takes the record away."""
    if child is not None:
        try:
            child.kill()
            child.wait(timeout=10)
        except Exception:                           # noqa: BLE001 - it had ended already
            pass
    _note(here, "the watcher did not come up under the chosen Python; going on under the bundled runtime")
    _supervise(home, {"phase": PHASE_RUNTIME_FAILED})


def _supervised(here: Path, home: Path, chosen=None, held=None):
    """SUPERVISE (v0.6.19): run the watcher as a child and wait for it; once it ended, ask P13 again, and start it once
    more only where the answer is RESTART. What to return: the child's last exit code - or None where no child could be
    started at all, and the watcher is then run in this process, as with no supervisor.

    With `chosen` (v0.6.23), the pythonw.exe the person chose runs that child, and each start of it is held to coming up
    (`_came_up`); one that does not leaves None, and the watcher is run in this process, on the bundled runtime. `held`
    is why the start question named no supervisor for it (`_start_answer`): once that child ended, the question is asked
    again - the one later moment a supervisor can be had, as main asks it of a watcher it ran itself - and the end is
    judged under it.

    Every end that is not followed by another start says so in the launcher's log, with its exit code (v0.6.23: an end
    crash restart passed over left no line at all, and a crash could not be told from a kill).

    The child is this file again, under the pythonw.exe beside the interpreter that runs it (as `_relaunch_once` finds
    it), with CREATE_NO_WINDOW and nothing to read or write; its arguments are constants. A child that ended because the
    state is newer than its code has started the installed copy once itself (`_relaunch_once`, unchanged), so its code
    is returned as it is, unasked. While it waits, this process holds no lock and no state - only the child."""
    import subprocess
    interpreter = chosen or Path(sys.executable).resolve().with_name("pythonw.exe")
    if not interpreter.is_file():
        _note(here, "no pythonw.exe to run a supervised watcher under; running it here")
        return None
    arguments = [str(interpreter), *NO_REMOTE_DEBUG, str(Path(__file__).resolve()), "run", CHILD_ARGUMENT]
    started = False
    while True:
        try:
            child = subprocess.Popen(arguments, close_fds=True,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            _complain(here, "could not start a supervised watcher: %s" % exc)
            if chosen is not None:
                _not_up(here, home, None)
                return None
            return EXIT_ERROR if started else None
        started = True
        _note(here, "watcher started as a supervised child (pid %d)" % child.pid
              + ("" if chosen is None else " under the chosen Python, %s since the launcher started" % _since()))
        if chosen is not None:
            if not _came_up(home, child):
                _not_up(here, home, child)
                return None
            _note(here, "the watcher came up under the chosen Python (%s since the launcher started)" % _since())
        code = child.wait()
        if code == EXIT_SCHEMA_NEWER:
            _note(here, "the supervised watcher ended (exit %s): the state is newer than its code, and it started the "
                        "installed copy itself; not starting it again here" % code)
            return code
        if held is not None and _supervise(home, {"phase": PHASE_START}) == SUPERVISE:
            held = None
            _unsupervised(home, None)
        if _supervise(home, {"phase": PHASE_ENDED, "exit_code": code}) != RESTART:
            _note(here, "the supervised watcher (pid %d) ended (exit %s); not starting it again" % (child.pid, code))
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
        subprocess.Popen([str(interpreter), *NO_REMOTE_DEBUG, str(Path(__file__).resolve())] + list(command),
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


def _again_without_remote_debug():
    """Start this launcher again with remote debugging off, where it is on (PEP 768): True when it was, and this
    process ends; False to go on here.

    The sign-in value keeps the form every released version reads (startup.command_line), and a notification-button
    value an older version wrote has no option either, so the launcher Windows starts under pythonw.exe may have
    remote debugging on. It is then started once more, detached, as `_relaunch_once` starts it - the same arguments
    with NO_REMOTE_DEBUG in front - before anything is read or run. What the product starts itself passes the option
    and never comes here. Once at most: a launcher given the option never starts another, and one that cannot be
    started leaves this one to go on. A launcher run by hand with python.exe goes on as it is."""
    probe = getattr(sys, "is_remote_debug_enabled", None)
    try:
        if probe is None or not probe() or NO_REMOTE_DEBUG[1] in getattr(sys, "_xoptions", {}):
            return False
    except Exception:                               # noqa: BLE001 - a question that cannot be asked is a no
        return False
    if Path(sys.executable).name.lower() != "pythonw.exe":
        return False
    import subprocess
    here = Path(__file__).resolve().parent
    # pythonw.exe, a GUI program: detached opens nothing (see _relaunch_once).
    interpreter = Path(sys.executable).resolve().with_name("pythonw.exe")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([str(interpreter), *NO_REMOTE_DEBUG, str(Path(__file__).resolve()), *sys.argv[1:]],
                         close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        _complain(here, "could not start again with remote debugging off: %s" % exc)
        return False
    _note(here, "remote debugging was on; started again without it")
    return True


if __name__ == "__main__":
    sys.exit(0 if _again_without_remote_debug() else _guarded(sys.argv[1:]))
