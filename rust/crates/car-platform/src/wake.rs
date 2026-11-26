//! The Windows calls of the advanced edition's `win/waketimer.py` and `win/stopflag.py` (seat S7.2c remainder, D3).
//!
//! The reference makes these calls through ctypes with a `kernel`/`power` seam a test fills with a fake that records
//! its calls. Here the seams are three traits - [`TimerKernel`], [`PowerSettings`] and [`EventKernel`] - each with
//! the one real implementation over the `windows` crate ([`SystemTimer`], [`SystemPower`], [`SystemEvents`]) and
//! whatever stand-in a test brings. The caller's timer and stop flag hold the logic and take the traits; they
//! name no Windows call of their own.
//!
//! A test never builds the `System*` types: a real timer set with `fResume` wakes a sleeping PC, and the stop event
//! is the real watcher's (P7-DESIGN section 4). Nothing here suspends, shuts down or writes a power setting: the
//! values are read (`PowerRead*ValueIndex`), never written.

use windows::Win32::Foundation::{CloseHandle, HANDLE, HLOCAL, LocalFree};
use windows::Win32::System::Power::{
    GetSystemPowerStatus, PowerGetActiveScheme, PowerReadACValueIndex, PowerReadDCValueIndex,
    SYSTEM_POWER_STATUS,
};
use windows::Win32::System::Threading::{
    CancelWaitableTimer, CreateEventW, CreateWaitableTimerExW, OpenEventW,
    SYNCHRONIZATION_ACCESS_RIGHTS, SetWaitableTimer, WaitForSingleObject,
};
use windows::core::{GUID, PCWSTR};

use crate::paths::wide;

/// What a call raised: a ctypes error, or a test's fake raising. The callers treat it as the reference's
/// `except Exception`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Raised;

/// One call's answer.
pub type Call<T> = Result<T, Raised>;

/// A handle as ctypes gives one back: an integer, 0 for none.
pub type Handle = isize;

/// The active power scheme as `PowerGetActiveScheme` hands it out: the pointer `LocalFree` takes back, and the
/// scheme's GUID read through it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Scheme {
    pub pointer: usize,
    pub guid: u128,
}

/// `GUID_SLEEP_SUBGROUP`, `GUID_ALLOW_RTC_WAKE` as the reference spells them (uuid.UUID values).
pub const GUID_SLEEP_SUBGROUP: u128 = 0x238c9fa8_0aad_41ed_83f4_97be242c8f20;
pub const GUID_ALLOW_RTC_WAKE: u128 = 0xbd3b718a_0680_4d9d_8ab2_e1d2b4ac806d;

/// kernel32 as `WakeTimer` calls it.
pub trait TimerKernel: Send {
    /// `CreateWaitableTimerExW(NULL, NULL, 0, access)`: the handle, 0 where none was made.
    fn create_waitable_timer(&mut self, access: u32) -> Call<Handle>;
    /// `SetWaitableTimer(handle, &due, period, NULL, NULL, resume)`: whether it answered TRUE.
    fn set_waitable_timer(
        &mut self,
        handle: Handle,
        due: i64,
        period: i32,
        resume: bool,
    ) -> Call<bool>;
    /// `CancelWaitableTimer(handle)`.
    fn cancel_waitable_timer(&mut self, handle: Handle) -> Call<bool>;
    /// `CloseHandle(handle)`.
    fn close_handle(&mut self, handle: Handle) -> Call<bool>;
    /// `GetSystemPowerStatus`: the `ACLineStatus`, or None where the call answered FALSE.
    fn system_power_status(&mut self) -> Call<Option<u8>>;
    /// `LocalFree(scheme)`.
    fn local_free(&mut self, scheme: &Scheme) -> Call<()>;
}

/// powrprof as `WakeTimer` calls it.
pub trait PowerSettings: Send {
    /// `PowerGetActiveScheme(NULL, &scheme)`: its return code, and the scheme where the pointer is not NULL.
    fn active_scheme(&mut self) -> Call<(u32, Option<Scheme>)>;
    /// `PowerReadDCValueIndex` where `dc`, else `PowerReadACValueIndex`: the return code and the value written.
    fn read_value_index(
        &mut self,
        dc: bool,
        scheme: &Scheme,
        subgroup: u128,
        setting: u128,
    ) -> Call<(u32, u32)>;
}

/// kernel32 as `StopFlag` calls it.
pub trait EventKernel: Send {
    /// `CreateEventW(NULL, manual_reset, initial, name)`: the handle, 0 where none.
    fn create_event(&mut self, manual_reset: bool, initial: bool, name: &str) -> Call<Handle>;
    /// `OpenEventW(access, inherit, name)`: the handle, 0 where none.
    fn open_event(&mut self, access: u32, inherit: bool, name: &str) -> Call<Handle>;
    /// `WaitForSingleObject(handle, millis)`.
    fn wait_for_single_object(&mut self, handle: Handle, millis: u32) -> Call<u32>;
    /// `CloseHandle(handle)`.
    fn close_handle(&mut self, handle: Handle) -> Call<bool>;
}

fn handle_of(value: Handle) -> HANDLE {
    HANDLE(value as *mut core::ffi::c_void)
}

fn raw_of(handle: HANDLE) -> Handle {
    handle.0 as Handle
}

fn close(handle: Handle) -> Call<bool> {
    // SAFETY: the caller hands back a handle this process opened through these types.
    Ok(unsafe { CloseHandle(handle_of(handle)) }.is_ok())
}

