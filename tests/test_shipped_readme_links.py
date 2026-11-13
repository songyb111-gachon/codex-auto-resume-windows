"""The README an archive carries links only to what the archive carries, or to GitHub at the release's tag (v0.6.23 final).

The shipped README is the repository's, copied. Its relative links and pictures name the guide and the pictures under
docs/images/, which the archive does not carry (the 2026-11-12 size audit counted them), so on a person's PC they led
nowhere. build/make_release.py absolute_links now rewrites, in the archive's copy only, each relative link whose target
the archive does not carry: a document to https://github.com/<repository>/blob/v<version>/<path>, a picture to
.../raw/v<version>/<path>. What the archive carries stays relative. collect_app does it, and both editions go through
collect_app (tests/test_edition_build.py holds the order).

Nothing here reaches the network, an installation or the registry; every build step writes into a temporary directory.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import languages  # noqa: E402

MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
REPOSITORY = "https://github.com/songyb111-gachon/codex-auto-resume-windows"
# Written apart from make_release's own pattern, so the test does not agree with the code by sharing its mistake.
TARGETS = (re.compile(r"\]\(\s*<?([^)\s>]+)"), re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']"""),
           re.compile(r"^\[[^\]\n]+\]:[ \t]*(\S+)", re.MULTILINE))


