"""Prove, from the two archives' bytes, that the standard one holds nothing of the advanced edition.

The standard archive is built from a list of trees that does not name `advanced/`
(build/make_release.py), so it cannot hold the advanced code - by construction. This is the
proof that does not take the build script's word for it. It reads the archives that were built,
the repository they were built from, and nothing else, and fails the build on any of six findings:

  (a) an entry of the standard archive lies where the advanced edition's files go;
  (b) an entry of the standard archive is, byte for byte, a file of the advanced tree;
  (c) a text entry of the standard archive spells an identifier the advanced tree declares, or
      the line every shipped advanced file begins with - except the few lines of edition
      machinery in ALLOWED, each with its reason;
  (d) one of our own executables in the standard archive holds a name or a string literal of
      the advanced window's C#;
  (e) the standard archive built again from `git archive HEAD`, with `advanced/` deleted before
      the build, is not the same file. This is the one that proves the standard bytes do not
      depend on the advanced tree at all: not merely that nothing of it is found, but that
      removing it changes nothing;
  (f) an entry of the standard archive is missing from the advanced one, or differs there -
      except the settings window, which each edition builds for itself, and the manifest's
      display name - or the advanced archive adds anything outside its own two places.

Run in the release build job after both archives are built:

    python build/edition_audit.py [--dist build/dist]

(e) builds the standard edition again, executables included, so it needs what a release build
needs: Windows, the in-box C# compiler and Python. The tests (tests/test_edition_audit.py) hold
every check to small archives made for the purpose, where each finding can be put in on
purpose and seen to be caught.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import make_release  # noqa: E402

PACKAGE = make_release.ADVANCED_PACKAGE
SKILL = make_release.ADVANCED_SKILL
# What every shipped file under advanced/ says in its first lines (tests/editions.py, SENTINEL).
SENTINEL = "ADVANCED-EDITION-CODE"
# The trees under advanced/ whose files ship in the advanced edition. Its tests do not.
SHIPPED = ("src", "gui", "skills")
# The advanced edition's places in its archive, and the one name its tree has in the
# repository. Nothing of the standard archive may lie in any of them.
PLACEMENTS = tuple("payload/app/%s/" % placed for _tree, placed in make_release.ADVANCED_TREES)
REPOSITORY_TREE = "payload/app/advanced/"
# The two entries the editions may differ in (f): each builds its own settings window, and the
# advanced manifest's display name carries the edition's word.
WINDOW = "payload/" + make_release.GUI_EXE
MANIFEST = "payload/app/.codex-plugin/plugin.json"
# Our own executables, which (d) reads. The runtime's are python.org's, and not ours to judge.
EXECUTABLES = (WINDOW, "payload/app/mcp/" + make_release.MCP_EXE)
# The edition machinery: the lines of the standard archive that have to spell an advanced name
# to tell one edition's installation from the other's. Keyed by the entry and the name, so an
# allowance for one is no allowance for another; tests/test_edition_audit.py holds this to the
# files the standard build actually ships, so an allowance nothing uses does not linger.
ALLOWED = {
    ("payload/app/src/codex_auto_resume/edition.py", PACKAGE):
        "the one module of core that looks for the package, by its name (tests/test_edition.py)",
    ("payload/app/scripts/bootstrap.ps1", PACKAGE):
        "tells which edition a tree is by whether the package is in it, as edition.py does, and "
        "which edition an archive is before it unpacks it (Test-Archive)",
    ("payload/app/scripts/bootstrap.ps1", SKILL):
        "refuses a standard archive that carries the advanced skill, which Codex would load from "
        "the plugin tree (Test-Archive)",
    ("install/install.ps1", PACKAGE):
        "tells which edition the payload it installs is, the same way",
}
# Shorter names and plain lowercase words - `create`, `record` - are English as often as they
# are code, and would be found in any text; the checks look for the ones that can only be ours.
MIN_LENGTH = 6
_WORD = rb"[A-Za-z0-9_]"


# --------------------------------------------------------------------------- the advanced tree
@dataclass(frozen=True)
class Inventory:
    """What the audit looks for: the advanced tree, as the standard archive must not hold it."""
    digests: frozenset          # SHA-256 of every shipped advanced file, in either line ending
    names: frozenset            # what no text entry may spell (c)
    window: frozenset           # what no executable of ours may hold (d)
    literals: frozenset         # the advanced window's string literals, also for (d)

    @classmethod
    def build(cls, advanced: dict, core_python=(), core_csharp=()) -> "Inventory":
        """From the shipped advanced files (repository path -> bytes) and the text of the core's
        Python and C#. A name the core uses too is the core's word, not a sign of the advanced
        edition, so it is left out; so is a literal the core's own contains."""
        core_words = set()
        for text in core_python:
            core_words |= python_words(text)
        core_cs, core_literals = set(), set()
        for text in core_csharp:
            words, literals = csharp(text)
            core_cs |= words
            core_literals |= literals
        digests, declared, cs_words, cs_literals = set(), set(), set(), set()
        for name, data in advanced.items():
            if not data.strip():
                continue                   # an empty file is every empty file
            for form in (data, data.replace(b"\r\n", b"\n"),
                         data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")):
                digests.add(hashlib.sha256(form).hexdigest())
            path = Path(name)
            if path.suffix == ".py":
                declared |= python_declared(data.decode("utf-8"))
                # Its module's name, and its packages': `__init__` names none of them.
                declared |= {part for part in path.with_suffix("").parts
                             if part not in ("advanced", "src", "__init__")}
            elif path.suffix == ".cs":
                words, literals = csharp(data.decode("utf-8"))
                cs_words |= words
                cs_literals |= literals
        strong = {PACKAGE, SKILL, SENTINEL}
        names = strong | {name for name in declared - core_words if distinctive(name)}
        window = strong | {name for name in cs_words - core_cs if distinctive(name)}
        literals = {literal for literal in cs_literals
                    if len(literal) >= MIN_LENGTH and literal not in core_cs
                    and not any(literal in other for other in core_literals)}
        return cls(frozenset(digests), frozenset(names), frozenset(window), frozenset(literals))


def distinctive(name: str) -> bool:
    return len(name) >= MIN_LENGTH and (not name.islower() or "_" in name
                                        or any(c.isdigit() for c in name))


def python_words(text: str) -> set:
    """Every identifier a Python module binds or uses."""
    words = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Name):
            words.add(node.id)
        elif isinstance(node, ast.Attribute):
            words.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            words.add(node.name)
        elif isinstance(node, ast.arg):
            words.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            words.add(node.arg)
        elif isinstance(node, ast.alias):
            words.update(node.name.split("."))
            if node.asname:
                words.add(node.asname)
        elif isinstance(node, ast.ImportFrom) and node.module:
            words.update(node.module.split("."))
    return words


