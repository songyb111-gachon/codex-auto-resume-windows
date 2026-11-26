//! `control/layer.py`, `control/state.py` and `control/policy.py`: the control layer itself, bound to one runtime
//! home; the one door to the state; the settings as this layer offers them.
//!
//! `Control` is cheap to construct and opens the store per call. Everything outside the process - the clock,
//! Windows, the policy keys, the Codex home - comes in through [`Host`](crate::host::Host), and the edition's plug
//! is the one the binary was built with (`Guarded::null()` in the standard edition). The plug is shared: the reference
//! hands every part of one process the same plug object (`edition.plug(paths)`, "the same object every time after"), so
//! a `Control` holds an `Arc` of the one the watcher, its icon and its cards hold, and sees what that plug keeps.

use std::path::PathBuf;
use std::sync::Arc;

use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_policy::plug::Guarded;
use car_policy::settings::managed::{self, Managed};
use car_policy::settings::{self, SettingsError, homes, notice_kinds, schema};
use car_store::LegacyStore;
use car_store::Store;
use car_store::errors::{Error as StoreError, Kind};
use car_store::open::{OpenState, Opened, UPGRADE_PENDING, open_state};

use crate::error::{ControlError, Failure, Res, refuse};
use crate::host::Host;

/// `NEWER_STATE`.
pub const NEWER_STATE: &str = "The recovery state was written by a newer version of Codex Auto Resume. Update this installation; do not delete the state.";

/// The class `upgrade_failed` hands back through `open_state`: a failed upgrade is the state being unavailable,
/// whatever the store called it.
const UPGRADE_FAILED: &str = "UpgradeFailed";

/// `Control(home, plug=...)`.
pub struct Control {
    pub paths: Paths,
    pub host: Arc<dyn Host>,
    plug: Arc<Guarded>,
    /// `_seen`: the failure-seen file's identity as last read, and what it said (`control/seen.py`).
    pub(crate) seen: std::cell::RefCell<Option<crate::seen::Remembered>>,
}

/// What a state open gives, and the legacy marker the callers branch on.
pub enum State {
    Current(Store),
    Legacy(LegacyStore),
}

impl Control {
    pub fn new(paths: Paths, host: Arc<dyn Host>, plug: Arc<Guarded>) -> Control {
        Control {
            paths,
            host,
            plug,
            seen: std::cell::RefCell::new(None),
        }
    }

    /// The edition's plug as core holds one.
    pub fn plug(&self) -> &Guarded {
        &self.plug
    }

    pub fn state_dir(&self) -> PathBuf {
        PathBuf::from(&self.paths.state_dir)
    }

    // ------------------------------------------------------------------------------------------ state.py
    /// `_open(legacy_ok=...)`: the state as every per-call opener opens it; a store that will not open becomes a
    /// refusal a front end can show.
    pub fn open(&self, legacy_ok: bool) -> Res<State> {
        let host = Arc::clone(&self.host);
        let superseded = move || host.superseded();
        let upgrade_failed =
            |error: StoreError| StoreError::Python(UPGRADE_FAILED, error.message());
        let options = OpenState {
            legacy: "if_reducing",
            reducing: legacy_ok,
            check: false,
            upgrade_failed: Some(&upgrade_failed),
            hold_while_installing: true,
            superseded: Some(&superseded),
            clock: self.host.store_clock(),
        };
        match open_state(&self.state_dir(), &*self.host, &options) {
            Ok(Opened::Store(store)) => Ok(State::Current(store)),
            Ok(Opened::Legacy(store)) => Ok(State::Legacy(store)),
            Err(error) => Err(unopened(error)),
        }
    }

    /// `_open()` for what only a current store answers: an older watcher's store is the pending upgrade.
    pub fn open_current(&self) -> Res<Store> {
        match self.open(false)? {
            State::Current(store) => Ok(store),
            State::Legacy(_) => refuse(UPGRADE_PENDING, "upgrade_pending"),
        }
    }

    // ------------------------------------------------------------------------------------------ policy.py
    pub fn settings_path(&self) -> PathBuf {
        PathBuf::from(&self.paths.settings_file)
    }

    /// `managed()`: the policy keys in force now.
    pub fn managed(&self) -> Managed {
        self.host.managed()
    }

    /// `get_settings()`: the stored settings as an administrator's policy keys leave them.
    pub fn get_settings(&self) -> Res<Map> {
        let os = self.host.os();
        let loaded = settings::load(&*os, &self.settings_path()).map_err(other)?;
        Ok(managed::clamp(&loaded, &self.managed()))
    }

