//! `compat/evaluator.py`: the watcher's side - recompute when something changed, write the report, answer the gate's
//! one word - and the refresh a person asks for.

use std::ffi::OsString;
use std::path::Path;

use car_config::winpath;
use car_machine::compat::model::{Document, RECOMPUTE_SECONDS};
use car_machine::json::{Map, Str, Value, to_string};
use car_machine::pytext::{decimal_value, is_space, strip};
use car_machine::pyval;
use car_machine::vocab_gen::compat_model as words;

use super::cache::{Cache, cache_empty, coerce, judge_cache, read_cache, sources_of};
use super::files::{REFRESH_EXIT, REFRESH_TIMEOUT_SECONDS, load_bundled, stamp, write_json_atomic};
use super::probes::{
    api_checks, candidate_paths, engine_from_backend, engine_from_discovery, server_check,
    source_checks,
};
use super::standing::{FAIL, INCOMPATIBLE, UNKNOWN, accepted_word};
use super::views::{Registry, assemble};
use crate::errors::{Error, Result};
use crate::transport::Backend;

fn get<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// What changes the engine the report is about: the backend (by identity, its file and the app's server) or the
/// record of discovery.
#[derive(Clone, Debug, PartialEq)]
enum EngineKey {
    Backend(u64, Option<(u64, u64)>, &'static str),
    Discovery(Vec<(String, String, [&'static str; 3])>),
}

/// The watcher's side of the registry.
pub struct Evaluator {
    pub registry: Registry,
    pub codex_home: String,
    pub explicit: Option<String>,
    pub product: String,
    log: Box<dyn FnMut(&str) + Send>,
    clock: Box<dyn FnMut() -> f64 + Send>,
    pub recompute: f64,
    pub bundled: Option<Document>,
    pub bundled_state: &'static str,
    pub cache: Cache,
    cache_stamp: Option<Option<(u64, u64)>>,
    engine_key: Option<EngineKey>,
    last_at: Option<f64>,
    pub report: Option<Value>,
    pub acting: Option<&'static str>,
    said: Option<Value>,
    write_failed: bool,
}

impl Evaluator {
    pub fn new(
        registry: Registry,
        codex_home: &str,
        explicit: Option<&str>,
        product: Option<&str>,
        log: Box<dyn FnMut(&str) + Send>,
        mut clock: Box<dyn FnMut() -> f64 + Send>,
        recompute: Option<f64>,
    ) -> Evaluator {
        let product = product
            .filter(|each| !each.is_empty())
            .map(str::to_owned)
            .unwrap_or_else(|| registry.product());
        let _now = clock();
        let (bundled, bundled_state) = load_bundled(&registry.bundled, &product);
        Evaluator {
            codex_home: winpath::path_str(codex_home),
            explicit: explicit.map(str::to_owned),
            product,
            log,
            clock,
            recompute: recompute.unwrap_or(RECOMPUTE_SECONDS as f64),
            bundled,
            bundled_state,
            cache: cache_empty("absent"),
            cache_stamp: None,
            engine_key: None,
            last_at: None,
            report: None,
            acting: None,
            said: None,
            write_failed: false,
            registry,
        }
    }

    /// `acting_for(backend)`: the gate's word for a backend that exists.
    pub fn acting_for(&self, backend: &Backend) -> &'static str {
        let version = backend
            .engine_version
            .as_deref()
            .map_or(Value::Null, Value::from);
        accepted_word(&version, &sources_of(self.bundled.as_ref(), &self.cache))
    }

    fn engine_key_of(&self, backend: Option<&Backend>, discovery: &[(String, Value)]) -> EngineKey {
        if let Some(backend) = backend {
            return EngineKey::Backend(
                backend.object_id(),
                stamp(&backend.codex_exe).ok().flatten(),
                server_check(backend),
            );
        }
        let mut items: Vec<(String, String, [&'static str; 3])> = discovery
            .iter()
            .map(|(path, result)| {
                let signature =
                    to_string(get(result, "signature"), &Default::default()).unwrap_or_default();
                let kind = match get(result, "signature") {
                    Value::Array(_) => "list",
                    _ => "other",
                };
                (
                    path.clone(),
                    format!("{kind}:{signature}"),
                    [
                        coerce(get(result, "official_location")),
                        coerce(get(result, "version_runs")),
                        coerce(get(result, "queue_flags")),
                    ],
                )
            })
            .collect();
        items.sort_by(|a, b| a.0.cmp(&b.0));
        EngineKey::Discovery(items)
    }

    /// `tick(backend, discovery)`: called once per watcher tick, before the engine ticks. The gate's word.
    pub fn tick(
        &mut self,
        mut backend: Option<&mut Backend>,
        discovery: &[(String, Value)],
    ) -> Result<&'static str> {
        let now = (self.clock)();
        let found = stamp(&self.registry.cache_file).map_err(Error::Python)?;
        let mut cache_changed = self.cache_stamp != Some(found);
        if cache_changed {
            self.cache = read_cache(
                &self.registry.cache_file,
                self.bundled.as_ref(),
                &self.product,
                now,
            );
            self.cache_stamp = Some(found);
        } else {
            let judged = judge_cache(&self.cache, self.bundled.as_ref(), &self.product, now);
            if judged.state != self.cache.state {
                self.cache = judged;
                cache_changed = true;
            }
        }
        let engine_key = self.engine_key_of(backend.as_deref(), discovery);
        let due = self.report.is_none()
            || cache_changed
            || Some(&engine_key) != self.engine_key.as_ref()
            || self.last_at.is_none_or(|last| now - last >= self.recompute);
        let acting;
        if due {
            let (engine_checks, engine) = match backend.as_deref_mut() {
                Some(backend) => engine_from_backend(backend),
                None => {
                    let count = candidate_paths(
                        self.registry.system.as_ref(),
                        &self.registry.config,
                        self.explicit.as_deref(),
                    )
                    .len() as i64;
                    engine_from_discovery(self.registry.system.as_ref(), discovery, Some(count))?
                }
            };
            let mut other = source_checks(
                self.registry.system.as_ref(),
                &super::probes::source_home(&self.codex_home),
            );
            for (key, value) in api_checks(self.registry.system.as_ref()) {
                other.insert(key, value);
            }
            let report = assemble(
                &engine_checks,
                &engine,
                &other,
                self.bundled.as_ref(),
                self.bundled_state,
                &self.cache,
                &self.product,
                now,
                None,
            )
            .map_err(Error::Python)?;
            acting = match backend.as_deref() {
                Some(backend) => self.acting_for(backend),
                None => word_of(get(&report, "overall")),
            };
            self.report = Some(with_acting(report, acting));
            self.engine_key = Some(engine_key);
            self.last_at = Some(now);
            self.write();
        } else {
            let report = self.report.clone().unwrap_or(Value::Null);
            acting = match backend.as_deref() {
                Some(backend) => self.acting_for(backend),
                None => word_of(get(&report, "overall")),
            };
            if !pyval::is(get(&report, "acting"), acting) {
                self.report = Some(with_acting(report, acting));
                self.write();
            }
        }
        self.acting = Some(acting);
        self.say();
        Ok(acting)
    }

    /// `_write()`: the report, atomically; a failure is said once in the log.
    fn write(&mut self) {
        let report = self.report.clone().unwrap_or(Value::Null);
        match write_json_atomic(&self.registry.report_file, &report, "compatibility.") {
            Ok(()) => self.write_failed = false,
            Err(_) => {
                if !self.write_failed {
                    (self.log)(
                        "compatibility report could not be written; readers will show unknown",
                    );
                }
                self.write_failed = true;
            }
        }
    }

    /// `_say()`: one log line whenever what is known changes.
    fn say(&mut self) {
        let report = self.report.clone().unwrap_or(Value::Null);
        let mut failing: Vec<String> = Vec::new();
        if let Value::Object(capabilities) = get(&report, "capabilities") {
            for (name, entry) in capabilities {
                let state = pyval::text(get(entry, "state")).unwrap_or_default();
                let reason = pyval::text(get(entry, "reason")).unwrap_or_default();
                if (state == INCOMPATIBLE || state == UNKNOWN) && reason != "not_implemented" {
                    failing.push(format!(
                        "{}={state}/{reason}",
                        name.as_str().unwrap_or_default()
                    ));
                }
            }
        }
        failing.sort();
        let unmatched = pyval::is(get(get(&report, "checks"), "app_server_matched"), FAIL);
        let engine = get(&report, "engine");
        let data = get(&report, "data");
        let said = Value::Array(vec![
            get(&report, "acting").clone(),
            get(&report, "overall").clone(),
            get(engine, "version").clone(),
            get(data, "cache").clone(),
            Value::Array(
                failing
                    .iter()
                    .map(|each| Value::from(each.as_str()))
                    .collect(),
            ),
            Value::Bool(unmatched),
        ]);
        if self
            .said
            .as_ref()
            .is_some_and(|before| pyval::eq(before, &said))
        {
            return;
        }
        self.said = Some(said);
        if unmatched {
            (self.log)(
                "compatibility: the ChatGPT app runs, and no Codex server of its could be matched",
            );
        }
        let version = get(engine, "version");
        let version = if pyval::truthy(version) {
            car_machine::pytext::py_str(version)
        } else {
            "not found".to_owned()
        };
        let line = format!(
            "compatibility: acting {}, found {} (engine {}; data {}, cache {}){}",
            car_machine::pytext::py_str(get(&report, "acting")),
            car_machine::pytext::py_str(get(&report, "overall")),
            version,
            car_machine::pytext::py_str(get(data, "source")),
            car_machine::pytext::py_str(get(data, "cache")),
            if failing.is_empty() {
                String::new()
            } else {
                format!("; not established: {}", failing.join(", "))
            }
        );
        (self.log)(&line);
    }
}

fn word_of(value: &Value) -> &'static str {
    words::ENGINE_STATES
        .iter()
        .copied()
        .find(|each| pyval::is(value, each))
        .unwrap_or("unknown")
}

fn with_acting(report: Value, acting: &str) -> Value {
    match report {
        Value::Object(mut map) => {
            map.insert(Str::from("acting"), Value::from(acting));
            Value::Object(map)
        }
        other => other,
    }
}

// ------------------------------------------------------------------------------------------------ the refresh
/// What the refresh's process gave: its exit code and its output, or why there is none.
pub enum Ran {
    Done {
        code: i64,
        stdout: Option<String>,
    },
    /// `subprocess.TimeoutExpired`.
    Timeout,
    /// `OSError`, `ValueError` or another `SubprocessError`.
    Failed,
}

/// Something that runs the refresh's PowerShell: the system, or a test's stand-in (`runner=`).
pub trait Runner {
    fn run(&self, argv: &[String], env: &[(OsString, OsString)], timeout: f64) -> Ran;
}

/// Windows itself: PowerShell with no window, its output read as UTF-8 with replacement.
pub struct SystemRunner;

impl Runner for SystemRunner {
    /// `subprocess.run(..., timeout=timeout)`: one bound for the output's end and the exit, as `communicate`
    /// gives it (transport's `run_to_end`), so a process PowerShell started that holds the pipe is a timeout.
    fn run(&self, argv: &[String], env: &[(OsString, OsString)], timeout: f64) -> Ran {
        let spawn = car_platform::spawn::Spawn::new(argv.to_vec())
            .with_env(env.to_vec())
            .with_streams(
                car_platform::spawn::Stream::Null,
                car_platform::spawn::Stream::Piped,
                car_platform::spawn::Stream::Null,
            );
        match crate::transport::run_to_end(&spawn, timeout) {
            Ok((code, bytes)) => Ran::Done {
                code,
                stdout: Some(crate::transport::decode(&bytes)),
            },
            Err(crate::transport::RunError::Timeout) => Ran::Timeout,
            Err(crate::transport::RunError::Os) => Ran::Failed,
        }
    }
}

/// `str.splitlines()`'s line ends.
fn line_end(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r'
            | '\u{0b}'
            | '\u{0c}'
            | '\u{1c}'
            | '\u{1d}'
            | '\u{1e}'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}'
    )
}

fn splitlines(text: &str) -> Vec<String> {
    let mut lines = Vec::new();
    let mut current = String::new();
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if line_end(c) {
            if c == '\r' && chars.peek() == Some(&'\n') {
                chars.next();
            }
            lines.push(std::mem::take(&mut current));
        } else {
            current.push(c);
        }
    }
    if !current.is_empty() {
        lines.push(current);
    }
    lines
}