def python_declared(text: str) -> set:
    """What a Python module declares: every function and class, and every name assigned in
    the module's body or a class's."""
    tree = ast.parse(text)
    names = {node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    scopes = [tree] + [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    for scope in scopes:
        for statement in scope.body:
            if isinstance(statement, ast.Assign):
                targets = statement.targets
            elif isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            else:
                continue
            for target in targets:
                names |= {item.id for item in ast.walk(target) if isinstance(item, ast.Name)}
    return names


_CSHARP = re.compile(r"""
      (?P<comment>//[^\n]*|/\*.*?\*/)
    | (?P<verbatim>@"(?:[^"]|"")*")
    | (?P<string>"(?:\\.|[^"\\\n])*")
    | (?P<char>'(?:\\.|[^'\\\n])+')
    | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
""", re.S | re.X)
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\", '"': '"', "'": "'"}


def csharp(text: str) -> tuple[set, set]:
    """A C# source's identifiers and string literals. Comments are neither, and what a string
    says is not an identifier."""
    words, literals = set(), set()
    for match in _CSHARP.finditer(text):
        kind, token = match.lastgroup, match.group()
        if kind == "word":
            words.add(token)
        elif kind == "string":
            literals.add(re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), token[1:-1]))
        elif kind == "verbatim":
            literals.add(token[2:-1].replace('""', '"'))
    return words, literals


