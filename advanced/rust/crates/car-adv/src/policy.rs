//! `policy.py`: what an administrator's policy allows, read from the registry and never written.
//!
//! Three values under `Software\Policies\CodexAutoResume`, in the machine's hive and the user's: `ForbidAdvanced` (DWORD 1:
//! no capability may be on or watched), `ForceShadow` (DWORD 1: a capability may be watched, never on) and
//! `AllowedCapabilities` (REG_MULTI_SZ, or one string split at commas, semicolons and spaces: only these ids may be on or
//! watched). Both hives count, and together they are as strict as the stricter. A value that is there but is not what it
//! should be - another type, a number that is not 0 or 1 - counts as the strictest thing it could have meant, and so does a
//! key that is there but cannot be read: a policy that cannot be understood is never read as no policy.
//!
//! The key is opened for reading only, here and nowhere else in this edition. The reader is a function a caller hands in;
//! the default one (`windows_reader`) asks a `car_platform::registry::Registry` for `KEY_READ` and nothing else.

use std::collections::BTreeSet;

use car_machine::pytext::is_space;
use car_platform::registry::{
    KEY_READ, Open, RegError, Registry, Root, TYPE_EXPAND_SZ, TYPE_SZ, Value,
};

pub const KEY: &str = r"Software\Policies\CodexAutoResume";
pub const FORBID: &str = "ForbidAdvanced";
pub const FORCE_SHADOW: &str = "ForceShadow";
pub const ALLOWED: &str = "AllowedCapabilities";
pub const VALUES: [&str; 3] = [FORBID, FORCE_SHADOW, ALLOWED];
pub const HIVES: [&str; 2] = ["HKLM", "HKCU"];
/// REG_MULTI_SZ's type number: the platform's registry hands it back as bytes.
pub const TYPE_MULTI_SZ: u32 = 7;

/// What a reader says a value is: its kind (`DWORD`, `TEXT`, `LIST`, `OTHER`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Dword,
    Text,
    List,
    Other,
}

/// What a value holds, whatever its kind says: a number, text, a list of text, or something else (the tag's reader may
/// hand a kind and a value that disagree, and a test does).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Content {
    Int(i64),
    Text(String),
    List(Vec<String>),
    Other,
}

/// `(value, kind)` of one policy value.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Found {
    pub value: Content,
    pub kind: Kind,
}

/// The policy key is there and could not be read (`Unreadable`), or the reader failed in any other way: either way the
/// policy is the strictest.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Unreadable(pub String);

impl std::fmt::Display for Unreadable {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for Unreadable {}

#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Policy {
    pub forbid: bool,
    pub force_shadow: bool,
    /// `None`: no list, every id allowed.
    pub allowed: Option<BTreeSet<String>>,
}

impl Policy {
    /// Whether `capability` may be on or watched at all under this policy.
    pub fn admits(&self, capability: &str) -> bool {
        !self.forbid
            && self
                .allowed
                .as_ref()
                .is_none_or(|allowed| allowed.contains(capability))
    }

    /// `as_json()`: `{"forbid", "force_shadow", "allowed": null | sorted list}`, as the tag orders them.
    pub fn as_json(&self) -> car_machine::json::Value {
        use car_machine::json::{Map, Str, Value};
        let mut map = Map::new();
        map.insert(Str::from("forbid"), Value::Bool(self.forbid));
        map.insert(Str::from("force_shadow"), Value::Bool(self.force_shadow));
        map.insert(
            Str::from("allowed"),
            match &self.allowed {
                None => Value::Null,
                // Python sorts text by code point; a Rust `str` sorts by UTF-8 byte, which is the same order.
                Some(allowed) => {
                    Value::Array(allowed.iter().map(|id| Value::from(id.as_str())).collect())
                }
            },
        );
        Value::Object(map)
    }
}

/// `NONE`.
pub fn none() -> Policy {
    Policy::default()
}

/// `STRICTEST`: forbidden, forced to shadow, and no id allowed.
pub fn strictest() -> Policy {
    Policy {
        forbid: true,
        force_shadow: true,
        allowed: Some(BTreeSet::new()),
    }
}

/// `_switch(found)`: `None` if absent, else whether it is on - anything but a DWORD 0 is on.
fn switch(found: &Option<Found>) -> Option<bool> {
    let found = found.as_ref()?;
    Some(!(found.kind == Kind::Dword && found.value == Content::Int(0)))
}

