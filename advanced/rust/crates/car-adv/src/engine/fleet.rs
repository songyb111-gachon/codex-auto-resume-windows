//! See your other PCs (`fleet_view`, v0.6.22): this PC's status in a folder the person syncs themselves, and the
//! other PCs' files read from it (seat S7.2e2, `engine/fleet.py`). There is no network code here: the folder may be a
//! network share Windows reaches, and this only opens files there.
//!
//! At P8, at most every EVERY seconds, a thread of its own writes `<folder>/<alias>.json` - statusfile's closed document
//! with the alias and the edition, nothing else (KEYS, `clean`) - whole or not at all, and replaces only a regular file
//! that says it is this PC's own (`ours`). The folder is checked on every pass (`folder_problem`). Nothing waits on the
//! folder past BOUND seconds an access: a tick that finds one running longer gives that pass up (LATE). The peers are
//! `*.json` there, at most MOST files of at most LIMIT bytes each, this PC's alias skipped (`read_peers`); a hostile
//! file is ignored and counted. What a pass came to is taken up by the next tick, which alone writes to the state.

use std::io::{Read as _, Write as _};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use car_config::Paths;
use car_machine::json::{Map, Options, Str, Value};
use car_policy::plug::{Errand, Guards, HookFailed, View};
use car_policy::settings::statusfile;

use super::supervise::{Bound, field, lock, word};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::vocabulary::{OptionKey, WordingKey};

pub const CAPABILITY: &str = "fleet_view";
pub const FORMAT: &str = "codex-auto-resume/fleet/1";
pub const EDITION: &str = "advanced";
pub const EVERY: f64 = 300.0;
pub const MOST: usize = 16;
pub const LIMIT: u64 = 16 * 1024;
pub const SCAN_MOST: usize = 1024;
pub const ALIAS_MOST: usize = 32;
pub const FOLDER_MOST: usize = 248;
pub const STALE: f64 = 7.0 * 24.0 * 3600.0;
pub const QUIET: f64 = 3.0 * EVERY;
pub const CLOCK_SLACK: f64 = 600.0;
pub const NEXT_MOST: f64 = 8.0 * 24.0 * 3600.0;
pub const PENDING_MOST: i64 = 100_000;
pub const IGNORED_EVERY: f64 = 3600.0;
pub const VERSION_MOST: usize = 32;
pub const BOUND: f64 = 5.0;
pub const OK: &str = "ok";
pub const UNSET: &str = "unset";
pub const MISSING: &str = "missing";
pub const HELD: &str = "held";
pub const NOT_OURS: &str = "not_ours";
pub const INSIDE: &str = "inside";
pub const LINK: &str = "link";
pub const INVALID: &str = "invalid";
pub const LATE: &str = "late";
pub const WAITING_WORDS: [&str; 7] = [MISSING, HELD, NOT_OURS, INSIDE, LINK, INVALID, LATE];
pub const REFUSALS: [&str; 3] = [INSIDE, LINK, INVALID];
pub const WROTE: &str = "wrote";
pub const WAITING: &str = "waiting";
pub const REFUSED: &str = "refused";
pub const IGNORED: &str = "ignored";
pub const FRESH: &str = "fresh";
pub const OLD: &str = "old";
pub const CLOCK: &str = "clock";
pub const QUIET_WORD: &str = "quiet";
const CLOUD_MASK: u32 = 0xFFFF_0FFF;
const CLOUD: u32 = 0x9000_001A;
const ONEDRIVE: u32 = 0x8000_0021;
pub const SEEN_NAME: &str = "fleet-seen.json";
pub const SEEN_FORMAT: &str = "codex-auto-resume/fleet-seen/1";
pub const SEEN_KEYS: [&str; 5] = ["format", "read_at", "ignored", "held", "peers"];
pub const SEEN_LIMIT: u64 = (MOST as u64 + 1) * LIMIT;

/// `KEYS`: exactly what leaves this PC, in the order it is written.
pub fn keys() -> Vec<&'static str> {
    ["format", "alias", "edition"]
        .into_iter()
        .chain(statusfile::KEYS.iter().skip(1).copied())
        .collect()
}

// ---------------------------------------------------------------------------------------------- text helpers
/// `str.casefold()`.
pub fn casefold(text: &str) -> String {
    let points: Vec<u32> = text.chars().map(u32::from).collect();
    car_codex::refold::casefold_points(&points)
        .into_iter()
        .filter_map(char::from_u32)
        .collect()
}

/// `str.isalnum()` of one character: Python's `isalpha` (the reference interpreter's table) or a numeric character.
fn is_alnum(c: char) -> bool {
    let mut buffer = [0u8; 4];
    crate::codex::turns::is_alpha(c.encode_utf8(&mut buffer)) || c.is_numeric()
}

fn reserved(upper: &str) -> bool {
    matches!(upper, "CON" | "PRN" | "AUX" | "NUL")
        || ["COM", "LPT"].iter().any(|stem| {
            upper
                .strip_prefix(stem)
                .is_some_and(|rest| rest.len() == 1 && (b'1'..=b'9').contains(&rest.as_bytes()[0]))
        })
}

