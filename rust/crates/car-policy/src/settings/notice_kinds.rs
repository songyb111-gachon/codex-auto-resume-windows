//! `notice_kinds.py`: the kinds of notice a person can keep on screen until they click it (v0.6.16), one registry.
//!
//! The standard edition's kinds are [`CORE`], named by the catalog key their words are under. An edition registers
//! its own with [`register`] - the advanced edition as it makes its plug - with its words in every language, so the
//! standard build names none of them. The setting [`FIELD`] holds the ids chosen and nothing else.

use std::sync::Mutex;

use car_machine::json::{Map, Str, Value};
use car_words::l10n;

use super::vocab_gen::notice_kinds as words;
use crate::classify::text::has_non_space;

pub const FIELD: &str = words::FIELD;
/// How many ids a stored value keeps.
pub const LIMIT: usize = 64;

/// One kind: its id, the notifier kinds it covers, and its words - a catalog key of core's, or one text per
/// language (an edition's, sorted by locale).
#[derive(Clone, Debug, PartialEq)]
pub struct Kind {
    pub id: String,
    pub notices: Vec<String>,
    pub key: Option<&'static str>,
    pub words: Vec<(String, Str)>,
}

impl Kind {
    fn core(id: &str, notices: &[&str], key: &'static str) -> Kind {
        Kind {
            id: id.to_owned(),
            notices: notices.iter().map(|notice| (*notice).to_owned()).collect(),
            key: Some(key),
            words: Vec::new(),
        }
    }

    /// `label(locale)`: a catalog key's text, or the edition's words in `locale` (else in the default language).
    pub fn label(&self, locale: &str) -> Value {
        if let Some(key) = self.key {
            return l10n::text(key, locale, &[]).map_or_else(|| Value::from(key), Value::from);
        }
        let find = |wanted: &str| {
            self.words
                .iter()
                .find(|(each, _)| each == wanted)
                .map(|(_, text)| text.clone())
        };
        let found = find(locale)
            .filter(|text| !text.is_empty())
            .or_else(|| find(l10n::DEFAULT));
        found.map_or(Value::Null, Value::Str)
    }
}

/// The standard edition's kinds, in the order the window lists them.
pub fn core() -> Vec<Kind> {
    vec![
        Kind::core(
            "interruption",
            &["interruption"],
            "field.notify_interruption",
        ),
        Kind::core("starting", &["starting"], "field.notify_starting"),
        Kind::core("resumed", &["resumed"], "msg.toast_resumed_title"),
        Kind::core("failed", &["failed", "unknown"], "msg.toast_failed_title"),
        Kind::core("stopped", &["stopped"], "field.notify_stopped"),
        Kind::core("cancelled", &["cancelled"], "msg.toast_cancelled_title"),
        Kind::core("needs_you", &["needs_you"], "field.notify_needs_you"),
        Kind::core("after_sleep", &["after_sleep"], "stay.after_sleep"),
        Kind::core(
            "memory",
            &["memory_warning", "memory_stopped"],
            "msg.toast_memory_warning",
        ),
        Kind::core(
            "power",
            &[
                "power_grace",
                "power_now",
                "power_failed",
                "power_not_met",
                "power_stopped",
            ],
            "power.title",
        ),
    ]
}

static REGISTERED: Mutex<Vec<Kind>> = Mutex::new(Vec::new());

fn registered() -> std::sync::MutexGuard<'static, Vec<Kind>> {
    REGISTERED
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

/// `ID.match(text)`: `[a-z][a-z0-9_]{0,31}\Z`.
pub fn is_id(text: &str) -> bool {
    let mut chars = text.chars();
    chars.next().is_some_and(|first| first.is_ascii_lowercase())
        && text.len() <= 32
        && chars.all(|each| each.is_ascii_lowercase() || each.is_ascii_digit() || each == '_')
}

fn id_of(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str().filter(|text| is_id(text)),
        _ => None,
    }
}

/// `KindError`: a kind that cannot be registered, and the rule it broke.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KindError(pub &'static str);

