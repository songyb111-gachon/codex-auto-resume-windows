//! Windows hands for restarting one application (seat S7.2b): the Restart Manager's request to close one process, the
//! end of one process by its id and creation time, and a folder's access list made the current user's alone.
//!
//! Nothing here decides anything: the caller makes its own checks and calls these in its own order, through the
//! [`Manager`] and [`Kernel`] traits, so a diff can hand both sides a stand-in that logs every call (the real ones are
//! [`Windows`]). The standard edition never calls any of it. `RmShutdown` is asked with the flags the caller gives (0
//! from the one caller there is, never `RmForceShutdown`), and only for the one process registered by id AND creation
//! time, so a reused id is never asked.

use std::path::Path;

use windows::Win32::Foundation::{CloseHandle, FILETIME, HANDLE, HLOCAL, LocalFree, WIN32_ERROR};
use windows::Win32::Security::Authorization::{
    ConvertStringSecurityDescriptorToSecurityDescriptorW, SDDL_REVISION_1, SE_FILE_OBJECT,
    SetNamedSecurityInfoW,
};
use windows::Win32::Security::{
    ACL, DACL_SECURITY_INFORMATION, GetSecurityDescriptorDacl, PROTECTED_DACL_SECURITY_INFORMATION,
    PSECURITY_DESCRIPTOR,
};
use windows::Win32::System::RestartManager::{
    CCH_RM_SESSION_KEY, RM_UNIQUE_PROCESS, RmEndSession, RmRegisterResources, RmShutdown,
    RmStartSession,
};
use windows::Win32::System::Threading::{
    GetProcessTimes, OpenProcess, PROCESS_ACCESS_RIGHTS, TerminateProcess, WaitForSingleObject,
};
use windows::core::{BOOL, PCWSTR, PWSTR};

use crate::paths::wide;

/// The Restart Manager's four calls, as `ask_close` makes them. Each answers the Win32 error code (0 is success).
pub trait Manager {
    /// `RmStartSession`: the session handle, or the error code.
    fn start_session(&self) -> Result<u32, u32>;
    /// `RmRegisterResources(session, 0, NULL, 1, &{pid, created}, 0, NULL)`.
    fn register(&self, session: u32, pid: u32, created: u64) -> u32;
    /// `RmShutdown(session, flags, NULL)`.
    fn shutdown(&self, session: u32, flags: u32) -> u32;
    /// `RmEndSession(session)`.
    fn end_session(&self, session: u32) -> u32;
}

/// kernel32's five calls, as `end_process` makes them. A handle is its value; 0 is none.
pub trait Kernel {
    /// `OpenProcess(access, FALSE, pid)`: the handle, or 0.
    fn open(&self, access: u32, pid: u32) -> isize;
    /// `WaitForSingleObject(handle, millis)`.
    fn wait(&self, handle: isize, millis: u32) -> u32;
    /// `GetProcessTimes(handle, ...)`: the creation FILETIME as one integer, or None where the call failed.
    fn created(&self, handle: isize) -> Option<u64>;
    /// `TerminateProcess(handle, code)`: whether it answered TRUE.
    fn terminate(&self, handle: isize, code: u32) -> bool;
    /// `CloseHandle(handle)`.
    fn close(&self, handle: isize) -> bool;
}

/// Windows itself.
#[derive(Debug, Clone, Copy, Default)]
pub struct Windows;

fn filetime(value: u64) -> FILETIME {
    FILETIME {
        dwLowDateTime: (value & 0xFFFF_FFFF) as u32,
        dwHighDateTime: (value >> 32) as u32,
    }
}

impl Manager for Windows {
    fn start_session(&self) -> Result<u32, u32> {
        let mut session = 0u32;
        let mut key = vec![0u16; CCH_RM_SESSION_KEY as usize + 1];
        // SAFETY: out values of our own, the key buffer as long as the API asks.
        let code = unsafe { RmStartSession(&mut session, None, PWSTR(key.as_mut_ptr())) };
        if code == WIN32_ERROR(0) {
            Ok(session)
        } else {
            Err(code.0)
        }
    }

    fn register(&self, session: u32, pid: u32, created: u64) -> u32 {
        let process = [RM_UNIQUE_PROCESS {
            dwProcessId: pid,
            ProcessStartTime: filetime(created),
        }];
        // SAFETY: one structure of our own, alive for the call.
        unsafe { RmRegisterResources(session, None, Some(&process), None) }.0
    }

    fn shutdown(&self, session: u32, flags: u32) -> u32 {
        // SAFETY: a session this process started; no callback.
        unsafe { RmShutdown(session, flags, None) }.0
    }

    fn end_session(&self, session: u32) -> u32 {
        // SAFETY: a session this process started.
        unsafe { RmEndSession(session) }.0
    }
}

impl Kernel for Windows {
    fn open(&self, access: u32, pid: u32) -> isize {
        // SAFETY: a plain open; the handle is closed by `close`.
        match unsafe { OpenProcess(PROCESS_ACCESS_RIGHTS(access), false, pid) } {
            Ok(handle) => handle.0 as isize,
            Err(_) => 0,
        }
    }