/// `alias_valid(value)`: 1 to 32 letters, digits, spaces and hyphens, no space at either end, a name a file may have.
pub fn alias_valid(value: &Value) -> bool {
    let Value::Str(text) = value else {
        return false;
    };
    let Some(text) = text.as_str() else {
        return false;
    };
    let count = text.chars().count();
    (1..=ALIAS_MOST).contains(&count)
        && text == car_machine::pytext::strip(text)
        && text.chars().all(|c| is_alnum(c) || c == ' ' || c == '-')
        && !reserved(&text.to_uppercase())
}

fn version_valid(value: &Value) -> bool {
    let Value::Str(text) = value else {
        return false;
    };
    let Some(text) = text.as_str() else {
        return false;
    };
    let count = text.chars().count();
    (1..=VERSION_MOST).contains(&count)
        && text
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || ".-+".contains(c))
}

/// `machine.epoch(value, *EPOCH_CODEX)`: an OverflowError for an int too large to be a float.
fn bounded_time(value: &Value) -> Result<bool, &'static str> {
    let (low, high) = car_machine::domain::states::EPOCH_CODEX;
    car_machine::domain::states::epoch(value, low, high, false, true)
}

fn refused(message: &'static str) -> &'static str {
    let _ = message;
    "ValueError"
}

/// `clean(value, stem)`: `value` exactly as a fleet file may hold it, in KEYS' order, or a ValueError (an
/// OverflowError for a time too large to be a float, as `epoch` raises it).
pub fn clean(value: &Value, stem: Option<&str>) -> Result<Value, &'static str> {
    let Value::Object(map) = value else {
        return Err(refused("fleet keys"));
    };
    let keys = keys();
    if map.len() != keys.len() || !keys.iter().all(|key| map.contains_key(&Str::new(key))) {
        return Err(refused("fleet keys"));
    }
    if *field(value, "format") != word(FORMAT) {
        return Err(refused("fleet keys"));
    }
    let alias = field(value, "alias");
    if !alias_valid(alias) {
        return Err(refused("fleet alias"));
    }
    if let Some(stem) = stem {
        let alias = car_adv_text(alias);
        if casefold(&alias) != casefold(stem) {
            return Err(refused("fleet alias"));
        }
    }
    if *field(value, "edition") != word(EDITION) || !version_valid(field(value, "version")) {
        return Err(refused("fleet words"));
    }
    let next = field(value, "next_check_at");
    if !bounded_time(field(value, "written_at"))?
        || !(matches!(next, Value::Null) || bounded_time(next)?)
    {
        return Err(refused("fleet times"));
    }
    match field(value, "pending") {
        Value::Int(number)
            if number
                .as_i64()
                .is_some_and(|n| (0..=PENDING_MOST).contains(&n)) => {}
        _ => return Err(refused("fleet pending")),
    }
    let mut status = Map::new();
    for key in statusfile::KEYS {
        let held = if *key == "format" {
            word(statusfile::FORMAT)
        } else {
            field(value, key).clone()
        };
        status.insert((*key).into(), held);
    }
    statusfile::clean(&Value::Object(status))?;
    let mut ordered = Map::new();
    for key in keys {
        ordered.insert(key.into(), field(value, key).clone());
    }
    Ok(Value::Object(ordered))
}

fn car_adv_text(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    }
}

/// `document(status, alias)`: statusfile's document as this PC's file holds it.
pub fn document(status: &Value, alias: &Value) -> Result<Value, &'static str> {
    let mut made = Map::new();
    made.insert("format".into(), word(FORMAT));
    made.insert("alias".into(), alias.clone());
    made.insert("edition".into(), word(EDITION));
    for key in statusfile::KEYS.iter().skip(1) {
        let Value::Object(source) = status else {
            return Err("TypeError");
        };
        let found = source.get(*key).ok_or("KeyError")?;
        made.insert((*key).into(), found.clone());
    }
    let next = made.get("next_check_at").cloned().unwrap_or(Value::Null);
    if !matches!(next, Value::Null) && !bounded_time(&next)? {
        made.insert("next_check_at".into(), Value::Null);
    }
    clean(&Value::Object(made), None)
}

fn as_number(value: &Value) -> f64 {
    super::supervise::number(value).unwrap_or(f64::NAN)
}

/// `shown(found, now)`: one peer as the window shows it.
pub fn shown(found: &Value, now: f64) -> Value {
    let written = as_number(field(found, "written_at"));
    let age = now - written;
    let seen = if age < -CLOCK_SLACK {
        CLOCK
    } else if age > STALE {
        OLD
    } else if age > QUIET {
        QUIET_WORD
    } else {
        FRESH
    };
    let due = field(found, "next_check_at");
    let next = if seen == FRESH && !matches!(due, Value::Null) && {
        let due = as_number(due);
        now <= due && due <= now + NEXT_MOST
    } {
        due.clone()
    } else {
        Value::Null
    };
    let mut row = Map::new();
    for key in ["alias", "watcher", "recovery", "pending"] {
        row.insert(key.into(), field(found, key).clone());
    }
    row.insert("seen".into(), word(seen));
    row.insert(
        "written_at".into(),
        if seen == CLOCK {
            Value::Null
        } else {
            field(found, "written_at").clone()
        },
    );
    row.insert("next_check_at".into(), next);
    Value::Object(row)
}

