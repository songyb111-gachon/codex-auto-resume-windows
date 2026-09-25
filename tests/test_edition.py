"""Which edition an installation is, and the plug it runs with.

The advanced edition is the standard edition plus one package, found beside the core package
(src/codex_auto_resume/edition.py) and reached only through the plug interface
(src/codex_auto_resume/domain/plug.py). Four things are held here:

* NULL, the standard edition's plug, answers every point exactly as core would alone, and a
  hook's answer is only ever taken from its point's closed set - and core, which holds a plug
  only as `Guarded`, takes nothing else from one;
* the loader takes the package only from beside core and only as it should be - anything else
  is the standard edition, or an advanced one that says it is not loaded;
* a run of this suite tests the edition it says it does (StandardRunGuard), and CI runs it once
  for each edition (EditionLaneTests);
* core names the package in one place, and nothing the standard build copies names it at all.

The loader's cases run in a child Python on a copy of src/ with the package put beside it
(tests/editions.py), so this process - the standard edition's - never imports it.
"""
from __future__ import annotations

import contextlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan and editions live next to this file

import editions  # noqa: E402
import srcscan  # noqa: E402
from codex_auto_resume import cli, config, edition, logbook, shortcut, startup  # noqa: E402
from codex_auto_resume.domain import plug  # noqa: E402
from codex_auto_resume.domain.plug import (DEFER, NULL, Alternative, DamagedPlug, Edition,  # noqa: E402
                                           Guarded, Plug, PlugFailure, Point, Surface, guard)

ROOT = srcscan.ROOT
WORKFLOWS = ROOT / ".github" / "workflows"
# Files the standard build copies that may spell the advanced package's name besides
# src/codex_auto_resume/edition.py, each with why. The installer spells it too, from build/install/,
# which is no tree of the ones checked here; build/edition_audit.py's ALLOWED holds all three as
# entries of the standard archive.
NAMED_BY: dict = {
    "scripts/bootstrap.ps1": "tells which edition a tree is by whether the package is in it, and "
                             "which edition an archive is before it unpacks it",
}


def arguments(point) -> list:
    """One distinct object for each argument the point's hook takes."""
    hook = getattr(Plug, plug.HOOKS[point])
    return [object() for _ in list(inspect.signature(hook).parameters)[1:]]


class NullPlugTests(unittest.TestCase):
    def test_every_point_has_one_hook_and_the_interface_defines_it(self):
        self.assertEqual(set(plug.HOOKS), set(Point))
        self.assertEqual(len(set(plug.HOOKS.values())), len(plug.HOOKS), "two points, one hook")
        for point, hook in plug.HOOKS.items():
            with self.subTest(point):
                self.assertTrue(callable(getattr(Plug, hook, None)))

    def test_null_defers_everywhere_and_hands_the_sender_back_its_backend(self):
        """The standard edition's plug is core with no plug: DEFER at every point but the
        sender, where the one send goes to the backend core was given, the very same object."""
        for point in Point:
            with self.subTest(point):
                given = arguments(point)
                answer = getattr(NULL, plug.HOOKS[point])(*given)
                if point is Point.SENDER:
                    self.assertIs(answer, given[-1])
                else:
                    self.assertIs(answer, DEFER)

    def test_null_is_the_standard_edition_and_cannot_be_changed(self):
        self.assertIs(type(NULL), Plug)
        self.assertEqual((NULL.edition, NULL.badge), (Edition.STANDARD, "Standard"))
        with self.assertRaises(AttributeError):
            NULL.anything = 1
        with self.assertRaises(AttributeError):
            NULL.edition = Edition.ADVANCED
        for previous in Edition:
            self.assertIsNone(NULL.edition_changed(previous))

    def test_a_damaged_plug_is_null_with_a_badge_that_says_so(self):
        for reason in PlugFailure:
            damaged = DamagedPlug(reason)
            with self.subTest(reason):
                self.assertEqual((damaged.edition, damaged.badge, damaged.reason),
                                 (Edition.ADVANCED, "Advanced - not loaded", reason))
                for point in Point:
                    given = arguments(point)
                    self.assertIs(plug.consult(damaged, point, *given), plug.consult(NULL, point, *given))
        with self.assertRaises(ValueError):
            DamagedPlug("tired")

    def test_the_interface_has_a_version(self):
        self.assertIs(type(plug.PLUG_API), int)
        self.assertGreaterEqual(plug.PLUG_API, 1)


