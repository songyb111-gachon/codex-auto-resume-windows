//! car-surface's calls (S6.0): `surface.batch` takes `cases`, a list of `[name, arg, ...]`, and answers one entry per
//! case, `{"ok": value}` or `{"error": "ExceptionName"}`, as tests/rustdiff/surface.py's reference side writes them.
//!
//! The stand-ins are the ones that file describes, written here a second time: PowerShell and explorer.exe record what
//! would have been started (car-platform's own `pwsh::run` builds the request, a recording `Starter` takes it), the
//! presence answers and the card host's wakes are the case's, Windows' preferred languages are `["en-US"]`, and the
//! clock is car-platform's `Crt`. Nothing here starts a process, raises a notification or shows a window.

use std::cell::RefCell;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use car_brand::data::Num;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval::{self, Py};
use car_platform::localclock::Crt;
use car_platform::spawn::{Spawn, SpawnError, Starter, Stream};
use car_surface::notice_card::{self, CardMotion, FloatShadow, Frame};
use car_surface::notice_inbox::Inbox;
use car_surface::notice_presence::{self as presence, Answers};
use car_surface::notifier::{self, Activation, Notice};
use car_surface::popup::model::{self, Ctx, PopupModel};
use car_surface::popup::{placement, words};
use car_surface::py::{self, object, str_of, text_of};
use car_surface::seam::{
    CardControl, Launch, NotRun, PopupControl, PowerShell, Raised, StoredSettings,
    SystemPowerShell, TrayStore, TraySurface,
};
use car_surface::speech::Speech;
use car_surface::tray::stored::{Languages, Stored};
use car_surface::{codex_link, notice_uris, notify, pyurl, tray, usage};
use car_words::l10n;

use crate::leaves::Args;

fn ok(value: Value) -> Value {
    object([("ok", value)])
}

fn error(name: &str) -> Value {
    object([("error", Value::from(name))])
}

fn outcome(result: Py<Value>) -> Value {
    match result {
        Ok(value) => ok(value),
        Err(name) => error(name),
    }
}

fn opt(found: Option<String>) -> Value {
    found.map_or(Value::Null, Value::from)
}

fn text(value: &Value) -> String {
    match value {
        Value::Str(each) => text_of(each),
        other => str_of(other),
    }
}

fn number(value: &Value) -> Py<f64> {
    pyval::Num::of(value).map(|n| n.as_f64()).ok_or("TypeError")
}

fn int(value: &Value) -> Py<i64> {
    match value {
        Value::Int(int) => int.as_i64().ok_or("OverflowError"),
        Value::Bool(on) => Ok(i64::from(*on)),
        _ => Err("TypeError"),
    }
}

fn ints(value: &Value) -> Py<Vec<i64>> {
    py::items(value)?.iter().map(int).collect()
}

fn rect(value: &Value) -> Py<placement::Rect> {
    let found = ints(value)?;
    if found.len() != 4 {
        return Err("ValueError");
    }
    Ok([found[0], found[1], found[2], found[3]])
}

fn opt_rect(value: &Value) -> Py<Option<placement::Rect>> {
    match value {
        Value::Null => Ok(None),
        other => rect(other).map(Some),
    }
}

fn map_of(value: &Value) -> Map {
    match value {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    }
}

fn environ(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

fn windows() -> Vec<String> {
    vec!["en-US".to_owned()]
}

/// `l10n.set_preference(value)` and then `current()`.
fn speak(value: &Value) -> &'static str {
    let chosen = match value {
        Value::Str(each) => each
            .as_str()
            .filter(|each| l10n::CHOICES.contains(each))
            .unwrap_or(l10n::SYSTEM),
        _ => l10n::SYSTEM,
    };
    l10n::resolve(Some(chosen), &environ, &windows)
}

/// `strings_of(spec)`: `["catalog", locale]` as that catalog, anything else as given.
fn strings_of(spec: &Value) -> Map {
    if let Value::Array(items) = spec
        && items.len() == 2
        && pyval::is(&items[0], "catalog")
    {
        let mut made = Map::new();
        for (key, each) in l10n::catalog(pyval::text(&items[1]).unwrap_or("")) {
            made.insert(Str::from(key), Value::from(each));
        }
        return made;
    }
    map_of(spec)
}

fn notice_out(found: Option<&Notice>) -> Value {
    found.map_or(Value::Null, Notice::to_value)
}

/// The renderer's stand-in (tests/rustdiff/surface.py `measure`).
fn measure(role: &str, shown: &str, width: i64, wrap: bool) -> (i64, i64) {
    let size: i64 = match role {
        "label" => 14,
        "chip" => 12,
        "name" => 15,
        "body" => 14,
        "small" => 12,
        "button" => 14,
        _ => 13,
    };
    let mut w: i64 = shown
        .chars()
        .map(|c| if c.is_ascii() { 7 } else { 13 })
        .sum::<i64>()
        * size
        / 10;
    let mut lines = 1;
    if wrap && width > 0 && w > width {
        lines = (w + width - 1) / width;
        w = width;
    }
    (w, lines * (size + 6))
}

/// A stand-in's answer: the value, or the exception a `{"raise": class, "code": code}` spec names.
fn answer(spec: &Value) -> Result<Value, Raised> {
    if let Value::Object(map) = spec
        && let Some(class) = map.get("raise")
    {
        let code = map.get("code").cloned().unwrap_or(Value::Null);
        return Err(Raised::coded(&text(class), code));
    }
    Ok(spec.clone())
}

// ------------------------------------------------------------------ the recorders
struct Recorder {
    calls: RefCell<Vec<Value>>,
    outcome: Value,
}

impl Recorder {
    fn new(outcome: &Value) -> Recorder {
        Recorder {
            calls: RefCell::new(Vec::new()),
            outcome: outcome.clone(),
        }
    }

    fn calls(&self) -> Value {
        Value::Array(self.calls.borrow().clone())
    }
}

fn stream(each: Stream) -> Value {
    Value::from(match each {
        Stream::Null => "null",
        Stream::Inherit => "inherit",
        Stream::Piped => "other",
    })
}

impl Starter for Recorder {
    fn run(&self, spawn: &Spawn, timeout: Duration) -> Result<i32, SpawnError> {
        let env: Vec<Value> = spawn
            .env()
            .unwrap_or(&[])
            .iter()
            .filter(|(name, _)| {
                name.to_string_lossy()
                    .to_uppercase()
                    .starts_with("CODEX_AUTO_RESUME_ARG_")
            })
            .map(|(name, value)| {
                Value::Array(vec![
                    Value::from(name.to_string_lossy().as_ref()),
                    Value::from(value.to_string_lossy().as_ref()),
                ])
            })
            .collect();
        let seconds = timeout.as_secs_f64();
        let timeout = if seconds.fract() == 0.0 {
            Value::from(seconds as i64)
        } else {
            Value::Float(seconds)
        };
        self.calls.borrow_mut().push(object([
            ("argv", py::strings(spawn.argv())),
            ("env", Value::Array(env)),
            ("flags", Value::from(i64::from(spawn.flags()))),
            ("timeout", timeout),
            (
                "streams",
                Value::Array(vec![
                    stream(spawn.stdin),
                    stream(spawn.stdout),
                    stream(spawn.stderr),
                ]),
            ),
        ]));
        match &self.outcome {
            Value::Int(code) => Ok(code.as_i64().unwrap_or(0) as i32),
            other if pyval::is(other, "timeout") => Err(SpawnError::Timeout),
            _ => Err(SpawnError::Os(std::io::Error::other("not started"))),
        }
    }
}

impl Launch for Recorder {
    fn is_file(&self, path: &Path) -> bool {
        path.is_file()
    }

