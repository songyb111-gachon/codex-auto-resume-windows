"""Derive build/runtime_keep.json for another Python's embeddable zip: the list the build trims the bundled runtime to.

    python build/runtime_keep.py <python-X.Y.Z-embed-amd64.zip> --python X.Y.Z --sha256 <digest> --out <file>

Not shipped, and never run by a build: a person runs it on the day the bundled Python moves (docs/DEVELOPMENT.md says what
else changes that day), reads what it prints and copies its file over build/runtime_keep.json. It writes only --out.

What it can decide, it decides from the runtime itself:
  files     the committed list, each pythonXY name renamed for this version;
  library   the committed members this zip still has, what any import statement of the shipped code names, and whatever
            the shipped modules then fail for lack of, found by importing them under the runtime trimmed to the list and
            adding what is missing until nothing is;
  reviewed  the committed reasons for the imports that still exist, renamed the same way.
What it cannot decide is why an import of a module that went cannot run: such an import is printed under "to read", nothing
is invented for it, and the exit code is 3. The build's own check (build/runtime_check.py) stops on it until a reason is
written, as it stops on an entry here that no import matches any more.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
KEEP = BUILD / "runtime_keep.json"
_TAG = re.compile(r"python3\d+")
_ABSENT = re.compile(r"No module named '([^']+)'")
# More than any new Python has needed, and short of forever if a module keeps failing the same way.
_ROUNDS = 40


def tag_of(version: str) -> str:
    """python315 for 3.15.2: how a runtime's own files are named."""
    return "python" + "".join(version.split(".")[:2])


def renamed(old: str, new_tag: str) -> str:
    return _TAG.sub(new_tag, old)


def inside(asked_path: str) -> int:
    """Under the trimmed runtime: the modules the shipped ones fail for lack of, and the imports of what went."""
    asked = json.loads(Path(asked_path).read_text(encoding="utf-8"))
    sys.path.insert(0, asked["build"])
    import importlib
    import runtime_check
    trees = [Path(path) for path in asked["trees"]]
    sys.addaudithook(runtime_check._no_effects)
    sys.path[:0] = [str(tree) for tree in trees]
    missing, failed = set(), []
    for name in [name for tree in trees for name in runtime_check.module_names(tree)]:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            missing.add(exc.name or name)
            failed.append("%s: %s" % (name, exc))
        except BaseException as exc:    # noqa: BLE001 - a SystemExit at import is as much a failure as an ImportError
            failed.append("%s: %s: %s" % (name, type(exc).__name__, exc))
    edges = sorted(runtime_check.library_edges(asked["library"], set(asked["removed"])))
    Path(asked["answer"]).write_text(json.dumps({"missing": sorted(missing), "failed": failed, "edges": edges}), encoding="utf-8")
    sys.stdout.flush()
    os._exit(0)


def _shipped_files() -> list:
    """The Python files a release carries, by the build's own lists, and the smoke test the release runs under them."""
    sys.path.insert(0, str(BUILD))
    import make_release
    scripts = make_release.LISTED_TREES["scripts"]
    return (sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "advanced" / "src").rglob("*.py"))
            + [ROOT / "scripts" / name for name in scripts if name.endswith(".py")] + [BUILD / "smoke_archive.py"])


def _named_by_shipped(members) -> set:
    """Each member of the runtime's library that an import statement of the shipped code names: runtime_check stops on
    any it finds gone, however guarded."""
    sys.path.insert(0, str(BUILD))
    import runtime_check
    wanted = set()
    for path in _shipped_files():
        for name in runtime_check.statements(path.read_text(encoding="utf-8")):
            wanted |= _member_of(name, members)
    return wanted


def _member_of(name: str, members) -> set:
    """The one member a module's name is, and each package above it, which an import loads first."""
    found, parts = set(), name.split(".")
    for count in range(1, len(parts) + 1):
        path = "/".join(parts[:count])
        found |= {member for member in (path + ".pyc", path + "/__init__.pyc") if member in members}
    return found


def _modules_of(members) -> list:
    names = [member[:-len(".pyc")].replace("/", ".") for member in members if member.endswith(".pyc")]
    return [name[:-len(".__init__")] if name.endswith(".__init__") else name for name in names]


