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
    python build/make_screenshots.py --cards     # only the notification card's pictures
    python build/make_screenshots.py --icon      # only the icon's motion, as a GIF

Run it from a checkout, on Windows, with the settings window built. It writes the
canonical assets and copies them to `docs/images/`. The popup and the notification card are
drawn off-screen by their own renderers and need neither the window nor Edge; the icon's
motion is drawn from the icon's own frames and needs nothing of Windows at all.

Two things it deliberately does NOT do:

* It does not run a watcher. The window shows "watching" when the single-instance mutex
  is held and "checking" while the watcher's heartbeat is fresh, so a helper holds exactly
  that mutex and writes exactly that heartbeat for the length of the capture. A real
  watcher would scan the user's own Codex history and could resume a real conversation,
  which is not a thing a documentation build may do. The records the Dashboard shows are
  synthetic, written into the scratch installation's own store (see `seed_window_state`),
  and the conversation names come from a synthetic Codex home the window is pointed at -
  never from the user's. The compatibility report the Diagnostics page reads is the one the
  watcher's own evaluator writes, made against that home and a stand-in `codex.exe` under the
  scratch installation's own LOCALAPPDATA, which answers the engine checks' two questions and
  is never run (see `seed_compatibility`).
* It does not edit an image. If a screenshot is wrong, the source that produced it is
  wrong.
"""
from __future__ import annotations

import ast
from contextlib import ExitStack, contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "build"))

from codex_auto_resume import config, l10n, mcpui                   # noqa: E402
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

# What the *window* is rendered from, in two halves.
#
# The compiled half is files, hashed byte for byte (line endings aside): a compiled Windows
# application has no output to look at without running it. Listing is how this went wrong
# the first time - the tuple named seven files and missed five more that visibly change the
# pictures: the title-bar icon, the store fields behind every pending row, the control layer
# that decides what a row carries, the DPI manifest and the capture script itself.
#
# The Python half is not a list of files any more. The window renders no text of its own:
# every label, every value, every row and the whole status line arrive over the bridge as
# JSON, so what the Python side contributes to a picture is exactly what the bridge answers
# the window. `window_envelopes` below asks the bridge the window's own questions, against
# the same kind of scratch installation the capture uses, and the manifest records a hash of
# the answers (`<bridge envelope:{locale}>`). Until v0.6.5 this list held fifteen of the
# package's modules and `tests/codexsim.py` instead, so moving a function between two files
# - the whole of the v0.6.5 modularisation - marked every picture stale and cost a
# re-render on Windows with Edge and a compiled window, while a comment edit in any of them
# did the same. A hash of the answers moves when a word, a row field, a figure, a name or
# the status moves, wherever in the package that is decided, and at no other time.
#
# tests/test_screenshots.py checks both halves: that the C# the window is compiled from is
# on this list, and that each thing the Dashboard's figures, rows and names are computed
# from - the store, the source of the names, the version, the catalogs, the mutex, the Run
# key, the control layer, the state machine, the synthetic Codex home - moves the envelope
# when it changes what it computes.
WINDOW_INPUTS = (
    ".codex-plugin/plugin.json",          # the version in the footer, and the version resource
    "gui/SettingsApp.cs",                 # the window's layout and wording
    "gui/Dashboard.cs",                   # the Dashboard pages
    "gui/Controls.cs",                    # the soft controls both are drawn with
    "gui/Brand.cs",                       # its palette
    "gui/app.manifest",                   # its DPI awareness, and so its size
    "assets/codex-auto-resume.ico",       # the mark in the title bar, which is captured
    "build/capture_window.ps1",           # how much of the window is captured
    # Whether the icon and the DPI manifest are compiled into the binary at all, and
    # which sources go into it. The two entries above it are only inputs because this
    # file passes them to the compiler.
    "build/make_gui.ps1",
    # The sample installation the window is run against, the questions the envelope asks
    # and how its answers are pinned.
    "build/make_screenshots.py",
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
    raw = path.read_bytes()
    if raw[:6] == b"GIF89a":
        return "%dx%d" % struct.unpack("<HH", raw[6:10])
    return "%dx%d" % struct.unpack(">II", raw[16:24])


# --------------------------------------------------------------------- sample data
def sample_settings() -> dict:
    """The stored settings every picture is drawn from: the defaults, in the pinned THEME.

    Stored, because storing is the only way the window can be given a theme. It resolves the stored
    Theme when it starts, and the default, Use system setting, follows Windows' app mode - so a
    scratch installation holding the plain defaults was photographed dark on a machine in dark mode,
    beside light panel and popup pictures and under a manifest that said light. `--theme` is no way
    round it either: the window's first settings read reopens it in the stored theme.
    """
    return dict(policy.defaults(), theme=THEME)


def write_settings(home: Path) -> Path:
    """Write `sample_settings()` where the window, the bridge and the watcher all read them."""
    state = home / "config"
    state.mkdir(parents=True, exist_ok=True)
    target = state / "settings.json"
    target.write_text(json.dumps(sample_settings(), indent=2), encoding="utf-8")
    return target


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
    from unittest.mock import patch

    from codex_auto_resume import control as control_module
    from codex_auto_resume import l10n, mcpserver, reasons
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
        workspace = Path(name)
        codex, local = workspace / "codex", workspace / "LocalAppData"
        paths = config.Paths(workspace / "home")
        paths.ensure()
        with Store(paths.state_dir) as store:
            # On, as in the picture's headline: a scratch store starts paused, and every row
            # would otherwise carry a "paused" chip under a headline saying recovery is on.
            store.set_enabled(True, 90.0)
            for index, (thread, category) in enumerate(zip(threads, categories)):
                store.register({
                    "thread_id": thread,
                    "turn_id": "0a1b2c3d-020%d-7000-8000-00000000020%d" % (index, index),
                    "completed_at": 110.0 + index, "started_at": 105.0 + index,
                    "ordinal": 2, "interruption_id": chr(ord("a") + index) * 64,
                    "reset_at": 150.0 + index * 600, "limit_type": "codex.primary",
                    "uncertain": False, "category": category}, 100.0 + index)
        # What the window's Diagnostics page and the popup are shown too: the report the
        # watcher's evaluator writes for the synthetic Codex home, and the heartbeat carrying
        # the word it gave - so the panel's compatibility card is the same card, read at the
        # same pinned moment.
        synthetic_codex(codex)
        word = seed_compatibility(paths.home, codex, local, POPUP_NOW)
        write_heartbeat(paths, POPUP_NOW, word)
        surface = control_module.Control(paths)
        # A watcher is running in the picture, so the rows are described as they are when
        # one is - without "watcher not running" beside a headline that says it is. The
        # status is the MCP server's own, which adds the compatibility summary the panel's card
        # is drawn from; read with the clock pinned, the stand-in engine where readers look for
        # it, and the registry read as a scratch installation's, never written.
        with patch.object(control_module.Control, "watcher_running", return_value=True), \
                patch.object(time, "time", return_value=POPUP_NOW), \
                patch.dict(os.environ, {"LOCALAPPDATA": str(local.resolve())}), \
                _registry_stand_in():
            os.environ.pop(config.ENV_CODEX_EXE, None)
            waiting = surface.list_pending()
            status = mcpserver.Server(surface, io.StringIO(), io.StringIO())._status()
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
    # The rest of what `open_settings` returns, so the language choices and the Preview are
    # drawn the way Codex draws them. The system language is pinned to the page's own.
    return {"status": status, "schema": policy.describe(),
            "settings": sample_settings(), "pending": waiting,
            "reasons": list(reasons.RECOVERABLE), "endonyms": dict(l10n.ENDONYMS),
            "system_language": l10n.current()}


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
    from codex_auto_resume.store import Store

    sim = synthetic_codex(codex)
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
        # What the watcher last recorded for each of them, so "Why it is waiting" shows the
        # checklist it shows for a real one: everything it could check passed, the schedule
        # is what it is waiting on, and the checks that need Codex running were not reached.
        from codex_auto_resume import machine
        for index, schedule in ((7, "waiting_reset"), (8, "not_due")):
            vector = {name: machine.gate(machine.PASS) for name in machine.GATES}
            vector["schedule"] = machine.gate(machine.WAIT, schedule)
            for name in ("thread_available", "no_newer_user_work", "usage"):
                vector[name] = machine.gate(machine.UNKNOWN, machine.NOT_CHECKED)
            store.record_gates("%x" % index * 64, vector, now - 40)


def synthetic_codex(codex: Path):
    """The synthetic Codex home `tests/codexsim.py` builds at `codex`: its three databases and
    its rollout directory, with no conversation in them yet - and the folder of conversation
    locks every Codex that has opened a conversation has, so the Diagnostics card can tell
    whether a conversation is open, as it can on a machine that has used Codex."""
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        from codexsim import CodexHome
    finally:
        sys.path.pop(0)
    home = CodexHome(codex)
    (Path(codex) / "thread-writer-locks").mkdir(parents=True, exist_ok=True)
    return home


# The Codex the pictures describe, as `codex --version` names it: the build the synthetic home's
# tables are taken from, and the one the bundled registry data has its one entry for - so the
# Diagnostics card shows that entry's restriction as an installation on this build shows it.
CODEX_VERSION = "codex-cli 0.153.4"
# The content-addressed folder the official installer puts a build in; any hexadecimal name is
# one. From the fixture family, like every other identifier here.
CODEX_BUILD = "0a1b2c3d"
# All the engine checks read of `codex queue --help`: that it still offers the two flags sent.
CODEX_QUEUE_HELP = "Usage: codex queue --thread <THREAD_ID> --message <MESSAGE>\n"


class ProcessRefused(BaseException):
    """Raised by the stand-in for Codex's processes on anything but the two questions it answers.

    A `BaseException`, as `RegistryWriteRefused` is: the engine checks turn a failed process into
    UNAVAILABLE, which would only have changed the picture. This stops the generator instead.
    """


class _CodexProcesses:
    """`subprocess` as `windows.Backend` sees it while the report is made.

    The stand-in engine answers the two questions the engine checks put to the official binary -
    `--version` and `queue --help` - as that build answers them, and nothing is ever started.
    """

    def __init__(self, exe: Path):
        self.exe = exe

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def run(self, argv, **_options):
        argv = [str(part) for part in argv]
        if argv and Path(argv[0]) == self.exe:
            if argv[1:] == ["--version"]:
                return subprocess.CompletedProcess(argv, 0, CODEX_VERSION + "\n")
            if argv[1:] == ["queue", "--help"]:
                return subprocess.CompletedProcess(argv, 0, CODEX_QUEUE_HELP)
        raise ProcessRefused("the screenshot's Codex answers two questions and starts nothing: %r"
                             % argv[1:])


def place_codex(local: Path, at: float) -> Path:
    """A stand-in `codex.exe` where the official installer puts one, under `local`: the scratch
    installation's own LOCALAPPDATA, never the user's. It is never run (`_CodexProcesses`); it is
    there because a report is bound to the engine on disk - its path and its size and time, which
    are pinned to `at` - and every reader looks for it where discovery does."""
    exe = local / "OpenAI" / "Codex" / "bin" / CODEX_BUILD / "codex.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"A stand-in for codex.exe in a screenshot's scratch installation; never run.\n")
    os.utime(exe, ns=(int(at) * 1_000_000_000,) * 2)
    return exe.resolve()


def _checked_as_on_windows(backend) -> dict:
    """`windows.Backend.engine_checks` for the stand-in, off Windows: what it answers on Windows,
    where the official location is a Windows path. Only so the envelope can be recomputed off
    Windows, as `_watcher_mutex_held` answers the mutex probe there; the pictures are made on it."""
    status = backend.codex_exe.stat()
    backend.engine_version = CODEX_VERSION
    return {"official_location": "PASS", "version_runs": "PASS", "queue_flags": "PASS",
            "version": CODEX_VERSION, "signature": (status.st_size, status.st_mtime_ns)}


def frozen_registry():
    """The registry data every picture is made with: v0.6.6's bundled document, frozen in
    `tests/fixtures/codex_compat_frozen.json`. The live file on main changes whenever
    compatibility data is published; a picture must not go stale because of that."""
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        import frozen_registry as frozen
    finally:
        sys.path.pop(0)
    return frozen


def engine_word() -> str:
    """The word the watcher's gate reads, and its heartbeat stores, for CODEX_VERSION once it
    passed its checks, with the registry data the pictures are made with - for the popup, which
    is drawn from a status rather than an installation. `seed_compatibility` checks that the
    watcher's own evaluation gives the same word."""
    from codex_auto_resume import compat, compatio
    with frozen_registry().frozen():
        bundled, _state = compatio.load_bundled()
    return compat.accepted_word(CODEX_VERSION, [("bundled", bundled, True)])


