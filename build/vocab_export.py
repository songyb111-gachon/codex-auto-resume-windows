"""Write `vocab.json`: every closed vocabulary the product's behaviour and wire depend on, from one commit.

A port of the core has to write exactly these strings: a record's state, a journal event, a public code,
a reason, a gate, a failure category, a refusal, a setting's key and its choices, a bridge command, an MCP
tool, a registry state. Python holds each as an `enum.StrEnum` or as a word list in a module's body.
This reads them out of a tree of a given tag or commit - never out of a working tree - so a Rust crate can
be generated from them and held to them both ways (docs/ROADMAP.md, the v0.6.27 port; the reference is the
v0.6.26 tag, and only it).

    python build/vocab_export.py --ref v0.6.26-beta.2 [--out vocab.json] [--advanced]

* The tree is taken out of git into a scratch folder - `git archive`, read in memory, extracted there -
  and imported from there by a child run as `python -I -B` with a scratch home. Nothing is checked out,
  no worktree is touched, no file is written under the repository, and the scratch folder is removed.
* What is exported, from every module of the package except the Windows interface and the
  registrations (EXCLUDED_*): each `enum.Enum` the module defines, its members in definition order
  (aliases included); and each public UPPER_CASE constant the module assigns whose value is a string,
  or a tuple, list, set, frozenset or dict made of strings only, none longer than 64 characters or
  spanning lines, none a version. A tuple or list keeps its order, a dict written out in the source keeps
  its order, and a set - or a dict built by code, whose order is that of a set it iterated - is sorted. Numbers are
  not vocabulary (a limit is a tuning, pinned by its test) and are left out. Beside them, `tables`: the
  settings' keys in the order the schema has them with each one's type, and the interruption categories
  with what the product says of each.
* The advanced edition is kept apart: its vocabularies go to a second file, `<out stem>-advanced.json`,
  written only with `--advanced`, by a child that is the only one to put `advanced/src` on its path. The
  standard child never imports the package, and a core constant that spells the advanced edition's package,
  skill or sentinel (`edition.ADVANCED_PACKAGE`) is moved out of the standard file into the advanced one
  (`core_edition`): a Rust standard build generated from this file must not hold what the edition audit
  (build/edition_audit.py, (c) and (g)) looks for. tests/test_vocab_export.py runs the audit's own name
  check over the standard file.
* Deterministic: modules sorted by name, enum members and constants in source order, sets sorted, JSON
  with two-space indent and LF. It carries no ref, commit, version or time, so the same vocabularies give
  the same bytes whichever tag they were read from; what was read is printed on stderr.

This file is a tool of the repository: build/ ships in neither archive.
"""
from __future__ import annotations

import argparse
import ast
import enum
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "codex-auto-resume/vocab/1"
CORE = "codex_auto_resume"
ADVANCED = "codex_auto_resume_advanced"
# What every shipped advanced file begins with, and the advanced skill: spelled by no standard output.
SKILL = "codex-auto-resume-advanced"
SENTINEL = "ADVANCED-EDITION-CODE"
SECRET_NAMES = (ADVANCED, SKILL, SENTINEL)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# The Windows interface, drawn by the C# side, and what only registers or draws: no closed vocabulary of
# the behaviour or the wire. `win` holds the platform calls (their object names have their own tests),
# `brand` the palette, `ui` the icon, the popup and the card.
EXCLUDED_PACKAGES = ("brand", "ui", "win")
EXCLUDED_MODULES = ("addremove", "shortcut", "startup", "pwsh", "tray_place", "notifier", "notify", "notice_card",
                    "notice_presence", "notice_uris", "notice_inbox", "notice_window", "codex_link",
                    "chosen_runtime", "messages", "interface")
# The advanced tree's tools a person runs by hand from a checkout (docs/evidence), not behaviour; the
# statements' catalog keys (the words family compares every key in every language) and the build-time
# table of measurements (data, with engine versions in it). `__main__` modules are left out too:
# importing one would start it.
ADVANCED_EXCLUDED_PACKAGES = ("win",)
ADVANCED_EXCLUDED_MODULES = ("measure", "evidence", "statement", "measured")