    fn start(&self, spawn: &Spawn) -> Py<()> {
        self.calls.borrow_mut().push(object([
            ("argv", py::strings(spawn.argv())),
            ("flags", Value::from(i64::from(spawn.flags()))),
            ("close_fds", Value::Bool(true)),
        ]));
        if pyval::is(&self.outcome, "oserror") {
            return Err("OSError");
        }
        Ok(())
    }
}

/// PowerShell present (the real `pwsh::executable`) or not.
struct Shell<'a> {
    inner: SystemPowerShell<'a>,
    available: bool,
}

impl PowerShell for Shell<'_> {
    fn available(&self) -> bool {
        self.available && self.inner.available()
    }

    fn run(&self, script: &str, values: &[(&str, &str)], timeout: Duration) -> Result<i32, NotRun> {
        self.inner.run(script, values, timeout)
    }
}

fn shown(result: Py<bool>, recorder: &Recorder) -> Value {
    object([
        ("result", outcome(result.map(Value::Bool))),
        ("calls", recorder.calls()),
    ])
}

fn toast_of(options: &Value) -> notify::Toast {
    let mut toast = notify::Toast::default();
    let map = map_of(options);
    for (name, slot) in [
        ("button", &mut toast.button),
        ("uri", &mut toast.uri),
        ("extra", &mut toast.extra),
        ("more", &mut toast.more),
        ("silent", &mut toast.silent),
        ("sound", &mut toast.sound),
        ("launch", &mut toast.launch),
        ("stays", &mut toast.stays),
    ] {
        if let Some(value) = map.get(name) {
            *slot = value.clone();
        }
    }
    toast
}

// ------------------------------------------------------------------ the cases
fn case(name: &str, a: &Args) -> Option<Py<Value>> {
    uris(name, a)
        .or_else(|| notify_case(name, a))
        .or_else(|| notifier_case(name, a))
        .or_else(|| card_case(name, a))
        .or_else(|| popup_case(name, a))
        .or_else(|| tray_case(name, a))
}

fn uris(name: &str, a: &Args) -> Option<Py<Value>> {
    let v = |at: usize| a.get(at);
    Some(match name {
        "uri.nfkc" => Ok(Value::Array(
            pyurl::NFKC_DELIMITERS
                .iter()
                .map(|point| Value::from(i64::from(*point)))
                .collect(),
        )),
        "uri.split" => pyurl::urlsplit(&text(v(0))).map(|parts| {
            py::strings([
                parts.scheme,
                parts.netloc,
                parts.path,
                parts.query,
                parts.fragment,
            ])
        }),
        "uri.qs" => {
            let mut map = Map::new();
            for (key, values) in pyurl::parse_qs(&text(v(0)), pyval::truthy(v(1))) {
                map.insert(Str::from(key), py::strings(values));
            }
            Ok(Value::Object(map))
        }
        "uri.parse_cancel" => Ok(opt(notice_uris::parse_cancel_uri(v(0)))),
        "uri.parse_open" => Ok(opt(notice_uris::parse_open_uri(v(0)))),
        "uri.parse_power" => Ok(opt(notice_uris::parse_power_stop_uri(v(0)))),
        "uri.asks_flag" => Ok(Value::Bool(notice_uris::cancel_asks_open_codex(v(0)))),
        "uri.with_flag" => Ok(notice_uris::with_open_codex_flag(v(0))),
        "uri.cancel" => Ok(Value::from(notice_uris::cancel_uri(v(0)))),
        "uri.open" => Ok(Value::from(notice_uris::open_uri(v(0)))),
        "uri.power" => Ok(Value::from(notice_uris::power_stop_uri(v(0)))),
        "link.codex" => Ok(opt(codex_link::codex_thread_uri(v(0)))),
        "link.chat" => Ok(opt(codex_link::chat_uri(v(0)))),
        "link.parse_codex" => Ok(opt(codex_link::parse_codex_thread_uri(v(0)))),
        "link.parse_chat" => Ok(opt(codex_link::parse_chat_uri(v(0)))),
        "link.open" => {
            let recorder = Recorder::new(v(2));
            let root = text(v(1));
            let result = codex_link::open_in_codex(v(0), Some(&root), &recorder);
            Ok(object([
                ("result", outcome(result.map(Value::Bool))),
                ("started", recorder.calls()),
            ]))
        }
        "presence.allowed" => {
            let map = map_of(v(0));
            let take = |key: &str| map.get(key).cloned().unwrap_or(Value::Null);
            Ok(Value::Bool(presence::card_allowed(&Answers {
                setting: take("setting"),
                tray_present: take("tray_present"),
                notification_state: take("notification_state"),
                notification_mode: take("notification_mode"),
                app_notifications: take("app_notifications"),
                screen_reader: take("screen_reader"),
                remote_session: take("remote_session"),
                session_locked: take("session_locked"),
            })))
        }
        "presence.numbers" => Ok(presence_numbers()),
        "inbox.script" => inbox_script(v(0)),
        _ => return None,
    })
}

fn presence_numbers() -> Value {
    let list = |found: &[i64]| Value::Array(found.iter().map(|n| Value::from(*n)).collect());
    let iid = |(a, b, c, d): (u32, u16, u16, [u8; 8])| {
        Value::Array(vec![
            Value::from(i64::from(a)),
            Value::from(i64::from(b)),
            Value::from(i64::from(c)),
            Value::Array(d.iter().map(|x| Value::from(i64::from(*x))).collect()),
        ])
    };
    Value::Array(vec![
        list(&presence::NOTIFICATION_STATES),
        list(&presence::NOTIFICATION_MODES),
        list(&presence::APP_SETTINGS),
        Value::from(i64::from(presence::SPI_GETSCREENREADER)),
        Value::from(i64::from(presence::SPI_GETMESSAGEDURATION)),
        Value::from(i64::from(presence::SM_REMOTESESSION)),
        Value::from(i64::from(presence::DESKTOP_READOBJECTS)),
        Value::from(i64::from(presence::UOI_NAME)),
        Value::from(presence::INPUT_DESKTOP),
        Value::from(presence::TOAST_MANAGER_CLASS),
        iid(presence::IID_MANAGER_STATICS),
        iid(presence::IID_MANAGER_STATICS5),
        iid(presence::IID_MANAGER_FOR_USER3),
        Value::from(presence::INSPECTABLE_SLOTS as i64),
        Value::from(presence::SLOT_CREATE_NOTIFIER_WITH_ID as i64),
        Value::from(presence::SLOT_NOTIFIER_SETTING as i64),
        Value::from(i64::from(presence::RO_INIT_MULTITHREADED)),
        Value::from(i64::from(presence::RPC_E_CHANGED_MODE)),
    ])
}

fn inbox_script(steps: &Value) -> Py<Value> {
    let inbox: Arc<Inbox<Value>> = Arc::new(Inbox::new());
    let wakes: Arc<Mutex<Vec<Value>>> = Arc::new(Mutex::new(Vec::new()));
    let mut out = Vec::new();
    let quiet = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    for step in py::items(steps)? {
        let parts = py::items(&step)?;
        let kind = parts.first().and_then(pyval::text).unwrap_or("");
        match kind {
            "attach" => {
                *wakes.lock().unwrap_or_else(|p| p.into_inner()) =
                    py::items(parts.get(1).unwrap_or(&Value::Null)).unwrap_or_default();
                let (box_ref, script) = (Arc::clone(&inbox), Arc::clone(&wakes));
                inbox.attach(Arc::new(move || {
                    let what = {
                        let mut left = script.lock().unwrap_or_else(|p| p.into_inner());
                        if left.is_empty() {
                            Value::Bool(true)
                        } else {
                            left.remove(0)
                        }
                    };
                    if pyval::is(&what, "raise") {
                        panic!("a wake that raises");
                    }
                    if pyval::is(&what, "take") {
                        box_ref.take();
                        return false;
                    }
                    pyval::truthy(&what)
                }));
                out.push(Value::Null);
            }
            "post" => out.push(Value::Bool(
                inbox.post(parts.get(1).cloned().unwrap_or(Value::Null)),
            )),
            "take" => out.push(Value::Array(inbox.take())),
            "detach" => out.push(Value::Array(inbox.detach())),
            _ => out.push(Value::Bool(inbox.attached())),
        }
    }
    std::panic::set_hook(quiet);
    // The wake holds the inbox: let both go.
    inbox.detach();
    Ok(Value::Array(out))
}

