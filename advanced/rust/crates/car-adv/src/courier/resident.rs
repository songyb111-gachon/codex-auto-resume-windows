//! `courier/resident.py` (seat S7.3b): the resident courier, `courier --serve` - the roles that stay while local_api or
//! telegram_remote stands on: the loopback API (`api`) and Telegram's long poll (`telegram`).
//!
//! It holds a mutex of its own ([`mutex`]), not the short-lived courier's, so a notice is never held behind a server and
//! a second resident for the same home exits at once. [`serve`] reads the capabilities' states every [`CHECK`] seconds:
//! the server is started while local_api stands on (on every network while local_api_lan does too) and started again
//! when its port or reach changes; the poll runs while telegram_remote stands on; each is closed within CHECK seconds
//! of being turned off, and with neither on the process ends. A read of the states that fails is no reading that says
//! off: what runs keeps running for up to [`UNREADABLE_FOR`] seconds of failed reads in a row. Where the server stands is
//! stamped beside local_api's choices (bound, or the port found taken - never both).

#![allow(clippy::result_unit_err)]

use std::sync::Arc;
use std::thread::JoinHandle;

use car_config::Paths;
use car_machine::json::Value;

use crate::courier::address;
use crate::courier::main::{EXIT_DONE, SharedRuntime};
use crate::courier::telegram::Stop;
use crate::engine::remote::DEFAULT_PORT;
use crate::state::sql::string;
use crate::vocabulary::ArmingState;

pub const BOUND: &str = "api_bound_at";
pub const TAKEN: &str = "api_taken_at";
pub const LAN_KEYS: [&str; 4] = ["api_lan_1", "api_lan_2", "api_lan_3", "api_lan_4"];
pub const API: &str = "local_api";
pub const API_LAN: &str = "local_api_lan";
pub const TELEGRAM: &str = "telegram_remote";
pub const CHECK: f64 = 10.0;
pub const UNREADABLE_FOR: f64 = 600.0;
pub const UNREADABLE: &str = "unreadable";

/// This home's resident mutex's name: core's named mutex under a name of the resident's own.
pub fn mutex_name(paths: &Paths) -> Option<String> {
    car_platform::sync::Mutex::new(&format!("courier-resident\0{}", paths.state_dir), 0.0)
        .ok()
        .map(|mutex| mutex.name.clone())
}

/// `mutex(paths, timeout)`.
pub fn mutex(paths: &Paths, timeout: f64) -> Option<car_platform::sync::Mutex> {
    car_platform::sync::Mutex::new(&format!("courier-resident\0{}", paths.state_dir), timeout).ok()
}

/// `running(paths)`: whether a resident courier holds this home's mutex now - opened, never taken.
pub fn running(paths: &Paths) -> bool {
    mutex_name(paths).is_some_and(|name| car_platform::job::mutex_exists(&name))
}

/// A server the resident started (`api::Running`): its own addresses beyond 127.0.0.1, and `close`.
pub trait Served: Send {
    fn addresses(&self) -> Vec<String>;
    fn close(&mut self);
}

/// `server(runtime, port, lan)`: a server started, or `Err` where the port is taken.
pub type ServerFactory =
    Arc<dyn Fn(&SharedRuntime, i64, bool) -> Result<Box<dyn Served>, ()> + Send + Sync>;
/// `poller(runtime, stop)`: runs until `stop` is set.
pub type Poller = Arc<dyn Fn(SharedRuntime, Stop) + Send + Sync>;

/// `Roles(runtime, server=, poller=)`: what the resident runs now, and what it was asked to run.
pub struct Roles {
    runtime: SharedRuntime,
    /// The monotonic clock a run of failed reads is timed by (a test sets its own).
    pub clock: Box<dyn Fn() -> f64 + Send>,
    server_factory: ServerFactory,
    poller: Poller,
    thread: Option<JoinHandle<()>>,
    stop: Option<Stop>,
    server: Option<Box<dyn Served>>,
    serving: Option<(i64, bool)>,
    taken: Option<(i64, bool)>,
    unread_since: Option<f64>,
}

fn monotonic() -> Box<dyn Fn() -> f64 + Send> {
    let start = std::time::Instant::now();
    Box::new(move || start.elapsed().as_secs_f64())
}

impl Roles {
    pub fn new(runtime: SharedRuntime, server: ServerFactory, poller: Poller) -> Roles {
        let roles = Roles {
            runtime,
            clock: monotonic(),
            server_factory: server,
            poller,
            thread: None,
            stop: None,
            server: None,
            serving: None,
            taken: None,
            unread_since: None,
        };
        roles.mark(None);
        roles
    }

    fn counted(&self, capability: &str, code: &str) {
        let _ = self
            .runtime
            .state()
            .counted(&string(capability), &string(code), &Value::Null);
    }

    /// `wanted()`: (port or None, lan, telegram) - what the states ask for now; `Err` where they cannot be read.
    pub fn wanted(&self) -> Result<(Option<i64>, bool, bool), ()> {
        let states = self.runtime.states()?;
        if self.runtime.unreadable() {
            return Err(());
        }
        let api = states.state_of(API) == ArmingState::Armed;
        let mut port = None;
        if api {
            let options = self.runtime.state().options(&string(API)).map_err(|_| ())?;
            port = Some(match options.get("api_port") {
                Some(Value::Int(chosen)) => chosen.as_i64().unwrap_or(DEFAULT_PORT),
                _ => DEFAULT_PORT,
            });
        }
        Ok((
            port,
            api && states.state_of(API_LAN) == ArmingState::Armed,
            states.state_of(TELEGRAM) == ArmingState::Armed,
        ))
    }