// ---------------------------------------------------------------------------------------------- the folder
/// `_linked(path)`: a symbolic link, a junction or any other reparse point but a cloud drive's own placeholder.
pub fn linked(path: &Path) -> bool {
    let Ok(metadata) = std::fs::symlink_metadata(path) else {
        return false;
    };
    use std::os::windows::fs::MetadataExt;
    const REPARSE: u32 = 0x400;
    if metadata.file_type().is_symlink() {
        return true;
    }
    if metadata.file_attributes() & REPARSE == 0 {
        return false;
    }
    let tag = car_platform::links::reparse_tag(path).unwrap_or(0);
    if tag == car_platform::links::MOUNT_POINT_TAG || tag == car_platform::links::SYMLINK_TAG {
        return true;
    }
    (tag & CLOUD_MASK) != CLOUD && tag != ONEDRIVE
}

/// `os.path.abspath` of an absolute path: normalised.
fn abspath(text: &str) -> String {
    car_platform::paths::normpath(text)
}

/// The parts of a normalised, case-folded path: (drive, rooted, components).
fn parts_of(text: &str) -> (String, bool, Vec<String>) {
    let (drive, rest) = car_machine::winpath::splitdrive(text);
    let rooted = rest.starts_with('\\') || rest.starts_with('/');
    let parts = rest
        .split(['\\', '/'])
        .filter(|part| !part.is_empty() && *part != ".")
        .map(str::to_owned)
        .collect();
    (drive.to_owned(), rooted, parts)
}

/// `_within(path, root)`: `commonpath((normcase(path), normcase(root))) == normcase(root)`; another drive is not.
pub fn within(path: &str, root: &str) -> bool {
    let (path, root) = (
        car_platform::paths::normcase(path),
        car_platform::paths::normcase(root),
    );
    let (drive, rooted, parts) = parts_of(&path);
    let (root_drive, root_rooted, root_parts) = parts_of(&root);
    if drive != root_drive || rooted != root_rooted {
        return false;
    }
    let common: Vec<&String> = parts
        .iter()
        .zip(&root_parts)
        .take_while(|(a, b)| a == b)
        .map(|(a, _)| a)
        .collect();
    let joined: Vec<&str> = common.iter().map(|part| part.as_str()).collect();
    let made = format!(
        "{drive}{}{}",
        if rooted { "\\" } else { "" },
        joined.join("\\")
    );
    made == root
}

/// `_share(drive)`: two separators, then a server and a share, each named.
fn share(drive: &str) -> bool {
    let chars: Vec<char> = drive.chars().collect();
    if chars.len() < 5 || !"\\/".contains(chars[0]) || !"\\/".contains(chars[1]) {
        return false;
    }
    let named: String = chars[2..].iter().collect::<String>().replace('/', "\\");
    let parts: Vec<&str> = named.split('\\').collect();
    parts.len() == 2
        && parts
            .iter()
            .all(|part| !part.trim_matches([' ', '.']).is_empty())
}

/// `_guarded(paths)`: the folders it may never be inside: this product's home and the Codex homes it knows of.
pub type Guarded = Box<dyn Fn(&Paths) -> Vec<String> + Send + Sync>;

/// The product's guarded folders: the home, `inuse.home(paths)` and `config.codex_home()`.
pub fn guarded_homes(paths: &Paths) -> Vec<String> {
    let mut homes = vec![paths.home.clone()];
    if let Ok(home) = super::supervise::codex_home(paths) {
        homes.push(home);
    }
    let env = |name: &str| std::env::var(name).ok();
    let os = car_config::Os::here(false, Arc::new(super::supervise::PlatformLinks));
    if let Ok(home) = car_config::codex::codex_home(&env, &os) {
        homes.push(home);
    }
    homes
}

/// `_a_home_holds(path, guarded)`: whether `path` or a folder above it is one of the homes, by what the file system
/// says each is.
fn a_home_holds(path: &str, guarded: &[String]) -> bool {
    let homes: Vec<(u32, u64)> = guarded
        .iter()
        .filter_map(|home| car_platform::files::file_identity(Path::new(home)))
        .filter(|(_, inode)| *inode != 0)
        .collect();
    let mut path = abspath(path);
    while !homes.is_empty() {
        if let Some(found) = car_platform::files::file_identity(Path::new(&path))
            && found.1 != 0
            && homes.contains(&found)
        {
            return true;
        }
        let above = dirname(&path);
        if above == path {
            return false;
        }
        path = above;
    }
    false
}

/// `os.path.dirname(path)` (ntpath): the head of `split`, its trailing separators taken off unless it is all of them.
fn dirname(path: &str) -> String {
    let (drive, rest) = car_machine::winpath::splitdrive(path);
    let cut = rest.rfind(['\\', '/']).map_or(0, |at| at + 1);
    let head = &rest[..cut];
    let stripped = head.trim_end_matches(['\\', '/']);
    format!(
        "{drive}{}",
        if stripped.is_empty() { head } else { stripped }
    )
}

