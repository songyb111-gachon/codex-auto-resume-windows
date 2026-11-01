"""Compact a full conversation, then continue (v0.6.16-beta.4): a turn that failed on Codex's context window is taken
up for that one code, held while the app has the conversation until a compaction turn is the latest - then
continued once by core's ordinary send - and, where nothing holds it and Codex is closed, compacted and continued on
the headless route.

Held against the shipped definition and statement and against core's own engine, store and simulated Codex home
(takingcase.py); the turns it reads are the harness's Codex home's.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from takingcase import TakingCase  # noqa: E402
from advancedcase import ENGINE, ROOT  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import registry  # noqa: E402
from codex_auto_resume_advanced.codex import headless  # noqa: E402
from codex_auto_resume_advanced.codex.turns import Turn, Turns  # noqa: E402
from codex_auto_resume_advanced.engine.compact import GIVE_UP_SECONDS, CompactContinue  # noqa: E402
from codex_auto_resume_advanced.registry import COMPACT_CONTINUE  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (ArmingState, ArmingWarning, Measurement,  # noqa: E402
                                                   Verdict)
from test_engine import T1  # noqa: E402

CONTEXT_FULL = json.dumps({"codexErrorInfo": "contextWindowExceeded"})
KEY = "%064x" % 7


class CompactCase(TakingCase):
    DEFINITION = COMPACT_CONTINUE

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(word) for word in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def armed(self, h=None, state="armed"):
        plug = super().armed(h, state=state)
        h = h or self.h
        plug.runtime._code_of(self.DEFINITION)._turns = Turns(h.home.root)
        return plug

    def compaction(self, status="completed"):
        turn = self.h.home.add_turn(T1, None, status, user_text=None, progress=False)
        self.h.home.add_item(T1, turn, "contextCompaction")
        self.h.home.catch_up(T1)
        return turn


class AppTests(CompactCase):
    def test_off_a_full_context_window_is_never_taken_up(self):
        self.plugged(self.advanced())
        self.failing(CONTEXT_FULL)
        self.h.tick()
        self.assertEqual(self.h.records(), [])

    def test_held_until_the_person_compacts_then_continued_once(self):
        """Fails with core's compaction rule reverted: the compaction turn would supersede the record."""
        self.armed()
        self.failing(CONTEXT_FULL)
        self.h.tick()
        (row,) = self.h.records()
        self.assertEqual(row["category"], "terminal_invalid")
        for _ in range(15):
            self.h.tick(advance=60)
        self.assertEqual(self.h.backend.send_calls, [], "held, past its wait, while the failed turn is the latest")
        self.compaction()
        for _ in range(3):
            self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1, "the ordinary continuation, once")
        self.assertNotIn(self.h.record()["state"], ("superseded", "superseded_by_user"))
        self.assertNotIn("not_taken_up", [line[1] for line in self.h.logs], "taken up, so never said passed over")


class CodeTests(unittest.TestCase):
    class Scoped:
        def __init__(self, now, taken):
            self._now, self._taken = now, taken

        def now(self):
            return self._now

        def admission(self, key):
            return {"created_at": self._taken}

    def code(self, latest, *, now=1000.0, taken=900.0):
        class Reader:
            def latest(self, thread_id):
                return latest
        made = CompactContinue(None, turns=Reader(), session=lambda capability: None,
                               follower=headless.Follower(poll=0.01), app_running=lambda: False)
        made.bind(self.Scoped(now, taken))
        return made

    @staticmethod
    def turn(ordinal, kinds, status="completed"):
        return Turn("0" * 8 + "-0000-0000-0000-" + "0" * 12, status, False, 1, False, ordinal, kinds)

    def record(self, **changes):
        return dict({"interruption_id": KEY, "thread_id": T1, "category": "terminal_invalid", "ordinal": 5,
                     "holder": "none", "app": False}, **changes)

    def test_only_codex_s_own_context_window_code(self):
        code = self.code(None)
        self.assertIs(code.admission({"category": "terminal_invalid", "code": "contextWindowExceeded"}),
                      Alternative.ADMIT)
        for failure in ({"category": "terminal_invalid", "code": "badRequest"},
                        {"category": "unknown", "code": "contextWindowExceeded"}):
            self.assertIs(code.admission(failure), DEFER, failure)

    def test_known_failure_gives_up_after_a_day_or_a_failed_compaction(self):
        compacting = self.turn(6, {"contextCompaction": 1})
        self.assertIs(self.code(compacting).gate("known_failure", self.record(), {}), Alternative.ADMIT)
        self.assertIs(self.code(compacting, now=900.0 + GIVE_UP_SECONDS).gate("known_failure", self.record(), {}),
                      DEFER)
        failed_one = self.turn(6, {"contextCompaction": 1}, status="failed")
        self.assertIs(self.code(failed_one).gate("known_failure", self.record(), {}), DEFER)

    def test_held_in_the_app_until_a_compaction_alone_is_the_latest(self):
        self.assertIs(self.code(self.turn(5, {})).gate("thread_available", self.record(), {}), Alternative.HOLD)
        mixed = self.turn(6, {"contextCompaction": 1, "userMessage": 1})
        self.assertIs(self.code(mixed).gate("thread_available", self.record(), {}), Alternative.HOLD)
        alone = self.turn(6, {"contextCompaction": 1, "reasoning": 2})
        self.assertIs(self.code(alone).gate("thread_available", self.record(), {}), DEFER)

    def test_unheld_it_compacts_here_then_continues_here(self):
        first = self.code(self.turn(5, {})).unloaded(self.record())
        self.assertEqual(first.mode, headless.COMPACT)
        then = self.code(self.turn(6, {"contextCompaction": 1})).unloaded(self.record())
        self.assertEqual(then.mode, headless.TURN)
        for record in (self.record(holder="session", app=True), self.record(category="usage_limit")):
            self.assertIs(self.code(self.turn(5, {})).unloaded(record), DEFER, record)


