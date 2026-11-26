//! `runtime/health.py`: the watcher's side of its own health (v0.6.11) - its memory, how it ended, and the status
//! file.
//!
//! Asked by the loop on the thread that ticks, after a tick has ended - never inside one. At the defaults the guard
//! is off and the status file is not written: the watcher asks Windows about its own memory and writes the peak into
//! its heartbeat.

use std::path::Path;

use car_machine::json::{Int, Map, Value};
use car_machine::pyval;
use car_policy::settings::memguard;
use car_policy::settings::os::Os;
use car_policy::settings::statusfile;
use car_store::Store;

use crate::fail::{Failed, Res};

/// `win/ownprocess.py`, or a test's stand-in with the same three names.
pub trait OwnProcess {
    /// (private bytes committed now, the most so far), or None where Windows will not say.
    fn memory(&self) -> Option<(u64, u64)>;
    fn sign_in(&self) -> Option<String>;
    fn booted_at(&self) -> Option<f64>;
}

/// This process, asked of Windows.
pub struct ThisProcess;

impl OwnProcess for ThisProcess {
    fn memory(&self) -> Option<(u64, u64)> {
        car_platform::ownprocess::memory()
    }
    fn sign_in(&self) -> Option<String> {
        car_platform::ownprocess::sign_in()
    }
    fn booted_at(&self) -> Option<f64> {
        car_platform::ownprocess::booted_at()
    }
}

/// `notice(event, detail, final=...)`.
pub type Notice<'a> = &'a dyn Fn(&str, Map, bool) -> Res<()>;

/// `Health(paths=, log=, notice=, port=, clock=)`: one watcher's memory readings, warning and status file.
pub struct Health {
    port: Box<dyn OwnProcess>,
    clock: Box<dyn Fn() -> f64>,
    status_file: String,
    version: String,
    /// Private memory committed at the last look, and the most so far, in bytes; None until known.
    pub private: Option<u64>,
    pub peak: Option<u64>,
    pub warned: bool,
    /// Which sign-in this watcher runs in, and when Windows started: asked once, as it starts.
    pub sign_in: Option<String>,
    pub booted_at: Option<f64>,
    /// Whether the status file was being written at the last look: None before the first.
    writing: Option<bool>,
}

fn int(value: u64) -> Value {
    Value::Int(Int::from(value))
}

fn failed(class: &'static str) -> Failed {
    Failed::new(class, "")
}

impl Health {
    pub fn new(
        status_file: &str,
        version: &str,
        port: Box<dyn OwnProcess>,
        clock: Box<dyn Fn() -> f64>,
    ) -> Health {
        let sign_in = port.sign_in();
        let booted_at = port.booted_at();
        Health {
            port,
            clock,
            status_file: status_file.to_owned(),
            version: version.to_owned(),
            private: None,
            peak: None,
            warned: false,
            sign_in,
            booted_at,
            writing: None,
        }
    }

    /// `look()`: how much memory this process has committed now, and the most it has.
    pub fn look(&mut self) {
        match self.port.memory() {
            None => self.private = None,
            Some((private, peak)) => {
                self.private = Some(private);
                self.peak = Some(peak.max(private).max(self.peak.unwrap_or(0)));
            }
        }
    }

    /// `over(values)`: whether the watcher is to stop now, for the memory guard. With warn, over the limit is said
    /// once and the watcher goes on; with stop, it is said, and this answers True.
    pub fn over(&mut self, values: &Value, log: &dyn Fn(&str), notice: Notice) -> Res<bool> {
        let private = self.private.map_or(Value::Null, int);
        let answer = memguard::verdict(values, &private, &Value::Bool(self.warned));
        if answer == memguard::OK {
            return Ok(false);
        }
        let used = memguard::mib(&private);
        let limit = memguard::limit_mib(values);
        let mut detail = Map::new();
        detail.insert("used".into(), used.clone());
        detail.insert("limit".into(), Value::from(limit));
        self.warned = true;
        let used = match &used {
            Value::Int(number) => number.to_string(),
            _ => return Err(failed("TypeError")),
        };
        if answer == memguard::WARN {
            log(&format!(
                "the watcher uses {used} MiB of memory, more than the {limit} MiB the memory guard allows; it goes on"
            ));
            notice("memory_warning", detail, false)?;
            return Ok(false);
        }
        log(&format!(
            "the watcher uses {used} MiB of memory, more than the {limit} MiB the memory guard allows; stopping before the next tick"
        ));
        notice("memory_stopped", detail, true)?;
        Ok(true)
    }

    /// `ended(store, end)`: that the watcher stops on purpose, and how (clean or memory_guard).
    pub fn ended(&self, store: &Store, end: &str) -> Res<()> {
        store.watcher_ended((self.clock)(), end)?;
        Ok(())
    }

    /// `status(store, values, running=, engine=)`: the status file while its setting is on; removed, once, when the
    /// setting is off.
    pub fn status(
        &mut self,
        store: &Store,
        values: &Value,
        running: bool,
        engine: &str,
        os: &dyn Os,
        log: &dyn Fn(&str),
    ) -> Res<()> {
        let target = Path::new(&self.status_file);
        if !statusfile::wanted(values) {
            if self.writing != Some(false) {
                self.writing = Some(false);
                if statusfile::remove(os, target).map_err(failed)? {
                    log("status file removed: its setting is off");
                }
            }
            return Ok(());
        }
        if self.writing != Some(true) {
            log("writing the status file for other tools after every tick");
        }
        self.writing = Some(true);
        let settings = store.settings()?;
        let heartbeat = store.watcher_status()?.unwrap_or_default();
        let enabled = match settings.get("enabled") {
            None => return Err(failed("KeyError")),
            Some(found) => pyval::truthy(found),
        };
        let stored = Value::Object(settings);
        let observe_only = pyval::truthy(pyval::get(&stored, "observe_only").unwrap_or(&Value::Null))
            || pyval::truthy(pyval::get(values, "observe_only").unwrap_or(&Value::Null));
        let rows = Value::Array(store.pending()?.into_iter().map(Value::Object).collect());
        let reading = heartbeat.get("usage").cloned().unwrap_or(Value::Null);
        let content = statusfile::content(
            &Value::Float((self.clock)()),
            &Value::from(self.version.as_str()),
            &Value::Bool(running),
            &Value::Bool(enabled),
            &Value::Bool(observe_only),
            &Value::from(engine),
            &rows,
            &reading,
        )
        .map_err(failed)?;
        statusfile::write(os, target, &content).map_err(failed)?;
        Ok(())
    }
}
