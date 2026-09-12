r"""Properties the product claims about itself that nothing was executing.

Each of these was a row in `docs/FEATURE_MATRIX.md` whose evidence was "the code exists and
somebody read it". A claim in a README backed by a reading is a claim that stops being true
the first time a file is edited by someone who never read that README, which is the failure
mode the matrix exists to name - so the ones that can be executed are executed here.

Two kinds live in this file. The lock and the shortcut are run for real on Windows. The
rest are properties of the source: that the window is a Windows window and not a browser in
disguise, that nothing automates anybody's keyboard, and that the journal is written and
never read back to decide anything. Those cannot be run, but they can be checked
mechanically against every file that ships, which is worth more than a sentence.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

WINDOWS = os.name == "nt"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def shipped(*globs):
    """Every tracked file under those globs. Tracked, so a build output or a scratch file
    that happens to be in the tree is not mistaken for something that ships."""
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", *globs],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if listing.returncode != 0:
        return []
    return [ROOT / name for name in listing.stdout.split() if (ROOT / name).is_file()]


class HomeLockTests(unittest.TestCase):
    """One Codex home, one watcher - across installations and across logon sessions.

    The single-instance mutex is per state directory and per session, so two installations
    with different state directories, or one in another session of the same user, would
    both recover the same conversations without this. It is the only thing standing between
    that and two continuations for one interruption.
    """

    @unittest.skipUnless(WINDOWS, "the lock is a Windows byte-range lock")
    def setUp(self):
        from codex_auto_resume.windows import AdapterError, HomeLock
        self.AdapterError = AdapterError
        self.HomeLock = HomeLock
        self.folder = tempfile.TemporaryDirectory()
        self.base = Path(self.folder.name) / "locks"
        self.home = Path(self.folder.name) / "codex"
        self.home.mkdir()

    def tearDown(self):
        self.folder.cleanup()

    def test_a_second_holder_of_one_home_is_refused(self):
        with self.HomeLock(self.home, base=self.base):
            with self.assertRaises(self.AdapterError) as refusal:
                with self.HomeLock(self.home, base=self.base):
                    self.fail("two watchers hold one Codex home")
        self.assertEqual(str(refusal.exception), "home_lock_busy")

    def test_the_lock_is_released_when_the_holder_lets_go(self):
        with self.HomeLock(self.home, base=self.base) as first:
            self.assertTrue(first.held)
        second = self.HomeLock(self.home, base=self.base)
        with second:
            self.assertTrue(second.held, "the lock was never released")

    def test_two_homes_do_not_share_a_lock(self):
        other = Path(self.folder.name) / "codex-other"
        other.mkdir()
        with self.HomeLock(self.home, base=self.base):
            with self.HomeLock(other, base=self.base) as second:
                self.assertTrue(second.held, "unrelated Codex homes are not each other's business")

    def test_the_same_home_spelled_differently_is_the_same_home(self):
        """`C:\\X\\codex` and `C:\\X\\CODEX\\` are one directory, and one lock."""
        spelled = Path(str(self.home).upper() + os.sep)
        with self.HomeLock(self.home, base=self.base):
            with self.assertRaises(self.AdapterError):
                with self.HomeLock(spelled, base=self.base):
                    self.fail("case or a trailing separator was enough to get a second lock")

    @unittest.skipUnless(WINDOWS, "the lock is a Windows byte-range lock")
    def test_a_second_process_is_refused_too(self):
        """Within one process a second lock could be refused by bookkeeping. The case that
        matters is two processes, which is what two installations actually are."""
        program = (
            "import sys, time\n"
            "sys.path.insert(0, %r)\n"
            "from codex_auto_resume.windows import HomeLock\n"
            "with HomeLock(%r, base=%r):\n"
            "    print('held', flush=True)\n"
            "    time.sleep(30)\n"
        ) % (str(ROOT / "src"), str(self.home), str(self.base))
        child = subprocess.Popen([sys.executable, "-c", program],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            first = child.stdout.readline().strip()
            self.assertEqual(first, "held", "the child never took the lock")
            with self.assertRaises(self.AdapterError) as refusal:
                with self.HomeLock(self.home, base=self.base):
                    self.fail("a second process holds the same Codex home")
            self.assertEqual(str(refusal.exception), "home_lock_busy")
        finally:
            child.kill()
            child.wait(timeout=30)
            for pipe in (child.stdout, child.stderr):
                pipe.close()
        # And once that process is gone the home is free again, because Windows closes the
        # handle with it. A lock that outlived its holder would need a person to clear it.
        with self.HomeLock(self.home, base=self.base) as after:
            self.assertTrue(after.held)


class WakeEventTests(unittest.TestCase):
    """Retry now shortens a wait that is already running.

    The watcher sleeps on two named events at once, and Retry now sets one of them from
    another process. Nothing had ever signalled a real one: the control layer's test asks
    whether there was something to wake, which is a different question from whether a
    waiting watcher notices. A wake that never arrives is not dangerous - the stored
    schedule stays the authority, so the recovery is only late - but Retry now would then
    do nothing a person can see, which is the whole of what that button promises.
    """

    @unittest.skipUnless(WINDOWS, "named events are Windows")
    def setUp(self):
        from codex_auto_resume.windows import WakeEvent
        self.WakeEvent = WakeEvent
        self.folder = tempfile.TemporaryDirectory()
        # The name is derived from the state directory, so a test's event is its own.
        self.name = str(Path(self.folder.name) / "state")

    def tearDown(self):
        self.folder.cleanup()

    def waiter(self, seconds):
        """A process that holds the event and waits on it, printing what woke it."""
        program = (
            "import sys, time\n"
            "sys.path.insert(0, %r)\n"
            "from codex_auto_resume.windows import WakeEvent, wait_any\n"
            "with WakeEvent(%r) as wake:\n"
            "    print('waiting', flush=True)\n"
            "    started = time.monotonic()\n"
            "    fired = wait_any([wake.handle], %r)\n"
            "    print('%%s %%.2f' %% (fired, time.monotonic() - started), flush=True)\n"
        ) % (str(ROOT / "src"), self.name, seconds)
        child = subprocess.Popen([sys.executable, "-c", program],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(child.stdout.readline().strip(), "waiting",
                         "the waiter never took the event")
        return child

    def finish(self, child):
        try:
            answer = child.stdout.readline().strip()
        finally:
            child.kill()
            child.wait(timeout=30)
            for pipe in (child.stdout, child.stderr):
                pipe.close()
        return answer

    def test_a_signal_ends_a_wait_that_had_a_long_way_to_go(self):
        child = self.waiter(120)
        self.assertTrue(self.WakeEvent(self.name).signal(), "nothing was holding the event")
        fired, elapsed = self.finish(child).split()
        self.assertEqual(fired, "0", "the wait ended without the wake being what ended it")
        self.assertLess(float(elapsed), 30.0,
                        "the wait was not shortened; Retry now would appear to do nothing")

    def test_signalling_when_nobody_is_waiting_says_so(self):
        """The control layer tells the person whether a watcher heard it, and "nobody was
        there" is a different answer from "asked"."""
        self.assertFalse(self.WakeEvent(self.name).signal())

    def test_the_event_is_per_state_directory(self):
        other = str(Path(self.folder.name) / "another")
        child = self.waiter(20)
        try:
            self.assertFalse(self.WakeEvent(other).signal(),
                             "one installation's Retry now reached another's watcher")
        finally:
            child.kill()
            child.wait(timeout=30)
            for pipe in (child.stdout, child.stderr):
                pipe.close()

    def test_a_wait_with_nothing_to_wait_on_still_ends(self):
        """The fallback path where no event could be created: it sleeps rather than
        returning at once, so a watcher without events does not spin."""
        from codex_auto_resume.windows import wait_any
        started = time.monotonic()
        self.assertIsNone(wait_any([None], 0.3))
        self.assertGreaterEqual(time.monotonic() - started, 0.25)


