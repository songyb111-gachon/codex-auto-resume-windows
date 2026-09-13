"""Which Pythons this project claims to run on, said once and checked everywhere.

The question "which Python versions are supported?" had four answers before this file:
the test workflow's matrix, the release workflow's pinned version, the ko sync's pinned
version, and the prose in README.md and CONTRIBUTING.md. Nothing compared them, so any
one of them could drift and the first evidence would be a user on a version CI never ran.

`scripts/python_support.json` is now the answer, and these tests are what make the copies
of it copies rather than independent opinions. A GitHub matrix cannot read a file, so the
repetition in the workflow is unavoidable; being unable to remove it is not a reason to
leave it unchecked.

The file also keeps three things apart that are easy to conflate - source compatibility,
the runtime a release bundles, and whatever Python a contributor happens to have - and a
couple of tests here exist only to stop the first silently dragging the second along.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "scripts" / "python_support.json").read_text(encoding="utf-8"))
WORKFLOWS = ROOT / ".github" / "workflows"

VERSION = re.compile(r"^3\.\d+$")


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


class PolicyShapeTests(unittest.TestCase):
    def test_every_version_is_a_python_minor(self):
        for key in ("minimum", "future_prerelease", "release_build"):
            with self.subTest(key):
                self.assertRegex(POLICY[key], VERSION)
        for version in POLICY["blocking"]:
            with self.subTest(version):
                self.assertRegex(version, VERSION)

    def test_the_blocking_list_is_ordered_and_has_no_duplicates(self):
        ordered = sorted(POLICY["blocking"], key=lambda v: int(v.split(".")[1]))
        self.assertEqual(POLICY["blocking"], ordered)
        self.assertEqual(len(set(POLICY["blocking"])), len(POLICY["blocking"]))

    def test_the_minimum_is_the_oldest_version_that_is_actually_tested(self):
        """A minimum nobody runs is a guess, not a minimum."""
        self.assertEqual(POLICY["minimum"], POLICY["blocking"][0])

    def test_support_does_not_reach_below_the_minimum(self):
        """Old interpreters are not added for the version count.

        This ships its own runtime; a user needs no Python at all. Reaching down to
        3.11 or older would be support promised to nobody and paid for on every run.
        """
        floor = int(POLICY["minimum"].split(".")[1])
        for version in POLICY["blocking"]:
            with self.subTest(version):
                self.assertGreaterEqual(int(version.split(".")[1]), floor)

    def test_the_future_lane_is_newer_than_everything_that_blocks(self):
        newest = max(int(v.split(".")[1]) for v in POLICY["blocking"])
        self.assertGreater(int(POLICY["future_prerelease"].split(".")[1]), newest)

    def test_the_future_lane_has_not_quietly_become_a_blocking_one(self):
        self.assertNotIn(POLICY["future_prerelease"], POLICY["blocking"])


class WorkflowAgreementTests(unittest.TestCase):
    def matrix_versions(self):
        text = workflow("test.yml")
        listed = re.search(r'python-version:\s*\[([^\]]+)\]', text)
        self.assertIsNotNone(listed, "test.yml has no python-version matrix")
        return [part.strip().strip('"\'') for part in listed.group(1).split(",")]

    def test_the_matrix_is_exactly_the_blocking_list(self):
        self.assertEqual(self.matrix_versions(), POLICY["blocking"])

    def test_the_future_lane_is_in_the_workflow_and_marked_experimental(self):
        text = workflow("test.yml")
        self.assertIn('python-version: "%s"' % POLICY["future_prerelease"], text)
        self.assertIn("experimental: true", text)
        self.assertIn("continue-on-error: ${{ matrix.experimental }}", text)

    def test_only_the_future_lane_is_allowed_to_fail_quietly(self):
        """`continue-on-error` on the whole job would silence the versions that matter."""
        text = workflow("test.yml")
        self.assertNotIn("continue-on-error: true", text)

    def test_the_future_lane_actually_runs_the_suite(self):
        """An advisory lane that skips the tests advises nothing.

        There is one set of steps and every lane runs it, so this is really a check
        that nobody adds an `if` to spare the pre-release lane the work.
        """
        text = workflow("test.yml")
        self.assertIn("unittest discover", text)
        self.assertIn("compileall", text)
        for guard in ("if: matrix.experimental", "if: ${{ matrix.experimental",
                      "if: !matrix.experimental", "if: ${{ !matrix.experimental"):
            self.assertNotIn(guard, text, "a lane is being spared a step")

    def test_prereleases_are_permitted_where_the_interpreter_is_chosen(self):
        self.assertIn("allow-prereleases: true", workflow("test.yml"))

    def test_the_workflows_that_pin_one_version_pin_a_supported_one(self):
        """release.yml and sync-ko.yml each choose a single interpreter."""
        for name in ("release.yml", "sync-ko.yml"):
            with self.subTest(name):
                pinned = re.findall(r'python-version:\s*"(3\.\d+)"', workflow(name))
                self.assertTrue(pinned, "%s pins no Python" % name)
                for version in pinned:
                    self.assertIn(version, POLICY["blocking"],
                                  "%s builds on a version nothing tests" % name)

    def test_the_release_workflow_uses_the_version_the_policy_names(self):
        """The archive's bytes depend on it, so it is named rather than incidental."""
        pinned = re.findall(r'python-version:\s*"(3\.\d+)"', workflow("release.yml"))
        self.assertEqual(pinned, [POLICY["release_build"]])


