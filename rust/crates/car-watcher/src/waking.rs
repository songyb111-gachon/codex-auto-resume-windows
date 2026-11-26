//! `runtime/waking.py`: the watcher's side of sleep and of keeping this PC awake (v0.6.11).
//!
//! Before a tick, whether this PC slept since the last one, which the engine is then told; after it, whether to keep
//! the PC awake; and when the watcher stops, to let go of everything. At the defaults it asks Windows nothing - no
//! listener is registered, no clock is compared and no request is made. Keeping awake is a request the thread that
//! ticks holds (SetThreadExecutionState), counted once per stretch of waiting; the PC's own power settings are never
//! changed (F1).

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use car_machine::json::Value;
use car_machine::vocab_gen::domain_states::WAITING;
use car_policy::classify::power;
use car_store::Store;

use crate::fail::{Failed, Res};

/// A listener for this PC waking: `start` says whether Windows took it.
pub trait Listener {
    fn start(&mut self) -> bool;
    fn stop(&mut self);
}

/// `win/power.py`, or a test's stand-in with the same four names.
pub trait PowerPort {
    /// Seconds this PC has been awake, or None.
    fn awake_seconds(&self) -> Option<f64>;
    /// `WakeListener(heard)`.
    fn listener(&self, heard: Arc<dyn Fn() + Send + Sync>) -> Box<dyn Listener>;
    /// `keep_awake(on)`: whether Windows took the request.
    fn keep_awake(&self, on: bool) -> bool;
    /// `on_mains()`: True on mains power, False on battery, None where it cannot be told.
    fn on_mains(&self) -> Option<bool>;
}

/// This PC.
pub struct ThisPower;

struct Windows(car_platform::power::WakeListener);

impl Listener for Windows {
    fn start(&mut self) -> bool {
        self.0.start()
    }
    fn stop(&mut self) {
        self.0.stop();
    }
}

impl PowerPort for ThisPower {
    fn awake_seconds(&self) -> Option<f64> {
        car_platform::power::awake_seconds()
    }
    fn listener(&self, heard: Arc<dyn Fn() + Send + Sync>) -> Box<dyn Listener> {
        Box::new(Windows(car_platform::power::WakeListener::new(move || {
            heard()
        })))
    }
    fn keep_awake(&self, on: bool) -> bool {
        car_platform::power::keep_awake(on)
    }
    fn on_mains(&self) -> Option<bool> {
        car_platform::power::on_mains()
    }
}

/// What the engine is told after a sleep: `engine.after_sleep(since, slept)`.
pub trait Sleeper {
    fn after_sleep(&mut self, since: f64, slept: f64) -> Res<()>;
}

/// `Waking(signal=, log=, port=, clock=)`: one watcher's listener, clock readings and keep-awake request.
pub struct Waking {
    port: Box<dyn PowerPort>,
    signal: Arc<dyn Fn() -> Res<()> + Send + Sync>,
    clock: Box<dyn Fn() -> f64>,
    woke: Arc<AtomicBool>,
    listener: Option<Box<dyn Listener>>,
    /// (wall clock, time awake) at the last look, while listening.
    reading: Option<(f64, f64)>,
    /// Since when this PC is asked to stay awake, while it is.
    pub awake_since: Option<f64>,
    stretch: Option<f64>,
    spent: bool,
}

fn reading_value(reading: (f64, f64)) -> Value {
    Value::Array(vec![Value::Float(reading.0), Value::Float(reading.1)])
}

fn class(error: &'static str) -> Failed {
    Failed::new(error, "")
}

impl Waking {
    pub fn new(
        port: Box<dyn PowerPort>,
        signal: Arc<dyn Fn() -> Res<()> + Send + Sync>,
        clock: Box<dyn Fn() -> f64>,
    ) -> Waking {
        Waking {
            port,
            signal,
            clock,
            woke: Arc::new(AtomicBool::new(false)),
            listener: None,
            reading: None,
            awake_since: None,
            stretch: None,
            spent: false,
        }
    }

