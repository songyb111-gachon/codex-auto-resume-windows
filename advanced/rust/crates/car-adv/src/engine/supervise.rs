//! Restart the watcher if it stops unexpectedly (`crash_restart`, v0.6.19): P13's answers (seat S7.2e2,
//! `engine/supervise.py`).
//!
//! With this capability on, the launcher asks P13 before it runs the watcher and this answers SUPERVISE: the launcher
//! runs the watcher as a child of its own and waits for it. Once the child ended the launcher asks again, with its exit
//! code and whether its heartbeat says it stopped on purpose, and this answers RESTART only when every one holds: the
//! end was not clean (`clean` is not True); the exit code is not 0, EXIT_BUSY (3), EXIT_SCHEMA_NEWER (4) nor
//! EXIT_MEMORY_GUARD (5); the stop event was not signalled; fewer than CAP restarts in the HOUR before - each one a row
//! in `restarts`, written before the restart is made, so a restart that could not be counted is not made. Before it
//! answers RESTART it waits RESTART_DELAY seconds on the stop event itself. The third restart in an hour is the last:
//! at the next abnormal end it answers DEFER and one notice of its own kind (`restart_gave_up`) says it was left
//! stopped. It never kills anything (E8), and answers RESTART only in a launcher it answered SUPERVISE in.
//!
//! This file also holds [`Bound`], what `bind(scoped)` hands every S7.2e2 code: the runtime's [`Binding`], or (for the
//! harness) a state of its own - the Python `Scoped` object a test binds directly - and the small helpers the other
//! S7.2e2 files share (no seat adds a module: P7-DESIGN 2.1).

use std::path::Path;
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::Alternative;

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::state::scoped::Scoped;
use crate::state::{Error, sql};
use crate::win::stopflag::StopFlag;

pub const CAPABILITY: &str = "crash_restart";
/// How many restarts an hour, and the hour.
pub const CAP: usize = 3;
pub const HOUR: f64 = 3600.0;
/// Seconds between a watcher's end and its restart.
pub const RESTART_DELAY: f64 = 5.0;
pub const EXIT_OK: i64 = 0;
pub const EXIT_BUSY: i64 = 3;
pub const EXIT_SCHEMA_NEWER: i64 = 4;
pub const EXIT_MEMORY_GUARD: i64 = 5;
/// The exit codes a watcher is never started again after.
pub const NEVER_RESTARTED: [i64; 4] = [EXIT_OK, EXIT_BUSY, EXIT_SCHEMA_NEWER, EXIT_MEMORY_GUARD];
pub const PHASE_START: &str = "start";
pub const PHASE_ENDED: &str = "ended";
/// The notice of its own kind, and core's notifier event that raises it.
pub const GAVE_UP: &str = "restart_gave_up";
/// Written by the launcher where a watcher runs in its own process for want of an answer: its pid and the word.
pub const UNSUPERVISED_FILE: &str = "unsupervised.txt";