/// `folder_problem(folder, paths)`: the word for what is wrong with `folder`, or None.
pub fn folder_problem(folder: &Value, guarded: &[String]) -> Option<&'static str> {
    let Value::Str(text) = folder else {
        return Some(INVALID);
    };
    let Some(folder) = text.as_str() else {
        return Some(INVALID);
    };
    if folder.is_empty()
        || folder.chars().count() > FOLDER_MOST
        || folder
            .chars()
            .any(|c| (c as u32) < 32 || "<>\"|?*".contains(c))
    {
        return Some(INVALID);
    }
    let (drive, rest) = car_machine::winpath::splitdrive(folder);
    let is_share = share(drive);
    if is_share {
        if !rest.is_empty() && !rest.starts_with(['\\', '/']) {
            return Some(INVALID);
        }
    } else if drive.chars().count() != 2 || !drive.ends_with(':') || !rest.starts_with(['\\', '/'])
    {
        return Some(INVALID);
    }
    for home in guarded {
        if within(&abspath(folder), &abspath(home)) {
            return Some(INSIDE);
        }
    }
    if linked(Path::new(folder)) {
        return Some(LINK);
    }
    let Ok(metadata) = std::fs::symlink_metadata(folder) else {
        return Some(MISSING);
    };
    if !metadata.is_dir() {
        return Some(INVALID);
    }
    let real = car_platform::paths::realpath(folder);
    for home in guarded {
        if within(&real, &car_platform::paths::realpath(home)) {
            return Some(INSIDE);
        }
    }
    if (is_share || real.starts_with("\\\\") || real.starts_with("//"))
        && a_home_holds(&real, guarded)
    {
        return Some(INSIDE);
    }
    None
}

// ---------------------------------------------------------------------------------------------- the files
/// Why a read or write of the folder went no further: the file vanished, or any other OSError (held).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Access {
    NotFound,
    Os,
    /// A raise that is not an OSError (a time too large to be a float in `ours`).
    Other,
}

fn access(error: &std::io::Error) -> Access {
    if error.kind() == std::io::ErrorKind::NotFound {
        Access::NotFound
    } else {
        Access::Os
    }
}

/// `json.loads(raw.decode("utf-8"))` with `parse_constant` refusing NaN and the infinities.
fn loads_strict(raw: &[u8], refuse_constants: bool) -> Option<Value> {
    let text = std::str::from_utf8(raw).ok()?;
    let value = car_machine::compat::loads(text).ok()?;
    if refuse_constants && has_constant(text) {
        return None;
    }
    Some(value)
}

/// Whether a JSON text that parsed holds `NaN`, `Infinity` or `-Infinity` outside its strings: the only bare `N` or `I`
/// a parsed text can have.
fn has_constant(text: &str) -> bool {
    let mut inside = false;
    let mut escaped = false;
    for c in text.chars() {
        if inside {
            if escaped {
                escaped = false;
            } else if c == '\\' {
                escaped = true;
            } else if c == '"' {
                inside = false;
            }
        } else if c == '"' {
            inside = true;
        } else if c == 'N' || c == 'I' {
            return true;
        }
    }
    false
}

fn read_limited(path: &Path, limit: u64) -> Result<(std::fs::File, Vec<u8>), Access> {
    let mut file = std::fs::File::open(path).map_err(|error| access(&error))?;
    let mut raw = Vec::new();
    (&mut file)
        .take(limit + 1)
        .read_to_end(&mut raw)
        .map_err(|error| access(&error))?;
    Ok((file, raw))
}

/// `_ours(target, alias, wrote_before)`: whether the file at `target` may be replaced.
pub fn ours(target: &Path, alias: &str, wrote_before: &Value) -> Result<bool, Access> {
    if linked(target) {
        return Ok(false);
    }
    let metadata = std::fs::symlink_metadata(target).map_err(|error| access(&error))?;
    if !metadata.is_file() || metadata.len() > LIMIT {
        return Ok(false);
    }
    let (_, raw) = read_limited(target, LIMIT)?;
    let Some(held) = loads_strict(&raw, false) else {
        return Ok(false);
    };
    if !matches!(held, Value::Object(_))
        || *field(&held, "format") != word(FORMAT)
        || *field(&held, "alias") != word(alias)
    {
        return Ok(false);
    }
    let at = field(&held, "written_at");
    let before = match wrote_before {
        Value::Int(number) => number.as_i64().unwrap_or(0),
        _ => 0,
    };
    if before == 0 {
        return Ok(true);
    }
    let at = match at {
        Value::Int(number) => number.as_i64().map(|n| n as f64),
        Value::Float(number) => Some(*number),
        _ => None,
    };
    match at {
        Some(at) if !at.is_nan() => {
            if at.is_infinite() {
                return Err(Access::Other);
            }
            Ok(!((at.trunc() as i64) > before))
        }
        _ => Ok(true),
    }
}

/// The text `json.dumps(clean(value), indent=2, allow_nan=False) + "\n"` written in text mode (CRLF line ends).
fn fleet_text(value: &Value) -> Result<String, &'static str> {
    let cleaned = clean(value, None)?;
    let text = car_machine::json::to_string(&cleaned, &Options::new().indent(2))
        .map_err(|_| "ValueError")?;
    Ok(format!("{text}\n").replace('\n', "\r\n"))
}