class RecordingPlug(Plug):
    """Answers whatever it is told to, per hook."""
    __slots__ = ("answers",)

    def __init__(self, **answers):
        self.answers = answers

    def __getattribute__(self, name):
        answers = object.__getattribute__(self, "answers")
        if name in answers:
            answer = answers[name]
            if isinstance(answer, Exception):
                def hook(*_):
                    raise answer
                return hook
            return lambda *_: answer
        return object.__getattribute__(self, name)


class ClosedAlternativeTests(unittest.TestCase):
    def test_a_decision_point_takes_only_its_own_closed_set(self):
        for answer in ("release", "defer", "HOLD ", 1, None, True, ["hold"], {"hold": 1}, object()):
            with self.subTest(answer=answer):
                self.assertIs(plug.consult(RecordingPlug(gate=answer), Point.GATES, 1, 2, 3), DEFER)
        taken = plug.consult(RecordingPlug(gate="hold"), Point.GATES, 1, 2, 3)
        self.assertIs(taken, Alternative.HOLD)
        # A word of another point is no word here: nothing at all relaxes a start yet.
        self.assertIs(plug.consult(RecordingPlug(start_route=Alternative.HOLD), Point.START_ROUTE, 1), DEFER)

    def test_every_decision_point_accepts_a_restriction_or_nothing(self):
        """A hook may always restrict and may relax only as core has learned to carry out, which
        is not at all yet. A relaxation joins its point's set in the commit that teaches core to
        carry it out, and this test changes with it. v0.6.11-alpha: the claim ledger holds a
        claim as a gate holds a record; a record served, a follow-up, a route, a division of the
        due records and a restart are asked for, and none is carried out."""
        self.assertEqual(plug.ANSWERS, plug.RESTRICTIONS)
        self.assertEqual(plug.ANSWERS, frozenset(Alternative))
        for point, accepted in plug.ALTERNATIVES.items():
            with self.subTest(point):
                self.assertIn(point, Point)
                self.assertLessEqual(accepted, plug.RESTRICTIONS)
        self.assertEqual({point for point, accepted in plug.ALTERNATIVES.items() if accepted},
                         {Point.GATES, Point.SCHEDULE, Point.CLAIM_LEDGER})
        self.assertEqual({point for point, accepted in plug.ALTERNATIVES.items() if not accepted},
                         {Point.RECORDS, Point.OUTCOME, Point.START_ROUTE, Point.CONCURRENCY,
                          Point.SUPERVISION})
        for point, accepted in plug.ALTERNATIVES.items():
            for answer in ([object()], {"records": []}, "go", Alternative.HOLD):
                if answer is Alternative.HOLD and answer in accepted:
                    continue
                with self.subTest(point=point, answer=answer):
                    asked = RecordingPlug(**{plug.HOOKS[point]: answer})
                    self.assertIs(plug.consult(asked, point, *arguments(point)), DEFER)

    def test_a_hook_that_raises_gets_nulls_answer(self):
        backend = object()
        failing = RecordingPlug(sender=RuntimeError("x"), gate=ValueError("y"), text=KeyError("z"))
        self.assertIs(plug.consult(failing, Point.SENDER, object(), backend), backend)
        self.assertIs(plug.consult(failing, Point.GATES, 1, 2, 3), DEFER)
        self.assertIs(plug.consult(failing, Point.TEXT, 1, "words"), DEFER)

    def test_a_value_point_hands_the_value_on_for_core_to_check(self):
        self.assertEqual(plug.consult(RecordingPlug(text="words"), Point.TEXT, 1, "core's"), "words")
        self.assertIs(plug.consult(NULL, Point.TEXT, 1, "core's"), DEFER)

    def test_an_unknown_point_is_a_mistake_not_a_deferral(self):
        with self.assertRaises(ValueError):
            plug.consult(NULL, "classify", 1)

    def test_a_failing_hook_is_reported_with_its_point(self):
        told = []
        self.assertIs(plug.consult(RecordingPlug(gate=ValueError("y")), Point.GATES, 1, 2, 3,
                                   failed=told.append), DEFER)
        self.assertEqual(told, [Point.GATES])
        plug.consult(NULL, Point.GATES, 1, 2, 3, failed=told.append)
        self.assertEqual(told, [Point.GATES], "a hook that answered is no failure")


