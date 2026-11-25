//! `notify.py`: what every toast says (`*_content`, pure), the toast's XML document, and raising it.
//!
//! The toast travels as an environment variable into a constant PowerShell script, never as script text (`SCRIPT`,
//! issue #65: `-Command` plain text, never an encoded command), under the product's AppUserModelID; `show` hands
//! both to [`PowerShell`](crate::seam::PowerShell), which car-platform's `pwsh` runs with `CREATE_NO_WINDOW`. Nothing
//! about the interrupted work is disclosed: a name, a project, a shortened time and the exact conversation id.

use std::time::Duration;

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Py};
use car_platform::startup::AUMID as PRODUCT_AUMID;
use car_policy::classify::vocab_gen::needsyou as needsyou_steps;
use car_policy::classify::{needsyou, reasons};

use crate::notice_uris::{cancel_uri, open_page, power_stop_uri};
use crate::py::{self, Whole, str_of};
use crate::seam::PowerShell;
use crate::speech::{Speech, format};

pub use crate::codex_link::{
    CODEX_THREAD_LINK, chat_uri, codex_thread_uri, open_in_codex, parse_chat_uri,
    parse_codex_thread_uri,
};
pub use crate::notice_uris::{
    OPEN_CODEX_FLAG, SCHEME, cancel_asks_open_codex, open_uri, parse_cancel_uri, parse_open_uri,
    parse_power_stop_uri, with_open_codex_flag,
};

pub const LEGACY_POWERSHELL_AUMID: &str =
    r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe";
pub const TIMEOUT_SECONDS: u64 = 20;

/// `notify.aumid()`: the AppUserModelID every toast is raised under (`startup.AUMID`).
pub fn aumid() -> &'static str {
    PRODUCT_AUMID
}

/// `_SCRIPT`: the constant the toast's values travel beside.
pub const SCRIPT: &str = "
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($env:CODEX_AUTO_RESUME_ARG_XML)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
if ($env:CODEX_AUTO_RESUME_ARG_SILENT -eq '1') { $toast.SuppressPopup = $true }
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:CODEX_AUTO_RESUME_ARG_AUMID).Show($toast)
";

/// Windows shows at most five buttons on a toast.
pub const MAX_TOAST_ACTIONS: usize = 5;
/// Windows renders at most three `<text>` elements in a ToastGeneric binding.
pub const MAX_TOAST_LINES: usize = 3;
pub const NEEDS_YOU_SOUND: &str = "ms-winsoundevent:Notification.Reminder";
pub const DEFAULT_SOUND: &str = "ms-winsoundevent:Notification.Default";
pub const NEAR_LIMIT_KINDS: [&str; 3] = ["not_stopped", "press_resume", "not_continued"];
pub const POWER_ACTIONS: [&str; 3] = ["sleep", "hibernate", "shut_down"];
/// `NOT_RESUMED`: a record born stopped, and the sentence it is said with.
pub const NOT_RESUMED: [(&str, &str); 2] = [
    ("parent_handed_over", "toast_handed_over_body"),
    ("parent_cancelled", "toast_parent_cancelled_body"),
];
/// `HELD_MESSAGES`.
pub const HELD_MESSAGES: [(&str, &str); 4] = [
    ("ask", "toast_held"),
    ("notify_only", "toast_notify_only"),
    ("workspace_changed", "toast_workspace_changed"),
    ("context_cost", "toast_context_cost"),
];

// ------------------------------------------------------------------------- the document
/// `xml.sax.saxutils.escape(text)`: a TypeError-free text only (`.replace` of anything else is an AttributeError).
fn escape_text(value: &Value) -> Py<String> {
    match value {
        Value::Str(text) => Ok(py::text_of(text)
            .replace('&', "&amp;")
            .replace('>', "&gt;")
            .replace('<', "&lt;")),
        _ => Err("AttributeError"),
    }
}

/// `xml.sax.saxutils.quoteattr(text)`.
fn quoteattr(value: &Value) -> Py<String> {
    let data = escape_text(value)?
        .replace('\n', "&#10;")
        .replace('\r', "&#13;")
        .replace('\t', "&#9;");
    Ok(if data.contains('"') {
        if data.contains('\'') {
            format!("\"{}\"", data.replace('"', "&quot;"))
        } else {
            format!("'{data}'")
        }
    } else {
        format!("\"{data}\"")
    })
}