/// What `write` came to: OK, NOT_OURS, or a raise (an access error, or `clean`'s refusal).
#[derive(Debug, PartialEq, Eq)]
pub enum Wrote {
    Word(&'static str),
    Access(Access),
    Refused(&'static str),
}

/// `write(folder, alias, value, wrote_before)`: replace `<folder>/<alias>.json` with `value`, whole.
pub fn write(folder: &str, alias: &str, value: &Value, wrote_before: &Value) -> Wrote {
    let target = PathBuf::from(car_machine::winpath::join(folder, &format!("{alias}.json")));
    let text = match fleet_text(value) {
        Ok(text) => text,
        Err(class) => return Wrote::Refused(class),
    };
    match std::fs::symlink_metadata(&target) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Wrote::Access(access(&error)),
        Ok(_) => match ours(&target, alias, wrote_before) {
            Ok(true) => {}
            Ok(false) => return Wrote::Word(NOT_OURS),
            Err(found) => return Wrote::Access(found),
        },
    }
    let Some((temporary, mut stream)) =
        super::powertasks::temporary_in(Path::new(folder), "fleet-", ".tmp")
    else {
        return Wrote::Access(if Path::new(folder).is_dir() {
            Access::Os
        } else {
            Access::NotFound
        });
    };
    let written = stream
        .write_all(text.as_bytes())
        .and_then(|()| stream.flush())
        .and_then(|()| stream.sync_all());
    drop(stream);
    if let Err(error) = written {
        let _ = std::fs::remove_file(&temporary);
        return Wrote::Access(access(&error));
    }
    if linked(&target) {
        let _ = std::fs::remove_file(&temporary);
        return Wrote::Word(NOT_OURS);
    }
    if let Err(error) = car_platform::files::replace(&temporary, &target) {
        let _ = std::fs::remove_file(&temporary);
        return Wrote::Access(access(&error));
    }
    Wrote::Word(OK)
}

/// `remove_old_name(folder, alias)`: this PC's file under the name it had - only one that says it is that alias's.
pub fn remove_old_name(folder: &str, alias: &str) -> bool {
    let target = PathBuf::from(car_machine::winpath::join(folder, &format!("{alias}.json")));
    match ours(&target, alias, &Value::Null) {
        Ok(true) => std::fs::remove_file(&target).is_ok(),
        _ => false,
    }
}

/// `_read_one(path, stem)`: the file as `clean` keeps it, or None where it is to be ignored.
fn read_one(path: &Path, stem: &str) -> Result<Option<Value>, Access> {
    if linked(path) {
        return Ok(None);
    }
    let before = std::fs::symlink_metadata(path).map_err(|error| access(&error))?;
    if !before.is_file() || before.len() > LIMIT {
        return Ok(None);
    }
    let identity = car_platform::files::file_identity(path);
    let (_file, raw) = read_limited(path, LIMIT)?;
    // `os.path.samestat(before, os.fstat(stream))`: swapped for a link since it was looked at.
    if identity.is_some() && car_platform::files::file_identity(path) != identity {
        return Ok(None);
    }
    if raw.len() as u64 > LIMIT {
        return Ok(None);
    }
    let Some(value) = loads_strict(&raw, true) else {
        return Ok(None);
    };
    Ok(clean(&value, Some(stem)).ok())
}

/// `read_peers(folder, own, step)`: (each other PC's file, how many were ignored, how many are held now), `own`
/// skipped, in the aliases' order. `step` is called before each access.
pub fn read_peers(
    folder: &str,
    own: &Value,
    step: &mut dyn FnMut(),
) -> Result<(Vec<Value>, usize, usize), Access> {
    let mut names: Vec<String> = Vec::new();
    let (mut ignored, mut held) = (0usize, 0usize);
    step();
    let entries = std::fs::read_dir(folder).map_err(|error| access(&error))?;
    for (count, entry) in entries.enumerate() {
        if count >= SCAN_MOST {
            ignored += 1;
            break;
        }
        let Ok(entry) = entry else {
            return Err(Access::Os);
        };
        let name = entry.file_name().to_string_lossy().into_owned();
        if casefold(&name).ends_with(".json") {
            names.push(name);
        }
    }
    names.sort_by_key(|name| casefold(name));
    let own = match own {
        Value::Str(text) => Some(casefold(text.as_str().unwrap_or_default())),
        _ => None,
    };
    let mut kept = Vec::new();
    let mut looked = 0usize;
    for name in names {
        let stem: String = {
            let chars: Vec<char> = name.chars().collect();
            chars[..chars.len() - 5].iter().collect()
        };
        if Some(casefold(&stem)) == own {
            continue;
        }
        if looked >= MOST {
            ignored += 1;
            continue;
        }
        looked += 1;
        step();
        match read_one(
            &PathBuf::from(car_machine::winpath::join(folder, &name)),
            &stem,
        ) {
            Err(Access::NotFound) => continue,
            Err(_) => held += 1,
            Ok(None) => ignored += 1,
            Ok(Some(found)) => kept.push(found),
        }
    }
    Ok((kept, ignored, held))
}

/// `seen_path(paths)`.
pub fn seen_path(paths: &Paths) -> PathBuf {
    Path::new(&paths.advanced_dir).join(SEEN_NAME)
}

/// `write_seen(paths, now, kept, ignored, held)`: what a pass read, kept whole. A raise (an OSError making the folder
/// or the temporary file, `clean`'s refusal) is the caller's.
pub fn write_seen(
    paths: &Paths,
    now: f64,
    kept: &[Value],
    ignored: usize,
    held: usize,
) -> Result<(), &'static str> {
    let mut value = Map::new();
    value.insert("format".into(), word(SEEN_FORMAT));
    value.insert("read_at".into(), Value::Float(now));
    value.insert("ignored".into(), Value::Int((ignored as i64).into()));
    value.insert("held".into(), Value::Int((held as i64).into()));
    let mut peers = Vec::new();
    for each in kept.iter().take(MOST) {
        peers.push(clean(each, None)?);
    }
    value.insert("peers".into(), Value::Array(peers));
    let target = seen_path(paths);
    let folder = target.parent().map(Path::to_path_buf).unwrap_or_default();
    std::fs::create_dir_all(&folder).map_err(|_| "OSError")?;
    if linked(&target) {
        return Ok(());
    }
    let text = car_machine::json::to_string(&Value::Object(value), &Options::new())
        .map_err(|_| "ValueError")?;
    let (temporary, mut stream) =
        super::powertasks::temporary_in(&folder, "fleet-seen.", ".tmp").ok_or("OSError")?;
    let written = stream.write_all(text.as_bytes());
    drop(stream);
    if written.is_err() || car_platform::files::replace(&temporary, &target).is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    Ok(())
}

