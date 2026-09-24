"""Time the window's own layout, so a claim about how fast it is can be checked rather than believed.

    py build\\measure_window.py                     # this checkout
    py build\\measure_window.py --tree <path>       # another checkout, to compare with

It builds `gui/*.cs` into a scratch folder and calls `SettingsForm.LayoutAudit`, which is the window
the product ships - built off screen, with no bridge and no timers - walked page by page and section
by section at each locale and scale. That walk is the work a page switch does, so the number it gives
is the one a person feels. Nothing of an installation is read or written: the exe, its inputs and its
answers all live in a temporary folder, and no watcher, registry key or real home is touched.

What it printed for v0.6.9, on the maintainer's machine, median of three runs (before is v0.6.9-alpha,
after is v0.6.9):

    en@1.00   5642 -> 2806 ms      ko@1.00   17333 -> 3527 ms
    en@1.50   6381 -> 2802 ms      ko@1.50   13273 -> 3662 ms

Timings are a machine's, not a fact about the code, so nothing in the suite asserts them: what the
suite holds is the behaviour the speed comes from (tests/test_gui_v069_idle.py - an unchanged snapshot
fills nothing), and this tool is how the next person sees the same thing for themselves.
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
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
LOCALES = ("en", "ko")          # English, and the language the lag was worst in
SCALES = (1.0, 1.5)
ROUNDS = 3

PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$static = [Reflection.BindingFlags]'Static,NonPublic,Public'
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$audit = $form.GetMethod('LayoutAudit', $static)
if (-not $audit) { throw 'SettingsForm has no LayoutAudit' }
$work = [string]$env:CAR_WORK
$utf8 = New-Object Text.UTF8Encoding $false
$schema = [IO.File]::ReadAllText((Join-Path $work 'schema.json'), $utf8)
$current = [IO.File]::ReadAllText((Join-Path $work 'settings.json'), $utf8)
$snapshot = [IO.File]::ReadAllText((Join-Path $work 'snapshot.json'), $utf8)
$out = @{}
foreach ($locale in (ConvertFrom-Json $env:CAR_LOCALES)) {
    $catalog = [IO.File]::ReadAllText((Join-Path $work ('strings-' + $locale + '.json')), $utf8)
    foreach ($scale in (ConvertFrom-Json $env:CAR_SCALES)) {
        $times = @()
        for ($i = 0; $i -lt [int]$env:CAR_ROUNDS; $i++) {
            $watch = [Diagnostics.Stopwatch]::StartNew()
            $null = $audit.Invoke($null, [object[]]@($schema, $current, $catalog, $snapshot, [double]$scale))
            $times += [int]$watch.ElapsedMilliseconds
        }
        $out[($locale + '@' + ([double]$scale).ToString('0.00'))] = $times
    }
}
ConvertTo-Json $out -Compress
"""



def window_sources(tree) -> list:
    """The window's compile list, as the tree being measured spells it.

    Read from that tree rather than from this one: this script compiles a checkout of another
    version to compare it with today's, and a list taken from here would compile the old
    sources in the new order - or name a file that version did not have.
    """
    manifest = tree / "gui" / "window.sources"
    if not manifest.is_file():                       # before v0.6.10-alpha it was written out
        return ["gui/" + name for name in
                ("SettingsApp.cs", "Dashboard.cs", "Controls.cs", "Brand.cs")]
    names = [line.split("#", 1)[0].strip()
             for line in manifest.read_text(encoding="utf-8").splitlines()]
    # The `[group]` markers are for the tests; the compiler is handed every source.
    return [name for name in names if name and not name.startswith("[")]

def measure(tree: Path) -> dict:
    sys.path.insert(0, str(tree / "src"))
    sys.path.insert(0, str(tree / "tests"))
    from codex_auto_resume import l10n, settings
    import test_gui_layout

    work = Path(tempfile.mkdtemp(prefix="measure-window-"))
    exe = work / "CodexAutoResumeSettings.exe"
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                    "/reference:System.dll", "/reference:System.Drawing.dll",
                    "/reference:System.Windows.Forms.dll"]
                   + [str(tree / name) for name in window_sources(tree)],
                   check=True, capture_output=True, timeout=600)
    current = dict(settings.defaults(), continuation_style="custom", custom_message_mode="per_reason")
    (work / "schema.json").write_text(json.dumps(settings.describe(), ensure_ascii=False), encoding="utf-8")
    (work / "settings.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    for locale in LOCALES:
        reply = {"ok": True, "language": locale, "strings": l10n.catalog(locale),
                 "endonyms": dict(l10n.ENDONYMS), "preference": locale, "system_language": locale}
        (work / ("strings-%s.json" % locale)).write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
    # The fullest the pages ever are, which is the suite's own sample (tests/test_gui_layout.py).
    (work / "snapshot.json").write_text(
        json.dumps(test_gui_layout.fullest_snapshot(1_700_000_000.0), ensure_ascii=False), encoding="utf-8")

    done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-Command", PROBE], capture_output=True, text=True, timeout=1800,
                          env=dict(os.environ, CAR_EXE=str(exe), CAR_WORK=str(work),
                                   CAR_LOCALES=json.dumps(list(LOCALES)),
                                   CAR_SCALES=json.dumps(list(SCALES)), CAR_ROUNDS=str(ROUNDS)))
    if done.returncode != 0:
        raise SystemExit((done.stdout or "")[-3000:] + (done.stderr or "")[-3000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Time the window's layout, page by page.")
    parser.add_argument("--tree", default=str(ROOT), help="the checkout to build and measure")
    arguments = parser.parse_args(argv)
    if os.name != "nt" or not CSC.is_file():
        raise SystemExit("the window is C# and is built with the in-box compiler, on Windows")
    answer = measure(Path(arguments.tree).resolve())
    print("%s (median of %d)" % (Path(arguments.tree).resolve(), ROUNDS))
    for key in sorted(answer):
        times = answer[key]
        print("  %-10s %6d ms   %s" % (key, sorted(times)[len(times) // 2], times))
    return 0


if __name__ == "__main__":
    sys.exit(main())
