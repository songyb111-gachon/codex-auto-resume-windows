//! `notifier.py`: one notification, built once, shown one way - the product's card or today's Windows toast.
//!
//! * `build(event, detail, identity)`: the one builder, an engine event to a Notice;
//! * `deliver(notice, ...)`: hand it to the card, or raise today's toast;
//! * `complete(notice, shown)`: how a notice the card took ends;
//! * `activate(uri, ...)`: a card button, done in process.
//!
//! A `Notice` carries the toast's own content - the exact arguments `notify::show` is given - and the card's view of
//! the same lines; the card's buttons are the toast's buttons, as data. Nothing here can recover anything: a button
//! can cancel one exact interruption, open one page, or stop one batch's power action.

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_policy::classify::reasons;
use car_policy::classify::vocab_gen::failures::CATEGORIES;
use car_policy::settings::{demo, notice_kinds};

use crate::codex_link::{chat_uri, codex_thread_uri, parse_chat_uri, parse_codex_thread_uri};
use crate::notice_inbox::Inbox;
use crate::notice_presence::{Answers, card_allowed};
use crate::notice_uris::{
    open_page, parse_cancel_uri, parse_open_uri, parse_power_stop_uri, with_open_codex_flag,
};
use crate::notify::{self, MAX_TOAST_ACTIONS};
use crate::py::{self, str_of};
use crate::seam::{CardControl, Raised};
use crate::speech::Speech;

/// The setting that turns the card off.
pub const CARD_SETTING: &str = "notification_card";
/// `CLICK_SETTING`, its destinations and the default (`settings.FIELDS["notice_click"][0]`).
pub const CLICK_SETTING: &str = "notice_click";
pub const CLICK_DESTINATIONS: [&str; 3] = ["page", "chat", "codex"];
pub const DEFAULT_CLICK: &str = "page";

/// `NOTICE_STATUS`: what each kind of notice wears as its status light.
pub const NOTICE_STATUS: [(&str, &str); 21] = [
    ("interruption", "waiting"),
    ("starting", "recovering"),
    ("resumed", "monitoring"),
    ("failed", "failed"),
    ("unknown", "attention"),
    ("stopped", "attention"),
    ("cancelled", "paused"),
    ("needs_you", "attention"),
    ("after_sleep", "attention"),
    ("memory_warning", "attention"),
    ("memory_stopped", "attention"),
    ("demo", "waiting"),
    ("near_limit", "attention"),
    ("near_limit_not_stopped", "attention"),
    ("near_limit_press_resume", "attention"),
    ("near_limit_not_continued", "attention"),
    ("update_offered", "attention"),
    ("restart_gave_up", "attention"),
    ("account_changed", "paused"),
    ("accounts_exhausted", "paused"),
    ("python_returned", "paused"),
];
/// `POWER_STATUS` (v0.6.12).
pub const POWER_STATUS: [(&str, &str); 5] = [
    ("power_grace", "attention"),
    ("power_now", "attention"),
    ("power_failed", "failed"),
    ("power_not_met", "attention"),
    ("power_stopped", "paused"),
];
/// `BODY_PAGES`: the page a notice with no Open button is about.
pub const BODY_PAGES: [(&str, &str); 7] = [
    ("starting", "pending"),
    ("resumed", "history"),
    ("failed", "history"),
    ("unknown", "history"),
    ("stopped", "history"),
    ("cancelled", "history"),
    ("power_stopped", "settings"),
];

/// `STATUS[kind]`.
pub fn status_of(kind: &str) -> Option<&'static str> {
    NOTICE_STATUS
        .iter()
        .chain(POWER_STATUS.iter())
        .find(|(name, _)| *name == kind)
        .map(|(_, status)| *status)
}

/// `STATUS` (`{**NOTICE_STATUS, **POWER_STATUS}`), in the reference's order.
pub fn statuses() -> Vec<(&'static str, &'static str)> {
    NOTICE_STATUS
        .iter()
        .chain(POWER_STATUS.iter())
        .copied()
        .collect()
}