fn notify_case(name: &str, a: &Args) -> Option<Py<Value>> {
    if !name.starts_with("notify.") {
        return None;
    }
    let v = |at: usize| a.get(at);
    let content = |made: Py<Map>| made.map(Value::Object);
    match name {
        "notify.xml" => {
            return Some(notify::toast_xml(v(0), v(1), &toast_of(v(2))).map(Value::from));
        }
        "notify.show" => {
            let recorder = Recorder::new(v(4));
            let shell = Shell {
                inner: SystemPowerShell { starter: &recorder },
                available: pyval::truthy(v(3)),
            };
            let result = notify::show(&shell, v(0), v(1), &toast_of(v(2)));
            return Some(Ok(shown(result, &recorder)));
        }
        "notify.show_content" => {
            let recorder = Recorder::new(v(3));
            let shell = Shell {
                inner: SystemPowerShell { starter: &recorder },
                available: pyval::truthy(v(2)),
            };
            let result = notify::show_content(&shell, &map_of(v(0)), pyval::truthy(v(1)));
            return Some(Ok(shown(result, &recorder)));
        }
        "notify.consts" => {
            let pairs = |found: &[(&str, &str)]| {
                let mut map = Map::new();
                for (key, each) in found {
                    map.insert(Str::from(*key), Value::from(*each));
                }
                Value::Object(map)
            };
            return Some(Ok(Value::Array(vec![
                Value::from(notify::SCRIPT),
                Value::from(notify::MAX_TOAST_ACTIONS as i64),
                Value::from(notify::MAX_TOAST_LINES as i64),
                Value::from(notify::NEEDS_YOU_SOUND),
                Value::from(notify::DEFAULT_SOUND),
                Value::from(notify::aumid()),
                Value::from(notify::TIMEOUT_SECONDS as i64),
                Value::from(notify::LEGACY_POWERSHELL_AUMID),
                py::strings(notify::NEAR_LIMIT_KINDS),
                py::strings(notify::POWER_ACTIONS),
                pairs(&notify::NOT_RESUMED),
                pairs(&notify::HELD_MESSAGES),
                Value::from(notify::update_version_pattern()),
                Value::from(notify::CODEX_THREAD_LINK),
                Value::from(notify::SCHEME),
                Value::from(notify::OPEN_CODEX_FLAG),
            ])));
        }
        _ => {}
    }
    let locale = speak(v(0));
    let speech = Speech::new(locale, &Crt);
    let s = &speech;
    let w = |at: usize| a.get(at + 1);
    let is_true = |value: &Value| matches!(value, Value::Bool(true));
    Some(match name {
        "notify.headline" => notify::headline(s, w(0)).map(Value::from),
        "notify.origin" => notify::origin_line(s, w(0), &text(w(1)), w(2)).map(Value::from),
        "notify.scheduled" => content(notify::scheduled_content(
            s,
            w(0),
            w(1),
            w(2),
            w(3),
            w(4),
            w(5),
        )),
        "notify.objection" => content(notify::objection_content(s, w(0), w(1), w(2), w(3), w(4))),
        "notify.objection_message" => notify::objection_message(s, w(0)).map(Value::from),
        "notify.cancelled" => content(notify::cancelled_content(s, w(0))),
        "notify.starting" => content(notify::starting_content(s, w(0), w(1), is_true(w(2)))),
        "notify.resumed" => content(notify::resumed_content(s, w(0), w(1))),
        "notify.failed" => content(notify::attempt_failed_content(
            s,
            w(0),
            w(1),
            pyval::truthy(w(2)),
        )),
        "notify.stopped" => content(notify::stopped_content(s, w(0), w(1), w(2))),
        "notify.not_resumed" => content(notify::not_resumed_content(s, w(0), w(1), w(2), w(3))),
        "notify.not_resumed_message" => notify::not_resumed_message(s, w(0)).map(Value::from),
        "notify.held" => notify::held_message(s, w(0)).map(Value::from),
        "notify.needs_label" => notify::needs_you_label(s, w(0)).map(Value::from),
        "notify.needs_message" => notify::needs_you_message(s, w(0), w(1)).map(Value::from),
        "notify.needs" => content(notify::needs_you_content(
            s,
            w(0),
            w(1),
            w(2),
            w(3),
            is_true(w(4)),
        )),
        "notify.slept" => notify::slept_for(s, w(0)).map(Value::from),
        "notify.after_sleep" => content(notify::after_sleep_content(s, w(0), w(1))),
        "notify.memory" => content(notify::memory_content(s, w(0), w(1), w(2))),
        "notify.near" => content(notify::near_limit_content(s, w(0), w(1), w(2), w(3))),
        "notify.update" => notify::update_offered_content(s, w(0), w(1))
            .map(|found| found.map_or(Value::Null, Value::Object)),
        "notify.restart" => content(notify::restart_gave_up_content(s)),
        "notify.grace" => content(notify::power_grace_content(
            s,
            w(0),
            w(1),
            w(2),
            is_true(w(3)),
        )),
        "notify.power" => content(notify::power_content(s, w(0), w(1))),
        "notify.local_time" => s.local_time(w(0)).map(Value::from),
        _ => return None,
    })
}

fn built(
    speech: &Speech,
    event: &Value,
    detail: &Value,
    identity: &Value,
    sound: &Value,
    destination: &Value,
    stay: &Value,
) -> Py<Option<Notice>> {
    let destination = pyval::text(destination).unwrap_or("");
    notifier::build(
        speech,
        event,
        detail,
        identity,
        matches!(sound, Value::Bool(true)),
        destination,
        stay,
    )
}

fn plain(speech: &Speech, event: &Value, detail: &Value) -> Py<Option<Notice>> {
    built(
        speech,
        event,
        detail,
        &Value::Null,
        &Value::Bool(false),
        &Value::from("page"),
        &Value::Array(Vec::new()),
    )
}

fn pairs_of(value: &Value) -> Py<Vec<(Value, Value)>> {
    py::items(value)?.iter().map(py::pair).collect()
}

