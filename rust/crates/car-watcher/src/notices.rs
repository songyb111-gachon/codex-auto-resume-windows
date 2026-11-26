//! The watcher's notices by exactly one route (runtime/app.py `_notifier`'s announce, `_deliver`, `_watcher_notice`,
//! `_show_watcher_notice`): the card where the host attached its stack and Windows says a card may be shown now
//! (`notice_presence`, car-platform `presence`), else today's toast.
//!
//! A card goes to the host as the `notice` event (`events::Events::hand_over`); the host ends it with
//! `notice_complete {id, shown}` (`notifier.complete`: the silent history copy once it was seen, else the toast).

use std::path::Path;
use std::sync::{Arc, Mutex, OnceLock, PoisonError};

use car_machine::json::{Map, Value};
use car_store::Store;
use car_surface::notice_inbox::Inbox;
use car_surface::notifier::Notice;
use car_surface::seam::Raised;

use crate::app::Probe;
use crate::events::Events;
use crate::fail::{Failed, Res};
use crate::toasts::Toasts;

/// `notifier._presence()`: `notice_presence.snapshot(notify.aumid())`, each answer an int, a bool or None.
pub fn presence() -> Result<Value, Raised> {
    let found = car_platform::presence::snapshot(Some(car_surface::notify::aumid()));
    let int = |answer: Option<i32>| answer.map_or(Value::Null, |n| Value::from(i64::from(n)));
    let flag = |answer: Option<bool>| answer.map_or(Value::Null, Value::Bool);
    let mut map = Map::new();
    map.insert("notification_state".into(), int(found.notification_state));
    map.insert("notification_mode".into(), int(found.notification_mode));
    map.insert("app_notifications".into(), int(found.app_notifications));
    map.insert("screen_reader".into(), flag(found.screen_reader));
    map.insert("remote_session".into(), flag(found.remote_session));
    map.insert("session_locked".into(), flag(found.session_locked));
    Ok(Value::Object(map))
}

/// `notify.show_content(content, silent)` through this PC's PowerShell.
fn show(content: &Map, silent: bool) -> car_machine::pyval::Py<bool> {
    let shell = car_surface::seam::SystemPowerShell::system();
    car_surface::notify::show_content(&shell, content, silent)
}

/// `settings.get(CARD_SETTING, True) is True`.
pub fn card_setting(values: &Value) -> Value {
    let chosen = match values {
        Value::Object(map) => map.get(car_surface::notifier::CARD_SETTING).cloned(),
        _ => None,
    };
    Value::Bool(matches!(chosen, None | Some(Value::Bool(true))))
}

/// `notifier.deliver(notice, inbox=..., setting=...)` with this PC's presence and toast: whether it was shown.
pub fn deliver(notice: &Notice, inbox: Option<&Inbox<Notice>>, setting: &Value) -> Res<bool> {
    let (_, shown) = car_surface::notifier::deliver(notice, inbox, setting, &presence, &show)
        .map_err(|class| Failed::new(class, ""))?;
    Ok(shown)
}

/// `notifier.complete(notice, shown)`: the silent history copy, or today's toast. Runs PowerShell.
pub fn complete(notice: &Notice, shown: &Value) -> bool {
    car_surface::notifier::complete(notice, shown, &show).unwrap_or(false)
}

/// What a route needs of the watcher: its settings in force, its plug (P20), its state folder and its events.
#[derive(Clone)]
pub struct Route {
    pub settings: Arc<Mutex<Map>>,
    pub plug: Arc<car_policy::plug::Guarded>,
    pub state_dir: String,
    pub events: Arc<Events>,
}

impl Route {
    pub fn values(&self) -> Value {
        Value::Object(
            self.settings
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .clone(),
        )
    }

