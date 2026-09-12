"""The live-acceptance evidence, and the two ways it could quietly stop meaning anything.

`docs/LIVE_ACCEPTANCE.md` is a procedure a person runs on a real machine;
`scripts/live_evidence.py` is what keeps the files it produces honest. Neither is
exercised by anything else in this suite, because nothing else in this suite touches a
real Codex - which is exactly why both need tests of their own.

Two failures are worth guarding against, and they are different:

* **The validator stops refusing something.** Each refusal below is a shape that would
  make a directory of files look like acceptance without being it - a pass with nothing
  observed, a conversation id in the raw, a step id nobody wrote down. They are asserted
  one at a time, so a refusal that is dropped in a refactor fails here by name.
* **The document and the validator drift apart.** A step renamed in one and not the other
  produces evidence that validates and proves nothing, or a procedure whose files are all
  refused. The two sets of step ids, and the values each step must record, are compared
  directly.

Every fixture here is synthetic and from the project's fixture families. Nothing in this
file reads a real Codex home, installs anything, or writes into `docs/evidence/live/`.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import live_evidence                                          # noqa: E402

DOCUMENT = ROOT / "docs" / "LIVE_ACCEPTANCE.md"
KOREAN = ROOT / "docs" / "LIVE_ACCEPTANCE.ko.md"
EVIDENCE = ROOT / "docs" / "evidence" / "live"

# Never the manifest's version: a test that happened to agree with the product would pass
# whether or not the check it is about still exists.
VERSION = "9.9.9"
# The project's fixture family, as an alias rather than as a UUID - which is the whole
# point of the schema, and which tests/test_repo_hygiene.py would object to otherwise.
THREAD = "thread-0a1b2c3d"
RECORD = "record-0a1b2c3e"
FIXTURE_UUID = "0a1b2c3d-0001-7000-8000-000000000001"


def observation(step: str) -> dict:
    """Values a `pass` for this step needs, in the vocabulary the engine defines.

    Built from the validator's own tables rather than written out, so a step that gains a
    required value gets a valid fixture instead of a test that fails for the wrong reason.
    """
    values = {}
    for key in live_evidence.STEPS[step]:
        if key in live_evidence.ALIAS_KEYS:
            values[key] = THREAD if key == "thread" else RECORD
        elif (step, key) in live_evidence.PASS_VALUES:
            values[key] = live_evidence.PASS_VALUES[(step, key)]
        elif key in live_evidence.VOCABULARY:
            values[key] = sorted(live_evidence.VOCABULARY[key])[0]
        else:
            values[key] = True
    return values


def evidence(step: str = "install-verify", verdict: str = "pass", **changes) -> dict:
    document = {
        "format": live_evidence.FORMAT,
        "step": step,
        "verdict": verdict,
        "recorded_at": "2026-09-12",
        "codex_version": "0.153.4",
        "windows_build": "10.0.26200",
        "product_version": VERSION,
        "observed": observation(step),
    }
    if verdict != "pass":
        document["note"] = "the usage limit did not happen during the acceptance"
    document.update(changes)
    return document


def refusals(document, name: str = "install-verify.json") -> list:
    return live_evidence.refusals(name, document, product_version=VERSION)


def run(directory, *arguments) -> tuple:
    """The validator as a person runs it: an exit code and what it printed."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = live_evidence.main(["--product-version", VERSION, str(directory), *arguments])
    return code, out.getvalue()