def builder():
    spec = importlib.util.spec_from_file_location("make_release_readme_links", ROOT / "build" / "make_release.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def targets_of(text: str) -> list:
    return [found for pattern in TARGETS for found in pattern.findall(text)]


def relative(target: str) -> bool:
    return bool(target) and not target.startswith("#") and not re.match(r"[A-Za-z][A-Za-z0-9+.-]*:|//", target)


class AbsoluteLinksTests(unittest.TestCase):
    """The rewrite itself, on text of its own."""

    CARRIED = {"LICENSE", "docs/PRIVACY.md"}

    def setUp(self):
        self.make = builder()

    def rewrite(self, text):
        return self.make.absolute_links(text, "2.1.0-beta.3", self.CARRIED)

    def test_a_document_the_archive_does_not_carry_is_a_blob_address_at_the_tag(self):
        self.assertEqual(self.rewrite("[the guide](docs/GUIDE.md)"),
                         "[the guide](%s/blob/v2.1.0-beta.3/docs/GUIDE.md)" % REPOSITORY)

    def test_a_picture_the_archive_does_not_carry_is_a_raw_address_at_the_tag(self):
        self.assertEqual(self.rewrite('<img src="docs/images/a.png" width="9">'),
                         '<img src="%s/raw/v2.1.0-beta.3/docs/images/a.png" width="9">' % REPOSITORY)
        self.assertEqual(self.rewrite("![x](assets/logo-motion.png)"),
                         "![x](%s/raw/v2.1.0-beta.3/assets/logo-motion.png)" % REPOSITORY)

    def test_what_the_archive_carries_stays_relative(self):
        for text in ("[privacy](docs/PRIVACY.md)", '<a href="LICENSE">l</a>', "[l](LICENSE)", "[p](docs/PRIVACY.md#top)"):
            self.assertEqual(self.rewrite(text), text)

    def test_an_address_and_a_link_inside_the_page_stay_as_they_are(self):
        for text in ('<a href="#install">', "[why](#why)", "[g](https://example.org/a/b.md)",
                     '<img src="https://img.shields.io/a.png">', "[m](mailto:a@example.org)", "[r](/abs/path.md)"):
            self.assertEqual(self.rewrite(text), text)

    def test_a_fragment_and_a_title_survive_and_a_dotted_path_is_resolved(self):
        self.assertEqual(self.rewrite("[g](docs/GUIDE.md#languages)"),
                         "[g](%s/blob/v2.1.0-beta.3/docs/GUIDE.md#languages)" % REPOSITORY)
        self.assertEqual(self.rewrite('![i](docs/images/a.png "title")'),
                         '![i](%s/raw/v2.1.0-beta.3/docs/images/a.png "title")' % REPOSITORY)
        self.assertEqual(self.rewrite("[g](docs/images/../GUIDE.md)"),
                         "[g](%s/blob/v2.1.0-beta.3/docs/GUIDE.md)" % REPOSITORY)

    def test_a_reference_definition_is_rewritten_too(self):
        self.assertEqual(self.rewrite("[ref]: docs/EDITIONS.md\n"),
                         "[ref]: %s/blob/v2.1.0-beta.3/docs/EDITIONS.md\n" % REPOSITORY)

    def test_line_endings_and_everything_else_are_kept(self):
        text = "line one\r\n[a](docs/GUIDE.md) and [b](docs/PRIVACY.md)\r\nline three\r\n"
        out = self.rewrite(text)
        self.assertEqual(out.count("\r\n"), 3)
        self.assertEqual(out.replace("%s/blob/v2.1.0-beta.3/" % REPOSITORY, ""), text)


@unittest.skipIf(languages.generated_ko_branch(), "the generated ko branch's README is the Korean text; nothing ships from ko")
class StagedReadmeTests(unittest.TestCase):
    """The README as collect_app writes it into the payload."""

    @classmethod
    def setUpClass(cls):
        cls.make = builder()
        cls.version = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["version"]
        cls.source = (ROOT / "README.md").read_bytes()
        with tempfile.TemporaryDirectory(prefix="car-readme-links-") as work:
            stage = Path(work)
            cls.make.collect_app(stage)
            app = stage / "payload" / "app"
            cls.carried = {path.relative_to(app).as_posix() for path in app.rglob("*") if path.is_file()}
            cls.shipped = (app / "README.md").read_bytes().decode("utf-8")
            if (ROOT / "advanced").is_dir():
                cls.make.collect_advanced(stage)
                cls.shipped_advanced = (app / "README.md").read_bytes().decode("utf-8")
            else:
                cls.shipped_advanced = cls.shipped

    def test_no_relative_link_names_a_path_the_archive_does_not_carry(self):
        found = [target for target in targets_of(self.shipped) if relative(target)]
        self.assertTrue(found, "the shipped README links nothing of the archive at all")
        loose = sorted(target for target in found if re.split(r"[#?]", target)[0] not in self.carried)
        self.assertEqual(loose, [], "the shipped README links paths the archive does not carry")

    def test_every_rewritten_address_names_this_versions_tag_and_a_file_of_the_repository(self):
        before = set(targets_of(self.source.decode("utf-8")))
        rewritten = sorted(set(targets_of(self.shipped)) - before)
        self.assertGreater(len(rewritten), 5, "the README's pictures are not rewritten")
        for address in rewritten:
            match = re.fullmatch(re.escape(REPOSITORY) + r"/(raw|blob)/v([^/]+)/([^#?]+)", address)
            self.assertIsNotNone(match, address)
            kind, tag, path = match.groups()
            self.assertEqual(tag, self.version, address)
            self.assertTrue((ROOT / path).is_file(), "%s is not a file of the repository" % address)
            self.assertEqual(kind, "raw" if path.endswith(".png") else "blob", address)

    def test_what_the_archive_carries_is_still_linked_relative(self):
        shipped = set(targets_of(self.shipped))
        for name in ("docs/PRIVACY.md", "docs/SECURITY.md", "docs/SUPPORT.md", "LICENSE"):
            self.assertIn(name, shipped)

    def test_the_repositorys_own_readme_is_not_touched(self):
        self.assertEqual((ROOT / "README.md").read_bytes(), self.source)
        self.assertIn("docs/images/", self.source.decode("utf-8"))
        self.assertNotIn("/raw/v", self.source.decode("utf-8"))

    def test_both_editions_carry_the_same_readme(self):
        self.assertEqual(self.shipped_advanced, self.shipped)

    def test_only_links_differ_from_the_repositorys_readme(self):
        out = self.shipped
        for address in set(targets_of(out)) - set(targets_of(self.source.decode("utf-8"))):
            out = out.replace(address, "")
        # What is left of each rewritten target is the path it had, which the original also holds.
        original = self.source.decode("utf-8")
        for address in set(targets_of(original)) - set(targets_of(self.shipped)):
            original = original.replace(address, "")
        self.assertEqual(out.replace("\r\n", "\n"), original.replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()
