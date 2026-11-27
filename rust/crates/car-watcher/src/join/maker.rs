//! [`Joined`]: what `runtime/app.py` builds the engine from, on this machine.

use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::Path;
use std::rc::Rc;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use car_codex::system::System;
use car_codex::transport::Backend as Codex;
use car_engine::transport::Transport;
use car_engine::{Engine, Given};
use car_machine::json::{Map, Value};
use car_policy::plug::Guarded;
use car_policy::settings::managed::Managed;
use car_store::Store;

use super::Bound;
use super::engine::{Driven, Words};
use super::store::EngineStore;
use crate::app::EngineMaker;
use crate::fail::{Failed, Res, guarded};
use crate::homes::{HeldLock, HomeBackend};
use crate::watchloop::{RecoveryFacts, TickEngine};

/// `ENGINE_LOG_WORDS[word]`: what the log says about the engine it just accepted.
fn engine_log_words(word: &str) -> &'static str {
    match word {
        "verified" => {
            "is verified: its local checks pass, and the registry data in force verifies this build"
        }
        "structurally_compatible" => {
            "is compatible: its local checks pass (`codex queue` still offers --thread/--message), and the registry data in force does not verify this build"
        }
        "incompatible" => {
            "passes its local checks, but the registry data in force marks it incompatible; nothing is sent while that data is in force"
        }
        "checked" => {
            "is checked: its local checks pass, and the registry data in force records the maintainer's checks passing on this build; no real recovery has verified it yet"
        }
        _ => ENGINE_LOG_CHECKS_ONLY,
    }
}

const ENGINE_LOG_CHECKS_ONLY: &str =
    "passes its local checks (`codex queue` still offers --thread/--message)";

/// v0.6.13: a minute, then twice as long each time, up to every 15 minutes.
pub const ELSEWHERE_FIRST_WAIT: f64 = 60.0;
pub const ELSEWHERE_LONGEST_WAIT: f64 = 15.0 * 60.0;

/// `_file_stamp(path)`: (size, write time in ns), or None when nothing stands there.
type Stamp = Option<(u64, u128)>;

fn file_stamp(path: &str) -> Stamp {
    let meta = std::fs::metadata(path).ok()?;
    let modified = meta
        .modified()
        .ok()?
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_nanos();
    Some((meta.len(), modified))
}

/// The stamp as the layout file keeps it (`[size, mtime_ns]`, or null).
fn stamp_value(stamp: Stamp) -> Value {
    match stamp {
        Some((size, ns)) => Value::Array(vec![
            Value::from(size),
            Value::from(i64::try_from(ns).unwrap_or(i64::MAX)),
        ]),
        None => Value::Null,
    }
}

fn codex_failed(error: &car_codex::errors::Error) -> Failed {
    Failed::new(error.class(), error.message())
}

fn held(transport: &Transport) -> MutexGuard<'_, Codex> {
    transport.0.lock().unwrap_or_else(PoisonError::into_inner)
}

/// `os.path.normcase`.
fn normcase(path: &str) -> String {
    path.replace('/', "\\").to_lowercase()
}

