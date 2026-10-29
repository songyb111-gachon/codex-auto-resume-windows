"""A scratch stand-in for the Codex Desktop app's IPC pipe, for the forced stop's tests (v0.6.16-beta.4): a named pipe of
the test's own name - never \\\\.\\pipe\\codex-ipc - answering the frames codex/ipc.py sends as the app does (the MIPC
record), with each answer a test can change: `script` maps a method to a reply's fields, or to None for silence.
Windows only; every test that uses it skips elsewhere."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import struct
import threading
import uuid

_K32 = ctypes.WinDLL("kernel32", use_last_error=True) if hasattr(ctypes, "WinDLL") else None
if _K32 is not None:
    _K32.CreateNamedPipeW.restype = wintypes.HANDLE
    _K32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    _K32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _K32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    _K32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                              ctypes.c_void_p]
    _K32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                               ctypes.c_void_p]
    _K32.CloseHandle.argtypes = [wintypes.HANDLE]

OWNER = "owner-client"
CLIENT = "our-client"


class FakeApp:
    """One connection's worth of the app: initialize, thread-owner-discovery, then whatever is asked. `script`:
    {method: dict of the reply's fields (resultType, result, error, handledByClientId) or None for no answer}.
    `seen` keeps every request's method, version and params."""

    def __init__(self, script=None):
        self.name = r"\\.\pipe\car-test-ipc-%s" % uuid.uuid4().hex
        self.script = dict(script or {})
        self.seen = []
        self.broadcast_first = True
        # The turn the app has running: None takes any expectedTurnId as it (and names "t" to a v3 stop); a turn id
        # makes a v4 stop naming another a silent success that names no stopped turn, as the app does (MIPC-v4).
        self.running = None
        self._handle = _K32.CreateNamedPipeW(self.name, 3, 0, 1, 65536, 65536, 0, None)
        if self._handle in (None, wintypes.HANDLE(-1).value):
            raise OSError("no scratch pipe")
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _read(self, size):
        found = b""
        while len(found) < size:
            buffer = ctypes.create_string_buffer(size - len(found))
            count = wintypes.DWORD(0)
            if not _K32.ReadFile(self._handle, buffer, size - len(found), ctypes.byref(count), None) or not count.value:
                raise EOFError
            found += buffer.raw[:count.value]
        return found

    def _write(self, message):
        data = json.dumps(message).encode("utf-8")
        frame = struct.pack("<I", len(data)) + data
        count = wintypes.DWORD(0)
        _K32.WriteFile(self._handle, frame, len(frame), ctypes.byref(count), None)

    def _serve(self):
        _K32.ConnectNamedPipe(self._handle, None)
        try:
            while True:
                size = struct.unpack("<I", self._read(4))[0]
                request = json.loads(self._read(size).decode("utf-8"))
                method = request.get("method")
                self.seen.append((method, request.get("version"), request.get("params"), request.get("targetClientId")))
                if self.broadcast_first:
                    self._write({"type": "broadcast", "method": "thread-stream-state-changed", "params": {}})
                reply = self.script.get(method, self._default(method, request.get("params") or {}))
                if reply is None:
                    continue                                   # silent
                self._write(dict({"type": "response", "requestId": request.get("requestId")}, **reply))
        except Exception:
            return

    def _default(self, method, params):
        if method == "initialize":
            return {"resultType": "success", "result": {"clientId": CLIENT}}
        if method == "thread-owner-discovery":
            return {"resultType": "success", "handledByClientId": OWNER, "result": {"supportsUntrustedAppInput": True}}
        if method == "thread-follower-interrupt-turn":
            expected = params.get("expectedTurnId")
            if expected is None:
                return {"resultType": "success", "result": {"interruptedTurnId": self.running or "t"}}
            if self.running is not None and expected != self.running:
                return {"resultType": "success", "result": {}}
            return {"resultType": "success", "result": {"interruptedTurnId": expected}}
        if method == "thread-follower-set-queued-follow-ups-state":
            return {"resultType": "success", "result": {}}
        if method == "thread-follower-start-turn":
            return {"resultType": "success", "result": {"result": {"turn": {}}}}
        if method == "thread-follower-steer-turn":
            return {"resultType": "success", "result": {"result": {}}}
        return {"resultType": "error", "error": "no-handler-for-request"}

    def close(self):
        _K32.CloseHandle(self._handle)
