"""Render the screenshots the README and the plugin card show.

Both images had drifted three releases behind the product: they showed v0.5.2 while the
manifest said 0.5.4. That was not carelessness, it was the absence of this file. Every
screenshot in the repository was made by hand - build the window, arrange it, run
`capture_window.ps1`, copy the PNG into place - and a step nobody has written down is a
step that gets skipped, especially the fourth time.

So the version in a screenshot now comes from the same place as the version everywhere
else. There is no number in this file and no mock JSON on disk to forget: the window -
its Overview, Pending and Settings pages - is rendered from a scratch installation
assembled out of the working tree, and the panel is rendered from `mcpui` with sample
data whose version field is `config.version()`. Change `.codex-plugin/plugin.json` and
re-run this, and every image says the new version without another edit anywhere.

`assets/screenshots.json` records what the images were rendered from. It is not a
signature and it is not checked at runtime - `tests/test_screenshots.py` compares the
recorded input hashes against the working tree and fails when the sources moved and the
images did not. That is the part that could not be done by remembering.

    python build/make_screenshots.py

Run it from a checkout, on Windows, with the settings window built. It writes the
canonical assets and copies them to `docs/images/`.

Two things it deliberately does NOT do:

* It does not run a watcher. The window shows "watching" when the single-instance mutex
  is held and "checking" while the watcher's heartbeat is fresh, so a helper holds exactly
  that mutex and writes exactly that heartbeat for the length of the capture. A real
  watcher would scan the user's own Codex history and could resume a real conversation,
  which is not a thing a documentation build may do. The records the Dashboard shows are
  synthetic, written into the scratch installation's own store (see `seed_window_state`),
  and the conversation names come from a synthetic Codex home the window is pointed at -
  never from the user's.
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

from codex_auto_resume import config, mcpui, messages               # noqa: E402
from codex_auto_resume import settings as policy                    # noqa: E402

ASSETS = ROOT / "assets"
DOCS = ROOT / "docs" / "images"
MANIFEST = ASSETS / "screenshots.json"

# The canonical image is the one the plugin card ships; the documentation copy is
# generated from it rather than captured a second time. Four files that have to be kept
# in step by hand is four files that drift.
PANEL = ASSETS / "screenshot-panel.png"
SETTINGS = ASSETS / "screenshot-settings.png"
COPIES = {PANEL: DOCS / "settings-panel.png", SETTINGS: DOCS / "settings-window.png"}

# What the *window* is rendered from. It is a compiled Windows application, so there is
# no way to look at its output without running it, and its inputs have to be listed.
#
# Listing is how this went wrong the first time: the tuple named seven files and missed
# five more that visibly change the pictures - the title-bar icon, the store fields behind
# every pending row, the control layer that decides what a row carries, the DPI manifest
# and the capture script itself. The panel no longer relies on a list at all (see below);
# this one stays as short as it can be. Nothing can check it against what the compiled
# window actually reads, so tests/test_screenshots.py checks the part that can be named:
# that every file the Dashboard's figures, rows and names are computed by is on it. A file
# missing from that test is a file this list can miss again.
WINDOW_INPUTS = (
    ".codex-plugin/plugin.json",          # the version in the footer
    "gui/SettingsApp.cs",                 # the window's layout and wording
    "gui/Dashboard.cs",                   # the Dashboard pages
    "gui/Brand.cs",                       # its palette
    "gui/app.manifest",                   # its DPI awareness, and so its size
    "assets/codex-auto-resume.ico",       # the mark in the title bar, which is captured
    "src/codex_auto_resume/settings.py",  # the schema that decides which rows exist
    # The window renders no text of its own. Every label, every value and the whole
    # status line arrive over the bridge as JSON, so the read path is a render input as
    # surely as the layout is: `controlcli` shapes the envelope the window unpacks, and
    # `watcher_running` in `app.py` is what decides the headline, the dot and whether the
    # Start button is in the picture at all.
    "src/codex_auto_resume/controlcli.py",
    "src/codex_auto_resume/app.py",
    # Every word of the window, in both languages, is the interface catalog; what a row
    # carries and which public status it shows are decided by the control layer and the
    # state machine.
    "src/codex_auto_resume/interface.py",
    "src/codex_auto_resume/control.py",
    "src/codex_auto_resume/machine.py",
    # The Dashboard computes its figures from the local records rather than reading them
    # from a caption, so each of these changes a number, a row or a word in the picture.
    # statistics, history order, pending rows, and the heartbeat behind 'checking'
    "src/codex_auto_resume/store.py",
    "src/codex_auto_resume/source.py",    # conversation names, via LocalSource.identity
    "src/codex_auto_resume/config.py",    # Paths, codex_home and the version it reads
    "src/codex_auto_resume/messages.py",  # which language the window is resolved to
    "src/codex_auto_resume/windows.py",   # the mutex that decides 'watching'
    "src/codex_auto_resume/startup.py",   # the start-at-sign-in value
    "tests/codexsim.py",                  # the synthetic Codex home the names come from
    "build/capture_window.ps1",           # how much of the window is captured
    # Whether the icon and the DPI manifest are compiled into the binary at all, and
    # which sources go into it. The two entries above it are only inputs because this
    # file passes them to the compiler.
    "build/make_gui.ps1",
    "build/make_screenshots.py",          # the sample installation it is run against
)

# Rendered at half size and captured at twice the device scale, so the committed image is
# the same pixels whatever display it was generated on. The window is captured at whatever
# the machine's scaling is, because a window has no such control; the manifest records
# which, so a surprising diff has an explanation.
#
# 550x494 was inherited and was wrong twice over, which is what the picture showed: the
# panel's grid collapses to one column below 260px per column, so the screenshot was a
# tall narrow strip rather than the two-column layout Codex actually shows - and 494 was
# shorter than the content, so the image ended in the middle of the recovery card with
# both remaining cards and the whole footer cut off. A screenshot that stops mid-card
# reads as a broken product.
#
# 900 is wide enough for two columns with the cards at a comfortable width, and near the
# width a Codex side panel actually gets. The height is measured from the rendered page
# rather than guessed, so it cannot go stale when a setting is added.
PANEL_CSS_WIDTH = 900
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
               "22222222-2222-7222-8222-222222222222")
    categories = ("usage_limit", "network_transient")
    # Named, because the panel falls back to the first segment of the thread id and a
    # column of `11111111` reads as debug output rather than as work waiting to resume.
    # Synthetic throughout - `tests/test_repo_hygiene.py` requires the placeholder family
    # - but shaped like something a person would recognise as their own task.
    names = ("example-project", "example-service")
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
    # A name is what a person recognises the work by. It reaches a real row from the
    # identity the watcher recorded, which a scratch store has no way to have; without it
    # the panel falls back to the first segment of the thread id and the picture shows a
    # column of `11111111`, which reads as debug output rather than as work waiting.
    for row, name in zip(waiting, names):
        row["name"] = name
    # The two facts a picture of a working product should show, which a scratch store
    # cannot know: it is on, and something is watching.
    status["enabled"] = True
    status["watcher_running"] = True
    status["startup_enabled"] = True
    status["home"] = r"%USERPROFILE%\.codex-auto-resume"
    return {"status": status, "schema": policy.describe(),
            "settings": policy.defaults(), "pending": waiting}


# The Dashboard's sample: four conversations, from the same fixture family as the panel's.
WINDOW_THREADS = ("11111111-1111-7111-8111-111111111111",
                  "22222222-2222-7222-8222-222222222222",
                  "33333333-3333-7333-8333-333333333333",
                  "44444444-4444-7444-8444-444444444444")
WINDOW_NAMES = ("example-project", "example-service", "example-docs", "example-app")


def seed_window_state(home: Path, codex: Path, now: float) -> None:
    """The records the Dashboard is photographed showing, written by the product's own store.

    Two recoveries waiting - a usage limit that resets in about forty minutes and a
    network failure due in a minute and a half - and six that finished earlier in the
    week: four recovered, one whose turn ran but made no progress, and one a person took
    over. Enough finished records for the success rate to be shown at all (it needs
    five), and not a flattering hundred percent. Every record walks the same transitions the
    engine makes (claim, send, the exact turn it started, how that turn ended), so the
    history, the statistics and each timeline are what the store derives from them rather
    than numbers typed here.

    The names come from a synthetic Codex home, read through the same `LocalSource` the
    window uses for a real one - so the picture never shows `11111111` where a person
    would see their own project. `tests/codexsim.py` builds it: the columns of a real
    Codex installation, with nothing of the user's in them.
    """
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        from codexsim import CodexHome
    finally:
        sys.path.pop(0)
    from codex_auto_resume.store import Store

    sim = CodexHome(codex)
    for thread, name in zip(WINDOW_THREADS, WINDOW_NAMES):
        sim.add_thread(thread, name=name)
    paths = config.Paths(home)
    paths.ensure()
    limits = {"max_recovery_attempts": 9, "max_no_progress": 9, "max_chain_continuations": 9}

    def detection(index, thread, category, detected, reset_at=None):
        return {"thread_id": thread, "turn_id": "0a1b2c3d-0301-7000-8000-%012d" % index,
                "completed_at": detected - 1, "started_at": detected - 240, "ordinal": 2,
                "interruption_id": "%x" % index * 64, "reset_at": reset_at,
                "limit_type": "codex.primary" if category == "usage_limit" else category,
                "uncertain": False, "category": category}

    def finished(store, index, thread, category, detected, outcome):
        record = detection(index, thread, category, detected)
        store.register(record, detected, state="waiting_backoff", next_retry_at=detected + 60)
        key = record["interruption_id"]
        store.reserve_detailed(key, detected + 60, limits=limits)
        store.update(key, at=detected + 61, event="submitted", state="queued",
                     queue_id="0a1b2c3d-0302-7000-8000-%012d" % index)
        store.correlate(key, "0a1b2c3d-0303-7000-8000-%012d" % index, detected + 64)
        if outcome == "stopped_by_user":
            store.update(key, at=detected + 200, state="stopped_by_user", outcome_at=detected + 200)
            return
        store.update(key, at=detected + 610, state="turn_completed")
        store.update(key, at=detected + 620, state=outcome, outcome_at=detected + 620)

    hour = 3600
    with Store(paths.state_dir) as store:
        store.set_enabled(True, now - 6 * 24 * hour)
        finished(store, 1, WINDOW_THREADS[2], "server_5xx", now - 5 * 24 * hour, "recovered")
        finished(store, 2, WINDOW_THREADS[0], "usage_limit", now - 4 * 24 * hour, "recovered")
        finished(store, 3, WINDOW_THREADS[3], "network_transient", now - 3 * 24 * hour,
                 "completed_no_progress")
        finished(store, 4, WINDOW_THREADS[1], "server_5xx", now - 2 * 24 * hour, "recovered")
        finished(store, 5, WINDOW_THREADS[3], "network_transient", now - 9 * hour, "stopped_by_user")
        finished(store, 6, WINDOW_THREADS[2], "usage_limit", now - 3 * hour, "recovered")
        store.register(detection(7, WINDOW_THREADS[0], "usage_limit", now - 25 * 60,
                                 reset_at=now + 42 * 60 + 20), now - 25 * 60)
        store.register(detection(8, WINDOW_THREADS[1], "network_transient", now - 50),
                       now - 50, state="waiting_backoff", next_retry_at=now + 95)


# ------------------------------------------------------------------------- panel
def find_edge() -> Path:
    for candidate in EDGE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit("Microsoft Edge was not found; it is the renderer for the panel.")


def panel_height(page: Path, workspace: str) -> int:
    """How tall the rendered panel actually is, asked of the renderer.

    A constant here is a constant that goes stale the first time a setting is added, and
    the way it goes stale is that the bottom of the picture disappears. Chromium prints
    the DOM after layout, so the page can be asked instead: render it once at the target
    width, read the height off the root element, and shoot at that.
    """
    marker = "CAR-PANEL-HEIGHT:"
    probe = Path(workspace) / "probe.html"
    probe.write_text(
        page.read_text(encoding="utf-8").replace(
            "</body>",
            "<script>document.title='%s'+"
            "Math.ceil(document.documentElement.getBoundingClientRect().height);"
            "</script></body>" % marker),
        encoding="utf-8")
    dumped = subprocess.run(
        [str(find_edge()), "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--virtual-time-budget=2000",
         "--window-size=%d,%d" % (PANEL_CSS_WIDTH, 2000),
         "--dump-dom", probe.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, cwd=workspace)
    for piece in dumped.stdout.split(marker)[1:]:
        digits = ""
        for character in piece:
            if character.isdigit():
                digits += character
            else:
                break
        if digits:
            # The page's own padding is already in the measurement; a little more keeps
            # the bottom card from sitting flush against the edge of the image.
            return int(digits) + 16
    raise SystemExit("could not measure the panel; the renderer printed no height")


def render_panel(target: Path) -> None:
    """The panel, rendered from `mcpui` rather than photographed inside Codex.

    Codex draws this HTML in its own frame, so a picture taken here is a faithful
    rendering of the same document and not a picture of Codex. The README says so; do not
    let it start implying otherwise.
    """
    html = panel_html(theme=THEME)
    with tempfile.TemporaryDirectory() as workspace:
        page = Path(workspace) / "panel.html"
        page.write_text(html, encoding="utf-8")
        shot = Path(workspace) / "panel.png"
        height = panel_height(page, workspace)
        subprocess.run(
            [str(find_edge()), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=%d" % PANEL_SCALE,
             "--window-size=%d,%d" % (PANEL_CSS_WIDTH, height),
             "--screenshot=%s" % shot, page.as_uri()],
            check=True, capture_output=True, timeout=180,
            cwd=workspace)
        if not shot.is_file():
            raise SystemExit("the renderer produced no image")
        shutil.copyfile(shot, target)


# ---------------------------------------------------------------- settings window
# A host that answers `callTool`, and nothing else.
#
# The panel feature-detects its host and falls back to read-only when it finds none -
# every control disabled, and a line explaining why. That fallback is correct and is
# worth having, but it is not what the panel looks like inside Codex, where a host is
# always present. Rendering without one produced a screenshot of the degraded state:
# greyed checkboxes, a greyed Save, and a notice telling the reader to go and use a
# different window.
#
# So the preview is given the one thing Codex gives it. Nothing here is drawn by the
# stub: the markup, the styles and every string are still the resource Codex is served.
PREVIEW_HOST = ("<script>window.openai={callTool:function(){"
                "return new Promise(function(){});}};</script>")


def panel_html(theme=None) -> str:
    """The exact markup the panel screenshot is a picture of."""
    page = mcpui.settings_page(sample_panel_data(), theme=theme)
    # Before the panel's own script, which reads the host as it starts.
    head, _, tail = page.rpartition("<script>")
    return head + PREVIEW_HOST + "<script>" + tail


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


# Holds the watcher's mutex and writes the watcher's heartbeat once a second - the two
# things the window reads to say a watcher is running and checking - and nothing else. No
# engine, no source, no Codex.
HOLD_MUTEX = """
import os, sys, time
sys.path.insert(0, sys.argv[1])
from codex_auto_resume import config
from codex_auto_resume.app import App
from codex_auto_resume.store import Store
paths = config.Paths(sys.argv[2])
started = time.time()
with App(paths, console=False, enable_logging=False).mutex(timeout=0):
    sys.stdout.write("held\\n")
    sys.stdout.flush()
    while time.time() - started < float(sys.argv[3]):
        with Store(paths.state_dir) as store:
            store.heartbeat(time.time(), pid=os.getpid(), session_id="screenshot",
                            started_at=started - 5400, ok=True, engine_state="verified",
                            code_version=config.version())
        time.sleep(1)
