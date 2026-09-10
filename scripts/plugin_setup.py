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
RUNTIME_DIR_NAME = ".codex-auto-resume"
MIN_PYTHON = (3, 12)
CHECK = "✓"
EXIT_OK = 0
EXIT_ERROR = 1

sys.path.insert(0, str(PLUGIN_ROOT / "src"))
from codex_auto_resume import config, messages, startup      # noqa: E402
from codex_auto_resume.app import App                        # noqa: E402


def say(key: str) -> None:
    print(messages.text(key))


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
    """
    runtime = home / "runtime"
    if windowless:
        launcher = runtime / "pythonw.exe"
        if launcher.is_file():
            return launcher
    executable = runtime / "python.exe"
    return executable if executable.is_file() else None


def installed(home: Path) -> bool:
    """A complete installation: the bundled runtime and the application beside it."""
    return (bundled_python(home, windowless=False) is not None
            and (home / "app" / "src" / "codex_auto_resume").is_dir())


def python_for_watcher(home: Path | None = None) -> Path:
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
    (home / RUNTIME_CONFIG).write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
    argv = [str(python_for_watcher(home)), str(home / LAUNCHER_NAME), "activate"]
    return " ".join(startup.quote_argument(argument) for argument in argv) + ' "%1"'


def start_watcher(home: Path) -> bool:
    """Launch the watcher detached, so it outlives this command and the Codex UI."""
    app = App(config.Paths(home), console=False, enable_logging=False)
    if app.watcher_running() is not False:
        return False
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(python_for_watcher(home)), str(home / LAUNCHER_NAME), "run"],
                     cwd=str(home), close_fds=True, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


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
    _cli_silent(home, ["--quiet", "install"])
    _cli_silent(home, ["--quiet", "enable"])
    if not args.no_startup:
        startup.install(watcher_command(home))
    # `install` above registered the protocol against the plugin's own versioned path;
    # replace it with the stable launcher so an update cannot orphan the button.
    try:
        startup.install_protocol(notification_command(home))
    except startup.StartupError:
        pass
    start_watcher(home)
    say("ready_title")
    print()
    say("ready_defaults")
    for key in ("ready_b1", "ready_b2", "ready_b3", "ready_b4"):
        print("  " + bullet() + " " + messages.text(key))
    print()
    say("setup_done")
    if not args.no_startup:
        say("setup_autostart")
    print()
    print("state: %s" % home)
    return EXIT_OK


def cmd_enable(args) -> int:
    home = runtime_home()
    code = _cli_silent(home, ["--quiet", "enable"])
    start_watcher(home)
    say("enabled")
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


def cmd_uninstall(args) -> int:
    home = runtime_home()
    # Keeping settings and pending recoveries is the default here: the installer offers a
    # separate purge for the other case, and losing a queued recovery to an ordinary
    # uninstall is not something a user would expect or forgive.
    flags = [] if getattr(args, "purge", False) else ["--keep-state"]
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
    sub.add_parser("status")
    sub.add_parser("pending")
    sub.add_parser("enable")
    sub.add_parser("disable")
    p = sub.add_parser("cancel")
    p.add_argument("thread_id")
    sub.add_parser("stop")
    sub.add_parser("doctor")
    sub.add_parser("verify-home", help="exit 0 only if the install root is provably ours")
    p = sub.add_parser("uninstall", help="remove the watcher, autostart and registrations")
    p.add_argument("--purge", action="store_true",
                   help="also delete settings, pending recoveries and logs")
    p = sub.add_parser("logs")
    p.add_argument("-n", "--lines", type=int, default=30)
    return parser


COMMANDS = {
    "setup": cmd_setup, "status": cmd_status, "pending": cmd_pending, "enable": cmd_enable,
    "disable": cmd_disable, "cancel": cmd_cancel, "uninstall": cmd_uninstall,
    "verify-home": cmd_verify_home,
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
    sys.exit(main())