class GuardTests(unittest.TestCase):
    """How core holds a plug: `Guarded`, which asks every hook through `consult` and takes only
    values core can use."""

    def test_the_guard_asks_every_hook_the_plug_has_with_the_same_arguments(self):
        for point, hook in plug.HOOKS.items():
            with self.subTest(point):
                ours = inspect.signature(getattr(Guarded, hook))
                theirs = inspect.signature(getattr(Plug, hook))
                self.assertEqual(list(ours.parameters), list(theirs.parameters))

    def test_guarded_null_answers_as_null_everywhere(self):
        guarded = guard(None)
        self.assertIs(guarded.plug, NULL)
        self.assertTrue(guarded.null)
        self.assertEqual((guarded.edition, guarded.badge), (Edition.STANDARD, "Standard"))
        for point in Point:
            with self.subTest(point):
                given = arguments(point)
                if point is Point.SURFACES:
                    given[0] = Surface.STATUS
                answer = getattr(guarded, plug.HOOKS[point])(*given)
                if point is Point.SENDER:
                    self.assertIs(answer, given[-1])
                elif point is Point.TICK:
                    self.assertIsNone(answer, "a tick's answer is not read")
                else:
                    self.assertIs(answer, DEFER)
        self.assertEqual(guarded.failures, 0)

    def test_a_guard_is_made_once_and_holds_only_plugs(self):
        guarded = guard(NULL)
        self.assertIs(guard(guarded), guarded)
        self.assertIs(guard(object()).plug, NULL, "something that is not a plug is no plug")
        damaged = guard(DamagedPlug(PlugFailure.SHADOWED))
        self.assertFalse(damaged.null, "a damaged plug is asked, and answers as NULL")
        self.assertEqual(damaged.badge, "Advanced - not loaded")

    def test_a_hook_that_raises_is_counted_and_costs_only_its_answer(self):
        backend = object()
        failing = guard(RecordingPlug(**{hook: RuntimeError("x") for hook in plug.HOOKS.values()}))
        self.assertIs(failing.sender(object(), backend), backend)
        self.assertIs(failing.gate("usage", {}, {}), DEFER)
        self.assertIs(failing.claim_ledger(object(), {}, 1.0), DEFER)
        self.assertIsNone(failing.tick(object()))
        self.assertIs(failing.surface(Surface.STATUS, {}), DEFER)
        self.assertEqual(failing.failures, 5)

    def test_a_sender_is_something_with_a_send_or_it_is_the_backend(self):
        backend = object()

        class Channel:
            def __init__(self):
                self.calls = []

            def send(self, thread_id, prompt, *, launch_guard=None):
                with launch_guard as permitted:
                    self.calls.append((thread_id, prompt, permitted))
                return {"outcome": "unknown"}

        class Lookup:
            @property
            def send(self):
                raise RuntimeError("no")

        channel = Channel()
        held = guard(RecordingPlug(sender=channel)).sender({}, backend)
        self.assertIsNot(held, backend)
        self.assertIs(guard(RecordingPlug(sender=backend)).sender({}, backend), backend)
        # The channel is called only inside the launch guard core hands the send, and only while
        # it permits; it is handed a guard already held.
        entered = []

        @contextlib.contextmanager
        def launch_guard(permitted):
            entered.append(permitted)
            yield permitted
        self.assertEqual(held.send("t", "p", launch_guard=launch_guard(True)), {"outcome": "unknown"})
        self.assertEqual(held.send("t", "p", launch_guard=launch_guard(False)),
                         {"outcome": "not_started", "error_code": "queue_consent_refused"})
        self.assertEqual((entered, channel.calls), ([True, False], [("t", "p", True)]))
        for answer in (None, "backend", object(), Lookup(), type("NotCallable", (), {"send": 1})()):
            with self.subTest(answer=answer):
                self.assertIs(guard(RecordingPlug(sender=answer)).sender({}, backend), backend)

    def test_a_strange_answer_is_a_failure_or_nothing_and_never_escapes_the_guard(self):
        """An answer's own hashing, comparison and iteration are the plug's code running. At a
        decision point one that raises is a hook that failed; at a surface it is nothing - a
        surface is get_status and the Dashboard, which no answer may break."""
        class Weird:
            def __hash__(self):
                raise ValueError("no hash")

            def __eq__(self, other):
                raise ValueError("no comparison")

        class Iterating(dict):
            def __iter__(self):
                raise RuntimeError("iteration broke")

            def items(self):
                raise RuntimeError("items broke")

        class Word(str):
            pass

        weird = guard(RecordingPlug(gate=Weird()))
        self.assertIs(weird.gate("usage", {}, {}), DEFER)
        self.assertEqual(weird.failures, 1)
        for answer in (Iterating(a=1), {"a": Iterating(b=1)}, {Word("a"): 1}):
            with self.subTest(answer=type(answer).__name__):
                self.assertIs(guard(RecordingPlug(surface=answer)).surface(Surface.STATUS, {}), DEFER)

    def test_words_are_words(self):
        self.assertEqual(guard(RecordingPlug(text="go on")).text({}, "core's"), "go on")
        for answer in (None, 1, ["go on"], b"go on"):
            with self.subTest(answer=answer):
                self.assertIs(guard(RecordingPlug(text=answer)).text({}, "core's"), DEFER)

    def test_a_surface_takes_a_json_object_and_nothing_else(self):
        """Copied through strict JSON, so a plug can neither break a reply's writer nor change a
        reply after it was made."""
        kept = {"on": 1, "names": ["a"], "nested": {"x": None}}
        taken = guard(RecordingPlug(surface=kept)).surface(Surface.STATUS, {})
        self.assertEqual(taken, kept)
        self.assertIsNot(taken, kept)
        kept["names"].append("b")
        self.assertEqual(taken["names"], ["a"])
        self.assertEqual(guard(RecordingPlug(surface={"mode": Edition.ADVANCED})).surface("status", {}),
                         {"mode": "advanced"})
        for answer in ([1], "on", {1: "x"}, {"x": float("nan")}, {"x": object()}, {"x": {1, 2}}):
            with self.subTest(answer=answer):
                self.assertIs(guard(RecordingPlug(surface=answer)).surface(Surface.STATUS, {}), DEFER)
        with self.assertRaises(ValueError):
            guard(NULL).surface("popup", {})

    def test_the_guard_names_the_surface_in_its_own_word(self):
        seen = []

        class Seeing(Plug):
            __slots__ = ()

            def surface(self, name, facts):
                seen.append(name)
                return DEFER

        guard(Seeing()).surface("bridge", {})
        self.assertEqual(seen, [Surface.BRIDGE])
        self.assertIs(type(seen[0]), Surface)