class Directory:
    """A scratch evidence directory. Nothing here ever writes into the repository."""

    def __enter__(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.path = Path(self._scratch.name)
        return self

    def __exit__(self, *exception):
        self._scratch.cleanup()

    def write(self, name: str, document) -> Path:
        path = self.path / name
        body = document if isinstance(document, str) else json.dumps(document, indent=2)
        path.write_text(body, encoding="utf-8")
        return path


class WellFormedTests(unittest.TestCase):
    def test_a_well_formed_file_is_accepted(self):
        for step in live_evidence.STEPS:
            with self.subTest(step):
                self.assertEqual(refusals(evidence(step)), [])

    def test_a_blocked_step_with_a_note_is_accepted(self):
        """Not every honest file is a pass, and a validator that only accepted passes
        would push whoever ran the procedure towards writing one."""
        document = evidence("interruption-detected", "blocked", observed={})
        self.assertEqual(refusals(document), [])

    def test_the_shipped_example_is_valid_and_is_not_evidence(self):
        example = EVIDENCE / "example.json"
        self.assertTrue(example.is_file(), "the example of the shape is missing")
        document = json.loads(example.read_text(encoding="utf-8"))
        self.assertTrue(live_evidence.is_example(example.name))
        # Validated like any other file, so it cannot rot - but exempt from the version
        # check, because it is not a record of a build.
        self.assertEqual(live_evidence.refusals(example.name, document,
                                                product_version=VERSION), [])

    def test_the_example_directory_holds_nothing_that_claims_to_be_evidence(self):
        """Committing a fabricated file here would be the one unrecoverable mistake.

        It cannot be refused after the fact: a well-formed file about a run nobody made
        is indistinguishable from a well-formed file about a run somebody made. So the
        repository ships the shape and nothing else until a person has actually run it.
        """
        for path in sorted(EVIDENCE.glob("*.json")):
            with self.subTest(path.name):
                self.assertTrue(live_evidence.is_example(path.name),
                                "%s claims to be evidence; nothing may be committed here "
                                "that nobody performed" % path.name)


class RefusalTests(unittest.TestCase):
    def assertRefused(self, document, because: str, name="install-verify.json"):
        found = refusals(document, name)
        self.assertTrue(found, "nothing was refused")
        self.assertTrue(any(because in refusal for refusal in found),
                        "refused for the wrong reason: %s" % found)

    def test_a_missing_required_field_is_refused(self):
        for field in live_evidence.REQUIRED_FIELDS:
            with self.subTest(field):
                document = evidence()
                document.pop(field)
                self.assertRefused(document, 'required field "%s" is missing' % field)

    def test_a_pass_with_nothing_observed_is_refused(self):
        self.assertRefused(evidence(observed={}), "nothing was observed")
        self.assertRefused(evidence(observed={"attestation": None}), "nothing was observed")

    def test_a_pass_missing_one_of_its_own_values_is_refused(self):
        for step, keys in live_evidence.STEPS.items():
            with self.subTest(step):
                observed = observation(step)
                observed.pop(keys[0])
                self.assertRefused(evidence(step, observed=observed),
                                   '"observed.%s" is missing' % keys[0])

    def test_a_raw_conversation_id_is_refused(self):
        self.assertRefused(evidence(note="looked at %s" % FIXTURE_UUID), "raw id")
        self.assertRefused(evidence("interruption-detected",
                                    observed=dict(observation("interruption-detected"),
                                                  thread=FIXTURE_UUID)),
                           "raw id")

    def test_an_id_that_is_not_an_alias_is_refused(self):
        observed = dict(observation("interruption-detected"), record="the second one")
        self.assertRefused(evidence("interruption-detected", observed=observed),
                           "only as the alias")

    def test_a_long_hexadecimal_run_is_refused(self):
        # A record id is 64 hex characters, and so is a digest. Nothing can tell them
        # apart by looking, so neither is written down.
        digest = "a" * 64
        self.assertRefused(evidence(observed=dict(observation("install-verify"),
                                                  archive_sha256=digest)),
                           "long hexadecimal run")

    def test_a_windows_path_is_refused(self):
        self.assertRefused(evidence(note=r"installed to C:\Users\ExampleUser\.codex-auto-resume"),
                           "file-system path")
        self.assertRefused(evidence(observed=dict(observation("install-verify"),
                                                  install_root=r"D:\tools")),
                           "file-system path")

    def test_an_e_mail_address_is_refused(self):
        self.assertRefused(evidence(note="reported by someone@example.invalid"),
                           "e-mail address")

    def test_this_machines_user_name_is_refused(self):
        with patch.dict("os.environ", {"USERNAME": "ExampleUser"}):
            self.assertRefused(evidence(note="run by exampleuser on the test machine"),
                               "Windows user name")

    def test_a_short_user_name_is_not_hunted_for(self):
        """A two-letter account name matches half the language; a check that fires on
        everything is turned off by whoever meets it first. `diagnostics.py` draws the
        line in the same place."""
        with patch.dict("os.environ", {"USERNAME": "ab"}):
            self.assertEqual(refusals(evidence(note="the tab was already open")), [])

    def test_a_field_that_promises_content_is_refused(self):
        for field in ("prompt", "reply", "title", "username", "path"):
            with self.subTest(field):
                observed = dict(observation("install-verify"))
                observed[field] = "x"
                self.assertRefused(evidence(observed=observed), "field for content")

    def test_a_step_the_validator_does_not_know_is_refused(self):
        document = evidence()
        document["step"] = "looked-fine"
        self.assertRefused(document, "not a step this validator knows")

    def test_an_unknown_top_level_field_is_refused(self):
        self.assertRefused(evidence(transcript="..."), "unknown top-level field")

    def test_a_code_the_engine_does_not_define_is_refused(self):
        observed = dict(observation("outcome-recorded"), code="worked_fine")
        self.assertRefused(evidence("outcome-recorded", observed=observed),
                           "which the engine does not define")

    def test_every_vocabulary_comes_from_the_product(self):
        """The codes are read out of the engine, not repeated here.

        A public code that is renamed has to invalidate the evidence written in the old
        word rather than quietly mean nothing, which only holds while these are the
        engine's own sets.
        """
        from codex_auto_resume import failures, machine
        self.assertEqual(live_evidence.VOCABULARY["code"], frozenset(machine.PUBLIC_CODES))
        self.assertEqual(live_evidence.VOCABULARY["category"], frozenset(failures.CATEGORIES))
        self.assertEqual(live_evidence.VOCABULARY["turn_status"],
                         frozenset(machine.TURN_STATUSES))
        self.assertEqual(live_evidence.VOCABULARY["overlay_while_paused"],
                         frozenset(machine.OVERLAYS))

    def test_a_verdict_that_is_not_a_pass_needs_a_note(self):
        document = evidence("interruption-detected", "blocked", observed={})
        document.pop("note")
        self.assertRefused(document, "needs a note", "interruption-detected.json")

    def test_an_unknown_verdict_is_refused(self):
        self.assertRefused(evidence(verdict="mostly"), '"verdict"')

    def test_a_product_version_that_is_not_the_manifests_is_refused(self):
        self.assertRefused(evidence(product_version="0.0.1"), "run the acceptance again")

    def test_a_malformed_field_is_refused(self):
        for field, value in (("format", "something-else/1"), ("recorded_at", "last Tuesday"),
                             ("windows_build", "Windows 11"), ("codex_version", "the latest"),
                             ("product_version", "v1.2"), ("observed", "everything"),
                             ("note", 3)):
            with self.subTest(field):
                self.assertTrue(refusals(evidence(**{field: value})),
                                "%s=%r was accepted" % (field, value))


class DirectoryTests(unittest.TestCase):
    def test_an_empty_directory_is_not_a_pass(self):
        with Directory() as scratch:
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_NOT_A_PASS)
        self.assertIn("Nothing has been accepted yet", printed)
        self.assertIn("is not a pass", printed)

    def test_a_directory_holding_only_the_example_is_not_a_pass(self):
        with Directory() as scratch:
            scratch.write("example.json", evidence(product_version="0.0.0"))
            scratch.write("README.md", "# notes")
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_NOT_A_PASS)
        self.assertIn("Nothing has been accepted yet", printed)

    def test_two_files_claiming_one_step_with_different_verdicts_are_refused(self):
        with Directory() as scratch:
            scratch.write("cancel.json", evidence("cancel"))
            scratch.write("cancel-second-run.json",
                          evidence("cancel", "fail", observed={}))
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_REFUSED)
        self.assertIn("different verdicts", printed)

    def test_two_files_that_agree_are_not_refused(self):
        with Directory() as scratch:
            scratch.write("cancel.json", evidence("cancel"))
            scratch.write("cancel-second-run.json", evidence("cancel"))
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_NOT_A_PASS, printed)
        self.assertNotIn("refused", printed)

    def test_a_screenshot_is_refused(self):
        """A picture of a real Codex window publishes a conversation permanently."""
        with Directory() as scratch:
            scratch.write("dashboard-shows-it.png", "not really a png")
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_REFUSED)
        self.assertIn("evidence is JSON", printed)

    def test_a_file_that_is_not_json_is_refused(self):
        with Directory() as scratch:
            scratch.write("cancel.json", "{ this is not json")
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_REFUSED)
        self.assertIn("is not JSON", printed)

    def test_a_complete_set_of_passes_is_a_pass(self):
        with Directory() as scratch:
            for step in live_evidence.STEPS:
                scratch.write("%s.json" % step, evidence(step))
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_OK, printed)
        self.assertIn("All %d steps recorded" % len(live_evidence.STEPS), printed)

    def test_one_missing_step_is_not_a_pass(self):
        with Directory() as scratch:
            for step in list(live_evidence.STEPS)[:-1]:
                scratch.write("%s.json" % step, evidence(step))
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_NOT_A_PASS)
        self.assertIn("no evidence", printed)

    def test_a_blocked_step_is_not_a_pass(self):
        with Directory() as scratch:
            for step in live_evidence.STEPS:
                scratch.write("%s.json" % step, evidence(step))
            scratch.write("interruption-detected.json",
                          evidence("interruption-detected", "blocked", observed={}))
            code, printed = run(scratch.path)
        self.assertEqual(code, live_evidence.EXIT_NOT_A_PASS)
        self.assertIn("did not pass", printed)

    def test_the_repositorys_own_directory_is_read_without_error(self):
        code, printed = run(EVIDENCE)
        self.assertIn(code, (live_evidence.EXIT_NOT_A_PASS, live_evidence.EXIT_OK), printed)
        self.assertNotIn("refused", printed)