def _trim(full: Path, library: Path, wanted) -> None:
    with zipfile.ZipFile(full) as whole, zipfile.ZipFile(library, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as kept:
        for info in whole.infolist():
            if info.filename in wanted:
                kept.writestr(info, whole.read(info))


def derive(archive: Path, version: str, digest: str, out: Path) -> int:
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != digest.lower():
        raise SystemExit("%s has the digest %s, not the one given (%s): nothing was derived" % (archive, actual, digest))
    old = json.loads(KEEP.read_text(encoding="utf-8"))
    tag = tag_of(version)
    library_zip = renamed(old["library_zip"], tag)
    files = [renamed(name, tag) for name in old["files"]]
    with tempfile.TemporaryDirectory(prefix="car-runtime-keep-") as scratch:
        work = Path(scratch)
        runtime = work / "runtime"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(runtime)
        present = {path.name for path in runtime.iterdir()}
        missing = sorted(set(files) - present)
        dropped = sorted(present - set(files))
        full = work / "full.zip"
        (runtime / library_zip).replace(full)
        for name in dropped:
            (runtime / name).unlink()
        with zipfile.ZipFile(full) as bundle:
            members = {info.filename for info in bundle.infolist()}
        kept_before = set(old["library"]) & members
        wanted = kept_before | _named_by_shipped(members)
        home = work / "home"
        home.mkdir()
        environment = {name: value for name, value in os.environ.items() if name.upper() != "PYTHONPATH"}
        environment.update({name: str(home) for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "CODEX_HOME")})
        shipped = work / "shipped"
        (shipped / "scripts").mkdir(parents=True)
        sys.path.insert(0, str(BUILD))
        import make_release
        for name in make_release.LISTED_TREES["scripts"]:
            if name.endswith(".py"):
                (shipped / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
        trees = [str(ROOT / "src"), str(ROOT / "advanced" / "src"), str(shipped / "scripts")]
        for _round in range(_ROUNDS):
            _trim(full, runtime / library_zip, wanted)
            removed = _modules_of(members - wanted) + [name[:-len(".pyd")] for name in dropped if name.endswith(".pyd")]
            asked = {"build": str(BUILD), "trees": trees, "library": str(runtime / library_zip), "removed": removed,
                     "answer": str(work / "answer.json")}
            (work / "asked.json").write_text(json.dumps(asked), encoding="utf-8")
            done = subprocess.run([str(runtime / "python.exe"), "-B", "-X", "disable-remote-debug", str(Path(__file__).resolve()),
                                   "--inside", str(work / "asked.json")], cwd=scratch, env=environment, stdin=subprocess.DEVNULL,
                                  capture_output=True, encoding="utf-8", errors="replace", timeout=600,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            absent = _ABSENT.findall(done.stderr) if done.returncode != 0 else []
            if absent and set().union(*[_member_of(name, members) for name in absent]) - wanted:
                # A module of the standard library itself that needs another: the interpreter could not get as far as asking.
                wanted |= set().union(*[_member_of(name, members) for name in absent])
                continue
            if done.returncode != 0 or not (work / "answer.json").is_file():
                raise SystemExit("the runtime could not be asked (exit %s):\n%s\n%s" % (done.returncode, done.stdout[-3000:], done.stderr[-3000:]))
            answer = json.loads((work / "answer.json").read_text(encoding="utf-8"))
            added = set().union(*[_member_of(name, members) for name in answer["missing"]], set()) - wanted
            if not added:
                break
            wanted |= added
    edges = [tuple(edge) for edge in answer["edges"]]
    reviewed, unmatched = {}, []

    def covered(key, edge):
        importer, _arrow, target = key.partition(" -> ")
        return edge[0] == importer and (edge[1] == target or edge[1].startswith(target + "."))

    for key, reason in old["reviewed"].items():
        if any(covered(key, edge) for edge in edges):
            reviewed[key] = renamed(reason, tag)
        else:
            unmatched.append(key)
    to_read = ["%s -> %s" % edge for edge in edges if not any(covered(key, edge) for key in reviewed)]
    made = dict(old, python=version, sha256=actual, library_zip=library_zip, files=files, library=sorted(wanted), reviewed=reviewed)
    out.write_text(json.dumps(made, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for title, lines in (("files the committed list names and this runtime does not have", missing),
                         ("files of this runtime that go", dropped),
                         ("members the committed list names and this zip does not have", sorted(set(old["library"]) - members)),
                         ("members added", sorted(wanted - kept_before)),
                         ("shipped modules that do not import under the list", answer["failed"]),
                         ("reviewed entries no import matches any more (left out)", unmatched),
                         ("to read: imports of a module that went, with no reason written yet", to_read)):
        print("%s: %d" % (title, len(lines)))
        for line in lines:
            print("    " + line)
    print("%d members of %s kept, %d reasons carried over; written to %s" % (len(wanted), library_zip, len(reviewed), out))
    return 3 if missing or answer["failed"] or to_read else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archive", nargs="?")
    parser.add_argument("--python")
    parser.add_argument("--sha256")
    parser.add_argument("--out")
    parser.add_argument("--inside", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inside:
        return inside(args.inside)
    if not (args.archive and args.python and args.sha256 and args.out):
        parser.error("give the archive, --python, --sha256 and --out")
    return derive(Path(args.archive), args.python, args.sha256, Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