def _git(root: Path, *arguments: str) -> bytes:
    done = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, timeout=300)
    if done.returncode != 0:
        raise SystemExit("git %s failed: %s" % (arguments[0], done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout


def tracked(root: Path, *trees: str) -> list:
    """Every tracked file under the trees, as git spells it. Loud: an audit of nothing proves
    nothing, and a listing that came back empty is not an advanced tree with nothing in it."""
    names = sorted(name for name in _git(root, "ls-files", "-z", "--", *trees).decode("utf-8").split("\0")
                   if name)
    if not names:
        raise SystemExit("git lists nothing under %s" % ", ".join(trees))
    return names


def inventory(root: Path = ROOT) -> Inventory:
    """The advanced tree of the repository at `root`, and the core it is told apart from."""
    advanced = {name: (root / name).read_bytes()
                for name in tracked(root, *("advanced/" + tree for tree in SHIPPED))}
    python = [(root / name).read_text(encoding="utf-8") for name in tracked(root, "src", "scripts")
              if name.endswith(".py")]
    csharp_sources = [(root / name).read_text(encoding="utf-8") for name in tracked(root, "gui")
                      if name.endswith(".cs")]
    return Inventory.build(advanced, python, csharp_sources)


# --------------------------------------------------------------------------------- the checks
def entries(archive: Path) -> dict:
    """Every entry of a ZIP, by name, in the archive's order."""
    with zipfile.ZipFile(archive) as bundle:
        return {info.filename: bundle.read(info) for info in bundle.infolist() if not info.is_dir()}


def text(data: bytes) -> str | None:
    """The entry as text, or None for a binary: UTF-8 and no NUL."""
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def check_paths(standard: dict) -> list:
    """(a) Nothing of the standard archive where the advanced edition's files go."""
    found = []
    for name in standard:
        lowered = name.replace("\\", "/").lower()
        parts = set(lowered.split("/"))
        if (PACKAGE.lower() in parts or SKILL.lower() in parts or lowered.startswith(REPOSITORY_TREE)
                or any(lowered.startswith(place.lower()) for place in PLACEMENTS)):
            found.append("(a) %s lies where the advanced edition's files go" % name)
    return found


def check_digests(standard: dict, advanced: Inventory) -> list:
    """(b) No entry of the standard archive is a file of the advanced tree."""
    return ["(b) %s has the bytes of a file of the advanced tree" % name
            for name, data in standard.items() if hashlib.sha256(data).hexdigest() in advanced.digests]


def _spells(haystack: str, name: str) -> bool:
    if name in (PACKAGE, SKILL, SENTINEL):
        return name in haystack
    return re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name), haystack) is not None


def check_names(standard: dict, advanced: Inventory) -> tuple[list, set]:
    """(c) No text entry spells an advanced name, outside the edition machinery. Returns the
    findings and the allowances that were needed, so a caller can see none has gone stale."""
    found, used = [], set()
    for entry, data in standard.items():
        content = text(data)
        if content is None:
            continue
        for name in sorted(advanced.names):
            if not _spells(content, name):
                continue
            if (entry, name) in ALLOWED:
                used.add((entry, name))
            else:
                found.append("(c) %s spells %s" % (entry, name))
    return found, used


def _holds(data: bytes, name: str, word: bool) -> bool:
    for encoding in ("utf-8", "utf-16-le"):
        needle = name.encode(encoding)
        if not word:
            if needle in data:
                return True
            continue
        if encoding == "utf-8":
            pattern = rb"(?<!" + _WORD + rb")" + re.escape(needle) + rb"(?!" + _WORD + rb")"
        else:
            pattern = rb"(?<!" + _WORD + rb"\x00)" + re.escape(needle) + rb"(?!" + _WORD + rb"\x00)"
        if re.search(pattern, data):
            return True
    return False


def check_executables(standard: dict, advanced: Inventory) -> list:
    """(d) Our executables in the standard archive hold no name and no literal of the advanced
    window: not as metadata (UTF-8) and not as a string or a resource (UTF-16)."""
    found = []
    for entry in EXECUTABLES:
        data = standard.get(entry)
        if data is None:
            found.append("(d) the standard archive has no %s to read" % entry)
            continue
        for name in sorted(advanced.window):
            if _holds(data, name, word=name not in (PACKAGE, SKILL, SENTINEL)):
                found.append("(d) %s holds %s" % (entry, name))
        for literal in sorted(advanced.literals):
            if _holds(data, literal, word=False):
                found.append("(d) %s holds the literal %r" % (entry, literal))
    return found


def check_rebuild(standard: Path, rebuilt: Path) -> list:
    """(e) The standard archive and the one built again without advanced/ are one file."""
    first, second = standard.read_bytes(), rebuilt.read_bytes()
    if first == second:
        return []
    found = ["(e) the standard archive is not the one built from `git archive HEAD` without advanced/ "
             "(%s, rebuilt %s)" % (hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())]
    ours, again = entries(standard), entries(rebuilt)
    for name in sorted(set(ours) | set(again)):
        if ours.get(name) != again.get(name):
            state = ("only in the archive" if name not in again else
                     "only in the rebuild" if name not in ours else "differs")
            found.append("(e)   %s: %s" % (name, state))
    return found


def check_superset(standard: dict, advanced: dict) -> list:
    """(f) The advanced archive is the standard one plus its own two places: every standard
    entry is there with the same bytes, but the window and the display name."""
    found = []
    for name, data in standard.items():
        if name not in advanced:
            found.append("(f) %s is missing from the advanced archive" % name)
        elif name == WINDOW:
            continue
        elif name == MANIFEST:
            found += _manifests(data, advanced[name])
        elif advanced[name] != data:
            found.append("(f) %s differs in the advanced archive" % name)
    for name in advanced:
        if name not in standard and not any(name.startswith(place) for place in PLACEMENTS):
            found.append("(f) the advanced archive adds %s outside its own places" % name)
    for name in make_release.REQUIRED_ADVANCED_FILES:
        if "payload/app/" + name not in advanced:
            found.append("(f) the advanced archive has no payload/app/%s" % name)
    return found