// ---------------------------------------------------------------------------------------------- Bound (all S7.2e2)
/// A state a harness binds a code to directly (the Python test's `state.scoped(capability, on=..., ...)`).
pub trait Direct: Send + Sync {
    /// `f(scoped)` once, with the capability's `Scoped`.
    fn scoped(&self, f: &mut dyn FnMut(&Scoped<'_>));
}

/// What `bind(scoped)` handed a code: the runtime's binding, or a harness's own state. Cheap to clone, so a code's
/// errand and its threads hold it as the Python objects hold `self._scoped`.
#[derive(Clone)]
pub enum Bound {
    Runtime(Arc<Binding>),
    Direct(Arc<dyn Direct>),
}

impl Bound {
    /// The runtime's binding.
    pub fn of(binding: Binding) -> Bound {
        Bound::Runtime(Arc::new(binding))
    }

    /// `f(scoped)`, or None once the runtime is gone.
    pub fn with<R>(&self, f: impl FnOnce(&Scoped<'_>) -> R) -> Option<R> {
        match self {
            Bound::Runtime(binding) => binding.with(f),
            Bound::Direct(direct) => {
                let mut f = Some(f);
                let mut out = None;
                direct.scoped(&mut |scoped| {
                    if let Some(f) = f.take() {
                        out = Some(f(scoped));
                    }
                });
                out
            }
        }
    }

    /// `f(scoped)` where a state error (or a runtime gone) is the reference's raise of that class.
    pub fn read<R>(&self, f: impl FnOnce(&Scoped<'_>) -> Result<R, Error>) -> Result<R, Raised> {
        match self.with(f) {
            Some(Ok(found)) => Ok(found),
            Some(Err(error)) => Err(raised(&error)),
            None => Err(Raised::new("StateError")),
        }
    }

    /// `scoped.now()`.
    pub fn now(&self) -> Result<f64, Raised> {
        self.with(|scoped| scoped.now())
            .ok_or_else(|| Raised::new("StateError"))
    }
}

/// The reference's raise of a state error: its class.
pub fn raised(error: &Error) -> Raised {
    Raised::new(error.class())
}

/// A text value.
pub(crate) fn word(text: &str) -> Value {
    Value::Str(text.into())
}

/// `value` as a float for a number (`int` or `float`, never a bool); None otherwise.
pub(crate) fn number(value: &Value) -> Option<f64> {
    match value {
        Value::Int(number) => number.as_i64().map(|n| n as f64),
        Value::Float(number) => Some(*number),
        _ => None,
    }
}

/// `dictionary.get(key)` of an object; None (Python's None) for anything else.
pub(crate) fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NONE: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NONE),
        _ => &NONE,
    }
}

/// `car_config::Links` over car-platform's link test (what the product's paths are made with).
#[derive(Debug)]
pub(crate) struct PlatformLinks;

impl car_config::Links for PlatformLinks {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

/// `inuse.home(paths)`: the Codex home the watcher told, else CODEX_HOME's as the watcher finds it; the reference's
/// raise (`ConfigError`, `OSError`) where none can be named.
pub(crate) fn codex_home(paths: &Paths) -> Result<String, Raised> {
    let env = |name: &str| std::env::var(name).ok();
    let os = car_config::Os::here(false, Arc::new(PlatformLinks));
    crate::codex::inuse::home(Some(&paths.home), &env, &os).map_err(Raised::new)
}

/// The lock of a shared value, whatever a thread that held it last did.
pub(crate) fn lock<T>(shared: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    shared.lock().unwrap_or_else(PoisonError::into_inner)
}

// ---------------------------------------------------------------------------------------------- the seams
/// `win/stopflag.StopFlag`'s shape: what the capability asks of the stop event. Each may raise, as a test's may.
pub trait Flag: Send {
    fn hold(&mut self) -> Result<(), Raised>;
    fn signalled(&mut self) -> Result<bool, Raised>;
    fn wait(&mut self, seconds: f64) -> Result<bool, Raised>;
}

impl Flag for StopFlag {
    fn hold(&mut self) -> Result<(), Raised> {
        StopFlag::hold(self);
        Ok(())
    }
    fn signalled(&mut self) -> Result<bool, Raised> {
        Ok(StopFlag::signalled(self))
    }
    fn wait(&mut self, seconds: f64) -> Result<bool, Raised> {
        Ok(StopFlag::wait(self, seconds))
    }
}

/// How the stop flag is made where none was handed (`StopFlag(self.paths)`).
pub type MakeFlag = Box<dyn Fn(&Paths) -> Result<Box<dyn Flag>, Raised> + Send>;
/// `notify(paths)`: the notice that the watcher was left stopped; whether it was shown (`gave_up_notice`).
pub type Notify = Box<dyn Fn(&Paths) -> Result<bool, Raised> + Send>;

/// The product's stop flag: the event of this installation's state folder, over Windows (made only when first asked,
/// as the reference makes it; never in a test).
pub fn system_flag(paths: &Paths) -> Result<Box<dyn Flag>, Raised> {
    StopFlag::new(&paths.state_dir, Box::new(car_platform::wake::SystemEvents))
        .map(|flag| Box::new(flag) as Box<dyn Flag>)
        .map_err(|_| Raised::new("AdapterError"))
}

/// `gave_up_notice(paths)` until the entry points hand core's notifier (S6.1/S7.3d: `config.load_settings`,
/// `settings.notification_enabled(values, GAVE_UP)`, `notifier.build`/`deliver`): not shown.
pub fn no_notice(_paths: &Paths) -> Result<bool, Raised> {
    Ok(false)
}

// ---------------------------------------------------------------------------------------------- the view
/// `view(runtime)`: `{"crash_restart": {"unsupervised": word}}` while crash_restart stands on (`armed`) and the watcher
/// running now started without its supervisor - the file's process still running (`process_there`) - else `{}`.
pub fn view(armed: bool, logs_dir: &Path, process_there: &dyn Fn(i64) -> bool) -> Value {
    let mut found = car_machine::json::Map::new();
    if !armed {
        return Value::Object(found);
    }
    let Ok(bytes) = std::fs::read(logs_dir.join(UNSUPERVISED_FILE)) else {
        return Value::Object(found);
    };
    // read_text(encoding="utf-8"): a byte that is not UTF-8 is a UnicodeDecodeError, a ValueError.
    let Ok(text) = String::from_utf8(bytes) else {
        return Value::Object(found);
    };
    // Universal newlines change nothing `split()` sees.
    let parts: Vec<&str> = text
        .split(car_machine::pytext::is_space)
        .filter(|part| !part.is_empty())
        .collect();
    let [pid, said] = parts.as_slice() else {
        return Value::Object(found);
    };
    let Some(parsed) = car_machine::pytext::parse_int(pid, 10) else {
        return Value::Object(found);
    };
    let pid = match parsed.magnitude.and_then(|m| i64::try_from(m).ok()) {
        Some(m) if parsed.negative => -m,
        Some(m) => m,
        // Past what a process id can be: no such process is there.
        None => return Value::Object(found),
    };
    if process_there(pid) {
        let mut inner = car_machine::json::Map::new();
        inner.insert("unsupervised".into(), word(said));
        found.insert(CAPABILITY.into(), Value::Object(inner));
    }
    Value::Object(found)
}

// ---------------------------------------------------------------------------------------------- the code
/// `CrashRestart(paths, stop=..., notify=...)`: P13's two answers.
pub struct CrashRestart {
    paths: Paths,
    bound: Option<Bound>,
    stop: Option<Box<dyn Flag>>,
    make_flag: MakeFlag,
    notify: Notify,
    supervising: bool,
}

impl CrashRestart {
    pub fn new(paths: Paths, stop: Option<Box<dyn Flag>>, notify: Option<Notify>) -> CrashRestart {
        CrashRestart {
            paths,
            bound: None,
            stop,
            make_flag: Box::new(system_flag),
            notify: notify.unwrap_or_else(|| Box::new(no_notice)),
            supervising: false,
        }
    }

