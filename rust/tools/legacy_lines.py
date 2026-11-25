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
import ast
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


class Blobs:
    """`git show <ref>:<path>` through one `git cat-file --batch`: a git process per file took minutes for 64 tags."""

    def __init__(self):
        self.process = subprocess.Popen(["git", "-C", str(ROOT), "cat-file", "--batch"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, creationflags=NO_WINDOW)

    def show(self, ref: str, path: str) -> str | None:
        self.process.stdin.write(("%s:%s\n" % (ref, path)).encode("utf-8"))
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode("utf-8", "replace").split()
        if len(header) != 3 or header[1] != "blob":
            return None
        body = self.process.stdout.read(int(header[2]) + 1)[:-1]
        return body.decode("utf-8", "replace")

    def close(self):
        self.process.stdin.close()
        self.process.wait()


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


# ------------------------------------------------------------------------------- the skill's and documents' commands

SKILL = "skills/codex-auto-resume/SKILL.md"
# The program and script every skill names; `<command>` is one row of its Commands table.
SKILL_RUN = (r"%USERPROFILE%\.codex-auto-resume\runtime\python.exe "
             r"%USERPROFILE%\.codex-auto-resume\app\scripts\plugin_setup.py <command>")
# A document line that tells someone to run the installation's runtime\python.exe with plugin_setup.py.
RUNS_SETUP = re.compile(r"runtime[\\/]pythonw?\.exe\S*\s+\S*plugin_setup\.py", re.I)
# The placeholders a Commands table writes for a value (`cancel <thread-uuid>`).
PLACEHOLDER = re.compile(r"<[a-z][a-z-]*>")


# The refs `collect` reads, so that one git grep answers `matching` for all of them at once.
REFS: list[str] = []
_MATCHES: dict = {}


def matching(ref: str, pattern: str, *paths: str) -> list[str]:
    """The files of `ref` under `paths` whose text matches `pattern`: one git grep over every ref in REFS, the first
    time a pattern is asked about (a git grep per ref and pattern took minutes)."""
    key = (pattern, paths)
    if key not in _MATCHES:
        everyone = REFS if ref in REFS else [ref]
        listed = git("grep", "-l", "-I", "-i", "-E", pattern, *everyone, "--", *paths) or ""
        found: dict = {}
        for line in listed.splitlines():
            where, _, path = line.partition(":")
            if path:
                found.setdefault(where, []).append(path)
        _MATCHES[key] = (everyone, found)
    everyone, found = _MATCHES[key]
    if ref not in everyone:
        _MATCHES.pop(key)
        return matching(ref, pattern, *paths)
    return found.get(ref, [])


def documents(ref: str) -> list[str]:
    """The shipped documents of a ref that name plugin_setup.py: the skills, README and docs, both languages."""
    return [path for path in matching(ref, r"plugin_setup\.py", "*.md")
            if path.startswith(("skills/", "docs/")) or "/" not in path]


def table_commands(text: str) -> list[list[str]]:
    """The Commands table's backticked commands, as words (`cancel <thread-uuid>` -> ["cancel", "<thread-uuid>"])."""
    commands = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and len(cells[1]) > 2 and cells[1].startswith("`") and cells[1].endswith("`"):
            commands.append(cells[1].strip("`").split())
    return commands


def document_commands(path: str, text: str) -> list[list[str]]:
    """The plugin_setup.py commands a document tells someone to run through the installation's runtime\\python.exe."""
    commands = []
    for line in text.splitlines():
        found = RUNS_SETUP.search(line)
        if not found:
            continue
        if re.search(r"pythonw\.exe", found.group(0), re.I):
            raise SystemExit("%s tells someone to run pythonw.exe with plugin_setup.py; read it again" % path)
        if SKILL_RUN in line:
            rest = line.split(SKILL_RUN, 1)[1].strip()
            if rest not in ("", "```"):
                raise SystemExit("%s adds %r after the skill's command line; read it again" % (path, rest))
            table = table_commands(text)
            if not table:
                raise SystemExit("%s names `<command>` without a Commands table; read it again" % path)
            commands += table
            continue
        after = line[found.end():].strip().strip("`").split()
        if not after or after[0].startswith("<"):
            raise SystemExit("%s runs plugin_setup.py in a way this reader does not know: %r" % (path, line))
        commands.append(after)
    return commands


def parser_shapes(setup: str) -> dict[str, list[list[str]]]:
    """{subcommand: [its argument shapes]} as build_parser in a tag's plugin_setup.py takes them. Each shape is the words
    after the subcommand: its positionals in order (`{value}`, or one of the choices), then none or one of its options
    (a flag alone; an option that takes a value as `<spelling> {value}`, for each of its spellings)."""
    tree = ast.parse(setup)
    build = next((node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "build_parser"),
                 None)
    if build is None:
        raise SystemExit("plugin_setup.py has no build_parser; read it again")
    named: dict[str, str] = {}
    arguments: dict[str, list[ast.Call]] = {}
    for statement in build.body:
        call = statement.value if isinstance(statement, (ast.Expr, ast.Assign)) else None
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        method = call.func.attr
        owner = call.func.value.id if isinstance(call.func.value, ast.Name) else None
        if method == "add_parser":
            name = ast.literal_eval(call.args[0])
            arguments.setdefault(name, [])
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    named[target.id] = name
        elif method == "add_argument" and owner in named:
            arguments[named[owner]].append(call)
    shapes: dict[str, list[list[str]]] = {}
    for name, calls in arguments.items():
        positional: list[list[str]] = [[]]
        options: list[list[str]] = []
        for call in calls:
            spellings = [ast.literal_eval(argument) for argument in call.args]
            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            if "nargs" in keywords:
                raise SystemExit("plugin_setup.py %s has an argument with nargs; read it again" % name)
            try:
                choices = [str(choice) for choice in ast.literal_eval(keywords["choices"])] if "choices" in keywords else None
            except ValueError:
                choices = None  # a name (edition.EDITIONS): an option no published command uses
            if not spellings[0].startswith("-"):
                positional = [words + [choice] for words in positional for choice in (choices or ["{value}"])]
                continue
            action = ast.literal_eval(keywords["action"]) if "action" in keywords else "store"
            if action not in ("store", "store_true"):
                raise SystemExit("plugin_setup.py %s has an option of action %r; read it again" % (name, action))
            for spelling in spellings:
                if action == "store_true":
                    options.append([spelling])
                else:
                    options += [[spelling, value] for value in (choices or ["{value}"])]
        shapes[name] = [words + option for words in positional for option in [[]] + options]
    return shapes


def command_lines(commands: list[list[str]], setup: str, where: str) -> list[list[str]]:
    """The plugin_setup.py lines for `commands` (each a published command's words), in every shape the tag's parser
    takes their subcommands: the published words must be one of those shapes, placeholders standing for `{value}`."""
    shapes = parser_shapes(setup)
    lines = []
    for words in commands:
        name = words[0]
        if name not in shapes:
            raise SystemExit("%s publishes `%s`, which that tag's plugin_setup.py does not have" % (where, " ".join(words)))
        written = [("{value}" if PLACEHOLDER.fullmatch(word) else word) for word in words[1:]]
        if written not in shapes[name]:
            raise SystemExit("%s publishes `%s`, which that tag's parser does not take" % (where, " ".join(words)))
        for shape in shapes[name]:
            lines.append([SETUP, name] + shape)
    return lines


def shortcut_lines(text: str) -> list[list[str]]:
    """The Start-menu (and Desktop) shortcut `install` makes when the home has no settings window: pythonw.exe (the
    runtime's, beside sys.executable) [-X ...] <watcher-launcher.py, or app\\src\\auto_resume.py> --home <home> status."""
    found = re.search(r'arguments = " "\.join\(startup\.quote_argument\(argument\) for argument in\s+'
                      r'\((\*startup\.NO_REMOTE_DEBUG, )?str\(target\), "--home", str\((?:app\.)?paths\.home\), '
                      r'"status"\)\)', text)
    if not found:
        return []
    if not re.search(r'launcher = (?:app\.)?paths\.home / "watcher-launcher\.py"\s+'
                     r'target = launcher if launcher\.is_file\(\) else (?:app\.)?paths\.entry_script', text):
        raise SystemExit("the shortcut names another script; read it again")
    if "target=startup.python_launcher()" not in text and '"target": startup.python_launcher()' not in text:
        raise SystemExit("the shortcut starts another program; read it again")
    prefix = X if found.group(1) else []
    return [prefix + [script, "--home", "{home}", "status"] for script in (LAUNCHER, ENTRY)]


def window_lines(texts: dict[str, str]) -> tuple[list[list[str]], list[list[str]]]:
    """(python.exe lines, lines car-legacy never takes) of the settings window's own children of runtime\\python.exe."""
    lines, never = [], []
    for path, text in sorted(texts.items()):
        for found in re.finditer(r'new ProcessStartInfo\(python, ([^;]*)\);', text):
            spelled = found.group(1)
            prefix = X if "NoRemoteDebug +" in spelled else []
            repair = re.fullmatch(r'(?:Bridge\.NoRemoteDebug \+ )?Bridge\.Quote\(setup\) \+ " setup --keep-state"', spelled)
            shortcut = re.fullmatch(r'(?:NoRemoteDebug \+ )?"\\"" \+ setup \+ "\\" desktop-shortcut " \+ '
                                    r'\(make \? "make" : "remove"\)', spelled)
            if repair:
                lines.append(prefix + [SETUP, "setup", "--keep-state"])
            elif shortcut:
                lines += [prefix + [SETUP, "desktop-shortcut", action] for action in ("make", "remove")]
            else:
                raise SystemExit("%s starts runtime\\python.exe another way: %s; read it again" % (path, spelled))
            if not re.search(r'string setup = Path\.Combine\([^;]*"plugin_setup\.py"\);', text):
                raise SystemExit("%s names another setup script; read it again" % path)
        if "from codex_auto_resume.controlcli import main" in text and "info.FileName = python;" in text:
            never.append((X if "NoRemoteDebug + \"-c \"" in text or ".Append(NoRemoteDebug)" in text else [])
                         + ["-c", "<controlcli code>", r"{home}\app\src", "<command>"])
        if "from codex_auto_resume_advanced.hook import main" in text:
            # The advanced Stop hook's launcher (gui/HookLauncher.cs): refused, it relays nothing and ends 0, which is
            # the hook's one safe failure (the turn ends as it would have).
            never.append(["-I"] + (X if "-X disable-remote-debug -c" in text else [])
                         + ["-c", "<hook code>", r"{home}\app\src", "--home", "{home}"])
    return lines, never


def collect(refs: list[tuple[str, str]]) -> tuple[dict, dict]:
    """{(program, tuple(argv)): [labels]} for what car-legacy accepts, and the same for what it can never be given."""
    table: dict = {}
    never: dict = {}
    REFS[:] = [ref for _, ref in refs]
    _MATCHES.clear()
    blobs = Blobs()
    for label, ref in refs:
        def show(path: str) -> str | None:
            return blobs.show(ref, path)
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
        published = []
        for path in documents(ref):
            text = show(path)
            if text is not None:
                published += document_commands("%s:%s" % (label, path), text)
        if show(SKILL) is not None and not published:
            raise SystemExit("%s's skill names no command; read it again" % label)
        if published:
            if setup is None:
                raise SystemExit("%s publishes commands but has no plugin_setup.py" % label)
            found += [("python.exe", line) for line in command_lines(published, setup, label)]
        for path in ("src/codex_auto_resume/cli.py", "src/codex_auto_resume/commands/install.py"):
            text = show(path)
            if text is not None:
                found += [("pythonw.exe", line) for line in shortcut_lines(text)]
        window = {}
        for path in matching(ref, r"ProcessStartInfo\(python|info\.FileName = python|hook import main", "gui/*.cs"):
            if path.endswith(".cs"):
                text = show(path)
                if text is not None:
                    window[path] = text
        window_found, window_never = window_lines(window)
        found += [("python.exe", line) for line in window_found]
        for line in window_never:
            never.setdefault(("python.exe", tuple(line)), []).append(label)
        for program, line in found:
            labels = table.setdefault((program, tuple(line)), [])
            if label not in labels:
                labels.append(label)
    blobs.close()
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
        print("never taken (a -c line: the bootstrap's behind its controlcli.py guard, the old window's, the hook's): "
              "%s %s  [%s..%s]" % (program, " ".join(argv), labels[0],
                                                                            labels[-1]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
