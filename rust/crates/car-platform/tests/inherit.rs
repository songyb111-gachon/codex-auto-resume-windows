//! The Dashboard's start inherits no handle, as `subprocess.Popen(..., close_fds=True)` does (Integration 13, item d).
//!
//! A test binary of its own: the proof watches an inheritable pipe end, and any other test of the crate starting a process
//! with std's `Command` on another thread at that moment would inherit it too (the lib's tests run in parallel).

use car_platform::spawn::{CREATE_NO_WINDOW, Spawn, SpawnError, SystemStarter, last_started_flags};
use windows::Win32::Foundation::{CloseHandle, HANDLE};
use windows::Win32::Security::SECURITY_ATTRIBUTES;
use windows::Win32::System::Pipes::{CreatePipe, PeekNamedPipe};
use windows::Win32::System::Threading::{OpenProcess, PROCESS_TERMINATE, TerminateProcess};

fn cmd() -> String {
    let root = std::env::var("SystemRoot").unwrap_or_else(|_| r"C:\Windows".into());
    format!(r"{root}\System32\cmd.exe")
}

/// An inheritable pipe's write end is held by a child that inherits handles: with ours closed, the read end still
/// has a writer while that child lives (`cmd /c pause` waits on its hidden console).
fn writer_left_with(start: impl FnOnce(&Spawn) -> u32) -> bool {
    let inherit = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: std::ptr::null_mut(),
        bInheritHandle: true.into(),
    };
    let (mut read, mut write) = (HANDLE::default(), HANDLE::default());
    // SAFETY: two handles written by the call, closed below.
    unsafe { CreatePipe(&mut read, &mut write, Some(&inherit), 0) }.unwrap();
    let pid = start(&Spawn::new([
        cmd(),
        "/d".into(),
        "/c".into(),
        "pause".into(),
    ]));
    // SAFETY: our own handles; the child is the one this test started.
    unsafe {
        let _ = CloseHandle(write);
        let left = PeekNamedPipe(read, None, 0, None, None, None).is_ok();
        let _ = CloseHandle(read);
        let child = OpenProcess(PROCESS_TERMINATE, false, pid).unwrap();
        let _ = TerminateProcess(child, 1);
        let _ = CloseHandle(child);
        left
    }
}

#[test]
fn the_dashboards_start_inherits_no_handle_as_popen_with_close_fds_does() {
    // The control: std's Command hands the child every inheritable handle, so the writer is still there.
    assert!(writer_left_with(|spawn| SystemStarter
        .start(spawn)
        .unwrap()
        .id()));
    assert!(!writer_left_with(|spawn| SystemStarter
        .start_inheriting_nothing(spawn, true)
        .unwrap()));
}

#[test]
fn what_windows_refuses_is_the_oserror_popen_raises() {
    let missing = SystemStarter
        .start_inheriting_nothing(&Spawn::new([r"C:\car-no-such-folder\a.exe"]), true)
        .unwrap_err();
    let SpawnError::Os(missing) = missing else {
        panic!("a start error")
    };
    assert_eq!(missing.raw_os_error(), Some(2));
    assert_eq!(
        car_machine::pyfile::os_error_class(&missing),
        "FileNotFoundError"
    );
    let nowhere = SystemStarter
        .start_inheriting_nothing(
            &Spawn::new([cmd(), "/c".into(), "exit".into()]).with_cwd(r"C:\car-no-such-folder"),
            true,
        )
        .unwrap_err();
    let SpawnError::Os(nowhere) = nowhere else {
        panic!("a start error")
    };
    assert_eq!(nowhere.raw_os_error(), Some(267));
    assert_eq!(
        car_machine::pyfile::os_error_class(&nowhere),
        "NotADirectoryError"
    );
    assert_eq!(last_started_flags() & CREATE_NO_WINDOW, CREATE_NO_WINDOW);
}
