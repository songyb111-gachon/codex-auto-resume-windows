"""Windows adapter. Only documented Win32 APIs and the pinned official Codex CLI.

Writer-lock ownership is a version-pinned implementation dependency, not a public
loaded-state endpoint. Unknown ownership fails closed. No GUI or private pipe.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess as S
import threading
import time
import uuid

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
# Engine versions this tool was actually verified against end to end.
VERIFIED_VERSIONS = ("codex-cli 0.153.4",)
VERSION = VERIFIED_VERSIONS[0]
# A Codex update bumps the version string, which alone must not disable auto-resume.
# Instead of requiring equality, an unrecognised version has to prove it still offers
# the exact interface this tool drives. Anything that cannot prove it is refused.
REQUIRED_QUEUE_FLAGS = ("--thread", "--message")


class AdapterError(RuntimeError):
    """Contains only a static reason code; never raw CLI/protocol output."""


def canonical_uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("invalid_uuid")
    return value


def _kernel():
    if os.name != "nt":
        raise AdapterError("windows_required")
    k = C.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]
    k.CloseHandle.restype = W.BOOL
    k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    k.QueryFullProcessImageNameW.restype = W.BOOL
    k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
    k.GetProcessTimes.restype = W.BOOL
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k.WaitForSingleObject.restype = W.DWORD
    return k


def process_identity(pid):
    k = _kernel()
    handle = k.OpenProcess(0x101000, False, pid)  # query limited + synchronize
    if not handle:
        raise AdapterError("process_identity_unavailable")
    try:
        if k.WaitForSingleObject(handle, 0) != 258:
            raise AdapterError("process_exited")
        buf, count = C.create_unicode_buffer(32768), W.DWORD(32768)
        times = [W.FILETIME() for _ in range(4)]
        if not k.QueryFullProcessImageNameW(handle, 0, buf, C.byref(count)):
            raise AdapterError("process_path_unavailable")
        if not k.GetProcessTimes(handle, *(C.byref(t) for t in times)):
            raise AdapterError("process_time_unavailable")
        return {"pid": pid, "path": buf.value.lower(),
                "created": (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}
    finally:
        k.CloseHandle(handle)


# NOTE: no LockFileEx/byte-lock probe exists anywhere in this tool by design.
# Acquiring the thread writer lock -- even for microseconds on a momentarily free
# range -- could make the ChatGPT app's own try_lock fail. Loaded-state ownership is
# determined solely by the Restart Manager inventory in Backend.loaded().


class _UniqueProcess(C.Structure):
    _fields_ = [("pid", W.DWORD), ("created", W.FILETIME)]


class _ProcessInfo(C.Structure):
    _fields_ = [("process", _UniqueProcess), ("name", W.WCHAR * 256),
                ("service", W.WCHAR * 64), ("type", C.c_int),
                ("status", W.ULONG), ("session", W.DWORD), ("restartable", W.BOOL)]


def resource_users(path):
    """Documented Restart Manager inventory ONLY. Never shutdown/restart APIs.

    Windows creates temporary session metadata; EndSession always releases it.
    Return PID + creation time only. Resource names/content are not logged.
    """
    if os.name != "nt":
        raise AdapterError("windows_required")
    rm = C.WinDLL("rstrtmgr", use_last_error=True)
    rm.RmStartSession.argtypes = [C.POINTER(W.DWORD), W.DWORD, W.LPWSTR]
    rm.RmStartSession.restype = W.DWORD
    rm.RmRegisterResources.argtypes = [W.DWORD, W.UINT, C.POINTER(W.LPCWSTR), W.UINT,
                                      C.POINTER(_UniqueProcess), W.UINT, C.POINTER(W.LPCWSTR)]
    rm.RmRegisterResources.restype = W.DWORD
    rm.RmGetList.argtypes = [W.DWORD, C.POINTER(W.UINT), C.POINTER(W.UINT),
                           C.POINTER(_ProcessInfo), C.POINTER(W.DWORD)]
    rm.RmGetList.restype = W.DWORD
    rm.RmEndSession.argtypes = [W.DWORD]
    rm.RmEndSession.restype = W.DWORD
    session, key = W.DWORD(), C.create_unicode_buffer(33)
    if rm.RmStartSession(C.byref(session), 0, key):
        raise AdapterError("resource_session_failed")
    try:
        files = (W.LPCWSTR * 1)(str(path))
        if rm.RmRegisterResources(session, 1, files, 0, None, 0, None):
            raise AdapterError("resource_registration_failed")
        needed, count, reason = W.UINT(), W.UINT(), W.DWORD()
        result = rm.RmGetList(session, C.byref(needed), C.byref(count), None, C.byref(reason))
        if result == 0:
            return []
        for _ in range(3):
            if result != 234 or needed.value > 1024:
                raise AdapterError("resource_inventory_failed")
            array = (_ProcessInfo * needed.value)()
            count.value = needed.value
            result = rm.RmGetList(session, C.byref(needed), C.byref(count), array, C.byref(reason))
            if result == 0:
                return [{"pid": p.process.pid,
                         "created": (p.process.created.dwHighDateTime << 32) | p.process.created.dwLowDateTime}
                        for p in array[:count.value]]
        raise AdapterError("resource_inventory_unstable")
    finally:
        rm.RmEndSession(session)


_INVENTORY_PS = r"""
$ErrorActionPreference='Stop'
# Windows PowerShell 5.1 emits the console OEM code page by default; force UTF-8 so
# non-ASCII executable paths (e.g. a non-ASCII user profile) survive the round-trip.
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
@(Get-CimInstance Win32_Process -Filter "Name = 'ChatGPT.exe' OR Name = 'codex.exe'" |
 ForEach-Object { [pscustomobject]@{
 pid=[int]$_.ProcessId; parent=[int]$_.ParentProcessId; path=$_.ExecutablePath
 } }) | ConvertTo-Json -Compress
