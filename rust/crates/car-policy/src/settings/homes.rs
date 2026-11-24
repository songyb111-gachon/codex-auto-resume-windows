//! `homes.py`: the Codex homes a watcher is set to watch beside the default one (v0.6.15-beta), as Settings keep them.
//!
//! Up to MAX_EXTRA more homes, each a folder and an alias of 1 to 32 characters. A home is keyed by the SHA-256 of
//! its resolved, case-folded path. Pure but for `key` (`Path.resolve`) and `problem`, which look at the folder; the
//! questions only Windows answers are the [`Os`] handed in, and a folder's identity is the caller's callback.

use car_machine::hash;
use car_machine::json::{Map, Str, Value};
use car_machine::pytext;
use car_machine::pyval::{self, Py};

use super::os::{Os, from_wide, os_path, wide};
use super::unicode_gen::CASEFOLD;
use super::vocab_gen::homes as words;

pub const FIELD: &str = words::FIELD;
pub const MAX_EXTRA: usize = 3;
pub const ALIAS_MAX: usize = 32;
pub const PATH_MAX: usize = 260;
pub const UNC: &str = "unc";
pub const LINK: &str = "link";
pub const MISSING: &str = "missing";
pub const NO_STATE: &str = "no_state";
/// MH was measured up to this Codex (major, minor).
pub const MEASURED: (u64, u64) = (0, 162);

/// `PROBLEMS[word]`: why a folder cannot be a Codex home to watch, in the words a refusal uses.
pub fn problem_text(word: &str) -> &'static str {
    match &words::PROBLEMS {
        car_machine::vocab::Node::Map(pairs) => pairs
            .iter()
            .find(|(name, _)| *name == word)
            .and_then(|(_, text)| text.as_str())
            .unwrap_or(""),
        _ => "",
    }
}

/// `str.casefold()` of a Python `str`.
pub fn casefold(text: &Str) -> Str {
    let mut points = Vec::new();
    for point in text.code_points() {
        match CASEFOLD.binary_search_by_key(&point, |(from, _)| *from) {
            Ok(found) => points.extend(CASEFOLD[found].1.chars().map(u32::from)),
            Err(_) => points.push(point),
        }
    }
    Str::from_code_points(points).expect("folded code points stay in range")
}

const BACKSLASH: u16 = b'\\' as u16;
const SLASH: u16 = b'/' as u16;
const DOT: u16 = b'.' as u16;

/// `ntpath.normpath(text)` of a path that starts with a drive letter, a colon and a separator (`_path_ok`'s).
fn normpath_drive(text: &[u16]) -> Vec<u16> {
    let units: Vec<u16> = text
        .iter()
        .map(|unit| if *unit == SLASH { BACKSLASH } else { *unit })
        .collect();
    let mut out: Vec<u16> = units[..2].to_vec();
    out.push(BACKSLASH);
    let mut parts: Vec<&[u16]> = Vec::new();
    for part in units[3..].split(|unit| *unit == BACKSLASH) {
        if part.is_empty() || part == [DOT] {
            continue;
        }
        if part == [DOT, DOT] {
            parts.pop();
            continue;
        }
        parts.push(part);
    }
    for (index, part) in parts.iter().enumerate() {
        if index > 0 {
            out.push(BACKSLASH);
        }
        out.extend_from_slice(part);
    }
    out
}

/// `_text(value, low, high)`: text of that many characters, none of them a control character.
fn text_ok(value: &Value, low: usize, high: usize) -> bool {
    let Value::Str(text) = value else {
        return false;
    };
    let length = text.len();
    low <= length && length <= high && !text.code_points().any(|point| point < 32 || point == 127)
}

/// `_path_ok(value)`: a local absolute folder path - `PureWindowsPath(value)` absolute, its drive `[A-Za-z]:`.
fn path_ok(value: &Value) -> bool {
    if !text_ok(value, 3, PATH_MAX) {
        return false;
    }
    let Value::Str(text) = value else {
        return false;
    };
    let head: Vec<u32> = text.code_points().take(3).collect();
    let letter = char::from_u32(head[0]).is_some_and(|c| c.is_ascii_alphabetic());
    letter && head[1] == u32::from(':') && (head[2] == u32::from('\\') || head[2] == u32::from('/'))
}

/// `_alias_ok(value)`: 1 to 32 characters with nothing around them.
fn alias_ok(value: &Value) -> bool {
    if !text_ok(value, 1, ALIAS_MAX) {
        return false;
    }
    let Value::Str(text) = value else {
        return false;
    };
    let points: Vec<u32> = text.code_points().collect();
    let space = |point: &u32| char::from_u32(*point).is_some_and(pytext::is_space);
    !points.first().is_some_and(space) && !points.last().is_some_and(space)
}

/// The two entries of one home, when it is exactly `{"path", "alias"}`.
fn entry_parts(entry: &Value) -> Option<(&Value, &Value)> {
    let Value::Object(map) = entry else {
        return None;
    };
    if map.len() != 2 {
        return None;
    }
    Some((map.get("path")?, map.get("alias")?))
}

