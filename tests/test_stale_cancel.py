"""v0.6.18 (audit R3): a stale notice's Cancel never says "Automatic recovery cancelled" for a finished recovery.

A detection notice can stay in Windows' notification centre, or on screen, long after its recovery was recovered.
A Cancel pressed on it then changes nothing (the store answers changed: False), yet both routes still raised the
cancelled notice - "This task will not be recovered automatically" - about a task that had already gone on. Now
neither announces anything when nothing changed: the card's `activate` answers "already_finished", the toast's
`activate` command leaves its line in the log and delivers nothing.
"""
from __future__ import annotations

import contextlib
import io
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import cli, config, notifier, notify  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_control import KEY, THREAD, detection  # noqa: E402


class CardCancelTests(unittest.TestCase):
    def test_a_cancel_that_changed_nothing_announces_nothing_and_says_so(self):
        control = MagicMock()
        control.cancel_interruption.return_value = {"thread_id": THREAD, "changed": False}
        announced, lines = [], []
        result = notifier.activate(notify.cancel_uri(KEY), control=control, announce=announced.append,
                                   log=lines.append)
        self.assertEqual(result, "already_finished")
        self.assertEqual(announced, [], "no notice says it was cancelled")
        self.assertEqual(len(lines), 1)
        self.assertIn("already finished", lines[0])

    def test_a_cancel_that_stopped_something_still_says_so(self):
        control = MagicMock()
        control.cancel_interruption.return_value = {"thread_id": THREAD, "changed": True}
        announced = []
        self.assertEqual(notifier.activate(notify.cancel_uri(KEY), control=control, announce=announced.append),
                         "cancelled")
        self.assertEqual([notice.kind for notice in announced], ["cancelled"])


class ToastCancelTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        config.Paths(self.home).ensure()
        self.addCleanup(self._close)
        with Store(config.Paths(self.home).state_dir) as store:
            store.set_enabled(True, 90.0)
            store.register(detection(), 100.0)

    @staticmethod
    def _close():
        logger = logging.getLogger("codex_auto_resume")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def activate(self):
        args = cli.build_parser().parse_args(["--home", str(self.home), "--quiet", "activate",
                                              notify.cancel_uri(KEY)])
        delivered = []
        with contextlib.redirect_stdout(io.StringIO()), \
                patch.object(notifier, "deliver", lambda notice, **kwargs: delivered.append(notice)):
            code = cli.cmd_activate(args)
        return code, delivered

    def finish(self, state):
        with Store(config.Paths(self.home).state_dir) as store:
            store.update(KEY, at=200.0, state=state)

    def test_a_task_that_finished_since_is_not_announced_as_cancelled(self):
        self.finish("superseded")       # gone on without this recovery: the notice is stale
        code, delivered = self.activate()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(delivered, [], "no notice says it was cancelled")

    def test_a_waiting_task_is_cancelled_and_says_so(self):
        code, delivered = self.activate()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual([notice.kind for notice in delivered], ["cancelled"])
        with Store(config.Paths(self.home).state_dir) as store:
            self.assertEqual(store.get(KEY)["state"], "cancelled")

    def test_a_second_press_says_nothing_more(self):
        self.activate()
        _, delivered = self.activate()
        self.assertEqual(delivered, [])


if __name__ == "__main__":
    unittest.main()