/// `read_seen(paths)`: what the last pass kept, each peer checked again - or None.
pub fn read_seen(paths: &Paths) -> Option<Value> {
    let target = seen_path(paths);
    if linked(&target) || std::fs::symlink_metadata(&target).ok()?.len() > SEEN_LIMIT {
        return None;
    }
    let (_, raw) = read_limited(&target, SEEN_LIMIT).ok()?;
    let value = loads_strict(&raw, false)?;
    let Value::Object(map) = &value else {
        return None;
    };
    let order: Vec<&str> = map
        .keys()
        .map(|key| key.as_str().unwrap_or_default())
        .collect();
    if order != SEEN_KEYS || *field(&value, "format") != word(SEEN_FORMAT) {
        return None;
    }
    let count = |name: &str| match field(&value, name) {
        Value::Int(number) => number
            .as_i64()
            .filter(|n| (0..=SCAN_MOST as i64).contains(n)),
        _ => None,
    };
    let (ignored, held) = (count("ignored")?, count("held")?);
    if !bounded_time(field(&value, "read_at")).ok()? {
        return None;
    }
    let Value::Array(peers) = field(&value, "peers") else {
        return None;
    };
    let mut checked = Vec::new();
    for each in peers.iter().take(MOST) {
        let stem = match each {
            Value::Object(_) => match field(each, "alias") {
                Value::Str(text) => Some(text.as_str().unwrap_or_default().to_owned()),
                // `clean(each, alias)` with an alias that is not a text: casefold raises (AttributeError).
                Value::Null => None,
                _ => return None,
            },
            _ => None,
        };
        checked.push(clean(each, stem.as_deref()).ok()?);
    }
    let mut found = Map::new();
    found.insert("read_at".into(), field(&value, "read_at").clone());
    found.insert("ignored".into(), Value::Int(ignored.into()));
    found.insert("held".into(), Value::Int(held.into()));
    found.insert("peers".into(), Value::Array(checked));
    Some(Value::Object(found))
}

/// `forget_seen(paths)`.
pub fn forget_seen(paths: &Paths) {
    let target = seen_path(paths);
    if !linked(&target) {
        let _ = std::fs::remove_file(&target);
    }
}

/// `waiting_word(stamp)`: the word a FLEET_WAITING stamp stands for, or None.
pub fn waiting_word(stamp: &Value) -> Option<&'static str> {
    match stamp {
        Value::Int(number) => number
            .as_i64()
            .filter(|n| (1..=WAITING_WORDS.len() as i64).contains(n))
            .map(|n| WAITING_WORDS[n as usize - 1]),
        _ => None,
    }
}

// ---------------------------------------------------------------------------------------------- the code
/// `status(now)`: statusfile's document as the watcher's status file would say it now (`_status_now`).
pub type Status = Box<dyn Fn(f64) -> Result<Value, Raised> + Send + Sync>;
/// How a pass is run: `spawn(run)`, the pass's thread (its `is_alive` read through the handle answered).
pub type Spawn = Box<dyn Fn(Box<dyn FnOnce() + Send>) -> Result<Worker, Raised> + Send + Sync>;
/// The clock an access is timed by (`time.monotonic`).
pub type Clock = Box<dyn Fn() -> f64 + Send + Sync>;

/// A pass's thread: whether it still runs.
pub struct Worker(pub Box<dyn Fn() -> bool + Send + Sync>);

