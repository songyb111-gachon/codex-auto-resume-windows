//! `win/appclose.py` (seat S7.2b): ending the Codex app's main process, for the restart a person agreed to
//! (account_switch) or the automatic switch's (account_auto_switch). Two ways, the gentler first (`codex::restart`
//! decides when):
//!
//! * [`ask_close`]: Windows' own request to close an application - the Restart Manager's `RmShutdown`, with no force
//!   flag, for that one process, registered by its id and creation time so a reused id is never asked;
//! * [`end_process`]: `TerminateProcess` of that same process, only where its creation time is still the one asked
//!   about.
//!
//! Nothing else is ended, asked or read. Every function answers false rather than fail where Windows says no. The
//! Windows calls are car-platform's (`car_platform::restart`, D3), asked through its [`Manager`] and [`Kernel`] traits in
//! the reference's order, so a diff hands both sides a stand-in that logs them; [`Windows`] is the real one.

pub use car_platform::restart::{Kernel, Manager, Windows};

use car_machine::json::Value;

pub const ERROR_SUCCESS: u32 = 0;
pub const PROCESS_TERMINATE: u32 = 0x0001;
pub const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
pub const SYNCHRONIZE: u32 = 0x0010_0000;
pub const WAIT_TIMEOUT: u32 = 258;

/// `type(value) is int and value > 0`: a Python int (never a bool), positive.
fn positive(value: &Value) -> bool {
    matches!(value, Value::Int(_))
        && car_machine::pyval::greater(value, &Value::from(0)).unwrap_or(false)
}

/// The low 64 bits of a non-negative int (what ctypes keeps of it: it masks, it never refuses), and whether it fits.
pub fn low_bits(value: &Value) -> (u64, bool) {
    let Value::Int(number) = value else {
        return (0, false);
    };
    if let Some(small) = number.as_u64() {
        return (small, true);
    }
    let mut low = 0u64;
    for digit in number.to_string().bytes().filter(u8::is_ascii_digit) {
        low = low.wrapping_mul(10).wrapping_add(u64::from(digit - b'0'));
    }
    (low, false)
}

/// `ask_close(pid, created)`: Windows' request to close the process `pid` made at `created` (FILETIME as one integer):
/// whether Windows says it was closed. Not forced; a program that will not close stays open and this answers false.
pub fn ask_close(manager: &dyn Manager, pid: &Value, created: &Value) -> bool {
    if !positive(pid) || !positive(created) {
        return false;
    }
    let Ok(session) = manager.start_session() else {
        return false;
    };
    let (pid, _) = low_bits(pid);
    let (created, _) = low_bits(created);
    let answer = manager.register(session, pid as u32, created) == ERROR_SUCCESS
        && manager.shutdown(session, 0) == ERROR_SUCCESS; // 0: no RmForceShutdown
    manager.end_session(session);
    answer
}

/// `end_process(pid, created)`: TerminateProcess of `pid`, only while it is still the process made at `created`:
/// whether Windows ended it.
pub fn end_process(kernel: &dyn Kernel, pid: &Value, created: &Value) -> bool {
    if !positive(pid) || !positive(created) {
        return false;
    }
    let (number, _) = low_bits(pid);
    let handle = kernel.open(
        PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
        number as u32,
    );
    if handle == 0 {
        return false;
    }
    let answer = (|| {
        if kernel.wait(handle, 0) != WAIT_TIMEOUT {
            return false; // already ended
        }
        let Some(found) = kernel.created(handle) else {
            return false;
        };
        let (wanted, fits) = low_bits(created);
        if !fits || found != wanted {
            return false; // another process under a reused id
        }
        kernel.terminate(handle, 1)
    })();
    kernel.close(handle);
    answer
}
