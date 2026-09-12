"""Compose the repository's social preview card.

GitHub shows this image whenever a link to the repository is unfurled - in a chat, in a
search result, on a social site - so for a lot of people it is the first and sometimes the
only thing they see. It is 1280x640, and GitHub does not crop or pad it.

It is generated rather than drawn so it cannot drift from the palette and the mark, and it
lives under `build/` because it is a repository asset, not something the product ships.

The image itself has to be uploaded by hand: Settings -> General -> Social preview. There
is no API for it that a push can reach, so this writes the PNG into `docs/images/` and the
upload is a step someone with repository settings access does once.

The headline is the README's opening sentence, deliberately: this card is what a search
result and an unfurled link show, and a card whose first sentence differs from the page's
is two different products to whoever is skimming.

Run: python build/make_social.py

It writes the page and then rasterises it with Microsoft Edge headless - the same renderer
build/make_screenshots.py uses for the Codex panel - so the committed picture cannot drift
from the palette, the mark or the sentence without somebody running this. Pass --page-only
to write the HTML and stop, which is what to do on a machine with no Chromium.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import brand      # noqa: E402

PAGE = ROOT / "build" / "dist" / "social.html"
TARGET = ROOT / "docs" / "images" / "social-preview.png"
WIDTH, HEIGHT = 1280, 640

EDGE_CANDIDATES = tuple(
    Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    for base in (os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 os.environ.get("PROGRAMFILES", r"C:\Program Files")))

TEMPLATE = """<style>
  html,body{margin:0;padding:0}
  body{width:1280px;height:640px;overflow:hidden;
       background:radial-gradient(120%% 140%% at 18%% 30%%, #17457F 0%%, %(navy)s 55%%, #06182D 100%%);
       font:16px/1.4 "Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;color:#fff}
  .wrap{display:flex;align-items:center;justify-content:center;gap:60px;height:100%%;
        padding:0 76px;box-sizing:border-box}
  .mark{width:264px;height:264px;flex:none;
        filter:drop-shadow(0 18px 46px rgba(3,12,26,.55))}
  .mark svg{width:100%%;height:100%%;display:block}
  h1{margin:0;font-size:66px;line-height:1.02;font-weight:700;letter-spacing:-.018em}
  .rule{width:104px;height:5px;border-radius:3px;margin:26px 0 22px;
        background:linear-gradient(90deg,%(cyan)s,%(sky)s)}
  p{margin:0;font-size:29px;line-height:1.34;color:#C3D4E8;max-width:730px}
  .tags{display:flex;gap:10px;margin-top:30px;flex-wrap:wrap}
  .tag{font-size:18px;letter-spacing:.02em;color:#9FC4E8;
       border:1px solid rgba(159,196,232,.35);border-radius:999px;padding:6px 16px}
</style>
<div class="wrap">
  <div class="mark">%(svg)s</div>
  <div>
    <h1>Codex&nbsp;Auto&nbsp;Resume</h1>
    <div class="rule"></div>
    <p>Automatically resume the exact same Codex task on Windows
       after a usage limit resets.</p>
    <div class="tags"><span class="tag">Windows</span><span class="tag">exact conversation</span>
      <span class="tag">acts only on failures it can name</span></div>
  </div>
</div>
"""


def find_edge() -> Path:
    for candidate in EDGE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit("Microsoft Edge was not found; pass --page-only to write just the HTML.")


def rasterise(page: Path) -> None:
    """The picture, at exactly the size GitHub asks for and no other.

    Checked rather than assumed: a renderer that quietly produced a different size would
    give GitHub something to crop, and the crop is not the card anybody looked at.
    """
    with tempfile.TemporaryDirectory() as workspace:
        shot = Path(workspace) / "social.png"
        subprocess.run(
            [str(find_edge()), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=1", "--virtual-time-budget=3000",
             "--window-size=%d,%d" % (WIDTH, HEIGHT),
             "--screenshot=" + str(shot), page.as_uri()],
            check=True, capture_output=True, timeout=180, cwd=workspace)
        if not shot.is_file():
            raise SystemExit("the renderer produced nothing")
        header = shot.read_bytes()[:24]
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            raise SystemExit("the renderer did not produce a PNG")
        width, height = struct.unpack(">II", header[16:24])
        if (width, height) != (WIDTH, HEIGHT):
            raise SystemExit("expected %dx%d, got %dx%d" % (WIDTH, HEIGHT, width, height))
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_bytes(shot.read_bytes())


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    svg = (ROOT / "assets" / "brand" / "icon.svg").read_text(encoding="utf-8")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(TEMPLATE % {"navy": brand.RAMP[0], "cyan": brand.RAMP[4],
                                "sky": brand.RAMP[3], "svg": svg}, encoding="utf-8")
    print("page  : %s" % PAGE)
    if "--page-only" in argv:
        print("rasterise it with a headless Chromium at %dx%d; see this file's docstring"
              % (WIDTH, HEIGHT))
        return 0
    rasterise(PAGE)
    print("card  : %s (%dx%d, %d bytes)"
          % (TARGET.relative_to(ROOT), WIDTH, HEIGHT, TARGET.stat().st_size))
    print("upload: Settings -> General -> Social preview -> Edit -> Upload an image")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
