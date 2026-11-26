//! car-watcher's calls (S6.1): `watcher.loop` runs car-watcher's watch loop over a scripted world, and
//! `watcher.batch` runs the watcher's smaller pieces case by case.
//!
//! The world of `watcher.loop` is `tests/rustdiff/diffs_watcher_loop.py`'s, written once here and once in its
//! reference script, so both loops meet the same answers: the named objects (entered, busy, abandoned, refused),
//! every wait (stop, wake, or the time running out, on a clock of the script's own), the store's opens, the engine's
//! builds, ticks, watches and readings, the process's memory, and what the self-check asks. Nothing of the machine
//! is asked: no named object, no timer, no window, no Codex. The store is car-store's, in the case's scratch home,
//! so the heartbeat, the status file and the self-check file are the real writers' bytes.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::path::Path;
use std::rc::Rc;
use std::sync::Arc;

use car_machine::json::{Map, Value};
use car_policy::settings::managed::Managed;
use car_policy::settings::os::Os;
use car_store::Store;
use car_watcher::afterwork::AfterWork;
use car_watcher::fail::{Failed, Res};
use car_watcher::health::{Health, OwnProcess};
use car_watcher::homes::{HeldLock, HomeBackend, HomesApp};
use car_watcher::waking::{Listener, PowerPort, Waking};
use car_watcher::watchloop::{Adapter, Fired, Loop, TickEngine, World, run};

use crate::object;

mod batch;
mod launch;
pub use batch::batch;
pub use launch::run as launcher;

fn field<'a>(map: &'a Map, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map.get(key).unwrap_or(&NULL)
}

fn list(map: &Map, key: &str) -> Vec<Value> {
    match map.get(key) {
        Some(Value::Array(items)) => items.clone(),
        _ => Vec::new(),
    }
}

fn number(value: &Value) -> f64 {
    car_machine::pytext::to_float(value).unwrap_or(0.0)
}

/// A scripted answer: `{"raise": class}` or the value.
fn raised(value: &Value) -> Option<Failed> {
    match value {
        Value::Object(map) => match map.get("raise") {
            Some(Value::Str(class)) => Some(Failed::new(class.as_str().unwrap_or("Exception"), "")),
            _ => None,
        },
        _ => None,
    }
}

/// The script's clock: the wall time, and the monotonic clock a constant behind it.
#[derive(Clone)]
struct Clock(Rc<RefCell<f64>>);

impl Clock {
    fn now(&self) -> f64 {
        *self.0.borrow()
    }
    fn advance(&self, seconds: f64) {
        *self.0.borrow_mut() += seconds.max(0.0);
    }
}

const MONOTONIC_BEHIND: f64 = 1_700_000_000.0;

/// What every call of the world wrote, in order.
type Calls = Rc<RefCell<Vec<Value>>>;

fn call(calls: &Calls, items: Vec<Value>) {
    calls.borrow_mut().push(Value::Array(items));
}

struct Script {
    items: RefCell<BTreeMap<String, Vec<Value>>>,
}

impl Script {
    fn new(script: &Map, keys: &[&str]) -> Script {
        let mut items = BTreeMap::new();
        for key in keys {
            items.insert((*key).to_owned(), list(script, key));
        }
        Script {
            items: RefCell::new(items),
        }
    }

    /// The next answer of a list, or `otherwise` once it is spent.
    fn next(&self, key: &str, otherwise: Value) -> Value {
        let mut items = self.items.borrow_mut();
        match items.get_mut(key) {
            Some(found) if !found.is_empty() => found.remove(0),
            _ => otherwise,
        }
    }
}

struct ScriptEngine {
    script: Rc<Script>,
    calls: Calls,
    detection_failed: Option<bool>,
    failures: Vec<Value>,
}

impl car_watcher::waking::Sleeper for ScriptEngine {
    fn after_sleep(&mut self, since: f64, slept: f64) -> Res<()> {
        call(
            &self.calls,
            vec!["after_sleep".into(), Value::Float(since), Value::Float(slept)],
        );
        Ok(())
    }
}