/// One notification as data (`notifier.Notice`, a frozen dataclass).
#[derive(Clone, Debug, PartialEq)]
pub struct Notice {
    pub kind: String,
    pub status: String,
    pub title: Value,
    pub line: Value,
    pub origin: Value,
    pub chip: Option<String>,
    pub chip_tone: Option<String>,
    pub actions: Vec<(Value, Value)>,
    /// The toast's arguments, sorted by name (`_frozen`): `extra` and `more` as lists.
    pub content: Vec<(Str, Value)>,
    pub locale: String,
    pub key: Value,
    pub click: String,
    pub stays: bool,
}

impl Notice {
    /// `toast_content()`: the toast, as `notify::show_content` takes it.
    pub fn toast_content(&self) -> Py<Map> {
        let mut content = Map::new();
        for (name, value) in &self.content {
            let value = match name.as_str() {
                Some("extra") => Value::Array(py::items(value)?),
                Some("more") => {
                    let mut pairs = Vec::new();
                    for pair in py::items(value)? {
                        pairs.push(Value::Array(py::items(&pair)?));
                    }
                    Value::Array(pairs)
                }
                _ => value.clone(),
            };
            content.insert(name.clone(), value);
        }
        Ok(content)
    }

    /// The dataclass's fields as a dict, in their order (what the diffs compare).
    pub fn to_value(&self) -> Value {
        let text = |value: &Option<String>| value.as_deref().map_or(Value::Null, Value::from);
        py::object([
            ("kind", Value::from(self.kind.as_str())),
            ("status", Value::from(self.status.as_str())),
            ("title", self.title.clone()),
            ("line", self.line.clone()),
            ("origin", self.origin.clone()),
            ("chip", text(&self.chip)),
            ("chip_tone", text(&self.chip_tone)),
            (
                "actions",
                Value::Array(
                    self.actions
                        .iter()
                        .map(|(label, uri)| Value::Array(vec![label.clone(), uri.clone()]))
                        .collect(),
                ),
            ),
            (
                "content",
                Value::Array(
                    self.content
                        .iter()
                        .map(|(name, value)| {
                            Value::Array(vec![Value::Str(name.clone()), value.clone()])
                        })
                        .collect(),
                ),
            ),
            ("locale", Value::from(self.locale.as_str())),
            ("key", self.key.clone()),
            ("click", Value::from(self.click.as_str())),
            ("stays", Value::Bool(self.stays)),
        ])
    }
}

/// `_frozen(content)`.
fn frozen(content: &Map) -> Py<Vec<(Str, Value)>> {
    let mut names: Vec<&Str> = content.keys().collect();
    names.sort();
    let mut found = Vec::new();
    for name in names {
        let value = &content[name];
        let value = match name.as_str() {
            Some("extra") => Value::Array(py::items(value)?),
            Some("more") => {
                let mut pairs = Vec::new();
                for pair in py::items(value)? {
                    pairs.push(Value::Array(py::items(&pair)?));
                }
                Value::Array(pairs)
            }
            _ => value.clone(),
        };
        found.push((name.clone(), value));
    }
    Ok(found)
}

fn field<'a>(content: &'a Map, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    content.get(name).unwrap_or(&NULL)
}

/// `toast_actions(content)`: the buttons a toast with this content shows.
pub fn toast_actions(content: &Map) -> Py<Vec<(Value, Value)>> {
    let mut pairs = notify::action_pairs(
        field(content, "button"),
        field(content, "uri"),
        field(content, "more"),
        true,
    )?;
    pairs.truncate(MAX_TOAST_ACTIONS);
    Ok(pairs)
}

/// `_notice(kind, content, key=..., chip=..., chip_tone=..., line=...)`.
fn notice(
    speech: &Speech,
    kind: &str,
    content: &Map,
    key: Value,
    chip: Option<String>,
    chip_tone: Option<&str>,
    line: Option<Value>,
) -> Py<Notice> {
    let extra = py::items(py::or(field(content, "extra"), &Value::Array(Vec::new())))?;
    let status = status_of(kind).ok_or("KeyError")?;
    let title = content.get("title").ok_or("KeyError")?.clone();
    let line = line.unwrap_or_else(|| extra.first().cloned().unwrap_or_else(|| Value::from("")));
    let origin = content.get("body").ok_or("KeyError")?.clone();
    Ok(Notice {
        kind: kind.to_owned(),
        status: status.to_owned(),
        title,
        line,
        origin,
        chip,
        chip_tone: chip_tone.map(str::to_owned),
        actions: toast_actions(content)?,
        content: frozen(content)?,
        locale: speech.locale.to_owned(),
        key,
        click: String::new(),
        stays: false,
    })
}

