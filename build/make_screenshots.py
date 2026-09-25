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
    python build/make_screenshots.py --breathe   # then: every captured light that moves, moving
    python build/make_screenshots.py --cards     # only the notification card's pictures
    python build/make_screenshots.py --icon      # only the icon's motion, as a GIF
    python build/make_screenshots.py --light     # only the status light's own picture
    python build/make_screenshots.py --audit OUT # light and dark sheets of all four surfaces, into OUT only

Run it from a checkout, on Windows, with the settings window built, from PowerShell: launched
from a POSIX shell, headless Edge exits at once and prints nothing. A whole regeneration is the
first two lines, in that order. It writes the canonical assets and copies them to `docs/images/`.
The popup and the notification card are drawn off-screen by their own renderers, moving, and need
neither the window nor Edge; the icon's motion is drawn from the icon's own frames and needs nothing
of Windows at all. The window and the panel are captured still, and `--breathe` then draws their
lights moving over the capture (see "pictures that breathe").

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
from fractions import Fraction
import hashlib
import html as html_text
import io
import json
import math
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
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "build"))

from codex_auto_resume import brand, config, l10n            # noqa: E402
from codex_auto_resume.mcp import panel as mcpui
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
    # Its C#, as one input: the compile list is `gui/window.sources` since v0.6.10-alpha,
    # and naming the four files here would be the eighteenth copy of that list - one that
    # goes quietly out of date the day the window is split into more files. `window_digest`
    # below hashes every compiled source in compile order, so a file added to the window is
    # an input without anybody adding it here.
    "<window sources>",
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
def sample_settings(theme: str | None = None, design: str | None = None) -> dict:
    """The stored settings every picture is drawn from: the defaults, in the pinned THEME and design.

    Stored, because storing is the only way the window can be given a theme. It resolves the stored
    Theme when it starts, and the default, Use system setting, follows Windows' app mode - so a
    scratch installation holding the plain defaults was photographed dark on a machine in dark mode,
    beside light panel and popup pictures and under a manifest that said light. `--theme` is no way
    round it either: the window's first settings read reopens it in the stored theme.

    `theme` is only ever another theme for the audit sheets (`--audit`), which draw both; every
    published picture is drawn in THEME. `design` is the Design (v0.6.10), stored the same way and for
    the same reason - the window reads it in the same parse as the theme - and it is only ever another
    design for the pictures of the designs themselves (DESIGNS_PICTURED); every other picture is drawn
    in the default, Soft.
    """
    return dict(policy.defaults(), theme=theme or THEME, design=design or brand.DEFAULT_DESIGN)


def write_settings(home: Path, theme: str | None = None, design: str | None = None) -> Path:
    """Write `sample_settings()` where the window, the bridge and the watcher all read them."""
    state = home / "config"
    state.mkdir(parents=True, exist_ok=True)
    target = state / "settings.json"
    target.write_text(json.dumps(sample_settings(theme, design), indent=2), encoding="utf-8")
    return target


# The one set of records every surface is pictured showing, and the one set of offsets it is read at
# (v0.6.10).
#
# Until then there were three. The panel registered two rows of its own in a store of its own, at
# times near 1970, so both read "due now" and its network failure said it was waiting for a usage
# reset; the popup was handed three hand-written rows, one a server error nobody else showed; and the
# window, seeded by `seed_window_state`, said "2 recoveries pending". Three pictures of one product,
# three datasets and three moments, cannot be laid side by side - which is what an audit of the
# product's look does, and what a reader of the README does without being asked to.
#
# Now the window's own seed is written once, at POPUP_NOW, into a scratch store and read back the
# way each surface reads it: the rows through `Control.list_pending` with the names the synthetic
# Codex home gives them (the popup's own read, `ui/popup/model.perform`, and the window's), and the
# status through the MCP server (the panel's). The panel's page is told POPUP_NOW (`pinned_clock`)
# and the card's reset is the usage limit's, so the panel, the popup and the card are one moment.
# The window is not: the bridge behind it runs with the real clock, so `render_window` writes the
# same seed, with the same offsets (USAGE_RESET_IN, RETRY_IN), at the moment it is photographed
# and tells the window that moment (CODEX_AR_STILL_NOW). So a countdown, a chip and a count read the
# same on all four, and only times relative to the moment are comparable across them: a wall-clock
# time the window prints, such as History's, is the day of the run's, not POPUP_NOW's.
_FIXTURE = {}


def fixture() -> dict:
    """{"pending": rows, "status": the MCP server's status}, read from the one seed at POPUP_NOW.

    A fresh copy each time, of one reading per process: every locale's panel and popup read it,
    and the answer is codes, numbers and the synthetic names, in no language.
    """
    key = (POPUP_NOW, WINDOW_THREADS, WINDOW_NAMES, USAGE_RESET_IN, RETRY_IN)
    if key not in _FIXTURE:
        _FIXTURE[key] = json.dumps(_read_fixture())
    return json.loads(_FIXTURE[key])


def _read_fixture() -> dict:
    from unittest.mock import patch

    from codex_auto_resume import control as control_module
    from codex_auto_resume import mcpserver
    from codex_auto_resume.codex import LocalSource

    with tempfile.TemporaryDirectory() as name:
        workspace = Path(name)
        home, codex, local = workspace / "home", workspace / "codex", workspace / "LocalAppData"
        paths = config.Paths(home)
        # The clock pinned before anything is written, as `pinned_installation` pins it: a row the
        # store is not given a time for is stamped with `time.time`.
        with patch.object(time, "time", return_value=POPUP_NOW):
            seed_window_state(home, codex, POPUP_NOW)
            # What the window's Diagnostics page and the popup are shown too: the report the
            # watcher's evaluator writes for the synthetic Codex home, and the heartbeat carrying
            # the word it gave - so the panel's compatibility card is the same card.
            word = seed_compatibility(home, codex, local, POPUP_NOW)
            write_heartbeat(paths, POPUP_NOW, word)
        surface = control_module.Control(paths)
        # A watcher is running in the picture, so the rows are described as they are when one is -
        # without "watcher not running" beside a headline that says it is. Read with the clock
        # pinned, the stand-in engine where readers look for it, and the registry read as a scratch
        # installation's, never written.
        with patch.object(control_module.Control, "watcher_running", return_value=True), \
                patch.object(time, "time", return_value=POPUP_NOW), \
                patch.dict(os.environ, {"LOCALAPPDATA": str(local.resolve())}), \
                _registry_stand_in():
            os.environ.pop(config.ENV_CODEX_EXE, None)
            pending = surface.list_pending(source=LocalSource(codex))
            status = mcpserver.Server(surface, io.StringIO(), io.StringIO())._status()
    return {"pending": pending, "status": status}


def sample_panel_data(design: str | None = None) -> dict:
    """What the panel is showing in the picture, produced by the product itself, its settings in `design`.

    Not a hand-written dictionary: the fixture's rows and the MCP server's own status, read back
    from the store `seed_window_state` writes (see `fixture`), so the sample has exactly the shape
    the panel is given at runtime. The first attempt at this file did hand-write it, got two field
    names wrong, and rendered a table of "undefined" - which is the same class of drift the whole
    file exists to end, in the file that ends it.

    The values are synthetic throughout, and from the project's own fixture family: this
    image is published on a plugin card, so a real conversation id would be published
    with it. `tests/test_repo_hygiene.py` enforces the family.

    The version is not written here either. It arrives through `get_status()`, from the
    manifest, like every other current-facing surface.
    """
    from codex_auto_resume import l10n, reasons

    shown = fixture()
    # The names are the synthetic Codex home's, read as the window and the popup read them. The
    # panel is not given them at runtime - the MCP server lists no names - and falls back to the
    # first segment of the thread id, which reads as debug output rather than as work waiting; the
    # picture shows what a person recognises the work by.
    waiting = shown["pending"]
    status = shown["status"]
    # The facts a picture of a working product should show, which a scratch store cannot know: it
    # is on, and something is watching.
    status["enabled"] = True
    status["watcher_running"] = True
    status["startup_enabled"] = True
    status["home"] = r"%USERPROFILE%\.codex-auto-resume"
    # The rest of what `open_settings` returns, so the language choices and the Preview are
    # drawn the way Codex draws them. The system language is pinned to the page's own.
    return {"status": status, "schema": policy.describe(),
            "settings": sample_settings(design=design), "pending": waiting,
            "reasons": list(reasons.RECOVERABLE), "endonyms": dict(l10n.ENDONYMS),
            "system_language": l10n.current()}


# The Dashboard's sample: four conversations, from the same fixture family as the panel's.
WINDOW_THREADS = ("11111111-1111-7111-8111-111111111111",
                  "22222222-2222-7222-8222-222222222222",
                  "33333333-3333-7333-8333-333333333333",
                  "44444444-4444-7444-8444-444444444444")
WINDOW_NAMES = ("example-project", "example-service", "example-docs", "example-app")
# How far off the two waiting recoveries are at the moment every surface is pictured at: the usage
# limit resets in 42:20 and the network failure is retried in 1:35. The window's rows, the popup's,
# the panel's and the card's reset time are all this, because they are all read from one seed.
USAGE_RESET_IN = 42 * 60 + 20
RETRY_IN = 95


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
                                 reset_at=now + USAGE_RESET_IN), now - 25 * 60)
        store.register(detection(8, WINDOW_THREADS[1], "network_transient", now - 50),
                       now - 50, state="waiting_backoff", next_retry_at=now + RETRY_IN)
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
        # Where Backend looks `S` up: codex/transport.py since v0.6.10-alpha. On the windows
        # front the patch would reach nothing, and the pictures would run the real `codex`.
        from codex_auto_resume.codex import transport
        stack.enter_context(patch.object(transport, "S", _CodexProcesses(exe)))
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


PANEL_PROBE = "CAR-PANEL-PROBE:"


