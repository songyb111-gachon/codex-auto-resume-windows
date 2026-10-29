"""v0.6.18 (audit M3): the toast's Cancel is tried again while the watcher holds the state, as a card's is.

A card's Cancel goes through the control layer, which tries a busy store again for CANCEL_RETRY_SECONDS. The toast's
went straight to the store once: a lock held past the store's own wait ended the windowless `activate` process in an
error on a stderr nobody reads, nothing cancelled and nothing said. Now it tries again for as long, and when the
state stays busy it leaves one line in the log and returns an error instead of raising.
"""
from __future__ import annotations

import contextlib
import io
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import cli, config, notifier, notify  # noqa: E402
from codex_auto_resume.commands import watcher as watcher_command  # noqa: E402
from codex_auto_resume.store import Store, StoreError  # noqa: E402
from test_control import KEY, detection  # noqa: E402


class ToastCancelBusyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.paths = config.Paths(self.home)
        self.paths.ensure()
        self.addCleanup(self._close)
        with Store(self.paths.state_dir) as store:
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
                patch.object(notifier, "deliver", lambda notice, **kwargs: delivered.append(notice)), \
                patch.object(watcher_command.time, "sleep", lambda seconds: None):
            code = cli.cmd_activate(args)
        return code, delivered

    def state(self):
        with Store(self.paths.state_dir) as store:
            return store.get(KEY)["state"]

    def test_a_busy_store_is_tried_again_and_the_cancel_lands(self):
        original, calls = Store.cancel_interruption, []

        def busy_once(store, *args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise StoreError("database is locked")
            return original(store, *args, **kwargs)

        with patch.object(Store, "cancel_interruption", busy_once):
            code, delivered = self.activate()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.state(), "cancelled")
        self.assertEqual([notice.kind for notice in delivered], ["cancelled"])

    def test_a_store_that_stays_busy_ends_in_an_error_code_not_an_exception(self):
        with patch.object(Store, "cancel_interruption", side_effect=StoreError("database is locked")), \
                patch("codex_auto_resume.control.actions.CANCEL_RETRY_SECONDS", 0.0):
            code, delivered = self.activate()
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(delivered, [])
        self.assertNotEqual(self.state(), "cancelled")


if __name__ == "__main__":
    unittest.main()
