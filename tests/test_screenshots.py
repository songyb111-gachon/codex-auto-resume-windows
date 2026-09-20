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
  by name across its modules and the palette's - and across the definitions they import by
  name from anywhere else, wherever those live - so moving one between modules cannot fire
  it and changing one does.
* The **notification card** is hashed the same way: by what it says, built by the watcher's
  own builder, and by the definitions that draw it - its own modules, wherever v0.6.6 moves
  them, pooled with the popup's renderer and palette, which paint it.

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
# The notification card (v0.6.5), light and dark, drawn off-screen by the card's own code. Kept
# apart from COPIES, whose window pictures the pixel checks below read for the window's cards
# and its state dot.
CARD_COPIES = {
    "en": {
        "assets/screenshot-notification.png": "docs/images/notification-card.png",
        "assets/screenshot-notification-dark.png": "docs/images/notification-card-dark.png",
    },
    "ko": {
        "assets/screenshot-notification-ko.png": "docs/images/notification-card-ko.png",
        "assets/screenshot-notification-dark-ko.png": "docs/images/notification-card-dark-ko.png",
    },
}
ALL_COPIES = {canonical: copy for mapping in (COPIES, CARD_COPIES)
              for pairs in mapping.values() for canonical, copy in pairs.items()}

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
        from codex_auto_resume import (compatio, config, continuation, control, controlcli, l10n,
                                       machine, settings, startup, windows)
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
            "compatio.py - the local checks behind the Diagnostics card":
                lambda: changed(compatio, "source_checks", lambda checks: dict(checks, queue_schema="FAIL")),
            "data/codex_compat.json - the registry data in force":
                lambda: patch.object(compatio, "load_bundled", return_value=(None, "missing")),
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
            for copy in list(COPIES[locale].values()) + list(CARD_COPIES[locale].values()):
                with self.subTest(name + " -> " + copy):
                    self.assertIn(copy, body, "%s does not show %s" % (name, copy))
            for other in COPIES:
                if other == locale:
                    continue
                for wrong in list(COPIES[other].values()) + list(CARD_COPIES[other].values()):
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
            width, height = struct.unpack("<HH", raw[6:10]) if raw[:6] == b"GIF89a" else struct.unpack(">II", raw[16:24])
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

    def test_the_diagnostics_card_reads_the_report_the_watcher_writes(self):
        """Not "not checked yet", and no word the product cannot say. The Diagnostics card reads the
        report the watcher's own evaluator writes for the synthetic Codex home, still bound to the
        engine on disk; the status line says the word that evaluation gave; and the panel and the
        popup say the same, because they are drawn from the same state."""
        from codex_auto_resume import compat, compatio
        generator = self.generator
        view = self.reply("compatibility")["compatibility"]
        watcher = self.reply("status")["status"]["watcher"]
        self.assertEqual((view["status"], view["live"]), ("ok", False), "the card would say why it cannot be used")
        self.assertEqual(view["checked_at"], generator.ENVELOPE_NOW - 40)
        self.assertEqual(view["engine"], {"found": True, "version": generator.CODEX_VERSION})
        bundled, _state = compatio.load_bundled()
        self.assertEqual((view["data"]["source"], view["data"]["bundled_sequence"], view["data"]["cache"]),
                         ("bundled", bundled["sequence"], "absent"))
        # The word the gate reads for this build with the bundled data - "verified" only if that
        # data verifies it - in the report, the heartbeat and the popup alike.
        self.assertEqual(view["overall"], generator.engine_word())
        self.assertEqual(view["acting"], generator.engine_word())
        self.assertEqual(watcher["engine_state"], generator.engine_word())
        self.assertEqual(generator.popup_status()["watcher"]["engine_state"], generator.engine_word())
        # Every local check passed: the synthetic home has what a Codex that has been used has,
        # the folder of conversation locks included, so the picture shows what such a machine shows.
        self.assertEqual(sorted(name for name, result in view["checks"].items() if result != "PASS"), [])
        # Each part the card lists, with its state: the bundled data's entry for this build shows.
        listed = {name: entry for name, entry in view["capabilities"].items()
                  if entry["reason"] != "not_implemented"}
        self.assertGreater(len(listed), 1)
        restricted, _source, _why = compat.evidence_for("not_loaded_recovery", generator.CODEX_VERSION,
                                                        [("bundled", bundled, True)])
        if restricted == compat.INCOMPATIBLE:
            self.assertEqual((listed["not_loaded_recovery"]["state"], listed["not_loaded_recovery"]["reason"]),
                             (compat.INCOMPATIBLE, "registry_incompatible"))
        # The panel's card: the MCP server's summary of the same report, at the same moment.
        panel = generator.sample_panel_data()["status"]["watcher"]
        self.assertEqual(panel["compatibility"], compat.mcp_view(view))
        self.assertEqual(panel["engine_state"], watcher["engine_state"])

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

    v0.6.5 moves the popup into `ui/popup/`, the palette into `ui/brand/`, and the Win32
    structures and DLL cache the popup shares with the icon into `win/dll.py`. The popup's
    manifest entry hashes the definitions of its modules pooled by name rather than their
    files, and follows what they import by name to wherever it is defined, so the moves
    leave it where it is while any real change still moves it.
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
            return self.generator.popup_drawing(root)

    @staticmethod
    def cut(text, *names):
        """`text` without its top-level statements that bind `names`, and those statements."""
        tree = ast.parse(text)
        lines = text.splitlines(keepends=True)
        spans = []
        for node in tree.body:
            bound = {node.name} if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else {
                target.id for target in getattr(node, "targets", []) if isinstance(target, ast.Name)}
            if bound & set(names):
                start = min([node.lineno] + [item.lineno for item in getattr(node, "decorator_list", [])])
                spans.append((start - 1, node.end_lineno))
        assert len(spans) == len(names), (names, spans)
        kept = [line for number, line in enumerate(lines) if not any(a <= number < b for a, b in spans)]
        taken = ["".join(lines[a:b]) + "\n\n" for a, b in spans]
        return "".join(kept), "".join(taken)

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

    TRAY = ('"""The icon."""\n'
            "import ctypes\n"
            "\n"
            "class GUID(ctypes.Structure):\n"
            "    _fields_ = [('Data1', ctypes.c_ulong)]\n"
            "\n"
            "def countdown(seconds):\n"
            "    return '%ds' % seconds\n"
            "\n"
            "def tooltip(snapshot):\n"
            "    return 'Codex Auto Resume'\n")
    POPUP_WITH_THE_ICON = (
        "import ctypes\n"
        "from . import brand\n"
        "from .tray import GUID, countdown\n"
        "\n"
        "_DLLS = {}\n"
        "\n"
        "def _dll(name):\n"
        "    if name not in _DLLS:\n"
        "        _DLLS[name] = ctypes.WinDLL(name)\n"
        "    return _DLLS[name]\n"
        "\n"
        "def label(seconds):\n"
        "    return countdown(seconds) + brand.SURFACE\n"
        "\n"
        "def register():\n"
        "    return _dll('user32'), GUID()\n")

    def test_what_the_popup_imports_by_name_is_followed_wherever_it_lives(self):
        """`win/dll.py` is not one of the popup's modules, and should not be: it will hold the
        icon's and the card's structures too. What the popup takes from it by name is in the
        key all the same, so moving the popup's DLL cache there, or the icon's structure,
        leaves the key; and a change to what the popup takes from the icon moves it."""
        files = {"tray_popup.py": self.POPUP_WITH_THE_ICON, "brand.py": self.BRAND, "tray.py": self.TRAY}
        before = self.digest(files)
        popup, cache = self.cut(self.POPUP_WITH_THE_ICON, "_DLLS", "_dll")
        tray, guid = self.cut(self.TRAY, "GUID")
        layouts = {}
        for importer in ("tray", "win.dll"):            # re-exported by the icon, or imported directly
            layouts[importer] = {
                "tray_popup.py": popup.replace("from .tray import GUID, countdown",
                                               "from .%s import GUID\nfrom .tray import countdown\n"
                                               "from .win.dll import _dll" % importer),
                "brand.py": self.BRAND,
                "tray.py": "from .win.dll import GUID\n" + tray,
                "win/__init__.py": "",
                "win/dll.py": "import ctypes\n\n" + guid + cache,
            }
            with self.subTest(importer):
                self.assertEqual(self.digest(layouts[importer]), before)
        moved = layouts["win.dll"]
        for what, (name, old, new) in {
                "the countdown the popup shows": ("tray.py", "'%ds' % seconds", "'%d s' % seconds"),
                "the cache the popup's DLL handle fills": ("win/dll.py", "_DLLS = {}", "_DLLS = dict()"),
                "a structure the popup registers": ("win/dll.py", "c_ulong", "c_uint")}.items():
            changed = dict(moved)
            self.assertIn(old, changed[name])
            changed[name] = changed[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertNotEqual(self.digest(changed), before, what + " did not move the digest")
        changed = dict(moved, **{"tray.py": moved["tray.py"].replace("'Codex Auto Resume'", "'Codex'")})
        self.assertNotEqual(changed["tray.py"], moved["tray.py"])
        self.assertEqual(self.digest(changed), before, "the icon's own tooltip is not the popup's drawing")

    def test_folding_the_real_dll_caches_and_structures_into_win_leaves_the_digest(self):
        """Step 9 on the real modules: the popup's private DLL cache and the Win32 structures
        it takes from the icon move into `win/dll.py`, each importer taking them back by name.
        The key is the same; a change to the icon's real countdown is not."""
        package = ROOT / "src" / "codex_auto_resume"
        real = {name: (package / name).read_text(encoding="utf-8") for name in ("tray_popup.py", "brand.py", "tray.py")}
        imported = [entry.split(" | ")[0] for entry in self.generator.imported_definitions(
            package, self.generator.popup_code_files(package))]
        self.assertIn("countdown", imported)
        self.assertIn("GUID", imported)
        before = self.digest(real)
        popup, cache = self.cut(real["tray_popup.py"], "_DLLS", "_dll")
        tray, structures = self.cut(real["tray.py"], "LRESULT", "WNDPROC", "WNDCLASSW", "GUID")
        imports = "from .tray import GUID, LRESULT, WNDCLASSW, WNDPROC"
        self.assertIn(imports, popup)
        moved = {
            "tray_popup.py": popup.replace(imports, imports.replace(".tray", ".win.dll")) + "\nfrom .win.dll import _dll\n",
            "brand.py": real["brand.py"],
            "tray.py": tray + "\nfrom .win.dll import GUID, LRESULT, WNDCLASSW, WNDPROC\n",
            "win/__init__.py": "",
            "win/dll.py": "import ctypes as C\nfrom ctypes import wintypes as W\n\n" + structures + cache,
        }
        self.assertEqual(self.digest(moved), before)
        recounted = dict(real, **{"tray.py": real["tray.py"].replace('"%ds" % secs', '"%d s" % secs', 1)})
        self.assertNotEqual(recounted["tray.py"], real["tray.py"])
        self.assertNotEqual(self.digest(recounted), before)

    def test_the_spelling_of_a_tree_does_not_depend_on_the_python(self):
        """3.13 changed `ast.dump`'s default to leave empty fields out; the digest leaves them out
        on every version, so a field a later Python adds with an empty default changes nothing."""
        spelled = self.generator._canonical_ast(ast.parse("def f(a, *, b=1):\n    return a\n"))
        self.assertNotIn("=[]", spelled)
        self.assertNotIn("=None", spelled)
        self.assertNotIn("lineno", spelled)


class CardPictureTests(unittest.TestCase):
    """The notification card's pictures, pinned the way the popup's are.

    Until v0.6.5 the README's notification was a capture of a Windows toast taken before Open
    Dashboard existed, and nothing pinned it, so nothing noticed that it no longer showed what
    the product does. The card's pictures are keyed by what the card says - built by the
    watcher's own builder from the catalogs - and by a digest of the definitions that draw it,
    pooled by name across its modules, the package they move into and the popup's renderer and
    palette it is painted with.
    """

    SYNTHETIC = re.compile(r"^(?:0a1b2c3d-|([0-9a-f])\1{7}-|deadbeef-|12345678-)", re.I)

    @classmethod
    def setUpClass(cls):
        cls.generator = generator()
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def locales(self):
        return self.generator.LOCALES + self.generator.EXTRA_LOCALES

    def test_every_card_picture_is_pinned_under_its_locales_entry(self):
        expected = set()
        for locale in self.locales():
            with self.subTest(locale=locale):
                self.assertIn("<card render:%s>" % locale, self.manifest["inputs"])
            for asset, copy in self.generator.card_paths(locale).values():
                expected.update(path.relative_to(ROOT).as_posix() for path in (asset, copy) if path)
        for name in sorted(expected):
            with self.subTest(name):
                self.assertIn(name, self.manifest["images"], "a card picture the manifest does not pin")
        # Both themes in both README languages, each an asset with its documentation copy.
        for locale, pairs in CARD_COPIES.items():
            made = {asset.relative_to(ROOT).as_posix(): copy.relative_to(ROOT).as_posix()
                    for asset, copy in self.generator.card_paths(locale).values()}
            self.assertEqual(made, pairs)
        # No picture of a notification is left outside the manifest, as notification.png was.
        pictured = {path.relative_to(ROOT).as_posix() for folder in ("assets", "docs/images")
                    for path in (ROOT / folder).glob("*notification*.png")}
        self.assertEqual(pictured, expected)

    def test_the_card_says_what_the_watcher_would_say(self):
        """The watcher's builder, the catalogs' words, the sample's conversation - never a real one."""
        import time
        from codex_auto_resume import l10n, notice_card, reasons
        g = self.generator
        at = time.strftime("%H:%M", time.gmtime(g.CARD_RESET_AT))
        for locale in self.locales():
            words = l10n.catalog(locale)
            view = g.card_view(locale)
            with self.subTest(locale=locale):
                self.assertEqual(view["locale"], locale)
                self.assertEqual(view["title"], g.WINDOW_NAMES[0])
                self.assertEqual(view["line"], words["msg.toast_usage_at"].replace("{time}", at))
                self.assertEqual(view["chip"], l10n.text(reasons.label_key("usage_limit"), locale))
                self.assertEqual(view["origin"], words["msg.toast_thread"].replace("{uuid}", g.WINDOW_THREADS[0]))
                self.assertEqual([(action["label"], action["primary"]) for action in view["actions"]],
                                 [(words["msg.toast_button_cancel"], False), (words["msg.toast_button_open"], True)])
                drawn = " ".join(notice_card.texts(view))
                self.assertNotIn(g.CARD_INTERRUPTION, drawn, "the capability id stays in the button's URI")
                for value in re.findall(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                                        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", drawn):
                    self.assertRegex(value, self.SYNTHETIC, "a published picture must not show a real conversation")
        # The same conversation, resetting at the same moment, as the popup's usage-limit row.
        row = next(row for row in g.popup_rows() if row["category"] == "usage_limit")
        self.assertEqual((row["thread_id"], row["name"], row["reset_at"]),
                         (g.WINDOW_THREADS[0], g.WINDOW_NAMES[0], g.CARD_RESET_AT))

    def test_the_card_entry_is_the_same_on_any_machine(self):
        """The toast writes the reset in local time and speaks the stored language; neither the
        machine's clock, its language nor a language already chosen in the process moves it."""
        import time
        from codex_auto_resume import l10n, notify
        before = self.generator.card_render_input("en")
        preference, local_time = l10n.preference(), notify._local_time
        elsewhere = lambda seconds=None: time.gmtime((time.time() if seconds is None else seconds) + 9 * 3600)
        with patch.dict(os.environ, {l10n.ENV_LANG: "ja"}), patch.object(time, "localtime", elsewhere):
            l10n.set_preference("de")
            try:
                self.assertEqual(self.generator.card_render_input("en"), before)
            finally:
                l10n.set_preference(preference)
        self.assertIs(notify._local_time, local_time, "the pinned clock is put back")
        self.assertEqual(l10n.preference(), preference, "and the language")

    def test_the_card_entry_moves_when_what_it_says_moves(self):
        from codex_auto_resume import l10n
        g = self.generator
        drawing = g.card_drawing()
        before = g.card_render_input("en", drawing)
        l10n.catalog("en")
        changes = {
            "a catalog word": lambda: patch.dict(l10n._CACHE["en"], {"msg.toast_button_open": "Open the Dashboard"}),
            "the reset time": lambda: patch.object(g, "CARD_RESET_AT", g.CARD_RESET_AT + 60),
            "the conversation's name": lambda: patch.object(g, "WINDOW_NAMES", ("example-other",) + g.WINDOW_NAMES[1:]),
            "a theme pictured": lambda: patch.object(g, "CARD_THEMES", ("light",)),
        }
        for what, change in changes.items():
            with self.subTest(what), change():
                self.assertNotEqual(g.card_render_input("en", drawing), before, what + " did not move the entry")
        self.assertEqual(g.card_render_input("en", drawing), before)

    def drawing(self, files):
        with tempfile.TemporaryDirectory() as root:
            for name, text in files.items():
                path = Path(root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return self.generator.card_drawing(root)

    def real(self):
        package = ROOT / "src" / "codex_auto_resume"
        return {name: (package / name).read_text(encoding="utf-8")
                for name in ("notice_card.py", "notice_window.py", "tray_popup.py", "brand.py", "tray.py")}

    def test_the_patterns_cover_the_card_the_package_it_moves_into_and_the_popup_it_is_painted_by(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("notice_card.py", "notice_window.py", "notice_presence.py", "notifier.py",
                         "ui/card/view.py", "ui/card/win/layer.py", "ui/popup/layout.py", "ui/brand/tokens.py",
                         "tray_popup.py", "brand.py", "tray.py", "ui/tray/icon.py"):
                (Path(root) / name).parent.mkdir(parents=True, exist_ok=True)
                (Path(root) / name).write_text("X = 1\n", encoding="utf-8")
            covered = [path.relative_to(root).as_posix() for path in self.generator.card_code_files(root)]
        self.assertEqual(covered, ["brand.py", "notice_card.py", "notice_window.py", "tray_popup.py",
                                   "ui/brand/tokens.py", "ui/card/view.py", "ui/card/win/layer.py",
                                   "ui/popup/layout.py"])
        today = [path.relative_to(ROOT / "src" / "codex_auto_resume").as_posix()
                 for path in self.generator.card_code_files()]
        for name in ("notice_card.py", "notice_window.py", "tray_popup.py", "brand.py"):
            self.assertIn(name, today)

    def test_a_change_to_what_draws_the_card_moves_the_digest(self):
        real = self.real()
        before = self.drawing(real)
        self.assertEqual(before, self.generator.card_drawing(),
                         "the five modules are everything the card's digest reads today")
        for what, (name, old, new) in {
                "the card's layout": ("notice_card.py", "button_h = px(32)", "button_h = px(34)"),
                "the card's own light": ("notice_window.py", "brand.glow(self.vm[\"status\"], 0.0,",
                                         "brand.glow(self.vm[\"status\"], 0.5,"),
                "its floating shadow": ("notice_card.py", "DARK_ENOUGH = 0.05", "DARK_ENOUGH = 0.06"),
                "the popup's renderer it is painted by": ("tray_popup.py", "class Renderer:",
                                                          "class Renderer:\n    painted = True\n"),
                "a colour token": ("brand.py", '"canvas":  "#E9EEF4"', '"canvas":  "#E9EEF5"')}.items():
            changed = dict(real)
            self.assertIn(old, changed[name], what)
            changed[name] = changed[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertNotEqual(self.drawing(changed), before, what + " did not move the digest")

    def test_moving_the_card_into_ui_card_leaves_the_digest(self):
        """v0.6.6 moves the card into `ui/card/`: its layout and its motion leave `notice_card.py`
        for their own modules, with the imports that follow them, and comments change on the way."""
        real = self.real()
        before = self.drawing(real)
        rest, moved = PopupDrawingTests.cut(real["notice_card.py"], "layout", "CardMotion")
        moved_files = dict(real, **{
            "notice_card.py": rest.replace("# ----", "# moved: ----") + "\nfrom .ui.card.layout import layout, CardMotion\n",
            "ui/__init__.py": "",
            "ui/card/__init__.py": '"""The notification card."""\n',
            "ui/card/layout.py": ("from __future__ import annotations\n"
                                  "from ... import brand, tray_popup\n"
                                  "from ...notice_card import SETTLED, HOLD_MS, EXIT_MS, ENTRANCE_MS, SWAP_MS, "
                                  "SLIDE_MS, HOVER_GRACE_MS, entrance, leaving, ease_out\n\n" + moved),
        })
        self.assertEqual(self.drawing(moved_files), before)


class IconMotionPictureTests(unittest.TestCase):
    """The README's GIF of the notification-area icon's motion (v0.6.5), pinned the way the card's pictures are.

    The user asked for it ("마크다운에 아이콘 GIF 있으면 좋을 거 같아"). It is the icon's own frames at the moments its
    own timer shows them, drawn by the generator and never by hand, and its manifest entry is keyed by what it
    pictures and by a digest of the definitions the frames and their schedule are made of - so it goes stale exactly
    when the motion, its numbers, the mark or its colours change, and not when the icon's menu or the popup does.
    """

    GIF = "docs/images/icon-motion.gif"

    @classmethod
    def setUpClass(cls):
        cls.generator = generator()
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.made = cls.generator.icon_motion_frames()

    def test_the_gif_is_pinned_and_both_readmes_show_it_with_words_for_it(self):
        self.assertIn("<icon motion>", self.manifest["inputs"])
        self.assertIn(self.GIF, self.manifest["images"])
        self.assertEqual(self.manifest["images"][self.GIF]["size"], "%dx%d" % (self.made["width"], self.made["height"]))
        for name in READMES:
            if not (ROOT / name).is_file():
                continue
            body = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name):
                found = re.search(r'<img src="%s" alt="([^"]{80,})"' % re.escape(self.GIF), body)
                self.assertIsNotNone(found, "%s shows the icon's motion, with alt text that says what it shows" % name)

    def test_it_is_small_and_exactly_what_the_generator_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "icon-motion.gif"
            self.generator.render_icon_motion(target)
            written = target.read_bytes()
        committed = (ROOT / self.GIF).read_bytes()
        self.assertEqual(written, committed, "the committed GIF is not the generator's; run build/make_screenshots.py --icon")
        self.assertLess(len(committed), 300 * 1024)
        self.assertEqual(committed[:6], b"GIF89a")
        self.assertIn(b"NETSCAPE2.0\x03\x01\x00\x00", committed, "it loops for ever")

    def test_every_picture_is_the_icon_s_frame_at_that_moment(self):
        """Two loops of watching from two breaths before a sweep, recovering's sweeps, attention's one pulse and
        paused, as the icon's rules have them at each picture's moment - never breathing while it travels."""
        from codex_auto_resume import brand, tray
        g = self.generator
        start, end = g.icon_motion_stretch()
        top = tray.ICON_MOTION["levels"] - 1
        breath, motion = brand.GLOW["monitoring_ms"], tray.ICON_MOTION
        loop = breath * (motion["breaths"] + motion["sweep_breaths"])
        self.assertEqual((start, end), (breath, 2 * loop))
        self.assertEqual((start, end), (3200, 32000))
        sweeps_at = breath * motion["breaths"] - start                  # the first sweep, in the stretch's own ms
        frames = self.made["frames"]
        self.assertEqual(sum(delay for delay, _, _ in frames), (end - start) // 10)
        self.assertTrue(all(delay > 0 for delay, _, _ in frames))
        self.assertEqual(len(self.made["moments"]), len(frames))
        seen = {state: set() for state, _ in g.ICON_MOTION_LIGHTS}
        for (delay, _, shown), moment in zip(frames, self.made["moments"]):
            for state, frame in shown.items():
                seen[state].add(tuple(frame))
                with self.subTest(state=state, moment=moment):
                    if frame[0] != 0:
                        self.assertEqual(frame[1], top, "a head that has left its place is at full brightness")
                    if state in ("recovering", "idle"):
                        self.assertEqual(frame[1], top, "recovering never breathes, and paused is still")
                    if state == "watching" and moment < sweeps_at - 100:
                        self.assertEqual(frame[0], 0, "no sweep while it breathes")
                    if state == "attention" and moment >= brand.GLOW["attention_ms"] + 100:
                        self.assertEqual(tuple(frame), (0, top), "one pulse, then it holds")
        # The stroke's own positions: its place and every fifteen degrees clockwise of it, to the far end.
        stroke = set(range(round(tray.ICON_SWEEP / (360.0 / motion["positions"])) + 1))
        self.assertEqual({position for position, _ in seen["watching"]}, stroke, "watching sweeps the whole stroke")
        self.assertIn((0, 0), seen["watching"], "and breathes to its low")
        self.assertEqual({position for position, _ in seen["recovering"]}, stroke)
        # A problem's one pulse dims most of the way down: its frames need not land on the lowest level itself.
        self.assertLessEqual(min(level for _, level in seen["attention"]), top // 8)
        self.assertEqual({position for position, _ in seen["attention"]}, {0})
        self.assertEqual(seen["idle"], {(0, top)})

    @staticmethod
    def delays(data: bytes) -> list:
        """Each picture's delay in a GIF, in hundredths of a second, read block by block."""
        at = 13 + ((3 << ((data[10] & 7) + 1)) if data[10] & 0x80 else 0)
        found = []

        def skip(at):
            while data[at]:
                at += data[at] + 1
            return at + 1

        while data[at] != 0x3B:
            if data[at] == 0x21:
                if data[at + 1] == 0xF9:
                    found.append(struct.unpack("<H", data[at + 4:at + 6])[0])
                at = skip(at + 2)
            elif data[at] == 0x2C:
                flags = data[at + 9]
                at += 10 + ((3 << ((flags & 7) + 1)) if flags & 0x80 else 0)
                at = skip(at + 1)
            else:
                raise ValueError("not a GIF block at %d" % at)
        return found

    def test_no_picture_is_shorter_than_a_browser_shows_it(self):
        """Browsers - Chromium, Firefox and Safari alike - show a GIF picture of 10 ms or less for 100 ms. The first
        GIF merged the four states' moments into hundredths of a second, and where watching's and recovering's frames
        fell 10 ms apart a picture got 10 ms: on GitHub the 9.6 s loop took about 10.95 s, with fifteen stalls, most
        of them in the turns. So moments closer than ICON_MOTION_SHORTEST are shown as one picture."""
        g = self.generator
        start, end = g.icon_motion_stretch()
        self.assertEqual(g.ICON_MOTION_SHORTEST, 2)
        made = [delay for delay, _, _ in self.made["frames"]]
        self.assertGreaterEqual(min(made), g.ICON_MOTION_SHORTEST, sorted(made)[:20])
        committed = self.delays((ROOT / self.GIF).read_bytes())
        self.assertEqual(committed, made)
        self.assertEqual(sum(committed), (end - start) // 10, "the loop is as long as the stretch it shows")

    def test_it_loops_without_a_jump(self):
        """The GIF starts again where its stretch ends: the same frame of every state, as watching's loop and a whole
        number of recovering's turns have it."""
        from codex_auto_resume import tray
        g = self.generator
        start, end = g.icon_motion_stretch()
        first = self.made["frames"][0][2]
        for state, _ in g.ICON_MOTION_LIGHTS:
            if state == "attention":
                continue                        # its pulse is what arriving looks like
            with self.subTest(state=state):
                moment = end if state == "watching" else end - start
                self.assertEqual(tuple(first[state]), tray.icon_frame(state, moment, None))

    def drawing(self, files):
        with tempfile.TemporaryDirectory() as root:
            for name, text in files.items():
                path = Path(root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return self.generator.icon_drawing(root)

    def real(self):
        package = ROOT / "src" / "codex_auto_resume"
        return {name: (package / name).read_text(encoding="utf-8")
                for name in ("tray.py", "tray_popup.py", "brand.py", "notice_card.py")}

    def test_the_entry_moves_when_the_motion_or_the_mark_changes_and_not_otherwise(self):
        from codex_auto_resume import tray
        real = self.real()
        before = self.drawing(real)
        self.assertEqual(before, self.generator.icon_drawing(), "the four modules hold everything the digest reads")
        turn_ms = '"turn_frame_ms": %d,' % tray.ICON_MOTION["turn_frame_ms"]
        glow = re.search(r'"monitoring_ms": (\d+)', real["brand.py"])
        moves = {
            "the way it turns": ("tray.py", 'ICON_SHAPE["arc_end"] - 360.0 * position', 'ICON_SHAPE["arc_end"] + 360.0 * position'),
            "the breaths before a sweep": ("tray.py", '"breaths": 3,', '"breaths": 4,'),
            "the sweep's slot": ("tray.py", '"sweep_breaths": 2,', '"sweep_breaths": 3,'),
            "how much of the slot it travels": ("tray.py", '"sweep_out": 0.4,', '"sweep_out": 0.45,'),
            "the pause at the far end": ("tray.py", '"sweep_hold": 0.025,', '"sweep_hold": 0.05,'),
            "recovering's rest at home": ("tray.py", '"recover_rest": 0.075,', '"recover_rest": 0.1,'),
            "how far along the stroke it goes": ("brand.py", '"arc_start": 125.0, "arc_end": 55.0,',
                                                 '"arc_start": 130.0, "arc_end": 55.0,'),
            "the frame rate while it travels": ("tray.py", turn_ms, turn_ms.replace(",", "1,")),
            "the breath's depth": ("tray.py", '"dim": 0.6,', '"dim": 0.5,'),
            "the breath's rhythm": ("brand.py", glow.group(0), '"monitoring_ms": %d' % (int(glow.group(1)) + 100)),
            "the mark's accent": ("brand.py", 'ICON_ACCENT = "#4FE0F5"', 'ICON_ACCENT = "#4FE0F6"'),
            "the badge": ("tray_popup.py", "cut = max(2.5, width * 0.25)", "cut = max(2.5, width * 0.3)"),
        }
        for what, (name, old, new) in moves.items():
            changed = dict(real)
            self.assertIn(old, changed[name], what)
            changed[name] = changed[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertNotEqual(self.drawing(changed), before, what + " did not move the entry")
        stays = {
            "the icon's menu": ("tray.py", "MENU_OPEN, MENU_TOGGLE, MENU_STOP, MENU_PENDING = 1, 2, 3, 4",
                                "MENU_OPEN, MENU_TOGGLE, MENU_STOP, MENU_PENDING = 1, 2, 3, 5"),
            "the popup's renderer": ("tray_popup.py", "class Renderer:", "class Renderer:\n    painted = True\n"),
            "the notification card": ("notice_card.py", "DARK_ENOUGH = 0.05", "DARK_ENOUGH = 0.06"),
            "a comment on the motion": ("tray.py", "# The badge's own deep blue", "# The badge's deep blue"),
        }
        for what, (name, old, new) in stays.items():
            changed = dict(real)
            self.assertIn(old, changed[name], what)
            changed[name] = changed[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertEqual(self.drawing(changed), before, what + " moved the entry")

    def test_moving_the_motion_into_a_module_of_its_own_leaves_the_entry(self):
        """v0.6.6 splits the package; the motion leaving tray.py for its own module, with the imports that follow it,
        is the same GIF."""
        real = self.real()
        before = self.drawing(real)
        names = ("ICON_MOTION", "ICON_SWEEP", "_breath_level", "icon_turn", "_pulsing", "icon_frame", "icon_frame_ms",
                 "IconFrames")
        rest, moved = PopupDrawingTests.cut(real["tray.py"], *names)
        moved_files = dict(real, **{
            "tray.py": rest + "\nfrom .ui.tray.motion import %s\n" % ", ".join(names),
            "ui/__init__.py": "",
            "ui/tray/__init__.py": '"""The notification-area icon."""\n',
            "ui/tray/motion.py": ("from __future__ import annotations\nimport math\n"
                                  "from ... import brand\nfrom ...tray import icon_brand_state\n\n"
                                  + moved.replace("from . import tray_popup", "from ... import tray_popup")),
        })
        self.assertEqual(self.drawing(moved_files), before)

    def test_the_entry_moves_when_what_is_pictured_moves(self):
        g = self.generator
        drawing = g.icon_drawing()
        before = g.icon_render_input(drawing)
        for what, change in {
                "the size": lambda: patch.object(g, "ICON_MOTION_SIZE", 32),
                "a ground": lambda: patch.object(g, "ICON_MOTION_GROUNDS", (("light", "#F3F3F3"), ("dark", "#1F1F1F"))),
                "the states": lambda: patch.object(g, "ICON_MOTION_LIGHTS", g.ICON_MOTION_LIGHTS[:3]),
                "the shortest picture": lambda: patch.object(g, "ICON_MOTION_SHORTEST", 3)}.items():
            with self.subTest(what), change():
                self.assertNotEqual(g.icon_render_input(drawing), before, what + " did not move the entry")
        self.assertEqual(g.icon_render_input(drawing), before)


if __name__ == "__main__":
    unittest.main()