def panel_probe(page: Path, workspace: str) -> dict:
    """How tall the rendered panel is, and where its lights are, asked of the renderer.

    A constant here is a constant that goes stale the first time a setting is added, and
    the way it goes stale is that the bottom of the picture disappears. Chromium prints
    the DOM after layout, so the page can be asked instead: render it once at the target
    width, read the height off the root element, and shoot at that.

    Since v0.6.10 the page is asked for its status lights too - every `.halo`, the state's at the top
    and the Automatic recovery tile's mini one (F15) - each as its centre and radius in CSS px, its
    state (the class the page gave it) and the ground it dims toward, resolved by the page itself: a
    probe element coloured `var(--halo-ground)` where the light stands. So the lights `--breathe`
    draws are the page's, wherever the page puts them, rather than whichever disc of a colour a search
    of the picture found first.

    And at the width the picture is taken at. Edge prints the DOM of a window whose page is 30 px narrower
    than the window it is told to be, where it screenshots one exactly as wide: measured at 870 CSS px, the
    page's centred column stood 15 px left of where the picture has it, and every height this measured was a
    narrower page's. So the page says how wide it was laid out, and the probe is taken again in a window
    widened by what was missing until it is PANEL_CSS_WIDTH.

    Returns {"height": CSS px, with a margin, "lights": [{"x", "y", "radius", "state", "ground"}]}.
    """
    window = PANEL_CSS_WIDTH
    for _attempt in range(3):
        found = _panel_probe_once(page, workspace, window)
        if found["width"] == PANEL_CSS_WIDTH:
            break
        window += PANEL_CSS_WIDTH - found["width"]
    else:
        raise SystemExit("the panel could not be laid out %d CSS px wide to be measured" % PANEL_CSS_WIDTH)
    lights = []
    for light in found["lights"]:
        states = [name for name in light["classes"].split() if name not in ("halo", "mini")]
        lights.append({"x": light["x"], "y": light["y"], "radius": light["radius"],
                       "state": states[-1] if states else "idle", "ground": css_colour(light["ground"])})
    # The page's own padding is already in the measurement; a little more keeps
    # the bottom card from sitting flush against the edge of the image.
    return {"height": int(found["height"]) + 16, "lights": lights}


def _panel_probe_once(page: Path, workspace: str, window: int) -> dict:
    """One probe of `page` in a window `window` px wide: what the page said, with the width it was laid out at."""
    probe = Path(workspace) / "probe.html"
    probe.write_text(
        page.read_text(encoding="utf-8").replace(
            "</body>",
            "<script>(function(){var lights=[];"
            "Array.prototype.forEach.call(document.querySelectorAll('.halo'),function(node){"
            "var box=node.getBoundingClientRect(),swatch=document.createElement('span');"
            "swatch.style.cssText='position:absolute;width:0;height:0;background-color:var(--halo-ground)';"
            "node.parentNode.appendChild(swatch);"
            "var ground=getComputedStyle(swatch).backgroundColor;swatch.remove();"
            "lights.push({x:box.left+box.width/2+window.scrollX,y:box.top+box.height/2+window.scrollY,"
            "radius:box.width/2,classes:String(node.className),ground:ground});});"
            "document.title='%s'+JSON.stringify({width:window.innerWidth,height:Math.ceil("
            "document.documentElement.getBoundingClientRect().height),lights:lights});})();"
            "</script></body>" % PANEL_PROBE),
        encoding="utf-8")
    dumped = subprocess.run(
        [str(find_edge()), "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--virtual-time-budget=2000",
         "--window-size=%d,%d" % (window, 2000),
         "--dump-dom", probe.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, cwd=workspace)
    for piece in dumped.stdout.split(PANEL_PROBE)[1:]:
        try:
            return json.loads(html_text.unescape(piece.split("</title>", 1)[0]))
        except ValueError:
            continue
    raise SystemExit("could not measure the panel; the renderer printed no height")


def css_colour(text: str) -> str:
    """#RRGGBB for a colour as Chromium computes one: rgb()/rgba(), or color(srgb ...) for a mix."""
    text = text.strip()
    found = re.fullmatch(r"rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\s*\)", text)
    if found:
        return "#%02X%02X%02X" % tuple(int(value) for value in found.groups())
    found = re.fullmatch(r"color\(srgb\s+([-\d.e]+)\s+([-\d.e]+)\s+([-\d.e]+)(?:\s*/\s*[\d.]+)?\s*\)", text)
    if found:
        return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(float(value) * 255))))
                                       for value in found.groups())
    raise SystemExit("the panel named a ground this cannot read: %r" % text)


def render_panel(target: Path, *, theme: str | None = None, design: str | None = None,
                 scale: float = PANEL_SCALE, height: int | None = None) -> dict:
    """The panel, rendered from `mcpui` rather than photographed inside Codex; returns its lights.

    Codex draws this HTML in its own frame, so a picture taken here is a faithful
    rendering of the same document and not a picture of Codex. The README says so; do not
    let it start implying otherwise.

    Published pictures are the whole page, in THEME, at PANEL_SCALE, in `design` - Soft but for the
    designs' own pictures. The audit sheets (`--audit`) ask for another theme, the window's scale and
    the top `height` CSS pixels. Every light on the page is held at the first moment of its breath
    (`held_lights`), and the page's lights are returned as the picture's record (`picture_record`), in
    device px, for `--breathe` to draw moving.
    """
    theme, design = theme or THEME, design or brand.DEFAULT_DESIGN
    html = panel_html(theme=theme, design=design)
    with tempfile.TemporaryDirectory() as workspace:
        page = Path(workspace) / "panel.html"
        page.write_text(html, encoding="utf-8")
        shot = Path(workspace) / "panel.png"
        probed = panel_probe(page, workspace)
        if height is None:
            height = probed["height"]
        subprocess.run(
            [str(find_edge()), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=%g" % scale,
             "--window-size=%d,%d" % (PANEL_CSS_WIDTH, height),
             "--screenshot=%s" % shot, page.as_uri()],
            check=True, capture_output=True, timeout=180,
            cwd=workspace)
        if not shot.is_file():
            raise SystemExit("the renderer produced no image")
        copy_file(shot, target)
    lights = [{"x": light["x"] * scale, "y": light["y"] * scale, "radius": light["radius"] * scale,
               "scale": scale, "state": light["state"], "ground": light["ground"]}
              for light in probed["lights"] if light["y"] + light["radius"] <= height]
    return picture_record("panel", theme, design, lights)


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


def pinned_clock() -> str:
    """The page's clock, stopped at POPUP_NOW - the moment the fixture is read at - and read in UTC.

    The panel writes a waiting row's next check as a clock time, or "due now" once that time has
    passed on the browser's own clock (panel.js `nextCheck`). Read against the machine's clock, the
    fixture's rows were months in the future the day a picture was made and would all turn into
    "due now" the day the machine's clock passed POPUP_NOW. The window is told its moment the same
    way (CODEX_AR_STILL_NOW). A date given to `Date` is still that date.

    And in UTC, as the card's reset time and every clock time in the window's envelope are: read in
    the machine's zone, the panel said 17:42 on a machine in Seoul beside a card saying 08:42 for the
    same reset. Edge takes its zone from Windows, not from TZ, so the page's local-time readings are
    its UTC ones - the only readings panel.js makes.
    """
    return ("<script>(function(){var Real=Date,at=%d;"
            "function Pinned(){var given=Array.prototype.slice.call(arguments);"
            "if(!(this instanceof Pinned))return new Real(at).toString();"
            "return given.length?new(Function.prototype.bind.apply(Real,[null].concat(given))):new Real(at);}"
            "Pinned.prototype=Real.prototype;Pinned.now=function(){return at;};"
            "Pinned.parse=Real.parse;Pinned.UTC=Real.UTC;window.Date=Pinned;"
            "['FullYear','Month','Date','Day','Hours','Minutes','Seconds','Milliseconds'].forEach("
            "function(part){Real.prototype['get'+part]=Real.prototype['getUTC'+part];});"
            "Real.prototype.getTimezoneOffset=function(){return 0;};})();</script>"
            % int(POPUP_NOW * 1000))


def held_lights() -> str:
    """Every animation on the page held at its first moment, which is the top of a light's breath.

    The panel starts its lights' cycle where its script says (`--light-delay`, from the page's own
    `performance.now()`), so a capture caught each light wherever the renderer happened to be - the
    four pixels that differed between two runs of this generator. Held at 0, the picture is the
    lights' first frame, and `--breathe` draws the rest from there (F15), as it does the window's,
    which is held at the same moment (CODEX_AR_STILL_LIGHT=0, build/capture_window.ps1).
    """
    return ("<style>*,*::before,*::after{animation-play-state:paused!important;"
            "animation-delay:0s!important}</style>")


def panel_html(theme=None, design=None) -> str:
    """The exact markup the panel screenshot is a picture of, pinned to `theme` and `design` (Soft when
    none is given: the page is stamped as the script stamps a stored Soft, and told to keep it)."""
    page = mcpui.settings_page(sample_panel_data(design), theme=theme,
                               design=design or brand.DEFAULT_DESIGN)
    # Before the panel's own script, which reads the host and the clock as it starts.
    head, _, tail = page.rpartition("<script>")
    return head + held_lights() + pinned_clock() + preview_host() + "<script>" + tail


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
    """The popup's rows: the fixture's, as the popup's own read (`ui/popup/model.perform`) lists them.

    Until v0.6.10 these were written out here, three of them, with a disabled server error the
    window and the panel never showed ("Waiting 3" beside "2 recoveries pending"). A row the other
    surfaces do not have is a row an audit cannot compare.
    """
    return fixture()["pending"]