impl car_watcher::afterwork::Activity for ScriptEngine {
    fn activity(&mut self, threads: &[String]) -> Res<Value> {
        call(
            &self.calls,
            vec![
                "activity".into(),
                Value::Array(threads.iter().map(|t| Value::from(t.as_str())).collect()),
            ],
        );
        Ok(Value::Null)
    }
    fn follow_option(&self) -> Option<Value> {
        None
    }
}

impl TickEngine for ScriptEngine {
    fn tick(&mut self) -> Res<()> {
        call(&self.calls, vec!["tick".into()]);
        let outcome = self.script.next("ticks", Value::from("ok"));
        match raised(&outcome) {
            Some(failed) => Err(failed),
            None => Ok(()),
        }
    }
    fn watch_needed(&mut self) -> Res<bool> {
        let found = self.script.next("watch_needed", Value::Bool(false));
        match raised(&found) {
            Some(failed) => Err(failed),
            None => Ok(car_machine::pyval::truthy(&found)),
        }
    }
    fn watch(&mut self) -> Res<()> {
        call(&self.calls, vec!["watch".into()]);
        match raised(&self.script.next("watches", Value::Null)) {
            Some(failed) => Err(failed),
            None => Ok(()),
        }
    }
    fn last_usage(&mut self) -> Res<Option<(Value, Value)>> {
        match self.script.next("usage", Value::Null) {
            Value::Array(pair) if pair.len() == 2 => Ok(Some((pair[0].clone(), pair[1].clone()))),
            _ => Ok(None),
        }
    }
    fn detection_failed(&self) -> Option<bool> {
        self.detection_failed
    }
    fn handed_waits(&self) -> Map {
        Map::new()
    }
    fn apply_policy(&mut self, _values: &Value, _managed: &Managed) {}
    fn set_retiring(&mut self, _retiring: bool) {}
    fn latest_failures(&mut self, since: f64) -> Res<Vec<Value>> {
        call(&self.calls, vec!["latest_failures".into(), Value::Float(since)]);
        Ok(self.failures.clone())
    }
}

struct Memory {
    script: Rc<Script>,
}

impl OwnProcess for Memory {
    fn memory(&self) -> Option<(u64, u64)> {
        match self.script.next("memory", Value::Null) {
            Value::Array(pair) if pair.len() == 2 => Some((
                number(&pair[0]) as u64,
                number(&pair[1]) as u64,
            )),
            _ => None,
        }
    }
    fn sign_in(&self) -> Option<String> {
        Some("S-1-5-21-0-0-0-1001:7".into())
    }
    fn booted_at(&self) -> Option<f64> {
        Some(1_700_000_000.0)
    }
}

struct NoListener;

impl Listener for NoListener {
    fn start(&mut self) -> bool {
        false
    }
    fn stop(&mut self) {}
}

struct NoPower(Calls);

impl PowerPort for NoPower {
    fn awake_seconds(&self) -> Option<f64> {
        None
    }
    fn listener(&self, _heard: Arc<dyn Fn() + Send + Sync>) -> Box<dyn Listener> {
        call(&self.0, vec!["listener".into()]);
        Box::new(NoListener)
    }
    fn keep_awake(&self, on: bool) -> bool {
        call(&self.0, vec!["keep_awake".into(), Value::Bool(on)]);
        false
    }
    fn on_mains(&self) -> Option<bool> {
        None
    }
}

struct ScriptWorld {
    home: String,
    state_dir: String,
    status_file: String,
    self_check_file: String,
    script: Rc<Script>,
    whole: Map,
    clock: Clock,
    calls: Calls,
    lines: Rc<RefCell<Vec<Value>>>,
    os: Arc<dyn Os + Send + Sync>,
    log_clock: car_watcher::clock::LogClock,
}

