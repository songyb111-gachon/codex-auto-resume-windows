//! Usage and token analytics (`usage_analytics`, v0.6.20): how many tokens each project used a day, and at what pace a
//! usage window fills - shown on the Advanced features page, never acted on (seat S7.2e2, `engine/analytics.py`).
//!
//! At P8, at most every INGEST_EVERY and only as an errand, it reads what the watched Codex homes' rollouts added since
//! the last pass (`codex::tokens`): at most FILE_BYTES of one file and PASS_BYTES in all, no longer than PASS_SECONDS,
//! newest first. What it read goes into token_days and token_files under the conversation's project key: core's own
//! (Codex's project id, else the folder) cut to 16 hex digits, else the digest of the folder the rollout's first line
//! names, else none. Where MTOK failed on the Codex in force no rollout is read (the narrower route: lifetime totals,
//! read when the Dashboard asks). The pace is the meter's samples' (`pace`). Nothing about recovery changes (E11).

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_machine::localclock::LocalClock;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::supervise::{Bound, field, lock, number, raised, word};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::tokens;
use crate::vocabulary::OptionKey;

pub const CAPABILITY: &str = "usage_analytics";
pub const INGEST_EVERY: f64 = 600.0;
pub const PASS_SECONDS: f64 = 2.0;
pub const DAYS: [i64; 3] = [7, 30, 90];
pub const DEFAULT_DAYS: i64 = 7;
pub const PACE_SECONDS: f64 = 3600.0;
pub const PACE_SAMPLES: usize = 3;
pub const PACE_SPAN: f64 = 900.0;
pub const INGESTED: &str = "ingested";
pub const CAPPED: &str = "capped";
pub const UNREADABLE: &str = "unreadable";
/// MTOK, the measurement whose verdict picks the route.
pub const MTOK: &str = "mtok";

/// `route(verdict)`: "lifetime" where MTOK failed, else "per_day".
pub fn route(verdict: &Value) -> &'static str {
    if *verdict == word("fail") {
        "lifetime"
    } else {
        "per_day"
    }
}

/// `round(x, 1)`: CPython's correctly rounded result (the shortest repr of the double nearest x * 10, divided back).
fn round1(value: f64) -> f64 {
    if !value.is_finite() {
        return value;
    }
    // CPython rounds through the decimal string of the exact double: format with 1 place does the same rounding of
    // the exact binary value, half to even on an exact tie.
    format!("{value:.1}").parse().unwrap_or(value)
}