fn notifier_case(name: &str, a: &Args) -> Option<Py<Value>> {
    if !name.starts_with("notifier.") {
        return None;
    }
    let v = |at: usize| a.get(at);
    match name {
        "notifier.click_destination" => {
            return Some(Ok(Value::from(notifier::click_destination(
                v(0),
                matches!(v(1), Value::Bool(true)),
            ))));
        }
        "notifier.notice_page" => {
            return Some(
                pairs_of(v(1)).map(|pairs| Value::from(notifier::notice_page(&text(v(0)), &pairs))),
            );
        }
        "notifier.click_uri" => {
            return Some(pairs_of(v(1)).map(|pairs| {
                Value::from(notifier::click_uri(
                    &text(v(0)),
                    &pairs,
                    v(2),
                    pyval::text(v(3)).unwrap_or(""),
                ))
            }));
        }
        "notifier.toast_actions" => {
            return Some(notifier::toast_actions(&map_of(v(0))).map(|pairs| {
                Value::Array(
                    pairs
                        .into_iter()
                        .map(|(label, uri)| Value::Array(vec![label, uri]))
                        .collect(),
                )
            }));
        }
        "notifier.statuses" => {
            let mut map = Map::new();
            for (kind, status) in notifier::statuses() {
                map.insert(Str::from(kind), Value::from(status));
            }
            return Some(Ok(Value::Object(map)));
        }
        _ => {}
    }
    let locale = speak(v(0));
    let speech = Speech::new(locale, &Crt);
    let s = &speech;
    let w = |at: usize| a.get(at + 1);
    Some(match name {
        "notifier.build" => {
            built(s, w(0), w(1), w(2), w(3), w(4), w(5)).map(|found| notice_out(found.as_ref()))
        }
        "notifier.demo" => notifier::build_demo(s, w(0)).map(|found| found.to_value()),
        "notifier.cancelled" => {
            notifier::build_cancelled(s, w(0), w(1)).map(|found| found.to_value())
        }
        "notifier.power_stopped" => {
            notifier::build_power_stopped(s, w(0)).map(|found| found.to_value())
        }
        "notifier.open_codex" => (|| {
            let found = built(
                s,
                w(0),
                w(1),
                &Value::Null,
                &Value::Bool(false),
                w(2),
                &Value::Array(Vec::new()),
            )?;
            match found {
                None => Ok(Value::Null),
                Some(found) => Ok(notifier::with_open_codex(
                    &found,
                    matches!(w(3), Value::Bool(true)),
                )?
                .to_value()),
            }
        })(),
        "notifier.sounds" => built(
            s,
            w(0),
            w(1),
            &Value::Null,
            w(2),
            &Value::from("page"),
            &Value::Array(Vec::new()),
        )
        .and_then(|found| found.ok_or("AttributeError"))
        .map(|found| Value::Bool(notifier::sounds(&found))),
        "notifier.deliver" => deliver(s, w(0), w(1), w(2), w(3), w(4), w(5)),
        "notifier.complete" => complete(s, w(0), w(1), w(2), w(3)),
        "notifier.show_demo" => show_demo(s, w(0), w(1), w(2), w(3)),
        "notifier.told" => (|| {
            let found = plain(s, w(0), w(1))?.ok_or("AttributeError")?;
            let pending = w(3).clone();
            let opened = move || answer(&pending);
            let opener: Option<&dyn Fn() -> Result<Value, Raised>> = if matches!(w(3), Value::Null)
            {
                None
            } else {
                Some(&opened)
            };
            notifier::told(&found, w(2), opener, w(4).clone())
        })(),
        "notifier.activate" => activate(s, w(0), w(1), w(2), w(3), w(4), w(5), w(6)),
        _ => return None,
    })
}

fn host(spec: &Value) -> Option<Inbox<Notice>> {
    if matches!(spec, Value::Null) {
        return None;
    }
    let inbox = Inbox::new();
    if !pyval::is(spec, "detached") {
        let wakes = pyval::is(spec, "wakes");
        inbox.attach(Arc::new(move || wakes));
    }
    Some(inbox)
}

fn probe_of(answers: &Value) -> impl Fn() -> Result<Value, Raised> + use<> {
    let answers = answers.clone();
    move || {
        if pyval::is(&answers, "raise") {
            Err(Raised::new("OSError"))
        } else {
            Ok(answers.clone())
        }
    }
}

fn taken(inbox: &Option<Inbox<Notice>>) -> Value {
    match inbox {
        None => Value::Null,
        Some(inbox) => Value::Array(inbox.take().iter().map(Notice::to_value).collect()),
    }
}

fn recording_show<'a>(
    shown: &'a Value,
    calls: &'a RefCell<Vec<Value>>,
) -> impl Fn(&Map, bool) -> Py<bool> + 'a {
    move |content: &Map, silent: bool| {
        calls.borrow_mut().push(Value::Array(vec![
            Value::Object(content.clone()),
            Value::Bool(silent),
        ]));
        if pyval::is(shown, "raise") {
            return Err("ValueError");
        }
        Ok(pyval::truthy(shown))
    }
}

fn deliver(
    s: &Speech,
    event: &Value,
    detail: &Value,
    host_spec: &Value,
    setting: &Value,
    answers: &Value,
    shown: &Value,
) -> Py<Value> {
    let sound = Value::Bool(pyval::is(event, "needs_you"));
    let found = built(
        s,
        event,
        detail,
        &Value::Null,
        &sound,
        &Value::from("page"),
        &Value::Array(Vec::new()),
    )?
    .ok_or("AttributeError")?;
    let inbox = host(host_spec);
    let calls = RefCell::new(Vec::new());
    let show = recording_show(shown, &calls);
    let result = notifier::deliver(&found, inbox.as_ref(), setting, &probe_of(answers), &show)
        .map(|(route, done)| Value::Array(vec![Value::from(route), Value::Bool(done)]));
    Ok(object([
        ("result", outcome(result)),
        ("calls", Value::Array(calls.borrow().clone())),
        ("taken", taken(&inbox)),
    ]))
}

fn complete(
    s: &Speech,
    event: &Value,
    detail: &Value,
    card_shown: &Value,
    shown: &Value,
) -> Py<Value> {
    let found = if pyval::is(event, "demo") {
        notifier::build_demo(s, detail)?
    } else {
        plain(s, event, detail)?.ok_or("AttributeError")?
    };
    let calls = RefCell::new(Vec::new());
    let show = recording_show(shown, &calls);
    let result = notifier::complete(&found, card_shown, &show).map(Value::Bool);
    Ok(object([
        ("result", outcome(result)),
        ("calls", Value::Array(calls.borrow().clone())),
    ]))
}

fn show_demo(
    s: &Speech,
    now: &Value,
    host_spec: &Value,
    setting: &Value,
    answers: &Value,
) -> Py<Value> {
    let found = notifier::build_demo(s, now)?;
    let inbox = host(host_spec);
    let result = notifier::show_demo(&found, inbox.as_ref(), setting, &probe_of(answers));
    Ok(object([
        ("result", Value::Bool(result)),
        ("taken", taken(&inbox)),
    ]))
}

struct Control<'a> {
    spec: &'a Value,
    calls: &'a RefCell<Vec<Value>>,
}

impl Control<'_> {
    fn field(&self, name: &str) -> Value {
        map_of(self.spec).get(name).cloned().unwrap_or(Value::Null)
    }
}

impl CardControl for Control<'_> {
    fn cancel_interruption(&self, interruption_id: &str, actor: &str) -> Result<Value, Raised> {
        self.calls
            .borrow_mut()
            .push(py::strings(["cancel", interruption_id, actor]));
        answer(&self.field("cancel"))
    }

    fn stop_power_countdown(&self, nonce: &str, actor: &str) -> Result<Value, Raised> {
        self.calls
            .borrow_mut()
            .push(py::strings(["stop", nonce, actor]));
        answer(&self.field("stop"))
    }
}

