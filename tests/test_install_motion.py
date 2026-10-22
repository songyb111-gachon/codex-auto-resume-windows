"""The install motion pictures' plans (build/motion/install-*.json) and their generator (build/make_install_motion.py).

A plan says, on one clock, what a person does in the setup program's window and what the installer prints: these hold
its shape and pacing to the README motion's rhythm, its pages to a first installation's in the window's order, its
lines to the ones build/install/install.ps1 prints, in the order it prints them, each moving the window's bar as the
window reads it - and the picture-build shim out of everything that is shipped. Pure Python: nothing is compiled or
drawn here (tests/test_install_motion_window.py compiles and drives the window).
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import guiscan  # noqa: E402
import make_install_motion as motion  # noqa: E402
import make_setup  # noqa: E402
import motion_plan  # noqa: E402

FLOW = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
INSTALL_PS1 = (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
SETUP_CS = (ROOT / "build" / "setup" / "Setup.cs").read_text(encoding="utf-8")
# The one line the setup program prints itself, before install.ps1 runs (Setup.cs, InstallFrom).
SETUP_LINE = "Codex Auto Resume setup: unpacking "
# The setup window's progress lines, `progress: <step> <done>/<total>`: real counts the installer prints inside a step
# when the window asks (gui/InstallerFlow.cs, InstallerProgress). Each step's printer, the milestone line it follows,
# the indent the window receives it with (install.ps1 prints its own with two spaces; Invoke-Setup indents what the
# setup step and the health check print by four), and its fixed total where the source fixes one.
PROGRESS = re.compile(r"progress: (\w+) (\d+)/(\d+)\Z")
PLUGIN_SETUP = (ROOT / "scripts" / "plugin_setup.py").read_text(encoding="utf-8")
STATUS_PY = (ROOT / "src" / "codex_auto_resume" / "commands" / "status.py").read_text(encoding="utf-8")
COUNTED = {
    "files": (INSTALL_PS1, "Progress 'files' ", "Copying the program files into place", "  ", None),
    "plugin": (INSTALL_PS1, "Progress 'plugin' ", "Registering the Codex plugin", "  ", 3),
    "setup": (PLUGIN_SETUP, 'progress("setup", ', "Setting up the watcher", "    ",
              int(re.search(r"^SETUP_STEPS = (\d+)$", PLUGIN_SETUP, re.M).group(1))),
    "check": (STATUS_PY, 'progress("check", ', "Checking the installation", "    ",
              int(re.search(r"^DOCTOR_CHECKS = (\d+)$", STATUS_PY, re.M).group(1))),
}


def plans() -> dict:
    return {name: motion.load(name) for name in motion.PLAN_NAMES}


def milestones(table: str = "Installing") -> list:
    """(starts, place, step) of the window's table for a first installation (InstallerProgress)."""
    body = FLOW[FLOW.index("Milestone[] %s =" % table):]
    body = body[:body.index("};")]
    return [(starts, float(at), step) for starts, at, step in
            re.findall(r'new Milestone\("([^"]+)", ([0-9.]+), "([a-z_]+)"\)', body)]


def unpacked_at() -> float:
    return float(re.search(r"const double UnpackedAt = ([0-9.]+);", FLOW).group(1))


def advance(line: str, at: float, step: str) -> tuple:
    """InstallerProgress.Advance, in Python: the bar's place and step after `line`."""
    said = line.strip()
    for starts, place, named in milestones():
        if said.startswith(starts):
            return (place, named) if place > at else (at, step)
    return at, step


def ceiling() -> float:
    return float(re.search(r"const double Ceiling = ([0-9.]+);", FLOW).group(1))


def within(begun: float, done: int, total: int) -> float:
    """InstallerProgress.Within, in Python, for a first installation: `done` of `total` of the step that began at the
    milestone `begun` - that share of the gap to the next milestone, never the whole bar."""
    following = [place for _starts, place, _step in milestones() if place > begun]
    after = min(following) if following else 1.0
    return min(begun + (after - begun) * min(1.0, done / total), max(begun, ceiling()))


