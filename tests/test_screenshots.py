"""The screenshots are generated, and stale ones fail the build.

For four releases the committed screenshots showed v0.5.2 while the manifest said
something newer. Nothing was wrong with the images; there was simply no script that made
them and no test that noticed, so "regenerate the screenshots" was a step in somebody's
head. The repository already guards every other generated artwork this way - `gui/Brand.cs`,
`icon.svg`, the `.ico`, the two logo sizes - and the screenshots were the gap.

What is checked is the *render input*, not the picture. Comparing pixels would fail on a
different display, a font update or a Windows theme, none of which mean the screenshot is
wrong. Reading the version out of a PNG is the other tempting approach and is worse: OCR
turns a hard question into a flaky one, and it would still miss a layout change that moved
a control.

Three kinds of input, and the difference matters:

* The **panel** is hashed by the markup it renders. That cannot fall behind - the version,
  the settings schema, the fields a pending row carries and the palette all reach the HTML
  wherever in the package they live - and editing a comment cannot fire it.
* The **window** is a compiled application, so the files it is compiled from are a list,
  and a list is exactly what went wrong the first time: seven files named, five that change
  the picture missed. It is as short as it can be, and a comment in `SettingsApp.cs` will
  fire this check unnecessarily. That cost is real and it is the smaller one. Everything
  the window shows arrives over the bridge, though, and that half is hashed the way the
  panel is: by what the bridge answers the window (`<bridge envelope:*>`), not by the
  fifteen package files it was until v0.6.5 - so moving code inside the package cannot fire
  it, and a changed word, row, figure, name or status cannot slip past it.
* The **popup** is hashed by the view it draws and by the definitions that draw it, pooled
  by name across its modules and the palette's, so moving one between modules cannot fire
  it and changing one does.

So this fires whenever something the picture is drawn from changed - not, as an earlier
version of this paragraph claimed, exactly when the picture stopped being true.
"""
from __future__ import annotations

import ast
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "assets" / "screenshots.json"

# The canonical asset on the left, the documentation copy on the right, per locale. One
# render, two files, copied by the generator - not two captures kept in step by hand.
#
# English keeps the plain names because the plugin card ships that pair: a catalogue entry
# has one set of screenshots and the product's own interface language there is English.
COPIES = {
    "en": {
        "assets/screenshot-panel.png": "docs/images/settings-panel.png",
        "assets/screenshot-dashboard.png": "docs/images/dashboard-overview.png",
        "assets/screenshot-pending.png": "docs/images/dashboard-pending.png",
        "assets/screenshot-settings.png": "docs/images/settings-window.png",
    },
    "ko": {
        "assets/screenshot-panel-ko.png": "docs/images/settings-panel-ko.png",
        "assets/screenshot-dashboard-ko.png": "docs/images/dashboard-overview-ko.png",
        "assets/screenshot-pending-ko.png": "docs/images/dashboard-pending-ko.png",
        "assets/screenshot-settings-ko.png": "docs/images/settings-window-ko.png",
    },
}
ALL_COPIES = {canonical: copy
              for pairs in COPIES.values() for canonical, copy in pairs.items()}

# What the plugin card ships: the panel Codex shows and the settings window. The card
# describes the version an install fetches, and that version has no Dashboard, so the
# Dashboard picture joins the card in the commit that bumps the version and not before.
# The Pending page is documentation only - a catalogue entry is not the place for a table.
CARD = ("assets/screenshot-panel.png", "assets/screenshot-settings.png")
WINDOW_SHOTS = tuple(name for pairs in COPIES.values() for name in pairs
                     if "screenshot-panel" not in name)

# Which README shows which locale's pictures. A Korean page above English screenshots is
# the documentation equivalent of the settings window that would not translate.
READMES = {"README.md": "en", "README.ko.md": "ko"}

