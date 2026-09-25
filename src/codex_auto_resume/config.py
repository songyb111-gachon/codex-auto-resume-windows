"""Paths and official-binary discovery. No network, no auth files, no Codex writes."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re

# The plugin manifest, relative to the installation it describes. It is the one place the
# product version is written, and the one file every layout has at its root: a checkout, the
# installed `app/` directory, the release archive's payload and Codex's plugin cache.
PLUGIN_MANIFEST = Path(".codex-plugin") / "plugin.json"
# How many directories, starting with this module's own, are looked at for the manifest.
# Today it is two above this module; five leaves room for this file to move two packages
# deeper, which is more than any planned layout does.
ROOT_SEARCH_LEVELS = 5
# The top-level package this module belongs to: an installation's `src/` holds it.
_PACKAGE = __name__.partition(".")[0]


def _project_root(module: Path, levels: int = ROOT_SEARCH_LEVELS, package: str = _PACKAGE) -> Path:
    """The installation root: the nearest directory above `module` that holds the plugin
    manifest and whose `src/<package>/` holds `module`.

    This was `parents[2]`, a count that is only true while this file sits exactly one package
    below `src/`. Moved a level down, it named `src/` instead: the manifest was not found,
    `version()` swallowed the error and said "unknown" everywhere at once, and `Paths` put
    the default home and the entry script in the wrong place - without one test failing for
    the reason. Searching for the manifest finds the same directory wherever the module is.

    The second condition keeps the search to this installation. The root is the directory
    whose `src/` holds this package, so a directory further up that holds some other plugin's
    manifest is never taken for ours - not even one with a `src/` of its own somewhere above
    this file, as a copy of the sources kept inside another project's `src/` has. When nothing
    qualifies - a copy of the sources without a manifest - the answer is the old one,
    `parents[2]`, exactly as before.
    """
    for candidate in module.parents[:levels]:
        if (candidate / "src" / package) in module.parents and (candidate / PLUGIN_MANIFEST).is_file():
            return candidate
    return module.parents[2]


PROJECT_ROOT = _project_root(Path(__file__).resolve())
ENV_HOME = "CODEX_AUTO_RESUME_HOME"
ENV_CODEX_EXE = "CODEX_AUTO_RESUME_CODEX_EXE"
# Provenance marker: uninstall deletes ONLY inside a directory this tool created.
# Without it, a name match alone could remove a user file that merely shares the name.
OWNER_MARKER = ".owned-by-codex-auto-resume"
OWNER_TEXT = "Created by codex-auto-resume. Deleting this file makes `uninstall` skip this directory.\n"


class ConfigError(RuntimeError):
    """Static reason only; never includes file contents."""


def installed_home() -> str | None:
    """The runtime home of an installed copy: the directory above `app/`, which holds its
    state, settings and logs. None for a checkout, which is its own home (Paths decides).
    The bridge and the MCP server start with no --home and find theirs here."""
    return str(PROJECT_ROOT.parent) if PROJECT_ROOT.name == "app" else None


class Paths:
    """All files this tool owns live under one root (default: the project directory)."""

    def __init__(self, home: str | os.PathLike | None = None):
        root = home or os.environ.get(ENV_HOME) or PROJECT_ROOT
        self.home = Path(root).expanduser().resolve()
        self.state_dir = self.home / "config"
        self.logs_dir = self.home / "logs"
        self.settings_file = self.state_dir / "settings.json"
        # The Compatibility Registry's two files, both content-free. The report is derived
        # and has one writer, the watcher; the cache holds registry data a person asked
        # for, written only by the validator that imports it.
        self.compat_report_file = self.state_dir / "compatibility.json"
        self.compat_cache_file = self.state_dir / "compat-cache.json"
        # v0.6.8: when a person last saw a failure on the icon or the Dashboard (control.acknowledge_failure).
        self.failure_seen_file = self.state_dir / "failure-seen.json"
        # v0.6.11: the advanced edition's own state, in one directory of its own under config/,
        # carrying the same marker config/ does. Core never writes there and the standard edition
        # never creates it; it is named here only so a purge can take it (owned_state_files).
        self.advanced_dir = self.state_dir / "advanced"
        self.log_file = self.logs_dir / "auto-resume.log"
        self.error_log = self.logs_dir / "errors.log"
        # v0.6.9: one line each time Codex starts the MCP server and it considers starting the
        # watcher (control.start_for_codex). Trimmed, not rotated, like the launcher's launcher.log.
        self.codex_start_log = self.logs_dir / "codex-start.log"
        self.entry_script = PROJECT_ROOT / "src" / "auto_resume.py"
        # Kept in the runtime home, not the versioned plugin cache: Windows reads the
        # icon lazily when it draws a toast, long after an update may have moved us.
        self.icon_file = self.home / "codex-auto-resume.ico"

    def confined(self, path: Path) -> bool:
        """True only if, after resolving ALL reparse points (NTFS junctions
        included, which is_symlink() misses on Windows), the path stays in home."""
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return resolved == self.home or resolved.is_relative_to(self.home)

    def ensure(self) -> None:
        for directory in (self.state_dir, self.logs_dir):
            if directory.is_symlink() or (directory.exists() and not self.confined(directory)):
                raise ConfigError("Owned directory is a link/junction escaping the home; refusing")
            directory.mkdir(parents=True, exist_ok=True)
            if not self.confined(directory):
                raise ConfigError("Owned directory escapes the configured home; refusing")
            marker = directory / OWNER_MARKER
            try:
                if not marker.exists():
                    marker.write_text(OWNER_TEXT, encoding="utf-8")
            except OSError:
                pass    # A missing marker only makes uninstall MORE conservative.

    def owns(self, directory: Path) -> bool:
        """Uninstall may only delete inside a directory carrying our provenance marker."""
        marker = directory / OWNER_MARKER
        try:
            return (directory.is_dir() and self.confined(directory)
                    and marker.is_file() and not marker.is_symlink() and self.confined(marker))
        except OSError:
            return False

    def claim_home(self) -> bool:
        """Mark the installation root as ours. Called when the program files are put there.

        `ensure()` marks `config/` and `logs/` because those are the directories the
        *engine* creates. Nothing marked the root, and so nothing could vouch for the
        program directories beside it - which is why the PowerShell uninstaller had
        nothing to check before deleting `app/` and `runtime/`.

        Written at install time and never anywhere else. A marker created moments before
        a deletion, to make the deletion's own check pass, would be theatre.
        """
        try:
            if self.home.is_symlink() or not self.confined(self.home):
                return False
            self.home.mkdir(parents=True, exist_ok=True)
            marker = self.home / OWNER_MARKER
            if not marker.exists():
                marker.write_text(OWNER_TEXT, encoding="utf-8")
            return True
        except OSError:
            return False

    def owns_home(self) -> bool:
        """Whether this installation root is one we created.

        The gate on every destructive operation the installer performs: deleting `app/`
        and `runtime/`, sweeping `*.old-*`, and purging `config/` and `logs/`. The
        installation root can be pointed anywhere by an environment variable, so "it is
        named like ours" is not evidence and never was.

        Three ways to prove it, in descending order of strength:

        1. the root carries our marker - written by `claim_home()` at install time;
        2. `config/` carries one - every installation has had that since v0.1, so an
           installation made before the root marker existed still uninstalls;
        3. `runtime.json` names this very home - written by setup, and the only file
           here that says which installation it belongs to.

        Any of the three is enough; none of them is true of a directory that merely
        happens to contain folders called `app` and `runtime`.
        """
        try:
            if self.home.is_symlink() or not self.home.is_dir() or not self.confined(self.home):
                return False
        except OSError:
            return False
        if self.owns(self.home) or self.owns(self.state_dir):
            return True
        record = self.home / "runtime.json"
        try:
            if not record.is_file() or record.is_symlink() or not self.confined(record):
                return False
            declared = json.loads(record.read_text(encoding="utf-8")).get("home")
        except (OSError, ValueError, AttributeError):
            return False
        if not isinstance(declared, str) or not declared:
            return False
        try:
            return Path(declared).expanduser().resolve() == self.home
        except OSError:
            return False

    # Owned files that uninstall may remove. A file is removable only if it is inside a
    # directory WE created (provenance marker), matches an owned name, is not a link, and
    # resolves inside the home. Anything else is never deleted.
    def owned_state_files(self) -> list[Path]:
        if not self.owns(self.state_dir):
            return []
        names = ["state.sqlite", "state.sqlite-journal", "state.sqlite-wal", "state.sqlite-shm", "settings.json",
                 "compatibility.json", "compat-cache.json", "failure-seen.json"]
        files = [self.state_dir / name for name in names]
        for pattern in ("settings.*.tmp", "compatibility.*.tmp", "compat-cache.*.tmp", "failure-seen.*.tmp"):
            files += [p for p in sorted(self.state_dir.glob(pattern))
                      if not p.is_symlink() and self.confined(p)]
        return files + self.owned_advanced_files() + [self.state_dir / OWNER_MARKER]

    def owned_advanced_files(self) -> list[Path]:
        """What a purge takes from `advanced_dir`: every file directly in it, its marker last,
        and only while that marker is there.

        The one rule core has for the advanced edition's state, and a generic one. Core does
        not know that edition's files and must not spell them, so it cannot delete by name, as
        it does everywhere else; the marker is what vouches for them instead. It is written by
        the advanced edition when it makes the directory, and it says the whole directory is
        ours - so a directory without it, or one that is a link, or one whose files resolve
        outside the home, is left exactly as it is. Nothing below it is followed."""
        directory = self.advanced_dir
        try:
            if directory.is_symlink() or not self.owns(directory):
                return []
            found = [path for path in sorted(directory.iterdir())
                     if path.name != OWNER_MARKER and path.is_file() and not path.is_symlink()
                     and self.confined(path)]
        except OSError:
            return []
        return found + [directory / OWNER_MARKER]

    def owned_log_files(self) -> list[Path]:
        if not self.owns(self.logs_dir):
            return []
        result = []
        for path in sorted(self.logs_dir.iterdir()):
            name = path.name
            if (re.fullmatch(r"(auto-resume|errors)\.log(\.\d+)?", name)
                    and not path.is_symlink() and self.confined(path)):
                result.append(path)
        return result + [self.logs_dir / OWNER_MARKER]


def read_version(manifest: Path) -> str:
    """The version a plugin manifest declares, or `ConfigError` saying why it cannot be read.

    Strict: the file must be readable, JSON, an object, and carry a non-empty string
    `version`. The reason is one of a closed set of sentences and never quotes the file.
    """
    try:
        # utf-8-sig, not utf-8: a manifest saved by a Windows editor carries a BOM,
        # `json.loads` rejects it, and every version-bearing surface in the product
        # would then quietly say "unknown" together.
        raw = Path(manifest).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ConfigError("the plugin manifest is missing") from None
    except (OSError, ValueError):
        # ValueError: bytes that are not UTF-8.
        raise ConfigError("the plugin manifest could not be read") from None
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError):
        raise ConfigError("the plugin manifest is not JSON") from None
    if not isinstance(document, dict):
        raise ConfigError("the plugin manifest is not a JSON object") from None
    declared = document.get("version")
    if not isinstance(declared, str) or not declared.strip():
        raise ConfigError("the plugin manifest has no version string") from None
    return declared


# Each reason `version()` has logged in this process, so a watcher asking every tick says it once.
_reported: set = set()


def version() -> str:
    """The product version, read from the plugin manifest.

    The manifest is the one place the version is written: the release archive is named
    from it, the release workflow refuses a tag that disagrees with it, and everything
    that displays a version reads it from here.

    "unknown" in two cases, which used to be one. No manifest at the installation root is
    a copy of the sources with nothing to report, and says so quietly, as it always has. A
    manifest that is there but cannot be read as one - unreadable, not JSON, not an object,
    no version string - is a damaged installation, and it no longer passes silently: the
    reason from `read_version` is logged as a warning, once per process (into the watcher's
    log when one is set up, and to stderr otherwise), before the answer. The answer itself
    stays "unknown" rather than an exception, because the watcher writes this into its
    heartbeat every tick and several front ends show it, and a broken version string must
    never be the thing that stops recovery or a status read. `read_version` is the strict
    form, for anything that must not settle for "unknown".
    """
    manifest = PROJECT_ROOT / PLUGIN_MANIFEST
    if not manifest.exists():
        return "unknown"
    try:
        return read_version(manifest)
    except ConfigError as exc:
        reason = str(exc)
        if reason not in _reported:
            _reported.add(reason)
            logging.getLogger(__name__).warning("%s; the product version is shown as unknown",
                                                reason)
        return "unknown"


def codex_home() -> Path:
    value = os.environ.get("CODEX_HOME")
    if value:
        return Path(value).expanduser().resolve()
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return (Path(profile) / ".codex").resolve()


def codex_bin_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise ConfigError("LOCALAPPDATA is not set; cannot locate the official Codex binary")
    return Path(local) / "OpenAI" / "Codex" / "bin"


def candidate_codex_exes() -> list[Path]:
    bin_dir = codex_bin_dir()
    if not bin_dir.is_dir():
        return []
    found = []
    for child in sorted(bin_dir.iterdir()):
        if child.is_dir() and not child.is_symlink() and re.fullmatch(r"[0-9a-f]+", child.name):
            exe = child / "codex.exe"
            if exe.is_file() and not exe.is_symlink():
                found.append(exe.resolve())
    return found


def discover_codex_exe(explicit: str | os.PathLike | None, compatible) -> Path:
    """Return exactly one official codex.exe that passes ``compatible(path)``.

    ``compatible`` must raise on an unsupported binary. Ambiguity fails closed.
    """
    chosen = explicit or os.environ.get(ENV_CODEX_EXE)
    if chosen:
        path = Path(chosen).expanduser().resolve()
        if not path.is_file():
            raise ConfigError("Configured codex.exe does not exist")
        compatible(path)
        return path
    candidates = candidate_codex_exes()
    if not candidates:
        raise ConfigError("No official Codex desktop engine found under %LOCALAPPDATA%\\OpenAI\\Codex\\bin")
    usable = []
    failed = set()
    for candidate in candidates:
        try:
            compatible(candidate)
        except Exception as exc:
            # Only a reason code is kept - `AdapterError` carries nothing else - and anything
            # that is not shaped like one is not repeated.
            reason = str(exc)
            failed.add(reason if re.fullmatch(r"[a-z_]{1,48}", reason) else "check_failed")
            continue
        usable.append(candidate)
    if len(usable) > 1:
        raise ConfigError("%d official codex.exe builds pass the engine checks, so which one "
                          "to drive is ambiguous; pass --codex-exe explicitly" % len(usable))
    if not usable:
        # The check that failed, not a version pin: no version has been required to match
        # since v0.2.0, and the registry that replaced the pin never requires one either.
        raise ConfigError("No official codex.exe passed the engine checks (%s); the official "
                          "location, `codex --version` and `codex queue` offering --thread and "
                          "--message are required" % ", ".join(sorted(failed)))
    return usable[0]


def load_settings(paths: Paths) -> dict:
    """Read the user's settings.

    A thin adapter over the shared settings module, which owns the schema, the
    defaults, the validation and the file format. This used to be a second reader that
    understood three of the sixteen fields, and its matching writer persisted only
    those three - so changing the lookback from the command line silently erased every
    recovery category and notification preference set anywhere else. One reader and one
    writer is the point: there is no version of "partly authoritative" that is safe.
    """
    from . import settings as _settings
    return _settings.load(paths.settings_file)


def save_settings(paths: Paths, values: dict) -> dict:
    """Persist a complete settings mapping through the shared validator."""
    from . import settings as _settings
    paths.ensure()
    try:
        return _settings.save(paths.settings_file, values)
    except _settings.SettingsError as exc:
        raise ConfigError(str(exc)) from None


def update_settings(paths: Paths, changes: dict) -> dict:
    """Merge an explicit edit, leaving every field the caller did not name alone."""
    from . import settings as _settings
    paths.ensure()
    try:
        return _settings.update(paths.settings_file, changes)
    except _settings.SettingsError as exc:
        raise ConfigError(str(exc)) from None
