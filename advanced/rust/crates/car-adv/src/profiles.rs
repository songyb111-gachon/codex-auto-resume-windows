//! The person's saved Codex accounts (`profiles.py`, account_auto_switch): each a copy of Codex's sign-in file, sealed.
//!
//! A profile is one file, `<product home>\accounts\<id>.dat`: the seal (Windows' data protection for the current
//! user, through [`Host`]) over a JSON object - the sign-in file's bytes (base64), the address, the plan word and its
//! times. Beside them `switch.intent`, `switch.last`, `switch.times` and `usage.read`, sealed the same way. What
//! leaves this module for a person to see is `view`: an id, the address masked, the plan word and a state word.
//! The diffs compare what is unsealed, never sealed bytes.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use car_machine::json::{Map, Options, Str, Value};

use crate::state::py;
use crate::state::seam::accounts::{self, Failure, Host};
use crate::state::sql::{Row, int, string};

pub const FOLDER: &str = "accounts";
pub const SUFFIX: &str = ".dat";
pub const INTENT: &str = "switch.intent";
pub const LAST: &str = "switch.last";
pub const TIMES: &str = "switch.times";
pub const READS: &str = "usage.read";
pub const READY: &str = "ready";
pub const EXHAUSTED: &str = "exhausted";
pub const NEEDS_SIGN_IN: &str = "needs_sign_in";
pub const DAMAGED: &str = "damaged";
pub const MOST: usize = 8;
pub const LOCK_SECONDS: f64 = 5.0;
pub const KEEP_SECONDS: f64 = 60.0;
pub const WINDOWS: &[&str] = &["five_hour", "weekly"];
const FIELDS: &[&str] = &[
    "used_at",
    "exhausted_until",
    "failed_at",
    "auth",
    "plan",
    "usage",
    "unread_at",
    "seen_at",
];

/// `ProfileError` and its two subclasses, by class.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProfileError {
    pub class: &'static str,
    pub message: String,
}

impl ProfileError {
    fn new(message: &str) -> ProfileError {
        ProfileError {
            class: "ProfileError",
            message: message.into(),
        }
    }
}

impl std::fmt::Display for ProfileError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.class, self.message)
    }
}

impl std::error::Error for ProfileError {}

pub type Result<T> = std::result::Result<T, ProfileError>;

fn auth_error(failure: Failure) -> ProfileError {
    ProfileError {
        class: "AuthFileError",
        message: failure.0,
    }
}