/// The product's spawn: a daemon thread named `car-fleet`.
pub fn thread_spawn(run: Box<dyn FnOnce() + Send>) -> Result<Worker, Raised> {
    let handle = std::thread::Builder::new()
        .name("car-fleet".into())
        .spawn(run)
        .map_err(|_| Raised::new("RuntimeError"))?;
    let handle = Arc::new(handle);
    Ok(Worker(Box::new(move || !handle.is_finished())))
}

#[derive(Default)]
struct Pass {
    came_to: Option<(&'static str, usize, Option<i64>)>,
    touched: Option<f64>,
    late: bool,
}

#[derive(Default)]
struct Memory {
    word: Option<&'static str>,
    ignored: usize,
    ignored_told: Option<f64>,
}

struct Inner {
    paths: Paths,
    bound: Mutex<Option<Bound>>,
    status: Status,
    spawn: Spawn,
    clock: Clock,
    guarded: Guarded,
    worker: Mutex<Option<Worker>>,
    pass: Mutex<Pass>,
    memory: Mutex<Memory>,
}

/// `FleetView(paths, status=..., spawn=..., clock=...)`: its P8 errand.
#[derive(Clone)]
pub struct FleetView {
    inner: Arc<Inner>,
}

impl FleetView {
    pub fn new(
        paths: Paths,
        status: Status,
        spawn: Spawn,
        clock: Clock,
        guarded: Guarded,
    ) -> FleetView {
        FleetView {
            inner: Arc::new(Inner {
                paths,
                bound: Mutex::new(None),
                status,
                spawn,
                clock,
                guarded,
                worker: Mutex::new(None),
                pass: Mutex::new(Pass::default()),
                memory: Mutex::new(Memory::default()),
            }),
        }
    }

    /// `bind(scoped)` with a harness's own state.
    pub fn bind_to(&self, bound: Bound) {
        *lock(&self.inner.bound) = Some(bound);
    }

    /// P8: what the last pass came to taken up; DEFER while a pass is held; an errand where one is due.
    pub fn ticked(&self) -> Spoke {
        let Some(bound) = lock(&self.inner.bound).clone() else {
            return Ok(Said::Defer);
        };
        let answer = (|| -> Result<Option<(f64, Value, Value)>, Raised> {
            self.take_up(&bound)?;
            let alive = lock(&self.inner.worker)
                .as_ref()
                .is_some_and(|worker| (worker.0)());
            if alive {
                self.give_up_late(&bound)?;
                return Ok(None);
            }
            let now = bound.now()?;
            let last =
                bound.read(|scoped| scoped.stamped(&word(OptionKey::LastFleetWrite.as_str())))?;
            if let Some(last) = super::supervise::number(&last)
                && 0.0 <= now - last
                && now - last < EVERY
            {
                return Ok(None);
            }
            let words = bound.read(|scoped| scoped.wordings())?;
            let alias = words
                .get(WordingKey::FleetAlias.as_str())
                .cloned()
                .unwrap_or(Value::Null);
            let folder = words
                .get(WordingKey::FleetFolder.as_str())
                .cloned()
                .unwrap_or(Value::Null);
            if alias_valid(&alias) && car_machine::pyval::truthy(&folder) {
                Ok(Some((now, alias, folder)))
            } else {
                Ok(None)
            }
        })();
        match answer {
            Ok(Some((now, alias, folder))) => Ok(Said::Errand(Box::new(FleetErrand {
                code: self.clone(),
                now,
                alias,
                folder,
            }))),
            _ => Ok(Said::Defer),
        }
    }

    /// `_begin(now, alias, folder)`: the stamp first, then the pass on a thread of its own.
    pub fn begin(&self, now: f64, alias: Value, folder: Value) -> Result<(), Raised> {
        let bound = lock(&self.inner.bound)
            .clone()
            .ok_or_else(|| Raised::new("AttributeError"))?;
        let whole = super::anchor::whole(now).map_err(Raised::new)?;
        bound.read(|scoped| {
            scoped.stamp(
                &word(OptionKey::LastFleetWrite.as_str()),
                &Value::Int(whole.max(1).into()),
            )
        })?;
        let wrote_before =
            bound.read(|scoped| scoped.stamped(&word(OptionKey::FleetWroteAt.as_str())))?;
        {
            let mut pass = lock(&self.inner.pass);
            pass.late = false;
            pass.touched = Some((self.inner.clock)());
        }
        let passing = self.clone();
        let worker = (self.inner.spawn)(Box::new(move || {
            passing.run_pass(now, &alias, &folder, &wrote_before)
        }));
        *lock(&self.inner.worker) = worker.ok();
        Ok(())
    }

    fn step(&self) {
        lock(&self.inner.pass).touched = Some((self.inner.clock)());
    }