#[allow(clippy::too_many_arguments)]
fn activate(
    s: &Speech,
    uri: &Value,
    control_spec: &Value,
    opener: &Value,
    announce: &Value,
    log: &Value,
    chat: &Value,
    stay: &Value,
) -> Py<Value> {
    let calls = RefCell::new(Vec::new());
    let lines = RefCell::new(Vec::new());
    let announced = RefCell::new(Vec::new());
    let control = Control {
        spec: control_spec,
        calls: &calls,
    };
    let opening = |what: &'static str| {
        let calls = &calls;
        move |value: &str| -> Result<Value, Raised> {
            calls
                .borrow_mut()
                .push(Value::Array(vec![Value::from(what), Value::from(value)]));
            answer(opener)
        }
    };
    let dashboard = opening("dashboard");
    let link = opening("link");
    let open_chat = opening("chat");
    let announcing = |found: Notice| -> Result<(), Raised> {
        if pyval::is(announce, "raise") {
            return Err(Raised::new("OSError"));
        }
        announced.borrow_mut().push(found.to_value());
        Ok(())
    };
    let logging = |line: &str| -> Result<(), Raised> {
        if pyval::is(log, "raise") {
            return Err(Raised::new("OSError"));
        }
        lines.borrow_mut().push(Value::from(line));
        Ok(())
    };
    let no_opener = matches!(opener, Value::Null);
    let with = Activation {
        control: if matches!(control_spec, Value::Null) {
            None
        } else {
            Some(&control)
        },
        open_dashboard: if no_opener { None } else { Some(&dashboard) },
        announce: if pyval::truthy(announce) {
            Some(&announcing)
        } else {
            None
        },
        log: if pyval::truthy(log) {
            Some(&logging)
        } else {
            None
        },
        open_link: if no_opener { None } else { Some(&link) },
        stay: stay.clone(),
        open_chat: if no_opener || !pyval::truthy(chat) {
            None
        } else {
            Some(&open_chat)
        },
    };
    let result = notifier::activate(s, uri, &with).map(Value::from);
    Ok(object([
        ("result", outcome(result)),
        ("log", Value::Array(lines.into_inner())),
        ("announced", Value::Array(announced.into_inner())),
        ("calls", Value::Array(calls.into_inner())),
    ]))
}

fn num(value: Num) -> Value {
    match value {
        Num::I(int) => Value::from(int),
        Num::F(x) => Value::Float(x),
    }
}

fn num_of(value: &Value) -> Py<Num> {
    match value {
        Value::Int(int) => int.as_i64().map(Num::I).ok_or("OverflowError"),
        Value::Bool(on) => Ok(Num::I(i64::from(*on))),
        Value::Float(x) => Ok(Num::F(*x)),
        _ => Err("TypeError"),
    }
}

fn shadow_value(shadow: &FloatShadow) -> Value {
    Value::Array(vec![
        num(shadow.dx),
        num(shadow.dy),
        num(shadow.blur),
        Value::from(shadow.colour.as_str()),
        num(shadow.alpha),
    ])
}

fn shadows_of(value: &Value) -> Py<Vec<FloatShadow>> {
    let mut found = Vec::new();
    for each in py::items(value)? {
        let parts = py::items(&each)?;
        if parts.len() != 5 {
            return Err("TypeError");
        }
        found.push(FloatShadow {
            dx: num_of(&parts[0])?,
            dy: num_of(&parts[1])?,
            blur: num_of(&parts[2])?,
            colour: text(&parts[3]),
            alpha: num_of(&parts[4])?,
        });
    }
    Ok(found)
}

