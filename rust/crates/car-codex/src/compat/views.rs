//! `compat/views.py`: a live report on request, and the view a reader - the window, the panel - may see.

use std::path::Path;
use std::sync::Arc;

use car_machine::compat::model::{Document, MAX_REPORT_BYTES, REPORT_MAX_AGE, decode};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::compat_model as words;

use super::cache::{Cache, read_cache, sources_of};
use super::files::{load_bundled, path_digest, product_version, read_capped, signature};
use super::probes::{
    self, api_checks, candidate_paths, discover, engine_from_backend, engine_from_discovery,
    served_engines, source_checks,
};
use super::report::{build_report, unusable_view, validate_report, view_of};
use super::reported;
use super::standing::{UNAVAILABLE, evaluate};
use crate::errors::{Error, Result};
use crate::system::System;
use crate::transport::Backend;

pub const SERVER_CHECK: &str = "app_server_matched";

/// Where the registry's files are, and what this installation is.
pub struct Registry {
    pub system: Arc<dyn System>,
    /// car-config's `Os` (Path.resolve, the link probe) for the candidate search.
    pub config: car_config::Os,
    /// `data/codex_compat.json` beside the package.
    pub bundled: String,
    /// `data/reported.json` beside the package.
    pub reported: String,
    /// `<home>/config/compat-cache.json`.
    pub cache_file: String,
    /// `<home>/config/compatibility.json`.
    pub report_file: String,
    /// `config.version()`.
    pub version: String,
}

impl Registry {
    /// `product_version()`.
    pub fn product(&self) -> String {
        product_version(&self.version)
    }
}

fn get<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// `assemble(...)`: the report of these checks and this data, built and validated.
#[allow(clippy::too_many_arguments)]
pub fn assemble(
    engine_checks: &Map,
    engine: &Value,
    other_checks: &Map,
    bundled: Option<&Document>,
    bundled_state: &str,
    cache: &Cache,
    product: &str,
    now: f64,
    acting: Option<&str>,
) -> Py<Value> {
    let mut checks = other_checks.clone();
    for (key, value) in engine_checks {
        checks.insert(key.clone(), value.clone());
    }
    let capabilities = evaluate(&checks, get(engine, "version"), &sources_of(bundled, cache));
    let in_force = words::RESTRICTING_STATES.contains(&cache.state);
    let mut data = Map::new();
    let mut put = |key: &str, value: Value| {
        data.insert(Str::from(key), value);
    };
    put("bundled", Value::from(bundled_state));
    put(
        "bundled_sequence",
        bundled.map_or(Value::Null, |document| Value::from(document.sequence)),
    );
    put("cache", Value::from(cache.state));
    put(
        "cache_sequence",
        cache.sequence.map_or(Value::Null, Value::from),
    );
    put(
        "cache_origin",
        cache.origin.as_deref().map_or(Value::Null, Value::from),
    );
    put(
        "fetched_at",
        cache.fetched_at.map_or(Value::Null, Value::Float),
    );
    put(
        "source",
        Value::from(if in_force {
            "cache"
        } else if bundled.is_some() {
            "bundled"
        } else {
            "none"
        }),
    );
    put("expired", Value::Bool(cache.state == "expired"));
    let mut kept = Map::new();
    for key in ["found", "version", "signature", "path_digest", "candidates"] {
        kept.insert(Str::from(key), get(engine, key).clone());
    }
    build_report(
        now,
        product,
        Value::Object(kept),
        Value::Object(data),
        &checks,
        Value::Object(capabilities),
        acting,
    )
}

/// `read_report(paths, now=)`: (report or None, status), validated on read.
pub fn read_report(report_file: &str, now: f64) -> Py<(Option<Value>, &'static str)> {
    if !Path::new(report_file).exists() {
        return Ok((None, "absent"));
    }
    let Ok(value) =
        read_capped(report_file, MAX_REPORT_BYTES).and_then(|raw| decode(&raw, MAX_REPORT_BYTES))
    else {
        return Ok((None, "invalid"));
    };
    Ok(match validate_report(&value, Some(now))? {
        Some(report) => (Some(report), "ok"),
        None => (None, "invalid"),
    })
}