/// `pace(samples, row, now)`: one usage window's share now, the change over the last hour, and when it would be full
/// at this pace (`eta`) - given only with enough samples, a rising slope, and an answer before the window resets.
pub fn pace(samples: &[Value], row: &Value, now: f64) -> Result<Value, &'static str> {
    let used = field(row, "used_percent").clone();
    let reset = field(row, "reset_at").clone();
    let mut found = Map::new();
    found.insert("bucket".into(), field(row, "bucket").clone());
    found.insert("minutes".into(), field(row, "minutes").clone());
    found.insert("used".into(), used.clone());
    found.insert("reset_at".into(), reset.clone());
    found.insert("change_hour".into(), Value::Null);
    found.insert("eta".into(), Value::Null);
    found.insert("enough".into(), Value::Bool(false));
    let mut start = now - PACE_SECONDS;
    let int = |value: &Value| match value {
        Value::Int(number) => number.as_i64(),
        _ => None,
    };
    if let (Some(reset), Some(minutes)) = (int(&reset), int(field(row, "minutes"))) {
        start = start.max((reset - minutes * 60) as f64);
    }
    let mut points: Vec<(f64, f64)> = Vec::new();
    for sample in samples {
        if !car_store::value::py_eq(field(sample, "bucket"), field(row, "bucket"))
            || !car_store::value::py_eq(field(sample, "minutes"), field(row, "minutes"))
        {
            continue;
        }
        let at = match sample {
            Value::Object(map) => map.get("at").cloned().unwrap_or(Value::Int(0.into())),
            _ => return Err("AttributeError"),
        };
        let at = number(&at).ok_or("TypeError")?;
        if !(start <= at && at <= now) {
            continue;
        }
        let reset_ok = matches!(reset, Value::Null) || {
            let held = field(sample, "reset_at");
            matches!(held, Value::Null) || car_store::value::py_eq(held, &reset)
        };
        if !reset_ok {
            continue;
        }
        // `float(sample["used_percent"])`.
        let share = match sample {
            Value::Object(map) => map.get("used_percent").ok_or("KeyError")?,
            _ => return Err("TypeError"),
        };
        let share = match share {
            Value::Bool(flag) => f64::from(u8::from(*flag)),
            other => number(other).ok_or("TypeError")?,
        };
        points.push((at, share));
    }
    points.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let used_number = match &used {
        Value::Int(_) | Value::Float(_) => number(&used),
        Value::Bool(flag) => Some(f64::from(u8::from(*flag))),
        _ => None,
    };
    if let (Some(first), Some(used)) = (points.first(), used_number) {
        found.insert("change_hour".into(), Value::Float(round1(used - first.1)));
    }
    if points.len() < PACE_SAMPLES || points[points.len() - 1].0 - points[0].0 < PACE_SPAN {
        return Ok(Value::Object(found));
    }
    found.insert("enough".into(), Value::Bool(true));
    let count = points.len() as f64;
    let mean_t = points.iter().map(|(at, _)| at).sum::<f64>() / count;
    let mean_u = points.iter().map(|(_, share)| share).sum::<f64>() / count;
    let spread: f64 = points.iter().map(|(at, _)| (at - mean_t).powi(2)).sum();
    if spread <= 0.0 {
        return Ok(Value::Object(found));
    }
    let slope = points
        .iter()
        .map(|(at, share)| (at - mean_t) * (share - mean_u))
        .sum::<f64>()
        / spread;
    let Some(used) = used_number.filter(|_| slope > 0.0) else {
        return Ok(Value::Object(found));
    };
    let eta = now + (100.0 - used).max(0.0) / slope;
    if let Some(reset) = int(&reset)
        && eta >= reset as f64
    {
        return Ok(Value::Object(found));
    }
    found.insert("eta".into(), Value::Int((eta.trunc() as i64).into()));
    Ok(Value::Object(found))
}

// ---------------------------------------------------------------------------------------------- the seams
/// Core's reader of one home, for a conversation's project key (`LocalSource(home).project_key(thread)`).
pub trait ProjectSource {
    fn project_key(&mut self, thread: &str) -> Result<Value, Raised>;
}

impl ProjectSource for car_codex::source::LocalSource {
    fn project_key(&mut self, thread: &str) -> Result<Value, Raised> {
        match car_codex::source::LocalSource::project_key(self, thread) {
            Ok(found) => Ok(found.map_or(Value::Null, |key| word(&key))),
            Err(_) => Err(Raised::new("CodexError")),
        }
    }
}

/// The Codex homes to read (`tokens.watched_homes(paths)`).
pub type Homes = Box<dyn Fn() -> Result<Vec<String>, Raised> + Send + Sync>;
/// `source(home)`: core's reader of that home.
pub type Source = Box<dyn Fn(&str) -> Result<Box<dyn ProjectSource>, Raised> + Send + Sync>;
/// The clock a pass measures its own time by (`time.monotonic`).
pub type Clock = Box<dyn Fn() -> f64 + Send + Sync>;
/// The local clock a rollout's days are read by (`time.localtime`).
pub type Local = Box<dyn LocalClock + Send + Sync>;
/// The file system the rollouts are found on.
pub type Os = Arc<dyn car_policy::settings::os::Os + Send + Sync>;

/// The product's homes: `tokens.watched_homes(paths)` over this process's environment.
pub fn watched(paths: &Paths) -> Vec<String> {
    let env = |name: &str| std::env::var(name).ok();
    let config_os = car_config::Os::here(false, Arc::new(super::supervise::PlatformLinks));
    tokens::watched_homes(
        Some(&paths.home),
        Some(std::path::Path::new(&paths.settings_file)),
        &env,
        &config_os,
        &car_codex::system::PolicyOs,
    )
}