fn frame_value(frame: Frame) -> Value {
    Value::Array(vec![
        Value::Float(frame.alpha),
        Value::Float(frame.offset),
        Value::Float(frame.scale),
        Value::Float(frame.depth),
    ])
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn unhex(text: &str) -> Py<Vec<u8>> {
    (0..text.len() / 2)
        .map(|i| u8::from_str_radix(&text[i * 2..i * 2 + 2], 16).map_err(|_| "ValueError"))
        .collect()
}

fn opt_f64(value: &Value) -> Py<Option<f64>> {
    match value {
        Value::Null => Ok(None),
        other => number(other).map(Some),
    }
}

fn card_case(name: &str, a: &Args) -> Option<Py<Value>> {
    let v = |at: usize| a.get(at);
    let card = |locale: &Value, event: &Value, detail: &Value, identity: &Value| -> Py<Map> {
        let speech = Speech::new(speak(locale), &Crt);
        let found = built(
            &speech,
            event,
            detail,
            identity,
            &Value::Bool(false),
            &Value::from("page"),
            &Value::Array(Vec::new()),
        )?
        .ok_or("AttributeError")?;
        Ok(notice_card::view(&found))
    };
    Some(match name {
        "card.view" => card(v(0), v(1), v(2), v(3)).map(Value::Object),
        "card.texts" => card(v(0), v(1), v(2), v(3))
            .and_then(|vm| notice_card::texts(&vm))
            .map(Value::Array),
        "card.layout" => card(v(0), v(1), v(2), v(3)).and_then(|mut vm| {
            vm.insert(Str::from("scene"), v(5).clone());
            notice_card::layout(&vm, v(4), &measure)
        }),
        "card.layout_vm" => notice_card::layout(&map_of(v(0)), v(1), &measure),
        "card.mirror" => notice_card::mirror(v(0)),
        "card.consts" => Ok(card_consts()),
        "card.entrance" => number(v(0))
            .map(|elapsed| frame_value(notice_card::entrance(elapsed, pyval::truthy(v(1))))),
        "card.leaving" => (|| {
            notice_card::leaving(
                number(v(0))?,
                number(v(1))?,
                pyval::truthy(v(2)),
                number(v(3))?,
            )
            .map(Value::Float)
        })(),
        "card.ease_in" => number(v(0)).map(|p| Value::Float(notice_card::ease_in(p))),
        "card.rise" => notice_card::rise_vector(v(0))
            .map(|(x, y)| Value::Array(vec![Value::from(x), Value::from(y)])),
        "card.hold_ms" => notice_card::hold_ms(v(0)).map(Value::Float),
        "card.depth_level" => number(v(0)).map(|d| Value::from(notice_card::depth_level(d))),
        "card.motion" => motion(v(0)),
        "popup.edge" => (|| {
            Ok(Value::from(placement::taskbar_edge(
                rect(v(0))?,
                rect(v(1))?,
                opt_rect(v(2))?,
            )))
        })(),
        "popup.place" => (|| {
            let size = ints(v(0))?;
            let cursor = match v(4) {
                Value::Null => None,
                other => {
                    let found = ints(other)?;
                    Some((found[0], found[1]))
                }
            };
            let (x, y, edge) = placement::place(
                (size[0], size[1]),
                rect(v(1))?,
                rect(v(2))?,
                opt_rect(v(3))?,
                cursor,
                int(v(5))?,
            );
            Ok(Value::Array(vec![
                Value::from(x),
                Value::from(y),
                Value::from(edge),
            ]))
        })(),
        "card.stack" => (|| {
            let mut sizes = Vec::new();
            for each in py::items(v(0))? {
                let pair = ints(&each)?;
                sizes.push((pair[0], pair[1]));
            }
            let (positions, edge) = notice_card::stack_positions(
                &sizes,
                rect(v(1))?,
                rect(v(2))?,
                opt_rect(v(3))?,
                int(v(4))?,
                int(v(5))?,
            );
            let positions = positions
                .into_iter()
                .map(|(x, y)| Value::Array(vec![Value::from(x), Value::from(y)]))
                .collect();
            Ok(Value::Array(vec![
                Value::Array(positions),
                Value::from(edge),
            ]))
        })(),
        "card.direction" => (|| {
            Ok(Value::from(notice_card::stack_direction(
                &text(v(0)),
                int(v(1))?,
                int(v(2))?,
                rect(v(3))?,
            )))
        })(),
        "card.float_shadows" => notice_card::float_shadows(pyval::text(v(0)), pyval::text(v(1)))
            .map(|found| Value::Array(found.iter().map(shadow_value).collect())),
        "card.shadow_at" => (|| {
            let found = notice_card::shadow_at(&shadows_of(v(0))?, number(v(1))?);
            Ok(Value::Array(found.iter().map(shadow_value).collect()))
        })(),
        "card.shadow_margin" => (|| {
            Ok(Value::from(notice_card::shadow_margin(
                &shadows_of(v(0))?,
                number(v(1))?,
            )))
        })(),
        "card.corner" => (|| {
            let rows = notice_card::corner_coverage(number(v(0))?, opt_f64(v(1))?)?;
            Ok(py::strings(rows.iter().map(|row| hex(row))))
        })(),
        "card.premultiply" => (|| {
            let pixels = unhex(&text(v(0)))?;
            let found = notice_card::premultiply(
                &pixels,
                int(v(1))?,
                int(v(2))?,
                number(v(3))?,
                int(v(4))?,
                opt_f64(v(5))?,
            )?;
            Ok(Value::from(hex(&found)))
        })(),
        _ => return None,
    })
}

fn card_consts() -> Value {
    let f = |x: f64| Value::from(x as i64);
    let mut depth = Map::new();
    for (name, value) in notice_card::DEPTH_START {
        depth.insert(Str::from(name), Value::Float(value));
    }
    Value::Array(vec![
        Value::from(notice_card::WIDTH),
        Value::from(notice_card::card_width()),
        Value::from(notice_card::MAX_CARDS),
        Value::from(notice_card::FRAME_MS),
        Value::from(notice_card::BREATH_FRAME_MS),
        f(notice_card::ENTRANCE_MS),
        f(notice_card::EXIT_MS),
        f(notice_card::SLIDE_MS),
        f(notice_card::SWAP_MS),
        Value::from(notice_card::STACK_DELAY_MS),
        f(notice_card::HOLD_MS),
        f(notice_card::HOVER_GRACE_MS),
        f(notice_card::RISE),
        Value::Float(notice_card::SCALE_FROM),
        Value::Float(notice_card::ALPHA_SHARE),
        Value::Object(depth),
        Value::from(notice_card::DEPTH_LEVELS),
        Value::from(notice_card::FLOAT_SHADOW_INK),
        Value::from(notice_card::FLOAT_SHADOW_THEME),
        Value::Float(notice_card::DARK_ENOUGH),
        Value::from(notice_card::HEADER_KEY),
        Value::from(notice_card::USUAL_HEIGHT),
        Value::Float(notice_card::UNTIL_CLICKED),
    ])
}

fn motion_state(m: &CardMotion) -> Value {
    let list = |found: &Option<Vec<i64>>| match found {
        None => Value::Null,
        Some(found) => Value::Array(found.iter().map(|n| Value::from(*n)).collect()),
    };
    let slide = match m.slide() {
        None => Value::Null,
        Some((start, target, began)) => Value::Array(vec![
            list(&Some(start)),
            list(&Some(target)),
            Value::Float(began),
        ]),
    };
    object([
        ("phase", Value::from(m.phase)),
        ("since", Value::Float(m.since)),
        ("hold_ms", Value::Float(m.hold_ms)),
        ("hold_left", Value::Float(m.hold_left)),
        ("paused", Value::Bool(m.paused)),
        ("from_alpha", Value::Float(m.from_alpha)),
        ("exit_ms", Value::Float(m.exit_ms)),
        ("final", Value::Bool(m.is_final)),
        ("position", list(&m.position)),
        ("slide", slide),
    ])
}

fn motion(steps: &Value) -> Py<Value> {
    let mut m: Option<CardMotion> = None;
    let mut out = Vec::new();
    for step in py::items(steps)? {
        let parts = py::items(&step)?;
        let at = |index: usize| parts.get(index).cloned().unwrap_or(Value::Null);
        let kind = pyval::text(&at(0)).unwrap_or("").to_owned();
        if kind == "new" {
            let position = match at(4) {
                Value::Null => None,
                other => Some(ints(&other)?),
            };
            m = Some(CardMotion::new(
                number(&at(1))?,
                number(&at(2))?,
                pyval::truthy(&at(3)),
                position,
            ));
            out.push(Value::Null);
            continue;
        }
        let card = m.as_mut().ok_or("AttributeError")?;
        out.push(match kind.as_str() {
            "frame" => frame_value(card.frame(number(&at(1))?)?),
            "pause" => {
                card.pause(number(&at(1))?, pyval::truthy(&at(2)))?;
                Value::Null
            }
            "retire" => {
                card.retire(number(&at(1))?, pyval::truthy(&at(2)))?;
                Value::Null
            }
            "restart" => {
                card.restart(number(&at(1))?);
                Value::Null
            }
            "delay" => {
                card.delay(number(&at(1))?);
                Value::Null
            }
            "move" => {
                card.move_to(number(&at(1))?, ints(&at(2))?, number(&at(3))?);
                Value::Null
            }
            "place" => match card.place(number(&at(1))?) {
                None => Value::Null,
                Some(found) => Value::Array(found.into_iter().map(Value::from).collect()),
            },
            "moving" => Value::Bool(card.moving(number(&at(1))?)),
            "wait" => card
                .wait_ms(number(&at(1))?)
                .map_or(Value::Null, Value::Float),
            "gone" => Value::Bool(card.gone()),
            _ => motion_state(card),
        });
    }
    Ok(Value::Array(out))
}

// ------------------------------------------------------------------ the popup and the icon
fn rows_of(value: &Value) -> Py<Option<Vec<Value>>> {
    match value {
        Value::Null => Ok(None),
        other => py::items(other).map(Some),
    }
}

fn popup_case(name: &str, a: &Args) -> Option<Py<Value>> {
    if !name.starts_with("popup.") {
        return None;
    }
    let v = |at: usize| a.get(at);
    let ctx_for = |current: &Value| Ctx {
        current: speak(current),
        clock: &Crt,
    };
    Some(match name {
        "popup.say" => {
            let fields: Vec<(String, String)> = map_of(v(2))
                .iter()
                .map(|(key, each)| (text_of(key), str_of(each)))
                .collect();
            let borrowed: Vec<(&str, String)> = fields
                .iter()
                .map(|(key, each)| (key.as_str(), each.clone()))
                .collect();
            Ok(Value::from(words::say(
                &strings_of(v(0)),
                &text(v(1)),
                &borrowed,
            )))
        }
        "popup.locale_of" => Ok(Value::from(words::locale_of(
            &strings_of(v(0)),
            speak(v(1)),
        ))),
        "popup.kept" => {
            let keep = words::kept(&strings_of(v(0)), speak(v(1)));
            Ok(Value::from(keep(&text(v(2)))))
        }
        "popup.vocabulary" => {
            let found = words::vocabulary(v(0), &environ, &windows);
            Ok(object([
                ("n", Value::from(found.len() as i64)),
                (
                    "title",
                    found.get("tray.title").cloned().unwrap_or(Value::Null),
                ),
                (
                    "probe",
                    found
                        .get("activity.monitoring")
                        .cloned()
                        .unwrap_or(Value::Null),
                ),
            ]))
        }
        "popup.one_line" => int(v(1)).map(|limit| Value::from(words::one_line(v(0), limit))),
        "popup.activity" => rows_of(v(1))
            .and_then(|rows| model::activity(v(0), rows.as_deref(), v(2)).map(Value::from)),
        "popup.light" => rows_of(v(2))
            .and_then(|rows| model::light_for(v(0), &text(v(1)), rows.as_deref()).map(Value::from)),
        "popup.icon_attention" => rows_of(v(1))
            .and_then(|rows| model::icon_attention(v(0), rows.as_deref()).map(Value::Bool)),
        "popup.known_running" => rows_of(v(1))
            .and_then(|rows| model::watcher_known_running(v(0), rows.as_deref()).map(Value::Bool)),
        "popup.snapshot_activity" => {
            model::snapshot_activity(v(0), v(1), pyval::truthy(v(2))).map(Value::from)
        }
        "popup.urgency" => model::urgency(v(0)).map(Value::Array),
        "popup.is_waiting" => model::is_waiting(v(0)).map(Value::Bool),
        // Integration 12: the v0.6.26 final's `newest_reading`, for test_status_newest_usage through surfaceproxy.
        "popup.newest_reading" => model::newest_reading(v(0)),
        "popup.blocked" => Ok(Value::Bool(model::blocked(v(0)))),
        "popup.task" => {
            let ctx = ctx_for(v(3));
            let strings = strings_of(v(1));
            let keep = words::kept(&strings, ctx.current);
            model::task_item(v(0), &strings, v(2), &keep).map(Value::Object)
        }
        "popup.row_menu" => model::row_menu(v(0), &strings_of(v(1)), v(2)),
        "popup.view_model" => rows_of(v(0)).and_then(|rows| {
            let ctx = ctx_for(v(6));
            model::view_model(
                &ctx,
                rows.as_deref(),
                v(1),
                &strings_of(v(2)),
                v(3),
                v(4).clone(),
                v(5).clone(),
            )
            .map(Value::Object)
        }),
        "popup.newest" => usage::newest(v(0), v(1)),
        "popup.perform" => perform(v(0), v(1), v(2), v(3)),
        "popup.busy_key" => py::items(v(0))
            .and_then(|action| model::busy_key(&action))
            .map(|key| key.map_or(Value::Null, Value::Array)),
        "popup.select" => (|| {
            Ok(Value::from(model::select_action(
                pyval::truthy(v(0)),
                number(v(1))?,
                opt_f64(v(2))?,
                opt_f64(v(3))?,
                opt_f64(v(4))?,
                pyval::truthy(v(5)),
            )))
        })(),
        "popup.model" => popup_script(v(0), v(1), v(2)),
        _ => return None,
    })
}

struct Popup<'a> {
    spec: &'a Value,
    calls: &'a RefCell<Vec<Value>>,
}