def labels(plan: dict) -> list:
    """[(step, ms it is shown)] as the window names the run's steps, event after event (InstallerWindow.Heard and
    Unpacking), from "starting" on."""
    at, step, shown = 0.0, "starting", []
    for event in plan["events"]:
        if "unpacked" in event:
            place = unpacked_at() * float(event["unpacked"])
            if place > at:
                at, step = place, "unpack"
        else:
            at, step = advance(event["line"], at, step)
        if shown and shown[-1][0] == step:
            shown[-1][1] += int(event["hold"])
        else:
            shown.append([step, int(event["hold"])])
    return [tuple(item) for item in shown]


class PlanTests(unittest.TestCase):
    def test_the_install_is_one_plan_in_english_and_one_in_korean_and_nothing_else_is_pictured(self):
        """The owner, 2026-10-20: the install alone is enough - the update's picture went."""
        loaded = plans()
        self.assertEqual(set(loaded), {"install-en", "install-ko"})
        english, korean = loaded["install-en"], loaded["install-ko"]
        self.assertEqual(english["output"], "docs/images/install-motion.png")
        self.assertEqual(korean["output"], "docs/images/install-motion-ko.png")
        self.assertEqual((english["locale"], korean["locale"]), ("en", "ko"))
        same = {key: value for key, value in english.items() if key not in ("name", "output", "locale")}
        other = {key: value for key, value in korean.items() if key not in ("name", "output", "locale")}
        self.assertEqual(same, other)
        self.assertEqual(sorted(path.name for path in motion.PLANS.glob("install-*.json")),
                         ["install-en.json", "install-ko.json", "install-scenes.json"])
        for name in ("README.md", "README.ko.md", "docs/GUIDE.md", "docs/GUIDE.ko.md"):
            path = ROOT / name
            if path.is_file():
                with self.subTest(name):
                    self.assertNotIn("install-update-motion", path.read_text(encoding="utf-8"))

    def test_the_manifest_lists_only_what_a_plan_makes(self):
        manifest = motion.read_manifest()
        outputs = {plan["output"] for plan in plans().values()}
        self.assertLessEqual(set(manifest["images"]), outputs)
        self.assertLessEqual(set(manifest["inputs"]), {"<install-motion:%s>" % name for name in motion.PLAN_NAMES})
        stale = {"images": {"docs/images/install-update-motion.png": {}, "docs/images/install-motion.png": {"x": 1}},
                 "inputs": {"<install-motion:install-update-en>": "a", "<install-motion:install-en>": "b"}}
        pruned = motion.prune(stale)
        self.assertEqual(pruned["images"], {"docs/images/install-motion.png": {"x": 1}})
        self.assertEqual(pruned["inputs"], {"<install-motion:install-en>": "b"})

    def test_what_a_picture_is_made_from_reads_no_korean_document(self):
        """The main tree has no *.ko.md: an input read from one moves there and the picture reads stale on main CI
        (dev CI on 4590e238, the update picture's CHANGELOG.ko.md)."""
        import make_screenshots as shots
        read = []
        real = shots.input_digest
        with mock.patch.object(shots, "input_digest", side_effect=lambda path: read.append(Path(path)) or real(path)):
            for plan in plans().values():
                motion.render_input(plan)
        self.assertTrue(read)
        self.assertEqual([path for path in read if path.name.endswith(".ko.md")], [])

    def test_it_is_the_standard_edition_framed_bare(self):
        for name, plan in plans().items():
            with self.subTest(name):
                self.assertEqual(plan["edition"], "standard")
                self.assertEqual(plan["kind"], "installer")
                canvas = plan["canvas"]
                self.assertEqual((canvas["transparent"], canvas["shadow"], canvas["theme"], canvas["design"]),
                                 (True, False, "light", "soft"))
                self.assertEqual(plan["window"]["still"], dict(motion.FIDELITY)["en"])
                self.assertLessEqual(plan["budget"]["cap"], 9000000)

    def test_the_scenes_walk_the_pages_in_the_windows_order(self):
        order = re.search(r"return new\[\] \{ (Welcome, Options, Progress, Finish) \};", FLOW)
        self.assertIsNotNone(order, "InstallerFlow.Pages no longer goes Welcome, Options, Progress, Finish")
        for name, plan in plans().items():
            with self.subTest(name):
                frames = motion_plan.expand(plan)
                self.assertEqual(dict(frames[0].window)["page"], "welcome")
                self.assertEqual(frames[0].t, 0)
                self.assertEqual(tuple(motion.walk_pages(frames, len(plan["events"]))), motion.PAGES)
                self.assertEqual(dict(frames[-1].window)["page"], "finish")

    def test_it_lasts_fifteen_to_twenty_seconds(self):
        for name, plan in plans().items():
            with self.subTest(name):
                self.assertTrue(15000 <= motion_plan.plan_end(plan) <= 20000, motion_plan.plan_end(plan))

    def test_every_click_has_the_readme_motions_rhythm(self):
        """Hover 10 and press 8 frames of 16 ms, the pointer travelling 25 - as the README motion clicks."""
        for name, plan in plans().items():
            for scene in plan["scenes"]:
                steps = scene["steps"]
                for index, step in enumerate(steps):
                    if "press" not in step:
                        continue
                    with self.subTest(name=name, scene=scene["id"]):
                        self.assertEqual((step["frames"], step["step"]), (8, 16))
                        self.assertEqual(steps[index - 1].get("hover"), step["press"])
                        self.assertEqual((steps[index - 1]["frames"], steps[index - 1]["step"]), (10, 16))
                        self.assertEqual((steps[index - 2].get("move"), steps[index - 2]["frames"]),
                                         (step["press"], 25))

    def test_every_page_holds_long_enough_to_be_read(self):
        """The owner found a hurried scene too fast (2026-10-20): each page stands at least 900 ms between what moves
        it, the Welcome and Options pages, which have text to read, at least 2.5 s, and the Finish page at least 3."""
        least = {"welcome": 2500, "options": 2500, "progress": 900, "finish": 3000}
        for name, plan in plans().items():
            frames = motion_plan.expand(plan)
            end = motion_plan.plan_end(plan)
            spans = {}
            for frame, after in zip(frames, frames[1:] + [None]):
                page = dict(frame.window)["page"]
                moving = frame.pointer[0] == "move" or dict(frame.window).get("pressed") is not None
                if not moving:
                    spans[page] = spans.get(page, 0) + ((after.t if after else end) - frame.t)
            for page, ms in least.items():
                with self.subTest(name=name, page=page):
                    self.assertGreaterEqual(spans.get(page, 0), ms)

    def test_each_step_of_the_run_is_named_long_enough_to_read(self):
        """The step labels change one after another as a real installation prints them: each named at least 900 ms
        (the moment it starts, "Starting", only shortly)."""
        for name, plan in plans().items():
            shown = labels(plan)
            with self.subTest(name):
                if shown[0][0] == "starting":
                    shown = shown[1:]
                self.assertEqual([step for step, _ms in shown],
                                 ["unpack", "codex", "prepare", "files", "plugin", "setup", "check"])
                for step, ms in shown:
                    self.assertGreaterEqual(ms, 900, step)

    def test_the_lines_are_install_ps1s_own_in_the_order_it_prints_them(self):
        for name, plan in plans().items():
            last = -1
            for event in plan["events"]:
                if "line" not in event:
                    continue
                line = event["line"].strip()
                if line.startswith(SETUP_LINE) or PROGRESS.match(line):
                    continue  # the progress lines: test_the_progress_lines_are_the_installers_real_counts
                with self.subTest(name=name, line=line):
                    if line.startswith("edition: "):
                        self.assertEqual(line, "edition: " + plan["edition"])
                        found = INSTALL_PS1.index("Write-Host ('edition: ' + $edition)")
                    elif line.startswith("[ok] Bundled Python "):
                        found = INSTALL_PS1.index("Ok ('Bundled Python ' + $runtimeVersion + ' (no system Python needed)')")
                        self.assertEqual(line, "[ok] Bundled Python %s (no system Python needed)" % python_minor())
                    elif line.startswith("[ok] "):
                        found = INSTALL_PS1.index("Ok '%s'" % line[len("[ok] "):])
                    else:
                        found = INSTALL_PS1.index("Step '%s'" % line)
                    # install.ps1's Step and Ok indent by two spaces, as the window reads them.
                    self.assertTrue(event["line"].startswith("  ") or line.startswith("edition: "))
                    self.assertGreater(found, last, "printed before the line above it")
                    last = found

    def test_the_progress_lines_are_the_installers_real_counts(self):
        """The bar in the picture fills as the window's does (owner 2026-10-21: only as far as the work is): each
        counted step shows its own progress lines, after its milestone, from the printer that prints them, with the
        indent the window gets, counting up to the step's total."""
        for name, plan in plans().items():
            milestone, said = None, {}
            for event in plan["events"]:
                text = event.get("line")
                if text is None:
                    continue
                found = PROGRESS.match(text.strip())
                if not found:
                    milestone = text.strip()
                    continue
                step, done, total = found.group(1), int(found.group(2)), int(found.group(3))
                with self.subTest(name=name, line=text):
                    self.assertIn(step, COUNTED, "a step no installer counts")
                    source, printer, after, indent, fixed = COUNTED[step]
                    self.assertIn(printer, source, "printed where the step is counted")
                    self.assertEqual(milestone, after, "inside its own step")
                    self.assertTrue(text.startswith(indent) and not text.startswith(indent + " "))
                    if fixed is not None:
                        self.assertEqual(total, fixed)
                    last_done, last_total = said.get(step, (0, total))
                    self.assertEqual(total, last_total, "one total for the whole step")
                    self.assertGreater(done, last_done, "counting up")
                    self.assertLessEqual(done, total)
                    said[step] = (done, total)
            with self.subTest(name=name):
                self.assertEqual(sorted(said), sorted(COUNTED), "every counted step shows its count")
                self.assertTrue(all(done == total for done, total in said.values()), "each count reaches its total")

    def test_the_run_begins_with_the_setup_programs_own_line_naming_its_archive(self):
        import make_release
        self.assertIn('heard("%s" + Embedded.Archive + " into " + folder.Path);' % SETUP_LINE, SETUP_CS)
        for name, plan in plans().items():
            with self.subTest(name):
                first = plan["events"][0]["line"]
                archive = make_release.archive_name(plan["edition"], motion.version())
                self.assertTrue(first.startswith(SETUP_LINE + archive + " into C:\\Users\\ExampleUser\\"), first)
                self.assertEqual(sum(1 for event in plan["events"] if event.get("line", "").startswith(SETUP_LINE)), 1)

    def test_every_line_moves_the_window_on(self):
        """A line the window does not read is a line nobody sees move anything. As InstallerWindow.Heard reads them: a
        milestone begins its step, measured from the milestone before it, and takes the bar to its place - where the
        step before was counted to its end the bar stands there already, and the step's name moves on; a progress line
        of the step under way takes the bar to its share of the gap to the next milestone (InstallerProgress.
        Progressed), or holds it at the ceiling, which only the finish passes. The run ends at the health check's last
        count, short of the whole bar."""
        for name, plan in plans().items():
            at, step, reached = 0.0, "starting", 0.0
            for event in plan["events"]:
                with self.subTest(name=name, event=event):
                    if "unpacked" in event:
                        place = unpacked_at() * float(event["unpacked"])
                        self.assertGreater(place, at)
                        at = reached = place
                    elif not event["line"].startswith(SETUP_LINE):
                        counted = PROGRESS.match(event["line"].strip())
                        if counted:
                            self.assertEqual(counted.group(1), step, "a count of the step under way")
                            after = within(reached, int(counted.group(2)), int(counted.group(3)))
                            self.assertTrue(after > at or at == ceiling(), "moves the bar, or holds it at the ceiling")
                            at = max(at, after)
                        else:
                            place, named = advance(event["line"], reached, step)
                            self.assertGreater(place, reached, "a milestone the window reads begins its step")
                            self.assertTrue(place > at or named != step, "moves the bar or the step's name")
                            reached, step, at = place, named, max(at, place)
            self.assertEqual(at, within(milestones()[-1][1], 1, 1))
            self.assertLess(at, 1.0)

    def test_the_unpacking_fills_its_share_of_the_bar(self):
        for name, plan in plans().items():
            shares = [float(event["unpacked"]) for event in plan["events"] if "unpacked" in event]
            with self.subTest(name):
                self.assertEqual(shares, sorted(shares))
                self.assertEqual(shares[-1], 1.0)
                self.assertGreaterEqual(len(shares), 8, "the bar fills smoothly, not in a jump or two")
                first_line = next(i for i, event in enumerate(plan["events"]) if "line" in event)
                self.assertTrue(all("unpacked" in event for event in plan["events"][:first_line]))

    def test_the_frames_are_the_readme_motions_cadence(self):
        for name, plan in plans().items():
            with self.subTest(name):
                self.assertEqual((plan["light_step_ms"], plan["ripple_step"]), (33, 16))
                frames, held, end = motion.schedule(plan)
                self.assertEqual(sum(held), end)
                self.assertGreaterEqual(min(held), motion_plan.SHORTEST)


