//! `homefind.py`: a Codex home this PC's Codex uses that the watcher does not watch yet, offered in the Dashboard
//! (v0.6.18). Suggested, never added: Add writes it through the one way a home is added (`homes.strict`), Not now
//! remembers the folder so it is not offered again. Where it looks: the account's `CODEX_HOME` as Windows holds it,
//! and the Codex app's own list of where it has run. Only an installed copy looks.

use std::path::Path;

use car_machine::json::{Map, Str, Value};
use car_policy::settings::homefind::{DISMISSED, DISMISSED_MAX, SWITCH, coerce_dismissed};
use car_policy::settings::homes;
use car_policy::settings::os::{Os, from_wide, normpath, wide};

use crate::error::{Res, refuse};
use crate::host::Host;
use crate::layer::Control;

/// `APP_FILE_MAX`, `APP_ENTRIES_MAX`, `FOUND_MAX`.
pub const APP_FILE_MAX: usize = 1024 * 1024;
pub const APP_ENTRIES_MAX: usize = 256;
pub const FOUND_MAX: usize = 16;

/// `_well_formed(path)`: a local absolute folder path a home may have.
fn well_formed(os: &dyn Os, path: &Value) -> bool {
    let Value::Str(_) = path else { return false };
    let mut entry = Map::new();
    entry.insert(Str::from("path"), path.clone());
    entry.insert(Str::from("alias"), Value::from("home"));
    homes::well_formed(os, &Value::Array(vec![Value::Object(entry)]))
}

/// `os.path.normpath(text)`.
fn norm(text: &Str) -> Str {
    from_wide(&normpath(&wide(text)))
}

/// `dismissed_with(stored, path)`: the folders set aside once `path` is: added last, any other spelling of it
/// dropped, the oldest let go past DISMISSED_MAX.
pub fn dismissed_with(os: &dyn Os, stored: &Value, path: &Str) -> Value {
    let Value::Array(held) = coerce_dismissed(os, stored, &Value::Array(Vec::new())) else {
        return Value::Array(Vec::new());
    };
    let wanted = homes::as_written(os, path);
    let mut kept: Vec<Value> = held
        .into_iter()
        .filter(|entry| match entry {
            Value::Str(text) => homes::as_written(os, text) != wanted,
            _ => true,
        })
        .collect();
    kept.push(Value::Str(norm(path)));
    let skip = kept.len().saturating_sub(DISMISSED_MAX);
    Value::Array(kept.into_iter().skip(skip).collect())
}

/// `app_homes(local_appdata)`: each `paths.codexHome` the Codex app's list of where it has run names, in its order.
pub fn app_homes(base: Option<&str>) -> Vec<String> {
    let Some(base) = base.filter(|each| !each.is_empty()) else {
        return Vec::new();
    };
    let names = ["OpenAI", "Codex", "chrome-native-hosts-v2.json"];
    let mut direct = Path::new(base).to_path_buf();
    for part in names {
        direct.push(part);
    }
    let mut packaged = Path::new(base)
        .join("Packages")
        .join(car_machine::domain::ids::codex_app_family())
        .join("LocalCache")
        .join("Local");
    for part in names {
        packaged.push(part);
    }
    for place in [direct, packaged] {
        let Ok(raw) = std::fs::read(&place) else {
            continue;
        };
        if raw.len() > APP_FILE_MAX {
            continue;
        }
        // `raw.decode("utf-8-sig")`: a leading byte order mark is dropped.
        let body = raw.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(&raw);
        let Ok(text) = std::str::from_utf8(body) else {
            continue;
        };
        let Ok(Value::Object(map)) = car_machine::compat::loads(text) else {
            continue;
        };
        let Some(Value::Array(entries)) = map.get("entries") else {
            continue;
        };
        let mut found = Vec::new();
        for entry in entries.iter().take(APP_ENTRIES_MAX) {
            let home = match entry {
                Value::Object(each) => match each.get("paths") {
                    Some(Value::Object(paths)) => paths.get("codexHome"),
                    _ => None,
                },
                _ => None,
            };
            if let Some(Value::Str(text)) = home
                && let Some(plain) = text.as_str()
                && !car_machine::pytext::strip(plain).is_empty()
            {
                found.push(car_machine::pytext::strip(plain).to_owned());
            }
        }
        return found;
    }
    Vec::new()
}