/// The buttons a toast shows, as `_toast_xml` and `notifier.toast_actions` lay them out: (button, uri) when both are
/// truthy, then each truthy pair of `more`, at most five.
/// `more` is iterated as it is (`_toast_xml`) or as `more or ()` (`toast_actions`, `or_empty`).
pub fn action_pairs(
    button: &Value,
    uri: &Value,
    more: &Value,
    or_empty: bool,
) -> Py<Vec<(Value, Value)>> {
    let mut pairs = Vec::new();
    if pyval::truthy(button) && pyval::truthy(uri) {
        pairs.push((button.clone(), uri.clone()));
    }
    let empty = Value::Array(Vec::new());
    let more = if or_empty { py::or(more, &empty) } else { more };
    for entry in py::items(more)? {
        let (label, target) = py::pair(&entry)?;
        if pyval::truthy(&label) && pyval::truthy(&target) {
            pairs.push((label, target));
        }
    }
    pairs.truncate(MAX_TOAST_ACTIONS);
    Ok(pairs)
}

/// What `show` is given beside the title and the body (its keyword arguments, defaults included).
#[derive(Clone, Debug)]
pub struct Toast {
    pub button: Value,
    pub uri: Value,
    pub extra: Value,
    pub more: Value,
    pub silent: Value,
    pub sound: Value,
    pub launch: Value,
    pub stays: Value,
}

impl Default for Toast {
    fn default() -> Toast {
        Toast {
            button: Value::Null,
            uri: Value::Null,
            extra: Value::Array(Vec::new()),
            more: Value::Array(Vec::new()),
            silent: Value::Bool(false),
            sound: Value::Null,
            launch: Value::Null,
            stays: Value::Bool(false),
        }
    }
}

/// `_toast_xml(title, body, button, uri, extra, more, silent, sound, launch, stays)`: `silent`, `stays` and `launch` by
/// their truth, `sound` only as exactly True or False (`show` hands it `silent is True`, `stays is True`, a bool or
/// None for `sound` and a text or None for `launch`).
pub fn toast_xml(title: &Value, body: &Value, toast: &Toast) -> Py<String> {
    let pairs = action_pairs(&toast.button, &toast.uri, &toast.more, false)?;
    let stays = pyval::truthy(&toast.stays);
    let mut actions = String::new();
    if !pairs.is_empty() {
        let mut each = Vec::new();
        for (label, target) in &pairs {
            each.push(format!(
                "<action content={} activationType=\"protocol\" arguments={}/>",
                quoteattr(label)?,
                quoteattr(target)?
            ));
        }
        actions = format!("<actions>{}</actions>", each.concat());
    } else if stays {
        actions =
            "<actions><action activationType=\"system\" arguments=\"dismiss\" content=\"\"/></actions>"
                .into();
    }
    let mut lines = vec![title.clone()];
    lines.extend(py::items(&toast.extra)?);
    lines.push(body.clone());
    let lines: Vec<Value> = lines
        .into_iter()
        .filter(pyval::truthy)
        .take(MAX_TOAST_LINES)
        .collect();
    let mut text = String::new();
    for line in &lines {
        text.push_str(&format!("<text>{}</text>", escape_text(line)?));
    }
    let silent = pyval::truthy(&toast.silent);
    let mut audio = if silent || matches!(toast.sound, Value::Bool(false)) {
        "<audio silent=\"true\"/>".to_owned()
    } else if matches!(toast.sound, Value::Bool(true)) {
        format!("<audio src=\"{NEEDS_YOU_SOUND}\"/>")
    } else {
        String::new()
    };
    if stays && audio.is_empty() {
        audio = format!("<audio src=\"{DEFAULT_SOUND}\"/>");
    }
    let mut opens = if pyval::truthy(&toast.launch) {
        format!(
            " launch={} activationType=\"protocol\"",
            quoteattr(&toast.launch)?
        )
    } else {
        String::new()
    };
    if stays {
        opens.push_str(" scenario=\"reminder\"");
    }
    Ok(format!(
        "<toast duration=\"long\"{opens}><visual><binding template=\"ToastGeneric\">{text}</binding></visual>{audio}{actions}</toast>"
    ))
}

