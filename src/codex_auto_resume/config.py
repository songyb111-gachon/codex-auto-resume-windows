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
MAX_SETTINGS_BYTES = 64 * 1024
LOOKBACK_HOURS_DEFAULT = 6.0
LOOKBACK_HOURS_MAX = 24 * 7
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
    """Optional user settings; malformed files are ignored, never rewritten."""
    defaults = {"detection_lookback_hours": LOOKBACK_HOURS_DEFAULT, "codex_exe": None}
    path = paths.settings_file
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_SETTINGS_BYTES:
            return defaults
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    hours = raw.get("detection_lookback_hours", defaults["detection_lookback_hours"])
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 <= hours <= LOOKBACK_HOURS_MAX:
        hours = defaults["detection_lookback_hours"]
    exe = raw.get("codex_exe")
    if not isinstance(exe, str) or not exe:
        exe = None
    return {"detection_lookback_hours": float(hours), "codex_exe": exe}


def save_settings(paths: Paths, settings: dict) -> None:
    paths.ensure()
    hours = settings.get("detection_lookback_hours", LOOKBACK_HOURS_DEFAULT)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 <= hours <= LOOKBACK_HOURS_MAX:
        raise ConfigError("detection_lookback_hours must be between 0 and %d" % LOOKBACK_HOURS_MAX)
    exe = settings.get("codex_exe")
    if exe is not None and (not isinstance(exe, str) or not exe):
        raise ConfigError("codex_exe must be a non-empty path or null")
    payload = {"detection_lookback_hours": float(hours), "codex_exe": exe}
    # mkstemp creates a uniquely named file with O_EXCL, so a pre-planted symlink at a
    # predictable temp path cannot be followed, and concurrent writers never collide.
    descriptor, temporary_name = tempfile.mkstemp(dir=str(paths.state_dir), prefix="settings.", suffix=".json.tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        os.replace(temporary, paths.settings_file)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ConfigError("Cannot save settings") from exc