/// `found(environment, app, installed)`: the folders the two places name, each once (by spelling), at most
/// FOUND_MAX, as named and not yet checked. Nothing where this copy does not look.
pub fn found(os: &dyn Os, host: &dyn Host) -> Vec<Str> {
    if !host.installed() {
        return Vec::new();
    }
    let mut named: Vec<String> = Vec::new();
    named.extend(host.account_codex_home());
    named.extend(host.app_homes());
    let mut seen: Vec<Str> = Vec::new();
    let mut listed: Vec<Str> = Vec::new();
    for path in named {
        let stripped = car_machine::pytext::strip(&path);
        if stripped.is_empty() {
            continue;
        }
        let spelled = homes::as_written(os, &Str::from(stripped));
        if seen.contains(&spelled) {
            continue;
        }
        seen.push(spelled);
        listed.push(norm(&Str::from(stripped)));
    }
    listed.truncate(FOUND_MAX);
    listed
}

fn key_of(os: &dyn Os, path: &Str) -> Option<String> {
    homes::key(os, path).ok()
}

fn identity(path: &Str) -> Option<String> {
    car_platform::homelock::folder_identity(Path::new(path.as_str()?))
}

/// `candidates(values, default_home, named, identity)`: of `named`, each folder that may be offered.
fn candidates(os: &dyn Os, values: &Map, default_home: &Str, named: &[Str]) -> Vec<Str> {
    let null = Value::Null;
    let added = homes::coerce(
        os,
        values.get(homes::FIELD).unwrap_or(&null),
        &Value::Array(Vec::new()),
    );
    let mut taken: Vec<Str> = vec![default_home.clone()];
    if let Value::Array(entries) = &added {
        for entry in entries {
            if let Value::Object(map) = entry
                && let Some(Value::Str(path)) = map.get("path")
            {
                taken.push(path.clone());
            }
        }
    }
    let mut keys: Vec<String> = taken.iter().filter_map(|path| key_of(os, path)).collect();
    let mut ids: Vec<String> = taken.iter().filter_map(identity).collect();
    let aside: Vec<Str> = match coerce_dismissed(
        os,
        values.get(DISMISSED).unwrap_or(&null),
        &Value::Array(Vec::new()),
    ) {
        Value::Array(paths) => paths
            .iter()
            .filter_map(|path| match path {
                Value::Str(text) => Some(homes::as_written(os, text)),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };
    let mut offered = Vec::new();
    for path in named {
        let whole = Value::Str(path.clone());
        if !well_formed(os, &whole)
            || aside.contains(&homes::as_written(os, path))
            || homes::problem(os, path).is_some()
        {
            continue;
        }
        let Some(name) = key_of(os, path) else {
            continue;
        };
        if keys.contains(&name) {
            continue;
        }
        let Some(folder) = identity(path) else {
            continue;
        };
        if ids.contains(&folder) {
            continue;
        }
        ids.push(folder);
        keys.push(name);
        offered.push(path.clone());
    }
    offered
}

impl Control {
    /// `home_suggestion()`: the Codex home Settings > Advanced offers to watch too, and whether it looks at all and
    /// every home is added. Read only: nothing is added here.
    pub fn home_suggestion(&self) -> Res<Value> {
        let values = self.get_settings()?;
        let os = self.host.os();
        let looked = !matches!(values.get(SWITCH), Some(Value::Bool(false)));
        let reply = |on: bool, path: Value, full: bool| {
            let mut map = Map::new();
            map.insert(Str::from("on"), Value::Bool(on));
            map.insert(Str::from("path"), path);
            map.insert(Str::from("full"), Value::Bool(full));
            Value::Object(map)
        };
        if !looked {
            return Ok(reply(false, Value::Null, false));
        }
        let named = found(&*os, &*self.host);
        let offered = candidates(&*os, &values, &Str::from(self.host.codex_home()), &named);
        let null = Value::Null;
        let full = match homes::coerce(
            &*os,
            values.get(homes::FIELD).unwrap_or(&null),
            &Value::Array(Vec::new()),
        ) {
            Value::Array(entries) => entries.len() >= homes::MAX_EXTRA,
            _ => false,
        };
        Ok(reply(
            true,
            offered
                .first()
                .map_or(Value::Null, |path| Value::Str(path.clone())),
            full,
        ))
    }

    /// `dismiss_home_suggestion(path)`: Not now - `path` is never offered again - and what is offered next.
    pub fn dismiss_home_suggestion(&self, path: &Value) -> Res<Value> {
        let named = match path {
            Value::Str(text) => text
                .as_str()
                .map(car_machine::pytext::strip)
                .filter(|plain| !plain.is_empty())
                .map(Str::from),
            _ => None,
        };
        let Some(named) = named else {
            return refuse("name the folder to set aside", "request_failed");
        };
        let stored = self
            .stored_settings()?
            .get(DISMISSED)
            .cloned()
            .unwrap_or(Value::Null);
        let os = self.host.os();
        let mut changes = Map::new();
        changes.insert(Str::from(DISMISSED), dismissed_with(&*os, &stored, &named));
        self.update_settings(&Value::Object(changes))?;
        self.home_suggestion()
    }
}