    /// `before(engine, values)`: listen while a setting wants it, and tell `engine` if this PC slept since the last
    /// look. The seconds it slept (0.0 for none); the reading is kept only once the engine has been told.
    pub fn before(
        &mut self,
        engine: Option<&mut dyn Sleeper>,
        values: &Value,
        log: &dyn Fn(&str),
    ) -> Res<f64> {
        if !power::listens(values) {
            self.deafen();
            return Ok(0.0);
        }
        self.listen();
        let Some(engine) = engine else {
            return Ok(0.0);
        };
        let now = self
            .port
            .awake_seconds()
            .map(|awake| ((self.clock)(), awake));
        let woke = self.woke.load(Ordering::SeqCst);
        let slept = match (self.reading, now) {
            (Some(before), Some(after)) => {
                power::asleep(&reading_value(before), &reading_value(after)).map_err(class)?
            }
            _ => 0.0,
        };
        if slept != 0.0 || woke {
            if slept != 0.0 {
                log(&format!(
                    "this PC slept for about {} minutes; looking again at everything that waits",
                    (slept / 60.0).floor() as i64
                ));
            }
            let since = match self.reading {
                Some(before) => before.0,
                None => (self.clock)(),
            };
            engine.after_sleep(since, slept)?;
        }
        self.woke.store(false, Ordering::SeqCst);
        self.reading = now;
        Ok(slept)
    }

    fn listen(&mut self) {
        if self.listener.is_none() {
            let woke = Arc::clone(&self.woke);
            let signal = Arc::clone(&self.signal);
            // `_heard`: on a thread of Windows' own, so a flag and the wake event, and nothing else.
            let heard: Arc<dyn Fn() + Send + Sync> = Arc::new(move || {
                woke.store(true, Ordering::SeqCst);
                crate::fail::quietly(|| {
                    let _ = signal();
                });
            });
            let mut listener = self.port.listener(heard);
            if listener.start() {
                self.listener = Some(listener);
            }
        }
    }

    fn deafen(&mut self) {
        if let Some(mut listener) = self.listener.take() {
            listener.stop();
        }
        self.reading = None;
        self.woke.store(false, Ordering::SeqCst);
    }

    /// `after(store, values, ok=, paused=)`: keep this PC awake, or let it go, after a tick. Since when it is kept
    /// awake, or None.
    pub fn after(
        &mut self,
        store: &Store,
        values: &Value,
        ok: bool,
        paused: bool,
        log: &dyn Fn(&str),
    ) -> Res<Option<f64>> {
        let mode = power::keep_awake(values);
        if mode == "off" || paused {
            self.stretch = None;
            self.spent = false;
            return Ok(self.let_go(log));
        }
        if !ok {
            return Ok(self.let_go(log));
        }
        let waiting: Vec<String> = WAITING.iter().map(|each| (*each).to_owned()).collect();
        let rows = Value::Array(
            store
                .records_in(&waiting, None)?
                .into_iter()
                .map(Value::Object)
                .collect(),
        );
        let count = power::waiting(&rows).map_err(class)?;
        let now = (self.clock)();
        if count == 0 {
            self.stretch = None;
            self.spent = false;
            return Ok(self.let_go(log));
        }
        let stretch = *self.stretch.get_or_insert(now);
        let cap = power::awake_cap(values);
        if !self.spent && cap.is_some_and(|cap| now - stretch >= cap as f64) {
            self.spent = true;
            if self.awake_since.is_some() {
                log("kept this PC awake for the hours chosen; it may sleep again");
            }
        }
        let mains = if mode == "on_ac" {
            match self.port.on_mains() {
                Some(on) => Value::Bool(on),
                None => Value::Null,
            }
        } else {
            Value::Null
        };
        if self.spent
            || !power::wants_awake(&Value::from(mode), &Value::from(count), &mains)
                .map_err(class)?
        {
            return Ok(self.let_go(log));
        }
        if self.awake_since.is_none() && self.port.keep_awake(true) {
            self.awake_since = Some(now);
            log(&format!("keeping this PC awake while {count} task(s) wait"));
        }
        Ok(self.awake_since)
    }

    /// `let_go()`: take back the request to keep this PC awake, if one is held. None.
    pub fn let_go(&mut self, log: &dyn Fn(&str)) -> Option<f64> {
        if self.awake_since.is_some() {
            self.awake_since = None;
            self.port.keep_awake(false);
            log("no longer keeping this PC awake");
        }
        None
    }

    /// `stop()`: the watcher stops - let go, and stop listening.
    pub fn stop(&mut self, log: &dyn Fn(&str)) {
        self.let_go(log);
        self.deafen();
    }

    /// Whether a listener is registered now (for tests and the diffs).
    pub fn listening(&self) -> bool {
        self.listener.is_some()
    }

    /// `_heard`, as a test's port calls it.
    pub fn woke_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.woke)
    }
}
