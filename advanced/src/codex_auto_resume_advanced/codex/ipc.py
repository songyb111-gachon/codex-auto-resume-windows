# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Codex Desktop app's own IPC pipe, \\\\.\\pipe\\codex-ipc - for the forced stop near a usage limit and, from v0.6.20, MSTEER2's steer
(v0.6.16-beta.4, usage_pause; measurement MIPC passed on codex-cli 0.162.0-alpha.17.2 with app 26.1007.9446.0, and
again on 0.163.0-alpha.10.2 with app 26.1013.3656.0 - f16c9ca2 on measure-20261017 - where v4 was measured too).

What it does, and nothing else: open the pipe, `initialize`, ask `thread-owner-discovery` which client of the app
holds the conversation, and ask that client `thread-follower-interrupt-turn` (mode "system") for it - the stop a
person makes with the app's own Stop button. The app then pauses that conversation's queue, a pause that survives
its restart. And, after the window resets, `thread-follower-start-turn` - a turn started with the product's own
continuation, which goes past that paused queue - for a conversation it stopped (start_turn); measured 2026-10-16,
once that turn completes the app sends what was queued by itself and the pause is gone, so nothing else is asked of
the queue (`thread-follower-set-queued-follow-ups-state` is not needed). v0.6.20 adds `steer_turn`, a line added to the
running turn, for the MSTEER2 measurement and - from v0.6.20, by the owner's decision of 2026-10-29 after MSTEER2 found the
line delivered but never shown - the steer_send capability's errand (engine/steer.py), which only the watcher runs. Every frame is 4 bytes of little-endian
length and UTF-8 JSON. Each request has one deadline for its whole answer, READ_SECONDS from when it is written,
however many broadcasts come first (an overlapped read, cancelled and waited out, then the pipe closed - as the MIPC
look does); nothing here waits for good.