    /// `_pass(now, alias, folder, wrote_before)`: one pass, off the watcher's tick; never raises.
    pub fn run_pass(&self, now: f64, alias: &Value, folder: &Value, wrote_before: &Value) {
        let (mut word_found, mut ignored, mut wrote) = (HELD, 0usize, None);
        let outcome = (|| -> Result<(), Access> {
            self.step();
            word_found =
                folder_problem(folder, &(self.inner.guarded)(&self.inner.paths)).unwrap_or(OK);
            if word_found == OK {
                let folder = car_adv_text(folder);
                let alias_text = car_adv_text(alias);
                let status = (self.inner.status)(now).map_err(|_| Access::Other)?;
                let value = document(&status, alias).map_err(|_| Access::Other)?;
                self.step();
                match write(&folder, &alias_text, &value, wrote_before) {
                    Wrote::Word(found) => word_found = found,
                    Wrote::Access(found) => return Err(found),
                    Wrote::Refused(_) => return Err(Access::Other),
                }
                if word_found == OK {
                    let at = super::supervise::number(field(&value, "written_at")).unwrap_or(1.0);
                    wrote = Some((at.trunc() as i64).max(1));
                }
                let mut step = || self.step();
                let (kept, found_ignored, held) = read_peers(&folder, alias, &mut step)?;
                ignored = found_ignored;
                if !lock(&self.inner.pass).late {
                    write_seen(&self.inner.paths, now, &kept, ignored, held)
                        .map_err(|_| Access::Other)?;
                }
                if held > 0 && word_found == OK {
                    word_found = HELD;
                }
            }
            Ok(())
        })();
        match outcome {
            Err(Access::NotFound) => word_found = MISSING,
            Err(_) => word_found = HELD,
            Ok(()) => {}
        }
        let mut pass = lock(&self.inner.pass);
        if !pass.late {
            pass.came_to = Some((word_found, ignored, wrote));
        }
    }

    /// `_give_up_late()`: a pass whose access has run longer than BOUND is given up, once.
    fn give_up_late(&self, bound: &Bound) -> Result<(), Raised> {
        {
            let mut pass = lock(&self.inner.pass);
            let Some(touched) = pass.touched else {
                return Ok(());
            };
            if pass.late || pass.came_to.is_some() || (self.inner.clock)() - touched <= BOUND {
                return Ok(());
            }
            pass.late = true;
            let ignored = lock(&self.inner.memory).ignored;
            pass.came_to = Some((LATE, ignored, None));
        }
        self.take_up(bound)
    }

    /// `_take_up()`: what the last pass came to, into the stamps and the journal.
    fn take_up(&self, bound: &Bound) -> Result<(), Raised> {
        let Some((found, ignored, wrote)) = lock(&self.inner.pass).came_to.take() else {
            return Ok(());
        };
        if found == OK {
            bound.read(|scoped| scoped.unstamp(&word(OptionKey::FleetWaiting.as_str())))?;
        } else {
            let index = WAITING_WORDS
                .iter()
                .position(|each| *each == found)
                .unwrap_or(0) as i64
                + 1;
            bound.read(|scoped| {
                scoped.stamp(
                    &word(OptionKey::FleetWaiting.as_str()),
                    &Value::Int(index.into()),
                )
            })?;
        }
        if let Some(wrote) = wrote {
            bound.read(|scoped| {
                scoped.stamp(
                    &word(OptionKey::FleetWroteAt.as_str()),
                    &Value::Int(wrote.into()),
                )
            })?;
        }
        let changed = {
            let mut memory = lock(&self.inner.memory);
            let changed = memory.word != Some(found);
            if changed {
                memory.word = Some(found);
            }
            changed
        };
        if changed {
            let code = if found == OK {
                WROTE
            } else if REFUSALS.contains(&found) || found == NOT_OURS {
                REFUSED
            } else {
                WAITING
            };
            bound.read(|scoped| scoped.count(&word(code)))?;
        }
        let before = lock(&self.inner.memory).ignored;
        if ignored > before {
            let now = bound.now()?;
            let told = lock(&self.inner.memory).ignored_told;
            if told.is_none_or(|told| !(0.0 <= now - told && now - told < IGNORED_EVERY)) {
                lock(&self.inner.memory).ignored_told = Some(now);
                bound.read(|scoped| scoped.count(&word(IGNORED)))?;
            }
        }
        lock(&self.inner.memory).ignored = ignored;
        Ok(())
    }
}

struct FleetErrand {
    code: FleetView,
    now: f64,
    alias: Value,
    folder: Value,
}

impl Errand for FleetErrand {
    fn run(&self, _view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        self.code
            .begin(self.now, self.alias.clone(), self.folder.clone())
            .map(|()| Value::Null)
            .map_err(|_| HookFailed)
    }
}

impl Code for FleetView {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.bind_to(Bound::of(binding));
        Some(Ok(()))
    }

    fn tick(&mut self, _view: &dyn View) -> Spoke {
        self.ticked()
    }
}

/// `_status_now(paths, now)` until the entry points hand it (S6.1/S7.3d: core's store, settings and version through
/// `statusfile.content`): no status, so every pass is HELD.
pub fn no_status(_now: f64) -> Result<Value, Raised> {
    Err(Raised::new("NotImplementedError"))
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(FleetView::new(
        paths.clone(),
        Box::new(no_status),
        Box::new(thread_spawn),
        Box::new(super::analytics::monotonic),
        Box::new(guarded_homes),
    )))
}
