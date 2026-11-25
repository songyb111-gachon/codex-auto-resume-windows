//! `oncewords.py`: words for this time (v0.6.16-beta.3) - a person's own words added, once, to one waiting
//! interruption's next continuation.
//!
//! Kept in `config/once-words.json`, one small file beside the state: `{"<64-hex interruption id>": {"text": "...",
//! "written_at": 1760000000.0}, ...}`. The text is a Custom message in every way (A27): at most 2000 characters,
//! checked again every time it is read - an entry that fails is treated as not set, and a file that cannot be
//! believed is read as holding nothing. Each write takes one named lock (the one the file's path names), rereads,
//! decides and replaces the file whole. Nothing here sends anything.

use std::io::Write;
use std::path::{Path, PathBuf};

use car_machine::compat::loads;
use car_machine::domain::ids;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_policy::classify::continuation::validate_custom;

use crate::host::Host;
use crate::seen::temporary;

pub const FILE_NAME: &str = "once-words.json";
/// At most this many interruptions hold words at once.
pub const MAX_ENTRIES: usize = 50;
pub const FILE_LIMIT: u64 = 512 * 1024;
pub const LOCK_SECONDS: f64 = 5.0;
const REPLACE_TRIES: usize = 20;
const REPLACE_PAUSE_MS: u64 = 25;

pub const READ_OK: &str = "ok";
pub const READ_MISSING: &str = "missing";
pub const READ_INVALID: &str = "invalid";
pub const READ_UNREADABLE: &str = "unreadable";

/// Every entry that may be believed (interruption id -> (text, written_at)), in the file's order.
pub type Held = Vec<(String, (Str, f64))>;

/// `OnceWordsError(message, code)`.
#[derive(Clone, Debug, PartialEq)]
pub struct OnceWordsError {
    pub message: String,
    pub code: String,
}

/// `entries(document)`: the entries of a document that may be believed, each checked again (A27). `Err` is the
/// Python exception class a number too large for a float raises.
pub fn entries(document: &Value) -> Result<Held, &'static str> {
    let Value::Object(map) = document else {
        return Ok(Vec::new());
    };
    if map.len() > MAX_ENTRIES {
        return Ok(Vec::new());
    }
    let mut kept: Held = Vec::new();
    for (key, entry) in map {
        let Some(name) = key.as_str() else { continue };
        if ids::read_interruption_id(name).as_deref() != Some(name) {
            continue;
        }
        let Value::Object(entry) = entry else {
            continue;
        };
        let written = match entry.get("written_at") {
            Some(Value::Float(x)) => *x,
            Some(Value::Int(int)) => match int.as_i64() {
                Some(small) => small as f64,
                None => match int.to_string().parse::<f64>() {
                    Ok(big) if big.is_finite() => big,
                    _ => return Err("OverflowError"),
                },
            },
            _ => continue,
        };
        if !written.is_finite() || written < 0.0 {
            continue;
        }
        let Ok(text) = validate_custom(entry.get("text").unwrap_or(&Value::Null)) else {
            continue;
        };
        kept.retain(|(each, _)| each != name);
        kept.push((name.to_owned(), (Str::from(text), written)));
    }
    Ok(kept)
}

/// `read_file(path)`: (why, entries).
pub fn read_file(path: &Path) -> Result<(&'static str, Held), &'static str> {
    if car_config::paths::is_link(&path.to_string_lossy()) {
        return Ok((READ_INVALID, Vec::new()));
    }
    let info = match std::fs::metadata(path) {
        Ok(info) => info,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok((READ_MISSING, Vec::new()));
        }
        Err(_) => return Ok((READ_UNREADABLE, Vec::new())),
    };
    if info.len() > FILE_LIMIT {
        return Ok((READ_INVALID, Vec::new()));
    }
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok((READ_MISSING, Vec::new()));
        }
        Err(_) => return Ok((READ_UNREADABLE, Vec::new())),
    };
    let Ok(text) = String::from_utf8(bytes) else {
        return Ok((READ_INVALID, Vec::new()));
    };
    // `read_text` translates a carriage return to a line feed: the same JSON, or the same refusal.
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    match loads(&text) {
        Ok(document @ Value::Object(_)) => Ok((READ_OK, entries(&document)?)),
        Ok(_) | Err(_) => Ok((READ_INVALID, Vec::new())),
    }
}