REGENERATE = ("the screenshots no longer match the source they were rendered from; "
              "run `python build/make_screenshots.py`")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ManifestTests(unittest.TestCase):
    def setUp(self):
        if not MANIFEST.is_file():
            self.fail("assets/screenshots.json is missing; run build/make_screenshots.py")
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_the_recorded_version_is_the_current_version(self):
        from codex_auto_resume import config
        self.assertEqual(self.manifest["version"], config.version(), REGENERATE)

    def generator(self):
        import sys
        sys.path.insert(0, str(ROOT / "build"))
        try:
            import make_screenshots
            return make_screenshots
        finally:
            sys.path.pop(0)

    def test_every_render_input_is_unchanged_since_the_images_were_made(self):
        """Asked of the generator, so the two can never disagree about what an input is.

        The panel's input is the markup it renders rather than the files that produce it,
        so this recomputes it rather than hashing a path.
        """
        current = self.generator().render_inputs()
        stale = []
        for name, recorded in self.manifest["inputs"].items():
            if name not in current:
                stale.append("%s is no longer an input" % name)
            elif current[name] != recorded:
                stale.append(name)
        stale.extend("%s is a new input" % name
                     for name in current if name not in self.manifest["inputs"])
        self.assertEqual(sorted(stale), [], REGENERATE)

    def test_the_panel_input_is_the_rendered_markup_not_a_file_list(self):
        """The property that stops the list going stale again.

        Listing files missed five that visibly change the picture. Hashing what the panel
        actually renders cannot: the version, the schema, the fields a row carries and the
        palette all reach the markup, wherever in the package they live.
        """
        for locale in ("en", "ko"):
            self.assertIn("<panel render:%s>" % locale, self.manifest["inputs"],
                          "each locale's render is its own input, pinned rather than "
                          "observed - an unpinned one takes the machine's language")
        html = self.generator().panel_html()
        # The seed data the panel is rendered from. The visible strings are assembled by
        # the panel's own script in the browser, so what the markup carries is the JSON.
        for expected in ('"version": "%s"' % self.manifest["version"],
                         '"state": "waiting_reset"',
                         '"retry_timing"'):
            self.assertTrue(expected in html, "the rendered panel does not carry " + expected)

    def test_the_window_inputs_include_what_the_dashboard_is_computed_by(self):
        """The window's list went stale once already, by missing files like these.

        Its compiled half is still a list, so every C# file `make_gui.ps1` compiles into the
        window is on it, beside what the compiler is handed and the scripts that capture it.

        Its Python half is the bridge envelope. A missing file cannot happen there, but a
        missing question can - so each thing the Dashboard's figures, rows, names, headline and
        footer are computed from is changed here, one at a time, and must move the envelope.
        Each change is named for the file this list used to name for it, so nothing that list
        guarded is guarded less: it is guarded by what it computes, wherever that code lives.
        """
        generator = self.generator()
        inputs = set(generator.WINDOW_INPUTS)
        build = (ROOT / "build" / "make_gui.ps1").read_text(encoding="utf-8")
        window = re.search(r"Build -Name 'CodexAutoResumeSettings\.exe'.*?-Sources @\(([^\n]*)", build, re.S)
        compiled = {"gui/" + name for name in re.findall(r"gui\\([A-Za-z]+\.cs)", window.group(1))}
        self.assertIn("gui/Dashboard.cs", compiled)
        self.assertIn("gui/SettingsApp.cs", compiled)
        expected = compiled | {"gui/app.manifest", "assets/codex-auto-resume.ico",
                               ".codex-plugin/plugin.json", "build/capture_window.ps1",
                               "build/make_gui.ps1", "build/make_screenshots.py"}
        self.assertEqual(sorted(expected - inputs), [],
                         "the window is compiled from these, so a change to one of them "
                         "must mark the screenshots stale")
        self.assertEqual(sorted(name for name in inputs if name.startswith(("src/", "tests/"))), [],
                         "what the package computes reaches the window through the bridge, and is "
                         "hashed there; a file listed here would fire on every move")
        for locale in generator.LOCALES + generator.EXTRA_LOCALES:
            self.assertIn("<bridge envelope:%s>" % locale, self.manifest["inputs"])

        import codexsim
        from codex_auto_resume import (config, continuation, control, controlcli, l10n, machine,
                                       settings, startup, windows)
        from codex_auto_resume.source import LocalSource
        from codex_auto_resume.store import Store

        def changed(owner, name, change):
            real = getattr(owner, name)
            return patch.object(owner, name, lambda *args, **kwargs: change(real(*args, **kwargs)))

        def several(*patches):
            def enter():
                stack = ExitStack()
                for each in patches:
                    stack.enter_context(each())
                return stack
            return enter

        real_add_thread = codexsim.CodexHome.add_thread
        nowhere = Path(tempfile.gettempdir()) / "no-codex-home-for-the-envelope"
        perturbations = {
            "store.py - the Statistics figures":
                lambda: changed(Store, "statistics", lambda figures: dict(
                    figures, interruptions_detected=figures["interruptions_detected"] + 1)),
            "store.py - the pending rows":
                lambda: changed(Store, "pending", lambda rows: rows[:-1]),
            "store.py - the order of the history":
                lambda: changed(Store, "history", lambda rows: list(reversed(rows))),
            "store.py - the heartbeat behind 'checking'":
                lambda: changed(Store, "watcher_status", lambda status: dict(
                    status, last_tick_at=status["last_tick_at"] - 3600)),
            "source.py - the conversation names, via LocalSource.identity":
                lambda: changed(LocalSource, "identity", lambda found: dict(found, name="renamed")),
            "config.py - the version it reads":
                lambda: patch.object(config, "version", return_value="9.9.9"),
            "config.py - the Codex home the names are read from":
                lambda: patch.object(config, "codex_home", return_value=nowhere),
            "locales/*.json, l10n.py, interface.py - a word of the window":
                lambda: changed(l10n, "catalog", lambda words: dict(
                    words, **{"nav.pending": words["nav.pending"] + "!"})),
            "messages.py - which language the window is resolved to":
                lambda: patch.object(l10n, "resolve", return_value="ko"),
            "startup.py - the start-at-sign-in value":
                several(lambda: patch.object(startup, "current_value", return_value="registered"),
                        lambda: patch.object(startup, "belongs_to", return_value=True)),
            "control.py - what a row carries":
                lambda: changed(control, "describe_record", lambda row: dict(row, budget_resets_left=0)),
            "machine.py - which public status a row shows":
                lambda: changed(machine, "public_code", lambda code: "failed_retryable"),
            "controlcli.py - the envelope the window unpacks":
                lambda: changed(controlcli, "dispatch", lambda reply: dict(reply, extra=True)),
            "settings.py - the schema that decides which rows exist":
                lambda: changed(settings, "describe", lambda fields: fields[:-1]),
            "continuation.py, reasons.py - the Settings page's Preview":
                lambda: changed(continuation, "for_settings", lambda text: text + " Thanks."),
            "tests/codexsim.py - the synthetic Codex home the names come from":
                lambda: patch.object(codexsim.CodexHome, "add_thread",
                                     lambda sim, thread, *, name=None, **rest: real_add_thread(
                                         sim, thread, name=(name or "").upper(), **rest)),
        }
        if os.name == "nt":
            # Not acquired, so nothing holds it and the probe finds it free.
            perturbations["windows.py - the mutex that decides 'watching'"] = several(
                lambda: patch.object(windows.Mutex, "__enter__", lambda mutex: mutex),
                lambda: patch.object(windows.Mutex, "__exit__", lambda mutex, *unused: None))
        before = generator.bridge_envelope("en")
        for what, change in perturbations.items():
            with self.subTest(what), change():
                self.assertNotEqual(generator.bridge_envelope("en"), before,
                                    "%s changes the window without moving its manifest entry" % what)
        self.assertEqual(generator.bridge_envelope("en"), before)

    def test_the_committed_images_are_the_ones_the_manifest_describes(self):
        wrong = [name for name, recorded in self.manifest["images"].items()
                 if digest(ROOT / name) != recorded["sha256"]]
        self.assertEqual(wrong, [],
                         "an image was replaced without regenerating the manifest")