def seed_compatibility(home: Path, codex: Path, local: Path, now: float) -> str:
    """The compatibility report the Diagnostics card is photographed showing, written the way a
    watcher's tick writes it; returns the word the watcher's gate reads, which its heartbeat stores.

    It is the product's code throughout. Discovery finds the engine where the official installer
    puts one (`compatio.discover`, the watcher's own way), `windows.Backend` checks it, and
    `compatio.Evaluator` - the watcher's side - adds the synthetic Codex home's schema, the APIs
    and the bundled registry data in force, and writes `config/compatibility.json`. Only the
    engine is a stand-in (`place_codex`), and it answers only its checks' two questions.

    So the card says what an installation on CODEX_VERSION says: every part its local checks
    establish is Compatible, since the frozen registry data verifies no build; not-loaded recovery is
    Incompatible, from the bundled data's entry for this build; and loaded-state detection is
    Unknown, because the synthetic home has no writer-lock directory for its check to find.

    Checked forty seconds before `now`, on the tick that recorded the waiting rows' gates, and
    read back as every reader reads it - validated, fresh and still bound to the engine on disk -
    so the generator stops rather than photograph a card that says Codex changed.
    """
    from unittest.mock import patch

    from codex_auto_resume import compatio, windows
    local.mkdir(parents=True, exist_ok=True)
    exe = place_codex(local, now - 6 * 24 * 3600)
    paths = config.Paths(home)
    with ExitStack() as stack:
        stack.enter_context(frozen_registry().frozen())
        stack.enter_context(patch.dict(os.environ, {"LOCALAPPDATA": str(local.resolve())}))
        os.environ.pop(config.ENV_CODEX_EXE, None)
        stack.enter_context(patch.object(windows, "S", _CodexProcesses(exe)))
        if os.name != "nt":
            stack.enter_context(patch.object(windows.Backend, "engine_checks", _checked_as_on_windows))
            stack.enter_context(patch.object(windows, "restart_manager_available", return_value=True))
        backend, discovery = compatio.discover(codex)
        if backend is None:
            raise RuntimeError("the stand-in Codex engine was not accepted: %r" % sorted(
                (result or {}).get("official_location") for result in discovery.values()))
        word = compatio.Evaluator(paths, codex, clock=lambda: now - 40).tick(backend, discovery)
        view = compatio.read_view(paths, now=now)
    if view["status"] != "ok":
        raise RuntimeError("the compatibility report reads as %r, not as written" % view["status"])
    if word != engine_word():
        raise RuntimeError("the watcher's evaluation says %r, the popup %r" % (word, engine_word()))
    return word


def write_heartbeat(paths, now: float, engine_state: str) -> None:
    """The watcher's heartbeat as the capture's mutex holder writes it (HOLD_MUTEX), with the
    process id and the clock pinned: a tick a second ago, from a watcher started ninety minutes
    ago, carrying the word its compatibility check gave."""
    from codex_auto_resume.store import Store
    with Store(paths.state_dir) as store:
        store.heartbeat(now - 1, pid=ENVELOPE_PID, session_id="screenshot",
                        started_at=now - 5400, ok=True, engine_state=engine_state,
                        code_version=config.version())


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
#
# Its one answer is the Preview: `preview_recovery_message` returns what the real tool
# returns for the default settings, computed by the same function, so the Continuation
# message card shows real text rather than a spinner. Every other call never settles.
def preview_host() -> str:
    from codex_auto_resume import continuation, reasons
    values = policy.defaults()
    previews = {}
    for category in reasons.RECOVERABLE:
        # No reset time: a clock time would be this machine's, and the page's digest has to
        # be the same on every machine.
        text = continuation.for_settings(category, values,
                                         row={"category": category, "attempt_count": 0})
        previews[category] = {"category": category,
                              "locale": continuation.resolve_locale(values),
                              "style": continuation.style_from(values),
                              "source": continuation.source_for(category, values),
                              "text": text, "refusal": None}
    return ("<script>window.__CAR_PREVIEWS__=%s;window.openai={callTool:function(name,args){"
            "if(name==='preview_recovery_message'&&args&&window.__CAR_PREVIEWS__[args.category])"
            "{return Promise.resolve({structuredContent:{preview:window.__CAR_PREVIEWS__[args.category]}});}"
            "return new Promise(function(){});}};</script>"
            % json.dumps(previews, ensure_ascii=False).replace("<", "\\u003c"))


def panel_html(theme=None) -> str:
    """The exact markup the panel screenshot is a picture of."""
    page = mcpui.settings_page(sample_panel_data(), theme=theme)
    # Before the panel's own script, which reads the host as it starts.
    head, _, tail = page.rpartition("<script>")
    return head + preview_host() + "<script>" + tail


# ------------------------------------------------------------------ tray popup
# The notification-area popup, drawn by its own renderer into memory at a fixed scale and
# written out, so the picture is the same pixels whatever display it is made on. The rows
# are the Dashboard sample's conversations, at a fixed moment, so the countdowns read the
# same every time.
POPUP_SCALE = 2.0
POPUP_NOW = 1_800_000_000.0


def popup_status() -> dict:
    """What the popup is told about the watcher: running, ticking, and the word its heartbeat
    carries for the sample's Codex - the word the window's status card and the panel show."""
    return {"enabled": True, "watcher_running": True,
            "watcher": {"running": True, "ticking": True, "engine_state": engine_word()}}


def popup_rows() -> list:
    def row(index, state, category, eligible, reset, enabled=True):
        return {"interruption_id": ("%x" % index) * 64, "thread_id": WINDOW_THREADS[index - 1],
                "state": state, "category": category, "eligible_at": eligible,
                "reset_at": reset, "next_retry_at": eligible, "thread_enabled": enabled,
                "name": WINDOW_NAMES[index - 1], "overlays": [],
                "detected_at": POPUP_NOW - 600 + index}
    return [row(1, "waiting_reset", "usage_limit", POPUP_NOW + 2540, POPUP_NOW + 2540),
            row(2, "waiting_retry", "network_transient", POPUP_NOW + 95, None),
            row(3, "waiting_backoff", "server_5xx", POPUP_NOW + 610, None, enabled=False)]


def popup_view(locale: str):
    from codex_auto_resume import interface, tray_popup
    strings = interface.STRINGS[locale]
    model = tray_popup.PopupModel(strings)
    model.apply_outcome(("read",), ("ok", {"rows": popup_rows(), "status": popup_status()}), POPUP_NOW)
    return strings, model.view(POPUP_NOW)


def write_png(path: Path, width: int, height: int, bgra: bytes) -> None:
    import zlib
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        line = bgra[y * width * 4:(y + 1) * width * 4]
        for x in range(width):
            raw += bytes((line[x * 4 + 2], line[x * 4 + 1], line[x * 4], 255))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------- animated PNG
# A GIF holds 256 colours, and a screenshot of this window holds thousands: quantising one costs the soft grounds
# and the shadows the whole design is made of. An APNG costs nothing - it is a PNG with more frames, the first of
# which is what a viewer that ignores the rest shows - so the pictures that move keep their name, their colours and
# their still first frame ("APNG (화질 그대로)").
#
# Only what changed is written after the first frame: each later frame carries the smallest rectangle that differs
# from the one before, drawn over it (APNG_OVER, APNG_KEEP). For these pictures that is the status light and
# nothing else, so a breathing dashboard costs a few kilobytes more than a still one.
APNG_KEEP, APNG_OVER = 0, 1          # dispose: leave the frame as it is; blend: draw this frame over it


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    import zlib
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def _png_rows(rgb: bytes, width: int, height: int, stride: int, left: int, top: int, alpha=None) -> bytes:
    """The raw scanlines of a rectangle of a picture, each with the filter byte PNG puts first.

    With `alpha` - one byte a pixel, the whole picture - the rows are RGBA, so a picture that has
    transparent corners keeps them. The window's screenshots do: Windows rounds a window's corners
    and PrintWindow does not draw them, so the capture cuts them to the system's radius and leaves
    them clear, and an encoding that dropped the alpha would fill them with black.
    """
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        row = (top + y) * stride + left
        if alpha is None:
            raw += rgb[row * 3:(row + width) * 3]
            continue
        # Interleaved by three slice assignments rather than a loop over six million pixels: the
        # panel's picture is 1800 by 3424, and a pixel at a time costs half a minute a frame.
        colours = rgb[row * 3:(row + width) * 3]
        line = bytearray(width * 4)
        line[0::4] = colours[0::3]
        line[1::4] = colours[1::3]
        line[2::4] = colours[2::3]
        line[3::4] = alpha[row:row + width]
        raw += line
    return bytes(raw)


def _apng_changed(before: bytes, after: bytes, width: int, height: int) -> tuple:
    """The smallest (left, top, width, height) that differs, or None when the two are the same."""
    left, top, right, bottom = width, height, -1, -1
    for y in range(height):
        row = y * width * 3
        if before[row:row + width * 3] == after[row:row + width * 3]:
            continue
        top = min(top, y)
        bottom = max(bottom, y)
        for x in range(width):
            at = row + x * 3
            if before[at:at + 3] != after[at:at + 3]:
                left = min(left, x)
                right = max(right, x)
    if bottom < 0:
        return None
    return left, top, right - left + 1, bottom - top + 1


def write_apng(path: Path, width: int, height: int, frames: list, alpha=None) -> None:
    """An animated PNG that loops forever, from RGB pictures all `width` by `height`.

    `frames` is [(delay in ms, RGB bytes)], each picture the whole size. The first is what a viewer without APNG
    shows; each later one is written as the rectangle that differs from the frame before it, over it - so a picture
    where only a light moves costs a few hundred bytes a frame, and can be shown at the rate the real thing moves
    at. Nothing here depends on the machine: the same pictures make the same bytes.

    `alpha` is the picture's transparency, one byte a pixel, kept for every frame: only the light moves, and the
    light is never at a corner, so what is transparent stays transparent throughout.
    """
    import zlib
    if not frames:
        raise ValueError("an APNG needs at least one picture")
    denominator = 1000
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0))
    out += _png_chunk(b"acTL", struct.pack(">II", len(frames), 0))
    sequence = 0
    out += _png_chunk(b"fcTL", struct.pack(">IIIIIHHBB", sequence, width, height, 0, 0,
                                           frames[0][0], denominator, APNG_KEEP, APNG_OVER))
    sequence += 1
    out += _png_chunk(b"IDAT", zlib.compress(_png_rows(frames[0][1], width, height, width, 0, 0, alpha), 9))
    previous = frames[0][1]
    for delay_ms, picture in frames[1:]:
        box = _apng_changed(previous, picture, width, height)
        if box is None:
            box = (0, 0, 1, 1)                       # a frame that changes nothing still takes its time
        left, top, wide, tall = box
        out += _png_chunk(b"fcTL", struct.pack(">IIIIIHHBB", sequence, wide, tall, left, top,
                                               delay_ms, denominator, APNG_KEEP, APNG_OVER))
        sequence += 1
        rows = _png_rows(picture, wide, tall, width, left, top, alpha)
        out += _png_chunk(b"fdAT", struct.pack(">I", sequence) + zlib.compress(rows, 9))
        sequence += 1
        previous = picture
    out += _png_chunk(b"IEND", b"")
    path.write_bytes(bytes(out))


def read_png_rgb(path: Path) -> tuple:
    """(width, height, RGB bytes) of an 8-bit RGB or RGBA PNG - the first frame of an APNG included."""
    width, height, rgb, _alpha = read_png(path)
    return width, height, rgb