fn written_bytes(held: &Held) -> Option<String> {
    let mut map = Map::new();
    for (key, (text, written)) in held {
        let mut entry = Map::new();
        entry.insert(Str::from("text"), Value::Str(text.clone()));
        entry.insert(Str::from("written_at"), Value::Float(*written));
        map.insert(Str::from(key.as_str()), Value::Object(entry));
    }
    to_string(&Value::Object(map), &Options::wire().sort_keys(true)).ok()
}

fn replace(temporary: &Path, path: &Path) -> std::io::Result<()> {
    let mut last = None;
    for attempt in 0..REPLACE_TRIES {
        match std::fs::rename(temporary, path) {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
                last = Some(error);
                if attempt + 1 < REPLACE_TRIES {
                    std::thread::sleep(std::time::Duration::from_millis(REPLACE_PAUSE_MS));
                }
            }
            Err(error) => return Err(error),
        }
    }
    Err(last.unwrap_or_else(|| std::io::Error::other("replace")))
}

/// `_write(path, held)`: `held` to `path` whole, or the file removed when it holds nothing: false where Windows
/// refused, with nothing left behind.
fn write(path: &Path, held: &Held) -> bool {
    if held.is_empty() {
        let present = path.exists() || car_config::paths::is_link(&path.to_string_lossy());
        if !present {
            return true;
        }
        return match std::fs::remove_file(path) {
            Ok(()) => true,
            Err(error) => error.kind() == std::io::ErrorKind::NotFound,
        };
    }
    let folder = path.parent().unwrap_or(Path::new("."));
    let Ok((temp, mut file)) = temporary(folder, "once-words.", ".tmp") else {
        return false;
    };
    let ok = written_bytes(held)
        .map(|text| {
            file.write_all(text.as_bytes())
                .and_then(|_| file.flush())
                .and_then(|_| file.sync_all())
                .is_ok()
        })
        .unwrap_or(false);
    drop(file);
    if ok && replace(&temp, path).is_ok() {
        return true;
    }
    let _ = std::fs::remove_file(&temp);
    false
}

/// The words for this time of one state folder: read by anyone, written under the file's one lock.
pub struct OnceWords<'a> {
    pub path: PathBuf,
    host: &'a dyn Host,
}

impl<'a> OnceWords<'a> {
    pub fn of(file: &str, host: &'a dyn Host) -> OnceWords<'a> {
        OnceWords {
            path: PathBuf::from(file),
            host,
        }
    }

    /// `held()`: every entry that may be believed now.
    pub fn held(&self) -> Result<Held, &'static str> {
        Ok(read_file(&self.path)?.1)
    }