class CopyTests(unittest.TestCase):
    """Four files, two pictures. They are copies, so they are byte-identical."""

    def test_each_documentation_image_is_a_copy_of_its_canonical_asset(self):
        for canonical, copy in ALL_COPIES.items():
            with self.subTest(copy):
                self.assertEqual(digest(ROOT / canonical), digest(ROOT / copy),
                                 "%s is not a copy of %s; the generator makes both"
                                 % (copy, canonical))

    def test_the_plugin_card_ships_the_canonical_assets(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        declared = [name.lstrip("./") for name in manifest["interface"]["screenshots"]]
        self.assertEqual(declared, list(CARD),
                         "the plugin card and this test disagree about which images ship")

    def test_each_readme_shows_its_own_locale(self):
        # On the generated ko branch README.md holds the Korean text and shows the Korean
        # pictures, so the name-to-locale map below describes main, not that branch.
        import subprocess
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", ".github/GENERATED-BRANCH.md"],
            capture_output=True, text=True, encoding="utf-8")
        if listed.returncode == 0 and listed.stdout.strip():
            self.skipTest("the generated ko branch renames the READMEs")
        """Korean prose over English screenshots is the defect this release removed.

        On the generated `ko` branch README.ko.md *is* README.md, so only one of these
        names resolves there and opening the other would raise rather than fail.
        """
        for name, locale in READMES.items():
            if not (ROOT / name).is_file():
                continue
            body = (ROOT / name).read_text(encoding="utf-8")
            for copy in COPIES[locale].values():
                with self.subTest(name + " -> " + copy):
                    self.assertIn(copy, body, "%s does not show %s" % (name, copy))
            for other, pairs in COPIES.items():
                if other == locale:
                    continue
                for wrong in pairs.values():
                    with self.subTest(name + " must not show " + wrong):
                        self.assertNotIn(wrong, body,
                                         "%s shows the %s screenshots" % (name, other))