    /// `follow()`: the roles brought to what the states ask for; whether any is wanted.
    pub fn follow(&mut self) -> bool {
        let (port, lan, telegram) = match self.wanted() {
            Ok(found) => {
                self.unread_since = None;
                found
            }
            Err(()) => {
                let now = (self.clock)();
                let since = match self.unread_since {
                    Some(since) => since,
                    None => {
                        self.unread_since = Some(now);
                        self.count_unreadable();
                        now
                    }
                };
                if now - since < UNREADABLE_FOR {
                    return true;
                }
                (None, false, false)
            }
        };
        if self.server.is_some() && self.serving != port.map(|port| (port, lan)) {
            self.close_server();
        }
        if let Some(port) = port
            && self.server.is_none()
        {
            match (self.server_factory)(&self.runtime, port, lan) {
                Ok(server) => {
                    self.server = Some(server);
                    self.serving = Some((port, lan));
                    self.taken = None;
                    self.mark(Some(BOUND));
                    self.counted(API, "started");
                }
                Err(()) => {
                    self.server = None;
                    self.serving = None;
                    if self.taken != Some((port, lan)) {
                        self.taken = Some((port, lan));
                        self.mark(Some(TAKEN));
                        self.counted(API, "port_taken");
                    }
                }
            }
        }
        if self.thread.is_some()
            && (!telegram || self.thread.as_ref().is_some_and(JoinHandle::is_finished))
        {
            self.stop_poll();
        }
        if telegram && self.thread.is_none() {
            let stop = Stop::new();
            let (runtime, poller, held) = (self.runtime.clone(), self.poller.clone(), stop.clone());
            self.thread = std::thread::Builder::new()
                .name("telegram".into())
                .spawn(move || {
                    // D15: a panic ends the poll's thread alone; the next check starts it again.
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        poller(runtime, held)
                    }));
                })
                .ok();
            self.stop = Some(stop);
            self.counted(TELEGRAM, "started");
        }
        port.is_some() || telegram
    }

    fn count_unreadable(&self) {
        let mut capabilities = Vec::new();
        if self.server.is_some() {
            capabilities.push(API);
        }
        if self.thread.is_some() {
            capabilities.push(TELEGRAM);
        }
        if capabilities.is_empty() {
            capabilities.push(API);
        }
        for capability in capabilities {
            self.counted(capability, UNREADABLE);
        }
    }

    fn close_server(&mut self) {
        if let Some(mut server) = self.server.take() {
            server.close();
        }
        self.serving = None;
        self.mark(None);
        self.counted(API, "stopped");
    }

    /// `_mark(stamp)`: where the server stands, as the card reads it. Never fatal.
    fn mark(&self, stamp: Option<&str>) {
        let state = self.runtime.state();
        let api = string(API);
        let found = if stamp == Some(BOUND) {
            self.server
                .as_ref()
                .map(|server| server.addresses())
                .unwrap_or_default()
        } else {
            Vec::new()
        };
        for (place, key) in LAN_KEYS.iter().enumerate() {
            match found.get(place) {
                Some(address_text) => {
                    if let Some(value) = address::ipv4(address_text) {
                        let _ = state.stamp(&api, &string(key), &Value::from(i64::from(value)));
                    }
                }
                None => {
                    let _ = state.unstamp(&api, &string(key));
                }
            }
        }
        for key in [BOUND, TAKEN] {
            if Some(key) == stamp {
                let at = (self.runtime.clock().trunc() as i64).max(1);
                let _ = state.stamp(&api, &string(key), &Value::from(at));
            } else {
                let _ = state.unstamp(&api, &string(key));
            }
        }
    }

    fn stop_poll(&mut self) {
        if let Some(stop) = self.stop.take() {
            stop.set();
        }
        if let Some(thread) = self.thread.take() {
            // join(timeout=1): a read held open ends by itself and obeys nothing it brought.
            let until = std::time::Instant::now() + std::time::Duration::from_secs(1);
            while !thread.is_finished() && std::time::Instant::now() < until {
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            if thread.is_finished() {
                let _ = thread.join();
            }
        }
        self.counted(TELEGRAM, "stopped");
    }

    /// `close()`.
    pub fn close(&mut self) {
        if self.server.is_some() {
            self.close_server();
        }
        if self.thread.is_some() {
            self.stop_poll();
        }
    }
}

/// `serve(runtime, server=, poller=, sleep=, rounds=)`: the resident's life; its exit code.
pub fn serve(
    runtime: SharedRuntime,
    server: ServerFactory,
    poller: Poller,
    sleep: &dyn Fn(f64),
    rounds: Option<usize>,
) -> i32 {
    let mut roles = Roles::new(runtime, server, poller);
    let mut count = 0;
    while roles.follow() {
        count += 1;
        if rounds.is_some_and(|rounds| count >= rounds) {
            break;
        }
        sleep(CHECK);
    }
    roles.close();
    EXIT_DONE
}