/// `show(title, body, **options)`: best effort, Ok(true) only when PowerShell reported success. The document and the
/// identity travel as values (`XML`, `AUMID`, and `SILENT` for the history copy). An exception building the document
/// is raised, as the reference raises it; PowerShell's own failures are Ok(false).
pub fn show(powershell: &dyn PowerShell, title: &Value, body: &Value, toast: &Toast) -> Py<bool> {
    if !powershell.available() {
        return Ok(false);
    }
    let silent = matches!(toast.silent, Value::Bool(true));
    let shaped = Toast {
        silent: Value::Bool(silent),
        sound: match toast.sound {
            Value::Bool(_) => toast.sound.clone(),
            _ => Value::Null,
        },
        launch: match toast.launch {
            Value::Str(_) => toast.launch.clone(),
            _ => Value::Null,
        },
        stays: Value::Bool(matches!(toast.stays, Value::Bool(true))),
        ..toast.clone()
    };
    let xml = toast_xml(title, body, &shaped)?;
    let mut values: Vec<(&str, &str)> = vec![("XML", xml.as_str()), ("AUMID", aumid())];
    if silent {
        values.push(("SILENT", "1"));
    }
    Ok(matches!(
        powershell.run(SCRIPT, &values, Duration::from_secs(TIMEOUT_SECONDS)),
        Ok(0)
    ))
}

/// `show_content(content, silent=...)`: raise the toast one of the `*_content` functions describes. A content with
/// no title or body is a KeyError.
pub fn show_content(powershell: &dyn PowerShell, content: &Map, silent: bool) -> Py<bool> {
    let mut toast = Toast::default();
    for (name, slot) in [
        ("button", &mut toast.button),
        ("uri", &mut toast.uri),
        ("extra", &mut toast.extra),
        ("more", &mut toast.more),
        ("sound", &mut toast.sound),
        ("launch", &mut toast.launch),
        ("stays", &mut toast.stays),
    ] {
        if let Some(value) = content.get(name) {
            *slot = value.clone();
        }
    }
    if silent {
        toast.silent = Value::Bool(true);
    }
    let title = content.get("title").ok_or("KeyError")?;
    let body = content.get("body").ok_or("KeyError")?;
    show(powershell, title, body, &toast)
}

// ------------------------------------------------------------------------- the lines
fn identity_of(identity: &Value) -> Map {
    match identity {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    }
}

fn stripped(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::Str(text)) => {
            let text = py::text_of(text);
            let kept = car_machine::pytext::strip(&text).to_owned();
            (!kept.is_empty()).then_some(kept)
        }
        _ => None,
    }
}

/// `headline(identity)`: the title, then the project, then the working directory's name, else "Unnamed".
pub fn headline(speech: &Speech, identity: &Value) -> Py<String> {
    let identity = identity_of(identity);
    for key in ["name", "project", "cwd_basename"] {
        if let Some(value) = stripped(identity.get(key)) {
            return Ok(value);
        }
    }
    speech.message("toast_unnamed")
}

fn second_line(identity: &Value, used: &str) -> Option<String> {
    let identity = identity_of(identity);
    ["project", "cwd_basename"]
        .into_iter()
        .filter_map(|key| stripped(identity.get(key)))
        .find(|value| value != used)
}

fn thread_line(speech: &Speech, thread_id: &Value) -> Py<String> {
    format(
        &speech.message("toast_thread")?,
        &[("uuid", speech.run(thread_id))],
    )
}

/// `_origin_line(identity, used, thread_id)`: where this task lives, and which conversation it is exactly.
pub fn origin_line(speech: &Speech, identity: &Value, used: &str, thread_id: &Value) -> Py<String> {
    let thread = thread_line(speech, thread_id)?;
    Ok(match second_line(identity, used) {
        Some(secondary) => format!(
            "{}  \u{b7}  {thread}",
            speech.run(&Value::from(secondary.as_str()))
        ),
        None => thread,
    })
}

/// `_content(title, body, *, button, uri, extra, more, sound)`: only what was given is kept.
pub fn content(
    title: String,
    body: String,
    button: Option<String>,
    uri: Option<String>,
    extra: Vec<String>,
    more: Vec<(String, String)>,
    sound: Option<bool>,
) -> Map {
    let mut made = Map::new();
    made.insert(Str::from("title"), Value::from(title));
    made.insert(Str::from("body"), Value::from(body));
    if let Some(button) = button.filter(|each| !each.is_empty()) {
        made.insert(Str::from("button"), Value::from(button));
    }
    if let Some(uri) = uri.filter(|each| !each.is_empty()) {
        made.insert(Str::from("uri"), Value::from(uri));
    }
    if !extra.is_empty() {
        made.insert(Str::from("extra"), py::strings(extra));
    }
    if !more.is_empty() {
        let pairs = more
            .into_iter()
            .map(|(label, target)| Value::Array(vec![Value::from(label), Value::from(target)]))
            .collect();
        made.insert(Str::from("more"), Value::Array(pairs));
    }
    if let Some(sound) = sound {
        made.insert(Str::from("sound"), Value::Bool(sound));
    }
    made
}

