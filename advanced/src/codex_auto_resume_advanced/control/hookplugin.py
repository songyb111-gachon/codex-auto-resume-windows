# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Continue inside the turn (stop_hook_continuation, v0.6.20): the Stop hook's declaration, written into this
product's own plugin copies while the capability is on, and removed the moment it is not (D-stop-hook.md).

Where: this plugin's roots and no other file - the installation's own (`<home>/app`, the marketplace Codex was given)
and each advanced copy Codex keeps of this plugin (`<CODEX_HOME>/plugins/cache/<marketplace>/<plugin>/<version>`), as
the format names them (hook/format.py, FORMAT.roots). Never Codex's config.toml, never another plugin's files, never
a path that leaves its root or runs through a link. Codex's own hook-trust prompt gates what is written; nothing here
bypasses it, and nothing in this edition names a way to (advanced/tests/test_advanced_hook_decl.py).

When: `follow` makes the files match the capability's stored state - written while it is on (at arming, and again at
each tick while on, so a Repair that replaced the plugin's files gets it back), removed when it is off (a person's
turn-off, every capability off, an edition change, a tripwire). Uninstalling takes the installation's root away with
the program files, and Codex's copy with `codex plugin remove`.

What: the document format.declaration builds, its command the hook launcher (gui/HookLauncher.cs) - its absolute path
in the installation's home, or its path inside the plugin, as FORMAT.command says. A declaration file is removed only
when every command in it is one of ours; one a person or another tool wrote is left as it is.

The one write is `WRITER` (`write_declaration`), and the one removal `REMOVER` - the seam a test replaces, and the
place MHK's verdict about how Codex reads a declaration changes nothing but FORMAT.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from codex_auto_resume import config
from codex_auto_resume.edition import MARKETPLACE, PLUGIN

from ..hook.format import FORMAT, commands_in, declaration

CAPABILITY = "stop_hook_continuation"
HOOK_DIR = "hook"
HOOK_EXE = "codex-auto-resume-hook.exe"
MANIFEST = (".codex-plugin", "plugin.json")
ADVANCED_PACKAGE = ("src", "codex_auto_resume_advanced")


def launcher(paths) -> Path:
    """The hook launcher in the installation's home: where the advanced archive puts it."""
    return Path(paths.home) / "app" / HOOK_DIR / HOOK_EXE


def _linked(path, root) -> bool:
    """Whether `path`, or any folder between it and `root`, is a link or a junction."""
    try:
        current = Path(path)
        while True:
            if current.exists() and config.is_link(current):
                return True
            if current == Path(root) or current.parent == current:
                return False
            current = current.parent
    except OSError:
        return True


def _plugin_root(folder) -> bool:
    try:
        return (folder.is_dir() and not config.is_link(folder)
                and folder.joinpath(*MANIFEST).is_file() and folder.joinpath(*ADVANCED_PACKAGE).is_dir())
    except OSError:
        return False


def roots(paths, codex_home, found=FORMAT) -> list:
    """This plugin's advanced roots that exist, as FORMAT.roots names them."""
    found_roots = []
    if "installation" in found.roots:
        installation = Path(paths.home) / "app"
        if _plugin_root(installation):
            found_roots.append(installation)
    if "codex_copy" in found.roots and codex_home is not None:
        cache = Path(codex_home) / "plugins" / "cache" / MARKETPLACE / PLUGIN
        try:
            copies = sorted(entry for entry in cache.iterdir() if _plugin_root(entry)) if (
                cache.is_dir() and not _linked(cache, codex_home)) else []
        except OSError:
            copies = []
        found_roots += copies
    return found_roots


def command(paths, found=FORMAT) -> str:
    """The command the declaration runs."""
    if found.command == "contained":
        return "./%s/%s" % (HOOK_DIR, HOOK_EXE)
    return str(launcher(paths))


def ours(paths, found=FORMAT) -> set:
    """Every command a declaration of ours may run: the launcher's absolute path, and its path inside the plugin."""
    return {str(launcher(paths)), "./%s/%s" % (HOOK_DIR, HOOK_EXE)}


def target(root, found=FORMAT) -> Path | None:
    """The declaration file under `root`, or None where it would leave the root or run through a link."""
    path = Path(root).joinpath(*found.file)
    try:
        resolved_root = Path(root).resolve()
        if not path.resolve().is_relative_to(resolved_root) or _linked(path, root):
            return None
    except (OSError, ValueError):
        return None
    return path


def write_declaration(path, document) -> None:
    """The one write: `document` as UTF-8 JSON at `path`, whole or not at all (a temporary file beside it, replaced)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def remove_declaration(path) -> None:
    """The one removal: the file at `path`, and its folder if that is left empty."""
    path = Path(path)
    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass


WRITER = write_declaration
REMOVER = remove_declaration


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def _manifest(root, found, present) -> None:
    """The manifest's key for the declaration, where FORMAT names one: set while it is on, taken out when it is off."""
    if found.manifest_key is None:
        return
    path = Path(root).joinpath(*MANIFEST)
    manifest = _read(path)
    if not isinstance(manifest, dict):
        return
    wanted = "./" + "/".join(found.file)
    if present and manifest.get(found.manifest_key) != wanted:
        manifest[found.manifest_key] = wanted
    elif not present and manifest.get(found.manifest_key) == wanted:
        del manifest[found.manifest_key]
    else:
        return
    WRITER(path, manifest)


def write(paths, codex_home, found=FORMAT) -> int:
    """The declaration written into every root where it is not already as it should be: how many were written."""
    document = declaration(command(paths, found), found)
    written = 0
    for root in roots(paths, codex_home, found):
        path = target(root, found)
        if path is None or _read(path) == document:
            continue
        current = _read(path) if path.exists() else None
        if path.exists() and not _removable(current, paths, found):
            continue                                  # someone else's file: never ours to replace
        WRITER(path, document)
        _manifest(root, found, True)
        written += 1
    return written


def _removable(document, paths, found) -> bool:
    commands = commands_in(document, found)
    return bool(commands) and set(commands) <= ours(paths, found)


def remove(paths, codex_home, found=FORMAT) -> int:
    """Every declaration of ours removed from every root: how many were."""
    removed = 0
    for root in roots(paths, codex_home, found):
        path = target(root, found)
        if path is None or not path.is_file() or not _removable(_read(path), paths, found):
            continue
        REMOVER(path)
        _manifest(root, found, False)
        removed += 1
    return removed


def present(paths, codex_home, found=FORMAT) -> bool:
    """Whether a declaration of ours stands in any root."""
    for root in roots(paths, codex_home, found):
        path = target(root, found)
        if path is not None and path.is_file() and _removable(_read(path), paths, found):
            return True
    return False


def follow(paths, codex_home, armed, found=FORMAT) -> int:
    """The declarations made to match the capability: written while `armed`, removed otherwise. Never raises."""
    try:
        return write(paths, codex_home, found) if armed is True else remove(paths, codex_home, found)
    except Exception:
        return 0
