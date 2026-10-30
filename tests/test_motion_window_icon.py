r"""v0.6.20 (the owner, 2026-10-30): in the README's first motion the Timeline dialog did not wear the product's icon.

Two causes, both in how the pictures are made; the real window was never affected (Windows draws a title bar's icon):

* The motion's own build of the window (build/motion_window.compile_window) wrote the exe into a scratch folder with no
  codex-auto-resume.ico beside it. The window loads its icon from that file (SettingsForm: BaseDirectory) and the Timeline
  dialog takes the window's (`dialog.Icon = Icon`), so WindowRender painted Windows' default form icon. compile_window now
  embeds the icon (`/win32icon`, as build/make_gui.ps1 does) and puts the same file beside the exe.
* With the icon there, the dialog showed a square of coloured noise: every image in the .ico is PNG-compressed, and
  System.Drawing's Icon paints such an image as noise offscreen - DrawIcon, ToBitmap and a resized Icon alike.
  WindowRender.IconImage decodes the PNG image itself, and PaintDialog draws that.

The build test compiles the window once (csc); the pixel test loads the compiled window and asks IconImage for the 24 px
icon, then holds it to the .ico's own 24 px image. Run on its own.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

import guiscan

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "build") not in sys.path:
    sys.path.insert(0, str(ROOT / "build"))

import motion_window  # noqa: E402

ICON = ROOT / "assets" / "codex-auto-resume.ico"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def png_pixels(raw: bytes) -> tuple:
    """(width, height, [(r, g, b, a), ...]) of an 8-bit RGB or RGBA PNG, stdlib only."""
    at, header, data = 8, None, b""
    while at < len(raw):
        length = struct.unpack(">I", raw[at:at + 4])[0]
        kind, body = raw[at + 4:at + 8], raw[at + 8:at + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            data += body
        at += 12 + length
    width, height, depth, colour = header
    bpp = {6: 4, 2: 3}[colour]
    flat, stride, prev, out, at = zlib.decompress(data), width * bpp, bytearray(width * bpp), [], 0
    for _ in range(height):
        kind, line = flat[at], bytearray(flat[at + 1:at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += [tuple(line[x:x + bpp]) + ((255,) if bpp == 3 else ()) for x in range(0, stride, bpp)]
        prev = line
    return width, height, out


def ico_png(size: int) -> bytes:
    """The PNG image the product's .ico holds for `size` px."""
    raw = ICON.read_bytes()
    for i in range(struct.unpack("<H", raw[4:6])[0]):
        side, _, _, _, _, _, length, offset = struct.unpack("<BBBBHHII", raw[6 + 16 * i:22 + 16 * i])
        if (side or 256) == size:
            return raw[offset:offset + length]
    raise AssertionError("the icon holds no %d px image" % size)


class BuildTests(unittest.TestCase):
    @unittest.skipUnless(motion_window.CSC.is_file(), "the in-box C# compiler is not on this machine")
    def test_the_motions_window_has_the_products_icon_and_draws_it_whole(self):
        with tempfile.TemporaryDirectory() as name:
            work = Path(name)
            exe = motion_window.compile_window(work / "window")
            beside = exe.parent / "codex-auto-resume.ico"
            self.assertTrue(beside.is_file(), "the window the motion draws has no icon beside it")
            self.assertEqual(beside.read_bytes(), ICON.read_bytes(), "the icon beside it is the product's own")

            made = work / "icon24.png"
            probe = work / "probe.ps1"
            probe.write_text(
                "$ErrorActionPreference = 'Stop'\n"
                "Add-Type -AssemblyName System.Drawing\n"
                "$assembly = [Reflection.Assembly]::LoadFile('%s')\n"
                "$type = $assembly.GetType('CodexAutoResume.SettingsForm')\n"
                "$method = $type.GetMethod('IconImage', [Reflection.BindingFlags]'Static,NonPublic,Public')\n"
                "$given = [object[]]::new(2)\n"
                "$given[0] = [System.Drawing.Icon]::new('%s')\n"
                "$given[1] = [int]24\n"
                "$bitmap = [System.Drawing.Bitmap]$method.Invoke($null, $given)\n"
                "$bitmap.Save('%s', [System.Drawing.Imaging.ImageFormat]::Png)\n" % (exe, beside, made),
                encoding="utf-8")
            with open(work / "probe.out", "wb") as out, open(work / "probe.err", "wb") as err:
                done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                       "-File", str(probe)], stdout=out, stderr=err, timeout=120,
                                      creationflags=NO_WINDOW)
            self.assertEqual(done.returncode, 0, (work / "probe.err").read_text(errors="replace"))

            width, height, drawn = png_pixels(made.read_bytes())
            want_width, want_height, wanted = png_pixels(ico_png(24))
            self.assertEqual((width, height), (want_width, want_height))
            worst = max(max(abs(p - q) for p, q in zip(one, other))
                        for one, other in zip(drawn, wanted) if other[3] > 0)
            self.assertLessEqual(worst, 2, "the icon a picture draws is the .ico's own 24 px image, not noise")


class SourceTests(unittest.TestCase):
    def test_the_window_loads_its_icon_from_the_file_beside_it(self):
        body = guiscan.type_body("SettingsForm", "gui/SettingsApp.cs")
        self.assertIn('Path.Combine(root, "codex-auto-resume.ico")', body)
        self.assertIn("Icon = new Icon(icon);", body)

    def test_the_timeline_dialog_wears_the_windows_icon(self):
        body = guiscan.member_body("SettingsForm", "BuildTimeline")
        self.assertIn("dialog.Icon = Icon;", body)

    def test_a_rendered_dialog_draws_the_decoded_icon(self):
        body = guiscan.member_body("SettingsForm", "PaintDialog")
        self.assertIn("IconImage(icon, small)", body)
        self.assertNotIn("DrawIcon(", body)


if __name__ == "__main__":
    unittest.main()