// ------------------------------------------------------------- a click on the notice itself
/// `click_destination(values, chat)`: where a click goes under these settings.
pub fn click_destination(values: &Value, chat: bool) -> &'static str {
    let chosen = match values {
        Value::Object(map) if chat => map.get(CLICK_SETTING).cloned().unwrap_or(Value::Null),
        _ if chat => Value::Null,
        _ => Value::from(DEFAULT_CLICK),
    };
    CLICK_DESTINATIONS
        .into_iter()
        .find(|each| pyval::is(&chosen, each))
        .unwrap_or(DEFAULT_CLICK)
}

/// `notice_page(kind, actions)`: its Open button's page, else BODY_PAGES', else the Overview.
pub fn notice_page(kind: &str, actions: &[(Value, Value)]) -> String {
    for (_label, uri) in actions {
        if let Some(page) = parse_open_uri(uri) {
            return page;
        }
    }
    BODY_PAGES
        .iter()
        .find(|(name, _)| *name == kind)
        .map_or("overview", |(_, page)| page)
        .to_owned()
}

/// `click_uri(kind, actions, key, destination)`: THE place a click on a notice's face or body is sent.
pub fn click_uri(kind: &str, actions: &[(Value, Value)], key: &Value, destination: &str) -> String {
    if destination == "codex"
        && let Some(link) = codex_thread_uri(key)
    {
        return link;
    }
    if destination == "chat"
        && let Some(link) = chat_uri(key)
    {
        return link;
    }
    open_page(&notice_page(kind, actions))
}

/// `_with_click(notice, destination, stay)`.
fn with_click(notice: Notice, destination: &str, stay: &Value) -> Py<Notice> {
    let click = click_uri(&notice.kind, &notice.actions, &notice.key, destination);
    let chosen = py::items(py::or(stay, &Value::Array(Vec::new())))?;
    let values = py::object([(notice_kinds::FIELD, Value::Array(chosen))]);
    let stays = notice_kinds::stays(&notice.kind, &values);
    let mut content = notice.toast_content()?;
    content.insert(Str::from("launch"), Value::from(click.as_str()));
    if stays {
        content.insert(Str::from("stays"), Value::Bool(true));
    }
    Ok(Notice {
        click,
        stays,
        content: frozen(&content)?,
        ..notice
    })
}

/// `build(event, detail, identity, sound=..., destination=..., stay=...)`: the Notice for one engine event, or None for
/// an event that is never announced.
pub fn build(
    speech: &Speech,
    event: &Value,
    detail: &Value,
    identity: &Value,
    sound: bool,
    destination: &str,
    stay: &Value,
) -> Py<Option<Notice>> {
    match build_bare(speech, event, detail, identity, sound)? {
        Some(found) => Ok(Some(with_click(found, destination, stay)?)),
        None => Ok(None),
    }
}

fn chip_of(speech: &Speech, category: &Value) -> Py<String> {
    speech.text(&reasons::label_key(category)?, &[])
}

