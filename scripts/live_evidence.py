"""Whether anything has been accepted on a real machine, and whether the record says so honestly.

`docs/LIVE_ACCEPTANCE.md` is a procedure a person runs on real Windows against a real
Codex installation, and each of its steps ends in one JSON file under
`docs/evidence/live/`. This reads those files.

It exists because of the failure mode every written-down procedure has: it is run once,
the files are written afterwards from memory, and nothing later can tell a step that was
performed from a step that was described. A validator cannot fix that - it was not there
either - but it can refuse the shapes that make the difference invisible, and it can
refuse to call an empty directory a pass.

What it refuses, and why each is worth refusing:

* **A missing required field.** A file that does not say which product version, which
  Codex, which Windows or what was observed is not evidence about anything.
* **`"verdict": "pass"` with nothing observed.** The one shape that turns a procedure
  into a formality, and the easiest one to write by accident at the end of a long
  session.
* **A raw UUID, a Windows path, an e-mail address or this machine's user name.** These
  files are committed. A conversation id or a home directory published here is published
  permanently, and a conversation id is the one thing this product is careful never to
  put in front of anyone. Ids are recorded as the aliases `diagnostics.py` already
  writes - `thread-1a2b3c4d`, `record-9f8e7d6c` - and as nothing else.
* **A step id it does not know.** A typo accepts nothing while looking like acceptance,
  and a step invented in a file rather than in the document accepts something nobody
  wrote down.
* **Two files claiming one step with different verdicts.** The answer would then be
  whichever file someone happened to read.
* **A product version that is not the manifest's.** Evidence belongs to a build. When
  the version moves the acceptance is run again, not inherited.

What it cannot do is check that any of it happened. The verdict is the person's; this
checks the shape of what they wrote and the vocabulary they wrote it in - the codes,
categories, turn statuses and overlays come from the engine itself, so a value here
cannot drift away from the product without this saying so.

And the thing it says loudest: an empty `docs/evidence/live/` is not a pass. It is
nothing having been accepted yet, and those are different sentences.

    python scripts/live_evidence.py

Exit codes: 0 every step recorded and every verdict `pass`; 1 something was refused;
2 nothing is wrong but this is not a pass - the directory is empty, a step has no
evidence, or a verdict is `fail` or `blocked`.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "docs" / "evidence" / "live"
DOCUMENT = "docs/LIVE_ACCEPTANCE.md"

sys.path.insert(0, str(ROOT / "src"))
from codex_auto_resume import config, failures, machine      # noqa: E402

FORMAT = "codex-auto-resume-live-acceptance/1"
EXIT_OK = 0
EXIT_REFUSED = 1
# Nothing was wrong, and nothing is accepted either. The two have to be told apart: a
# caller that reads an empty directory as success says a release passed a procedure
# nobody ran, and one that reads it as failure says somebody did it badly.
EXIT_NOT_A_PASS = 2

# Every step of the document, in the order it is performed, with the values a `pass`
# has to record. The keys are what the step proves, expressed as machine values; the
# prose that says how to reach them is in the document, and tests/test_live_evidence.py
# keeps the two sets identical so neither can move alone.
STEPS = {
    "install-verify": ("archive_sha256_matches_published", "archive_sha256_matches_pin",
                       "attestation"),
    "install-run": ("route", "setup_exit_code", "install_root", "plugin_registered"),
    "watcher-starts": ("watcher_running", "tray_icon_present", "tooltip_reports"),
    "interruption-detected": ("category", "code", "thread", "record"),
    "continuation-exact-thread": ("thread", "record", "queue_items_owned",
                                  "other_threads_touched"),
    "follows-its-turn": ("record", "marker_matched_turns", "turn_status", "code"),
    "outcome-recorded": ("record", "code", "outcome_at_recorded"),
    "dashboard-shows-it": ("pages_seen", "code_shown", "agrees_with_command_line"),
    "cancel": ("code_before", "code_after", "queued_item",
               "confirmation_named_the_conversation"),
    "retry-now": ("code_before", "code_after", "continuation_sent"),
    "give-attempts-back": ("code_before", "code_after", "budget_resets", "continuation_sent"),
    "pause-resume": ("withdrawn_on_pause", "code_while_paused", "overlay_while_paused",
                     "code_after_resume", "continuation_sent_while_paused"),
    "upgrade-keeps-decisions": ("paused_before", "paused_after", "startup_entry_before",
                                "startup_entry_after"),
    "repair": ("outcome", "paused_unchanged", "startup_entry_unchanged"),
    "uninstall": ("route", "watcher_stopped", "startup_entry", "state_kept"),
}

REQUIRED_FIELDS = ("format", "step", "verdict", "recorded_at", "product_version",
                   "codex_version", "windows_build", "observed")
# `note` is required for anything that is not a pass: a step that failed or could not be
# reached is only useful if it says what happened instead.
OPTIONAL_FIELDS = ("codex_app_version", "note")
VERDICTS = ("pass", "fail", "blocked")

# Values the engine defines. Reading them from the engine rather than repeating them is
# the point: a public code that is renamed renames itself here too, and evidence written
# in the old words stops validating instead of quietly meaning nothing.
VOCABULARY = {
    "category": frozenset(failures.CATEGORIES),
    "turn_status": frozenset(machine.TURN_STATUSES),
    "overlay_while_paused": frozenset(machine.OVERLAYS),
}
VOCABULARY.update({key: frozenset(machine.PUBLIC_CODES) for key in
                   ("code", "code_before", "code_after", "code_shown", "code_while_paused",
                    "code_after_resume")})
# Ids are aliases or they are not recorded. The shape is the one `diagnostics.Redactor`
# writes: a prefix and the first eight hex characters of a keyed digest.
ALIAS_KEYS = ("thread", "record", "chain")
ALIAS_RE = re.compile(r"^(?:thread|record)-[0-9a-f]{8}$")

# Shapes that must not appear anywhere in a file, in a key or in a value. The first four
# are `diagnostics.py`'s, deliberately: what the diagnostics bundle removes before a user
# may share it is exactly what a committed file may not contain either.
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# Record ids are 64 hex characters. Anything from twelve up is refused, which also
# refuses a SHA-256 and a millisecond epoch - neither belongs in a file where a person
# might paste an id instead. Times are ISO-8601 text here, and a digest is recorded as
# whether it matched, not as itself.
HEX_RE = re.compile(r"\b[0-9a-fA-F]{12,}\b")
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\\?\\|\\\\)[^\s'\"<>|]*")
# Anything holding a backslash at all. Every value this schema asks for is an alias, a
# code, a version, a count or a yes/no, and none of those contains one - so a backslash
# is a path fragment that lost its drive letter, which the rule above would let through.
BACKSLASH_RE = re.compile(r"[^\s'\"<>|]*\\[^\s'\"<>|]*")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A home directory carries an account name whether or not it carries a drive letter.
HOME_RE = re.compile(r"(?:\bUsers[\\/]|/home/)[^\\/\s'\"]+", re.IGNORECASE)

# Field names that promise content. None of them can be filled in without writing down
# something this schema exists to keep out, so the name is refused rather than the value:
# a reviewer should not have to judge whether one line of a prompt is too much.
FORBIDDEN_KEYS = frozenset({
    "prompt", "prompt_text", "message", "message_text", "text", "reply", "response",
    "answer", "content", "title", "thread_title", "conversation_title", "subject",
    "user", "username", "user_name", "account", "operator", "tester", "author",
    "email", "path", "file_path", "filepath", "home", "directory", "folder", "cwd",
})

RECORDED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?"
                            r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
CODEX_VERSION_RE = re.compile(r"^\d[0-9A-Za-z.+-]*$")
BUILD_RE = re.compile(r"^\d+\.\d+\.\d+$")
# The example is a shape to copy, not something that happened. It is validated like any
# other file so it cannot rot, and it counts towards nothing.
EXAMPLE_RE = re.compile(r"^example(?:[-_.].*)?$", re.IGNORECASE)


def is_example(name: str) -> bool:
    return bool(EXAMPLE_RE.match(Path(name).stem))


def _texts(value, at=""):
    """Every string in a document, with where it is. Keys are strings too."""
    if isinstance(value, dict):
        for key, item in value.items():
            here = "%s.%s" % (at, key) if at else str(key)
            yield here, str(key)
            yield from _texts(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _texts(item, "%s[%d]" % (at, index))
    elif isinstance(value, bool):
        return
    elif isinstance(value, (str, int, float)):
        # Numbers are read as text too: an id written without its dashes, or a digest
        # written as a number, is the same thing published and would otherwise pass
        # every rule below, which are all written against strings.
        yield at or "(document)", str(value)


def _field_names(value, at=""):
    if isinstance(value, dict):
        for key, item in value.items():
            here = "%s.%s" % (at, key) if at else str(key)
            yield here, str(key)
            yield from _field_names(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _field_names(item, "%s[%d]" % (at, index))


def _excerpt(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def content_refusals(document) -> list:
    """The shapes that must not be in a committed file, wherever they appear."""
    found = []
    # The account this is being run under, the same test `diagnostics.Redactor` makes.
    # Short names are skipped there and here: a two-letter account name matches half the
    # English language, and a check that fires on everything is turned off by whoever
    # meets it first.
    user = os.environ.get("USERNAME") or ""
    user = user if len(user) >= 3 else None
    for where, text in _texts(document):
        if UUID_RE.search(text):
            found.append("%s holds a raw id (%s); record ids only as the aliases the "
                         "diagnostics export writes, `thread-xxxxxxxx` and `record-xxxxxxxx`"
                         % (where, _excerpt(text)))
        elif HEX_RE.search(text):
            found.append("%s holds a long hexadecimal run (%s); an interruption id is 64 "
                         "hex characters and belongs here only as `record-xxxxxxxx`. A time "
                         "is ISO-8601 text, and a digest is recorded as whether it matched"
                         % (where, _excerpt(text)))
        if PATH_RE.search(text) or HOME_RE.search(text):
            found.append("%s holds a file-system path (%s); record where something is as "
                         "`default` or `custom`, never as a path"
                         % (where, _excerpt(text)))
        if EMAIL_RE.search(text):
            found.append("%s holds an e-mail address (%s)" % (where, _excerpt(text)))
        if user and re.search(re.escape(user), text, re.IGNORECASE):
            found.append("%s holds this machine's Windows user name (%s)"
                         % (where, _excerpt(text)))
    for where, key in _field_names(document):
        if key.lower() in FORBIDDEN_KEYS:
            found.append("%s is a field for content this schema keeps out; there is no "
                         "field for a prompt, a reply, a title, a person or a path" % where)
    return found


def _field_refusals(document) -> list:
    found = []
    for field in REQUIRED_FIELDS:
        if field not in document:
            found.append('required field "%s" is missing' % field)
        elif document[field] is None:
            # Written as null rather than left out. Every check below reads a field only
            # when it is not None, so a document of nulls used to satisfy all of them at
            # once - including the one that ties evidence to a build.
            found.append('required field "%s" is null; a field written as null was not '
                         "recorded, and every check that reads it has nothing to read"
                         % field)
    unknown = sorted(set(document) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS))
    for field in unknown:
        found.append('unknown top-level field "%s"; the schema is in %s' % (field, DOCUMENT))
    if document.get("format") not in (None, FORMAT):
        found.append('"format" is %r, not %r' % (document.get("format"), FORMAT))
    step = document.get("step")
    if step is not None and step not in STEPS:
        found.append('"%s" is not a step this validator knows; the steps are the ones in '
                     "%s" % (step, DOCUMENT))
    verdict = document.get("verdict")
    if verdict is not None and verdict not in VERDICTS:
        found.append('"verdict" is %r; it is one of %s' % (verdict, ", ".join(VERDICTS)))
    for field, pattern, shape in (("recorded_at", RECORDED_AT_RE, "an ISO-8601 date or time"),
                                  ("product_version", VERSION_RE, "X.Y.Z"),
                                  ("codex_version", CODEX_VERSION_RE, "a version"),
                                  ("windows_build", BUILD_RE, "10.0.NNNNN")):
        value = document.get(field)
        if value is not None and not (isinstance(value, str) and pattern.match(value)):
            found.append('"%s" is %r; it has to be %s' % (field, value, shape))
    if "observed" in document and not isinstance(document["observed"], dict):
        found.append('"observed" has to be an object of what was seen')
    if "note" in document and not isinstance(document["note"], str):
        found.append('"note" has to be text')
    if verdict in ("fail", "blocked") and not str(document.get("note") or "").strip():
        found.append('a verdict of "%s" needs a note saying what happened instead'
                     % verdict)
    return found


def _recorded(value) -> bool:
    """Whether a value is an observation or a hole shaped like one."""
    if value is None:
        return False
    return not (isinstance(value, str) and not value.strip())


# What a step cannot have seen and still be a pass. Each one is a safety property of the
# product rather than a detail of the procedure: a continuation sent while recovery was
# paused, a Retry now that sent something, an action that reached a conversation nobody
# chose, an upgrade or a repair that changed a decision its owner had made. Recording one
# of these and calling the step a pass is the single way this evidence could say the
# opposite of what it saw, so it is refused rather than believed.
PASS_VALUES = {
    ("continuation-exact-thread", "other_threads_touched"): 0,
    ("retry-now", "continuation_sent"): False,
    ("give-attempts-back", "continuation_sent"): False,
    ("pause-resume", "continuation_sent_while_paused"): False,
    ("cancel", "confirmation_named_the_conversation"): True,
    ("dashboard-shows-it", "agrees_with_command_line"): True,
    ("repair", "paused_unchanged"): True,
    ("repair", "startup_entry_unchanged"): True,
}
# Two values of one step that have to agree with each other for that step to pass.
MUST_MATCH = {
    "upgrade-keeps-decisions": (("paused_before", "paused_after"),
                                ("startup_entry_before", "startup_entry_after")),
}


def _observation_refusals(document) -> list:
    """What a `pass` has to have looked at, and in which words."""
    found = []
    observed = document.get("observed")
    if not isinstance(observed, dict):
        return found
    step = document.get("step")
    if document.get("verdict") == "pass":
        if not any(_recorded(value) for value in observed.values()):
            found.append('"verdict" is "pass" but nothing was observed; a pass that '
                         "records no values is a formality, not evidence")
        for key in STEPS.get(step, ()):
            if not _recorded(observed.get(key)):
                found.append('"verdict" is "pass" but "observed.%s" is missing; that step '
                             "passes only when it is recorded" % key)
    known = set(STEPS.get(step, ()))
    if step in STEPS:
        for key in sorted(set(observed) - known):
            found.append('"observed.%s" is not one of the values "%s" records; the values '
                         "for each step are in %s, and an extra one is a place for "
                         "something this schema exists to keep out" % (key, step, DOCUMENT))
    if document.get("verdict") == "pass":
        for (at_step, key), expected in PASS_VALUES.items():
            if step != at_step:
                continue
            value = observed.get(key)
            if _recorded(value) and value != expected:
                found.append('"verdict" is "pass" but "observed.%s" is %r, and this step '
                             "passes only with %r; that value is the thing the step exists "
                             "to catch" % (key, value, expected))
        for first, second in MUST_MATCH.get(step, ()):
            one, other = observed.get(first), observed.get(second)
            if _recorded(one) and _recorded(other) and one != other:
                found.append('"verdict" is "pass" but "observed.%s" is %r and '
                             '"observed.%s" is %r; this step passes only when they are the '
                             "same" % (first, one, second, other))
    for key, value in observed.items():
        if key in ALIAS_KEYS and value is not None:
            if not (isinstance(value, str) and ALIAS_RE.match(value)):
                found.append('"observed.%s" is %r; an id is recorded only as the alias the '
                             "diagnostics export writes, `%s-xxxxxxxx`"
                             % (key, value, "thread" if key == "thread" else "record"))
        allowed = VOCABULARY.get(key)
        if allowed is not None and value is not None and value not in allowed:
            found.append('"observed.%s" is %r, which the engine does not define; it is one '
                         "of %s" % (key, value, ", ".join(sorted(allowed))))
    return found


def refusals(name: str, document, *, product_version: str) -> list:
    """Everything wrong with one file, as sentences a person can act on."""
    if not isinstance(document, dict):
        return ["the file has to hold one JSON object, and holds %s"
                % type(document).__name__]
    found = _field_refusals(document) + _observation_refusals(document)
    found += content_refusals(document)
    recorded = document.get("product_version")
    if not is_example(name) and recorded is not None and recorded != product_version:
        found.append('"product_version" is %r and the manifest says %r; evidence belongs '
                     "to one build, so a version that moved is a reason to run the "
                     "acceptance again, not to inherit it" % (recorded, product_version))
    return found


def read(path: Path):
    """One file's document, or the reason it is not one."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return None, "cannot be read (%s)" % exc.strerror
    try:
        return json.loads(text), None
    except ValueError as exc:
        return None, "is not JSON (%s)" % exc