"""

# Which page of the window each picture is of, as the window's own command line names it.
WINDOW_PAGES = ("overview", "pending", "settings")


def render_window(targets: dict) -> dict:
    """Capture each page of the window, with the watcher's mutex held but no watcher running.

    The window reports "watching" when the single-instance mutex is taken, so taking it
    is enough to show the product in its ordinary state. Starting a real watcher would
    put a recovery engine on the user's own Codex history for the length of a
    documentation build, which is not a trade this makes.

    `targets` maps a page name to the image it is captured into. One installation serves
    every page, so the pages show the same records at nearly the same moment.
    """
    with tempfile.TemporaryDirectory() as name:
        workspace = Path(name)
        home = scratch_installation(workspace)
        codex = workspace / "codex"
        seed_window_state(home, codex, time.time())
        # The window reads conversation names from Codex's own state, found through
        # CODEX_HOME - pointed here at the synthetic one, so a capture can never show,
        # or even open, the user's.
        environment = dict(os.environ, CODEX_HOME=str(codex))
        holder = subprocess.Popen(
            [str(home / "runtime" / "python.exe"), "-c", HOLD_MUTEX,
             str(home / "app" / "src"), str(home), str(40 + 20 * len(targets))],
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
            for page, target in targets.items():
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                     "Bypass", "-File", str(ROOT / "build" / "capture_window.ps1"),
                     "-Exe", str(home / "CodexAutoResumeSettings.exe"),
                     "-Out", str(target), "-Wait", "8", "-Arguments", "--page=" + page],
                    check=True, capture_output=True, timeout=300, env=environment)
        finally:
            holder.kill()
    return {page: dimensions(target) for page, target in targets.items()}


# ---------------------------------------------------------------------- manifest
def render_inputs() -> dict:
    """What each image is rendered from, hashed.

    The panel's entry is the **rendered HTML itself**, not the files that produce it, and
    that is stricter and looser in exactly the right directions. Stricter: it moves when
    the version, the settings schema, the fields a pending row carries, the palette or the
    markup move, wherever in the package those live, without anyone having to remember to
    add a filename. The first version of this listed seven files and missed five that
    visibly change the picture. Looser: editing a comment cannot change it, so a
    contributor who fixes a typo is not handed a red suite and a regeneration that needs
    Windows, Edge, a compiled settings window and a network fetch.

    The window gets no such handle - it is a compiled application, and running it is the
    only way to see its output - so its inputs are listed above, and a comment in
    `SettingsApp.cs` will fire this check unnecessarily. That is a real cost and it is
    the smaller one: the alternative is not noticing that the picture is wrong.
    """
    inputs = {name: input_digest(ROOT / name) for name in WINDOW_INPUTS}
    # One entry per locale, each rendered with that locale pinned.
    #
    # A single unpinned entry made the digest depend on the machine: the catalog is
    # resolved from the environment, so a Korean developer recorded the Korean render and
    # an English CI runner recomputed the English one and called the screenshots stale.
    # It is the same failure as hashing raw bytes for a file whose line endings the
    # checkout decides - the input has to be pinned, not observed.
    for locale in LOCALES:
        previous = os.environ.get(messages.ENV_LANG)
        os.environ[messages.ENV_LANG] = locale
        try:
            inputs["<panel render:%s>" % locale] = sha256(
                panel_html(theme=THEME).encode("utf-8"))
        finally:
            if previous is None:
                os.environ.pop(messages.ENV_LANG, None)
            else:
                os.environ[messages.ENV_LANG] = previous
    return inputs


# Hashed as bytes, because that is what they are. Everything else is source text.
BINARY_INPUTS = (".ico", ".png", ".zip")


def input_digest(path: Path) -> str:
    """Hash an input in a way a fresh checkout can reproduce.

    Text is normalised to LF first. `.gitattributes` forces `*.ps1` to CRLF on checkout
    while the repository stores LF, so a working copy that happens to hold LF hashes
    differently from what every clone and every CI run receives - and the manifest then
    records a digest nobody else can compute. That failed on the generated ko tree before
    it could fail in CI, which is the only reason it was noticed.

    A line ending cannot change what a screenshot looks like, so normalising loses nothing.
    """
    if path.suffix.lower() in BINARY_INPUTS:
        return sha256(path.read_bytes())
    # Python reads text in universal-newline mode, so CRLF and a lone CR both arrive
    # as LF and the digest is the same whichever way the file was checked out.
    return sha256(path.read_text(encoding="utf-8").encode("utf-8"))


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


# The public screenshot set: one language per README, one theme for all of them.
#
# Light, because the dark theme is the one that follows the reader's machine and a
# gallery mixing a light notification with a dark panel does not look like one product.
# The runtime still follows the user's Windows and Codex themes; only the pictures are
# pinned, and only so that a build on a machine in dark mode produces the same bytes as a
# build on a machine in light mode.
THEME = "light"
LOCALES = ("en", "ko")


# Canonical asset name and documentation copy name, per picture. The settings page keeps
# the names it has always had, so links to it from outside the repository keep working.
WINDOW_NAMES_BY_PAGE = {
    "overview": ("screenshot-dashboard", "dashboard-overview"),
    "pending": ("screenshot-pending", "dashboard-pending"),
    "settings": ("screenshot-settings", "settings-window"),
}


def paths_for(locale: str):
    """Where one locale's images live: the panel first, then one per window page, each
    mapped to its documentation copy. English keeps the plain names."""
    tag = "" if locale == "en" else "-" + locale
    pairs = {ASSETS / ("screenshot-panel%s.png" % tag): DOCS / ("settings-panel%s.png" % tag)}
    for page in WINDOW_PAGES:
        asset, copy = WINDOW_NAMES_BY_PAGE[page]
        pairs[ASSETS / ("%s%s.png" % (asset, tag))] = DOCS / ("%s%s.png" % (copy, tag))
    return pairs


def window_targets(locale: str) -> dict:
    """Page name to canonical asset, for one locale."""
    tag = "" if locale == "en" else "-" + locale
    return {page: ASSETS / ("%s%s.png" % (WINDOW_NAMES_BY_PAGE[page][0], tag))
            for page in WINDOW_PAGES}


def main(argv=None) -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    print("version        : %s" % config.version())
    print("theme          : %s" % THEME)
    copies = {}
    for locale in LOCALES:
        print("locale         : %s" % locale)
        # The engine resolves the language from the environment, so the environment is
        # what the generator sets. Nothing here passes a language into a renderer: the
        # screenshots go through exactly the path a user's machine goes through.
        os.environ[messages.ENV_LANG] = locale
        pairs = paths_for(locale)
        panel = next(iter(pairs))
        render_panel(panel)
        print("  %s  %s" % (panel.relative_to(ROOT), dimensions(panel)))
        targets = window_targets(locale)
        for page, size in render_window(targets).items():
            print("  %s  %s" % (targets[page].relative_to(ROOT), size))
        copies.update(pairs)
    os.environ.pop(messages.ENV_LANG, None)

    for source, copy in copies.items():
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
        "theme": THEME,
        "locales": list(LOCALES),
        "system_dpi": system_dpi(),
        "inputs": render_inputs(),
        "images": {str(path.relative_to(ROOT)).replace("\\", "/"):
                   {"sha256": sha256(path.read_bytes()), "size": dimensions(path)}
                   for path in list(copies) + list(copies.values())},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifest       : %s" % MANIFEST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