class EditionBadgeTests(unittest.TestCase):
    """The badge (decision C12): a word where the version already appears - the CLI status line
    here. It says nothing in the standard edition, where nothing can be armed, so a standard
    status is exactly what it was; an advanced installation shows its badge, and the count of
    what is armed when its package loaded."""

    def line(self, made):
        from codex_auto_resume.commands.status import _edition_line
        return _edition_line(guard(made))

    def test_the_standard_edition_shows_no_edition_line(self):
        self.assertIsNone(self.line(NULL))

    def test_a_loaded_advanced_edition_shows_the_badge_and_the_armed_count(self):
        class Loaded(Plug):
            __slots__ = ()
            edition = Edition.ADVANCED
            badge = "Advanced"

            def surface(self, name, facts):
                return {"edition": "advanced", "on": 2} if name == Surface.STATUS else DEFER

        self.assertEqual(self.line(Loaded()), "Advanced (2 armed)")

    def test_an_advanced_edition_that_did_not_load_shows_only_its_badge(self):
        self.assertEqual(self.line(DamagedPlug(PlugFailure.SHADOWED)), "Advanced - not loaded")


# What a child Python reports about the edition it finds. Its home is its working directory,
# a temporary one, and nothing is written there: loading a plug writes nothing.
PROBE = r"""
import importlib.util, inspect, json, logging
from codex_auto_resume import config, edition
from codex_auto_resume.domain import plug
said = []
class Keep(logging.Handler):
    def emit(self, record):
        said.append(record.getMessage())
logging.getLogger("codex_auto_resume").addHandler(Keep())
made = edition.load(config.Paths("."))
def given(point):
    hook = getattr(plug.Plug, plug.HOOKS[point])
    return [object() for _ in list(inspect.signature(hook).parameters)[1:]]
neutral = []
for point in plug.POINTS:
    args = given(point)
    neutral.append(plug.consult(made, point, *args) is plug.consult(plug.NULL, point, *args))
spec = importlib.util.find_spec(edition.ADVANCED_PACKAGE)
print(json.dumps({"name": edition.name(), "type": type(made).__name__, "edition": made.edition,
                  "badge": made.badge, "reason": getattr(made, "reason", None),
                  "neutral": all(neutral), "said": said,
                  "importable": spec is not None}))
"""


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.where = Path(self.temp.name)
        self.original = (editions.ADVANCED_SRC / editions.PACKAGE / "plug.py").read_text(encoding="utf-8")

    def probe(self, *path) -> dict:
        ran = editions.run(PROBE, *path, cwd=self.where)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return json.loads(ran.stdout.strip().splitlines()[-1])

    def assert_damaged(self, found, reason):
        self.assertEqual((found["name"], found["type"], found["edition"], found["badge"], found["reason"]),
                         ("advanced", "DamagedPlug", "advanced", "Advanced - not loaded", reason))
        self.assertTrue(found["neutral"], "a damaged plug must answer as NULL everywhere")
        self.assertEqual(found["said"], ["%s %s" % (edition.NOT_LOADED, reason)])

    def test_absent_is_the_standard_edition(self):
        """In this process, which is the standard leg's: no package beside core."""
        self.assertEqual(edition.name(), Edition.STANDARD)
        self.assertIs(edition.load(config.Paths(self.where)), NULL)
        found = self.probe(editions.overlay(self.where, package=False))
        self.assertEqual((found["name"], found["type"], found["said"]), ("standard", "Plug", []))

    def test_present_beside_core_is_the_advanced_edition_and_changes_nothing_yet(self):
        found = self.probe(editions.overlay(self.where))
        self.assertEqual((found["name"], found["type"], found["edition"], found["badge"], found["said"]),
                         ("advanced", "AdvancedPlug", "advanced", "Advanced", []))
        self.assertTrue(found["neutral"], "with nothing on, the advanced plug answers as NULL")

    def test_present_anywhere_else_is_not_this_installation(self):
        """Importable, and still the standard edition: a copy on the path is not a copy
        beside core, and it is not even looked at."""
        found = self.probe(ROOT / "src", editions.ADVANCED_SRC)
        self.assertTrue(found["importable"])
        self.assertEqual((found["name"], found["type"], found["said"]), ("standard", "Plug", []))

    def test_a_package_written_for_another_interface_is_not_loaded(self):
        text = self.original.replace("PLUG_API = %d" % plug.PLUG_API, "PLUG_API = %d" % (plug.PLUG_API + 1))
        self.assertNotEqual(text, self.original)
        self.assert_damaged(self.probe(editions.overlay(self.where, replace={"plug.py": text})),
                            "api_mismatch")

    def test_a_package_that_fails_to_import_is_not_loaded(self):
        broken = {"plug.py": "raise RuntimeError('broken on purpose')\n"}
        self.assert_damaged(self.probe(editions.overlay(self.where, replace=broken)), "import_failed")

    def test_a_factory_that_fails_or_makes_no_plug_is_not_loaded(self):
        for index, factory in enumerate(("def create(paths):\n    raise RuntimeError('no')\n",
                                         "def create(paths):\n    return object()\n",
                                         "def create(paths):\n    return Plug()\n")):
            with self.subTest(factory.splitlines()[1].strip()):
                replaced = {"plug.py": self.original + "\n\n" + factory}
                src = editions.overlay(self.where / str(index), replace=replaced)
                self.assert_damaged(self.probe(src), "factory_failed")

    def test_a_copy_that_shadows_the_one_beside_core_is_not_loaded(self):
        """The copy beside core is there, and Python would import another one first."""
        src = editions.overlay(self.where / "installed")
        stray = self.where / "stray"
        stray.mkdir()
        (stray / editions.PACKAGE).mkdir()
        (stray / editions.PACKAGE / "__init__.py").write_text("", encoding="utf-8")
        self.assert_damaged(self.probe(stray, src), "shadowed")

    def test_a_directory_that_is_not_a_package_is_no_edition(self):
        """What an uninstall that stopped half way, or a bytecode cache, leaves behind."""
        leftover = self.where / editions.PACKAGE / "__pycache__"
        leftover.mkdir(parents=True)
        self.assertEqual(edition.name(self.where), Edition.STANDARD)
        self.assertIs(edition.load(config.Paths(self.where), self.where), NULL)
        (self.where / editions.PACKAGE / "__init__.py").write_text("", encoding="utf-8")
        self.assertEqual(edition.name(self.where), Edition.ADVANCED)

    def test_the_plug_is_loaded_once_per_home(self):
        with patch.object(edition, "_plugs", {}), \
                patch.object(edition, "load", side_effect=lambda paths: Plug()) as load:
            paths = config.Paths(self.where)
            first = edition.plug(paths)
            self.assertIs(edition.plug(config.Paths(self.where)), first)
            load.assert_called_once()


