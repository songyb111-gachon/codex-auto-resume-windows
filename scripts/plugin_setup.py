"""Thin control layer used by the Codex plugin skill.

This is a front end, not a second engine. It picks a runtime home that survives
plugin updates, then calls the ordinary command-line interface. Detection,
scheduling, duplicate protection and submission all stay in the existing core;
nothing here talks to a Codex thread.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "codex-auto-resume"
LAUNCHER_NAME = "watcher-launcher.py"
RUNTIME_CONFIG = "runtime.json"
ICON_NAME = "codex-auto-resume.ico"
ENV_RUNTIME_HOME = "CODEX_AUTO_RESUME_PLUGIN_HOME"
# What the installer tells setup about the call it is making, as environment variables set for that one call and
# never as arguments: the installer may be a newer version than the setup it runs (the bootstrap's check-over runs
# the INSTALLED plugin_setup.py), and an older one rejects an argument it does not know - so `setup` would not run
# at all - while it ignores a variable it does not read.
ENV_WILL_LOOK_AGAIN = "CODEX_AUTO_RESUME_SETUP_WILL_LOOK_AGAIN"   # "1": the caller looks at the watcher again after setup
ENV_ENGLISH = "CODEX_AUTO_RESUME_SETUP_ENGLISH"                   # "1": the caller's log is English: say watcher-running so
RUNTIME_DIR_NAME = ".codex-auto-resume"
# The directory names the installer creates under the root - and therefore the ones
# it would destroy if it ever ran against a directory that merely contained them.
OCCUPIED_NAMES = ("app", "runtime", "config", "logs")
MIN_PYTHON = (3, 12)
CHECK = "✓"
EXIT_OK = 0
EXIT_ERROR = 1
# Everything asked for was done, but the watcher could not be confirmed running.
# Distinct from both, because the caller has to be able to tell the difference:
# an installer that treats it as failure rolls back a good install, and one that
# treats it as success says "Installed and running." about a watcher nobody saw.
EXIT_UNCONFIRMED = 2

sys.path.insert(0, str(PLUGIN_ROOT / "src"))
from codex_auto_resume import addremove, config, control, edition, l10n, startup # noqa: E402
from codex_auto_resume.app import App                        # noqa: E402
from codex_auto_resume.commands.base import PROGRESS_LINES, progress  # noqa: E402

# Setup's own steps, counted for the setup window's bar while the installer runs it (progress): the launcher, the
# state, recovery switched on, the sign-in start, the link handler, the entry in Add or remove programs, the watcher.
SETUP_STEPS = 7


def say(key: str) -> None:
    print(l10n.message(key))


def bullet() -> str:
    """A check mark, unless this console cannot encode one.

    Windows consoles often default to a legacy code page. Crashing setup over a
    decorative glyph would be absurd, so fall back to plain ASCII.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        CHECK.encode(encoding)
    except (LookupError, UnicodeError):
        return "-"
    return CHECK


def runtime_home() -> Path:
    """A fixed location *outside* the versioned plugin cache, next to Codex's own state.

    Pending interruptions, settings and logs live here, so updating or removing the
    plugin never destroys state the watcher still needs.

    Deliberately NOT under %LOCALAPPDATA%. Setup may be run from a packaged (MSIX) host,
    and Windows silently redirects that host's AppData writes into its own private
    LocalCache: the environment variable still reads as the normal path while the files
    land inside another application's sandbox. The user profile root is not redirected,
    which is why Codex keeps its own state in ~/.codex.
    """
    override = os.environ.get(ENV_RUNTIME_HOME)
    if override:
        return Path(override).expanduser().resolve()
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return (Path(profile) / RUNTIME_DIR_NAME).resolve()


def bundled_python(home: Path, windowless: bool = True) -> Path | None:
    """The interpreter the installer deploys, if this machine has one.

    This is what makes every route end at the same product. Whichever front end runs
    setup - the installer, the Codex skill, a command line - the watcher, the autostart
    entry and the notification handler all end up pointing at this one interpreter,
    rather than at whatever interpreter happened to be running the setup.

    `windowless` asks for pythonw.exe and nothing else. It used to fall back to python.exe,
    which is a console program: Windows starts the Run value and the protocol handler
    plainly, so each would have opened a console window, the watcher's for the whole session.
    """
    name = "pythonw.exe" if windowless else "python.exe"
    executable = home / "runtime" / name
    return executable if executable.is_file() else None


