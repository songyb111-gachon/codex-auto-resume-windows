"""What an executable in build/ was built from, written beside it and checked before it is packed.

build/make_gui.ps1 compiles the settings window (one per edition) and the MCP launcher into
build/ and build/advanced/. build/make_release.py packs whatever is there. A local candidate built
without rebuilding first would ship the previous window inside an archive named for the new
version (2026-11-12: build/advanced/ held 0.6.22 beside a 0.6.23 tree). So make_gui.ps1 leaves a
stamp beside each executable - `<name>.exe.stamp`, one JSON object - holding

* the version plugin.json declared, and
* a SHA-256 over everything the build reads: the sources it compiled (gui/window.sources and the
  advanced overlay's list, and the files they name, or the launcher's two), the manifest and icon
  compiled in, the two build scripts, and the three plugin.json fields the version resource is
  made of.

and `check` refuses an executable whose stamp is missing, or names another version, or another
digest than the tree holds now. It is a check on the tree being packed, not on the compiler:
CI builds the executables and packs them in one job, so the stamp always matches there.

    python build/gui_stamp.py write --root ROOT --edition standard|advanced --kind window|launcher EXE
    python build/gui_stamp.py check --root ROOT --edition standard|advanced --kind window|launcher EXE
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

STAMP_SUFFIX = ".stamp"
LAUNCHER_SOURCES = ("gui/McpLauncher.cs", "gui/RuntimeChoice.cs")
# Fixed inputs of every executable: the manifest and icon compiled into the window (the icon into
# the launcher too), and the two scripts that decide the bytes.
BUILD_SCRIPTS = ("build/make_gui.ps1", "build/normalize_pe.py")
ICON = "assets/codex-auto-resume.ico"
MANIFEST = "gui/app.manifest"


class StaleBuild(Exception):
    """The executable is not the one this tree builds."""


def stamp_path(exe: Path) -> Path:
    return Path(exe).with_name(Path(exe).name + STAMP_SUFFIX)


def _source_list(root: Path, list_file: str) -> list:
    """The sources a list names, as make_gui.ps1's Read-SourceList reads it: text after # is a
    comment, a [group] line divides the file for the tests and means nothing to the compiler."""
    names = []
    for line in (root / list_file).read_text(encoding="utf-8-sig").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry and not entry.startswith("["):
            names.append(entry)
    return names


def inputs(root: Path, edition: str, kind: str) -> list:
    """Every file the build reads, as root-relative names in the order the compiler takes them."""
    if kind == "launcher":
        names = list(LAUNCHER_SOURCES) + [ICON]
    elif kind == "window":
        names = ["gui/window.sources"] + _source_list(root, "gui/window.sources")
        if edition == "advanced":
            names += ["advanced/gui/window.sources"] + _source_list(root, "advanced/gui/window.sources")
        names += [MANIFEST, ICON]
    else:
        raise ValueError("kind is window or launcher, not %r" % kind)
    return names + list(BUILD_SCRIPTS)


def describe(root: Path, edition: str, kind: str) -> dict:
    """The stamp this tree would give an executable of that kind and edition."""
    root = Path(root)
    if kind == "launcher":
        edition = "standard"           # one file in both editions, built by the standard run only
    manifest = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
    digest = hashlib.sha256()
    # The version resource is a pure function of these three fields (make_gui.ps1).
    for field in (manifest.get("version"), (manifest.get("author") or {}).get("name"),
                  (manifest.get("interface") or {}).get("displayName")):
        digest.update(("%s\0" % field).encode("utf-8"))
    digest.update(("%s\0%s\0" % (edition, kind)).encode("utf-8"))
    for name in inputs(root, edition, kind):
        path = root / name
        if not path.is_file():
            raise SystemExit("%s is missing: the executable cannot be stamped for this tree" % name)
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {"version": str(manifest.get("version")), "sources": digest.hexdigest()}


def write(exe: Path, root: Path, edition: str, kind: str) -> dict:
    stamp = describe(root, edition, kind)
    stamp_path(exe).write_text(json.dumps(stamp, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return stamp


def rebuild_command(edition: str, kind: str) -> str:
    """What makes the executable again; the launcher is built by the standard run only."""
    if kind == "launcher" or edition == "standard":
        return "powershell -File build/make_gui.ps1"
    return "powershell -File build/make_gui.ps1 -Edition %s" % edition


def check(exe: Path, root: Path, edition: str, kind: str) -> None:
    """Raise StaleBuild, naming the executable and the command that rebuilds it, unless the stamp
    beside it is the one this tree gives."""
    exe = Path(exe)
    command = rebuild_command(edition, kind)
    where = "%s is stale" % exe
    try:
        recorded = json.loads(stamp_path(exe).read_text(encoding="utf-8"))
        if not isinstance(recorded, dict):
            raise ValueError("not an object")
    except FileNotFoundError:
        raise StaleBuild("%s: it has no build stamp (%s), so it is not known to match this tree - "
                         "run %s first" % (where, stamp_path(exe).name, command))
    except (OSError, ValueError) as exc:
        raise StaleBuild("%s: its build stamp %s cannot be read (%s) - run %s first"
                         % (where, stamp_path(exe).name, exc, command))
    now = describe(root, edition, kind)
    if recorded.get("version") != now["version"]:
        raise StaleBuild("%s: it was built for %s and this tree is %s - run %s first"
                         % (where, recorded.get("version"), now["version"], command))
    if recorded.get("sources") != now["sources"]:
        raise StaleBuild("%s: its sources, manifest or build scripts changed after it was built "
                         "(both are %s) - run %s first" % (where, now["version"], command))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=("write", "check"))
    parser.add_argument("exe")
    parser.add_argument("--root", required=True)
    parser.add_argument("--edition", choices=("standard", "advanced"), default="standard")
    parser.add_argument("--kind", choices=("window", "launcher"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "write":
            write(Path(args.exe), Path(args.root), args.edition, args.kind)
        else:
            check(Path(args.exe), Path(args.root), args.edition, args.kind)
    except StaleBuild as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
