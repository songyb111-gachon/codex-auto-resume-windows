"""Prove that every bootstrap already installed on people's machines takes this release.

An installation updates itself with the copy of scripts/bootstrap.ps1 it was installed with,
never with this one: the settings window runs <home>\\app\\scripts\\bootstrap.ps1
(gui/DashboardMaintenance.cs). That copy names the archive it downloads from its own
scripts/release.json and checks what arrives with its own Test-Archive, and neither can be
changed any more. So a release that renamed the standard archive, dropped an entry an old
Test-Archive requires, or added one it refuses would be a release every installed copy stops
updating to - and no test of this tree's bootstrap would notice, because this tree's bootstrap
is not the one that runs.

For every tag from v0.5.2, the first release whose bootstrap fetched an archive, up to the
version being built, this takes out of git - no network, and nothing of the working tree - that
tag's own

  * statement that names the archive, run against that tag's release.json for this version:
    it has to be the name the build wrote;
  * Test-Archive, run on the archive the build wrote: it has to accept it.

A tag whose release.json knows the advanced edition (v0.6.11 on) is held to the advanced archive
the same way, with its Test-Archive asked for that edition: an advanced installation updates
within its edition.

Run in the release build job after the archives are built, with the tags fetched:

    python build/legacy_bootstraps.py [--dist build/dist]

The old code runs in Windows PowerShell 5.1, which is what the settings window starts it with.
tests/test_legacy_bootstraps.py runs the same checks on archives made for the purpose.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import make_release  # noqa: E402

# The first release whose bootstrap fetched an archive: v0.5.0 and v0.5.1 have no
# scripts/bootstrap.ps1 at all.
FIRST = (0, 5, 2)
# How this project tags a release: vMAJOR.MINOR.PATCH, or a planned pre-release with one word
# after it (v0.6.9-alpha, v0.6.6-beta). Anything else is not a release of ours.
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([a-z]+))?$")
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")

# Each case is one tag's bootstrap asked about one edition's archive. Every function the script
# defines is defined - definitions only, nothing of the script runs - in a scope of its own, so
# one tag's functions never answer for another's. The naming statement is found by what it is
# rather than by its line, and run the way the script runs it: with its own release.json read as
# its Read-Json reads it, and the version under both names a bootstrap has given it ($version to
# v0.5.7, $target from v0.6.0). From v0.6.11 it also reads the edition the run settled on.
PROBE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$answers = @()
foreach ($case in (ConvertFrom-Json (Get-Content -LiteralPath $env:CAR_CASES -Raw -Encoding UTF8))) {
    $answers += & {
        param($case)
        $answer = [ordered]@{ index = $case.index; edition = $case.edition; stage = 'parse'
                              name = $null; error = $null }
        try {
            $errors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile($case.script, [ref]$null, [ref]$errors)
            if ($errors -and $errors.Count) { throw 'its bootstrap.ps1 does not parse' }
            foreach ($node in $ast.FindAll({ param($n)
                    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
                Invoke-Expression $node.Extent.Text
            }
            $answer.stage = 'name'
            $naming = @($ast.FindAll({ param($n)
                    $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
                    $n.Left.Extent.Text -eq '$name' -and $n.Right.Extent.Text -like '*{version}*' }, $true))
            if ($naming.Count -ne 1) {
                throw ('it has ' + $naming.Count + ' statements that name the archive, not one')
            }
            $release = Get-Content -LiteralPath $case.release -Raw -Encoding UTF8 | ConvertFrom-Json
            $version = $case.version
            $target = $case.version
            $targetEdition = $case.edition
            Invoke-Expression $naming[0].Extent.Text
            $answer.name = $name
            $answer.stage = 'contents'
            if ($case.edition -eq 'standard') { Test-Archive -Zip $case.archive -Version $case.version }
            else { Test-Archive -Zip $case.archive -Version $case.version -Edition $case.edition }
            $answer.stage = 'accepted'
        } catch {
            $answer.error = [string]$_.Exception.Message
        }
        [pscustomobject]$answer
    } $case
}
ConvertTo-Json -InputObject @($answers) -Depth 4 -Compress
"""


@dataclass(frozen=True)
class Bootstrap:
    """One bootstrap as it was published: its tag, and the two files that decide what it takes."""
    tag: str
    script: bytes
    release: bytes

    def knows_advanced(self) -> bool:
        return "advanced" in json.loads(self.release.decode("utf-8-sig"))


def order(version: str) -> tuple:
    """A version as something to sort by: 0.6.9-alpha before 0.6.9, and 0.6.10 after 0.6.9."""
    match = TAG.match("v" + version)
    if not match:
        raise ValueError("not a version this product uses: %s" % version)
    major, minor, patch, stage = match.groups()
    return (int(major), int(minor), int(patch), 0 if stage else 1, stage or "")