def python_minor() -> str:
    import make_release
    return ".".join(make_release.PYTHON_VERSION.split(".")[:2])


class CheckTests(unittest.TestCase):
    def plan(self) -> dict:
        return copy.deepcopy(plans()["install-en"])

    def assert_refused(self, plan, words):
        with self.assertRaises(motion.PlanError) as caught:
            motion.check(plan)
        self.assertIn(words, str(caught.exception))

    def test_a_page_out_of_order_is_refused(self):
        plan = self.plan()
        plan["scenes"][1]["steps"][-1]["set"]["page"] = "progress"
        self.assert_refused(plan, "first installation")

    def test_a_finish_before_the_installer_has_said_everything_is_refused(self):
        plan = self.plan()
        plan["events"].append({"line": "  Checking the installation", "hold": 100})
        self.assert_refused(plan, "finishes after")

    def test_lines_while_the_window_is_not_installing_are_refused(self):
        plan = self.plan()
        plan["scenes"][0]["steps"].append({"set": {"progress": 1}, "hold": 100})
        self.assert_refused(plan, "only while the window is installing")

    def test_a_name_the_window_does_not_have_and_a_state_it_has_not_are_refused(self):
        plan = self.plan()
        plan["scenes"][1]["steps"][0]["move"] = "page.overview"
        self.assert_refused(plan, "nothing called")
        plan = self.plan()
        plan["scenes"][0]["steps"][0]["set"]["scroll"] = 1
        self.assert_refused(plan, "no state")

    def test_a_frame_shorter_than_a_browser_shows_and_an_event_that_is_neither_are_refused(self):
        plan = self.plan()
        plan["scenes"][1]["steps"][0]["step"] = 10
        self.assert_refused(plan, "shorter than")
        plan = self.plan()
        plan["events"][0] = {"hold": 90}
        self.assert_refused(plan, "a line the installer prints or a share unpacked")

    def test_an_events_step_names_a_span_of_the_plans_events(self):
        with self.assertRaises(motion.PlanError):
            motion.spell_events([{"id": "A", "steps": [{"events": [1, 99]}]}], [{"line": "x", "hold": 20}])
        spelled = motion.spell_events([{"id": "A", "steps": [{"events": [1, 2]}]}],
                                      [{"line": "x", "hold": 20}, {"line": "y", "hold": 30}])
        self.assertEqual(spelled[0]["steps"], [{"set": {"progress": 1}, "hold": 20}, {"set": {"progress": 2}, "hold": 30}])