fn open_button(speech: &Speech, page: &str) -> Py<Vec<(String, String)>> {
    Ok(vec![(
        speech.message("toast_button_open")?,
        open_page(page),
    )])
}

/// `held_message(hold)`: the sentence for an interruption that waits for a person.
pub fn held_message(speech: &Speech, hold: &Value) -> Py<String> {
    pyval::hashable(hold)?;
    let key = HELD_MESSAGES
        .iter()
        .find(|(name, _)| pyval::is(hold, name))
        .map_or("toast_held", |(_, key)| key);
    speech.message(key)
}

/// `_reason_label(category)`: the reason's catalog label.
pub fn reason_label(speech: &Speech, category: &Value) -> Py<String> {
    speech.text(&reasons::label_key(category)?, &[])
}

fn cancel_button(speech: &Speech, category: &Value) -> Py<String> {
    speech.message(if pyval::is(category, "usage_limit") {
        "toast_button_cancel"
    } else {
        "toast_button_no_retry"
    })
}

/// `scheduled_content(thread_id, interruption_id, reset_at, category, identity, hold)`: the detection toast.
pub fn scheduled_content(
    speech: &Speech,
    thread_id: &Value,
    interruption_id: &Value,
    reset_at: &Value,
    category: &Value,
    identity: &Value,
    hold: &Value,
) -> Py<Map> {
    let usage = pyval::is(category, "usage_limit");
    let title = headline(speech, identity)?;
    if !matches!(hold, Value::Null) {
        let origin = origin_line(speech, identity, &title, thread_id)?;
        let button = cancel_button(speech, category)?;
        let uri = cancel_uri(interruption_id);
        let extra = format!(
            "{} \u{b7} {}",
            reason_label(speech, category)?,
            held_message(speech, hold)?
        );
        let more = open_button(speech, "pending")?;
        return Ok(content(
            title,
            origin,
            Some(button),
            Some(uri),
            vec![extra],
            more,
            None,
        ));
    }
    let (body, button) = if usage {
        let body = if pyval::truthy(reset_at) {
            let template = speech.message("toast_usage_at")?;
            format(&template, &[("time", speech.local_time(reset_at)?)])?
        } else {
            speech.message("toast_usage_soon")?
        };
        (body, speech.message("toast_button_cancel")?)
    } else {
        let label = reason_label(speech, category)?;
        let body = format!("{label} \u{b7} {}", speech.message("toast_transient")?);
        (body, speech.message("toast_button_no_retry")?)
    };
    let origin = origin_line(speech, identity, &title, thread_id)?;
    let uri = cancel_uri(interruption_id);
    let more = open_button(speech, "pending")?;
    Ok(content(
        title,
        origin,
        Some(button),
        Some(uri),
        vec![body],
        more,
        None,
    ))
}

/// `objection_message(until)`.
pub fn objection_message(speech: &Speech, until: &Value) -> Py<String> {
    let template = speech.message("toast_objection")?;
    format(&template, &[("time", speech.local_time(until)?)])
}

/// `objection_content(thread_id, interruption_id, until, category, identity)`: the objection window (v0.6.11).
pub fn objection_content(
    speech: &Speech,
    thread_id: &Value,
    interruption_id: &Value,
    until: &Value,
    category: &Value,
    identity: &Value,
) -> Py<Map> {
    let title = headline(speech, identity)?;
    let origin = origin_line(speech, identity, &title, thread_id)?;
    let button = cancel_button(speech, category)?;
    let uri = cancel_uri(interruption_id);
    let label = reason_label(speech, category)?;
    let extra = format!("{label} \u{b7} {}", objection_message(speech, until)?);
    let more = open_button(speech, "pending")?;
    Ok(content(
        title,
        origin,
        Some(button),
        Some(uri),
        vec![extra],
        more,
        None,
    ))
}

/// `cancelled_content(thread_id)`.
pub fn cancelled_content(speech: &Speech, thread_id: &Value) -> Py<Map> {
    Ok(content(
        speech.message("toast_cancelled_title")?,
        thread_line(speech, thread_id)?,
        None,
        None,
        vec![speech.message("toast_cancelled_body")?],
        Vec::new(),
        None,
    ))
}