/// `str.isdigit()`: a decimal digit, or one of the 128 other digits Python counts (superscripts, circled ...).
fn is_python_digit(c: char) -> bool {
    const OTHER: [(u32, u32); 20] = [
        (0xB2, 0xB3),
        (0xB9, 0xB9),
        (0x1369, 0x1371),
        (0x19DA, 0x19DA),
        (0x2070, 0x2070),
        (0x2074, 0x2079),
        (0x2080, 0x2089),
        (0x2460, 0x2468),
        (0x2474, 0x247C),
        (0x2488, 0x2490),
        (0x24EA, 0x24EA),
        (0x24F5, 0x24FD),
        (0x24FF, 0x24FF),
        (0x2776, 0x277E),
        (0x2780, 0x2788),
        (0x278A, 0x2792),
        (0x10A40, 0x10A43),
        (0x10E60, 0x10E68),
        (0x11052, 0x1105A),
        (0x1F100, 0x1F10A),
    ];
    decimal_value(c).is_some()
        || OTHER
            .iter()
            .any(|(low, high)| (*low..=*high).contains(&(c as u32)))
}

/// `run_refresh(home, script=, timeout=, runner=)`: the one fetch there is, for the Diagnostics button. `Err` is the
/// ValueError `int()` raises for a sequence of digits that are not decimal (`²`), which the reference lets through.
pub fn run_refresh(
    home: &str,
    script: Option<&str>,
    project_root: &str,
    env: &[(OsString, OsString)],
    timeout: Option<f64>,
    runner: &dyn Runner,
) -> Result<Value> {
    let answer = |word: &str, sequence: Value, reason: Value| {
        let mut map = Map::new();
        map.insert(Str::from("answer"), Value::from(word));
        map.insert(Str::from("sequence"), sequence);
        map.insert(Str::from("reason"), reason);
        Value::Object(map)
    };
    let failed = || answer("failed", Value::Null, Value::Null);
    let script = match script.filter(|each| !each.is_empty()) {
        Some(script) => winpath::path_str(script),
        None => winpath::path_str(&winpath::join(
            &winpath::join(project_root, "scripts"),
            "bootstrap.ps1",
        )),
    };
    let lookup = |name: &str| {
        env.iter()
            .find(|(key, _)| key.to_string_lossy().eq_ignore_ascii_case(name))
            .map(|(_, value)| value.to_string_lossy().into_owned())
    };
    let root = lookup("SystemRoot").unwrap_or_else(|| "C:\\Windows".into());
    let powershell = winpath::path_str(&winpath::join(
        &winpath::join(
            &winpath::join(&winpath::join(&root, "System32"), "WindowsPowerShell"),
            "v1.0",
        ),
        "powershell.exe",
    ));
    if !Path::new(&script).is_file() || !Path::new(&powershell).is_file() {
        return Ok(answer("incomplete", Value::Null, Value::Null));
    }
    let mut environment: Vec<(OsString, OsString)> = Vec::new();
    for (name, value) in env {
        let key = OsString::from(name.to_string_lossy().to_uppercase());
        match environment.iter_mut().find(|(each, _)| *each == key) {
            Some(slot) => slot.1 = value.clone(),
            None => environment.push((key, value.clone())),
        }
    }
    let key = OsString::from("CODEX_AUTO_RESUME_PLUGIN_HOME");
    let home = OsString::from(winpath::path_str(home));
    match environment.iter_mut().find(|(each, _)| *each == key) {
        Some(slot) => slot.1 = home,
        None => environment.push((key, home)),
    }
    let argv: Vec<String> = [
        powershell.as_str(),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script.as_str(),
        "-Compatibility",
    ]
    .iter()
    .map(|each| (*each).to_owned())
    .collect();
    let (code, stdout) = match runner.run(
        &argv,
        &environment,
        timeout.unwrap_or(REFRESH_TIMEOUT_SECONDS),
    ) {
        Ran::Done { code, stdout } => (code, stdout.unwrap_or_default()),
        Ran::Timeout => return Ok(answer("unavailable", Value::Null, Value::Null)),
        Ran::Failed => return Ok(failed()),
    };
    let mut line: Option<Vec<String>> = None;
    for raw in splitlines(&stdout) {
        let stripped = strip(&raw);
        if let Some(rest) = stripped.strip_prefix("compatibility: ") {
            line = Some(
                rest.split(is_space)
                    .filter(|each| !each.is_empty())
                    .map(str::to_owned)
                    .collect(),
            );
        }
    }
    let Some(line) = line.filter(|line| !line.is_empty()) else {
        return Ok(failed());
    };
    let said = line[0].as_str();
    let Some((_, exit)) = REFRESH_EXIT.iter().find(|(word, _)| *word == said) else {
        return Ok(failed());
    };
    if *exit != code {
        return Ok(failed());
    }
    let mut sequence = Value::Null;
    let mut reason = Value::Null;
    if said == "refreshed"
        && let Some(number) = line.get(1)
        && !number.is_empty()
        && number.chars().all(is_python_digit)
    {
        let mut digits = String::new();
        for c in number.chars() {
            let value = decimal_value(c).ok_or(Error::Python("ValueError"))?;
            digits.push(char::from_digit(value, 10).unwrap_or('0'));
        }
        sequence = car_machine::json::Int::parse(digits.trim_start_matches('0'))
            .or_else(|| car_machine::json::Int::parse("0"))
            .map_or(Value::Null, Value::Int);
    }
    if said == "refused"
        && let Some(word) = line.get(1)
        && words::IMPORT_REASONS.contains(&word.as_str())
    {
        reason = Value::from(word.as_str());
    }
    Ok(answer(said, sequence, reason))
}