/// `_ID.match(name)`: `^[0-9a-f]{16}$` - `$` also before a final line break, as Python's `re` has it.
pub fn is_id(text: &str) -> bool {
    let body = text.strip_suffix('\n').unwrap_or(text);
    body.len() == 16
        && body
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn whole(value: &Value) -> Value {
    if py::is_int(value) {
        value.clone()
    } else {
        Value::Null
    }
}

/// `_window(value)`: {used, resets_at} of a kept window, or None.
fn window(value: &Value) -> Value {
    let Value::Object(map) = value else {
        return Value::Null;
    };
    let used = map.get("used").cloned().unwrap_or(Value::Null);
    let fits = match &used {
        Value::Int(_) | Value::Float(_) => {
            py::as_f64(&used).is_some_and(|x| !x.is_nan() && (0.0..=10000.0).contains(&x))
        }
        _ => false,
    };
    if !fits {
        return Value::Null;
    }
    let mut found = Map::new();
    found.insert(Str::new("used"), used);
    found.insert(
        Str::new("resets_at"),
        whole(map.get("resets_at").unwrap_or(&Value::Null)),
    );
    Value::Object(found)
}

/// `reading(value)`: a kept usage reading as it is read back, or None for anything that is not exactly one.
pub fn reading(value: &Value) -> Value {
    let Value::Object(map) = value else {
        return Value::Null;
    };
    if !matches!(map.get("read_at"), Some(Value::Int(_))) {
        return Value::Null;
    }
    let most = map.get("most_used").cloned().unwrap_or(Value::Null);
    let available = map.get("available").cloned().unwrap_or(Value::Null);
    let mut found = Map::new();
    found.insert(Str::new("read_at"), map["read_at"].clone());
    found.insert(
        Str::new("available"),
        if py::is_bool(&available) {
            available
        } else {
            Value::Null
        },
    );
    let most_ok = match &most {
        Value::Int(_) => true,
        Value::Float(x) => !x.is_nan(),
        _ => false,
    };
    found.insert(
        Str::new("most_used"),
        if most_ok { most } else { Value::Null },
    );
    for name in WINDOWS {
        found.insert(
            Str::new(name),
            window(map.get(*name).unwrap_or(&Value::Null)),
        );
    }
    Value::Object(found)
}

/// `digest(data)`: sha256, hex.
pub fn digest(data: &[u8]) -> String {
    car_machine::hash::hex(&car_machine::hash::sha256(data))
}

/// The profiles under one product home.
pub struct Profiles {
    pub directory: PathBuf,
    pub host: Arc<dyn Host>,
    pub clock: Box<dyn Fn() -> f64 + Send + Sync>,
}

impl Profiles {
    /// `Profiles(home, seal=..., open_=..., clock=..., lock=...)`.
    pub fn new(
        home: &Path,
        host: Arc<dyn Host>,
        clock: Box<dyn Fn() -> f64 + Send + Sync>,
    ) -> Profiles {
        Profiles {
            directory: home.join(FOLDER),
            host,
            clock,
        }
    }

    fn now(&self) -> f64 {
        (self.clock)()
    }

    /// `locked(seconds)`: the saved accounts held for one switch, put-back, save or delete.
    pub fn locked<T>(&self, seconds: f64, body: impl FnOnce() -> Result<T>) -> Result<T> {
        let held = self
            .host
            .lock(&self.directory, seconds)
            .map_err(|_| ProfileError {
                class: "Locked",
                message: "the saved accounts are held".into(),
            })?;
        let outcome = body();
        drop(held);
        outcome
    }

    // ------------------------------------------------------------------ sealed files
    fn write(&self, name: &str, value: &Value) -> Result<()> {
        accounts::own_folder(self.host.as_ref(), &self.directory).map_err(auth_error)?;
        let text = car_machine::json::to_string(value, &Options::new().sort_keys(true)).map_err(
            |error| ProfileError {
                class: "ValueError",
                message: error.to_string(),
            },
        )?;
        let sealed = self
            .host
            .seal(text.as_bytes())
            .map_err(|failure| ProfileError {
                class: "OSError",
                message: failure.0,
            })?;
        accounts::write_atomic(self.host.as_ref(), &self.directory.join(name), &sealed).map_err(
            |failure| ProfileError {
                class: "OSError",
                message: failure.0,
            },
        )
    }

    fn read(&self, name: &str) -> Result<Option<Map>> {
        if !accounts::confined(&self.directory) {
            return Err(ProfileError::new("the saved accounts folder is a link"));
        }
        let blob = match std::fs::read(self.directory.join(name)) {
            Ok(blob) => blob,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(ProfileError::new("a profile cannot be read")),
        };
        let opened = self
            .host
            .open(&blob)
            .map_err(|_| ProfileError::new("a profile cannot be opened"))?;
        let text = std::str::from_utf8(&opened)
            .map_err(|_| ProfileError::new("a profile cannot be opened"))?;
        match car_machine::json::from_str(text) {
            Ok(Value::Object(map)) => Ok(Some(map)),
            _ => Err(ProfileError::new("a profile cannot be opened")),
        }
    }

    fn remove(&self, name: &str) -> bool {
        if !accounts::confined(&self.directory) {
            return false;
        }
        std::fs::remove_file(self.directory.join(name)).is_ok()
    }

    // ------------------------------------------------------------------ profiles
    /// `ids()`: the profiles' ids, sorted by file name.
    pub fn ids(&self) -> Vec<String> {
        if !accounts::confined(&self.directory) {
            return Vec::new();
        }
        let Ok(entries) = std::fs::read_dir(&self.directory) else {
            return Vec::new();
        };
        let mut names: Vec<String> = entries
            .filter_map(|entry| entry.ok())
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
            .into_iter()
            .filter_map(|name| {
                let id = name.strip_suffix(SUFFIX)?;
                is_id(id).then(|| id.to_string())
            })
            .collect()
    }

    /// `get(profile_id)`: a profile whole, its `auth` the sign-in file's bytes (as a list of numbers here).
    pub fn get(&self, profile_id: &Value) -> Result<Map> {
        let Some(id) = py::text(profile_id).filter(|id| is_id(id)) else {
            return Err(ProfileError::new("no such profile"));
        };
        let Some(mut value) = self.read(&format!("{id}{SUFFIX}"))? else {
            return Err(ProfileError::new("no such profile"));
        };
        let auth = value.get("auth").cloned().unwrap_or(string(""));
        let decoded = match &auth {
            Value::Str(text) => text.as_str().and_then(base64_decode),
            _ => {
                return Err(ProfileError {
                    class: "TypeError",
                    message: "argument should be a bytes-like object or ASCII string".into(),
                });
            }
        };
        let Some(decoded) = decoded else {
            return Err(ProfileError::new("a profile cannot be opened"));
        };
        let checked = accounts::check(&decoded)
            .map_err(|_| ProfileError::new("a profile cannot be opened"))?;
        value.insert(Str::new("auth"), bytes_value(&checked));
        value.insert(Str::new("id"), string(id));
        Ok(value)
    }

    /// `find(email)`: the id of the profile saved for `email` (any case), or None.
    pub fn find(&self, email: &Value) -> Option<String> {
        let wanted = py::text(email).map(str::to_lowercase);
        for id in self.ids() {
            let Ok(found) = self.get(&string(&id)) else {
                continue;
            };
            if let (Some(wanted), Some(Value::Str(saved))) = (&wanted, found.get("email"))
                && !wanted.is_empty()
                && saved
                    .as_str()
                    .is_some_and(|saved| saved.to_lowercase() == *wanted)
            {
                return Some(id);
            }
        }
        None
    }

    /// `save(data, email, plan)`: `data` kept as the profile of `email`; its id.
    pub fn save(&self, data: &[u8], email: &Value, plan: &Value) -> Result<String> {
        accounts::check(data).map_err(auth_error)?;
        if !py::text(email).is_some_and(|email| email.contains('@')) {
            return Err(ProfileError::new("an account is saved by its address"));
        }
        let (id, kept) = match self.find(email) {
            None => {
                if self.ids().len() >= MOST {
                    return Err(ProfileError::new("too many profiles"));
                }
                (self.host.token(8), Map::new())
            }
            Some(id) => {
                let kept = self.get(&string(&id))?;
                (id, kept)
            }
        };
        let field = |name: &str| kept.get(name).cloned().unwrap_or(Value::Null);
        let mut record = Map::new();
        record.insert(Str::new("auth"), string(&base64_encode(data)));
        record.insert(Str::new("email"), email.clone());
        record.insert(Str::new("plan"), plan.clone());
        record.insert(Str::new("saved_at"), int(self.now().trunc() as i64));
        record.insert(Str::new("used_at"), field("used_at"));
        record.insert(Str::new("exhausted_until"), Value::Null);
        record.insert(Str::new("failed_at"), Value::Null);
        record.insert(Str::new("usage"), field("usage"));
        record.insert(Str::new("unread_at"), field("unread_at"));
        record.insert(Str::new("seen_at"), field("seen_at"));
        self.write(&format!("{id}{SUFFIX}"), &Value::Object(record))?;
        Ok(id)
    }

    /// `update(profile_id, **fields)`: a profile's times, last usage reading, plan or sign-in file changed.
    pub fn update(&self, profile_id: &Value, fields: &[(String, Value)]) -> Result<()> {
        let mut found = self.get(profile_id)?;
        for (key, value) in fields {
            if !FIELDS.contains(&key.as_str()) {
                return Err(ProfileError::new("not a profile's field"));
            }
            found.insert(Str::new(key), value.clone());
        }
        let auth = value_bytes(found.get("auth").unwrap_or(&Value::Null))
            .ok_or_else(|| auth_error(Failure("not a sign-in file's size".into())))?;
        let auth = accounts::check(&auth).map_err(auth_error)?;
        found.insert(Str::new("auth"), string(&base64_encode(&auth)));
        found.shift_remove("id");
        self.write(
            &format!("{}{SUFFIX}", py::text(profile_id).unwrap_or_default()),
            &Value::Object(found),
        )
    }

    /// `delete(profile_id)`.
    pub fn delete(&self, profile_id: &Value) -> bool {
        match py::text(profile_id).filter(|id| is_id(id)) {
            Some(id) => self.remove(&format!("{id}{SUFFIX}")),
            None => false,
        }
    }

    /// `delete_all(codex_home=None)`: every saved account taken away, with the intent, the last switch's stamp and
    /// whatever plain sign-in file a kill left; how many accounts went. PutBackWaits where a put-back waits.
    pub fn delete_all(&self, codex_home: Option<&Path>) -> Result<i64> {
        if !self.host.unwind(&self.intent(), codex_home) {
            return Err(ProfileError {
                class: "PutBackWaits",
                message: "a put-back waits".into(),
            });
        }
        let gone = self
            .ids()
            .iter()
            .filter(|id| self.delete(&string(id)))
            .count() as i64;
        self.remove(INTENT);
        self.remove(LAST);
        self.host.sweep(&self.directory, codex_home);
        Ok(gone)
    }

    /// `state(found, now=None)`.
    pub fn state(&self, found: &Map, now: Option<f64>) -> &'static str {
        let now = now.unwrap_or_else(|| self.now());
        if found
            .get("failed_at")
            .is_some_and(crate::state::sql::truthy)
        {
            return NEEDS_SIGN_IN;
        }
        match found.get("exhausted_until") {
            Some(until @ (Value::Int(_) | Value::Float(_)))
                if py::as_f64(until).is_some_and(|until| until > now) =>
            {
                EXHAUSTED
            }
            _ => READY,
        }
    }

    /// `view()`: what a person may see of each profile.
    pub fn view(&self) -> Vec<Row> {
        let mut shown = Vec::new();
        for id in self.ids() {
            let mut entry = Row::new();
            entry.insert(Str::new("id"), string(&id));
            match self.get(&string(&id)) {
                Err(_) => {
                    entry.insert(Str::new("mask"), Value::Null);
                    entry.insert(Str::new("plan"), Value::Null);
                    entry.insert(Str::new("state"), string(DAMAGED));
                    entry.insert(Str::new("usage"), Value::Null);
                    entry.insert(Str::new("unread"), Value::Bool(false));
                    entry.insert(Str::new("seen_at"), Value::Null);
                    entry.insert(Str::new("used_at"), Value::Null);
                }
                Ok(found) => {
                    let field = |name: &str| found.get(name).cloned().unwrap_or(Value::Null);
                    let usage = reading(&field("usage"));
                    let unread = match field("unread_at") {
                        Value::Int(at) => match &usage {
                            Value::Object(usage) => car_machine::pyval::less_or_equal(
                                &usage["read_at"],
                                &Value::Int(at),
                            )
                            .unwrap_or(false),
                            _ => true,
                        },
                        _ => false,
                    };
                    entry.insert(
                        Str::new("mask"),
                        accounts::mask(&field("email")).map_or(Value::Null, |m| string(&m)),
                    );
                    entry.insert(Str::new("plan"), field("plan"));
                    entry.insert(Str::new("state"), string(self.state(&found, None)));
                    entry.insert(Str::new("usage"), usage);
                    entry.insert(Str::new("unread"), Value::Bool(unread));
                    entry.insert(Str::new("seen_at"), whole(&field("seen_at")));
                    entry.insert(Str::new("used_at"), whole(&field("used_at")));
                }
            }
            shown.push(entry);
        }
        shown
    }

    /// `read_now_at()`: when the card's Read usage last began, or None.
    pub fn read_now_at(&self) -> Value {
        match self.read(READS) {
            Ok(Some(found)) => whole(found.get("at").unwrap_or(&Value::Null)),
            _ => Value::Null,
        }
    }

    /// `note_read_now(at)`.
    pub fn note_read_now(&self, at: f64) -> Result<()> {
        let mut value = Map::new();
        value.insert(Str::new("at"), int(at.trunc() as i64));
        self.write(READS, &Value::Object(value))
    }

    // ------------------------------------------------------------------ a switch under way, and the last one
    /// `intent()`: the switch under way, None, or {"damaged": True}.
    pub fn intent(&self) -> Value {
        match self.read(INTENT) {
            Ok(found) => found.map_or(Value::Null, Value::Object),
            Err(_) => {
                let mut damaged = Map::new();
                damaged.insert(Str::new("damaged"), Value::Bool(true));
                Value::Object(damaged)
            }
        }
    }

    /// `begin(source, target, step="swap", tries=0, put_in=None, previous=None, to_email=None)`.
    #[allow(clippy::too_many_arguments)]
    pub fn begin(
        &self,
        source: &Value,
        target: &Value,
        step: &Value,
        tries: &Value,
        put_in: &Value,
        previous: &Value,
        to_email: &Value,
    ) -> Result<()> {
        let mut value = Map::new();
        value.insert(Str::new("from"), source.clone());
        value.insert(Str::new("to"), target.clone());
        value.insert(Str::new("at"), int(self.now().trunc() as i64));
        value.insert(Str::new("step"), step.clone());
        value.insert(Str::new("tries"), tries.clone());
        if !matches!(put_in, Value::Null) {
            let kept = match put_in {
                Value::Str(_) => put_in.clone(),
                other => string(&digest(&value_bytes(other).unwrap_or_default())),
            };
            value.insert(Str::new("put_in"), kept);
        }
        if !matches!(previous, Value::Null) {
            let kept = match previous {
                Value::Str(_) => previous.clone(),
                other => string(&base64_encode(&value_bytes(other).unwrap_or_default())),
            };
            value.insert(Str::new("previous"), kept);
        }
        if py::is_str(to_email) {
            value.insert(Str::new("to_email"), to_email.clone());
        }
        self.write(INTENT, &Value::Object(value))
    }

    /// `end()`.
    pub fn end(&self) {
        self.remove(INTENT);
    }

    /// `last_switch_at()`.
    pub fn last_switch_at(&self) -> Value {
        match self.read(LAST) {
            Ok(Some(found)) => whole(found.get("at").unwrap_or(&Value::Null)),
            _ => Value::Null,
        }
    }

    /// `attempts()`: the times of the last switches, or None where none was ever kept.
    pub fn attempts(&self) -> Result<Value> {
        let Some(found) = self.read(TIMES)? else {
            return Ok(Value::Null);
        };
        let Some(Value::Array(times)) = found.get("times") else {
            return Err(ProfileError::new("the switch times cannot be read"));
        };
        Ok(Value::Array(
            times
                .iter()
                .filter(|each| py::is_int(each))
                .cloned()
                .collect(),
        ))
    }

    /// `note_attempts(times)`.
    pub fn note_attempts(&self, times: &[i64]) -> Result<()> {
        let mut value = Map::new();
        value.insert(
            Str::new("times"),
            Value::Array(times.iter().map(|one| int(*one)).collect()),
        );
        self.write(TIMES, &Value::Object(value))
    }

    /// `mark_switched(email)`.
    pub fn mark_switched(&self, email: &str) -> Result<()> {
        let mut value = Map::new();
        value.insert(Str::new("email"), string(&email.to_lowercase()));
        value.insert(Str::new("at"), int(self.now().trunc() as i64));
        self.write(LAST, &Value::Object(value))
    }

    /// `switched_to(identity, after)`.
    pub fn switched_to(&self, identity: &Value, after: &Value) -> bool {
        let Ok(Some(last)) = self.read(LAST) else {
            return false;
        };
        let Some(identity) = py::text(identity) else {
            return false;
        };
        let (Some(Value::Str(email)), Some(at @ Value::Int(_))) =
            (last.get("email"), last.get("at"))
        else {
            return false;
        };
        email.as_str() == Some(identity.to_lowercase().as_str())
            && py::is_number(after)
            && car_machine::pyval::less_or_equal(after, at).unwrap_or(false)
    }
}

