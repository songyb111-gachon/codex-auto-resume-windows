"""account_auto_switch's saved accounts and Codex's sign-in file (v0.6.22): sealed profiles, fail-closed stores, atomic swaps.

Every home is a temporary folder and every sign-in file a fixture of no one's (a JSON object with no token in it): no real
Codex home, sign-in file or product home is read or written. The DPAPI round trip seals and opens a fixture for the
Windows user running the tests; nothing is kept.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume_advanced import profiles  # noqa: E402
from codex_auto_resume_advanced.codex import authfile  # noqa: E402
from codex_auto_resume_advanced.win import dpapi  # noqa: E402

FIRST = json.dumps({"fixture": "first account", "n": 1}).encode("utf-8")
SECOND = json.dumps({"fixture": "second account", "n": 2}).encode("utf-8")


def sealed(data):
    return b"SEALED:" + bytes(reversed(data))


def opened(blob):
    if not blob.startswith(b"SEALED:"):
        raise dpapi.DpapiError(13, "not ours")
    return bytes(reversed(blob[len(b"SEALED:"):]))


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="car-autoswitch-"))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.codex = self.dir / "codex-home"
        self.codex.mkdir()
        self.home = self.dir / "product-home"


class DpapiTests(unittest.TestCase):
    def test_a_blob_opens_for_this_user_and_label_only(self):
        blob = dpapi.protect(FIRST)
        self.assertNotIn(b"first account", blob)
        self.assertEqual(dpapi.unprotect(blob), FIRST)
        with patch.object(dpapi, "ENTROPY", b"another label"):
            with self.assertRaises(dpapi.DpapiError):
                dpapi.unprotect(blob)
        with self.assertRaises(dpapi.DpapiError):
            dpapi.unprotect(b"not a blob at all")


class StoreModeTests(Temp):
    def test_only_a_file_store_with_a_file_is_usable(self):
        """Fails if a keyring, auto or ephemeral store - or no file - were switched: the sign-in is not in a file there."""
        self.assertEqual(authfile.usable(self.codex), authfile.NO_FILE)
        (self.codex / "auth.json").write_bytes(FIRST)
        self.assertEqual(authfile.usable(self.codex), authfile.USABLE)
        for mode, word in (("keyring", authfile.NOT_FILE), ("auto", authfile.NOT_FILE),
                           ("ephemeral", authfile.NOT_FILE), ("file", authfile.USABLE), ("nonsense", authfile.UNREADABLE)):
            with self.subTest(mode):
                (self.codex / "config.toml").write_text('model = "x"\ncli_auth_credentials_store = "%s"\n' % mode,
                                                        encoding="utf-8")
                self.assertEqual(authfile.usable(self.codex), word)
        (self.codex / "config.toml").write_text("this is [not toml", encoding="utf-8")
        self.assertEqual(authfile.usable(self.codex), authfile.UNREADABLE)

    def test_a_damaged_copy_is_never_written_into_codex_home(self):
        (self.codex / "auth.json").write_bytes(FIRST)
        for bad in (b"", b"[1, 2]", b"{}", b"not json", b"{" + b" " * authfile.LIMIT + b"}"):
            with self.subTest(bad[:10]), self.assertRaises(authfile.AuthFileError):
                authfile.replace(self.codex, bad)
        self.assertEqual((self.codex / "auth.json").read_bytes(), FIRST)

    def test_a_replace_is_whole_and_leaves_nothing_beside_it(self):
        (self.codex / "auth.json").write_bytes(FIRST)
        authfile.replace(self.codex, SECOND)
        self.assertEqual(authfile.read(self.codex), SECOND)
        self.assertEqual(sorted(path.name for path in self.codex.iterdir()), ["auth.json"])

    def test_a_crash_before_the_rename_leaves_the_old_file(self):
        (self.codex / "auth.json").write_bytes(FIRST)
        with patch("codex_auto_resume_advanced.codex.authfile.os.replace", side_effect=OSError("power cut")):
            with self.assertRaises(authfile.AuthFileError):
                authfile.replace(self.codex, SECOND)
        self.assertEqual(authfile.read(self.codex), FIRST)
        self.assertEqual(sorted(path.name for path in self.codex.iterdir()), ["auth.json"])

    def test_a_scratch_home_keeps_a_refreshed_copy_and_goes(self):
        with authfile.Scratch(self.home / "accounts", FIRST) as where:
            self.assertIn('cli_auth_credentials_store = "file"', (where / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual((where / "auth.json").read_bytes(), FIRST)
            (where / "auth.json").write_bytes(SECOND)          # Codex refreshed the tokens there
        scratch = authfile.Scratch(self.home / "accounts", FIRST)
        with scratch:
            (scratch.path / "auth.json").write_bytes(SECOND)
        self.assertEqual(scratch.after, SECOND)
        self.assertFalse(scratch.path.exists())


class ProfileTests(Temp):
    def store(self, clock=lambda: 1_800_000_000):
        return profiles.Profiles(self.home, seal=sealed, open_=opened, clock=clock)

    def test_a_profile_is_sealed_and_named_by_nothing_of_the_account(self):
        store = self.store()
        profile_id = store.save(FIRST, "Someone@Example.com", "plus")
        files = list((self.home / "accounts").iterdir())
        self.assertEqual([path.name for path in files], [profile_id + ".dat"])
        raw = files[0].read_bytes()
        self.assertNotIn(b"someone", raw.lower())
        self.assertNotIn(b"first account", raw)
        self.assertEqual(store.get(profile_id)["auth"], FIRST)

    def test_the_same_account_saved_again_replaces_its_copy(self):
        store = self.store()
        first = store.save(FIRST, "someone@example.com", "plus")
        again = store.save(SECOND, "SOMEONE@example.com", "pro")
        self.assertEqual(first, again)
        self.assertEqual(store.get(first)["auth"], SECOND)
        self.assertEqual(len(store.ids()), 1)

    def test_the_view_shows_only_a_masked_address(self):
        store = self.store()
        store.save(FIRST, "someone@example.com", "plus")
        view = store.view()
        self.assertEqual(view[0]["mask"], "s•••@e•••.com")
        self.assertNotIn("someone", json.dumps(view))
        self.assertEqual(view[0]["state"], profiles.READY)

    def test_a_profile_of_another_user_is_damaged_never_read(self):
        store = self.store()
        profile_id = store.save(FIRST, "someone@example.com", "plus")
        (self.home / "accounts" / (profile_id + ".dat")).write_bytes(b"another user's blob")
        self.assertEqual(store.view()[0]["state"], profiles.DAMAGED)
        with self.assertRaises(profiles.ProfileError):
            store.get(profile_id)

    def test_delete_takes_the_file_away(self):
        store = self.store()
        one = store.save(FIRST, "one@example.com", "plus")
        store.save(SECOND, "two@example.com", "plus")
        self.assertTrue(store.delete(one))
        self.assertEqual(len(store.ids()), 1)
        store.begin("a" * 16, "b" * 16)
        store.mark_switched("two@example.com")
        self.assertEqual(store.delete_all(), 1)
        self.assertEqual(list((self.home / "accounts").iterdir()), [])

    def test_states_follow_the_times(self):
        now = [1_800_000_000]
        store = self.store(clock=lambda: now[0])
        profile_id = store.save(FIRST, "one@example.com", "plus")
        store.update(profile_id, exhausted_until=now[0] + 3600)
        self.assertEqual(store.view()[0]["state"], profiles.EXHAUSTED)
        now[0] += 3601
        self.assertEqual(store.view()[0]["state"], profiles.READY)
        store.update(profile_id, failed_at=now[0])
        self.assertEqual(store.view()[0]["state"], profiles.NEEDS_SIGN_IN)

    def test_switched_to_names_only_the_account_this_capability_put_in(self):
        now = [1_800_000_000]
        store = self.store(clock=lambda: now[0])
        store.mark_switched("Two@Example.com")
        self.assertTrue(store.switched_to("two@example.com", after=now[0] - 10))
        self.assertFalse(store.switched_to("one@example.com", after=now[0] - 10), "a person's change is not ours")
        self.assertFalse(store.switched_to("two@example.com", after=now[0] + 1), "older than the last reading")

    def test_at_most_eight(self):
        store = self.store()
        for index in range(profiles.MOST):
            store.save(FIRST, "p%d@example.com" % index, "plus")
        with self.assertRaises(profiles.ProfileError):
            store.save(FIRST, "ninth@example.com", "plus")


if __name__ == "__main__":
    unittest.main()