MAX_LENGTH = 64
_VERSION = re.compile(r"v?\d+\.\d+\.\d+([-+.][0-9A-Za-z.]+)*\Z")


class Skip(Exception):
    """A value that is not a closed word list."""


# ------------------------------------------------------------------------------ the child's side
def _leaf(value: str) -> str:
    if len(value) > MAX_LENGTH or "\n" in value or "\r" in value or _VERSION.match(value):
        raise Skip
    return str(value)


def _written_out(node) -> bool:
    """Whether the source writes this dict out, key by key: the only dict whose order is the source's."""
    return isinstance(node, ast.Dict) and None not in node.keys


def _part(node, index, size):
    """The source node of a literal's `index`th item, or None where the value is not written out
    (or has more or fewer items than the literal: a repeated key collapses)."""
    if isinstance(node, ast.Dict) and None not in node.keys and len(node.values) == size:
        return node.values[index]
    if (isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) == size
            and not any(isinstance(item, ast.Starred) for item in node.elts)):
        return node.elts[index]
    return None


def encode(value, node=None):
    """A constant as JSON, or Skip. Strings only, whatever the nesting.

    A tuple or list keeps its order. A set is sorted. A dict keeps its order only where the source writes
    it out (`node`, its source, is a dict literal with no `**`); a dict built by code - `{state: ... for state
    in WAITING}`, which iterates a set - has the order of whatever it iterated, which changes from one run to
    the next (hash randomisation, which `python -I` keeps on), so its keys are sorted."""
    if isinstance(value, enum.Enum):
        value = value.value
    if isinstance(value, str):
        return _leaf(value)
    if isinstance(value, (tuple, list)):
        return [encode(item, _part(node, index, len(value))) for index, item in enumerate(value)]
    if isinstance(value, (set, frozenset)):
        return sorted((encode(item) for item in value), key=lambda item: json.dumps(item, ensure_ascii=False))
    if isinstance(value, dict):
        keys = [encode(key) for key in value]
        items = [(key, encode(item, _part(node, index, len(value))))
                 for index, (key, item) in enumerate(zip(keys, value.values()))]
        if not (_written_out(node) and len(node.values) == len(value)):
            items.sort(key=lambda pair: json.dumps(pair[0], ensure_ascii=False))
        if all(isinstance(key, str) for key in keys) and len(set(keys)) == len(keys):
            return dict(items)
        return {"pairs": [list(pair) for pair in items]}
    raise Skip


def _member(value):
    """An enum member's value: a string or a number as it is, anything else as the string it prints."""
    if isinstance(value, enum.Enum):
        value = value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return str(value) if isinstance(value, str) else value
    return str(value)


def _base(cls) -> str:
    for base in cls.__mro__:
        if base.__module__ == "enum" and base.__name__ != "Enum" and base.__name__ in (
                "StrEnum", "IntEnum", "IntFlag", "Flag", "ReprEnum"):
            return base.__name__
    return "Enum"


def module_names(source: Path, package: str, excluded_packages, excluded_modules) -> list:
    """Every module of a package tree, as (dotted name below the package, file), sorted by name."""
    base = source / package
    found = []
    for path in sorted(base.rglob("*.py")):
        parts = list(path.relative_to(base).with_suffix("").parts)
        if parts[-1] == "__main__":
            continue
        if parts[-1] == "__init__":
            parts.pop()
        name = ".".join(parts) or "__init__"
        if parts and parts[0] in excluded_packages:
            continue
        if name in excluded_modules:
            continue
        found.append((name, path))
    return sorted(found)