"""


def inventory():
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = S.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", _INVENTORY_PS],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=15, creationflags=NO_WINDOW, check=True, shell=False)
        rows = json.loads(result.stdout) if result.stdout.strip() else []
        return rows if isinstance(rows, list) else [rows]
    except (OSError, S.SubprocessError, ValueError):
        raise AdapterError("process_inventory_unavailable") from None


def desktop_pair(rows, codex_exe):
    """Bind the configured official engine to exactly one Windows Store app main."""
    # Under WOW64 (32-bit Python on 64-bit Windows) ProgramFiles is the (x86) directory;
    # ProgramW6432 always holds the native one, where WindowsApps actually lives.
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
    app_pattern = re.compile(re.escape(str(Path(program_files) / "WindowsApps")) +
                             r"\\OpenAI\.Codex_[0-9.]+_(x64|arm64)__2p2nqsd0c76g0\\app\\ChatGPT\.exe", re.I)
    apps = [row for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)
            and app_pattern.fullmatch(row["path"])]
    app_ids = {row["pid"] for row in apps}
    mains = [row for row in apps if row.get("parent") not in app_ids]
    if len(mains) != 1:
        raise AdapterError("desktop_main_missing_or_ambiguous")
    servers = [row for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)
               and row["path"].lower() == str(codex_exe).lower() and row.get("parent") == mains[0]["pid"]]
    if len(servers) != 1:
        raise AdapterError("desktop_server_missing_or_ambiguous")
    app = process_identity(mains[0]["pid"])
    server = process_identity(servers[0]["pid"])
    if app["path"] != mains[0]["path"].lower() or server["path"] != str(codex_exe).lower():
        raise AdapterError("process_identity_changed")
    if server["created"] < app["created"]:
        raise AdapterError("process_parent_identity_invalid")
    return {**app, "server": server}


ERROR_ALREADY_EXISTS = 183
SECURITY_MANDATORY_MEDIUM_RID = 0x2000
SYSTEM_MANDATORY_LABEL_ACE_TYPE = 0x11


def _integrity_rid(handle) -> int:
    """The mandatory integrity level of a kernel object, as the label SID's last RID.

    An object with no explicit label is Medium: that is how Windows treats it, and it is
    what an object created by this (Medium) process looks like.
    """
    advapi = C.WinDLL("advapi32", use_last_error=True)
    advapi.GetSecurityInfo.argtypes = [W.HANDLE, C.c_int, W.DWORD, C.c_void_p, C.c_void_p,
                                       C.c_void_p, C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)]
    advapi.GetSecurityInfo.restype = W.DWORD
    advapi.GetAce.argtypes = [C.c_void_p, W.DWORD, C.POINTER(C.c_void_p)]
    advapi.GetAce.restype = W.BOOL
    advapi.GetSidSubAuthorityCount.argtypes = [C.c_void_p]
    advapi.GetSidSubAuthorityCount.restype = C.POINTER(C.c_ubyte)
    advapi.GetSidSubAuthority.argtypes = [C.c_void_p, W.DWORD]
    advapi.GetSidSubAuthority.restype = C.POINTER(W.DWORD)
    kernel = _kernel()
    kernel.LocalFree.argtypes = [C.c_void_p]
    kernel.LocalFree.restype = C.c_void_p
    sacl, descriptor = C.c_void_p(), C.c_void_p()
    # SE_KERNEL_OBJECT, LABEL_SECURITY_INFORMATION
    status = advapi.GetSecurityInfo(handle, 6, 0x10, None, None, None, C.byref(sacl), C.byref(descriptor))
    if status != 0:
        raise AdapterError("object_label_unreadable")
    try:
        if not sacl.value:
            return SECURITY_MANDATORY_MEDIUM_RID
        count = C.cast(sacl.value + 4, C.POINTER(C.c_ushort))[0]   # ACL.AceCount
        for index in range(count):
            ace = C.c_void_p()
            if not advapi.GetAce(sacl, index, C.byref(ace)):
                continue
            if C.cast(ace.value, C.POINTER(C.c_ubyte))[0] != SYSTEM_MANDATORY_LABEL_ACE_TYPE:
                continue
            sid = ace.value + 8                                        # ACE_HEADER + Mask
            last = advapi.GetSidSubAuthorityCount(sid)[0] - 1
            return int(advapi.GetSidSubAuthority(sid, last)[0])
        return SECURITY_MANDATORY_MEDIUM_RID
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)


def _refuse_if_squatted(handle, existed: bool) -> None:
    """Refuse a named object that a lower-integrity process created before we did.

    The watcher's mutex and stop event have predictable names in the session namespace,
    which a low-integrity process - a browser renderer, say - is allowed to create
    objects in. The v0.6.0 security review demonstrated it with a real Low process: by
    creating the mutex first it made every status read say the watcher was running while
    none was, and blocked the real one from starting; by creating the stop event first and
    signalling it, it made a real watcher exit on start.

    Once this process has created them, a lower-integrity process cannot touch them - the
    default policy forbids writing up. So the only opening is getting there first, and
    that is detectable: the object then carries the creator's lower label. Refusing it
    turns a silent lie ("running") into an honest failure that says why. It does not
    make recovery run while the squatter is alive; nothing at this level can, and the
    alternative is a watcher controlled by a process with fewer rights than the user.
    """
    if existed and _integrity_rid(handle) < SECURITY_MANDATORY_MEDIUM_RID:
        _kernel().CloseHandle(handle)
        raise AdapterError("named_object_squatted")


class Mutex:
    """Current-session named mutex, default user DACL, unique per user + state path.

    Abandonment grants the lock; the engine must reconcile its durable dispatch
    journal before sending. No PID-file inference or force-unlocking.
    """
    def __init__(self, name: str, timeout: float = 5.0):
        identity = os.path.normcase(str(Path.home().resolve())) + "\0" + str(name)
        self.name = "Local\\codex-auto-resume-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.timeout = max(0.0, min(float(timeout), 60.0))
        self.handle = None
        self.abandoned = False

    def __enter__(self):
        k = _kernel()
        k.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
        k.CreateMutexW.restype = W.HANDLE
        self.handle = k.CreateMutexW(None, False, self.name)
        existed = C.get_last_error() == ERROR_ALREADY_EXISTS
        if not self.handle:
            raise AdapterError("mutex_creation_failed")
        try:
            _refuse_if_squatted(self.handle, existed)
        except AdapterError:
            self.handle = None
            raise
        result = k.WaitForSingleObject(self.handle, int(self.timeout * 1000))
        if result not in (0, 128):
            k.CloseHandle(self.handle)
            self.handle = None
            raise AdapterError("mutex_busy" if result == 258 else "mutex_wait_failed")
        self.abandoned = result == 128
        return self

    def __exit__(self, *unused):
        if self.handle is not None:
            k = _kernel()
            k.ReleaseMutex.argtypes = [W.HANDLE]
            k.ReleaseMutex.restype = W.BOOL
            k.ReleaseMutex(self.handle)
            k.CloseHandle(self.handle)
            self.handle = None


class StopEvent:
    """Manual-reset named event so `stop` can wake the watcher without killing it."""

    def __init__(self, name: str):
        identity = os.path.normcase(str(Path.home().resolve())) + "::stop::" + str(name)
        self.name = "Local\\codex-auto-resume-stop-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.handle = None

    @staticmethod
    def _api():
        k = _kernel()
        k.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]
        k.CreateEventW.restype = W.HANDLE
        k.OpenEventW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
        k.OpenEventW.restype = W.HANDLE
        k.SetEvent.argtypes = [W.HANDLE]
        k.SetEvent.restype = W.BOOL
        k.ResetEvent.argtypes = [W.HANDLE]
        k.ResetEvent.restype = W.BOOL
        return k

    def __enter__(self):
        k = self._api()
        self.handle = k.CreateEventW(None, True, False, self.name)
        existed = C.get_last_error() == ERROR_ALREADY_EXISTS
        if not self.handle:
            raise AdapterError("stop_event_creation_failed")
        try:
            _refuse_if_squatted(self.handle, existed)
        except AdapterError:
            self.handle = None
            raise
        k.ResetEvent(self.handle)  # a stale signal must not stop a fresh watcher
        return self

    def wait(self, seconds: float) -> bool:
        """True when a stop was requested; False after the timeout elapsed."""
        k = self._api()
        millis = int(max(0.0, min(float(seconds), 3600.0)) * 1000)
        return k.WaitForSingleObject(self.handle, millis) == 0

    def __exit__(self, *unused):
        if self.handle is not None:
            _kernel().CloseHandle(self.handle)
            self.handle = None

    def signal(self) -> bool:
        """Signal a running watcher. False when no watcher currently holds the event."""
        k = self._api()
        handle = k.OpenEventW(0x0002, False, self.name)  # EVENT_MODIFY_STATE
        if not handle:
            return False
        try:
            return bool(k.SetEvent(handle))
        finally:
            k.CloseHandle(handle)


class WakeEvent:
    """Auto-reset named event: "look now", sent by Retry Now.

    Only the watcher creates it, and it refuses one a lower-integrity process created
    first, exactly like the stop event. A client can only open it and set it. It is
    never an instruction to send: a wake runs the ordinary tick, every gate included,
    and the stored schedule stays the authority, so a lost wake only delays.
    """

    def __init__(self, name: str):
        identity = os.path.normcase(str(Path.home().resolve())) + "::wake::" + str(name)
        self.name = "Local\\codex-auto-resume-wake-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.handle = None

    def __enter__(self):
        k = StopEvent._api()
        self.handle = k.CreateEventW(None, False, False, self.name)
        existed = C.get_last_error() == ERROR_ALREADY_EXISTS
        if not self.handle:
            raise AdapterError("wake_event_creation_failed")
        try:
            _refuse_if_squatted(self.handle, existed)
        except AdapterError:
            self.handle = None
            raise
        return self

    def __exit__(self, *unused):
        if self.handle is not None:
            _kernel().CloseHandle(self.handle)
            self.handle = None

    def signal(self) -> bool:
        """Ask a running watcher to look now. False when none holds the event."""
        k = StopEvent._api()
        handle = k.OpenEventW(0x0002, False, self.name)  # EVENT_MODIFY_STATE
        if not handle:
            return False
        try:
            return bool(k.SetEvent(handle))
        finally:
            k.CloseHandle(handle)


def wait_any(handles, seconds: float):
    """Wait on several events. Returns the index of the one signalled, or None on timeout."""
    live = [handle for handle in handles if handle]
    if not live:
        time.sleep(max(0.0, min(float(seconds), 3600.0)))
        return None
    k = _kernel()
    k.WaitForMultipleObjects.argtypes = [W.DWORD, C.POINTER(W.HANDLE), W.BOOL, W.DWORD]
    k.WaitForMultipleObjects.restype = W.DWORD
    array = (W.HANDLE * len(live))(*live)
    millis = int(max(0.0, min(float(seconds), 3600.0)) * 1000)
    result = k.WaitForMultipleObjects(len(live), array, False, millis)
    if result < len(live):
        return handles.index(live[result])
    return None


class HomeLock:
    """An exclusive lock, for the watcher's whole life, on our own file for one Codex home.

    The single-instance mutex is per state directory and per logon session. Two
    installations with different state directories - or one in another session of the
    same user - could otherwise both recover the same Codex conversations. The file is
    ours, under the user's local application data, never anything of Codex's.
    """

    def __init__(self, codex_home, base=None):
        resolved = os.path.normcase(str(Path(codex_home).resolve()))
        root = Path(base) if base else Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "codex-auto-resume" / "homes"
        self.path = root / (hashlib.sha256(resolved.encode("utf-8")).hexdigest() + ".lock")
        self._fd = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def __enter__(self):
        import msvcrt
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            raise AdapterError("home_lock_unavailable") from None
        try:
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            raise AdapterError("home_lock_busy") from None
        self._fd = fd
        return self

    def __exit__(self, *unused):
        if self._fd is not None:
            import msvcrt
            try:
                os.lseek(self._fd, 0, 0)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            os.close(self._fd)
            self._fd = None


def _epoch(value):
    return value if type(value) is int and 0 < value <= 4102444800 else None


def parse_usage(value):
    """Allowlist numeric usage fields. Never retain account IDs, banners or credits."""
    unknown = {"available": None, "reset_at": None, "limit_type": "unknown", "reason": "usage_snapshot_unknown"}
    if not isinstance(value, dict):
        return unknown
    buckets = value.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        legacy = value.get("rateLimits")
        buckets = {"legacy": legacy} if isinstance(legacy, dict) else {}
    windows, blocked, spending, explicit_limit = [], [], False, False
    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            return unknown
        safe_id = bucket_id if bucket_id in ("codex", "premium", "legacy") else "other"
        spending |= bucket.get("spendControlReached") is True
        explicit_limit |= bucket.get("rateLimitReachedType") == "rate_limit_reached"
        if bucket.get("rateLimitReachedType") in (
                "workspace_owner_credits_depleted", "workspace_member_credits_depleted",
                "workspace_owner_usage_limit_reached", "workspace_member_usage_limit_reached"):
            spending = True
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if window is None:
                continue
            if not isinstance(window, dict):
                return unknown
            used = window.get("usedPercent")
            if type(used) not in (int, float) or not math.isfinite(used) or used < 0:
                return unknown
            duration = window.get("windowDurationMins")
            if duration is not None and (type(duration) is not int or duration <= 0):
                return unknown
            if window.get("resetsAt") is not None and _epoch(window["resetsAt"]) is None:
                return unknown
            entry = {"bucket": safe_id, "window": slot, "used_percent": used,
                     "window_minutes": duration, "reset_at": _epoch(window.get("resetsAt"))}
            windows.append(entry)
            if used >= 100:
                blocked.append(entry)
    if spending:
        return {"available": False, "reset_at": None, "limit_type": "spend_or_credits",
                "reason": "account_spend_or_credit_block", "windows": windows}
    if blocked:
        resets = [window["reset_at"] for window in blocked]
        reset = max(resets) if all(x is not None for x in resets) else None
        return {"available": False, "reset_at": reset,
                "limit_type": ",".join(sorted(set(str(w["window_minutes"] or "unknown") + "m" for w in blocked))),
                "reason": "one_or_more_exposed_windows_exhausted_blocking_bucket_not_attributed", "windows": windows}
    if explicit_limit:
        return {"available": False, "reset_at": None, "limit_type": "unattributed",
                "reason": "server_reports_rate_limit_reached", "windows": windows}
    if windows:
        return {"available": True, "reset_at": None, "limit_type": "exposed_windows",
                "reason": "exposed_windows_available_specific_model_bucket_not_guaranteed", "windows": windows}
    return unknown


class Protocol:
    """Finite separate stdio server: reads usage or deletes one owned queue item.

    Never attaches to desktop server, loads a thread, starts a turn, authenticates
    by a custom route or services server requests. Official binary owns auth.
    """
    def __init__(self, backend):
        self.backend = backend
        self.process = None
        self.sequence = 0
        self.responses = queue.Queue(maxsize=64)
        self.write_lock = threading.Lock()

    def __enter__(self):
        self.backend._compatible()
        try:
            self.process = S.Popen(self.backend._argv() + ["app-server", "--stdio"],
                                   stdin=S.PIPE, stdout=S.PIPE, stderr=S.DEVNULL, text=True,
                                   encoding="utf-8", errors="replace", bufsize=1,
                                   creationflags=NO_WINDOW, close_fds=True, shell=False,
                                   cwd=str(self.backend.codex_home), env=self.backend._environment())
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            # Codex reports clientInfo to OpenAI as the client's identity, so it should be
            # true: this product's real version, read from the manifest like every other
            # version it displays. It said "0.1" for six releases.
            from .config import version as product_version
            response = self.call("initialize", {"clientInfo": {"name": "codex_auto_resume",
                                                               "version": product_version()},
                                                "capabilities": {"experimentalApi": True}})
            if not isinstance(response, dict) or Path(response.get("codexHome", "")).resolve() != self.backend.codex_home:
                raise AdapterError("protocol_home_mismatch")
            if response.get("platformOs") != "windows":
                raise AdapterError("protocol_platform_mismatch")
            self._write({"method": "initialized"})
            return self
        except BaseException:
            self.__exit__()
            raise

    def _write(self, payload):
        with self.write_lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(1024 * 1024 + 1)
                if not line or len(line) > 1024 * 1024:
                    return
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(value, dict):
                    continue
                if "id" in value and "method" in value:
                    self._write({"id": value["id"], "error": {"code": -32601, "message": "Client requests unsupported"}})
                elif "id" in value and ("result" in value or "error" in value):
                    try:
                        self.responses.put_nowait(value)
                    except queue.Full:
                        return
        except (OSError, ValueError):
            return

    def call(self, method, params=None):
        if method not in ("initialize", "account/rateLimits/read", "thread/queue/delete"):
            raise AdapterError("protocol_method_not_allowed")
        self.sequence += 1
        sequence = self.sequence
        request = {"id": sequence, "method": method}
        if params is not None:
            request["params"] = params
        try:
            self._write(request)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                response = self.responses.get(timeout=max(0.01, deadline - time.monotonic()))
                if response.get("id") != sequence:
                    continue
                if "error" in response:
                    raise AdapterError("protocol_request_failed")
                return response.get("result")
        except (queue.Empty, OSError, ValueError):
            raise AdapterError("protocol_unavailable") from None
        raise AdapterError("protocol_timeout")

    def __exit__(self, *unused):
        process = self.process
        if process is None:
            return
        try:
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=4)
            except S.TimeoutExpired:
                process.terminate()  # only our own finite helper
                process.wait(timeout=4)
        finally:
            if hasattr(self, "reader"):
                self.reader.join(timeout=1)
            if process.stdout:
                process.stdout.close()


class Backend:
    def __init__(self, codex_home: Path, codex_exe: Path):
        self.codex_home = Path(codex_home).resolve()
        self.codex_exe = Path(codex_exe).resolve()
        self._version_signature = None
        self.engine_version = None
        self.engine_verified = False

    def _environment(self):
        env = os.environ.copy()
        env["CODEX_HOME"] = str(self.codex_home)
        # The binary reuses its own authenticated context; Python reads no auth file.
        env["OTEL_SDK_DISABLED"] = "true"
        return env

    def _argv(self):
        return [str(self.codex_exe), "-c", "analytics.enabled=false",
                "-c", 'otel.exporter="none"', "-c", 'otel.trace_exporter="none"',
                "-c", 'otel.metrics_exporter="none"', "-c", "otel.log_user_prompt=false",
                "-c", 'chatgpt_base_url="https://chatgpt.com/backend-api/"']

    def _queue_interface_ok(self):
        """Prove `codex queue` still takes the exact flags we drive it with."""
        result = S.run([str(self.codex_exe), "queue", "--help"], stdout=S.PIPE, stderr=S.DEVNULL,
                       text=True, encoding="utf-8", errors="replace", timeout=20,
                       creationflags=NO_WINDOW, shell=False, env=self._environment())
        if result.returncode != 0:
            return False
        text = result.stdout
        return all(flag in text for flag in REQUIRED_QUEUE_FLAGS)

    def _compatible(self):
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
        expected = re.compile(re.escape(str(local)) + r"\\[0-9a-f]+\\codex\.exe", re.I)
        if not expected.fullmatch(str(self.codex_exe)):
            raise AdapterError("unsupported_codex_location")
        try:
            stat = self.codex_exe.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            if signature == self._version_signature:
                return
            result = S.run([str(self.codex_exe), "--version"], stdout=S.PIPE, stderr=S.DEVNULL,
                           text=True, encoding="utf-8", timeout=10, creationflags=NO_WINDOW,
                           shell=False, env=self._environment())
            if result.returncode != 0:
                raise AdapterError("codex_binary_unavailable")
            version = result.stdout.strip()
            if version in VERIFIED_VERSIONS:
                self.engine_version, self.engine_verified = version, True
            elif self._queue_interface_ok():
                # Structurally compatible but not a version we have exercised end to end.
                # Allowed so an app update does not silently stop auto-resume, and every
                # send is still proven afterwards by the per-interruption marker.
                self.engine_version, self.engine_verified = version, False
            else:
                raise AdapterError("unsupported_codex_version")
            self._version_signature = signature
        except (OSError, S.SubprocessError):
            raise AdapterError("codex_binary_unavailable") from None

    def app_identity(self):
        try:
            self._compatible()
            return desktop_pair(inventory(), self.codex_exe)
        except (AdapterError, OSError, KeyError, TypeError):
            return None

    def loaded(self, thread_id, app_identity):
        try:
            canonical_uuid(thread_id)
            self._compatible()
            if not app_identity or self.app_identity() != app_identity:
                return "unknown"
            path = self.codex_home / "thread-writer-locks" / (thread_id + ".lock")
            # Identify who holds the lock file OPEN via Restart Manager first. This never
            # acquires a byte lock, so it cannot race the app's own exclusive writer lock.
            # An empty inventory (absent file, or a stale file no process holds) is notLoaded.
            users = resource_users(path)
            if not users:
                return "notLoaded"
            expected = {key: app_identity["server"][key] for key in ("pid", "created")}
            # Exactly the app's own Codex server holds it, and app identity is stable.
            # A CLI-owned writer, missing identity or ambiguity fails closed.
            #
            # Ownership is decided PURELY by Restart Manager: the upstream writer lock
            # guard holds the file open for exactly as long as it holds the byte lock
            # (it closes and deletes the file on drop), so "the app server has this file
            # open" already means "the app server holds the writer lock". We deliberately
            # do NOT probe with LockFileEx: on a momentarily free range that call would
            # ACQUIRE the app's own exclusive lock and could make the app's try_lock fail.
            if users != [expected] or self.app_identity() != app_identity:
                return "unknown"
            return "loaded"
        except (AdapterError, ValueError, OSError, KeyError, TypeError):
            return "unknown"

    def usage(self):
        try:
            with Protocol(self) as client:
                return parse_usage(client.call("account/rateLimits/read"))
        except (AdapterError, OSError, S.SubprocessError, ValueError):
            return {"available": None, "reset_at": None, "limit_type": "unknown", "reason": "usage_probe_unavailable"}

    def send(self, thread_id, prompt):
        """Only spawn failure permits retry. Every post-spawn uncertainty is terminal."""
        try:
            canonical_uuid(thread_id)
            if not isinstance(prompt, str) or not prompt or len(prompt) > 8192 or "\0" in prompt:
                raise ValueError("invalid_prompt")
            self._compatible()
        except (AdapterError, ValueError):
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        try:
            process = S.Popen(self._argv() + ["queue", "--thread", thread_id, "--message", prompt],
                              stdin=S.DEVNULL, stdout=S.PIPE, stderr=S.DEVNULL, text=True,
                              encoding="utf-8", errors="replace", shell=False, close_fds=True,
                              creationflags=NO_WINDOW, cwd=str(self.codex_home), env=self._environment())
        except OSError:
            return {"outcome": "not_started", "error_code": "queue_spawn_failed"}
        try:
            stdout, _ = process.communicate(timeout=45)
            match = re.fullmatch(r"Queued message ([0-9a-f-]{36}) for thread " + re.escape(thread_id) + r"\.", stdout.strip())
            if process.returncode == 0 and match:
                queue_id = canonical_uuid(match.group(1))
                return {"outcome": "accepted", "queue_id": queue_id}
            return {"outcome": "unknown", "error_code": "queue_response_unconfirmed"}
        except S.TimeoutExpired:
            try:
                process.kill()  # only this helper; accepted delivery is still possible
                process.communicate(timeout=5)
            except (OSError, S.SubprocessError):
                pass
            return {"outcome": "unknown", "error_code": "queue_timeout"}
        except (OSError, ValueError, S.SubprocessError):
            return {"outcome": "unknown", "error_code": "queue_result_unknown"}
        finally:
            if process.stdout:
                process.stdout.close()

    def delete_queue(self, thread_id, queue_id):
        try:
            canonical_uuid(thread_id)
            canonical_uuid(queue_id)
            with Protocol(self) as client:
                result = client.call("thread/queue/delete", {"threadId": thread_id, "queuedSubmissionId": queue_id})
            return isinstance(result, dict) and result.get("deleted") is True
        except (AdapterError, ValueError, OSError, S.SubprocessError):
            return False
