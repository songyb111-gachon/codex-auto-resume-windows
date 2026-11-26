//! `compat/probes.py`: the local checks - the source's schema and the App Server's methods - and which engine is in
//! force.

use std::cell::RefCell;
use std::path::Path;
use std::sync::Arc;

use car_config::winpath;
use car_machine::compat::model::{REPORT_MAX_AGE, safe_version};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;

use super::cache::coerce;
use super::files::path_digest;
use super::standing::{FAIL, NOT_APPLICABLE, PASS, UNAVAILABLE};
use crate::appserver::{BROKEN, PROTOCOL_METHODS, last_result};
use crate::errors::{Error, Result};
use crate::pairing;
use crate::sql;
use crate::system::{PolicyOs, System};
use crate::transport::Backend;

fn put(map: &mut Map, key: &str, value: &str) {
    map.insert(Str::from(key), Value::from(value));
}

/// `_columns(connection, table)`: the column names, or none for a table name that is not a plain word.
fn columns(connection: &rusqlite::Connection, table: &str) -> rusqlite::Result<Vec<String>> {
    let plain = table
        .chars()
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && table.chars().all(|c| c.is_ascii_alphanumeric() || c == '_');
    if !plain {
        return Ok(Vec::new());
    }
    sql::columns(connection, table)
}

/// `source_checks(source)`: E6/E7 and the two directories, through a read-only connection; column names only.
pub fn source_checks(system: &dyn System, home: &str) -> Map {
    let mut checks = Map::new();
    for name in [
        "state_schema",
        "history_schema",
        "queue_schema",
        "projection_table",
        "sessions_directory",
        "lock_directory",
    ] {
        put(&mut checks, name, UNAVAILABLE);
    }
    if !Path::new(home).is_dir() {
        return checks;
    }
    // Whether the newest state database holds a conversation: None unknown (not read, or the read failed), Some(false)
    // none, Some(true) some (v0.6.26 final: three-way, as the reference's None / False / True).
    let mut threads: Option<bool> = None;
    let os = PolicyOs;
    for (kind, check) in [
        ("state", "state_schema"),
        ("history", "history_schema"),
        ("queue", "queue_schema"),
    ] {
        let outcome = (|| -> std::result::Result<bool, ()> {
            let Some(path) = crate::paths::newest_generation(&os, home, kind).map_err(|_| ())?
            else {
                if kind == "history" && threads == Some(false) {
                    // v0.6.26 final: Codex makes its history with the first conversation it saves, so a home whose
                    // newest state database was read and holds none has no history yet - "not yet", as a lock folder
                    // is. With a conversation it stays unavailable: there Codex moved, renamed or dropped it.
                    put(&mut checks, "history_schema", NOT_APPLICABLE);
                    put(&mut checks, "projection_table", NOT_APPLICABLE);
                }
                return Ok(false);
            };
            let tables = crate::paths::kind(kind).ok_or(())?.tables;
            let resolved = system.resolve(&path).ok_or(())?;
            let connection = sql::connect(Path::new(&resolved)).map_err(|_| ())?;
            let mut missing = false;
            for (table, required) in tables {
                let found = columns(&connection, table).map_err(|_| ())?;
                if !required
                    .iter()
                    .all(|column| found.iter().any(|each| each == column))
                {
                    missing = true;
                    break;
                }
            }
            put(&mut checks, check, if missing { FAIL } else { PASS });
            if kind == "state" && !missing {
                // A read that fails leaves it unknown (None), the check as it always was.
                threads = sql::query(&connection, "SELECT 1 FROM threads LIMIT 1", &[])
                    .ok()
                    .map(|rows| !rows.is_empty());
            }
            if kind == "history" {
                let found = sql::query(
                    &connection,
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='thread_history_projection_state'",
                    &[],
                )
                .map_err(|_| ())?;
                let projection = !found.is_empty()
                    && columns(&connection, "thread_history_projection_state")
                        .map_err(|_| ())?
                        .iter()
                        .any(|each| each == "next_rollout_byte_offset");
                put(
                    &mut checks,
                    "projection_table",
                    if projection { PASS } else { FAIL },
                );
            }
            Ok(true)
        })();
        if outcome.is_err() {
            put(&mut checks, check, UNAVAILABLE);
            if kind == "history" {
                put(&mut checks, "projection_table", UNAVAILABLE);
            }
        }
    }
    for (name, directory) in [
        ("sessions_directory", "sessions"),
        ("lock_directory", "thread-writer-locks"),
    ] {
        let there = Path::new(&winpath::join(home, directory)).is_dir();
        let word = if there {
            PASS
        } else if name == "lock_directory" && threads == Some(true) {
            FAIL
        } else {
            NOT_APPLICABLE
        };
        put(&mut checks, name, word);
    }
    checks
}