def read_png(path):
    """Width, height and rows of RGB tuples, from an 8-bit RGB or RGBA PNG.

    Standard library only: the tests run where Pillow is not installed. Handles exactly
    what the screenshot generator writes and refuses anything else.
    """
    import zlib
    raw = Path(path).read_bytes()
    if raw[:8] != bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]):
        raise ValueError("not a PNG")
    pos, data, width = 8, b"", None
    while pos < len(raw):
        length, kind = struct.unpack(">I4s", raw[pos:pos + 8])
        chunk = raw[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            if depth != 8 or colour not in (2, 6) or interlace:
                raise ValueError("unsupported PNG layout")
            channels = 3 if colour == 2 else 4
        elif kind == b"IDAT":
            data += chunk
        pos += 12 + length
    pixels = zlib.decompress(data)
    stride = width * channels
    rows, previous = [], bytearray(stride)
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
                p_ = left + up - corner
                pa, pb, pc = abs(p_ - left), abs(p_ - up), abs(p_ - corner)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 0xFF
        rows.append([tuple(line[x * channels:x * channels + 3]) for x in range(width)])
        previous = line
    return width, height, rows


class PixelTests(unittest.TestCase):
    """A few things that must be visible, checked on the pixels themselves.

    The v0.5.7 Korean window screenshot was published with a white square where the
    status dot belongs: the capture landed after the dot's panel was erased and before it
    was painted. Every input the freshness digest tracks was unchanged, so nothing else
    noticed. The capture now forces a synchronous repaint and the dot is double-buffered;
    this checks the result.
    """

    ACTIVE = (0x06, 0xB6, 0xD4)   # Brand.Active - the state light whenever the watcher is running
    SURFACE = (0xF6, 0xF8, 0xFB)  # Brand.Surface - the cards: the header, the pages and the footer

    def test_every_window_screenshot_shows_its_cards(self):
        """The pages are cards on the window's ground. A capture that lost them - erased and
        not yet repainted - is mostly ground, which is what this catches."""
        for name in WINDOW_SHOTS:
            width, height, rows = read_png(ROOT / name)
            surface = sum(1 for row in rows for pixel in row if pixel == self.SURFACE)
            with self.subTest(name):
                self.assertGreater(surface, width * height * 0.15,
                                   "%s shows almost no card surface" % name)

    def test_every_window_screenshot_has_its_header_and_footer_cards(self):
        """Since v0.6.4 the header and the footer are cards floating on the canvas; until then they
        were bands ruled off with a hairline, and one capture in four lost the header's rule the
        same way the dot was lost. A capture that loses a card shows canvas where it belongs."""
        for name in WINDOW_SHOTS:
            width, height, rows = read_png(ROOT / name)
            carded = [y for y, row in enumerate(rows)
                      if sum(1 for pixel in row if pixel == self.SURFACE) > width * 0.8]
            with self.subTest(name):
                self.assertTrue(any(y < height // 6 for y in carded), "no header card")
                self.assertTrue(any(y > height * 5 // 6 for y in carded), "no footer card")

    def test_every_window_screenshot_shows_the_state_dot(self):
        for name in WINDOW_SHOTS:
            width, height, rows = read_png(ROOT / name)
            header = rows[:height * 15 // 100]
            left = width // 8
            near = sum(1 for row in header for pixel in row[:left]
                       if all(abs(a - b) <= 24 for a, b in zip(pixel, self.ACTIVE)))
            with self.subTest(name):
                self.assertGreater(near, 40, "the header's state dot is missing from %s" % name)


class ContentTests(unittest.TestCase):
    """Two properties of the pictures themselves, checked without reading pixels."""

    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_the_images_are_the_size_they_were_recorded_at(self):
        for name, recorded in self.manifest["images"].items():
            raw = (ROOT / name).read_bytes()
            width, height = struct.unpack(">II", raw[16:24])
            with self.subTest(name):
                self.assertEqual("%dx%d" % (width, height), recorded["size"])

    def test_the_sample_data_carries_no_real_identifier(self):
        """The panel image is published on a plugin card, so its contents are public.

        `tests/test_repo_hygiene.py` enforces the fixture family across tracked text;
        this checks the same rule at the point the data is built, because the generator
        composes it at run time rather than storing it in a tracked file.
        """
        import re
        import sys
        sys.path.insert(0, str(ROOT / "build"))
        sys.path.insert(0, str(ROOT / "src"))
        try:
            import make_screenshots
            data = make_screenshots.sample_panel_data()
        finally:
            sys.path.pop(0)
            sys.path.pop(0)
        blob = json.dumps(data, default=str)
        synthetic = re.compile(r"^(?:0a1b2c3d-|([0-9a-f])\1{7}-|deadbeef-|12345678-)", re.I)
        found = re.findall(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                           r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", blob)
        self.assertTrue(found, "the sample should contain conversations to show")
        for value in found:
            with self.subTest(value):
                self.assertRegex(value, synthetic,
                                 "a published screenshot must not show a real conversation")
        self.assertNotIn(str(Path.home()), blob, "the sample names a real home directory")

    def test_the_window_sample_carries_no_real_identifier(self):
        """The Dashboard pictures are public too, and are rendered from records written
        at capture time. Seeded here the same way and read back whole."""
        import re
        import sqlite3
        import sys
        import tempfile
        import time
        sys.path.insert(0, str(ROOT / "build"))
        try:
            import make_screenshots
        finally:
            sys.path.pop(0)
        synthetic = re.compile(r"^(?:0a1b2c3d-|([0-9a-f])\1{7}-|deadbeef-|12345678-)", re.I)
        uuid = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                          r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
        with tempfile.TemporaryDirectory() as scratch:
            home, codex = Path(scratch) / "home", Path(scratch) / "codex"
            make_screenshots.seed_window_state(home, codex, time.time())
            # codexsim records absolute rollout paths, so the scratch root is in the data,
            # and on some machines TEMP itself has a GUID segment. That identifier names
            # this machine's temporary directory rather than a conversation, and it is not
            # drawn, so it is set aside instead of failing a check about the sample. The
            # resolved spelling too, in case a short name in TEMP is expanded on the way in.
            own = {value.lower() for text in (scratch, str(Path(scratch).resolve()))
                   for value in uuid.findall(text)}
            # Each column value as it was stored. A repr'd row doubles every backslash in a
            # Windows path, so the text searched would not be the text that was written.
            values = []
            for database in list(home.rglob("*.sqlite*")) + list(codex.rglob("*.sqlite")):
                if database.suffix != ".sqlite":
                    continue
                with sqlite3.connect(database) as connection:
                    for (table,) in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                        for row in connection.execute(
                                'SELECT * FROM "%s"' % table).fetchall():
                            values.extend(str(value) for value in row)
                connection.close()
        found = [value for text in values for value in uuid.findall(text)
                 if value.lower() not in own]
        self.assertTrue(found, "the sample should contain conversations to show")
        for value in found:
            with self.subTest(value):
                self.assertRegex(value, synthetic,
                                 "a published screenshot must not show a real conversation")
        for name in make_screenshots.WINDOW_NAMES:
            self.assertTrue(name.startswith("example-"), name)

    def test_every_surface_is_drawn_in_the_pinned_theme(self):
        """The window resolves the stored Theme when it starts, and the default - Use system
        setting - follows Windows' app mode. A scratch installation that stored the defaults was
        photographed dark on a machine in dark mode, beside light panel and popup pictures, under a
        manifest that said light. Passing `--theme` is no way round it: the window's first settings
        read reopens it in the stored theme. So the theme is stored, for every surface alike."""
        import inspect
        import sys
        import tempfile
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / "build"))
        sys.path.insert(0, str(ROOT / "src"))
        try:
            import make_screenshots
            from codex_auto_resume import settings as policy
            from codex_auto_resume import tray_popup
        finally:
            sys.path.pop(0)
            sys.path.pop(0)
        theme = make_screenshots.THEME
        self.assertEqual(theme, self.manifest["theme"])
        self.assertIn(theme, ("light", "dark"), "a picture cannot follow the machine it is made on")
        # The window: what its scratch installation stores, read back the way the product reads it.
        with tempfile.TemporaryDirectory() as scratch:
            home = Path(scratch)
            make_screenshots.write_settings(home)
            stored = policy.load(home / "config" / "settings.json")
            raw = json.loads((home / "config" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual((stored["theme"], raw["theme"]), (theme, theme))
        self.assertEqual({k: v for k, v in stored.items() if k != "theme"},
                         {k: v for k, v in policy.defaults().items() if k != "theme"},
                         "otherwise the pictures show the defaults")
        self.assertIn("write_settings(home)", inspect.getsource(make_screenshots.scratch_installation))
        self.assertNotIn("policy.defaults()", inspect.getsource(make_screenshots.scratch_installation))
        self.assertNotIn("--theme", inspect.getsource(make_screenshots.render_window))
        # The panel: served pinned, and its sample's own Theme control says the same.
        self.assertEqual(make_screenshots.sample_panel_data()["settings"]["theme"], theme)
        self.assertIn('data-theme="%s" data-theme-pinned=""' % theme, make_screenshots.panel_html(theme=theme))
        # The popup: its renderer is told, rather than trusted to default to it.
        seen = []

        class Renderer:
            theme = "unset"

            def layout(self, view, scale, locale):
                seen.append(self.theme)
                return {"size": (1, 1)}

            def draw(self, view, plan, frame=None):
                return type("Canvas", (), {"pixels": lambda canvas: bytes(4)})()

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as scratch, patch.object(tray_popup, "Renderer", Renderer):
            make_screenshots.render_popup(Path(scratch) / "popup.png", "en")
        self.assertEqual(seen, [theme])

    def test_the_sample_version_comes_from_the_manifest(self):
        """The whole point: change plugin.json and the picture's version follows."""
        import sys
        sys.path.insert(0, str(ROOT / "build"))
        sys.path.insert(0, str(ROOT / "src"))
        try:
            import make_screenshots
            from codex_auto_resume import config
            self.assertEqual(make_screenshots.sample_panel_data()["status"]["version"],
                             config.version())
        finally:
            sys.path.pop(0)
            sys.path.pop(0)


def generator():
    """`build/make_screenshots.py`, imported the way the manifest tests import it."""
    sys.path.insert(0, str(ROOT / "build"))
    try:
        import make_screenshots
        return make_screenshots
    finally:
        sys.path.pop(0)


def strings_in(value):
    """Every string in a parsed JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


class EnvelopeTests(unittest.TestCase):
    """What the window is shown, as a manifest input: the same tree gives the same text anywhere.

    The envelope stands in the manifest for fifteen of the package's files, so it has to be as
    reproducible as their bytes were: recorded on one machine, recomputed on a CI runner in
    another language, time zone, code page and temporary directory, on three Pythons. The
    generator pins the clock, the paths, the process id and the machine's answers; these check
    that the pins hold, and that nothing it does can reach the real registry.
    """

    @classmethod
    def setUpClass(cls):
        cls.generator = generator()
        cls.envelope = cls.generator.bridge_envelope("en")
        cls.lines = [json.loads(line) for line in cls.envelope.splitlines()]

    def reply(self, command):
        return next(line["reply"] for line in self.lines if line["command"] == command)

    def test_the_envelope_is_the_same_from_another_root_temp_profile_and_clock(self):
        """A second scratch installation, under a temporary directory whose name has a space and
        non-ASCII letters, another profile directory, the product's own overrides set to values
        that would change the answer if anything read them, and the real clock a year on."""
        import time
        with tempfile.TemporaryDirectory() as scratch:
            temp, profile = Path(scratch) / "다른 임시 é", Path(scratch) / "profile ü"
            temp.mkdir()
            profile.mkdir()
            elsewhere = {"TEMP": str(temp), "TMP": str(temp), "USERPROFILE": str(profile),
                         "CODEX_AUTO_RESUME_LANG": "fr",
                         "CODEX_AUTO_RESUME_HOME": str(Path(scratch) / "another-home"),
                         "CODEX_AUTO_RESUME_CODEX_EXE": str(Path(scratch) / "codex.exe"),
                         "CODEX_HOME": str(Path(scratch) / "another-codex")}
            with patch.dict(os.environ, elsewhere), patch.object(tempfile, "tempdir", str(temp)), \
                    patch.object(time, "time", return_value=time.time() + 365 * 86400):
                again = self.generator.bridge_envelope("en")
        self.assertEqual(again, self.envelope)

    def test_the_envelope_names_no_path_of_this_machine(self):
        spellings = set()
        for directory in (ROOT, Path(tempfile.gettempdir()), Path.home()):
            for path in (directory, directory.resolve()):
                spellings.update((str(path).lower(), path.as_posix().lower()))
        texts = [text.lower() for line in self.lines for text in strings_in(line)]
        for spelling in spellings:
            with self.subTest(spelling):
                self.assertEqual([text for text in texts if spelling in text], [])

    def test_a_path_in_an_answer_is_written_as_its_placeholder(self):
        """None of today's answers carries a path; the day one does, it is rewritten, not hashed."""
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            spellings = self.generator._spellings(("<scratch>", root / "work"), ("<temp>", root))
            answer = {"log": str(root / "work" / "home" / "auto-resume.log"),
                      "other": (root / "elsewhere").as_posix().upper(), "count": 3,
                      "rows": [str(root / "work")]}
            self.assertEqual(self.generator._canonical(answer, spellings),
                             {"log": "<scratch>" + os.sep + "home" + os.sep + "auto-resume.log",
                              "other": "<temp>/ELSEWHERE", "count": 3, "rows": ["<scratch>"]})

    def test_the_pinned_values_are_the_ones_the_answers_carry(self):
        status = self.reply("status")["status"]
        self.assertEqual(status["watcher"]["pid"], self.generator.ENVELOPE_PID)
        self.assertEqual(status["watcher"]["last_tick_at"], self.generator.ENVELOPE_NOW - 1)
        # What the capture shows: a watcher running and checking, recovery on, not registered.
        self.assertEqual((status["watcher_running"], status["watcher"]["ticking"], status["enabled"],
                          status["startup_enabled"]), (True, True, True, False))
        self.assertEqual(self.reply("strings")["language"], "en")
        self.assertEqual(self.reply("strings")["system_language"], "en",
                         "the language Windows asks for is the locale being rendered, not this machine's")
        names = {row["name"] for row in self.reply("dashboard")["pending"]}
        self.assertEqual(names, {"example-project", "example-service"},
                         "the names come from the synthetic Codex home, never the user's")

    def test_the_reads_are_the_ones_the_window_makes(self):
        """Only questions the window's own code asks, and each photographed page's."""
        window = "".join((ROOT / "gui" / name).read_text(encoding="utf-8")
                         for name in ("Dashboard.cs", "SettingsApp.cs"))
        asked = set(re.findall(r'\b(?:Call|CallAsync|CallOnce|Send)\("([a-z-]+)"', window))
        commands = [line["command"] for line in self.lines]
        self.assertEqual(commands, ["strings", "describe", "settings", "status", "dashboard",
                                    "statistics", "compatibility", "preview-continuation"])
        self.assertEqual(sorted(set(commands) - asked), [])
        # The Statistics page opens on the first period its list offers.
        first = re.search(r'period\.Items\.Add\(new Choice\("(\d*)"', window).group(1)
        self.assertEqual(dict(self.generator.WINDOW_READS)["statistics"], {"days": int(first)})
        # The Preview is for the first reason of the schema, which is the Settings page's first.
        preview = next(line for line in self.lines if line["command"] == "preview-continuation")
        first_reason = next(field["category"] for field in self.reply("describe")["schema"]
                            if field["name"].startswith("custom_message_") and field.get("category"))
        self.assertEqual(preview["argument"]["category"], first_reason)
        self.assertEqual(preview["reply"]["result"]["category"], first_reason)

    def test_the_registry_reads_as_unregistered_and_refuses_every_write(self):
        """Checked on the stand-in itself. Nothing here calls a function that could write the real
        registry if the stand-in were not in place."""
        stand_in = self.generator._NoRegistration()
        with self.assertRaises(FileNotFoundError):
            stand_in.OpenKey(stand_in.HKEY_CURRENT_USER, "Software", 0, stand_in.KEY_READ)
        for writer in ("CreateKeyEx", "CreateKey", "SetValueEx", "SetValue", "DeleteValue", "DeleteKey"):
            with self.subTest(writer), self.assertRaises(self.generator.RegistryWriteRefused):
                getattr(stand_in, writer)(stand_in.HKEY_CURRENT_USER, "Software")
        self.assertFalse(issubclass(self.generator.RegistryWriteRefused, Exception),
                         "the bridge turns an Exception into a polite refusal, which would hide it")
        from codex_auto_resume import startup
        with self.generator._registry_stand_in():
            import winreg
            self.assertIs(type(winreg), self.generator._NoRegistration)
            if os.name == "nt":
                self.assertIs(type(startup._winreg()), self.generator._NoRegistration)
                self.assertIsNone(startup.current_value())
        self.assertIsNot(type(sys.modules.get("winreg")), self.generator._NoRegistration)


class PopupDrawingTests(unittest.TestCase):
    """What draws the popup, keyed so that a move is invisible and an edit is not.

    v0.6.5 moves the popup into `ui/popup/` and the palette into `ui/brand/`. The popup's
    manifest entry hashes the definitions of those modules pooled by name rather than their
    files, so the moves leave it where it is while any real change still moves it.
    """

    POPUP = (
        '"""The popup."""\n'
        "import os\n"
        "from . import brand\n"
        "\n"
        "WIDTH = 320  # the card\n"
        "\n"
        "def layout(view):\n"
        '    """Where everything goes."""\n'
        "    from .brand import ACCENT\n"
        "    return {'size': (WIDTH, 40), 'accent': ACCENT, 'rows': len(view)}\n"
        "\n"
        "class Renderer:\n"
        "    def draw(self, plan):\n"
        "        return [brand.SURFACE] * plan['rows']\n"
        "\n"
        "if os.name == 'nt':\n"
        "    import ctypes\n"
        "    class RECT(ctypes.Structure):\n"
        "        _fields_ = [('left', ctypes.c_long)]\n"
        "    def monitor():\n"
        "        return RECT()\n")
    BRAND = ('"""The palette."""\n'
             "ACCENT = '#06B6D4'\n"
             "SURFACE = '#F6F8FB'\n")

    @classmethod
    def setUpClass(cls):
        cls.generator = generator()

    def digest(self, files):
        with tempfile.TemporaryDirectory() as root:
            for name, text in files.items():
                path = Path(root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return self.generator.code_digest(self.generator.popup_code_files(root))

    def test_the_patterns_cover_the_popup_the_palette_and_the_packages_they_move_into(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("tray_popup.py", "brand.py", "ui/popup/layout.py", "ui/popup/win/rect.py",
                         "ui/brand/tokens.py", "ui/tray/icon.py", "tray.py", "notice_card.py"):
                (Path(root) / name).parent.mkdir(parents=True, exist_ok=True)
                (Path(root) / name).write_text("X = 1\n", encoding="utf-8")
            covered = [path.relative_to(root).as_posix()
                       for path in self.generator.popup_code_files(root)]
        self.assertEqual(covered, ["brand.py", "tray_popup.py", "ui/brand/tokens.py",
                                   "ui/popup/layout.py", "ui/popup/win/rect.py"])

    def test_today_the_patterns_find_every_tracked_popup_and_palette_module(self):
        package = ROOT / "src" / "codex_auto_resume"
        found = [path.relative_to(package).as_posix()
                 for path in self.generator.popup_code_files(package)]
        tracked = sorted(srcscan.relative(path).split("/", 1)[1] for path in srcscan.package_files()
                         if re.fullmatch(r"codex_auto_resume/(tray_popup|brand|ui/(popup|brand)/.+)\.py",
                                         srcscan.relative(path)))
        self.assertEqual(found, tracked)
        self.assertIn("tray_popup.py", found)
        self.assertIn("brand.py", found)

    def test_moving_definitions_between_modules_leaves_the_digest(self):
        before = self.digest({"tray_popup.py": self.POPUP, "brand.py": self.BRAND})
        # layout() and half of the guarded block into ui/popup/, a token into ui/brand/, each
        # with the imports that follow it, and the order of what is left changed.
        moved = {
            "tray_popup.py": (
                "import os\n"
                "from . import brand\n"
                "from .ui.popup.layout import WIDTH, layout\n"
                "class Renderer:\n"
                "    def draw(self, plan):\n"
                "        return [brand.SURFACE] * plan['rows']\n"
                "if os.name == 'nt':\n"
                "    from .ui.popup.win import RECT\n"
                "    def monitor():\n"
                "        return RECT()\n"),
            "brand.py": "from .ui.brand.tokens import ACCENT\nSURFACE = '#F6F8FB'  # moved later\n",
            "ui/brand/tokens.py": '"""Tokens."""\nACCENT = \'#06B6D4\'\n',
            "ui/popup/layout.py": (
                "WIDTH = 320\n"
                "def layout(view):\n"
                '    """Where everything goes, now in its own module."""\n'
                "    from ..brand.tokens import ACCENT\n"
                "    return {'size': (WIDTH, 40), 'accent': ACCENT, 'rows': len(view)}\n"),
            "ui/popup/win.py": (
                "import ctypes\n"
                "import os\n"
                "if os.name == 'nt':\n"
                "    class RECT(ctypes.Structure):\n"
                "        _fields_ = [('left', ctypes.c_long)]\n"),
        }
        self.assertEqual(self.digest(moved), before)

    def test_a_change_to_drawing_code_or_a_token_moves_the_digest(self):
        before = self.digest({"tray_popup.py": self.POPUP, "brand.py": self.BRAND})
        changes = {
            "a token": ("brand.py", "#06B6D4", "#0891B2"),
            "a number in the layout": ("tray_popup.py", "(WIDTH, 40)", "(WIDTH, 44)"),
            "a line of drawing code": ("tray_popup.py", "* plan['rows']", "* (plan['rows'] + 1)"),
            "a guard": ("tray_popup.py", "os.name == 'nt'", "os.name != 'nt'"),
            "a new definition": ("brand.py", "SURFACE =", "BORDER = '#E2E8F0'\nSURFACE ="),
            "a renamed definition": ("tray_popup.py", "def monitor", "def primary_monitor"),
        }
        for what, (name, old, new) in changes.items():
            files = {"tray_popup.py": self.POPUP, "brand.py": self.BRAND}
            self.assertIn(old, files[name])
            files[name] = files[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertNotEqual(self.digest(files), before, what + " did not move the digest")

    def test_moving_a_real_definition_of_the_palette_leaves_the_digest(self):
        """The same on the real modules: the palette's last function moved into `ui/brand/` and
        imported back leaves it; one real colour token changed does not."""
        package = ROOT / "src" / "codex_auto_resume"
        popup = (package / "tray_popup.py").read_text(encoding="utf-8")
        brand = (package / "brand.py").read_text(encoding="utf-8")
        before = self.digest({"tray_popup.py": popup, "brand.py": brand})
        tree = ast.parse(brand)
        last = [node for node in tree.body if isinstance(node, ast.FunctionDef)][-1]
        lines = brand.splitlines(keepends=True)
        start = min([last.lineno] + [decorator.lineno for decorator in last.decorator_list]) - 1
        cut = "".join(lines[start:last.end_lineno])
        left = "".join(lines[:start] + lines[last.end_lineno:]) + "from .ui.brand.moved import %s\n" % last.name
        moved = {"tray_popup.py": popup, "brand.py": left,
                 "ui/brand/moved.py": "from ...brand import *  # noqa\n\n" + cut}
        self.assertEqual(self.digest(moved), before)
        token = next(node for node in tree.body if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                     and re.fullmatch(r"#[0-9A-Fa-f]{6}", node.value.value))
        lines[token.lineno - 1] = lines[token.lineno - 1].replace(token.value.value, "#123456", 1)
        recoloured = "".join(lines)
        self.assertNotEqual(recoloured, brand)
        self.assertNotEqual(self.digest({"tray_popup.py": popup, "brand.py": recoloured}), before)

    def test_the_spelling_of_a_tree_does_not_depend_on_the_python(self):
        """3.13 changed `ast.dump`'s default to leave empty fields out; the digest leaves them out
        on every version, so a field a later Python adds with an empty default changes nothing."""
        spelled = self.generator._canonical_ast(ast.parse("def f(a, *, b=1):\n    return a\n"))
        self.assertNotIn("=[]", spelled)
        self.assertNotIn("=None", spelled)
        self.assertNotIn("lineno", spelled)

if __name__ == "__main__":
    unittest.main()