/// `_build(event, detail, identity, sound=...)`.
fn build_bare(
    speech: &Speech,
    event: &Value,
    detail: &Value,
    identity: &Value,
    sound: bool,
) -> Py<Option<Notice>> {
    let empty = Value::Object(Map::new());
    let detail = match detail {
        Value::Object(_) => detail,
        _ => &empty,
    };
    let get = |name: &str| pyval::get(detail, name).cloned().unwrap_or(Value::Null);
    let usage = Value::from("usage_limit");
    let thread_id = get("thread_id");
    let state = get("state");
    let event_text = pyval::text(event).unwrap_or("");
    let is = |name: &str| pyval::is(event, name);
    if is("interruption") {
        let category = py::or(&get("category"), &usage).clone();
        let hold = get("hold");
        let content = notify::scheduled_content(
            speech,
            &thread_id,
            &get("interruption_id"),
            &get("reset_at"),
            &category,
            identity,
            &hold,
        )?;
        let line = if !matches!(hold, Value::Null) {
            Some(Value::from(notify::held_message(speech, &hold)?))
        } else if pyval::eq(&category, &usage) {
            None
        } else {
            Some(Value::from(speech.message("toast_transient")?))
        };
        let chip = chip_of(speech, &category)?;
        return notice(
            speech,
            "interruption",
            &content,
            thread_id,
            Some(chip),
            Some("waiting"),
            line,
        )
        .map(Some);
    }
    if is("objection") {
        let category = py::or(&get("category"), &usage).clone();
        let until = get("until");
        let content = notify::objection_content(
            speech,
            &thread_id,
            &get("interruption_id"),
            &until,
            &category,
            identity,
        )?;
        let chip = chip_of(speech, &category)?;
        let line = Value::from(notify::objection_message(speech, &until)?);
        return notice(
            speech,
            "interruption",
            &content,
            thread_id,
            Some(chip),
            Some("waiting"),
            Some(line),
        )
        .map(Some);
    }
    if is("starting") {
        let changed = matches!(get("task_changed"), Value::Bool(true));
        let content = notify::starting_content(speech, &thread_id, identity, changed)?;
        return notice(speech, "starting", &content, thread_id, None, None, None).map(Some);
    }
    if is("result") {
        if pyval::is(&state, "turn_started") || pyval::is(&state, "resumed") {
            let content = notify::resumed_content(speech, &thread_id, identity)?;
            return notice(speech, "resumed", &content, thread_id, None, None, None).map(Some);
        }
        let certain = !pyval::is(&state, "submission_unknown");
        let content = notify::attempt_failed_content(speech, &thread_id, identity, certain)?;
        let kind = if certain { "failed" } else { "unknown" };
        return notice(speech, kind, &content, thread_id, None, None, None).map(Some);
    }
    if is("needs_you") {
        let kind = get("category");
        let minutes = get("minutes");
        let content =
            notify::needs_you_content(speech, &thread_id, &kind, identity, &minutes, sound)?;
        let chip = notify::needs_you_label(speech, &kind)?;
        let line = Value::from(notify::needs_you_message(speech, &kind, &minutes)?);
        return notice(
            speech,
            "needs_you",
            &content,
            thread_id,
            Some(chip),
            Some("attention"),
            Some(line),
        )
        .map(Some);
    }
    if is("after_sleep") {
        let content = notify::after_sleep_content(speech, &get("slept"), &get("count"))?;
        return notice(
            speech,
            "after_sleep",
            &content,
            Value::Null,
            None,
            None,
            None,
        )
        .map(Some);
    }
    if is("memory_warning") || is("memory_stopped") {
        let content = notify::memory_content(speech, event, &get("used"), &get("limit"))?;
        return notice(speech, event_text, &content, Value::Null, None, None, None).map(Some);
    }
    if is("near_limit") {
        let said = get("kind");
        let kind = match notify::near_limit_kind(&said) {
            Some(kind) => format!("near_limit_{kind}"),
            None => "near_limit".to_owned(),
        };
        let content = notify::near_limit_content(
            speech,
            &get("minutes"),
            &get("percent"),
            &get("reset_at"),
            &said,
        )?;
        return notice(speech, &kind, &content, Value::Null, None, None, None).map(Some);
    }
    if is("update_offered") {
        let prerelease = Value::Bool(matches!(get("prerelease"), Value::Bool(true)));
        return match notify::update_offered_content(speech, &get("version"), &prerelease)? {
            None => Ok(None),
            Some(content) => notice(
                speech,
                "update_offered",
                &content,
                Value::Null,
                None,
                None,
                None,
            )
            .map(Some),
        };
    }
    if is("restart_gave_up") {
        let content = notify::restart_gave_up_content(speech)?;
        return notice(
            speech,
            "restart_gave_up",
            &content,
            Value::Null,
            None,
            None,
            None,
        )
        .map(Some);
    }
    if is("account_changed") || is("accounts_exhausted") {
        let content = account_changed_content(speech, &get("count"), event_text, &get("why"))?;
        return notice(speech, event_text, &content, Value::Null, None, None, None).map(Some);
    }
    if is("python_returned") {
        let content = match pyval::get(detail, "content")? {
            Value::Null if !matches!(detail, Value::Object(map) if map.contains_key("content")) => {
                return Err("KeyError");
            }
            Value::Object(map) => map.clone(),
            _ => return Err("AttributeError"),
        };
        return notice(
            speech,
            "python_returned",
            &content,
            Value::Null,
            None,
            None,
            None,
        )
        .map(Some);
    }
    if POWER_STATUS.iter().any(|(name, _)| is(name)) {
        let content = notify::power_content(speech, event, detail)?;
        return notice(speech, event_text, &content, Value::Null, None, None, None).map(Some);
    }
    if is("stopped") {
        let reason = get("reason");
        if notify::is_not_resumed(&reason)? {
            let category = py::or(&get("category"), &usage).clone();
            let content =
                notify::not_resumed_content(speech, &thread_id, identity, &reason, &category)?;
            let chip = chip_of(speech, &category)?;
            let line = Value::from(notify::not_resumed_message(speech, &reason)?);
            return notice(
                speech,
                "stopped",
                &content,
                thread_id,
                Some(chip),
                Some("attention"),
                Some(line),
            )
            .map(Some);
        }
        let reason = if pyval::is(&state, "no_progress_exhausted") {
            Value::from("no_progress")
        } else if pyval::is(&reason, "chain_time_cap") {
            Value::from("time")
        } else if pyval::is(&state, "retry_budget_exhausted") {
            Value::from("attempts")
        } else {
            Value::Null
        };
        let content = notify::stopped_content(speech, &thread_id, identity, &reason)?;
        return notice(speech, "stopped", &content, thread_id, None, None, None).map(Some);
    }
    Ok(None)
}

