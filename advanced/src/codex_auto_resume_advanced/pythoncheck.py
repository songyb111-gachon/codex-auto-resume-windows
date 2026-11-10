# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Run by a Python not yet in use, as the last check before it is (control/pythons.py, python_choice): can it import every
module of this edition?

Started as a script, `python.exe -I -B -X disable-remote-debug pythoncheck.py <folder>...`, so it needs nothing of the
product to start and leaves no bytecode behind. As build/runtime_check.py does for the bundled runtime, it imports every
module under the folders it is given, and an audit hook holds the imports to doing nothing: a module that starts a program,
writes to the registry or opens a connection merely by being imported fails the check. Exit 0 only where all of them did
import; the names of those that did not go to stdout. Out without the interpreter's shutdown, so no exit handler runs.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

FORBIDDEN = frozenset(("subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile",
                       "os.startfile/2", "socket.connect", "winreg.CreateKey", "winreg.DeleteKey", "winreg.DeleteValue",
                       "winreg.SetValue", "winreg.SaveKey"))


def no_effects(event, _arguments):
    if event in FORBIDDEN:
        raise RuntimeError("importing a module tried %s" % event)


def module_names(folder: Path) -> list:
    names = []
    for path in sorted(folder.rglob("*.py")):
        parts = list(path.relative_to(folder).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            names.append(".".join(parts))
    return names


def failures(names) -> list:
    found = []
    for name in names:
        try:
            importlib.import_module(name)
        except BaseException as exc:                # a SystemExit at import is as much a failure as an ImportError
            found.append("%s: %s" % (name, type(exc).__name__))
    return found


def main(argv) -> None:
    folders = [Path(each) for each in argv[1:]]
    sys.addaudithook(no_effects)
    sys.path[:0] = [str(folder) for folder in folders]
    names = [name for folder in folders for name in module_names(folder)]
    found = failures(names) if names else ["nothing to import"]
    for line in found:
        print(line)
    sys.stdout.flush()
    os._exit(1 if found else 0)


if __name__ == "__main__":
    main(sys.argv)
