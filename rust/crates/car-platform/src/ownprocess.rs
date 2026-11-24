//! What Windows is asked about the watcher's own process, and about this sign-in (`win/ownprocess.py`).
//!
//! Three documented Win32 questions, each about this process or this PC and none about anything a person has
//! written, read or opened: `K32GetProcessMemoryInfo` of this process only (private memory committed now, and the
//! peak), `GetTokenInformation(TokenStatistics)` of this process's own token (the number Windows gives this sign-in -
//! a counter, new for every sign-in, naming no one), and `GetTickCount64` (how long ago Windows started).
//!
//! Nothing here reads a setting or decides anything, and nothing here fails: an answer that cannot be had is None.

use windows::Win32::Foundation::HANDLE;
use windows::Win32::Security::{GetTokenInformation, TOKEN_INFORMATION_CLASS, TOKEN_STATISTICS};
use windows::Win32::System::ProcessStatus::{
    K32GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS, PROCESS_MEMORY_COUNTERS_EX,
};
use windows::Win32::System::SystemInformation::GetTickCount64;
use windows::Win32::System::Threading::GetCurrentProcess;

const TOKEN_STATISTICS_CLASS: i32 = 10;

/// (private bytes now, the most private bytes so far) of this process, or None.
pub fn memory() -> Option<(u64, u64)> {
    let mut counters = PROCESS_MEMORY_COUNTERS_EX {
        cb: std::mem::size_of::<PROCESS_MEMORY_COUNTERS_EX>() as u32,
        ..Default::default()
    };
    // SAFETY: this process's pseudo handle; the structure is ours, sized as it says.
    let asked = unsafe {
        K32GetProcessMemoryInfo(
            GetCurrentProcess(),
            &mut counters as *mut _ as *mut PROCESS_MEMORY_COUNTERS,
            counters.cb,
        )
    };
    if !asked.as_bool() {
        return None;
    }
    let private = counters.PrivateUsage as u64;
    Some((private, private.max(counters.PeakPagefileUsage as u64)))
}

/// The number Windows gives this sign-in, as 16 hex digits, or None.
pub fn sign_in() -> Option<String> {
    let token = HANDLE(-4isize as *mut _); // GetCurrentProcessToken(): a pseudo-handle, needs no closing
    let mut statistics = TOKEN_STATISTICS::default();
    let mut needed = 0u32;
    // SAFETY: the structure is ours and as large as the size passed.
    unsafe {
        GetTokenInformation(
            token,
            TOKEN_INFORMATION_CLASS(TOKEN_STATISTICS_CLASS),
            Some(&mut statistics as *mut _ as *mut _),
            std::mem::size_of::<TOKEN_STATISTICS>() as u32,
            &mut needed,
        )
    }
    .ok()?;
    let luid = statistics.AuthenticationId;
    Some(format!("{:08x}{:08x}", luid.HighPart as u32, luid.LowPart))
}

/// When Windows started, by the wall clock, in seconds - or None.
pub fn booted_at() -> Option<f64> {
    // SAFETY: a plain query.
    let since = unsafe { GetTickCount64() };
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_secs_f64();
    Some(now - since as f64 / 1000.0)
}