/// `LocalSource(codex_home).home`: the home as the source reader holds it (`rollout._safe_path`), or the text where
/// that cannot be made.
pub fn source_home(codex_home: &str) -> String {
    crate::paths::safe_path(&PolicyOs, codex_home).unwrap_or_else(|_| winpath::path_str(codex_home))
}

/// `protocol_check(method)`: FAIL where the helper last met a broken answer for `method`, PASS otherwise.
pub fn protocol_check(method: &str) -> &'static str {
    if !PROTOCOL_METHODS.contains(&method) {
        return FAIL;
    }
    match last_result(method, None) {
        Some(code) if BROKEN.contains(&code.as_str()) => FAIL,
        _ => PASS,
    }
}

/// `api_checks()`.
pub fn api_checks(system: &dyn System) -> Map {
    let mut checks = Map::new();
    put(
        &mut checks,
        "restart_manager",
        if system.restart_manager_available() {
            PASS
        } else {
            UNAVAILABLE
        },
    );
    put(
        &mut checks,
        "protocol_usage_method",
        protocol_check("account/rateLimits/read"),
    );
    put(
        &mut checks,
        "protocol_delete_method",
        protocol_check("thread/queue/delete"),
    );
    checks
}

/// `_engine_part(raw)`.
pub fn engine_part(raw: &Value) -> Map {
    let mut part = Map::new();
    for name in ["official_location", "version_runs", "queue_flags"] {
        let found = match raw {
            Value::Object(map) => map.get(name).unwrap_or(&Value::Null),
            _ => &Value::Null,
        };
        put(&mut part, name, coerce(found));
    }
    part
}

/// `server_check(backend)`: the app_server_matched check, read off the last look the backend already took.
pub fn server_check(backend: &Backend) -> &'static str {
    let (Some(look), Some(at)) = (backend.app_look, backend.app_looked_at) else {
        return UNAVAILABLE;
    };
    if !["matched", "unmatched"].contains(&look) {
        return UNAVAILABLE;
    }
    if backend.system.monotonic() - at > REPORT_MAX_AGE as f64 {
        return UNAVAILABLE;
    }
    if look == "matched" { PASS } else { FAIL }
}

fn engine(found: bool, version: Value, signature: Value, digest: Value, candidates: i64) -> Value {
    let mut out = Map::new();
    out.insert(Str::from("found"), Value::Bool(found));
    out.insert(Str::from("version"), version);
    out.insert(Str::from("signature"), signature);
    out.insert(Str::from("path_digest"), digest);
    out.insert(Str::from("candidates"), Value::from(candidates));
    Value::Object(out)
}

fn safe(version: &Value) -> Value {
    safe_version(version).map_or(Value::Null, Value::from)
}