/// `starting_content(thread_id, identity, task_changed)`.
pub fn starting_content(
    speech: &Speech,
    thread_id: &Value,
    identity: &Value,
    task_changed: bool,
) -> Py<Map> {
    let mut body = speech.message("toast_starting_body")?;
    if task_changed {
        body = format!("{body} \u{b7} {}", speech.message("toast_task_changed")?);
    }
    let title = headline(speech, identity)?;
    let origin = origin_line(speech, identity, &headline(speech, identity)?, thread_id)?;
    Ok(content(
        title,
        origin,
        None,
        None,
        vec![body],
        Vec::new(),
        None,
    ))
}

/// `resumed_content(thread_id, identity)`.
pub fn resumed_content(speech: &Speech, thread_id: &Value, identity: &Value) -> Py<Map> {
    let title = speech.message("toast_resumed_title")?;
    let origin = origin_line(speech, identity, &title, thread_id)?;
    Ok(content(
        title,
        origin,
        None,
        None,
        vec![speech.message("toast_resumed_body")?],
        Vec::new(),
        None,
    ))
}

/// `attempt_failed_content(thread_id, identity, certain)`.
pub fn attempt_failed_content(
    speech: &Speech,
    thread_id: &Value,
    identity: &Value,
    certain: bool,
) -> Py<Map> {
    let title = speech.message(if certain {
        "toast_failed_title"
    } else {
        "toast_unknown_title"
    })?;
    let body = speech.message(if certain {
        "toast_failed_body"
    } else {
        "toast_unknown_body"
    })?;
    let origin = origin_line(speech, identity, &title, thread_id)?;
    Ok(content(
        title,
        origin,
        None,
        None,
        vec![body],
        Vec::new(),
        None,
    ))
}

/// `stopped_content(thread_id, identity, reason)`.
pub fn stopped_content(
    speech: &Speech,
    thread_id: &Value,
    identity: &Value,
    reason: &Value,
) -> Py<Map> {
    let title = speech.message("toast_exhausted_title")?;
    let key = if pyval::is(reason, "no_progress") {
        "toast_no_progress_body"
    } else if pyval::is(reason, "attempts") {
        "toast_exhausted_body"
    } else if pyval::is(reason, "time") {
        "toast_time_cap_body"
    } else {
        "toast_stopped_body"
    };
    let body = speech.message(key)?;
    let origin = origin_line(speech, identity, &title, thread_id)?;
    Ok(content(
        title,
        origin,
        None,
        None,
        vec![body],
        Vec::new(),
        None,
    ))
}

/// `reason in NOT_RESUMED`.
pub fn is_not_resumed(reason: &Value) -> Py<bool> {
    pyval::hashable(reason)?;
    Ok(NOT_RESUMED.iter().any(|(name, _)| pyval::is(reason, name)))
}

/// `not_resumed_message(reason)`: a KeyError for a reason not in NOT_RESUMED.
pub fn not_resumed_message(speech: &Speech, reason: &Value) -> Py<String> {
    pyval::hashable(reason)?;
    let key = NOT_RESUMED
        .iter()
        .find(|(name, _)| pyval::is(reason, name))
        .map(|(_, key)| *key)
        .ok_or("KeyError")?;
    speech.message(key)
}

/// `not_resumed_content(thread_id, identity, reason, category)` (2026-10-22).
pub fn not_resumed_content(
    speech: &Speech,
    thread_id: &Value,
    identity: &Value,
    reason: &Value,
    category: &Value,
) -> Py<Map> {
    let title = headline(speech, identity)?;
    let origin = origin_line(speech, identity, &title, thread_id)?;
    let extra = format!(
        "{} \u{b7} {}",
        reason_label(speech, category)?,
        not_resumed_message(speech, reason)?
    );
    Ok(content(
        title,
        origin,
        None,
        None,
        vec![extra],
        Vec::new(),
        None,
    ))
}

/// `needs_you_label(kind)`.
pub fn needs_you_label(speech: &Speech, kind: &Value) -> Py<String> {
    if pyval::is(kind, needsyou::STALLED) {
        return speech.message("needs_you_stalled_label");
    }
    reason_label(speech, kind)
}

