"""Compose the repository's social preview card.

GitHub shows this image whenever a link to the repository is unfurled - in a chat, in a
search result, on a social site - so for a lot of people it is the first and sometimes the
only thing they see. It is 1280x640, and GitHub does not crop or pad it.

It is generated rather than drawn so it cannot drift from the palette and the mark, and it
lives under `build/` because it is a repository asset, not something the product ships.

The image itself has to be uploaded by hand: Settings -> General -> Social preview. There
is no API for it that a push can reach, so this writes the PNG into `docs/images/` and the
upload is a step someone with repository settings access does once.

Run: python build/make_social.py
Then, to rasterise (any Chromium will do; Edge ships with Windows):
    msedge --headless=new --disable-gpu --hide-scrollbars --window-size=1280,640 \
           --screenshot=docs/images/social-preview.png file:///<abs path to the html>
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import brand      # noqa: E402

TARGET = ROOT / "build" / "dist" / "social.html"

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
    <p>Waits out a usage limit, a rate limit or a temporary failure &mdash; then continues
       that exact Codex conversation.</p>
    <div class="tags"><span class="tag">Windows</span><span class="tag">local only</span>
      <span class="tag">acts only on failures it can name</span></div>
  </div>
</div>
"""


def main() -> int:
    svg = (ROOT / "assets" / "brand" / "icon.svg").read_text(encoding="utf-8")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(TEMPLATE % {"navy": brand.RAMP[0], "cyan": brand.RAMP[4],
                                  "sky": brand.RAMP[3], "svg": svg}, encoding="utf-8")
    print("wrote %s" % TARGET)
    print("rasterise it with a headless Chromium at 1280x640; see this file's docstring")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
