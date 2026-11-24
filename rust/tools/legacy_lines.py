"""The command lines every published Python version starts `runtime\\python.exe` and `runtime\\pythonw.exe` with (D9).

car-legacy stands in for those two programs in every Rust installation and accepts only these lines, so this is the
list it is held to. Each line is taken out of git, from each tag's own code - nothing of the working tree - where it is
written:

  * scripts/bootstrap.ps1: the repair branch ("already installed - checking it over") and Invoke-InstalledSetup, which
    run the INSTALLED home's runtime\\python.exe app\\scripts\\plugin_setup.py <command> (a bootstrap Codex still holds
    in its plugin copy runs against an installation that is Rust by then);
  * scripts/plugin_setup.py: the sign-in Run value (watcher_command) and the notification button's protocol handler
    (notification_command), both runtime\\pythonw.exe;
  * src/codex_auto_resume/startup.py: the same two as `install --startup` writes them (command_line,
    protocol_command_line), runtime\\pythonw.exe with app\\src\\auto_resume.py;
  * gui/McpLauncher.cs: the MCP launcher a Codex plugin copy keeps, runtime\\python.exe -I ... -c <code>.

A line is written as its arguments after the program, with `{home}` for the installation and `{uri}` for the URI
Windows puts in the protocol handler's "%1". Bootstrap.ps1's Update-CompatibilityData also starts runtime\\python.exe
(`-c <code> ... compat-import`), but only where app\\src\\codex_auto_resume\\controlcli.py exists, which a Rust archive
never carries: it is listed under `never`, so a test can say it stays unreachable.

    python rust/tools/legacy_lines.py            # print the table
    python rust/tools/legacy_lines.py --write    # write rust/crates/car-legacy/tests/data/published.txt
    python rust/tools/legacy_lines.py --check    # rc 1 when that file is not what the tags say

The file is one line per accepted command line: program, first tag, last tag, the number of tags, then the arguments,
all separated by tabs (no argument holds a tab). `--ref dev` adds a branch tip after the tags (the v0.6.26 final's
updater before its tag exists), named by its commit.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "rust" / "crates" / "car-legacy" / "tests" / "data" / "published.txt"
TAG = re.compile(r"v([0-9]+)\.([0-9]+)\.([0-9]+)(?:-(alpha|beta)(?:\.([0-9]+))?)?")
FIRST = (0, 5, 2)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SETUP = r"{home}\app\scripts\plugin_setup.py"
LAUNCHER = r"{home}\watcher-launcher.py"
ENTRY = r"{home}\app\src\auto_resume.py"
X = ["-X", "disable-remote-debug"]


def git(*arguments: str) -> str | None:
    done = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, creationflags=NO_WINDOW)
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace")


def order(tag: str) -> tuple:
    major, minor, patch, stage, number = TAG.fullmatch(tag).groups()
    return (int(major), int(minor), int(patch), {"alpha": 0, "beta": 1, None: 2}[stage],
            int(number) if number else (0 if stage is None else 1))


def tags() -> list[str]:
    listed = [tag for tag in (git("tag", "--list", "v*") or "").split() if TAG.fullmatch(tag)]
    return sorted((tag for tag in listed if order(tag)[:3] >= FIRST), key=order)


def bootstrap_lines(text: str) -> tuple[list[list[str]], list[list[str]]]:
    """(python.exe lines, lines it can reach only past the controlcli.py guard)."""
    lines: list[list[str]] = []
    # The repair branch: `& $python @arguments` over `$arguments = @([-X ...,] $setup, 'setup'[, '--keep-state'])`.
    repair = re.search(r"\$arguments = @\((?:'-X', 'disable-remote-debug', )?\$setup, 'setup'(?:, '--keep-state')?\)", text)
    if repair:
        prefix = X if "'-X', 'disable-remote-debug', $setup" in repair.group(0) else []
        words = ["setup"] + (["--keep-state"] if "--keep-state" in repair.group(0) else [])
        lines += [prefix + [SETUP] + words, prefix + [SETUP] + words + ["--no-startup"]]
    for found in re.finditer(r"& \$python (-X disable-remote-debug )?\$setup 'watcher-running'", text):
        lines.append((X if found.group(1) else []) + [SETUP, "watcher-running"])
    # Invoke-InstalledSetup: `& $python [-X disable-remote-debug] $setup @Arguments`, and what it is called with.
    invoke = re.search(r"\$printed = @\(& \$python (-X disable-remote-debug )?\$setup @Arguments\)", text)
    if invoke:
        prefix = X if invoke.group(1) else []
        calls = re.findall(r"Invoke-InstalledSetup -Home_ \$Home_ -Arguments (@\([^)]*\)|\$arguments)", text)
        for call in calls:
            if call == "$arguments":
                # Start-CurrentWatcher: setup --keep-state [--no-startup] [--watcher-was-stopped].
                stopped = "$arguments += '--watcher-was-stopped'" in text
                for startup in ([], ["--no-startup"]):
                    for was in ([], ["--watcher-was-stopped"]) if stopped else ([],):
                        lines.append(prefix + [SETUP, "setup", "--keep-state"] + startup + was)
            elif "'downgrade-state'" in call:
                targets = ["3", "4"] if "[string]$To" in call else re.findall(r"'--to', '([0-9])'", call)
                # The only values Convert-StateForOlder passes: it refuses any other -To before the call.
                if targets == ["3", "4"] and "if ($To -ne 3 -and $To -ne 4)" not in text:
                    raise SystemExit("a bootstrap passes -To without the 3-or-4 guard; read it again")
                for target in targets:
                    lines.append(prefix + [SETUP, "downgrade-state", "--to", target, "--stop-watcher"])
            else:
                lines.append(prefix + [SETUP] + re.findall(r"'([^']*)'", call))
    never = []
    compat = re.search(r"& \$Python (-X disable-remote-debug )?-c \$code \$Source --home \$Home_ compat-import", text)
    if compat:
        guarded = "Join-Path $Source 'codex_auto_resume\\controlcli.py'" in text
        if not guarded:
            raise SystemExit("a bootstrap starts the compatibility import without the controlcli.py guard")
        never.append((X if compat.group(1) else []) + ["-c", "<code>", r"{home}\app\src", "--home", "{home}",
                                                        "compat-import", "--file", "<file>", "--origin", "main"])
    return lines, never


def plugin_setup_lines(text: str) -> list[list[str]]:
    lines = []
    if re.search(r"def watcher_command\(home: Path\) -> str:\s+return startup\.command_line\(home / LAUNCHER_NAME, None,", text):
        lines.append([LAUNCHER, "run"])
    notify = re.search(r"def notification_command\([^)]*\) -> str:.*?argv = \[([^\]]*)\]", text, re.S)
    if notify:
        if 'str(home / LAUNCHER_NAME), "activate"' not in notify.group(1):
            raise SystemExit("notification_command names something else; read it again")
        lines.append((X if "NO_REMOTE_DEBUG" in notify.group(1) else []) + [LAUNCHER, "activate", "{uri}"])
    if 'LAUNCHER_NAME = "watcher-launcher.py"' not in text:
        raise SystemExit("plugin_setup.py names another launcher; read it again")
    return lines


def startup_lines(text: str) -> list[list[str]]:
    lines = []
    run = re.search(r"def command_line\(.*?argv\.append\(\"run\"\)", text, re.S)
    if run:
        lines.append([ENTRY, "--home", "{home}", "run"])
    protocol = re.search(r"def protocol_command_line\(.*?argv = \[([^\]]*)\]", text, re.S)
    if protocol:
        if '"--quiet", "activate"' not in protocol.group(1):
            raise SystemExit("protocol_command_line writes something else; read it again")
        lines.append((X if "NO_REMOTE_DEBUG" in protocol.group(1) else []) +
                     [ENTRY, "--home", "{home}", "--quiet", "activate", "{uri}"])
    return lines


def mcp_lines(text: str) -> list[list[str]]:
    code = re.search(r'string code = ((?:"[^"]*"\s*\+?\s*)+);', text)
    arguments = re.search(r'info\.Arguments = "([^"]*)-c " \+ Quote\(code\) \+ " " \+ Quote\(source\) \+\s*'
                          r'" --home " \+ Quote\(home\);', text)
    if not code or not arguments:
        raise SystemExit("McpLauncher.cs starts the server another way; read it again")
    joined = "".join(re.findall(r'"([^"]*)"', code.group(1)))
    return [arguments.group(1).split() + ["-c", joined, r"{home}\app\src", "--home", "{home}"]]


def collect(refs: list[tuple[str, str]]) -> tuple[dict, dict]:
    """{(program, tuple(argv)): [labels]} for what car-legacy accepts, and the same for what it can never be given."""
    table: dict = {}
    never: dict = {}
    for label, ref in refs:
        def show(path: str) -> str | None:
            return git("show", "%s:%s" % (ref, path))
        bootstrap = show("scripts/bootstrap.ps1")
        if bootstrap is None:
            continue
        found: list[tuple[str, list[str]]] = []
        console, unreachable = bootstrap_lines(bootstrap)
        found += [("python.exe", line) for line in console]
        for line in unreachable:
            never.setdefault(("python.exe", tuple(line)), []).append(label)
        setup = show("scripts/plugin_setup.py")
        if setup is not None:
            found += [("pythonw.exe", line) for line in plugin_setup_lines(setup)]
        startup = show("src/codex_auto_resume/startup.py")
        if startup is not None:
            found += [("pythonw.exe", line) for line in startup_lines(startup)]
        launcher = show("gui/McpLauncher.cs")
        if launcher is not None:
            found += [("python.exe", line) for line in mcp_lines(launcher)]
        for program, line in found:
            labels = table.setdefault((program, tuple(line)), [])
            if label not in labels:
                labels.append(label)
    return table, never


def render(table: dict) -> str:
    rows = []
    for (program, argv), labels in sorted(table.items()):
        for argument in argv:
            if "\t" in argument or "\n" in argument:
                raise SystemExit("an argument holds a tab or a line end: %r" % argument)
        rows.append("\t".join([program, labels[0], labels[-1], str(len(labels)), *argv]))
    return "".join(row + "\n" for row in rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--ref", action="append", default=[],
                        help="a branch or commit to read after the tags (its commit names it)")
    args = parser.parse_args(argv)
    refs = [(tag, tag) for tag in tags()]
    if not refs:
        raise SystemExit("no tag from v0.5.2 on is in this checkout; fetch the tags")
    for ref in args.ref:
        commit = (git("rev-parse", "--short=9", ref) or "").strip()
        if not commit:
            raise SystemExit("no such ref: %s" % ref)
        refs.append(("%s@%s" % (ref, commit), ref))
    table, never = collect(refs)
    text = render(table)
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(text.encode("utf-8"))
        print("wrote %d lines from %d refs (%s to %s) to %s" % (len(table), len(refs), refs[0][0], refs[-1][0],
                                                               OUT.relative_to(ROOT).as_posix()))
    elif args.check:
        # The tags alone decide the file: a --ref adds rows the committed file need not have.
        current = OUT.read_bytes().decode("utf-8") if OUT.is_file() else ""
        if current != text:
            print("%s is not what the tags say; run rust/tools/legacy_lines.py --write" % OUT.relative_to(ROOT).as_posix())
            return 1
        print("published lines: %d, from %d refs, as the file has them" % (len(table), len(refs)))
    else:
        sys.stdout.write(text)
    for (program, argv), labels in sorted(never.items()):
        print("never reached (guarded by controlcli.py): %s %s  [%s..%s]" % (program, " ".join(argv), labels[0],
                                                                            labels[-1]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
