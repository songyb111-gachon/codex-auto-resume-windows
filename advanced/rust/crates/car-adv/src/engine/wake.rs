//! Wake this PC for a reset (`wake_for_reset`, v0.6.19): a waitable timer for the earliest reset something waits for
//! (seat S7.2e2, `engine/wake.py`).
//!
//! At P8 - once a tick, as an errand - the watcher finds the earliest time something it waits for falls due: core's
//! waiting usage-limit records (`eligible_at`), the reset actions' pending rules that know when they act (`due_at`),
//! the forced stop's held window (the meter's `paused_reset_at`), and - while window_anchor stands on too - its next
//! occasion and the next look of an occasion it holds open. The earliest, less the lead a person chose (1, 2 or 5
//! minutes), is when a waitable timer of the watcher's own wakes the PC: set, moved, and cancelled when nothing waits,
//! when that time has come, or when Windows does not allow wake timers for the power source in use (the product never
//! changes that setting, F1). A small watch on a thread of its own takes the timer back once the capability no longer
//! stands on, or no tick has come for STALE seconds. The real timer is car-platform `wake`'s, built only where none
//! was handed (never in a test).

use std::sync::{Arc, Mutex};

use car_config::Paths;
use car_machine::json::Value;
use car_machine::vocab_gen::domain_states::WAITING as CORE_WAITING;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::supervise::{Bound, field, lock, word};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::state::sql;
use crate::vocabulary::OptionKey;
use crate::win::waketimer::WakeTimer;

pub const CAPABILITY: &str = "wake_for_reset";
pub const LEADS: [i64; 3] = [1, 2, 5];
pub const DEFAULT_LEAD: i64 = 2;
/// How often the watch looks whether the timer is still wanted, and how long with no tick before it lets go.
pub const WATCH_EVERY: f64 = 15.0;
pub const STALE: f64 = 180.0;
/// How long Windows' answer about wake timers is taken as read.
pub const ASK_EVERY: f64 = 60.0;
pub const USAGE_LIMIT: &str = "usage_limit";
/// Start the 5-hour window early, whose occasions it wakes for too (v0.6.20).
pub const ANCHOR: &str = "window_anchor";

/// `_number(value)`: a positive int or float as a float, else None.
fn positive(value: &Value) -> Option<f64> {
    match value {
        Value::Int(number) => number.as_i64().filter(|n| *n > 0).map(|n| n as f64),
        Value::Float(number) if *number > 0.0 => Some(*number),
        _ => None,
    }
}

// ---------------------------------------------------------------------------------------------- the seams
/// `win/waketimer.WakeTimer`'s shape: `due`, `set`, `cancel`, `allowed`. Each may raise, as a test's may.
pub trait Timer: Send {
    /// The time it is set for, or None.
    fn due(&self) -> Option<f64>;
    /// `bool(timer.set(at))`.
    fn set(&mut self, at: f64) -> Result<bool, Raised>;
    /// `bool(timer.cancel())`.
    fn cancel(&mut self) -> Result<bool, Raised>;
    /// `timer.allowed() is True`.
    fn allowed(&mut self) -> Result<bool, Raised>;
}

impl Timer for WakeTimer {
    fn due(&self) -> Option<f64> {
        self.due
    }
    fn set(&mut self, at: f64) -> Result<bool, Raised> {
        Ok(WakeTimer::set(self, at))
    }
    fn cancel(&mut self) -> Result<bool, Raised> {
        Ok(WakeTimer::cancel(self))
    }
    fn allowed(&mut self) -> Result<bool, Raised> {
        Ok(WakeTimer::allowed(self))
    }
}

/// How the watch's thread is started (`start(target)`).
pub type Start = Box<dyn Fn(Box<dyn FnOnce() + Send>) -> Result<(), Raised> + Send + Sync>;

/// The product's timer: a waitable timer of this process over Windows (never in a test).
pub fn system_timer() -> Box<dyn Timer> {
    Box::new(WakeTimer::new(
        Box::new(car_platform::wake::SystemTimer),
        Box::new(car_platform::wake::SystemPower),
    ))
}

/// The product's start: a daemon thread named `wake-timer`.
pub fn thread_start(target: Box<dyn FnOnce() + Send>) -> Result<(), Raised> {
    std::thread::Builder::new()
        .name("wake-timer".into())
        .spawn(target)
        .map(|_| ())
        .map_err(|_| Raised::new("RuntimeError"))
}