class BundledRuntimeTests(unittest.TestCase):
    """The runtime a release ships is not derived from the CI matrix."""

    def test_the_pinned_runtime_is_the_one_the_build_downloads(self):
        text = (ROOT / "build" / "make_release.py").read_text(encoding="utf-8")
        found = re.search(r'PYTHON_VERSION\s*=\s*"([0-9.]+)"', text)
        self.assertIsNotNone(found, "make_release.py pins no runtime")
        self.assertEqual(found.group(1), POLICY["bundled_runtime"])

    def test_the_bundled_runtime_is_a_full_patch_version(self):
        """A release bundles one build, not a line that moves under it."""
        self.assertRegex(POLICY["bundled_runtime"], r"^3\.\d+\.\d+$")

    def test_the_bundled_runtime_is_on_a_line_that_is_tested(self):
        """Not a coupling - a sanity check.

        Adding a CI version must never move the bundled runtime, and nothing here does
        that. But shipping a runtime from a line no lane exercises would mean the code
        users actually run is the one version nothing checks.
        """
        line = ".".join(POLICY["bundled_runtime"].split(".")[:2])
        self.assertIn(line, POLICY["blocking"])


class DocumentedMinimumTests(unittest.TestCase):
    def test_the_documents_state_the_minimum_the_policy_names(self):
        minimum = POLICY["minimum"]
        for name in ("README.md", "CONTRIBUTING.md"):
            with self.subTest(name):
                self.assertIn("Python %s" % minimum,
                              (ROOT / name).read_text(encoding="utf-8"))

    def test_no_document_promises_an_older_interpreter(self):
        older = ["3.%d" % minor for minor in range(7, int(POLICY["minimum"].split(".")[1]))]
        for name in ("README.md", "README.ko.md", "CONTRIBUTING.md", "CONTRIBUTING.ko.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for version in older:
                with self.subTest(name=name, version=version):
                    self.assertNotIn("Python %s" % version, text)

    def test_the_message_a_user_sees_names_the_same_minimum(self):
        """The sentence shown when no interpreter is found, from the English catalog."""
        catalog = json.loads(
            (ROOT / "src" / "codex_auto_resume" / "locales" / "en.json")
            .read_text(encoding="utf-8"))
        self.assertIn("Python %s" % POLICY["minimum"], catalog["msg.python_missing"])


if __name__ == "__main__":
    unittest.main()
