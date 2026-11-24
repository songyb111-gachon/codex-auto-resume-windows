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
}