/// The product's source: car-codex's `LocalSource` of that home.
pub fn local_source(home: &str) -> Result<Box<dyn ProjectSource>, Raised> {
    car_codex::source::LocalSource::new(Arc::new(car_codex::system::PolicyOs), home, None)
        .map(|source| Box::new(source) as Box<dyn ProjectSource>)
        .map_err(|_| Raised::new("CodexError"))
}

/// `time.monotonic()`.
pub fn monotonic() -> f64 {
    static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
    START
        .get_or_init(std::time::Instant::now)
        .elapsed()
        .as_secs_f64()
}

// ---------------------------------------------------------------------------------------------- the code
struct Inner {
    bound: Mutex<Option<Bound>>,
    homes: Homes,
    source: Source,
    clock: Clock,
    local: Local,
    os: Os,
    looked: Mutex<Option<f64>>,
}

/// `UsageAnalytics(paths, homes=..., source=..., clock=..., local=...)`: its P8 errand, a pass over the rollouts.
#[derive(Clone)]
pub struct UsageAnalytics {
    inner: Arc<Inner>,
}

impl UsageAnalytics {
    pub fn new(homes: Homes, source: Source, clock: Clock, local: Local, os: Os) -> UsageAnalytics {
        UsageAnalytics {
            inner: Arc::new(Inner {
                bound: Mutex::new(None),
                homes,
                source,
                clock,
                local,
                os,
                looked: Mutex::new(None),
            }),
        }
    }

    /// `bind(scoped)` with a harness's own state.
    pub fn bind_to(&self, bound: Bound) {
        *lock(&self.inner.bound) = Some(bound);
    }

    /// P8: the errand, at most every INGEST_EVERY (by its own memory and its stamp); DEFER otherwise.
    pub fn ticked(&self) -> Spoke {
        let Some(bound) = lock(&self.inner.bound).clone() else {
            return Ok(Said::Defer);
        };
        let looked = *lock(&self.inner.looked);
        let due = bound.with(|scoped| -> Result<bool, ()> {
            let now = scoped.now();
            if let Some(looked) = looked
                && 0.0 <= now - looked
                && now - looked < INGEST_EVERY
            {
                return Ok(false);
            }
            let last = scoped
                .stamped(&word(OptionKey::LastIngest.as_str()))
                .map_err(|_| ())?;
            if let Value::Int(last) = last
                && let Some(last) = last.as_i64()
                && 0.0 <= now - last as f64
                && now - (last as f64) < INGEST_EVERY
            {
                return Ok(false);
            }
            Ok(true)
        });
        match due {
            Some(Ok(true)) => Ok(Said::Errand(Box::new(AnalyticsErrand(self.clone())))),
            _ => Ok(Said::Defer),
        }
    }

    /// `_project(home, thread, fallback)`: core's key cut to 16, else the rollout's own, else None.
    fn project(&self, home: &str, thread: &str, fallback: &Option<String>) -> Option<String> {
        let key = (self.inner.source)(home)
            .and_then(|mut source| source.project_key(thread))
            .unwrap_or(Value::Null);
        match key {
            Value::Str(text) => {
                let text = text.as_str().unwrap_or_default().to_owned();
                if text.chars().count() >= 16 {
                    Some(text.chars().take(16).collect())
                } else {
                    fallback.clone()
                }
            }
            _ => fallback.clone(),
        }
    }

