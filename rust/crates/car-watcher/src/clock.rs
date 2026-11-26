//! The clocks the watcher reads: `time.time()`, `time.monotonic()`, and the local zone its log lines are stamped in
//! (`logging`'s `time.localtime`, car-platform's C runtime through car-machine's `LocalClock`).

use car_machine::localclock::LocalClock;

/// `time.time()`.
pub fn wall() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0.0, |since| since.as_secs_f64())
}

/// `time.monotonic()`, from one start of this process.
pub fn monotonic() -> f64 {
    use std::sync::OnceLock;
    static START: OnceLock<std::time::Instant> = OnceLock::new();
    let start = START.get_or_init(std::time::Instant::now);
    // A large offset, so a value never reads as zero or as a time before the first look (`float("-inf")` aside).
    1_000_000.0 + start.elapsed().as_secs_f64()
}

fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = year.div_euclid(400);
    let yoe = year - era * 400;
    let mp = (month + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// The logbook's clock: the time now from `now`, the zone's offset from `zone`'s `localtime`.
pub struct LogClock {
    pub now: Box<dyn Fn() -> f64 + Send + Sync>,
    pub zone: Box<dyn LocalClock + Send + Sync>,
}

impl LogClock {
    /// This PC: the wall clock and the C runtime's zone.
    pub fn here() -> LogClock {
        LogClock {
            now: Box::new(wall),
            zone: Box::new(car_platform::localclock::Crt),
        }
    }
}

impl car_config::logbook::Clock for LogClock {
    fn now(&self) -> f64 {
        (self.now)()
    }

    fn utc_offset(&self, seconds: i64) -> Option<i32> {
        let tm = self.zone.localtime(seconds as f64).ok()?;
        let local = days_from_civil(tm.year, tm.mon, tm.mday) * 86_400
            + tm.hour * 3600
            + tm.min * 60
            + tm.sec;
        i32::try_from(local - seconds).ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn civil_days() {
        assert_eq!(days_from_civil(1970, 1, 1), 0);
        assert_eq!(days_from_civil(2026, 11, 26), 20_418);
        assert_eq!(days_from_civil(2000, 3, 1), 11_017);
    }
}