/// `build_demo(now)`: an interruption's card from the made-up task, its title saying Demo and every button inert.
pub fn build_demo(speech: &Speech, now: &Value) -> Py<Notice> {
    let detail = demo::detail(now)?;
    let identity = py::object([("name", Value::from(speech.text("demo.conversation", &[])?))]);
    let built = build(
        speech,
        &Value::from("interruption"),
        &detail,
        &identity,
        false,
        DEFAULT_CLICK,
        &Value::Array(Vec::new()),
    )?
    .ok_or("TypeError")?;
    let title = speech.text("demo.card_title", &[("title", str_of(&built.title))])?;
    let actions = built
        .actions
        .iter()
        .map(|(label, _)| (label.clone(), Value::from("")))
        .collect();
    Ok(Notice {
        kind: "demo".into(),
        status: status_of("demo").unwrap_or_default().into(),
        key: Value::Null,
        content: Vec::new(),
        click: String::new(),
        title: Value::from(title),
        actions,
        ..built
    })
}

/// What Windows says now, as `deliver` reads it: `dict((probe or _presence)() or {})`, `{}` where it raised.
fn presence_answers(probe: &dyn Fn() -> Result<Value, Raised>) -> Map {
    match probe() {
        Ok(value) => py::dict(py::or(&value, &Value::Object(Map::new()))).unwrap_or_default(),
        Err(_) => Map::new(),
    }
}

/// `show_demo(notice, inbox=..., setting=..., probe=...)`: a demo card to the host when a card may be shown now,
/// and otherwise nothing - never a toast.
pub fn show_demo(
    found: &Notice,
    inbox: Option<&Inbox<Notice>>,
    setting: &Value,
    probe: &dyn Fn() -> Result<Value, Raised>,
) -> bool {
    let Some(inbox) =
        inbox.filter(|inbox| matches!(setting, Value::Bool(true)) && inbox.attached())
    else {
        return false;
    };
    if !card_allowed(&Answers::from_probes(&presence_answers(probe))) {
        return false;
    }
    inbox.post(found.clone())
}

/// `build_power_stopped(stay)`: what a power action's stop button says afterwards (v0.6.12).
pub fn build_power_stopped(speech: &Speech, stay: &Value) -> Py<Notice> {
    let content = notify::power_content(
        speech,
        &Value::from("power_stopped"),
        &Value::Object(Map::new()),
    )?;
    let found = notice(
        speech,
        "power_stopped",
        &content,
        Value::Null,
        None,
        None,
        None,
    )?;
    with_click(found, DEFAULT_CLICK, stay)
}

/// `build_cancelled(thread_id, stay)`: what a cancel from a notification button says afterwards.
pub fn build_cancelled(speech: &Speech, thread_id: &Value, stay: &Value) -> Py<Notice> {
    let content = notify::cancelled_content(speech, thread_id)?;
    let found = notice(
        speech,
        "cancelled",
        &content,
        thread_id.clone(),
        None,
        None,
        None,
    )?;
    with_click(found, DEFAULT_CLICK, stay)
}