def installed(home: Path) -> bool:
    """A complete installation: the bundled runtime and the application beside it.

    Both interpreters: python.exe runs setup and the bridges, and the watcher runs under
    pythonw.exe or not at all. A runtime without pythonw.exe is a damaged one, and setup
    says so - with the command that installs it again - rather than set up a watcher that
    opens a console window."""
    return (bundled_python(home, windowless=False) is not None
            and bundled_python(home) is not None
            and (home / "app" / "src" / "codex_auto_resume").is_dir())


def python_for_watcher(home: Path | None = None) -> Path:
    """pythonw.exe: the bundled one, or for a home with no runtime, the one beside this
    interpreter. Raises startup.StartupError where there is none: python.exe is never the
    answer (startup.python_launcher)."""
    launcher = bundled_python(home) if home is not None else None
    return launcher if launcher is not None else startup.python_launcher()


def _cli(home: Path, argv: list[str]) -> int:
    from codex_auto_resume.cli import main as cli_main
    return cli_main(["--home", str(home)] + argv)


def _cli_silent(home: Path, argv: list[str]) -> int:
    """Run a core command for its effect only.

    Setup composes several core commands; their individual progress lines would
    contradict each other ("no watcher is running" before one is started) and would
    mix untranslated text into a localized summary.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        return _cli(home, argv)


def install_launcher(home: Path, mode: str) -> Path:
    """Copy the stable launcher and record how to find the engine again later."""
    home.mkdir(parents=True, exist_ok=True)
    launcher = home / LAUNCHER_NAME
    shutil.copyfile(PLUGIN_ROOT / "scripts" / "watcher_launcher.py", launcher)
    # The icon must outlive the versioned plugin directory, because Windows resolves it
    # when it draws a toast rather than when the notification is registered.
    icon = PLUGIN_ROOT / "assets" / ICON_NAME
    if icon.is_file():
        shutil.copyfile(icon, home / ICON_NAME)
    payload = {"mode": mode, "plugin_name": PLUGIN_NAME, "plugin_root": str(PLUGIN_ROOT), "home": str(home)}
    (home / RUNTIME_CONFIG).write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    # Claim the root, so that later on something can prove this directory is ours before
    # deleting the program files in it. The installer asks with `verify-home`.
    config.Paths(home).claim_home()
    return launcher


def installed_as_plugin() -> bool:
    # `codex plugin add` copies the plugin under <CODEX_HOME>/plugins/cache/...
    return "plugins" in PLUGIN_ROOT.parts and "cache" in PLUGIN_ROOT.parts


def watcher_command(home: Path) -> str:
    return startup.command_line(home / LAUNCHER_NAME, None, launcher=python_for_watcher(home))


def notification_command(home: Path) -> str:
    """The notification button also goes through the stable launcher.

    Registering the plugin's own path here would break on the next update, because the
    plugin lives in a directory named after its version.
    """
    argv = [str(python_for_watcher(home)), *startup.NO_REMOTE_DEBUG, str(home / LAUNCHER_NAME), "activate"]
    return " ".join(startup.quote_argument(argument) for argument in argv) + ' "%1"'


def start_watcher(home: Path) -> str:
    """Launch the watcher detached, so it outlives this command and the Codex UI.

    Returns the state the watcher is actually in - "running", "already-running",
    "exited", "unconfirmed", or "not-started" when there is no pythonw.exe to run it under -
    rather than whether a process was created. Setup prints
    a line about the watcher immediately afterwards, and it used to print the one that
    says it is running no matter what happened next.
    """
    app = App(config.Paths(home), console=False, enable_logging=False)
    # `is True`, not `is not False`. The probe has three answers, and None means it could
    # not tell - which this rounded up to "a watcher is already running", so setup printed
    # "the watcher is running" without having launched one or looked at one. That is the
    # exact overclaim the rest of this release removes.
    #
    # Falling through on None is safe: `App.run` refuses a busy mutex, so a second watcher
    # cannot start beside a live one, and the launch is reported by `await_watcher`, which
    # returns "unconfirmed" for a probe that stays unavailable.
    if app.watcher_running() is True:
        return "already-running"
    try:
        interpreter = python_for_watcher(home)
    except startup.StartupError:
        # No pythonw.exe to run it under. Nothing is started rather than a console one, and
        # the caller reports a watcher it could not confirm, which is the truth.
        return "not-started"
    flags = 0
    if os.name == "nt":
        # Safe only because the interpreter is pythonw.exe, a GUI program: see python_for_watcher.
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    # Never the setup window's request for progress lines: the watcher lives on long after the window has gone.
    environment = {name: value for name, value in os.environ.items() if name != PROGRESS_LINES}
    process = subprocess.Popen([str(interpreter), *startup.NO_REMOTE_DEBUG, str(home / LAUNCHER_NAME), "run"],
                               cwd=str(home), close_fds=True, creationflags=flags, env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return control.await_watcher(app.watcher_running, process)["state"]


def watcher_seen(home: Path):
    """The watcher's single-instance mutex, looked at once, now: True / False / None (the probe could not tell)."""
    return App(config.Paths(home), console=False, enable_logging=False).watcher_running()


