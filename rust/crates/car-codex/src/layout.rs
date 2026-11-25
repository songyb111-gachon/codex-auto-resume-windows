//! `codex/layout.py`: the Codex app's process layout, counted by role, and the watcher's look when it changes.
//!
//! `snapshot` counts one look's processes by role and names the catalogued shape it is; `Watch` says the layout in
//! the log when the engine's file or the app's package version changes and keeps it, with the last look that paired,
//! in `config/codex-layout.json`. It decides nothing: no send, no wait and no reason comes of it.

use std::sync::Arc;

use car_machine::compat::loads;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;

use crate::pairing;
use crate::refold::{self, points};
use crate::system::System;

pub const FORMAT: i64 = 1;
/// The process shapes this version is tested on, by (mains, engines under the main, engines under a helper).
pub const SHAPES: [((i64, i64, i64), &str); 6] = [
    ((1, 1, 0), "single_child"),
    ((1, 2, 0), "two_children"),
    ((1, 0, 1), "helper_parented"),
    ((1, 1, 1), "helper_parented"),
    ((1, 0, 0), "starting"),
    ((0, 0, 0), "closed"),
];
pub const STARTING_SECONDS: f64 = 600.0;
pub const LOOK_GAP_SECONDS: f64 = 300.0;
pub const TICKS_KEPT: usize = 8;
/// The most a kept layout file may hold.
pub const READ_MOST: usize = 16384;
const COUNTS: [&str; 5] = [
    "mains",
    "helpers",
    "engines_under_main",
    "engines_under_helper",
    "engines_elsewhere",
];
const FLAGS: [&str; 3] = ["renamed_main", "engine_in_package", "paired"];

fn shape_of(key: (i64, i64, i64)) -> Option<&'static str> {
    SHAPES
        .iter()
        .find(|(each, _)| *each == key)
        .map(|(_, name)| *name)
}

fn is_shape(word: &str) -> bool {
    SHAPES.iter().any(|(_, name)| *name == word)
}

fn get<'a>(map: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match map {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// `_VERSION.search(path)`: `OpenAI\.Codex_([0-9][0-9.]{0,31})_`, any case, the digits with trailing dots dropped.
fn app_version(path: &str) -> Option<String> {
    let text = points(path);
    let digit = |c: u32| (0x30..=0x39).contains(&c);
    for start in 0..text.len() {
        let Some(at) = refold::literal(&text, start, "OpenAI.Codex_") else {
            continue;
        };
        if !text.get(at).is_some_and(|c| digit(*c)) {
            continue;
        }
        let run = text[at..]
            .iter()
            .take_while(|c| digit(**c) || **c == u32::from(b'.'))
            .count();
        if run > 32 || text.get(at + run) != Some(&u32::from(b'_')) {
            continue;
        }
        let found: String = text[at..at + run]
            .iter()
            .filter_map(|c| char::from_u32(*c))
            .collect();
        return Some(found.trim_end_matches('.').to_owned());
    }
    None
}