/// `well_formed(value)`: at most MAX_EXTRA `{"path", "alias"}`, no two paths and no two aliases alike.
pub fn well_formed(os: &dyn Os, value: &Value) -> bool {
    let Value::Array(entries) = value else {
        return false;
    };
    if entries.len() > MAX_EXTRA {
        return false;
    }
    let mut paths: Vec<Vec<u16>> = Vec::new();
    let mut aliases: Vec<Str> = Vec::new();
    for entry in entries {
        let Some((path, alias)) = entry_parts(entry) else {
            return false;
        };
        if !path_ok(path) || !alias_ok(alias) {
            return false;
        }
        let (Value::Str(path), Value::Str(alias)) = (path, alias) else {
            return false;
        };
        paths.push(os.normcase(&normpath_drive(&wide(path))));
        aliases.push(casefold(alias));
    }
    paths.sort();
    paths.dedup();
    aliases.sort();
    aliases.dedup();
    paths.len() == entries.len() && aliases.len() == entries.len()
}

/// `coerce(value, default)`: the list, copied, when it is well formed - else the default.
pub fn coerce(os: &dyn Os, value: &Value, default: &Value) -> Value {
    if !well_formed(os, value) {
        return default.clone();
    }
    let Value::Array(entries) = value else {
        return default.clone();
    };
    Value::Array(
        entries
            .iter()
            .filter_map(entry_parts)
            .map(|(path, alias)| {
                let mut copy = Map::new();
                copy.insert(Str::from("path"), path.clone());
                copy.insert(Str::from("alias"), alias.clone());
                Value::Object(copy)
            })
            .collect(),
    )
}

/// `as_written(path)`: `normcase(abspath(path))`, which looks at no file.
pub fn as_written(os: &dyn Os, path: &Str) -> Result<Str, &'static str> {
    Ok(from_wide(&os.normcase(&os.abspath(&wide(path))?)))
}

/// `key(path)`: the SHA-256 of `normcase(str(Path(path).resolve()))` as lowercase hex.
pub fn key(os: &dyn Os, path: &Str) -> Result<String, &'static str> {
    let resolved = from_wide(&os.normcase(&os.resolve(&wide(path))?));
    // `.encode("utf-8")` of a text holding half a pair: UnicodeEncodeError.
    let text = resolved.as_str().ok_or("UnicodeEncodeError")?;
    Ok(hash::hex(&hash::sha256(text.as_bytes())))
}

/// `_STATE_DB.match(name)`: `^state_[0-9]{1,6}\.sqlite$`.
fn state_db(name: &str) -> bool {
    let Some(rest) = name.strip_prefix("state_") else {
        return false;
    };
    let Some(number) = rest.strip_suffix(".sqlite") else {
        return false;
    };
    (1..=6).contains(&number.len()) && number.bytes().all(|b| b.is_ascii_digit())
}

/// `problem(path)`: why `path` cannot be watched as a Codex home now, or None. Looks at the folder.
pub fn problem(os: &dyn Os, path: &Str) -> Option<&'static str> {
    let units = wide(path);
    let starts = |a: u16| units.len() >= 2 && units[0] == a && units[1] == a;
    if starts(BACKSLASH) || starts(SLASH) {
        return Some(UNC);
    }
    let folder = os_path(path);
    if os.is_symlink(&folder) || os.is_junction(&folder) {
        return Some(LINK);
    }
    if !std::fs::metadata(&folder).is_ok_and(|found| found.is_dir()) {
        return Some(MISSING);
    }
    let Ok(listing) = std::fs::read_dir(&folder) else {
        return Some(MISSING);
    };
    for child in listing {
        let Ok(child) = child else {
            return Some(MISSING);
        };
        let name = child.file_name();
        if name.to_str().is_some_and(state_db)
            && std::fs::metadata(child.path()).is_ok_and(|found| found.is_file())
        {
            return None;
        }
    }
    Some(NO_STATE)
}

/// `strict(value, default_home, identity)`: the Dashboard's write of `codex_homes`, refused in words a person can act
/// on (the ValueError's text). `identity` is the folder's id whatever its spelling, None where it cannot be read.
pub fn strict(
    os: &dyn Os,
    value: &Value,
    default_home: Option<&Str>,
    identity: &dyn Fn(&Str) -> Option<Value>,
) -> Result<(), Str> {
    if !well_formed(os, value) {
        return Err(Str::from(format!(
            "invalid value for codex_homes: at most {MAX_EXTRA} homes, each a local folder and an alias of 1 to \
             {ALIAS_MAX} characters, no two alike"
        )));
    }
    let mut seen: Vec<(Value, Option<Str>)> = Vec::new();
    if let Some(home) = default_home
        && let Some(found) = identity(home)
    {
        seen.push((found, None));
    }
    let Value::Array(entries) = value else {
        return Ok(());
    };
    for (path, alias) in entries.iter().filter_map(entry_parts) {
        let (Value::Str(path), Value::Str(alias)) = (path, alias) else {
            continue;
        };
        let head = |tail: &[u8]| {
            sentence(&[
                b"invalid value for codex_homes: ",
                alias.as_bytes(),
                b": ",
                tail,
            ])
        };
        if let Some(word) = problem(os, path) {
            return Err(head(problem_text(word).as_bytes()));
        }
        let Some(folder) = identity(path) else {
            return Err(head(problem_text(MISSING).as_bytes()));
        };
        if let Some((_, other)) = seen.iter().find(|(known, _)| pyval::eq(known, &folder)) {
            let other: &[u8] = match other {
                None => b"the default Codex home",
                Some(name) => name.as_bytes(),
            };
            return Err(head(
                &[b"that is the same folder as ".as_slice(), other].concat(),
            ));
        }
        seen.push((folder, Some(alias.clone())));
    }
    Ok(())
}

