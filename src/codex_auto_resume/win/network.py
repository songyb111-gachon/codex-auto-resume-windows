"""Whether Windows reports this PC connected to the internet (v0.6.11; power.py says when it is asked).

One question, asked of the Network List Manager through COM - INetworkListManager::GetConnectivity -
which answers from what Windows already knows: nothing is sent, no host is named and no socket is
opened (C1), and it is asked only while Wait for an internet connection is on. COM comes up
multithreaded on the calling thread for the question, or is used as it is where the thread already
has it another way, and goes down again only if this brought it up; the one interface pointer is
released whatever happens.

`internet()` is True when Windows reports IPv4 or IPv6 internet connectivity, False when it reports
neither, and None when it could not be asked or did not answer - which the engine takes as not asked
at all: usage is then read, and decides, as it would without this (E1).
"""
from __future__ import annotations

import ctypes as C
import os

from .dll import GUID, library

_dll = library()

CLSID_NETWORK_LIST_MANAGER = (0xDCB00C01, 0x570F, 0x4A9B, (0x8D, 0x69, 0x19, 0x9F, 0xDB, 0xA5, 0x72, 0x3B))
IID_NETWORK_LIST_MANAGER = (0xDCB00000, 0x570F, 0x4A9B, (0x8D, 0x69, 0x19, 0x9F, 0xDB, 0xA5, 0x72, 0x3B))
IPV4_INTERNET, IPV6_INTERNET = 0x40, 0x400          # NLM_CONNECTIVITY
# GetConnectivity's place in the interface: IUnknown's three, IDispatch's four, then GetNetworks,
# GetNetwork, GetNetworkConnections, GetNetworkConnection, get_IsConnectedToInternet, get_IsConnected.
_GET_CONNECTIVITY = 13
_RELEASE = 2
_CLSCTX = 0x1 | 0x4                                  # in process, or the service's own
_COINIT_MULTITHREADED = 0
_RPC_E_CHANGED_MODE = -2147417850                    # COM is up on this thread in another mode


def _guid(parts) -> GUID:
    data1, data2, data3, data4 = parts
    value = GUID(data1, data2, data3)
    value.Data4[:] = list(data4)
    return value


def _method(pointer, slot, *arguments):
    """A COM method by its place in the vtable: `this` first, an HRESULT back."""
    table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p)))[0]
    return C.WINFUNCTYPE(C.c_long, C.c_void_p, *arguments)(table[slot])


def connectivity():
    """NLM_CONNECTIVITY's flags as Windows reports them now, or None."""
    if os.name != "nt":
        return None
    try:
        ole = _dll("ole32")
        ole.CoInitializeEx.restype, ole.CoInitializeEx.argtypes = C.c_long, [C.c_void_p, C.c_uint32]
        ole.CoUninitialize.restype, ole.CoUninitialize.argtypes = None, []
        ole.CoCreateInstance.restype = C.c_long
        ole.CoCreateInstance.argtypes = [C.POINTER(GUID), C.c_void_p, C.c_uint32, C.POINTER(GUID),
                                         C.POINTER(C.c_void_p)]
    except Exception:
        return None
    started = ole.CoInitializeEx(None, _COINIT_MULTITHREADED)
    if started not in (0, 1, _RPC_E_CHANGED_MODE):
        return None
    manager = C.c_void_p()
    try:
        if ole.CoCreateInstance(C.byref(_guid(CLSID_NETWORK_LIST_MANAGER)), None, _CLSCTX,
                                C.byref(_guid(IID_NETWORK_LIST_MANAGER)), C.byref(manager)) != 0:
            return None
        flags = C.c_int(0)
        if _method(manager, _GET_CONNECTIVITY, C.POINTER(C.c_int))(manager, C.byref(flags)) != 0:
            return None
        return flags.value
    except Exception:
        return None
    finally:
        if manager:
            try:
                _method(manager, _RELEASE)(manager)
            except Exception:
                pass
        if started in (0, 1):
            ole.CoUninitialize()


def internet():
    """True when Windows reports internet over IPv4 or IPv6, False when it reports neither, None when
    it could not be asked."""
    flags = connectivity()
    if flags is None:
        return None
    return bool(flags & (IPV4_INTERNET | IPV6_INTERNET))
