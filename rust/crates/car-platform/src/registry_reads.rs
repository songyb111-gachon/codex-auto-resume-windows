//! The registry values the product only reads: the administrator's policy keys (`win/policykeys.py`), the account's own
//! `CODEX_HOME` (`win/userenv.py`) and Windows' text size (`win/textsize.py`). Each asks a [`Registry`], so a test
//! stands in for the machine's.

use crate::paths::wide;
use crate::registry::{
    KEY_READ, KEY_WOW64_64KEY, Open, RegError, Registry, Root, TYPE_DWORD, TYPE_EXPAND_SZ, TYPE_SZ,
    Typed, Value,
};

// ------------------------------------------------------------------------------------------------ policy keys

pub const POLICY_KEY: &str = "Software\\Policies\\CodexAutoResume";
pub const POLICY_NAMES: [&str; 7] = [
    "DisableAutoResume",
    "ForceObserveOnly",
    "DisableUpdateCheck",
    "DisableStatusFile",
    "MaxRecoveryAttempts",
    "QuietHours",
    "DisablePowerAction",
];

/// A value that is there and could not be read, as `(data, type)` is handed to `managed.parse`: no registry type is
/// negative.
pub const UNREADABLE_KIND: i64 = -1;

/// What a policy value is when it is read: its data and type, or "there and unreadable".
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PolicyValue {
    Data(Typed),
    Unreadable,
}

/// `[HKEY_LOCAL_MACHINE's, HKEY_CURRENT_USER's]`: each the values that are there, in the order of `POLICY_NAMES`;
/// `Unreadable` for each one that is there and could not be read, or for all seven where the place is there and
/// could not be opened. Only "not there" is an empty answer. Never fails.
pub fn read_policies(registry: &dyn Registry) -> Vec<Vec<(String, PolicyValue)>> {
    let access = KEY_READ | KEY_WOW64_64KEY;
    let mut places = Vec::new();
    for root in [Root::LocalMachine, Root::CurrentUser] {
        let mut found: Vec<(String, PolicyValue)> = Vec::new();
        match Open::read(registry, root, POLICY_KEY, access) {
            Ok(key) => {
                for name in POLICY_NAMES {
                    match key.query(name) {
                        Ok(typed) => found.push((name.to_string(), PolicyValue::Data(typed))),
                        Err(RegError::NotFound) => {}
                        Err(RegError::Other(_)) => {
                            found.push((name.to_string(), PolicyValue::Unreadable))
                        }
                    }
                }
            }
            Err(RegError::NotFound) => {}
            Err(RegError::Other(_)) => {
                found = POLICY_NAMES
                    .iter()
                    .map(|name| (name.to_string(), PolicyValue::Unreadable))
                    .collect();
            }
        }
        places.push(found);
    }
    places
}

/// `policykeys.read()` as `managed.parse` takes it: one object per place, each value's name to `[data, type]` -
/// text as text, a REG_DWORD or REG_QWORD as its number, any other data (bytes, a list of texts) as null, which
/// `parse` passes over as it passes over every type but those three - and `[null, -1]` for one that is there and
/// could not be read (UNREADABLE). The product's one conversion: the engine's policy read and the harness both call it.
pub fn policy_places(registry: &dyn Registry) -> Vec<car_machine::json::Value> {
    use car_machine::json::{Map, Str, Value as Json};
    read_policies(registry)
        .into_iter()
        .map(|place| {
            let mut entries = Map::new();
            for (name, found) in place {
                let pair = match found {
                    PolicyValue::Data((Value::Str(data), kind)) => {
                        vec![Json::from(data), Json::from(kind)]
                    }
                    PolicyValue::Data((Value::Qword(data), kind)) => {
                        vec![Json::from(data), Json::from(kind)]
                    }
                    PolicyValue::Data((Value::Int(data), kind)) => {
                        vec![Json::from(data), Json::from(kind)]
                    }
                    PolicyValue::Data((Value::Bytes(_), kind)) => vec![Json::Null, Json::from(kind)],
                    PolicyValue::Unreadable => vec![Json::Null, Json::from(UNREADABLE_KIND)],
                };
                entries.insert(Str::from(name.as_str()), Json::Array(pair));
            }
            Json::Object(entries)
        })
        .collect()
}

// ------------------------------------------------------------------------------------------------ CODEX_HOME

pub const ENVIRONMENT_KEY: &str = "Environment";
pub const CODEX_HOME_NAME: &str = "CODEX_HOME";

/// ExpandEnvironmentStrings, as Windows expands for a new program.
pub fn expand_environment(text: &str) -> String {
    use windows::Win32::System::Environment::ExpandEnvironmentStringsW;
    use windows::core::PCWSTR;
    let source = wide(text);
    // SAFETY: `source` is NUL-terminated and outlives the calls.
    let needed = unsafe { ExpandEnvironmentStringsW(PCWSTR(source.as_ptr()), None) } as usize;
    if needed == 0 {
        return text.to_string();
    }
    let mut buffer = vec![0u16; needed];
    // SAFETY: the buffer is as long as Windows said.
    let written =
        unsafe { ExpandEnvironmentStringsW(PCWSTR(source.as_ptr()), Some(&mut buffer)) } as usize;
    if written == 0 {
        return text.to_string();
    }
    crate::paths::from_wide(&buffer)
}

/// The account's CODEX_HOME as Windows holds it, expanded - or None. Never fails.
pub fn codex_home(registry: &dyn Registry) -> Option<String> {
    let key = Open::read(registry, Root::CurrentUser, ENVIRONMENT_KEY, KEY_READ).ok()?;
    let (value, kind) = key.query(CODEX_HOME_NAME).ok()?;
    let Value::Str(text) = value else { return None };
    let text = match kind {
        TYPE_EXPAND_SZ => expand_environment(&text),
        TYPE_SZ => text,
        _ => return None,
    };
    let trimmed = text.trim();
    (!trimmed.is_empty()).then(|| trimmed.to_string())
}

// ------------------------------------------------------------------------------------------------ text size

pub const TEXT_SIZE_KEY: &str = "Software\\Microsoft\\Accessibility";
pub const TEXT_SIZE_VALUE: &str = "TextScaleFactor";

/// A TextScaleFactor percentage as a factor: 100 to 225 as itself, anything else as 1.
pub fn text_factor(percent: Option<i64>) -> f64 {
    match percent {
        Some(percent) if (100..=225).contains(&percent) => percent as f64 / 100.0,
        _ => 1.0,
    }
}

/// Windows' text size now, as a factor from 1 to 2.25; 1 when Windows cannot be asked.
pub fn text_size(registry: &dyn Registry) -> f64 {
    let Ok(key) = Open::read(registry, Root::CurrentUser, TEXT_SIZE_KEY, KEY_READ) else {
        return 1.0;
    };
    match key.query(TEXT_SIZE_VALUE) {
        Ok((Value::Int(percent), kind)) if kind == TYPE_DWORD => {
            text_factor(Some(i64::from(percent)))
        }
        _ => 1.0,
    }
}

/// `textsize.fitting`: the text size a surface draws at - `text`, but no larger than lets what it `needs` at the
/// usual size, `(width, height)`, grow into the `room` it has - and never below 1.
pub fn fitting(text: f64, needs: (f64, f64), room: (f64, f64)) -> f64 {
    let mut size = if text > 1.0 { text } else { 1.0 };
    for (need, has) in [(needs.0, room.0), (needs.1, room.1)] {
        if need > 0.0 && has > 0.0 {
            size = size.min(has / need);
        }
    }
    size.max(1.0)
}