class StandardRunGuard(unittest.TestCase):
    """A run of this suite tests the edition it says it does.

    Unset, `CODEX_AR_EDITION` means the standard edition, and then the advanced package must
    not be importable at all - a run that could import it would pass for the standard edition
    while testing something else. Set to `advanced` - CI's advanced lane, which puts the
    repository's advanced/src on the path (EditionLaneTests) - the package has to be importable
    from there and be one core would take, or the advanced run would be the standard one under
    another name.

    Importable is not installed. Core takes the package only from beside itself, in the same
    `src` directory, and the advanced lane leaves `src/` as the repository has it: every test
    that reads the working tree as what the standard build copies (tests/srcscan.py, the build
    tests) goes on reading exactly that. So core in that lane is still the standard edition, now
    with an advanced checkout on its path, which must change nothing - the whole core suite
    passing there is what shows it. The package beside a copy of core is LoaderTests, in both.
    """

    def test_this_run_tests_the_edition_it_says_it_does(self):
        leg = os.environ.get(editions.LEG, "standard")
        self.assertIn(leg, tuple(Edition), "%s names no edition" % editions.LEG)
        home = config.Paths(tempfile.gettempdir())
        if leg == Edition.STANDARD:
            self.assertIsNone(importlib.util.find_spec(edition.ADVANCED_PACKAGE),
                              "the standard run can import the advanced package")
            self.assertEqual(edition.name(), Edition.STANDARD)
            self.assertIs(edition.load(home), NULL)
        else:
            found = importlib.util.find_spec(edition.ADVANCED_PACKAGE)
            self.assertIsNotNone(found, "the advanced run cannot import the advanced package")
            # This repository's copy and no other: a package from anywhere else would be testing
            # code this repository does not ship.
            self.assertEqual(Path(found.origin).resolve(),
                             (editions.ADVANCED_SRC / editions.PACKAGE / "__init__.py").resolve())
            self.assertEqual(edition.name(), Edition.STANDARD, "the package is beside core")
            self.assertIs(edition.load(home), NULL)
            # One core would take: written for this plug interface, making the advanced
            # edition's plug, and with every capability off answering every point as NULL does.
            module = importlib.import_module(edition.ADVANCED_PACKAGE + ".plug")
            self.assertEqual(module.PLUG_API, plug.PLUG_API)
            made = module.create(home)
            self.assertIsInstance(made, Plug)
            self.assertNotIsInstance(made, DamagedPlug)
            self.assertEqual(made.edition, Edition.ADVANCED)
            for point in Point:
                with self.subTest(point):
                    given = arguments(point)
                    self.assertIs(plug.consult(made, point, *given), plug.consult(NULL, point, *given))


