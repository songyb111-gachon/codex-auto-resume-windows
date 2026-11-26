//! The advanced edition's job object (seat S7.3b): `courier/launch.py`'s `_job` and `adopt`, which
//! `report/github.py` and `codex/wmi_escape.py` share.
//!
//! One job object for this process, made `KILL_ON_JOB_CLOSE` the first time it is needed and never closed here, so
//! every child put in it ends with this process however this process ends. A child is started suspended
//! (`CREATE_SUSPENDED`, with `CREATE_NO_WINDOW` as every child of ours: `crate::spawn`), put in the job, then resumed
//! (`NtResumeProcess`) - so it runs no instruction outside the job. One the job will not take is ended before it runs.

use std::os::windows::io::AsRawHandle;
use std::sync::Mutex;

use windows::Win32::Foundation::{CloseHandle, HANDLE};
use windows::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
    SetInformationJobObject,
};
use windows::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};
use windows::core::{PCWSTR, s, w};

/// `CREATE_SUSPENDED`.
pub const CREATE_SUSPENDED: u32 = 0x0000_0004;

/// The job's handle, as an integer (a raw handle is not `Send`).
static JOB: Mutex<Option<isize>> = Mutex::new(None);

fn error(text: &str) -> std::io::Error {
    std::io::Error::other(text.to_owned())
}

/// This process's one job object for its children: KILL_ON_JOB_CLOSE, never closed here.
fn job() -> std::io::Result<HANDLE> {
    let mut held = JOB.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
    if let Some(handle) = *held {
        return Ok(HANDLE(handle as *mut core::ffi::c_void));
    }
    // SAFETY: a job object made, given its limits, and kept for the life of the process.
    unsafe {
        let handle = CreateJobObjectW(None, PCWSTR::null()).map_err(|_| error("no job object"))?;
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let set = SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            (&info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if set.is_err() {
            let _ = CloseHandle(handle);
            return Err(error("the job object refused its limits"));
        }
        *held = Some(handle.0 as isize);
        Ok(handle)
    }
}

type Resume = unsafe extern "system" fn(HANDLE) -> i32;

/// `ntdll!NtResumeProcess`: every thread of a suspended process resumed.
fn resume(process: HANDLE) -> std::io::Result<()> {
    // SAFETY: ntdll is loaded in every process; the function's signature is NTSTATUS(HANDLE).
    unsafe {
        let ntdll = GetModuleHandleW(w!("ntdll.dll")).map_err(|_| error("no ntdll"))?;
        let Some(found) = GetProcAddress(ntdll, s!("NtResumeProcess")) else {
            return Err(error("no NtResumeProcess"));
        };
        let resume: Resume = std::mem::transmute::<_, Resume>(found);
        if resume(process) != 0 {
            return Err(error("the process could not be resumed"));
        }
    }
    Ok(())
}

/// `adopt(process)`: `child`, started suspended, put in the job and resumed - or ended, and the error.
pub fn adopt(child: &mut std::process::Child) -> std::io::Result<()> {
    let process = HANDLE(child.as_raw_handle());
    let done = job().and_then(|job| {
        // SAFETY: the child's own handle (PROCESS_ALL_ACCESS, std's) and this process's job.
        unsafe { AssignProcessToJobObject(job, process) }
            .map_err(|_| error("the process could not be put in the job"))?;
        resume(process)
    });
    if done.is_err() {
        let _ = child.kill();
    }
    done
}

/// Whether this process has made its job object yet (a test's question).
pub fn made() -> bool {
    JOB.lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .is_some()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spawn::{Spawn, Stream, SystemStarter};

    #[test]
    fn a_child_started_suspended_runs_only_once_it_is_in_the_job() {
        // A throwaway child of the test's own: cmd.exe exiting with a code, in the job, resumed.
        let system = std::env::var("SystemRoot").unwrap_or_else(|_| r"C:\Windows".into());
        let spawn = Spawn::new([format!(r"{system}\System32\cmd.exe"), "/c".into(), "exit 7".into()])
            .with_flags(CREATE_SUSPENDED)
            .with_streams(Stream::Null, Stream::Null, Stream::Null);
        let mut child = SystemStarter.start(&spawn).expect("the child starts");
        adopt(&mut child).expect("the job takes it");
        assert!(made());
        let status = child.wait().expect("it ends");
        assert_eq!(status.code(), Some(7));
    }
}
