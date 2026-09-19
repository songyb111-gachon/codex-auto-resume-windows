"""The product's own source, read the way every structural test reads it.

A structural test asserts something about the code rather than running it: that only the
watcher sends, that the popup reaches nothing that submits, that no second module builds a
PowerShell command. Until v0.6.5 most of them read one named file, `module.__file__`, or
`glob("*.py")` in one directory - and every one of those keeps passing when the code it
guards moves somewhere it does not look. Split `control.py` into `control/` and
`Path(control.__file__)` is the new package's `__init__.py`, which holds none of it; add a
module under a subdirectory and a non-recursive glob never opens it. A refactor would have
stayed green and quietly stopped checking the safety properties.

So they read through here instead: every *tracked* `.py` file under `src/`, at any depth.
Tracked, so a build output or a scratch file is never mistaken for product code - and
`tests/test_srcscan.py` fails when a `.py` file under `src/` exists on disk without being
tracked, so a forgotten `git add` cannot hide a module from the scans either.

The listing is loud: no git, or a listing with no package in it, raises rather than
returning nothing, because a scan over nothing passes every assertion of absence.

Not a test module (no `test_` prefix), so discovery does not collect it. A test imports it
by putting its own directory on `sys.path`, the way `tests/test_engine.py` reaches
`codexsim`.
"""
from __future__ import annotations

import ast
from collections import namedtuple
from functools import lru_cache
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = "codex_auto_resume"

# One import statement: the module it names, resolved to an absolute dotted name; its line;
# whether it runs only when a function is called; and whether it names this product's code.
Import = namedtuple("Import", "target line lazy internal")


class ScanError(RuntimeError):
    """The source could not be listed. Never caught: a scan over nothing proves nothing."""


@lru_cache(maxsize=None)
def tracked() -> tuple[str, ...]:
    """Every tracked path under `src/`, as git spells it (forward slashes, from the root)."""
    try:
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "src"],
                                 capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScanError("cannot list the tracked sources: %s" % exc) from None
    if listing.returncode != 0:
        raise ScanError("git ls-files failed: %s" % listing.stderr.decode("utf-8", "replace").strip())
    names = tuple(sorted(name for name in listing.stdout.decode("utf-8").split("\0") if name))
    if not any(name.startswith("src/%s/" % PACKAGE) for name in names):
        raise ScanError("git lists no file of the package under src/")
    return names


@lru_cache(maxsize=None)
def _package_files() -> tuple[Path, ...]:
    return tuple(ROOT / name for name in tracked() if name.endswith(".py") and (ROOT / name).is_file())


def package_files() -> list[Path]:
    """Every tracked `.py` file under `src/`, recursively: the package, its subpackages, and
    the `src/auto_resume.py` entry script beside it."""
    return list(_package_files())


def on_disk() -> list[Path]:
    """Every `.py` file under `src/` that exists, tracked or not (bytecode caches aside)."""
    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)


def relative(path: Path) -> str:
    """`codex_auto_resume/cli.py`: the path from `src/`, with forward slashes."""
    return Path(path).resolve().relative_to(SRC.resolve()).as_posix()


def module_name(path: Path) -> str:
    """`codex_auto_resume.cli`; a package's `__init__.py` is the package itself."""
    parts = list(Path(relative(path)).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@lru_cache(maxsize=None)
def modules() -> dict:
    """Dotted module name -> its file, for every tracked module."""
    return {module_name(path): path for path in _package_files()}


def files_of(*names: str) -> list[Path]:
    """The files of these modules and of everything beneath them, if they are packages.

    `files_of("codex_auto_resume.control")` is `control.py` today and every file of
    `control/` once it is a package, so a rule about a module keeps covering all of it."""
    return [path for module, path in sorted(modules().items())
            if any(module == name or module.startswith(name + ".") for name in names)]


@lru_cache(maxsize=None)
def read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _parse(path: Path) -> ast.Module:
    return ast.parse(read(path), filename=str(path))


def package_asts() -> dict:
    """Every tracked `.py` file under `src/` -> its parsed tree."""
    return {path: _parse(path) for path in _package_files()}


def qualnames(tree: ast.AST) -> dict:
    """Every node in `tree` -> the qualified name of the scope it belongs to.

    A function or class maps to its own name, spelled as Python's `__qualname__` spells it
    (`Engine.dispatch`, `outer.<locals>.inner`); every other node maps to the innermost
    function or class that contains it, and "" at module level. So "which function calls
    this" is one lookup, and survives a move that keeps the function's name."""
    names = {tree: ""}

    def visit(node, scope, in_function):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                own = child.name if not scope else scope + (".<locals>." if in_function else ".") + child.name
                names[child] = own
                visit(child, own, isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)))
            else:
                names[child] = scope
                visit(child, scope, in_function)

    visit(tree, "", False)
    return names


def _targets(node, module: str, is_package: bool) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        parts = module.split(".") if is_package else module.split(".")[:-1]
        if node.level > 1:
            parts = parts[:len(parts) - (node.level - 1)]
        target = ".".join(part for part in (".".join(parts), node.module) if part)
    else:
        target = node.module or ""
    known = modules()
    submodules = [target + "." + alias.name for alias in node.names if target + "." + alias.name in known]
    # `from . import config` names the module `config`, not the package's __init__; a name
    # that is not a module (`from .tray import countdown`) names the module it comes from.
    if len(submodules) == len(node.names):
        return submodules
    return [target] + submodules


@lru_cache(maxsize=None)
def _imports(path: Path) -> tuple:
    module = module_name(path)
    is_package = Path(path).name == "__init__.py"
    found = []

    def visit(node, lazy):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for target in _targets(child, module, is_package):
                    internal = target == PACKAGE or target.startswith(PACKAGE + ".") or target in modules()
                    found.append(Import(target, child.lineno, lazy, internal))
            visit(child, lazy or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)))

    visit(_parse(path), False)
    return tuple(found)


def imports(path: Path) -> list:
    """Every import statement in one file, resolved: relative imports become absolute
    dotted names, and an import inside a function is `lazy`."""
    return list(_imports(path))


def import_graph(*, lazy: bool = True) -> dict:
    """module -> the set of this product's modules it imports (itself excluded).

    With `lazy=False`, only the imports that run when the module is loaded."""
    known = modules()
    graph = {module: set() for module in known}
    for module, path in known.items():
        for entry in _imports(path):
            if entry.internal and entry.target in known and entry.target != module and (lazy or not entry.lazy):
                graph[module].add(entry.target)
    return graph


def closure(*roots: str, lazy: bool = True) -> set:
    """The roots and every module of this product they reach through imports."""
    graph = import_graph(lazy=lazy)
    seen, pending = set(), list(roots)
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        pending.extend(graph.get(module, ()))
    return seen


def holders(needle) -> set:
    """The files (as `relative` spells them) whose text contains `needle`: a string, or a
    compiled pattern that must match somewhere."""
    if isinstance(needle, re.Pattern):
        return {relative(path) for path in _package_files() if needle.search(read(path))}
    return {relative(path) for path in _package_files() if needle in read(path)}


def string_constants(tree: ast.AST):
    """Every string literal in a tree, f-string pieces included, as (node, value)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node, node.value
