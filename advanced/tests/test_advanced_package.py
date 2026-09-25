"""The advanced package on its own: what it was written for, what it ships, and that it changes
nothing yet.

Run from the repository root, with the core on the path:

    PYTHONPATH=src python -m unittest discover -s advanced/tests

The package is put on the path here as a directory of its own, which is enough to import it and,
on purpose, not enough for core to take it: core takes it only from beside itself
(src/codex_auto_resume/edition.py), and tests/test_edition.py builds that case. `golden/` holds
what the advanced edition adds to the core's golden replies; it adds nothing yet.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "tests", ROOT / "advanced" / "src", ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import editions  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.domain import plug as core  # noqa: E402
from codex_auto_resume_advanced import plug as advanced  # noqa: E402

PACKAGE_DIR = editions.ADVANCED_SRC / editions.PACKAGE
OVERLAY = editions.ADVANCED / "gui" / "window.sources"
SKILL = editions.ADVANCED / "skills" / "codex-auto-resume-advanced" / "SKILL.md"
STANDARD_SKILL = ROOT / "skills" / "codex-auto-resume" / "SKILL.md"


def given(point) -> list:
    hook = getattr(core.Plug, core.HOOKS[point])
    return [object() for _ in list(inspect.signature(hook).parameters)[1:]]


class InterfaceTests(unittest.TestCase):
    def test_it_was_written_for_the_core_beside_it(self):
        self.assertIs(type(advanced.PLUG_API), int)
        self.assertEqual(advanced.PLUG_API, core.PLUG_API)

    def test_the_number_is_written_out_and_not_taken_from_core(self):
        """A number read from core agrees with every core, and the check would prove nothing."""
        tree = ast.parse((PACKAGE_DIR / "plug.py").read_text(encoding="utf-8"))
        written = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(getattr(target, "id", None) == "PLUG_API" for target in node.targets)]
        self.assertEqual(len(written), 1)
        self.assertIsInstance(written[0].value, ast.Constant)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("PLUG_API", [alias.name for alias in node.names])

    def test_the_factory_makes_the_advanced_editions_plug(self):
        with tempfile.TemporaryDirectory() as home:
            made = advanced.create(config.Paths(home))
            self.assertIsInstance(made, core.Plug)
            self.assertNotIsInstance(made, core.DamagedPlug)
            self.assertEqual((made.edition, made.badge), (core.Edition.ADVANCED, "Advanced"))


class NeutralTests(unittest.TestCase):
    """With no capability, the advanced edition decides everything as the standard one does, and
    adds only its own surfaces: the Dashboard's bridge commands and a model's MCP tools."""

    def test_every_point_answers_as_null(self):
        with tempfile.TemporaryDirectory() as home:
            made = advanced.create(config.Paths(home))
            for point in core.Point:
                with self.subTest(point):
                    arguments = given(point)
                    self.assertIs(core.consult(made, point, *arguments),
                                  core.consult(core.NULL, point, *arguments))
            self.assertEqual(list(Path(home).iterdir()), [], "nothing was read into being")

    def test_it_adds_nothing_to_a_surface_core_already_has(self):
        with tempfile.TemporaryDirectory() as home:
            made = advanced.create(config.Paths(home))
            for surface in (core.Surface.STATUS, core.Surface.DIAGNOSTICS, core.Surface.TRAY):
                with self.subTest(surface):
                    self.assertIs(made.surface(surface, {}), core.DEFER)
            self.assertIs(made.surface(core.Surface.BRIDGE, {"command": "status", "argument": {}}),
                          core.DEFER)
            tools = made.surface(core.Surface.MCP, {"request": "tools"})["tools"]
            self.assertEqual(len(tools), 3)

    def test_nothing_in_the_package_sends(self):
        """Only core acts. The one send is core's (engine/dispatch.py); a channel this package
        names at P5 is handed it, and nothing here calls a method named `send` of anything."""
        sends = ["%s:%d" % (path.name, node.lineno) for path in sorted(PACKAGE_DIR.rglob("*.py"))
                 for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "send"]
        self.assertEqual(sends, [])

    def test_entering_the_edition_where_nothing_was_ever_on_writes_nothing(self):
        """Every capability is turned off on entry (advanced/tests/test_advanced_arming.py); where
        no advanced state was ever written, there is nothing to turn off."""
        with tempfile.TemporaryDirectory() as home:
            made = advanced.create(config.Paths(home))
            for previous in core.Edition:
                self.assertIsNone(made.edition_changed(previous))
            self.assertEqual(list(Path(home).iterdir()), [])


class ShippedFileTests(unittest.TestCase):
    """Every file under advanced/ that ships says so at the top, for the audit of the standard
    archive to look for; the package's modules are tracked, and import only the standard library,
    core and themselves."""

    def test_every_shipped_file_carries_the_sentinel_at_the_top(self):
        for name in editions.tracked(*editions.SHIPPED):
            with self.subTest(name):
                head = (ROOT / name).read_text(encoding="utf-8").splitlines()[:8]
                self.assertTrue(any(editions.SENTINEL in line for line in head))

    def test_every_module_on_disk_is_tracked(self):
        tracked = set(editions.tracked("src"))
        on_disk = {path.relative_to(ROOT).as_posix() for path in PACKAGE_DIR.rglob("*.py")
                   if "__pycache__" not in path.parts}
        self.assertEqual(on_disk - tracked, set(), "untracked, so the audit's listing misses it")
        self.assertIn("advanced/src/%s/plug.py" % editions.PACKAGE, tracked)

    def test_the_package_imports_the_standard_library_core_and_itself(self):
        allowed = set(sys.stdlib_module_names) | {"codex_auto_resume", editions.PACKAGE}
        for path in sorted(PACKAGE_DIR.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    with self.subTest(module=path.name, imports=name):
                        self.assertIn(name.split(".")[0], allowed)


class WindowOverlayTests(unittest.TestCase):
    """The advanced window's sources: listed on its own overlay, and named by no standard one."""

    def groups(self) -> dict:
        found, group = {}, None
        for line in OVERLAY.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                group = line[1:-1]
                found.setdefault(group, [])
            else:
                self.assertIsNotNone(group, "%s is listed before any [group]" % line)
                found[group].append(line)
        return found

    def test_the_overlay_is_one_group_listing_every_advanced_source(self):
        groups = self.groups()
        self.assertEqual(list(groups), ["advanced"])
        sources = {name for name in editions.tracked("gui") if name.endswith(".cs")}
        self.assertEqual(set(groups["advanced"]), sources)
        self.assertEqual(len(groups["advanced"]), len(set(groups["advanced"])))

    def test_no_standard_source_names_an_advanced_type(self):
        declared = set()
        for name in self.groups()["advanced"]:
            text = (ROOT / name).read_text(encoding="utf-8")
            declared |= set(re.findall(r"\b(?:class|struct|enum|interface)\s+(\w+)", text))
        for path in sorted((ROOT / "gui").glob("*.cs")):
            text = path.read_text(encoding="utf-8")
            for name in sorted(declared):
                with self.subTest(source=path.name, type=name):
                    self.assertIsNone(re.search(r"\b%s\b" % re.escape(name), text))


class SkillTests(unittest.TestCase):
    def frontmatter(self, path) -> dict:
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        block = text.split("---\n", 2)[1]
        return dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)

    def test_it_is_named_for_its_folder_and_beside_the_standard_skill(self):
        own, standard = self.frontmatter(SKILL), self.frontmatter(STANDARD_SKILL)
        self.assertEqual(set(own), set(standard))
        self.assertEqual(own["name"], SKILL.parent.name)
        self.assertEqual(own["name"], standard["name"] + "-advanced")
        self.assertIn(standard["name"], own["description"])

    def test_it_tells_the_model_never_to_turn_a_capability_on(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("**Never turn a capability on**", text)
        self.assertIn("only in the Dashboard", text)
        self.assertIn("Advanced - not loaded", text)
        self.assertEqual(core.DamagedPlug(core.PlugFailure.SHADOWED).badge, "Advanced - not loaded")


class GoldenTests(unittest.TestCase):
    def test_the_golden_directory_is_there_for_the_additions(self):
        self.assertTrue((Path(__file__).resolve().parent / "golden").is_dir())


if __name__ == "__main__":
    unittest.main()
