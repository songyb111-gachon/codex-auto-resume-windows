//! The named objects the watcher is one of, and the three it is woken by (`win/sync.py`).
//!
//! One mutex says a watcher is running; a manual-reset event asks it to stop and an auto-reset event asks it to
//! look now; and one more asks its icon to show a demo card. Each is created at this process's own integrity level
//! and refused if something lower got there first (`kernel::refuse_if_squatted`), because a named object is a name
//! anyone in the session can take. The names are `names`'s: the same as the Python reference makes, so a Rust
//! process and a Python process of one home see one watcher.

use std::time::Duration;

use windows::Win32::Foundation::{
    CloseHandle, GetLastError, HANDLE, WAIT_ABANDONED, WAIT_OBJECT_0, WAIT_TIMEOUT,
};
use windows::Win32::System::Threading::{
    CreateEventW, CreateMutexW, OpenEventW, ReleaseMutex, ResetEvent, SYNCHRONIZATION_SYNCHRONIZE,
    SetEvent, WaitForMultipleObjects, WaitForSingleObject,
};
use windows::core::PCWSTR;

use crate::kernel::{ERROR_ALREADY_EXISTS, refuse_if_squatted};
use crate::names;
use crate::paths::{home_identity, wide};
use crate::seams::AdapterError;

const EVENT_MODIFY_STATE: u32 = 0x0002;

fn close(handle: HANDLE) {
    // SAFETY: a handle this module opened.
    unsafe {
        let _ = CloseHandle(handle);
    }
}

fn millis(seconds: f64) -> u32 {
    (seconds.clamp(0.0, 3600.0) * 1000.0) as u32
}

fn home() -> Result<String, AdapterError> {
    home_identity().ok_or(AdapterError("windows_required"))
}

/// Create (or open) a named object and say whether it existed already: the handle and `ERROR_ALREADY_EXISTS`.
fn existed_after() -> bool {
    // SAFETY: reads the calling thread's last error, which the create call just set.
    unsafe { GetLastError() }.0 == ERROR_ALREADY_EXISTS
}

/// Current-session named mutex, default user DACL, unique per user + state path. Abandonment grants the lock; the
/// engine must reconcile its durable dispatch journal before sending. No PID-file inference or force-unlocking.
pub struct Mutex {
    pub name: String,
    timeout: f64,
    handle: Option<HANDLE>,
    pub abandoned: bool,
}

impl Mutex {
    /// `Mutex(name, timeout)`; the timeout is clamped to 0..60 seconds.
    pub fn new(name: &str, timeout: f64) -> Result<Self, AdapterError> {
        Ok(Self::for_home(&home()?, name, timeout))
    }

    pub fn for_home(home: &str, name: &str, timeout: f64) -> Self {
        Mutex {
            name: names::mutex_name_for(home, name),
            timeout: timeout.clamp(0.0, 60.0),
            handle: None,
            abandoned: false,
        }
    }

    pub fn held(&self) -> bool {
        self.handle.is_some()
    }

    /// `__enter__`: create the mutex, refuse it if squatted, and wait for it up to the timeout.
    pub fn enter(&mut self) -> Result<(), AdapterError> {
        let name = wide(&self.name);
        // SAFETY: `name` is NUL-terminated and outlives the call.
        let created = unsafe { CreateMutexW(None, false, PCWSTR(name.as_ptr())) };
        let existed = existed_after();
        let handle = created.map_err(|_| AdapterError("mutex_creation_failed"))?;
        refuse_if_squatted(handle, existed)?;
        // SAFETY: the handle is ours.
        let result = unsafe { WaitForSingleObject(handle, (self.timeout * 1000.0) as u32) };
        if result != WAIT_OBJECT_0 && result != WAIT_ABANDONED {
            close(handle);
            return Err(AdapterError(if result == WAIT_TIMEOUT {
                "mutex_busy"
            } else {
                "mutex_wait_failed"
            }));
        }
        self.abandoned = result == WAIT_ABANDONED;
        self.handle = Some(handle);
        Ok(())
    }

    /// `__exit__`.
    pub fn exit(&mut self) {
        if let Some(handle) = self.handle.take() {
            // SAFETY: the handle is ours and this thread holds the mutex.
            unsafe {
                let _ = ReleaseMutex(handle);
            }
            close(handle);
        }
    }
}

impl Drop for Mutex {
    fn drop(&mut self) {
        self.exit();
    }
}

/// `SetEvent` on an event opened for modify only: false when no watcher currently holds it.
fn signal_named(name: &str) -> bool {
    let wide_name = wide(name);
    // SAFETY: `wide_name` is NUL-terminated and outlives the call.
    let Ok(handle) = (unsafe {
        OpenEventW(
            windows::Win32::System::Threading::SYNCHRONIZATION_ACCESS_RIGHTS(EVENT_MODIFY_STATE),
            false,
            PCWSTR(wide_name.as_ptr()),
        )
    }) else {
        return false;
    };
    // SAFETY: the handle is ours.
    let done = unsafe { SetEvent(handle) }.is_ok();
    close(handle);
    done
}

fn create_event(
    name: &str,
    manual_reset: bool,
    failure: &'static str,
) -> Result<HANDLE, AdapterError> {
    let wide_name = wide(name);
    // SAFETY: `wide_name` is NUL-terminated and outlives the call.
    let created = unsafe { CreateEventW(None, manual_reset, false, PCWSTR(wide_name.as_ptr())) };
    let existed = existed_after();
    let handle = created.map_err(|_| AdapterError(failure))?;
    refuse_if_squatted(handle, existed)?;
    Ok(handle)
}