/// `with_open_codex(notice, on)` (v0.6.18, an edition's): a click that opens Codex at its conversation.
pub fn with_open_codex(found: &Notice, on: bool) -> Py<Notice> {
    if !on {
        return Ok(found.clone());
    }
    let Some(link) = codex_thread_uri(&found.key) else {
        return Ok(found.clone());
    };
    let mut content = found.toast_content()?;
    if let Some(uri) = content.get("uri").cloned()
        && pyval::truthy(&uri)
    {
        content.insert(Str::from("uri"), with_open_codex_flag(&uri));
    }
    let mut click = found.click.clone();
    if click.is_empty() || click == open_page(&notice_page(&found.kind, &found.actions)) {
        click = link.clone();
        content.insert(Str::from("launch"), Value::from(link.as_str()));
    }
    Ok(Notice {
        click,
        actions: toast_actions(&content)?,
        content: frozen(&content)?,
        ..found.clone()
    })
}

/// `told(notice, detail, opened, at)` (v0.6.19): what an edition's plug is told of a notice. `opened` reads the
/// pending records of a store of its own (`store.pending()`, closed after); an error there is no place at all. `at` is
/// the caller's `time.time()` where the reference's `at` is None.
pub fn told(
    found: &Notice,
    detail: &Value,
    opened: Option<&dyn Fn() -> Result<Value, Raised>>,
    at: Value,
) -> Py<Value> {
    let empty = Value::Object(Map::new());
    let detail = match detail {
        Value::Object(_) => detail,
        _ => &empty,
    };
    let get = |name: &str| pyval::get(detail, name).cloned().unwrap_or(Value::Null);
    let category = match get("category") {
        value if pyval::truthy(&value) => value,
        _ if found.kind == "interruption" => Value::from("usage_limit"),
        _ => Value::Null,
    };
    let key = get("interruption_id");
    let thread = get("thread_id");
    let mut index = Value::Null;
    if let Some(opened) = opened
        && (pyval::truthy(&key) || pyval::truthy(&thread))
    {
        index = place_of(opened, &key, &thread).unwrap_or(Value::Null);
    }
    pyval::hashable(&category)?;
    let kept = if pyval::text(&category).is_some_and(|word| CATEGORIES.contains(&word)) {
        category
    } else {
        Value::Null
    };
    Ok(py::object([
        ("kind", Value::from(found.kind.as_str())),
        ("category", kept),
        ("alias_index", index),
        ("at", at),
    ]))
}

fn place_of(
    opened: &dyn Fn() -> Result<Value, Raised>,
    key: &Value,
    thread: &Value,
) -> Option<Value> {
    let pending = opened().ok()?;
    for (place, record) in py::items(&pending).ok()?.iter().enumerate() {
        let matched = if pyval::truthy(key) {
            pyval::eq(pyval::get(record, "interruption_id").ok()?, key)
        } else {
            pyval::eq(pyval::get(record, "thread_id").ok()?, thread)
        };
        if matched {
            return Some(Value::from(place as i64 + 1));
        }
    }
    Some(Value::Null)
}

/// `sounds(notice)`: whether a notice carries a sound of its own.
pub fn sounds(found: &Notice) -> bool {
    found
        .content
        .iter()
        .rev()
        .find(|(name, _)| name.as_str() == Some("sound"))
        .is_some_and(|(_, value)| matches!(value, Value::Bool(true)))
}

/// The toast's raising, as `deliver` and `complete` are given it: `show(content, silent)`, its answer's truth.
pub type Show<'a> = &'a dyn Fn(&Map, bool) -> Py<bool>;

/// `deliver(notice, inbox=..., setting=..., probe=..., show=...)`: exactly one route, ("card", true) or ("toast",
/// what the toast answered).
pub fn deliver(
    found: &Notice,
    inbox: Option<&Inbox<Notice>>,
    setting: &Value,
    probe: &dyn Fn() -> Result<Value, Raised>,
    show: Show,
) -> Py<(&'static str, bool)> {
    let mut allowed = false;
    if matches!(setting, Value::Bool(true))
        && let Some(inbox) = inbox
        && inbox.attached()
        && !sounds(found)
    {
        allowed = card_allowed(&Answers::from_probes(&presence_answers(probe)));
    }
    if allowed
        && let Some(inbox) = inbox
        && inbox.post(found.clone())
    {
        return Ok(("card", true));
    }
    Ok(("toast", show(&found.toast_content()?, false)?))
}