class EditionLaneTests(unittest.TestCase):
    """CI runs this suite once for each edition, on every Python, and tells each run which.

    StandardRunGuard holds one run to the edition it names; this holds .github/workflows/test.yml
    to naming both, with the path each needs, and the release job to running the advanced tests
    before it builds. Read as text, as the other workflow tests read them: PyYAML is no
    dependency of this suite, and a test that skipped without it would guard nothing in CI.
    """

    def setUp(self):
        self.text = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
        self.matrix = self.text[self.text.index("\n    strategy:"):self.text.index("\n    steps:")]
        step = self.text[self.text.index("- name: Run the automated test suite"):]
        self.step = step[:step.index("\n      - name:")]

    def test_the_axis_is_the_editions_there_are(self):
        axis = re.search(r"(?m)^        edition: \[([^\]]+)\]\s*$", self.matrix)
        self.assertIsNotNone(axis, "test.yml has no edition axis")
        self.assertEqual([part.strip() for part in axis.group(1).split(",")], list(Edition))

    def test_the_future_python_runs_each_edition_too(self):
        """An `include` entry that sets a Python the axis does not list makes a lane of its own
        and joins no other, so an entry without an edition would test neither by name."""
        include = self.matrix[self.matrix.index("include:"):]
        entries = re.split(r"(?m)^          - ", include)[1:]
        self.assertTrue(entries, "the future Python has no lane")
        named = [re.search(r"(?m)^            edition: (\w+)\s*$", entry) for entry in entries]
        self.assertNotIn(None, named, "an include entry names no edition")
        self.assertEqual(sorted(found.group(1) for found in named), sorted(Edition))
        pythons = {re.search(r'python-version: "([\d.]+)"', entry).group(1) for entry in entries}
        self.assertEqual(len(pythons), 1, "each future lane is one Python in both editions")

    def test_each_lane_says_which_edition_it_tests(self):
        self.assertIn("%s: ${{ matrix.edition }}" % editions.LEG, self.step)

    def test_only_the_advanced_lane_has_the_package_on_its_path_and_it_runs_its_tests(self):
        advanced_src = editions.ADVANCED_SRC.relative_to(ROOT).as_posix()
        advanced_tests = (editions.ADVANCED / "tests").relative_to(ROOT).as_posix()
        self.assertTrue((ROOT / advanced_tests).is_dir())
        self.assertIn("PYTHONPATH: ${{ matrix.edition == 'advanced' && 'src;%s' || 'src' }}"
                      % advanced_src, self.step)
        self.assertIn("$suites = @('tests')", self.step)
        self.assertIn("if ($env:%s -eq 'advanced') { $suites += '%s' }" % (editions.LEG, advanced_tests),
                      self.step)
        self.assertIn("python -m unittest discover -s $suite -v", self.step)
        # Every suite runs before the lane gives its verdict.
        self.assertLess(self.step.index("foreach ($suite in $suites)"), self.step.index("if ($failed) { exit 1 }"))
        self.assertEqual(self.step.count("exit 1"), 1, "a suite's failure ends the lane before the next")

    def test_every_lane_compiles_the_advanced_tree(self):
        self.assertIn("python -m compileall -q src tests scripts advanced", self.text)

    def test_the_release_runs_the_advanced_tests_before_it_builds(self):
        release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        start = release.index("- name: Run the advanced edition's tests")
        step = release[start:release.index("\n      - name:", start)]
        self.assertIn("PYTHONPATH: src;%s" % editions.ADVANCED_SRC.relative_to(ROOT).as_posix(), step)
        self.assertIn("%s: advanced" % editions.LEG, step)
        self.assertIn("run: python -m unittest discover -s advanced/tests", step)
        self.assertLess(start, release.index("- name: Build the release archive"))