/// `engine_from_backend(backend)`: (checks, engine) for the backend the watcher is driving.
pub fn engine_from_backend(backend: &mut Backend) -> (Map, Value) {
    let raw = Value::Object(backend.engine_checks());
    let mut checks = engine_part(&raw);
    put(&mut checks, "single_candidate", PASS);
    put(&mut checks, "app_server_matched", server_check(backend));
    let signature = match &raw {
        Value::Object(map) => map.get("signature").cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let fine = matches!(&signature, Value::Array(parts) if parts.len() == 2
        && parts.iter().all(|part| matches!(part, Value::Int(_))
            && pyval::less_or_equal(&Value::from(0), part).unwrap_or(false)));
    let signature = if fine { signature } else { Value::Null };
    let digest = path_digest(backend.system.as_ref(), &backend.codex_exe);
    let version = match &raw {
        Value::Object(map) => map.get("version").cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let engine = engine(
        digest.is_some(),
        safe(&version),
        signature,
        digest.map_or(Value::Null, |each| Value::from(each.as_str())),
        1,
    );
    (checks, engine)
}

/// `engine_from_discovery(discovery, candidates=)`: (checks, engine) when discovery refused every candidate.
/// `discovery` is the record of every candidate's checks, in the order they were made.
pub fn engine_from_discovery(
    system: &dyn System,
    discovery: &[(String, Value)],
    candidates: Option<i64>,
) -> Result<(Map, Value)> {
    let count = candidates.unwrap_or(discovery.len() as i64);
    if discovery.is_empty() {
        let mut checks = Map::new();
        for name in [
            "official_location",
            "version_runs",
            "queue_flags",
            "single_candidate",
        ] {
            put(&mut checks, name, UNAVAILABLE);
        }
        return Ok((
            checks,
            engine(false, Value::Null, Value::Null, Value::Null, count),
        ));
    }
    let raw_of = |result: &Value| match result {
        Value::Object(_) => result.clone(),
        _ => Value::Object(Map::new()),
    };
    let field = |value: &Value, key: &str| match value {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    if discovery.len() == 1 {
        let (path, result) = &discovery[0];
        let mut checks = engine_part(result);
        put(&mut checks, "single_candidate", PASS);
        let raw = raw_of(result);
        let signature = match field(&raw, "signature") {
            Value::Array(parts) => Value::Array(parts),
            _ => Value::Null,
        };
        let digest = path_digest(system, path);
        return Ok((
            checks,
            engine(
                true,
                safe(&field(&raw, "version")),
                signature,
                digest.map_or(Value::Null, |each| Value::from(each.as_str())),
                count,
            ),
        ));
    }
    let probed: Vec<Map> = discovery
        .iter()
        .map(|(_, result)| engine_part(result))
        .collect();
    let mut checks = Map::new();
    for name in ["official_location", "version_runs", "queue_flags"] {
        let all = |word: &str| probed.iter().all(|entry| pyval::is(&entry[name], word));
        put(
            &mut checks,
            name,
            if all(PASS) {
                PASS
            } else if all(FAIL) {
                FAIL
            } else {
                UNAVAILABLE
            },
        );
    }
    put(&mut checks, "single_candidate", UNAVAILABLE);
    let mut versions: Vec<Value> = Vec::new();
    for (_, result) in discovery {
        let version = field(&raw_of(result), "version");
        pyval::hashable(&version).map_err(Error::Python)?;
        if !versions.iter().any(|each| pyval::eq(each, &version)) {
            versions.push(version);
        }
    }
    let version = if versions.len() == 1 {
        versions.remove(0)
    } else {
        Value::Null
    };
    Ok((
        checks,
        engine(false, safe(&version), Value::Null, Value::Null, count),
    ))
}

/// `_candidate_paths(explicit)`: the named engine, resolved, and every build in the official folder.
pub fn candidate_paths(
    system: &dyn System,
    config: &car_config::Os,
    explicit: Option<&str>,
) -> Vec<String> {
    let mut found = Vec::new();
    let env = |name: &str| system.env(name);
    if let Some(explicit) = explicit.filter(|each| !each.is_empty())
        && let Ok(expanded) = winpath::expanduser(explicit, &env)
        && let Some(resolved) = system.resolve(&winpath::path_str(&expanded))
    {
        found.push(resolved);
    }
    if let Ok(more) = car_config::codex::candidate_codex_exes(&env, config) {
        found.extend(more);
    }
    found
}

/// `_served_engines()`: the official engines the ChatGPT app main runs as its children; none where the process list
/// cannot be read.
pub fn served_engines(system: &dyn System) -> Vec<String> {
    let Ok(served) = pairing::app_engines(system) else {
        return Vec::new();
    };
    served
        .into_iter()
        .filter(|path| pairing::official_engine(system, path).0)
        .collect()
}

/// `_package_engines()` (v0.6.26 final, live acceptance R2b): the engines in the folders of the Codex app's package
/// installed for this account, whether or not the app runs; nothing where the package manager cannot answer (any
/// exception of `package_engines`). A generator in the reference, as `_served_engines` is: `official_engine` is asked
/// of each only as the caller comes to it ([`official`] over this list).
pub fn package_engines(system: &dyn System) -> Vec<String> {
    pairing::package_engines(system).unwrap_or_default()
}

/// The official ones of `found`, each asked only when the caller comes to it (the generators' filter).
pub fn official<'a>(
    system: &'a dyn System,
    found: Vec<String>,
) -> impl Iterator<Item = String> + 'a {
    found
        .into_iter()
        .filter(move |path| pairing::official_engine(system, path).0)
}

/// The record of discovery: every candidate's path and its checks, in the order they were made.
pub type Discovery = Vec<(String, Value)>;

/// `discover(codex_home, explicit)`: discovery as the watcher does it, recording every candidate's checks.
/// (backend or None, the record).
pub fn discover(
    system: &Arc<dyn System>,
    config: &car_config::Os,
    codex_home: &str,
    explicit: Option<&str>,
    product_version: &str,
) -> Result<(Option<Backend>, Discovery)> {
    let record: RefCell<Vec<(String, Value)>> = RefCell::new(Vec::new());
    let compatible = |path: &str| -> std::result::Result<(), String> {
        let mut probe = Backend::new(Arc::clone(system), codex_home, path, false, product_version);
        let answer = probe.compatible();
        let checks = probe.last_checks().map_or(Value::Null, Value::Object);
        let mut held = record.borrow_mut();
        match held.iter_mut().find(|(each, _)| each == path) {
            Some(slot) => slot.1 = checks,
            None => held.push((path.to_owned(), checks)),
        }
        answer.map_err(|error| error.message())
    };
    let running = || pairing::app_engines(system.as_ref()).ok();
    let env = |name: &str| system.env(name);
    let chosen = car_config::codex::discover_codex_exe(
        explicit,
        &compatible,
        Some(&running),
        false,
        false,
        &env,
        config,
    );
    let record = record.into_inner();
    let Ok(chosen) = chosen else {
        return Ok((None, record));
    };
    let mut backend = Backend::new(
        Arc::clone(system),
        codex_home,
        &chosen,
        false,
        product_version,
    );
    backend.compatible()?;
    Ok((Some(backend), record))
}