def read_png(path: Path) -> tuple:
    """(width, height, RGB bytes, alpha bytes or None) of an 8-bit RGB or RGBA PNG.

    The two planes are kept apart because everything that draws here works in RGB; the alpha is
    carried along so that what a picture has transparent - the corners Windows rounds - survives
    being written out again.
    """
    import zlib
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG: %s" % path)
    at, data, width, height, channels = 8, bytearray(), None, None, 3
    while at < len(raw):
        length, kind = struct.unpack(">I4s", raw[at:at + 8])
        body = raw[at + 8:at + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or colour not in (2, 6) or interlace:
                raise ValueError("unsupported PNG layout: %s" % path)
            channels = 3 if colour == 2 else 4
        elif kind == b"IDAT":
            data += body
        elif kind == b"IEND":
            break
        at += 12 + length
    pixels = zlib.decompress(bytes(data))
    stride = width * channels
    out, clear, previous = bytearray(), bytearray(), bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        mode, line = pixels[start], bytearray(pixels[start + 1:start + 1 + stride])
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if mode == 1:
                line[i] = (line[i] + left) & 0xFF
            elif mode == 2:
                line[i] = (line[i] + up) & 0xFF
            elif mode == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif mode == 4:
                guess = left + up - corner
                pa, pb, pc = abs(guess - left), abs(guess - up), abs(guess - corner)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 0xFF
        if channels == 3:
            out += line
        else:
            out += bytes(b for x in range(width) for b in line[x * 4:x * 4 + 3])
            clear += line[3::4]
        previous = line
    # A picture that is opaque everywhere is handed back without an alpha at all, so it is written
    # as the RGB it always was: only the window's captures, whose corners Windows rounds, carry one.
    return width, height, bytes(out), (bytes(clear) if channels == 4 and min(clear) < 255 else None)


def render_popup(target: Path, locale: str) -> None:
    from codex_auto_resume import tray_popup
    strings, view = popup_view(locale)
    renderer = tray_popup.Renderer()
    renderer.theme = THEME                      # said, not left to the renderer's default
    try:
        plan = renderer.layout(view, POPUP_SCALE, tray_popup.locale_of(strings))
        canvas = renderer.draw(view, plan, frame=tray_popup.halo(view["state"], 600, 5000))
        width, height = plan["size"]
        write_png(target, width, height, canvas.pixels())
    finally:
        renderer.close()


# What draws the popup, whichever file it is in.
#
# The popup's pixels are the view it is given and the code that draws it. The view is hashed
# as JSON. The code was hashed as two files, `tray_popup.py` and `brand.py`, which made every
# comment a reason to re-render - and made moving the renderer into `ui/popup/` and the
# palette into `ui/brand/`, which v0.6.5 does, a `FileNotFoundError` inside `render_inputs`.
#
# It is hashed now as what those modules define. Every top-level definition of every module
# `POPUP_CODE` matches - a function, a class, a constant, a token - is keyed by its name,
# with comments, docstrings and import statements left out, and the modules are pooled. So a
# definition moved from one module to another, with the imports that follow it, hashes the
# same; a changed line of drawing code, a changed token, a new definition or a removed one
# does not. The patterns already cover the two packages the modules are moving into, so the
# day they exist nothing here has to be remembered.
#
# The popup also draws with definitions it imports by name from the rest of the package -
# the icon's countdown, and the Win32 structures and DLL cache the split moves into `win/` -
# and those are pooled too, found by following the import to whichever module holds the
# definition today (`imported_definitions`). So moving one out of the popup's modules into
# `win/dll.py`, or from `tray.py` into it, with the import that brings it back, hashes the
# same as well, without `win/` having to be one of the patterns - which would pool the rest
# of that package, the icon's and the card's structures, into the popup's key.
POPUP_CODE = ("tray_popup.py", "brand.py", "ui/popup/**/*.py", "ui/brand/**/*.py")


def code_files(patterns, package=None) -> list:
    """Every module `patterns` match under the package, in a stable order."""
    package = Path(package) if package is not None else ROOT / "src" / "codex_auto_resume"
    found = set()
    for pattern in patterns:
        found.update(path for path in package.glob(pattern)
                     if path.is_file() and "__pycache__" not in path.parts)
    return sorted(found, key=lambda path: path.relative_to(package).as_posix())


def popup_code_files(package=None) -> list:
    """Every module `POPUP_CODE` matches under the package, in a stable order."""
    return code_files(POPUP_CODE, package)


def _is_docstring(statement) -> bool:
    return (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str))


def _without_imports_or_docstrings(node):
    """A copy of `node` with every import statement, at any depth, and every docstring gone.

    A move rewrites the imports that follow the code - `from .brand import X` becomes
    `from ..brand.tokens import X`, inside a function as readily as at the top - and changes
    nothing else, so the imports are exactly the part a move-proof digest must not see.
    """
    import copy
    node = copy.deepcopy(node)
    for inner in ast.walk(node):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(inner, field, None)
            if not isinstance(block, list) or not all(isinstance(item, ast.stmt) for item in block):
                continue
            kept = [item for item in block if not isinstance(item, (ast.Import, ast.ImportFrom))]
            if (field == "body" and kept and _is_docstring(kept[0])
                    and isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))):
                kept = kept[1:]
            if block and not kept:
                kept = [ast.Pass()]
            setattr(inner, field, kept)
    return node


def _canonical_ast(node) -> str:
    """One spelling of a syntax tree on every Python the suite runs on.

    Not `ast.dump`: 3.13 stopped printing empty lists and `None` fields by default, so the
    same code dumped differently on 3.12, and a field a later Python adds with an empty
    default would do it again. Omitting empty values in both is what keeps one digest true
    on every interpreter CI runs, and a recorded digest recomputable on any of them.
    """
    if isinstance(node, ast.AST):
        fields = ["%s=%s" % (name, _canonical_ast(value)) for name, value in ast.iter_fields(node)
                  if value is not None and value != []]
        return "%s(%s)" % (type(node).__name__, ", ".join(fields))
    if isinstance(node, list):
        return "[%s]" % ", ".join(_canonical_ast(item) for item in node)
    return repr(node)


def _statements(body, guards=()):
    """(guards, statement) for each definition in a module body, imports and docstrings aside.

    A top-level `if` - `if os.name == "nt":` around the Win32 structures - is looked into, and
    each definition inside it carries the condition, so splitting one guarded block between
    two modules keeps every definition's key.
    """
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or _is_docstring(node):
            continue
        if isinstance(node, ast.If):
            test = _canonical_ast(node.test)
            yield from _statements(node.body, guards + ("if " + test,))
            yield from _statements(node.orelse, guards + ("not " + test,))
            continue
        yield guards, node


def _entry(guards, node) -> str:
    """`guard | ... | name | tree`: one definition, as the digest keys it."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        name = node.name
    elif isinstance(node, ast.Assign):
        name = ",".join(_canonical_ast(target) for target in node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        name = _canonical_ast(node.target)
    else:
        name = "<%s>" % type(node).__name__
    return " | ".join(guards + (name, _canonical_ast(_without_imports_or_docstrings(node))))


def _definitions(body, guards=()):
    """`guard | ... | name | tree` for each definition in a module body (see `_statements`)."""
    for statement_guards, node in _statements(body, guards):
        yield _entry(statement_guards, node)


def _bound(node) -> set:
    """The names a top-level statement binds: a definition's own name, or every name it
    assigns - without looking inside the functions and classes it defines."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    names, pending = set(), [node]
    while pending:
        inner = pending.pop()
        if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(inner.name)
            continue
        if isinstance(inner, ast.Lambda):
            continue
        if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store):
            names.add(inner.id)
        pending.extend(ast.iter_child_nodes(inner))
    return names


class _Module:
    """One module of the package, read for what it defines and imports at its top level."""

    def __init__(self, dotted: str, path: Path, index: dict, package_name: str):
        self.dotted, self.index, self.package_name = dotted, index, package_name
        self.is_package = path.name == "__init__.py"
        self.tree = ast.parse(path.read_text(encoding="utf-8"))
        self.defines, self.imports, self.stars = {}, {}, []
        for guards, node in _statements(self.tree.body):
            for name in _bound(node):
                self.defines.setdefault(name, []).append((guards, node))
        pending = list(self.tree.body)
        while pending:                      # module level: into `if` and `try`, never a function
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    for target, name in self.named(node, alias):
                        if name == "*":
                            self.stars.append(target)
                        else:
                            self.imports[alias.asname or alias.name] = (target, name)
            pending.extend(ast.iter_child_nodes(node))

    def target(self, node):
        """The module an import names, dotted from the package; None outside the package."""
        if node.level:
            parts = self.dotted.split(".") if self.dotted else []
            if not self.is_package:
                parts = parts[:-1]
            if node.level > 1:
                parts = parts[:len(parts) - (node.level - 1)]
            return ".".join(part for part in (".".join(parts), node.module) if part)
        module = node.module or ""
        if module == self.package_name:
            return ""
        if module.startswith(self.package_name + "."):
            return module[len(self.package_name) + 1:]
        return None

    def named(self, node, alias=None):
        """(module, name) for each name an import takes from a module of the package - not
        the modules it takes (`from . import brand`), which bring no definition by name."""
        target = self.target(node)
        if target is None:
            return []
        found = []
        for each in ([alias] if alias is not None else node.names):
            submodule = (target + "." + each.name) if target else each.name
            if each.name != "*" and submodule in self.index:
                continue
            found.append((target, each.name))
        return found


def _module_index(package: Path) -> dict:
    """Dotted name within the package (`ui.popup.layout`, "" for the package) -> its file."""
    index = {}
    for path in package.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(package).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        index[".".join(parts)] = path
    return index


def imported_definitions(package, files) -> list:
    """The entries of every definition `files` import by name from the rest of `package`,
    wherever it is defined, and of what those definitions use in turn.

    `from .tray import countdown` in the popup brings `tray.countdown`; `from .tray import
    GUID`, once `tray.py` itself only re-exports it from `win/dll.py`, brings `GUID` from
    there. A definition takes with it the names of its own module it refers to - `_dll`
    brings the `_DLLS` cache it fills - and whatever it imports by name. A definition in one
    of `files` is pooled with them and is not followed again. A module reached as a whole
    (`from . import tray`, then `tray.countdown`) is not followed: the popup does not do that.
    """
    package = Path(package)
    index = _module_index(package)
    own = {dotted for dotted, path in index.items()
           if any(path.resolve() == Path(name).resolve() for name in files)}
    read = {}

    def module(dotted):
        if dotted not in read:
            read[dotted] = (_Module(dotted, index[dotted], index, package.name)
                            if dotted in index else None)
        return read[dotted]

    pending = []
    for dotted in sorted(own):
        reader = module(dotted)
        for node in ast.walk(reader.tree):            # function-level imports draw too
            if isinstance(node, ast.ImportFrom):
                pending.extend(reader.named(node))
    asked, taken, entries = set(), set(), []
    while pending:
        dotted, name = pending.pop()
        if (dotted, name) in asked or dotted in own:
            continue
        asked.add((dotted, name))
        reader = module(dotted)
        if reader is None:
            continue
        if name == "*":
            pending.extend((dotted, public) for public in reader.defines if not public.startswith("_"))
        elif name in reader.defines:
            for guards, node in reader.defines[name]:
                if (dotted, id(node)) in taken:
                    continue
                taken.add((dotted, id(node)))
                entries.append(_entry(guards, node))
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Name):
                        pending.append((dotted, inner.id))
                    elif isinstance(inner, ast.ImportFrom):
                        pending.extend(reader.named(inner))
        elif name in reader.imports:
            pending.append(reader.imports[name])
        else:
            pending.extend((star, name) for star in reader.stars)
    return entries


def code_digest(files, imported=()) -> str:
    """The definitions of `files`, pooled with `imported` entries, keyed by name and hashed.

    Independent of which of the files a definition lives in, of the order the definitions
    come in, and of comments, docstrings and import statements; dependent on everything else.
    """
    entries = list(imported)
    for path in files:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        entries.extend(_definitions(tree.body))
    return sha256("\n".join(sorted(entries)).encode("utf-8"))


def popup_drawing(package=None) -> str:
    """The digest of what draws the popup: the definitions of the modules `POPUP_CODE`
    matches, and of everything they import by name from the rest of the package."""
    package = Path(package) if package is not None else ROOT / "src" / "codex_auto_resume"
    files = popup_code_files(package)
    return code_digest(files, imported_definitions(package, files))


def popup_render_input(locale: str, drawing: str | None = None) -> str:
    """The popup's manifest entry for one locale: what it is shown, and what draws it.

    `drawing` is `popup_drawing()`, passed in when it is already known.
    """
    _strings, view = popup_view(locale)
    if drawing is None:
        drawing = popup_drawing()
    return sha256((json.dumps(view, sort_keys=True, default=str) + drawing).encode("utf-8"))


# ------------------------------------------------------------ the notification card
# Since v0.6.5 a notification appears as the product's own card beside the notification area
# (`notice_card.py`, `notice_window.py`), and as Windows' toast only where a card must not be
# shown. The README went on showing a capture of that toast taken before Open Dashboard existed,
# and nothing pinned it, so nothing noticed.
#
# The card is drawn here the way `tests/test_notice_card.py` draws it: a `notice_window.Card`
# with no windows - laid out by `notice_card.layout`, painted by the popup's own renderer at the
# popup pictures' scale, with its floating shadow - settled, and laid over the theme's canvas,
# the ground the popup pictures stand on. No window is made and nothing reaches the screen.
#
# What it says is what the watcher would say, built by the builder the watcher uses
# (`notifier.build`) from the catalogs: a usage limit detected on the Dashboard sample's first
# conversation - its synthetic id, and the name the synthetic Codex home gives it, which is all
# `LocalSource.identity` finds there - resetting when the popup's row for it says. The reset
# time is the one word a machine would change, since the toast writes it in local time, so it is
# read here on a clock pinned to UTC.
CARD_SCALE = POPUP_SCALE
CARD_RESET_AT = POPUP_NOW + 2540            # popup_rows()'s usage limit, on the same conversation
CARD_INTERRUPTION = "1" * 64                # its interruption: in a button's URI, never drawn
# Both themes for the two README languages; the popup's documentation languages in the pinned
# theme, as the popup is drawn.
# The documentation is drawn in the light theme; the dark one is described rather than pictured, which is
# the user's call ("대부분의 이미지는 화이트모드만 해") and halves the pictures a reader scrolls past.
CARD_THEMES = ("light",)
# Canonical asset name and documentation copy name; a dark picture adds "-dark" before the
# locale's tag.
CARD_NAMES = ("screenshot-notification", "notification-card")