// ---------------------------------------------------------------------------------------------- the code
struct Watch {
    ticked: Option<f64>,
    stale: f64,
    watching: bool,
}

struct Inner {
    bound: Mutex<Option<Bound>>,
    timer: Mutex<Option<Box<dyn Timer>>>,
    make_timer: Box<dyn Fn() -> Box<dyn Timer> + Send + Sync>,
    start: Start,
    watch: Mutex<Watch>,
    /// Windows' last answer and when it was asked (`_allowed`, `_asked`).
    asked: Mutex<(Option<bool>, Option<f64>)>,
}

/// `WakeForReset(paths, timer=..., start=...)`: its P8 errand and the watch beside it.
#[derive(Clone)]
pub struct WakeForReset {
    inner: Arc<Inner>,
}

type Answer<T> = Result<T, Raised>;

impl WakeForReset {
    pub fn new(_paths: Paths, timer: Option<Box<dyn Timer>>, start: Option<Start>) -> WakeForReset {
        WakeForReset {
            inner: Arc::new(Inner {
                bound: Mutex::new(None),
                timer: Mutex::new(timer),
                make_timer: Box::new(system_timer),
                start: start.unwrap_or_else(|| Box::new(thread_start)),
                watch: Mutex::new(Watch {
                    ticked: None,
                    stale: STALE,
                    watching: false,
                }),
                asked: Mutex::new((None, None)),
            }),
        }
    }

    /// `bind(scoped)` with a harness's own state.
    pub fn bind_to(&self, bound: Bound) {
        *lock(&self.inner.bound) = Some(bound);
    }

    fn bound(&self) -> Answer<Bound> {
        lock(&self.inner.bound)
            .clone()
            .ok_or_else(|| Raised::new("AttributeError"))
    }

    /// `self.timer()` and what is asked of it, the timer made where none was handed.
    fn with_timer<R>(&self, f: impl FnOnce(&mut dyn Timer) -> R) -> R {
        let mut held = lock(&self.inner.timer);
        if held.is_none() {
            *held = Some((self.inner.make_timer)());
        }
        f(held.as_mut().expect("made above").as_mut())
    }

    /// The timer's `due` now.
    pub fn due(&self) -> Option<f64> {
        self.with_timer(|timer| timer.due())
    }