impl HomesApp for ScriptWorld {
    fn values(&self) -> Value {
        field(&self.whole, "values").clone()
    }
    fn info(&self, line: &str) {
        self.lines.borrow_mut().push(Value::from(line.replace(&self.home, "<HOME>")));
    }
    fn record_failure(&self, label: &str, failed: &Failed) {
        call(
            &self.calls,
            vec!["failure".into(), label.into(), failed.class.as_str().into()],
        );
        self.info(&format!(
            "{label} failed ({}); no submission was made",
            failed.class
        ));
    }
    fn now(&mut self) -> f64 {
        self.clock.now()
    }
    fn monotonic(&mut self) -> f64 {
        self.clock.now() - MONOTONIC_BEHIND
    }
    fn path_os(&self) -> Arc<dyn Os + Send + Sync> {
        Arc::clone(&self.os)
    }
    fn default_codex_exe(&mut self) -> Option<String> {
        None
    }
    fn default_app_identity(&mut self) -> Res<Value> {
        Err(Failed::new("OSError", ""))
    }
    fn default_lock_identity(&self) -> Option<String> {
        None
    }
    fn codex_home(&self) -> String {
        format!("{}\\codex", self.home)
    }
    fn extra_home_lock(&mut self, _path: &str) -> Result<Box<dyn HeldLock>, Adapter> {
        Err(Adapter("home_lock_busy".into()))
    }
    fn home_backend(&mut self, _path: &str, _exe: &str) -> Res<Box<dyn HomeBackend>> {
        Err(Failed::new("OSError", ""))
    }
    fn home_engine(
        &mut self,
        _store: &Store,
        _path: &str,
        _exe: &str,
        _key: &str,
        _held: Rc<RefCell<Box<dyn HeldLock>>>,
    ) -> Res<Box<dyn TickEngine>> {
        Err(Failed::new("OSError", ""))
    }
}

impl ScriptWorld {
    fn enter(&mut self, what: &str) -> Result<(), Adapter> {
        let answer = self.script.next(what, Value::from("ok"));
        call(&self.calls, vec!["enter".into(), what.into()]);
        match answer.as_str_value() {
            Some("ok") | Some("abandoned") => Ok(()),
            Some(word) => Err(Adapter(word.to_owned())),
            None => Ok(()),
        }
    }
}

trait AsStr {
    fn as_str_value(&self) -> Option<&str>;
}

impl AsStr for Value {
    fn as_str_value(&self) -> Option<&str> {
        match self {
            Value::Str(text) => text.as_str(),
            _ => None,
        }
    }
}

