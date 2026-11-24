//! The Restart Manager, read and never used to restart anything (`win/inventory.py`).
//!
//! It answers one question - which processes hold a file open - and this product only ever asks it. Nothing here
//! shuts down, restarts or registers a restart.

use windows::Win32::Foundation::{ERROR_MORE_DATA, WIN32_ERROR};
use windows::Win32::System::RestartManager::{
    CCH_RM_SESSION_KEY, RM_PROCESS_INFO, RmEndSession, RmGetList, RmRegisterResources,
    RmStartSession,
};
use windows::core::{PCWSTR, PWSTR};

use crate::paths::wide;
use car_machine::domain::errors::AdapterError;

/// A process that holds a resource: its id and creation FILETIME. Only these leave; names and content are not kept.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Holder {
    pub pid: u32,
    pub created: u64,
}

/// Documented Restart Manager inventory ONLY. Never shutdown/restart APIs. Windows creates temporary session
/// metadata; `RmEndSession` always releases it. With several paths, all are registered in the one session, and the
/// answer is every process holding any of them, each once.
pub fn resource_users(paths: &[&str]) -> Result<Vec<Holder>, AdapterError> {
    let mut session = 0u32;
    let mut key = vec![0u16; CCH_RM_SESSION_KEY as usize + 1];
    // SAFETY: out values of our own.
    if unsafe { RmStartSession(&mut session, None, PWSTR(key.as_mut_ptr())) } != WIN32_ERROR(0) {
        return Err(AdapterError("resource_session_failed"));
    }
    let result = (|| {
        let names: Vec<Vec<u16>> = paths.iter().map(|path| wide(path)).collect();
        let files: Vec<PCWSTR> = names.iter().map(|name| PCWSTR(name.as_ptr())).collect();
        // SAFETY: NUL-terminated names that outlive the call.
        if unsafe { RmRegisterResources(session, Some(&files), None, None) } != WIN32_ERROR(0) {
            return Err(AdapterError("resource_registration_failed"));
        }
        let (mut needed, mut count, mut reason) = (0u32, 0u32, 0u32);
        // SAFETY: the first call only asks how many.
        let mut answer = unsafe { RmGetList(session, &mut needed, &mut count, None, &mut reason) };
        if answer == WIN32_ERROR(0) {
            return Ok(Vec::new());
        }
        for _ in 0..3 {
            if answer != ERROR_MORE_DATA || needed > 1024 {
                return Err(AdapterError("resource_inventory_failed"));
            }
            let mut array = vec![RM_PROCESS_INFO::default(); needed as usize];
            count = needed;
            // SAFETY: an array as long as `count` says.
            answer = unsafe {
                RmGetList(
                    session,
                    &mut needed,
                    &mut count,
                    Some(array.as_mut_ptr()),
                    &mut reason,
                )
            };
            if answer == WIN32_ERROR(0) {
                return Ok(array[..count as usize]
                    .iter()
                    .map(|info| Holder {
                        pid: info.Process.dwProcessId,
                        created: (u64::from(info.Process.ProcessStartTime.dwHighDateTime) << 32)
                            | u64::from(info.Process.ProcessStartTime.dwLowDateTime),
                    })
                    .collect());
            }
        }
        Err(AdapterError("resource_inventory_unstable"))
    })();
    // SAFETY: the session started above, always ended.
    unsafe {
        let _ = RmEndSession(session);
    }
    result
}

/// Whether the Restart Manager functions `resource_users` calls can be resolved: a structural check that starts no
/// session and registers no resource. They are linked in (`rstrtmgr.dll` ships with every supported Windows), so this
/// asks that the library loads.
pub fn restart_manager_available() -> bool {
    use windows::Win32::System::LibraryLoader::{
        GetProcAddress, LOAD_LIBRARY_SEARCH_SYSTEM32, LoadLibraryExW,
    };
    use windows::core::{PCSTR, w};
    // SAFETY: loads a system DLL by name, from System32 only.
    let Ok(library) =
        (unsafe { LoadLibraryExW(w!("rstrtmgr.dll"), None, LOAD_LIBRARY_SEARCH_SYSTEM32) })
    else {
        return false;
    };
    [
        "RmStartSession\0",
        "RmRegisterResources\0",
        "RmGetList\0",
        "RmEndSession\0",
    ]
    // SAFETY: a name constant, NUL-terminated.
    .iter()
    .all(|name| unsafe { GetProcAddress(library, PCSTR(name.as_ptr())) }.is_some())
}
