"""A named object another account created first is refused, not only one of a lower integrity (v0.6.18, security M2).

The watcher's mutex and its stop, wake and demo events have names anyone who reads the code can work out. The
v0.6.0 check refuses one a lower-integrity process made first. A process of ANOTHER account at the same
integrity - a sandbox account Codex runs commands under in this session, say - could still make one first with a
DACL that lets it hold or signal it later: a held mutex makes every status say "running", a signalled stop event
makes the watcher exit. Such an object's owner is that account, so it is refused as squatted too. An object this
account made (a real second watcher's), or one only someone with more rights could make (the administrators an
elevated process of this account owns its objects as, or SYSTEM), is still honoured.

No second account exists on a test machine, so the foreign owner is handed in where the owner is read.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from codex_auto_resume import config
from codex_auto_resume.app import App, EXIT_ERROR
from codex_auto_resume.win import kernel
from codex_auto_resume.windows import AdapterError

from test_named_objects import close, plant

OTHER_ACCOUNT = "S-1-5-21-1111111111-2222222222-3333333333-1002"


class TrustedOwnerTests(unittest.TestCase):
    def test_who_may_own_an_existing_object(self):
        me = "S-1-5-21-1-2-3-1001"
        self.assertTrue(kernel.trusted_owner(me, me))
        self.assertTrue(kernel.trusted_owner("S-1-5-32-544", me), "an elevated process of this account")
        self.assertTrue(kernel.trusted_owner("S-1-5-18", me), "Windows itself")
        self.assertFalse(kernel.trusted_owner(OTHER_ACCOUNT, me))
        self.assertFalse(kernel.trusted_owner("S-1-1-0", me), "Everyone is not an owner to trust")
        self.assertFalse(kernel.trusted_owner(None, me), "an owner that could not be read")
        self.assertFalse(kernel.trusted_owner(me, None), "this account could not be read")


@unittest.skipUnless(os.name == "nt", "Windows named objects")
class ForeignOwnerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(config.Paths(str(Path(self.folder.name) / "home")), console=False, enable_logging=False)

    def foreign(self):
        return mock.patch.object(kernel, "_owner_sid", lambda handle: OTHER_ACCOUNT, create=True)

    def test_this_accounts_own_objects_are_read_as_its_own(self):
        handle = plant("mutex", self.app.mutex().name, None)
        self.addCleanup(close, handle)
        # An elevated token (a CI runner's administrator) gives what it makes to the Administrators group, which
        # trusted_owner accepts as this account's own; any other token gives it to the account itself.
        self.assertIn(kernel._owner_sid(handle), {kernel._user_sid(), *kernel.TRUSTED_OWNERS})
        self.assertTrue(kernel.trusted_owner(kernel._owner_sid(handle), kernel._user_sid()))
        self.assertIs(self.app.watcher_running(), False, "a real second watcher's mutex is still honoured")

    def test_a_mutex_another_account_made_first_is_refused(self):
        handle = plant("mutex", self.app.mutex().name, None)
        self.addCleanup(close, handle)
        with self.foreign():
            self.assertIsNone(self.app.watcher_running(), "unknown, not a phantom watcher")
            with self.assertRaises(AdapterError) as caught:
                with self.app.mutex(timeout=0.0):
                    pass
        self.assertEqual(str(caught.exception), "named_object_squatted")

    def test_the_watcher_refuses_a_stop_event_another_account_made_first(self):
        handle = plant("event", self.app.stop_event().name, None)
        self.addCleanup(close, handle)
        with self.foreign():
            self.assertEqual(self.app.run(once=True), EXIT_ERROR)

    def test_a_new_object_is_never_asked_about_its_owner(self):
        """Only an object that existed before is suspect: one this process just made is its own."""
        with self.foreign():
            self.assertIs(self.app.watcher_running(), False)

    def test_an_elevated_owner_is_honoured(self):
        handle = plant("mutex", self.app.mutex().name, None)
        self.addCleanup(close, handle)
        with mock.patch.object(kernel, "_owner_sid", lambda handle: "S-1-5-32-544", create=True):
            self.assertIs(self.app.watcher_running(), False)


if __name__ == "__main__":
    unittest.main()