impl World for ScriptWorld {
    fn enter_mutex(&mut self) -> Result<bool, Adapter> {
        let answer = self.script.next("mutex", Value::from("ok"));
        call(&self.calls, vec!["enter".into(), "mutex".into()]);
        match answer.as_str_value() {
            Some("abandoned") => Ok(true),
            Some("ok") | None => Ok(false),
            Some(word) => Err(Adapter(word.to_owned())),
        }
    }
    fn exit_mutex(&mut self) {
        call(&self.calls, vec!["exit".into(), "mutex".into()]);
    }
    fn enter_stop(&mut self) -> Result<(), Adapter> {
        self.enter("stop")
    }
    fn exit_stop(&mut self) {
        call(&self.calls, vec!["exit".into(), "stop".into()]);
    }
    fn enter_wake(&mut self) -> Result<(), Adapter> {
        self.enter("wake")
    }
    fn exit_wake(&mut self) {
        call(&self.calls, vec!["exit".into(), "wake".into()]);
    }
    fn enter_home_lock(&mut self) -> Result<(), Adapter> {
        self.enter("home_lock")
    }
    fn exit_home_lock(&mut self) {
        call(&self.calls, vec!["exit".into(), "home_lock".into()]);
    }
    fn wait_for(&mut self, wake: bool, seconds: f64) -> Fired {
        call(
            &self.calls,
            vec!["wait".into(), Value::Bool(wake), Value::Float(seconds)],
        );
        let answer = self.script.next("waits", Value::from("stop"));
        let (fired, after) = match &answer {
            Value::Object(map) => (
                field(map, "fired").as_str_value().map(str::to_owned),
                map.get("after").map(number),
            ),
            other => (other.as_str_value().map(str::to_owned), None),
        };
        let fired = match fired.as_deref() {
            Some("stop") => Fired::Stop,
            Some("wake") => Fired::Wake,
            _ => Fired::Timeout,
        };
        let after = after.unwrap_or(if fired == Fired::Timeout { seconds } else { 0.5 });
        self.clock.advance(after);
        fired
    }
    fn sleep(&mut self, seconds: f64) {
        call(&self.calls, vec!["sleep".into(), Value::Float(seconds)]);
        self.clock.advance(seconds);
    }
    fn pid(&self) -> u32 {
        4242
    }
    fn session_id(&mut self) -> String {
        "0123456789ab".into()
    }
    fn clock_text(&self, seconds: f64) -> String {
        use car_machine::localclock::LocalClock;
        match car_platform::localclock::Crt.localtime(seconds) {
            Ok(tm) => format!("{:02}:{:02}:{:02}", tm.hour, tm.min, tm.sec),
            Err(_) => "00:00:00".into(),
        }
    }
    fn version(&self) -> String {
        field(&self.whole, "version").as_str_value().unwrap_or_default().to_owned()
    }
    fn state_dir(&self) -> String {
        self.state_dir.clone()
    }
    fn edition_badge(&self) -> Option<String> {
        None
    }
    fn open_store(&mut self) -> Res<(Store, Option<i64>)> {
        call(&self.calls, vec!["open".into()]);
        if let Some(failed) = raised(&self.script.next("opens", Value::Null)) {
            return Err(failed);
        }
        let mut options = car_store::Options::new(crate::links::for_store());
        options.migrate = true;
        options.check = true;
        let store = Store::open_with(Path::new(&self.state_dir), options)?;
        let from = store.migrated_from;
        Ok((store, from))
    }
    fn engine_moved(&mut self) -> bool {
        call(&self.calls, vec!["moved".into()]);
        false
    }
    fn engine(&mut self, _store: &Store) -> Res<Box<dyn TickEngine>> {
        call(&self.calls, vec!["build".into()]);
        if let Some(failed) = raised(&self.script.next("builds", Value::Null)) {
            return Err(failed);
        }
        Ok(Box::new(ScriptEngine {
            script: Rc::clone(&self.script),
            calls: Rc::clone(&self.calls),
            detection_failed: match field(&self.whole, "detection_failed") {
                Value::Bool(flag) => Some(*flag),
                _ => None,
            },
            failures: list(&self.whole, "failures"),
        }))
    }
    fn compatibility_tick(&mut self) {
        call(&self.calls, vec!["compat".into()]);
    }
    fn refresh_settings(&mut self, _engine: Option<&mut Box<dyn TickEngine>>) {
        call(&self.calls, vec!["refresh".into()]);
    }
    fn engine_state(&self) -> String {
        "unknown".into()
    }
    fn managed(&self) -> Managed {
        Managed::default()
    }
    fn settings_good(&self) -> bool {
        true
    }
    fn failure_baseline(&mut self) {
        call(&self.calls, vec!["baseline".into()]);
    }
    fn sweep_set_aside(&mut self) {
        call(&self.calls, vec!["sweep".into()]);
    }
    fn new_health(&mut self) -> Res<Health> {
        let clock = self.clock.clone();
        Ok(Health::new(
            &self.status_file,
            &self.version(),
            Box::new(Memory {
                script: Rc::clone(&self.script),
            }),
            Box::new(move || clock.now()),
        ))
    }
    fn new_waking(&mut self) -> Option<Waking> {
        let clock = self.clock.clone();
        Some(Waking::new(
            Box::new(NoPower(Rc::clone(&self.calls))),
            Arc::new(|| Ok(())),
            Box::new(move || clock.now()),
        ))
    }
    fn new_afterwork(&mut self) -> Res<AfterWork> {
        Err(Failed::new("OSError", ""))
    }
    fn watcher_notice(&self, event: &str, detail: Map, last: bool) -> Res<()> {
        call(
            &self.calls,
            vec![
                "notice".into(),
                event.into(),
                Value::Object(detail),
                Value::Bool(last),
            ],
        );
        Ok(())
    }
    fn start_tray(&mut self) -> bool {
        false
    }
    fn update_tray(&mut self, _store: &Store, _blocked: bool) {}
    fn edition_surface(&mut self, _store: &Store) {}
    fn stop_tray(&mut self) {}
    fn os(&self) -> Arc<dyn Os + Send + Sync> {
        Arc::clone(&self.os)
    }
    fn log_clock(&self) -> &dyn car_config::logbook::Clock {
        &self.log_clock
    }
    fn app_runs(&mut self) -> Option<bool> {
        call(&self.calls, vec!["app_runs".into()]);
        match field(&self.whole, "app_runs") {
            Value::Bool(flag) => Some(*flag),
            _ => None,
        }
    }
    fn recovery_facts(
        &mut self,
        _store: &Store,
        _engine: &mut dyn TickEngine,
    ) -> Res<(Option<bool>, BTreeMap<&'static str, Option<bool>>)> {
        call(&self.calls, vec!["facts".into()]);
        let mut facts = BTreeMap::new();
        if let Value::Object(given) = field(&self.whole, "facts") {
            for rule in car_engine::impossible::RECOVERY_RULES {
                if let Some(found) = given.get(*rule) {
                    facts.insert(
                        *rule,
                        match found {
                            Value::Bool(flag) => Some(*flag),
                            _ => None,
                        },
                    );
                }
            }
        }
        let runs = match field(&self.whole, "facts_runs") {
            Value::Bool(flag) => Some(*flag),
            _ => None,
        };
        Ok((runs, facts))
    }
    fn layout(&mut self) -> Res<Value> {
        Ok(Value::Null)
    }
    fn write_self_check(&mut self, written: &Value) -> Res<()> {
        car_codex::compat::files::write_json_atomic(&self.self_check_file, written, "selfcheck.")
            .map_err(|_| Failed::new("OSError", ""))
    }
}