def looked_again(home: Path, started: str) -> str:
    """What `start_watcher` answered, with one more look where it could not confirm a watcher that is still starting.

    `start_watcher` waits WATCHER_START_TIMEOUT and no longer, which is a promise to the person waiting. A watcher
    whose interpreter is still importing when that wait ends - on a busy PC, right after an update has written
    every file fresh, it can take longer (the v0.6.17 live acceptance: 6 to 9 seconds from its launcher's start)
    - was reported as not confirmed, and the installer then said nothing was being watched while its own health
    check had just seen the mutex held. So the answer is looked at once more, without waiting again, before any
    word about the watcher is said: only "unconfirmed", the launched process still alive and not yet seen. One
    that exited stays exited, and a probe that cannot tell stays unconfirmed - never rounded up to running."""
    if started == "unconfirmed" and watcher_seen(home) is True:
        return "running"
    return started


def conflicting_autostart(home: Path) -> str | None:
    """A different installation registered for autostart, if any.

    Two watchers with separate state could each resume the same interruption, so
    setup refuses rather than creating the second one.
    """
    try:
        current = startup.current_value()
    except startup.StartupError:
        return None
    # Ownership, not string equality: the same installation registers a different
    # command after a Python upgrade, and that must not look like a second install.
    if not current or startup.belongs_to(current, home):
        return None
    return current


def bootstrap_command() -> str:
    """How to turn this plugin into an installation, as a runnable command line."""
    script = PLUGIN_ROOT / "scripts" / "bootstrap.ps1"
    return 'powershell -NoProfile -ExecutionPolicy Bypass -File "%s"' % script


