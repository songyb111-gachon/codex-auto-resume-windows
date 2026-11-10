"""The Persian window face is bundled and process-private; damaged assets retain the existing face."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gui_v0611_access import CSC, POWERSHELL, compile_window, run_probe, reply
import guiscan
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
import make_setup

ROOT = Path(__file__).resolve().parents[1]
PROBE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$assembly = [Reflection.Assembly]::LoadFrom($env:CAR_EXE)
$t = $assembly.GetType('CodexAutoResume.Typeface', $true)
$flags = [Reflection.BindingFlags]'Static,NonPublic'
$method = $t.GetMethod('ForLanguage', $flags)
$words = New-Object 'Collections.Generic.Dictionary[string,object]'
$words.Add('sample', 'فارسی')
$out = @{directory=$t.GetMethod('PersianDirectory', $flags).Invoke($null, @())}
[GC]::Collect(); [GC]::WaitForPendingFinalizers()
foreach ($style in @([Drawing.FontStyle]::Regular, [Drawing.FontStyle]::Bold)) {
  $font = New-Object Drawing.Font('Segoe UI', [single]11, $style, [Drawing.GraphicsUnit]::Point)
  foreach ($lang in @('fa', 'en')) {
    $chosen = $method.Invoke($null, [object[]]@($font.PSObject.BaseObject, $words.PSObject.BaseObject, $lang))
    $out[($lang + '-' + $style)] = @{name=$chosen.FontFamily.Name; size=$chosen.SizeInPoints; bold=$chosen.Bold}
    if (-not [Object]::ReferenceEquals($font, $chosen)) { $chosen.Dispose() }
  }
  $font.Dispose()
}
if ($env:CAR_CTOR -eq '1') {
  Add-Type -AssemblyName System.Windows.Forms
  $j = $assembly.GetType('CodexAutoResume.Json', $true)
  $f = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
  $b = $assembly.GetType('CodexAutoResume.Bridge', $true)
  $pb = $assembly.GetType('CodexAutoResume.PersistentBridge', $true)
  $catalog = $j.GetMethod('Parse', $flags).Invoke($null, [object[]]@([IO.File]::ReadAllText((Join-Path $env:CAR_WORK 'strings-fa.json'))))
  [string]$probeRoot = Join-Path $env:CAR_WORK 'nowhere'
  $bridge = $b.GetConstructor($flags -bor [Reflection.BindingFlags]::Instance, $null, [type[]]@([string]), $null).Invoke([object[]]@($probeRoot))
  $persistent = $pb.GetConstructor($flags -bor [Reflection.BindingFlags]::Instance, $null, [type[]]@([string], $b), $null).Invoke([object[]]@($probeRoot, $bridge.PSObject.BaseObject))
  $font = New-Object Drawing.Font('Segoe UI', [single]9)
  $form = $f.GetConstructor($flags -bor [Reflection.BindingFlags]::Instance, $null, [type[]]@($pb, [Collections.Generic.Dictionary[string,object]], [Drawing.Font]), $null).Invoke([object[]]@($persistent.PSObject.BaseObject, $catalog.PSObject.BaseObject, $font.PSObject.BaseObject))
  $desired = $f.GetProperty('OpeningHeight', $flags).GetValue($null)
  $available = [Windows.Forms.Screen]::FromControl($form).WorkingArea.Height - ($form.Height - $form.ClientSize.Height)
  $out.ctor = @{height=$form.ClientSize.Height; desired=$desired; available=$available; font=$form.Font.FontFamily.Name}
  $form.Dispose()
}
[IO.File]::WriteAllText((Join-Path $env:CAR_WORK 'result.json'), ($out | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding $false))
"""

@unittest.skipUnless(os.name == 'nt' and CSC.is_file() and POWERSHELL.is_file(), 'requires Windows GDI/GDI+ and compiler')
class PersianWindowFontTests(unittest.TestCase):
    def test_private_regular_bold_installed_paths_and_safe_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            # Beyond the bounded ancestor search: a missing bundle cannot accidentally find the checkout's font.
            work = Path(temporary).joinpath(*(['n'] * 7))
            work.mkdir(parents=True)
            exe = compile_window(work)
            for placement in ('missing', 'assets', 'app/assets', 'invalid', 'embedded'):
                with self.subTest(placement=placement):
                    for relative in ('assets', 'app'):
                        shutil.rmtree(work / relative, ignore_errors=True)
                    if placement not in ('missing', 'embedded'):
                        destination = work / ('assets' if placement == 'invalid' else placement) / 'fonts' / 'vazirmatn'
                        destination.mkdir(parents=True)
                        for name in ('Vazirmatn-Regular.ttf', 'Vazirmatn-Bold.ttf'):
                            if placement == 'invalid':
                                (destination / name).write_bytes(b'not a font')
                            else:
                                shutil.copyfile(ROOT / 'assets' / 'fonts' / 'vazirmatn' / name, destination / name)
                    if placement == 'embedded':
                        holder = work / 'Setup.Fonts.cs'
                        holder.write_text(make_setup.font_source(), encoding='ascii')
                        subprocess.run([str(CSC), '/nologo', '/target:winexe', '/platform:x64',
                                        '/out:' + str(exe), '/reference:System.dll', '/reference:System.Drawing.dll',
                                        '/reference:System.Windows.Forms.dll',
                                        *[str(path) for path in guiscan.sources()], str(holder)],
                                       check=True, capture_output=True, timeout=300,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if placement == 'embedded':
                        import json
                        (work / 'strings-fa.json').write_text(json.dumps(reply('fa'), ensure_ascii=False), encoding='utf8')
                    found = run_probe(PROBE, work, 120, CAR_EXE=str(exe), CAR_CTOR='1' if placement == 'embedded' else '0')
                    if placement == 'embedded':
                        self.assertEqual(found['ctor']['font'], 'Vazirmatn')
                        self.assertEqual(found['ctor']['desired'], 728)
                        self.assertEqual(found['ctor']['height'], min(728, found['ctor']['available']))
                    for style in ('Regular', 'Bold'):
                        for language in ('fa', 'en'):
                            actual = found[language + '-' + style]
                            expected = 'Vazirmatn' if language == 'fa' and placement in ('assets', 'app/assets', 'embedded') else 'Segoe UI'
                            self.assertEqual(actual['name'], expected, str(found))
                            self.assertEqual(actual['size'], 11)
                            self.assertEqual(actual['bold'], style == 'Bold')

if __name__ == '__main__':
    unittest.main()