    /// `stored_settings()`: the stored settings an edit builds a whole list or table on, as a save keeps them.
    pub fn stored_settings(&self) -> Res<Map> {
        let os = self.host.os();
        match settings::kept(&*os, &self.settings_path()) {
            Ok(kept) => Ok(managed::clamp(&kept, &self.managed())),
            Err(error) if error.is_settings_error() => refuse(error.message(), "request_failed"),
            Err(error) => Err(other(error)),
        }
    }

    /// `update_settings(changes)`.
    pub fn update_settings(&self, changes: &Value) -> Res<Map> {
        let held = self.managed();
        let os = self.host.os();
        let path = self.settings_path();
        let mut changes = changes.clone();
        let refused = |error: SettingsError| -> Failure {
            if error.is_settings_error() {
                Failure::Control(ControlError::new(error.message(), "request_failed"))
            } else {
                other(error)
            }
        };
        if held.active() {
            // Checked as ever first, so a wrong value is refused in the validator's own words; then a setting a
            // key decides keeps what the key says (managed.admit).
            settings::validate_update(&*os, &changes).map_err(refused)?;
            let effective = managed::clamp(&settings::kept(&*os, &path).map_err(refused)?, &held);
            if let Value::Object(asked) = &changes {
                let (kept, refusal) = managed::admit(asked, &effective, &held);
                if let Some(name) = refusal {
                    let mut text = name.as_bytes().to_vec();
                    text.extend_from_slice(b" is set by your administrator");
                    return refuse(
                        Str::from_surrogatepass(text).unwrap_or_default(),
                        "managed_by_policy",
                    );
                }
                changes = Value::Object(kept);
            }
        }
        self.strict_homes(&changes).map_err(refused)?;
        let changes = self.keep_unlisted_kinds(changes).map_err(refused)?;
        let saved = settings::update(&*os, &path, &changes).map_err(refused)?;
        let saved = managed::clamp(&saved, &held);
        let named = matches!(&changes, Value::Object(map) if map.contains_key("observe_only"));
        if named || held.force_observe_only {
            self.observe_only(&saved)?;
        }
        Ok(saved)
    }

    /// `check_setting(name, value)`: whether one setting would take `value`, and as what.
    pub fn check_setting(&self, name: &Value, value: &Value) -> Res<Value> {
        let Value::Str(text) = name else {
            return refuse("name a setting", "request_failed");
        };
        let mut changes = Map::new();
        changes.insert(text.clone(), value.clone());
        let os = self.host.os();
        match settings::validate_update(&*os, &Value::Object(changes)) {
            Ok(clean) => {
                let mut reply = Map::new();
                reply.insert(Str::from("name"), name.clone());
                reply.insert(
                    Str::from("value"),
                    clean.get(text).cloned().unwrap_or(Value::Null),
                );
                Ok(Value::Object(reply))
            }
            Err(error) if error.is_settings_error() => refuse(error.message(), "request_failed"),
            Err(error) => Err(other(error)),
        }
    }

    /// `_strict_homes(changes)`: the Codex homes as written, checked against the folders on this PC.
    fn strict_homes(&self, changes: &Value) -> Result<(), SettingsError> {
        let Value::Object(map) = changes else {
            return Ok(());
        };
        let Some(written) = map.get(homes::FIELD) else {
            return Ok(());
        };
        let os = self.host.os();
        let default_home = Str::from(self.host.codex_home());
        let identity = |path: &Str| -> Option<Value> {
            let text = path.as_str()?;
            car_platform::homelock::folder_identity(std::path::Path::new(text)).map(Value::from)
        };
        homes::strict(&*os, written, Some(&default_home), &identity).map_err(SettingsError::Refused)
    }

    /// `_keep_unlisted_kinds(changes)`: the kinds of notice that stay on screen as written, with every stored id
    /// this process lists no kind for kept after them.
    fn keep_unlisted_kinds(&self, changes: Value) -> Result<Value, SettingsError> {
        let Value::Object(map) = &changes else {
            return Ok(changes);
        };
        let Some(Value::Array(written)) = map.get(notice_kinds::FIELD) else {
            return Ok(changes);
        };
        let listed: Vec<String> = notice_kinds::ids();
        let os = self.host.os();
        let kept_file = settings::kept(&*os, &self.settings_path())?;
        let stored = notice_kinds::coerce(
            kept_file.get(notice_kinds::FIELD).unwrap_or(&Value::Null),
            &Value::Array(Vec::new()),
        );
        let Value::Array(stored) = stored else {
            return Ok(changes);
        };
        let kept: Vec<Value> = stored
            .into_iter()
            .filter(|kind| match kind {
                Value::Str(text) => {
                    let name = text.as_str().unwrap_or_default();
                    !listed.iter().any(|each| each == name)
                        && !written.iter().any(|item| pyval::eq(item, kind))
                }
                _ => false,
            })
            .collect();
        if kept.is_empty() {
            return Ok(changes);
        }
        let mut merged = map.clone();
        let mut all = written.clone();
        all.extend(kept);
        merged.insert(Str::from(notice_kinds::FIELD), Value::Array(all));
        Ok(Value::Object(merged))
    }