/// `needs_you_message(kind, minutes)`: the one next step for this kind, `{minutes}` an int above 0 or 10.
pub fn needs_you_message(speech: &Speech, kind: &Value, minutes: &Value) -> Py<String> {
    pyval::hashable(kind)?;
    let steps = &needsyou_steps::NEXT_STEPS;
    let key = pyval::text(kind)
        .and_then(|kind| steps.get(kind))
        .or_else(|| steps.get("terminal_failure"))
        .and_then(car_machine::vocab::Node::as_str)
        .ok_or("KeyError")?;
    let count = match minutes {
        Value::Int(int) if py::whole_of_int(int).is_positive() => int.to_string(),
        _ => "10".to_owned(),
    };
    Ok(speech
        .message(key.strip_prefix("msg.").unwrap_or(key))?
        .replace("{minutes}", &count))
}

/// `needs_you_content(thread_id, kind, identity, minutes, sound)` (v0.6.11).
pub fn needs_you_content(
    speech: &Speech,
    thread_id: &Value,
    kind: &Value,
    identity: &Value,
    minutes: &Value,
    sound: bool,
) -> Py<Map> {
    let title = headline(speech, identity)?;
    let origin = origin_line(speech, identity, &title, thread_id)?;
    let extra = format!(
        "{} \u{b7} {}",
        needs_you_label(speech, kind)?,
        needs_you_message(speech, kind, minutes)?
    );
    let more = open_button(speech, "settings")?;
    Ok(content(
        title,
        origin,
        None,
        None,
        vec![extra],
        more,
        Some(sound),
    ))
}

/// `max(1, int(value))`, 1 where `int` raises.
fn at_least_one(value: &Value) -> Whole {
    match Whole::of(value) {
        Ok(whole) if whole.is_positive() => whole,
        _ => Whole::from_i64(1),
    }
}

/// `slept_for(seconds)`: how long this PC slept, in hours and minutes.
pub fn slept_for(speech: &Speech, seconds: &Value) -> Py<String> {
    let minutes = match Whole::of(seconds) {
        Ok(whole) if !whole.negative => {
            let (quotient, _) = whole.divmod(60);
            if quotient.is_zero() {
                Whole::from_i64(1)
            } else {
                quotient
            }
        }
        _ => Whole::from_i64(1),
    };
    let (hours, rest) = minutes.divmod(60);
    let mut parts = Vec::new();
    if !hours.is_zero() {
        parts.push(speech.text("time.hours", &[("n", hours.to_string())])?);
    }
    if rest != 0 || hours.is_zero() {
        parts.push(speech.text("time.minutes", &[("n", rest.to_string())])?);
    }
    Ok(parts.join(" "))
}

/// `after_sleep_content(slept, count)` (v0.6.11).
pub fn after_sleep_content(speech: &Speech, slept: &Value, count: &Value) -> Py<Map> {
    let waiting = at_least_one(count);
    let title = speech
        .message("toast_after_sleep")?
        .replace("{time}", &slept_for(speech, slept)?);
    let body = speech.message("toast_after_sleep_next")?;
    let extra = speech
        .message("toast_after_sleep_count")?
        .replace("{n}", &waiting.to_string());
    Ok(content(
        title,
        body,
        None,
        None,
        vec![extra],
        open_button(speech, "pending")?,
        None,
    ))
}

/// `memory_content(event, used, limit)` (v0.6.11).
pub fn memory_content(speech: &Speech, event: &Value, used: &Value, limit: &Value) -> Py<Map> {
    let whole = |value: &Value| match Whole::of(value) {
        Ok(found) if found.negative => "0".to_owned(),
        Ok(found) => found.to_string(),
        Err(_) => "?".to_owned(),
    };
    let stopped = pyval::is(event, "memory_stopped");
    let body = speech
        .message("toast_memory_body")?
        .replace("{used}", &whole(used))
        .replace("{limit}", &whole(limit));
    let title = speech.message(if stopped {
        "toast_memory_stopped"
    } else {
        "toast_memory_warning"
    })?;
    let extra = speech.message(if stopped {
        "toast_memory_stopped_next"
    } else {
        "toast_memory_warning_next"
    })?;
    let page = if stopped { "overview" } else { "diagnostics" };
    Ok(content(
        title,
        body,
        None,
        None,
        vec![extra],
        open_button(speech, page)?,
        None,
    ))
}

/// `kind in NEAR_LIMIT_KINDS`.
pub fn near_limit_kind(kind: &Value) -> Option<&'static str> {
    NEAR_LIMIT_KINDS
        .into_iter()
        .find(|each| pyval::is(kind, each))
}

