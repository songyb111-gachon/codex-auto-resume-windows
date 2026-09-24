"""The kernel objects this product opens, and what Windows has wrapped it in.

`process_context` is the one that matters: a watcher started from inside a job object that
kills on close dies when whatever opened it closes, which is how Codex ends the MCP servers
its plugins start. The rest are the handles and the integrity check every named object here
is opened through.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os

from ..domain.errors import AdapterError


NO_WINDOW = 0x08000000 if os.name == "nt" else 0


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


# The job-object limit bits `process_context` reports, and the creation flag that leaves a job.
JOB_BREAKAWAY_OK = 0x0800
JOB_SILENT_BREAKAWAY_OK = 0x1000
JOB_KILL_ON_CLOSE = 0x2000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
APPMODEL_ERROR_NO_PACKAGE = 15700


class _BasicLimits(C.Structure):
    _fields_ = [("per_process_user_time", C.c_longlong), ("per_job_user_time", C.c_longlong),
                ("flags", W.DWORD), ("minimum_working_set", C.c_size_t),
                ("maximum_working_set", C.c_size_t), ("active_process_limit", W.DWORD),
                ("affinity", C.c_size_t), ("priority_class", W.DWORD), ("scheduling_class", W.DWORD)]


class _ExtendedLimits(C.Structure):
    _fields_ = [("basic", _BasicLimits)] + [(name, C.c_ulonglong) for name in (
                    "read_operations", "write_operations", "other_operations",
                    "read_bytes", "write_bytes", "other_bytes")] + [
                (name, C.c_size_t) for name in ("process_memory_limit", "job_memory_limit",
                                                "peak_process_memory", "peak_job_memory")]


def process_context() -> dict:
    """What Windows has wrapped this process in: a job object and its limits, and a package.

    Asked by the MCP server each time Codex starts it, because a watcher the server starts
    inherits both. A job whose last handle closes with KILL_ON_JOB_CLOSE set ends every
    process still in it, so a watcher left inside the job of the Codex that started it would
    stop when that Codex closes; BREAKAWAY_OK is whether a child may leave it on request, and
    SILENT_BREAKAWAY_OK whether every child leaves it anyway. A package identity would move
    the watcher's AppData writes into the package's private copy - the home lock among them -
    which is why the home is not in AppData (tests/test_plugin.py).

    Content-free by construction: booleans, each None where Windows would not say. Only the
    immediate job is read; a job nested inside another reports its own limits.
    """
    facts = {"in_job": None, "kill_on_close": None, "breakaway_ok": None,
             "silent_breakaway_ok": None, "packaged": None}
    try:
        k = _kernel()
    except AdapterError:
        return facts
    k.GetCurrentProcess.restype = W.HANDLE
    k.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]
    k.IsProcessInJob.restype = W.BOOL
    inside = W.BOOL()
    if k.IsProcessInJob(k.GetCurrentProcess(), None, C.byref(inside)):
        facts["in_job"] = bool(inside.value)
    if facts["in_job"] is False:
        facts.update(kill_on_close=False, breakaway_ok=False, silent_breakaway_ok=False)
    elif facts["in_job"]:
        k.QueryInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD,
                                                C.POINTER(W.DWORD)]
        k.QueryInformationJobObject.restype = W.BOOL
        limits = _ExtendedLimits()
        # 9 is JobObjectExtendedLimitInformation; a NULL job is the caller's own.
        if k.QueryInformationJobObject(None, 9, C.byref(limits), C.sizeof(limits), None):
            flags = limits.basic.flags
            facts.update(kill_on_close=bool(flags & JOB_KILL_ON_CLOSE),
                         breakaway_ok=bool(flags & JOB_BREAKAWAY_OK),
                         silent_breakaway_ok=bool(flags & JOB_SILENT_BREAKAWAY_OK))
    try:
        k.GetCurrentPackageFullName.argtypes = [C.POINTER(W.UINT), W.LPWSTR]
        k.GetCurrentPackageFullName.restype = C.c_long
        length = W.UINT(0)
        facts["packaged"] = k.GetCurrentPackageFullName(C.byref(length), None) != APPMODEL_ERROR_NO_PACKAGE
    except AttributeError:
        pass
    return facts


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