/// `watcher.loop` {home, script}: the loop run once over the script's world.
pub fn run_loop(request: &Map) -> Value {
    let home = field(request, "home").as_str_value().unwrap_or_default().to_owned();
    let script = match field(request, "script") {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    };
    let state_dir = format!("{home}\\config");
    let _ = std::fs::create_dir_all(&state_dir);
    let _ = std::fs::create_dir_all(format!("{home}\\logs"));
    let keys = [
        "mutex", "stop", "wake", "home_lock", "waits", "opens", "builds", "ticks", "watches",
        "watch_needed", "usage", "memory",
    ];
    let calls: Calls = Rc::default();
    let lines: Rc<RefCell<Vec<Value>>> = Rc::default();
    let clock = Clock(Rc::new(RefCell::new(number(field(&script, "clock")))));
    let mut world = ScriptWorld {
        home: home.clone(),
        status_file: format!("{state_dir}\\status.json"),
        self_check_file: format!("{state_dir}\\selfcheck.json"),
        state_dir,
        script: Rc::new(Script::new(&script, &keys)),
        whole: script.clone(),
        clock: clock.clone(),
        calls: Rc::clone(&calls),
        lines: Rc::clone(&lines),
        os: Arc::new(car_control::host::PlatformOs),
        log_clock: car_watcher::clock::LogClock::here(),
    };
    let once = matches!(field(&script, "once"), Value::Bool(true));
    let poll = match field(&script, "poll") {
        Value::Int(number) => number.as_i64(),
        _ => None,
    };
    let mut state = Loop::new();
    let code = run(&mut world, &mut state, once, poll);
    let calls = calls.borrow().clone();
    let lines = lines.borrow().clone();
    object([
        ("code", Value::from(i64::from(code))),
        ("lines", Value::Array(lines)),
        ("calls", Value::Array(calls)),
    ])
}