def document_steps(path: Path) -> set:
    """The step ids a document actually documents: one section heading each.

    Only step sections are `###` in these documents, and each heading ends with its id in
    backticks. That is a convention, and it is the cheapest one that a reader and a test
    can both see.
    """
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"^###\s.*`([a-z][a-z0-9-]*)`\s*$", text, re.M))


def document_table(path: Path) -> dict:
    """The steps table: step id to the values its `pass` must record.

    Recognised by shape rather than by the heading above it, and by nothing written in
    any language: four cells, a backticked step id in the first and backticked field
    names in the third. The schema table has three cells and is not mistaken for it. That
    leaves the Korean document free to word its own columns.
    """
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not re.fullmatch(r"`[a-z][a-z0-9-]*`", cells[0]):
            continue
        rows[cells[0].strip("`")] = tuple(re.findall(r"`([a-z0-9_]+)`", cells[2]))
    return rows


class DocumentTests(unittest.TestCase):
    """The document and the validator, which must not be able to drift apart."""

    def test_the_document_exists_and_names_the_validator(self):
        self.assertTrue(DOCUMENT.is_file())
        text = DOCUMENT.read_text(encoding="utf-8")
        self.assertIn("scripts/live_evidence.py", text)
        self.assertIn("docs/evidence/live/", text)

    def test_the_document_and_the_validator_name_the_same_steps(self):
        self.assertEqual(document_steps(DOCUMENT), set(live_evidence.STEPS),
                         "a step in one and not the other means evidence that validates "
                         "and proves nothing, or a procedure whose files are all refused")

    def test_the_documents_table_names_the_same_steps_as_its_sections(self):
        self.assertEqual(set(document_table(DOCUMENT)), document_steps(DOCUMENT))

    def test_the_documents_table_names_the_values_each_pass_must_record(self):
        self.assertEqual(document_table(DOCUMENT), dict(live_evidence.STEPS),
                         "the table in the document is what a person reads before writing "
                         "a file; the validator is what refuses it")

    def test_the_document_says_an_empty_directory_is_not_a_pass(self):
        text = DOCUMENT.read_text(encoding="utf-8").lower()
        self.assertIn("not a pass", text)
        self.assertIn("nothing has been accepted yet", text)

    def test_the_document_says_which_steps_need_a_real_interruption(self):
        table = {}
        for line in DOCUMENT.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| `"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 4 and cells[3].lower().startswith(("yes", "no")):
                table[cells[0].strip("`")] = cells[3].lower()
        self.assertEqual(set(table), set(live_evidence.STEPS))
        self.assertTrue(table["interruption-detected"].startswith("yes"))
        self.assertTrue(table["install-verify"].startswith("no"))
        # And the sentence a reader needs most: a usage limit cannot be arranged.
        self.assertIn("cannot be summoned", DOCUMENT.read_text(encoding="utf-8"))

    def test_the_korean_document_documents_the_same_steps(self):
        """The Korean page is its own document, not a gloss - but the step ids are
        machine values, and a Korean reader writing files from it has to produce files
        the same validator accepts."""
        if not KOREAN.is_file():
            # On the generated `ko` branch the Korean text lives under the English name.
            raise unittest.SkipTest("no Korean source here; this checkout is not main")
        self.assertEqual(document_steps(KOREAN), set(live_evidence.STEPS))
        self.assertEqual(document_table(KOREAN), dict(live_evidence.STEPS))


if __name__ == "__main__":
    unittest.main()
