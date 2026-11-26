//! `runtime/plugnotices.py`: the notices an edition's plug adds to the icon's snapshot, shown by the watcher.
//!
//! The advanced edition's usage meter, update check and account switch say what happened in the snapshot; the
//! watcher shows each once in its life, under the notifications switch and off the tick path. The standard edition
//! adds none.

use car_machine::json::{Map, Str, Value};
use car_policy::plug::Answer;

use crate::fail::Res;

/// How many notice keys a watcher remembers per part: each sighting moves a key to the newest end, and past this
/// many the OLDEST is forgotten, never a new one refused.
pub const SHOWN_KEYS: usize = 64;

/// The watcher's part (App's `_open_codex`, `_chat` and the four `_<part>_shown` memories).
#[derive(Clone, Debug, Default)]
pub struct PlugNotices {
    /// Whether a notice offers Open Codex beside its other buttons (v0.6.18).
    pub open_codex: bool,
    /// Whether the in-app chat is on (v0.6.19, notifier.click_destination).
    pub chat: bool,
    /// The keys shown, per memory (`_near_limit_shown`, `_update_shown`, `_account_shown`, `_autoswitch_shown`),
    /// oldest first.
    shown: Vec<(&'static str, Vec<Str>)>,
}

fn get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

fn field(notice: &Value, key: &str) -> Value {
    get(notice, key).cloned().unwrap_or(Value::Null)
}

fn detail<const N: usize>(pairs: [(&str, Value); N]) -> Map {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(key.into(), value);
    }
    map
}

impl PlugNotices {
    pub fn new() -> PlugNotices {
        PlugNotices::default()
    }

    /// `_edition_notices(added)`: what the plug added to the icon's snapshot - the meter's warnings, the update
    /// check's offers and whether a notice offers Open Codex, whether the in-app chat is on, a change of account -
    /// each only while the plug says so. `notice(event, detail)` is `_watcher_notice`; what it raises ends the rest,
    /// as the exception leaves `_edition_notices`.
    pub fn edition_notices(
        &mut self,
        added: &Answer<Value>,
        notice: &mut dyn FnMut(&str, Map) -> Res<()>,
    ) -> Res<()> {
        let found = match added {
            Answer::Is(value @ Value::Object(_)) => get(value, "notice").cloned(),
            _ => None,
        };
        let is_true = |key: &str| {
            matches!(
                found.as_ref().and_then(|notice| get(notice, key)),
                Some(Value::Bool(true))
            ) && matches!(found, Some(Value::Object(_)))
        };
        self.open_codex = is_true("open_codex");
        self.chat = is_true("chat");
        let Answer::Is(added) = added else {
            return Ok(());
        };
        // _near_limit
        for shown in self.unshown(added, "meter", "_near_limit_shown") {
            notice(
                "near_limit",
                detail([
                    ("minutes", field(&shown, "window_minutes")),
                    ("percent", field(&shown, "used_percent")),
                    ("reset_at", field(&shown, "reset_at")),
                    ("kind", field(&shown, "kind")),
                ]),
            )?;
        }
        // _update_offered
        for shown in self.unshown(added, "update", "_update_shown") {
            notice(
                "update_offered",
                detail([
                    ("version", field(&shown, "version")),
                    (
                        "prerelease",
                        Value::Bool(matches!(get(&shown, "prerelease"), Some(Value::Bool(true)))),
                    ),
                ]),
            )?;
        }
        // _account_changed
        for shown in self.unshown(added, "account", "_account_shown") {
            notice("account_changed", detail([("count", field(&shown, "count"))]))?;
        }
        for shown in self.unshown(added, "autoswitch", "_autoswitch_shown") {
            notice("accounts_exhausted", detail([("why", field(&shown, "why"))]))?;
        }
        Ok(())
    }

    /// `_unshown(owner, added, part, shown_name)`: the notices under `part` not shown yet, by their keys, each
    /// marked shown. Python's generator marks each one as it is reached; a notice that raised ends the iteration,
    /// so the ones after it are not marked. Here they are taken in order and each marked before it is handed on,
    /// and the caller stops at the first that raised - the same marks.
    fn unshown(&mut self, added: &Value, part: &str, name: &'static str) -> Unshown<'_> {
        let notices = match get(added, part).and_then(|found| get(found, "notices")) {
            Some(Value::Array(items)) => items.clone(),
            _ => Vec::new(),
        };
        if !self.shown.iter().any(|(each, _)| *each == name) {
            self.shown.push((name, Vec::new()));
        }
        Unshown {
            owner: self,
            name,
            notices: notices.into_iter(),
        }
    }

    /// The keys a memory holds, oldest first (for tests and the diffs).
    pub fn keys(&self, name: &str) -> Vec<Str> {
        self.shown
            .iter()
            .find(|(each, _)| *each == name)
            .map(|(_, keys)| keys.clone())
            .unwrap_or_default()
    }
}

/// The generator: each notice whose key is new, after its key is marked.
struct Unshown<'a> {
    owner: &'a mut PlugNotices,
    name: &'static str,
    notices: std::vec::IntoIter<Value>,
}

impl Iterator for Unshown<'_> {
    type Item = Value;

    fn next(&mut self) -> Option<Value> {
        for notice in self.notices.by_ref() {
            let Some(Value::Str(key)) = get(&notice, "key") else {
                continue;
            };
            let key = key.clone();
            let shown = &mut self
                .owner
                .shown
                .iter_mut()
                .find(|(each, _)| *each == self.name)
                .expect("made by unshown")
                .1;
            let new = match shown.iter().position(|each| *each == key) {
                Some(at) => {
                    shown.remove(at);
                    false
                }
                None => true,
            };
            shown.push(key);
            while shown.len() > SHOWN_KEYS {
                shown.remove(0);
            }
            if new {
                return Some(notice);
            }
        }
        None
    }
}