class TrayMenuTests(unittest.TestCase):
    """Each menu item reaches the thing it names.

    The icon belongs to the watcher process and its menu is the only surface some people
    use. What a menu id dispatches to was read and never run, and the two ways to get it
    wrong are quiet ones: Pause wired to Resume looks identical until somebody uses it,
    and an id that reaches nothing looks like a menu that does not respond.
    """

    def setUp(self):
        from codex_auto_resume import tray
        self.tray = tray
        self.calls = []
        self.icon = tray.Tray(
            strings={},
            on_open=lambda: self.calls.append("open"),
            on_toggle=lambda paused: self.calls.append("resume" if paused else "pause"),
            on_stop=lambda: self.calls.append("stop"),
            log=lambda *unused: self.calls.append("logged"))

    def test_open_opens(self):
        self.icon._act(self.tray.MENU_OPEN, False)
        self.assertEqual(self.calls, ["open"])

    def test_stop_stops(self):
        self.icon._act(self.tray.MENU_STOP, False)
        self.assertEqual(self.calls, ["stop"])

    def test_the_one_item_that_changes_its_mind_is_told_which_way(self):
        """One item, two meanings, and the meaning is the state it was drawn in - not the
        state at the moment it is handled, which may have moved."""
        self.icon._act(self.tray.MENU_TOGGLE, True)
        self.icon._act(self.tray.MENU_TOGGLE, False)
        self.assertEqual(self.calls, ["resume", "pause"])

    def test_closing_the_menu_without_choosing_does_nothing(self):
        """TrackPopupMenu returns 0 when the person clicks away."""
        self.icon._act(0, False)
        self.assertEqual(self.calls, [])

    def test_an_id_that_is_not_a_menu_item_does_nothing(self):
        for chosen in (-1, 4, 99):
            with self.subTest(chosen):
                self.icon._act(chosen, False)
        self.assertEqual(self.calls, [])

    def test_an_action_that_throws_is_logged_and_never_ends_the_watcher(self):
        """The menu runs on the watcher's own thread. An exception escaping here would
        take the icon, and then the watcher, down with it."""
        def angry():
            raise RuntimeError("no")
        icon = self.tray.Tray(strings={}, on_open=angry,
                              log=lambda *unused: self.calls.append("logged"))
        icon._act(self.tray.MENU_OPEN, False)
        self.assertEqual(self.calls, ["logged"])

    def test_a_menu_with_nothing_wired_to_it_is_harmless(self):
        """The watcher builds the icon before its control callbacks exist in some paths."""
        icon = self.tray.Tray(strings={})
        for chosen in (self.tray.MENU_OPEN, self.tray.MENU_TOGGLE, self.tray.MENU_STOP):
            icon._act(chosen, False)


    def test_pending_opens_the_page_where_those_actions_live(self):
        """The tray's answer to Retry now and Cancel: a route to them, not a copy of them.

        A context menu built from a list the watcher is still changing would act on
        whichever row an id meant when the menu was drawn, and a menu item has nowhere to
        name the conversation it is about - which is what the window's confirmations use to
        stop somebody acting on the wrong task.
        """
        reached = []
        icon = self.tray.Tray(strings={}, on_pending=lambda: reached.append("pending"))
        icon._act(self.tray.MENU_PENDING, False)
        self.assertEqual(reached, ["pending"])

    def test_the_window_is_only_ever_opened_on_a_page_it_has(self):
        """The page is spliced into a command line. The list is closed, whatever is asked."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home = Path(folder.name)
        # No executable there, so nothing is started either way; the refusal happens first.
        with self.assertRaises(ValueError):
            self.tray.open_dashboard(home, "pending; Remove-Item C:\\")
        with self.assertRaises(ValueError):
            self.tray.open_dashboard(home, "--exec")
        self.assertIn("pending", self.tray.PAGES)
        self.assertFalse(self.tray.open_dashboard(home, "pending"),
                         "there is no window there to open")


class NoBrowserTests(unittest.TestCase):
    """The window is a Windows window.

    "No localhost server, no browser, no Electron" is one of the load-bearing claims in the
    README: it is why there is no port to reach, no renderer to inject into and no second
    runtime to keep patched. It is also the kind of claim a single convenient dependency
    would end.
    """

    # Anything that would mean a web stack: a browser control, an embedded renderer, a
    # listening socket, or a second runtime to host one.
    FORBIDDEN = re.compile(
        r"\bWebBrowser\b|\bWebView2?\b|\bCoreWebView\b|\bChromium\b|\bCefSharp\b|"
        r"\bHttpListener\b|\bTcpListener\b|\bSocket\s*\(|\bHttpServer\b|"
        # Not the bare word "Electron": `messages.py` names it while explaining which
        # Windows API it calls, and a rule that cannot tell a sentence from a dependency is
        # a rule somebody deletes. What would actually arrive is a second runtime, and
        # `test_no_second_runtime_is_in_the_release` looks for that instead.
        r"\bnode(?:\.exe|_modules)\b|\brequire\('electron'\)|"
        r"\blocalhost:\d|\b127\.0\.0\.1:\d|\bhttp://\+:")

    def test_nothing_that_ships_hosts_or_embeds_a_browser(self):
        offenders = []
        for path in shipped("gui/*", "src/*", "scripts/*", "install/*"):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in self.FORBIDDEN.finditer(text):
                offenders.append("%s: %s" % (path.relative_to(ROOT), match.group()))
        self.assertEqual(sorted(offenders), [],
                         "the window would no longer be only a Windows window")

    def test_no_second_runtime_is_in_the_release(self):
        """The archive carries one runtime, and it is Python's. A `package.json`, a
        `node_modules` or a second interpreter would be a web stack arriving quietly."""
        sys.path.insert(0, str(ROOT / "build"))
        import make_release
        self.assertEqual(make_release.LAUNCHER_FILES,
                         ("Install.cmd", "Uninstall.cmd", "README.txt", "install.ps1"))
        for name in ("package.json", "package-lock.json", "node_modules", "yarn.lock"):
            self.assertFalse((ROOT / name).exists(), name)
        self.assertNotIn("node", make_release.APP_TREES)

    def test_the_window_references_only_the_three_framework_assemblies(self):
        """What it is compiled against is what it can possibly do."""
        script = (ROOT / "build" / "make_gui.ps1").read_text(encoding="utf-8")
        references = set(re.findall(r"'(System[A-Za-z.]*\.dll)'", script))
        self.assertEqual(references, {"System.dll", "System.Drawing.dll", "System.Windows.Forms.dll"})


class NoGuiAutomationTests(unittest.TestCase):
    """Nobody's keyboard, nobody's mouse, nobody's screen.

    The product's safety story rests on doing everything through Codex's own interfaces. A
    single `SendInput` would replace that with typing into whatever window happens to be in
    front, which is both unsafe and unprovable - and it is exactly what a shortcut around a
    protocol limitation looks like when somebody is in a hurry.
    """

    FORBIDDEN = re.compile(
        r"\bSendInput\b|\bkeybd_event\b|\bmouse_event\b|\bSetCursorPos\b|\bSendKeys\b|"
        r"\bSendWait\b|\bSystem\.Windows\.Automation\b|\bAutomationElement\b|"
        r"\bUIAutomation\w*\b|\bIUIAutomation\b|\bAccessibleObjectFromWindow\b|"
        r"\btesseract\b|\bpytesseract\b|\bOcrEngine\b|\bWindows\.Media\.Ocr\b|"
        r"\bGraphics\.CopyFromScreen\b|\bPrintWindow\b|\bBitBlt\b|"
        r"\bpyautogui\b|\bpydirectinput\b|\bpywinauto\b")

    def test_nothing_that_ships_drives_a_keyboard_a_mouse_or_a_screen(self):
        offenders = []
        for path in shipped("gui/*", "src/*", "scripts/*", "install/*", "skills/*"):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in self.FORBIDDEN.finditer(text):
                offenders.append("%s: %s" % (path.relative_to(ROOT), match.group()))
        self.assertEqual(sorted(offenders), [],
                         "something that ships can now drive a window it does not own")

    def test_the_one_screen_capture_is_a_build_tool_and_does_not_ship(self):
        """`build/capture_window.ps1` uses PrintWindow to make the README's screenshots. It
        is developer-only, and the release payload excludes `build/` - which is what makes
        the rule above one this product can hold to rather than an exception list."""
        capture = ROOT / "build" / "capture_window.ps1"
        self.assertTrue(capture.is_file())
        self.assertIn("PrintWindow", capture.read_text(encoding="utf-8"))
        sys.path.insert(0, str(ROOT / "build"))
        import make_release
        self.assertIn("build", make_release.EXCLUDE_DIRS)
        self.assertNotIn("build", make_release.APP_TREES)


class JournalIsWriteOnlyTests(unittest.TestCase):
    """The journal is what happened, not what to do next.

    A journal that decisions read back is a second source of truth, and the two drift: a
    pruned entry, a hidden row or a retention bound would then change what the engine does.
    Every decision is made from the records; `events()` exists for the timeline a person
    reads and for the diagnostics export, and for nothing else.
    """

    def test_the_engine_never_reads_the_journal(self):
        for name in ("engine.py", "app.py", "source.py", "failures.py"):
            text = (ROOT / "src" / "codex_auto_resume" / name).read_text(encoding="utf-8")
            with self.subTest(name):
                self.assertNotIn(".events(", text,
                                 "a decision would now depend on the journal")

    def test_only_the_timeline_and_the_export_read_it(self):
        readers = set()
        for path in shipped("src/*"):
            if path.suffix != ".py":
                continue
            if ".events(" in path.read_text(encoding="utf-8"):
                readers.add(path.name)
        # store.py defines it; these two call it. Nothing else in the runtime does.
        self.assertEqual(readers, {"control.py", "diagnostics.py"},
                         "the set of things that read the journal has changed")

    def test_the_timeline_is_the_only_control_call_that_reads_it(self):
        control = (ROOT / "src" / "codex_auto_resume" / "control.py").read_text(encoding="utf-8")
        # One call site, inside `timeline`.
        self.assertEqual(control.count(".events("), 1)
        timeline = control[control.index("def timeline"):]
        self.assertIn(".events(", timeline[:timeline.index("\n    def ")])


@unittest.skipUnless(WINDOWS and POWERSHELL.is_file(), "the shortcut is a Windows .lnk")
class ShortcutTests(unittest.TestCase):
    r"""The Start Menu shortcut, and the identity the toasts depend on.

    A Windows toast is attributed to an AppUserModelID, and the way an unpackaged program
    gets a name and an icon on its toasts is a shortcut carrying that ID. The whole chain
    was UNVERIFIED: nothing had ever written a `.lnk` and read anything back off it, so a
    COM interface declared with the wrong property key would have looked exactly like this.

    The real `shortcut.install` runs, with `APPDATA` pointed at a temporary directory so
    the machine's own Start Menu is untouched. What it wrote is then read back twice: the
    target through the shell's own shortcut object, and the AppUserModelID out of the file's
    bytes, where it is stored as UTF-16. Reading it through `IPropertyStore` instead would
    check the same write through the same interface that performed it.
    """

    @classmethod
    def setUpClass(cls):
        from codex_auto_resume import shortcut, startup
        cls.shortcut = shortcut
        cls.aumid = startup.AUMID
        cls.folder = tempfile.TemporaryDirectory()
        cls.appdata = Path(cls.folder.name) / "AppData" / "Roaming"
        cls.target = Path(cls.folder.name) / "CodexAutoResumeSettings.exe"
        cls.target.write_bytes(b"MZ this is not a real program")
        previous = os.environ.get("APPDATA")
        os.environ["APPDATA"] = str(cls.appdata)
        try:
            cls.written = shortcut.install(str(cls.target), icon=str(cls.target))
            cls.link = shortcut.shortcut_path()
            cls.directory = shortcut.start_menu_dir()
            cls.exists = shortcut.exists()
        finally:
            if previous is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = previous

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_a_real_shortcut_file_is_written(self):
        self.assertTrue(self.written)
        self.assertTrue(self.exists, "install() reported success and exists() disagreed")
        self.assertTrue(self.link.is_file(), "no .lnk was written")
        self.assertGreater(self.link.stat().st_size, 0)

    def test_it_is_written_where_the_uninstaller_looks(self):
        """Two spellings of the path is a shortcut nothing can remove."""
        self.assertEqual(self.link.name, self.shortcut.SHORTCUT_NAME)
        self.assertEqual(self.link.parent, self.directory)
        self.assertIn("Start Menu", str(self.link))

    def test_windows_reads_the_target_back_off_it(self):
        script = Path(self.folder.name) / "read.ps1"
        script.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CAR_LINK)\n"
            "Write-Output ('target=' + $link.TargetPath)\n"
            "Write-Output ('description=' + $link.Description)\n",
            encoding="utf-8")
        result = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            env=dict(os.environ, CAR_LINK=str(self.link)))
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        found = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        self.assertEqual(found.get("target", "").strip().lower(), str(self.target).lower())
        self.assertEqual(found.get("description", "").strip(), "Codex Auto Resume")

    def test_it_carries_the_identity_the_notifier_sends_toasts_under(self):
        from codex_auto_resume import notify
        self.assertTrue(self.aumid, "there is no AppUserModelID to carry")
        self.assertEqual(notify.aumid(), self.aumid,
                         "the shortcut and the notifier would name two different senders")
        self.assertIn(self.aumid.encode("utf-16-le"), self.link.read_bytes(),
                      "the AppUserModelID was not written into the shortcut, so Windows has "
                      "nothing to attribute a toast to")

    def test_removing_it_removes_only_ours(self):
        previous = os.environ.get("APPDATA")
        os.environ["APPDATA"] = str(self.appdata)
        stranger = self.shortcut.start_menu_dir() / "Something Else.lnk"
        stranger.write_bytes(b"not ours")
        try:
            self.assertTrue(self.shortcut.uninstall())
            self.assertFalse(self.shortcut.exists())
            self.assertTrue(stranger.is_file(), "it removed a shortcut that is not this product's")
            # Idempotent: an uninstall with nothing to remove is not a failure.
            self.assertFalse(self.shortcut.uninstall())
            # Put it back for whatever runs after this.
            self.shortcut.install(str(self.target), icon=str(self.target))
        finally:
            stranger.unlink()
            if previous is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = previous


if __name__ == "__main__":
    unittest.main()