def _git(root: Path, *arguments: str) -> bytes:
    done = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, timeout=120)
    if done.returncode != 0:
        raise SystemExit("git %s failed: %s" % (" ".join(arguments),
                                               done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout


def published(root: Path, before: str) -> list[str]:
    """Every tag from v0.5.2 up to, and not including, the version `before`, oldest first.

    A pre-release counts: people install them, and their bootstraps update like any other."""
    tags = _git(root, "tag", "--list", "v*").decode("utf-8").split()
    limit = order(before)
    chosen = [tag for tag in tags if TAG.match(tag)
              and order(tag[1:])[:3] >= FIRST and order(tag[1:]) < limit]
    return sorted(chosen, key=lambda tag: order(tag[1:]))


def lift(root: Path, tag: str) -> Bootstrap:
    """The tag's bootstrap and release.json, from git and nowhere else."""
    return Bootstrap(tag, _git(root, "show", tag + ":scripts/bootstrap.ps1"),
                     _git(root, "show", tag + ":scripts/release.json"))


def check(bootstraps, version: str, standard: Path, advanced: Path | None = None) -> list:
    """Every finding, as a sentence. None means each bootstrap given names the archive the build
    wrote and accepts it - the advanced one too, for a bootstrap that knows that edition."""
    if not POWERSHELL.is_file():
        raise SystemExit("the published bootstraps are Windows PowerShell; %s is missing" % POWERSHELL)
    wanted = {"standard": (standard, make_release.archive_name("standard", version))}
    if advanced is not None:
        wanted["advanced"] = (advanced, make_release.archive_name("advanced", version))
    found, cases = [], []
    with tempfile.TemporaryDirectory(prefix="legacy-bootstraps-") as work:
        for index, bootstrap in enumerate(bootstraps):
            folder = Path(work) / str(index)
            folder.mkdir()
            (folder / "bootstrap.ps1").write_bytes(bootstrap.script)
            (folder / "release.json").write_bytes(bootstrap.release)
            editions = ["standard"]
            if bootstrap.knows_advanced():
                if advanced is None:
                    found.append("%s updates advanced installations, and no advanced archive was "
                                 "given to check it with" % bootstrap.tag)
                else:
                    editions.append("advanced")
            for edition in editions:
                cases.append({"index": index, "edition": edition, "version": version,
                              "script": str(folder / "bootstrap.ps1"),
                              "release": str(folder / "release.json"),
                              "archive": str(wanted[edition][0])})
        if not cases:
            return found
        (Path(work) / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", PROBE],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=900, env=dict(os.environ, CAR_CASES=str(Path(work) / "cases.json")))
    if done.returncode != 0 or not done.stdout.strip():
        raise SystemExit("the published bootstraps could not be run:\n%s"
                         % (done.stderr or done.stdout)[-2000:])
    answers = json.loads(done.stdout)
    if len(answers) != len(cases):
        raise SystemExit("asked about %d cases and heard about %d" % (len(cases), len(answers)))
    for answer in answers:
        tag = bootstraps[answer["index"]].tag
        edition = answer["edition"]
        archive, name = wanted[edition]
        if answer["stage"] in ("parse", "name"):
            found.append("%s cannot name the %s archive: %s" % (tag, edition, answer["error"]))
            continue
        if answer["name"] != name:
            found.append("%s would download %s, and the build wrote %s" % (tag, answer["name"], name))
        if answer["stage"] != "accepted":
            found.append("%s refuses %s: %s" % (tag, archive.name, answer["error"]))
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prove every published bootstrap takes this release.")
    parser.add_argument("--dist", default=str(make_release.OUT),
                        help="where make_release.py wrote the archives (default: build/dist)")
    args = parser.parse_args(argv)
    release = make_release.version()
    standard = Path(args.dist) / make_release.archive_name("standard", release)
    if not standard.is_file():
        raise SystemExit("missing %s - build the standard edition first" % standard)
    advanced = Path(args.dist) / make_release.archive_name("advanced", release)
    tags = published(ROOT, release)
    if not tags:
        # A check over no bootstraps would pass, and prove nothing.
        raise SystemExit("no tag from v0.5.2 on is in this checkout; fetch the tags (fetch-depth: 0)")
    print("the published bootstraps of %s to %s, on v%s" % (tags[0], tags[-1], release))
    found = check([lift(ROOT, tag) for tag in tags], release, standard,
                  advanced if advanced.is_file() else None)
    for line in found:
        print("  " + line)
    if found:
        print("an installed copy would not update to this release")
        return 1
    print("  all %d take %s" % (len(tags), standard.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