    /// `App._deliver(notice, detail, inbox=..., setting=...)`: told first to a plug that wants it, then delivered.
    pub fn deliver(&self, notice: &Notice, detail: &Map, card: bool, setting: &Value) -> Res<bool> {
        let detail = Value::Object(detail.clone());
        let state_dir = self.state_dir.clone();
        let opened = || -> Result<Value, Raised> {
            let store = Store::open_with(
                Path::new(&state_dir),
                car_store::Options::new(Arc::new(Probe)),
            )
            .map_err(|_| Raised::new("StoreError"))?;
            store
                .pending()
                .map(|rows| Value::Array(rows.into_iter().map(Value::Object).collect()))
                .map_err(|_| Raised::new("StoreError"))
        };
        self.plug.notice(&|| {
            car_surface::notifier::told(
                notice,
                &detail,
                Some(&opened),
                Value::Float(crate::clock::wall()),
            )
            .ok()
        });
        let inbox = card.then(|| self.events.inbox());
        deliver(notice, inbox, setting)
    }

    /// `_show_watcher_notice(event, detail, final)`: a notice about the watcher itself; the power action's are raised
    /// whatever the switches say, and a `final` one is the toast (the card's host ends with this watcher).
    pub fn watcher_notice(&self, event: &str, detail: &Map, last: bool) -> Res<bool> {
        let values = self.values();
        let fail = |class: &'static str| Failed::new(class, "");
        let power = car_surface::notifier::POWER_STATUS
            .iter()
            .any(|(name, _)| *name == event);
        if !power && !car_policy::settings::notification_enabled(&values, event).map_err(fail)? {
            return Ok(false);
        }
        let environ = |name: &str| std::env::var(name).ok();
        let locale = car_words::interface::language(&environ, &Vec::new);
        let clock = car_platform::localclock::Crt;
        let speech = car_surface::speech::Speech::new(locale, &clock);
        let stay = Value::Array(
            car_policy::settings::notice_kinds::chosen(&values)
                .into_iter()
                .map(Value::from)
                .collect(),
        );
        let built = car_surface::notifier::build(
            &speech,
            &Value::from(event),
            &Value::Object(detail.clone()),
            &Value::Null,
            false,
            car_surface::notifier::click_destination(&values, false),
            &stay,
        )
        .map_err(fail)?;
        let Some(notice) = built else {
            return Ok(false);
        };
        let card = !last && matches!(card_setting(&values), Value::Bool(true));
        self.deliver(&notice, detail, !last, &Value::Bool(card))
    }
}

/// `_watcher_notice(event, detail, final=...)`: a final one raised now, the rest queued off the tick path on the
/// watcher's own Toasts (made at the first).
pub struct WatcherNotices {
    route: Route,
    log: crate::toasts::Log,
    toasts: OnceLock<Toasts>,
}

impl WatcherNotices {
    pub fn new(route: Route, log: crate::toasts::Log) -> WatcherNotices {
        WatcherNotices {
            route,
            log,
            toasts: OnceLock::new(),
        }
    }

    pub fn notice(&self, event: &str, detail: Map, last: bool) -> Res<bool> {
        if last {
            return self.route.watcher_notice(event, &detail, true);
        }
        let toasts = self.toasts.get_or_init(|| {
            let route = self.route.clone();
            Toasts::new(
                Arc::new(move |event: &str, detail: &Map| {
                    route.watcher_notice(event, detail, false)
                }),
                Arc::clone(&self.log),
            )
        });
        Ok(toasts.call(event, &detail))
    }
}

