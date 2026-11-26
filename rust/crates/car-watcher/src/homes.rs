//! `runtime/homes.py`: the Codex homes a watcher holds beside the default one (v0.6.15-beta), each recovered by an
//! engine of its own.
//!
//! Up to three more are named in Settings, and each one this watcher can lock gets a [`HomeRun`]: a reader of that
//! home, a backend whose CODEX_HOME is that home (one codex.exe for all), a home lock on it held for the run's life,
//! and an engine with the NULL plug, the watcher's one dispatch lock and the home's key. A home whose lock is busy,
//! whose folder cannot be read, or that is the same folder as one already watched is not watched at all, and is
//! tried again every RETRY_SECONDS. A home taken out of Settings has every record waiting in it cancelled, final
//! (`home_removed`), and its run kept - detecting and sending nothing - until none of its records may still be in
//! Codex's queue; only then is its lock let go. Whatever goes wrong with another home costs that home alone.

use car_machine::json::{Map, Str, Value};
use car_machine::vocab_gen::domain_states::WATCHED;
use car_policy::settings::homes as configured;
use car_store::Store;

use crate::fail::{Failed, Res, guarded};
use crate::watchloop::{Adapter, TickEngine};

/// How often a home that could not be watched is tried again, and how often a watched one is asked whether the
/// ChatGPT app runs on it.
pub const RETRY_SECONDS: f64 = 600.0;
pub const REMOVED: &str = "home_removed";

/// A home's lock, held.
pub trait HeldLock {
    /// The folder's identity, as `HomeLock.identity` reads it.
    fn identity(&self) -> Option<String>;
    fn held(&self) -> bool;
    fn exit(&mut self);
}

/// A home's backend, as the homes ask it.
pub trait HomeBackend {
    /// `backend.app_identity()`.
    fn app_identity(&mut self) -> Res<Value>;
}

/// What a home's run is built from and asked of the watcher (`App`'s methods `Homes` calls).
pub trait HomesApp {
    /// `self.settings`, as in force.
    fn values(&self) -> Value;
    fn info(&self, line: &str);
    /// `_record_failure(label)`.
    fn record_failure(&self, label: &str, failed: &Failed);
    fn now(&mut self) -> f64;
    fn monotonic(&mut self) -> f64;
    /// The settings' questions about paths.
    fn path_os(&self) -> std::sync::Arc<dyn car_policy::settings::os::Os + Send + Sync>;
    /// `self.app.backend().codex_exe`, or None where no backend can be had.
    fn default_codex_exe(&mut self) -> Option<String>;
    /// `self.app.backend().app_identity()`.
    fn default_app_identity(&mut self) -> Res<Value>;
    /// The identity of the default home's lock.
    fn default_lock_identity(&self) -> Option<String>;
    /// `self.app.codex_home`.
    fn codex_home(&self) -> String;
    /// `self.app.extra_home_lock(path).__enter__()`.
    fn extra_home_lock(&mut self, path: &str) -> Result<Box<dyn HeldLock>, Adapter>;
    /// `home_backend(path, exe)`.
    fn home_backend(&mut self, path: &str, exe: &str) -> Res<Box<dyn HomeBackend>>;
    /// `home_engine(store, source, backend, key, held)`: the engine of that home, its lock read through `held`.
    fn home_engine(
        &mut self,
        store: &Store,
        path: &str,
        exe: &str,
        key: &str,
        held: std::rc::Rc<std::cell::RefCell<Box<dyn HeldLock>>>,
    ) -> Res<Box<dyn TickEngine>>;
}

/// `HomeRun`: one extra Codex home this watcher holds.
pub struct HomeRun {
    pub key: String,
    pub path: String,
    pub alias: Value,
    pub lock: std::rc::Rc<std::cell::RefCell<Box<dyn HeldLock>>>,
    pub backend: Box<dyn HomeBackend>,
    pub engine: Box<dyn TickEngine>,
    pub retiring: bool,
    pub other_home: bool,
    pub asked_at: f64,
}

impl HomeRun {
    fn close(&mut self) {
        let lock = std::rc::Rc::clone(&self.lock);
        crate::fail::quietly(move || lock.borrow_mut().exit());
    }
}

/// `Homes`: every extra Codex home of one watcher, ticked after the default home's engine, on the same thread.
#[derive(Default)]
pub struct Homes {
    pub runs: Vec<HomeRun>,
    /// key -> HomeState of a configured home not watched now.
    pub states: Vec<(String, &'static str)>,
    tried: Vec<(String, f64)>,
    swept: bool,
    exe: Option<String>,
}

/// `Path(text)`'s `str`.
fn path_of(text: &Str) -> String {
    car_machine::winpath::path_str(&crate::fail::lossy(text))
}

fn put<T>(list: &mut Vec<(String, T)>, key: &str, value: T) {
    match list.iter_mut().find(|(each, _)| each == key) {
        Some(slot) => slot.1 = value,
        None => list.push((key.to_owned(), value)),
    }
}

fn find<'a, T>(list: &'a [(String, T)], key: &str) -> Option<&'a T> {
    list.iter().find(|(each, _)| each == key).map(|(_, value)| value)
}

