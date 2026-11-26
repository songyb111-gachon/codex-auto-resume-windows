"""Prove that every published Python updater takes a Rust-shaped archive (D9), by one of its two means.

  (a) The compatibility entry: every bootstrap from v0.5.2 names the archive the build wrote and accepts it with its own
      Test-Archive, exactly as build/legacy_bootstraps.py holds the Python release (that module's `check`, unchanged).
      It then runs the archive's install\\install.ps1 - the migration, seat S8.2's.
  (b) The setup handover: a bootstrap that knows setup-handover.json (Read-SetupHandover, the v0.6.26 final's) holds the
      archive to its Test-Archive first, because the archive carries install/install.ps1 and payload/runtime/python.exe
      (BRIDGE.md section 2.3), then reads the marker - its format, the version and edition the run picked, a program of
      the archive by that exact name - and, unpacked, finds that program inside the folder with no link on the way, a
      PE image of the Windows GUI subsystem (Resolve-SetupProgram). It would then start it.
  (c) The compatibility entry run: every runtime\\python.exe line a bootstrap starts against the INSTALLED home (its
      repair branch, Invoke-InstalledSetup and what calls it: rust/tools/legacy_lines.py's bootstrap_lines of that
      tag) is run for real, by the tag's own Invoke-InstalledSetup where it has one (lifted from git, as (b) lifts its
      functions; without -Outside) or by the call operator over the same argument array where it has none, against a
      scratch installation made of the archive's runtime\\python.exe (car-legacy) and app\\bin\\codex-auto-resume.exe (the
      core), in a folder whose name holds a space, the home given with and without a trailing separator. Each line must
      reach the core: the stub core ends with 3, car-legacy's refusal with 2 and a missing program with 1.

Every tag from v0.5.2 below the version built is asked, and each bootstrap that has Read-SetupHandover is asked (b) as
well; `--ref` adds a branch tip or a tag after the tags. The release check names the v0.6.26 final's tag
(`--ref v0.6.26`, seat S8.2): from the tag on it is among the published ones, and a ref whose commit a listed tag has is
asked once, under the tag's name - so the check holds both before the tag is fetched and after. Only the bootstraps'
own function definitions run, from git, in Windows PowerShell 5.1 as the settings window starts them, with no network
and against nothing but the archives and a temporary folder: no installation, no registry, nothing started.

    python build/rust_legacy_bootstraps.py --dist build/dist/rust --version 0.6.27-alpha --ref v0.6.26
    python build/rust_legacy_bootstraps.py --entry-from rust/target/release      # (c) alone, from a cargo build
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import legacy_bootstraps as legacy  # noqa: E402
import rust_release  # noqa: E402

sys.path.insert(0, str(ROOT / "rust" / "tools"))
import legacy_lines  # noqa: E402

# What the stub core ends every command with (car-bin's NOT_PORTED): a line car-legacy handed on.
REACHED = 3

ENTRY = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$lifted = @{}
$answers = @()
foreach ($case in (ConvertFrom-Json (Get-Content -LiteralPath $env:CAR_CASES -Raw -Encoding UTF8))) {
    $answers += & {
        param($case)
        $answer = [ordered]@{ index = $case.index; line = $case.line; home = $case.home; code = $null; error = $null }
        try {
            if ($case.function) {
                if (-not $lifted.ContainsKey($case.script)) {
                    $errors = $null
                    $ast = [System.Management.Automation.Language.Parser]::ParseFile($case.script, [ref]$null, [ref]$errors)
                    if ($errors -and $errors.Count) { throw 'its bootstrap.ps1 does not parse' }
                    $node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                                       $n.Name -eq 'Invoke-InstalledSetup' }, $true)
                    $lifted[$case.script] = $node.Extent.Text
                }
                Invoke-Expression $lifted[$case.script]
                $done = Invoke-InstalledSetup -Home_ $case.home -Arguments @($case.words)
                $answer.code = $done.Code
            } else {
                # The repair branch of v0.5.2-v0.6.11: `& $python @arguments` over $setup and the words.
                $python = Join-Path $case.home 'runtime\python.exe'
                $setup = Join-Path $case.home 'app\scripts\plugin_setup.py'
                $arguments = @()
                if ($case.x) { $arguments += @('-X', 'disable-remote-debug') }
                $arguments += @($setup) + @($case.words)
                $ErrorActionPreference = 'Continue'
                $global:LASTEXITCODE = $null
                $null = @(& $python @arguments)
                $answer.code = $LASTEXITCODE
            }
        } catch {
            $answer.error = [string]$_.Exception.Message
        }
        [pscustomobject]$answer
    } $case
}
ConvertTo-Json -InputObject @($answers) -Depth 4 -Compress
"""

