//! `engine/remote.py` (seat S7.3b): the resident courier's capabilities - the loopback API (local_api, with
//! local_api_actions and local_api_lan beside it) and remote control over Telegram (telegram_remote, with
//! telegram_continue beside it).
//!
//! While local_api or telegram_remote stands on, the watcher keeps one resident courier running beside it. At P8 (and
//! at P22 while recovery is paused) the errand starts one where none answers the resident's mutex, at most
//! [`RESTARTS`] more times in an hour after the first: past that the journal says `gave_up` and the card says it
//! stopped. Each start is a journal line, so the count outlives a watcher that restarted. The others are actions that
//! only widen what the resident does ([`Widening`]). No network here: the errand only starts a process.

#![allow(clippy::result_unit_err)]

use std::path::Path;
use std::sync::Arc;

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::state::sql::string;

pub const API: &str = "local_api";
pub const API_ACTIONS: &str = "local_api_actions";
pub const API_LAN: &str = "local_api_lan";
pub const TELEGRAM: &str = "telegram_remote";
pub const TELEGRAM_CONTINUE: &str = "telegram_continue";
pub const RESIDENT: [&str; 2] = [API, TELEGRAM];
pub const DEFAULT_PORT: i64 = 47615;
pub const PORT_RANGE: (i64, i64) = (1024, 65535);
/// Starts after the first in one hour, at most.
pub const RESTARTS: usize = 3;
pub const HOUR: f64 = 3600.0;
/// Seconds a start is given to take its mutex before another is tried.
pub const STARTING: f64 = 30.0;
pub const START_WORD: &str = "resident_started";
pub const GAVE_UP_WORD: &str = "gave_up";
pub const API_CODES: [&str; 7] = [
    START_WORD,
    GAVE_UP_WORD,
    "started",
    "stopped",
    "port_taken",
    "locked",
    "unreadable",
];
pub const API_ACTION_CODES: [&str; 3] = ["paused", "cancelled", "list_again"];
pub const TELEGRAM_CODES: [&str; 11] = [
    START_WORD,
    GAVE_UP_WORD,
    "started",
    "stopped",
    "status",
    "listed",
    "cancelled",
    "paused",
    "list_again",
    "ignored",
    "unreadable",
];
pub const TELEGRAM_CONTINUE_CODES: [&str; 2] = ["continued", "pause_lifted"];

/// `setup_time(paths)`: when setup last ran for this installation (its runtime.json's time), as a whole second.
pub fn setup_time(paths: &Paths) -> Option<i64> {
    let modified = std::fs::metadata(Path::new(&paths.home).join("runtime.json"))
        .ok()?
        .modified()
        .ok()?;
    let seconds = match modified.duration_since(std::time::UNIX_EPOCH) {
        Ok(since) => since.as_secs_f64(),
        Err(before) => -before.duration().as_secs_f64(),
    };
    Some(seconds.trunc() as i64)
}

/// `starts(journal_times, now, since)`: when a resident was started in the last hour (and since `since`), oldest first.
pub fn starts(
    journal_times: &dyn Fn(&str, &str, f64) -> Vec<f64>,
    now: f64,
    since: Option<i64>,
) -> Vec<f64> {
    let floor = match since {
        None => now - HOUR,
        Some(since) => (now - HOUR).max(since as f64),
    };
    let mut found: Vec<f64> = RESIDENT
        .iter()
        .flat_map(|capability| journal_times(capability, START_WORD, floor))
        .filter(|at| 0.0 <= now - at && now - at < HOUR && *at >= floor)
        .collect();
    found.sort_by(f64::total_cmp);
    found
}

/// `stopped(journal_times, now, since)`: started as often as an hour allows - the card's `stopped`.
pub fn stopped(
    journal_times: &dyn Fn(&str, &str, f64) -> Vec<f64>,
    now: f64,
    since: Option<i64>,
) -> bool {
    starts(journal_times, now, since).len() > RESTARTS
}

/// Whether a resident answers its mutex (`courier/resident.running`), and how one is started (`launch.start(paths,
/// "--serve")`): the seams a test fills.
pub type Running = Arc<dyn Fn(&Paths) -> bool + Send + Sync>;
pub type Launch = Arc<dyn Fn(&Paths) -> bool + Send + Sync>;