def popup_view(locale: str):
    from codex_auto_resume import interface
    from codex_auto_resume.ui import popup as tray_popup
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

    write_file(path, b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


# Windows occasionally refuses a write to a picture this generator has just written - EINVAL from a
# scanner, a sync client or the shell still holding the file - and the same write succeeds a moment
# later. A run takes a quarter of an hour, so one unlucky file must not end it; every picture written
# or copied here goes through these two. Nothing else is retried: a path that is wrong stays wrong.
WRITE_ATTEMPTS = 6
WRITE_PAUSE = 0.4


def write_file(path: Path, data: bytes) -> None:
    for attempt in range(WRITE_ATTEMPTS):
        try:
            path.write_bytes(data)
            return
        except OSError:
            if attempt == WRITE_ATTEMPTS - 1:
                raise
            time.sleep(WRITE_PAUSE)


def copy_file(source, target) -> None:
    for attempt in range(WRITE_ATTEMPTS):
        try:
            shutil.copyfile(source, target)
            return
        except OSError:
            if attempt == WRITE_ATTEMPTS - 1:
                raise
            time.sleep(WRITE_PAUSE)


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


def _delay_parts(delay) -> tuple:
    """A frame's delay as an APNG writes it, (numerator, denominator) seconds: an int is milliseconds, and a
    Fraction a second's exact share - which is how a breath of 4400 ms in 132 frames is written, 1/30 s each,
    where 33 ms each made it 4356 (v0.6.10)."""
    parts = (delay.numerator, delay.denominator) if isinstance(delay, Fraction) else (int(delay), 1000)
    if not all(0 <= part <= 0xFFFF for part in parts) or not parts[1]:
        raise ValueError("an APNG cannot hold a delay of %r" % (delay,))
    return parts


def write_apng(path: Path, width: int, height: int, frames, alpha=None) -> None:
    """An animated PNG that loops forever, from RGB pictures all `width` by `height`.

    `frames` is [(delay, RGB bytes)] - any iterable of them, taken one at a time - each picture the whole size, each
    delay in ms or as a Fraction of a second (`_delay_parts`). The first is what a viewer without APNG shows; each
    later one is written as the rectangle that differs from the frame before it, over it - so a picture where only a
    light moves costs a few hundred bytes a frame, and can be shown at the rate the real thing moves at. Nothing
    here depends on the machine: the same pictures make the same bytes.

    `alpha` is the picture's transparency, one byte a pixel, kept for every frame: only the light moves, and the
    light is never at a corner, so what is transparent stays transparent throughout.
    """
    frames = iter(frames)
    first = next(frames, None)
    if first is None:
        raise ValueError("an APNG needs at least one picture")

    def later():
        previous = first[1]
        for delay, picture in frames:
            box = _apng_changed(previous, picture, width, height)
            if box is None:
                box = (0, 0, 1, 1)                   # a frame that changes nothing still takes its time
            yield delay, box, _region(picture, width, box)
            previous = picture
    write_apng_patches(path, width, height, first, later(), alpha)


def write_apng_patches(path: Path, width: int, height: int, first: tuple, later, alpha=None) -> None:
    """An animated PNG that loops forever, from its first picture whole - (delay, RGB bytes) - and each later frame
    as the one rectangle it draws over the frame before: (delay, (left, top, width, height), that rectangle's RGB).
    `alpha`, one byte a pixel of the whole picture, is kept for every frame, as `write_apng` keeps it."""
    import zlib
    body, sequence, count = bytearray(), 1, 1
    for delay, (left, top, wide, tall), patch in later:
        numerator, denominator = _delay_parts(delay)
        body += _png_chunk(b"fcTL", struct.pack(">IIIIIHHBB", sequence, wide, tall, left, top,
                                                numerator, denominator, APNG_KEEP, APNG_OVER))
        sequence += 1
        clear = None if alpha is None else b"".join(
            alpha[(top + row) * width + left:(top + row) * width + left + wide] for row in range(tall))
        rows = _png_rows(patch, wide, tall, wide, 0, 0, clear)
        body += _png_chunk(b"fdAT", struct.pack(">I", sequence) + zlib.compress(rows, 9))
        sequence += 1
        count += 1
    delay, picture = first
    numerator, denominator = _delay_parts(delay)
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0))
    out += _png_chunk(b"acTL", struct.pack(">II", count, 0))
    out += _png_chunk(b"fcTL", struct.pack(">IIIIIHHBB", 0, width, height, 0, 0,
                                           numerator, denominator, APNG_KEEP, APNG_OVER))
    out += _png_chunk(b"IDAT", zlib.compress(_png_rows(picture, width, height, width, 0, 0, alpha), 9))
    out += body
    out += _png_chunk(b"IEND", b"")
    write_file(path, bytes(out))


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


def render_popup(target: Path, locale: str, *, theme: str | None = None, design: str | None = None,
                 scale: float = POPUP_SCALE, moving: bool = True) -> dict:
    """The popup in THEME at POPUP_SCALE, in `design`; returns the picture's record (`picture_record`).

    Its light moves as the popup's own moves (F15): the whole popup drawn by its renderer at the first
    moment of the light's breath, and then, frame by frame, only the light, drawn again by the same
    renderer's `draw_halo` - the call the popup makes for a frame of its light - at each moment of one
    cycle (`light_timeline`). A light that does not move is one still picture, as is every picture the
    audit sheets ask for (`moving=False`), with another theme and scale.
    """
    from codex_auto_resume.ui import popup as tray_popup
    strings, view = popup_view(locale)
    theme, design = theme or THEME, design or brand.DEFAULT_DESIGN
    renderer = tray_popup.Renderer()
    renderer.theme = theme                      # said, not left to the renderer's default
    renderer.design = design                    # and the design, likewise
    try:
        plan = renderer.layout(view, scale, tray_popup.locale_of(strings))
        width, height = plan["size"]
        record = picture_record("popup", theme, design, popup_lights(plan, theme, design))

        def at(moment):
            return tray_popup.halo(view["light"], moment, moment, design=design)

        canvas = renderer.draw(view, plan, frame=at(0))
        timeline = light_timeline(record) if moving else None
        if timeline is None:
            write_png(target, width, height, canvas.pixels())
            return record

        def frames():
            yield timeline.delay, bgra_rgb(canvas.pixels())
            for moment in timeline.moments[1:]:
                yield timeline.delay, bgra_rgb(renderer.draw_halo(plan, at(moment)).pixels())
        write_apng(target, width, height, frames())
        return record
    finally:
        renderer.close()


def popup_lights(plan, theme: str, design: str) -> list:
    """The popup's one light, the plan's halo item, on the popup's card: a record's lights, in device px."""
    scale = plan.get("scale", 1.0)
    return [{"x": item["cx"], "y": item["cy"], "radius": brand.STATUS_DOT["popup"] * scale, "scale": scale,
             "state": item["state"], "ground": brand.card_ground(theme, design)}
            for item in plan["items"] if item["kind"] == "halo"]