/// The real kernel32 of [`TimerKernel`]. Built only by the product's own entry points.
#[derive(Debug, Default)]
pub struct SystemTimer;

impl TimerKernel for SystemTimer {
    fn create_waitable_timer(&mut self, access: u32) -> Call<Handle> {
        // SAFETY: no attributes, no name; the handle is the caller's to close.
        Ok(unsafe { CreateWaitableTimerExW(None, PCWSTR::null(), 0, access) }.map_or(0, raw_of))
    }

    fn set_waitable_timer(
        &mut self,
        handle: Handle,
        due: i64,
        period: i32,
        resume: bool,
    ) -> Call<bool> {
        // SAFETY: `due` outlives the call; no completion routine.
        Ok(
            unsafe { SetWaitableTimer(handle_of(handle), &due, period, None, None, resume) }
                .is_ok(),
        )
    }

    fn cancel_waitable_timer(&mut self, handle: Handle) -> Call<bool> {
        // SAFETY: a timer handle this process made.
        Ok(unsafe { CancelWaitableTimer(handle_of(handle)) }.is_ok())
    }

    fn close_handle(&mut self, handle: Handle) -> Call<bool> {
        close(handle)
    }

    fn system_power_status(&mut self) -> Call<Option<u8>> {
        let mut status = SYSTEM_POWER_STATUS::default();
        // SAFETY: `status` is a valid out parameter.
        Ok(unsafe { GetSystemPowerStatus(&mut status) }
            .ok()
            .map(|()| status.ACLineStatus))
    }

    fn local_free(&mut self, scheme: &Scheme) -> Call<()> {
        // SAFETY: the pointer PowerGetActiveScheme allocated, freed once.
        unsafe {
            let _ = LocalFree(Some(HLOCAL(scheme.pointer as *mut core::ffi::c_void)));
        }
        Ok(())
    }
}

/// The real powrprof of [`PowerSettings`]. Reads only.
#[derive(Debug, Default)]
pub struct SystemPower;

impl PowerSettings for SystemPower {
    fn active_scheme(&mut self) -> Call<(u32, Option<Scheme>)> {
        let mut pointer: *mut GUID = core::ptr::null_mut();
        // SAFETY: an out pointer; the GUID it receives is freed by `local_free`.
        let code = unsafe { PowerGetActiveScheme(None, &mut pointer) }.0;
        if pointer.is_null() {
            return Ok((code, None));
        }
        // SAFETY: a non-NULL pointer PowerGetActiveScheme wrote.
        let guid = unsafe { *pointer }.to_u128();
        Ok((
            code,
            Some(Scheme {
                pointer: pointer as usize,
                guid,
            }),
        ))
    }

    fn read_value_index(
        &mut self,
        dc: bool,
        scheme: &Scheme,
        subgroup: u128,
        setting: u128,
    ) -> Call<(u32, u32)> {
        let scheme_guid = GUID::from_u128(scheme.guid);
        let subgroup = GUID::from_u128(subgroup);
        let setting = GUID::from_u128(setting);
        let mut value = 0u32;
        // SAFETY: every GUID and the out value outlive the call.
        let code = unsafe {
            if dc {
                PowerReadDCValueIndex(
                    None,
                    Some(&scheme_guid),
                    Some(&subgroup),
                    Some(&setting),
                    &mut value,
                )
            } else {
                PowerReadACValueIndex(
                    None,
                    Some(&scheme_guid),
                    Some(&subgroup),
                    Some(&setting),
                    &mut value,
                )
                .0
            }
        };
        Ok((code, value))
    }
}

/// The real kernel32 of [`EventKernel`]. Built only by the product's own entry points.
#[derive(Debug, Default)]
pub struct SystemEvents;

impl EventKernel for SystemEvents {
    fn create_event(&mut self, manual_reset: bool, initial: bool, name: &str) -> Call<Handle> {
        let name = wide(name);
        // SAFETY: `name` is NUL-terminated and outlives the call.
        Ok(
            unsafe { CreateEventW(None, manual_reset, initial, PCWSTR(name.as_ptr())) }
                .map_or(0, raw_of),
        )
    }

    fn open_event(&mut self, access: u32, inherit: bool, name: &str) -> Call<Handle> {
        let name = wide(name);
        // SAFETY: `name` is NUL-terminated and outlives the call.
        Ok(unsafe {
            OpenEventW(
                SYNCHRONIZATION_ACCESS_RIGHTS(access),
                inherit,
                PCWSTR(name.as_ptr()),
            )
        }
        .map_or(0, raw_of))
    }

    fn wait_for_single_object(&mut self, handle: Handle, millis: u32) -> Call<u32> {
        // SAFETY: a handle this process holds.
        Ok(unsafe { WaitForSingleObject(handle_of(handle), millis) }.0)
    }

    fn close_handle(&mut self, handle: Handle) -> Call<bool> {
        close(handle)
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn nothing_here_suspends_shuts_down_or_writes_a_power_setting() {
        let source = include_str!("wake.rs");
        for name in [
            ["Set", "SuspendState"].concat(),
            ["Exit", "WindowsEx"].concat(),
            ["Initiate", "SystemShutdown"].concat(),
            ["PowerWrite", "ACValueIndex"].concat(),
            ["PowerWrite", "DCValueIndex"].concat(),
            ["PowerSet", "ActiveScheme"].concat(),
        ] {
            assert!(!source.contains(&name), "{name}");
        }
    }
}