/// Texts joined as `%s` joins them: half of a pair stays a code point of its own.
fn sentence(parts: &[&[u8]]) -> Str {
    Str::from_surrogatepass(parts.concat()).expect("whole texts joined")
}

/// `unmeasured(version)`: a second home is unproven on a Codex newer than MEASURED, or one whose version is unknown.
pub fn unmeasured(version: &Value) -> bool {
    let Value::Str(text) = version else {
        return true;
    };
    let chars: Vec<char> = text
        .code_points()
        .map(|point| char::from_u32(point).unwrap_or('\u{fffd}'))
        .collect();
    let digit_run = |from: usize| {
        let mut end = from;
        while end < chars.len() && pytext::decimal_value(chars[end]).is_some() {
            end += 1;
        }
        end
    };
    // re.search(r"(\d+)\.(\d+)\.(\d+)"): the first start that matches.
    for start in 0..chars.len() {
        let first = digit_run(start);
        if first == start || chars.get(first) != Some(&'.') {
            continue;
        }
        let second = digit_run(first + 1);
        if second == first + 1 || chars.get(second) != Some(&'.') {
            continue;
        }
        let third = digit_run(second + 1);
        if third == second + 1 {
            continue;
        }
        let value = |from: usize, to: usize| -> u64 {
            chars[from..to].iter().fold(0u64, |total, each| {
                total
                    .saturating_mul(10)
                    .saturating_add(u64::from(pytext::decimal_value(*each).unwrap_or(0)))
            })
        };
        let (major, minor) = (value(start, first), value(first + 1, second));
        return (major, minor) > MEASURED;
    }
    true
}

/// `view(configured, found, version, asked)`: what Settings show of the homes.
pub fn view(
    os: &dyn Os,
    configured: &Value,
    found: &Value,
    version: &Value,
    asked: bool,
) -> Py<Value> {
    let mut states: Vec<(Value, Value)> = Vec::new();
    let found_entries: &[Value] = match found {
        Value::Array(items) => items,
        Value::Null => &[],
        // `for entry in (found or [])` of a non-list: a dict iterates its keys, which are never dicts.
        Value::Object(_) | Value::Str(_) => &[],
        Value::Bool(false) => &[],
        Value::Int(int) if int.as_i64() == Some(0) => &[],
        Value::Float(x) if *x == 0.0 => &[],
        _ => return Err("TypeError"),
    };
    for entry in found_entries {
        let Value::Object(map) = entry else { continue };
        let key = map.get("key").ok_or("KeyError")?;
        let state = map.get("state").ok_or("KeyError")?;
        pyval::hashable(key)?;
        match states.iter_mut().find(|(known, _)| pyval::eq(known, key)) {
            Some(slot) => slot.1 = state.clone(),
            None => states.push((key.clone(), state.clone())),
        }
    }
    let lookup = |name: &Value| {
        states
            .iter()
            .find(|(known, _)| pyval::eq(known, name))
            .map(|(_, state)| state.clone())
    };
    let mut listed = Vec::new();
    let mut first = Map::new();
    first.insert(Str::from("key"), Value::from(""));
    first.insert(Str::from("alias"), Value::Null);
    first.insert(Str::from("path"), Value::Null);
    first.insert(
        Str::from("state"),
        lookup(&Value::from("")).unwrap_or_else(|| Value::from("watched")),
    );
    listed.push(Value::Object(first));
    if let Value::Array(entries) = coerce(os, configured, &Value::Array(Vec::new())) {
        for entry in &entries {
            let Some((path, alias)) = entry_parts(entry) else {
                continue;
            };
            let Value::Str(text) = path else { continue };
            let name = key(os, text).map_or(Value::Null, Value::from);
            let mut row = Map::new();
            row.insert(Str::from("key"), name.clone());
            row.insert(Str::from("alias"), alias.clone());
            row.insert(Str::from("path"), path.clone());
            row.insert(Str::from("state"), lookup(&name).unwrap_or(Value::Null));
            listed.push(Value::Object(row));
        }
    }
    let mut out = Map::new();
    out.insert(Str::from("homes"), Value::Array(listed));
    out.insert(
        Str::from("unmeasured"),
        Value::Bool(asked && unmeasured(version)),
    );
    Ok(Value::Object(out))
}
