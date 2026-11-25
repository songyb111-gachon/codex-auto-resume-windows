//! `win/waketimer.py`: a waitable timer that wakes this PC, and whether Windows allows one to (wake_for_reset, v0.6.19).
//!
//! [`WakeTimer::set`] makes one unnamed waitable timer of this process's own and sets it for an absolute time with
//! fResume; [`WakeTimer::cancel`] takes it back; [`WakeTimer::close`] closes its handle, and with it the timer.
//! [`WakeTimer::allowed`] reads the active scheme's *Allow wake timers* for the power source in use now: only 1,
//! Enable, allows it. Read, never written (F1).
//!
//! The Windows calls are car-platform's `wake` traits (D3): the product hands in `SystemTimer`/`SystemPower`, a test
//! a stand-in that records the calls. No real timer is set and no power setting read in a test.

use car_platform::wake::{
    GUID_ALLOW_RTC_WAKE, GUID_SLEEP_SUBGROUP, Handle, PowerSettings, Raised, TimerKernel,
};

pub const TIMER_ALL_ACCESS: u32 = 0x1F0003;
/// 100-nanosecond intervals from 1601-01-01 to the Unix epoch.
pub const EPOCH_AS_FILETIME: i64 = 116_444_736_000_000_000;
pub const ENABLE: u32 = 1;
/// ACLineStatus: 0 on battery, 1 on mains, 255 not known (read as mains).
pub const ON_BATTERY: u8 = 0;

/// `float(x) * 10_000_000` rounded half to even, as an exact integer taken modulo 2**64 (ctypes' `c_longlong` keeps
/// the low 64 bits of whatever Python integer it is handed). None where Python's `round` raises (inf, nan).
fn wrapped_ticks(seconds: f64) -> Option<i64> {
    let ticks = (seconds * 10_000_000.0).round_ties_even();
    if !ticks.is_finite() {
        return None;
    }
    if ticks.abs() < 9_223_372_036_854_775_808.0 {
        return Some(ticks as i64);
    }
    // |ticks| >= 2**63: an integer m * 2**e with e >= 11; its low 64 bits.
    let bits = ticks.to_bits();
    let mantissa = u128::from((bits & ((1u64 << 52) - 1)) | (1u64 << 52));
    let exponent = ((bits >> 52) & 0x7ff) as i32 - 1075;
    let low = if exponent >= 64 {
        0u64
    } else {
        (mantissa << exponent) as u64
    };
    let low = if ticks < 0.0 { low.wrapping_neg() } else { low };
    Some(low as i64)
}

/// `filetime(epoch_seconds)`: an absolute due time as SetWaitableTimer takes one, as the c_longlong it is passed in.
pub fn filetime(epoch_seconds: f64) -> Option<i64> {
    wrapped_ticks(epoch_seconds).map(|ticks| ticks.wrapping_add(EPOCH_AS_FILETIME))
}

/// One waitable timer of this process's own, set to wake the PC, and the question whether Windows allows it.
pub struct WakeTimer {
    kernel: Box<dyn TimerKernel>,
    power: Box<dyn PowerSettings>,
    handle: Option<Handle>,
    /// The time it is set for, in Unix seconds, or None.
    pub due: Option<f64>,
}

impl WakeTimer {
    pub fn new(kernel: Box<dyn TimerKernel>, power: Box<dyn PowerSettings>) -> WakeTimer {
        WakeTimer {
            kernel,
            power,
            handle: None,
            due: None,
        }
    }

    /// `on_battery()`: what `GetSystemPowerStatus` says, False where it fails. A raise is the caller's.
    pub fn on_battery(&mut self) -> Result<bool, Raised> {
        Ok(self.kernel.system_power_status()? == Some(ON_BATTERY))
    }

    /// Whether Windows' Allow wake timers is Enable for the power source in use now. Anything that cannot be read is
    /// not allowed.
    pub fn allowed(&mut self) -> bool {
        self.read_allowed().unwrap_or(false)
    }

    fn read_allowed(&mut self) -> Result<bool, Raised> {
        let battery = self.on_battery()?;
        let (code, scheme) = self.power.active_scheme()?;
        let Some(scheme) = scheme.filter(|_| code == 0) else {
            return Ok(false);
        };
        // The scheme is freed whatever the read did (the reference's `finally`).
        let read =
            self.power
                .read_value_index(battery, &scheme, GUID_SLEEP_SUBGROUP, GUID_ALLOW_RTC_WAKE);
        self.kernel.local_free(&scheme)?;
        let (found, value) = read?;
        Ok(found == 0 && value == ENABLE)
    }

    /// The timer set, or moved, to wake the PC at `epoch_seconds`. Whether Windows took it.
    pub fn set(&mut self, epoch_seconds: f64) -> bool {
        if self.arm(epoch_seconds) != Ok(true) {
            return false;
        }
        self.due = Some(epoch_seconds);
        true
    }

    fn arm(&mut self, epoch_seconds: f64) -> Result<bool, Raised> {
        let handle = match self.handle {
            Some(handle) => handle,
            None => {
                let made = self.kernel.create_waitable_timer(TIMER_ALL_ACCESS)?;
                self.handle = (made != 0).then_some(made);
                match self.handle {
                    Some(handle) => handle,
                    None => return Ok(false),
                }
            }
        };
        let due = filetime(epoch_seconds).ok_or(Raised)?;
        self.kernel.set_waitable_timer(handle, due, 0, true)
    }

    /// The timer taken back, where one is set. Whether one was.
    pub fn cancel(&mut self) -> bool {
        if self.due.is_none() {
            return false;
        }
        if let Some(handle) = self.handle {
            let _ = self.kernel.cancel_waitable_timer(handle);
        }
        self.due = None;
        true
    }

    /// Its handle closed, and with it the timer, as when this process ends.
    pub fn close(&mut self) {
        if let Some(handle) = self.handle {
            let _ = self.kernel.close_handle(handle);
        }
        self.handle = None;
        self.due = None;
    }
}

#[cfg(test)]
mod tests {
    use super::filetime;

    #[test]
    fn filetime_rounds_half_to_even_and_wraps_as_c_longlong() {
        assert_eq!(filetime(0.0), Some(116_444_736_000_000_000));
        assert_eq!(filetime(1.5), Some(116_444_736_015_000_000));
        assert_eq!(filetime(f64::INFINITY), None);
        assert_eq!(filetime(f64::NAN), None);
        // 2**80 seconds: 2**80 * 1e7 = 78125 * 2**87, whose low 64 bits are 0; ctypes keeps the epoch alone.
        assert_eq!(filetime(2f64.powi(80)), Some(116_444_736_000_000_000));
    }
}