The app checks each request's version exactly, and a new app build may move one: the versions are pinned in
REQUESTS, every request's shape is there too, and a version mismatch is an answer like any other failure - the
caller falls back (holds this product's continuations until the reset, and tells the person the turn could not be
stopped). Every outcome is one closed word (Stop). Never a conversation's words, never an id in a log: the caller
journals the word alone.
"""
from __future__ import annotations

import json
import struct
import time
import uuid
from enum import StrEnum

PIPE = r"\\.\pipe\codex-ipc"
# Each request's whole wait for its answer, from when it is written - one deadline, however many frames come first.
READ_SECONDS = 5.0
# The stop's own wait, longer: it took 1.1 s live (MIPC, 2026-10-16), the MIPC probe allowed 60 s; an answer slower than
# this is taken as a stop that may have been made (UNCONFIRMED), never as one that was not.
INTERRUPT_SECONDS = 30.0
# The most frames that are not the answer (the app's broadcasts, other clients' replies) taken while one is awaited.
FRAMES_LIMIT = 200
# The longest frame taken: the app's broadcasts can be long, a reply to these never is.
FRAME_LIMIT = 8 * 1024 * 1024
# The request shapes and the versions the app checks exactly (the MIPC record, 2026-10-16; app 26.1007). Filled with
# {thread}, {turn}, {message} and {text} where each request names them.
CLIENT_TYPE = "codex-auto-resume"
REQUESTS = {
    "initialize": (0, {"clientType": CLIENT_TYPE}),
    "thread-owner-discovery": (1, {"hostId": "local", "conversationId": "{thread}"}),
    "thread-follower-interrupt-turn": (3, {"conversationId": "{thread}", "mode": "system"}),
    "thread-follower-start-turn": (2, {"conversationId": "{thread}", "turnStart": {
        "request": {"threadId": "{thread}", "clientUserMessageId": "{message}",
                    "input": [{"type": "text", "text": "{text}", "text_elements": []}]},
        "context": {"inheritThreadSettings": True}}}),
    # v0.6.20 (MSTEER2, issue #50): a line added to the turn the app is running, as the app's own steer does for a window
    # that follows the conversation (the 2026-10-16 experiment, measure-20261016/ipc_try.py: success, inside the running
    # turn, shown as the person's message). It names no turn: the app steers the conversation's running one, which is
    # why the caller checks the history before and after. restoreMessage is what the app builds the steering item from.
    "thread-follower-steer-turn": (1, {
        "conversationId": "{thread}", "clientUserMessageId": "{message}",
        "input": [{"type": "text", "text": "{text}", "text_elements": []}],
        "restoreMessage": {"id": "{message}", "text": "{text}", "cwd": None,
                           "context": {"workspaceRoots": [], "collaborationMode": None, "commentAttachments": []}},
        "serviceTier": None, "attachments": [], "additionalContext": None, "toolOutput": None}),
}
# v4 of the stop names the running turn it expects to stop, so a turn begun in between is never stopped.
INTERRUPT_EXPECTING = (4, {"conversationId": "{thread}", "mode": "system", "expectedTurnId": "{turn}"})


class Stop(StrEnum):
    """What came of one forced stop - the closed words the journal keeps."""
    STOPPED = "stopped"                      # the app stopped the turn
    # The app answered success but named no stopped turn, or another one: v4 with a stale or made-up expectedTurnId
    # is a silent no-op, the turn still running (MIPC-v4, codex-cli 0.163 / app 26.1013, 2026-10-17).
    NOT_STOPPED = "not_stopped"
    NO_CLIENT = "no_client"                  # the app does not hold the conversation (not open, or not running)
    VERSION_MISMATCH = "version_mismatch"    # the app's build checks another version of a request
    NO_PIPE = "no_pipe"                      # the pipe is not there: the app is not running
    NO_ANSWER = "no_answer"                  # it did not answer in time
    # The stop was asked and no answer came within INTERRUPT_SECONDS: it may have been made - so the caller keeps the
    # conversation for its continuation after the reset, which is what lets a queue the app paused go.
    UNCONFIRMED = "unconfirmed"
    REFUSED = "refused"                      # any other answer than success
    BROKEN = "broken"                        # a frame that is not one, or the pipe failing under us
    # Core's errand guard refused the one request that cannot be taken back - recovery paused or only observed, an
    # administrator's DisableAutoResume, quiet hours - so it was never written.
    HELD = "held"


class Start(StrEnum):
    """What came of one turn started - the closed words the journal keeps (and Stop's for every failure)."""
    STARTED = "started"


class Steer(StrEnum):
    """What came of one line added to a running turn (steer_turn) - the closed word; Stop's for every failure."""
    STEERED = "steered"


class _Failed(Exception):
    def __init__(self, word):
        super().__init__(word)
        self.word = word


def _filled(shape, fields):
    if isinstance(shape, dict):
        return {key: _filled(value, fields) for key, value in shape.items()}
    if isinstance(shape, list):
        return [_filled(value, fields) for value in shape]
    if isinstance(shape, str) and shape.startswith("{") and shape.endswith("}") and shape[1:-1] in fields:
        return fields[shape[1:-1]]
    return shape


_OVERLAPPED = []


def _overlapped():
    """Windows' OVERLAPPED, made once, when a channel first needs it (ctypes only where it is used)."""
    if not _OVERLAPPED:
        import ctypes

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p), ("Offset", ctypes.c_uint32),
                        ("OffsetHigh", ctypes.c_uint32), ("hEvent", ctypes.c_void_p)]
        _OVERLAPPED.append(OVERLAPPED)
    return _OVERLAPPED[0]


# v0.6.18 (security review S5): the pipe is opened at SECURITY_IDENTIFICATION, so whoever serves it may learn who asks
# but never act as us; and its server is checked before anything is written (`server_trusted`).
SECURITY_SQOS = 0x00100000 | 0x00010000            # SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION


def server_trusted(pid) -> bool:
    """Whether the process `pid` serving the pipe runs as this account, in this Windows session, at no lower integrity
    than this process and outside an AppContainer - what the person's own Codex app is. The pipe's name is machine-wide:
    another account, or a sandboxed process of this one, could create it while the app is not running. False wherever
    anything cannot be read."""
    import ctypes
    import os
    from ctypes import wintypes
    if not isinstance(pid, int) or pid <= 0:
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    adv.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    token_query, query_limited = 0x0008, 0x1000
    token_user, token_integrity, token_app_container = 1, 25, 29

    def information(token, kind):
        needed = wintypes.DWORD(0)
        adv.GetTokenInformation(token, kind, None, 0, ctypes.byref(needed))
        if not 0 < needed.value <= 65536:
            return None
        buffer = ctypes.create_string_buffer(needed.value)
        if not adv.GetTokenInformation(token, kind, buffer, needed, ctypes.byref(needed)):
            return None
        return buffer

    def sid_of(buffer):                                 # TOKEN_USER and TOKEN_MANDATORY_LABEL: a SID pointer first
        return ctypes.c_void_p.from_buffer(buffer).value

    def integrity(buffer):
        sid = sid_of(buffer)
        count = adv.GetSidSubAuthorityCount(sid)[0]
        return adv.GetSidSubAuthority(sid, count - 1)[0] if count else None

    def token_of(process):
        token = wintypes.HANDLE()
        return token if adv.OpenProcessToken(process, token_query, ctypes.byref(token)) else None

    ours = token_of(k32.GetCurrentProcess())
    process = k32.OpenProcess(query_limited, False, pid)
    theirs = token_of(process) if process else None
    try:
        if ours is None or theirs is None:
            return False
        session, own_session = wintypes.DWORD(), wintypes.DWORD()
        if (not k32.ProcessIdToSessionId(pid, ctypes.byref(session))
                or not k32.ProcessIdToSessionId(os.getpid(), ctypes.byref(own_session))
                or session.value != own_session.value):
            return False
        user, own_user = information(theirs, token_user), information(ours, token_user)
        if user is None or own_user is None or not adv.EqualSid(sid_of(user), sid_of(own_user)):
            return False
        level, own_level = information(theirs, token_integrity), information(ours, token_integrity)
        if level is None or own_level is None:
            return False
        theirs_level, own = integrity(level), integrity(own_level)
        if theirs_level is None or own is None or theirs_level < own:
            return False
        contained = information(theirs, token_app_container)
        return contained is not None and wintypes.DWORD.from_buffer(contained).value == 0
    except Exception:
        return False
    finally:
        for handle in (ours, theirs):
            if handle:
                k32.CloseHandle(handle)
        if process:
            k32.CloseHandle(process)


def server_pid(k32, pipe):
    """The process serving `pipe` (GetNamedPipeServerProcessId), or None."""
    import ctypes
    from ctypes import wintypes
    k32.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    found = wintypes.ULONG(0)
    return found.value if k32.GetNamedPipeServerProcessId(pipe, ctypes.byref(found)) and found.value else None


class Channel:
    """One connection to the pipe, opened read-write, overlapped, at SECURITY_IDENTIFICATION, closed by `close` - and
    refused (NO_PIPE, as where no app runs) where its server is not this account's own (`server_trusted`). `name` is a
    seam a test fills with a scratch pipe of its own name - never the real one."""

    def __init__(self, name=None):
        import ctypes
        from ctypes import wintypes
        self._ctypes, self._wintypes = ctypes, wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.CreateEventW.restype = wintypes.HANDLE
        k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        for name_ in ("ReadFile", "WriteFile"):
            getattr(k32, name_).argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                           ctypes.c_void_p]
        k32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                            wintypes.BOOL]
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.ResetEvent.argtypes = [wintypes.HANDLE]
        self._k32 = k32
        self._pipe = None
        self._event = None
        generic_read_write, open_existing, overlapped = 0xC0000000, 3, 0x40000000
        pipe = k32.CreateFileW(PIPE if name is None else name, generic_read_write, 0, None, open_existing,
                               overlapped | SECURITY_SQOS, None)
        if pipe in (None, wintypes.HANDLE(-1).value):
            raise _Failed(Stop.NO_PIPE)
        self._pipe = pipe
        if not server_trusted(server_pid(k32, pipe)):
            self.close()                                # nothing written: not the person's own Codex app
            raise _Failed(Stop.NO_PIPE)
        self._event = k32.CreateEventW(None, True, False, None)
        if not self._event:
            self.close()
            raise _Failed(Stop.BROKEN)

    def _io(self, call, buffer, size, seconds):
        ctypes, k32 = self._ctypes, self._k32
        k32.ResetEvent(self._event)
        overlapped = _overlapped()(hEvent=self._event)
        count = self._wintypes.DWORD(0)
        started = call(self._pipe, buffer, size, None, ctypes.byref(overlapped))
        if not started and ctypes.get_last_error() != 997:            # ERROR_IO_PENDING
            raise _Failed(Stop.BROKEN)
        if k32.WaitForSingleObject(self._event, int(seconds * 1000)) != 0:
            k32.CancelIoEx(self._pipe, ctypes.byref(overlapped))
            k32.GetOverlappedResult(self._pipe, ctypes.byref(overlapped), ctypes.byref(count), True)
            raise _Failed(Stop.NO_ANSWER)
        if not k32.GetOverlappedResult(self._pipe, ctypes.byref(overlapped), ctypes.byref(count), False):
            raise _Failed(Stop.BROKEN)
        return count.value

    def _exactly(self, size, seconds):
        found = b""
        while len(found) < size:
            buffer = self._ctypes.create_string_buffer(size - len(found))
            got = self._io(self._k32.ReadFile, buffer, size - len(found), seconds)
            if got <= 0:
                raise _Failed(Stop.BROKEN)
            found += buffer.raw[:got]
        return found

    def write(self, message) -> None:
        data = json.dumps(message).encode("utf-8")
        frame = struct.pack("<I", len(data)) + data
        buffer = self._ctypes.create_string_buffer(frame, len(frame))
        if self._io(self._k32.WriteFile, buffer, len(frame), READ_SECONDS) != len(frame):
            raise _Failed(Stop.BROKEN)

    def read(self, seconds=READ_SECONDS):
        size = struct.unpack("<I", self._exactly(4, seconds))[0]
        if not 0 < size <= FRAME_LIMIT:
            raise _Failed(Stop.BROKEN)
        try:
            found = json.loads(self._exactly(size, seconds).decode("utf-8"))
        except ValueError:
            raise _Failed(Stop.BROKEN) from None
        if not isinstance(found, dict):
            raise _Failed(Stop.BROKEN)
        return found

    def close(self) -> None:
        if self._event:
            self._k32.CloseHandle(self._event)
            self._event = None
        if self._pipe is not None:
            self._k32.CloseHandle(self._pipe)
            self._pipe = None