/// `near_limit_content(minutes, percent, reset_at, kind)`: the advanced edition's usage meter at a warning, the share
/// LEFT as every glance surface says it, or (v0.6.16-beta.4) its forced stop's notice.
pub fn near_limit_content(
    speech: &Speech,
    minutes: &Value,
    percent: &Value,
    reset_at: &Value,
    kind: &Value,
) -> Py<Map> {
    if let Some(kind) = near_limit_kind(kind) {
        return Ok(content(
            speech.message(&format!("toast_near_limit_{kind}"))?,
            speech.message(&format!("near_limit_{kind}_body"))?,
            None,
            None,
            Vec::new(),
            open_button(speech, "overview")?,
            None,
        ));
    }
    let say = |key: &str, fields: &[(&str, String)]| speech.text(key, fields);
    let share = match percent {
        Value::Bool(_) => None,
        _ => Whole::of(percent).ok().map(|used| {
            let clamped = if used.negative {
                0
            } else {
                used.small().map_or(100, |small| small.min(100))
            };
            100 - clamped
        }),
    };
    let window = match minutes {
        Value::Int(int) if py::whole_of_int(int).is_positive() => {
            let whole = py::whole_of_int(int);
            if whole.small() == Some(7 * 24 * 60) {
                say("usage.weekly", &[])?
            } else {
                let (days, day_rest) = whole.divmod(1440);
                let (hours, hour_rest) = whole.divmod(60);
                if day_rest == 0 {
                    say("usage.days", &[("n", days.to_string())])?
                } else if hour_rest == 0 {
                    say("usage.hours", &[("n", hours.to_string())])?
                } else {
                    say("usage.minutes", &[("n", whole.to_string())])?
                }
            }
        }
        _ => say("usage.limit", &[])?,
    };
    let body = match share {
        None => window,
        Some(share) => match reset_at {
            Value::Int(_) => say(
                "usage.window_resets",
                &[
                    ("window", window),
                    ("percent", share.to_string()),
                    ("time", speech.local_time(reset_at)?),
                ],
            )?,
            _ => say(
                "usage.window",
                &[("window", window), ("percent", share.to_string())],
            )?,
        },
    };
    Ok(content(
        speech.message("toast_near_limit")?,
        body,
        None,
        None,
        Vec::new(),
        open_button(speech, "overview")?,
        None,
    ))
}

/// Digits `[0-9]` from `at`: how many.
fn digits_at(text: &[u8], at: usize) -> usize {
    text[at..].iter().take_while(|b| b.is_ascii_digit()).count()
}

/// `UPDATE_VERSION.match(version)`: `ids.PRODUCT_RELEASE` and an optional `ids.PRODUCT_STAGE`, then the end.
pub fn update_version(version: &str) -> bool {
    let text = version.as_bytes();
    let mut at = 0;
    for part in 0..3 {
        let run = digits_at(text, at);
        let number = &text[at..at + run];
        let ok = number == b"0" || ((1..=6).contains(&run) && number[0] != b'0');
        if !ok {
            return false;
        }
        at += run;
        if part < 2 {
            if text.get(at) != Some(&b'.') {
                return false;
            }
            at += 1;
        }
    }
    if at == text.len() {
        return true;
    }
    let rest = &text[at..];
    let after = if let Some(tail) = rest.strip_prefix(b"-alpha") {
        tail
    } else if let Some(tail) = rest.strip_prefix(b"-beta") {
        tail
    } else {
        return false;
    };
    if after.is_empty() {
        return true;
    }
    let Some(stage) = after.strip_prefix(b".") else {
        return false;
    };
    let run = digits_at(stage, 0);
    run == stage.len()
        && match run {
            1 => (b'2'..=b'9').contains(&stage[0]),
            2 | 3 => stage[0] != b'0',
            _ => false,
        }
}

/// `UPDATE_VERSION`'s two halves, as `ids` writes them (held to the reference by the diff).
pub fn update_version_pattern() -> String {
    format!("{}({})?\\Z", ids_release(), ids_stage())
}

fn ids_release() -> &'static str {
    r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})"
}

fn ids_stage() -> &'static str {
    r"-(alpha|beta)(\.([2-9]|[1-9][0-9]{1,2}))?"
}

/// `update_offered_content(version, prerelease)` (v0.6.18): None for a version of any other shape.
pub fn update_offered_content(
    speech: &Speech,
    version: &Value,
    prerelease: &Value,
) -> Py<Option<Map>> {
    let Some(text) = pyval::text(version).filter(|text| update_version(text)) else {
        return Ok(None);
    };
    let body = speech.message(if pyval::truthy(prerelease) {
        "toast_update_offered_prerelease_body"
    } else {
        "toast_update_offered_body"
    })?;
    Ok(Some(content(
        speech.message("toast_update_offered")?,
        body.replace("{version}", &speech.run(&Value::from(text))),
        None,
        None,
        Vec::new(),
        open_button(speech, "diagnostics")?,
        None,
    )))
}