/// Manual-reset named event so `stop` can wake the watcher without killing it.
pub struct StopEvent {
    pub name: String,
    handle: Option<HANDLE>,
}

impl StopEvent {
    pub fn new(name: &str) -> Result<Self, AdapterError> {
        Ok(Self::for_home(&home()?, name))
    }

    pub fn for_home(home: &str, name: &str) -> Self {
        StopEvent {
            name: names::stop_name_for(home, name),
            handle: None,
        }
    }

    pub fn raw(&self) -> Option<HANDLE> {
        self.handle
    }

    pub fn enter(&mut self) -> Result<(), AdapterError> {
        let handle = create_event(&self.name, true, "stop_event_creation_failed")?;
        // SAFETY: the handle is ours. A stale signal must not stop a fresh watcher.
        unsafe {
            let _ = ResetEvent(handle);
        }
        self.handle = Some(handle);
        Ok(())
    }

    /// True when a stop was requested; false after the timeout elapsed.
    pub fn wait(&self, seconds: f64) -> bool {
        match self.handle {
            // SAFETY: the handle is ours.
            Some(handle) => {
                (unsafe { WaitForSingleObject(handle, millis(seconds)) }) == WAIT_OBJECT_0
            }
            None => false,
        }
    }

    pub fn exit(&mut self) {
        if let Some(handle) = self.handle.take() {
            close(handle);
        }
    }

    /// Signal a running watcher. False when no watcher currently holds the event.
    pub fn signal(&self) -> bool {
        signal_named(&self.name)
    }
}

impl Drop for StopEvent {
    fn drop(&mut self) {
        self.exit();
    }
}

/// Auto-reset named event: "look now", sent by Retry Now. Only the watcher creates it; a client can only open it
/// and set it. It is never an instruction to send: a wake runs the ordinary tick, every gate included.
pub struct WakeEvent {
    pub name: String,
    handle: Option<HANDLE>,
}

impl WakeEvent {
    pub fn new(name: &str) -> Result<Self, AdapterError> {
        Ok(Self::for_home(&home()?, name))
    }

    pub fn for_home(home: &str, name: &str) -> Self {
        WakeEvent {
            name: names::wake_name_for(home, name),
            handle: None,
        }
    }

    pub fn raw(&self) -> Option<HANDLE> {
        self.handle
    }

    pub fn enter(&mut self) -> Result<(), AdapterError> {
        self.handle = Some(create_event(
            &self.name,
            false,
            "wake_event_creation_failed",
        )?);
        Ok(())
    }

    pub fn exit(&mut self) {
        if let Some(handle) = self.handle.take() {
            close(handle);
        }
    }

    /// Ask a running watcher to look now. False when none holds the event.
    pub fn signal(&self) -> bool {
        signal_named(&self.name)
    }
}

impl Drop for WakeEvent {
    fn drop(&mut self) {
        self.exit();
    }
}

/// Auto-reset named event: "show me what happens", sent from Diagnostics. It reaches no store and no engine: all a
/// signal can ever do is draw one card of made-up words.
pub struct DemoEvent {
    pub name: String,
    handle: Option<HANDLE>,
}

impl DemoEvent {
    pub fn new(name: &str) -> Result<Self, AdapterError> {
        Ok(Self::for_home(&home()?, name))
    }

    pub fn for_home(home: &str, name: &str) -> Self {
        DemoEvent {
            name: names::demo_name_for(home, name),
            handle: None,
        }
    }

    pub fn enter(&mut self) -> Result<(), AdapterError> {
        self.handle = Some(create_event(
            &self.name,
            false,
            "wake_event_creation_failed",
        )?);
        Ok(())
    }

    pub fn exit(&mut self) {
        if let Some(handle) = self.handle.take() {
            close(handle);
        }
    }

    pub fn signal(&self) -> bool {
        signal_named(&self.name)
    }

    /// Whether it was signalled since the last look, which resets it. Never waits.
    pub fn taken(&self) -> bool {
        // SAFETY: the handle is ours.
        self.handle
            .is_some_and(|handle| unsafe { WaitForSingleObject(handle, 0) } == WAIT_OBJECT_0)
    }
}

impl Drop for DemoEvent {
    fn drop(&mut self) {
        self.exit();
    }
}

/// Wait on several events. The index of the one signalled, or None on timeout (or when none is given: the time is
/// slept out, as the reference does).
pub fn wait_any(handles: &[Option<HANDLE>], seconds: f64) -> Option<usize> {
    let live: Vec<HANDLE> = handles.iter().flatten().copied().collect();
    if live.is_empty() {
        std::thread::sleep(Duration::from_millis(u64::from(millis(seconds))));
        return None;
    }
    // SAFETY: handles the caller owns.
    let result = unsafe { WaitForMultipleObjects(&live, false, millis(seconds)) };
    let index = result.0.wrapping_sub(WAIT_OBJECT_0.0) as usize;
    if index < live.len() {
        return handles
            .iter()
            .position(|handle| *handle == Some(live[index]));
    }
    None
}

#[allow(dead_code)]
const _SYNCHRONIZE: u32 = SYNCHRONIZATION_SYNCHRONIZE.0;
