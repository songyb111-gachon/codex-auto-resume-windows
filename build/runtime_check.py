"""Asked by build/make_release.py (check_trimmed_runtime) under the trimmed runtime it has just staged.

The bundled runtime leaves out what the product does not use (build/runtime_keep.json). What is to be feared is a rare
path that needs a module that went and crashes on a person's PC with no test seeing it, so three things are read here,
and any finding stops the build:

  every module of the staged app is imported, under this interpreter, the one a person will have;
  every import statement of the staged code, however deep in a function and however guarded, is read, and none may name
  a module that went: an import that only runs on a rare path is exactly what importing the module does not reach;
  every import inside the kept standard library is read from its bytecode, and each one of a module that went has to be
  in the list's `reviewed`, with the reason it does not run. A new import there, from a new Python, stops the build
  until someone has read it; and an entry that no longer matches any import stops it too, so the list does not rot.

What it is given is one JSON file: {app, library, removed, reviewed, also}. `also` are more Python files to read for
imports: build/smoke_archive.py runs under this same interpreter when a release is verified.

Standard library only, and only modules the list keeps. It imports the product's modules and does nothing with them, and
an audit hook holds that to be true: a module that starts a program, writes to the registry or opens a connection
merely by being imported is a finding of its own.
"""
from __future__ import annotations

import ast
import dis
import importlib
import json
import marshal
import os
from pathlib import Path
import sys
import types
import zipfile

# What no import may do. A hook cannot be taken back, so the guard lasts as long as this process.
_FORBIDDEN = frozenset(("subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile",
                        "os.startfile/2", "socket.connect", "winreg.CreateKey", "winreg.DeleteKey", "winreg.DeleteValue",
                        "winreg.SetValue", "winreg.SaveKey"))


def _no_effects(event, _arguments):
    if event in _FORBIDDEN:
        raise RuntimeError("importing a module tried %s" % event)


def goes(name: str, removed) -> bool:
    """Whether `name`, or a package it is inside, is one of the modules the trim took out."""
    parts = name.split(".")
    return any(".".join(parts[:count]) in removed for count in range(1, len(parts) + 1))


def statements(source: str) -> set:
    """Every module an import statement, or __import__/import_module of a literal, names in this Python source - at any
    depth, guarded or not. `from a import b` names a and a.b, as b may be a module; relative imports are ours."""
    named = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            named.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            named.add(node.module)
            named.update("%s.%s" % (node.module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            called = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if called in ("__import__", "import_module") and isinstance(node.args[0].value, str):
                named.add(node.args[0].value)
    return named


def shipped_findings(files, removed) -> list:
    """Each import of the shipped code that names a module the trim took out."""
    found = []
    for path in files:
        for name in sorted(statements(Path(path).read_text(encoding="utf-8"))):
            if goes(name, removed):
                found.append("%s imports %s, which the trimmed runtime does not have" % (path, name))
    return found


def _code_objects(code):
    yield code
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            yield from _code_objects(constant)


def imports_in(code, module: str, package: bool) -> set:
    """Every module one compiled module's IMPORT_NAME instructions name, at any depth, as absolute names."""
    found = set()
    for each in _code_objects(code):
        instructions = [item for item in dis.get_instructions(each) if item.opname != "EXTENDED_ARG"]
        for place, instruction in enumerate(instructions):
            if instruction.opname != "IMPORT_NAME":
                continue
            level, fromlist, name = instructions[place - 2].argval, instructions[place - 1].argval, instruction.argval
            target = name
            if level:
                parts = module.split(".") if package else module.split(".")[:-1]
                parts = parts[:len(parts) - (level - 1)]
                target = ".".join(parts + ([name] if name else []))
            found.add(target)
            found.update("%s.%s" % (target, item) for item in fromlist or () if item != "*")
    return found


def library_edges(library, removed) -> set:
    """(kept module, module that went) for every import inside the kept library."""
    edges = set()
    with zipfile.ZipFile(library) as bundle:
        for info in bundle.infolist():
            if not info.filename.endswith(".pyc"):
                continue
            module = info.filename[:-len(".pyc")].replace("/", ".")
            package = module.endswith(".__init__")
            module = module[:-len(".__init__")] if package else module
            code = marshal.loads(bundle.read(info)[16:])
            edges.update((module, target) for target in imports_in(code, module, package) if goes(target, removed))
    return edges


def _covers(key: str, edge) -> bool:
    importer, _arrow, target = key.partition(" -> ")
    return importer == edge[0] and (edge[1] == target or edge[1].startswith(target + "."))


def library_findings(edges, reviewed) -> list:
    """An import of a module that went that nobody has read, and an entry of `reviewed` no import matches."""
    found = ["%s can import %s, which the trimmed runtime does not have, and build/runtime_keep.json does not say why "
             "that cannot run" % edge for edge in sorted(edges) if not any(_covers(key, edge) for key in reviewed)]
    found += ["build/runtime_keep.json reviews %s, an import no kept module has any more" % key
              for key in sorted(reviewed) if not any(_covers(key, edge) for edge in edges)]
    return found


def module_names(src: Path) -> list:
    """Each module under `src` as an import would name it."""
    names = []
    for path in sorted(src.rglob("*.py")):
        parts = list(path.relative_to(src).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            names.append(".".join(parts))
    return names


def import_findings(names) -> list:
    """Each module that does not import."""
    found = []
    for name in names:
        try:
            importlib.import_module(name)
        except BaseException as exc:       # a SystemExit at import is as much a failure as an ImportError
            found.append("%s does not import under the trimmed runtime: %s: %s" % (name, type(exc).__name__, exc))
    return found


def main(argv) -> None:
    asked = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    removed = set(asked["removed"])
    app = Path(asked["app"])
    src, scripts = app / "src", app / "scripts"
    python = sorted(src.rglob("*.py")) + sorted(scripts.rglob("*.py")) + [Path(extra) for extra in asked["also"]]
    found = shipped_findings(python, removed)
    found += library_findings(library_edges(asked["library"], removed), asked["reviewed"])
    # Every import done now: a lazy one would prove nothing of a module that is not there (PEP 810, Python 3.15).
    eager = getattr(sys, "set_lazy_imports_filter", None)
    if eager is not None:
        eager(lambda _importing, _imported, _names: False)
    sys.addaudithook(_no_effects)
    sys.path[:0] = [str(src), str(scripts)]
    names = module_names(src) + module_names(scripts)
    found += import_findings(names)
    for line in found:
        print(line)
    print("%d modules imported, %d files read for imports, %d findings" % (len(names), len(python), len(found)))
    # Out without the interpreter's shutdown: nothing imported here is to run its exit handlers.
    sys.stdout.flush()
    os._exit(1 if found else 0)


if __name__ == "__main__":
    main(sys.argv)
