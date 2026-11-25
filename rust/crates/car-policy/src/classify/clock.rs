//! The local clock, as quiet hours, a postponement and a reset time read it: `time.localtime` and `time.mktime`.
//!
//! The Python reads Windows' own conversion through the C runtime; that is a Windows call, and every Windows call
//! is car-platform's (D3). So the policy takes the clock as a parameter, as `quiet.py` already does
//! (`localtime=`, `mktime=`), and car-platform (or a test's zone) answers it.

use car_machine::pyval::Py;

/// `time.struct_time`'s fields the policy reads.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Tm {
    pub year: i64,
    /// 1 to 12.
    pub mon: i64,
    /// 1 to 31.
    pub mday: i64,
    pub hour: i64,
    pub min: i64,
    pub sec: i64,
    /// Monday is 0 (`tm_wday`).
    pub wday: i64,
}

/// `time.localtime(seconds)` and `time.mktime(tuple)` of one zone.
pub trait LocalClock {
    /// `time.localtime(seconds)`: the error is the class of the exception it raises (`OSError`, `OverflowError`).
    fn localtime(&self, seconds: f64) -> Py<Tm>;
    /// `time.mktime((year, month, day, hour, minute, second, 0, 0, -1))`, the fields carried over as the C runtime
    /// carries them (a day past the month's end is the next month's), the summer time the zone's own.
    fn mktime(&self, year: i64, mon: i64, mday: i64, hour: i64, min: i64, sec: i64) -> Py<f64>;
    /// `time.localtime(None)`: the clock's own time now, `time(NULL)`'s whole seconds.
    fn localtime_now(&self) -> Py<Tm> {
        let seconds = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |since| since.as_secs());
        self.localtime(seconds as f64)
    }
}

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