class ShippedTests(unittest.TestCase):
    """The shim is picture-build only: the shipped setup program's bytes cannot change because of it."""

    def test_the_shim_is_in_no_compile_list_of_the_window_or_the_setup_programs(self):
        self.assertTrue((ROOT / motion.SHIM).is_file())
        self.assertNotIn(motion.SHIM, guiscan.window_sources())
        self.assertNotIn(motion.SHIM, guiscan.manifest())
        self.assertNotIn("InstallerRender", (ROOT / "gui" / "window.sources").read_text(encoding="utf-8"))
        self.assertNotIn(motion.SHIM, make_setup.window_sources())
        self.assertNotIn(motion.SHIM, (make_setup.SOURCE, make_setup.WINDOW))
        for name in ("build/make_setup.py", "build/make_gui.ps1", "build/make_release.py"):
            with self.subTest(name):
                self.assertNotIn("InstallerRender", (ROOT / name).read_text(encoding="utf-8"))

    def test_the_setup_build_never_hands_the_shim_to_the_compiler(self):
        """What make_setup.build gives csc, caught before csc runs: every source is the setup program's own."""
        seen = []

        def caught(arguments, **_kwargs):
            seen.extend(arguments)
            return subprocess.CompletedProcess(arguments, 1, b"", b"stopped by the test")
        archive = ROOT / "build" / "motion" / "install-en.json"          # any file: it is only read
        with mock.patch.object(make_setup, "compiler", return_value=Path("csc.exe")), \
                mock.patch.object(make_setup.subprocess, "run", side_effect=caught), \
                mock.patch.object(make_setup, "normalize_pe"):
            import tempfile
            with tempfile.TemporaryDirectory() as out, self.assertRaises(SystemExit):
                make_setup.build(archive, Path(out), "standard", "0.0.0")
        sources = [Path(item).name for item in seen if item.endswith(".cs")]
        self.assertIn("Setup.cs", sources)
        self.assertIn("InstallerWindow.cs", sources)
        self.assertNotIn(Path(motion.SHIM).name, sources)

    def test_the_shim_is_not_a_gui_source_and_is_compiled_only_by_the_generator(self):
        self.assertFalse((ROOT / "gui" / Path(motion.SHIM).name).exists())
        users = [path.name for path in list((ROOT / "build").glob("*.py")) + list((ROOT / "build").glob("*.ps1"))
                 + list((ROOT / "scripts").glob("*.py")) if "InstallerRender" in path.read_text(encoding="utf-8")]
        self.assertEqual(users, ["make_install_motion.py"])

    def test_the_generator_compiles_the_setup_programs_own_list_and_the_shim(self):
        seen = []

        def caught(arguments, **_kwargs):
            seen.extend(arguments)
            return subprocess.CompletedProcess(arguments, 1, b"", b"stopped by the test")
        import tempfile
        with mock.patch.object(make_setup, "compiler", return_value=Path("csc.exe")), \
                mock.patch.object(motion.subprocess, "run", side_effect=caught), \
                tempfile.TemporaryDirectory() as work, self.assertRaises(RuntimeError):
            motion.compile_shim(Path(work))
        sources = [item for item in seen if item.endswith(".cs")]
        wanted = [str(ROOT / name) for name in [motion.SHIM, make_setup.SOURCE, make_setup.WINDOW]
                  + make_setup.window_sources()]
        self.assertEqual(sources[:len(wanted)], wanted)
        self.assertEqual([Path(item).name for item in sources[len(wanted):]],
                         ["Setup.VersionInfo.cs", "Setup.Embedded.cs"])
        self.assertIn("/main:" + motion.ENTRY, seen)

    def test_the_shim_drives_the_window_only_through_doors_it_has(self):
        """What the shim reaches for in the window, each still there: its pages, its primary button, the flow the setup
        program makes, its words and speaker, the light's state and the button's own faces."""
        window = guiscan.type_body("InstallerWindow")
        self.assertIn("internal string Page", window)
        self.assertIn("AcceptButton = forward;", window)
        self.assertIn("internal delegate InstallerWords Speaker(string language);", window)
        self.assertIn("internal delegate int Runner(InstallerFlow flow, Action<string> line, Action<double> unpacked);",
                      window)
        setup = (ROOT / make_setup.WINDOW).read_text(encoding="utf-8")
        self.assertIn("internal static InstallerFlow FlowFor(string[] arguments, string home, string edition, "
                      "string installed, string version,", setup)
        button = guiscan.type_body("SoftButton")
        self.assertIn("private bool primary, danger, hover, pressed;", button)
        self.assertIn("private void Press(bool down)", button)
        self.assertIn("internal string State", guiscan.type_body("HaloDot"))
        self.assertIn("internal static double StillLightMs", guiscan.controls())