    /// `words(key)`: this interruption's words, checked again as they are read, or None.
    pub fn words(&self, key: &str) -> Result<Option<Str>, &'static str> {
        Ok(self
            .held()?
            .into_iter()
            .find(|(each, _)| each == key)
            .map(|(_, (text, _))| text))
    }

    /// `count()`.
    pub fn count(&self) -> Result<usize, &'static str> {
        Ok(self.held()?.len())
    }

    /// `_change(change)`: take the lock, reread, `change` the entries (which returns the answer), and write them
    /// back if they moved. `(answer, written)`: written is false where the lock or Windows refused.
    fn change<T>(&self, change: impl FnOnce(&mut Held) -> T) -> (Option<T>, bool) {
        if !self.path.parent().is_some_and(Path::is_dir) {
            return (None, false);
        }
        let Ok(lock) = self.host.lock(&self.path.to_string_lossy(), LOCK_SECONDS) else {
            return (None, false);
        };
        let outcome = (|| {
            let Ok((why, mut held)) = read_file(&self.path) else {
                return (None, false);
            };
            if why == READ_UNREADABLE {
                return (None, false);
            }
            let before = held.clone();
            let answer = change(&mut held);
            if held == before && why != READ_INVALID {
                return (Some(answer), true);
            }
            let written = write(&self.path, &held);
            (Some(answer), written)
        })();
        drop(lock);
        outcome
    }

    /// `put(key, text, now=None, guard=None)`: words for interruption `key`, replacing any it had.
    pub fn put(
        &self,
        key: &str,
        text: &Value,
        now: Option<f64>,
        guard: impl FnOnce() -> Result<(), String>,
    ) -> Result<bool, OnceWordsError> {
        if ids::read_interruption_id(key).as_deref() != Some(key) {
            return Err(OnceWordsError {
                message: "invalid interruption id".into(),
                code: "invalid_id".into(),
            });
        }
        let text = validate_custom(text).map_err(|refused| OnceWordsError {
            message: refused.message,
            code: "request_failed".into(),
        })?;
        let moment = now.unwrap_or_else(|| self.host.now());
        let mut refusal: Option<String> = None;
        let (answer, written) = self.change(|held| {
            if let Err(message) = guard() {
                refusal = Some(message);
                return "guard";
            }
            if !held.iter().any(|(each, _)| each == key) && held.len() >= MAX_ENTRIES {
                return "too_many";
            }
            held.retain(|(each, _)| each != key);
            held.push((key.to_owned(), (Str::from(text.as_str()), moment)));
            "set"
        });
        if let Some(message) = refusal {
            return Err(OnceWordsError {
                message,
                code: "guard".into(),
            });
        }
        if answer == Some("too_many") {
            return Err(OnceWordsError {
                message: format!(
                    "at most {MAX_ENTRIES} waiting recoveries can have words for this time"
                ),
                code: "too_many_messages".into(),
            });
        }
        if !written {
            return Err(OnceWordsError {
                message: "the state is busy".into(),
                code: "state_busy".into(),
            });
        }
        Ok(true)
    }

    /// `remove(key)`: true when it holds none afterwards.
    pub fn remove(&self, key: &str) -> bool {
        self.change(|held| held.retain(|(each, _)| each != key)).1
    }

    /// `unchanged(key, seen)`: whether this interruption's words are still `seen`, read under the file's lock.
    pub fn unchanged(&self, key: &str, seen: Option<&Str>) -> Option<bool> {
        let (answer, written) = self.change(|held| {
            let found = held
                .iter()
                .find(|(each, _)| each == key)
                .map(|(_, (text, _))| text);
            found == seen
        });
        if written { answer } else { None }
    }

    /// `restore(key, text, now=None)`: words put back for `key` only if it holds none now.
    pub fn restore(&self, key: &str, text: &Value, now: Option<f64>) -> bool {
        let Ok(text) = validate_custom(text) else {
            return false;
        };
        let moment = now.unwrap_or_else(|| self.host.now());
        let (answer, written) = self.change(|held| {
            if held.iter().any(|(each, _)| each == key) || held.len() >= MAX_ENTRIES {
                return false;
            }
            held.push((key.to_owned(), (Str::from(text.as_str()), moment)));
            true
        });
        answer == Some(true) && written
    }

    /// `prune(keep)`: every entry whose interruption `keep` no longer keeps taken away; how many.
    pub fn prune(&self, keep: impl Fn(&str) -> bool) -> usize {
        let Ok((why, held)) = read_file(&self.path) else {
            return 0;
        };
        if why == READ_MISSING || (why == READ_OK && held.iter().all(|(key, _)| keep(key))) {
            return 0;
        }
        let (answer, written) = self.change(|held| {
            let before = held.len();
            held.retain(|(key, _)| keep(key));
            before - held.len()
        });
        if written { answer.unwrap_or(0) } else { 0 }
    }
}
