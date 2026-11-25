//! The product's local clock: `time.localtime` and `time.mktime` as CPython calls them on Windows (fix5's note 3,
//! moved here from car-policy by Integration 6: D3, the C runtime's reading of Windows' zone is a Windows call).
//!
//! car-machine holds the trait ([`LocalClock`]); car-policy's quiet hours and postponements, car-engine's `Given::local`
//! and car-control's `Host::local_clock` take it as a parameter, and the binaries hand them [`Crt`].

use car_machine::localclock::{LocalClock, Tm};
use car_machine::pyval::Py;

/// The product's clock: Windows' C runtime, as CPython's `time.localtime` and `time.mktime` call it on Windows
/// (`_localtime64_s` and `_mktime64` of the UCRT every Rust program on Windows links, as car-brand's `erfc` is), so
/// the zone, its summer time and its limits (no time before 1970, none after 3000-12-31) are the ones the reference
/// reads, whatever they are on the PC. The diff holds it to the reference interpreter's own `time` module
/// (`diffs_classify_policy.py`, the zone `"local"`).
#[derive(Clone, Copy, Debug, Default)]
pub struct Crt;

#[cfg(windows)]
mod crt {
    use super::{Crt, LocalClock, Py, Tm};

    /// The C runtime's `struct tm`: nine `int`s.
    #[repr(C)]
    #[derive(Clone, Copy, Default)]
    struct CTm {
        tm_sec: i32,
        tm_min: i32,
        tm_hour: i32,
        tm_mday: i32,
        tm_mon: i32,
        tm_year: i32,
        tm_wday: i32,
        tm_yday: i32,
        tm_isdst: i32,
    }

    unsafe extern "C" {
        fn _localtime64_s(tm: *mut CTm, time: *const i64) -> i32;
        fn _mktime64(tm: *mut CTm) -> i64;
    }

    /// 2^63: CPython's range check of a float for `time_t` is `-2^63 <= x < 2^63` (`_PyTime_ObjectToTime_t`).
    const TIME_T_END: f64 = 9_223_372_036_854_775_808.0;

    impl LocalClock for Crt {
        fn localtime(&self, seconds: f64) -> Py<Tm> {
            // `_PyTime_ObjectToTime_t(seconds, ROUND_FLOOR)`: a NaN is a ValueError, a float past time_t an
            // OverflowError; `localtime_s`'s refusal (before 1970, past 3000) is an OSError.
            if seconds.is_nan() {
                return Err("ValueError");
            }
            let whole = seconds.floor();
            if !(-TIME_T_END..TIME_T_END).contains(&whole) {
                return Err("OverflowError");
            }
            let time = whole as i64;
            let mut tm = CTm::default();
            // SAFETY: both pointers are to live locals of the types the UCRT declares; it writes only `tm`.
            if unsafe { _localtime64_s(&mut tm, &time) } != 0 {
                return Err("OSError");
            }
            Ok(Tm {
                year: i64::from(tm.tm_year) + 1900,
                mon: i64::from(tm.tm_mon) + 1,
                mday: i64::from(tm.tm_mday),
                hour: i64::from(tm.tm_hour),
                min: i64::from(tm.tm_min),
                sec: i64::from(tm.tm_sec),
                wday: (i64::from(tm.tm_wday) + 6) % 7,
            })
        }

        fn mktime(&self, year: i64, mon: i64, mday: i64, hour: i64, min: i64, sec: i64) -> Py<f64> {
            // `gettmarg`: each field an `int` ("signed integer is greater than maximum" is an OverflowError), the year
            // from 1900, the month from 0, `tm_isdst` -1; then `tm_wday` -1 as the sentinel `time_mktime` checks.
            let int = |value: i64| i32::try_from(value).map_err(|_| "OverflowError");
            let year = int(year)?;
            if year < i32::MIN + 1900 {
                return Err("OverflowError");
            }
            let mut tm = CTm {
                tm_sec: int(sec)?,
                tm_min: int(min)?,
                tm_hour: int(hour)?,
                tm_mday: int(mday)?,
                tm_mon: int(mon)?.wrapping_sub(1),
                tm_year: year - 1900,
                tm_wday: -1,
                tm_yday: -1,
                tm_isdst: -1,
            };
            // SAFETY: a pointer to a live local `struct tm`, which `_mktime64` normalises in place.
            let time = unsafe { _mktime64(&mut tm) };
            if time == -1 && tm.tm_wday == -1 {
                return Err("OverflowError");
            }
            Ok(time as f64)
        }
    }
}