class RegistryTests(CompactCase):
    def test_it_answers_at_p16_before_headless_run_and_is_shown_after_the_model_fallback(self):
        at = tuple(d.id for d in registry.REGISTRY.at(Point.UNLOADED))
        self.assertLess(at.index(self.cap), at.index("headless_run"))
        shown = registry.SHOWN_ORDER
        # 2026-10-31: the capacity retry, the model fallback, then this - the failures of Codex's own, together.
        self.assertEqual(shown[shown.index("capacity_retry"):shown.index("capacity_retry") + 3],
                         ("capacity_retry", "model_fallback", self.cap))

    def test_unmeasured_on_this_codex_is_a_warning_never_a_refusal(self):
        plug = self.advanced()
        definition = plug.runtime.registry.get(self.cap)
        self.assertIn(ArmingWarning.UNMEASURED, plug.runtime.arming.warnings(definition))
        self.measured = {word: (Verdict.PASS, ENGINE) for word in (Measurement.M7, Measurement.MX, Measurement.MXA)}
        self.assertNotIn(ArmingWarning.UNMEASURED, plug.runtime.arming.warnings(definition))
        self.measured = {}
        self.arm(plug)
        self.assertEqual(plug.runtime.states(fresh=True)[self.cap], ArmingState.ARMED)


class NoSlashTextTests(unittest.TestCase):
    """Design-4 5.2 and 12: no source file of either edition sends a text beginning with "/" - a queued slash command
    (M7: Codex keeps a queued /compact as plain text, so the queue never compacts; a person runs /compact). Read as
    source, so a text a later change adds is found before it is ever sent: every string the code of either edition
    holds that is shaped as a slash command, and every template a continuation or a message of this product is made of,
    in every language."""
    # Shaped as a slash command: "/" and a word, alone or before more - never a path such as "/pull/".
    COMMAND = re.compile(r"^\s*/[A-Za-z][\w-]*(\s|$)")
    # The one string allowed, and why: M7's own probe queues "/compact" once, by hand, on its own probe conversation, to
    # measure that Codex keeps it as plain text (measure.py, _m7) - a measurement, never a recovery's or a person's.
    ALLOWED = {("codex_auto_resume_advanced/measure.py", "_m7", "/compact")}

    @staticmethod
    def sources():
        for root in (ROOT / "src", ROOT / "advanced" / "src"):
            for path in sorted(root.rglob("*.py")):
                yield path.relative_to(root).as_posix(), path

    def commands(self) -> set:
        """(file, function, text) for every string constant shaped as a slash command, docstrings left out."""
        found = set()
        for name, path in self.sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            documented = {id(node.body[0].value) for node in ast.walk(tree)
                          if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                          and node.body and isinstance(node.body[0], ast.Expr)
                          and isinstance(node.body[0].value, ast.Constant)}
            for function in [tree] + [node for node in ast.walk(tree)
                                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                owner = getattr(function, "name", None)
                for node in ast.walk(function):
                    if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in documented
                            and self.COMMAND.match(node.value)):
                        found.add((name, owner, node.value.strip()))
        # A constant inside a function is found from the module too; the function's own name is the one kept.
        return {entry for entry in found if entry[1] is not None
                or not any(other[0] == entry[0] and other[2] == entry[2] and other[1] for other in found)}

    def test_no_source_holds_a_slash_command_but_m7s_probe(self):
        """Fails with any text such as "/compact" added to a send of either edition."""
        self.assertEqual(self.commands(), self.ALLOWED)

    def test_no_template_of_a_continuation_or_a_message_begins_with_a_slash(self):
        catalogs = [(ROOT / "src" / "codex_auto_resume" / "locales", ("continuation.",)),
                    (ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "locales", ("continue.",))]
        checked = 0
        for folder, prefixes in catalogs:
            for path in sorted(folder.glob("*.json")):
                for key, text in json.loads(path.read_text(encoding="utf-8")).items():
                    if key.startswith(prefixes):
                        checked += 1
                        self.assertFalse(text.lstrip().startswith("/"), "%s %s" % (path.name, key))
        self.assertGreater(checked, 18 * 20, "the templates were found")


if __name__ == "__main__":
    unittest.main()