impl Homes {
    pub fn new() -> Homes {
        Homes::default()
    }

    /// `configured()`: key -> (path, alias) for each home Settings name beside the default, as the settings coerced
    /// them, in Settings' order (a key named twice keeps its first place and its last value).
    pub fn configured(app: &dyn HomesApp) -> Vec<(String, (String, Value))> {
        let values = app.values();
        let field = match &values {
            Value::Object(map) => map
                .get(configured::FIELD)
                .cloned()
                .unwrap_or(Value::Array(Vec::new())),
            _ => Value::Array(Vec::new()),
        };
        let os = app.path_os();
        let entries = configured::coerce(&*os, &field, &Value::Array(Vec::new()));
        let mut found: Vec<(String, (String, Value))> = Vec::new();
        if let Value::Array(entries) = entries {
            for entry in entries {
                let Value::Object(entry) = entry else {
                    continue;
                };
                let Some(Value::Str(path)) = entry.get("path") else {
                    continue;
                };
                let Ok(key) = configured::key(&*os, path) else {
                    continue;
                };
                let alias = entry.get("alias").cloned().unwrap_or(Value::Null);
                put(&mut found, &key, (path_of(path), alias));
            }
        }
        found
    }

    /// `sync(store)`: bring the runs in line with Settings - retire what was removed, let go of what has settled,
    /// start what can be started (each at most every RETRY_SECONDS), and rebuild every engine on a new codex.exe.
    pub fn sync(&mut self, app: &mut dyn HomesApp, store: &Store) -> Res<()> {
        let wanted = Homes::configured(app);
        let now = app.monotonic();
        let os = app.path_os();
        let written = |path: &str| configured::as_written(&*os, &Str::from(path));
        let named: Vec<Str> = wanted.iter().map(|(_, (path, _))| written(path)).collect();
        if !self.swept {
            let orphans: Vec<String> = store
                .home_keys()?
                .iter()
                .map(car_machine::pytext::py_str)
                .filter(|key| find(&wanted, key).is_none())
                .collect();
            if orphans.is_empty()
                || !wanted.iter().any(|(_, (path, _))| {
                    configured::problem(&*os, &Str::from(path.as_str())) == Some(configured::MISSING)
                })
            {
                self.swept = true;
                for key in orphans {
                    let at = app.now();
                    store.cancel_home(&key, at, REMOVED)?;
                }
            }
        }
        let mut index = 0;
        while index < self.runs.len() {
            let key = self.runs[index].key.clone();
            let present = find(&wanted, &key).is_some();
            let run = &mut self.runs[index];
            if !present && !run.retiring && named.contains(&written(&run.path)) {
                index += 1;
                continue;
            }
            if !present && !run.retiring {
                run.retiring = true;
                run.engine.set_retiring(true);
                let at = app.now();
                let cancelled = store.cancel_home(&key, at, REMOVED)?;
                app.info(&format!(
                    "a Codex home was removed from Settings; {cancelled} waiting recover{} cancelled, and it is watched until what was sent there settles",
                    if cancelled == 1 { "y" } else { "ies" }
                ));
            } else if present && run.retiring {
                run.retiring = false;
                run.engine.set_retiring(false);
            }
            if run.retiring {
                let watched: Vec<String> = WATCHED.iter().map(|each| (*each).to_owned()).collect();
                let mut in_flight = false;
                for row in store.records_in(&watched, Some(&key))? {
                    let state = row.get("state").cloned().unwrap_or(Value::Null);
                    let queue = row.get("queue_id").cloned().unwrap_or(Value::Null);
                    if car_store::machine::may_be_queued(&state, &queue)? {
                        in_flight = true;
                        break;
                    }
                }
                if !in_flight {
                    let mut gone = self.runs.remove(index);
                    gone.close();
                    app.info("a removed Codex home has nothing in flight any more; its lock is let go");
                    continue;
                }
            }
            index += 1;
        }
        let exe = guarded(|| Ok(app.default_codex_exe())).unwrap_or(None);
        if let Some(exe) = &exe
            && Some(exe) != self.exe.as_ref()
        {
            self.exe = Some(exe.clone());
            for run in &mut self.runs {
                run.backend = app.home_backend(&run.path, exe)?;
                run.engine =
                    app.home_engine(store, &run.path, exe, &run.key, std::rc::Rc::clone(&run.lock))?;
                run.engine.set_retiring(run.retiring);
            }
        }
        for (key, (path, alias)) in &wanted {
            if let Some(run) = self.runs.iter_mut().find(|run| &run.key == key) {
                run.alias = alias.clone();
                if now - run.asked_at >= RETRY_SECONDS {
                    run.asked_at = now;
                    let asked = guarded(|| {
                        let default = app.default_app_identity()?;
                        if !car_machine::pyval::truthy(&default) {
                            return Ok(false);
                        }
                        Ok(!car_machine::pyval::truthy(&run.backend.app_identity()?))
                    });
                    run.other_home = asked.unwrap_or(false);
                }
                continue;
            }
            if find(&self.tried, key).is_some_and(|at| now - at < RETRY_SECONDS) {
                continue;
            }
            put(&mut self.tried, key, now);
            let state = self.start(app, store, key, path, alias, exe.as_deref())?;
            put(&mut self.states, key, state);
        }
        self.states.retain(|(key, _)| find(&wanted, key).is_some());
        Ok(())
    }