# What draws the card, whichever file it is in: its own two modules, the package v0.6.10-alpha moves
# them into, and the popup's renderer and palette it is painted with. Keyed exactly as the
# popup is (see POPUP_CODE): definitions pooled by name, what they import by name followed to
# wherever it is defined.
CARD_CODE = ("notice_card.py", "notice_window.py", "ui/card/**/*.py") + POPUP_CODE


def card_themes(locale: str) -> tuple:
    return CARD_THEMES if locale in LOCALES else (THEME,)


def card_paths(locale: str) -> dict:
    """theme -> (canonical asset or None, documentation copy), for one locale's card pictures.

    The README languages' go into assets/ with a copy in docs/images/, as the window's do; the
    documentation languages' only into docs/images/, as the popup's do."""
    tag = "" if locale == "en" else "-" + locale
    found = {}
    for theme in card_themes(locale):
        shade = "" if theme == "light" else "-" + theme
        asset = ASSETS / ("%s%s%s.png" % (CARD_NAMES[0], shade, tag)) if locale in LOCALES else None
        found[theme] = (asset, DOCS / ("%s%s%s.png" % (CARD_NAMES[1], shade, tag)))
    return found


def card_identity() -> dict:
    """What `LocalSource.identity` finds for the sample's first conversation in the synthetic
    Codex home: its name, and no project or working directory, which that home does not have."""
    return {"name": WINDOW_NAMES[0], "project": None, "cwd_basename": None}


def _utc_time(when: float) -> str:
    return time.strftime("%H:%M", time.gmtime(when))


def card_notice(locale: str):
    """The Notice the watcher builds for the sample's usage limit, in `locale`."""
    from codex_auto_resume import notifier, notify
    previous, local_time = l10n.preference(), notify._local_time
    l10n.set_preference(locale)                 # the stored Interface language, as the watcher's
    notify._local_time = _utc_time
    try:
        return notifier.build("interruption", {"thread_id": WINDOW_THREADS[0],
                                               "interruption_id": CARD_INTERRUPTION,
                                               "reset_at": CARD_RESET_AT, "category": "usage_limit"},
                              card_identity())
    finally:
        notify._local_time = local_time
        l10n.set_preference(previous)


def card_view(locale: str) -> dict:
    """What the card says, as `notice_card.view` gives it to the layout."""
    from codex_auto_resume import notice_card
    return notice_card.view(card_notice(locale))


def card_code_files(package=None) -> list:
    """Every module `CARD_CODE` matches under the package, in a stable order."""
    return code_files(CARD_CODE, package)


def card_drawing(package=None) -> str:
    """The digest of what draws the card: the definitions of the modules `CARD_CODE` matches,
    and of everything they import by name from the rest of the package."""
    package = Path(package) if package is not None else ROOT / "src" / "codex_auto_resume"
    files = card_code_files(package)
    return code_digest(files, imported_definitions(package, files))


def card_render_input(locale: str, drawing: str | None = None) -> str:
    """The card's manifest entry for one locale: what it says, the themes and scale it is
    pictured at, and what draws it. `drawing` is `card_drawing()` when already known."""
    shown = {"view": card_view(locale), "themes": list(card_themes(locale)), "scale": CARD_SCALE}
    if drawing is None:
        drawing = card_drawing()
    return sha256((json.dumps(shown, sort_keys=True, default=str) + drawing).encode("utf-8"))


class _NoStack:
    """What a Card asks of its stack when it has no windows: how long it holds - which moves no
    pixel, and is not read from Windows' setting here - and the windows it would list."""

    def __init__(self):
        self.windows = {}

    def hold(self):
        from codex_auto_resume import notice_card
        return float(notice_card.HOLD_MS)


