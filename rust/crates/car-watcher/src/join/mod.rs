//! The engine join (P6 step 2, seat S6.2b2): `App.backend()`, `App.engine()`, `engine_moved`, `_served_elsewhere`,
//! `engine_state`, `_compatibility_tick`, `_layout_look`, `home_backend`, `home_engine` and `_recovery_facts` over
//! car-engine, car-codex's discovery, transport, Compatibility Registry evaluator and layout watch.
//!
//! [`Joined`] is the product's [`crate::app::EngineMaker`]; App binds it once ([`Bound`]: the paths, the Codex home,
//! the host, the one log, the home lock, the notifier) and asks it for each engine with the loop's own store
//! ([`store::EngineStore`] over the same `Rc<Store>`, as the reference hands the engine the loop's `Store`) and the
//! process's one plug (`Arc<Guarded>`, as the reference hands every part the same plug object).

pub mod engine;
pub mod maker;
pub mod store;

use std::sync::{Arc, Mutex, PoisonError};

use car_config::logbook::Logbook;
use car_machine::json::{Map, Value};

use crate::clock::LogClock;
use crate::fail::{Failed, Res};

pub use maker::Joined;

/// The watcher's one log (`self.logger`): App's lines, the engine's (`EngineLog`), discovery's and the evaluator's,
/// from the loop's thread and the notifier's.
#[derive(Clone)]
pub struct SharedLog {
    pub book: Arc<Mutex<Logbook>>,
    pub clock: Arc<LogClock>,
}

impl SharedLog {
    pub fn new(book: Logbook, clock: LogClock) -> SharedLog {
        SharedLog {
            book: Arc::new(Mutex::new(book)),
            clock: Arc::new(clock),
        }
    }

    /// `logger.info(line)`.
    pub fn info(&self, line: &str) {
        self.book
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .info(line, &*self.clock);
    }

    /// `EngineLog(logger)(thread_id, code, detail)`.
    pub fn engine(&self, thread_id: Option<&str>, code: &str, detail: &Value) {
        let thread = thread_id.map_or(Value::Null, Value::from);
        let _ = self
            .book
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .log(&thread, &Value::from(code), detail, &*self.clock);
    }
}

/// `notifier(source)`'s announce, as App makes it: `(event, detail, identity)` -> whether it was shown. The identity
/// is asked only once the settings let the event be shown (`source.identity(thread_id)`, None where it fails).
pub type Announce = Arc<dyn Fn(&str, &Map, &dyn Fn() -> Value) -> Res<bool> + Send + Sync>;

/// A text value's text (`isinstance(value, str)`).
pub fn text(value: &Value) -> Option<&str> {
    match value {
        Value::Str(found) => found.as_str(),
        _ => None,
    }
}

/// An int value that fits (`isinstance(value, int)`; a bool is not one here).
pub fn int(value: &Value) -> Option<i64> {
    match value {
        Value::Int(found) => found.as_i64(),
        _ => None,
    }
}

/// What App hands the maker as it is made.
pub struct Bound {
    pub paths: car_config::Paths,
    pub project_root: String,
    pub codex_home: String,
    /// `_codex_exe_override`: the argument, else the settings' `codex_exe`.
    pub codex_exe: Option<String>,
    pub host: Arc<dyn car_control::host::Host>,
    pub log: SharedLog,
    /// `self._home_lock is not None and self._home_lock.held`.
    pub home_lock: std::rc::Rc<dyn Fn() -> bool>,
    pub announce: Announce,
    /// The process's one plug: told the Codex found here (`plug.codex(exe, home)`).
    pub plug: Arc<car_policy::plug::Guarded>,
}

/// `App._record_failure(label)`: the log's line and the error log's entry.
pub fn record_failure(log: &SharedLog, error_log: &str, label: &str, failed: &Failed) {
    log.info(&format!(
        "{label} failed ({}); no submission was made",
        failed.class
    ));
    let path = std::path::PathBuf::from(error_log);
    let _ = (|| -> std::io::Result<()> {
        use std::io::Write;
        let mut stream = car_machine::pyfile::options()
            .create(true)
            .append(true)
            .open(&path)?;
        let when = crate::app::stamp_now();
        let text = format!("{when}{label}\n{failed}\n");
        stream.write_all(text.replace('\n', "\r\n").as_bytes())?;
        drop(stream);
        if std::fs::metadata(&path)?.len() > 2_000_000 {
            car_platform::files::replace(&path, &path.with_extension("log.1"))?;
        }
        Ok(())
    })();
}
