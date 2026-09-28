"""Who Windows lets open the state folder (v0.6.11, Diagnostics).

One documented Win32 question, asked only when Diagnostics is shown: the folder's access list
(GetNamedSecurityInfoW, the DACL only), read and never written. Each entry that lets someone in is
compared with the few that are expected there - this account, Windows itself (SYSTEM), the
computer's administrators and CREATOR OWNER, which Windows turns into the account that made a file -
and an app's own sandbox (S-1-15-...), which runs as this account and is no other person. Anyone
else - another account, Users, Everyone, Authenticated Users - means other accounts on this PC can
open the folder where the settings, the pending tasks and the logs are kept.

Only the verdict leaves this module (`verdict`): no security identifier, no account name and no
path is kept or returned. The account's own identifier is read from this process's own token
(TokenUser) to be compared, and dropped. Nothing here raises: what cannot be read is UNKNOWN.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os

from ..domain.vocabulary import StateAccess
from .dll import library

SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x4
TOKEN_USER = 1
ACL_SIZE_INFORMATION = 2
ACCESS_ALLOWED_ACE_TYPE = 0x0
ACCESS_DENIED_ACE_TYPE = 0x1
# GetCurrentProcessToken(): a pseudo-handle that needs no opening or closing, and can only be asked.
_CURRENT_PROCESS_TOKEN = -4
# Windows itself, the administrators, and CREATOR OWNER - the three expected beside this account -
# and the prefix of an app sandbox's package and capability identifiers, which are not accounts.
EXPECTED = frozenset({"S-1-5-18", "S-1-5-32-544", "S-1-3-0"})
# The three answers, in the order Diagnostics has words for them.
STATE_ACCESS = tuple(StateAccess)
SANDBOX = "S-1-15-"

_dll = library()


class _AceHeader(C.Structure):
    _fields_ = [("AceType", C.c_ubyte), ("AceFlags", C.c_ubyte), ("AceSize", W.WORD)]


class _AllowedAce(C.Structure):
    """ACCESS_ALLOWED_ACE: its header, its mask, and the SID that starts at SidStart."""
    _fields_ = [("Header", _AceHeader), ("Mask", W.DWORD), ("SidStart", W.DWORD)]


class _AclSize(C.Structure):
    _fields_ = [("AceCount", W.DWORD), ("AclBytesInUse", W.DWORD), ("AclBytesFree", W.DWORD)]


def _call(dll, name, result, *arguments):
    function = getattr(_dll(dll), name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


def _sid_text(sid) -> str | None:
    text = W.LPWSTR()
    if not _call("advapi32", "ConvertSidToStringSidW", W.BOOL, C.c_void_p, C.POINTER(W.LPWSTR))(sid, C.byref(text)):
        return None
    try:
        return text.value
    finally:
        _call("kernel32", "LocalFree", C.c_void_p, C.c_void_p)(text)


def _own_sid() -> str | None:
    """This account's security identifier, as text, from this process's own token."""
    needed = W.DWORD(0)
    asked = _call("advapi32", "GetTokenInformation", W.BOOL, W.HANDLE, C.c_int, C.c_void_p, W.DWORD,
                  C.POINTER(W.DWORD))
    asked(W.HANDLE(_CURRENT_PROCESS_TOKEN), TOKEN_USER, None, 0, C.byref(needed))
    if not needed.value or needed.value > 4096:
        return None
    buffer = C.create_string_buffer(needed.value)
    if not asked(W.HANDLE(_CURRENT_PROCESS_TOKEN), TOKEN_USER, buffer, needed, C.byref(needed)):
        return None
    # TOKEN_USER begins with SID_AND_ATTRIBUTES, whose first field is the SID's address.
    return _sid_text(C.c_void_p.from_buffer(buffer).value)


def allowed_sids(path) -> list | None:
    """The identifiers each entry of the folder's access list that lets someone in names, as text -
    or None when the list cannot be read. An empty list is a folder nobody may open; a missing list
    (a NULL DACL) lets everyone in, and is ["S-1-1-0"], Everyone's."""
    descriptor, dacl = C.c_void_p(), C.c_void_p()
    asked = _call("advapi32", "GetNamedSecurityInfoW", W.DWORD, W.LPCWSTR, C.c_int, W.DWORD, C.c_void_p,
                  C.c_void_p, C.POINTER(C.c_void_p), C.c_void_p, C.POINTER(C.c_void_p))
    if asked(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, C.byref(dacl), None,
             C.byref(descriptor)) != 0:
        return None
    try:
        if not dacl.value:
            return ["S-1-1-0"]
        size = _AclSize()
        if not _call("advapi32", "GetAclInformation", W.BOOL, C.c_void_p, C.c_void_p, W.DWORD, C.c_int)(
                dacl, C.byref(size), C.sizeof(size), ACL_SIZE_INFORMATION):
            return None
        get_ace = _call("advapi32", "GetAce", W.BOOL, C.c_void_p, W.DWORD, C.POINTER(C.c_void_p))
        found = []
        for index in range(min(size.AceCount, 1024)):
            ace = C.c_void_p()
            if not get_ace(dacl, index, C.byref(ace)):
                return None
            header = _AceHeader.from_address(ace.value)
            if header.AceType == ACCESS_DENIED_ACE_TYPE:
                continue                        # a refusal lets no one in
            if header.AceType != ACCESS_ALLOWED_ACE_TYPE:
                return None                     # a kind this does not read: unknown, never "only you"
            allowed = _AllowedAce.from_address(ace.value)
            if not allowed.Mask:
                continue
            text = _sid_text(ace.value + _AllowedAce.SidStart.offset)
            if text is None:
                return None
            found.append(text)
        return found
    finally:
        _call("kernel32", "LocalFree", C.c_void_p, C.c_void_p)(descriptor)


def verdict(allowed, own) -> str:
    """OWNER_ONLY, SHARED or UNKNOWN for the identifiers an access list lets in and this account's.
    Pure: the rule, apart from the asking."""
    if allowed is None or not own:
        return StateAccess.UNKNOWN.value
    others = [sid for sid in allowed if sid != own and sid not in EXPECTED and not sid.startswith(SANDBOX)]
    return StateAccess.SHARED.value if others else StateAccess.OWNER_ONLY.value


def state_access(path) -> str:
    """Who may open the folder at `path`: OWNER_ONLY, SHARED or UNKNOWN. Never raises."""
    if os.name != "nt":
        return StateAccess.UNKNOWN.value
    try:
        return verdict(allowed_sids(path), _own_sid())
    except Exception:
        return StateAccess.UNKNOWN.value
