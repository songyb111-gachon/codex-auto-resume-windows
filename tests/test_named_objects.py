"""A lower-integrity process cannot impersonate or stop the watcher by naming its objects first.

The watcher's single-instance mutex and its stop event have predictable names in the
session namespace, and a Low-integrity process may create objects there. The v0.6.0
security review showed, with a real Low process, that pre-creating the mutex made every
status read report a running watcher when none existed and made the real one exit as if
it had a twin, and that pre-creating and signalling the stop event made a real watcher
quit on start - silently, with nothing in the log.

Once this process has created them, a lower-integrity process cannot touch them; the only
opening is getting there first, which leaves the creator's lower label on the object.
These tests plant a Low-labelled object the way a squatter would - a process may label an
object at or below its own level - and check the watcher refuses it and says why, while
an ordinary Medium object, such as a real second watcher's, is still honoured.

Measured separately against the review's real Low-integrity squatter: v0.5.x reported the
phantom watcher as running and obeyed the planted stop event in a third of a second; this
code reports "unknown", refuses to run, and logs named_object_squatted.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.app import App, EXIT_ERROR  # noqa: E402
from codex_auto_resume.windows import AdapterError  # noqa: E402

LOW_LABEL = "S:(ML;;NW;;;LW)"


class SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", ctypes.c_uint32), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", ctypes.c_int)]


def plant(kind: str, name: str, sddl: str | None):
    """Create a named mutex or event, optionally with an explicit label. Returns the handle."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    attributes = None
    if sddl:
        descriptor = ctypes.c_void_p()
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise OSError(ctypes.get_last_error())
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor.value, 0)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    pointer = ctypes.byref(attributes) if attributes else None
    handle = (kernel.CreateMutexW(pointer, False, name) if kind == "mutex"
              else kernel.CreateEventW(pointer, True, False, name))
    if not handle:
        raise OSError(ctypes.get_last_error())
    return handle


def close(handle):
    ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(handle))


@unittest.skipUnless(os.name == "nt", "Windows named objects")
class SquattedObjectTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(config.Paths(str(Path(self.folder.name) / "home")), console=False,
                       enable_logging=False)

    def test_a_low_labelled_mutex_is_not_reported_as_a_running_watcher(self):
        handle = plant("mutex", self.app.mutex().name, LOW_LABEL)
        self.addCleanup(close, handle)
        self.assertIsNone(self.app.watcher_running(),
                          "unknown, not a phantom watcher that is running")
        with self.assertRaises(AdapterError) as caught:
            with self.app.mutex(timeout=0.0):
                pass
        self.assertEqual(str(caught.exception), "named_object_squatted")

    def test_the_watcher_refuses_to_run_on_a_squatted_mutex(self):
        handle = plant("mutex", self.app.mutex().name, LOW_LABEL)
        self.addCleanup(close, handle)
        self.assertEqual(self.app.run(once=True), EXIT_ERROR)

    def test_the_watcher_refuses_a_squatted_stop_event(self):
        handle = plant("event", self.app.stop_event().name, LOW_LABEL)
        self.addCleanup(close, handle)
        self.assertEqual(self.app.run(once=True), EXIT_ERROR)

    def test_an_ordinary_existing_mutex_is_still_honoured(self):
        """A real second watcher's mutex is Medium; it must still mean 'busy', not 'squatted'."""
        handle = plant("mutex", self.app.mutex().name, None)
        self.addCleanup(close, handle)
        # Present but not held: an ordinary object, so the probe acquires and releases it.
        self.assertIs(self.app.watcher_running(), False)

    def test_no_squatter_no_change(self):
        self.assertIs(self.app.watcher_running(), False)


if __name__ == "__main__":
    unittest.main()