/// `register(kind_id, notices, words)`: register an edition's kind; the same id again replaces it in its place.
pub fn register(kind_id: &Value, notices: &Value, said: &Value) -> Result<Kind, String> {
    let Some(id) = id_of(kind_id) else {
        return Err("an id is lowercase letters, digits and _".into());
    };
    let notices: Vec<&Value> = match notices {
        Value::Array(items) => items.iter().collect(),
        _ => Vec::new(),
    };
    let named: Vec<String> = notices
        .iter()
        .filter_map(|notice| id_of(notice).map(str::to_owned))
        .collect();
    if named.is_empty() || named.len() != notices.len() {
        return Err("a kind covers at least one notice".into());
    }
    let Value::Object(texts) = said else {
        return Err("a kind has its words in every language".into());
    };
    let every = texts.len() == l10n::LOCALES.len()
        && l10n::LOCALES
            .iter()
            .all(|locale| texts.contains_key(*locale))
        && texts.values().all(
            |text| matches!(text, Value::Str(text) if has_non_space(text) && text.len() <= 200),
        );
    if !every {
        return Err("a kind has its words in every language".into());
    }
    let mut held = registered();
    let mut taken: Vec<Kind> = core();
    taken.extend(held.iter().filter(|kind| kind.id != id).cloned());
    if taken.iter().any(|kind| kind.id == id) {
        return Err(format!("the id {id} is taken"));
    }
    if taken
        .iter()
        .any(|kind| kind.notices.iter().any(|notice| named.contains(notice)))
    {
        return Err("a notice is another kind's".into());
    }
    let mut sorted: Vec<(String, Str)> = texts
        .iter()
        .filter_map(|(locale, text)| match text {
            Value::Str(text) => {
                Some((locale.as_str().unwrap_or_default().to_owned(), text.clone()))
            }
            _ => None,
        })
        .collect();
    sorted.sort_by(|a, b| a.0.cmp(&b.0));
    let made = Kind {
        id: id.to_owned(),
        notices: named,
        key: None,
        words: sorted,
    };
    match held.iter_mut().find(|kind| kind.id == id) {
        Some(slot) => *slot = made.clone(),
        None => held.push(made.clone()),
    }
    Ok(made)
}

/// Every kind there is in this process: CORE, then an edition's, as registered.
pub fn kinds() -> Vec<Kind> {
    let mut every = core();
    every.extend(registered().iter().cloned());
    every
}

pub fn ids() -> Vec<String> {
    kinds().into_iter().map(|kind| kind.id).collect()
}

/// `kind_of(notice_kind)`: the kind a notifier notice belongs to, or None.
pub fn kind_of(notice_kind: &str) -> Option<Kind> {
    kinds()
        .into_iter()
        .find(|kind| kind.notices.iter().any(|notice| notice == notice_kind))
}

/// `coerce(value, default)`: distinct ids, at most LIMIT, in the order given; anything else is `default`.
pub fn coerce(value: &Value, default: &Value) -> Value {
    let Value::Array(entries) = value else {
        return default.clone();
    };
    if entries.len() > LIMIT {
        return default.clone();
    }
    let mut kept: Vec<Value> = Vec::new();
    for entry in entries {
        if id_of(entry).is_none() {
            return default.clone();
        }
        if !kept.contains(entry) {
            kept.push(entry.clone());
        }
    }
    Value::Array(kept)
}

/// `chosen(values)`: the ids a settings mapping keeps on screen, as stored.
pub fn chosen(values: &Value) -> Vec<String> {
    let stored = match values {
        Value::Object(map) => map.get(FIELD).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    match coerce(&stored, &Value::Array(Vec::new())) {
        Value::Array(items) => items
            .iter()
            .filter_map(|item| id_of(item).map(str::to_owned))
            .collect(),
        _ => Vec::new(),
    }
}

/// `stays(notice_kind, values)`: whether a notice of this notifier kind stays on screen until clicked.
pub fn stays(notice_kind: &str, values: &Value) -> bool {
    kind_of(notice_kind).is_some_and(|kind| chosen(values).contains(&kind.id))
}

/// `edition_labels(locale)`: an edition's kinds' words in `locale`, by id.
pub fn edition_labels(locale: &str) -> Value {
    let mut map = Map::new();
    for kind in registered().iter() {
        map.insert(Str::from(kind.id.as_str()), kind.label(locale));
    }
    Value::Object(map)
}

/// Whether an edition registered any kind (describe() asks the language only then).
pub fn any_registered() -> bool {
    !registered().is_empty()
}
