"""The forced stop's channel to the Codex app's pipe trusts only this account's own server (v0.6.18, security review
S5): the pipe is opened at SECURITY_IDENTIFICATION, so whoever serves it cannot act as the watcher's account, and the
server process (GetNamedPipeServerProcessId) must run as this account, in this session, at no lower integrity and
outside an AppContainer before anything is written - else NO_PIPE, as where no app runs. Scratch pipes only, never
the real codex-ipc pipe.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import threading
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume_advanced.codex import ipc  # noqa: E402

THREAD = "aaaaaaaa-0000-7000-8000-00000000a001"
LEVELS = {0: "Anonymous", 1: "Identification", 2: "Impersonation", 3: "Delegation"}


def _impersonating_server(name, seen, ready):
    """A scratch server that reads one frame, then impersonates its client and reports the level it got."""
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.CreateNamedPipeW.restype = wintypes.HANDLE
    k32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    k32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                             ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetCurrentThread.restype = wintypes.HANDLE
    adv.ImpersonateNamedPipeClient.argtypes = [wintypes.HANDLE]
    adv.OpenThreadToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    pipe = k32.CreateNamedPipeW(name, 0x3, 0x0, 1, 65536, 65536, 0, None)
    ready.set()
    try:
        k32.ConnectNamedPipe(pipe, None)
        head, got = ctypes.create_string_buffer(4), wintypes.DWORD()
        k32.ReadFile(pipe, head, 4, ctypes.byref(got), None)
        body = ctypes.create_string_buffer(max(1, int.from_bytes(head.raw, "little")))
        k32.ReadFile(pipe, body, len(body), ctypes.byref(got), None)
        seen["frame"] = got.value > 0
        if adv.ImpersonateNamedPipeClient(pipe):
            token = wintypes.HANDLE()
            if adv.OpenThreadToken(k32.GetCurrentThread(), 0x8, True, ctypes.byref(token)):
                level, needed = ctypes.c_int(), wintypes.DWORD()
                adv.GetTokenInformation(token, 9, ctypes.byref(level), 4, ctypes.byref(needed))
                seen["level"] = LEVELS.get(level.value, level.value)
                k32.CloseHandle(token)
            adv.RevertToSelf()
    finally:
        k32.CloseHandle(pipe)


@unittest.skipUnless(sys.platform == "win32", "a Windows named pipe")
class ServerTests(unittest.TestCase):
    def test_the_server_can_identify_the_client_but_never_act_as_it(self):
        """Fails with the SQOS flags reverted: the server impersonated the client at Impersonation."""
        name = r"\\.\pipe\car-test-ipc-sqos-%s" % uuid.uuid4().hex
        seen, ready = {}, threading.Event()
        server = threading.Thread(target=_impersonating_server, args=(name, seen, ready), daemon=True)
        server.start()
        ready.wait(5)
        channel = ipc.Channel(name)
        try:
            channel.write({"type": "request", "method": "initialize"})
        finally:
            server.join(5)
            channel.close()
        self.assertTrue(seen.get("frame"))
        self.assertEqual(seen.get("level"), "Identification")

    def test_a_server_not_this_accounts_own_is_refused_before_anything_is_written(self):
        """Fails with the server check reverted: the stop was written to a pipe whose server was not trusted."""
        import fakeipc
        self.assertTrue(callable(getattr(ipc, "server_trusted", None)), "the server is checked")
        app = fakeipc.FakeApp()
        self.addCleanup(app.close)
        asked = []
        with patch.object(ipc, "server_trusted", lambda pid: asked.append(pid) or False):
            with self.assertRaises(ipc._Failed) as refused:
                ipc.Channel(app.name)
        self.assertEqual(refused.exception.word, ipc.Stop.NO_PIPE, "as where no app runs")
        self.assertEqual(asked, [os.getpid()], "the pipe's own server process is the one checked")
        self.assertEqual(app.seen, [], "nothing written")

    def test_this_process_is_trusted_and_another_account_s_is_not(self):
        self.assertTrue(ipc.server_trusted(os.getpid()))
        for pid in (4, 0, None, -1):                    # 4: the System process, another account
            self.assertFalse(ipc.server_trusted(pid), pid)


if __name__ == "__main__":
    unittest.main()