def _manifests(standard: bytes, advanced: bytes) -> list:
    """The one difference the manifests may have: the display name, with the edition's word."""
    try:
        ours, theirs = json.loads(standard), json.loads(advanced)
        name = ours["interface"]["displayName"]
        expected = "%s %s" % (name, make_release.ADVANCED_WORD)
    except (ValueError, KeyError, TypeError):
        return ["(f) the manifest cannot be read"]
    if theirs.get("interface", {}).get("displayName") != expected:
        return ["(f) the advanced manifest's display name is not %r" % expected]
    before, after = json.dumps(name).encode("utf-8"), json.dumps(expected).encode("utf-8")
    if standard.count(before) != 1 or standard.replace(before, after) != advanced:
        return ["(f) the manifests differ in more than the display name"]
    return []


# ------------------------------------------------------------------------------- (e)'s rebuild
def _powershell() -> str:
    """pwsh where there is one, as the release workflow runs the build; Windows PowerShell
    otherwise. Either compiles the same bytes: the script hands csc the same arguments."""
    found = shutil.which("pwsh")
    if found:
        return found
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell"
               / "v1.0" / "powershell.exe")


def rebuild_standard(root: Path, work: Path) -> Path:
    """The standard archive built again from the commit alone, with advanced/ deleted first.

    `git archive HEAD`, not the working tree, so nothing uncommitted and nothing untracked can
    stand in for what the commit holds. The runtime is the one the first build verified, taken
    from its cache only to save the download; make_release checks its digest again."""
    tree = work / "tree"
    with tarfile.open(fileobj=io.BytesIO(_git(root, "archive", "--format=tar", "HEAD"))) as exported:
        exported.extractall(tree, filter="data")
    shutil.rmtree(tree / "advanced", ignore_errors=True)
    if (tree / "advanced").exists():
        raise SystemExit("(e) advanced/ could not be deleted from the exported tree")
    cached = root / "build" / "cache" / make_release.PYTHON_ZIP
    if cached.is_file():
        (tree / "build" / "cache").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, tree / "build" / "cache" / make_release.PYTHON_ZIP)
    steps = (("make_gui.ps1", [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                               "Bypass", "-File", str(tree / "build" / "make_gui.ps1"), "-Root", str(tree)]),
             ("make_release.py", [sys.executable, str(tree / "build" / "make_release.py"),
                                  "--edition", "standard", "--output", str(work / "dist")]))
    for step, command in steps:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=1800)
        if done.returncode != 0:
            raise SystemExit("(e) the rebuild's %s failed:\n%s"
                             % (step, (done.stderr or done.stdout)[-2000:]))
    manifest = json.loads((tree / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
    return work / "dist" / make_release.archive_name("standard", str(manifest["version"]))


# -------------------------------------------------------------------------------------- main
def audit(standard: Path, advanced: Path, root: Path = ROOT, rebuild=rebuild_standard) -> list:
    """Every finding, (a) to (f), as a sentence each. None means the standard archive holds
    nothing of the advanced edition, and the advanced one adds only its own."""
    tree = inventory(root)
    ours, theirs = entries(standard), entries(advanced)
    found = check_paths(ours) + check_digests(ours, tree)
    found += check_names(ours, tree)[0]
    found += check_executables(ours, tree)
    with tempfile.TemporaryDirectory(prefix="edition-audit-") as work:
        found += check_rebuild(standard, rebuild(root, Path(work)))
    found += check_superset(ours, theirs)
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prove the standard archive holds no advanced code.")
    parser.add_argument("--dist", default=str(make_release.OUT),
                        help="where make_release.py wrote both archives (default: build/dist)")
    args = parser.parse_args(argv)
    release = make_release.version()
    standard = Path(args.dist) / make_release.archive_name("standard", release)
    advanced = Path(args.dist) / make_release.archive_name("advanced", release)
    for archive in (standard, advanced):
        if not archive.is_file():
            raise SystemExit("missing %s - build both editions first" % archive)
    print("edition audit of %s and %s" % (standard.name, advanced.name))
    found = audit(standard, advanced)
    for line in found:
        print("  " + line)
    if found:
        print("the standard archive is not proven free of the advanced edition")
        return 1
    print("  (a)-(f) found nothing: the standard archive holds none of the advanced edition")
    return 0


if __name__ == "__main__":
    sys.exit(main())