def review(directory: Path, *, product_version: str) -> dict:
    """Read a directory of evidence. Refusals, what is covered, and what is not."""
    directory = Path(directory)
    found, verdicts, examples, files = [], {}, [], []
    observations = {}
    for entry in sorted(directory.iterdir()) if directory.is_dir() else []:
        name = entry.name
        if entry.is_dir():
            found.append("%s: a directory; evidence is one flat set of files, so a nested "
                         "one hides what it holds" % name)
            continue
        if name.lower() == "readme.md":
            # Skipped as evidence, not as text. It is the one file here a person writes
            # sentences into, which makes it the likeliest place for a real id or a real
            # path to arrive.
            try:
                text = entry.read_text(encoding="utf-8-sig")
            except OSError as exc:
                found.append("%s: cannot be read (%s)" % (name, exc.strerror))
                continue
            for refusal in content_refusals(text):
                found.append("%s: %s" % (name, refusal))
            continue
        if entry.suffix.lower() != ".json":
            found.append("%s: evidence is JSON. A screenshot of a real Codex window "
                         "publishes a conversation permanently, which is the one thing "
                         "this schema exists to prevent" % name)
            continue
        document, problem = read(entry)
        if problem:
            found.append("%s: %s" % (name, problem))
            continue
        for refusal in refusals(name, document, product_version=product_version):
            found.append("%s: %s" % (name, refusal))
        if is_example(name):
            examples.append(name)
            continue
        files.append(name)
        step, verdict = document.get("step"), document.get("verdict")
        if step in STEPS and verdict in VERDICTS:
            verdicts.setdefault(step, {}).setdefault(verdict, []).append(name)
            if isinstance(document.get("observed"), dict):
                for key, value in document["observed"].items():
                    observations.setdefault(step, {}).setdefault(key, {})[name] = value
    for step, seen in sorted(observations.items()):
        for key, values in sorted(seen.items()):
            distinct = {json.dumps(value, sort_keys=True) for value in values.values()}
            if len(distinct) > 1:
                found.append("%s: %s disagree about \"observed.%s\"; one step cannot have "
                             "been seen two ways, and reading whichever file came first is "
                             "not an answer"
                             % (step, " and ".join(sorted(values)), key))
    for step, claims in sorted(verdicts.items()):
        if len(claims) > 1:
            found.append("%s: %s claim one step with different verdicts (%s); the answer "
                         "would be whichever file someone read"
                         % (step, " and ".join(sorted(n for names in claims.values()
                                                      for n in names)),
                            ", ".join(sorted(claims))))
    recorded = {step for step, claims in verdicts.items() if "pass" in claims
                and len(claims) == 1}
    return {"refusals": found, "files": files, "examples": examples,
            "verdicts": {step: sorted(claims) for step, claims in verdicts.items()},
            "passed": sorted(recorded),
            "missing": sorted(set(STEPS) - set(verdicts)),
            "directory": directory}


