//! The power action's Windows calls: may this account do it, is anyone here, and doing it (`win/powerdown.py`).
//!
//! `poweraction` says when; this is only how, and every call is a documented Win32 function, made from the
//! watcher's own process - no program is started, no task or service is made, and nothing needs an administrator:
//!
//! * the process's token, read (`GetTokenInformation(TokenPrivileges)`): does this account hold
//!   `SeShutdownPrivilege` at all?
//! * `GetPwrCapabilities`: does Windows report a sleep state (S1, S2 or S3), and hibernation with its file there?
//! * `GetLastInputInfo` and `GetTickCount`: how long since anybody used this PC - a time, no hook, nothing typed;
//! * `WTSEnumerateSessionsW`: how many other sessions are signed in - a count, no user name read;
//! * and, to act: `SeShutdownPrivilege` enabled on the process's own token, then `SetSuspendState` or
//!   `ExitWindowsEx(EWX_POWEROFF)` with a planned application's reason. Never a force flag.
//!
//! Nothing here acts while a test runs: `act` refuses whenever it is told to refuse ([`refuse_power_actions`]), when
//! it is built for a unit test, or when `CAR_NO_POWER_ACTION` is set - the reference refuses whenever `unittest` is
//! loaded. The tests of this crate never reach the two calls that act (`SetSuspendState`, `ExitWindowsEx`).

use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};

use windows::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, LUID};
use windows::Win32::Security::{
    AdjustTokenPrivileges, GetTokenInformation, LUID_AND_ATTRIBUTES, LookupPrivilegeValueW,
    SE_PRIVILEGE_ENABLED, TOKEN_ADJUST_PRIVILEGES, TOKEN_INFORMATION_CLASS, TOKEN_PRIVILEGES,
    TOKEN_QUERY,
};
use windows::Win32::System::Power::{
    GetPwrCapabilities, SYSTEM_POWER_CAPABILITIES, SetSuspendState,
};
use windows::Win32::System::RemoteDesktop::ProcessIdToSessionId;
use windows::Win32::System::RemoteDesktop::{
    WTS_SESSION_INFOW, WTSEnumerateSessionsW, WTSFreeMemory,
};
use windows::Win32::System::Shutdown::{EWX_POWEROFF, ExitWindowsEx, SHUTDOWN_REASON};
use windows::Win32::System::SystemInformation::GetTickCount;
use windows::Win32::System::Threading::{GetCurrentProcess, GetCurrentProcessId, OpenProcessToken};
use windows::Win32::UI::Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO};
use windows::core::{PWSTR, w};

pub const SHTDN_REASON_MAJOR_APPLICATION: u32 = 0x0004_0000;
pub const SHTDN_REASON_FLAG_PLANNED: u32 = 0x8000_0000;
const ERROR_NOT_ALL_ASSIGNED: u32 = 1300;
const TOKEN_PRIVILEGES_CLASS: i32 = 3;
const WTS_ACTIVE: i32 = 0;
const WTS_DISCONNECTED: i32 = 4;

pub const SLEEP: &str = "sleep";
pub const HIBERNATE: &str = "hibernate";
pub const SHUT_DOWN: &str = "shut_down";
pub const NO_PRIVILEGE: &str = "no_privilege";
pub const NO_SLEEP_STATE: &str = "no_sleep_state";
pub const HIBERNATE_OFF: &str = "hibernate_off";

static REFUSE: AtomicBool = AtomicBool::new(false);
static LAST_ERROR: AtomicU32 = AtomicU32::new(0);
static HAS_LAST_ERROR: AtomicBool = AtomicBool::new(false);

/// From now on `act` does nothing and answers false (a test, a probe, a dry run).
pub fn refuse_power_actions() {
    REFUSE.store(true, Ordering::SeqCst);
}

fn refused() -> bool {
    cfg!(test) || REFUSE.load(Ordering::SeqCst) || std::env::var_os("CAR_NO_POWER_ACTION").is_some()
}

fn close(handle: HANDLE) {
    // SAFETY: a handle this module opened.
    unsafe {
        let _ = CloseHandle(handle);
    }
}