    fn wait(&self, handle: isize, millis: u32) -> u32 {
        // SAFETY: a handle `open` gave.
        unsafe { WaitForSingleObject(HANDLE(handle as *mut _), millis) }.0
    }

    fn created(&self, handle: isize) -> Option<u64> {
        let mut times = [FILETIME::default(); 4];
        let [creation, exit, kernel, user] = &mut times;
        // SAFETY: four FILETIMEs of our own; a handle `open` gave.
        unsafe { GetProcessTimes(HANDLE(handle as *mut _), creation, exit, kernel, user) }.ok()?;
        Some((u64::from(times[0].dwHighDateTime) << 32) | u64::from(times[0].dwLowDateTime))
    }

    fn terminate(&self, handle: isize, code: u32) -> bool {
        // SAFETY: a handle `open` gave, opened with PROCESS_TERMINATE.
        unsafe { TerminateProcess(HANDLE(handle as *mut _), code) }.is_ok()
    }

    fn close(&self, handle: isize) -> bool {
        // SAFETY: a handle `open` gave, closed once.
        unsafe { CloseHandle(HANDLE(handle as *mut _)) }.is_ok()
    }
}

/// `_private_dacl(directory)`'s Windows half: `directory`'s access list replaced by `D:P(A;OICI;FA;;;<sid>)` - the one
/// user, full control, inherited by everything in it, nothing inherited from above. Whether Windows took it (a drive
/// that keeps no access list does not). `sid` is checked by the caller.
pub fn private_folder(directory: &Path, sid: &str) -> bool {
    let sddl = wide(&format!("D:P(A;OICI;FA;;;{sid})"));
    let mut descriptor = PSECURITY_DESCRIPTOR::default();
    // SAFETY: a NUL-terminated string of our own; the descriptor is freed with LocalFree below.
    if unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            PCWSTR(sddl.as_ptr()),
            SDDL_REVISION_1,
            &mut descriptor,
            None,
        )
    }
    .is_err()
    {
        return false;
    }
    let outcome = (|| {
        let (mut present, mut defaulted) = (BOOL(0), BOOL(0));
        let mut dacl: *mut ACL = std::ptr::null_mut();
        // SAFETY: a descriptor Windows just made; out values of our own.
        if unsafe { GetSecurityDescriptorDacl(descriptor, &mut present, &mut dacl, &mut defaulted) }
            .is_err()
            || !present.as_bool()
        {
            return false;
        }
        let path = wide(&directory.to_string_lossy());
        // SAFETY: the path is NUL-terminated and outlives the call; the DACL lives in the descriptor.
        let code = unsafe {
            SetNamedSecurityInfoW(
                PCWSTR(path.as_ptr()),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                Some(dacl),
                None,
            )
        };
        code == WIN32_ERROR(0)
    })();
    // SAFETY: the descriptor ConvertStringSecurityDescriptorToSecurityDescriptorW allocated.
    unsafe {
        let _ = LocalFree(Some(HLOCAL(descriptor.0)));
    }
    outcome
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::windows::process::CommandExt;

    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    const ACCESS: u32 = 0x0001 | 0x1000 | 0x0010_0000;

    /// A throwaway child of the test's own (cmd.exe waiting on a pipe the test holds), never anyone else's process.
    fn child() -> std::process::Child {
        std::process::Command::new("cmd.exe")
            .args(["/d", "/q", "/k"])
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .expect("cmd.exe starts")
    }

    #[test]
    fn a_process_of_the_test_s_own_is_read_and_ended_by_its_own_handle() {
        let mut started = child();
        let kernel = Windows;
        let handle = kernel.open(ACCESS, started.id());
        assert_ne!(handle, 0);
        assert!(kernel.created(handle).is_some());
        assert_eq!(kernel.wait(handle, 0), 258, "still running");
        assert!(started.try_wait().expect("asked").is_none());
        assert!(kernel.terminate(handle, 1));
        assert!(kernel.close(handle));
        assert_eq!(started.wait().expect("ended").code(), Some(1));
    }

    #[test]
    fn the_restart_manager_is_asked_only_of_the_test_s_own_child() {
        let mut started = child();
        let kernel = Windows;
        let handle = kernel.open(0x1000, started.id());
        let created = kernel.created(handle).expect("its times");
        kernel.close(handle);
        let manager = Windows;
        let session = manager.start_session().expect("a session");
        assert_eq!(manager.register(session, started.id(), created), 0);
        // Whatever Windows answers for a console child, nothing but it was registered; it is ended below either way.
        let _ = manager.shutdown(session, 0);
        assert_eq!(manager.end_session(session), 0);
        let _ = started.kill();
        let _ = started.wait();
    }

    #[test]
    fn a_folder_of_the_test_s_own_is_made_private_to_this_user() {
        let folder = std::env::temp_dir().join(format!("car-restart-acl-{}", std::process::id()));
        std::fs::create_dir_all(&folder).expect("made");
        let sid = crate::kernel::user_sid().expect("this user's SID");
        assert!(private_folder(&folder, &sid));
        assert_eq!(crate::acl::allowed_sids(&folder), Some(vec![sid]));
        let _ = std::fs::remove_dir_all(&folder);
    }
}
