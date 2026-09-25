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
  own builder, and by the definitions that draw it - its own modules, wherever v0.6.10-alpha moves
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

import guiscan
import srcscan  # noqa: E402
from codex_auto_resume.domain import public as domain_public  # noqa: E402
from codex_auto_resume.compat import (files as compat_files, probes as compat_probes,  # noqa: E402
                                      reported as compat_reported)

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
# The notification card (v0.6.5), drawn off-screen by the card's own code. Kept apart from COPIES,
# whose window pictures the pixel checks below read for the window's cards and its state dot. Since
# v0.6.6 the documentation is the light theme's only ("대부분의 이미지는 화이트모드만 해"), so the
# dark twin of each card is described in the text rather than pictured.
CARD_COPIES = {
    "en": {"assets/screenshot-notification.png": "docs/images/notification-card.png"},
    "ko": {"assets/screenshot-notification-ko.png": "docs/images/notification-card-ko.png"},
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


def real_modules(*names) -> dict:
    """The named modules of the package as {path: text}, with the popup's own files listed
    rather than named, and any other package among `names` listed the same way.

    Until v0.6.10-alpha the popup was one file and these tests named it; the icon was another.
    They are packages now, so a file added to either joins the digest - and these tests -
    without one of them being edited. Naming a file would mean a new module silently left out
    of what a picture is hashed from, which is the one mistake these tests cannot make.
    """
    package = ROOT / "src" / "codex_auto_resume"

    def listed(where: Path) -> dict:
        return {path.relative_to(package).as_posix(): path.read_text(encoding="utf-8")
                for path in sorted(where.rglob("*.py"))}

    files = listed(package / "ui" / "popup")
    for name in names:
        files.update(listed(package / name) if (package / name).is_dir()
                     else {name: (package / name).read_text(encoding="utf-8")})
    return files


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
        # `gui/window.sources`, not a regex over the build script. That regex read
        # `gui\\([A-Za-z]+\.cs)` out of the `-Sources` line, and its character class holds no
        # digit and no dot: a source named `Controls2.cs` or `Dashboard.Pages.cs` was missed
        # silently, and this test then said the window's inputs were complete. Since
        # v0.6.10-alpha the build reads the same file, so there is one answer to compare with.
        compiled = set(guiscan.manifest())
        self.assertIn("gui/Dashboard.cs", compiled)
        self.assertIn("gui/SettingsApp.cs", compiled)
        # The sources are one input, `<window sources>`, whose value is every compiled file
        # in compile order - so a file added to the window is an input without this list, or
        # any other, being edited.
        self.assertIn("<window sources>", inputs)
        expected = {"<window sources>", "gui/app.manifest", "assets/codex-auto-resume.ico",
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
        from codex_auto_resume.control import records as control_records
        from codex_auto_resume import (compatio, config, continuation, control, controlcli, l10n,
                                       machine, settings, startup, windows)
        from codex_auto_resume.codex import LocalSource
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
            "l10n.py - which language the window is resolved to":
                lambda: patch.object(l10n, "resolve", return_value="ko"),
            "startup.py - the start-at-sign-in value":
                several(lambda: patch.object(startup, "current_value", return_value="registered"),
                        lambda: patch.object(startup, "belongs_to", return_value=True)),
            # `control/records.py`, not the front: `_described` calls `describe_record` from
            # its own module, so a change made on the front would reach nothing.
            "control/records.py - what a row carries":
                lambda: changed(control_records, "describe_record",
                                lambda row: dict(row, budget_resets_left=0)),
            # describe calls public_code in domain/public.py, its own module; the counts
            # still read it through the machine front. Both, so the change reaches every row.
            "domain/public.py - which public status a row shows": several(
                lambda: changed(machine, "public_code", lambda code: "failed_retryable"),
                lambda: changed(domain_public, "public_code", lambda code: "failed_retryable")),
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
            # compat/probes.py and compat/files.py since v0.6.10-alpha: the registry's parts
            # call these through the module that defines them, and the pictures read
            # load_bundled through the compatio front too - so both, for that one.
            "compat/probes.py - the local checks behind the Diagnostics card":
                lambda: changed(compat_probes, "source_checks", lambda checks: dict(checks, queue_schema="FAIL")),
            "tests/fixtures/codex_compat_frozen.json - the registry data the pictures are made with": several(
                lambda: patch.object(compatio, "load_bundled", return_value=(None, "missing")),
                lambda: patch.object(compat_files, "load_bundled", return_value=(None, "missing"))),
            # v0.6.10: what others report, shown beside the version on the Diagnostics card.
            "tests/fixtures/reported_frozen.json - the counts beside the version":
                lambda: changed(compat_reported, "lookup", lambda answer: dict(answer, worked=answer["worked"] + 1)),
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
        # pictures, so the name-to-locale map below describes dev, not that branch.
        import languages
        if languages.generated_ko_branch():
            self.skipTest("the generated ko branch renames the READMEs")
        # main is English only: its README is held to the English pictures, and the Korean
        # one is dev's to answer. Anywhere else a missing README fails, rather than skipping.
        english_only = languages.english_only()
        """Korean prose over English screenshots is the defect this release removed.

        On the generated `ko` branch README.ko.md *is* README.md, so only one of these
        names resolves there and opening the other would raise rather than fail.
        """
        for name, locale in READMES.items():
            if english_only and name.endswith(".ko.md"):
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
    """Width, height, rows of RGB tuples and rows of alpha (None where the picture has none).

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
        rows.append([tuple(line[x * channels:x * channels + channels]) for x in range(width)])
        previous = line
    return width, height, [[pixel[:3] for pixel in row] for row in rows], (
        [[pixel[3] for pixel in row] for row in rows] if channels == 4 else None)


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
            width, height, rows, _clear = read_png(ROOT / name)
            surface = sum(1 for row in rows for pixel in row if pixel == self.SURFACE)
            with self.subTest(name):
                self.assertGreater(surface, width * height * 0.15,
                                   "%s shows almost no card surface" % name)

    def test_every_window_screenshot_has_its_header_and_footer_cards(self):
        """Since v0.6.4 the header and the footer are cards floating on the canvas; until then they
        were bands ruled off with a hairline, and one capture in four lost the header's rule the
        same way the dot was lost. A capture that loses a card shows canvas where it belongs."""
        for name in WINDOW_SHOTS:
            width, height, rows, _clear = read_png(ROOT / name)
            carded = [y for y, row in enumerate(rows)
                      if sum(1 for pixel in row if pixel == self.SURFACE) > width * 0.8]
            with self.subTest(name):
                self.assertTrue(any(y < height // 6 for y in carded), "no header card")
                self.assertTrue(any(y > height * 5 // 6 for y in carded), "no footer card")

    def test_every_window_screenshot_shows_the_state_dot(self):
        for name in WINDOW_SHOTS:
            width, height, rows, _clear = read_png(ROOT / name)
            header = rows[:height * 15 // 100]
            left = width // 8
            near = sum(1 for row in header for pixel in row[:left]
                       if all(abs(a - b) <= 24 for a, b in zip(pixel, self.ACTIVE)))
            with self.subTest(name):
                self.assertGreater(near, 40, "the header's state dot is missing from %s" % name)

    def test_no_window_screenshot_carries_the_frame_windows_draws(self):
        """Until v0.6.6 every one of them had a black band down each side and along the bottom - 11 px
        at 100%, 16 at 150% - and nobody had looked at the edge of a 1522-pixel picture. PrintWindow
        returns the window without its frame, because the frame is Windows' to draw, and the bitmap it
        is drawn into starts black. The picture is cut to the window's own client rectangle now."""
        for name in WINDOW_SHOTS:
            width, height, rows, _clear = read_png(ROOT / name)
            with self.subTest(name):
                middle = height // 2
                self.assertNotEqual(rows[middle][0], (0, 0, 0), "a black band down the left")
                self.assertNotEqual(rows[middle][width - 1], (0, 0, 0), "and down the right")
                self.assertNotEqual(rows[height - 1][width // 2], (0, 0, 0), "and along the bottom")

    def test_every_window_screenshot_has_the_corners_windows_rounds(self):
        """A screenshot of a Windows 11 window with square corners is a screenshot of a window nobody
        has. The capture cuts them to the system's radius and leaves them clear, so the page behind the
        picture shows through - which only holds while every encoding after it keeps the alpha."""
        for name in WINDOW_SHOTS:
            width, height, _rows, clear = read_png(ROOT / name)
            with self.subTest(name):
                self.assertIsNotNone(clear, "%s has no transparency at all" % name)
                for x, y, where in ((0, 0, "top left"), (width - 1, 0, "top right"),
                                    (0, height - 1, "bottom left"), (width - 1, height - 1, "bottom right")):
                    self.assertEqual(clear[y][x], 0, "%s: the %s corner is not clear" % (name, where))
                self.assertEqual(clear[height // 2][width // 2], 255, "and the window itself is opaque")


def apng_controls(data: bytes) -> list:
    """(x, y, width, height, delay as a Fraction of a second) of each APNG frame, in order."""
    from fractions import Fraction
    found, at = [], 8
    while at + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        if kind == b"fcTL":
            width, height, x, y, numerator, denominator = struct.unpack(">IIIIHH", data[at + 12:at + 32])
            found.append((x, y, width, height, Fraction(numerator, denominator or 100)))
        at += 12 + length
    return found


def apng_frames(path) -> tuple:
    """(width, height, [whole RGB picture after each frame]) of an RGB APNG this generator writes: its first
    picture, then each later frame's rectangle drawn over the picture before it."""
    import zlib
    raw = Path(path).read_bytes()
    at, chunks = 8, []
    while at < len(raw):
        length, kind = struct.unpack(">I4s", raw[at:at + 8])
        chunks.append((kind, raw[at + 8:at + 8 + length]))
        at += 12 + length
    width, height, _depth, colour = struct.unpack(">IIBB", next(body for kind, body in chunks if kind == b"IHDR")[:10])
    if colour != 2:
        raise ValueError("only an RGB APNG is read here")

    def rows(data, wide, tall):
        stride, out, previous = wide * 3, bytearray(), bytearray(wide * 3)
        for y in range(tall):
            start = y * (stride + 1)
            mode, line = data[start], bytearray(data[start + 1:start + 1 + stride])
            if mode:
                for i in range(stride):
                    left = line[i - 3] if i >= 3 else 0
                    up, corner = previous[i], (previous[i - 3] if i >= 3 else 0)
                    if mode == 1:
                        line[i] = (line[i] + left) & 0xFF
                    elif mode == 2:
                        line[i] = (line[i] + up) & 0xFF
                    elif mode == 3:
                        line[i] = (line[i] + (left + up) // 2) & 0xFF
                    else:
                        guess = left + up - corner
                        pa, pb, pc = abs(guess - left), abs(guess - up), abs(guess - corner)
                        line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 0xFF
            out += line
            previous = line
        return out

    pictures, canvas, control, data = [], None, None, bytearray()

    def flush():
        nonlocal canvas
        if control is None:
            return
        wide, tall, x, y = control
        pixels = rows(zlib.decompress(bytes(data)), wide, tall)
        if canvas is None:
            canvas = bytearray(pixels)
        else:
            for row in range(tall):
                start = ((y + row) * width + x) * 3
                canvas[start:start + wide * 3] = pixels[row * wide * 3:(row + 1) * wide * 3]
        pictures.append(bytes(canvas))

    for kind, body in chunks:
        if kind == b"fcTL":
            flush()
            data = bytearray()
            control = struct.unpack(">IIII", body[4:20])
        elif kind == b"IDAT":
            data += body
        elif kind == b"fdAT":
            data += body[4:]
    flush()
    return width, height, pictures


class BreathingPictureTests(unittest.TestCase):
    """Every light a surface moves, moving in its picture, on its own ground, for exactly one cycle (F15, v0.6.10).

    Until v0.6.10 every animated picture was its capture with one disc painted again: the topmost disc of the
    monitoring colour, on the light theme's `surface`, in 132 frames of 33 ms. Which disc that was had gone wrong
    once - the panel's pictures breathed the dot in the Automatic recovery tile, which then never moved in the
    product, while the status light above it held still ("상태등이 맨위에 있는건 안 깜빡이네?") - and once the tile's
    light moved in the product (F1) the picture held it still instead; a light on a tile or in the dark theme would
    have been painted in a box of the wrong ground; and the loop took 4356 ms where the product takes 4400.

    Now each picture's surface declares its lights, and the manifest keeps them ("lights"): the popup and the card
    from their own layout, the panel from the page, the window from its capture. These hold every committed picture
    to its record, and the generator's frames to the product's own drawing.
    """

    @classmethod
    def setUpClass(cls):
        cls.generator = generator()
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.records = cls.manifest.get("lights", {})

    def moving(self):
        """(name, record, timeline) of every committed picture whose lights move."""
        found = []
        for name, record in sorted(self.records.items()):
            timeline = self.generator.light_timeline(record)
            if timeline is not None:
                found.append((name, record, timeline))
        return found

    def test_every_picture_of_a_surface_says_what_it_holds_of_the_light(self):
        """The icon's and the light's own pictures are drawn from their frames; every other picture is of a surface
        with a status light, and says where each of its lights is, in which state and on which ground."""
        g = self.generator
        pictured = set(self.manifest["images"]) - {"docs/images/icon-motion.png", "docs/images/status-light.png"}
        self.assertEqual(sorted(pictured - set(self.records)), [], "a picture of a surface with no record")
        self.assertEqual(sorted(set(self.records) - set(self.manifest["images"])), [], "a record of no picture")
        for name, record in self.records.items():
            with self.subTest(name):
                self.assertIn(record["surface"], ("window", "panel", "popup", "card"))
                self.assertEqual(record["theme"], g.THEME)
                self.assertIn(record["design"], g.DESIGNS_PICTURED)
                self.assertTrue(record["lights"], "every surface pictured has its status light")
                for light in record["lights"]:
                    self.assertRegex(light["ground"], r"^#[0-9A-F]{6}$")
                    self.assertGreater(light["radius"], 0)
                    self.assertIn(light["state"], ("monitoring", "waiting", "checking", "recovering", "attention",
                                                   "failed", "paused", "idle"))

    def test_every_light_that_moves_moves_in_its_picture_and_nothing_else_does(self):
        """For every committed picture: animated exactly when a light in it moves in its design; its frames' union
        covers every light that moves; every frame draws within one of those lights and nowhere else; and the frames
        take exactly one cycle of their rhythm, one frame per light per moment."""
        from fractions import Fraction
        g = self.generator
        still = []
        for name, record in sorted(self.records.items()):
            raw = (ROOT / name).read_bytes()
            timeline = g.light_timeline(record)
            if timeline is None:
                still.append(name)
                with self.subTest(name):
                    self.assertNotIn(b"acTL", raw, "%s moves, and nothing in it does in the product" % name)
                continue
            with self.subTest(name):
                self.assertIn(b"acTL", raw, "%s holds still, and its light moves in the product" % name)
                controls = apng_controls(raw)
                self.assertEqual(controls[0][:4], (0, 0) + tuple(int(v) for v in record_size(self.manifest, name)))
                self.assertEqual(sum(control[4] for control in controls), Fraction(timeline.cycle, 1000),
                                 "one cycle of the rhythm, exactly")
                self.assertEqual(len(controls), timeline.steps * len(timeline.moving))
                self.assertEqual({control[4] for control in controls}, {timeline.delay})
                drawn = [control for control in controls[1:] if control[2:4] != (1, 1)]
                lights = [record["lights"][index] for index in timeline.moving]
                for light in lights:
                    self.assertTrue(any(x <= light["x"] <= x + w and y <= light["y"] <= y + h
                                        for x, y, w, h, _delay in drawn),
                                    "%s never draws its light at (%g, %g)" % (name, light["x"], light["y"]))
                for x, y, w, h, _delay in drawn:
                    self.assertTrue(any(self.within(light, (x, y, w, h)) for light in lights),
                                    "%s draws (%d, %d, %d, %d), which is no light of it" % (name, x, y, w, h))
        self.assertTrue(still, "Still's pictures are still")
        self.assertTrue(self.moving(), "no picture breathes any more; run build/make_screenshots.py --breathe")

    def within(self, light, box) -> bool:
        """Whether a frame's rectangle lies inside what a light owns: its reach and the margin drawn with it."""
        g = self.generator
        reach = g.light_reach(light) + g.LIGHT_MARGIN + 1
        x, y, w, h = box
        return (light["x"] - reach <= x and x + w <= light["x"] + reach
                and light["y"] - reach <= y and y + h <= light["y"] + reach)

    def test_the_panel_moves_both_its_lights_and_every_other_surface_its_one(self):
        """Since v0.6.10 the panel has two lights that breathe together - the state's, and the Automatic recovery
        tile's mini one (F1) - on two grounds; the window, the popup and the card have one each."""
        counts = {}
        for name, record, timeline in self.moving():
            counts.setdefault(record["surface"], set()).add(len(timeline.moving))
            if record["surface"] == "panel":
                grounds = [record["lights"][index]["ground"] for index in timeline.moving]
                with self.subTest(name):
                    self.assertLess(record["lights"][0]["radius"], 13)
                    self.assertGreater(record["lights"][0]["radius"], record["lights"][1]["radius"],
                                       "the state's light, then the tile's smaller one")
                    if record["design"] in ("soft", "still"):
                        self.assertNotEqual(grounds[0], grounds[1], "the card's ground, then the tile's")
        self.assertEqual(counts, {"panel": {2}, "window": {1}, "popup": {1}, "card": {1}})

    def test_the_card_breathes_with_the_rest(self):
        """Until v0.6.9 an interruption card held still, so its picture did too. Waiting breathes now."""
        self.assertIn(b"acTL", (ROOT / "docs/images/notification-card.png").read_bytes())
        self.assertEqual(self.records["docs/images/notification-card.png"]["lights"][0]["state"], "waiting")

    def test_the_window_has_as_many_lights_as_its_pictures_declare(self):
        """The window is the one surface that cannot say where its lights are, so its captures are searched for them
        and must hold as many as the window draws: HaloDot instances in its compiled source."""
        self.assertEqual(len(re.findall(r"\bnew HaloDot\(", guiscan.window())), self.generator.WINDOW_LIGHTS)
        for name, record in self.records.items():
            if record["surface"] == "window":
                with self.subTest(name):
                    self.assertEqual(len(record["lights"]), self.generator.WINDOW_LIGHTS)

    def test_one_picture_loops_on_one_rhythm_exactly(self):
        from fractions import Fraction
        g = self.generator

        def record(*states, design="soft"):
            return g.picture_record("panel", "light", design, [
                {"x": 10.0, "y": 10.0 + 40 * index, "radius": 6.0, "scale": 1.0, "state": state, "ground": "#F6F8FB"}
                for index, state in enumerate(states)])

        one = g.light_timeline(record("waiting"))
        self.assertEqual((one.cycle, one.steps, one.delay), (4400, 132, Fraction(1, 30)))
        self.assertEqual(one.steps * one.delay, Fraction(22, 5), "132 frames take 4400 ms, not 4356")
        self.assertAlmostEqual(one.moments[1], 4400 / 132.0)
        two = g.light_timeline(record("waiting", "waiting"))
        self.assertEqual((two.delay, two.moving), (Fraction(1, 60), (0, 1)))
        self.assertEqual(two.steps * len(two.moving) * two.delay, Fraction(22, 5))
        self.assertEqual(g.light_timeline(record("checking")).cycle, g.brand.GLOW["arc_ms"])
        self.assertEqual(g.light_timeline(record("recovering")).steps, 84)
        self.assertEqual(g.light_timeline(record("waiting", "idle")).moving, (0,), "a light that is off is not drawn")
        for off in (record("idle"), record("paused"), record("waiting", design="still")):
            self.assertIsNone(g.light_timeline(off))
        with self.assertRaises(SystemExit):
            g.light_timeline(record("waiting", "recovering"))

    def synthetic(self, dark_ground, tile_ground):
        """A dark card with a tile on its right half, a light standing on each - the card's and the tile's - drawn at
        the first moment of the breath, as a capture holds them: (width, height, RGB, record)."""
        g = self.generator
        width, height = 90, 50
        card, tile = g.brand.rgb(dark_ground), g.brand.rgb(tile_ground)
        rgb = bytearray()
        for y in range(height):
            for x in range(width):
                rgb += bytes(tile if x >= 45 else card)
        lights = [{"x": 20.0, "y": 25.0, "radius": 6.0, "scale": 1.0, "state": "waiting", "ground": dark_ground},
                  {"x": 68.5, "y": 25.5, "radius": 4.0, "scale": 1.0, "state": "waiting", "ground": tile_ground}]
        record = g.picture_record("panel", "dark", "soft", lights)
        colour = g.brand.rgb(g.brand.palette("dark")["active"])
        for light in record["lights"]:
            g.paint_light(rgb, width, light, g.brand.glow("waiting", 0, 0), colour)
        return width, height, bytes(rgb), record

    def test_each_light_is_drawn_on_its_own_ground_and_never_a_box_of_another(self):
        """A synthetic dark picture with a light on the card and one on a tile of another ground: in every frame the
        ring just outside each light's reach is exactly its own ground, and nothing outside what the lights own
        changes. And a light declared on a ground it does not stand on is refused before anything is drawn."""
        g = self.generator
        dark, tile = g.brand.card_ground("dark"), g.brand.palette("dark")["raised"]
        self.assertNotEqual(dark, tile)
        width, height, rgb, record = self.synthetic(dark, tile)
        delay, first, later = g.breathe_frames(rgb, width, height, record)
        self.assertEqual(len(later) + 1, 264)
        owned = {(x, y) for light in record["lights"] for x, y, _samples in g.light_pixels(light)}
        picture = bytearray(first)
        pictures = [bytes(picture)]
        for _delay, (left, top, wide, tall), patch in later:
            for row in range(tall):
                start = ((top + row) * width + left) * 3
                picture[start:start + wide * 3] = patch[row * wide * 3:(row + 1) * wide * 3]
            pictures.append(bytes(picture))
        dimmest = pictures[132]                         # both lights near the bottom of the breath
        for index, frame in enumerate((pictures[0], dimmest, pictures[-1])):
            for x in range(width):
                for y in range(height):
                    at = (y * width + x) * 3
                    if (x, y) not in owned:
                        self.assertEqual(frame[at:at + 3], rgb[at:at + 3], "(%d, %d) is no light's" % (x, y))
            for light in record["lights"]:
                ground = bytes(g.brand.rgb(light["ground"]))
                for x, y, samples in g.light_pixels(light):
                    if min(sample[2] for sample in samples) > g.light_reach(light) + 0.5:
                        at = (y * width + x) * 3
                        self.assertEqual(frame[at:at + 3], ground, "frame %d: (%d, %d) round the light at "
                                                                   "(%g, %g)" % (index, x, y, light["x"], light["y"]))
        # Dimmed, each dot is drawn toward its own ground: the tile's light is not the card's colour mixed in.
        for light in record["lights"]:
            at = (int(light["y"]) * width + int(light["x"])) * 3
            ground, colour = g.brand.rgb(light["ground"]), g.brand.rgb(g.brand.palette("dark")["active"])
            frame = g.brand.glow("waiting", 2200, 2200)
            expected = [one + (two - one) * (1.0 - frame["dim"]) for one, two in zip(ground, colour)]
            for channel in range(3):
                self.assertLessEqual(abs(dimmest[at + channel] - expected[channel]), 12)
        # Declared on the card's ground, the tile's light is refused: a frame would draw a box of the card on the tile.
        wrong = json.loads(json.dumps(record))
        wrong["lights"][1]["ground"] = dark
        with self.assertRaises(SystemExit):
            g.breathe_frames(rgb, width, height, wrong)
        # And one declared where it is not.
        moved = json.loads(json.dumps(record))
        moved["lights"][0]["x"] += 9
        with self.assertRaises(SystemExit):
            g.breathe_frames(rgb, width, height, moved)

    def test_checking_turns_its_arc_in_the_picture(self):
        """A light that is checking holds lit and turns its arc (brand.GLOW arc_*): its frames draw the arc going
        round, once a cycle of arc_ms."""
        g = self.generator
        width = height = 40
        rgb = bytearray(bytes(g.brand.rgb("#F6F8FB")) * (width * height))
        light = {"x": 20.0, "y": 20.0, "radius": 5.0, "scale": 1.5, "state": "checking", "ground": "#F6F8FB"}
        colour = g.brand.rgb(g.brand.palette("light")["active"])
        g.paint_light(rgb, width, light, g.brand.glow("checking", 0, 0), colour)
        record = g.picture_record("window", "light", "soft", [light])
        delay, first, later = g.breathe_frames(bytes(rgb), width, height, record)
        self.assertEqual(len(later) + 1, g.brand.GLOW["arc_ms"] * g.BREATHE_FPS // 1000)
        middle = 5.0 + g.brand.GLOW["arc_gap"] * 1.5
        right = (20 * width + int(20 + middle)) * 3            # three o'clock, where the arc starts at 0
        left = (20 * width + int(20 - middle)) * 3             # nine o'clock, half a turn on
        self.assertNotEqual(first[right:right + 3], bytes(g.brand.rgb("#F6F8FB")))
        self.assertEqual(first[left:left + 3], bytes(g.brand.rgb("#F6F8FB")))

    @unittest.skipUnless(os.name == "nt", "the popup is drawn by GDI+")
    def test_the_popup_s_frames_are_the_popup_s_own_drawing(self):
        """Frame k of the popup's picture is the popup drawn whole with its light at moment k - byte for byte - so
        the picture moves exactly as the popup's own renderer moves it: `draw_halo`, the popup's call for a frame of
        its light, over the band it keeps, is what the generator writes."""
        from codex_auto_resume.ui import popup as tray_popup
        g = self.generator
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "popup.png"
            with patch.dict(os.environ, {"CODEX_AUTO_RESUME_LANG": "en"}):
                record = g.render_popup(target, "en")
                width, height, pictures = apng_frames(target)
                timeline = g.light_timeline(record)
                strings, view = g.popup_view("en")
                renderer = tray_popup.Renderer()
                renderer.theme, renderer.design = g.THEME, "soft"
                try:
                    plan = renderer.layout(view, g.POPUP_SCALE, tray_popup.locale_of(strings))
                    self.assertEqual(len(pictures), timeline.steps)
                    for step in (0, 1, 33, 66, 99, timeline.steps - 1):
                        moment = timeline.moments[step]
                        whole = renderer.draw(view, plan, frame=tray_popup.halo(view["light"], moment, moment))
                        with self.subTest(step=step):
                            self.assertEqual(pictures[step], g.bgra_rgb(whole.pixels()))
                finally:
                    renderer.close()
        self.assertEqual(record["lights"][0]["state"], view["light"])


def record_size(manifest, name) -> tuple:
    """(width, height) a manifest records for a picture."""
    return tuple(int(value) for value in manifest["images"][name]["size"].split("x"))


class DesignPictureTests(unittest.TestCase):
    """The four designs pictured (D16, v0.6.10): the Dashboard's Overview, the panel, the popup and the card, in
    each - Soft's the pictures the set always had, every other design's `docs/images/design-<design>-<surface>.png` -
    in English and the light theme only, each keyed by what it is drawn from in its design."""

    @classmethod
    def setUpClass(cls):
        cls.generator = generator()
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_every_design_is_pictured_on_its_four_surfaces(self):
        g = self.generator
        from codex_auto_resume import brand
        self.assertEqual(list(g.DESIGNS_PICTURED), list(brand.DESIGNS))
        self.assertEqual(g.DESIGNS_PICTURED[0], brand.DEFAULT_DESIGN)
        self.assertEqual(self.manifest["designs"], list(g.DESIGNS_PICTURED))
        records = self.manifest["lights"]
        for design in g.DESIGNS_PICTURED:
            for surface in g.DESIGN_SURFACES:
                name = g.design_picture(design, surface).relative_to(ROOT).as_posix()
                with self.subTest(design=design, surface=surface):
                    self.assertIn(name, self.manifest["images"])
                    self.assertEqual(records[name]["design"], design)
                    self.assertEqual(records[name]["surface"], "window" if surface == "dashboard" else surface)
                    if design != brand.DEFAULT_DESIGN:
                        self.assertEqual(name, "docs/images/design-%s-%s.png" % (design, surface))
        # Soft's are the pictures the set always had, under the names they always had.
        self.assertEqual(g.design_picture("soft", "popup").name, "tray-popup.png")
        self.assertEqual(g.design_picture("soft", "panel").name, "settings-panel.png")
        # Documentation only: nothing of another design is shipped in assets/.
        self.assertEqual(sorted(path.name for path in (ROOT / "assets").glob("*design*")), [])

    def test_each_design_is_keyed_under_its_own_name_and_soft_under_the_old_ones(self):
        g = self.generator
        inputs = self.manifest["inputs"]
        for design in g.DESIGNS_PICTURED[1:]:
            for kind in ("bridge envelope", "panel render", "popup render", "card render"):
                with self.subTest(design=design, kind=kind):
                    self.assertIn("<%s:en:%s>" % (kind, design), inputs)
        self.assertEqual([name for name in inputs if name.endswith(":soft>")], [])
        for kind in ("bridge envelope", "panel render", "popup render", "card render"):
            self.assertIn("<%s:en>" % kind, inputs)

    def test_a_design_s_entries_move_with_the_design_and_soft_s_are_what_they_were(self):
        """Soft's popup and card entries are what they were before designs were pictured - Soft is named in
        nothing hashed - and each other design's differs from Soft's and from every other's."""
        g = self.generator
        popup, card = g.popup_drawing(), g.card_drawing()
        self.assertEqual(g.popup_render_input("en", popup), g.popup_render_input("en", popup, "soft"))
        self.assertEqual(g.card_render_input("en", card), g.card_render_input("en", card, "soft"))
        entries = {design: (g.popup_render_input("en", popup, design), g.card_render_input("en", card, design))
                   for design in g.DESIGNS_PICTURED}
        self.assertEqual(len({popup_entry for popup_entry, _card in entries.values()}), len(g.DESIGNS_PICTURED))
        self.assertEqual(len({card_entry for _popup, card_entry in entries.values()}), len(g.DESIGNS_PICTURED))

    def test_a_design_s_tokens_move_its_popup_and_card(self):
        """Every design's colours are among the definitions both digests pool (brand/tokens.py), so a change to one
        of Classic's or Plain's tokens moves the pictures drawn in it."""
        g = self.generator
        files = real_modules("notice_card.py", "notice_window.py", "brand", "ui/tray", "ui/card", "ui/words.py",
                             "win/dll.py")

        def digests(files):
            with tempfile.TemporaryDirectory() as root:
                for name, text in files.items():
                    path = Path(root) / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
                return g.popup_drawing(root), g.card_drawing(root)

        before = digests(files)
        tokens = files["brand/tokens.py"]
        for design, (old, new) in {"classic": ('"canvas": "#F2F5F9"', '"canvas": "#F2F5FA"'),
                                   "plain": ('"ink": "#1B1B1B"', '"ink": "#1B1B1C"')}.items():
            self.assertIn(old, tokens, design)
            changed = digests(dict(files, **{"brand/tokens.py": tokens.replace(old, new, 1)}))
            with self.subTest(design):
                self.assertNotEqual(changed[0], before[0], "the popup's")
                self.assertNotEqual(changed[1], before[1], "the card's")

    def test_the_panel_is_pinned_to_its_design(self):
        from codex_auto_resume import brand
        g = self.generator
        soft = g.panel_html()
        # Soft is no stamp, as the script stamps a stored Soft, and the page is told to keep it.
        self.assertEqual(re.search(r"<html[^>]*>", soft).group(0), '<html data-design-pinned="">')
        for design in g.DESIGNS_PICTURED[1:]:
            page = g.panel_html(design=design)
            with self.subTest(design):
                self.assertEqual(re.search(r"<html[^>]*>", page).group(0),
                                 '<html data-design="%s" data-design-pinned="">' % design)
                self.assertEqual(g.sample_panel_data(design)["settings"]["design"], design)
        self.assertIn(brand.CLASSIC_LIGHT["canvas"], g.panel_html(design="classic"))
        # Every light the page draws is held at the first moment of its breath, which the picture is of.
        self.assertIn(g.held_lights(), soft)
        self.assertLess(soft.index(g.held_lights()), soft.rindex("<script>"))

    def test_a_design_s_window_is_what_the_bridge_answers_an_installation_storing_it(self):
        """The window's picture in a design is keyed by the bridge's answers to an installation that stores the
        design, and they differ from Soft's in the stored design and nothing else."""
        g = self.generator
        soft = g.bridge_envelope("en")
        classic = g.window_envelopes(("en",), "classic")["en"]
        self.assertNotEqual(classic, soft)
        self.assertIn('"design":"classic"', classic)
        self.assertEqual(classic.replace('"design":"classic"', '"design":"soft"'), soft)


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

    def test_every_surface_is_drawn_in_the_pinned_theme_and_design(self):
        """The window resolves the stored Theme when it starts, and the default - Use system
        setting - follows Windows' app mode. A scratch installation that stored the defaults was
        photographed dark on a machine in dark mode, beside light panel and popup pictures, under a
        manifest that said light. Passing `--theme` is no way round it: the window's first settings
        read reopens it in the stored theme. So the theme is stored, for every surface alike.

        Since v0.6.10 the Design is pinned the same way, in the same file: every picture is drawn in
        Soft but the designs' own (DESIGNS_PICTURED), each in the design it pictures, and the stored
        settings are the defaults but for the theme and the design."""
        import inspect
        import sys
        import tempfile
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / "build"))
        sys.path.insert(0, str(ROOT / "src"))
        try:
            import make_screenshots
            from codex_auto_resume import settings as policy
            from codex_auto_resume.ui import popup as tray_popup
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
        self.assertEqual((stored["design"], raw["design"]), ("soft", "soft"))
        self.assertEqual({k: v for k, v in stored.items() if k not in ("theme", "design")},
                         {k: v for k, v in policy.defaults().items() if k not in ("theme", "design")},
                         "otherwise the pictures show the defaults")
        # A design's own pictures store that design, and nothing else apart from the theme.
        with tempfile.TemporaryDirectory() as scratch:
            make_screenshots.write_settings(Path(scratch), design="classic")
            classic = policy.load(Path(scratch) / "config" / "settings.json")
        self.assertEqual(classic, dict(stored, design="classic"))
        # Since v0.6.10 the installation stores the theme it is given, which is THEME unless the
        # audit sheets (`--audit`, never published) ask for the other: no published picture asks.
        # And the design it is given, which is Soft unless the picture is of another design.
        self.assertIn("write_settings(home, theme, design)", inspect.getsource(make_screenshots.scratch_installation))
        self.assertNotIn("policy.defaults()", inspect.getsource(make_screenshots.scratch_installation))
        self.assertNotIn("--theme", inspect.getsource(make_screenshots.render_window))
        for published in (make_screenshots.scratch_installation, make_screenshots.render_window,
                          make_screenshots.render_panel, make_screenshots.render_popup):
            self.assertIsNone(inspect.signature(published).parameters["theme"].default, published.__name__)
            self.assertIsNone(inspect.signature(published).parameters["design"].default, published.__name__)
        for whole_run in (make_screenshots.main, make_screenshots.render_inputs):
            self.assertNotIn("theme=", inspect.getsource(whole_run).replace("theme=THEME", ""),
                             "a published picture is drawn in THEME")
            self.assertNotIn("design=\"", inspect.getsource(whole_run),
                             "a published picture is drawn in Soft or in the design it pictures")
        # The panel: served pinned, and its sample's own Theme control says the same.
        self.assertEqual(make_screenshots.sample_panel_data()["settings"]["theme"], theme)
        self.assertEqual(make_screenshots.sample_panel_data()["settings"]["design"], "soft")
        self.assertIn('data-theme="%s" data-theme-pinned=""' % theme, make_screenshots.panel_html(theme=theme))
        # The popup: its renderer is told the theme and the design, rather than trusted to default to them.
        seen = []

        class Renderer:
            theme = design = "unset"

            def layout(self, view, scale, locale):
                seen.append((self.theme, self.design))
                return {"size": (1, 1), "scale": scale,
                        "items": [{"kind": "halo", "cx": 0.5, "cy": 0.5, "state": "idle"}]}

            def draw(self, view, plan, frame=None):
                return type("Canvas", (), {"pixels": lambda canvas: bytes(4)})()

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as scratch, patch.object(tray_popup, "Renderer", Renderer):
            make_screenshots.render_popup(Path(scratch) / "popup.png", "en")
            make_screenshots.render_popup(Path(scratch) / "popup.png", "en", design="plain")
        self.assertEqual(seen, [(theme, "soft"), (theme, "plain")])

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

    def test_the_panel_the_popup_and_the_window_show_one_fixture_at_one_moment(self):
        """Since v0.6.10 every surface is pictured from one set of records at one set of offsets: the
        panel, the popup and the card at POPUP_NOW, the window at the moment it is photographed. Until
        then the panel registered two rows of its own at times near 1970, so both read "due now" and
        its network failure waited for a usage reset, and the popup was handed a third row, a server
        error, that the window and the panel never showed - three pictures an audit cannot compare."""
        import inspect
        g = self.generator
        fields = ("interruption_id", "thread_id", "name", "category", "state", "code",
                  "eligible_at", "reset_at", "next_retry_at", "thread_enabled")

        def shown(rows):
            return sorted(tuple(row[field] for field in fields) for row in rows)

        window = shown(self.reply("dashboard")["pending"])
        self.assertEqual(len(window), 2)
        self.assertEqual(shown(g.sample_panel_data()["pending"]), window, "the panel's rows")
        self.assertEqual(g.sample_panel_data()["status"]["pending"], len(window), "the panel's count")
        self.assertEqual(shown(g.popup_rows()), window, "the popup's rows")
        # One moment: the envelope's, the popup's and the panel page's clock, and the card's reset is
        # the usage limit's. The window is seeded by the same function, with the same offsets, at the
        # moment it is photographed - the bridge behind it runs with the real clock - and is told that
        # moment; so its countdowns agree with the others and its wall-clock times are the run's.
        self.assertEqual(g.ENVELOPE_NOW, g.POPUP_NOW)
        self.assertEqual({row[3]: row[6] - g.POPUP_NOW for row in window},
                         {"usage_limit": g.USAGE_RESET_IN, "network_transient": g.RETRY_IN})
        self.assertEqual(g.CARD_RESET_AT - g.POPUP_NOW, g.USAGE_RESET_IN)
        self.assertIn("at=%d;" % int(g.POPUP_NOW * 1000), g.pinned_clock())
        # Read in UTC, as the card's reset time is, so a machine's zone cannot set them apart.
        self.assertIn("Real.prototype['get'+part]=Real.prototype['getUTC'+part]", g.pinned_clock())
        page = g.panel_html()
        self.assertLess(page.index(g.pinned_clock()), page.rindex("<script>"),
                        "the page's clock is pinned before the panel's own script reads it")
        capture = inspect.getsource(g.render_window)
        self.assertIn("seed_window_state(home, codex, now)", capture)
        self.assertIn("CODEX_AR_STILL_NOW=repr(now)", capture)

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
        with generator.frozen_registry().frozen():
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
        # What others report, beside the version (v0.6.10): the frozen stand-in's sample counts for
        # this build, so the card is photographed with its row filled in - and never in the panel's
        # summary, which is codes only.
        with generator.frozen_registry().frozen():
            expected = compat_reported.lookup(generator.CODEX_VERSION)
        self.assertEqual(view["reported"]["state"], "reported")
        self.assertEqual(view["reported"], dict(expected, state="reported"))
        self.assertNotIn("reported", panel["compatibility"])

    def test_the_reads_are_the_ones_the_window_makes(self):
        """Only questions the window's own code asks, and each photographed page's."""
        # Both halves, every file of each: the reads moved with the pages that make them.
        window = guiscan.window()
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
            for name in ("tray_popup.py", "tray_popup/window.py", "brand.py", "ui/popup/layout.py",
                         "ui/popup/win/rect.py", "ui/brand/tokens.py", "ui/tray/icon.py", "tray.py",
                         "notice_card.py"):
                (Path(root) / name).parent.mkdir(parents=True, exist_ok=True)
                (Path(root) / name).write_text("X = 1\n", encoding="utf-8")
            covered = [path.relative_to(root).as_posix()
                       for path in self.generator.popup_code_files(root)]
        self.assertEqual(covered, ["brand.py", "tray_popup.py", "tray_popup/window.py",
                                   "ui/brand/tokens.py", "ui/popup/layout.py", "ui/popup/win/rect.py"])

    def test_today_the_patterns_find_every_tracked_popup_and_palette_module(self):
        package = ROOT / "src" / "codex_auto_resume"
        found = [path.relative_to(package).as_posix()
                 for path in self.generator.popup_code_files(package)]
        tracked = sorted(srcscan.relative(path).split("/", 1)[1] for path in srcscan.package_files()
                         if re.fullmatch(r"codex_auto_resume/"
                                         r"(brand|(brand|ui/popup|ui/brand)/.+)\.py",
                                         srcscan.relative(path)))
        self.assertEqual(found, tracked)
        # Every file of each, not the one file each used to be: since v0.6.10-alpha the popup
        # is thirteen and the palette is ten - eleven since v0.6.10, with brand/design.py, which
        # decides how every design draws the popup and the card, so it is in their key too.
        self.assertEqual(len([name for name in found if name.startswith("ui/popup/")]), 13)
        self.assertEqual(len([name for name in found if name.startswith("brand/")]), 11)
        self.assertIn("brand/design.py", found)
        self.assertIn("ui/popup/renderer.py", found)
        self.assertIn("brand/tokens.py", found)

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
        # Since v0.6.10-alpha the palette is a package; `tokens.py` is the file the colours
        # themselves are in, and `colour.py` the arithmetic, so one of each is exercised here.
        popup = real_modules("brand")
        arithmetic, colours = "brand/colour.py", "brand/tokens.py"
        before = self.digest(popup)
        tree = ast.parse(popup[arithmetic])
        last = [node for node in tree.body if isinstance(node, ast.FunctionDef)][-1]
        lines = popup[arithmetic].splitlines(keepends=True)
        start = min([last.lineno] + [decorator.lineno for decorator in last.decorator_list]) - 1
        cut = "".join(lines[start:last.end_lineno])
        left = "".join(lines[:start] + lines[last.end_lineno:]) + \
            "from ..ui.brand.moved import %s\n" % last.name
        moved = dict(popup, **{arithmetic: left,
                               "ui/brand/moved.py": "from ...brand import *  # noqa\n\n" + cut})
        self.assertEqual(self.digest(moved), before)
        palette = ast.parse(popup[colours])
        token = next(node for node in palette.body if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                     and re.fullmatch(r"#[0-9A-Fa-f]{6}", node.value.value))
        rows = popup[colours].splitlines(keepends=True)
        rows[token.lineno - 1] = rows[token.lineno - 1].replace(token.value.value, "#123456", 1)
        recoloured = "".join(rows)
        self.assertNotEqual(recoloured, popup[colours])
        self.assertNotEqual(self.digest(dict(popup, **{colours: recoloured})), before)

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

    def test_what_the_popup_takes_from_win_and_ui_is_in_the_key(self):
        """Step 9, done: the popup's DLL cache and the Win32 declarations it registers its
        window with live in `win/dll.py`, and the countdown it draws in `ui/words.py`. Neither
        is one of the popup's own modules, and what it takes from each by name is in the key
        all the same - so a change to either moves the pictures, and this is where that is
        checked on the real tree rather than on a made-up one.

        The move itself left the key where it was; that was rehearsed here before it happened,
        and the rehearsal is gone because the arrangement it described is the one on disk.
        """
        package = ROOT / "src" / "codex_auto_resume"
        imported = [entry.split(" | ")[0] for entry in self.generator.imported_definitions(
            package, self.generator.popup_code_files(package))]
        for name in ("countdown", "GUID", "WNDCLASSW"):
            with self.subTest(name):
                self.assertIn(name, imported, "%s is drawn with, so it belongs in the key" % name)
        # `win.library()` is not, and should not be: the popup calls it through the package
        # rather than by name, and what it hands back is handles. Handles draw nothing; the
        # declarations above and the countdown below are what a picture depends on.

        real = real_modules("brand", "ui/tray", "ui/words.py", "win/dll.py")
        before = self.digest(real)
        for what, (name, old, new) in {
                "the countdown the popup shows": ("ui/words.py", '"%ds" % secs', '"%d s" % secs'),
                "a declaration it registers": ("win/dll.py", "C.c_ssize_t", "C.c_longlong")}.items():
            changed = dict(real)
            self.assertIn(old, changed[name], what)
            changed[name] = changed[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertNotEqual(self.digest(changed), before, what + " did not move the digest")
        # And the icon's own tooltip is still not the popup's drawing.
        changed = dict(real, **{"ui/tray/words.py":
                                real["ui/tray/words.py"].replace('"tray.title"', '"tray.name"', 1)})
        self.assertNotEqual(changed["ui/tray/words.py"], real["ui/tray/words.py"])
        self.assertEqual(self.digest(changed), before, "the icon's own tooltip is not the popup's")

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
            "a theme pictured": lambda: patch.object(g, "CARD_THEMES", ("light", "dark")),
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
        # v0.6.10-alpha: the countdown and the Win32 declarations the card's window is
        # registered with moved into ui/ and win/, and the digest follows them; so does the
        # card's window code, which notice_window.py became ui/card/ in the same release.
        return real_modules("notice_card.py", "notice_window.py", "brand",
                            "ui/tray", "ui/card", "ui/words.py", "win/dll.py")

    def test_the_patterns_cover_the_card_the_package_it_moves_into_and_the_popup_it_is_painted_by(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("notice_card.py", "notice_window.py", "notice_presence.py", "notifier.py",
                         "ui/card/view.py", "ui/card/win/layer.py", "ui/popup/layout.py", "ui/brand/tokens.py",
                         "tray_popup.py", "tray_popup/window.py", "brand.py", "tray.py", "ui/tray/icon.py"):
                (Path(root) / name).parent.mkdir(parents=True, exist_ok=True)
                (Path(root) / name).write_text("X = 1\n", encoding="utf-8")
            covered = [path.relative_to(root).as_posix() for path in self.generator.card_code_files(root)]
        self.assertEqual(covered, ["brand.py", "notice_card.py", "notice_window.py", "tray_popup.py",
                                   "tray_popup/window.py", "ui/brand/tokens.py", "ui/card/view.py",
                                   "ui/card/win/layer.py", "ui/popup/layout.py"])
        today = [path.relative_to(ROOT / "src" / "codex_auto_resume").as_posix()
                 for path in self.generator.card_code_files()]
        for name in ("notice_card.py", "notice_window.py", "ui/popup/renderer.py",
                     "brand/tokens.py"):
            self.assertIn(name, today)

    def test_a_change_to_what_draws_the_card_moves_the_digest(self):
        real = self.real()
        before = self.drawing(real)
        self.assertEqual(before, self.generator.card_drawing(),
                         "these are everything the card's digest reads today")
        for what, (name, old, new) in {
                "the card's layout": ("notice_card.py", 'button_h = px(brand.LAYOUT["button_height"])',
                                      'button_h = px(brand.LAYOUT["button_height"] + 2)'),
                "the card's own light": ("ui/card/card.py", "brand.glow(self.vm[\"status\"], age, age,",
                                         "brand.glow(self.vm[\"status\"], age + 1, age,"),
                "its floating shadow": ("notice_card.py", "DARK_ENOUGH = 0.05", "DARK_ENOUGH = 0.06"),
                "the popup's renderer it is painted by": ("ui/popup/renderer.py", "class Renderer:",
                                                          "class Renderer:\n    painted = True\n"),
                "a colour token": ("brand/tokens.py", '"canvas":  "#E9EEF4"', '"canvas":  "#E9EEF5"')}.items():
            changed = dict(real)
            self.assertIn(old, changed[name], what)
            changed[name] = changed[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertNotEqual(self.drawing(changed), before, what + " did not move the digest")

    def test_moving_the_card_into_ui_card_leaves_the_digest(self):
        """v0.6.10-alpha moves the card into `ui/card/`: its layout and its motion leave `notice_card.py`
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
                                  "SLIDE_MS, HOVER_GRACE_MS, entrance, leaving\n\n" + moved),
        })
        self.assertEqual(self.drawing(moved_files), before)


class IconMotionPictureTests(unittest.TestCase):
    """The README's GIF of the notification-area icon's motion (v0.6.5), pinned the way the card's pictures are.

    The user asked for it ("마크다운에 아이콘 GIF 있으면 좋을 거 같아"). It is the icon's own frames at the moments its
    own timer shows them, drawn by the generator and never by hand, and its manifest entry is keyed by what it
    pictures and by a digest of the definitions the frames and their schedule are made of - so it goes stale exactly
    when the motion, its numbers, the mark or its colours change, and not when the icon's menu or the popup does.
    """

    GIF = "docs/images/icon-motion.png"

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

    @staticmethod
    def chunks(data: bytes) -> list:
        """A PNG's chunks as (kind, payload), with every deflated one inflated.

        What is compared has to be the picture, not the deflate stream that carries it. The same
        bytes given to `zlib.compress` do not come back the same length from every Python: 3.14
        ships zlib-ng, which found this picture 3 bytes shorter than 3.13 did, and a test that
        compared the files byte for byte called that a stale commit. Inflating first compares what
        a viewer would see - the pixels, the frame rectangles, the delays and the order - and still
        fails the moment the generator would draw something else.
        """
        import zlib
        found, at = [], 8
        while at < len(data):
            length, kind = struct.unpack(">I4s", data[at:at + 8])
            body = data[at + 8:at + 8 + length]
            if kind == b"IDAT":
                body = zlib.decompress(body)
            elif kind == b"fdAT":
                body = body[:4] + zlib.decompress(body[4:])
            found.append((kind, body))
            at += 12 + length
        return found

    def test_it_is_small_and_exactly_what_the_generator_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "icon-motion.png"
            self.generator.render_icon_motion(target)
            written = target.read_bytes()
        committed = (ROOT / self.GIF).read_bytes()
        kinds = [kind for kind, _ in self.chunks(committed)]
        # So that a comparison of two empty lists can never be the thing that passes.
        for required in (b"IHDR", b"acTL", b"fcTL", b"IDAT", b"fdAT", b"IEND"):
            self.assertIn(required, kinds)
        self.assertEqual([kind for kind, _ in self.chunks(written)], kinds,
                         "the committed picture is not the generator's; run build/make_screenshots.py --icon")
        for index, ((kind, mine), (_, theirs)) in enumerate(zip(self.chunks(written), self.chunks(committed))):
            with self.subTest("%s #%d" % (kind.decode("ascii"), index)):
                self.assertEqual(mine, theirs,
                                 "the committed picture is not the generator's; "
                                 "run build/make_screenshots.py --icon")
        # 768 KiB since v0.6.8, from 300: attention and a failure now move for as long as they last, where each used
        # to hold still after one pulse, and a failure blinks as it sweeps, so two more of the five columns change in
        # almost every picture.
        self.assertLess(len(committed), 768 * 1024)
        # An APNG since v0.6.6: a PNG whose first frame is what a viewer without animation shows, so the
        # badge's gradient and the ring's edges keep their colours instead of sharing 255 of them.
        self.assertEqual(committed[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn(b"acTL", committed, "it is animated")
        self.assertEqual(committed[committed.index(b"acTL") + 8:committed.index(b"acTL") + 12][2:], b"\x00\x00",
                         "it loops for ever")

    def test_every_picture_is_the_icon_s_frame_at_that_moment(self):
        """Two loops of watching from two breaths before a sweep, recovering's sweeps, attention's slow breath, a
        failure's quick sweeps and paused, as the icon's rules have them at each picture's moment - never breathing
        while it travels."""
        from codex_auto_resume import brand
        from codex_auto_resume.ui import tray
        g = self.generator
        start, end = g.icon_motion_stretch()
        top = tray.ICON_MOTION["levels"] - 1
        breath, motion = brand.GLOW["monitoring_ms"], tray.ICON_MOTION
        loop = breath * (motion["breaths"] + motion["sweep_breaths"])
        self.assertEqual((start, end), (breath, 2 * loop))
        self.assertEqual((start, end), (4400, 44000))
        sweeps_at = breath * motion["breaths"] - start                  # the first sweep, in the stretch's own ms
        frames = self.made["frames"]
        self.assertEqual(sum(delay for delay, _, _ in frames), end - start)      # ms, as an APNG counts
        self.assertTrue(all(delay > 0 for delay, _, _ in frames))
        self.assertEqual(len(self.made["moments"]), len(frames))
        seen = {state: set() for state, _ in g.ICON_MOTION_LIGHTS}
        for (delay, _, shown), moment in zip(frames, self.made["moments"]):
            for state, frame in shown.items():
                seen[state].add(tuple(frame))
                with self.subTest(state=state, moment=moment):
                    if frame[0] != 0 and state != "failed":
                        self.assertEqual(frame[1], top, "a head that has left its place is at full brightness")
                    if state in ("recovering", "idle"):
                        self.assertEqual(frame[1], top, "recovering never breathes, and paused is still")
                    if state == "watching" and moment < sweeps_at - 100:
                        self.assertEqual(frame[0], 0, "no sweep while it breathes")
                    if state == "attention":
                        self.assertEqual(frame[0], 0, "attention breathes at home and never sweeps")
        # The stroke's own positions: its place and every fifteen degrees clockwise of it, to the far end.
        stroke = set(range(round(tray.ICON_SWEEP / (360.0 / motion["positions"])) + 1))
        self.assertEqual({position for position, _ in seen["watching"]}, stroke, "watching sweeps the whole stroke")
        self.assertIn((0, 0), seen["watching"], "and breathes to its low")
        self.assertEqual({position for position, _ in seen["recovering"]}, stroke)
        # A failure's sweep is twice as quick at the same frame rate: it passes some positions between frames, and
        # reaches both ends of the stroke.
        self.assertTrue({0, max(stroke)} <= {position for position, _ in seen["failed"]})
        # And it blinks as it goes (v0.6.8), far out as well as at home.
        self.assertLessEqual(min(level for _, level in seen["failed"]), top // 8)
        self.assertTrue(any(position > 0 and level < top for position, level in seen["failed"]))
        # Attention's slow breath dims most of the way down: its frames need not land on the lowest level itself.
        self.assertLessEqual(min(level for _, level in seen["attention"]), top // 8)
        self.assertEqual({position for position, _ in seen["attention"]}, {0})
        self.assertEqual(seen["idle"], {(0, top)})

    @staticmethod
    def delays(data: bytes) -> list:
        """Each picture's delay in milliseconds, read from the APNG's fcTL chunks in order.

        A GIF counted hundredths; an APNG carries a numerator and a denominator, which the writer sets
        to milliseconds over 1000 - the icon's own rates are milliseconds, so nothing is rounded away.
        """
        found, at = [], 8
        while at + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[at:at + 8])
            if kind == b"fcTL":
                numerator, denominator = struct.unpack(">HH", data[at + 28:at + 32])
                found.append(int(round(numerator * 1000.0 / (denominator or 1000))))
            at += 12 + length
        return found

    def test_no_picture_is_shorter_than_a_browser_shows_it(self):
        """Browsers - Chromium, Firefox and Safari alike - show a picture of 10 ms or less for 100 ms. The first
        GIF merged the four states' moments into hundredths of a second, and where watching's and recovering's frames
        fell 10 ms apart a picture got 10 ms: on GitHub the 9.6 s loop took about 10.95 s, with fifteen stalls, most
        of them in the turns. So moments closer than ICON_MOTION_SHORTEST are shown as one picture."""
        g = self.generator
        start, end = g.icon_motion_stretch()
        self.assertEqual(g.ICON_MOTION_SHORTEST, 2)
        made = [delay for delay, _, _ in self.made["frames"]]
        self.assertGreaterEqual(min(made), g.ICON_MOTION_SHORTEST * 10, sorted(made)[:20])
        committed = self.delays((ROOT / self.GIF).read_bytes())
        self.assertEqual(committed, made)
        self.assertEqual(sum(committed), end - start, "the loop is as long as the stretch it shows")

    def test_it_loops_without_a_jump(self):
        """The GIF starts again where its stretch ends: the same frame of every state, as watching's loop and a whole
        number of recovering's and a failure's turns have it - and attention, whose 5.6 s breath does not divide the
        stretch, within one level of 24 of the frame it began with."""
        from codex_auto_resume.ui import tray
        g = self.generator
        start, end = g.icon_motion_stretch()
        first = self.made["frames"][0][2]
        for state, _ in g.ICON_MOTION_LIGHTS:
            with self.subTest(state=state):
                moment = end if state == "watching" else end - start
                position, level = tray.icon_frame(state, moment, None)
                if state == "attention":
                    self.assertEqual(position, first[state][0])
                    self.assertLessEqual(abs(level - first[state][1]), 1)
                else:
                    self.assertEqual(tuple(first[state]), (position, level))

    def drawing(self, files):
        with tempfile.TemporaryDirectory() as root:
            for name, text in files.items():
                path = Path(root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return self.generator.icon_drawing(root)

    def real(self):
        return real_modules("ui/tray", "brand", "notice_card.py")

    def test_the_entry_moves_when_the_motion_or_the_mark_changes_and_not_otherwise(self):
        from codex_auto_resume.ui import tray
        real = self.real()
        before = self.drawing(real)
        self.assertEqual(before, self.generator.icon_drawing(), "the four modules hold everything the digest reads")
        turn_ms = '"turn_frame_ms": %d,' % tray.ICON_MOTION["turn_frame_ms"]
        glow = re.search(r'"monitoring_ms": (\d+)', real["brand/light.py"])
        moves = {
            "the way it turns": ("ui/tray/motion.py", 'ICON_SHAPE["arc_end"] - 360.0 * position', 'ICON_SHAPE["arc_end"] + 360.0 * position'),
            "the breaths before a sweep": ("ui/tray/motion.py", '"breaths": 3,', '"breaths": 4,'),
            "the sweep's slot": ("ui/tray/motion.py", '"sweep_breaths": 2,', '"sweep_breaths": 3,'),
            "how much of the slot it travels": ("ui/tray/motion.py", '"sweep_out": 0.4,', '"sweep_out": 0.45,'),
            "the pause at the far end": ("ui/tray/motion.py", '"sweep_hold": 0.025,', '"sweep_hold": 0.05,'),
            "recovering's rest at home": ("ui/tray/motion.py", '"recover_rest": 0.075,', '"recover_rest": 0.1,'),
            "how far along the stroke it goes": ("brand/mark.py", '"arc_start": 125.0, "arc_end": 55.0,',
                                                 '"arc_start": 130.0, "arc_end": 55.0,'),
            "the frame rate while it travels": ("ui/tray/motion.py", turn_ms, turn_ms.replace(",", "1,")),
            "the breath's depth": ("ui/tray/motion.py", '"dim": 0.6,', '"dim": 0.5,'),
            "the breath's rhythm": ("brand/light.py", glow.group(0), '"monitoring_ms": %d' % (int(glow.group(1)) + 100)),
            "the mark's accent": ("brand/mark.py", 'ICON_ACCENT = "#4FE0F5"', 'ICON_ACCENT = "#4FE0F6"'),
            "attention's rhythm": ("brand/light.py", '"attention_ms": 5600,', '"attention_ms": 6600,'),
            "which states breathe in place": ("ui/tray/motion.py", '"attention": "attention_ms"}', '"attention": "recovering_ms"}'),
            "how quickly a failure sweeps": ("ui/tray/motion.py", '"failed_slot": 0.5,', '"failed_slot": 0.6,'),
            "what a failure blinks on": ("ui/tray/motion.py", 'ICON_TRAVEL_BREATHS = {"failed": "failed_ms"}',
                                         'ICON_TRAVEL_BREATHS = {"failed": "attention_ms"}'),
        }
        for what, (name, old, new) in moves.items():
            changed = dict(real)
            self.assertIn(old, changed[name], what)
            changed[name] = changed[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertNotEqual(self.drawing(changed), before, what + " did not move the entry")
        stays = {
            "the icon's menu": ("ui/tray/menu.py", "MENU_OPEN, MENU_TOGGLE, MENU_STOP, MENU_PENDING = 1, 2, 3, 4",
                                "MENU_OPEN, MENU_TOGGLE, MENU_STOP, MENU_PENDING = 1, 2, 3, 5"),
            "the popup's renderer": ("ui/popup/renderer.py", "class Renderer:", "class Renderer:\n    painted = True\n"),
            "the notification card": ("notice_card.py", "DARK_ENOUGH = 0.05", "DARK_ENOUGH = 0.06"),
            "a comment on the motion": ("ui/tray/motion.py", "# The badge's own deep blue", "# The badge's deep blue"),
        }
        for what, (name, old, new) in stays.items():
            changed = dict(real)
            self.assertIn(old, changed[name], what)
            changed[name] = changed[name].replace(old, new, 1)
            with self.subTest(what):
                self.assertEqual(self.drawing(changed), before, what + " moved the entry")

    def test_moving_the_motion_into_a_module_of_its_own_leaves_the_entry(self):
        """The move this was written for has happened - the motion left `tray.py` for
        `ui/tray/motion.py` in v0.6.10-alpha, and this entry did not change - so it asks the
        same question of the next move instead: the frame table leaving `motion.py` for a file
        beside it, with the import that brings it back, is the same GIF."""
        real = self.real()
        before = self.drawing(real)
        names = ("ICON_BREATHS", "ICON_SWEEPS", "ICON_TRAVEL_BREATHS", "ICON_MOTION", "ICON_SWEEP",
                 "_breath_level", "icon_turn", "icon_frame", "icon_frame_ms", "IconFrames")
        rest, moved = PopupDrawingTests.cut(real["ui/tray/motion.py"], *names)
        moved_files = dict(real, **{
            "ui/tray/motion.py": rest + "\nfrom .frames import %s\n" % ", ".join(names),
            "ui/tray/frames.py": ("from __future__ import annotations\nimport math\n"
                                  "from ... import brand\nfrom .motion import icon_brand_state\n\n"
                                  + moved),
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


class AuditSheetTests(unittest.TestCase):
    """`make_screenshots.py --audit OUT` (v0.6.10): light and dark sheets of the four surfaces, for
    developers. Every committed picture is light, so these are the only pictures of the dark half and
    of a change before it is made - and they are written under OUT and nowhere else: never docs/,
    never assets/, never the manifest.

    Checked with the renderers stood in for, so it runs anywhere: each writes a small picture where it
    is told to, and Edge's screenshot of a sheet is a small picture too. What is checked is where
    things go, what each surface is asked for, and the sheet's own layout.
    """

    @classmethod
    def setUpClass(cls):
        cls.generator = generator()

    @staticmethod
    def published():
        """Every file under assets/ and docs/, with its size and time."""
        return {path.relative_to(ROOT).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
                for folder in ("assets", "docs") for path in (ROOT / folder).rglob("*") if path.is_file()}

    def run_audit(self, *arguments):
        """`main(["--audit", *arguments])` with every renderer stood in for; (mocks, files written)."""
        from contextlib import redirect_stdout
        import io
        from unittest.mock import MagicMock
        g = self.generator
        written = []

        def picture(target, width=12, height=8):
            target = Path(target)
            written.append(target)
            g.write_png(target, width, height, bytes(width * height * 4))

        def window(targets, theme=None):
            for target in targets.values():
                picture(target, 30, 20)
            return {page: g.dimensions(target) for page, target in targets.items()}

        def edge(argv, **_options):
            shot = next(part.split("=", 1)[1] for part in argv if part.startswith("--screenshot="))
            size = next(part.split("=", 1)[1] for part in argv if part.startswith("--window-size="))
            picture(Path(shot), *(int(value) for value in size.split(",")))

        mocks = {"render_window": MagicMock(side_effect=window),
                 "render_panel": MagicMock(side_effect=lambda target, **_options: picture(target, 20, 30)),
                 "render_popup": MagicMock(side_effect=lambda target, _locale, **_options: picture(target, 10, 16)),
                 "render_card": MagicMock(side_effect=lambda target, _locale, _theme, **_options: picture(target, 11, 7)),
                 "system_dpi": MagicMock(return_value=144),
                 "find_edge": MagicMock(return_value=Path("msedge.exe"))}
        with ExitStack() as stack:
            for name, mock in mocks.items():
                stack.enter_context(patch.object(g, name, mock))
            stack.enter_context(patch.object(g.subprocess, "run", side_effect=edge))
            stack.enter_context(redirect_stdout(io.StringIO()))
            self.assertEqual(g.main(["--audit"] + list(arguments)), 0)
        return mocks, written

    def test_it_writes_both_themes_under_out_and_nothing_else(self):
        from codex_auto_resume import l10n
        g = self.generator
        manifest, published = MANIFEST.read_bytes(), self.published()
        language = os.environ.get(l10n.ENV_LANG)
        with tempfile.TemporaryDirectory() as scratch:
            out = Path(scratch) / "before"
            mocks, written = self.run_audit(str(out))
            made = sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())
            # Every picture a renderer was told to write is under OUT; Edge's own shot of a sheet goes
            # to a temporary folder of its own and is copied in.
            for path in written:
                if path.name != "sheet.png":
                    self.assertIn(out.resolve(), path.resolve().parents, path)
            surfaces = ("card", "panel", "popup", "window-overview", "window-pending")
            self.assertEqual(made, sorted(["%s/%s.png" % (theme, stem) for theme in ("dark", "light") for stem in surfaces]
                                          + ["sheet-%s.%s" % (theme, kind) for theme in ("dark", "light")
                                             for kind in ("html", "png")]))
            # Each surface in each theme, at the window's scale, from the one fixture.
            self.assertEqual([call.kwargs["theme"] for call in mocks["render_window"].call_args_list], ["light", "dark"])
            for name in ("render_panel", "render_popup"):
                self.assertEqual([(call.kwargs["theme"], call.kwargs["scale"]) for call in mocks[name].call_args_list],
                                 [("light", 1.5), ("dark", 1.5)], name)
            self.assertEqual({call.kwargs["height"] for call in mocks["render_panel"].call_args_list},
                             {g.AUDIT_PANEL_HEIGHT})
            self.assertEqual([(call.args[2], call.kwargs["scale"], call.kwargs["themes"])
                              for call in mocks["render_card"].call_args_list],
                             [("light", 1.5, ("light", "dark")), ("dark", 1.5, ("light", "dark"))])
            # Still pictures, since the popup's and the card's move where they are made (v0.6.10): a sheet is
            # a photograph of a page, and a light moving on it would be caught wherever it happened to be.
            for name in ("render_popup", "render_card"):
                self.assertEqual([call.kwargs["moving"] for call in mocks[name].call_args_list], [False, False], name)
            # The sheet: every picture at its own size, inside the page, none over another.
            page = (out / "sheet-dark.html").read_text(encoding="utf-8")
            width, height = (int(value) for value in re.search(r"width:(\d+)px;height:(\d+)px", page).groups())
            boxes = [tuple(int(value) for value in found) for found in re.findall(
                r'<img src="[^"]+" width="(\d+)" height="(\d+)" style="left:(\d+)px;top:(\d+)px"', page)]
            self.assertEqual(len(boxes), len(surfaces))
            sources = re.findall(r'<img src="([^"]+)"', page)
            self.assertEqual(sorted(sources), sorted("dark/%s.png" % stem for stem in surfaces))
            for (w, h, left, top), source in zip(boxes, sources):
                self.assertEqual(g.png_size(out / source), (w, h), source)
                self.assertLessEqual((left + w, top + h), (width, height))
            for first, (w1, h1, x1, y1) in enumerate(boxes):
                for w2, h2, x2, y2 in boxes[first + 1:]:
                    self.assertTrue(x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1)
            self.assertIn(g.config.version(), page)
            # The heading puts POPUP_NOW over the three surfaces drawn at it, not over the window,
            # which is seeded at its own capture's moment.
            from html import escape
            title = g.audit_title("dark", "en", 1.5)
            self.assertIn(escape(title), page)
            moment = g.time.strftime("%Y-%m-%d %H:%M UTC", g.time.gmtime(g.POPUP_NOW))
            self.assertIn("the panel, popup and card at %s," % moment, title)
            self.assertIn("the window at its capture's moment", title)
            # A second run beside the first: one before-and-after sheet per theme, of the same surfaces.
            after = Path(scratch) / "after"
            self.run_audit(str(after), "--before", str(out))
            pair = (after / "pair-light.html").read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r'src="\.\./before/light/', pair)), len(surfaces))
            self.assertEqual(len(re.findall(r'src="light/', pair)), len(surfaces))
            self.assertTrue((after / "pair-dark.png").is_file())
        self.assertEqual(MANIFEST.read_bytes(), manifest, "the audit never writes the manifest")
        self.assertEqual(self.published(), published, "nor anything under assets/ or docs/")
        self.assertEqual(os.environ.get(l10n.ENV_LANG), language, "and it puts the language back")

    def test_it_refuses_to_write_where_published_pictures_live(self):
        manifest, published = MANIFEST.read_bytes(), self.published()
        for inside in (ROOT / "docs" / "images" / "audit", ROOT / "assets", ROOT / "docs"):
            with self.subTest(inside.relative_to(ROOT).as_posix()), self.assertRaises(SystemExit):
                self.run_audit(str(inside))
        self.assertEqual(MANIFEST.read_bytes(), manifest)
        self.assertEqual(self.published(), published)
        self.assertFalse((ROOT / "docs" / "images" / "audit").exists())


if __name__ == "__main__":
    unittest.main()