def cmd_setup(args) -> int:
    home = runtime_home()
    # A plugin on its own is a source tree. It has no Python runtime, no settings window
    # and no MCP launcher, because those are a runtime and two compiled binaries that do
    # not belong in a source repository - and Codex has no install hook that could put
    # them there. Setting up a watcher anyway would produce a second, lesser installation
    # pointing at whatever interpreter happened to run this: a different Python, no
    # settings window, no panel. One product, one installation, so this stops and says
    # what to run instead.
    if not installed(home):
        say("not_installed")
        print()
        print("  " + bootstrap_command())
        print()
        say("not_installed_hint")
        return EXIT_ERROR
    if sys.version_info < MIN_PYTHON:
        say("python_missing")
        return EXIT_ERROR
    conflict = conflicting_autostart(home)
    if conflict and not args.replace_existing:
        say("conflict")
        print("  %s" % conflict)
        return EXIT_ERROR
    install_launcher(home, "plugin" if installed_as_plugin() else "local")
    progress("setup", 1, SETUP_STEPS)
    # Both are reported when they fail. Ignoring them is how a setup that never prepared
    # the state, or never switched recovery on, used to end with "set up and running".
    # An edition change is the installer's to report and the new edition's to act on
    # (`install --edition-from`); setup only carries it across.
    prepare = ["--quiet", "install"]
    if getattr(args, "edition_from", None):
        prepare += ["--edition-from", args.edition_from]
    incomplete = (_cli_silent(home, prepare) != EXIT_OK)
    progress("setup", 2, SETUP_STEPS)
    # A repair must not undo a decision the user made. Turning recovery back on, or
    # adding a sign-in entry they removed, would do exactly that under the name of fixing
    # something - so --keep-state leaves the pause switch alone and only re-registers an
    # autostart that is already this installation's, which also repairs a stale path.
    keep_state = getattr(args, "keep_state", False)
    if not keep_state:
        incomplete |= (_cli_silent(home, ["--quiet", "enable"]) != EXIT_OK)
    progress("setup", 3, SETUP_STEPS)
    # The same ownership check the settings window uses, so "ours" means one thing.
    register_startup = (not args.no_startup
                        and (not keep_state or control.Control(config.Paths(home)).startup_enabled()))
    if register_startup:
        startup.install(watcher_command(home))
    progress("setup", 4, SETUP_STEPS)
    # `install` above registered the protocol against the plugin's own versioned path;
    # replace it with the stable launcher so an update cannot orphan the button.
    try:
        startup.install_protocol(notification_command(home))
    except startup.StartupError:
        pass
    progress("setup", 5, SETUP_STEPS)
    # The entry in Add or remove programs, where the installer has kept an uninstaller for it to name.
    try:
        addremove.register(home, edition.name().value, config.version(),
                           addremove.display_name(config.PROJECT_ROOT / config.PLUGIN_MANIFEST))
    except startup.StartupError:
        pass
    progress("setup", 6, SETUP_STEPS)
    # v0.6.16: an update starts again what it stopped, and nothing the person had turned off. The installer says
    # --watcher-was-stopped when no watcher of this installation ran before it; the watcher is then started only
    # where it would run at the next sign-in anyway. A first installation, and every other repair, starts it as before.
    left_stopped = (keep_state and getattr(args, "watcher_was_stopped", False)
                    and not control.Control(config.Paths(home)).startup_enabled())
    started = "left-stopped" if left_stopped else start_watcher(home)
    progress("setup", 7, SETUP_STEPS)
    say("ready_title")
    print()
    say("ready_defaults")
    for key in ("ready_b1", "ready_b2", "ready_b3", "ready_b4"):
        print("  " + bullet() + " " + l10n.message(key))
    print()
    started = looked_again(home, started)
    confirmed = started in ("running", "already-running")
    # A caller that looks at the watcher again after this (the installer, after its health check) has not heard a
    # verdict yet: "not confirmed yet" is the true word mid-log, and its own last word is the verdict (v0.6.17, the
    # live acceptance's second round). A setup run alone, from Codex, has no later look, so its word stays final.
    unconfirmed_word = "setup_unconfirmed_yet" if os.environ.get(ENV_WILL_LOOK_AGAIN) == "1" else "setup_unconfirmed"
    if incomplete:
        say("setup_incomplete")
    else:
        say("setup_done" if confirmed else "setup_left_stopped" if left_stopped else unconfirmed_word)
    if register_startup:
        say("setup_autostart")
    print()
    print("state: %s" % home)
    if incomplete:
        return EXIT_ERROR
    return EXIT_OK if confirmed or left_stopped else EXIT_UNCONFIRMED


def cmd_enable(args) -> int:
    home = runtime_home()
    code = _cli_silent(home, ["--quiet", "enable"])
    # `start_watcher` blocks for up to six seconds to learn the answer; throwing it away
    # and then printing "Auto resume is on." says the thing is on when nothing is
    # watching. `_cli_silent` also swallows the engine's own warning about this.
    started = looked_again(home, start_watcher(home))
    say("enabled")
    if started not in ("running", "already-running"):
        say("setup_unconfirmed")
        return code or EXIT_UNCONFIRMED
    return code


def cmd_disable(args) -> int:
    code = _cli_silent(runtime_home(), ["--quiet", "disable"])
    say("disabled")
    return code


def cmd_cancel(args) -> int:
    code = _cli(runtime_home(), ["--quiet", "cancel", args.thread_id])
    if code == EXIT_OK:
        say("cancelled")
    return code


def cmd_status(args) -> int:
    home = runtime_home()
    app = App(config.Paths(home), console=False, enable_logging=False)
    running = app.watcher_running()
    say({True: "watcher_running", False: "watcher_stopped", None: "watcher_unknown"}[running])
    conflict = conflicting_autostart(home)
    if conflict:
        say("conflict_other")
        print("  %s" % conflict)
    print()
    return _cli(home, ["--quiet", "status"])


def cmd_watcher_running(args) -> int:
    """Whether this installation's watcher runs now, by its mutex, for the installer's last word: 0 when it does,
    EXIT_UNCONFIRMED when it does not or the probe cannot tell. One line, the words `status` says first.

    The installer asks it after its health check, where setup could not confirm the watcher it started
    (build/install/install.ps1, scripts/bootstrap.ps1): a watcher that took the mutex after setup's wait ended is
    running, and the last word says so rather than contradicting the health check printed above it."""
    running = watcher_seen(runtime_home())
    if os.environ.get(ENV_ENGLISH) == "1":
        # The installer's log is English, and this line is the one place a localized sentence landed in it (v0.6.17,
        # the live acceptance: "워처: 실행 중" on a Korean PC). `watcher_seen` has just built the App, which adopted the
        # Interface language the person stored - and an explicit choice outranks the environment's override
        # (l10n.resolve), so the line is asked for in English by name, for this one process. What the Dashboard's
        # Diagnostics shows is another process, and is untouched.
        l10n.set_preference("en")
    say({True: "watcher_running", False: "watcher_stopped", None: "watcher_unknown"}[running])
    return EXIT_OK if running is True else EXIT_UNCONFIRMED


