"""Paths and official-binary discovery. No network, no auth files, no Codex writes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_HOME = "CODEX_AUTO_RESUME_HOME"
ENV_CODEX_EXE = "CODEX_AUTO_RESUME_CODEX_EXE"
# Provenance marker: uninstall deletes ONLY inside a directory this tool created.
# Without it, a name match alone could remove a user file that merely shares the name.
OWNER_MARKER = ".owned-by-codex-auto-resume"
OWNER_TEXT = "Created by codex-auto-resume. Deleting this file makes `uninstall` skip this directory.\n"


class ConfigError(RuntimeError):
    """Static reason only; never includes file contents."""


class Paths:
    """All files this tool owns live under one root (default: the project directory)."""

    def __init__(self, home: str | os.PathLike | None = None):
        root = home or os.environ.get(ENV_HOME) or PROJECT_ROOT
        self.home = Path(root).expanduser().resolve()
        self.state_dir = self.home / "config"
        self.logs_dir = self.home / "logs"
        self.settings_file = self.state_dir / "settings.json"
        self.log_file = self.logs_dir / "auto-resume.log"
        self.error_log = self.logs_dir / "errors.log"
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

    # Owned files that uninstall may remove. A file is removable only if it is inside a
    # directory WE created (provenance marker), matches an owned name, is not a link, and
    # resolves inside the home. Anything else is never deleted.
    def owned_state_files(self) -> list[Path]:
        if not self.owns(self.state_dir):
            return []
        names = ["state.sqlite", "state.sqlite-journal", "state.sqlite-wal", "state.sqlite-shm", "settings.json"]
        files = [self.state_dir / name for name in names]
        files += [p for p in sorted(self.state_dir.glob("settings.*.tmp"))
                  if not p.is_symlink() and self.confined(p)]
        return files + [self.state_dir / OWNER_MARKER]

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


def version() -> str:
    """The product version, read from the plugin manifest.

    The manifest is the one place the version is written: the release archive is named
    from it, the release workflow refuses a tag that disagrees with it, and everything
    that displays a version reads it from here.
    """
    manifest = PROJECT_ROOT / ".codex-plugin" / "plugin.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "unknown")
    except (OSError, ValueError):
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
    for candidate in candidates:
        try:
            compatible(candidate)
        except Exception:
            continue
        usable.append(candidate)
    if len(usable) != 1:
        # Late import: report the pin that is actually in force, so bumping the pin
        # cannot leave this message quoting a stale version.
        from .windows import VERSION
        raise ConfigError("No codex.exe matching the verified engine pin (%s); "
                          "re-verify against the new version, then pass --codex-exe explicitly" % VERSION)
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