impl Popup<'_> {
    fn answer(&self, name: &str, args: Vec<Value>) -> Result<Value, Raised> {
        let mut call = vec![Value::from(name)];
        call.extend(args);
        self.calls.borrow_mut().push(Value::Array(call));
        let spec = map_of(self.spec)
            .get(name)
            .cloned()
            .unwrap_or_else(|| object([("ok", Value::Bool(true))]));
        answer(&spec)
    }
}

impl PopupControl for Popup<'_> {
    fn list_pending(&self, source: Option<&Value>) -> Result<Value, Raised> {
        self.answer("list_pending", vec![source.cloned().unwrap_or(Value::Null)])
    }

    fn get_status(&self) -> Result<Value, Raised> {
        self.answer("get_status", vec![])
    }

    fn set_enabled(&self, enabled: bool) -> Result<Value, Raised> {
        self.answer("set_enabled", vec![Value::Bool(enabled)])
    }

    fn set_interruption_recovery(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        enabled: bool,
    ) -> Result<Value, Raised> {
        self.answer(
            "set_interruption_recovery",
            vec![
                interruption_id.clone(),
                thread_id.clone(),
                Value::Bool(enabled),
            ],
        )
    }

    fn postpone(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        preset: &Value,
    ) -> Result<Value, Raised> {
        self.answer(
            "postpone",
            vec![interruption_id.clone(), thread_id.clone(), preset.clone()],
        )
    }

    fn unpostpone(&self, interruption_id: &Value, thread_id: &Value) -> Result<Value, Raised> {
        self.answer(
            "unpostpone",
            vec![interruption_id.clone(), thread_id.clone()],
        )
    }

    fn release_hold(&self, interruption_id: &Value, thread_id: &Value) -> Result<Value, Raised> {
        self.answer(
            "release_hold",
            vec![interruption_id.clone(), thread_id.clone()],
        )
    }

    fn set_thread_tier(
        &self,
        thread_id: &Value,
        tier: &Value,
        interruption_id: &Value,
    ) -> Result<Value, Raised> {
        self.answer(
            "set_thread_tier",
            vec![thread_id.clone(), tier.clone(), interruption_id.clone()],
        )
    }

    fn set_project_rule(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        always: bool,
        source: Option<&Value>,
    ) -> Result<Value, Raised> {
        self.answer(
            "set_project_rule",
            vec![
                interruption_id.clone(),
                thread_id.clone(),
                Value::Bool(always),
                source.cloned().unwrap_or(Value::Null),
            ],
        )
    }

    fn set_once_words(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        words: &Value,
    ) -> Result<Value, Raised> {
        self.answer(
            "set_once_words",
            vec![interruption_id.clone(), thread_id.clone(), words.clone()],
        )
    }
}

fn perform(action: &Value, spec: &Value, source: &Value, dashboard: &Value) -> Py<Value> {
    let calls = RefCell::new(Vec::new());
    let control = Popup {
        spec,
        calls: &calls,
    };
    let opener = |row: Option<(Value, Value, Value)>| -> Result<Value, Raised> {
        let shown = match row {
            None => Value::Null,
            Some((a, b, c)) => Value::Array(vec![a, b, c]),
        };
        calls
            .borrow_mut()
            .push(Value::Array(vec![Value::from("dashboard"), shown]));
        answer(dashboard)
    };
    let source = match source {
        Value::Null => None,
        other => Some(other),
    };
    let action = py::items(action)?;
    let (verdict, payload) = model::perform(
        &action,
        &control,
        source,
        if matches!(dashboard, Value::Null) {
            None
        } else {
            Some(&opener)
        },
    );
    Ok(object([
        ("result", Value::Array(vec![Value::from(verdict), payload])),
        ("calls", Value::Array(calls.into_inner())),
    ]))
}

fn sorted_keys(busy: &[Vec<Value>]) -> Value {
    let mut found: Vec<String> = busy
        .iter()
        .map(|key| to_string(&Value::Array(key.clone()), &Options::new()).unwrap_or_default())
        .collect();
    found.sort();
    py::strings(found)
}

fn popup_state(m: &PopupModel) -> Value {
    object([
        (
            "rows",
            m.rows
                .as_ref()
                .map_or(Value::Null, |rows| Value::Array(rows.clone())),
        ),
        ("status", m.status.clone().unwrap_or(Value::Null)),
        ("read_failed", Value::Bool(m.read_failed)),
        (
            "notice_key",
            m.notice_key.as_deref().map_or(Value::Null, Value::from),
        ),
        ("notice_until", Value::Float(m.notice_until)),
        ("busy", sorted_keys(m.busy())),
        (
            "drawn_paused",
            m.drawn_paused.map_or(Value::Null, Value::Bool),
        ),
        ("wants_read", Value::Bool(m.wants_read)),
    ])
}

fn popup_script(strings: &Value, current: &Value, steps: &Value) -> Py<Value> {
    let ctx = Ctx {
        current: speak(current),
        clock: &Crt,
    };
    let mut m = PopupModel::new(strings_of(strings));
    let mut out = Vec::new();
    for step in py::items(steps)? {
        let parts = py::items(&step)?;
        let at = |index: usize| parts.get(index).cloned().unwrap_or(Value::Null);
        let kind = pyval::text(&at(0)).unwrap_or("").to_owned();
        let result: Py<Value> = match kind.as_str() {
            "view" => m.view(&ctx, &at(1)).map(Value::Object),
            "apply" => (|| {
                let action = py::items(&at(1))?;
                let answered = py::items(&at(2))?;
                m.apply_outcome(&action, &answered, number(&at(3))?)?;
                Ok(Value::Null)
            })(),
            "begin" => py::items(&at(1)).and_then(|action| m.begin(&action).map(Value::Bool)),
            "action_for" => py::items(&at(1)).and_then(|target| {
                m.action_for(&target)
                    .map(|found| found.map_or(Value::Null, Value::Array))
            }),
            "menu_for" => m.menu_for(&at(1)),
            "attention" => m.attention().map(Value::Bool),
            "popup_attention" => {
                let visible = at(1);
                let popup = if matches!(visible, Value::Null) {
                    None
                } else {
                    Some((pyval::truthy(&visible), &m))
                };
                tray::model::popup_attention(popup).map(Value::Bool)
            }
            _ => Ok(popup_state(&m)),
        };
        out.push(outcome(result));
    }
    Ok(Value::Array(out))
}

