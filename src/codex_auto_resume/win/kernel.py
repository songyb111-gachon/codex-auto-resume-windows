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
import re

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



# ------------------------------------------------------------------ inside another app (v0.6.17)
# gui/HostApp.cs's walk, asked of a process by Diagnostics: whether it descends from a live MSIX app - the Codex app
# (OpenAI.Codex), Claude desktop - whose private view of Windows takes what it registers (HKCU, %APPDATA%), and whose
# closing may end it. The same guards as HostApp.Decide, held to the same answers by the tests: each parent from one
# Toolhelp snapshot; a parent created after its child is not its parent (its id was reused); a parent that cannot be
# opened, a cycle and HOST_MAX_STEPS end the walk, outside. Only the package family name leaves: never a path.
HOST_MAX_STEPS = 32
TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# A package family name as Windows writes one: the package's name, "_", and the publisher's 13-letter id.
_FAMILY = re.compile(r"[A-Za-z0-9.\-]{1,64}_[a-z0-9]{13}\Z")
# Where the answer is the start process's own: inside an app (its family), outside every one, or not to be had.
INSIDE, OUTSIDE, UNKNOWN = "inside", "outside", "unknown"
# 100-ns intervals between 1601-01-01 (FILETIME) and 1970-01-01 (the epoch).
_EPOCH_AS_FILETIME = 116444736000000000


class _ProcessEntry(C.Structure):
    _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("pid", W.DWORD), ("heap", C.c_size_t),
                ("module", W.DWORD), ("threads", W.DWORD), ("parent", W.DWORD), ("priority", C.c_long),
                ("flags", W.DWORD), ("exe", W.WCHAR * 260)]


def decide_host(start, table):
    """The package family name of `start`, or of its nearest live ancestor that has one, or None.

    `table` maps a process id to (parent id, creation FILETIME - 0 where it could not be opened - and package family
    name or None). HostApp.Decide, line for line: pure, so a test feeds it a table of its own."""
    row = (table or {}).get(start)
    if row is None:
        return None
    if row[2] is not None:
        return row[2]
    seen = {start}
    for _step in range(HOST_MAX_STEPS):
        parent = table.get(row[0])
        if parent is None or parent[1] == 0:
            return None
        if row[0] in seen:
            return None
        seen.add(row[0])
        if parent[1] > row[1]:
            return None
        if parent[2] is not None:
            return parent[2]
        row = parent
    return None


def app_name(family) -> str:
    """The app's name for a person: the family name without its publisher id ("OpenAI.Codex"). HostApp.Name."""
    if not family:
        return ""
    cut = family.rfind("_")
    return family[:cut] if cut > 0 else family


def _toolhelp_parents(k) -> dict:
    """Every process's parent id, from one Toolhelp snapshot."""
    k.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    k.CreateToolhelp32Snapshot.restype = W.HANDLE
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [W.HANDLE, C.POINTER(_ProcessEntry)]
    k.Process32FirstW.restype = k.Process32NextW.restype = W.BOOL
    snapshot = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == W.HANDLE(-1).value:
        return {}
    parents = {}
    try:
        entry = _ProcessEntry()
        entry.size = C.sizeof(_ProcessEntry)
        more = k.Process32FirstW(snapshot, C.byref(entry))
        while more:
            parents[int(entry.pid)] = int(entry.parent)
            more = k.Process32NextW(snapshot, C.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    return parents


def _opened(k, pid, own) -> tuple:
    """(creation FILETIME, package family name or None) of one process: (0, None) where it cannot be opened."""
    handle = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0, None
    try:
        times = [W.FILETIME() for _ in range(4)]
        created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                   if k.GetProcessTimes(handle, *(C.byref(t) for t in times)) else 0)
        family = None
        try:
            name, length = C.create_unicode_buffer(256), W.UINT(256)
            if own:
                k.GetCurrentPackageFamilyName.argtypes = [C.POINTER(W.UINT), W.LPWSTR]
                k.GetCurrentPackageFamilyName.restype = C.c_long
                answer = k.GetCurrentPackageFamilyName(C.byref(length), name)
            else:
                k.GetPackageFamilyName.argtypes = [W.HANDLE, C.POINTER(W.UINT), W.LPWSTR]
                k.GetPackageFamilyName.restype = C.c_long
                answer = k.GetPackageFamilyName(handle, C.byref(length), name)
            if answer == 0 and name.value:
                family = name.value
        except AttributeError:
            pass                                    # a Windows with no packages at all
        return created, family
    finally:
        k.CloseHandle(handle)


def _host_table(k, start) -> dict:
    """`start` and its ancestors as the walk sees them, as HostApp.LiveTable gathers them."""
    parents = _toolhelp_parents(k)
    own = os.getpid()
    table, pid = {}, start
    for _step in range(HOST_MAX_STEPS + 2):
        if pid in table or pid not in parents:
            break
        created, family = _opened(k, pid, pid == own)
        table[pid] = (parents[pid], created, family)
        if created == 0:
            break
        pid = parents[pid]
    return table


