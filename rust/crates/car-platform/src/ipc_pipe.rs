//! The Windows calls of the advanced edition's `codex/ipc.py` (seat adv72d, D3): one connection to a named pipe, opened
//! read-write and overlapped at SECURITY_IDENTIFICATION, refused where its server is not this account's own
//! ([`server_trusted`]), and one overlapped read or write at a time with its own deadline ([`Pipe::io`]); and the
//! random request ids (`uuid.uuid4()`, [`uuid4`]).
//!
//! The pipe's name is the caller's: the caller names `\\.\pipe\codex-ipc` (the Codex Desktop's) only in
//! the product. A test names a pipe of its own; [`open`] refuses the Desktop's own name in this crate's tests and
//! wherever `CAR_NO_REAL_IPC` is set (the diffs set it), as if no app ran.

use windows::Win32::Foundation::{
    CloseHandle, ERROR_IO_PENDING, GENERIC_READ, GENERIC_WRITE, HANDLE, INVALID_HANDLE_VALUE,
};
use windows::Win32::Security::Cryptography::{BCRYPT_USE_SYSTEM_PREFERRED_RNG, BCryptGenRandom};
use windows::Win32::Security::{
    EqualSid, GetSidSubAuthority, GetSidSubAuthorityCount, GetTokenInformation, PSID,
    TOKEN_ACCESS_MASK, TOKEN_INFORMATION_CLASS,
};
use windows::Win32::Storage::FileSystem::{
    CreateFileW, FILE_FLAGS_AND_ATTRIBUTES, FILE_SHARE_MODE, OPEN_EXISTING, ReadFile, WriteFile,
};
use windows::Win32::System::IO::{CancelIoEx, GetOverlappedResult, OVERLAPPED};
use windows::Win32::System::Pipes::GetNamedPipeServerProcessId;
use windows::Win32::System::RemoteDesktop::ProcessIdToSessionId;
use windows::Win32::System::Threading::{
    CreateEventW, GetCurrentProcess, GetCurrentProcessId, OpenProcess, OpenProcessToken,
    PROCESS_ACCESS_RIGHTS, ResetEvent, WaitForSingleObject,
};
use windows::core::PCWSTR;

use crate::paths::wide;

/// The Codex Desktop app's own pipe.
pub const DESKTOP_PIPE: &str = r"\\.\pipe\codex-ipc";
/// SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION.
pub const SECURITY_SQOS: u32 = 0x0010_0000 | 0x0001_0000;
const FILE_FLAG_OVERLAPPED: u32 = 0x4000_0000;

/// What a pipe call came to, in the reference's closed words.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PipeError {
    /// `Stop.NO_PIPE`: not there, or not served by this account's own process.
    NoPipe,
    /// `Stop.BROKEN`.
    Broken,
    /// `Stop.NO_ANSWER`: the deadline passed (the I/O cancelled and waited out).
    NoAnswer,
}

/// Whether the Desktop's real pipe is refused here: in this crate's tests, and where `CAR_NO_REAL_IPC` is set.
fn real_refused() -> bool {
    cfg!(test) || std::env::var_os("CAR_NO_REAL_IPC").is_some()
}

/// One connection to a named pipe.
#[derive(Debug)]
pub struct Pipe {
    pipe: Option<HANDLE>,
    event: Option<HANDLE>,
}

// SAFETY: the handles are this process's own kernel objects, used from one thread at a time through `&mut`.
unsafe impl Send for Pipe {}

/// `Channel(name)`: the pipe opened, its server checked, its event made.
pub fn open(name: &str) -> Result<Pipe, PipeError> {
    if real_refused() && name.eq_ignore_ascii_case(DESKTOP_PIPE) {
        return Err(PipeError::NoPipe);
    }
    let wide_name = wide(name);
    // SAFETY: `wide_name` is NUL-terminated and outlives the call.
    let opened = unsafe {
        CreateFileW(
            PCWSTR(wide_name.as_ptr()),
            GENERIC_READ.0 | GENERIC_WRITE.0,
            FILE_SHARE_MODE(0),
            None,
            OPEN_EXISTING,
            FILE_FLAGS_AND_ATTRIBUTES(FILE_FLAG_OVERLAPPED | SECURITY_SQOS),
            None,
        )
    };
    let pipe = match opened {
        Ok(handle) if handle != INVALID_HANDLE_VALUE && !handle.is_invalid() => handle,
        _ => return Err(PipeError::NoPipe),
    };
    let mut made = Pipe {
        pipe: Some(pipe),
        event: None,
    };
    if !server_trusted(server_pid(pipe)) {
        made.close();
        return Err(PipeError::NoPipe);
    }
    // SAFETY: an unnamed manual-reset event of this process's own.
    match unsafe { CreateEventW(None, true, false, PCWSTR::null()) } {
        Ok(event) if !event.is_invalid() => made.event = Some(event),
        _ => {
            made.close();
            return Err(PipeError::Broken);
        }
    }
    Ok(made)
}