/// `random.Random().random()`.
fn draw() -> f64 {
    let bytes = car_control::host::std_random(8);
    let mut word = [0u8; 8];
    for (slot, byte) in word.iter_mut().zip(bytes) {
        *slot = byte;
    }
    (u64::from_le_bytes(word) >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
}

/// A home's backend as the homes ask it.
struct HomeTransport(Arc<Transport>);

impl HomeBackend for HomeTransport {
    fn app_identity(&mut self) -> Res<Value> {
        held(&self.0)
            .app_identity()
            .map(|found| found.unwrap_or(Value::Null))
            .map_err(|error| codex_failed(&error))
    }
}

/// The product's engine maker.
#[derive(Default)]
pub struct Joined {
    bound: Option<Bound>,
    system: Option<Arc<dyn System>>,
    /// `self._backend`, shared with the engine built on it and its `engine_state`.
    backend: Rc<RefCell<Option<Arc<Transport>>>>,
    backend_stamp: Stamp,
    discovery: Vec<(String, Value)>,
    elsewhere_seen: BTreeSet<(String, (u64, u128))>,
    elsewhere_due: f64,
    elsewhere_wait: f64,
    compat: Option<car_codex::compat::evaluator::Evaluator>,
    layout: Option<car_codex::layout::Watch>,
    /// `self._engine_state`.
    state: Rc<RefCell<Option<String>>>,
    /// `self._dispatch_lock`: one for every engine of this process.
    dispatch_lock: Arc<Mutex<()>>,
    /// The backends `home_backend` made, by home path, for the engine `home_engine` makes next.
    homes: HashMap<String, Arc<Transport>>,
}

impl Joined {
    pub fn new() -> Joined {
        Joined {
            elsewhere_wait: ELSEWHERE_FIRST_WAIT,
            ..Joined::default()
        }
    }

    fn bound(&self) -> Res<&Bound> {
        self.bound
            .as_ref()
            .ok_or_else(|| Failed::new("EngineNotJoined", "not bound"))
    }

    fn system(&mut self) -> Arc<dyn System> {
        Arc::clone(
            self.system
                .get_or_insert_with(|| Arc::new(car_codex::system::Platform::new())),
        )
    }

    fn version(bound: &Bound) -> String {
        car_config::codex::version(&bound.project_root, &mut |_| {})
    }

    /// The named engine, never second-guessed: the override or `CODEX_AUTO_RESUME_CODEX_EXE`.
    fn named(bound: &Bound) -> bool {
        bound.codex_exe.is_some()
            || std::env::var(car_config::paths::ENV_CODEX_EXE).is_ok_and(|found| !found.is_empty())
    }

    /// `App.backend()`.
    fn backend(&mut self) -> Res<Arc<Transport>> {
        if let Some(found) = self.backend.borrow().as_ref() {
            return Ok(Arc::clone(found));
        }
        let system = self.system();
        let bound = self
            .bound
            .take()
            .ok_or_else(|| Failed::new("EngineNotJoined", "not bound"))?;
        let found = self.discover(&system, &bound);
        self.bound = Some(bound);
        found
    }

    fn discover(&mut self, system: &Arc<dyn System>, bound: &Bound) -> Res<Arc<Transport>> {
        let version = Self::version(bound);
        let record: RefCell<Vec<(String, Value)>> = RefCell::new(Vec::new());
        let compatible = |path: &str| -> Result<(), String> {
            let mut probe =
                Codex::new(Arc::clone(system), &bound.codex_home, path, false, &version);
            let answer = probe.compatible();
            let checks = probe.last_checks().map_or(Value::Null, Value::Object);
            let mut kept = record.borrow_mut();
            match kept.iter_mut().find(|(each, _)| each == path) {
                Some(slot) => slot.1 = checks,
                None => kept.push((path.to_owned(), checks)),
            }
            answer.map_err(|error| error.message())
        };
        let asked = std::cell::Cell::new(false);
        let running = || {
            asked.set(true);
            car_codex::pairing::app_engines(system.as_ref()).ok()
        };
        let env = |name: &str| std::env::var(name).ok();
        let config = car_config::Os::here(false, Arc::new(crate::app::Probe));
        let chosen = car_config::codex::discover_codex_exe(
            bound.codex_exe.as_deref(),
            &compatible,
            Some(&running),
            !self.elsewhere_seen.is_empty(),
            true,
            &env,
            &config,
        );
        self.discovery = record.into_inner();
        if asked.get() {
            bound.log.info("the ChatGPT app was asked which Codex server it runs; where more than one official Codex engine passes the engine checks, the one it runs is the one driven");
        }
        let exe = chosen.map_err(|error| match error {
            car_config::codex::DiscoverError::Config(error) => Failed::new("ConfigError", error.0),
            car_config::codex::DiscoverError::Check(message) => {
                Failed::new("AdapterError", message)
            }
        })?;
        let mut backend = Codex::new(Arc::clone(system), &bound.codex_home, &exe, false, &version);
        backend.named_engine = Self::named(bound);
        backend.compatible().map_err(|error| codex_failed(&error))?;
        let engine_version = backend.engine_version.clone();
        let word = car_codex::compat::cache::engine_word(
            &registry_of(bound, Arc::clone(system)).bundled,
            &bound.paths.compat_cache_file,
            &engine_version.as_deref().map_or(Value::Null, Value::from),
            &version,
            crate::clock::wall(),
        );
        bound.log.info(&format!(
            "engine {} {}. Delivery is still proven per interruption before anything is marked resumed.",
            engine_version.as_deref().unwrap_or("None"),
            engine_log_words(word)
        ));
        self.backend_stamp = file_stamp(&backend.codex_exe);
        let (exe, home) = (backend.codex_exe.clone(), backend.codex_home.clone());
        let transport = Arc::new(Transport::new(backend));
        *self.backend.borrow_mut() = Some(Arc::clone(&transport));
        // v0.6.11: the edition's plug is told the Codex found here; NULL is told nothing.
        bound.plug.codex(&exe, &home);
        Ok(transport)
    }

    /// `_served_elsewhere()`.
    fn served_elsewhere(&mut self) -> BTreeSet<(String, (u64, u128))> {
        let Some(bound) = self.bound.as_ref() else {
            return BTreeSet::new();
        };
        if Self::named(bound) {
            return BTreeSet::new();
        }
        let served = match self.backend.borrow().as_ref() {
            Some(transport) => held(transport).served_elsewhere.clone(),
            None => return BTreeSet::new(),
        };
        let system = self.system();
        let mut stamps: BTreeMap<String, Stamp> = BTreeMap::new();
        for path in served {
            if car_codex::pairing::official_engine(system.as_ref(), &path).0 {
                stamps.insert(normcase(&path), file_stamp(&path));
            }
        }
        stamps
            .into_iter()
            .filter_map(|(key, stamp)| stamp.map(|stamp| (key, stamp)))
            .collect()
    }

    fn source(&self, bound: &Bound, home: &str) -> Res<car_codex::source::LocalSource> {
        let chains =
            car_codex::chains::memory(Some(Path::new(&bound.paths.split_chains_file)), true);
        car_codex::source::LocalSource::new(
            Arc::new(car_control::host::PlatformOs),
            home,
            Some(chains),
        )
        .map_err(|error| codex_failed(&error))
    }

    /// The keywords every engine of this watcher is given (`log`, `notify`, `language`, `engine_state`, `connectivity`,
    /// `dispatch_lock`, `open_store`, `once_words`, `options`).
    fn given(
        &self,
        bound: &Bound,
        home: &str,
        home_key: &str,
        home_lock: Box<dyn Fn() -> car_machine::pyval::Py<bool>>,
        plug: Arc<Guarded>,
    ) -> Res<Given> {
        let log = bound.log.clone();
        let notifier = self.source(bound, home)?;
        let announce = Arc::clone(&bound.announce);
        let toasts = crate::toasts::Toasts::new(
            Arc::new(move |event: &str, detail: &Map| {
                let identity = || {
                    let thread = detail.get("thread_id").and_then(super::text).unwrap_or("");
                    notifier.identity(thread).map_or(Value::Null, Value::Object)
                };
                announce(event, detail, &identity)
            }),
            {
                let log = log.clone();
                Arc::new(move |line: &str| log.info(line))
            },
        );
        let state = Rc::clone(&self.state);
        let backend = Rc::clone(&self.backend);
        let host = Arc::clone(&bound.host);
        let mut options = Map::new();
        options.insert(
            "delivery_timeout_seconds".into(),
            Value::from(car_engine::DELIVERY_TIMEOUT),
        );
        let environ = |name: &str| std::env::var(name).ok();
        let language = car_words::interface::language(&environ, &Vec::new).to_owned();
        Ok(Given {
            dispatch_lock: Some(Arc::clone(&self.dispatch_lock)),
            clock: Box::new(crate::clock::wall),
            log: Some(Box::new(move |thread, code, detail| {
                log.engine(thread, code, detail);
            })),
            options,
            notify: Some(Box::new(move |event, detail| {
                toasts.call(event, detail);
                Ok(())
            })),
            language: Some(language),
            home_lock: Some(home_lock),
            engine_state: Some(Box::new(move || {
                Ok(Value::from(engine_state(
                    state.borrow().as_deref(),
                    backend.borrow().as_ref(),
                )))
            })),
            plug,
            connectivity: Some(Box::new(move || {
                Ok(match host.internet() {
                    Ok(Some(found)) => Value::Bool(found),
                    _ => Value::Null,
                })
            })),
            home_key: home_key.to_owned(),
            open_store: true,
            once_words: Some(Box::new(Words {
                file: bound.paths.once_words_file.clone(),
                host: Arc::clone(&bound.host),
            })),
            draw: Box::new(draw),
            local: bound.host.local_clock(),
            environ: Box::new(|name| std::env::var(name).ok()),
            windows_languages: Box::new(Vec::new),
            os: Arc::new(car_control::host::PlatformOs),
        })
    }

    /// `_layout_look()`: never the watcher's failure.
    fn layout_look(&mut self) {
        let _ = guarded(|| {
            let bound = self.bound()?;
            if self.layout.is_none() {
                let log = bound.log.clone();
                self.layout = Some(car_codex::layout::Watch::new(
                    &bound.paths.codex_layout_file,
                    &Value::from(Self::version(bound)),
                    Box::new(move |line: &str| log.info(line)),
                    Box::new(crate::clock::monotonic),
                    std::process::id(),
                ));
            }
            let (found, engine_version) = match self.backend.borrow().as_ref() {
                Some(transport) => {
                    let backend = held(transport);
                    (
                        backend.layout.clone(),
                        backend
                            .engine_version
                            .as_deref()
                            .map_or(Value::Null, Value::from),
                    )
                }
                None => (None, Value::Null),
            };
            let stamp = stamp_value(self.backend_stamp);
            if let Some(watch) = self.layout.as_mut() {
                let _ = watch.look(found.as_ref(), &stamp, &engine_version);
            }
            Ok(())
        });
    }
}

/// The Compatibility Registry's files, as `compatio` finds them (`SystemHost::compat_view`'s).
fn registry_of(bound: &Bound, system: Arc<dyn System>) -> car_codex::compat::views::Registry {
    let data = Path::new(&bound.project_root)
        .join("src")
        .join("codex_auto_resume")
        .join("data");
    let text = |path: std::path::PathBuf| path.to_string_lossy().into_owned();
    car_codex::compat::views::Registry {
        system,
        config: car_config::Os::here(false, Arc::new(crate::app::Probe)),
        bundled: text(data.join("codex_compat.json")),
        reported: text(data.join("reported.json")),
        cache_file: bound.paths.compat_cache_file.clone(),
        report_file: bound.paths.compat_report_file.clone(),
        version: Joined::version(bound),
    }
}

/// `engine_state()`: the evaluator's word, else the answer before it.
fn engine_state(state: Option<&str>, backend: Option<&Arc<Transport>>) -> String {
    if let Some(state) = state {
        return state.to_owned();
    }
    match backend {
        None => "unknown".into(),
        Some(transport) if held(transport).engine_verified => "verified".into(),
        Some(_) => "structurally_compatible".into(),
    }
}

impl EngineMaker for Joined {
    fn bind(&mut self, bound: Bound) {
        self.bound = Some(bound);
    }
    fn refresh_codex_exe(&mut self, codex_exe: Option<String>) {
        if self.backend.borrow().is_none()
            && let Some(bound) = self.bound.as_mut()
        {
            bound.codex_exe = codex_exe;
        }
    }
    fn engine(
        &mut self,
        store: &Rc<Store>,
        values: &Map,
        managed: &Managed,
        plug: Arc<Guarded>,
    ) -> Res<Box<dyn TickEngine>> {
        let source = {
            let bound = self.bound()?;
            self.source(bound, &bound.codex_home)?
        };
        let backend = self.backend()?;
        let bound = self.bound()?;
        let home_lock = Rc::clone(&bound.home_lock);
        let given = self.given(
            bound,
            &bound.codex_home,
            "",
            Box::new(move || Ok(home_lock())),
            plug,
        )?;
        let mut engine = Engine::new(
            Box::new(EngineStore(Rc::clone(store), None)),
            Box::new(car_engine::seam::Codex(source)),
            Box::new(backend),
            given,
        );
        engine.apply_policy(&Value::Object(values.clone()), Some(managed.clone()));
        Ok(Box::new(Driven(engine)))
    }
    fn engine_moved(&mut self) -> bool {
        let Some(transport) = self.backend.borrow().clone() else {
            return false;
        };
        let exe = held(&transport).codex_exe.clone();
        let Some(bound) = self.bound.as_ref() else {
            return false;
        };
        let log = bound.log.clone();
        if file_stamp(&exe) != self.backend_stamp {
            log.info(
                "the Codex engine found earlier is gone or was replaced; looking for it again",
            );
        } else {
            let elsewhere = self.served_elsewhere();
            if elsewhere.is_empty() {
                return false;
            }
            let now = crate::clock::monotonic();
            if elsewhere != self.elsewhere_seen {
                self.elsewhere_wait = ELSEWHERE_FIRST_WAIT;
            } else if now < self.elsewhere_due {
                return false;
            } else {
                self.elsewhere_wait = (self.elsewhere_wait * 2.0).min(ELSEWHERE_LONGEST_WAIT);
            }
            self.elsewhere_seen = elsewhere;
            self.elsewhere_due = now + self.elsewhere_wait;
            log.info("the ChatGPT app runs its Codex server from another official Codex engine than the one found earlier; looking for it again");
        }
        *self.backend.borrow_mut() = None;
        self.discovery = Vec::new();
        true
    }
    fn compatibility_tick(&mut self) {
        let result = guarded(|| {
            let bound = self.bound()?;
            if self.compat.is_none() {
                let explicit = bound.codex_exe.clone().or_else(|| {
                    std::env::var(car_config::paths::ENV_CODEX_EXE)
                        .ok()
                        .filter(|found| !found.is_empty())
                });
                let log = bound.log.clone();
                let codex_home = bound.codex_home.clone();
                let system = Arc::clone(
                    self.system
                        .get_or_insert_with(|| Arc::new(car_codex::system::Platform::new())),
                );
                let registry = registry_of(self.bound()?, system);
                self.compat = Some(car_codex::compat::evaluator::Evaluator::new(
                    registry,
                    &codex_home,
                    explicit.as_deref(),
                    None,
                    Box::new(move |line: &str| log.info(line)),
                    Box::new(crate::clock::wall),
                    None,
                ));
            }
            let transport = self.backend.borrow().clone();
            let mut guard = transport.as_ref().map(|found| held(found));
            let compat = self.compat.as_mut().expect("made above");
            let word = compat
                .tick(guard.as_deref_mut(), &self.discovery)
                .map_err(|error| codex_failed(&error))?;
            Ok(word.to_owned())
        });
        match result {
            Ok(word) => *self.state.borrow_mut() = Some(word),
            Err(failed) => {
                *self.state.borrow_mut() = Some("unknown".into());
                if let Some(bound) = self.bound.as_ref() {
                    super::record_failure(
                        &bound.log,
                        &bound.paths.error_log,
                        "compatibility check",
                        &failed,
                    );
                }
            }
        }
        self.layout_look();
    }
    fn engine_state(&self) -> String {
        engine_state(
            self.state.borrow().as_deref(),
            self.backend.borrow().as_ref(),
        )
    }
    fn codex_exe(&mut self) -> Option<String> {
        let transport = self.backend().ok()?;
        let exe = held(&transport).codex_exe.clone();
        Some(exe)
    }
    fn app_identity(&mut self) -> Res<Value> {
        let transport = self.backend()?;
        let found = held(&transport).app_identity();
        found
            .map(|found| found.unwrap_or(Value::Null))
            .map_err(|error| codex_failed(&error))
    }
    fn recovery_facts(&mut self, store: &Store, engine: &mut dyn TickEngine) -> Res<RecoveryFacts> {
        let transport = self.backend()?;
        let system = self.system();
        recovery_facts(store, engine, &transport, system.as_ref())
    }
    fn home_backend(&mut self, path: &str, exe: &str) -> Res<Box<dyn HomeBackend>> {
        let version = Self::version(self.bound()?);
        let system = self.system();
        let transport = Arc::new(Transport::new(Codex::new(
            system, path, exe, true, &version,
        )));
        self.homes.insert(path.to_owned(), Arc::clone(&transport));
        Ok(Box::new(HomeTransport(transport)))
    }
    fn home_engine(
        &mut self,
        store: &Rc<Store>,
        path: &str,
        exe: &str,
        key: &str,
        lock: Rc<RefCell<Box<dyn HeldLock>>>,
        values: &Map,
        managed: &Managed,
    ) -> Res<Box<dyn TickEngine>> {
        let backend = match self.homes.get(path) {
            Some(found) => Arc::clone(found),
            None => {
                self.home_backend(path, exe)?;
                Arc::clone(&self.homes[path])
            }
        };
        let bound = self.bound()?;
        let source = self.source(bound, path)?;
        let given = self.given(
            bound,
            path,
            key,
            Box::new(move || Ok(lock.borrow().held())),
            Arc::new(Guarded::null()),
        )?;
        let mut engine = Engine::new(
            Box::new(EngineStore(Rc::clone(store), None)),
            Box::new(car_engine::seam::Codex(source)),
            Box::new(backend),
            given,
        );
        engine.apply_policy(&Value::Object(values.clone()), Some(managed.clone()));
        Ok(Box::new(Driven(engine)))
    }
}

fn pids(users: &[Value]) -> Vec<i64> {
    let mut found: Vec<i64> = users
        .iter()
        .filter_map(|user| match user {
            Value::Object(map) => map.get("pid").and_then(super::int),
            _ => None,
        })
        .collect();
    found.sort_unstable();
    found.dedup();
    found
}

/// `_recovery_facts(store, engine)`: (app runs, {rule: held}) for one look of the recovery rules.
fn recovery_facts(
    store: &Store,
    engine: &mut dyn TickEngine,
    transport: &Transport,
    system: &dyn System,
) -> Res<RecoveryFacts> {
    use car_engine::impossible::{
        ELSEWHERE_REASONS, LOCKS_UNREAD_REASONS, Look, USAGE_BROKEN_REASONS,
    };
    let states: Vec<String> = car_machine::vocab_gen::domain_states::WAITING
        .iter()
        .map(|each| (*each).to_owned())
        .collect();
    let mut waiting: Vec<(Option<String>, Option<String>)> = store
        .records_in(&states, Some(""))?
        .into_iter()
        .map(|row| {
            let text = |key: &str| row.get(key).and_then(super::text).map(str::to_owned);
            (text("thread_id"), text("last_error"))
        })
        .collect();
    // Review V6: and every record the running edition's plug handed over that waits now (sorted by conversation).
    for (thread, reason) in engine.handed_waits() {
        if let (Some(thread), Value::Str(reason)) = (thread.as_str(), reason)
            && let Some(reason) = reason.as_str()
        {
            waiting.push((Some(thread.to_owned()), Some(reason.to_owned())));
        }
    }
    let reasons: BTreeSet<String> = waiting
        .iter()
        .filter_map(|(_, reason)| reason.clone())
        .collect();
    let any = |group: &[&str]| group.iter().any(|each| reasons.contains(*each));
    let mut facts = BTreeMap::new();
    let usage = any(USAGE_BROKEN_REASONS);
    facts.insert("usage_protocol", Some(usage));
    if !any(ELSEWHERE_REASONS) && !any(LOCKS_UNREAD_REASONS) {
        let runs = if usage {
            car_codex::pairing::app_running_now(system)
        } else {
            None
        };
        return Ok((runs, facts));
    }
    let mut backend = held(transport);
    let identity = backend
        .app_identity()
        .map_err(|error| codex_failed(&error))?;
    let look = backend.app_look;
    let runs = matches!(look, Some("matched" | "unmatched"));
    let home = backend.codex_home.clone();
    drop(backend);
    let os = car_control::host::PlatformOs;
    let mut newest: Vec<(&str, Option<String>)> = Vec::new();
    for kind in ["queue", "state"] {
        let found = car_codex::paths::newest_generation(&os, &home, kind)
            .map_err(|error| codex_failed(&error))?;
        newest.push((kind, found));
    }
    let paths: Vec<String> = newest.iter().filter_map(|(_, path)| path.clone()).collect();
    let database_holders = system.resource_users(&paths).ok().map(|users| pids(&users));
    let locks = car_codex::paths::child(&home, "thread-writer-locks");
    let mut lock_holders: Vec<i64> = Vec::new();
    let elsewhere = waiting.iter().filter(|(_, reason)| {
        reason
            .as_deref()
            .is_some_and(|reason| ELSEWHERE_REASONS.contains(&reason))
    });
    for (thread, _) in elsewhere.take(5) {
        let Some(thread) = thread else { continue };
        let lock = car_codex::paths::child(&locks, &format!("{thread}.lock"));
        if let Ok(users) = system.resource_users(&[lock]) {
            lock_holders.extend(pids(&users));
        }
    }
    lock_holders.sort_unstable();
    lock_holders.dedup();
    let mut older: Vec<Vec<i64>> = Vec::new();
    for (kind, path) in &newest {
        let Some(path) = path else { continue };
        if database_holders.is_none() {
            continue;
        }
        let Ok(users) = system.resource_users(std::slice::from_ref(path)) else {
            continue;
        };
        if !users.is_empty() {
            continue;
        }
        let Some(found) = car_codex::paths::kind(kind) else {
            continue;
        };
        let Ok(entries) = std::fs::read_dir(&home) else {
            continue;
        };
        let mut others = Vec::new();
        let mut failed = false;
        for entry in entries {
            let Ok(entry) = entry else {
                failed = true;
                break;
            };
            let name = entry.file_name().to_string_lossy().into_owned();
            let full = car_codex::paths::child(&home, &name);
            if car_codex::paths::generation(&name, found).is_some()
                && full != *path
                && Path::new(&full).is_file()
                && !car_platform::links::is_symlink(Path::new(&full))
            {
                others.push(full);
            }
        }
        if failed {
            continue;
        }
        if others.is_empty() {
            older.push(Vec::new());
        } else if let Ok(users) = system.resource_users(&others) {
            older.push(pids(&users));
        }
    }
    let server = match &identity {
        Some(Value::Object(map)) => match map.get("server") {
            Some(Value::Object(server)) => server.get("pid").and_then(super::int),
            _ => None,
        },
        _ => None,
    };
    let locks_folder = Path::new(&locks).is_dir();
    facts.extend(car_engine::impossible::recovery_facts(&Look {
        matched: look == Some("matched") && identity.is_some(),
        server,
        reasons: &reasons,
        lock_holders: &lock_holders,
        database_holders: database_holders.as_deref(),
        locks_folder: Some(locks_folder),
        older_holders: &older,
    }));
    Ok((Some(runs), facts))
}
