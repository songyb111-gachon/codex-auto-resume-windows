"""The local log: what it says about a state, and what it still refuses to say.

Two things are being protected.

The first is that the log answers the question it is read for. It is the only record of
why a recovery did what it did - the diagnostics bundle carries its last lines, and a bug
report quotes them - and a line that names a state without naming the reason for it sends
the reader back to the source. `STATE_CODES` listed 13 of the state machine's 27 states,
so for the other 14 the reason was not read as a reason at all: it arrived in the detail
slot, where no template prints it, and the line came out as the bare state name. Every
outcome of a recovery turn was in that half - `recovered`, `completed_no_progress`,
`recovery_turn_failed`, `handed_over`, `stopped_by_user`, `outcome_unverified` - and so
were the two exhaustions, `withdrawn_unconfirmed` and `turn_started`.

The second is that saying more does not mean saying anything new. Prompt text, Codex error
text and usage-account fields have never reached this module and still do not: a reason is
a static code from the engine's own vocabulary, and anything that is not one word of
`[A-Za-z0-9_]` is written as "unspecified" rather than printed.
"""
from __future__ import annotations

import unittest

from codex_auto_resume import logbook, machine

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
# A reason of the shape the engine writes: one word from its own closed vocabulary, and
# deliberately one the message table has no sentence for. That is the general case - the
# table pairs a sentence with 13 of the reasons a state can carry, and the engine writes
# more than that - and it is the case the log was dropping.
REASON = "thread_disabled"


class Recorder:
    """The logger EngineLog writes through, kept to one line at a time."""

    def __init__(self):
        self.lines = []

    def info(self, line):
        self.lines.append(line)


class StateVocabularyTests(unittest.TestCase):
    """The list of what counts as a state is derived, so it cannot go stale again."""

    def test_every_stored_state_is_read_as_a_state(self):
        self.assertEqual(set(logbook.STATE_CODES), set(machine.STATES))

    def test_the_states_the_list_used_to_miss_are_in_it(self):
        # Named rather than counted: these are the 14 the log was silent about, and this
        # is the list a reviewer can check against `machine.py` by eye.
        for state in ("turn_started", "turn_completed", "recovered", "completed_no_progress",
                      "recovery_turn_failed", "handed_over", "stopped_by_user",
                      "outcome_unverified", "retry_budget_exhausted", "no_progress_exhausted",
                      "terminal_failure", "superseded_by_user", "withdrawn_unconfirmed",
                      "waiting_backoff"):
            with self.subTest(state=state):
                self.assertIn(state, logbook.STATE_CODES)
                self.assertIn(state, machine.STATES)


class ReasonTests(unittest.TestCase):
    """No state is left without its reason."""

    def test_the_reason_this_file_uses_really_has_no_sentence_of_its_own(self):
        # Otherwise the tests below would be measuring the message table rather than the
        # rule, and would go quiet the day a sentence was written for this reason.
        self.assertEqual([key for key in logbook._MESSAGES if key[1] == REASON], [])
        self.assertIn(REASON, machine.WITHDRAW_REASONS)

    def test_every_state_says_the_reason_it_was_given(self):
        for state in sorted(machine.STATES):
            with self.subTest(state=state):
                line = logbook.render(THREAD, state, REASON)
                self.assertIn(REASON, line, line)

    def test_every_state_says_the_reason_through_the_engine_adapter(self):
        # The engine calls `log(thread, state, reason)`; the adapter decides which of its
        # two shapes that is. A state the adapter does not recognise reads the reason as a
        # detail, and no template prints a detail - which is exactly how the reason was
        # lost. Asserted end to end, on the lines that would reach the file.
        for state in sorted(machine.STATES):
            with self.subTest(state=state):
                recorder = Recorder()
                logbook.EngineLog(recorder)(THREAD, state, REASON)
                self.assertTrue(recorder.lines)
                self.assertIn(REASON, "\n".join(recorder.lines))

    def test_the_reason_is_said_once(self):
        # Some templates already carry `{reason}` in their own words. Appending it to
        # those would say it twice, which reads like two different reasons.
        for state in sorted(machine.STATES):
            with self.subTest(state=state):
                self.assertEqual(logbook.render(THREAD, state, REASON).count(REASON), 1)

    def test_a_state_with_no_reason_reads_as_it_always_has(self):
        # The lines a person recognises. Unchanged, word for word.
        for state, wanted in (("waiting_reset", "waiting for reset"),
                              ("waiting_poll", "waiting (no reset timestamp; conservative polling)"),
                              ("resumed", "resumed"),
                              ("cancelled", "cancelled"),
                              ("queued", "queued; awaiting delivery receipt")):
            with self.subTest(state=state):
                self.assertEqual(logbook.render(THREAD, state, None),
                                 "thread " + THREAD + ": " + wanted)

    def test_a_reason_with_its_own_sentence_keeps_it(self):
        # Where a (state, reason) pair has been given words, those words are what is
        # written - the appended code would be noise beside them.
        self.assertEqual(logbook.render(THREAD, "waiting_for_app", "desktop_app_unavailable"),
                         "thread " + THREAD + ": ChatGPT app or its Codex server not "
                         "running; waiting")
        self.assertEqual(logbook.render(THREAD, "failed", "daily_submission_cap"),
                         "thread " + THREAD + ": daily submission cap reached; giving up "
                         "on this interruption")


class PrivacyTests(unittest.TestCase):
    """Saying the reason for every state says nothing that was not already allowed."""

    UNSAFE = ("C:\\Users\\someone\\.codex\\sessions", "sk-live-0123456789",
              "error: connection to api failed", "reason\nwith a break", "x" * 200, 17)

    def test_a_reason_that_is_not_a_static_code_is_not_printed(self):
        for state in sorted(machine.STATES):
            for reason in self.UNSAFE:
                with self.subTest(state=state, reason=repr(reason)):
                    line = logbook.render(THREAD, state, reason)
                    self.assertNotIn("Users", line)
                    self.assertNotIn("sk-live", line)
                    self.assertNotIn("api failed", line)
                    self.assertNotIn("\n", line)
                    self.assertLess(len(line), 200)

    def test_an_unreadable_reason_is_said_as_unspecified(self):
        self.assertIn("unspecified", logbook.render(THREAD, "turn_started", "not a code at all"))

    def test_a_detail_is_still_not_read_as_a_reason(self):
        # The adapter's other shape: an event code carries a detail, and an interruption
        # hash is still the only kind of detail that is printed at all.
        recorder = Recorder()
        logbook.EngineLog(recorder)(THREAD, "usageLimitExceeded_detected", "a" * 64)
        self.assertEqual(recorder.lines,
                         ["thread " + THREAD + ": usageLimitExceeded detected "
                          "(interruption " + "a" * 12 + ")"])

    def test_an_event_still_reads_its_detail_as_a_detail(self):
        recorder = Recorder()
        logbook.EngineLog(recorder)(THREAD, "reset_expected", "1788645827")
        self.assertIn(logbook.format_local(1788645827), recorder.lines[0])


if __name__ == "__main__":
    unittest.main()