def bgra_rgb(bgra: bytes) -> bytes:
    """A canvas's BGRA bytes as the RGB an APNG frame is written from."""
    count = len(bgra) // 4
    rgb = bytearray(count * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    return bytes(rgb)


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
# `tray_popup.py` and `tray_popup/**` are kept although neither exists: this tuple has
# always named both where a thing is and where it is going, so that the move itself is
# never the change that makes a picture stale.
POPUP_CODE = ("tray_popup.py", "tray_popup/**/*.py", "brand.py", "brand/**/*.py",
              "ui/popup/**/*.py", "ui/brand/**/*.py")


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


def popup_render_input(locale: str, drawing: str | None = None, design: str | None = None) -> str:
    """The popup's manifest entry for one locale: what it is shown, and what draws it.

    `drawing` is `popup_drawing()`, passed in when it is already known. `design` is the design it is
    drawn in (v0.6.10), named in what is hashed for any design but Soft - so Soft's entries are keyed
    as they always were, and each other design's picture has an entry of its own, which moves when
    the design's tokens or its drawing do, since both are in `drawing`.
    """
    _strings, view = popup_view(locale)
    if drawing is None:
        drawing = popup_drawing()
    shown = json.dumps(view, sort_keys=True, default=str)
    if design not in (None, brand.DEFAULT_DESIGN):
        shown += "\0design:" + design
    return sha256((shown + drawing).encode("utf-8"))


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
CARD_RESET_AT = POPUP_NOW + USAGE_RESET_IN  # the fixture's usage limit, on the same conversation
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


def card_render_input(locale: str, drawing: str | None = None, design: str | None = None) -> str:
    """The card's manifest entry for one locale: what it says, the themes and scale it is
    pictured at, and what draws it. `drawing` is `card_drawing()` when already known; `design`, as for
    the popup (`popup_render_input`), is named only for a design other than Soft."""
    shown = {"view": card_view(locale), "themes": list(card_themes(locale)), "scale": CARD_SCALE}
    if design not in (None, brand.DEFAULT_DESIGN):
        shown["design"] = design
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


class _SettledCard:
    """The card at rest, off-screen, and its light at any moment of its breath: `at(ms)` is the whole
    picture - the card and its floating shadow over the theme's canvas - as BGRA.

    The first picture is the card drawn whole (`Card._draw_card`) and settled; every later one is the
    card's own breath (`Card._draw_light`, the call a card makes for a frame of its light), which draws
    the light's band again and cuts it as the whole card is cut - so only the rows of that band are
    laid over the ground again, and every other pixel is the first picture's.
    """

    def __init__(self, locale, theme, design, scale, themes):
        from codex_auto_resume import notice_card, notice_window
        from codex_auto_resume.ui import popup as tray_popup
        self._release = tray_popup._gdiplus_release
        where = {"dpi": int(round(96 * scale)), "work": (0, 0, 0, 0), "monitor": (0, 0, 0, 0),
                 "anchor": None}
        drawn = {"theme": theme, "design": design, "contrast": False, "reduced": False}
        tray_popup._gdiplus_acquire()
        self.card = None
        try:
            self.card = card = notice_window.Card(_NoStack(), card_notice(locale), now_ms=0, where=where,
                                                  drawn=drawn, windows=False)
            frame = card.paint(notice_card.ENTRANCE_MS)["frame"]     # at rest: whole, full depth
            if frame != notice_card.SETTLED:
                raise RuntimeError("the card is not at rest: %r" % (frame,))
            (width, height), margin = card.size, card.margin
            body, shadow = card.body.pixels(), card.shadow.pixels()
        except BaseException:
            self.close()
            raise
        # The ground reaches as far as the deeper theme's shadow in both, so a light and a dark
        # picture of the same card are the same size and can stand side by side - and as far as
        # Soft's in every design, so a design that floats no shadow (Classic, Plain) is pictured at
        # the same size, and on the same margin of canvas, as Soft's.
        self.pad = pad = max(notice_card.shadow_margin(notice_card.float_shadows(each), scale)
                             for each in (themes or CARD_THEMES))
        red, green, blue = brand.rgb(brand.palette(theme, design)["canvas"])
        self.card_width, self.card_height = width, height
        self.width, self.height = width + 2 * pad, height + 2 * pad
        ground = bytearray(bytes((blue, green, red, 255)) * (self.width * self.height))
        if margin:
            _over(ground, self.width, shadow, width + 2 * margin, height + 2 * margin,
                  pad - margin, pad - margin)
        self._ground = bytes(ground)                   # the canvas and the shadow, under the card
        _over(ground, self.width, body, width, height, pad, pad)
        self._first = bytes(ground)
        self.lights = [{"x": item["cx"] + pad, "y": item["cy"] + pad,
                        "radius": brand.STATUS_DOT["popup"] * scale, "scale": scale, "state": item["state"],
                        "ground": brand.card_ground(theme, design)}
                       for item in card.plan["items"] if item["kind"] == "halo"]

    def at(self, moment) -> bytes:
        if not moment:
            return self._first
        card = self.card
        card._draw_light(card.born + moment)
        top, bottom = card.renderer.halo_rows
        row = self.card_width * 4
        band = bytes(card.image._pixels[top * row:bottom * row])
        whole = bytearray(self._first)
        start, stop = (self.pad + top) * self.width * 4, (self.pad + bottom) * self.width * 4
        rows = bytearray(self._ground[start:stop])
        _over(rows, self.width, band, self.card_width, bottom - top, self.pad, 0)
        whole[start:stop] = rows
        return bytes(whole)

    def close(self):
        if self.card is not None:
            self.card.close()
            self.card = None
        if self._release is not None:
            self._release()
            self._release = None


def card_pixels(locale: str, theme: str, *, design: str | None = None, scale: float = CARD_SCALE,
                themes: tuple | None = None):
    """(width, height, BGRA): the settled card and its floating shadow over the theme's canvas, its
    light at the first moment of its breath.

    At CARD_SCALE, on a ground as wide as the deepest shadow of CARD_THEMES; the audit sheets ask
    for the window's scale and both themes."""
    settled = _SettledCard(locale, theme, design or brand.DEFAULT_DESIGN, scale, themes)
    try:
        return settled.width, settled.height, settled.at(0)
    finally:
        settled.close()


def render_card(target: Path, locale: str, theme: str, *, design: str | None = None, moving: bool = True,
                scale: float = CARD_SCALE, themes: tuple | None = None) -> dict:
    """The card in `theme` and `design`, its light moving as the card's own does (F15); returns the
    picture's record. Still when its light does not move, or when the audit sheets ask for a still
    picture (`moving=False`)."""
    design = design or brand.DEFAULT_DESIGN
    settled = _SettledCard(locale, theme, design, scale, themes)
    try:
        record = picture_record("card", theme, design, settled.lights)
        timeline = light_timeline(record) if moving else None
        if timeline is None:
            write_png(target, settled.width, settled.height, settled.at(0))
            return record
        write_apng(target, settled.width, settled.height,
                   ((timeline.delay, bgra_rgb(settled.at(moment))) for moment in timeline.moments))
        return record
    finally:
        settled.close()


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
    records = {}
    for locale in LOCALES + EXTRA_LOCALES:
        for theme, (asset, copy) in card_paths(locale).items():
            records[asset or copy] = render_card(asset or copy, locale, theme)
            if asset is not None:
                copy_file(asset, copy)
                records[copy] = records[asset]
            print("  %s  %s" % ((asset or copy).relative_to(ROOT), dimensions(asset or copy)))
    for design in DESIGNS_PICTURED[1:]:
        target = design_picture(design, "card")
        records[target] = render_card(target, "en", THEME, design=design)
        print("  %s  %s" % (target.relative_to(ROOT), dimensions(target)))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    drawing = card_drawing()
    for locale in LOCALES + EXTRA_LOCALES:
        manifest["inputs"]["<card render:%s>" % locale] = card_render_input(locale, drawing)
    for design in DESIGNS_PICTURED[1:]:
        manifest["inputs"]["<card render:en:%s>" % design] = card_render_input("en", drawing, design)
    ordered = {}
    for key, value in manifest.items():                 # where a whole run writes it
        if key != "card_themes":
            ordered[key] = value
        if key == "theme":
            ordered["card_themes"] = list(CARD_THEMES)
    manifest = ordered
    files = _card_files() + [design_picture(design, "card") for design in DESIGNS_PICTURED[1:]]
    manifest.setdefault("lights", {})
    for path in files:
        key = str(path.relative_to(ROOT)).replace("\\", "/")
        manifest["images"][key] = {"sha256": sha256(path.read_bytes()), "size": dimensions(path)}
        manifest["lights"][key] = records[path]
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
ICON_ROOTS = (("ui.tray", "IconFrames"), ("ui.tray", "icon_frame"), ("ui.tray", "icon_frame_ms"),
              ("ui.tray", "icon_head_colour"), ("ui.tray", "icon_level_colour"),
              ("ui.tray", "ICON_FOR_LIGHT"), ("brand", "rgb"))


# --------------------------------------------------------- pictures that breathe
# A still picture of a light says nothing about a light that moves, so every picture of a surface whose light moves
# is animated (v0.6.9), and since v0.6.10 every light in it moves as the product moves it (F15). Until then one disc
# a picture was found by its colour and painted again, on the light theme's `surface` whatever it stood on, in
# monitoring's rhythm, 132 frames of 33 ms - 4356 ms against the product's 4400: the panel's tile light held still
# beside the one above it, a light on a tile or in the dark theme would have been painted in a box of the wrong
# ground, and every picture ran 1% fast.
#
# Now each surface declares its lights (`picture_record`): where each one is, its radius, its state and the ground
# it stands on. The popup and the card declare the halo their own layout places, and are drawn moving by their own
# renderers where they are made (`render_popup`, `render_card`). The panel is asked where its lights are
# (`panel_probe`) and the window, which cannot be asked, is searched for discs of its light's colour
# (`find_lights`), as many as it has (WINDOW_LIGHTS); both are captured still at the first moment of the breath, and
# `--breathe` draws each light they declare again over the capture at every moment of one cycle, with its own
# radius, ground and state (`paint_light`), the checking arc included - after holding the capture to what was
# declared (`check_capture`). A viewer that ignores the animation sees the first frame.
#
# One cycle exactly (`light_timeline`): the lights that move in a picture move on one rhythm - a picture whose lights
# have two is refused - at BREATHE_FPS, and a frame's delay is written as the exact fraction of a second it is, so a
# 4400 ms breath takes 4400 ms. A picture with two lights (the panel) draws one of them a frame, each in its turn:
# an APNG frame is one rectangle, and one rectangle round two lights 1170 px apart is most of the page, every frame.
BREATHE_FPS = 30
# The surfaces `--breathe` draws over a capture. The popup and the card are drawn moving where they are made.
CAPTURED = ("window", "panel")
# The window's lights: its one HaloDot, the header's (gui/Marks.cs), which tests/test_screenshots.py counts.
WINDOW_LIGHTS = 1
# How much larger than its geometry GDI+ draws an antialiased disc, in device px: the window's 7.5 px dot at 144 DPI
# is fully covered 16 px across in a capture, and a light drawn 8 px in radius over it matches the capture to a mean
# of under two levels a channel, where one drawn at 7.5 is off by 13 (measured on the v0.6.10 captures).
GDI_PLUS_SPREAD = 0.5
# How far, per channel, a capture's pixel just outside a light's reach may be from the ground the light declares;
# and how far its pixel at the light's centre may be from the light's colour at the first moment of the breath.
GROUND_TOLERANCE = 2
CENTRE_TOLERANCE = 8
# A light owns every pixel within its reach and LIGHT_MARGIN device px more, which it draws again at every moment;
# the capture is held to its ground past its reach and LIGHT_FRINGE, where a renderer's antialiasing of the glow's
# edge - GDI+'s path gradient reaches most of a pixel past it - has faded to nothing.
LIGHT_MARGIN = 2.0
LIGHT_FRINGE = 1.0


def picture_record(surface: str, theme: str, design: str, lights: list) -> dict:
    """What a picture holds of the status light, as the manifest keeps it (its "lights"): the surface, the theme and
    the design it is drawn in, and each light, top to bottom, as {"x", "y": its centre in device px from the
    picture's corner - the pixel (i, j) spans i to i + 1 - "radius": the dot's, in device px, "scale": device px a
    CSS px, "state": the light's state, "ground": the #RRGGBB it stands on}."""
    def kept(light):
        return {key: (round(float(value), 3) if isinstance(value, (int, float)) and not isinstance(value, bool)
                      else value) for key, value in light.items()}
    return {"surface": surface, "theme": theme, "design": design,
            "lights": [kept(light) for light in sorted(lights, key=lambda light: (light["y"], light["x"]))]}


def light_cycle(state: str):
    """One cycle of a state's light in ms: its breath (brand.GLOW), or checking's turn of the arc; None when off."""
    if state in brand.GLOW_BREATHES:
        return brand.GLOW[state + "_ms"]
    if state == "checking":
        return brand.GLOW["arc_ms"]
    return None


class Timeline(NamedTuple):
    """When a picture's lights are drawn: `steps` moments of one `cycle` (ms), at `moments` (ms from the start), each
    frame shown for `delay` (a Fraction of a second), and which of the record's lights move (`moving`)."""
    cycle: int
    steps: int
    moments: tuple
    delay: Fraction
    moving: tuple


def light_timeline(record: dict):
    """The one cycle a picture's lights move on, or None when none of them moves (lights that are off). The same
    in every design: none holds its light still. Refuses a picture whose moving lights have different rhythms: it
    could not loop for both."""
    moving = tuple(index for index, light in enumerate(record["lights"])
                   if brand.glow_moves(light["state"]))
    if not moving:
        return None
    cycles = sorted({light_cycle(record["lights"][index]["state"]) for index in moving})
    if len(cycles) != 1:
        raise SystemExit("a %s picture's lights move on %s ms: one picture loops on one rhythm"
                         % (record["surface"], cycles))
    cycle = cycles[0]
    steps = max(1, int(round(cycle * BREATHE_FPS / 1000.0)))
    delay = Fraction(cycle, 1000 * steps * len(moving))
    if delay.numerator > 0xFFFF or delay.denominator > 0xFFFF:
        raise SystemExit("a frame of %s s cannot be written in an APNG" % delay)
    return Timeline(cycle, steps, tuple(cycle * step / float(steps) for step in range(steps)), delay, moving)


# How far toward the card a dot may be dimmed and still be the dot. brand.glow dims to `glow_floor` - about 0.38
# of the way - at the bottom of a breath, and the glow round it never comes closer to the light's own colour than
# about two thirds of the way, so a threshold between the two tells a dimmed dot from the glow it sits in.
LIGHT_DIM = 0.45


def find_lights(rgb: bytes, width: int, height: int, colour: tuple, ground: tuple) -> list:
    """[(x, y, radius)] of every status light in a captured picture, top to bottom: each round disc of its colour.

    How the window declares its lights (`window_record`): it is the one surface that cannot be asked where they are.
    x and y are pixel indexes - the disc's centre is at (x + 0.5, y + 0.5) - and the radius is half the disc's width
    in pixels. A capture is held at the first moment of the breath, the brightest, but a disc is found at any
    point of it: pixels are the light's when they lie on the line from its colour toward the ground under it, no
    further than LIGHT_DIM - which the glow never reaches - and are gathered into clusters; a chip or a button is a
    rectangle and fails the roundness check, and a glyph is neither round nor wide enough.

    Every disc, not the topmost or the roundest (v0.6.10). Until then the one found was the one light a picture
    moved, and which it was had gone wrong once already: the panel's pictures breathed the dot in the Automatic
    recovery tile, which did not move in the product, and held the status light above it still. What a picture
    moves now is what its surface declares; this finds the window's, and `window_record` refuses a capture where it
    finds more or fewer than the window has.
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
    discs = []
    for found in clusters:
        xs = [x for x, _ in found]
        ys = [y for _, y in found]
        wide, tall = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if abs(wide - tall) > 2 or not (6 <= wide <= 40):
            continue                                        # a small disc, not a chip and not a glyph
        area = 3.14159 * (wide / 2.0) ** 2
        if abs(len(found) - area) > 0.35 * area:
            continue                                        # filled like a disc, not a ring or a letter
        discs.append((sum(xs) / len(xs), sum(ys) / len(ys), wide / 2.0))
    return sorted(discs, key=lambda disc: (disc[1], disc[0]))


def find_light(rgb: bytes, width: int, height: int, colour: tuple, ground: tuple) -> tuple | None:
    """The topmost of `find_lights`, or None: (x, y, radius) in pixel indexes."""
    found = find_lights(rgb, width, height, colour, ground)
    return found[0] if found else None


def fixture_light() -> str:
    """The header light the fixture shows at its moment: the popup's word for it, which the window's is held to by
    tests/test_light_parity.py - and so the state of the window's light in every capture."""
    return popup_view("en")[1]["light"]


def window_record(path: Path, theme: str | None = None, design: str | None = None) -> dict:
    """A window capture's record: its lights, found in the picture (`find_lights`) - as many as the window has, each
    at the size the window draws it at the scale it was captured at (and GDI_PLUS_SPREAD), in the fixture's state,
    on the header card's ground - or SystemExit."""
    theme, design = theme or THEME, design or brand.DEFAULT_DESIGN
    state = fixture_light()
    colour = brand.rgb(brand.palette(theme, design)[brand.status_fill(state)])
    ground = brand.card_ground(theme, design)
    width, height, rgb, _alpha = read_png(path)
    found = find_lights(rgb, width, height, colour, brand.rgb(ground))
    if len(found) != WINDOW_LIGHTS:
        raise SystemExit("%s: %d lights of the colour %s, where the window has %d"
                         % (path.name, len(found), brand.status_fill(state), WINDOW_LIGHTS))
    scale = (system_dpi() or 96) / 96.0
    radius = brand.STATUS_DOT["window"] * scale + GDI_PLUS_SPREAD
    lights = []
    for x, y, measured in found:
        if abs(measured - radius) > 1.0:
            raise SystemExit("%s: a light %.1f px across where the window draws %.1f" % (path.name, 2 * measured,
                                                                                         2 * radius))
        # The window centres its light in a box a whole number of pixels wide, so the centre is on the
        # half-pixel grid; the disc's mean is a little off it where the antialiasing is not symmetric.
        lights.append({"x": round(2 * (x + 0.5)) / 2.0, "y": round(2 * (y + 0.5)) / 2.0, "radius": radius,
                       "scale": scale, "state": state, "ground": ground})
    return picture_record("window", theme, design, lights)


def light_reach(light: dict) -> float:
    """How far from its centre any moment of a light draws, in device px: its glow's widest, or checking's arc."""
    drawn, scale = light["radius"], light.get("scale", 1.0)
    reach = drawn + brand.glow_reach(drawn)
    if light["state"] == "checking":
        reach = max(reach, drawn + (brand.GLOW["arc_gap"] + brand.GLOW["arc_width"] / 2.0) * scale)
    return reach


def light_pixels(light: dict) -> list:
    """[(x, y, samples)] of every pixel a light owns - within its reach and LIGHT_MARGIN more - each with its nine
    samples as (dx, dy, distance, angle) from the centre, the angle in degrees clockwise from three o'clock."""
    cx, cy = light["x"], light["y"]
    edge = light_reach(light) + LIGHT_MARGIN
    owned = []
    for y in range(int(math.floor(cy - edge)), int(math.ceil(cy + edge)) + 1):
        for x in range(int(math.floor(cx - edge)), int(math.ceil(cx + edge)) + 1):
            if math.hypot(x + 0.5 - cx, y + 0.5 - cy) > edge:
                continue
            samples = []
            for sub_y in range(3):
                for sub_x in range(3):
                    dx, dy = x + (sub_x + 0.5) / 3.0 - cx, y + (sub_y + 0.5) / 3.0 - cy
                    samples.append((dx, dy, math.hypot(dx, dy), math.degrees(math.atan2(dy, dx)) % 360.0))
            owned.append((x, y, samples))
    return owned


def paint_light(picture: bytearray, width: int, light: dict, frame, colour: tuple, owned=None) -> tuple:
    """Draw one light at one moment into the RGB `picture` (`width` px wide), over its declared ground; returns the
    (left, top, width, height) it drew.

    `frame` is brand.glow's for the moment. The light is drawn as every surface draws it: its ground, the glow's
    falloff at that spread (brand.glow_stops, a share of the dot, so one table serves every radius), the dot drawn
    toward its ground by the breath's dim - which is the same pixel whether the glow is under the dot (the window,
    the popup) or over it (the panel) - and checking's arc, `arc_sweep` degrees of a ring `arc_gap` past the dot,
    round-capped. Every pixel the light owns (`light_pixels`) is drawn again, nine samples a pixel, and no other.
    """
    owned = light_pixels(light) if owned is None else owned
    ground = brand.rgb(light["ground"])
    drawn, scale = light["radius"], light.get("scale", 1.0)
    stops = brand.glow_stops(drawn)
    dim, opacity = (frame["dim"], frame["opacity"]) if frame else (0.0, 0.0)
    outer = brand.glow_radius(drawn, frame["spread"]) if frame else drawn
    arc = frame.get("arc") if frame else None
    middle = drawn + brand.GLOW["arc_gap"] * scale
    half = brand.GLOW["arc_width"] * scale / 2.0
    sweep = brand.GLOW["arc_sweep"]
    ends = ()
    if arc is not None:
        ends = tuple((middle * math.cos(math.radians(angle)), middle * math.sin(math.radians(angle)))
                     for angle in (arc, arc + sweep))
    left = top = None
    right = bottom = None
    for x, y, samples in owned:
        red = green = blue = 0.0
        for dx, dy, away, angle in samples:
            parts = list(ground)
            if opacity > 0 and outer > 0 and away < outer:
                alpha = opacity * _falloff(stops, away / outer)
                parts = [part + (one - part) * alpha for part, one in zip(parts, colour)]
            if away < drawn:
                parts = [part + (one - part) * (1.0 - dim) for part, one in zip(parts, colour)]
            if arc is not None and (
                    (abs(away - middle) <= half and (angle - arc) % 360.0 <= sweep)
                    or any(math.hypot(dx - ex, dy - ey) <= half for ex, ey in ends)):
                alpha = brand.GLOW["arc_alpha"]
                parts = [part + (one - part) * alpha for part, one in zip(parts, colour)]
            red += parts[0]
            green += parts[1]
            blue += parts[2]
        at = (y * width + x) * 3
        picture[at:at + 3] = bytes((int(round(red / 9.0)), int(round(green / 9.0)), int(round(blue / 9.0))))
        left = x if left is None else min(left, x)
        right = x if right is None else max(right, x)
        top = y if top is None else min(top, y)
        bottom = y if bottom is None else max(bottom, y)
    return left, top, right - left + 1, bottom - top + 1


def check_capture(rgb: bytes, width: int, height: int, light: dict, colour: tuple, owned: list, where: str) -> None:
    """Hold a capture to a light it declares before anything is drawn over it, or SystemExit.

    Every pixel the light owns lies inside the picture; each one no sample of which is within the light's reach and
    its fringe - the ring round it, which every frame draws as the ground - is the declared ground, so a frame can
    never paint a box of a ground the light does not stand on; and the pixel at the centre is the light's colour, as it is at the
    first moment of a breath, so the light is where it was declared.
    """
    reach = light_reach(light) + LIGHT_FRINGE
    ground = brand.rgb(light["ground"])
    for x, y, samples in owned:
        if not (0 <= x < width and 0 <= y < height):
            raise SystemExit("%s: the light at (%g, %g) reaches past the picture" % (where, light["x"], light["y"]))
        if min(sample[2] for sample in samples) <= reach:
            continue
        at = (y * width + x) * 3
        if any(abs(rgb[at + channel] - ground[channel]) > GROUND_TOLERANCE for channel in range(3)):
            raise SystemExit("%s: the light at (%g, %g) stands on #%02X%02X%02X at (%d, %d), not on its ground %s"
                             % ((where, light["x"], light["y"]) + tuple(rgb[at:at + 3]) + (x, y, light["ground"])))
    at = (int(light["y"]) * width + int(light["x"])) * 3
    if any(abs(rgb[at + channel] - colour[channel]) > CENTRE_TOLERANCE for channel in range(3)):
        raise SystemExit("%s: no light of its colour at (%g, %g)" % (where, light["x"], light["y"]))


def _region(picture: bytes, width: int, box: tuple) -> bytes:
    """The RGB bytes of a (left, top, width, height) rectangle of a picture `width` px wide."""
    left, top, wide, tall = box
    return b"".join(bytes(picture[((top + row) * width + left) * 3:((top + row) * width + left + wide) * 3])
                    for row in range(tall))


def breathe_frames(rgb: bytes, width: int, height: int, record: dict, where: str = "a picture"):
    """One cycle of a captured picture's lights, as (delay, first picture, [(delay, box, RGB of the box)]): the first
    picture whole and each later frame the one light it moves; None when no light in it moves.

    Frame k * n + i, of n lights that move, draws light i at moment k (`light_timeline`), so every light is drawn
    at every moment for the same time and the loop is exactly one cycle. The first picture has the first light at
    the first moment and each other where it was one frame before the loop began, so the loop has no seam.
    """
    timeline = light_timeline(record)
    if timeline is None:
        return None
    palette = brand.palette(record["theme"], record["design"])
    picture = bytearray(rgb)
    lights = []
    for index in timeline.moving:
        light = record["lights"][index]
        colour = brand.rgb(palette[brand.status_fill(light["state"])])
        owned = light_pixels(light)
        check_capture(rgb, width, height, light, colour, owned, where)
        lights.append((light, colour, owned))

    def draw(entry, step):
        light, colour, owned = entry
        moment = timeline.moments[step]
        frame = brand.glow(light["state"], moment, moment, design=record["design"])
        return paint_light(picture, width, light, frame, colour, owned)

    last = timeline.steps - 1
    for position, entry in enumerate(lights):
        draw(entry, 0 if position == 0 else last)
    first = bytes(picture)
    later = []
    for step in range(timeline.steps):
        for position, entry in enumerate(lights):
            if step == 0 and position == 0:
                continue
            box = draw(entry, step)
            later.append((timeline.delay, box, _region(picture, width, box)))
    return timeline.delay, first, later


def breathe_pictures(paths=None) -> list:
    """Draw every captured light that moves, moving, and say which pictures now move.

    The second step of a whole regeneration, after `python build/make_screenshots.py`:

        python build/make_screenshots.py --breathe

    It reads each picture's record from the manifest (its "lights"), where the first step wrote it, and draws the
    window's and the panel's pictures (CAPTURED); the popup's and the card's move already. A documentation copy is
    copied rather than drawn again: two encodings of one picture are two files, and the suite holds each copy to be
    its canonical asset byte for byte. A picture that already moves is drawn again from its first frame, which is
    the same picture: running this twice changes nothing.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = manifest.get("lights", {})
    copies = {}
    for locale in LOCALES:
        copies.update(paths_for(locale))
    copied = set(copies.values())
    done = []
    for key in sorted(records):
        path, record = ROOT / key, records[key]
        if record["surface"] not in CAPTURED or path in copied:
            continue
        if paths is not None and path not in paths:
            continue
        if breathe_picture(path, record):
            done.append(path)
            print("  %s  %s" % (path.relative_to(ROOT), dimensions(path)))
            copy = copies.get(path)
            if copy is not None:
                copy_file(path, copy)
                done.append(copy)
    for path in done:
        key = str(path.relative_to(ROOT)).replace("\\", "/")
        manifest["images"][key] = {"sha256": sha256(path.read_bytes()), "size": dimensions(path)}
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifest       : %s (the pictures that breathe)" % MANIFEST.relative_to(ROOT))
    return done


def breathe_picture(path: Path, record: dict) -> bool:
    """Rewrite a captured picture as an APNG in which every light it declares moves. False when none moves."""
    width, height, rgb, alpha = read_png(path)
    made = breathe_frames(rgb, width, height, record, where=path.name)
    if made is None:
        return False
    delay, first, later = made
    write_apng_patches(path, width, height, (delay, first), later, alpha)
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
    """One breath of the light, as an APNG: the pictures keep their colours, and only the light changes.

    Each picture is held for exactly its share of the breath, a Fraction of a second: 33 ms each made the 4400 ms
    breath 4356 until v0.6.10, as it did every picture that breathes (`light_timeline`)."""
    cycle = brand.GLOW[LIGHT_MOTION_STATE + "_ms"]
    steps = int(round(cycle / 1000.0 * LIGHT_MOTION_FPS))
    delay = Fraction(cycle, 1000 * steps)
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
    from codex_auto_resume import brand
    from codex_auto_resume.ui import tray
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
    from codex_auto_resume.ui import tray
    for at in range(0, loop, 97):
        if abs(tray.icon_turn(state, length + at) - tray.icon_turn(state, at)) > 1e-6:
            return False
    return True


def icon_timeline(state: str, start: float, end: float) -> list:
    """(ms from `start`, position, level) for each frame the icon's own timer shows in [start, end): stepped from the
    motion clock's zero, where the state is entered, by the interval each frame asks for (tray.icon_frame_ms). The
    frame on show at `start` comes first, at 0; a state that stops moving holds its last frame."""
    from codex_auto_resume.ui import tray
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
    from codex_auto_resume import brand
    from codex_auto_resume.ui import tray
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
    from codex_auto_resume.ui import tray
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
    write_file(path, bytes(data))


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
    # In the order a whole run writes it, which since v0.6.10 renders this picture too.
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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


def scratch_installation(workspace: Path, theme: str | None = None, design: str | None = None) -> Path:
    """An installation made out of the working tree, so the picture is of this code.

    It stores THEME, as every published picture is drawn; the audit sheets store the theme they draw.
    It stores Soft, but for the designs' own pictures, which store the design they picture.
    """
    import make_release
    import zipfile

    home = workspace / "home"
    (home / "app").mkdir(parents=True)
    shutil.copytree(ROOT / "src", home / "app" / "src")
    # Bundling the frozen registry data, so the window's own bridge answers as the envelope does.
    shutil.copyfile(frozen_registry().FROZEN,
                    home / "app" / "src" / "codex_auto_resume" / "data" / "codex_compat.json")
    # And the sample counts of what others report, so the card's Reported row is the envelope's too.
    shutil.copyfile(frozen_registry().REPORTED,
                    home / "app" / "src" / "codex_auto_resume" / "data" / "reported.json")
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
    write_settings(home, theme, design)
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


def render_window(targets: dict, theme: str | None = None, design: str | None = None) -> dict:
    """Capture each page of the window, with the watcher's mutex held but no watcher running.

    The window reports "watching" when the single-instance mutex is taken, so taking it
    is enough to show the product in its ordinary state. Starting a real watcher would
    put a recovery engine on the user's own Codex history for the length of a
    documentation build, which is not a trade this makes.

    `targets` maps a page name to the image it is captured into. One installation serves
    every page, so the pages show the same records at nearly the same moment. `theme` is stored in
    it, THEME unless the audit sheets ask for the other, and `design`, Soft unless the picture is of
    another design (DESIGNS_PICTURED): the window reads both in one parse before its first control.
    """
    with tempfile.TemporaryDirectory() as name:
        workspace = Path(name)
        home = scratch_installation(workspace, theme, design)
        codex, local = workspace / "codex", workspace / "LocalAppData"
        now = time.time()
        seed_window_state(home, codex, now)
        word = seed_compatibility(home, codex, local, now)
        # The window reads conversation names from Codex's own state, found through
        # CODEX_HOME - pointed here at the synthetic one, so a capture can never show,
        # or even open, the user's. It finds the Codex engine the compatibility report is
        # bound to under LOCALAPPDATA, pointed at the scratch installation's own for the
        # same reason; and the product's own overrides are unset, as for the envelope.
        # The window is told the moment these records were seeded at, and reads it instead of its
        # own clock (Soft.StillNow). Every page is then photographed at one moment rather than at
        # whatever second its capture began, so a countdown reads the same on the Overview and on
        # Pending. The records themselves are still seeded at the real clock, because the bridge
        # behind the window runs with the real one: what moves between two runs is the wall-clock
        # time printed in History, and pinning that means giving the product a clock it can be
        # told, which is not something to add for a picture.
        environment = dict(os.environ, CODEX_HOME=str(codex), LOCALAPPDATA=str(local.resolve()),
                           CODEX_AR_STILL_NOW=repr(now))
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
# `window_envelopes` builds the installation `render_window` builds (`pinned_installation`) -
# the stored settings in the pinned theme, the Dashboard's records written by the product's
# own store, the synthetic Codex home the names come from, the compatibility report the
# watcher's evaluator writes for it, the watcher's mutex held and its heartbeat written,
# recovery switched on through the bridge - and asks the bridge, through the same `serve` loop
# the window keeps open, what the window asks to draw the photographed pages.
# The canonical text of the answers is the envelope; its hash is the manifest entry.
# The wire goldens (`tests/wiregolden.py`) ask every other command of the same installation.
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


def workspace_spellings(workspace: Path) -> list:
    """The rewriting for an answer given in `workspace`: the four directories above, pinned."""
    return _spellings(("<scratch>", workspace), ("<checkout>", ROOT),
                      ("<temp>", tempfile.gettempdir()), ("<profile>", Path.home()))


def serve_lines(surface, text: str) -> str:
    """What `controlcli.serve` - the loop the window keeps open - writes for `text`, as written."""
    from codex_auto_resume import controlcli

    answer = io.StringIO()
    controlcli.serve(surface, io.StringIO(text), answer)
    return answer.getvalue()


def ask(surface, command, argument=None) -> dict:
    """One request through `serve_lines`, and its reply."""
    sent = json.dumps({"id": 1, "command": command, "argument": argument})
    return json.loads(serve_lines(surface, sent + "\n"))["reply"]


@contextmanager
def pinned_installation(workspace: Path, *, watching: bool = True, engine: bool = True,
                        design: str | None = None):
    """The installation the envelope asks, built in `workspace`, with the machine pinned.

    Yields the `Control` the bridge answers for, with recovery switched on through the bridge.
    Everything listed above is pinned for as long as it is open, and put back whole after it,
    the l10n language preference included. `tests/wiregolden.py` asks its questions of the same
    installation under the same pins, so the wire goldens and the envelope cannot disagree about
    what a scratch installation says; `watching=False` leaves the watcher's mutex free. `design` is the
    Design it stores, Soft unless a design's own picture is keyed (`window_envelopes`).
    """
    from unittest.mock import patch

    from codex_auto_resume import control

    home, codex, local = workspace / "home", workspace / "codex", workspace / "LocalAppData"
    paths = config.Paths(home)
    previous = l10n.preference()
    with ExitStack() as stack:
        stack.enter_context(frozen_registry().frozen())
        # The clock first, and before anything is written: the store stamps a row it is not given
        # a time for with `time.time`, and the History page showed those - so a picture taken at
        # 08:55 and the same picture taken at 09:10 differed by the clock alone.
        stack.enter_context(patch.object(time, "time", return_value=ENVELOPE_NOW))
        stack.enter_context(patch.object(
            time, "localtime", side_effect=lambda seconds=None: time.gmtime(
                ENVELOPE_NOW if seconds is None else seconds)))
        # The part of `scratch_installation` the bridge reads: the settings it stores. The
        # interpreter and the compiled window are not read by any answer.
        write_settings(home, design=design)
        seed_window_state(home, codex, ENVELOPE_NOW)
        # `engine=False` is the wire goldens': no engine to discover and no report about one, so
        # a live check finds none on every machine and the answers are the same everywhere.
        word = seed_compatibility(home, codex, local, ENVELOPE_NOW) if engine else "unknown"
        # Put back whole when the envelope is done, including the two removed here.
        stack.enter_context(patch.dict(os.environ, {"CODEX_HOME": str(codex),
                                                    "LOCALAPPDATA": str(local.resolve())}))
        for override in (config.ENV_HOME, config.ENV_CODEX_EXE):
            os.environ.pop(override, None)
        stack.enter_context(_registry_stand_in())
        if watching:
            stack.enter_context(_watcher_mutex_held(paths))
        write_heartbeat(paths, ENVELOPE_NOW, word)
        surface = control.Control(paths)
        # Switched on through the bridge before anything is read, as `render_window` does.
        switched = ask(surface, "enabled", {"enabled": True})
        if not switched.get("ok"):
            raise RuntimeError("the scratch installation could not be switched on: %r" % switched)
        try:
            yield surface
        finally:
            l10n.set_preference(previous)


def window_envelopes(locales, design: str | None = None) -> dict:
    """Locale -> the canonical text of what the bridge tells the window, one line per read, with the
    installation's Design stored as `design` (Soft when none is given).

    Each line is the request and its reply as the reply crossed the wire: keys in the order
    the bridge wrote them, because the window lists some objects in that order (the
    Statistics page's kinds of interruption), with only the pinned values above rewritten.
    """
    envelopes = {}
    with tempfile.TemporaryDirectory() as name:
        workspace = Path(name)
        with pinned_installation(workspace, design=design) as surface:
            spellings = workspace_spellings(workspace)
            for locale in locales:
                os.environ[l10n.ENV_LANG] = locale
                lines, replies = [], {}
                for command, argument in WINDOW_READS:
                    replies[command] = ask(surface, command, argument)
                    lines.append((command, argument, replies[command]))
                preview = preview_request((replies["describe"] or {}).get("schema") or [],
                                          (replies["settings"] or {}).get("settings") or {})
                if preview is not None:
                    lines.append(preview + (ask(surface, *preview),))
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
    inputs = {name: (window_digest() if name == "<window sources>" else input_digest(ROOT / name))
              for name in WINDOW_INPUTS}
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
    # The designs' own pictures (v0.6.10), in English: each keyed the way Soft's are, with the design it is
    # drawn in - the window by what the bridge answers an installation storing it, the panel by its markup
    # stamped with it, the popup and the card by their view and drawing with the design named. Soft's are
    # the entries above, under the names they always had.
    previous = os.environ.get(l10n.ENV_LANG)
    os.environ[l10n.ENV_LANG] = DESIGN_LOCALE
    try:
        for design in DESIGNS_PICTURED[1:]:
            inputs["<bridge envelope:%s:%s>" % (DESIGN_LOCALE, design)] = sha256(
                window_envelopes((DESIGN_LOCALE,), design)[DESIGN_LOCALE].encode("utf-8"))
            inputs["<panel render:%s:%s>" % (DESIGN_LOCALE, design)] = sha256(
                panel_html(theme=THEME, design=design).encode("utf-8"))
            inputs["<popup render:%s:%s>" % (DESIGN_LOCALE, design)] = popup_render_input(
                DESIGN_LOCALE, drawing, design)
            inputs["<card render:%s:%s>" % (DESIGN_LOCALE, design)] = card_render_input(
                DESIGN_LOCALE, card, design)
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



def window_sources() -> list:
    """The window's compile list, read from `gui/window.sources`, in compile order."""
    names = [line.split("#", 1)[0].strip()
             for line in (ROOT / "gui" / "window.sources").read_text(encoding="utf-8").splitlines()]
    # The `[group]` markers divide the list for the tests; every source is compiled.
    return [name for name in names if name and not name.startswith("[")]


def window_digest() -> str:
    """One digest over every compiled source, in compile order.

    The order is part of it: csc takes its sources in the order given, and the release is
    reproducible byte for byte, so two builds that compile the same files differently are two
    different windows.
    """
    return sha256("".join("%s\0%s\0" % (name, input_digest(ROOT / name))
                          for name in window_sources()).encode("utf-8"))

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

# The designs (v0.6.10), each pictured on the four surfaces a person meets first - the Dashboard's
# Overview, the panel, the popup and the notification card - in English and the light theme only, as
# the user asked of every picture ("대부분의 이미지는 화이트모드만 해"); the dark half of each design is held
# by the property tests instead. Soft's pictures are the set above, under the names they always had;
# every other design's are `docs/images/design-<design>-<surface>.png`, documentation only and never in
# assets/, which ships. Every design's light moves in its pictures as it does in the product - Classic's
# with its glow, Plain's dimming only. v0.6.10's Still is not pictured since it became Reduce motion
# (settings._migrate): its pictures were Soft's, held.
DESIGNS_PICTURED = ("soft", "classic", "plain")
DESIGN_SURFACES = ("dashboard", "panel", "popup", "card")
DESIGN_LOCALE = "en"


def design_picture(design: str, surface: str) -> Path:
    """Where one design's picture of one surface lives: Soft's is the picture of that surface in the set
    above, and every other design's is docs/images/design-<design>-<surface>.png."""
    if design == brand.DEFAULT_DESIGN:
        return {"dashboard": DOCS / "dashboard-overview.png", "panel": DOCS / "settings-panel.png",
                "popup": DOCS / "tray-popup.png", "card": DOCS / "notification-card.png"}[surface]
    return DOCS / ("design-%s-%s.png" % (design, surface))


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


# ------------------------------------------------------------------ the audit sheets
# `python build/make_screenshots.py --audit OUT [--before DIR] [--locale L]`, since v0.6.10. For
# developers; nothing it makes is published.
#
# Every committed picture is light, by the user's choice ("대부분의 이미지는 화이트모드만 해"), so
# nothing in the repository shows the dark half of the product - and nothing shows a change to its
# look before the change is made, which is what the user approves a design change from. An audit of
# the look needs both: the four surfaces side by side in each theme, and the same sheet from before a
# change beside the one from after it.
#
# So this draws, in each theme, the window's Overview and Pending pages, the top of the panel, the
# popup and the notification card - from the one fixture the published pictures use (`fixture`: the
# panel, the popup and the card at POPUP_NOW, the window at its capture's own moment with the same
# offsets, so relative times agree and wall-clock times need not), every surface at the scale the
# window is captured at, so one CSS pixel is the same size in all four - and lays them out, each at
# its own pixel size, on one contact sheet per theme.
# Given `--before`, a folder an earlier `--audit` wrote, it adds a sheet per theme of each surface
# before and after.
#
# Everything is written under OUT, which may not be in docs/ or assets/, and the manifest is neither
# read nor written: these are pictures to look at, not pictures to publish. The window is captured
# from a scratch installation exactly as the published pictures are (`render_window`), so the real
# installation, its registry entries and the user's Codex are never touched. It needs what a whole
# run needs: Windows, Edge and the compiled window.
AUDIT_THEMES = ("light", "dark")
AUDIT_PANEL_HEIGHT = 1000             # CSS px of the panel's top: the hero and the first cards
# (file stem, label) per picture, in rows, in the order a person meets the product.
AUDIT_ROWS = ((("window-overview", "Window - Overview"), ("window-pending", "Window - Pending")),
              (("panel", "Panel - top %d CSS px" % AUDIT_PANEL_HEIGHT), ("popup", "Popup"),
               ("card", "Notification card")))
AUDIT_SPACE = 40                      # device px round the sheet and between pictures
AUDIT_LABEL = 44                      # device px of label above each picture
AUDIT_TITLE = 56                      # device px of the sheet's title line


def audit_folder(out) -> Path:
    """OUT, resolved - or SystemExit when it is in docs/ or assets/, where published pictures live."""
    out = Path(out).resolve()
    for kept in (ROOT / "docs", ASSETS):
        kept = kept.resolve()
        if out == kept or kept in out.parents:
            raise SystemExit("--audit writes outside docs/ and assets/, never into them: %s" % out)
    return out


def audit_scale() -> float:
    """The scale the window is captured at, which every other surface is drawn at for the sheets."""
    return (system_dpi() or 96) / 96.0


def png_size(path) -> tuple:
    width, height = struct.unpack(">II", Path(path).read_bytes()[16:24])
    return width, height


def render_audit_surfaces(folder: Path, theme: str, locale: str, scale: float) -> dict:
    """Each surface in `theme`, at `scale`, into `folder`: file stem -> picture."""
    folder.mkdir(parents=True, exist_ok=True)
    files = {stem: folder / (stem + ".png") for row in AUDIT_ROWS for stem, _label in row}
    render_window({"overview": files["window-overview"], "pending": files["window-pending"]},
                  theme=theme)
    render_panel(files["panel"], theme=theme, scale=scale, height=AUDIT_PANEL_HEIGHT)
    # Still pictures: a sheet is a photograph of a page, and an animated picture on it would be caught
    # wherever it happened to be.
    render_popup(files["popup"], locale, theme=theme, scale=scale, moving=False)
    # On a ground as wide as the deeper theme's shadow, so the two sheets' cards are one size.
    render_card(files["card"], locale, theme, scale=scale, themes=AUDIT_THEMES, moving=False)
    return files


def sheet_layout(rows) -> tuple:
    """((width, height), [(label, picture, left, top, width, height)]) for `rows` of (label, picture).

    Every picture at its own pixel size - a sheet that scaled one would be auditing the scaling -
    with its label above it; rows top to bottom, pictures left to right."""
    placed, top, width = [], AUDIT_SPACE + AUDIT_TITLE, 0
    for row in rows:
        left, tallest = AUDIT_SPACE, 0
        for label, picture in row:
            w, h = png_size(picture)
            placed.append((label, Path(picture), left, top + AUDIT_LABEL, w, h))
            left += w + AUDIT_SPACE
            tallest = max(tallest, h)
        width = max(width, left)
        top += AUDIT_LABEL + tallest + AUDIT_SPACE
    return (max(width, 2 * AUDIT_SPACE), top), placed


def sheet_html(title: str, rows, theme: str, folder: Path) -> tuple:
    """(page, (width, height)): the sheet as HTML kept in `folder`, on the theme's own canvas."""
    from html import escape
    from urllib.parse import quote
    from codex_auto_resume import brand
    colours = brand.palette(theme)
    (width, height), placed = sheet_layout(rows)

    def source(picture: Path) -> str:
        try:
            return quote(os.path.relpath(picture, folder).replace(os.sep, "/"))
        except ValueError:                              # on another drive
            return picture.resolve().as_uri()

    parts = ["<!doctype html><html><head><meta charset=\"utf-8\"><title>%s</title><style>"
             "html,body{margin:0;background:%s}"
             "body{position:relative;width:%dpx;height:%dpx;color:%s;"
             "font:22px/1.25 'Segoe UI',system-ui,sans-serif}"
             ".t{position:absolute;left:%dpx;top:%dpx;font-size:28px;font-weight:600;white-space:nowrap}"
             ".l{position:absolute;color:%s;white-space:nowrap}img{position:absolute;display:block}"
             "</style></head><body><div class=\"t\">%s</div>"
             % (escape(title), colours["canvas"], width, height, colours["ink"], AUDIT_SPACE,
                AUDIT_SPACE, colours["muted"], escape(title))]
    for label, picture, left, top, w, h in placed:
        parts.append("<div class=\"l\" style=\"left:%dpx;top:%dpx\">%s</div>"
                     "<img src=\"%s\" width=\"%d\" height=\"%d\" style=\"left:%dpx;top:%dpx\" alt=\"%s\">"
                     % (left, top - AUDIT_LABEL + 6, escape(label), source(picture), w, h, left, top,
                        escape(label)))
    parts.append("</body></html>\n")
    return "".join(parts), (width, height)


def render_sheet(target: Path, title: str, rows, theme: str) -> None:
    """The sheet as `target` - a PNG, photographed by Edge at one device pixel per CSS pixel - and the
    page it was photographed from beside it, to open in a browser."""
    page, (width, height) = sheet_html(title, rows, theme, target.parent)
    html = target.with_suffix(".html")
    write_file(html, page.encode("utf-8"))
    with tempfile.TemporaryDirectory() as workspace:
        shot = Path(workspace) / "sheet.png"
        subprocess.run(
            [str(find_edge()), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=1", "--allow-file-access-from-files",
             "--window-size=%d,%d" % (width, height), "--screenshot=%s" % shot, html.as_uri()],
            check=True, capture_output=True, timeout=180, cwd=workspace)
        if not shot.is_file():
            raise SystemExit("the renderer produced no sheet")
        copy_file(shot, target)


def audit_title(theme: str, locale: str, scale: float) -> str:
    """The contact sheet's heading: what it shows, and at which moment each surface is.

    The panel, the popup and the card are drawn at POPUP_NOW. The window is not: it is seeded at the
    moment it is photographed, with the same offsets (`fixture`), so the heading says so rather than
    putting one wall-clock moment over all four.
    """
    moment = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(POPUP_NOW))
    return ("Codex Auto Resume %s - %s - %s - every surface at %gx - the panel, popup and card at %s,"
            " the window at its capture's moment, same offsets" % (config.version(), theme, locale, scale,
                                                                    moment))


def render_audit(out, before=None, locale: str = "en") -> list:
    """The audit sheets under `out`: each surface per theme, a sheet per theme, and - given `before`,
    a folder an earlier run wrote - a before-and-after sheet per theme. Returns what it wrote."""
    out = audit_folder(out)
    if before is not None:
        before = Path(before).resolve()
        if not before.is_dir():
            raise SystemExit("--before is not a folder an earlier --audit wrote: %s" % before)
    scale = audit_scale()
    written = []
    previous = os.environ.get(l10n.ENV_LANG)
    # The language every surface resolves, as a whole run sets it.
    os.environ[l10n.ENV_LANG] = locale
    try:
        for theme in AUDIT_THEMES:
            files = render_audit_surfaces(out / theme, theme, locale, scale)
            written.extend(files.values())
            title = audit_title(theme, locale, scale)
            sheet = out / ("sheet-%s.png" % theme)
            render_sheet(sheet, title, [[(label, files[stem]) for stem, label in row]
                                        for row in AUDIT_ROWS], theme)
            written.append(sheet)
            if before is None:
                continue
            pairs = [[("before - " + label, before / theme / (stem + ".png")),
                      ("after - " + label, files[stem])]
                     for row in AUDIT_ROWS for stem, label in row
                     if (before / theme / (stem + ".png")).is_file()]
            if pairs:
                pair = out / ("pair-%s.png" % theme)
                render_sheet(pair, "Before (%s) and after - %s - %s" % (before.name, theme, locale),
                             pairs, theme)
                written.append(pair)
    finally:
        if previous is None:
            os.environ.pop(l10n.ENV_LANG, None)
        else:
            os.environ[l10n.ENV_LANG] = previous
    for path in written:
        print("  %s  %s" % (path, dimensions(path)))
    return written


def audit_main(argv) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="make_screenshots.py --audit",
        description="Light and dark contact sheets of the window, the panel, the popup and the card, "
                    "for an audit of the look. Written under OUT only; never docs/, assets/ or the "
                    "manifest.")
    parser.add_argument("out", help="the folder to write into")
    parser.add_argument("--before", help="a folder an earlier --audit wrote, to set beside this one")
    parser.add_argument("--locale", default="en", choices=[str(each) for each in l10n.ENDONYMS])
    options = parser.parse_args(argv)
    render_audit(options.out, before=options.before, locale=options.locale)
    return 0


