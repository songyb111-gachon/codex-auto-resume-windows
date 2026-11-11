"""account_auto_switch after its security review (v0.6.22, plans/v0622-autoswitch-security-review.md): each finding's
reproduction, as a test that fails with its fix taken away.

The rule behind most of them: nothing writes Codex's sign-in file unless it knows what is there now; where it does not
know, it leaves the file, keeps what it can and says so once; a person's own sign-in is never overwritten. The Codex app,
its restart and every session are fakes; every home is a temporary folder and every sign-in file a fixture of no one's.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_autoswitch_swap import NOW, ONE, THREE, TWO, Fake, SwapCase, fixture  # noqa: E402
from codex_auto_resume_advanced.codex import authfile, swap  # noqa: E402


class RecoverKnowsWhatIsThere(SwapCase):
    """Finding 1 (R6): recover wrote the from-copy over auth.json without looking at what was there."""

    def setUp(self):
        super().setUp()
        self.two = self.store.save(TWO, "two@example.com", "plus")
        self.one = self.store.save(ONE, "one@example.com", "plus")
        patcher = patch.object(swap, "_app_running", lambda: False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def recover(self, fake):
        return swap.recover(None, self.store, self.codex, read_real=fake.read_real)

    def test_a_crash_before_the_swap_leaves_the_newest_tokens_in_place(self):
        """Fails with the check removed: the profile's older copy went over the tokens Codex refreshed since."""
        newest = fixture("one", n=9)
        (self.codex / "auth.json").write_bytes(newest)
        self.store.begin(self.one, self.two)                    # killed while the app was closing
        self.assertEqual(self.recover(Fake(self)), swap.LEFT)
        self.assertEqual((self.codex / "auth.json").read_bytes(), newest)
        self.assertIsNone(self.store.intent())

    def test_a_person_signed_in_since_is_never_overwritten(self):
        """Fails with the check removed: a third account a person signed in to went, unsaved, under the from-copy."""
        self.store.begin(self.one, self.two)
        (self.codex / "auth.json").write_bytes(THREE)            # the capability off meanwhile; a person signed in
        self.assertEqual(self.recover(Fake(self)), swap.LEFT)
        self.assertEqual((self.codex / "auth.json").read_bytes(), THREE)

    def test_the_target_put_in_and_not_signed_in_is_put_back(self):
        self.store.begin(self.one, self.two)
        authfile.replace(self.codex, TWO)
        self.assertEqual(self.recover(Fake(self, signs_in=False)), swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_nothing_is_written_under_a_running_app(self):
        self.store.begin(self.one, self.two)
        authfile.replace(self.codex, TWO)
        with patch.object(swap, "_app_running", lambda: True):
            self.assertEqual(self.recover(Fake(self, signs_in=False)), swap.NOT_PUT_BACK)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)
        self.assertIsNotNone(self.store.intent(), "kept for the next look")


class PutBackUntilItIsBack(SwapCase):
    """Finding 2 (R7): the target not signed in, then the second restart failed or the rename was refused - auth.json
    stayed the target's, the intent was cleared, and nothing ever put the good copy back."""

    def setUp(self):
        super().setUp()
        self.two = self.store.save(TWO, "two@example.com", "plus")
        patcher = patch.object(swap, "_app_running", lambda: True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def switch_with_second(self, second):
        fake = Fake(self)
        calls = []

        def restart(between):
            calls.append(1)
            if len(calls) == 1:
                between()
                return swap_restarts().RESTARTED, swap_restarts().CLOSED
            return second(between)
        reads = iter([fake.read_real(), {"present": False, "plan_word": None, "email": None, "kind": None}])
        return swap.switch(None, self.store, self.codex, self.two, restart=restart, read_real=lambda: next(reads), now=NOW)

    def refused(self, between):
        with patch.object(authfile.os, "replace", side_effect=PermissionError(13, "held")):
            try:
                between()
            except OSError:
                pass                                            # restart() swallows what `between` raises
        return swap_restarts().RESTARTED, swap_restarts().CLOSED

    def test_each_failed_put_back_keeps_the_intent_and_a_later_look_finishes_it(self):
        """Fails with the old ending: the intent went and the target's file stayed in Codex for good."""
        for second in (lambda between: (swap_restarts().NOT_ENDED, None),
                       lambda between: (swap_restarts().FAILED, None), self.refused):
            with self.subTest(second=second):
                authfile.replace(self.codex, ONE)
                self.store.end()
                self.assertEqual(self.switch_with_second(second), swap.NOT_PUT_BACK)
                self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)
                self.assertEqual(self.store.intent()["step"], "back")
                with patch.object(swap, "_app_running", lambda: False):
                    word = swap.recover(None, self.store, self.codex, read_real=Fake(self, signs_in=False).read_real)
                self.assertEqual(word, swap.NOT_SIGNED_IN)
                self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
                self.assertIsNone(self.store.intent())

    def test_a_later_look_restarts_at_most_a_few_times(self):
        self.assertEqual(self.switch_with_second(lambda between: (swap_restarts().NOT_ENDED, None)), swap.NOT_PUT_BACK)
        made = []

        def restart(between):
            made.append(1)
            return swap_restarts().NOT_ENDED, None
        for _ in range(swap.BACK_TRIES + 3):
            self.assertEqual(swap.recover(None, self.store, self.codex, read_real=Fake(self, signs_in=False).read_real,
                                          restart=restart), swap.NOT_PUT_BACK)
        self.assertEqual(len(made), swap.BACK_TRIES)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)

    def test_a_later_restart_puts_it_back(self):
        self.assertEqual(self.switch_with_second(lambda between: (swap_restarts().NOT_ENDED, None)), swap.NOT_PUT_BACK)
        fake = Fake(self, signs_in=False)
        self.assertEqual(swap.recover(None, self.store, self.codex, read_real=fake.read_real, restart=fake.restart),
                         swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)