NOTHING = ("Nothing has been accepted yet.\n"
           "An empty %s is not a pass. It means no step of the live acceptance has been\n"
           "run on a real machine and written down - which is a different sentence from\n"
           "\"it was run and it passed\", and the two must never be printed as one."
           % "docs/evidence/live/")


def report(result: dict, *, product_version: str, out=None) -> int:
    out = sys.stdout if out is None else out
    directory = result["directory"]
    for refusal in result["refusals"]:
        print("refused: %s" % refusal, file=out)
    if result["refusals"]:
        print("", file=out)
        print("%d refusal(s). Nothing here is accepted until each one is answered."
              % len(result["refusals"]), file=out)
        return EXIT_REFUSED
    if not result["files"]:
        if not Path(directory).is_dir():
            print("%s does not exist." % directory, file=out)
        print(NOTHING, file=out)
        if result["examples"]:
            print("", file=out)
            print("(%s is an example of the shape, not a record of anything.)"
                  % ", ".join(result["examples"]), file=out)
        return EXIT_NOT_A_PASS
    print("%d file(s) in %s, product version %s."
          % (len(result["files"]), directory, product_version), file=out)
    for step in STEPS:
        claims = result["verdicts"].get(step)
        print("  %-26s %s" % (step, claims[0] if claims else "no evidence"), file=out)
    if result["missing"]:
        print("", file=out)
        print("Not a pass: %d of %d steps have no evidence yet (%s)."
              % (len(result["missing"]), len(STEPS), ", ".join(result["missing"])), file=out)
        return EXIT_NOT_A_PASS
    not_passed = sorted(set(STEPS) - set(result["passed"]))
    if not_passed:
        print("", file=out)
        print("Not a pass: %s did not pass." % ", ".join(not_passed), file=out)
        return EXIT_NOT_A_PASS
    print("", file=out)
    print("All %d steps recorded and passed for %s." % (len(STEPS), product_version), file=out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live_evidence",
        description="Validate the live-acceptance evidence in docs/evidence/live/.")
    parser.add_argument("directory", nargs="?", default=str(EVIDENCE_DIR),
                        help="where the evidence files are (default: docs/evidence/live/)")
    parser.add_argument("--product-version", default=None,
                        help="the version the evidence must claim (default: the manifest's)")
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    args = build_parser().parse_args(argv)
    product_version = args.product_version or config.version()
    result = review(Path(args.directory), product_version=product_version)
    return report(result, product_version=product_version)


if __name__ == "__main__":
    sys.exit(main())