fn age(report: &Value, now: f64) -> f64 {
    now - pyval::Num::of(get(report, "checked_at"))
        .map(pyval::Num::as_f64)
        .unwrap_or(f64::NAN)
}

/// `_watchers_server_check(paths, now)`: what the watcher's own report last found of the app's server.
pub fn watchers_server_check(report_file: &str, now: f64) -> Py<Value> {
    let (report, _) = read_report(report_file, now)?;
    match report {
        Some(report) if age(&report, now) <= REPORT_MAX_AGE as f64 => {
            Ok(get(get(&report, "checks"), SERVER_CHECK).clone())
        }
        _ => Ok(Value::from(UNAVAILABLE)),
    }
}

/// `_binding_holds(report, explicit)`: whether the report still describes the engine on disk.
pub fn binding_holds(registry: &Registry, report: &Value, explicit: Option<&str>) -> bool {
    let system = registry.system.as_ref();
    let engine = get(report, "engine");
    if pyval::truthy(get(engine, "found")) {
        let digest = get(engine, "path_digest");
        if !pyval::truthy(digest) || matches!(get(engine, "signature"), Value::Null) {
            return false;
        }
        let wanted = pyval::text(digest).unwrap_or_default();
        let matches = |candidate: &str| path_digest(system, candidate).as_deref() == Some(wanted);
        for candidate in candidate_paths(system, &registry.config, explicit) {
            if matches(&candidate) {
                return pyval::eq(
                    &signature(&candidate).unwrap_or(Value::Null),
                    get(engine, "signature"),
                );
            }
        }
        // v0.6.26 final (live acceptance R2b): before the app, the engines of its package on disk, so the report on the
        // app's engine stays bound while that very file is there, whether or not the app runs now.
        for candidate in probes::official(system, probes::package_engines(system)) {
            if matches(&candidate) {
                return pyval::eq(
                    &signature(&candidate).unwrap_or(Value::Null),
                    get(engine, "signature"),
                );
            }
        }
        for candidate in served_engines(system) {
            if matches(&candidate) {
                return pyval::eq(
                    &signature(&candidate).unwrap_or(Value::Null),
                    get(engine, "signature"),
                );
            }
        }
        return false;
    }
    let count = candidate_paths(system, &registry.config, explicit).len() as i64;
    let held = match get(engine, "candidates") {
        Value::Int(number) => number.as_i64().unwrap_or(-1),
        _ => 0,
    };
    count == held
}

/// `reported_for(view)`: what other people's filed reports add up to for the version a view names.
pub fn reported_for(registry: &Registry, view: &Value) -> Py<Value> {
    let engine = match get(view, "engine") {
        found @ Value::Object(_) => found.clone(),
        _ => Value::Object(Map::new()),
    };
    if !pyval::is(get(view, "status"), "ok") || !pyval::truthy(get(&engine, "found")) {
        reported::lookup(&Value::Null, &registry.reported)
    } else {
        reported::lookup(get(&engine, "version"), &registry.reported)
    }
}

fn with(view: Value, live: bool, reported: Value) -> Value {
    let Value::Object(mut map) = view else {
        return view;
    };
    map.insert(Str::from("live"), Value::Bool(live));
    map.insert(Str::from("reported"), reported);
    Value::Object(map)
}

/// `read_view(paths, now=, explicit=)`: the report as every front end shows it, or UNKNOWN with the reason.
pub fn read_view(registry: &Registry, now: f64, explicit: Option<&str>) -> Py<Value> {
    let (report, status) = read_report(&registry.report_file, now)?;
    let view = match report {
        None => unusable_view(status, Value::Null, Value::Null, None),
        Some(report) => {
            let data = get(&report, "data").clone();
            let checked = get(&report, "checked_at").clone();
            let engine = get(&report, "engine").clone();
            if age(&report, now) > REPORT_MAX_AGE as f64 {
                unusable_view("stale", data, checked, Some(&engine))
            } else if !binding_holds(registry, &report, explicit) {
                unusable_view("engine_changed", data, checked, Some(&engine))
            } else {
                view_of(&report)
            }
        }
    };
    let reported = reported_for(registry, &view)?;
    Ok(with(view, false, reported))
}

