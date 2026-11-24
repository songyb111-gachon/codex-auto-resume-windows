//! What Windows is asked about power, and the one request made of it (`win/power.py`).
//!
//! Each is a documented Win32 call, made only while a setting that needs it is on:
//!
//! * `QueryUnbiasedInterruptTime` - how long this PC has been awake, time asleep or hibernating not counted;
//! * `GetSystemPowerStatus` - whether it runs on mains power (its ACLineStatus, and nothing else);
//! * `RegisterSuspendResumeNotification` with a callback rather than a window - that it has just woken;
//! * `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` - a request, held by the calling thread, that the
//!   PC not sleep on its own; `ES_CONTINUOUS` alone takes it back. No setting of Windows is changed.
//!
//! Nothing here reads a setting or decides anything, and nothing here fails: an answer that cannot be had is None,
//! and a request Windows did not take is false. The wake callback runs on a thread of Windows' own, so a panic in
//! it is caught there (D15): nothing may escape to Windows.

use std::ffi::c_void;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Arc;

use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::Power::{
    DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS, ES_CONTINUOUS, ES_SYSTEM_REQUIRED, EXECUTION_STATE,
    GetSystemPowerStatus, HPOWERNOTIFY, RegisterSuspendResumeNotification, SYSTEM_POWER_STATUS,
    SetThreadExecutionState, UnregisterSuspendResumeNotification,
};
use windows::Win32::UI::WindowsAndMessaging::REGISTER_NOTIFICATION_FLAGS;

/// What a suspend-resume callback is told: the PC is going to sleep, woke with a person present, woke.
pub const PBT_APMSUSPEND: u32 = 0x0004;
pub const PBT_APMRESUMESUSPEND: u32 = 0x0007;
pub const PBT_APMRESUMEAUTOMATIC: u32 = 0x0012;
const DEVICE_NOTIFY_CALLBACK: u32 = 2;

/// Whether a callback type means the PC woke.
pub fn woke(kind: u32) -> bool {
    kind == PBT_APMRESUMESUSPEND || kind == PBT_APMRESUMEAUTOMATIC
}

/// Seconds this PC has been awake since it started - sleep and hibernation not counted - or None.
pub fn awake_seconds() -> Option<f64> {
    let mut value = 0u64;
    // SAFETY: a u64 of our own.
    if !unsafe {
        windows::Win32::System::WindowsProgramming::QueryUnbiasedInterruptTime(&mut value)
    }
    .as_bool()
    {
        return None;
    }
    Some(value as f64 / 10_000_000.0) // in units of 100 nanoseconds
}

/// True on mains power, false on battery, None when Windows cannot say.
pub fn on_mains() -> Option<bool> {
    let mut status = SYSTEM_POWER_STATUS::default();
    // SAFETY: a structure of our own.
    unsafe { GetSystemPowerStatus(&mut status) }.ok()?;
    match status.ACLineStatus {
        1 => Some(true),
        0 => Some(false),
        _ => None,
    }
}

/// Ask that this PC not sleep on its own (`on`), or take that back. Held by the calling thread: made and taken back
/// on the thread that ticks. Whether Windows took it.
pub fn keep_awake(on: bool) -> bool {
    let flags: EXECUTION_STATE = if on {
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    } else {
        ES_CONTINUOUS
    };
    // SAFETY: a plain request.
    unsafe { SetThreadExecutionState(flags) }.0 != 0
}

type Callback = Arc<dyn Fn() + Send + Sync>;

/// The context Windows hands the callback back: the closure, kept alive for as long as Windows may call it.
struct Context {
    on_wake: Callback,
}

unsafe extern "system" fn told(context: *const c_void, kind: u32, _setting: *const c_void) -> u32 {
    if !context.is_null() && woke(kind) {
        // SAFETY: the pointer `start` gave Windows, alive until `stop` has unregistered it.
        let context = unsafe { &*(context as *const Context) };
        // A thread of Windows' own: nothing may escape to it.
        let _ = catch_unwind(AssertUnwindSafe(|| (context.on_wake)()));
    }
    0
}

/// Told that this PC has woken, while it is open. `on_wake` is called on a thread of Windows' own, so it must do no
/// more than set a flag and signal an event.
pub struct WakeListener {
    context: Box<Context>,
    parameters: Box<DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS>,
    handle: Option<HPOWERNOTIFY>,
}

impl WakeListener {
    pub fn new(on_wake: impl Fn() + Send + Sync + 'static) -> Self {
        let context = Box::new(Context {
            on_wake: Arc::new(on_wake),
        });
        let parameters = Box::new(DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS {
            Callback: Some(told),
            Context: &*context as *const Context as *mut c_void,
        });
        WakeListener {
            context,
            parameters,
            handle: None,
        }
    }

    pub fn open(&self) -> bool {
        self.handle.is_some()
    }

    /// Listen. Whether Windows took it.
    pub fn start(&mut self) -> bool {
        if self.handle.is_some() {
            return true;
        }
        let _ = &self.context;
        let recipient =
            HANDLE(&*self.parameters as *const DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS as *mut c_void);
        // SAFETY: `parameters` and the context behind it live as long as this listener, which unregisters first.
        match unsafe {
            RegisterSuspendResumeNotification(
                recipient,
                REGISTER_NOTIFICATION_FLAGS(DEVICE_NOTIFY_CALLBACK),
            )
        } {
            Ok(handle) if !handle.is_invalid() => {
                self.handle = Some(handle);
                true
            }
            _ => false,
        }
    }

    /// Stop listening; nothing is called after this returns.
    pub fn stop(&mut self) {
        if let Some(handle) = self.handle.take() {
            // SAFETY: the registration `start` made.
            unsafe {
                let _ = UnregisterSuspendResumeNotification(handle);
            }
        }
    }
}

impl Drop for WakeListener {
    fn drop(&mut self) {
        self.stop();
    }
}