/// `Resident(paths, capability)`: local_api's and telegram_remote's code.
pub struct Resident {
    pub paths: Paths,
    pub capability: String,
    binding: Option<Arc<Binding>>,
    running: Running,
    launch: Launch,
    told: bool,
}

/// The starts journalled in the hour, as `starts(scoped.journal_times, now, setup_time(paths))` reads them; `Err` where
/// the state's read raised (or the runtime is gone).
fn started_of(binding: &Binding, now: f64, since: Option<i64>) -> Result<Vec<f64>, ()> {
    let failed = std::cell::Cell::new(false);
    let times = |capability: &str, word: &str, since: f64| -> Vec<f64> {
        match binding.with(|scoped| {
            scoped.journal_times(&string(capability), &string(word), &Value::Float(since))
        }) {
            Some(Ok(times)) => times.iter().filter_map(crate::state::py::as_f64).collect(),
            _ => {
                failed.set(true);
                Vec::new()
            }
        }
    };
    let found = starts(&times, now, since);
    if failed.get() { Err(()) } else { Ok(found) }
}

/// One start of the resident: it looks again just before it launches.
struct StartErrand {
    paths: Paths,
    binding: Arc<Binding>,
    running: Running,
    launch: Launch,
}

impl Errand for StartErrand {
    fn run(&self, _view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let Some(now) = self.binding.with(|scoped| scoped.now()) else {
            return Ok(Value::Null);
        };
        let Ok(started) = started_of(&self.binding, now, setup_time(&self.paths)) else {
            return Ok(Value::Null);
        };
        if (self.running)(&self.paths)
            || started.last().is_some_and(|last| now - last < STARTING)
            || started.len() > RESTARTS
        {
            return Ok(Value::Null);
        }
        if (self.launch)(&self.paths) {
            self.binding
                .with(|scoped| scoped.count(&string(START_WORD)));
        }
        Ok(Value::Null)
    }
}

impl Resident {
    pub fn new(paths: Paths, capability: &str, running: Running, launch: Launch) -> Resident {
        Resident {
            paths,
            capability: capability.to_owned(),
            binding: None,
            running,
            launch,
            told: false,
        }
    }

    fn ask(&mut self) -> Spoke {
        let Some(binding) = self.binding.clone() else {
            return Ok(Said::Defer);
        };
        if (self.running)(&self.paths) {
            self.told = false;
            return Ok(Said::Defer);
        }
        let Some(now) = binding.with(|scoped| scoped.now()) else {
            return Ok(Said::Defer);
        };
        let Ok(started) = started_of(&binding, now, setup_time(&self.paths)) else {
            return Ok(Said::Defer);
        };
        if started.last().is_some_and(|last| now - last < STARTING) {
            return Ok(Said::Defer);
        }
        if started.len() > RESTARTS {
            if !self.told {
                self.told = binding
                    .with(|scoped| scoped.count(&string(GAVE_UP_WORD)).unwrap_or(false))
                    .unwrap_or(false);
            }
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(StartErrand {
            paths: self.paths.clone(),
            binding,
            running: self.running.clone(),
            launch: self.launch.clone(),
        })))
    }
}

impl Code for Resident {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(Arc::new(binding));
        Some(Ok(()))
    }

    /// P8: the errand that keeps the resident running.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        self.ask()
    }

    /// P22, asked only while recovery is paused: the same errand, so the courier stays reachable.
    fn resident(&mut self, _view: &dyn View) -> Spoke {
        self.ask()
    }
}

/// `Widening(paths)`: an action that only widens what the resident does; nothing of it runs at a plug point.
pub struct Widening {
    pub paths: Paths,
}

impl Code for Widening {}

fn running_default() -> Running {
    Arc::new(|paths: &Paths| crate::courier::resident::running(paths))
}

fn launch_default() -> Launch {
    Arc::new(|paths: &Paths| crate::courier::launch::start(paths, &["--serve"]))
}

pub fn make_local_api(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(Resident::new(
        paths.clone(),
        API,
        running_default(),
        launch_default(),
    )))
}

pub fn make_telegram_remote(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(Resident::new(
        paths.clone(),
        TELEGRAM,
        running_default(),
        launch_default(),
    )))
}

pub fn make_widening(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(Widening {
        paths: paths.clone(),
    }))
}
