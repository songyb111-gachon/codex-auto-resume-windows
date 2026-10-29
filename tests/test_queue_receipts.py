"""A `codex queue` that leaves no one-line receipt (PR #53, @Kdevaulo): the record is held as submission_unknown before
anything is logged, the log names why in fixed words only - never the CLI's output, the message or an error text - and
no diagnostic ever adds a second send.

In a module of its own: test_engine is one of the frozen scenario modules (tests/neutral.py MODULES), whose scenarios
stay the ones v0.6.10 was tested with; these began there in the PR and moved here when it was merged.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from test_engine import EngineCase, T1  # noqa: E402


class QueueReceiptTests(EngineCase):
    def test_queue_receipt_details_are_log_only_and_do_not_retry(self):
        for detail, code, wanted in (("nonzero_exit", 2, "queue_receipt_exit_nonzero"),
                                     ("empty_stdout", None, "queue_receipt_empty_stdout"),
                                     ("unrecognized_stdout", None, "queue_receipt_unrecognized_stdout")):
            with self.subTest(detail=detail):
                h = self.fresh()
                self.ready_after_reset(h)
                response = {"outcome": "unknown", "error_code": "queue_response_unconfirmed",
                            "receipt_detail": detail, "exit_code": code}
                with patch.object(h.backend, "send", return_value=response) as send:
                    h.tick()
                    self.assertEqual(h.record()["state"], "submission_unknown")
                    self.assertEqual(h.record()["last_error"], "queue_result_unknown_do_not_resend")
                    self.assertIn((T1, wanted, str(code) if code is not None else None), h.logs)
                    for _ in range(3):
                        h.tick(advance=1800)
                    self.assertEqual(send.call_count, 1, "diagnostics must never add a send")

    def test_untrusted_receipt_details_never_reach_the_log(self):
        self.ready_after_reset()
        response = {"outcome": "unknown", "error_code": "queue_response_unconfirmed",
                    "receipt_detail": "secret prompt\nwith a newline", "exit_code": "secret token"}
        with patch.object(self.h.backend, "send", return_value=response):
            self.h.tick()
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        self.assertNotIn("secret", repr(self.h.logs))

    def test_diagnostic_logger_failure_cannot_affect_delivery_state(self):
        self.ready_after_reset()
        response = {"outcome": "unknown", "error_code": "queue_response_unconfirmed",
                    "receipt_detail": "empty_stdout"}
        old_log = self.h.engine.log

        def fail_diagnostic(thread_id, event, detail):
            if event.startswith("queue_receipt_"):
                raise OSError("logger unavailable")
            old_log(thread_id, event, detail)

        self.h.engine.log = fail_diagnostic
        with patch.object(self.h.backend, "send", return_value=response) as send:
            self.h.tick()
            self.assertEqual(self.h.record()["state"], "submission_unknown")
            self.assertEqual(self.h.record()["last_error"], "queue_result_unknown_do_not_resend")
            self.h.tick(advance=1800)
            self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