    /// `_observe_only(values)`: Observe only written into the state as the settings now say it, where the claim
    /// itself refuses every send while it is on. A state that cannot take it now is left to the watcher.
    ///
    /// `except (ControlError, StoreError): pass` and nothing more: any other exception leaves the save as the
    /// generic refusal, after the settings were written.
    fn observe_only(&self, values: &Map) -> Res<()> {
        let on = values.get("observe_only").is_some_and(pyval::truthy);
        match self.open(false) {
            Ok(State::Current(store)) => match store.set_observe_only(on) {
                Ok(_) | Err(StoreError::Store(..)) => Ok(()),
                Err(error) => Err(from_store(error)),
            },
            Ok(State::Legacy(_)) | Err(Failure::Control(_)) => Ok(()),
            Err(other) => Err(other),
        }
    }

    /// `describe_settings()`: the schema, with `"managed": true` on each setting a policy key decides while one
    /// does, and on one the key holds only under a ceiling, `"ceiling"`.
    pub fn describe_settings(&self) -> Vec<Value> {
        let host = Arc::clone(&self.host);
        let current = move || self.language_of(&*host).to_owned();
        let described = schema::describe(&current);
        let held = self.managed();
        let decided = managed::fields(&held);
        let ceilings = managed::ceilings(&held);
        if decided.is_empty() {
            return described;
        }
        described
            .into_iter()
            .map(|entry| {
                let Value::Object(mut map) = entry else {
                    return entry;
                };
                let name = map
                    .get("name")
                    .and_then(|value| match value {
                        Value::Str(text) => text.as_str().map(str::to_owned),
                        _ => None,
                    })
                    .unwrap_or_default();
                if decided.contains(&name.as_str()) {
                    map.insert(Str::from("managed"), Value::Bool(true));
                    if let Some(ceiling) = ceilings.get(name.as_str()) {
                        map.insert(Str::from("ceiling"), ceiling.clone());
                    }
                }
                Value::Object(map)
            })
            .collect()
    }

    /// `l10n.current()` for this process.
    pub fn language_of(&self, host: &dyn Host) -> &'static str {
        let environ = |name: &str| host.environ(name);
        let windows = || host.windows_languages();
        car_words::l10n::current(&environ, &windows)
    }

    /// `restore_defaults()`.
    pub fn restore_defaults(&self) -> Res<Map> {
        let os = self.host.os();
        let path = self.settings_path();
        let refused = |error: SettingsError| -> Failure {
            if error.is_settings_error() {
                Failure::Control(ControlError::new(error.message(), "request_failed"))
            } else {
                other(error)
            }
        };
        // The Codex homes are where to watch, not a preference: Restore defaults keeps them.
        let kept = match settings::kept(&*os, &path) {
            Ok(found) => {
                let mut keep = Map::new();
                keep.insert(
                    Str::from(homes::FIELD),
                    found.get(homes::FIELD).cloned().unwrap_or(Value::Null),
                );
                keep
            }
            Err(SettingsError::Unreadable {
                transient: true,
                reason,
            }) => {
                return Err(refused(SettingsError::Unreadable {
                    reason,
                    transient: true,
                }));
            }
            Err(SettingsError::Unreadable { .. }) => {
                // A file it cannot read at all is the one way out of a save it refuses: kept beside it first.
                crate::aside::set_aside(&*self.host, &*os, &path, self.host.now())
                    .map_err(refused)?;
                Map::new()
            }
            Err(error) => return Err(other(error)),
        };
        let mut values = settings::defaults();
        for (name, value) in kept {
            values.insert(name, value);
        }
        let saved = settings::save(&*os, &path, &Value::Object(values)).map_err(refused)?;
        let saved = managed::clamp(&saved, &self.managed());
        self.observe_only(&saved)?;
        Ok(saved)
    }
}

/// Any other exception of a settings call: the bridge answers it generically.
pub(crate) fn other(error: SettingsError) -> Failure {
    Failure::Other(error.class().to_owned())
}

/// `_open`'s mapping of what the store refused.
pub(crate) fn unopened(error: StoreError) -> Failure {
    match &error {
        StoreError::Store(Kind::UpgradePending, _) => {
            Failure::Control(ControlError::new(UPGRADE_PENDING, "upgrade_pending"))
        }
        StoreError::Store(Kind::StateFromNewerVersion, _) => {
            Failure::Control(ControlError::new(NEWER_STATE, "newer_state"))
        }
        StoreError::Store(..) | StoreError::Python(UPGRADE_FAILED, _) => unavailable(&error),
        StoreError::Python(class, _) => Failure::Other((*class).to_owned()),
        StoreError::Sqlite(_) => Failure::Other("OperationalError".to_owned()),
    }
}