    /// `ingest()`: the errand's pass.
    pub fn ingest(&self) -> Result<(), Raised> {
        let bound = lock(&self.inner.bound)
            .clone()
            .ok_or_else(|| Raised::new("AttributeError"))?;
        let on = bound
            .with(|scoped| scoped.handle().is_on())
            .ok_or_else(|| Raised::new("StateError"))?;
        if !on {
            return Ok(());
        }
        let now = bound.now()?;
        *lock(&self.inner.looked) = Some(now);
        let failed = bound
            .with(|scoped| scoped.failed(&word(MTOK)))
            .unwrap_or(false);
        let stamp_last = |bound: &Bound| {
            let whole = super::anchor::whole(now).map_err(Raised::new)?;
            bound
                .read(|scoped| {
                    scoped.stamp(
                        &word(OptionKey::LastIngest.as_str()),
                        &Value::Int(whole.max(1).into()),
                    )
                })
                .map(|_| ())
        };
        if failed {
            // The narrower route (MTOK failed): no rollout is read.
            return stamp_last(&bound);
        }
        let started = (self.inner.clock)();
        let mut budget = tokens::PASS_BYTES;
        let known = bound.read(|scoped| scoped.handle().analytics_files())?;
        let mut projects: HashMap<String, Option<String>> = HashMap::new();
        let (mut capped, mut unreadable, mut ingested) = (false, false, false);
        let homes = (self.inner.homes)()?;
        let found = tokens::rollouts(self.inner.os.as_ref(), &homes, now, tokens::KEEP_DAYS)
            .map_err(Raised::new)?;
        for rollout in found {
            let row = match known.get(rollout.key.as_str()) {
                Some(Value::Object(map)) => Some(map.clone()),
                _ => None,
            };
            if tokens::unchanged(&rollout, row.as_ref()).map_err(Raised::new)? {
                continue;
            }
            if budget <= 0 || (self.inner.clock)() - started >= PASS_SECONDS {
                capped = true;
                break;
            }
            let read = tokens::read(&rollout, row.as_ref(), budget, self.inner.local.as_ref())
                .map_err(Raised::new)?;
            budget -= read.consumed;
            let Some(thread) = read
                .thread_id
                .clone()
                .filter(|_| read.outcome != tokens::UNREADABLE)
            else {
                // Tried again once it changes, or at the next pass.
                unreadable = true;
                continue;
            };
            if read.outcome == tokens::CAPPED {
                capped = true;
            }
            let mut key = projects.get(&thread).cloned().flatten();
            if key.is_none() && !read.days.is_empty() {
                key = self.project(&rollout.home, &thread, &read.project_key);
                projects.insert(thread.clone(), key.clone());
            }
            let mut days = Map::new();
            for (day, numbers) in &read.days {
                days.insert(
                    day.as_str().into(),
                    Value::Array(numbers.iter().map(|n| Value::Int((*n).into())).collect()),
                );
            }
            let written = bound.with(|scoped| -> Result<i64, crate::state::Error> {
                scoped.handle().analytics_ingest()?;
                scoped.state.ingest_file(
                    &word(&rollout.key),
                    &word(&thread),
                    &Value::Int(read.size.into()),
                    &Value::Int(read.offset.into()),
                    &Value::Int((read.changed_ns as i64).into()),
                    &Value::Object(days),
                    &key.as_deref().map_or(Value::Null, word),
                    &Value::Float(now),
                )
            });
            if !matches!(written, Some(Ok(_))) {
                unreadable = true;
                continue;
            }
            ingested = ingested || !read.days.is_empty();
        }
        stamp_last(&bound)?;
        for (flag, code) in [
            (ingested, INGESTED),
            (capped, CAPPED),
            (unreadable, UNREADABLE),
        ] {
            if flag {
                let _ = bound.with(|scoped| scoped.count(&word(code)));
            }
        }
        Ok(())
    }
}

struct AnalyticsErrand(UsageAnalytics);

impl Errand for AnalyticsErrand {
    fn run(&self, _view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        self.0
            .ingest()
            .map(|()| Value::Null)
            .map_err(|_| HookFailed)
    }
}

impl Code for UsageAnalytics {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.bind_to(Bound::of(binding));
        Some(Ok(()))
    }

    fn tick(&mut self, _view: &dyn View) -> Spoke {
        self.ticked()
    }
}

/// A state error as the reference raises it (for the probe).
pub fn class_of(error: &crate::state::Error) -> Raised {
    raised(error)
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    let homes = paths.clone();
    Some(Box::new(UsageAnalytics::new(
        Box::new(move || Ok(watched(&homes))),
        Box::new(local_source),
        Box::new(monotonic),
        Box::new(car_platform::localclock::Crt),
        Arc::new(car_codex::system::PolicyOs),
    )))
}