def collect_module(module, path: Path) -> dict:
    """The enums a module defines and the word-list constants it assigns, in source order."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    enums, constants = {}, {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cls = getattr(module, node.name, None)
            if isinstance(cls, type) and issubclass(cls, enum.Enum) and cls.__module__ == module.__name__:
                enums[node.name] = {"base": _base(cls),
                                    "members": [[name, _member(member.value)]
                                                for name, member in cls.__members__.items()]}
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Name) or target.id.startswith("_") or not target.id.isupper():
                    continue
                if not hasattr(module, target.id):
                    continue
                try:
                    constants[target.id] = encode(getattr(module, target.id), node.value)
                except Skip:
                    pass
    entry = {}
    if enums:
        entry["enums"] = enums
    if constants:
        entry["constants"] = constants
    return entry


def tables() -> dict:
    """What no constant holds: the settings' keys and types, and the interruption categories' presentation."""
    found = {}
    try:
        settings = importlib.import_module(CORE + ".settings")
        found["settings"] = {"keys": list(settings.FIELDS),
                             "types": {name: settings.field_type(name) for name in settings.FIELDS}}
    except (ImportError, AttributeError, KeyError):
        pass
    try:
        reasons = importlib.import_module(CORE + ".reasons")
        found["interruption_categories"] = [
            {"category": entry.category, "recoverable": bool(entry.recoverable), "order": entry.order,
             "has_reset_time": bool(entry.has_reset_time), "configurable": bool(entry.configurable)}
            for entry in sorted(reasons.REASONS.values(), key=lambda entry: entry.order)]
    except (ImportError, AttributeError):
        pass
    return found


def collect(source: Path, package: str, excluded_packages, excluded_modules) -> dict:
    modules, unimportable = {}, []
    for name, path in module_names(source, package, excluded_packages, excluded_modules):
        dotted = package if name == "__init__" else package + "." + name
        try:
            module = importlib.import_module(dotted)
        except Exception as error:                       # a module of an old tag that does not import here
            unimportable.append([name, type(error).__name__])
            continue
        entry = collect_module(module, path)
        if entry:
            modules[name] = entry
    return {"modules": modules, "unimportable": unimportable}


def child(kind: str, source: Path, output: Path) -> None:
    """Run as `python -I -B vocab_export.py --child KIND SOURCE OUTPUT`: import the extracted tree and write what it holds."""
    if kind not in ("standard", "advanced"):
        raise SystemExit("--child takes standard or advanced")
    sys.path.insert(0, str(source / "src"))
    if kind == "advanced":
        sys.path.insert(0, str(source / "advanced" / "src"))
        os.environ["CODEX_AR_EDITION"] = "advanced"
    core = collect(source / "src", CORE, EXCLUDED_PACKAGES, EXCLUDED_MODULES)
    result = {"core": core}
    if kind == "standard":
        result["tables"] = tables()
    else:
        result["advanced"] = collect(source / "advanced" / "src", ADVANCED, ADVANCED_EXCLUDED_PACKAGES,
                                     ADVANCED_EXCLUDED_MODULES)
    output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8", newline="\n")


# ----------------------------------------------------------------------------- the parent's side
def _git(repo: Path, *arguments: str) -> bytes:
    done = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, timeout=600,
                          creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise SystemExit("git %s failed: %s" % (arguments[0], done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout


def resolve(repo: Path, ref: str) -> str:
    """The commit a tag, branch or commit names; a ref that is an option is refused."""
    if not ref or ref.startswith("-"):
        raise SystemExit("not a ref: %r" % ref)
    return _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}").decode("ascii").strip()


def extract(repo: Path, commit: str, trees, destination: Path) -> None:
    """The trees of a commit, from git's own archive and into a folder of ours, without a checkout."""
    data = _git(repo, "archive", "--format=tar", commit, "--", *trees)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        if hasattr(tarfile, "data_filter"):
            archive.extractall(destination, filter="data")
        else:                                              # pragma: no cover - Python before 3.12
            archive.extractall(destination)


def _environment(scratch: Path) -> dict:
    """A child's world: nothing of this account's, and a home of its own."""
    keep = ("SYSTEMROOT", "SYSTEMDRIVE", "PATH", "PATHEXT", "COMSPEC", "WINDIR", "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE")
    environment = {key: os.environ[key] for key in keep if key in os.environ}
    home = scratch / "home"
    for name in ("home", "local", "roaming", "temp", "codex"):
        (scratch / name).mkdir(exist_ok=True)
    environment.update(USERPROFILE=str(home), HOME=str(home), LOCALAPPDATA=str(scratch / "local"),
                       APPDATA=str(scratch / "roaming"), TEMP=str(scratch / "temp"), TMP=str(scratch / "temp"),
                       CODEX_HOME=str(scratch / "codex"), PYTHONDONTWRITEBYTECODE="1")
    return environment