/// `snapshot(rows, codex_exe, seen)`: one look's processes counted by role, content-free. Never raises.
pub fn snapshot(
    system: &dyn System,
    rows: Option<&[Value]>,
    codex_exe: Option<&str>,
    seen: Option<&Map>,
) -> Value {
    let mut found = Map::new();
    let set = |found: &mut Map, key: &str, value: Value| {
        found.insert(Str::from(key), value);
    };
    set(&mut found, "mains", Value::from(0));
    set(&mut found, "helpers", Value::from(0));
    set(&mut found, "renamed_main", Value::Bool(false));
    set(&mut found, "app_version", Value::Null);
    set(&mut found, "engines_under_main", Value::from(0));
    set(&mut found, "engines_under_helper", Value::from(0));
    set(&mut found, "engines_elsewhere", Value::from(0));
    set(&mut found, "engine_in_package", Value::Bool(false));
    set(
        &mut found,
        "paired",
        Value::Bool(seen.is_some_and(|seen| seen.contains_key("server_holds"))),
    );
    set(
        &mut found,
        "server_holds",
        seen.and_then(|seen| seen.get("server_holds").cloned())
            .unwrap_or(Value::Null),
    );
    set(&mut found, "shape", Value::Null);
    let (mut mains, mut under_main, mut under_helper) = (0i64, 0i64, 0i64);
    let _ = (|| -> crate::errors::Result<()> {
        let rows: Vec<Value> = rows
            .unwrap_or(&[])
            .iter()
            .filter(|row| matches!(row, Value::Object(_)))
            .cloned()
            .collect();
        let listed = pairing::app_mains(system, &rows)?;
        mains = listed.len() as i64;
        found.insert(Str::from("mains"), Value::from(mains));
        let main = (listed.len() == 1).then(|| listed[0]);
        let path_of = |row: &Value| match get(row, "path") {
            Value::Str(text) => text.as_str().map(str::to_owned),
            _ => None,
        };
        let mut helpers = 0i64;
        for row in &rows {
            if !pairing::app_process(system, row)
                || listed.iter().any(|each| std::ptr::eq(*each, row))
            {
                continue;
            }
            let place = pairing::main_place(system, &path_of(row).unwrap_or_default());
            let under = match main {
                Some(main) if !place => {
                    pairing::under_app(system, &rows, row, pyval_index(main, "pid")?)?
                }
                _ => false,
            };
            if place || under {
                helpers += 1;
            }
        }
        found.insert(Str::from("helpers"), Value::from(helpers));
        if let Some(main) = main {
            let path = match pyval_index(main, "path")? {
                Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
                _ => return Err(crate::errors::Error::Python("TypeError")),
            };
            found.insert(
                Str::from("renamed_main"),
                Value::Bool(!pairing::package_app(system, &path)),
            );
            found.insert(
                Str::from("app_version"),
                app_version(&path).map_or(Value::Null, |each| Value::from(each.as_str())),
            );
        }
        let mut elsewhere = 0i64;
        for row in &rows {
            if !pairing::engine_row(system, row) {
                continue;
            }
            let pid = match main {
                Some(main) => Some(pyval_index(main, "pid")?),
                None => None,
            };
            let child = match pid {
                Some(pid) if pyval::eq(get(row, "parent"), pid) => {
                    pairing::under_app(system, &rows, row, pid)?
                }
                _ => false,
            };
            if child {
                under_main += 1;
                found.insert(Str::from("engines_under_main"), Value::from(under_main));
            } else if match pid {
                Some(pid) => pairing::under_app(system, &rows, row, pid)?,
                None => false,
            } {
                under_helper += 1;
                found.insert(Str::from("engines_under_helper"), Value::from(under_helper));
            } else {
                elsewhere += 1;
                found.insert(Str::from("engines_elsewhere"), Value::from(elsewhere));
            }
        }
        found.insert(
            Str::from("engine_in_package"),
            Value::Bool(codex_exe.is_some_and(|exe| pairing::package_file(system, exe))),
        );
        Ok(())
    })();
    let shape = shape_of((mains.min(2), under_main, under_helper));
    found.insert(Str::from("shape"), shape.map_or(Value::Null, Value::from));
    Value::Object(found)
}

fn pyval_index<'a>(row: &'a Value, key: &str) -> crate::errors::Result<&'a Value> {
    match row {
        Value::Object(map) => map.get(key).ok_or(crate::errors::Error::Python("KeyError")),
        _ => Err(crate::errors::Error::Python("TypeError")),
    }
}

/// `catalogued(found)`: whether a snapshot is one of the shapes this version is tested on.
pub fn catalogued(found: &Value) -> bool {
    matches!(found, Value::Object(_))
        && matches!(get(found, "shape"), Value::Str(text) if text.as_str().is_some_and(is_shape))
}

/// `_word(value)`: printable ASCII of 1 to 64 characters, or None.
pub fn word(value: &Value) -> Value {
    match value {
        Value::Str(text)
            if (1..=64).contains(&text.len())
                && text.as_bytes().iter().all(|b| (0x20..=0x7e).contains(b)) =>
        {
            value.clone()
        }
        _ => Value::Null,
    }
}

fn flag(value: &Value) -> Value {
    match value {
        Value::Bool(_) => value.clone(),
        _ => Value::Null,
    }
}

/// `_layout(value)`: a kept snapshot's closed shape.
fn kept_layout(value: &Value) -> Value {
    let mut kept = Map::new();
    for name in COUNTS {
        let each = get(value, name);
        let fine = matches!(each, Value::Int(_))
            && pyval::less_or_equal(&Value::from(0), each).unwrap_or(false)
            && pyval::less(each, &Value::from(1_000_000)).unwrap_or(false);
        kept.insert(
            Str::from(name),
            if fine { each.clone() } else { Value::from(0) },
        );
    }
    for name in FLAGS {
        kept.insert(Str::from(name), flag(get(value, name)));
    }
    kept.insert(Str::from("app_version"), word(get(value, "app_version")));
    let shape = match get(value, "shape") {
        Value::Str(text) if text.as_str().is_some_and(is_shape) => get(value, "shape").clone(),
        _ => Value::Null,
    };
    kept.insert(Str::from("shape"), shape);
    Value::Object(kept)
}