struct Tray<'a> {
    spec: &'a Value,
}

impl Tray<'_> {
    fn field(&self, name: &str) -> Py<Value> {
        answer(&map_of(self.spec).get(name).cloned().unwrap_or(Value::Null))
            .map_err(|raised| class_name(&raised.class))
    }
}

/// An exception's class as the harness's error word: the names the stand-ins raise.
fn class_name(class: &str) -> &'static str {
    match class {
        "OSError" => "OSError",
        "ValueError" => "ValueError",
        "KeyError" => "KeyError",
        "TypeError" => "TypeError",
        "PermissionError" => "PermissionError",
        "FileNotFoundError" => "FileNotFoundError",
        "RuntimeError" => "RuntimeError",
        "AttributeError" => "AttributeError",
        _ => "Exception",
    }
}

impl TrayStore for Tray<'_> {
    fn pending(&self) -> Py<Vec<Value>> {
        py::items(&self.field("pending")?)
    }

    fn disabled_threads(&self) -> Py<Vec<Value>> {
        let found = py::items(&self.field("disabled")?)?;
        for each in &found {
            pyval::hashable(each)?;
        }
        Ok(found)
    }

    fn settings(&self) -> Py<Value> {
        self.field("settings")
    }

    fn failure_marks(&self) -> Py<Value> {
        self.field("marks")
    }
}

struct Settings<'a> {
    spec: RefCell<Value>,
    stamp: RefCell<Value>,
    record: &'a RefCell<Vec<Value>>,
}

impl StoredSettings for Settings<'_> {
    fn has_get_settings(&self) -> bool {
        map_of(&self.spec.borrow()).contains_key("settings")
    }

    fn get_settings(&self) -> Result<Value, Raised> {
        self.record
            .borrow_mut()
            .push(Value::Array(vec![Value::from("get_settings")]));
        answer(&map_of(&self.spec.borrow())["settings"])
    }

    fn settings_path(&self) -> Option<Result<Value, Raised>> {
        map_of(&self.spec.borrow()).get("path").map(answer)
    }

    fn stat(&self, path: &Value) -> Result<(i128, u64), Raised> {
        self.record
            .borrow_mut()
            .push(Value::Array(vec![Value::from("stat"), path.clone()]));
        let stamp = self.stamp.borrow().clone();
        if let Value::Array(parts) = &stamp {
            let mtime = parts
                .first()
                .and_then(|n| {
                    if let Value::Int(int) = n {
                        int.as_i64()
                    } else {
                        None
                    }
                })
                .unwrap_or(0);
            let size = parts
                .get(1)
                .and_then(|n| {
                    if let Value::Int(int) = n {
                        int.as_u64()
                    } else {
                        None
                    }
                })
                .unwrap_or(0);
            return Ok((i128::from(mtime), size));
        }
        answer(&stamp).and(Err(Raised::new("AttributeError")))
    }
}

struct Icon<'a> {
    strings: RefCell<Map>,
    adopt: RefCell<Value>,
    record: &'a RefCell<Vec<Value>>,
}

impl TraySurface for Icon<'_> {
    fn adopt_settings(&self, values: &Map) -> Result<(), Raised> {
        self.record.borrow_mut().push(Value::Array(vec![
            Value::from("adopt_settings"),
            Value::Object(values.clone()),
        ]));
        answer(&self.adopt.borrow()).map(|_| ())
    }

    fn strings(&self) -> Map {
        self.strings.borrow().clone()
    }

    fn set_strings(&self, strings: Map) {
        self.record.borrow_mut().push(Value::Array(vec![
            Value::from("set_strings"),
            strings.get("tray.title").cloned().unwrap_or(Value::Null),
            Value::from(strings.len() as i64),
        ]));
        *self.strings.borrow_mut() = strings;
    }

    fn set_reduce_motion(&self, value: &Value) {
        self.record.borrow_mut().push(Value::Array(vec![
            Value::from("reduce_motion"),
            value.clone(),
        ]));
    }

    fn log(&self, line: &str) {
        self.record
            .borrow_mut()
            .push(Value::Array(vec![Value::from("log"), Value::from(line)]));
    }
}

fn tray_case(name: &str, a: &Args) -> Option<Py<Value>> {
    let v = |at: usize| a.get(at);
    Some(match name {
        "tray.snapshot" => tray::model::snapshot_from(&Tray { spec: v(0) }),
        "tray.stored" => icon_script(v(0), v(1)),
        _ => return None,
    })
}

fn icon_script(strings: &Value, steps: &Value) -> Py<Value> {
    let record = RefCell::new(Vec::new());
    let settings = Settings {
        spec: RefCell::new(Value::Object(Map::new())),
        stamp: RefCell::new(Value::Null),
        record: &record,
    };
    let icon = Icon {
        strings: RefCell::new(strings_of(strings)),
        adopt: RefCell::new(Value::Null),
        record: &record,
    };
    let languages = Languages {
        environ: &environ,
        windows: &windows,
    };
    let mut kept = Stored::default();
    let mut out = Vec::new();
    for step in py::items(steps)? {
        let parts = py::items(&step)?;
        let at = |index: usize| parts.get(index).cloned().unwrap_or(Value::Null);
        match pyval::text(&at(0)).unwrap_or("") {
            "control" => {
                *settings.spec.borrow_mut() = at(1);
                out.push(Value::Null);
            }
            "stamp" => {
                *settings.stamp.borrow_mut() = at(1);
                out.push(Value::Null);
            }
            "adopt_raises" => {
                *icon.adopt.borrow_mut() = at(1);
                out.push(Value::Null);
            }
            "stored" => out.push(match kept.stored_settings(&settings) {
                Ok(found) => ok(found.map_or(Value::Null, Value::Object)),
                Err(raised) => error(&raised.class),
            }),
            "adopt" => {
                kept.adopt_settings(&settings, &icon, &languages);
                out.push(Value::Null);
            }
            "motion" => {
                kept.adopt_reduce_motion(&settings, &icon);
                out.push(Value::Null);
            }
            _ => out.push(object([
                (
                    "stamp",
                    kept.stamp.map_or(Value::Null, |(mtime, size)| {
                        Value::Array(vec![Value::from(mtime as i64), Value::from(size as i64)])
                    }),
                ),
                (
                    "values",
                    kept.values.clone().map_or(Value::Null, Value::Object),
                ),
                ("failed", Value::Bool(kept.motion_read_failed)),
            ])),
        }
    }
    Ok(object([
        ("out", Value::Array(out)),
        ("record", Value::Array(record.into_inner())),
    ]))
}

// ------------------------------------------------------------------ the batch
/// `surface.batch`: every case of `cases`, in order.
pub fn batch(cases: &Value) -> Value {
    let Value::Array(cases) = cases else {
        return Value::Null;
    };
    let mut answers = Vec::with_capacity(cases.len());
    for each in cases {
        let Value::Array(parts) = each else {
            answers.push(error("TypeError"));
            continue;
        };
        let name = parts.first().map(text).unwrap_or_default();
        let args = Args(&parts[1..]);
        let found = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| case(&name, &args)));
        answers.push(match found {
            Ok(Some(Ok(value))) => ok(value),
            Ok(Some(Err(name))) => error(name),
            Ok(None) => error(&format!("NotPorted:{name}")),
            Err(_) => error("RustPanic"),
        });
    }
    Value::Array(answers)
}