/// Bytes as the diffs carry them: a list of numbers.
pub fn bytes_value(data: &[u8]) -> Value {
    Value::Array(data.iter().map(|byte| int(i64::from(*byte))).collect())
}

/// A list of numbers back to bytes.
pub fn value_bytes(value: &Value) -> Option<Vec<u8>> {
    match value {
        Value::Array(items) => items
            .iter()
            .map(|item| py::small(item).and_then(|byte| u8::try_from(byte).ok()))
            .collect(),
        _ => None,
    }
}

const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// `base64.b64encode(data).decode("ascii")`.
pub fn base64_encode(data: &[u8]) -> String {
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let bytes = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let number = (u32::from(bytes[0]) << 16) | (u32::from(bytes[1]) << 8) | u32::from(bytes[2]);
        for index in 0..4 {
            if index <= chunk.len() {
                out.push(char::from(
                    ALPHABET[((number >> (18 - 6 * index)) & 63) as usize],
                ));
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// `base64.b64decode(text, validate=True)`: only the alphabet, then at most two `=`; None where Python raises.
pub fn base64_decode(text: &str) -> Option<Vec<u8>> {
    let data = text.trim_end_matches('=');
    let padding = text.len() - data.len();
    if padding > 2 || !data.bytes().all(|byte| ALPHABET.contains(&byte)) {
        return None;
    }
    let values: Vec<u32> = data
        .bytes()
        .map(|byte| ALPHABET.iter().position(|each| *each == byte).unwrap_or(0) as u32)
        .collect();
    match values.len() % 4 {
        1 => return None,
        2 if padding < 2 => return None,
        3 if padding < 1 => return None,
        _ => {}
    }
    let mut out = Vec::new();
    for chunk in values.chunks(4) {
        let mut number = 0u32;
        for (index, value) in chunk.iter().enumerate() {
            number |= value << (18 - 6 * index);
        }
        out.push((number >> 16) as u8);
        if chunk.len() > 2 {
            out.push((number >> 8) as u8);
        }
        if chunk.len() > 3 {
            out.push(number as u8);
        }
    }
    Some(out)
}