/// `server_pid(k32, pipe)`: the process serving the pipe, or None.
fn server_pid(pipe: HANDLE) -> Option<u32> {
    let mut found = 0u32;
    // SAFETY: an open pipe handle and a valid out parameter.
    let asked = unsafe { GetNamedPipeServerProcessId(pipe, &mut found) };
    (asked.is_ok() && found != 0).then_some(found)
}

fn close_handle(handle: HANDLE) {
    // SAFETY: a handle this module opened, closed once.
    unsafe {
        let _ = CloseHandle(handle);
    }
}

/// `information(token, kind)`: the token's information of that class, or None.
fn information(token: HANDLE, kind: i32) -> Option<Vec<u8>> {
    let mut needed = 0u32;
    // SAFETY: a size query, no buffer.
    unsafe {
        let _ = GetTokenInformation(token, TOKEN_INFORMATION_CLASS(kind), None, 0, &mut needed);
    }
    if !(0 < needed && needed <= 65536) {
        return None;
    }
    // A buffer aligned for the pointer the structure begins with.
    let mut buffer = vec![0u64; (needed as usize).div_ceil(8)];
    // SAFETY: the buffer holds `needed` bytes.
    unsafe {
        GetTokenInformation(
            token,
            TOKEN_INFORMATION_CLASS(kind),
            Some(buffer.as_mut_ptr().cast()),
            needed,
            &mut needed,
        )
    }
    .ok()?;
    let bytes: Vec<u8> = buffer.iter().flat_map(|word| word.to_le_bytes()).collect();
    Some(bytes)
}

/// TOKEN_USER and TOKEN_MANDATORY_LABEL: a SID pointer first.
fn sid_of(buffer: &[u8]) -> PSID {
    let mut pointer = [0u8; 8];
    pointer.copy_from_slice(&buffer[..8]);
    PSID(usize::from_le_bytes(pointer) as *mut core::ffi::c_void)
}

fn integrity(buffer: &[u8]) -> Option<u32> {
    let sid = sid_of(buffer);
    // SAFETY: a SID inside the token information buffer, which outlives these reads.
    unsafe {
        let count = *GetSidSubAuthorityCount(sid);
        if count == 0 {
            return None;
        }
        Some(*GetSidSubAuthority(sid, u32::from(count) - 1))
    }
}

fn token_of(process: HANDLE) -> Option<HANDLE> {
    let mut token = HANDLE::default();
    // SAFETY: a process handle and a valid out parameter.
    unsafe { OpenProcessToken(process, TOKEN_ACCESS_MASK(0x0008), &mut token) }
        .ok()
        .map(|()| token)
}

/// `server_trusted(pid)`: the process runs as this account, in this Windows session, at no lower integrity than this
/// process and outside an AppContainer. False wherever anything cannot be read.
pub fn server_trusted(pid: Option<u32>) -> bool {
    let Some(pid) = pid.filter(|pid| *pid > 0) else {
        return false;
    };
    // SAFETY: the pseudo handle of this process.
    let ours = token_of(unsafe { GetCurrentProcess() });
    // SAFETY: PROCESS_QUERY_LIMITED_INFORMATION on a pid; the handle is closed below.
    let process = unsafe { OpenProcess(PROCESS_ACCESS_RIGHTS(0x1000), false, pid) }.ok();
    let theirs = process.and_then(token_of);
    let trusted = (|| {
        let (ours, theirs) = (ours?, theirs?);
        let (mut session, mut own_session) = (0u32, 0u32);
        // SAFETY: valid out parameters.
        unsafe {
            ProcessIdToSessionId(pid, &mut session).ok()?;
            ProcessIdToSessionId(GetCurrentProcessId(), &mut own_session).ok()?;
        }
        if session != own_session {
            return Some(false);
        }
        let (user, own_user) = (information(theirs, 1)?, information(ours, 1)?);
        // SAFETY: two SIDs inside live buffers.
        if unsafe { EqualSid(sid_of(&user), sid_of(&own_user)) }.is_err() {
            return Some(false);
        }
        let (level, own_level) = (information(theirs, 25)?, information(ours, 25)?);
        let (theirs_level, own) = (integrity(&level)?, integrity(&own_level)?);
        if theirs_level < own {
            return Some(false);
        }
        let contained = information(theirs, 29)?;
        Some(u32::from_le_bytes([contained[0], contained[1], contained[2], contained[3]]) == 0)
    })()
    .unwrap_or(false);
    for handle in [ours, theirs, process].into_iter().flatten() {
        close_handle(handle);
    }
    trusted
}