class MadeTests(unittest.TestCase):
    def test_a_made_picture_is_the_bytes_its_manifest_records_from_the_inputs_it_records(self):
        manifest = motion.read_manifest()
        for name, plan in plans().items():
            output = ROOT / plan["output"]
            with self.subTest(name):
                if not output.exists():
                    self.assertNotIn(plan["output"], manifest["images"])
                    continue
                recorded = manifest["images"].get(plan["output"])
                self.assertIsNotNone(recorded, "%s is not in %s" % (plan["output"], motion.MANIFEST.name))
                self.assertEqual(recorded["sha256"], hashlib.sha256(output.read_bytes()).hexdigest(),
                                 "the picture is not the one made: run build/make_install_motion.py")
                self.assertEqual(manifest["inputs"].get("<install-motion:%s>" % name), motion.render_input(plan),
                                 "what %s is made from moved: run build/make_install_motion.py" % plan["output"])
                self.assertLessEqual(recorded["bytes"], plan["budget"]["cap"])
                self.assertTrue(manifest["fidelity"] and all(result["passed"] for result in manifest["fidelity"].values()),
                                "it was made from a window that is not the captured one")

    def test_what_a_picture_is_made_from_moves_with_its_plan_the_setup_window_and_its_code(self):
        import make_screenshots as shots
        plan = plans()["install-en"]
        before = motion.render_input(plan)
        self.assertEqual(motion.render_input(copy.deepcopy(plan)), before)
        moved = copy.deepcopy(plan)
        moved["scenes"][0]["steps"][0]["hold"] += 100
        self.assertNotEqual(motion.render_input(moved), before)
        real = shots.input_digest
        for path in ("gui/InstallerWindow.cs", "build/setup/SetupWindow.cs", "src/codex_auto_resume/locales/en.json",
                     motion.SHIM, "build/motion_compose.py"):
            with self.subTest(path), mock.patch.object(
                    shots, "input_digest", side_effect=lambda p, path=path: "moved" if Path(p) == ROOT / path else real(p)):
                self.assertNotEqual(motion.render_input(plan), before)


class FrameTests(unittest.TestCase):
    """The captured still's caption and corners round a client area of any height."""

    def still(self, width=4, caption=2, client=3):
        height = caption + client
        rgb = bytes((7,)) * (width * height * 3)
        alpha = bytearray(b"\xff" * (width * height))
        alpha[(height - 1) * width] = alpha[(height - 1) * width + width - 1] = 0
        return width, height, rgb, bytes(alpha)

    def test_the_caption_and_the_rounded_corners_go_round_a_taller_client(self):
        width, height, rgb, alpha = motion.framed_still(self.still(), 2, (4, 6))
        self.assertEqual((width, height), (4, 8))
        self.assertEqual(rgb[:2 * 4 * 3], bytes((7,)) * 24)
        self.assertEqual(alpha[-4:], b"\x00\xff\xff\x00")
        self.assertEqual(alpha[:-4], b"\xff" * 28)
        self.assertEqual(motion.corner_rows(self.still()), 1)

    def test_a_still_of_another_width_is_not_the_window(self):
        with self.assertRaises(ValueError):
            motion.framed_still(self.still(), 2, (5, 3))


if __name__ == "__main__":
    unittest.main()