def _over(ground: bytearray, ground_width: int, layer: bytes, width: int, height: int,
          left: int, top: int) -> None:
    """Premultiplied BGRA `layer` over the opaque BGRA `ground`, its top-left at (left, top)."""
    for y in range(height):
        row = layer[y * width * 4:(y + 1) * width * 4]
        base = ((top + y) * ground_width + left) * 4
        for x in range(width):
            alpha = row[x * 4 + 3]
            if alpha == 0:
                continue
            at = base + x * 4
            if alpha == 255:
                ground[at:at + 3] = row[x * 4:x * 4 + 3]
                continue
            keep = 255 - alpha
            for channel in range(3):
                ground[at + channel] = min(255, row[x * 4 + channel]
                                           + (ground[at + channel] * keep + 127) // 255)


def card_pixels(locale: str, theme: str):
    """(width, height, BGRA): the settled card and its floating shadow over the theme's canvas."""
    from codex_auto_resume import brand, notice_card, notice_window, tray_popup
    where = {"dpi": int(round(96 * CARD_SCALE)), "work": (0, 0, 0, 0), "monitor": (0, 0, 0, 0),
             "anchor": None}
    drawn = {"theme": theme, "contrast": False, "reduced": False}
    tray_popup._gdiplus_acquire()
    try:
        card = notice_window.Card(_NoStack(), card_notice(locale), now_ms=0, where=where, drawn=drawn,
                                  windows=False)
        try:
            frame = card.paint(notice_card.ENTRANCE_MS)["frame"]     # at rest: whole, full depth
            if frame != notice_card.SETTLED:
                raise RuntimeError("the card is not at rest: %r" % (frame,))
            (width, height), margin = card.size, card.margin
            body, shadow = card.body.pixels(), card.shadow.pixels()
        finally:
            card.close()
    finally:
        tray_popup._gdiplus_release()
    # The ground reaches as far as the deeper theme's shadow in both, so a light and a dark
    # picture of the same card are the same size and can stand side by side.
    pad = max(notice_card.shadow_margin(notice_card.float_shadows(each), CARD_SCALE)
              for each in CARD_THEMES)
    red, green, blue = brand.rgb(brand.palette(theme)["canvas"])
    full_width, full_height = width + 2 * pad, height + 2 * pad
    ground = bytearray(bytes((blue, green, red, 255)) * (full_width * full_height))
    if margin:
        _over(ground, full_width, shadow, width + 2 * margin, height + 2 * margin,
              pad - margin, pad - margin)
    _over(ground, full_width, body, width, height, pad, pad)
    return full_width, full_height, bytes(ground)


def render_card(target: Path, locale: str, theme: str) -> None:
    width, height, pixels = card_pixels(locale, theme)
    write_png(target, width, height, pixels)


def _card_files() -> list:
    """Every card picture the set holds, canonical assets first."""
    pairs = [pair for locale in LOCALES + EXTRA_LOCALES for pair in card_paths(locale).values()]
    return [asset for asset, _copy in pairs if asset is not None] + [copy for _asset, copy in pairs]


def render_cards() -> list:
    """Only the notification card's pictures: render them, copy them and pin them.

    For a change that moves only the card, and for looking at it: no Edge, no compiled window
    and no scratch installation, only Windows' GDI+. Every other entry in the manifest is left
    as it was, so this is no substitute for a whole run when anything else moved.

        python build/make_screenshots.py --cards
    """
    for locale in LOCALES + EXTRA_LOCALES:
        for theme, (asset, copy) in card_paths(locale).items():
            render_card(asset or copy, locale, theme)
            if asset is not None:
                shutil.copyfile(asset, copy)
            print("  %s  %s" % ((asset or copy).relative_to(ROOT), dimensions(asset or copy)))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    drawing = card_drawing()
    for locale in LOCALES + EXTRA_LOCALES:
        manifest["inputs"]["<card render:%s>" % locale] = card_render_input(locale, drawing)
    ordered = {}
    for key, value in manifest.items():                 # where a whole run writes it
        if key != "card_themes":
            ordered[key] = value
        if key == "theme":
            ordered["card_themes"] = list(CARD_THEMES)
    manifest = ordered
    files = _card_files()
    for path in files:
        manifest["images"][str(path.relative_to(ROOT)).replace("\\", "/")] = {
            "sha256": sha256(path.read_bytes()), "size": dimensions(path)}
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifest       : %s (the card's entries only)" % MANIFEST.relative_to(ROOT))
    return files


# ------------------------------------------------------------ the icon's motion
# Since v0.6.5 the notification-area icon moves (tray.py, "the icon's motion"), and the README shows how, as an
# animated GIF. It is drawn here and never by hand: every picture in it is the icon's own frame (tray.IconFrames, with
# nothing on top since v0.6.8, as the icon has nothing), at the moments the icon's own timer shows one
# (tray.icon_frame and icon_frame_ms, stepped as the frame timer steps), laid over a light and a dark taskbar. Five
# states side by side - watching, recovering, needing attention, failed and paused - over a stretch of watching's
# loop that begins two breaths before a sweep and is a whole number of its loops and of recovering's and a failure's
# sweeps and of a failure's 1.2 s blink (`icon_motion_stretch`), so those columns loop without a jump. Attention's
# slow breath does not divide it:
# where the picture starts again that column is within one level of 24 of where it began.
#
# Its manifest entry, `<icon motion>`, is keyed as the card's is: what is pictured (the states, the size, the grounds and the stretch of the loop) and the digest of the code that draws the frames - here the
# definitions the frame table and the schedule are made of, followed name by name from the few the GIF calls
# (ICON_ROOTS) to whatever they use, in whichever module that lives (`icon_drawing`). So a change to the motion, its
# numbers, the mark or its colours marks the GIF stale; a change to the icon's menu or popup does not.
ICON_MOTION_APNG = DOCS / "icon-motion.png"
# The icon at 48 px: the notification-area icon at 300%, and the taskbar button's big icon at 150%, which the .ico
# carries as an entry of its own.
ICON_MOTION_SIZE = 48
ICON_MOTION_PAD = 12
# The states pictured, each as the status-light word the icon takes it from (tray.ICON_FOR_LIGHT).
ICON_MOTION_LIGHTS = (("watching", "monitoring"), ("recovering", "recovering"), ("attention", "attention"),
                      ("failed", "failed"), ("idle", "paused"))
# Windows 11's taskbar in its light and its dark mode, as assets/make_icon.py's contact sheet has them.
ICON_MOTION_GROUNDS = (("light", "#EEF0F3"),)
# The shortest a picture is held, in hundredths of a second. Browsers - Chromium, Firefox and Safari alike - show a
# picture of 10 ms or less for 100 ms, so moments of the states closer than this are one picture: the later one's.
ICON_MOTION_SHORTEST = 2
# What the GIF draws with, followed from these to everything they use (`icon_drawing`).
ICON_ROOTS = (("tray", "IconFrames"), ("tray", "icon_frame"), ("tray", "icon_frame_ms"), ("tray", "icon_head_colour"),
              ("tray", "icon_level_colour"), ("tray", "ICON_FOR_LIGHT"), ("brand", "rgb"))


# --------------------------------------------------------- pictures that breathe
# A still picture of a light says nothing about a light that moves, so the pictures a reader meets first are
# animated: the same capture, with its status light redrawn frame by frame from brand.glow - the function the
# window, the popup and the panel all draw it with - at the rate the window itself repaints (BREATHE_FPS).
#
# Nothing else in the picture moves. The light is found by its own colour (`find_light`), the ground under it is
# the card it sits on, and every frame is the capture with that one disc painted again; what a viewer without APNG
# sees is the first frame, which is the still picture that was always there.
BREATHE_FPS = 30
# Monitoring's rhythm, which is also waiting's (brand.GLOW waiting_ms) - and waiting is the state most of
# these pictures are in, since their sample data has interruptions waiting. One rhythm covers both.
BREATHE_STATE = "monitoring"


# How far toward the card a dot may be dimmed and still be the dot. brand.glow dims to `glow_floor` - about 0.38
# of the way - at the bottom of a breath, and the glow round it never comes closer to the light's own colour than
# about two thirds of the way, so a threshold between the two tells a dimmed dot from the glow it sits in.
LIGHT_DIM = 0.45


def find_light(rgb: bytes, width: int, height: int, colour: tuple, ground: tuple) -> tuple | None:
    """(x, y, radius) of the status light in a captured picture, or None where it is not there.

    The light is the topmost round disc of its own colour, at any point of its breath: a captured window or panel
    is caught at whatever moment it was in, and since v0.6.9 waiting breathes too, so the dot in a picture is
    rarely at full brightness. Pixels are taken as the light's when they lie on the line from its colour toward
    the card under it, no further than LIGHT_DIM - which the glow never reaches - and gathered into clusters; a
    chip or a button is a rectangle and loses the roundness check, a glyph is neither round nor wide enough.

    Topmost, not roundest: every surface carries its status light at the top, and the panel's pictures used to
    breathe an 8 px dot in the Automatic recovery tile far below it - a dot that never moves in the product -
    because it scored as the rounder disc.
    """
    def lit(at):
        """Whether the pixel at byte offset `at` is the light's colour, dimmed no further than LIGHT_DIM."""
        spread = max(abs(one - other) for one, other in zip(colour, ground))
        if spread == 0:
            return False
        channel = max(range(3), key=lambda index: abs(ground[index] - colour[index]))
        share = (rgb[at + channel] - colour[channel]) / float(ground[channel] - colour[channel])
        if not -0.02 <= share <= LIGHT_DIM:
            return False
        return all(abs(rgb[at + index] - (colour[index] + share * (ground[index] - colour[index]))) <= 6
                   for index in range(3))

    seen, clusters = set(), []
    for y in range(height):
        row = y * width * 3
        for x in range(width):
            if (x, y) in seen or not lit(row + x * 3):
                continue
            stack, found = [(x, y)], []
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                found.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen and lit((ny * width + nx) * 3):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            clusters.append(found)
    best = None
    for found in clusters:
        xs = [x for x, _ in found]
        ys = [y for _, y in found]
        wide, tall = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if abs(wide - tall) > 2 or not (6 <= wide <= 40):
            continue                                        # a small disc, not a chip and not a glyph
        area = 3.14159 * (wide / 2.0) ** 2
        if abs(len(found) - area) > 0.35 * area:
            continue                                        # filled like a disc, not a ring or a letter
        top = min(ys)
        if best is None or top < best[0]:
            best = (top, (sum(xs) / len(xs), sum(ys) / len(ys)), wide / 2.0)
    return None if best is None else (best[1][0], best[1][1], best[2])


def breathe_over(rgb: bytes, width: int, height: int, where: tuple, ground: tuple, colour: tuple) -> list:
    """One cycle of the light, as whole pictures: the capture with its light redrawn at each moment.

    `where` is (x, y, drawn radius) from find_light, `ground` the card's colour under it and `colour` the light's.
    Every pixel of the disc is sampled nine times across, as the window's own antialiasing does.
    """
    from codex_auto_resume import brand
    cycle = brand.GLOW[BREATHE_STATE + "_ms"]
    steps = int(round(cycle / 1000.0 * BREATHE_FPS))
    delay = int(round(cycle / steps))
    centre_x, centre_y, drawn = where
    dot = brand.STATUS_DOT["window"]
    reach = brand.glow_reach(dot) * (drawn / dot)
    stops = brand.glow_stops(dot)
    box = int(drawn + reach) + 2
    frames = []
    for step in range(steps):
        frame = brand.glow(BREATHE_STATE, step / float(steps) * cycle)
        outer = drawn + reach * frame["spread"]
        picture = bytearray(rgb)
        for y in range(max(0, int(centre_y - box)), min(height, int(centre_y + box) + 1)):
            for x in range(max(0, int(centre_x - box)), min(width, int(centre_x + box) + 1)):
                red = green = blue = 0.0
                for sub_y in range(3):
                    for sub_x in range(3):
                        away = (((x + (sub_x + 0.5) / 3.0 - 0.5) - centre_x) ** 2
                                + ((y + (sub_y + 0.5) / 3.0 - 0.5) - centre_y) ** 2) ** 0.5
                        parts = list(ground)
                        if frame["opacity"] > 0 and outer > 0 and away < outer:
                            alpha = frame["opacity"] * _falloff(stops, away / outer)
                            parts = [part + (one - part) * alpha for part, one in zip(parts, colour)]
                        if away < drawn:
                            parts = [part + (one - part) * (1.0 - frame["dim"])
                                     for part, one in zip(parts, colour)]
                        red += parts[0]; green += parts[1]; blue += parts[2]
                at = (y * width + x) * 3
                picture[at] = int(round(red / 9.0))
                picture[at + 1] = int(round(green / 9.0))
                picture[at + 2] = int(round(blue / 9.0))
        frames.append((delay, bytes(picture)))
    return frames


# The pictures that hold a light that moves. The icon's and the light's own pictures are animated already, and the
# social preview is a poster. The notification card was here too while it held still: since v0.6.9 an interruption
# waiting for its reset breathes, on the card as everywhere, so its picture breathes with it.
BREATHE_SKIP = ("icon-motion", "status-light", "social-preview")


def breathes(path: Path) -> bool:
    """Whether a picture is one whose light moves in the product."""
    return not any(part in path.name for part in BREATHE_SKIP)


def breathe_pictures(paths=None) -> list:
    """Make every captured picture with a status light breathe, and say which ones did.

    A documentation copy is copied rather than drawn again: two encodings of one picture are two
    files, and the suite holds each copy to be its canonical asset byte for byte.

        python build/make_screenshots.py --breathe
    """
    copies = {}
    for locale in LOCALES:
        copies.update(paths_for(locale))
    if paths is None:
        paths = sorted(list(ASSETS.glob("*.png")) + [path for path in DOCS.glob("*.png")
                                                     if path not in set(copies.values())])
    done = []
    for path in paths:
        if not breathes(path):
            continue
        if breathe_picture(path):
            done.append(path)
            print("  %s  %s" % (path.relative_to(ROOT), dimensions(path)))
            copy = copies.get(path)
            if copy is not None:
                shutil.copyfile(path, copy)
                done.append(copy)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for path in done:
        key = str(path.relative_to(ROOT)).replace("\\", "/")
        if key in manifest["images"]:
            entry = manifest["images"][key]
            if isinstance(entry, dict):
                manifest["images"][key] = {"sha256": sha256(path.read_bytes()), "size": dimensions(path)}
            else:
                manifest["images"][key] = sha256(path.read_bytes())
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifest       : %s (the pictures that breathe)" % MANIFEST.relative_to(ROOT))
    return done


def breathe_picture(path: Path, theme: str = "light") -> bool:
    """Rewrite a captured picture as an APNG whose status light breathes. False when it has no light to find."""
    from codex_auto_resume import brand
    palette = brand.palette(theme)
    width, height, rgb, alpha = read_png(path)
    colour = brand.rgb(palette[brand.status_fill(BREATHE_STATE)])
    ground = brand.rgb(palette["surface"])
    where = find_light(rgb, width, height, colour, ground)
    if where is None:
        return False
    frames = breathe_over(rgb, width, height, where, ground, colour)
    write_apng(path, width, height, frames, alpha)
    return True


# ---------------------------------------------------------------- the status light, as a GIF
# The light is a rhythm, and a still picture of a rhythm says nothing - so the documentation carries one breath of
# it as an animated GIF, drawn here from brand.glow itself at the window's dot size, on the card it sits on. One
# cycle exactly, so it loops where it began, and the light theme only, as the rest of the pictures are.
#
# Its manifest entry, `<light motion>`, is what it pictures and the digest of what draws it (LIGHT_ROOTS,
# followed), so a change to the curve, the depth, the reach or the colours marks it stale.
LIGHT_MOTION_APNG = DOCS / "status-light.png"
LIGHT_MOTION_STATE = "monitoring"
LIGHT_MOTION_SCALE = 6              # the window's 5 px dot, drawn at 30
LIGHT_MOTION_PAD = 6                # CSS px of card round the glow's widest
# Pictures a second. The window's own light redraws on a 33 ms timer, so this is the rate the real thing
# moves at rather than a rate that merely reads as smooth.
LIGHT_MOTION_FPS = 30
LIGHT_ROOTS = (("brand", "glow"), ("brand", "glow_stops"), ("brand", "glow_radius"), ("brand", "glow_extent"),
               ("brand", "STATUS_DOT"), ("brand", "status_fill"), ("brand", "LIGHT"), ("brand", "rgb"))


def light_motion_cell(fraction: float) -> tuple:
    """(width, RGB bytes) of the light at `fraction` of its cycle: the glow under the dot, both over the card.

    Every pixel is sampled nine times across, so an edge is the curve's and not the grid's; the alphas are
    brand's own - the glow's falloff at that spread, then the dot at what the breath leaves it."""
    from codex_auto_resume import brand
    dot = brand.STATUS_DOT["window"]
    half = (brand.glow_extent(dot) + LIGHT_MOTION_PAD) * LIGHT_MOTION_SCALE
    size = int(round(2 * half))
    frame = brand.glow(LIGHT_MOTION_STATE, fraction * brand.GLOW[LIGHT_MOTION_STATE + "_ms"])
    ground = brand.rgb(brand.LIGHT["surface"])
    colour = brand.rgb(brand.LIGHT[brand.status_fill(LIGHT_MOTION_STATE)])
    outer = brand.glow_radius(dot, frame["spread"]) * LIGHT_MOTION_SCALE
    stops = brand.glow_stops(dot)
    radius = dot * LIGHT_MOTION_SCALE
    out = bytearray(size * size * 3)
    for y in range(size):
        for x in range(size):
            red = green = blue = 0.0
            for sub_y in range(3):
                for sub_x in range(3):
                    px = x + (sub_x + 0.5) / 3.0 - half
                    py = y + (sub_y + 0.5) / 3.0 - half
                    away = (px * px + py * py) ** 0.5
                    parts = list(ground)
                    if frame["opacity"] > 0 and outer > 0 and away < outer:
                        alpha = frame["opacity"] * _falloff(stops, away / outer)
                        parts = [part + (one - part) * alpha for part, one in zip(parts, colour)]
                    if away < radius:
                        lit = 1.0 - frame["dim"]
                        parts = [part + (one - part) * lit for part, one in zip(parts, colour)]
                    red += parts[0]; green += parts[1]; blue += parts[2]
            at = (y * size + x) * 3
            out[at] = int(round(red / 9.0))
            out[at + 1] = int(round(green / 9.0))
            out[at + 2] = int(round(blue / 9.0))
    return size, bytes(out)


def _falloff(stops, fraction: float) -> float:
    """The glow's alpha factor at `fraction` of its outer radius, straight between brand's stops."""
    for (first, alpha), (second, next_alpha) in zip(stops, stops[1:]):
        if fraction <= second:
            if second == first:
                return alpha
            return alpha + (next_alpha - alpha) * (fraction - first) / (second - first)
    return 0.0


def render_light_motion(target: Path = LIGHT_MOTION_APNG) -> None:
    """One breath of the light, as an APNG: the pictures keep their colours, and only the light changes."""
    from codex_auto_resume import brand
    cycle = brand.GLOW[LIGHT_MOTION_STATE + "_ms"]
    steps = int(round(cycle / 1000.0 * LIGHT_MOTION_FPS))
    delay = int(round(cycle / steps))
    cells = [light_motion_cell(step / float(steps)) for step in range(steps)]
    size = cells[0][0]
    write_apng(target, size, size, [(delay, picture) for _size, picture in cells])


def light_drawing(package=None) -> str:
    """The digest of what draws the light (LIGHT_ROOTS, followed)."""
    package = Path(package) if package is not None else ROOT / "src" / "codex_auto_resume"
    return sha256("\n".join(sorted(reached_definitions(package, LIGHT_ROOTS))).encode("utf-8"))


def light_render_input(drawing: str | None = None) -> str:
    """The light GIF's manifest entry: what it pictures, and what draws it."""
    shown = {"state": LIGHT_MOTION_STATE, "scale": LIGHT_MOTION_SCALE, "pad": LIGHT_MOTION_PAD,
             "fps": LIGHT_MOTION_FPS, "theme": "light"}
    if drawing is None:
        drawing = light_drawing()
    return sha256((json.dumps(shown, sort_keys=True) + drawing).encode("utf-8"))


def icon_motion_stretch() -> tuple:
    """(start, end) in ms of watching's loop that the GIF shows.

    It begins two breaths before a sweep and ends on a whole number of watching's loops, so that column picks up
    where it left off; and it is a whole number of recovering's cycles, so that column does too - recovering sweeps
    every 2.88 s, which shares no short multiple with the 16 s loop, so the shortest stretch that closes for both
    is two loops. With v0.6.5's numbers: 3.2 s to 32 s, two breaths and a sweep, then three breaths and a sweep.
    Since v0.6.8 it is a whole number of a failure's sweeps as well, which are twice as quick as recovering's.
    """
    from codex_auto_resume import brand, tray
    slot, motion = brand.GLOW["monitoring_ms"], tray.ICON_MOTION
    loop = slot * (motion["breaths"] + motion["sweep_breaths"])
    start = slot * max(0, motion["breaths"] - 2)
    for loops in range(1, 12):
        end = loop * loops
        if end > start and all(_icon_sweep_closes(state, end - start, loop) for state in ("recovering", "failed")) \
                and all((end - start) % brand.GLOW[rhythm] == 0 for rhythm in tray.ICON_TRAVEL_BREATHS.values()):
            return start, end
    raise ValueError("the GIF would jump where it loops: no stretch is a whole number of recovering's and a "
                     "failure's sweeps")


def _icon_sweep_closes(state: str, length: int, loop: int) -> bool:
    """Whether a state that sweeps all the time is in the same phase `length` ms apart, so its column loops without
    a jump."""
    from codex_auto_resume import tray
    for at in range(0, loop, 97):
        if abs(tray.icon_turn(state, length + at) - tray.icon_turn(state, at)) > 1e-6:
            return False
    return True


def icon_timeline(state: str, start: float, end: float) -> list:
    """(ms from `start`, position, level) for each frame the icon's own timer shows in [start, end): stepped from the
    motion clock's zero, where the state is entered, by the interval each frame asks for (tray.icon_frame_ms). The
    frame on show at `start` comes first, at 0; a state that stops moving holds its last frame."""
    from codex_auto_resume import tray
    shown, at = [], 0.0
    while at < end:
        position, level = tray.icon_frame(state, at, at)
        if at <= start:
            shown = [(0.0, position, level)]
        else:
            shown.append((at - start, position, level))
        step = tray.icon_frame_ms(state, at, at)
        if step is None:
            break
        at += step
    return shown


def _icon_cell(frames, state: str, ground: str, position: int, level: int) -> bytes:
    """One state's picture on one ground, RGB: the icon's own frame - its head at `position` and `level` - laid over
    the ground with its straight alpha, in a cell ICON_MOTION_PAD wider each way."""
    from codex_auto_resume import brand, tray
    size, pad = ICON_MOTION_SIZE, ICON_MOTION_PAD
    cell = size + 2 * pad
    head = tray.icon_level_colour(tray.icon_head_colour(state), level)
    pixels = frames.compose(position, head)
    red, green, blue = brand.rgb(dict(ICON_MOTION_GROUNDS)[ground])
    out = bytearray(bytes((red, green, blue)) * (cell * cell))
    for y in range(size):
        for x in range(size):
            b, g, r, a = pixels[(y * size + x) * 4:(y * size + x) * 4 + 4]
            at = ((pad + y) * cell + pad + x) * 3
            for offset, (source, base) in enumerate(((r, red), (g, green), (b, blue))):
                out[at + offset] = (source * a + base * (255 - a) + 127) // 255
    return bytes(out)


def _median_cut(weights: dict, count: int) -> list:
    """At most `count` colours standing for `weights` (colour -> weight). The box whose longest side times its weight
    is largest is split at its weighted median along that side, until there are `count`; each box is then its
    weighted mean. A colour that outweighs its neighbours - a taskbar ground - ends in a box of its own, exact."""
    def side(box, channel):
        return max(colour[channel] for colour in box) - min(colour[channel] for colour in box)

    boxes = [sorted(weights)]
    while len(boxes) < count:
        best, score = None, 0
        for index, box in enumerate(boxes):
            if len(box) > 1:
                value = max(side(box, channel) for channel in range(3)) * sum(weights[colour] for colour in box)
                if value > score:
                    best, score = index, value
        if best is None:
            break
        box = boxes[best]
        channel = max(range(3), key=lambda each: (side(box, each), -each))
        box = sorted(box, key=lambda colour: (colour[channel], colour))
        total, running, cut = sum(weights[colour] for colour in box), 0, 1
        for cut in range(1, len(box)):
            running += weights[box[cut - 1]]
            if running * 2 >= total:
                break
        boxes[best:best + 1] = [box[:cut], box[cut:]]
    palette = []
    for box in boxes:
        total = sum(weights[colour] for colour in box)
        palette.append(tuple((sum(colour[channel] * weights[colour] for colour in box) + total // 2) // total
                             for channel in range(3)))
    return palette


def icon_motion_frames() -> dict:
    """The GIF, before it is encoded: its size, its palette and its pictures.

    `frames` is [(delay in hundredths of a second, palette indices, {state: (position, level)})], each picture held
    until the next frame of any state is due, on the hundredth of a second a GIF counts in, and `moments` the ms into
    the stretch each is the picture of. Frames of the states due less than ICON_MOTION_SHORTEST apart are one
    picture, of the later moment, which a browser then shows for as long as the GIF says. The pictures are the
    icon's own frames at 48 px (`_icon_cell`); a GIF holds 256 colours and these hold more - the badge's gradient
    and the ring's edges on two grounds - so they share at most 255 (`_median_cut`, weighted by how much of the GIF
    each colour covers), and the last index is kept for "as before"."""
    from codex_auto_resume import tray
    start, end = icon_motion_stretch()
    length = end - start
    for state, word in ICON_MOTION_LIGHTS:
        if tray.ICON_FOR_LIGHT[word] != state:
            raise ValueError("%s is not the icon's state for %s" % (state, word))
    timelines = [icon_timeline(state, start if state == "watching" else 0.0, end if state == "watching" else length)
                 for state, _ in ICON_MOTION_LIGHTS]
    total = int(round(length / 10.0))
    shortest = ICON_MOTION_SHORTEST
    ticks = []                                  # (hundredth, moment): a picture, and the last moment it stands for
    for at in sorted({at for timeline in timelines for at, _, _ in timeline}):
        hundredth = int(round(at / 10.0))
        if hundredth > total - shortest:
            break                               # too close to the GIF starting again, which is the end's moment
        if ticks and hundredth - ticks[-1][0] < shortest:
            ticks[-1] = (ticks[-1][0], at)      # too soon after the picture before: that picture shows it
        else:
            ticks.append((hundredth, at))
    shown = []
    for index, (hundredth, at) in enumerate(ticks):
        frame = {state: [each for each in timeline if each[0] <= at][-1][1:]
                 for (state, _), timeline in zip(ICON_MOTION_LIGHTS, timelines)}
        following = ticks[index + 1][0] if index + 1 < len(ticks) else total
        shown.append((following - hundredth, frame))
    frames = tray.IconFrames(ICON_MOTION_SIZE)
    cells, counted = {}, {}
    for _delay, frame in shown:
        for state, _ in ICON_MOTION_LIGHTS:
            for ground, _ in ICON_MOTION_GROUNDS:
                key = (state, ground) + tuple(frame[state])
                if key not in cells:
                    cells[key] = _icon_cell(frames, state, ground, *frame[state])
                counted[key] = counted.get(key, 0) + 1
    # The pictures keep their own colours: an APNG has no palette to fit them into, and the badge's gradient and
    # the ring's edges are what a quantised GIF used to spend its 255 colours on.
    cell = ICON_MOTION_SIZE + 2 * ICON_MOTION_PAD
    width, height = len(ICON_MOTION_LIGHTS) * cell, len(ICON_MOTION_GROUNDS) * cell
    out = []
    for delay, frame in shown:
        canvas = bytearray(width * height * 3)
        for column, (state, _) in enumerate(ICON_MOTION_LIGHTS):
            for row, (ground, _) in enumerate(ICON_MOTION_GROUNDS):
                picture = cells[(state, ground) + tuple(frame[state])]
                for y in range(cell):
                    at = ((row * cell + y) * width + column * cell) * 3
                    canvas[at:at + cell * 3] = picture[y * cell * 3:(y + 1) * cell * 3]
        out.append((delay * 10, bytes(canvas), frame))          # the GIF counted hundredths; an APNG counts ms
    return {"width": width, "height": height, "frames": out, "moments": [at for _, at in ticks]}


def _lzw(indices: bytes, minimum: int) -> bytes:
    """GIF's variable-length LZW of `indices`, codes packed least significant bit first."""
    clear, stop = 1 << minimum, (1 << minimum) + 1
    size, next_code, table = minimum + 1, stop + 1, {}
    out, bits, count = bytearray(), 0, 0

    def emit(code):
        nonlocal bits, count
        bits |= code << count
        count += size
        while count >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            count -= 8

    emit(clear)
    prefix = indices[0]
    for index in indices[1:]:
        key = (prefix << 8) | index
        code = table.get(key)
        if code is not None:
            prefix = code
            continue
        emit(prefix)
        if next_code < 4096:
            table[key] = next_code
            next_code += 1
            if next_code > (1 << size) and size < 12:
                size += 1
        else:
            emit(clear)
            size, next_code, table = minimum + 1, stop + 1, {}
        prefix = index
    emit(prefix)
    emit(stop)
    if count:
        out.append(bits & 0xFF)
    return bytes(out)


# Index 255 of the palette: "as the frame before", transparent over it.
GIF_SAME = 255
_EQUAL_TO_MASK = bytes([0xFF] + [0] * 255)            # a zero difference -> 0xFF, any other -> 0


def write_gif(path: Path, width: int, height: int, palette: list, frames: list) -> None:
    """An animated GIF that loops forever, from pictures already in `palette`'s indices (at most 255 colours).

    After the first picture only the rectangle that changed is written, and what did not change in it is GIF_SAME,
    transparent over the picture before. Nothing here depends on the machine: the same pictures make the same bytes.
    """
    if len(palette) > GIF_SAME:
        raise ValueError("%d colours: more than a GIF palette holds with one kept for transparency" % len(palette))
    table = b"".join(bytes(colour) for colour in palette) + bytes(3 * (256 - len(palette)))
    data = bytearray(b"GIF89a" + struct.pack("<HHBBB", width, height, 0xF7, 0, 0) + table)
    data += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"           # loop forever
    previous = None
    size = width * height
    for frame in frames:
        delay, canvas = frame[0], frame[1]
        if previous is None:
            left, top, right, bottom, written = 0, 0, width, height, canvas
        else:
            # Whole-picture arithmetic on big integers: which bytes differ, and the picture with the rest made SAME.
            difference = (int.from_bytes(canvas, "big") ^ int.from_bytes(previous, "big")).to_bytes(size, "big")
            same = int.from_bytes(difference.translate(_EQUAL_TO_MASK), "big")
            written = ((int.from_bytes(canvas, "big") & ~same) | same).to_bytes(size, "big")
            rows = [y for y in range(height) if difference[y * width:(y + 1) * width].strip(b"\x00")]
            if not rows:
                rows = [0]
            top, bottom = rows[0], rows[-1] + 1
            left, right = width, 0
            for y in rows:
                line = difference[y * width:(y + 1) * width]
                if line.strip(b"\x00"):
                    left = min(left, width - len(line.lstrip(b"\x00")))
                    right = max(right, len(line.rstrip(b"\x00")))
            if right <= left:
                left, right = 0, 1
        region = b"".join(written[y * width + left:y * width + right] for y in range(top, bottom))
        disposal = 0x05 if previous is not None else 0x04       # keep what is there; transparency after the first
        data += b"\x21\xF9\x04" + struct.pack("<BHB", disposal, delay, GIF_SAME) + b"\x00"
        data += b"\x2C" + struct.pack("<HHHHB", left, top, right - left, bottom - top, 0)
        packed = _lzw(region, 8)
        data += b"\x08" + b"".join(bytes((len(packed[at:at + 255]),)) + packed[at:at + 255]
                                   for at in range(0, len(packed), 255)) + b"\x00"
        previous = canvas
    data += b"\x3B"
    path.write_bytes(bytes(data))


def render_icon_motion(target: Path = ICON_MOTION_APNG) -> None:
    """The icon's motion as an APNG: the icon's own frames, at their own colours."""
    made = icon_motion_frames()
    write_apng(target, made["width"], made["height"], [(delay, picture) for delay, picture, _ in made["frames"]])


def _module_aliases(reader, index) -> dict:
    """Name -> module, for every module of the package `reader`'s module imports whole (`from . import brand`)."""
    aliases = {}
    for node in ast.walk(reader.tree):
        if isinstance(node, ast.ImportFrom):
            target = reader.target(node)
            if target is None:
                continue
            for alias in node.names:
                dotted = (target + "." + alias.name) if target else alias.name
                if dotted in index:
                    aliases[alias.asname or alias.name] = dotted
    return aliases


def reached_definitions(package, roots) -> list:
    """The entries of the definitions `roots` - (module, name) pairs - are, and of everything they use in turn: a
    name of their own module, a name they import, or `module.name` of a module of the package they import whole.
    Keyed as `code_digest` keys them, so a definition moved to another module, with the import that follows it,
    is the same entry."""
    package = Path(package)
    index = _module_index(package)
    read, aliases = {}, {}

    def module(dotted):
        if dotted not in read:
            read[dotted] = (_Module(dotted, index[dotted], index, package.name) if dotted in index else None)
            if read[dotted] is not None:
                aliases[dotted] = _module_aliases(read[dotted], index)
        return read[dotted]

    pending, asked, taken, entries = list(roots), set(), set(), []
    while pending:
        dotted, name = pending.pop()
        if (dotted, name) in asked:
            continue
        asked.add((dotted, name))
        reader = module(dotted)
        if reader is None:
            continue
        if name in reader.defines:
            for guards, node in reader.defines[name]:
                if (dotted, id(node)) in taken:
                    continue
                taken.add((dotted, id(node)))
                entries.append(_entry(guards, node))
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Name):
                        pending.append((dotted, inner.id))
                    elif (isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name)
                          and inner.value.id in aliases[dotted]):
                        pending.append((aliases[dotted][inner.value.id], inner.attr))
                    elif isinstance(inner, ast.ImportFrom):
                        pending.extend(reader.named(inner))
        elif name in reader.imports:
            pending.append(reader.imports[name])
        else:
            pending.extend((star, name) for star in reader.stars)
    return entries


def icon_drawing(package=None) -> str:
    """The digest of what draws the icon's frames and decides when each is shown (ICON_ROOTS, followed)."""
    package = Path(package) if package is not None else ROOT / "src" / "codex_auto_resume"
    return sha256("\n".join(sorted(reached_definitions(package, ICON_ROOTS))).encode("utf-8"))


def icon_render_input(drawing: str | None = None) -> str:
    """The GIF's manifest entry: what it pictures, and what draws it. `drawing` is `icon_drawing()` when known."""
    shown = {"states": [list(pair) for pair in ICON_MOTION_LIGHTS], "grounds": [list(pair) for pair in ICON_MOTION_GROUNDS],
             "size": ICON_MOTION_SIZE, "pad": ICON_MOTION_PAD, "stretch": list(icon_motion_stretch()),
             "shortest": ICON_MOTION_SHORTEST}
    if drawing is None:
        drawing = icon_drawing()
    return sha256((json.dumps(shown, sort_keys=True) + drawing).encode("utf-8"))


def render_light_only() -> Path:
    """Only the status light's GIF: render it and pin it, leaving every other entry of the manifest as it was.

        python build/make_screenshots.py --light
    """
    render_light_motion(LIGHT_MOTION_APNG)
    print("  %s  %s" % (LIGHT_MOTION_APNG.relative_to(ROOT), dimensions(LIGHT_MOTION_APNG)))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["inputs"]["<light motion>"] = light_render_input()
    manifest["images"][str(LIGHT_MOTION_APNG.relative_to(ROOT)).replace("\\", "/")] = {
        "sha256": sha256(LIGHT_MOTION_APNG.read_bytes()), "size": dimensions(LIGHT_MOTION_APNG)}
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("manifest       : %s (the light's entries only)" % MANIFEST.relative_to(ROOT))
    return LIGHT_MOTION_APNG


def render_icon_only() -> Path:
    """Only the icon's GIF: render it and pin it, leaving every other entry of the manifest as it was.

        python build/make_screenshots.py --icon
    """
    render_icon_motion(ICON_MOTION_APNG)
    print("  %s  %s" % (ICON_MOTION_APNG.relative_to(ROOT), dimensions(ICON_MOTION_APNG)))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["inputs"]["<icon motion>"] = icon_render_input()
    manifest["images"][str(ICON_MOTION_APNG.relative_to(ROOT)).replace("\\", "/")] = {
        "sha256": sha256(ICON_MOTION_APNG.read_bytes()), "size": dimensions(ICON_MOTION_APNG)}
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifest       : %s (the icon's entries only)" % MANIFEST.relative_to(ROOT))
    return ICON_MOTION_APNG


def scratch_installation(workspace: Path) -> Path:
    """An installation made out of the working tree, so the picture is of this code."""
    import make_release
    import zipfile

    home = workspace / "home"
    (home / "app").mkdir(parents=True)
    shutil.copytree(ROOT / "src", home / "app" / "src")
    # Bundling the frozen registry data, so the window's own bridge answers as the envelope does.
    shutil.copyfile(frozen_registry().FROZEN,
                    home / "app" / "src" / "codex_auto_resume" / "data" / "codex_compat.json")
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

    # The defaults in the pinned theme (see `sample_settings`); recovery itself is switched on
    # through the engine in `render_window`, so the window shows the state it is in when it is
    # doing its job.
    write_settings(home)
    return home


# Holds the watcher's mutex and writes the watcher's heartbeat once a second - the two
# things the window reads to say a watcher is running and checking - and nothing else. No
# engine, no source, no Codex. The heartbeat carries the word the watcher's compatibility
# check gave for the scratch installation (`seed_compatibility`), as a real watcher's does.
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
                            started_at=started - 5400, ok=True, engine_state=sys.argv[4],
                            code_version=config.version())
        time.sleep(1)
"""

# Which page of the window each picture is of, as the window's own command line names it.
# Every page the window has. The README shows three of them; the other three are here
# because a page with no artifact is a page nothing in this repository shows ever
# rendering, which is what docs/FEATURE_MATRIX.md said about History, Statistics and
# Diagnostics for as long as they existed.
WINDOW_PAGES = ("overview", "pending", "history", "statistics", "diagnostics", "settings")


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
        codex, local = workspace / "codex", workspace / "LocalAppData"
        now = time.time()
        seed_window_state(home, codex, now)
        word = seed_compatibility(home, codex, local, now)
        # The window reads conversation names from Codex's own state, found through
        # CODEX_HOME - pointed here at the synthetic one, so a capture can never show,
        # or even open, the user's. It finds the Codex engine the compatibility report is
        # bound to under LOCALAPPDATA, pointed at the scratch installation's own for the
        # same reason; and the product's own overrides are unset, as for the envelope.
        environment = dict(os.environ, CODEX_HOME=str(codex), LOCALAPPDATA=str(local.resolve()))
        for override in (config.ENV_HOME, config.ENV_CODEX_EXE):
            environment.pop(override, None)
        holder = subprocess.Popen(
            [str(home / "runtime" / "python.exe"), "-c", HOLD_MUTEX,
             str(home / "app" / "src"), str(home), str(40 + 20 * len(targets)), word],
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
                     "-Out", str(target), "-Wait", "15", "-Arguments",
                     # The Settings page opens on the section with the most to show.
                     "--page=settings --section=continuation" if page == "settings"
                     else "--page=" + page],
                    check=True, capture_output=True, timeout=300, env=environment)
        finally:
            holder.kill()
    return {page: dimensions(target) for page, target in targets.items()}


# ------------------------------------------------------------ what the window is shown
# The window's Python half, as the window receives it (see WINDOW_INPUTS).
#
# `window_envelopes` builds the installation `render_window` builds - the stored settings in
# the pinned theme, the Dashboard's records written by the product's own store, the
# synthetic Codex home the names come from, the compatibility report the watcher's evaluator
# writes for it, the watcher's mutex held and its heartbeat written, recovery switched on
# through the bridge - and asks the bridge, through the same `serve` loop the window keeps
# open, what the window asks to draw the photographed pages.
# The canonical text of the answers is the envelope; its hash is the manifest entry.
#
# It has to come out the same on every machine and every run, and the answers carry four
# things that would not. Each is pinned or rewritten, never dropped, so the envelope still
# moves when the thing itself does:
#
# * the clock. The records are seeded at ENVELOPE_NOW and the bridge answers with `time.time`
#   reading ENVELOPE_NOW, so every countdown, age, "checking" and the week the Statistics
#   figures cover come out the same; the compatibility report is checked forty seconds
#   before it, and the engine file it is bound to dated six days before. A clock time
#   formatted for a person is formatted in UTC rather than the machine's zone;
# * paths. The scratch installation, the checkout, the temporary directory and the user's
#   profile are rewritten to `<scratch>`, `<checkout>`, `<temp>` and `<profile>` wherever
#   they appear in an answer, in every spelling (resolved or not, either slash, any case);
# * the process id. The capture's mutex holder writes its own into the heartbeat; the
#   envelope writes ENVELOPE_PID;
# * the machine. The language is the locale being rendered, set the way the generator sets
#   it for every surface; the Run key and the notification registration read as they read
#   for any scratch installation, "nothing registered", from a stand-in that refuses every
#   write; CODEX_HOME points at the synthetic home and LOCALAPPDATA at the scratch
#   installation's own, where the stand-in Codex engine is, so the engine the report
#   describes is found - and no other; the product's own overrides (CODEX_AUTO_RESUME_HOME,
#   CODEX_AUTO_RESUME_CODEX_EXE) are unset. The report itself reaches the window as the
#   reader's view, which carries no path: the digest of the engine's path and the engine's
#   size and time bind the report on disk and are never part of an answer.
#
# Nothing here starts a watcher, a window or a process, writes the registry, or reads the
# user's own Codex home or installation.
ENVELOPE_NOW = POPUP_NOW
ENVELOPE_PID = 4242
# The reads that paint the photographed pages, as the window names them: its words
# (`SettingsApp.AskStrings`), the Settings page's schema and values, the status line, the
# Dashboard's one-round-trip snapshot (Overview, Pending, History), the Statistics page at
# the period it opens on, the Diagnostics page's compatibility report, and the Settings
# page's Preview - which is built from the first two answers, see `preview_request`.
WINDOW_READS = (("strings", None), ("describe", None), ("settings", None), ("status", None),
                ("dashboard", None), ("statistics", {"days": 7}), ("compatibility", None))


def preview_request(schema: list, stored: dict):
    """The Preview the Settings page asks for when it opens, as `SettingsApp.RunPreview` builds it.

    For the first reason in the schema's order (`reasonOrder`), with the form's values: every
    field as stored, a blank message box as "not set", and Standard when no style is chosen.
    """
    order = [field.get("category") for field in schema
             if str(field.get("name", "")).startswith("custom_message_") and field.get("category")]
    if not order:
        return None

    def text(value):
        plain = (value or "").replace("\r\n", "\n")
        return plain if plain.strip() else None

    changes = {"interface_language": stored.get("interface_language"),
               "continuation_language": stored.get("continuation_language"),
               "continuation_style": stored.get("continuation_style") or "standard",
               "custom_message_mode": stored.get("custom_message_mode"),
               "custom_message": text(stored.get("custom_message"))}
    for category in order:
        changes["custom_message_" + category] = text(stored.get("custom_message_" + category))
    return ("preview-continuation", {"category": order[0], "changes": changes})


class RegistryWriteRefused(BaseException):
    """Raised by the envelope's stand-in registry on any write.

    A `BaseException`, not an `Exception`, on purpose: the bridge turns every `Exception` into
    a polite refusal on the wire, and a refusal would only have changed a hash. This stops
    the generator and the test instead.
    """


class _NoRegistration:
    """`winreg` as a scratch installation finds it: nothing registered, and nothing writable.

    Every read answers "not found", which is what the real registry answers for a home that
    was never installed - on every machine, whatever the developer's own installation has
    registered. Every write raises: the envelope must never be able to touch the Run key,
    the protocol handler or the notification identity, whatever a later bridge command does.
    """
    HKEY_CURRENT_USER = object()
    KEY_READ = KEY_SET_VALUE = KEY_WRITE = KEY_ALL_ACCESS = 0
    REG_SZ = 1

    @staticmethod
    def OpenKey(*_args, **_kwargs):                      # noqa: N802 - winreg's own name
        raise FileNotFoundError("not registered")

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def refused(*_args, **_kwargs):
            raise RegistryWriteRefused("the screenshot envelope never writes the registry (%s)" % name)
        return refused


@contextmanager
def _registry_stand_in():
    """`import winreg`, wherever in the package it happens, finds `_NoRegistration` meanwhile.

    Only that one entry of `sys.modules` is replaced and put back: restoring a whole copy of
    `sys.modules` would also drop every module first imported in between, and the next import
    of one of them would make a second copy of it.
    """
    missing = object()
    saved = sys.modules.get("winreg", missing)
    sys.modules["winreg"] = _NoRegistration()
    try:
        yield
    finally:
        if saved is missing:
            sys.modules.pop("winreg", None)
        else:
            sys.modules["winreg"] = saved


@contextmanager
def _watcher_mutex_held(paths):
    """Hold the watcher's single-instance mutex for `paths`, as the capture's holder does.

    From another thread: a Windows mutex is re-entrant for the thread that owns it, so a
    probe from the owning thread would be granted it and report no watcher. The name is
    derived from the scratch state directory, so this can never be the user's own watcher's.
    Off Windows there is no mutex to hold and the probe is answered as the held one answers.
    """
    from unittest.mock import patch

    from codex_auto_resume import control
    if os.name != "nt":
        with patch.object(control.Control, "watcher_running", return_value=True):
            yield
        return
    from codex_auto_resume.windows import Mutex
    held, done, failure = threading.Event(), threading.Event(), []

    def hold():
        try:
            with Mutex(str(paths.state_dir), timeout=0.0):
                held.set()
                done.wait(120)
        except Exception as exc:                        # noqa: BLE001 - re-raised below
            failure.append(exc)
            held.set()

    holder = threading.Thread(target=hold, name="screenshot-mutex", daemon=True)
    holder.start()
    held.wait(30)
    try:
        if failure or not held.is_set():
            raise RuntimeError("could not hold the watcher mutex for the envelope: %r" % failure)
        yield
    finally:
        done.set()
        holder.join(30)


def _spellings(*pairs) -> list:
    """(pattern, placeholder) for every way each directory can be written, longest first."""
    found = {}
    for placeholder, directory in pairs:
        if not directory:
            continue
        path = Path(directory)
        variants = {str(path), path.as_posix()}
        try:
            resolved = path.resolve()
            variants.update((str(resolved), resolved.as_posix()))
        except OSError:
            pass
        for variant in variants:
            if len(variant) > 3:                         # never a bare drive or root
                found.setdefault(variant, placeholder)
    return [(re.compile(re.escape(text), re.IGNORECASE), placeholder)
            for text, placeholder in sorted(found.items(), key=lambda item: -len(item[0]))]


def _canonical(value, spellings):
    if isinstance(value, str):
        for pattern, placeholder in spellings:
            value = pattern.sub(lambda _match, text=placeholder: text, value)
        return value
    if isinstance(value, dict):
        return {key: _canonical(item, spellings) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item, spellings) for item in value]
    return value


def window_envelopes(locales) -> dict:
    """Locale -> the canonical text of what the bridge tells the window, one line per read.

    Each line is the request and its reply as the reply crossed the wire: keys in the order
    the bridge wrote them, because the window lists some objects in that order (the
    Statistics page's kinds of interruption), with only the pinned values above rewritten.
    """
    from unittest.mock import patch

    from codex_auto_resume import control, controlcli

    envelopes = {}
    with tempfile.TemporaryDirectory() as name, ExitStack() as stack:
        stack.enter_context(frozen_registry().frozen())
        workspace = Path(name)
        home, codex, local = workspace / "home", workspace / "codex", workspace / "LocalAppData"
        # The part of `scratch_installation` the bridge reads: the settings it stores. The
        # interpreter and the compiled window are not read by any answer.
        write_settings(home)
        seed_window_state(home, codex, ENVELOPE_NOW)
        word = seed_compatibility(home, codex, local, ENVELOPE_NOW)
        paths = config.Paths(home)
        # Put back whole when the envelope is done, including the two removed here.
        stack.enter_context(patch.dict(os.environ, {"CODEX_HOME": str(codex),
                                                    "LOCALAPPDATA": str(local.resolve())}))
        for override in (config.ENV_HOME, config.ENV_CODEX_EXE):
            os.environ.pop(override, None)
        stack.enter_context(patch.object(time, "time", return_value=ENVELOPE_NOW))
        stack.enter_context(patch.object(
            time, "localtime", side_effect=lambda seconds=None: time.gmtime(
                ENVELOPE_NOW if seconds is None else seconds)))
        stack.enter_context(_registry_stand_in())
        stack.enter_context(_watcher_mutex_held(paths))
        write_heartbeat(paths, ENVELOPE_NOW, word)
        surface = control.Control(paths)

        def ask(command, argument=None):
            sent = json.dumps({"id": 1, "command": command, "argument": argument})
            answer = io.StringIO()
            controlcli.serve(surface, io.StringIO(sent + "\n"), answer)
            return json.loads(answer.getvalue())["reply"]

        # Switched on through the bridge before anything is read, as `render_window` does.
        switched = ask("enabled", {"enabled": True})
        if not switched.get("ok"):
            raise RuntimeError("the scratch installation could not be switched on: %r" % switched)
        spellings = _spellings(("<scratch>", workspace), ("<checkout>", ROOT),
                               ("<temp>", tempfile.gettempdir()), ("<profile>", Path.home()))
        previous = l10n.preference()
        try:
            for locale in locales:
                os.environ[l10n.ENV_LANG] = locale
                lines, replies = [], {}
                for command, argument in WINDOW_READS:
                    replies[command] = ask(command, argument)
                    lines.append((command, argument, replies[command]))
                preview = preview_request((replies["describe"] or {}).get("schema") or [],
                                          (replies["settings"] or {}).get("settings") or {})
                if preview is not None:
                    lines.append(preview + (ask(*preview),))
                # The photographed pages show a product that works. A read that failed here
                # would be photographed failing too, so it stops the generator instead.
                failed = [command for command, _argument, reply in lines
                          if not reply.get("ok") or any(key.endswith("_error") for key in reply)]
                if failed:
                    raise RuntimeError("the bridge could not answer %s for the envelope" % failed)
                envelopes[locale] = "\n".join(
                    json.dumps({"command": command, "argument": argument,
                                "reply": _canonical(reply, spellings)},
                               ensure_ascii=False, separators=(",", ":"))
                    for command, argument, reply in lines) + "\n"
        finally:
            l10n.set_preference(previous)
    return envelopes


def bridge_envelope(locale: str) -> str:
    """One locale's envelope, for reading. From the repository root,

        python -X utf8 -c "import sys; sys.path.insert(0, 'build'); import make_screenshots as m; print(m.bridge_envelope('en'))"

    prints exactly what a changed `<bridge envelope:en>` entry was taken over."""
    return window_envelopes((locale,))[locale]


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

    The window's Python half, the popup and the notification card are keyed the same way since
    v0.6.5: the window by what the bridge answers it (`<bridge envelope:*>`, see
    `window_envelopes`), the popup and the card by the view each draws and a digest of the
    definitions that draw it (`popup_render_input`, `card_render_input`), and the icon's GIF
    by what it pictures and the definitions its frames are made from (`icon_render_input`).
    Only the compiled window has no such handle - running it is the only way to see its
    output - so its files are listed in WINDOW_INPUTS, and a comment in `SettingsApp.cs`
    will still fire this check unnecessarily. That is a real cost and it is the smaller one:
    the alternative is not noticing that the picture is wrong.
    """
    inputs = {name: input_digest(ROOT / name) for name in WINDOW_INPUTS}
    # One entry per locale, each rendered with that locale pinned.
    #
    # A single unpinned entry made the digest depend on the machine: the catalog is
    # resolved from the environment, so a Korean developer recorded the Korean render and
    # an English CI runner recomputed the English one and called the screenshots stale.
    # It is the same failure as hashing raw bytes for a file whose line endings the
    # checkout decides - the input has to be pinned, not observed.
    envelopes = window_envelopes(LOCALES + EXTRA_LOCALES)
    drawing = popup_drawing()
    card = card_drawing()
    for locale in LOCALES + EXTRA_LOCALES:
        inputs["<bridge envelope:%s>" % locale] = sha256(envelopes[locale].encode("utf-8"))
        previous = os.environ.get(l10n.ENV_LANG)
        os.environ[l10n.ENV_LANG] = locale
        try:
            inputs["<panel render:%s>" % locale] = sha256(
                panel_html(theme=THEME).encode("utf-8"))
            inputs["<popup render:%s>" % locale] = popup_render_input(locale, drawing)
            inputs["<card render:%s>" % locale] = card_render_input(locale, card)
        finally:
            if previous is None:
                os.environ.pop(l10n.ENV_LANG, None)
            else:
                os.environ[l10n.ENV_LANG] = previous
    inputs["<icon motion>"] = icon_render_input()
    inputs["<light motion>"] = light_render_input()
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
# The runtime still follows the user's Theme setting, and with it Windows and Codex; only the
# pictures are pinned, and only so that a build on a machine in dark mode produces the same
# bytes as a build on a machine in light mode. Each surface is told in its own way: the panel
# is served with the theme pinned, the popup's renderer is set to it, and the window's scratch
# installation stores it as the Theme setting (`sample_settings`). The notification card is the
# one surface pictured in both (CARD_THEMES), each picture named for its theme and drawn in it:
# it floats over whatever desktop the reader has, so both are what a reader may see.
THEME = "light"
LOCALES = ("en", "ko")
# Three more languages, documentation only: the Dashboard's main pages, the panel and the
# popup, so the translations are seen rendered at all. They are not copied into assets/,
# which ships in the release, and no README embeds them.
EXTRA_LOCALES = ("ja", "zh-CN", "de")
EXTRA_PAGES = ("overview", "pending", "settings")


# Canonical asset name and documentation copy name, per picture. The settings page keeps
# the names it has always had, so links to it from outside the repository keep working.
WINDOW_NAMES_BY_PAGE = {
    "overview": ("screenshot-dashboard", "dashboard-overview"),
    "pending": ("screenshot-pending", "dashboard-pending"),
    "history": ("screenshot-history", "dashboard-history"),
    "statistics": ("screenshot-statistics", "dashboard-statistics"),
    "diagnostics": ("screenshot-diagnostics", "dashboard-diagnostics"),
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
    if list(sys.argv[1:] if argv is None else argv) == ["--cards"]:
        render_cards()
        return 0
    if list(sys.argv[1:] if argv is None else argv) == ["--icon"]:
        render_icon_only()
        return 0
    if list(sys.argv[1:] if argv is None else argv) == ["--light"]:
        render_light_only()
        return 0
    if list(sys.argv[1:] if argv is None else argv) == ["--breathe"]:
        breathe_pictures()
        return 0

    print("version        : %s" % config.version())
    print("theme          : %s" % THEME)
    copies = {}
    for locale in LOCALES:
        print("locale         : %s" % locale)
        # The engine resolves the language from the environment, so the environment is
        # what the generator sets. Nothing here passes a language into a renderer: the
        # screenshots go through exactly the path a user's machine goes through.
        os.environ[l10n.ENV_LANG] = locale
        pairs = paths_for(locale)
        panel = next(iter(pairs))
        render_panel(panel)
        print("  %s  %s" % (panel.relative_to(ROOT), dimensions(panel)))
        targets = window_targets(locale)
        for page, size in render_window(targets).items():
            print("  %s  %s" % (targets[page].relative_to(ROOT), size))
        copies.update(pairs)
    extras = []
    for locale in LOCALES + EXTRA_LOCALES:
        os.environ[l10n.ENV_LANG] = locale
        tag = "" if locale == "en" else "-" + locale
        popup = DOCS / ("tray-popup%s.png" % tag)
        render_popup(popup, locale)
        extras.append(popup)
        print("  %s  %s" % (popup.relative_to(ROOT), dimensions(popup)))
        for theme, (asset, copy) in card_paths(locale).items():
            render_card(asset or copy, locale, theme)
            if asset is not None:
                copies[asset] = copy
            else:
                extras.append(copy)
            print("  %s  %s" % ((asset or copy).relative_to(ROOT), dimensions(asset or copy)))
        if locale in EXTRA_LOCALES:
            panel = DOCS / ("settings-panel%s.png" % tag)
            render_panel(panel)
            extras.append(panel)
            targets = {page: DOCS / ("%s%s.png" % (WINDOW_NAMES_BY_PAGE[page][1], tag))
                       for page in EXTRA_PAGES}
            for page, size in render_window(targets).items():
                print("  %s  %s" % (targets[page].relative_to(ROOT), size))
            extras.extend(targets.values())
    os.environ.pop(l10n.ENV_LANG, None)
    render_icon_motion(ICON_MOTION_APNG)
    extras.append(ICON_MOTION_APNG)
    print("  %s  %s" % (ICON_MOTION_APNG.relative_to(ROOT), dimensions(ICON_MOTION_APNG)))

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
        "card_themes": list(CARD_THEMES),
        "locales": list(LOCALES),
        "documentation_locales": list(EXTRA_LOCALES),
        "system_dpi": system_dpi(),
        "inputs": render_inputs(),
        "images": {str(path.relative_to(ROOT)).replace("\\", "/"):
                   {"sha256": sha256(path.read_bytes()), "size": dimensions(path)}
                   for path in list(copies) + list(copies.values()) + extras},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifest       : %s" % MANIFEST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