    /// `bind(scoped)` with a harness's own state.
    pub fn bind_to(&mut self, bound: Bound) {
        self.bound = Some(bound);
    }

    fn flag(&mut self) -> Result<&mut Box<dyn Flag>, Raised> {
        if self.stop.is_none() {
            self.stop = Some((self.make_flag)(&self.paths)?);
        }
        Ok(self.stop.as_mut().expect("made above"))
    }

    /// `supervise(facts)`.
    pub fn answer(&mut self, facts: &Value) -> Spoke {
        if !matches!(facts, Value::Object(_)) || self.bound.is_none() {
            return Ok(Said::Defer);
        }
        let phase = field(facts, "phase");
        if *phase == word(PHASE_START) {
            // The stop event is held from now on, so a stop asked while the child runs is still seen once it ended.
            self.flag()?.hold()?;
            self.supervising = true;
            return Ok(Said::Word(Alternative::Supervise));
        }
        if *phase == word(PHASE_ENDED) && self.supervising {
            let code = field(facts, "exit_code").clone();
            let clean = field(facts, "clean").clone();
            return self.ended(&code, &clean);
        }
        Ok(Said::Defer)
    }

    fn ended(&mut self, code: &Value, clean: &Value) -> Spoke {
        let Value::Int(number) = code else {
            return Ok(Said::Defer);
        };
        if number
            .as_i64()
            .is_some_and(|n| NEVER_RESTARTED.contains(&n))
            || matches!(clean, Value::Bool(true))
        {
            return Ok(Said::Defer);
        }
        if self.flag()?.signalled()? {
            return Ok(Said::Defer);
        }
        let bound = self.bound.clone().expect("bound before");
        let recent = bound.with(|scoped| -> Result<usize, Error> {
            let now = scoped.now();
            let rows = scoped.state.restarts_since(&sql::float(now - HOUR))?;
            Ok(rows
                .iter()
                .filter(|row| sql::truthy(sql::get(row, "restarted")))
                .count())
        });
        // Restarts that cannot be counted are not made.
        let Some(Ok(recent)) = recent else {
            return Ok(Said::Defer);
        };
        if recent >= CAP {
            let _ = bound.with(|scoped| -> Result<(), Error> {
                scoped.handle().restarts_noted(code, &Value::Bool(false))?;
                scoped.count(&word("gave_up"))?;
                Ok(())
            });
            // A notice not shown leaves it stopped all the same.
            let _ = (self.notify)(&self.paths);
            return Ok(Said::Defer);
        }
        if self.flag()?.wait(RESTART_DELAY)? {
            return Ok(Said::Defer);
        }
        let noted = bound.with(|scoped| scoped.handle().restarts_noted(code, &Value::Bool(true)));
        if !matches!(noted, Some(Ok(true))) {
            return Ok(Said::Defer);
        }
        bound.read(|scoped| scoped.count(&word("restarted")))?;
        Ok(Said::Word(Alternative::Restart))
    }
}

impl Code for CrashRestart {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.bound = Some(Bound::of(binding));
        Some(Ok(()))
    }

    fn supervise(&mut self, facts: &Value) -> Spoke {
        self.answer(facts)
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(CrashRestart::new(paths.clone(), None, None)))
}