    /// `_start(store, key, path, alias, exe)`: watch one home, or say why it is not watched.
    fn start(
        &mut self,
        app: &mut dyn HomesApp,
        store: &Store,
        key: &str,
        path: &str,
        alias: &Value,
        exe: Option<&str>,
    ) -> Res<&'static str> {
        let os = app.path_os();
        let Some(exe) = exe else {
            return Ok("unavailable");
        };
        if configured::problem(&*os, &Str::from(path)).is_some() {
            return Ok("unavailable");
        }
        let mut taken: Vec<Option<String>> = vec![app.default_lock_identity()];
        taken.extend(self.runs.iter().map(|run| run.lock.borrow().identity()));
        if configured::key(&*os, &Str::from(app.codex_home().as_str())).ok().as_deref() == Some(key) {
            return Ok("duplicate");
        }
        let lock = match app.extra_home_lock(path) {
            Ok(lock) => lock,
            Err(Adapter(word)) => {
                return Ok(if word == "home_lock_busy" {
                    "lock_busy"
                } else {
                    "unavailable"
                });
            }
        };
        let lock = std::rc::Rc::new(std::cell::RefCell::new(lock));
        if taken.contains(&lock.borrow().identity()) {
            lock.borrow_mut().exit();
            return Ok("duplicate");
        }
        let built = (|| -> Res<(Box<dyn HomeBackend>, Box<dyn TickEngine>)> {
            let backend = app.home_backend(path, exe)?;
            let engine = app.home_engine(store, path, exe, key, std::rc::Rc::clone(&lock))?;
            Ok((backend, engine))
        })();
        let (backend, mut engine) = match built {
            Ok(found) => found,
            Err(failed) => {
                lock.borrow_mut().exit();
                return Err(failed);
            }
        };
        engine.set_retiring(false);
        self.runs.push(HomeRun {
            key: key.to_owned(),
            path: path.to_owned(),
            alias: alias.clone(),
            lock,
            backend,
            engine,
            retiring: false,
            other_home: false,
            asked_at: f64::NEG_INFINITY,
        });
        self.states.retain(|(each, _)| each != key);
        app.info("another Codex home is watched beside the default one");
        Ok("watched")
    }

    /// `tick()`: each home's engine; what fails costs that home alone.
    pub fn tick(&mut self, app: &mut dyn HomesApp) {
        for run in &mut self.runs {
            if let Err(failed) = guarded(|| run.engine.tick()) {
                app.record_failure("tick of another Codex home", &failed);
            }
        }
    }

    pub fn watch_needed(&mut self) -> Res<bool> {
        for run in &mut self.runs {
            if run.engine.watch_needed()? {
                return Ok(true);
            }
        }
        Ok(false)
    }

    pub fn watch(&mut self, app: &mut dyn HomesApp) {
        for run in &mut self.runs {
            if let Err(failed) = guarded(|| run.engine.watch()) {
                app.record_failure("watch of another Codex home", &failed);
            }
        }
    }

    pub fn apply_policy(&mut self, values: &Value, managed: &car_policy::settings::managed::Managed) {
        for run in &mut self.runs {
            run.engine.apply_policy(values, managed);
        }
    }

    /// `heartbeat()`: what the heartbeat keeps of each home; None with the default alone.
    pub fn heartbeat(&self, app: &dyn HomesApp) -> Value {
        let entry = |key: &str, state: &str| {
            let mut map = Map::new();
            map.insert("key".into(), Value::from(key));
            map.insert("state".into(), Value::from(state));
            Value::Object(map)
        };
        let mut listed = vec![("".to_owned(), entry("", "watched"))];
        for (key, _) in Homes::configured(app) {
            let state = match self.runs.iter().find(|run| run.key == key) {
                None => find(&self.states, &key).copied().unwrap_or("unavailable"),
                Some(run) if run.retiring => "retiring",
                Some(run) if run.other_home => "other_home",
                Some(_) => "watched",
            };
            listed.push((key.clone(), entry(&key, state)));
        }
        for run in &self.runs {
            if run.retiring && listed.iter().all(|(key, _)| *key != run.key) {
                listed.push((run.key.clone(), entry(&run.key, "retiring")));
            }
        }
        if listed.len() > 1 {
            Value::Array(listed.into_iter().take(4).map(|(_, value)| value).collect())
        } else {
            Value::Null
        }
    }

    /// `close()`.
    pub fn close(&mut self, _app: &mut dyn HomesApp) {
        for run in &mut self.runs {
            run.close();
        }
        self.runs.clear();
    }
}