/// `_unavailable(exc)`.
pub(crate) fn unavailable(error: &StoreError) -> Failure {
    Failure::Control(ControlError::new(
        format!("local state is unavailable: {}", error.message()),
        "store_unavailable",
    ))
}

/// A store's own error met inside a call, as Python meets it: a `StoreError` is the state being unavailable to
/// the layer that caught it, any other exception leaves the call by class.
pub(crate) fn from_store(error: StoreError) -> Failure {
    match error {
        StoreError::Python(class, _) => Failure::Other(class.to_owned()),
        StoreError::Sqlite(_) => Failure::Other("OperationalError".to_owned()),
        store => Failure::Other(store.class().to_owned()),
    }
}

/// `settings.CONVERSATION_MESSAGES`: one conversation's own continuation messages, by thread.
pub const CONVERSATION_MESSAGES: &str = car_policy::classify::continuation::BY_THREAD_FIELD;
/// `settings.MAX_CONVERSATION_MESSAGES` (`continuation.MAX_CONVERSATIONS`).
pub const MAX_CONVERSATION_MESSAGES: usize = 50;

impl Control {
    /// `validated_text(text)`: `text` as a Custom message is stored, or the refusal the settings validator words.
    pub fn validated_text(&self, text: &Value) -> Res<()> {
        let mut changes = Map::new();
        changes.insert(Str::from("custom_message"), text.clone());
        let os = self.host.os();
        match settings::validate_update(&*os, &Value::Object(changes)) {
            Ok(_) => Ok(()),
            Err(error) if error.is_settings_error() => refuse(error.message(), "request_failed"),
            Err(error) => Err(other(error)),
        }
    }

    /// `set_conversation_message(thread_id, text)`: one conversation's own continuation message (v0.6.11): `text`
    /// for it, or None - or text of nothing but spaces - to take it away.
    pub fn set_conversation_message(&self, thread: &Value, text: &Value) -> Res<Value> {
        let thread = crate::error::thread_id(thread)?;
        let mut held: Map = match self.stored_settings()?.get(CONVERSATION_MESSAGES) {
            Some(Value::Object(map)) => map.clone(),
            _ => Map::new(),
        };
        let blank = match text {
            Value::Null => true,
            Value::Str(each) => match each.as_str() {
                Some(plain) => car_machine::pytext::strip(plain).is_empty(),
                None => false,
            },
            _ => false,
        };
        if blank {
            held.shift_remove(thread.as_str());
        } else {
            self.validated_text(text)?;
            held.insert(Str::from(thread.as_str()), text.clone());
            if held.len() > MAX_CONVERSATION_MESSAGES {
                return refuse(
                    format!(
                        "at most {MAX_CONVERSATION_MESSAGES} conversations can have a message of their own"
                    ),
                    "too_many_messages",
                );
            }
        }
        let mut changes = Map::new();
        changes.insert(
            Str::from(CONVERSATION_MESSAGES),
            if held.is_empty() {
                Value::Null
            } else {
                Value::Object(held)
            },
        );
        let saved = self.update_settings(&Value::Object(changes))?;
        let own = match saved.get(CONVERSATION_MESSAGES) {
            Some(Value::Object(map)) => Some(map),
            _ => None,
        };
        let mut reply = Map::new();
        reply.insert(Str::from("thread_id"), Value::from(thread.as_str()));
        reply.insert(
            Str::from("set"),
            Value::Bool(own.is_some_and(|map| map.get(thread.as_str()).is_some())),
        );
        reply.insert(
            Str::from("count"),
            Value::from(own.map_or(0, |map| map.len()) as i64),
        );
        Ok(Value::Object(reply))
    }

    /// `once_words(interruption_id)`: one interruption's words for this time, as they are read and checked again.
    pub fn once_words(&self, id: &Value) -> Res<Value> {
        let key = crate::error::interruption_id(id)?;
        let text = crate::oncewords::OnceWords::of(&self.paths.once_words_file, &*self.host)
            .words(&key)
            .map_err(|class| Failure::Other(class.to_owned()))?;
        let mut reply = Map::new();
        reply.insert(Str::from("interruption_id"), Value::from(key));
        reply.insert(Str::from("set"), Value::Bool(text.is_some()));
        reply.insert(Str::from("text"), text.map_or(Value::Null, Value::Str));
        Ok(Value::Object(reply))
    }
}
