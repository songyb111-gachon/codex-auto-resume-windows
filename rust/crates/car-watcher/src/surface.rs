//! The host's surfaces seam (S6.2b; P6-DESIGN 1.5, DECISIONS.md "The popup's model at the host boundary" and its
//! addendum): what the reference's icon thread read or asked for itself, and the C# host cannot, computed here and
//! carried in the events.
//!
//! * the catalog's locale and letters (`locale_of(strings)`, `fonts._letters(locale)`), in `surfaces` and `strings`;
//! * the popup's model (car-surface `PopupModel`): read as `perform(("read",), control, source=names)` reads it, its
//!   `view(now)`, each task's row menu and `attention()` - the snapshot's `popup` field
//!   `{view, menus: [[id, row_menu]], read, attention}`;
//! * the three answers the icon asked its control layer (ui/tray/clicks.py `_failure_unseen`, `_unconfirmed_unseen`;
//!   ui/tray/menu.py `_power_armed`), as the snapshot's `failure_unseen`, `unconfirmed_unseen` and `power_armed`;
//! * a popup click (`popup {call, args}`): `(kind, *args)` rebuilt and done as `perform` does it, with the popup's own
//!   pending source, its outcome applied to the model the next snapshot is drawn from.

use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use car_codex::source::LocalSource;
use car_control::{Control, Failure};
use car_machine::json::{Map, Value};
use car_surface::popup::model::{self, Ctx, PopupModel};
use car_surface::seam::{PopupControl, Raised};

/// ui/tray/menu.py `POWER_OFF_WORDS`' keys: the armed actions the icon's menu offers to take back.
pub const POWER_OFF_WORDS: [&str; 3] = ["sleep", "hibernate", "shut_down"];

/// The Interface language's catalog, as the icon is handed it, with what the host cannot derive.
#[derive(Clone, Debug, PartialEq)]
pub struct Catalog {
    /// `interface.catalog()`.
    pub strings: Map,
    /// `l10n.current()`: the language the process speaks (the popup's `Ctx.current`).
    pub language: String,
    /// `locale_of(strings)`.
    pub locale: String,
    /// `fonts._letters(locale)`: every letter that locale's whole catalog draws.
    pub letters: String,
}

/// `interface.catalog()` and its locale and letters. Windows' preferred UI languages are not in car-platform yet
/// (GROUNDWORK, Integration 6): the environment's language is read, as the bridge's host reads it.
pub fn catalog() -> Catalog {
    let environ = |name: &str| std::env::var(name).ok();
    let language = car_words::interface::language(&environ, &Vec::new);
    let table = car_words::l10n::catalog(language);
    let mut strings = Map::new();
    for (key, value) in table.iter() {
        strings.insert(key.as_str().into(), Value::from(value.as_str()));
    }
    let locale = car_surface::popup::words::locale_of(&strings, language).to_owned();
    let letters = letters_of(&locale);
    Catalog {
        strings,
        language: language.to_owned(),
        locale,
        letters,
    }
}

/// `fonts._letters(locale)`: `typeface.letters(l10n.catalog(locale).values())`.
pub fn letters_of(locale: &str) -> String {
    let table = car_words::l10n::catalog(locale);
    let texts: Vec<&str> = table.iter().map(|(_, value)| value.as_str()).collect();
    car_platform::typeface::letters(&texts)
}

/// The popup's names (`App.source()`): Codex's own state, read-only, with the state folder's split chains.
pub fn names(host: &dyn car_control::host::Host, split_chains_file: &str) -> Option<LocalSource> {
    let chains = car_codex::chains::memory(Some(Path::new(split_chains_file)), true);
    LocalSource::new(host.os(), &host.codex_home(), Some(chains)).ok()
}

fn raised(failure: Failure) -> Raised {
    match failure {
        Failure::Control(error) => Raised::coded("ControlError", Value::from(error.code.as_str())),
        Failure::Other(class) => Raised::new(&class),
    }
}

/// car-control's `Control` as the popup calls it: every write with the reference's default actor, `gui`, and the
/// popup's own pending source for `list_pending` and `set_project_rule`.
pub struct ControlPopup<'a> {
    pub control: &'a Control,
    pub source: Option<LocalSource>,
}

