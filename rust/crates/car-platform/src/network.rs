//! Whether Windows reports this PC connected to the internet (`win/network.py`).
//!
//! One question, asked of the Network List Manager through COM - `INetworkListManager::GetConnectivity` - which
//! answers from what Windows already knows: nothing is sent, no host is named and no socket is opened, and it is
//! asked only while "Wait for an internet connection" is on. The reference reached the interface through a vtable
//! slot number (13); here it is the typed interface of the `windows` crate (D3), so the slot cannot drift.
//!
//! COM comes up multithreaded on the calling thread for the question, or is used as it is where the thread already
//! has it another way, and goes down again only if this brought it up; the interface pointer is released whatever
//! happens (it is a smart pointer here).
//!
//! `internet()` is true when Windows reports IPv4 or IPv6 internet connectivity, false when it reports neither, and
//! None when it could not be asked, which the engine takes as not asked at all.

use windows::Win32::Networking::NetworkListManager::{INetworkListManager, NetworkListManager};
use windows::Win32::System::Com::{
    CLSCTX_INPROC_SERVER, CLSCTX_LOCAL_SERVER, COINIT_MULTITHREADED, CoCreateInstance,
    CoInitializeEx, CoUninitialize,
};

pub const IPV4_INTERNET: i32 = 0x40;
pub const IPV6_INTERNET: i32 = 0x400;
/// COM is up on this thread in another mode (`RPC_E_CHANGED_MODE`).
const RPC_E_CHANGED_MODE: i32 = -2147417850;

/// NLM_CONNECTIVITY's flags as Windows reports them now, or None.
pub fn connectivity() -> Option<i32> {
    // SAFETY: COM initialisation of this thread, undone below only where this call did it.
    let started = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
    let code = started.0;
    if code != 0 && code != 1 && code != RPC_E_CHANGED_MODE {
        return None;
    }
    let answer = (|| {
        // SAFETY: the typed class and interface of the Network List Manager.
        let manager: INetworkListManager = unsafe {
            CoCreateInstance(
                &NetworkListManager,
                None,
                CLSCTX_INPROC_SERVER | CLSCTX_LOCAL_SERVER,
            )
        }
        .ok()?;
        // SAFETY: a call on a live interface.
        unsafe { manager.GetConnectivity() }
            .ok()
            .map(|flags| flags.0)
    })();
    if code == 0 || code == 1 {
        // SAFETY: balances this call's CoInitializeEx; the interface above is already dropped.
        unsafe { CoUninitialize() };
    }
    answer
}

/// True when Windows reports internet over IPv4 or IPv6, false when it reports neither, None when it could not be
/// asked.
pub fn internet() -> Option<bool> {
    connectivity().map(|flags| flags & (IPV4_INTERNET | IPV6_INTERNET) != 0)
}