def host_verdict(start, table, started_by=None) -> dict:
    """{"state", "family", "app"} for the process `start` over `table`: INSIDE with the app's family name and name,
    OUTSIDE, or UNKNOWN where `start` itself is not in the table or could not be opened - or, given `started_by` (the
    epoch second the process says it started, the watcher's heartbeat), was created after it: its id now belongs to
    another process. A family name that is not one is said as no name. Pure."""
    row = (table or {}).get(start)
    if row is None or row[1] == 0:
        return {"state": UNKNOWN, "family": None, "app": None}
    if started_by is not None and (row[1] - _EPOCH_AS_FILETIME) / 1e7 > started_by + 2:
        return {"state": UNKNOWN, "family": None, "app": None}
    family = decide_host(start, table)
    if family is None:
        return {"state": OUTSIDE, "family": None, "app": None}
    family = family if _FAMILY.match(family) else None
    return {"state": INSIDE, "family": family, "app": app_name(family) or None}


def host_app(pid=None, started_by=None) -> dict:
    """Whether the process `pid` - this one when None - runs inside another app's private view, and which:
    host_verdict over the live process table. Never raises: UNKNOWN where Windows would not say."""
    start = os.getpid() if pid is None else pid
    try:
        k = _kernel()
        return host_verdict(start, _host_table(k, start), started_by)
    except Exception:
        return {"state": UNKNOWN, "family": None, "app": None}


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
    if existed and (_integrity_rid(handle) < SECURITY_MANDATORY_MEDIUM_RID
                    or not trusted_owner(_owner_sid(handle), _user_sid())):
        _kernel().CloseHandle(handle)
        raise AdapterError("named_object_squatted")


# Owners an existing object may have and still be this account's own (v0.6.18, security M2): this
# account, and the two that only someone with more rights than it can set - the computer's
# administrators, which an elevated process of this account makes its objects with, and Windows itself.
TRUSTED_OWNERS = frozenset({"S-1-5-32-544", "S-1-5-18"})


def trusted_owner(owner: str | None, user: str | None) -> bool:
    """Whether a named object whose owner is `owner` was made by this account `user` (or by someone
    with more rights). Another account of the same integrity - a sandbox account Codex runs commands
    under in this session, say - can create the same predictable name first with a DACL that lets it
    signal or hold the object later; its owner then is that account. An owner or user that could not
    be read is not trusted. Pure."""
    if not owner or not user:
        return False
    return owner == user or owner in TRUSTED_OWNERS


def _owner_sid(handle) -> str | None:
    """The owner of a kernel object, as SID text; None where Windows would not say."""
    advapi = C.WinDLL("advapi32", use_last_error=True)
    advapi.GetSecurityInfo.argtypes = [W.HANDLE, C.c_int, W.DWORD, C.POINTER(C.c_void_p), C.c_void_p,
                                       C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p)]
    advapi.GetSecurityInfo.restype = W.DWORD
    owner, descriptor = C.c_void_p(), C.c_void_p()
    # SE_KERNEL_OBJECT, OWNER_SECURITY_INFORMATION
    if advapi.GetSecurityInfo(handle, 6, 0x1, C.byref(owner), None, None, None, C.byref(descriptor)) != 0:
        return None
    try:
        return _sid_text(advapi, owner.value) if owner.value else None
    finally:
        if descriptor.value:
            _local_free(descriptor)


def _user_sid() -> str | None:
    """This account's SID text, from this process's own token (TokenUser); None where it is unreadable."""
    advapi = C.WinDLL("advapi32", use_last_error=True)
    advapi.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    advapi.GetTokenInformation.restype = W.BOOL
    token = W.HANDLE(-4)                     # GetCurrentProcessToken(): a pseudo-handle, never closed
    needed = W.DWORD(0)
    advapi.GetTokenInformation(token, 1, None, 0, C.byref(needed))
    if not needed.value or needed.value > 4096:
        return None
    buffer = C.create_string_buffer(needed.value)
    if not advapi.GetTokenInformation(token, 1, buffer, needed, C.byref(needed)):
        return None
    return _sid_text(advapi, C.c_void_p.from_buffer(buffer).value)


def _sid_text(advapi, sid) -> str | None:
    advapi.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = W.BOOL
    text = W.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, C.byref(text)):
        return None
    try:
        return text.value
    finally:
        _local_free(text)


def _local_free(pointer) -> None:
    k = _kernel()
    k.LocalFree.argtypes = [C.c_void_p]
    k.LocalFree.restype = C.c_void_p
    k.LocalFree(pointer)