def _request(channel, client, method, shape, fields, target=None, seconds=None, gate=None):
    """One request and its answer, within one deadline (`seconds`, READ_SECONDS unless given) from its writing.
    `gate`, for the one request that cannot be taken back: core's errand guard, entered around its writing alone (the
    answer is waited for outside it, as the queue launch lets its guard go before the receipt); refused, it is never
    written (HELD)."""
    version, params = shape
    key = str(uuid.uuid4())
    message = {"type": "request", "requestId": key, "sourceClientId": client, "version": version,
               "method": method, "params": _filled(params, fields)}
    if target is not None:
        message["targetClientId"] = target
    if gate is None:
        channel.write(message)
    else:
        with gate() as permitted:
            if permitted is not True:
                raise _Failed(Stop.HELD)
            channel.write(message)
    deadline = time.monotonic() + (READ_SECONDS if seconds is None else seconds)
    for _ in range(FRAMES_LIMIT + 1):
        left = deadline - time.monotonic()
        if left <= 0:
            break
        found = channel.read(left)
        if found.get("type") == "client-discovery-request":
            channel.write({"type": "client-discovery-response", "requestId": found.get("requestId"),
                           "response": {"canHandle": False}})
            continue
        if found.get("type") != "response" or found.get("requestId") != key:
            continue                                       # a broadcast, or another client's
        if found.get("resultType") == "success":
            return found
        error = found.get("error")
        if error == "no-client-found":
            raise _Failed(Stop.NO_CLIENT)
        if error == "request-version-mismatch":
            raise _Failed(Stop.VERSION_MISMATCH)
        raise _Failed(Stop.REFUSED)
    raise _Failed(Stop.NO_ANSWER)


def _stopped(answer, turn_id):
    """STOPPED only where the app names the turn it stopped - the one expected (v4), or any (v3, no turn known): a
    success that names none, or another, stopped nothing (MIPC-v4, 2026-10-17)."""
    result = answer.get("result")
    stopped = result.get("interruptedTurnId") if isinstance(result, dict) else None
    if not isinstance(stopped, str) or not stopped:
        return Stop.NOT_STOPPED
    return Stop.STOPPED if not turn_id or stopped == turn_id else Stop.NOT_STOPPED


def stop_turn(thread_id, turn_id=None, *, channel=None, gate=None) -> tuple:
    """Stop the running turn of `thread_id` the app holds: the Stop word of what came of it. `turn_id`, where known,
    makes it the v4 stop that names it. `gate` is core's errand guard, around the stop's writing (HELD where it
    refuses). `channel` is a seam (a Channel of a test's own pipe)."""
    try:
        opened = channel if channel is not None else Channel()
    except _Failed as failed:
        return failed.word
    except Exception:
        return Stop.BROKEN
    try:
        hello = _request(opened, "initializing-client", "initialize", REQUESTS["initialize"], {})
        client = (hello.get("result") or {}).get("clientId")
        if not isinstance(client, str) or not client:
            return Stop.REFUSED
        owner = _request(opened, client, "thread-owner-discovery", REQUESTS["thread-owner-discovery"],
                         {"thread": thread_id}).get("handledByClientId")
        if not isinstance(owner, str) or not owner:
            return Stop.NO_CLIENT
        shape = INTERRUPT_EXPECTING if turn_id else REQUESTS["thread-follower-interrupt-turn"]
        try:
            answer = _request(opened, client, "thread-follower-interrupt-turn", shape,
                              {"thread": thread_id, "turn": turn_id}, target=owner, seconds=INTERRUPT_SECONDS,
                              gate=gate)
        except _Failed as failed:
            if failed.word == Stop.NO_ANSWER:
                return Stop.UNCONFIRMED
            raise
        return _stopped(answer, turn_id)
    except _Failed as failed:
        return failed.word
    except Exception:
        return Stop.BROKEN
    finally:
        opened.close()