/// `reader_view(paths, now=, settings=)`: `read_view` with the engine the settings, the environment or discovery
/// name.
pub fn reader_view(registry: &Registry, now: f64, settings: &Value) -> Py<Value> {
    let named = match settings {
        Value::Object(map) => map.get("codex_exe").cloned().unwrap_or(Value::Null),
        Value::Null => Value::Null,
        _ if !pyval::truthy(settings) => Value::Null,
        _ => return read_view(registry, now, None),
    };
    let explicit = if pyval::truthy(&named) {
        pyval::text(&named).map(str::to_owned)
    } else {
        registry
            .system
            .env(car_config::paths::ENV_CODEX_EXE)
            .filter(|each| !each.is_empty())
    };
    read_view(registry, now, explicit.as_deref())
}

/// `live_report(paths, codex_home, backend=, discovery=, explicit=, source=, now=)`: a fresh evaluation for a reader
/// with no watcher to ask. Never written anywhere.
pub fn live_report(
    registry: &Registry,
    codex_home: &str,
    backend: Option<&mut Backend>,
    discovery: Option<Vec<(String, Value)>>,
    explicit: Option<&str>,
    now: f64,
) -> Result<Value> {
    let product = registry.product();
    let mut discovery = discovery;
    let mut found = if backend.is_none() && discovery.is_none() {
        let (chosen, record) = discover(
            &registry.system,
            &registry.config,
            codex_home,
            explicit,
            &registry.version,
        )?;
        discovery = Some(record);
        chosen
    } else {
        None
    };
    let backend = match backend {
        Some(backend) => Some(backend),
        None => found.as_mut(),
    };
    let (mut engine_checks, engine) = match backend {
        Some(backend) => engine_from_backend(backend),
        None => {
            let count =
                candidate_paths(registry.system.as_ref(), &registry.config, explicit).len() as i64;
            engine_from_discovery(
                registry.system.as_ref(),
                discovery.as_deref().unwrap_or(&[]),
                Some(count),
            )?
        }
    };
    let matched = engine_checks
        .get(SERVER_CHECK)
        .cloned()
        .unwrap_or_else(|| Value::from(UNAVAILABLE));
    if pyval::is(&matched, UNAVAILABLE) {
        let watcher = watchers_server_check(&registry.report_file, now).map_err(Error::Python)?;
        engine_checks.insert(Str::from(SERVER_CHECK), watcher);
    }
    let (bundled, bundled_state) = load_bundled(&registry.bundled, &product);
    let cache = read_cache(&registry.cache_file, bundled.as_ref(), &product, now);
    let mut other = source_checks(
        registry.system.as_ref(),
        &super::probes::source_home(codex_home),
    );
    for (key, value) in api_checks(registry.system.as_ref()) {
        other.insert(key, value);
    }
    assemble(
        &engine_checks,
        &engine,
        &other,
        bundled.as_ref(),
        bundled_state,
        &cache,
        &product,
        now,
        None,
    )
    .map_err(Error::Python)
}

/// `live_view(...)`.
pub fn live_view(
    registry: &Registry,
    codex_home: &str,
    backend: Option<&mut Backend>,
    discovery: Option<Vec<(String, Value)>>,
    explicit: Option<&str>,
    now: f64,
) -> Result<Value> {
    let view = view_of(&live_report(
        registry, codex_home, backend, discovery, explicit, now,
    )?);
    let reported = reported_for(registry, &view).map_err(Error::Python)?;
    Ok(with(view, true, reported))
}
