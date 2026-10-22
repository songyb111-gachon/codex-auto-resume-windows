"""v0.6.18 (docs audit R6, D4): a crafted cancel URI cannot put Open Codex on a standard edition's notice.

Open Codex on a notice is an advanced capability that departs from A28 (a notification's buttons cancel, stop the
power action, or open one Dashboard page - nothing else). The watcher carries its decision on the cancel button's URI
(`&c=1`, notify.cancel_asks_open_codex) for the notice a toast's Cancel raises, since that process loads no plug - and
`activate` honoured the flag with no edition or capability check, so a `codex-auto-resume:` cancel URI with `&c=1` made
a standard installation offer the advanced edition's button. Now the flag is honoured only where the edition offers
the button now: never in the standard edition, and in the advanced only while its plug's icon surface says so.
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

from codex_auto_resume import cli, config, edition, notifier, notify  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_control import KEY, detection  # noqa: E402


class FakePlug:
    def __init__(self, answer):
        self.answer = answer

    def surface(self, name, facts):
        return self.answer if name == "tray" else {}


class OpenCodexFlagTests(unittest.TestCase):
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

    def offers_open_codex(self, *patches):
        uri = notify.with_open_codex_flag(notify.cancel_uri(KEY))
        self.assertTrue(notify.cancel_asks_open_codex(uri))
        args = cli.build_parser().parse_args(["--home", str(self.home), "--quiet", "activate", uri])
        delivered = []
        with contextlib.ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(notifier, "deliver",
                                             lambda notice, **kwargs: delivered.append(notice)))
            self.assertEqual(cli.cmd_activate(args), cli.EXIT_OK)
        self.assertEqual([notice.kind for notice in delivered], ["cancelled"])
        return any(notify.parse_codex_thread_uri(link) is not None for _label, link in delivered[0].actions)

    def test_the_standard_edition_ignores_the_flag(self):
        self.assertFalse(self.offers_open_codex(
            patch.object(edition, "name", return_value=edition.Edition.STANDARD),
            patch.object(edition, "plug", return_value=FakePlug({"notice": {"open_codex": True}}))))

    def test_the_advanced_edition_ignores_it_while_the_capability_is_off(self):
        self.assertFalse(self.offers_open_codex(
            patch.object(edition, "name", return_value=edition.Edition.ADVANCED),
            patch.object(edition, "plug", return_value=FakePlug({}))))

    def test_the_advanced_edition_honours_it_while_the_capability_is_on(self):
        self.assertTrue(self.offers_open_codex(
            patch.object(edition, "name", return_value=edition.Edition.ADVANCED),
            patch.object(edition, "plug", return_value=FakePlug({"notice": {"open_codex": True}}))))


if __name__ == "__main__":
    unittest.main()