def cmd_pending(args) -> int:
    home = runtime_home()
    app = App(config.Paths(home), console=False, enable_logging=False)
    with app.open_store() as store:
        rows = store.pending()
    if not rows:
        say("no_pending")
        return EXIT_OK
    return _cli(home, ["--quiet", "pending"])


def cmd_verify_home(args) -> int:
    """Prove the installation root belongs to us, for the PowerShell installer.

    The installer can delete `app/`, `runtime/` and, on request, `config/` and `logs/` -
    under a root an environment variable can point anywhere. It had no way to tell an
    installation from a directory that merely contained folders with those names, so it
    asks here rather than growing a second, subtly different ownership rule of its own.

    Prints the canonical root on success, so the caller confines every target it deletes
    to exactly the path this check passed on rather than to the string it started with.
    Exit code is the answer; the text is for a human reading a transcript.
    """
    home = runtime_home()
    paths = config.Paths(home)
    if not paths.owns_home():
        print("not-owned")
        print(str(home))
        return EXIT_ERROR
    print("owned")
    print(str(paths.home))
    return EXIT_OK


def cmd_claim_home(args) -> int:
    """The same question as `verify-home`, asked before the first install rather than after.

    The install path destroys three things under a root an environment variable can point
    anywhere: it sweeps `*.old-*`, moves `app/` and `runtime/` aside, and deletes the
    copies it moved. `verify-home` cannot gate that, because the first install of all
    happens into a directory that is not ours yet - and never would be, if a check that
    only recognises existing installations were allowed to refuse it.

    So the install-side question is the other half: is there anything of ours here?

    * Provably ours already - an upgrade. Nothing more to decide.
    * Nothing of ours here at all - then there is nothing to destroy, and the directory is
      claimed *now*, before a single file is written. A marker written afterwards would
      authorise the deletions backwards, which is not authorisation.
    * Anything else - a directory that already holds `app`, `runtime`, `config`, `logs` or
      a set-aside copy, with no proof any of it is ours - is refused. That is exactly the
      shape the uninstaller refuses, and installing into it would delete the same files
      the uninstaller declines to touch.

    Claiming first also survives an interrupted install: a run that dies between the claim
    and the first copy leaves a marker in an otherwise untouched directory, so the retry
    is an upgrade rather than a refusal.

    Prints the canonical root, so the caller confines what it deletes to the path that
    passed rather than to the string it started from.
    """
    home = runtime_home()
    paths = config.Paths(home)
    if paths.owns_home():
        print("owned")
        print(str(paths.home))
        return EXIT_OK
    try:
        occupied = sorted(entry.name for entry in home.iterdir()
                          if entry.name in OCCUPIED_NAMES or ".old-" in entry.name)
    except OSError:
        # No directory here yet, or not a directory at all. The first is the ordinary
        # first install; the second is caught by the claim below, which will not create a
        # directory over a file.
        occupied = []
    if occupied or not paths.claim_home():
        print("not-owned")
        print(str(home))
        for name in occupied:
            print(name)
        return EXIT_ERROR
    print("claimed")
    print(str(paths.home))
    return EXIT_OK


def cmd_uninstall(args) -> int:
    home = runtime_home()
    # Keeping settings and pending recoveries is the default here: the installer offers a
    # separate purge for the other case, and losing a queued recovery to an ordinary
    # uninstall is not something a user would expect or forgive.
    # The watcher's log too ("Keep settings and history"): the core uninstall deletes auto-resume.log and errors.log
    # unless --keep-logs, so the v0.6.17 acceptance's keep-data uninstall and reinstall left auto-resume.log starting
    # at the reinstall while launcher.log and codex-start.log, which it never names, kept their lines.
    flags = [] if getattr(args, "purge", False) else ["--keep-state", "--keep-logs"]
    code = _cli(home, ["--quiet", "uninstall"] + flags)
    if code != EXIT_OK:
        return code
    paths = config.Paths(home)
    for name in (LAUNCHER_NAME, RUNTIME_CONFIG):
        path = home / name
        try:
            if path.is_file() and not path.is_symlink() and paths.confined(path):
                path.unlink()
        except OSError:
            pass
    try:
        if home.is_dir() and not any(home.iterdir()):
            home.rmdir()
    except OSError:
        pass
    say("uninstalled")
    return EXIT_OK