/// `re.split(r"[,;\s]+", text)` with the empty words dropped, as `_ids` takes them.
fn words(text: &str) -> impl Iterator<Item = String> + '_ {
    text.split(|each: char| each == ',' || each == ';' || is_space(each))
        .filter(|word| !word.is_empty())
        .map(str::to_owned)
}

/// `_ids(found)`: `None` if absent, else the ids it names; a value of the wrong kind names none.
fn ids(found: &Option<Found>) -> Option<BTreeSet<String>> {
    let found = found.as_ref()?;
    Some(match (&found.kind, &found.value) {
        (Kind::List, Content::List(items)) => items.iter().flat_map(|item| words(item)).collect(),
        (Kind::Text, Content::Text(text)) => words(text).collect(),
        _ => BTreeSet::new(),
    })
}

/// The reader a caller hands in: one policy value of one hive (`"HKLM"` or `"HKCU"`), `Ok(None)` where it or its key is
/// not there, an error where the key is there and cannot be read.
pub type Reader<'a> = &'a dyn Fn(&str, &str) -> Result<Option<Found>, Unreadable>;

/// `read(reader)`: the policy in force now. Never fails: a reader that does is the strictest policy.
pub fn read(reader: Reader<'_>) -> Policy {
    let (mut forbid, mut force, mut allowed): (bool, bool, Option<BTreeSet<String>>) =
        (false, false, None);
    for hive in HIVES {
        let mut found = Vec::with_capacity(VALUES.len());
        for name in VALUES {
            match reader(hive, name) {
                Ok(value) => found.push(value),
                Err(_) => return strictest(),
            }
        }
        forbid = forbid || switch(&found[0]).unwrap_or(false);
        force = force || switch(&found[1]).unwrap_or(false);
        if let Some(listed) = ids(&found[2]) {
            allowed = Some(match allowed {
                None => listed,
                Some(held) => held.intersection(&listed).cloned().collect(),
            });
        }
    }
    Policy {
        forbid,
        force_shadow: force,
        allowed,
    }
}

/// REG_MULTI_SZ's bytes as `winreg` splits them: UTF-16 text, a NUL between the strings and a last NUL at the end.
fn multi_sz(bytes: &[u8]) -> Vec<String> {
    let units: Vec<u16> = bytes
        .as_chunks::<2>()
        .0
        .iter()
        .map(|pair| u16::from_le_bytes(*pair))
        .collect();
    let mut listed: Vec<String> = units
        .split(|unit| *unit == 0)
        .map(String::from_utf16_lossy)
        .collect();
    while listed.last().is_some_and(String::is_empty) {
        listed.pop();
    }
    listed
}

/// `windows_reader(hive, name)` over a registry: `(value, kind)` of one policy value, `None` when it or its key is not
/// there, an error when the key is there and cannot be read. Opened with `KEY_READ` and nothing else.
pub fn windows_reader(
    registry: &dyn Registry,
    hive: &str,
    name: &str,
) -> Result<Option<Found>, Unreadable> {
    let root = match hive {
        "HKLM" => Root::LocalMachine,
        _ => Root::CurrentUser,
    };
    let unreadable = || Unreadable("the policy key could not be read".into());
    let key = match Open::read(registry, root, KEY, KEY_READ) {
        Ok(key) => key,
        Err(RegError::NotFound) => return Ok(None),
        Err(RegError::Other(_)) => return Err(unreadable()),
    };
    let (value, kind) = match key.query(name) {
        Ok(typed) => typed,
        Err(RegError::NotFound) => return Ok(None),
        Err(RegError::Other(_)) => return Err(unreadable()),
    };
    Ok(Some(match (value, kind) {
        (Value::Int(number), _) => Found {
            value: Content::Int(i64::from(number)),
            kind: Kind::Dword,
        },
        (Value::Str(text), TYPE_SZ | TYPE_EXPAND_SZ) => Found {
            value: Content::Text(text),
            kind: Kind::Text,
        },
        (Value::Bytes(bytes), TYPE_MULTI_SZ) => Found {
            value: Content::List(multi_sz(&bytes)),
            kind: Kind::List,
        },
        (Value::Qword(number), _) => Found {
            value: Content::Int(i64::try_from(number).unwrap_or(i64::MAX)),
            kind: Kind::Other,
        },
        _ => Found {
            value: Content::Other,
            kind: Kind::Other,
        },
    }))
}
