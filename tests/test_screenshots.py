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

Two kinds of input, and the difference matters:

* The **panel** is hashed by the markup it renders. That cannot fall behind - the version,
  the settings schema, the fields a pending row carries and the palette all reach the HTML
  wherever in the package they live - and editing a comment cannot fire it.
* The **window** is a compiled application, so its inputs are a list, and a list is exactly
  what went wrong the first time: seven files named, five that change the picture missed.
  It is as short as it can be, and a comment in `SettingsApp.cs` will fire this check
  unnecessarily. That cost is real and it is the smaller one.

So this fires whenever something the picture is drawn from changed - not, as an earlier
version of this paragraph claimed, exactly when the picture stopped being true.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "assets" / "screenshots.json"

# The canonical asset on the left, the documentation copy on the right. One render, two
# files, copied by the generator - not two captures kept in step by hand.
# The canonical asset on the left, the documentation copy on the right, per locale. One
# render, two files, copied by the generator - not two captures kept in step by hand.
#
# English keeps the plain names because the plugin card ships that pair: a catalogue entry
# has one set of screenshots and the product's own interface language there is English.
COPIES = {
    "en": {
        "assets/screenshot-panel.png": "docs/images/settings-panel.png",
        "assets/screenshot-settings.png": "docs/images/settings-window.png",
    },
    "ko": {
        "assets/screenshot-panel-ko.png": "docs/images/settings-panel-ko.png",
        "assets/screenshot-settings-ko.png": "docs/images/settings-window-ko.png",
    },
}
ALL_COPIES = {canonical: copy
              for pairs in COPIES.values() for canonical, copy in pairs.items()}

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
        self.assertIn("<panel render>", self.manifest["inputs"])
        html = self.generator().panel_html()
        # The seed data the panel is rendered from. The visible strings are assembled by
        # the panel's own script in the browser, so what the markup carries is the JSON.
        for expected in ('"version": "%s"' % self.manifest["version"],
                         '"state": "waiting_reset"',
                         '"retry_timing"'):
            self.assertTrue(expected in html, "the rendered panel does not carry " + expected)

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
        declared = {name.lstrip("./") for name in manifest["interface"]["screenshots"]}
        self.assertEqual(declared, set(COPIES["en"]),
                         "the plugin card and this test disagree about which images ship")

    def test_each_readme_shows_its_own_locale(self):
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


if __name__ == "__main__":
    unittest.main()