fn token(access: windows::Win32::Security::TOKEN_ACCESS_MASK) -> Option<HANDLE> {
    let mut handle = HANDLE::default();
    // SAFETY: this process's pseudo handle; a handle of our own comes back.
    unsafe { OpenProcessToken(GetCurrentProcess(), access, &mut handle) }.ok()?;
    (!handle.is_invalid()).then_some(handle)
}

fn shutdown_luid() -> Option<LUID> {
    let mut luid = LUID::default();
    // SAFETY: a name constant and a LUID of our own.
    unsafe { LookupPrivilegeValueW(None, w!("SeShutdownPrivilege"), &mut luid) }.ok()?;
    Some(luid)
}

/// Whether this process's token holds SeShutdownPrivilege, enabled or not: Some(true), Some(false), or None.
pub fn holds_shutdown_privilege() -> Option<bool> {
    let luid = shutdown_luid()?;
    let handle = token(TOKEN_QUERY)?;
    let class = TOKEN_INFORMATION_CLASS(TOKEN_PRIVILEGES_CLASS);
    let mut needed = 0u32;
    // SAFETY: asks the size.
    let _ = unsafe { GetTokenInformation(handle, class, None, 0, &mut needed) };
    if !(4..=1 << 20).contains(&needed) {
        close(handle);
        return None;
    }
    let mut buffer = vec![0u8; needed as usize];
    // SAFETY: as long as the size asked.
    let read = unsafe {
        GetTokenInformation(
            handle,
            class,
            Some(buffer.as_mut_ptr() as *mut _),
            needed,
            &mut needed,
        )
    };
    close(handle);
    read.ok()?;
    let count = u32::from_le_bytes(buffer[..4].try_into().ok()?) as usize;
    let entry = std::mem::size_of::<LUID_AND_ATTRIBUTES>();
    if 4 + count * entry > buffer.len() {
        return None;
    }
    for index in 0..count {
        let at = 4 + index * entry;
        let low = u32::from_le_bytes(buffer[at..at + 4].try_into().ok()?);
        let high = i32::from_le_bytes(buffer[at + 4..at + 8].try_into().ok()?);
        if low == luid.LowPart && high == luid.HighPart {
            return Some(true);
        }
    }
    Some(false)
}

fn capabilities() -> Option<SYSTEM_POWER_CAPABILITIES> {
    let mut found = SYSTEM_POWER_CAPABILITIES::default();
    // SAFETY: a structure of our own.
    unsafe { GetPwrCapabilities(&mut found) }.then_some(found)
}

/// (true, None) when Windows lets this account do `action` on this PC now, else (false, why): no SeShutdownPrivilege
/// (for all three, before anything else is asked), no sleep state reported, or hibernation off (or its file
/// missing). An answer that cannot be had is not an offer.
pub fn available(action: &str) -> (bool, Option<&'static str>) {
    if ![SLEEP, HIBERNATE, SHUT_DOWN].contains(&action) {
        return (false, None);
    }
    if holds_shutdown_privilege() != Some(true) {
        return (false, Some(NO_PRIVILEGE));
    }
    if action == SHUT_DOWN {
        return (true, None);
    }
    let found = capabilities();
    if action == SLEEP {
        let ok = found
            .as_ref()
            .is_some_and(|f| f.SystemS1 || f.SystemS2 || f.SystemS3);
        return if ok {
            (true, None)
        } else {
            (false, Some(NO_SLEEP_STATE))
        };
    }
    let ok = found
        .as_ref()
        .is_some_and(|f| f.SystemS4 && f.HiberFilePresent);
    if ok {
        (true, None)
    } else {
        (false, Some(HIBERNATE_OFF))
    }
}

/// Seconds since anybody last used this PC's keyboard or mouse, or None.
pub fn idle_seconds() -> Option<f64> {
    let mut last = LASTINPUTINFO {
        cbSize: std::mem::size_of::<LASTINPUTINFO>() as u32,
        dwTime: 0,
    };
    // SAFETY: a structure of our own with its size set.
    if !unsafe { GetLastInputInfo(&mut last) }.as_bool() {
        return None;
    }
    // SAFETY: a plain query.
    let now = unsafe { GetTickCount() };
    Some(f64::from(now.wrapping_sub(last.dwTime)) / 1000.0) // both wrap after 49.7 days
}