/// `complete(notice, card_shown, show=...)`: the silent history copy once the card was seen, else the toast.
pub fn complete(found: &Notice, card_shown: &Value, show: Show) -> Py<bool> {
    if found.kind == "demo" {
        return Ok(false);
    }
    let content = found.toast_content()?;
    show(&content, matches!(card_shown, Value::Bool(true)))
}

// ------------------------------------------------------------------------- the buttons
/// A callback of the host's given a text: an answer, or the exception it raised.
pub type TextCall<'a, R> = &'a dyn Fn(&str) -> Result<R, Raised>;
/// The callback a notice is announced through.
pub type Announce<'a> = &'a dyn Fn(Notice) -> Result<(), Raised>;

/// What `activate` may call, each None where the host has no such thing.
pub struct Activation<'a> {
    pub control: Option<&'a dyn CardControl>,
    pub open_dashboard: Option<TextCall<'a, Value>>,
    pub announce: Option<Announce<'a>>,
    pub log: Option<TextCall<'a, ()>>,
    pub open_link: Option<TextCall<'a, Value>>,
    pub stay: Value,
    pub open_chat: Option<TextCall<'a, Value>>,
}

/// `re.fullmatch(r"[a-z][a-z0-9_]{0,47}", code)`.
fn identifier(code: &str) -> bool {
    let bytes = code.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 48
        && bytes[0].is_ascii_lowercase()
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'_')
}

/// A refusal's code, as a log line may name it: the code where it is an identifier, else "unrecognised code";
/// None where the exception carries no code (a text, not empty).
fn refusal(raised: &Raised) -> Option<String> {
    match &raised.code {
        Value::Str(code) if !code.is_empty() => {
            let code = py::text_of(code);
            Some(if identifier(&code) {
                code
            } else {
                "unrecognised code".into()
            })
        }
        _ => None,
    }
}

/// `activate(uri, ...)`: do what a card button's URI asks, in process; one word for what happened, and exactly one
/// line through `log`.
pub fn activate(speech: &Speech, uri: &Value, with: &Activation) -> Py<String> {
    let say = |line: &str| {
        if let Some(log) = with.log {
            let _ = log(line);
        }
    };
    if let Some(thread_id) = parse_codex_thread_uri(uri) {
        let link = codex_thread_uri(&Value::from(thread_id.as_str())).unwrap_or_default();
        let opened = match with.open_link {
            None => false,
            Some(open) => match open(&link) {
                Ok(answer) => matches!(answer, Value::Bool(true)),
                Err(raised) => {
                    say(&format!(
                        "notification card: opening Codex failed ({})",
                        raised.class
                    ));
                    return Ok("failed".into());
                }
            },
        };
        say(&if opened {
            format!("thread {thread_id}: Codex opened from a notification card")
        } else {
            "notification card: Codex could not be opened".to_owned()
        });
        return Ok(if opened { "opened" } else { "not_opened" }.into());
    }
    if let Some(chat_thread) = parse_chat_uri(uri) {
        let opened = match with.open_chat {
            None => false,
            Some(open) => match open(&chat_thread) {
                Ok(answer) => matches!(answer, Value::Bool(true)),
                Err(raised) => {
                    say(&format!(
                        "notification card: opening the chat failed ({})",
                        raised.class
                    ));
                    return Ok("failed".into());
                }
            },
        };
        say(&if opened {
            format!("thread {chat_thread}: the chat opened from a notification card")
        } else {
            "notification card: the chat could not be opened".to_owned()
        });
        return Ok(if opened { "opened" } else { "not_opened" }.into());
    }
    if let Some(page) = parse_open_uri(uri) {
        let Some(open) = with.open_dashboard else {
            say("notification card: the Dashboard is not installed here");
            return Ok("not_installed".into());
        };
        let opened = match open(&page) {
            Ok(answer) => pyval::truthy(&answer),
            Err(raised) => {
                say(&format!(
                    "notification card: opening the Dashboard failed ({})",
                    raised.class
                ));
                return Ok("failed".into());
            }
        };
        say(if opened {
            "dashboard opened from a notification card"
        } else {
            "notification card: the Dashboard is not installed here"
        });
        return Ok(if opened { "opened" } else { "not_installed" }.into());
    }
    if let Some(nonce) = parse_power_stop_uri(uri) {
        return power_stop(speech, &nonce, with, &say);
    }
    let interruption_id = parse_cancel_uri(uri);
    let (Some(interruption_id), Some(control)) = (interruption_id.as_ref(), with.control) else {
        say(&format!(
            "notification card: a button was ignored ({})",
            if interruption_id.is_none() {
                "malformed or unsupported URI"
            } else {
                "no control layer"
            }
        ));
        return Ok("ignored".into());
    };
    let result = match control.cancel_interruption(interruption_id, "toast") {
        Ok(result) => result,
        Err(raised) => {
            if let Some(code) = refusal(&raised) {
                say(&format!(
                    "notification card: the cancel was refused ({code})"
                ));
                return Ok("refused".into());
            }
            say(&format!(
                "notification card: the cancel failed ({})",
                raised.class
            ));
            return Ok("failed".into());
        }
    };
    let thread_id = py::get_or_empty(&result, "thread_id")?.clone();
    let changed = if pyval::truthy(&result) {
        match &result {
            Value::Object(map) => map.get("changed").cloned().unwrap_or(Value::Bool(true)),
            _ => return Err("AttributeError"),
        }
    } else {
        Value::Bool(true)
    };
    if matches!(changed, Value::Bool(false)) {
        say(&format!(
            "thread {}: a notification card's cancel changed nothing; it had already finished",
            str_of(&thread_id)
        ));
        return Ok("already_finished".into());
    }
    say(&format!(
        "thread {}: cancelled from a notification card",
        str_of(&thread_id)
    ));
    if let Some(announce) = with.announce
        && pyval::truthy(&thread_id)
        && let Ok(found) = build_cancelled(speech, &thread_id, &with.stay)
    {
        let _ = announce(found);
    }
    Ok("cancelled".into())
}

