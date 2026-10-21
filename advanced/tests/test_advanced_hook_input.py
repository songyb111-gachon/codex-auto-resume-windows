"""The Stop hook's handler (hook/handler.py, stop_hook_continuation, plans/v0619-design/D-stop-hook.md): what it reads
of Codex's input and what it answers.

Held here: the input is kept through an allow-list of keys and no other key's value is ever asked for - a sentinel
whose every other access fails the test, and fuzzed documents whose other keys never come out; input over the bound,
not UTF-8, not JSON or not one object passes; only a Stop of a conversation named by its id, and never one that follows
a hook's own block, is looked at; it continues only a failed latest turn - the one the input names - of a kind a hook can
wait for, under the person's settings, and only where the shared claim grants it; it answers within its budget or
passes; and the block's reason is the standard continuation with the record's marker after it.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import random
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume import settings  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume_advanced.hook import format as hookformat, handler  # noqa: E402
from codex_auto_resume_advanced.vocabulary import HookOutcome  # noqa: E402

THREAD = "11111111-1111-4111-8111-111111111111"
TURN = "22222222-2222-4222-8222-222222222222"
ALLOWED = set(hookformat.allowed_keys())
STARTED = 1_790_000_000.0


def stop(**changes) -> dict:
    found = {"hook_event_name": "Stop", "session_id": THREAD, "turn_id": TURN, "stop_hook_active": False}
    found.update(changes)
    return found


def row(code="httpConnectionFailed", status="failed", turn=TURN) -> dict:
    return {"thread_id": THREAD, "turn_id": turn, "status": status, "started_at": STARTED, "completed_at": STARTED + 10,
            "rollout_ordinal": 3, "error_json": json.dumps({"codexErrorInfo": code, "message": "never read"})}


class Sentinel(dict):
    """A document whose every key but the allowed ones fails the test when its value is asked for - and which cannot be
    walked at all, so a reader that iterates it fails too."""
    def __getitem__(self, key):
        if key not in ALLOWED:
            raise AssertionError("the value of %r was read" % key)
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        if key not in ALLOWED:
            raise AssertionError("the value of %r was read" % key)
        return dict.get(self, key, default)

    def _walked(self, *_arguments):
        raise AssertionError("the document was walked")

    __iter__ = keys = values = items = copy = _walked


class Hands(handler.Hands):
    def __init__(self, *, armed=True, values=None, latest=None, outcome=HookOutcome.BLOCKED, clock=None):
        self.claims = []

        def claim(failure, turn_key, now):
            self.claims.append((failure["interruption_id"], turn_key, now))
            return outcome
        super().__init__(armed=lambda: armed, settings=lambda: dict(values or settings.DEFAULTS),
                         latest=lambda thread: latest if latest is not None else handler_row_for(thread),
                         claim=claim, clock=clock or time.time)


def handler_row_for(thread):
    from codex_auto_resume.codex.values import normalize
    return normalize(dict(row(), thread_id=thread))


class AllowListTests(unittest.TestCase):
    def test_only_the_allowed_keys_are_read_and_nothing_is_walked(self):
        """Fails with a reader that copies the document or reads any other key."""
        document = Sentinel(stop(last_assistant_message="secret words", transcript_path="C:\\somewhere",
                                 prompt="more words"))
        self.assertEqual(handler.pick(document), stop())

    def test_the_parser_drops_every_other_key_as_it_reads(self):
        raw = json.dumps(stop(last_assistant_message="secret words", transcript_path="C:\\x", cwd="C:\\y",
                              nested={"session_id": "inner", "text": "deep"})).encode("utf-8")
        picked = handler.read_input(io.BytesIO(raw))
        self.assertEqual(picked, stop())
        self.assertNotIn("secret", json.dumps(picked))

    def test_fuzzed_documents_give_back_only_allowed_keys(self):
        generator = random.Random(19)
        words = sorted(ALLOWED) + ["last_assistant_message", "transcript_path", "prompt", "cwd", "model", "x"]

        def value(depth):
            kind = generator.randrange(6 if depth < 3 else 4)
            if kind == 0:
                return generator.random()
            if kind == 1:
                return "".join(chr(generator.randrange(32, 0x2FFF)) for _ in range(generator.randrange(20)))
            if kind == 2:
                return generator.choice([True, False, None])
            if kind == 3:
                return generator.randrange(-10 ** 6, 10 ** 6)
            if kind == 4:
                return [value(depth + 1) for _ in range(generator.randrange(4))]
            return {generator.choice(words): value(depth + 1) for _ in range(generator.randrange(5))}

        for _ in range(300):
            document = {generator.choice(words): value(0) for _ in range(generator.randrange(8))}
            picked = handler.read_input(io.BytesIO(json.dumps(document).encode("utf-8")))
            self.assertIsNotNone(picked)
            self.assertLessEqual(set(picked), ALLOWED)
            for key in picked:
                if isinstance(document[key], dict):
                    self.assertLessEqual(set(picked[key]), ALLOWED, "an object inside is kept to the list too")

    def test_oversize_malformed_and_not_an_object_pass(self):
        big = json.dumps(stop(padding="x" * handler.MAX_INPUT)).encode("utf-8")
        for raw in (big, b"", b"not json", b"[1, 2]", b'"Stop"', b"\xff\xfe{}", b"[" * 100000 + b"]" * 100000,
                    b'{"hook_event_name": "Stop"'):
            with self.subTest(raw[:20]):
                self.assertIsNone(handler.read_input(io.BytesIO(raw)))
        self.assertIsNotNone(handler.read_input(io.BytesIO(json.dumps(stop()).encode("utf-8"))))


class StopTests(unittest.TestCase):
    def test_only_a_stop_of_a_named_conversation_not_following_a_block(self):
        self.assertEqual(handler.stop_of(stop()), (THREAD, TURN))
        self.assertEqual(handler.stop_of(stop(turn_id=None)), (THREAD, None))
        for changed in (stop(hook_event_name="SubagentStop"), stop(stop_hook_active=True), stop(session_id="latest"),
                        stop(session_id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"), stop(turn_id="7"), {"session_id": THREAD}, None, []):
            with self.subTest(changed):
                self.assertIsNone(handler.stop_of(changed))


class DecisionTests(unittest.TestCase):
    def test_a_transient_failure_of_the_named_turn_is_claimed_and_continued_with_its_marker(self):
        hands = Hands()
        reason = handler.decide(stop(), hands)
        self.assertEqual(len(hands.claims), 1)
        key, turn_key, _now = hands.claims[0]
        self.assertEqual(key, ids.interruption_id(THREAD, TURN, STARTED + 10, 3), "core's own id, so the watcher knows it")
        self.assertEqual(turn_key, handler.turn_key(TURN))
        self.assertNotIn(TURN, turn_key)
        self.assertTrue(reason.endswith("\n\n" + ids.short_marker(key)))
        self.assertNotIn("never read", reason)

    def test_nothing_is_claimed_where_the_capability_is_off(self):
        hands = Hands(armed=False)
        self.assertIsNone(handler.decide(stop(), hands))
        self.assertEqual(hands.claims, [])

    def test_a_claim_not_granted_passes(self):
        for outcome in (HookOutcome.PASSED, HookOutcome.REFUSED, None):
            with self.subTest(outcome):
                self.assertIsNone(handler.decide(stop(), Hands(outcome=outcome)))

    def test_only_what_a_hook_can_wait_for_is_taken(self):
        """A usage limit waits hours and stays the watcher's; a rate limit, a terminal kind, an unknown error and a
        turn that completed are never the hook's (keep going after a normal stop is keep_going's)."""
        from codex_auto_resume.codex.values import normalize
        for code, status in (("usageLimitExceeded", "failed"), ("rateLimitExceeded", "failed"),
                             ("contextWindowExceeded", "failed"), ("somethingNew", "failed"),
                             ("httpConnectionFailed", "completed"), ("httpConnectionFailed", "interrupted")):
            with self.subTest(code=code, status=status):
                hands = Hands(latest=normalize(row(code, status)))
                self.assertIsNone(handler.decide(stop(), hands))
                self.assertEqual(hands.claims, [])
        for code in ("httpConnectionFailed", "internalServerError", "responseStreamDisconnected"):
            with self.subTest(code=code):
                self.assertIsNotNone(handler.decide(stop(), Hands(latest=normalize(row(code)))))

    def test_another_turn_than_the_named_one_passes(self):
        from codex_auto_resume.codex.values import normalize
        other = "33333333-3333-4333-8333-333333333333"
        hands = Hands(latest=normalize(row(turn=other)))
        self.assertIsNone(handler.decide(stop(), hands))
        self.assertIsNotNone(handler.decide(stop(turn_id=None), hands), "no turn named: the latest failure is it")

    def test_the_person_s_settings_hold_it(self):
        values = dict(settings.DEFAULTS, recover_network_transient=False)
        self.assertIsNone(handler.decide(stop(), Hands(values=values)))
        slow = dict(settings.DEFAULTS, retry_timing="custom", retry_wait_1="m2")
        self.assertIsNone(handler.decide(stop(), Hands(values=slow)), "a first wait past a minute is the watcher's")

    def test_no_claim_is_begun_once_the_budget_is_nearly_spent(self):
        hands = Hands()
        self.assertIsNone(handler.decide(stop(), hands, started=time.time() - handler.BUDGET_SECONDS))
        self.assertEqual(hands.claims, [])


class MainTests(unittest.TestCase):
    def run_main(self, raw, hands):
        out = io.BytesIO()
        code = handler.main(["--home", "unused"], stdin=io.BytesIO(raw), stdout=out, hands=hands)
        return code, out.getvalue()

    def test_a_block_is_one_json_object_in_the_format_s_words(self):
        code, out = self.run_main(json.dumps(stop()).encode("utf-8"), Hands())
        self.assertEqual(code, 0)
        answer = json.loads(out.decode("utf-8"))
        self.assertEqual(set(answer), {hookformat.FORMAT.decision_key, hookformat.FORMAT.reason_key})
        self.assertEqual(answer[hookformat.FORMAT.decision_key], hookformat.FORMAT.block_word)

    def test_every_pass_is_exit_zero_and_nothing_written(self):
        for raw, hands in ((b"x" * (handler.MAX_INPUT + 1), Hands()), (b"{oops", Hands()),
                           (json.dumps(stop()).encode("utf-8"), Hands(armed=False)),
                           (json.dumps(stop()).encode("utf-8"), Hands(outcome=HookOutcome.REFUSED))):
            with self.subTest(raw[:10]):
                self.assertEqual(self.run_main(raw, hands), (0, b""))

    def test_a_hand_that_raises_passes(self):
        hands = Hands()
        hands.latest = lambda thread: (_ for _ in ()).throw(RuntimeError("Codex's history is locked"))
        self.assertEqual(self.run_main(json.dumps(stop()).encode("utf-8"), hands), (0, b""))

    def test_past_the_budget_with_no_claim_begun_it_passes_at_once(self):
        """Fails with a handler that waits for its reads: a turn's end would be held by them."""
        release = threading.Event()
        self.addCleanup(release.set)
        hands = Hands()
        hands.latest = lambda thread: release.wait(30) and None
        with patch.object(handler, "BUDGET_SECONDS", 0.3):
            started = time.monotonic()
            self.assertEqual(self.run_main(json.dumps(stop()).encode("utf-8"), hands), (0, b""))
            self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(hands.claims, [])


if __name__ == "__main__":
    unittest.main()
