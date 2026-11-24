//! `homefind.py`'s settings: the switch that turns the looking for another Codex home off, the folders "Not now" set
//! aside, and the coercer of the latter - the one function of the module the settings read.
//!
//! Ported as the reference has it: a list of at most [`DISMISSED_MAX`] texts, each a local absolute folder path
//! (`homes.well_formed` of a home of that path), no two the same folder by how `homes.as_written` spells it, is kept
//! as it is; anything else is the default. `diffs_settings_values.py`'s `DISMISSED` list (16 and 17 entries, a
//! relative path, a share, a lone surrogate, two spellings of one folder) goes through it as the field's coercer,
//! and `HomefindDiff` calls it on its own. The rest of the module (looking for homes, `dismissed_with`) is the
//! watcher's and is not here.

use car_machine::json::{Map, Str, Value};

use super::homes;
use super::os::Os;

/// `homefind.SWITCH`: the setting that turns the looking off.
pub const SWITCH: &str = "home_suggestions";
/// `homefind.DISMISSED`: the setting that remembers the folders set aside.
pub const DISMISSED: &str = "home_suggestions_dismissed";
/// The most folders Not now remembers.
pub const DISMISSED_MAX: usize = 16;

/// `coerce_dismissed(value, default)`: the folders set aside, each a local absolute path, none twice, at most
/// DISMISSED_MAX - as they are, else the default (none).
pub fn coerce_dismissed(os: &dyn Os, value: &Value, default: &Value) -> Value {
    let Value::Array(paths) = value else {
        return default.clone();
    };
    if paths.len() > DISMISSED_MAX {
        return default.clone();
    }
    let well = |path: &Value| {
        let mut home = Map::new();
        home.insert(Str::from("path"), path.clone());
        home.insert(Str::from("alias"), Value::from("home"));
        matches!(path, Value::Str(_))
            && homes::well_formed(os, &Value::Array(vec![Value::Object(home)]))
    };
    if !paths.iter().all(well) {
        return default.clone();
    }
    let mut written: Vec<Str> = paths
        .iter()
        .filter_map(|path| match path {
            Value::Str(text) => Some(homes::as_written(os, text)),
            _ => None,
        })
        .collect();
    written.sort();
    written.dedup();
    if written.len() != paths.len() {
        return default.clone();
    }
    value.clone()
}