impl PopupControl for ControlPopup<'_> {
    fn list_pending(&self, _source: Option<&Value>) -> Result<Value, Raised> {
        self.control
            .list_pending(false, self.source.as_ref())
            .map(Value::Array)
            .map_err(raised)
    }
    fn get_status(&self) -> Result<Value, Raised> {
        self.control.get_status().map_err(raised)
    }
    fn set_enabled(&self, enabled: bool) -> Result<Value, Raised> {
        self.control.set_enabled(enabled).map_err(raised)
    }
    fn set_interruption_recovery(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        enabled: bool,
    ) -> Result<Value, Raised> {
        self.control
            .set_interruption_recovery(interruption_id, thread_id, enabled, "gui")
            .map_err(raised)
    }
    fn postpone(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        preset: &Value,
    ) -> Result<Value, Raised> {
        self.control
            .postpone(
                interruption_id,
                thread_id,
                &Value::Null,
                preset,
                &Value::Null,
                "gui",
            )
            .map_err(raised)
    }
    fn unpostpone(&self, interruption_id: &Value, thread_id: &Value) -> Result<Value, Raised> {
        self.control
            .unpostpone(interruption_id, thread_id, "gui")
            .map_err(raised)
    }
    fn release_hold(&self, interruption_id: &Value, thread_id: &Value) -> Result<Value, Raised> {
        self.control
            .release_hold(interruption_id, thread_id, "gui")
            .map_err(raised)
    }
    fn set_thread_tier(
        &self,
        thread_id: &Value,
        tier: &Value,
        interruption_id: &Value,
    ) -> Result<Value, Raised> {
        self.control
            .set_thread_tier(thread_id, tier, interruption_id, "gui")
            .map_err(raised)
    }
    fn set_project_rule(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        always: bool,
        _source: Option<&Value>,
    ) -> Result<Value, Raised> {
        self.control
            .set_project_rule(
                interruption_id,
                thread_id,
                always,
                self.source.as_ref(),
                "gui",
            )
            .map_err(raised)
    }
    fn set_once_words(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        words: &Value,
    ) -> Result<Value, Raised> {
        self.control
            .set_once_words(interruption_id, thread_id, words)
            .map_err(raised)
    }
}

/// The three answers the icon asked its control layer, written into the snapshot it is sent.
///
/// * `failure_unseen` / `unconfirmed_unseen`: `control.failure_unseen(snapshot["failures"]) is True` where the
///   snapshot has failures, false without them or when the control layer cannot say (`_failure_unseen`);
/// * `power_armed`: the armed power action's word (`power_view()["armed"]["action"]`) where it is one of
///   [`POWER_OFF_WORDS`], else null (`_power_armed`).
pub fn icon_answers(control: &Control, snapshot: &mut Map) {
    let marks = snapshot
        .get("failures")
        .filter(|found| car_machine::pyval::truthy(found))
        .cloned();
    let (failed, unconfirmed) = match &marks {
        Some(Value::Object(marks)) => (
            control.failure_unseen(Some(marks)) == Ok(true),
            control.unconfirmed_unseen(Some(marks)) == Ok(true),
        ),
        _ => (false, false),
    };
    snapshot.insert("failure_unseen".into(), Value::Bool(failed));
    snapshot.insert("unconfirmed_unseen".into(), Value::Bool(unconfirmed));
    snapshot.insert("power_armed".into(), power_armed(control));
}

fn power_armed(control: &Control) -> Value {
    let Ok(Some(Value::Object(view))) = control.power_view() else {
        return Value::Null;
    };
    let Some(Value::Object(armed)) = view.get("armed") else {
        return Value::Null;
    };
    match armed.get("action") {
        Some(Value::Str(word)) => match word.as_str() {
            Some(word) if POWER_OFF_WORDS.contains(&word) => Value::from(word),
            _ => Value::Null,
        },
        _ => Value::Null,
    }
}

/// perform's action kind for one of the ten `CONTROL_CALLS` (the two reads are the popup's `read`).
pub fn kind_of(call: &str) -> Option<&'static str> {
    Some(match call {
        "list_pending" | "get_status" => "read",
        "set_enabled" => "enabled",
        "set_interruption_recovery" => "recovery",
        "postpone" => "postpone",
        "unpostpone" => "unpostpone",
        "release_hold" => "release",
        "set_thread_tier" => "tier",
        "set_project_rule" => "project",
        "set_once_words" => "unsay",
        _ => return None,
    })
}

/// What the popup knows between snapshots: its model, whether its first read is done, the language it speaks, and the
/// last tray snapshot sent (so a snapshot can follow a `strings` event or a click at once).
#[derive(Debug, Default)]
pub struct Shared {
    pub model: PopupModel,
    pub read: bool,
    pub language: String,
    pub snapshot: Option<Map>,
}

/// One watcher's popup, held by App (the tick's snapshot) and the Watcher (a click, a `strings` event).
pub type Popup = Arc<Mutex<Shared>>;

pub fn new_popup() -> Popup {
    Arc::new(Mutex::new(Shared::default()))
}

pub fn held(popup: &Popup) -> MutexGuard<'_, Shared> {
    popup.lock().unwrap_or_else(PoisonError::into_inner)
}

fn outcome(verdict: &str, payload: Value) -> [Value; 2] {
    [Value::from(verdict), payload]
}

impl Shared {
    /// A new catalog: the model's words and the language it speaks.
    pub fn adopt(&mut self, catalog: &Catalog) {
        self.model.strings = catalog.strings.clone();
        catalog.language.clone_into(&mut self.language);
    }