/// Which way one I/O goes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Way {
    Read,
    Write,
}

impl Pipe {
    /// `_io(call, buffer, size, seconds)`: one overlapped read or write, waited for `int(seconds * 1000)` ms; the
    /// count it moved. Past the wait it is cancelled and waited out: NoAnswer.
    pub fn io(&mut self, way: Way, buffer: &mut [u8], seconds: f64) -> Result<usize, PipeError> {
        let (Some(pipe), Some(event)) = (self.pipe, self.event) else {
            return Err(PipeError::Broken);
        };
        // SAFETY: our own event.
        unsafe {
            let _ = ResetEvent(event);
        }
        let mut overlapped = OVERLAPPED {
            hEvent: event,
            ..Default::default()
        };
        // SAFETY: the buffer and `overlapped` outlive the I/O: it is waited for, or cancelled and waited out, below.
        let started = unsafe {
            match way {
                Way::Read => ReadFile(pipe, Some(buffer), None, Some(&mut overlapped)),
                Way::Write => WriteFile(pipe, Some(buffer), None, Some(&mut overlapped)),
            }
        };
        if let Err(error) = started
            && error.code() != ERROR_IO_PENDING.to_hresult()
        {
            return Err(PipeError::Broken);
        }
        let millis = (seconds * 1000.0) as i64;
        let millis = millis.clamp(0, i64::from(u32::MAX - 1)) as u32;
        let mut count = 0u32;
        // SAFETY: our own event; the I/O above is the one cancelled and waited out.
        unsafe {
            if WaitForSingleObject(event, millis).0 != 0 {
                let _ = CancelIoEx(pipe, Some(&overlapped));
                let _ = GetOverlappedResult(pipe, &overlapped, &mut count, true);
                return Err(PipeError::NoAnswer);
            }
            if GetOverlappedResult(pipe, &overlapped, &mut count, false).is_err() {
                return Err(PipeError::Broken);
            }
        }
        Ok(count as usize)
    }

    /// `close()`: the event, then the pipe.
    pub fn close(&mut self) {
        if let Some(event) = self.event.take() {
            close_handle(event);
        }
        if let Some(pipe) = self.pipe.take() {
            close_handle(pipe);
        }
    }
}

impl Drop for Pipe {
    fn drop(&mut self) {
        self.close();
    }
}

/// `str(uuid.uuid4())`: 122 random bits from the system's preferred generator, version 4, RFC 4122 variant.
pub fn uuid4() -> String {
    let mut bytes = [0u8; 16];
    // SAFETY: a buffer of ours; the system's preferred generator needs no algorithm handle.
    let _ = unsafe { BCryptGenRandom(None, &mut bytes, BCRYPT_USE_SYSTEM_PREFERRED_RNG) };
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    )
}

#[cfg(test)]
mod tests {
    #[test]
    fn the_desktop_pipe_is_refused_in_a_test() {
        assert_eq!(
            super::open(super::DESKTOP_PIPE).err(),
            Some(super::PipeError::NoPipe)
        );
        assert_eq!(
            super::open(r"\\.\PIPE\CODEX-IPC").err(),
            Some(super::PipeError::NoPipe)
        );
    }

    #[test]
    fn uuid4_has_the_version_and_variant() {
        let made = super::uuid4();
        assert_eq!(made.len(), 36);
        assert_eq!(&made[14..15], "4");
        assert!(matches!(&made[19..20], "8" | "9" | "a" | "b"));
        assert_ne!(made, super::uuid4());
    }
}