/// How many sessions other than this one, and other than the services' session 0, are signed in - active or
/// disconnected - or None.
pub fn other_sessions() -> Option<usize> {
    let mut own = 0u32;
    // SAFETY: a plain query.
    unsafe { ProcessIdToSessionId(GetCurrentProcessId(), &mut own) }.ok()?;
    let mut listing: *mut WTS_SESSION_INFOW = std::ptr::null_mut();
    let mut count = 0u32;
    // SAFETY: out pointers of our own; the listing is freed below.
    unsafe { WTSEnumerateSessionsW(None, 0, 1, &mut listing, &mut count) }.ok()?;
    let mut total = 0;
    for index in 0..count as usize {
        // SAFETY: an index below the count the call returned.
        let session = unsafe { &*listing.add(index) };
        if session.SessionId != 0
            && session.SessionId != own
            && [WTS_ACTIVE, WTS_DISCONNECTED].contains(&session.State.0)
        {
            total += 1;
        }
    }
    // SAFETY: allocated by WTSEnumerateSessionsW.
    unsafe { WTSFreeMemory(listing as *mut _) };
    Some(total)
}

/// The Windows error number the last `act` that was refused ended with, or None.
pub fn last_error() -> Option<u32> {
    HAS_LAST_ERROR
        .load(Ordering::SeqCst)
        .then(|| LAST_ERROR.load(Ordering::SeqCst))
}

fn remember_error() {
    // SAFETY: reads the thread's last error.
    LAST_ERROR.store(unsafe { GetLastError() }.0, Ordering::SeqCst);
    HAS_LAST_ERROR.store(true, Ordering::SeqCst);
}

fn privilege(handle: HANDLE, luid: LUID, enabled: bool) -> bool {
    let change = TOKEN_PRIVILEGES {
        PrivilegeCount: 1,
        Privileges: [LUID_AND_ATTRIBUTES {
            Luid: luid,
            Attributes: if enabled {
                SE_PRIVILEGE_ENABLED
            } else {
                windows::Win32::Security::TOKEN_PRIVILEGES_ATTRIBUTES(0)
            },
        }],
    };
    // SAFETY: the structure is ours.
    let done = unsafe { AdjustTokenPrivileges(handle, false, Some(&change), 0, None, None) };
    // SAFETY: reads the thread's last error.
    done.is_ok() && unsafe { GetLastError() }.0 != ERROR_NOT_ALL_ASSIGNED
}

/// Do `action` now: true when Windows took it. Sleep and hibernate return once this PC wakes; a shut down returns at
/// once, before any program has answered - so a refused one looks taken. Refused (false) wherever a test could be
/// running, and for an action that is not one of the three.
pub fn act(action: &str) -> bool {
    if refused() || ![SLEEP, HIBERNATE, SHUT_DOWN].contains(&action) {
        return false;
    }
    HAS_LAST_ERROR.store(false, Ordering::SeqCst);
    let Some(luid) = shutdown_luid() else {
        return false;
    };
    let Some(handle) = token(TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY) else {
        remember_error();
        return false;
    };
    let enabled = privilege(handle, luid, true);
    let done = if !enabled {
        remember_error();
        false
    } else if action == SHUT_DOWN {
        // SAFETY: the one call that powers the PC off, reached only past `refused()`.
        let done = unsafe {
            ExitWindowsEx(
                EWX_POWEROFF,
                SHUTDOWN_REASON(SHTDN_REASON_MAJOR_APPLICATION | SHTDN_REASON_FLAG_PLANNED),
            )
        }
        .is_ok();
        if !done {
            remember_error();
        }
        done
    } else {
        // SAFETY: the one call that suspends the PC, reached only past `refused()`.
        let done = unsafe { SetSuspendState(action == HIBERNATE, false, false) };
        if !done {
            remember_error();
        }
        done
    };
    if enabled {
        privilege(handle, luid, false);
    }
    close(handle);
    done
}

#[allow(dead_code)]
fn _unused(_: PWSTR) {}