def cmd_remove_entry(args) -> int:
    """Take this installation's entry in Add or remove programs and the uninstaller kept for it away. What a
    hand-over to a version that knows neither runs first, so it leaves neither behind."""
    home = runtime_home()
    try:
        removed = addremove.unregister(home)
    except startup.StartupError as exc:
        print("entry: failed %s" % exc)
        return EXIT_ERROR
    kept = addremove.remove_kept(home)
    print("entry: removed" if removed or kept else "entry: none")
    return EXIT_OK


def cmd_downgrade_state(args) -> int:
    """For Install another version... (the bootstrap's -Pick): the state converted for an older
    release, the watcher asked to stop and waited for first, and one line saying what was done
    (cli downgrade-state --stop-watcher)."""
    argv = ["--quiet", "downgrade-state", "--to", str(args.to)]
    if args.stop_watcher:
        argv.append("--stop-watcher")
    return _cli(runtime_home(), argv)


def passthrough(name: str):
    def run(args) -> int:
        extra = ["-n", str(args.lines)] if name == "logs" else []
        return _cli(runtime_home(), ["--quiet", name] + extra)
    return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plugin_setup", description="Codex plugin control layer for codex-auto-resume.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup", help="prepare the runtime, enable auto resume and start the watcher")
    p.add_argument("--no-startup", action="store_true", help="do not register Windows sign-in autostart")
    p.add_argument("--replace-existing", action="store_true", help="take over an autostart registered by another installation")
    p.add_argument("--keep-state", action="store_true",
                   help="repair registrations only; never change the pause state or add a "
                        "sign-in autostart that is not already there")
    p.add_argument("--edition-from", choices=edition.EDITIONS, metavar="EDITION",
                   help="the edition the installer replaced (standard or advanced)")
    p.add_argument("--watcher-was-stopped", action="store_true",
                   help="with --keep-state: no watcher ran before the update, so it is started only where it "
                        "runs at sign-in")
    sub.add_parser("status")
    sub.add_parser("pending")
    sub.add_parser("enable")
    sub.add_parser("disable")
    p = sub.add_parser("cancel")
    p.add_argument("thread_id")
    sub.add_parser("stop")
    sub.add_parser("doctor")
    sub.add_parser("watcher-running", help="exit 0 only if this installation's watcher holds its mutex now")
    sub.add_parser("verify-home", help="exit 0 only if the install root is provably ours")
    sub.add_parser("claim-home",
                   help="exit 0 only if the install root is ours or holds nothing of ours")
    p = sub.add_parser("uninstall", help="remove the watcher, autostart and registrations")
    p.add_argument("--purge", action="store_true",
                   help="also delete settings, pending recoveries and logs")
    sub.add_parser("remove-entry", help="remove the Add or remove programs entry and the uninstaller kept for it")
    p = sub.add_parser("logs")
    p.add_argument("-n", "--lines", type=int, default=30)
    p = sub.add_parser("downgrade-state", help="convert the state for an older release (v0.6.0 to v0.6.14)")
    p.add_argument("--to", type=int, required=True, choices=[3, 4],
                   help="the schema to write: 4, what v0.6.11-beta to v0.6.14 read, or 3, what v0.6.0 to "
                        "v0.6.11-alpha read")
    p.add_argument("--stop-watcher", action="store_true",
                   help="ask a running watcher to stop and wait for it, at most a minute")
    return parser


COMMANDS = {
    "setup": cmd_setup, "status": cmd_status, "pending": cmd_pending, "enable": cmd_enable,
    "disable": cmd_disable, "cancel": cmd_cancel, "uninstall": cmd_uninstall,
    "verify-home": cmd_verify_home, "watcher-running": cmd_watcher_running,
    "claim-home": cmd_claim_home, "downgrade-state": cmd_downgrade_state, "remove-entry": cmd_remove_entry,
    "stop": passthrough("stop"), "doctor": passthrough("doctor"), "logs": passthrough("logs"),
}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")     # Korean output must survive a cp949 console.
        except (AttributeError, OSError):
            pass
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    # Remote debugging off (PEP 768) where whatever ran this did not say so: a published bootstrap runs setup as it
    # always has. What the product starts itself passes startup.NO_REMOTE_DEBUG, and this then does nothing.
    again = startup.again_without_remote_debug(__file__)
    sys.exit(main() if again is None else again)