/// `read(path)`: what the watcher last kept of the layout, or None.
pub fn read(path: &str) -> Option<Value> {
    use std::io::Read;
    let mut data = Vec::new();
    std::fs::File::open(path)
        .ok()?
        .take(READ_MOST as u64 + 1)
        .read_to_end(&mut data)
        .ok()?;
    if data.len() > READ_MOST {
        return None;
    }
    let found = loads(std::str::from_utf8(&data).ok()?).ok()?;
    if !matches!(get(&found, "format"), Value::Int(n) if n.as_i64() == Some(FORMAT)) {
        return None;
    }
    let last = get(&found, "last_good");
    let mut out = Map::new();
    let mut put = |key: &str, value: Value| {
        out.insert(Str::from(key), value);
    };
    put("format", Value::from(FORMAT));
    put("code_version", word(get(&found, "code_version")));
    put("engine_version", word(get(&found, "engine_version")));
    put("app_version", word(get(&found, "app_version")));
    put("layout", kept_layout(get(&found, "layout")));
    put("catalogued", flag(get(&found, "catalogued")));
    put(
        "last_good",
        if matches!(last, Value::Object(_)) {
            let mut good = Map::new();
            good.insert(Str::from("code_version"), word(get(last, "code_version")));
            good.insert(
                Str::from("engine_version"),
                word(get(last, "engine_version")),
            );
            good.insert(Str::from("app_version"), word(get(last, "app_version")));
            good.insert(Str::from("layout"), kept_layout(get(last, "layout")));
            Value::Object(good)
        } else {
            Value::Null
        },
    );
    put("updated_from", word(get(&found, "updated_from")));
    put(
        "unpaired_after_update",
        flag(get(&found, "unpaired_after_update")),
    );
    Some(Value::Object(out))
}

/// `_write(path, value)`: the file beside a temporary one of this process, replaced whole; a failure is not raised.
fn write(path: &str, value: &Value, pid: u32) {
    let target = std::path::Path::new(path);
    let _ = (|| -> Option<()> {
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent).ok()?;
        }
        let stem = target.file_stem()?.to_string_lossy().into_owned();
        let temporary = target.with_file_name(format!("{stem}.{pid}.tmp"));
        let text = to_string(value, &Options::new().sort_keys(true)).ok()?;
        std::fs::write(&temporary, text.as_bytes()).ok()?;
        std::fs::rename(&temporary, target).ok()
    })();
}

/// `%d` of a count.
fn count(value: &Value) -> String {
    match value {
        Value::Bool(on) => i64::from(*on).to_string(),
        Value::Int(n) => n.to_string(),
        Value::Float(x) => format!("{}", x.trunc() as i64),
        _ => "0".into(),
    }
}

fn get_or_zero<'a>(found: &'a Value, key: &str) -> &'a Value {
    static ZERO: std::sync::LazyLock<Value> = std::sync::LazyLock::new(|| Value::from(0));
    match found {
        Value::Object(map) => map.get(key).unwrap_or(&ZERO),
        _ => &ZERO,
    }
}

/// The layout as kept: the snapshot without `server_holds`.
fn without_holds(found: &Value) -> Value {
    match found {
        Value::Object(map) => Value::Object(
            map.iter()
                .filter(|(key, _)| key.as_str() != Some("server_holds"))
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect(),
        ),
        _ => Value::Object(Map::new()),
    }
}

/// The watcher's look at the layout.
pub struct Watch {
    path: String,
    code_version: Value,
    log: Box<dyn FnMut(&str) + Send>,
    clock: Box<dyn FnMut() -> f64 + Send>,
    pid: u32,
    starting_since: Option<f64>,
    untested: Option<bool>,
    found: Option<Arc<Value>>,
    found_at: Option<f64>,
    called: Option<f64>,
    ticks: Vec<f64>,
    kept: Value,
    key: Option<(Value, Value)>,
    pub updated_from: Value,
}

impl Watch {
    pub fn new(
        path: &str,
        code_version: &Value,
        log: Box<dyn FnMut(&str) + Send>,
        clock: Box<dyn FnMut() -> f64 + Send>,
        pid: u32,
    ) -> Watch {
        let code_version = word(code_version);
        let before = read(path).unwrap_or_else(|| Value::Object(Map::new()));
        let previous = word(get(&before, "code_version"));
        let updated_from = if pyval::truthy(&previous) && !pyval::eq(&previous, &code_version) {
            previous
        } else {
            word(get(&before, "updated_from"))
        };
        Watch {
            path: path.to_owned(),
            code_version,
            log,
            clock,
            pid,
            starting_since: None,
            untested: None,
            found: None,
            found_at: None,
            called: None,
            ticks: Vec::new(),
            kept: before,
            key: None,
            updated_from,
        }
    }