/// The `notice` event's notice (CardStack.Show): `{id, key, title, stays, view, letters}`, the view
/// `notice_card.view(notice)` and the letters `fonts._letters(view["locale"])`.
pub fn card_event(id: i64, notice: &Notice) -> Value {
    let view = car_surface::notice_card::view(notice);
    let locale = match view.get("locale") {
        Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    };
    let mut map = Map::new();
    map.insert("id".into(), Value::from(id));
    map.insert("key".into(), notice.key.clone());
    map.insert("title".into(), notice.title.clone());
    map.insert("stays".into(), Value::Bool(notice.stays));
    map.insert("view".into(), Value::Object(view));
    map.insert(
        "letters".into(),
        Value::from(crate::surface::letters_of(&locale).as_str()),
    );
    Value::Object(map)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn notice(title: &str, stays: bool) -> Notice {
        Notice {
            kind: "resumed".into(),
            status: "resumed".into(),
            title: Value::from(title),
            line: Value::from("A line"),
            origin: Value::Null,
            chip: None,
            chip_tone: None,
            actions: Vec::new(),
            content: Vec::new(),
            locale: "ko".into(),
            key: Value::from("thread-1"),
            click: "default".into(),
            stays,
        }
    }

    #[test]
    fn a_posted_notice_is_handed_to_the_host_as_one_card_event_and_ended_once() {
        let events = Arc::new(Events::new());
        // Not attached: the inbox refuses, and the caller raises the toast.
        assert!(!events.inbox().post(notice("first", false)));
        events.attach_cards();
        assert!(events.cards_attached());
        assert!(events.inbox().post(notice("Codex Auto Resume", true)));
        assert!(events.inbox().post(notice("second", false)));
        let first = events
            .next(std::time::Duration::from_millis(10))
            .expect("a notice event");
        let Value::Object(event) = &first else {
            panic!("{first:?}")
        };
        assert_eq!(event.get("kind"), Some(&Value::from("notice")));
        let Some(Value::Object(card)) = event.get("notice") else {
            panic!("{first:?}")
        };
        let names: Vec<&str> = card.keys().filter_map(|key| key.as_str()).collect();
        assert_eq!(names, ["id", "key", "title", "stays", "view", "letters"]);
        assert_eq!(card.get("id"), Some(&Value::from(1i64)));
        assert_eq!(card.get("key"), Some(&Value::from("thread-1")));
        assert_eq!(card.get("title"), Some(&Value::from("Codex Auto Resume")));
        assert_eq!(card.get("stays"), Some(&Value::Bool(true)));
        let Some(Value::Object(view)) = card.get("view") else {
            panic!("{card:?}")
        };
        assert_eq!(view.get("locale"), Some(&Value::from("ko")));
        let letters = crate::surface::letters_of("ko");
        assert_eq!(card.get("letters"), Some(&Value::from(letters.as_str())));
        let second = events
            .next(std::time::Duration::from_millis(10))
            .expect("the second");
        let Value::Object(second) = second else {
            unreachable!()
        };
        let Some(Value::Object(card)) = second.get("notice") else {
            unreachable!()
        };
        assert_eq!(card.get("id"), Some(&Value::from(2i64)));
        // Ended once, by its id as the host's reader writes it (a double) or as an int.
        assert!(events.take_posted(&Value::Float(1.0)).is_some());
        assert!(events.take_posted(&Value::from(1i64)).is_none());
        assert!(events.take_posted(&Value::from("2")).is_none());
        assert!(events.take_posted(&Value::from(2i64)).is_some());
        // Detached: refused again; once ended, a wake hands nothing over.
        assert!(events.detach_cards().is_empty());
        assert!(!events.inbox().post(notice("third", false)));
        events.attach_cards();
        events.end(0);
        assert!(!events.inbox().post(notice("fourth", false)));
    }

    #[test]
    fn the_card_setting_is_true_only_when_unset_or_exactly_true() {
        let with = |value: Value| {
            let mut map = Map::new();
            map.insert(car_surface::notifier::CARD_SETTING.into(), value);
            card_setting(&Value::Object(map))
        };
        assert_eq!(card_setting(&Value::Object(Map::new())), Value::Bool(true));
        assert_eq!(with(Value::Bool(true)), Value::Bool(true));
        assert_eq!(with(Value::Bool(false)), Value::Bool(false));
        assert_eq!(with(Value::from(1i64)), Value::Bool(false));
        assert_eq!(with(Value::Null), Value::Bool(false));
    }

    #[test]
    fn presence_answers_the_six_names_card_allowed_reads() {
        let Ok(Value::Object(map)) = presence() else {
            panic!()
        };
        let names: Vec<&str> = map.keys().filter_map(|key| key.as_str()).collect();
        assert_eq!(
            names,
            [
                "notification_state",
                "notification_mode",
                "app_notifications",
                "screen_reader",
                "remote_session",
                "session_locked"
            ]
        );
    }
}