def start_turn(thread_id, text, *, channel=None, gate=None):
    """Start a turn of `thread_id` the app holds with `text` - the product's continuation after a window reset, for a
    conversation the forced stop stopped (its queue may be paused): Start.STARTED, or the Stop word of what failed -
    NO_CLIENT above all, the app not holding the conversation; UNCONFIRMED where it was written and no answer came in
    time (it may have started). `gate` is core's errand guard, around the start's
    writing (HELD where it refuses). `channel` is a seam (a Channel of a test's own pipe)."""
    try:
        opened = channel if channel is not None else Channel()
    except _Failed as failed:
        return failed.word
    except Exception:
        return Stop.BROKEN
    try:
        hello = _request(opened, "initializing-client", "initialize", REQUESTS["initialize"], {})
        client = (hello.get("result") or {}).get("clientId")
        if not isinstance(client, str) or not client:
            return Stop.REFUSED
        owner = _request(opened, client, "thread-owner-discovery", REQUESTS["thread-owner-discovery"],
                         {"thread": thread_id}).get("handledByClientId")
        if not isinstance(owner, str) or not owner:
            return Stop.NO_CLIENT
        try:
            _request(opened, client, "thread-follower-start-turn", REQUESTS["thread-follower-start-turn"],
                     {"thread": thread_id, "message": str(uuid.uuid4()), "text": text}, target=owner, gate=gate)
        except _Failed as failed:
            # v0.6.18: written and no answer in time - the turn may have started, as a stop with no answer may have
            # been made: UNCONFIRMED, never said to have failed; the next look at the turns tells which.
            if failed.word == Stop.NO_ANSWER:
                return Stop.UNCONFIRMED
            raise
        return Start.STARTED
    except _Failed as failed:
        return failed.word
    except Exception:
        return Stop.BROKEN
    finally:
        opened.close()


def steer_turn(thread_id, text, *, message=None, channel=None, gate=None):
    """Add `text` to the turn the app is running for `thread_id` (MSTEER2, v0.6.20): Steer.STEERED, or the Stop word of
    what failed - NO_PIPE (no app), NO_CLIENT (the app does not hold the conversation), VERSION_MISMATCH, REFUSED, HELD,
    UNCONFIRMED where the request was written and no answer came in time, or the pipe failed after it was written (it
    may be in the turn), BROKEN where nothing of it was written. One request is written, once: nothing here asks again,
    whatever the answer. `message` is the client id the line carries (the history
    shows it on the person's message). `gate` is core's errand guard, around the one writing (HELD where it refuses).
    `channel` is a seam (a Channel of a test's own pipe)."""
    try:
        opened = channel if channel is not None else Channel()
    except _Failed as failed:
        return failed.word
    except Exception:
        return Stop.BROKEN
    try:
        hello = _request(opened, "initializing-client", "initialize", REQUESTS["initialize"], {})
        client = (hello.get("result") or {}).get("clientId")
        if not isinstance(client, str) or not client:
            return Stop.REFUSED
        owner = _request(opened, client, "thread-owner-discovery", REQUESTS["thread-owner-discovery"],
                         {"thread": thread_id}).get("handledByClientId")
        if not isinstance(owner, str) or not owner:
            return Stop.NO_CLIENT
        try:
            _request(opened, client, "thread-follower-steer-turn", REQUESTS["thread-follower-steer-turn"],
                     {"thread": thread_id, "message": message or str(uuid.uuid4()), "text": text}, target=owner,
                     gate=gate)
        except _Failed as failed:
            # v0.6.20 (steer_send): a pipe that fails while the steer is written or its answer read leaves it possibly
            # written, as an answer that never came does - UNCONFIRMED, never a failure a caller might write it again for.
            if failed.word in (Stop.NO_ANSWER, Stop.BROKEN):
                return Stop.UNCONFIRMED
            raise
        except Exception:
            return Stop.UNCONFIRMED
        return Steer.STEERED
    except _Failed as failed:
        return failed.word
    except Exception:
        return Stop.BROKEN
    finally:
        opened.close()