    /// `look(found, stamp=, engine_version=)`: take one look's snapshot; what is kept now, or None.
    pub fn look(
        &mut self,
        found: Option<&Arc<Value>>,
        stamp: &Value,
        engine_version: &Value,
    ) -> crate::errors::Result<Option<Value>> {
        let Some(found_arc) = found.filter(|each| matches!(each.as_ref(), Value::Object(_))) else {
            return Ok(None);
        };
        let found: &Value = found_arc;
        let zero = Value::from(0);
        let open = |key: &str| pyval::greater(get_or_zero(found, key), &zero);
        let app_open = open("mains").map_err(crate::errors::Error::Python)?
            || open("helpers").map_err(crate::errors::Error::Python)?;
        let now = (self.clock)();
        let fresh = !self
            .found
            .as_ref()
            .is_some_and(|each| Arc::ptr_eq(each, found_arc));
        let allowed = if self.ticks.is_empty() {
            2.0 * STARTING_SECONDS
        } else {
            LOOK_GAP_SECONDS.max(3.0 * self.ticks.iter().cloned().fold(f64::MIN, f64::max))
        };
        let run_on = fresh
            && self
                .found_at
                .is_some_and(|at| (0.0..=allowed).contains(&(now - at)));
        if let Some(called) = self.called {
            self.ticks.push((now - called).max(0.0));
            let extra = self.ticks.len().saturating_sub(TICKS_KEPT);
            self.ticks.drain(..extra);
        }
        self.called = Some(now);
        if fresh {
            self.found = Some(Arc::clone(found_arc));
            self.found_at = Some(now);
        }
        let at = self.found_at.unwrap_or(now);
        if pyval::is(get(found, "shape"), "starting") {
            if self.starting_since.is_none_or(|since| at < since) || (fresh && !run_on) {
                self.starting_since = Some(at);
            }
        } else {
            self.starting_since = None;
        }
        let tested = catalogued(found)
            && !self
                .starting_since
                .is_some_and(|since| at - since >= STARTING_SECONDS);
        let untested = app_open && !tested;
        let key = (stamp.clone(), get(found, "app_version").clone());
        let changed = !self
            .key
            .as_ref()
            .is_some_and(|(a, b)| pyval::eq(a, &key.0) && pyval::eq(b, &key.1));
        let said = self.untested;
        self.untested = Some(untested);
        if changed {
            self.key = Some(key);
            (self.log)(&format!(
                "Codex layout: {} main, {} helper, engines {} under the main, {} under a helper, {} elsewhere; {}",
                count(get_or_zero(found, "mains")),
                count(get_or_zero(found, "helpers")),
                count(get_or_zero(found, "engines_under_main")),
                count(get_or_zero(found, "engines_under_helper")),
                count(get_or_zero(found, "engines_elsewhere")),
                if pyval::truthy(get(found, "paired")) {
                    "paired"
                } else {
                    "not paired"
                }
            ));
        }
        if untested && (changed || said == Some(false)) {
            let version = get(found, "app_version");
            let named = if pyval::truthy(version) {
                car_machine::pytext::py_str(version)
            } else {
                "(version unknown)".to_owned()
            };
            (self.log)(&format!(
                "Codex {named} runs in a layout this version has not been tested on"
            ));
        }
        let kept_good = get(&self.kept, "last_good");
        let mut last_good = if matches!(kept_good, Value::Object(_)) {
            kept_good.clone()
        } else {
            Value::Null
        };
        if pyval::truthy(get(found, "paired")) {
            self.updated_from = Value::Null;
            let mut good = Map::new();
            good.insert(Str::from("code_version"), self.code_version.clone());
            good.insert(Str::from("engine_version"), word(engine_version));
            good.insert(Str::from("app_version"), get(found, "app_version").clone());
            good.insert(Str::from("layout"), without_holds(found));
            last_good = Value::Object(good);
        }
        let unpaired = pyval::truthy(&self.updated_from)
            && app_open
            && !pyval::truthy(get(found, "paired"))
            && pyval::truthy(&last_good);
        if unpaired && !pyval::truthy(get(&self.kept, "unpaired_after_update")) {
            (self.log)(&format!(
                "the first looks since this product was updated from {} pair no Codex server, where that version paired one",
                car_machine::pytext::py_str(&self.updated_from)
            ));
        }
        let mut now_kept = Map::new();
        let mut put = |key: &str, value: Value| {
            now_kept.insert(Str::from(key), value);
        };
        put("format", Value::from(FORMAT));
        put("code_version", self.code_version.clone());
        put("engine_version", word(engine_version));
        put("app_version", get(found, "app_version").clone());
        put("layout", without_holds(found));
        put("catalogued", Value::Bool(tested));
        put("last_good", last_good);
        put("updated_from", self.updated_from.clone());
        put("unpaired_after_update", Value::Bool(unpaired));
        let now_kept = Value::Object(now_kept);
        if !pyval::eq(&now_kept, &self.kept) {
            self.kept = now_kept.clone();
            write(&self.path, &now_kept, self.pid);
        }
        Ok(Some(now_kept))
    }
}

/// The `refold` points of a text (for the harness).
pub fn text_points(text: &str) -> Vec<u32> {
    points(text)
}