def main(argv=None) -> int:
    # Before anything is made under docs/ or assets/: the audit writes nothing there.
    if list(sys.argv[1:] if argv is None else argv)[:1] == ["--audit"]:
        return audit_main(list(sys.argv[1:] if argv is None else argv)[1:])
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
    # What each picture holds of the status light (`picture_record`), for `--breathe` and the suite.
    lights = {}

    def windowed(targets):
        for page, size in render_window(targets).items():
            lights[targets[page]] = window_record(targets[page])
            print("  %s  %s" % (targets[page].relative_to(ROOT), size))

    for locale in LOCALES:
        print("locale         : %s" % locale)
        # The engine resolves the language from the environment, so the environment is
        # what the generator sets. Nothing here passes a language into a renderer: the
        # screenshots go through exactly the path a user's machine goes through.
        os.environ[l10n.ENV_LANG] = locale
        pairs = paths_for(locale)
        panel = next(iter(pairs))
        lights[panel] = render_panel(panel)
        print("  %s  %s" % (panel.relative_to(ROOT), dimensions(panel)))
        windowed(window_targets(locale))
        copies.update(pairs)
    extras = []
    for locale in LOCALES + EXTRA_LOCALES:
        os.environ[l10n.ENV_LANG] = locale
        tag = "" if locale == "en" else "-" + locale
        popup = DOCS / ("tray-popup%s.png" % tag)
        lights[popup] = render_popup(popup, locale)
        extras.append(popup)
        print("  %s  %s" % (popup.relative_to(ROOT), dimensions(popup)))
        for theme, (asset, copy) in card_paths(locale).items():
            lights[asset or copy] = render_card(asset or copy, locale, theme)
            if asset is not None:
                copies[asset] = copy
            else:
                extras.append(copy)
            print("  %s  %s" % ((asset or copy).relative_to(ROOT), dimensions(asset or copy)))
        if locale in EXTRA_LOCALES:
            panel = DOCS / ("settings-panel%s.png" % tag)
            lights[panel] = render_panel(panel)
            extras.append(panel)
            print("  %s  %s" % (panel.relative_to(ROOT), dimensions(panel)))
            targets = {page: DOCS / ("%s%s.png" % (WINDOW_NAMES_BY_PAGE[page][1], tag))
                       for page in EXTRA_PAGES}
            windowed(targets)
            extras.extend(targets.values())
    # The designs (v0.6.10): the four surfaces a person meets first, in each design but Soft, whose
    # pictures are the ones above.
    os.environ[l10n.ENV_LANG] = DESIGN_LOCALE
    for design in DESIGNS_PICTURED[1:]:
        print("design         : %s" % design)
        target = design_picture(design, "dashboard")
        render_window({"overview": target}, design=design)
        lights[target] = window_record(target, design=design)
        target = design_picture(design, "panel")
        lights[target] = render_panel(target, design=design)
        target = design_picture(design, "popup")
        lights[target] = render_popup(target, DESIGN_LOCALE, design=design)
        target = design_picture(design, "card")
        lights[target] = render_card(target, DESIGN_LOCALE, THEME, design=design)
        for surface in DESIGN_SURFACES:
            extras.append(design_picture(design, surface))
            print("  %s  %s" % (design_picture(design, surface).relative_to(ROOT),
                                dimensions(design_picture(design, surface))))
    os.environ.pop(l10n.ENV_LANG, None)
    render_icon_motion(ICON_MOTION_APNG)
    extras.append(ICON_MOTION_APNG)
    print("  %s  %s" % (ICON_MOTION_APNG.relative_to(ROOT), dimensions(ICON_MOTION_APNG)))
    render_light_motion(LIGHT_MOTION_APNG)
    extras.append(LIGHT_MOTION_APNG)
    print("  %s  %s" % (LIGHT_MOTION_APNG.relative_to(ROOT), dimensions(LIGHT_MOTION_APNG)))

    for source, copy in copies.items():
        copy_file(source, copy)
        if source in lights:
            lights[copy] = lights[source]
        print("copied         : %s -> %s" % (source.relative_to(ROOT), copy.relative_to(ROOT)))

    def named(path):
        return str(path.relative_to(ROOT)).replace("\\", "/")

    MANIFEST.write_text(json.dumps({
        "_comment": [
            "What the committed screenshots were rendered from. Written by",
            "build/make_screenshots.py and checked by tests/test_screenshots.py, which",
            "fails when these inputs no longer match the working tree - that is, when",
            "the screenshots are stale. Regenerate them rather than editing this file.",
            "\"lights\" is what each picture holds of the status light, which",
            "`make_screenshots.py --breathe` draws moving and the suite holds it to.",
        ],
        "version": config.version(),
        "theme": THEME,
        "card_themes": list(CARD_THEMES),
        "locales": list(LOCALES),
        "documentation_locales": list(EXTRA_LOCALES),
        "designs": list(DESIGNS_PICTURED),
        "system_dpi": system_dpi(),
        "inputs": render_inputs(),
        "images": {named(path): {"sha256": sha256(path.read_bytes()), "size": dimensions(path)}
                   for path in list(copies) + list(copies.values()) + extras},
        "lights": {named(path): record for path, record in sorted(lights.items(), key=lambda item: named(item[0]))},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifest       : %s" % MANIFEST.relative_to(ROOT))
    print("then           : python build/make_screenshots.py --breathe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