class SpellingTests(unittest.TestCase):
    """Core names the advanced package once; the standard build's trees never."""

    def test_the_package_is_named_in_src_only_by_the_edition_module(self):
        self.assertEqual(edition.ADVANCED_PACKAGE, editions.PACKAGE)
        self.assertEqual(srcscan.holders(editions.PACKAGE), {"codex_auto_resume/edition.py"})

    def test_nothing_in_src_imports_it_and_only_the_edition_module_imports_by_name(self):
        """A static import would load it into every edition; `importlib` is how one could be
        made without spelling it, so it has one user."""
        for path in srcscan.package_files():
            for entry in srcscan.imports(path):
                with self.subTest(module=srcscan.relative(path), imports=entry.target):
                    self.assertFalse(entry.target.split(".")[0] == editions.PACKAGE)
        users = {srcscan.relative(path) for path in srcscan.package_files()
                 if any(entry.target.split(".")[0] == "importlib" for entry in srcscan.imports(path))}
        self.assertEqual(users, {"codex_auto_resume/edition.py"})
        self.assertEqual(srcscan.holders("__import__"), set())

    def test_no_other_tree_the_standard_build_copies_names_it_or_carries_the_sentinel(self):
        """The rest of what ships: only the files NAMED_BY lists may name the package, and
        none may carry the line every shipped advanced file begins with."""
        sys.path.insert(0, str(ROOT / "build"))
        try:
            import make_release
        finally:
            sys.path.remove(str(ROOT / "build"))
        self.assertNotIn("advanced", make_release.APP_TREES, "the standard build only ever adds")
        listing = [name for tree in make_release.APP_TREES
                   for name in subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", tree],
                                              capture_output=True, text=True,
                                              encoding="utf-8").stdout.splitlines()]
        self.assertGreater(len(listing), 100, "the listing itself looks wrong")
        naming, marked = set(), set()
        for name in listing:
            try:
                text = (ROOT / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue                               # a binary: an icon, a picture
            if editions.PACKAGE in text:
                naming.add(name)
            if editions.SENTINEL in text:
                marked.add(name)
        self.assertEqual(naming - {"src/codex_auto_resume/edition.py"}, set(NAMED_BY))
        self.assertEqual(marked, set(), "advanced code in a tree the standard build copies")


class EditionFromTests(unittest.TestCase):
    """`install --edition-from`: the installer says which edition it replaced, and the new
    edition's plug - only it knows what that means - is told once."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        env = patch.dict(os.environ, {"LOCALAPPDATA": str(Path(self.temp.name) / "no-codex"),
                                      "CODEX_HOME": str(Path(self.temp.name) / "codex"),
                                      config.ENV_HOME: str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        # `install` registers a notification sender, a toast handler and a Start Menu entry:
        # none of them may reach the real user's registry or Start Menu.
        from test_cli import FakeWinreg
        guard = patch.object(startup, "_winreg", return_value=FakeWinreg())
        guard.start()
        self.addCleanup(guard.stop)
        for name, result in (("install", True), ("uninstall", False)):
            guard = patch.object(shortcut, name, return_value=result)
            guard.start()
            self.addCleanup(guard.stop)
        self.addCleanup(self.reset_logging)

    @staticmethod
    def reset_logging():
        import logging
        logger = logging.getLogger(logbook.LOGGER_NAME)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def install(self, *extra, plug_=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if plug_ is None:
                code = cli.main(["--quiet", "install", *extra])
            else:
                with patch.object(edition, "plug", return_value=plug_):
                    code = cli.main(["--quiet", "install", *extra])
        return code, out.getvalue(), err.getvalue()

    def test_the_parser_takes_the_two_editions_and_nothing_else(self):
        parser = cli.build_parser()
        for name in Edition:
            self.assertEqual(parser.parse_args(["install", "--edition-from", name]).edition_from, name)
        self.assertIsNone(parser.parse_args(["install"]).edition_from)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["install", "--edition-from", "premium"])

    def test_without_it_install_says_what_it_always_said(self):
        code, out, _ = self.install()
        self.assertEqual(code, 0)
        self.assertNotIn("edition", out)

    def test_in_the_standard_edition_the_change_is_noted_and_nothing_is_done(self):
        """NULL is told, like any plug, and has nothing to do. The line says what happened."""
        with patch.object(Plug, "edition_changed") as told:
            code, out, _ = self.install("--edition-from", "advanced")
        self.assertEqual(code, 0)
        self.assertIn("edition               : standard (was advanced)", out)
        told.assert_called_once_with(Edition.ADVANCED)

    def test_the_new_editions_plug_is_told_which_edition_it_replaced(self):
        calls = []

        class Entered(Plug):
            __slots__ = ()
            edition = Edition.ADVANCED
            badge = "Advanced"

            def edition_changed(self, previous):
                calls.append(previous)

        code, out, _ = self.install("--edition-from", "standard", plug_=Entered())
        self.assertEqual(code, 0)
        self.assertEqual(calls, [Edition.STANDARD])
        self.assertIs(type(calls[0]), Edition)
        self.assertIn("edition               : advanced (was standard)", out)

    def test_the_same_edition_is_no_change(self):
        with patch.object(Plug, "edition_changed") as told:
            code, out, _ = self.install("--edition-from", "standard")
        self.assertEqual(code, 0)
        told.assert_not_called()
        self.assertIn("edition               : standard (unchanged)", out)

    def test_a_package_that_cannot_be_loaded_refuses_the_change(self):
        """Whatever the new edition would have reset on entry would still be set the day its
        package loads, so the change is refused rather than left half made."""
        code, _, err = self.install("--edition-from", "standard", plug_=DamagedPlug("import_failed"))
        self.assertEqual(code, 1)
        self.assertIn("import_failed", err)

    def test_a_plug_that_fails_to_set_itself_up_fails_the_install(self):
        class Failing(Plug):
            __slots__ = ()
            edition = Edition.ADVANCED

            def edition_changed(self, previous):
                raise OSError("disk full")

        code, _, err = self.install("--edition-from", "standard", plug_=Failing())
        self.assertEqual(code, 1)
        self.assertIn("could not be set up", err)
        self.assertNotIn("disk full", err)


if __name__ == "__main__":
    unittest.main()