    /// The popup's read: `perform(("read",), control, source=names)`, its outcome applied.
    pub fn read(&mut self, control: &dyn PopupControl, now: f64) {
        let action = [Value::from("read")];
        let (verdict, payload) = model::perform(&action, control, None, None);
        let _ = self
            .model
            .apply_outcome(&action, &outcome(&verdict, payload), now);
        self.model.wants_read = false;
        self.read = true;
    }

    /// The snapshot's `popup` field: `{view, menus: [[id, row_menu]], read, attention}`.
    pub fn field(&mut self, now: f64) -> Value {
        let clock = car_platform::localclock::Crt;
        let ctx = Ctx {
            current: &self.language.clone(),
            clock: &clock,
        };
        let view = match self.model.view(&ctx, &Value::Float(now)) {
            Ok(view) => Value::Object(view),
            Err(_) => Value::Null,
        };
        let mut menus = Vec::new();
        if let Value::Object(found) = &view
            && let Some(Value::Array(tasks)) = found.get("tasks")
        {
            for task in tasks {
                let id = match task {
                    Value::Object(task) => {
                        task.get("interruption_id").cloned().unwrap_or(Value::Null)
                    }
                    _ => Value::Null,
                };
                let menu = self
                    .model
                    .menu_for(&id)
                    .unwrap_or_else(|_| Value::Array(Vec::new()));
                menus.push(Value::Array(vec![id, menu]));
            }
        }
        let mut field = Map::new();
        field.insert("view".into(), view);
        field.insert("menus".into(), Value::Array(menus));
        field.insert("read".into(), Value::Bool(self.read));
        field.insert(
            "attention".into(),
            Value::Bool(self.model.attention().unwrap_or(false)),
        );
        Value::Object(field)
    }

    /// A click: `popup {call, args}` -> `(kind, *args)`, begun (a second of the same is refused, as `begin` refuses
    /// it), done as `perform` does it, its outcome applied and the rows read again where the model wants them.
    /// The answer is `{"ok": <verdict is ok>, "outcome": [verdict, payload]}` (`outcome` null where it was not begun).
    pub fn act(&mut self, control: &dyn PopupControl, call: &str, args: &Value, now: f64) -> Value {
        let mut answer = Map::new();
        let Some(kind) = kind_of(call) else {
            answer.insert("ok".into(), Value::Bool(false));
            answer.insert("outcome".into(), Value::Null);
            return Value::Object(answer);
        };
        if kind == "read" {
            self.read(control, now);
            answer.insert("ok".into(), Value::Bool(!self.model.read_failed));
            answer.insert("outcome".into(), Value::Null);
            return Value::Object(answer);
        }
        let mut action = vec![Value::from(kind)];
        if let Value::Array(items) = args {
            action.extend(items.iter().cloned());
        }
        if !self.model.begin(&action).unwrap_or(false) {
            answer.insert("ok".into(), Value::Bool(false));
            answer.insert("outcome".into(), Value::Null);
            return Value::Object(answer);
        }
        let (verdict, payload) = model::perform(&action, control, None, None);
        let said = outcome(&verdict, payload);
        let _ = self.model.apply_outcome(&action, &said, now);
        if self.model.wants_read {
            self.read(control, now);
        }
        answer.insert("ok".into(), Value::Bool(verdict == "ok"));
        answer.insert("outcome".into(), Value::Array(said.to_vec()));
        Value::Object(answer)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_popup_call_has_a_kind_and_nothing_else_does() {
        for call in [
            "list_pending",
            "get_status",
            "set_enabled",
            "set_interruption_recovery",
            "postpone",
            "unpostpone",
            "release_hold",
            "set_thread_tier",
            "set_project_rule",
            "set_once_words",
        ] {
            assert!(kind_of(call).is_some(), "{call}");
        }
        for call in ["cancel_all", "send", "", "dashboard", "read"] {
            assert_eq!(kind_of(call), None, "{call}");
        }
    }

    #[test]
    fn the_catalog_carries_its_locale_and_every_letter_of_it() {
        let english = letters_of("en");
        assert!(english.contains('A') && !english.contains(' '));
        let korean = letters_of("ko");
        assert!(
            korean
                .chars()
                .any(|c| ('\u{ac00}'..='\u{d7a3}').contains(&c))
        );
        let found = catalog();
        assert_eq!(found.letters, letters_of(&found.locale));
        assert!(!found.strings.is_empty());
    }

    #[test]
    fn a_field_before_any_read_says_so() {
        let mut shared = Shared::default();
        shared.adopt(&Catalog {
            strings: car_words::l10n::catalog("en")
                .iter()
                .map(|(key, value)| (key.as_str().into(), Value::from(value.as_str())))
                .collect(),
            language: "en".into(),
            locale: "en".into(),
            letters: String::new(),
        });
        let Value::Object(field) = shared.field(1_700_000_000.0) else {
            panic!("an object");
        };
        let keys: Vec<&str> = field.keys().filter_map(|key| key.as_str()).collect();
        assert_eq!(keys, ["view", "menus", "read", "attention"]);
        assert_eq!(field.get("read"), Some(&Value::Bool(false)));
    }
}