    /// P8: the errand, once bound.
    pub fn ticked(&self, _view: &dyn View) -> Spoke {
        if lock(&self.inner.bound).is_none() {
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(WakeErrand(self.clone()))))
    }

    /// The errand's run: `learn_poll`, `earliest` (what cannot be read wakes nothing), `apply`.
    pub fn run(&self, view: &dyn View) -> Answer<()> {
        self.learn_poll(view);
        let due = self.earliest(view).ok().flatten();
        self.apply(due)
    }

    /// `learn_poll(view)`: STALE, or two of the watcher's tick intervals and a look where those are longer.
    pub fn learn_poll(&self, view: &dyn View) {
        let poll = match view.settings() {
            Ok(settings) if !sql::truthy(&settings) => Value::Null,
            Ok(settings @ Value::Object(_)) => field(&settings, "poll_seconds").clone(),
            // `.get` of a value that is not a dict raises: caught.
            _ => Value::Null,
        };
        let mut stale = STALE;
        if let Value::Int(number) = &poll
            && let Some(poll) = number.as_i64()
            && 0 < poll
            && poll <= 3600
        {
            stale = STALE.max(2.0 * poll as f64 + WATCH_EVERY);
        }
        lock(&self.inner.watch).stale = stale;
    }

    /// `earliest(view)`: the earliest time something waits for that is still to come, or None.
    pub fn earliest(&self, view: &dyn View) -> Answer<Option<f64>> {
        let bound = self.bound()?;
        let now = bound.now()?;
        let mut found: Vec<Option<f64>> = Vec::new();
        let rows = view
            .records_in(CORE_WAITING)
            .map_err(|failed| Raised::new(failed.0))?;
        for row in rows {
            let Value::Object(_) = row else {
                return Err(Raised::new("AttributeError"));
            };
            if *field(&row, "category") == word(USAGE_LIMIT) {
                let at = car_machine::domain::public::eligible_at(&row).map_err(Raised::new)?;
                found.push(positive(&at));
            }
        }
        let rules =
            bound.read(|scoped| scoped.state.reset_rules(&Value::Null, &Value::Bool(true)))?;
        for rule in rules {
            found.push(positive(sql::get(&rule, "due_at")));
        }
        let meter = bound.read(|scoped| scoped.state.meter())?;
        for (_, row) in meter {
            let held = sql::get(&row, "paused_reset_at");
            if !matches!(held, Value::Null) && sql::py_eq(held, sql::get(&row, "reset_at")) {
                found.push(positive(held));
            }
        }
        found.push(self.anchor_due(&bound, now));
        Ok(found.into_iter().flatten().filter(|when| *when > now).fold(
            None,
            |least: Option<f64>, when| {
                Some(least.map_or(when, |least| if when < least { when } else { least }))
            },
        ))
    }

    /// `_anchor_due(now)`: window_anchor's next occasion while it stands on, and the next look of an occasion it
    /// holds open: the earlier still ahead, or None.
    fn anchor_due(&self, bound: &Bound, now: f64) -> Option<f64> {
        let anchor = word(ANCHOR);
        let stamp = |key: OptionKey| word(key.as_str());
        let first = bound.with(|scoped| -> Result<Option<Value>, Raised> {
            if !scoped.armed(&anchor) {
                return Ok(None);
            }
            let read = |key: OptionKey| {
                scoped
                    .stamped_of(&anchor, &stamp(key))
                    .map_err(|error| super::supervise::raised(&error))
            };
            let options = scoped
                .options_of(&anchor)
                .map_err(|error| super::supervise::raised(&error))?;
            let next = super::anchor::next_due(
                &Value::Object(options),
                now,
                &read(OptionKey::AnchorSlotDone)?,
                &read(OptionKey::AnchorSeenReset)?,
                &read(OptionKey::AnchorResetDone)?,
                &car_platform::localclock::Crt,
            )
            .map_err(Raised::new)?;
            Ok(Some(next.map_or(Value::Null, |at| Value::Int(at.into()))))
        })?;
        let Ok(Some(first)) = first else {
            return None;
        };
        let mut found = vec![first];
        if let Some(Ok(next)) =
            bound.with(|scoped| scoped.stamped_of(&anchor, &stamp(OptionKey::AnchorNextLook)))
        {
            found.push(next);
        }
        found
            .iter()
            .filter_map(|at| match at {
                Value::Int(number) => number.as_i64().map(|n| n as f64),
                Value::Float(number) => Some(*number),
                _ => None,
            })
            .filter(|at| *at > now)
            .fold(None, |least: Option<f64>, at| {
                Some(least.map_or(at, |least| if at < least { at } else { least }))
            })
    }

    /// `lead()`: the minutes chosen, as a number of minutes (1, 2 or 5; 2 by default).
    pub fn lead(&self) -> Answer<f64> {
        let bound = self.bound()?;
        let options = bound.read(|scoped| scoped.options())?;
        let value = options
            .get(OptionKey::WakeLeadMinutes.as_str())
            .cloned()
            .unwrap_or(Value::Int(DEFAULT_LEAD.into()));
        let chosen = LEADS
            .iter()
            .any(|lead| sql::py_eq(&value, &Value::Int((*lead).into())));
        Ok(if chosen {
            super::supervise::number(&value)
                .or(match value {
                    Value::Bool(flag) => Some(f64::from(u8::from(flag))),
                    _ => None,
                })
                .unwrap_or(DEFAULT_LEAD as f64)
        } else {
            DEFAULT_LEAD as f64
        })
    }

    fn count(&self, bound: &Bound, code: &str) -> Answer<()> {
        bound.read(|scoped| scoped.count(&word(code))).map(|_| ())
    }

    /// `apply(due)`: the timer set for `due` less the lead, moved, or cancelled - and the watch started.
    pub fn apply(&self, due: Option<f64>) -> Answer<()> {
        let bound = self.bound()?;
        let now = bound.now()?;
        lock(&self.inner.watch).ticked = Some(now);
        let wake_at = match due {
            None => None,
            Some(due) => Some(due - 60.0 * self.lead()?),
        };
        // `wake_at is None or wake_at <= now` (a NaN goes on, as in the reference).
        let Some(wake_at) = wake_at.filter(|at| {
            !matches!(
                at.partial_cmp(&now),
                Some(std::cmp::Ordering::Less | std::cmp::Ordering::Equal)
            )
        }) else {
            if self.with_timer(|timer| timer.cancel())? {
                self.count(&bound, "cancelled")?;
            }
            return Ok(());
        };
        if !self.windows_allows(&bound, now)? {
            if self.with_timer(|timer| timer.cancel())? {
                self.count(&bound, "cancelled")?;
            }
            return Ok(());
        }
        let current = self.with_timer(|timer| timer.due());
        if current == Some(wake_at) {
            self.watch();
            return Ok(());
        }
        let first = current.is_none();
        if self.with_timer(|timer| timer.set(wake_at))? {
            if first {
                // A move is not counted: core's next look moves it often.
                self.count(&bound, "set")?;
            }
            self.watch();
        } else if self.with_timer(|timer| timer.cancel())? {
            // A move Windows refused leaves no timer at the old time (seatA:B-M6).
            self.count(&bound, "cancelled")?;
        }
        Ok(())
    }

    /// `_windows_allows(now)`: asked at most once in ASK_EVERY seconds; a change to not allowed counted once.
    fn windows_allows(&self, bound: &Bound, now: f64) -> Answer<bool> {
        let (allowed, asked) = *lock(&self.inner.asked);
        let stale = match asked {
            None => true,
            Some(asked) => !(0.0 <= now - asked && now - asked < ASK_EVERY),
        };
        if !stale {
            return Ok(allowed == Some(true));
        }
        let answer = self.with_timer(|timer| timer.allowed())?;
        if !answer && allowed != Some(false) {
            self.count(bound, "not_allowed")?;
        }
        *lock(&self.inner.asked) = (Some(answer), Some(now));
        Ok(answer)
    }

    fn watch(&self) {
        {
            let mut watch = lock(&self.inner.watch);
            if watch.watching {
                return;
            }
            watch.watching = true;
        }
        let looking = self.clone();
        let target: Box<dyn FnOnce() + Send> = Box::new(move || {
            // A look that raised ends the thread where it stood, as the reference's uncaught raise does.
            while matches!(looking.look(), Ok(true)) {
                std::thread::sleep(std::time::Duration::from_secs_f64(WATCH_EVERY));
            }
        });
        if (self.inner.start)(target).is_err() {
            lock(&self.inner.watch).watching = false;
        }
    }

    /// `look()`: one look of the watch - the timer cancelled where the capability no longer stands on or no tick came
    /// for STALE seconds. Whether to go on looking; the timer's raise on cancelling goes out, as the reference's.
    pub fn look(&self) -> Answer<bool> {
        if self.with_timer(|timer| timer.due()).is_none() {
            lock(&self.inner.watch).watching = false;
            return Ok(false);
        }
        let (ticked, stale) = {
            let watch = lock(&self.inner.watch);
            (watch.ticked, watch.stale)
        };
        let bound = lock(&self.inner.bound).clone();
        let looked = bound.as_ref().and_then(|bound| {
            bound.with(|scoped| -> Option<(bool, bool)> {
                let capability = word(CAPABILITY);
                let standing = scoped.armed(&capability) && scoped.stored_on().ok()?;
                let now = scoped.now();
                let fresh =
                    ticked.is_some_and(|ticked| 0.0 <= now - ticked && now - ticked < stale);
                Some((standing, fresh))
            })
        });
        let (standing, fresh) = looked.flatten().unwrap_or((false, false));
        if standing && fresh {
            return Ok(true);
        }
        self.with_timer(|timer| timer.cancel())?;
        if let Some(bound) = bound {
            // Counted only while on.
            let _ = self.count(&bound, "cancelled");
        }
        lock(&self.inner.watch).watching = false;
        Ok(false)
    }
}

struct WakeErrand(WakeForReset);

impl Errand for WakeErrand {
    fn run(&self, view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        self.0
            .run(view)
            .map(|()| Value::Null)
            .map_err(|_| HookFailed)
    }
}

impl Code for WakeForReset {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.bind_to(Bound::of(binding));
        Some(Ok(()))
    }

    fn tick(&mut self, view: &dyn View) -> Spoke {
        self.ticked(view)
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(WakeForReset::new(paths.clone(), None, None)))
}
