"""Render the two screenshots the README and the plugin card show.

Both images had drifted three releases behind the product: they showed v0.5.2 while the
manifest said 0.5.4. That was not carelessness, it was the absence of this file. Every
screenshot in the repository was made by hand - build the window, arrange it, run
`capture_window.ps1`, copy the PNG into place - and a step nobody has written down is a
step that gets skipped, especially the fourth time.

So the version in a screenshot now comes from the same place as the version everywhere
else. There is no number in this file and no mock JSON on disk to forget: the settings
window is rendered from a scratch installation assembled out of the working tree, and the
panel is rendered from `mcpui` with sample data whose version field is `config.version()`.
Change `.codex-plugin/plugin.json` and re-run this, and both images say the new version
without another edit anywhere.

`assets/screenshots.json` records what the images were rendered from. It is not a
signature and it is not checked at runtime - `tests/test_screenshots.py` compares the
recorded input hashes against the working tree and fails when the sources moved and the
images did not. That is the part that could not be done by remembering.

    python build/make_screenshots.py

Run it from a checkout, on Windows, with the settings window built. It writes the two
canonical assets and copies them to `docs/images/`.

Two things it deliberately does NOT do:

* It does not run a watcher. The settings window shows "watching" when the
  single-instance mutex is held, so a helper holds exactly that mutex for the few seconds
  of the capture. A real watcher would scan the user's own Codex history and could resume
  a real conversation, which is not a thing a documentation build may do.
* It does not edit an image. If a screenshot is wrong, the source that produced it is
  wrong.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "build"))

from codex_auto_resume import config, mcpui, settings as policy   # noqa: E402

ASSETS = ROOT / "assets"
DOCS = ROOT / "docs" / "images"
MANIFEST = ASSETS / "screenshots.json"

# The canonical image is the one the plugin card ships; the documentation copy is
# generated from it rather than captured a second time. Four files that have to be kept
# in step by hand is four files that drift.
PANEL = ASSETS / "screenshot-panel.png"
SETTINGS = ASSETS / "screenshot-settings.png"
COPIES = {PANEL: DOCS / "settings-panel.png", SETTINGS: DOCS / "settings-window.png"}

# What the images are a picture of. If one of these changes, the screenshots are stale -
# that is the whole claim `tests/test_screenshots.py` makes, so the list is the test's
# definition of "render input" as much as it is this script's.
RENDER_INPUTS = (
    ".codex-plugin/plugin.json",          # the version, and nothing else from here
    "gui/SettingsApp.cs",                 # the window's layout and wording
    "gui/Brand.cs",                       # its palette
    "src/codex_auto_resume/mcpui.py",     # the panel's markup, style and script
    "src/codex_auto_resume/brand.py",     # the palette both share
    "src/codex_auto_resume/settings.py",  # the schema that decides which rows exist
    "build/make_screenshots.py",          # the sample data below
)

# The panel is rendered at half size and captured at twice the device scale, so the
# committed image is 1100x988 whatever the display it was generated on. The window is
# captured at whatever the machine's scaling is, because a window has no such control;
# the manifest records which, so a surprising diff has an explanation.
PANEL_CSS_SIZE = (550, 494)
PANEL_SCALE = 2

EDGE_CANDIDATES = (
    Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    / "Microsoft/Edge/Application/msedge.exe",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dimensions(path: Path) -> str:
    raw = path.read_bytes()[16:24]
    return "%dx%d" % struct.unpack(">II", raw)


# --------------------------------------------------------------------- sample data
def sample_panel_data() -> dict:
    """What the panel is showing in the picture, produced by the product itself.

    Not a hand-written dictionary. Three synthetic interruptions are registered in a
    throwaway store and read back through `Control.list_pending()` and
    `Control.get_status()`, so the sample has exactly the shape the panel is given at
    runtime. The first attempt at this file did hand-write it, got two field names wrong,
    and rendered a table of "undefined" - which is the same class of drift the whole file
    exists to end, in the file that ends it.

    The values are synthetic throughout, and from the project's own fixture family: this
    image is published on a plugin card, so a real conversation id would be published
    with it. `tests/test_repo_hygiene.py` enforces the family.

    The version is not written here either. It arrives through `get_status()`, from the
    manifest, like every other current-facing surface.
    """
    from codex_auto_resume import control as control_module
    from codex_auto_resume.store import Store

    # The panel shows a conversation by its first segment, so three ids from the same
    # fixture prefix would render as three identical rows. Repeated-nibble values are
    # equally synthetic - `tests/test_repo_hygiene.py` accepts both - and tell the rows
    # apart in the picture.
    threads = ("11111111-1111-7111-8111-111111111111",
               "22222222-2222-7222-8222-222222222222",
               "33333333-3333-7333-8333-333333333333")
    categories = ("usage_limit", "network_transient", "server_5xx")
    with tempfile.TemporaryDirectory() as name:
        paths = config.Paths(Path(name))
        paths.ensure()
        with Store(paths.state_dir) as store:
            for index, (thread, category) in enumerate(zip(threads, categories)):
                store.register({
                    "thread_id": thread,
                    "turn_id": "0a1b2c3d-020%d-7000-8000-00000000020%d" % (index, index),
                    "completed_at": 110.0 + index, "started_at": 105.0 + index,
                    "ordinal": 2, "interruption_id": chr(ord("a") + index) * 64,
                    "reset_at": 150.0 + index * 600, "limit_type": "codex.primary",
                    "uncertain": False, "category": category}, 100.0 + index)
        surface = control_module.Control(paths)
        waiting = surface.list_pending()
        status = surface.get_status()
    # The two facts a picture of a working product should show, which a scratch store
    # cannot know: it is on, and something is watching.
    status["enabled"] = True
    status["watcher_running"] = True
    status["startup_enabled"] = True
    status["home"] = r"%USERPROFILE%\.codex-auto-resume"
    return {"status": status, "schema": policy.describe(),
            "settings": policy.defaults(), "pending": waiting}


# ------------------------------------------------------------------------- panel
def find_edge() -> Path:
    for candidate in EDGE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit("Microsoft Edge was not found; it is the renderer for the panel.")


def render_panel(target: Path) -> None:
    """The panel, rendered from `mcpui` rather than photographed inside Codex.

    Codex draws this HTML in its own frame, so a picture taken here is a faithful
    rendering of the same document and not a picture of Codex. The README says so; do not
    let it start implying otherwise.
    """
    html = mcpui.settings_page(sample_panel_data())
    with tempfile.TemporaryDirectory() as workspace:
        page = Path(workspace) / "panel.html"
        page.write_text(html, encoding="utf-8")
        shot = Path(workspace) / "panel.png"
        width, height = PANEL_CSS_SIZE
        subprocess.run(
            [str(find_edge()), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=%d" % PANEL_SCALE,
             "--window-size=%d,%d" % (width, height),
             "--screenshot=%s" % shot, page.as_uri()],
            check=True, capture_output=True, timeout=180,
            cwd=workspace)
        if not shot.is_file():
            raise SystemExit("the renderer produced no image")
        shutil.copyfile(shot, target)


# ---------------------------------------------------------------- settings window
def scratch_installation(workspace: Path) -> Path:
    """An installation made out of the working tree, so the picture is of this code."""
    import make_release
    import zipfile

    home = workspace / "home"
    (home / "app").mkdir(parents=True)
    shutil.copytree(ROOT / "src", home / "app" / "src")
    shutil.copytree(ROOT / ".codex-plugin", home / "app" / ".codex-plugin")
    # The same pinned, checksum-verified interpreter the release ships, from the same
    # cache, so the window in the picture runs on the interpreter users will have.
    (home / "runtime").mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(make_release.fetch_runtime()) as bundle:
        bundle.extractall(home / "runtime")
    exe = ROOT / "build" / "CodexAutoResumeSettings.exe"
    if not exe.is_file():
        raise SystemExit("build/CodexAutoResumeSettings.exe is missing; run build/make_gui.ps1")
    shutil.copyfile(exe, home / exe.name)
    # The window loads its title-bar icon from beside itself at runtime, so a scratch
    # installation without it is photographed wearing the default Windows icon.
    shutil.copyfile(ROOT / "assets" / "codex-auto-resume.ico", home / "codex-auto-resume.ico")

    # Recovery on, so the window shows the state it is in when it is doing its job.
    state = home / "config"
    state.mkdir(parents=True, exist_ok=True)
    (state / "settings.json").write_text(json.dumps(policy.defaults(), indent=2), encoding="utf-8")
    return home


HOLD_MUTEX = """
import sys, time
sys.path.insert(0, sys.argv[1])
from codex_auto_resume import config
from codex_auto_resume.app import App
paths = config.Paths(sys.argv[2])
with App(paths, console=False, enable_logging=False).mutex(timeout=0):
    sys.stdout.write("held\\n")
    sys.stdout.flush()
    time.sleep(float(sys.argv[3]))
