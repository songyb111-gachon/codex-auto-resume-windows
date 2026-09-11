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
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

CONFIG_NAME = "runtime.json"
# The marketplace names this product is published under. See resolve_plugin_root.
OUR_MARKETPLACES = frozenset({"codex-auto-resume-windows"})
EXIT_ERROR = 1


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
    return cli_main(["--home", str(home), "--quiet"] + command)


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