HANDOVER = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
Add-Type -AssemblyName System.IO.Compression.FileSystem
$answers = @()
foreach ($case in (ConvertFrom-Json (Get-Content -LiteralPath $env:CAR_CASES -Raw -Encoding UTF8))) {
    $answers += & {
        param($case)
        $answer = [ordered]@{ index = $case.index; edition = $case.edition; stage = 'parse'; setup = $null
                              python = $null; program = $null; error = $null }
        try {
            $errors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile($case.script, [ref]$null, [ref]$errors)
            if ($errors -and $errors.Count) { throw 'its bootstrap.ps1 does not parse' }
            foreach ($node in $ast.FindAll({ param($n)
                    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
                Invoke-Expression $node.Extent.Text
            }
            $answer.stage = 'contents'
            Test-Archive -Zip $case.archive -Version $case.version -Edition $case.edition
            $answer.stage = 'marker'
            $handover = Read-SetupHandover -Zip $case.archive -Version $case.version -Edition $case.edition
            if ($null -eq $handover) { throw 'it finds no setup handover in the archive' }
            $answer.setup = $handover.Setup
            $answer.python = [bool]$handover.Python
            $answer.stage = 'program'
            $unpacked = Join-Path $case.work ('unpacked-' + $case.index + '-' + $case.edition)
            [IO.Compression.ZipFile]::ExtractToDirectory((Resolve-Path -LiteralPath $case.archive), $unpacked)
            $program = Resolve-SetupProgram -Unpacked $unpacked -Setup $handover.Setup
            # Resolve-SetupProgram answers through [IO.Path]::GetFullPath, which on Windows PowerShell spells an 8.3 name
            # long (a CI runner's TEMP is an 8.3 name, RUNNER~1): the path inside is measured from the same full spelling.
            $root = [IO.Path]::GetFullPath($unpacked).TrimEnd('\')
            if (-not $program.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw ('the setup program is outside the unpacked archive: ' + $program)
            }
            $answer.program = $program.Substring($root.Length).TrimStart('\')
            $answer.stage = 'handed over'
        } catch {
            $answer.error = [string]$_.Exception.Message
        }
        [pscustomobject]$answer
    } $case
}
ConvertTo-Json -InputObject @($answers) -Depth 4 -Compress
"""


def knows_handover(bootstrap: legacy.Bootstrap) -> bool:
    return b"function Read-SetupHandover" in bootstrap.script and b"function Resolve-SetupProgram" in bootstrap.script


def lift_ref(ref: str) -> legacy.Bootstrap:
    commit = legacy._git(ROOT, "rev-parse", "--short=9", ref).decode("utf-8").strip()
    return legacy.Bootstrap("%s@%s" % (ref, commit), legacy._git(ROOT, "show", ref + ":scripts/bootstrap.ps1"),
                            legacy._git(ROOT, "show", ref + ":scripts/release.json"))


def commit_of(ref: str) -> str:
    return legacy._git(ROOT, "rev-parse", "%s^{commit}" % ref).decode("utf-8").strip()


def lift_refs(refs, tags) -> tuple[list, list]:
    """The bootstraps of `refs` that no tag in `tags` already is (by commit), and the refs that were, said once."""
    listed = {commit_of(tag) for tag in tags}
    lifted, already = [], []
    for ref in refs:
        if commit_of(ref) in listed:
            already.append(ref)
        else:
            lifted.append(lift_ref(ref))
    return lifted, already


def check_handover(bootstraps, version: str, standard: Path, advanced: Path) -> list:
    """Every finding of (b), as a sentence: none means each bootstrap given hands both archives over to their setup
    program after its Test-Archive accepted them."""
    if not legacy.POWERSHELL.is_file():
        raise SystemExit("the published bootstraps are Windows PowerShell; %s is missing" % legacy.POWERSHELL)
    archives = {"standard": standard, "advanced": advanced}
    found, cases = [], []
    with tempfile.TemporaryDirectory(prefix="rust-handover-") as work:
        for index, bootstrap in enumerate(bootstraps):
            script = Path(work) / ("%d.ps1" % index)
            script.write_bytes(bootstrap.script)
            for edition, archive in archives.items():
                cases.append({"index": index, "edition": edition, "version": version, "script": str(script),
                              "archive": str(archive), "work": work})
        if not cases:
            return found
        (Path(work) / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        done = subprocess.run([str(legacy.POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", HANDOVER],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                              creationflags=legacy.NO_WINDOW,
                              env=dict(os.environ, CAR_CASES=str(Path(work) / "cases.json")))
    if done.returncode != 0 or not done.stdout.strip():
        raise SystemExit("the bootstraps could not be run:\n%s" % (done.stderr or done.stdout)[-2000:])
    answers = json.loads(done.stdout)
    if len(answers) != len(cases):
        raise SystemExit("asked about %d cases and heard about %d" % (len(cases), len(answers)))
    expected = rust_release.SETUP.replace("/", "\\")
    for answer in answers:
        tag = bootstraps[answer["index"]].tag
        edition = answer["edition"]
        if answer["stage"] != "handed over":
            found.append("%s does not hand the %s archive over (at %s): %s" % (tag, edition, answer["stage"],
                                                                               answer["error"]))
            continue
        if answer["setup"] != rust_release.SETUP or answer["program"] != expected or answer["python"] is not True:
            found.append("%s hands the %s archive over to %s (%s), not %s" % (tag, edition, answer["setup"],
                                                                             answer["program"], rust_release.SETUP))
    return found


def entry_cases(bootstraps, homes: list[str], scripts: Path) -> list[dict]:
    """One case per (bootstrap, python.exe line its own code starts against the installed home, spelling of the home)."""
    cases = []
    for index, bootstrap in enumerate(bootstraps):
        text = bootstrap.script.decode("utf-8-sig", "replace")
        lines, _ = legacy_lines.bootstrap_lines(text)
        if not lines:
            continue
        script = scripts / ("%d.ps1" % index)
        script.write_bytes(bootstrap.script)
        function = "function Invoke-InstalledSetup" in text
        for line in lines:
            x = line[:2] == legacy_lines.X
            words = line[(2 if x else 0):]
            if words[0] != legacy_lines.SETUP:
                raise SystemExit("%s starts runtime\\python.exe with %r; read it again" % (bootstrap.tag, line))
            for home in homes:
                cases.append({"index": index, "line": " ".join(line), "home": home, "words": words[1:], "x": x,
                              "function": function, "script": str(script)})
    return cases


def check_entry(bootstraps, runtime: Path, core: Path) -> list:
    """Every finding of (c), as a sentence: none means each bootstrap's own runtime\\python.exe lines reach the core
    through car-legacy, in a home whose name holds a space, with and without a trailing separator."""
    if not legacy.POWERSHELL.is_file():
        raise SystemExit("the published bootstraps are Windows PowerShell; %s is missing" % legacy.POWERSHELL)
    found = []
    with tempfile.TemporaryDirectory(prefix="rust-entry-") as work:
        home = Path(work) / "install home"
        for folder in ("runtime", "app\\bin", "app\\scripts", "app\\src", "profile", "local", "codex"):
            (home / folder if folder not in ("profile", "local", "codex") else Path(work) / folder).mkdir(parents=True)
        shutil.copy2(runtime, home / "runtime" / "python.exe")
        shutil.copy2(core, home / "app" / "bin" / "codex-auto-resume.exe")
        (home / "app" / "scripts" / "plugin_setup.py").write_text("# stub\n", encoding="utf-8")
        scripts = Path(work) / "scripts"
        scripts.mkdir()
        cases = entry_cases(bootstraps, [str(home), str(home) + "\\"], scripts)
        if not cases:
            raise SystemExit("no bootstrap starts runtime\\python.exe: nothing to prove")
        (Path(work) / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        # A scratch profile, local data and Codex home for whatever the core is: nothing real is read or written.
        environment = dict(os.environ, CAR_CASES=str(Path(work) / "cases.json"), USERPROFILE=str(Path(work) / "profile"),
                           LOCALAPPDATA=str(Path(work) / "local"), APPDATA=str(Path(work) / "local"),
                           CODEX_HOME=str(Path(work) / "codex"), CODEX_AUTO_RESUME_HOME=str(home),
                           CODEX_AUTO_RESUME_PLUGIN_HOME=str(home))
        done = subprocess.run([str(legacy.POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", ENTRY],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                              creationflags=legacy.NO_WINDOW, env=environment, cwd=work)
    if done.returncode != 0 or not done.stdout.strip():
        raise SystemExit("the bootstraps' lines could not be run:\n%s" % (done.stderr or done.stdout)[-2000:])
    answers = json.loads(done.stdout)
    if len(answers) != len(cases):
        raise SystemExit("asked about %d lines and heard about %d" % (len(cases), len(answers)))
    for answer in answers:
        if answer["error"] is not None or answer["code"] != REACHED:
            what = {2: "refused by car-legacy", 1: "missing the core"}.get(answer["code"], "code %r" % answer["code"])
            found.append("%s: `%s` (home %s) does not reach the core: %s%s"
                         % (bootstraps[answer["index"]].tag, answer["line"], answer["home"], what,
                            "" if answer["error"] is None else " (%s)" % answer["error"]))
    return found


def entry_from_archive(standard: Path, work: Path) -> tuple[Path, Path]:
    """The archive's runtime\\python.exe and app\\bin\\codex-auto-resume.exe, unpacked into `work`."""
    with zipfile.ZipFile(standard) as archive:
        paths = []
        for name in ("payload/runtime/python.exe", "payload/app/bin/codex-auto-resume.exe"):
            target = work / name.rsplit("/", 1)[1]
            target.write_bytes(archive.read(name))
            paths.append(target)
    return paths[0], paths[1]


def run(dist: Path, version: str, refs=(), entry: bool = True, already: list | None = None) -> tuple[list, dict]:
    """(findings, the means each bootstrap takes the archives by). `entry` False leaves (c) out: for archives of
    stand-in binaries, which cannot run."""
    standard = dist / rust_release.archive_name("standard", version)
    advanced = dist / rust_release.archive_name("advanced", version)
    for archive in (standard, advanced):
        if not archive.is_file():
            raise SystemExit("missing %s - build it with build/rust_release.py" % archive)
    tags = legacy.published(ROOT, version)
    if not tags:
        raise SystemExit("no tag from v0.5.2 on is in this checkout; fetch the tags (fetch-depth: 0)")
    lifted, repeated = lift_refs(refs, tags)
    if already is not None:
        already.extend(repeated)
    bootstraps = [legacy.lift(ROOT, tag) for tag in tags] + lifted
    found = legacy.check(bootstraps, version, standard, advanced)
    bridged = [bootstrap for bootstrap in bootstraps if knows_handover(bootstrap)]
    found += check_handover(bridged, version, standard, advanced)
    if entry:
        with tempfile.TemporaryDirectory(prefix="rust-entry-bin-") as work:
            runtime, core = entry_from_archive(standard, Path(work))
            found += check_entry(bootstraps, runtime, core)
    means = {bootstrap.tag: ("b" if knows_handover(bootstrap) else "a") for bootstrap in bootstraps}
    return found, means


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prove every published updater takes the Rust-shaped archives.")
    parser.add_argument("--dist", default=str(rust_release.OUT))
    parser.add_argument("--version", default=None)
    parser.add_argument("--ref", action="append", default=[],
                        help="a branch or commit whose bootstrap is asked after the tags (e.g. dev)")
    parser.add_argument("--entry-from", default=None,
                        help="(c) alone: python.exe and codex-auto-resume.exe from this folder (a cargo target\\release)")
    args = parser.parse_args(argv)
    if args.entry_from:
        folder = Path(args.entry_from)
        tags = legacy.published(ROOT, args.version or rust_release.version())
        lifted, repeated = lift_refs(args.ref, tags)
        for ref in repeated:
            print("--ref %s is a published tag's commit, asked once among the tags" % ref)
        bootstraps = [legacy.lift(ROOT, tag) for tag in tags] + lifted
        found = check_entry(bootstraps, folder / "python.exe", folder / "codex-auto-resume.exe")
        print("(c) the compatibility entry run: the bootstraps of %s to %s" % (bootstraps[0].tag, bootstraps[-1].tag))
        for line in found:
            print("  " + line)
        if found:
            return 1
        print("  every line of all %d reaches the core" % len(bootstraps))
        return 0
    version = args.version or rust_release.version()
    repeated: list = []
    found, means = run(Path(args.dist), version, args.ref, already=repeated)
    for ref in repeated:
        print("--ref %s is a published tag's commit, asked once among the tags" % ref)
    tags = list(means)
    by = {kind: [tag for tag in tags if means[tag] == kind] for kind in ("a", "b")}
    print("the bootstraps of %s to %s, on the Rust-shaped archives of v%s" % (tags[0], tags[-1], version))
    for kind, label in (("a", "(a) the compatibility entry"), ("b", "(b) the setup handover")):
        listed = by[kind]
        print("  %s: %d%s" % (label, len(listed), (" - %s to %s" % (listed[0], listed[-1])) if listed else ""))
    readers = legacy.readers([legacy.lift(ROOT, tag) for tag in legacy.published(ROOT, version)], version)
    refusing = [tag for tag, answer in readers.items() if answer == "refuses"]
    if refusing:
        print("  these cannot read v%s as an installed version (they compare no newer one): %s"
              % (version, ", ".join(refusing)))
    for line in found:
        print("  " + line)
    if found:
        print("an installed copy would not update to this release")
        return 1
    print("  both editions taken by all %d, and every runtime\\python.exe line of each reaches the core (c)" % len(tags))
    return 0


if __name__ == "__main__":
    sys.exit(main())