"""


def render_settings_window(target: Path) -> str:
    """Capture the window, with the watcher's mutex held but no watcher running.

    The window reports "watching" when the single-instance mutex is taken, so taking it
    is enough to show the product in its ordinary state. Starting a real watcher would
    put a recovery engine on the user's own Codex history for the length of a
    documentation build, which is not a trade this makes.
    """
    with tempfile.TemporaryDirectory() as name:
        workspace = Path(name)
        home = scratch_installation(workspace)
        holder = subprocess.Popen(
            [str(home / "runtime" / "python.exe"), "-c", HOLD_MUTEX,
             str(home / "app" / "src"), str(home), "40"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            if (holder.stdout.readline() or "").strip() != "held":
                raise SystemExit("could not hold the watcher mutex for the capture")
            # `enable` through the engine rather than by writing the file: the window
            # reads what the engine reports, so the picture should too.
            subprocess.run([str(home / "runtime" / "python.exe"), "-c",
                            "import sys;sys.path.insert(0, sys.argv[1]);"
                            "from codex_auto_resume.controlcli import main;"
                            "sys.exit(main(['--home', sys.argv[2], 'enabled', sys.argv[3]]))",
                            str(home / "app" / "src"), str(home),
                            json.dumps({"enabled": True})],
                           check=True, capture_output=True, timeout=120)
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                 "Bypass", "-File", str(ROOT / "build" / "capture_window.ps1"),
                 "-Exe", str(home / "CodexAutoResumeSettings.exe"),
                 "-Out", str(target), "-Wait", "8"],
                check=True, capture_output=True, timeout=300)
        finally:
            holder.kill()
    return dimensions(target)


# ---------------------------------------------------------------------- manifest
def render_inputs() -> dict:
    return {name: sha256((ROOT / name).read_bytes()) for name in RENDER_INPUTS}


def system_dpi() -> int:
    """The scaling the window was captured at, recorded so a size change has a reason.

    Declared DPI-aware first. A DPI-unaware process is told 96 no matter what the display
    is set to, and this reported exactly that while capturing a 144-DPI window - a
    misleading number is worse in a manifest than no number.
    """
    try:
        import ctypes
        # PER_MONITOR_AWARE_V2, as gui/app.manifest asks for. Ignored where unsupported.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return int(ctypes.windll.user32.GetDpiForSystem())
    except Exception:                                   # noqa: BLE001 - reporting only
        return 0


def main(argv=None) -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    print("version        : %s" % config.version())
    print("rendering panel...")
    render_panel(PANEL)
    print("  %s  %s" % (PANEL.relative_to(ROOT), dimensions(PANEL)))

    print("rendering the settings window...")
    size = render_settings_window(SETTINGS)
    print("  %s  %s" % (SETTINGS.relative_to(ROOT), size))

    for source, copy in COPIES.items():
        shutil.copyfile(source, copy)
        print("copied         : %s -> %s" % (source.relative_to(ROOT), copy.relative_to(ROOT)))

    MANIFEST.write_text(json.dumps({
        "_comment": [
            "What the committed screenshots were rendered from. Written by",
            "build/make_screenshots.py and checked by tests/test_screenshots.py, which",
            "fails when these inputs no longer match the working tree - that is, when",
            "the screenshots are stale. Regenerate them rather than editing this file.",
        ],
        "version": config.version(),
        "system_dpi": system_dpi(),
        "inputs": render_inputs(),
        "images": {str(path.relative_to(ROOT)).replace("\\", "/"):
                   {"sha256": sha256(path.read_bytes()), "size": dimensions(path)}
                   for path in list(COPIES) + list(COPIES.values())},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifest       : %s" % MANIFEST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