/// `restart_gave_up_content()` (v0.6.19).
pub fn restart_gave_up_content(speech: &Speech) -> Py<Map> {
    Ok(content(
        speech.message("toast_restart_gave_up")?,
        speech.message("toast_restart_gave_up_body")?,
        None,
        None,
        Vec::new(),
        open_button(speech, "overview")?,
        None,
    ))
}

/// `_power_word(action)`.
pub fn power_word(action: &Value) -> &'static str {
    POWER_ACTIONS
        .into_iter()
        .find(|each| pyval::is(action, each))
        .unwrap_or("sleep")
}

/// `power_grace_content(action, until, nonce, tasks)` (v0.6.12).
pub fn power_grace_content(
    speech: &Speech,
    action: &Value,
    until: &Value,
    nonce: &Value,
    tasks: bool,
) -> Py<Map> {
    let word = power_word(action);
    let title = speech
        .message(&format!("toast_power_grace.{word}"))?
        .replace("{time}", &speech.local_time(until)?);
    let body = speech.message(if tasks {
        "toast_power_grace_body_tasks"
    } else {
        "toast_power_grace_body"
    })?;
    Ok(content(
        title,
        body,
        Some(speech.message(&format!("toast_power_stop.{word}"))?),
        Some(power_stop_uri(nonce)),
        vec![speech.message("toast_power_grace_next")?],
        open_button(speech, "settings")?,
        None,
    ))
}

/// `power_content(event, detail)`: the power action's notice for `event`.
pub fn power_content(speech: &Speech, event: &Value, detail: &Value) -> Py<Map> {
    let empty = Value::Object(Map::new());
    let detail = match detail {
        Value::Object(_) => detail,
        _ => &empty,
    };
    let field = |name: &str| pyval::get(detail, name).cloned().unwrap_or(Value::Null);
    let action = power_word(&field("action"));
    let tasks = matches!(field("tasks"), Value::Bool(true));
    let plain = |title: String, body: String, page: Option<&str>| -> Py<Map> {
        let more = match page {
            Some(page) => open_button(speech, page)?,
            None => Vec::new(),
        };
        Ok(content(title, body, None, None, Vec::new(), more, None))
    };
    if pyval::is(event, "power_grace") {
        return power_grace_content(
            speech,
            &Value::from(action),
            &field("until"),
            &field("nonce"),
            tasks,
        );
    }
    if pyval::is(event, "power_now") {
        return plain(
            speech.message(&format!("toast_power_now.{action}"))?,
            String::new(),
            None,
        );
    }
    if pyval::is(event, "power_failed") {
        return plain(
            speech.message("toast_power_failed")?,
            speech.message("toast_power_failed_body")?,
            Some("settings"),
        );
    }
    if pyval::is(event, "power_not_met") {
        let key = if tasks {
            "toast_power_not_met_tasks"
        } else {
            "toast_power_not_met"
        };
        return plain(speech.message(key)?, String::new(), Some("settings"));
    }
    plain(speech.message("toast_power_stopped")?, String::new(), None)
}

/// `str(value)`, for a caller that writes a value into a sentence.
pub fn shown(value: &Value) -> String {
    str_of(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_policy::classify::clock::Crt;

    #[test]
    fn versions() {
        for good in [
            "0.6.26",
            "1.2.3-beta",
            "1.2.3-alpha.2",
            "123456.0.0-beta.999",
        ] {
            assert!(update_version(good), "{good}");
        }
        for bad in [
            "01.2.3",
            "1.2",
            "1.2.3-beta.1",
            "1.2.3-beta.0100",
            "1.2.3-rc",
            "1234567.0.0",
            "1.2.3\n",
        ] {
            assert!(!update_version(bad), "{bad}");
        }
    }

    #[test]
    fn toast_document() {
        let speech = Speech::new("en", &Crt);
        let made = cancelled_content(&speech, &Value::from("x")).unwrap();
        let toast = Toast {
            extra: made["extra"].clone(),
            ..Toast::default()
        };
        let xml = toast_xml(&made["title"], &made["body"], &toast).unwrap();
        assert!(xml.starts_with("<toast duration=\"long\"><visual>"));
        assert!(xml.ends_with("</binding></visual></toast>"));
    }
}
