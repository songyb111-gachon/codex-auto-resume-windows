"""Prove that every published Python updater takes a Rust-shaped archive (D9), by one of its two means.

  (a) The compatibility entry: every bootstrap from v0.5.2 names the archive the build wrote and accepts it with its own
      Test-Archive, exactly as build/legacy_bootstraps.py holds the Python release (that module's `check`, unchanged).
      It then runs the archive's install\\install.ps1 - the migration, seat S8.2's.
  (b) The setup handover: a bootstrap that knows setup-handover.json (Read-SetupHandover, the v0.6.26 final's) holds the
      archive to its Test-Archive first, because the archive carries install/install.ps1 and payload/runtime/python.exe
      (BRIDGE.md section 2.3), then reads the marker - its format, the version and edition the run picked, a program of
      the archive by that exact name - and, unpacked, finds that program inside the folder with no link on the way, a
      PE image of the Windows GUI subsystem (Resolve-SetupProgram). It would then start it.

Every tag from v0.5.2 below the version built is asked, and each bootstrap that has Read-SetupHandover is asked (b) as
well; `--ref` adds a branch tip after the tags (the v0.6.26 final's updater before its tag exists). Only the bootstraps'
own function definitions run, from git, in Windows PowerShell 5.1 as the settings window starts them, with no network
and against nothing but the archives and a temporary folder: no installation, no registry, nothing started.

    python build/rust_legacy_bootstraps.py --dist build/dist/rust --version 0.6.27-alpha [--ref dev]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import legacy_bootstraps as legacy  # noqa: E402
import rust_release  # noqa: E402

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
            $answer.program = $program.Substring($unpacked.Length).TrimStart('\')
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


def run(dist: Path, version: str, refs=()) -> tuple[list, dict]:
    """(findings, the means each bootstrap takes the archives by)."""
    standard = dist / rust_release.archive_name("standard", version)
    advanced = dist / rust_release.archive_name("advanced", version)
    for archive in (standard, advanced):
        if not archive.is_file():
            raise SystemExit("missing %s - build it with build/rust_release.py" % archive)
    tags = legacy.published(ROOT, version)
    if not tags:
        raise SystemExit("no tag from v0.5.2 on is in this checkout; fetch the tags (fetch-depth: 0)")
    bootstraps = [legacy.lift(ROOT, tag) for tag in tags] + [lift_ref(ref) for ref in refs]
    found = legacy.check(bootstraps, version, standard, advanced)
    bridged = [bootstrap for bootstrap in bootstraps if knows_handover(bootstrap)]
    found += check_handover(bridged, version, standard, advanced)
    means = {bootstrap.tag: ("b" if knows_handover(bootstrap) else "a") for bootstrap in bootstraps}
    return found, means


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prove every published updater takes the Rust-shaped archives.")
    parser.add_argument("--dist", default=str(rust_release.OUT))
    parser.add_argument("--version", default=None)
    parser.add_argument("--ref", action="append", default=[],
                        help="a branch or commit whose bootstrap is asked after the tags (e.g. dev)")
    args = parser.parse_args(argv)
    version = args.version or rust_release.version()
    found, means = run(Path(args.dist), version, args.ref)
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
    print("  both editions taken by all %d" % len(tags))
    return 0


if __name__ == "__main__":
    sys.exit(main())
