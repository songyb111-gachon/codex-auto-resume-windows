//! The pinned zone a stand-in host reads a continuation's `{reset_time}` on (`time.localtime`, `time.mktime`).
//!
//! The product's clock is car-platform's `localclock::Crt` (the C runtime's, as the reference's), which `SystemHost`
//! answers. `UtcClock` is the zone with no offset, the one the reference's golden installation pins (`make_screenshots`
//! and `tests/rustdiff/bridgeworld.py` patch `time.localtime` to `gmtime`): the differential harness's `WorldHost` hands
//! it in so both sides answer for one machine.

use car_machine::pyval::Py;
use car_policy::classify::clock::{LocalClock, Tm};

/// The last second `time.localtime` takes on this platform (year 3000).
const LAST_SECOND: f64 = 32_503_680_000.0;

/// The zone with no offset and no summer time.
pub struct UtcClock;

fn civil(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (y + i64::from(m <= 2), m, d)
}

fn days_from(y: i64, m: i64, d: i64) -> i64 {
    let y = y - i64::from(m <= 2);
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (m + if m > 2 { -3 } else { 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

impl LocalClock for UtcClock {
    fn localtime(&self, t: f64) -> Py<Tm> {
        if t.is_nan() {
            return Err("ValueError");
        }
        if t.is_infinite() {
            return Err("OverflowError");
        }
        if !(0.0..=LAST_SECOND).contains(&t) {
            return Err("OSError");
        }
        let t = t.floor() as i64;
        let (days, rest) = (t.div_euclid(86400), t.rem_euclid(86400));
        let (year, mon, mday) = civil(days);
        Ok(Tm {
            year,
            mon,
            mday,
            hour: rest / 3600,
            min: rest % 3600 / 60,
            sec: rest % 60,
            wday: (days + 3).rem_euclid(7),
        })
    }

    fn mktime(&self, year: i64, mon: i64, mday: i64, hour: i64, min: i64, sec: i64) -> Py<f64> {
        let year = year + (mon - 1).div_euclid(12);
        let mon = (mon - 1).rem_euclid(12) + 1;
        let local = (days_from(year, mon, 1) + mday - 1) * 86400 + hour * 3600 + min * 60 + sec;
        if !(0.0..=LAST_SECOND).contains(&(local as f64)) {
            return Err("OverflowError");
        }
        Ok(local as f64)
    }
}