class SavedSignInsCanAlwaysGo(SwapCase):
    """Finding 3 (R11, R12): saved sign-ins outlasted "removed" - no accounts folder in either purge, Delete refused while
    the capability was off or hidden, and the card gone."""

    ROOT = Path(__file__).resolve().parents[2]

    def paths(self):
        from codex_auto_resume import config
        return config.Paths(self.home)

    def test_the_purge_lists_every_saved_copy_and_scratch_home(self):
        """Fails with owned_account_files gone: uninstall --purge left live sign-ins behind."""
        self.store.save(TWO, "two@example.com", "plus")
        left = self.store.directory / "scratch-0123456789ab"
        left.mkdir()
        (left / "auth.json").write_bytes(TWO)                   # a scratch home a killed watcher left
        paths = self.paths()
        listed = {path.relative_to(self.home).as_posix() for path in paths.owned_account_files()}
        self.assertIn("accounts/scratch-0123456789ab/auth.json", listed)
        self.assertTrue(any(name.endswith(".dat") for name in listed))
        self.assertEqual(paths.owned_account_dirs()[-1], paths.accounts_dir)
        self.assertEqual(paths.owned_account_dirs()[0], left)
        source = (self.ROOT / "src" / "codex_auto_resume" / "commands" / "install.py").read_text(encoding="utf-8")
        self.assertIn("paths.owned_account_files()", source)
        self.assertIn("paths.owned_account_dirs()", source)

    def test_no_folder_or_one_not_ours_is_never_touched(self):
        paths = self.paths()
        self.assertEqual((paths.owned_account_files(), paths.owned_account_dirs()), ([], []))
        paths.accounts_dir.mkdir(parents=True)
        (paths.accounts_dir / "a person's file.txt").write_text("kept", encoding="utf-8")
        self.assertEqual(paths.owned_account_files(), [], "no marker: not ours")

    def test_a_junction_at_the_accounts_folder_is_not_followed(self):
        import _winapi
        outside = self.dir / "outside"
        self.store.save(TWO, "two@example.com", "plus")
        self.store.directory.rename(outside)
        _winapi.CreateJunction(str(outside), str(self.store.directory))
        self.assertEqual(self.paths().owned_account_files(), [])

    def test_the_installer_purge_takes_the_folder_never_through_a_link(self):
        source = (self.ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8")
        block = source[source.index("if ($Purge) {", source.index("$kept = Join-Path $OwnedHome 'uninstall'")):]
        block = block[:block.index("Write-Host ''")]
        self.assertIn("(Join-Path $OwnedHome 'accounts')", block)
        self.assertIn("$item.LinkType", block)

    def test_the_uninstall_question_says_so_where_copies_are_kept(self):
        import json
        source = (self.ROOT / "gui" / "InstallerWindow.cs").read_text(encoding="utf-8")
        at = source.index('"installer.uninstall.saved_accounts"')
        self.assertIn("if (flow.SavedAccountsThere)", source[at - 200:at])
        for name in ("SettingsRemove.cs",):
            self.assertIn("InstallerFlow.SavedAccountsAt(home)", (self.ROOT / "gui" / name).read_text(encoding="utf-8"))
        self.assertIn("InstallerFlow.SavedAccountsAt(home)",
                      (self.ROOT / "build" / "setup" / "SetupWindow.cs").read_text(encoding="utf-8"))
        catalogs = sorted((self.ROOT / "src" / "codex_auto_resume" / "locales").glob("*.json"))
        self.assertEqual(len(catalogs), 19)
        for catalog in catalogs:
            words = json.loads(catalog.read_text(encoding="utf-8"))
            self.assertIn("Codex", words["installer.uninstall.saved_accounts"], catalog.name)

    def test_the_card_stands_in_every_state_while_copies_are_kept(self):
        source = (self.ROOT / "advanced" / "gui" / "AdvancedAccounts.cs").read_text(encoding="utf-8")
        # v0.6.22 final (the owner, 2026-11-08): one store under both account capabilities' cards - either column shows it
        # while that capability stands, or with copies kept in every state.
        self.assertIn("return (id == AccountsId || id == AccountId) && (Standing(item) || AccountsKept());", source)
        page = (self.ROOT / "advanced" / "gui" / "AdvancedPage.cs").read_text(encoding="utf-8")
        self.assertIn("if (id == AccountsId || id == AccountId)", page)


class SavedSignInsThroughTheBridge(unittest.TestCase):
    """Finding 3: hidden in registry.WAITING (no runtime has it) or off, the card's read and Delete still answer."""

    def test_hidden_or_off_the_card_reads_and_deletes(self):
        import shutil
        import tempfile
        from types import SimpleNamespace
        from test_advanced_autoswitch_profiles import opened, sealed
        from codex_auto_resume_advanced import profiles
        from codex_auto_resume_advanced.control import autoswitch as card
        from codex_auto_resume_advanced.vocabulary import ArmingState
        root = Path(tempfile.mkdtemp(prefix="car-autoswitch-hidden-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        store = profiles.Profiles(root / "home", seal=sealed, open_=opened)
        for states, registry in (({}, {}), ({card.CAPABILITY: ArmingState.OFF}, {card.CAPABILITY: object()})):
            with self.subTest(states=states):
                store.save(TWO, "two@example.com", "plus")
                runtime = SimpleNamespace(paths=SimpleNamespace(home=root / "home"), states=lambda fresh=False: states,
                                          registry=registry, state=SimpleNamespace(stamped=lambda *_a: None))
                shown = card.view(runtime, store=store, codex_home=root)
                self.assertIsNone(shown["refusal"])
                self.assertEqual(len(shown["profiles"]), 1)
                self.assertEqual(shown["offered"], bool(registry))
                self.assertEqual(card.delete(runtime, {"all": True}, store=store)["deleted"], 1)
                self.assertEqual(store.ids(), [])


class NoPlainSignInLeftBehind(SwapCase):
    """Finding 4 (R1, R2, R3): a scratch home a kill or a held file left kept a plain sign-in file, so did a temporary
    beside auth.json killed at the rename; nothing swept them, and no access list was set."""

    def setUp(self):
        super().setUp()
        patcher = patch.object(authfile, "_PRIVATE", lambda directory: True)    # no real access list is changed
        patcher.start()
        self.addCleanup(patcher.stop)

    def left(self, age=authfile.SCRATCH_STALE + 5):
        import os
        import time
        self.store.save(TWO, "two@example.com", "plus")
        scratch = self.store.directory / "scratch-00112233aabb"
        (scratch / "sessions").mkdir(parents=True)
        (scratch / "auth.json").write_bytes(TWO)
        (scratch / "sessions" / "x.jsonl").write_text("{}", encoding="utf-8")
        beside = self.codex / "auth.json.car-0a1b2c3d"
        beside.write_bytes(TWO)
        then = time.time() - age
        for path in (scratch, beside):
            os.utime(path, (then, then))
        return scratch, beside

    def test_a_look_sweeps_what_a_kill_left(self):
        """Fails with the sweep removed: the plain copies stay until someone finds them."""
        scratch, beside = self.left()
        self.assertEqual(authfile.sweep(self.store.directory, self.codex), (2, 0))
        self.assertFalse(scratch.exists())
        self.assertFalse(beside.exists())
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertEqual(len(self.store.ids()), 1, "the sealed copies stay")

    def test_a_young_scratch_home_is_a_read_or_sign_in_under_way(self):
        scratch, beside = self.left(age=5)
        self.assertEqual(authfile.sweep(self.store.directory, self.codex), (0, 0))
        self.assertTrue(scratch.exists())
        self.assertEqual(self.store.delete_all(), 1)
        self.assertFalse(scratch.exists(), "Delete all takes every scratch home, whatever its age")

    def test_only_names_it_makes_and_never_through_a_link(self):
        import _winapi
        outside = self.dir / "outside"
        outside.mkdir()
        (outside / "auth.json").write_bytes(THREE)
        self.store.save(TWO, "two@example.com", "plus")
        _winapi.CreateJunction(str(outside), str(self.store.directory / "scratch-ffffffffffff"))
        (self.codex / "auth.json.bak").write_bytes(THREE)                       # a person's own copy
        (self.store.directory / "notes.txt").write_text("kept", encoding="utf-8")
        authfile.sweep(self.store.directory, self.codex, stale=0)
        self.assertEqual((outside / "auth.json").read_bytes(), THREE)
        self.assertTrue((self.codex / "auth.json.bak").exists())
        self.assertTrue((self.store.directory / "notes.txt").exists())

    def test_a_removal_that_failed_is_said(self):
        scratch, _beside = self.left()
        held = open(scratch / "auth.json", "rb")
        try:
            removed, failed = authfile.sweep(self.store.directory, self.codex)
        finally:
            held.close()
        self.assertEqual(failed, 1)
        engine = (Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume_advanced" / "engine"
                  / "autoswitch.py").read_text(encoding="utf-8")
        self.assertIn('self._count("sweep_failed")', engine)
        from codex_auto_resume_advanced.registry import ACCOUNT_AUTO_SWITCH
        self.assertIn("sweep_failed", ACCOUNT_AUTO_SWITCH.codes)

    def test_a_scratch_home_says_whether_it_went(self):
        scratch = authfile.Scratch(self.store.directory, TWO)
        with scratch as where:
            held = open(where / "auth.json", "rb")
        try:
            self.assertIs(scratch.removed, False)
        finally:
            held.close()
        self.assertTrue(authfile.remove_tree(where))
        with authfile.Scratch(self.store.directory, TWO) as where:
            pass
        self.assertFalse(where.exists())

    def test_the_folder_is_made_private_as_it_is_made(self):
        made = []
        with patch.object(authfile, "_PRIVATE", lambda directory: made.append(Path(directory)) or True):
            self.store.save(TWO, "two@example.com", "plus")
            self.store.save(THREE, "three@example.com", "plus")
        self.assertEqual(made, [self.store.directory], "once, as it is first made ours")


class PrivateAccessList(unittest.TestCase):
    """The access list itself, on a folder this test makes in its own temporary folder - never a real one."""

    def test_only_the_current_user_may_open_it(self):
        import shutil
        import tempfile
        from codex_auto_resume.win import acl
        root = Path(tempfile.mkdtemp(prefix="car-autoswitch-acl-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        folder = root / "accounts"
        folder.mkdir()
        if not authfile._private_dacl(folder):
            self.skipTest("this drive keeps no access list")
        (folder / "x.dat").write_bytes(b"x")
        self.assertEqual(acl.allowed_sids(folder), [acl._own_sid()])
        self.assertEqual(acl.allowed_sids(folder / "x.dat"), [acl._own_sid()])


class SaveBackKnowsWhoseFileItIs(SwapCase):
    """Finding 5 (R10): a person signed in to a third account while the app closed; the save-back sealed that sign-in
    under the first account's label, and the first account's own newest tokens were nowhere."""

    def test_another_account_signed_in_meanwhile_stops_the_switch(self):
        """Fails with the identity check removed: the first account's profile held the third account's sign-in."""
        two = self.store.save(TWO, "two@example.com", "plus")
        one = self.store.save(ONE, "one@example.com", "plus")
        fake = Fake(self)
        plain = fake.restart

        def restart(between):
            (self.codex / "auth.json").write_bytes(THREE)       # a person signed in as someone else
            return plain(between)
        fake.restart = restart
        self.assertEqual(self.switch(fake, two), swap.CHANGED)
        self.assertEqual((self.codex / "auth.json").read_bytes(), THREE, "the person's own sign-in stays")
        self.assertEqual(self.store.get(one)["auth"], ONE, "nothing sealed under another's label")
        self.assertIsNone(self.store.intent())

    def test_the_same_account_refreshed_is_saved_back(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        one = self.store.save(ONE, "one@example.com", "plus")
        fake = Fake(self)
        plain = fake.restart

        def restart(between):
            (self.codex / "auth.json").write_bytes(fixture("one", n=4))
            return plain(between)
        fake.restart = restart
        self.assertEqual(self.switch(fake, two), swap.SWITCHED)
        self.assertEqual(self.store.get(one)["auth"], fixture("one", n=4))


class RefreshedCopyKeptWhenTheReadBreaks(SwapCase):
    """Finding 6 (R9): Codex refreshed the tokens on the scratch home, then the usage read raised, and the newer copy was
    dropped with the scratch home - the profile kept a spent one."""

    def test_the_refreshed_copy_is_sealed_before_returning(self):
        """Fails with the except branch returning at once: the profile still held the copy Codex had replaced."""
        two = self.store.save(TWO, "two@example.com", "plus")
        rotated = fixture("two", n=5)

        def session_for(home):
            class Breaks:
                def __enter__(inner):
                    return inner

                def __exit__(inner, *_exc):
                    return False

                def call(inner, method, _params):
                    if method == swap.ACCOUNT_READ:
                        (Path(home) / "auth.json").write_bytes(rotated)
                        return {"account": {"type": "chatgpt", "email": "two@example.com", "planType": "plus"}}
                    raise RuntimeError("the network dropped")
            return Breaks()
        found = swap.read_profile(None, self.store, two, session_for=session_for, now=NOW)
        self.assertIsNone(found["present"])
        self.assertEqual(self.store.get(two)["auth"], rotated)


class OneHandOnTheSavedAccounts(SwapCase):
    """Finding 7 (R16): the intent had no owner and no lock - another process's look (MSWAP's hand beside an armed
    watcher) settled a switch still under way, writing the old copy back, and a save beside it raced. A second thread
    stands for that other process here: a Windows mutex belongs to a thread."""

    def other(self, job):
        import threading
        found = []
        worker = threading.Thread(target=lambda: found.append(job()))
        worker.start()
        worker.join(30)
        return found[0]

    def test_a_look_elsewhere_does_not_settle_a_switch_under_way(self):
        """Fails with the lock removed: the other look put the first account's old copy back mid-switch."""
        two = self.store.save(TWO, "two@example.com", "plus")
        one = self.store.save(fixture("one", n=0), "one@example.com", "plus")      # an old copy
        fake = Fake(self)
        plain = fake.restart
        seen = {}

        def restart(between):
            with patch.object(swap, "_app_running", lambda: False):
                seen["recover"] = self.other(lambda: swap.recover(None, self.store, self.codex, read_real=fake.read_real))
                seen["switch"] = self.other(lambda: swap.switch(None, self.store, self.codex, two, restart=plain,
                                                                read_real=fake.read_real, now=NOW))
                seen["delete"] = self.other(lambda: self.store_locked_delete(one))
            return plain(between)
        fake.restart = restart
        self.assertEqual(self.switch(fake, two), swap.SWITCHED)
        self.assertEqual(seen, {"recover": swap.LOCKED, "switch": swap.LOCKED, "delete": "locked"})
        self.assertEqual(self.store.get(one)["auth"], ONE, "the newest copy was saved back, not undone")

    def store_locked_delete(self, profile_id):
        from codex_auto_resume_advanced.profiles import Locked
        try:
            with self.store.locked(0.2):
                return self.store.delete(profile_id)
        except Locked:
            return "locked"

    def test_every_write_path_takes_the_lock(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume_advanced" / "codex"
                  / "swap.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("with store.locked("), 6)
        control = (Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume_advanced" / "control"
                   / "autoswitch.py").read_text(encoding="utf-8")
        self.assertIn("with store.locked():", control)


class AnAppThatDidNotComeBack(SwapCase):
    """Finding 8 (R8): the restart's NOT_STARTED still came back as switched - the app stayed closed, the waiting
    recoveries were released early into it, and nobody was told."""

    def test_not_started_is_its_own_outcome(self):
        """Fails with the old ending: the file read said the target, so it answered SWITCHED."""
        two = self.store.save(TWO, "two@example.com", "plus")
        fake = Fake(self)

        def restart(between):
            between()
            return swap_restarts().NOT_STARTED, swap_restarts().CLOSED
        fake.restart = restart
        self.assertEqual(self.switch(fake, two), swap.NOT_STARTED)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO, "the target stays in: the next start reads it")
        self.assertTrue(self.store.switched_to("two@example.com", after=NOW), "a change of ours, not a person's")

    def test_the_watcher_releases_nothing_early_for_it(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume_advanced" / "engine"
                  / "autoswitch.py").read_text(encoding="utf-8")
        # v0.6.22 final: the look switches through put_in, which a person's Switch to this account calls too.
        at = source.index("outcome, closed = self.put_in(target, now)")
        after = source[at:at + 600]
        self.assertIn("if outcome == swap.SWITCHED:\n            self._switched(now)", after)
        self.assertNotIn("swap.NOT_STARTED):\n            self._switched", after)


class SaysSoOnce(unittest.TestCase):
    """Finding 9: a failed switch or a settled crash was only counted - the design's "says so once" was not built."""

    def test_a_switch_that_did_not_finish_asks_for_one_notice(self):
        """Fails with the notice removed: notice() stayed None after a failed switch."""
        from types import SimpleNamespace
        from codex_auto_resume_advanced.engine import autoswitch
        code = autoswitch.AutoSwitch(SimpleNamespace(home=Path(".")))
        code._scoped = SimpleNamespace(count=lambda word: True)
        for word in autoswitch.NOT_FINISHED:
            self.assertIn(word, swap.OUTCOMES)
        code._not_finished("0123456789abcdef")
        self.assertEqual(code.notice(), {"key": "autoswitch:not_finished:0123456789abcdef", "why": "not_finished"})

    def test_the_watcher_shows_the_words_of_a_switch_that_did_not_finish(self):
        from codex_auto_resume import l10n, notifier
        said = notifier._account_changed_content(None, "accounts_exhausted", "not_finished")
        self.assertIn(l10n.message("toast_switch_not_finished"), json_of(said))
        plain = notifier._account_changed_content(None, "accounts_exhausted")
        self.assertIn(l10n.message("toast_accounts_exhausted"), json_of(plain))
        notices = (Path(__file__).resolve().parents[2] / "src" / "codex_auto_resume" / "runtime"
                   / "plugnotices.py").read_text(encoding="utf-8")
        self.assertIn('self._watcher_notice("accounts_exhausted", {"why": notice.get("why")})', notices)


def json_of(content):
    import json
    return json.dumps(content, ensure_ascii=False, default=str)


class NoSwapBesideAnotherEngine(SwapCase):
    """Finding 10: the restart waited for the app's main only; a TUI, IDE or exec-server codex.exe left running could
    write its old account's tokens after the swap. Nothing is ended: the switch waits."""

    TUI = {"pid": 4242, "parent": 1, "path": "C:\\Tools\\codex.exe"}

    def test_an_engine_left_running_holds_the_swap(self):
        """Fails with the check removed: the target's copy went in beside an engine of the old account."""
        two = self.store.save(TWO, "two@example.com", "plus")
        with patch.object(swap, "_inventory", lambda: [self.TUI]):
            self.assertEqual(self.switch(Fake(self), two), swap.ENGINE_ALIVE)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertIsNone(self.store.intent())

    def test_what_cannot_be_told_waits_too(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        with patch.object(swap, "_inventory", lambda: None):
            self.assertEqual(self.switch(Fake(self), two), swap.ENGINE_ALIVE)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_the_app_s_own_children_and_our_own_servers_do_not_count(self):
        from codex_auto_resume.codex import pairing
        main = {"pid": 10, "parent": 1, "path": "x"}
        child = {"pid": 11, "parent": 10, "path": "C:\\x\\codex.exe"}
        with patch.object(pairing, "_app_main", lambda rows: main):
            self.assertFalse(swap.other_engines([main, child], app_open=True))
            self.assertTrue(swap.other_engines([main, child], app_open=False), "once the app is gone, it is not its")
        with patch.object(pairing, "_OWN", {(4242, 1.0)}):
            self.assertFalse(swap.other_engines([self.TUI], app_open=False))

    def test_mswap_records_it(self):
        from codex_auto_resume_advanced import measure
        self.assertIn("other_engine_alive", measure._MSWAP_FIELDS)


class AccountsFolderStaysWhereItIs(SwapCase):
    """Finding 12 (R4): a junction at the accounts folder sent the sealed profiles and the plain scratch homes outside."""

    def setUp(self):
        super().setUp()
        import _winapi
        self.outside = self.dir / "outside"
        self.outside.mkdir()
        self.home.mkdir(parents=True, exist_ok=True)
        _winapi.CreateJunction(str(self.outside), str(self.store.directory))

    def test_nothing_is_written_read_or_made_through_it(self):
        """Fails with the check removed: the profile and the scratch home landed in the junction's target."""
        with self.assertRaises(OSError):
            self.store.save(TWO, "two@example.com", "plus")
        with self.assertRaises(OSError):
            with authfile.Scratch(self.store.directory, TWO):
                pass
        self.assertEqual(list(self.outside.iterdir()), [])
        (self.outside / "0123456789abcdef.dat").write_bytes(b"planted")
        self.assertEqual(self.store.ids(), [])
        self.assertFalse(self.store.delete("0123456789abcdef"))
        self.assertTrue((self.outside / "0123456789abcdef.dat").exists())


class SealWhatIsThereAfterTheRead(SwapCase):
    """Finding 14: the save-back read the file, then read the account on a session of the real home - which can refresh
    the tokens and write the file - and sealed the copy read before it; the newer tokens went under the rename."""

    def test_the_tokens_the_identity_read_refreshed_are_the_ones_sealed(self):
        """Fails with the second read removed: the profile kept n=4, which that session had already replaced."""
        two = self.store.save(TWO, "two@example.com", "plus")
        one = self.store.save(ONE, "one@example.com", "plus")
        fake = Fake(self)
        plain_read, plain_restart = fake.read_real, fake.restart
        calls = []

        def read_real():
            calls.append(1)
            if len(calls) == 2:                                 # the identity read inside the save-back
                (self.codex / "auth.json").write_bytes(fixture("one", n=9))
            return plain_read()

        def restart(between):
            (self.codex / "auth.json").write_bytes(fixture("one", n=4))   # the app refreshed before it closed
            return plain_restart(between)
        fake.read_real, fake.restart = read_real, restart
        self.assertEqual(self.switch(fake, two), swap.SWITCHED)
        self.assertEqual(self.store.get(one)["auth"], fixture("one", n=9))


class KeepWaitsOutASwitch(SwapCase):
    """Finding 15: keeping a copy Codex refreshed on a scratch home waited five seconds for the lock, which a switch holds
    through a whole app restart - so a read beside one dropped the newer copy."""

    def store_held_for(self, seconds_held):
        from codex_auto_resume_advanced import profiles
        from test_advanced_autoswitch_profiles import opened, sealed

        class Held:
            def __init__(self, seconds):
                self.seconds = seconds

            def __enter__(self):
                if self.seconds < seconds_held:
                    raise OSError("mutex_busy")
                return self

            def __exit__(self, *_exc):
                return False
        return profiles.Profiles(self.home, seal=sealed, open_=opened, clock=lambda: NOW,
                                 lock=lambda directory, seconds: Held(seconds))

    def test_both_keeps_wait_as_long_as_the_mutex_allows(self):
        """Fails with LOCK_SECONDS kept: a switch holding the lock 30 s cost both refreshed copies."""
        from codex_auto_resume_advanced import profiles
        self.assertEqual(profiles.KEEP_SECONDS, 60.0)
        store = self.store_held_for(30)
        two = store.save(TWO, "two@example.com", "plus")
        refreshed = fixture("two", n=6)
        swap.read_profile(None, store, two, session_for=Fake(self, refresh=refreshed).session_for, now=NOW)
        self.assertEqual(store.get(two)["auth"], refreshed, "the read that answered kept the newer copy")
        rotated = fixture("two", n=7)

        def session_for(home):
            class Breaks:
                def __enter__(inner):
                    return inner

                def __exit__(inner, *_exc):
                    return False

                def call(inner, method, _params):
                    (Path(home) / "auth.json").write_bytes(rotated)
                    raise RuntimeError("the network dropped")
            return Breaks()
        swap.read_profile(None, store, two, session_for=session_for, now=NOW)
        self.assertEqual(store.get(two)["auth"], rotated, "the read that broke kept the newer copy too")


class TheCardOffTouchesNothingOfCodex(unittest.TestCase):
    """Finding 16: Delete all never swept beside the real sign-in file; the card's read looked at Codex's home in every
    state; and a kill's leftovers stayed in plain text while the capability was off, since only a look swept."""

    def setUp(self):
        import shutil
        import tempfile
        from types import SimpleNamespace
        from test_advanced_autoswitch_profiles import opened, sealed
        from codex_auto_resume_advanced import profiles
        from codex_auto_resume_advanced.control import autoswitch as card
        from codex_auto_resume_advanced.vocabulary import ArmingState
        self.card = card
        self.root = Path(tempfile.mkdtemp(prefix="car-autoswitch-card-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.codex = self.root / "codex"
        self.codex.mkdir()
        self.store = profiles.Profiles(self.root / "home", seal=sealed, open_=opened)
        self.state = {card.CAPABILITY: ArmingState.OFF}
        self.runtime = SimpleNamespace(paths=SimpleNamespace(home=self.root / "home"),
                                       states=lambda fresh=False: self.state, registry={card.CAPABILITY: object()},
                                       state=SimpleNamespace(stamped=lambda *_a: None))
        patcher = patch.object(authfile, "_PRIVATE", lambda directory: True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def old(self, path):
        import os
        import time
        then = time.time() - authfile.SCRATCH_STALE - 5
        os.utime(path, (then, then))
        return path

    def test_delete_all_sweeps_beside_the_sign_in_file(self):
        """Fails with delete_all() given no home: the plain temporary beside auth.json stayed."""
        self.store.save(TWO, "two@example.com", "plus")
        beside = self.codex / "auth.json.car-0a1b2c3d"
        beside.write_bytes(TWO)
        self.old(beside)
        with patch.object(self.card, "_codex_home", lambda runtime: self.codex):
            self.assertEqual(self.card.delete(self.runtime, {"all": True}, store=self.store)["deleted"], 1)
        self.assertFalse(beside.exists())

    def test_a_home_that_cannot_be_told_stops_no_delete(self):
        self.store.save(TWO, "two@example.com", "plus")

        def broken(runtime):
            raise OSError("no Codex home")
        with patch.object(self.card, "_codex_home", broken):
            self.assertEqual(self.card.delete(self.runtime, {"all": True}, store=self.store)["deleted"], 1)

    def test_off_the_card_reads_nothing_of_codex_and_sweeps_its_own_folder(self):
        """Fails with the old view: it asked Codex's home whether its sign-in is a file while the feature was off."""
        self.store.save(TWO, "two@example.com", "plus")
        left = self.store.directory / "scratch-00112233aabb"
        left.mkdir()
        (left / "auth.json").write_bytes(TWO)
        self.old(left)

        def touched(runtime):
            raise AssertionError("Codex's home was looked at while the feature is off")
        with patch.object(self.card, "_codex_home", touched):
            shown = self.card.view(self.runtime, store=self.store)
        self.assertIsNone(shown["store"])
        self.assertFalse(left.exists(), "the kill's leftover is swept while off")
        self.assertEqual(len(shown["profiles"]), 1)

    def test_a_held_lock_changes_nothing_in_the_answer(self):
        import threading
        self.store.save(TWO, "two@example.com", "plus")
        left = self.store.directory / "scratch-00112233aabb"
        left.mkdir()
        self.old(left)
        held, release = threading.Event(), threading.Event()

        def holder():
            with self.store.locked(0):
                held.set()
                release.wait(10)
        worker = threading.Thread(target=holder)
        worker.start()
        held.wait(10)
        try:
            shown = self.card.view(self.runtime, store=self.store)
        finally:
            release.set()
            worker.join(10)
        self.assertIsNone(shown["refusal"])
        self.assertTrue(left.exists(), "never swept beside a switch")

    def test_the_card_off_with_no_store_word_still_offers_delete(self):
        source = (Path(__file__).resolve().parents[1] / "gui" / "AdvancedAccounts.cs").read_text(encoding="utf-8")
        start = source.index("private void BuildAccounts(")
        depth, at = 0, source.index("{", start)
        for end in range(at, len(source)):
            depth += {"{": 1, "}": -1}.get(source[end], 0)
            if depth == 0:
                break
        body = source[at:end]
        # The line about Codex's sign-in only while it stands (since the v0.6.22 final it names the real reason, R4).
        self.assertIn('string why = standing ? AccountsStoreLine(Str(advancedAccounts, "store")) : null;', body)
        # The last standing block holds Add and Save; the first, since the final, holds Read usage at the heading.
        block_at = body.rindex("if (standing)" + chr(10))
        depth, open_at = 0, body.index("{", block_at)
        for close in range(open_at, len(body)):
            depth += {"{": 1, "}": -1}.get(body[close], 0)
            if depth == 0:
                break
        add_and_save = body[open_at:close]
        self.assertIn("accountsAdd = CardButton(", add_and_save)
        for button in ("accountsDelete = CardButton(", "accountsDeleteAll = CardButton("):
            self.assertIn(button, body)
            self.assertNotIn(button, add_and_save, "Delete and Delete all stand in every state")


class TheAppsOwnEnginesAreTheApps(SwapCase):
    """Finding 17: with the app open only its main's direct children were excused, so an exec-server under the app server
    read as another engine for ever; and once the main was gone its children, ending a moment later, gave ENGINE_ALIVE -
    the app closed and started for nothing."""

    MAIN = {"pid": 10, "parent": 1, "path": "C:\\WindowsApps\\ChatGPT.exe"}
    SERVER = {"pid": 11, "parent": 10, "path": "C:\\app\\codex.exe"}
    EXEC = {"pid": 12, "parent": 11, "path": "C:\\app\\codex.exe"}

    def test_every_descendant_of_the_app_is_the_app_s(self):
        """Fails with the old rule: the exec-server under the app server counted as another engine."""
        from codex_auto_resume.codex import pairing
        with patch.object(pairing, "_app_main", lambda rows: self.MAIN):
            self.assertFalse(swap.other_engines([self.MAIN, self.SERVER, self.EXEC], app_open=True))
            stray = {"pid": 40, "parent": 39, "path": "C:\\x\\codex.exe"}
            self.assertTrue(swap.other_engines([self.MAIN, self.SERVER, stray], app_open=True))
            loop = [{"pid": 50, "parent": 51, "path": "C:\\x\\codex.exe"},
                    {"pid": 51, "parent": 50, "path": "C:\\x\\codex.exe"}]
            self.assertTrue(swap.other_engines([self.MAIN] + loop, app_open=True), "a loop is not the app's")

    def test_children_ending_after_the_main_get_their_time(self):
        """Fails with the single look: the server still listed a moment after the main went gave ENGINE_ALIVE."""
        two = self.store.save(TWO, "two@example.com", "plus")
        looks = []

        def inventory():
            looks.append(self.clock[0])
            return [self.SERVER, self.EXEC] if self.clock[0] < 2.0 else []
        with patch.object(swap, "_inventory", inventory):
            self.assertEqual(self.switch(Fake(self), two), swap.SWITCHED)
        self.assertGreater(len(looks), 1)
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO)

    def test_an_engine_that_stays_is_engine_alive_once_the_time_is_up(self):
        two = self.store.save(TWO, "two@example.com", "plus")
        with patch.object(swap, "_inventory", lambda: None):
            self.assertEqual(self.switch(Fake(self), two), swap.ENGINE_ALIVE)
        self.assertGreaterEqual(self.clock[0], swap.ENGINES_SETTLE)
        self.assertLess(self.clock[0], swap.ENGINES_SETTLE + 1)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)


class AStoppedSwitchSaysSo(unittest.TestCase):
    """Finding 18: a switch that closed and reopened the app and then did nothing, because another engine still ran,
    said nothing."""

    def test_engine_alive_from_a_switch_asks_for_the_notice(self):
        """Fails with engine_alive left out of NOT_FINISHED: notice() stayed None."""
        from types import SimpleNamespace
        from codex_auto_resume_advanced.engine import autoswitch
        code = autoswitch.AutoSwitch(SimpleNamespace(home=Path(".")), store=SimpleNamespace(
            directory=Path("does-not-exist"), intent=lambda: None), home=Path("does-not-exist"))
        code._scoped = SimpleNamespace(count=lambda word: True, stamped=lambda key: None, stamp=lambda *a: None)
        rows = [{"interruption_id": 1, "detected_at": 0}]
        with patch.object(autoswitch.AutoSwitch, "waiting", lambda self, view, now: rows), \
                patch.object(autoswitch.AutoSwitch, "_why_not", lambda self, view, found: None), \
                patch.object(autoswitch.AutoSwitch, "choose", lambda self, store, now: "0123456789abcdef"), \
                patch.object(swap, "recover", lambda *a, **k: None), \
                patch.object(swap, "switch", lambda *a, **k: swap.ENGINE_ALIVE):
            code.look(None, 1000)
        self.assertEqual(code.notice(), {"key": "autoswitch:not_finished:0123456789abcdef", "why": "not_finished"})

    def test_the_look_s_own_engine_alive_stays_silent(self):
        from types import SimpleNamespace
        from codex_auto_resume_advanced.engine import autoswitch
        code = autoswitch.AutoSwitch(SimpleNamespace(home=Path(".")), store=SimpleNamespace(
            directory=Path("does-not-exist"), intent=lambda: None), home=Path("does-not-exist"))
        code._scoped = SimpleNamespace(count=lambda word: True, stamped=lambda key: None, stamp=lambda *a: None)
        with patch.object(autoswitch.AutoSwitch, "waiting", lambda self, view, now: [{"interruption_id": 1, "detected_at": 0}]), \
                patch.object(autoswitch.AutoSwitch, "_why_not", lambda self, view, found: "engine_alive"), \
                patch.object(swap, "recover", lambda *a, **k: None):
            code.look(None, 1000)
        self.assertIsNone(code.notice())


class LookAgainBeforeTheClose(unittest.TestCase):
    """v0.6.23 audit A-R1: busy and idle were checked before reading every saved account - which can take minutes - and
    the app was then closed without looking again."""

    def test_a_person_back_while_the_accounts_were_read_closes_nothing(self):
        """Fails with the switch given the plain restart: the app was closed under the person's hands."""
        import test_advanced_autoswitch as engine_tests
        case = engine_tests.EngineCase("run")
        case.setUp()
        try:
            looks = []

            def busy():
                looks.append(1)
                return () if len(looks) == 1 else ("turn_running",)   # a turn started while the accounts were read
            case.code._busy = busy
            case.look()
            self.assertEqual(case.fake.restarts, 0)
            self.assertEqual(case.scoped.counted, [swap.HELD])
            self.assertEqual((case.codex / "auth.json").read_bytes(), ONE)
        finally:
            case.doCleanups()


class TheCeilingIsARolling24Hours(unittest.TestCase):
    """v0.6.23 audit A-R2: "at most ten a day" was counted by UTC calendar day, so twenty could happen within minutes
    around midnight UTC."""

    def test_ten_before_midnight_utc_hold_the_ceiling_after_it(self):
        """Fails with the calendar-day count: the eleventh switch went through one second after UTC midnight."""
        import test_advanced_autoswitch as engine_tests
        from codex_auto_resume_advanced.engine import autoswitch
        case = engine_tests.EngineCase("run")
        case.setUp()
        try:
            midnight = (engine_tests.NOW // autoswitch.DAY + 1) * autoswitch.DAY
            case.store.note_attempts([midnight - 600 + index for index in range(autoswitch.PER_DAY)])
            case.scoped.clock = midnight + 1
            case.look([engine_tests.waiting("c", detected=case.scoped.clock - autoswitch.SETTLE)])
            self.assertEqual(case.scoped.counted, ["ceiling"])
            self.assertEqual((case.codex / "auth.json").read_bytes(), ONE)
            case.scoped.clock = midnight - 600 + autoswitch.DAY
            case.look([engine_tests.waiting("d", detected=case.scoped.clock - autoswitch.SETTLE)])
            self.assertEqual(case.scoped.counted, ["ceiling", "switched"], "the first of the ten is 24 hours old")
        finally:
            case.doCleanups()


class EveryCloseCounts(unittest.TestCase):
    """v0.6.23 audit A-M2: an attempt that closed and restarted Codex without switching did not count toward the ten."""

    def test_a_switch_put_back_still_counts(self):
        """Fails with only SWITCHED and NOT_STARTED counted: two restarts, and the ceiling saw none."""
        import test_advanced_autoswitch as engine_tests
        case = engine_tests.EngineCase("run")
        case.setUp()
        try:
            case.code._read_real = lambda: {"present": True, "plan_word": "plus", "email": "one@example.com"}
            case.look()
            self.assertEqual(case.scoped.counted, ["not_signed_in"])
            self.assertEqual(case.fake.restarts, 2)
            self.assertEqual(case.store.attempts(), [case.scoped.clock], "one attempt, counted once")
        finally:
            case.doCleanups()

    def test_nothing_closed_counts_nothing(self):
        import test_advanced_autoswitch as engine_tests
        case = engine_tests.EngineCase("run")
        case.setUp()
        try:
            looks = []
            case.code._busy = lambda: (looks.append(1), () if len(looks) == 1 else ("queued",))[1]
            case.look()
            self.assertEqual(case.scoped.counted, [swap.HELD])
            self.assertIsNone(case.store.attempts())
        finally:
            case.doCleanups()


class APutBackIsFinishedWhileOff(unittest.TestCase):
    """v0.6.23 audit A-M3: a switch left NOT_PUT_BACK was never finished once the capability was turned off - only the
    armed look called recover."""

    def test_off_the_put_back_is_still_finished_and_nothing_new_is_switched(self):
        """Fails with no tend: nothing settled the intent while off, and Codex stayed on the dead copy."""
        import test_advanced_autoswitch as engine_tests
        case = engine_tests.EngineCase("run")
        case.setUp()
        try:
            case.code._read_real = lambda: {"present": False, "plan_word": None, "email": None}
            one = case.store.save(ONE, "one@example.com", "plus")
            case.store.begin(one, case.two, step="back")
            authfile.replace(case.codex, TWO)                    # the target's dead copy left in
            errand = case.code.tend(None)
            self.assertIsNotNone(getattr(errand, "run", None))
            with patch.object(swap, "_app_running", lambda: True):
                errand.run(None)
            self.assertEqual((case.codex / "auth.json").read_bytes(), ONE)
            self.assertIsNone(case.store.intent())
            self.assertEqual(case.fake.restarts, 1, "the put-back's restart, and no switch")
        finally:
            case.doCleanups()

    def test_nothing_under_way_is_nothing_to_tend(self):
        import test_advanced_autoswitch as engine_tests
        from codex_auto_resume.domain.plug import DEFER
        case = engine_tests.EngineCase("run")
        case.setUp()
        try:
            self.assertIs(case.code.tend(None), DEFER)
        finally:
            case.doCleanups()
        source = (Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume_advanced" / "runtime.py").read_text(
            encoding="utf-8")
        self.assertIn('TENDED = HEADLESS_CAPABILITIES + ("account_auto_switch",)', source)
        self.assertIn("definition.id in TENDED", source)


import test_advanced_usage as _usage  # noqa: E402


class ThePauseLetsGoAtASwitch(_usage.UsageCase):
    """v0.6.23 audit A-R4: usage_pause kept holding every recovery on the OLD account's window after an automatic switch,
    until the meter read again - past the switch's fifteen-minute early window."""

    CORE = {"interruption_id": _usage.ac.KEY, "thread_id": _usage.ac.THREAD}

    def test_a_window_read_before_the_switch_holds_nothing(self):
        """Fails with the mark kept: the gate still said HOLD on the new account."""
        from codex_auto_resume.domain.plug import DEFER, Alternative, Point
        from codex_auto_resume_advanced import profiles
        self.on("usage_pause")
        self.answer = _usage.reply(five=98)
        self.look()
        self.look()
        self.assertIs(self.rt.ask(Point.GATES, "usage", self.CORE, {}), Alternative.HOLD)
        read_at = self.rt.state.meter()[("codex", 300)]["read_at"]
        with patch.object(authfile, "_PRIVATE", lambda directory: True):
            profiles.Profiles(self.rt.paths.home, clock=lambda: int(read_at) + 5).mark_switched("two@example.com")
        self.assertIs(self.rt.ask(Point.GATES, "usage", self.CORE, {}), DEFER)


class TheStatementNamesTheEarlyLooksBound(unittest.TestCase):
    """v0.6.23 audit A-M7: the statement said the waiting recoveries are looked at at once, but the capability's own
    ceilings bound those early looks, and the statement did not say so."""

    def test_every_catalog_names_the_bound_the_registry_keeps(self):
        """Fails with the old statement: no catalog named the bound."""
        import json
        from codex_auto_resume_advanced.registry import ACCOUNT_AUTO_SWITCH
        day, conversation = ACCOUNT_AUTO_SWITCH.ceilings.per_day, ACCOUNT_AUTO_SWITCH.ceilings.per_conversation
        catalogs = sorted((Path(__file__).resolve().parents[1] / "src" / "codex_auto_resume_advanced" / "locales")
                          .glob("*.json"))
        self.assertEqual(len(catalogs), 19)
        english = json.loads(catalogs[[c.stem for c in catalogs].index("en")].read_text(encoding="utf-8"))
        self.assertIn("at most %d a day and %d for any one conversation" % (day, conversation),
                      english["statement.account_auto_switch.does"])
        for catalog in catalogs:
            said = json.loads(catalog.read_text(encoding="utf-8"))["statement.account_auto_switch.does"]
            self.assertIn(str(day), said[-160:], catalog.name)
            self.assertIn(str(conversation), said[-160:], catalog.name)


class APutBackOutlivesADelete(SwapCase):
    """v0.6.23 audit A-R5: deleting the account a failed switch set aside - the obvious thing, it shows "needs a new
    sign-in" - cancelled the pending put-back: recover could not get it, answered FAILED and cleared the intent."""

    def setUp(self):
        super().setUp()
        self.two = self.store.save(TWO, "two@example.com", "plus")
        patcher = patch.object(swap, "_app_running", lambda: True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def not_put_back(self):
        fake = Fake(self)
        calls = []

        def restart(between):
            calls.append(1)
            if len(calls) == 1:
                between()
                return swap_restarts().RESTARTED, swap_restarts().CLOSED
            return swap_restarts().NOT_ENDED, None
        reads = iter([fake.read_real(), {"present": False, "plan_word": None, "email": None, "kind": None}])
        self.assertEqual(swap.switch(None, self.store, self.codex, self.two, restart=restart,
                                     read_real=lambda: next(reads), now=NOW), swap.NOT_PUT_BACK)

    def test_deleting_the_account_set_aside_keeps_the_put_back(self):
        """Fails with recover leaning on the deleted profile: FAILED, the intent gone, Codex left on the dead copy."""
        self.not_put_back()
        self.assertTrue(self.store.delete(self.two))
        with patch.object(swap, "_app_running", lambda: False):
            word = swap.recover(None, self.store, self.codex, read_real=Fake(self, signs_in=False).read_real)
        self.assertEqual(word, swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)
        self.assertIsNone(self.store.intent())

    def test_deleting_the_previous_account_keeps_it_too(self):
        self.not_put_back()
        self.assertTrue(self.store.delete(self.store.find("one@example.com")))
        with patch.object(swap, "_app_running", lambda: False):
            word = swap.recover(None, self.store, self.codex, read_real=Fake(self, signs_in=False).read_real)
        self.assertEqual(word, swap.NOT_SIGNED_IN)
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)

    def test_a_file_not_put_in_is_still_left_alone(self):
        self.not_put_back()
        self.store.delete(self.two)
        (self.codex / "auth.json").write_bytes(THREE)            # a person signed in meanwhile
        with patch.object(swap, "_app_running", lambda: False):
            word = swap.recover(None, self.store, self.codex, read_real=Fake(self, signs_in=False).read_real)
        self.assertEqual(word, swap.LEFT)
        self.assertEqual((self.codex / "auth.json").read_bytes(), THREE)


class TheStopTextNamesItsOneException(unittest.TestCase):
    """After A-M3 a switch that did not finish is still undone once the capability is off; the stop text said
    "nothing is switched from then on" and named no exception."""

    def test_every_catalog_and_both_documents_name_it_and_the_revision_moved(self):
        """Fails with the old words: no catalog's stop text, and no document, named the exception."""
        import json
        from codex_auto_resume_advanced.registry import ACCOUNT_AUTO_SWITCH
        self.assertEqual(ACCOUNT_AUTO_SWITCH.revision, 2, "a person who turned it on reads the statement again")
        root = Path(__file__).resolve().parents[2]
        catalogs = sorted((root / "advanced" / "src" / "codex_auto_resume_advanced" / "locales").glob("*.json"))
        self.assertEqual(len(catalogs), 19)
        stops = {c.stem: json.loads(c.read_text(encoding="utf-8"))["statement.account_auto_switch.stop"] for c in catalogs}
        self.assertIn("a switch that did not finish is still undone", stops["en"])
        self.assertIn("끝나지 않은 전환", stops["ko"])
        self.assertEqual(len(set(stops.values())), 19)
        for name in ("SECURITY.md", "PRIVACY.md"):
            self.assertIn("a switch that did\nnot finish is still undone" if name == "SECURITY.md"
                          else "a switch that did not finish is\n  still undone",
                          (root / "docs" / name).read_text(encoding="utf-8"), name)
        import languages
        for name in ("SECURITY.ko.md", "PRIVACY.ko.md") if languages.both_languages() else ():
            self.assertIn("끝나지 않은 전환은 여전히", (root / "docs" / name).read_text(encoding="utf-8"), name)


def swap_restarts():
    from codex_auto_resume_advanced.codex import restart
    return restart


if __name__ == "__main__":
    unittest.main()