/// `_power_stop(nonce, control, announce, say, stay)` (v0.6.12, the A28 amendment).
fn power_stop(speech: &Speech, nonce: &str, with: &Activation, say: &dyn Fn(&str)) -> Py<String> {
    let Some(control) = with.control else {
        say("notification: a power action's stop was ignored (no control layer)");
        return Ok("ignored".into());
    };
    let result = match control.stop_power_countdown(nonce, "toast") {
        Ok(result) => result,
        Err(raised) => {
            if let Some(code) = refusal(&raised) {
                say(&format!(
                    "notification: the power action's stop was refused ({code})"
                ));
                return Ok("refused".into());
            }
            say(&format!(
                "notification: the power action's stop failed ({})",
                raised.class
            ));
            return Ok("failed".into());
        }
    };
    if !pyval::is(&result, "stopped") {
        say("notification: a power action's stop named a batch that is over; nothing changed");
        return Ok("ignored".into());
    }
    say("power action stopped from a notification; this PC stays on this time");
    if let Some(announce) = with.announce
        && let Ok(found) = build_power_stopped(speech, &with.stay)
    {
        let _ = announce(found);
    }
    Ok("stopped".into())
}

/// `_account_changed_content(count, event, why)` (v0.6.20, v0.6.22).
pub fn account_changed_content(
    speech: &Speech,
    count: &Value,
    event: &str,
    why: &Value,
) -> Py<Map> {
    let open = vec![(speech.message("toast_button_open")?, open_page("pending"))];
    if event == "accounts_exhausted" {
        let (title, body) = if pyval::is(why, "not_finished") {
            (
                "toast_switch_not_finished",
                "toast_switch_not_finished_body",
            )
        } else {
            ("toast_accounts_exhausted", "toast_accounts_exhausted_body")
        };
        return Ok(notify::content(
            speech.message(title)?,
            speech.message(body)?,
            None,
            None,
            Vec::new(),
            open,
            None,
        ));
    }
    let waiting = match py::Whole::of(count) {
        Ok(whole) if whole.is_positive() => whole,
        _ => py::Whole::from_i64(1),
    };
    Ok(notify::content(
        speech.message("toast_account_changed")?,
        speech.message("toast_after_sleep_next")?,
        None,
        None,
        vec![
            speech
                .message("toast_account_changed_count")?
                .replace("{n}", &waiting.to_string()),
        ],
        open,
        None,
    ))
}
