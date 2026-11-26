"""S7.2a's ledger of the advanced tests (P7-DESIGN 3.1, the owner's Q3 (c)): for every `advanced/tests/test_*.py` of the
reference tag, the seats whose modules it imports, and the one that unlocks it on Rust through the advanced proxy - the
last of them in the waves (2.3) - or the ledger's reason it runs on the reference only (the C# page, D8, D10).

    python -X utf8 tests/rustdiff/advledger_s72a.py [--tag v0.6.26] [--markdown]

The table only shrinks (`tests/rustdiff/LEDGER` discipline): a seat that ports a module moves its files from "waits" to
"green through the proxy" in its own ledger, `advledger_<seat>.py`. Reads the tag out of git; runs nothing of it.
"""
from __future__ import annotations

import argparse
import ast
import io
import subprocess
import sys
import tarfile

PACKAGE = "codex_auto_resume_advanced"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# The waves (P7-DESIGN 2.3): a file is unlocked by the latest seat it needs.
ORDER = ["S7.1", "S7.2c", "S7.3c", "S7.2a", "S7.3b", "S7.2b", "S7.2d", "S7.2e1", "S7.2e2", "S7.3a", "S7.4", "S7.3d"]
DONE = {"S7.1", "S7.2c", "S7.3c"}


def seat(module: str) -> str:
    """The seat that owns `module` (a dotted name below the package), P7-DESIGN 2.2."""
    parts = module.split(".")
    top = parts[0]
    engine = {
        "S7.2b": "account autoswitch", "S7.2d": "usage usagestop resetmessage resetwatch credits earlyreset wrapwords "
        "continued capacity", "S7.2e1": "headless compact fallback silent retries emptyreply keepgoing goal subagent "
        "markerfree foropen opentarget steer promptqueue chat oncemore everyconversation parallel sessions admitted",
        "S7.2e2": "anchor wake supervise updatecheck analytics fleet powertasks", "S7.3b": "feed push remote",
        "S7.3c": "hookclaims"}
    if module in ("", "plug", "runtime", "credentials", "win.dpapi") or module.endswith("__init__"):
        return "S7.2a"
    if module in ("codex.authfile", "codex.account", "codex.swap", "codex.restart", "win.appclose"):
        return "S7.2b"
    if top == "codex" or module in ("autocheck", "compatdata", "win.stopflag", "win.waketimer", "win"):
        return "S7.2c"
    if top == "engine" and len(parts) > 1:
        for owner, names in engine.items():
            if parts[1] in names.split():
                return owner
        return "S7.2a"
    if module in ("control.courier", "control.remote") or top == "courier":
        return "S7.3b"
    if top in ("report", "hook") or module == "control.hookplugin":
        return "S7.3c"
    if module in ("control.pythons", "courier.pythonorg", "pythoncheck"):
        return "retired"
    if top == "control" or module == "surfaces":
        return "S7.3a"
    if module in ("measure", "evidence"):
        return "S7.4"
    return "S7.1"


def files(tag: str) -> dict:
    archive = subprocess.run(["git", "archive", "--format=tar", tag, "advanced/tests"], capture_output=True,
                             creationflags=NO_WINDOW, check=True)
    found = {}
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        for member in tar.getmembers():
            name = member.name.rsplit("/", 1)[-1]
            if member.isfile() and name.endswith(".py"):
                found[name] = tar.extractfile(member).read().decode("utf-8")
    return found


def imported(source: str, helpers: dict, seen=None) -> set:
    """The package's modules `source` imports, through the tests' own helper modules too (advancedcase, pagecase...)."""
    seen = set() if seen is None else seen
    modules = set()
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module + "." + alias.name for alias in node.names] + [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        for name in names:
            if name.startswith(PACKAGE):
                modules.add(name[len(PACKAGE) + 1:] if name != PACKAGE else "")
            helper = name.split(".")[0] + ".py"
            if helper in helpers and helper not in seen and not helper.startswith("test_"):
                seen.add(helper)
                modules |= imported(helpers[helper], helpers, seen)
    return modules


def real(module: str, known: set) -> str:
    """`a.b.Name` cut to the module it names."""
    while module and module not in known:
        module = module.rpartition(".")[0]
    return module


def ledger(tag: str) -> list:
    source = subprocess.run(["git", "ls-tree", "-r", "--name-only", tag, "advanced/src/" + PACKAGE],
                            capture_output=True, creationflags=NO_WINDOW, check=True, text=True).stdout.split()
    known = {""}
    for path in source:
        if path.endswith(".py"):
            dotted = path[len("advanced/src/" + PACKAGE) + 1:-3].replace("/", ".")
            known.add(dotted[:-9] if dotted.endswith(".__init__") else dotted)
    tests = files(tag)
    rows = []
    for name in sorted(tests):
        if not name.startswith("test_"):
            continue
        text = tests[name]
        modules = {real(each, known) for each in imported(text, tests)}
        seats = {seat(each) for each in modules}
        case = "advancedcase" in text
        if "pagecase" in text:
            reason, unlock = "C# page (S6.2a's window, pagecase.py)", "S6.2a"
        elif "retired" in seats and seats <= {"retired", "S7.1", "S7.2a"}:
            reason, unlock = "retired by D8", "-"
        elif "S7.4" in seats:
            reason, unlock = "measurement harness (Q2 (a))", "S7.4"
        else:
            live = [each for each in ORDER if each in seats]
            unlock = live[-1] if live else "S7.2a"
            if unlock in DONE or unlock == "S7.1":
                unlock = "S7.2a"
            reason = "proxy"
        rows.append({"file": name, "advancedcase": case, "seats": sorted(seats), "unlock": unlock, "reason": reason})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.6.26")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    rows = ledger(args.tag)
    counts = {}
    for row in rows:
        key = (row["unlock"], row["advancedcase"])
        counts[key] = counts.get(key, 0) + 1
    if args.markdown:
        print("| unlocked by | files | of them advancedcase |")
        print("|---|---:|---:|")
        for unlock in ORDER + ["S6.2a", "-"]:
            total = sum(n for (seat_, _), n in counts.items() if seat_ == unlock)
            if total:
                print("| %s | %d | %d |" % (unlock, total, counts.get((unlock, True), 0)))
        print("| **all** | %d | %d |" % (len(rows), sum(row["advancedcase"] for row in rows)))
    else:
        for row in rows:
            print("%-58s %-6s %-6s %s" % (row["file"], row["unlock"], "case" if row["advancedcase"] else "", ",".join(row["seats"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