def run_child(kind: str, scratch: Path) -> dict:
    output = scratch / ("%s.json" % kind)
    done = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--child", kind,
                           str(scratch / "tree"), str(output)],
                          capture_output=True, timeout=900, env=_environment(scratch), cwd=str(scratch),
                          creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise SystemExit("the %s reader failed:\n%s" % (kind, done.stderr.decode("utf-8", "replace")[-2000:]))
    return json.loads(output.read_text(encoding="utf-8"))


def _spells(value) -> bool:
    if isinstance(value, str):
        return any(name in value for name in SECRET_NAMES)
    if isinstance(value, dict):
        return any(_spells(key) or _spells(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_spells(item) for item in value)
    return False


def withhold(modules: dict) -> tuple[dict, dict]:
    """The modules without what spells the advanced edition's names, and that, by `module.NAME`."""
    kept, taken = {}, {}
    for name, entry in modules.items():
        left = {}
        for section, items in entry.items():
            left[section] = {}
            for key, item in items.items():
                if _spells(item):
                    taken["%s.%s" % (name, key)] = item
                else:
                    left[section][key] = item
        left = {section: items for section, items in left.items() if items}
        if left:
            kept[name] = left
    return kept, taken


def export(repo: Path, ref: str, advanced: bool) -> tuple[str, dict, dict | None]:
    """(the commit, the standard document, the advanced one or None) for a ref of a repository."""
    commit = resolve(repo, ref)
    scratch = Path(tempfile.mkdtemp(prefix="car-vocab-"))
    try:
        trees = ("src", "advanced/src") if advanced else ("src",)
        try:
            extract(repo, commit, trees, scratch / "tree")
        except SystemExit as stop:
            if advanced and "advanced" in str(stop):
                raise SystemExit("%s has no advanced/src to read" % ref)
            raise
        standard = run_child("standard", scratch)
        kept, taken = withhold(standard["core"]["modules"])
        document = {"format": FORMAT, "edition": "standard", "modules": kept, "tables": standard["tables"],
                    "unimportable": standard["core"]["unimportable"], "withheld": len(taken)}
        second = None
        if advanced:
            adv = run_child("advanced", scratch)
            second = {"format": FORMAT, "edition": "advanced", "core_edition": taken,
                      "modules": adv["advanced"]["modules"], "unimportable": adv["advanced"]["unimportable"]}
        return commit, document, second
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def render(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def count(document: dict) -> str:
    modules = document["modules"]
    enums = sum(len(entry.get("enums", {})) for entry in modules.values())
    members = sum(len(item["members"]) for entry in modules.values() for item in entry.get("enums", {}).values())
    constants = sum(len(entry.get("constants", {})) for entry in modules.values())
    return "%d modules, %d enums (%d members), %d constants" % (len(modules), enums, members, constants)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write vocab.json: the closed vocabularies of one commit.")
    parser.add_argument("--ref", help="a tag, branch or commit of the repository (never a working tree)")
    parser.add_argument("--repo", default=str(ROOT), help="the git repository to read (default: this one)")
    parser.add_argument("--out", default="vocab.json", help="the standard file; default vocab.json in this folder")
    parser.add_argument("--advanced", action="store_true",
                        help="also write the advanced edition's file, <out stem>-advanced.json")
    parser.add_argument("--child", nargs=3, metavar=("KIND", "SOURCE", "OUTPUT"), help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.child:
        child(arguments.child[0], Path(arguments.child[1]), Path(arguments.child[2]))
        return 0
    if not arguments.ref:
        parser.error("--ref is required")
    repo = Path(arguments.repo).resolve()
    commit, standard, second = export(repo, arguments.ref, arguments.advanced)
    out = Path(arguments.out)
    written = [(out, standard)]
    if second is not None:
        written.append((out.with_name(out.stem + "-advanced" + out.suffix), second))
    for path, document in written:
        data = render(document)
        path.write_bytes(data)
        print("%s: %s from %s (%s), %s, sha256 %s" % (
            path, document["edition"], arguments.ref, commit[:9], count(document), hashlib.sha256(data).hexdigest()),
            file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
