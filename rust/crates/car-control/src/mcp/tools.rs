//! `mcp/tools.py`: what this server offers Codex - the tools, their schemas, and the one resource.
//!
//! Declarations only - no behaviour. Every tool here is a name, a description a model reads to decide whether to
//! call it, and a JSON Schema its arguments are validated against; what happens when one is called is
//! [`super::server`]. The values are built key by key in the reference's order, so `tools/list` is the reference's
//! bytes (`tests/golden/mcp/tools-list.json`).

use car_machine::json::{Map, Str, Value};
use car_machine::vocab_gen::domain_ids;
use car_policy::classify::quiet::MAX_POSTPONE_SECONDS;
use car_policy::classify::reasons::RECOVERABLE;
use car_policy::settings::{is_custom_text, schema};

use crate::bridge::DAYS;

/// `SETTINGS_UI`.
pub const SETTINGS_UI: &str = "ui://codex-auto-resume/settings";
/// `PANEL_DISPLAY_MODES`: where Codex may show the page - in the conversation, or beside it.
pub const PANEL_DISPLAY_MODES: &[&str] = &["inline", "fullscreen"];
/// `PANEL_PREFERRED_MODE`.
pub const PANEL_PREFERRED_MODE: &str = "inline";
/// `USER_GROUPS`: the settings groups a person can change from a front end.
pub const USER_GROUPS: &[&str] = &[
    "general",
    "recovery",
    "limits",
    "notifications",
    "continuation",
];
/// `PANEL_APPEARANCE`: the Appearance settings the panel offers.
pub const PANEL_APPEARANCE: &[&str] = &["theme", "panel_theme"];
/// `quiet.PRESETS`: the postponement presets.
pub const POSTPONE_PRESETS: &[&str] = &["30_minutes", "1_hour", "3_hours", "tomorrow_morning"];

/// A JSON object of these pairs, in this order.
pub fn object<const N: usize>(pairs: [(&str, Value); N]) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

fn text(value: &str) -> Value {
    Value::from(value)
}

fn texts(values: &[&str]) -> Value {
    Value::Array(values.iter().map(|each| Value::from(*each)).collect())
}

fn yes(on: bool) -> Value {
    Value::Bool(on)
}

/// `QUIET_AND_TIERS[name]`: what the quiet hours, the tiers and the guards do, for a model choosing a value.
fn quiet_and_tiers(name: &str) -> Option<String> {
    let fixed = match name {
        "quiet_hours_start" => {
            "When quiet hours start, local time, or off (the default: none). A recovery that falls due in them waits until they end; nothing else changes."
        }
        "quiet_hours_end" => {
            "When quiet hours end, local time. Nothing while quiet_hours_start is off."
        }
        "quiet_hours_days" => {
            "The days quiet hours start on. Nothing while quiet_hours_start is off."
        }
        "default_tier" => {
            "How much a conversation without a tier of its own asks before it is resumed: automatic (the default), objection_window (a card first, objection_minutes to stop it), ask_first or notify_only (nothing is sent until a person lets it continue). Applies to interruptions detected after it is chosen."
        }
        "objection_minutes" => "How long the objection window waits before a continuation is sent.",
        "observe_only" => {
            "Observe only: every check still runs and when a continuation would have been sent is recorded, but nothing is sent. false (the default) sends as usual."
        }
        "new_conversation_policy" => {
            "What a conversation this product has never seen before gets: resume (the default: the same as every other conversation) or notify_only (its own tier becomes Only notify me, so nothing is sent for it until a person lets a task continue)."
        }
        "project_policy" => {
            "Which projects resume without a person: every (the default), only_listed (only projects a person set to Always on a task's row) or except_listed (every project but those set to Never). An interruption of any other project, or of one whose project cannot be read, waits for a person and is never dropped. Applies to interruptions detected after it is chosen."
        }
        "retry_jitter" => {
            "Adds up to a fifth to each wait of a temporary failure, never taking any off. false (the default) waits exactly."
        }
        "chain_time_ceiling" => {
            "How long a task may keep failing with temporary errors before it stops: off (the default) or a number of hours, from its first failure to its latest. Waiting for a person, quiet hours or a closed app never count."
        }
        "task_changed_guard" => {
            "When a recovery falls due, compare its conversation's model, approval mode and folder's git HEAD with when it stopped: off (the default, nothing is read), hold (a change waits for a person) or tell (it is sent, and its notification says the task changed). Only a digest is kept."
        }
        "context_guard" => {
            "Codex's token count for a conversation, where Codex keeps one: off (the default, nothing is read), show (on Pending), or above_100k to above_1m (also hold a recovery whose conversation has used more, for a person)."
        }
        "stall_after" => {
            "How long a turn may record nothing new before a notice says its conversation may need a person: off (the default, never) or m10 to h2. Nothing is resumed or sent for it."
        }
        "ask_after_sleep_minutes" => {
            "After this PC slept for longer than this - off (the default) or m30 to h12 - a recovery that fell due while it slept waits for a person, who lets each continue from Pending. It only ever holds more back."
        }
        "wait_for_network" => {
            "When true, a due recovery asks Windows whether this PC is on the internet before usage is read, and waits while it reports none; nothing is sent to find out. false (the default) reads usage as before."
        }
        _ => "",
    };
    if !fixed.is_empty() {
        return Some(fixed.to_owned());
    }
    let steps = car_policy::settings::vocab_gen::settings::STEP_FIELDS;
    steps.iter().position(|field| *field == name).map(|index| {
        let number = index + 1;
        format!(
            "Wait {number} of the custom retry timing, read only while retry_timing is custom: the wait before attempt {number} at a task that failed with a temporary error. Whatever is chosen, one conversation gets a continuation at most every 15 minutes and 5 a day."
        )
    })
}

/// `"%d" % value` for a JSON number: an int as itself, a float truncated toward zero.
fn percent_d(value: Option<&Value>) -> String {
    match value {
        Some(Value::Int(int)) => int.to_string(),
        Some(Value::Float(x)) => format!("{}", x.trunc() as i64),
        Some(Value::Bool(on)) => i64::from(*on).to_string(),
        _ => "0".to_owned(),
    }
}

fn whole(value: Option<&Value>) -> i64 {
    match value {
        Some(Value::Int(int)) => int.as_i64().unwrap_or(0),
        Some(Value::Float(x)) => *x as i64,
        Some(Value::Bool(on)) => i64::from(*on),
        _ => 0,
    }
}

/// `_span(seconds)`: a bound of a wait in words, the largest whole unit that says it exactly.
pub fn span(seconds: i64) -> String {
    for (size, unit) in [
        (86400, "day"),
        (3600, "hour"),
        (60, "minute"),
        (1, "second"),
    ] {
        if seconds.rem_euclid(size) == 0 {
            let count = seconds.div_euclid(size);
            return format!("{count} {unit}{}", if count == 1 { "" } else { "s" });
        }
    }
    format!("{seconds} seconds")
}

fn strs(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(items)) => items
            .iter()
            .map(|each| match each {
                Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
                other => car_machine::pytext::py_str(other),
            })
            .collect(),
        _ => Vec::new(),
    }
}

/// `own_words(custom)`: what a setting takes of a person's own besides its choices.
pub fn own_words(custom: &Map) -> String {
    let kind = match custom.get("kind") {
        Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    };
    match kind.as_str() {
        "clock" => "Or any time of day, as HH:MM from 00:00 to 23:59.".to_owned(),
        "days" => format!(
            "Or any days, comma-separated: {}.",
            strs(custom.get("days")).join(", ")
        ),
        "duration" => {
            let units = strs(custom.get("units"));
            let examples: Vec<&str> = units
                .iter()
                .map(|unit| match unit.as_str() {
                    "s" => "s90 is 90 seconds",
                    "m" => "m45 is 45 minutes",
                    _ => "h36 is 36 hours",
                })
                .collect();
            format!(
                "Or a time of its own: {} and a whole number ({}), from {} to {}.",
                units.join("/"),
                examples.join(", "),
                span(whole(custom.get("min"))),
                span(whole(custom.get("max")))
            )
        }
        _ => {
            let prefix = match custom.get("prefix") {
                Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
                Some(other) => car_machine::pytext::py_str(other),
                None => "None".to_owned(),
            };
            let thousands = strs(custom.get("units")).iter().any(|unit| unit == "k");
            format!(
                "Or a number of its own after {prefix}, from {} to {}, in whole {}.",
                percent_d(custom.get("min")),
                percent_d(custom.get("max")),
                if thousands {
                    "thousands (above_300k, or above_300000)"
                } else {
                    "units"
                }
            )
        }
    }
}

fn identifier_schema(title: &str) -> Value {
    object([
        ("type", text("string")),
        ("title", text(title)),
        (
            "description",
            text(
                "The exact interruption id, as listed by list_pending. Never a title, a project name, or 'the most recent one'.",
            ),
        ),
        ("pattern", text(domain_ids::INTERRUPTION_ID_SCHEMA)),
    ])
}

fn thread_schema() -> Value {
    object([
        ("type", text("string")),
        ("pattern", text(domain_ids::THREAD_ID_SCHEMA)),
        (
            "description",
            text("The conversation's exact thread id, from the same row of list_pending"),
        ),
    ])
}

fn no_arguments() -> Value {
    object([
        ("type", text("object")),
        ("properties", Value::Object(Map::new())),
        ("additionalProperties", yes(false)),
    ])
}

fn annotations(read_only: bool, destructive: bool, idempotent: bool) -> Value {
    object([
        ("readOnlyHint", yes(read_only)),
        ("destructiveHint", yes(destructive)),
        ("idempotentHint", yes(idempotent)),
        ("openWorldHint", yes(false)),
    ])
}

fn get<'a>(map: &'a Map, name: &str) -> Option<&'a Value> {
    map.get(name)
}

fn name_of(map: &Map, key: &str) -> String {
    match map.get(key) {
        Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    }
}

/// `settings_schema()`: the update_settings input schema, generated from the shared field definitions.
pub fn settings_schema() -> Value {
    let described = schema::describe(&|| car_words::l10n::DEFAULT.to_owned());
    let mut properties = Map::new();
    for entry in described {
        let Value::Object(entry) = entry else {
            continue;
        };
        let name = name_of(&entry, "name");
        let group = name_of(&entry, "group");
        if !USER_GROUPS.contains(&group.as_str()) && !PANEL_APPEARANCE.contains(&name.as_str()) {
            continue;
        }
        if is_custom_text(&name) {
            continue;
        }
        let mut described = Map::new();
        described.insert(Str::from("type"), Value::from(name_of(&entry, "type")));
        if let Some(low) = get(&entry, "min") {
            described.insert(Str::from("minimum"), low.clone());
        }
        if let Some(high) = get(&entry, "max") {
            described.insert(Str::from("maximum"), high.clone());
        }
        let custom = match get(&entry, "custom") {
            Some(Value::Object(custom)) => Some(custom.clone()),
            _ => None,
        };
        let choices = get(&entry, "choices").cloned();
        if let (Some(choices), Some(custom)) = (&choices, &custom) {
            described.insert(
                Str::from("anyOf"),
                Value::Array(vec![
                    object([("enum", choices.clone())]),
                    object([(
                        "pattern",
                        custom.get("pattern").cloned().unwrap_or(Value::Null),
                    )]),
                ]),
            );
        } else if let Some(choices) = &choices {
            described.insert(Str::from("enum"), choices.clone());
        }
        let mut description = if let Some(category) = name.strip_prefix("recover_") {
            let _ = category;
            Some(format!(
                "Recover interruptions classified as {}. Turning this on can never widen what counts as recoverable; the classifier decides that.",
                name_of(&entry, "category").replace('_', " ")
            ))
        } else if name == "theme" {
            Some("Light or dark for the settings window, the popup, the notification card and, while panel_theme is same, the panel. system: Windows there, Codex in the panel.".to_owned())
        } else if name == "panel_theme" {
            Some("Light or dark for the settings panel in Codex alone: same uses theme's choice, system follows Codex whatever theme is. Changes nothing but colours.".to_owned())
        } else {
            quiet_and_tiers(&name)
        }
        .unwrap_or_else(|| "See the settings documentation.".to_owned());
        if let Some(custom) = &custom {
            description.push(' ');
            description.push_str(&own_words(custom));
        }
        described.insert(Str::from("description"), Value::from(description));
        properties.insert(Str::from(name.as_str()), Value::Object(described));
    }
    object([
        ("type", text("object")),
        ("properties", Value::Object(properties)),
        ("additionalProperties", yes(false)),
    ])
}

fn tool(
    name: &str,
    title: &str,
    description: &str,
    schema: Value,
    notes: Value,
    meta: Option<Value>,
) -> Value {
    let mut map = Map::new();
    map.insert(Str::from("name"), text(name));
    map.insert(Str::from("title"), text(title));
    map.insert(Str::from("description"), text(description));
    map.insert(Str::from("inputSchema"), schema);
    map.insert(Str::from("annotations"), notes);
    if let Some(meta) = meta {
        map.insert(Str::from("_meta"), meta);
    }
    Value::Object(map)
}

fn with_id(names: &[(&str, Value)], required: &[&str]) -> Value {
    let mut properties = Map::new();
    for (name, value) in names {
        properties.insert(Str::from(*name), value.clone());
    }
    object([
        ("type", text("object")),
        ("properties", Value::Object(properties)),
        ("required", texts(required)),
        ("additionalProperties", yes(false)),
    ])
}

fn thread_only() -> Value {
    with_id(
        &[(
            "thread_id",
            object([
                ("type", text("string")),
                ("pattern", text(domain_ids::THREAD_ID_SCHEMA)),
                (
                    "description",
                    text("The conversation's exact thread id from list_pending"),
                ),
            ]),
        )],
        &["thread_id"],
    )
}

/// `TOOLS`: core's seventeen tools and the preview, in the reference's order.
pub fn tools() -> Vec<Value> {
    let id = || identifier_schema("Interruption id");
    vec![
        tool(
            "open_settings",
            "Open Auto Resume settings",
            "Show the Codex Auto Resume settings panel, with the current status and every option. Read-only: opening it changes nothing.",
            no_arguments(),
            object([
                ("title", text("Open Auto Resume settings")),
                ("readOnlyHint", yes(true)),
                ("destructiveHint", yes(false)),
                ("idempotentHint", yes(true)),
                ("openWorldHint", yes(false)),
            ]),
            Some(object([
                ("openai/outputTemplate", text(SETTINGS_UI)),
                (
                    "openai/toolInvocation/invoking",
                    text("Opening Auto Resume settings"),
                ),
                (
                    "openai/toolInvocation/invoked",
                    text("Auto Resume settings"),
                ),
                (
                    "openai/ui",
                    object([(
                        "entrypoints",
                        Value::Array(vec![object([("type", text("thread"))])]),
                    )]),
                ),
            ])),
        ),
        tool(
            "get_status",
            "Auto Resume status",
            "Whether automatic recovery is on, whether the watcher is running, how many recoveries are pending, and the current settings. Works with the watcher stopped.",
            no_arguments(),
            annotations(true, false, true),
            None,
        ),
        tool(
            "list_pending",
            "List pending recoveries",
            "Interruptions waiting to be recovered, with their exact interruption ids, states and attempt counts.",
            object([
                ("type", text("object")),
                (
                    "properties",
                    object([(
                        "include_finished",
                        object([
                            ("type", text("boolean")),
                            (
                                "description",
                                text("Also list recoveries that have already finished."),
                            ),
                        ]),
                    )]),
                ),
                ("additionalProperties", yes(false)),
            ]),
            annotations(true, false, true),
            None,
        ),
        tool(
            "update_settings",
            "Change Auto Resume settings",
            "Change one or more settings. Only the named settings change. A value outside the allowed range is refused rather than silently adjusted. There is no setting that retries an unclassified failure; do not look for one.",
            settings_schema(),
            annotations(false, true, true),
            None,
        ),
        tool(
            "restore_default_settings",
            "Restore default settings",
            "Reset every setting to its recommended value. Pending recoveries are not affected.",
            no_arguments(),
            annotations(false, true, true),
            None,
        ),
        tool(
            "pause_auto_recovery",
            "Pause automatic recovery",
            "Global pause. Nothing is sent while paused. Pausing only ever reduces automation, so it needs no confirmation.",
            no_arguments(),
            annotations(false, false, true),
            None,
        ),
        tool(
            "turn_off_power_action",
            "Turn off the power action",
            "Turn off the power action after usage-limit recoveries, if it is on, so this PC is not put to sleep, hibernated or shut down when they finish. It only reduces automation, so it needs no confirmation. It cannot be turned on from Codex; only the Dashboard does that.",
            no_arguments(),
            annotations(false, false, true),
            None,
        ),
        tool(
            "resume_auto_recovery",
            "Resume automatic recovery",
            "Undo a global pause. Recovery then continues under every usual check. This turns automation back on, so Codex asks the user before running it.",
            no_arguments(),
            annotations(false, true, true),
            None,
        ),
        tool(
            "cancel_recovery",
            "Cancel one recovery",
            "Stop recovering one exact interruption and anything that continues it. Identify it by the interruption id from list_pending - never by title, project or recency. A continuation already in Codex's queue is withdrawn; one already running is not stopped. Cancelling only ever reduces automation.",
            with_id(&[("interruption_id", id())], &["interruption_id"]),
            annotations(false, true, true),
            None,
        ),
        tool(
            "reset_recovery_budget",
            "Give an exhausted recovery its attempts back",
            "For a recovery that stopped because it ran out of attempts or kept making no progress. It returns to the ordinary waiting state; it does not send anything, and every check runs again.",
            with_id(&[("interruption_id", id())], &["interruption_id"]),
            annotations(false, true, false),
            None,
        ),
        tool(
            "start_watcher",
            "Start the background watcher",
            "Start the watcher if it is not running. Nothing is recovered while it is stopped, so this is the fix when the status says it is not running. It starts the same process the installer starts and decides nothing about any interruption. Started from here it runs inside Codex. Where Codex ends what its plugins start, as Codex 26.915 was measured to, it stops when Codex closes, if not sooner; the reply reads that from the job each time and says so. A watcher that outlives Codex is one started from Codex Auto Resume in the Start menu once Codex has closed, or at Windows sign-in.",
            no_arguments(),
            annotations(false, true, true),
            None,
        ),
        tool(
            "retry_now",
            "Try a waiting recovery now",
            "Bring a waiting recovery's next attempt forward. This is not a send: the watcher still revalidates the interruption, still requires the conversation to be open, still waits for usage to be available, and still refuses anything uncertain.",
            with_id(&[("interruption_id", id())], &["interruption_id"]),
            annotations(false, false, true),
            None,
        ),
        tool(
            "postpone_recovery",
            "Postpone one waiting recovery",
            "Make one exact waiting recovery wait longer: nothing is sent for it before the time asked for - preset 30_minutes, 1_hour, 3_hours or tomorrow_morning (09:00 local time), or a number of minutes up to a week; give exactly one. Identify it by its interruption id and its thread id, both from the same row of list_pending - never by title, project or recency. It only ever makes a recovery later, sends nothing and skips no check; retry_now does not bring it forward.",
            with_id(
                &[
                    ("interruption_id", id()),
                    ("thread_id", thread_schema()),
                    (
                        "preset",
                        object([("type", text("string")), ("enum", texts(POSTPONE_PRESETS))]),
                    ),
                    (
                        "minutes",
                        object([
                            ("type", text("integer")),
                            ("minimum", Value::from(1)),
                            ("maximum", Value::from(MAX_POSTPONE_SECONDS / 60)),
                        ]),
                    ),
                ],
                &["interruption_id", "thread_id"],
            ),
            annotations(false, false, false),
            None,
        ),
        tool(
            "release_hold",
            "Let one held recovery continue",
            "Let one exact recovery that waits for a person continue - one whose conversation asks first or only notifies (its hold in list_pending). Identify it by its interruption id and its thread id from the same row. Nothing is sent by this; the watcher still runs every check, and a postponement or quiet hours still apply. This lets automation run again for that recovery, so Codex asks the user first.",
            with_id(
                &[("interruption_id", id()), ("thread_id", thread_schema())],
                &["interruption_id", "thread_id"],
            ),
            annotations(false, true, true),
            None,
        ),
        tool(
            "disable_conversation_recovery",
            "Turn recovery off for one conversation",
            "Stop automatic recovery for one exact conversation, including its later interruptions, and cancel what it has waiting. Only ever reduces automation.",
            thread_only(),
            annotations(false, false, true),
            None,
        ),
        tool(
            "enable_conversation_recovery",
            "Turn recovery back on for one conversation",
            "Let automatic recovery run again for one exact conversation. Nothing is sent by this; every check still applies. This turns automation back on, so Codex asks the user first.",
            thread_only(),
            annotations(false, true, true),
            None,
        ),
        tool(
            "get_recovery_statistics",
            "Recovery statistics",
            "Counts of interruptions and how their recoveries ended, and median waits, over the last N days or all time. Content-free.",
            object([
                ("type", text("object")),
                (
                    "properties",
                    object([(
                        "days",
                        object([
                            ("type", text("number")),
                            ("minimum", Value::from(DAYS.0)),
                            ("maximum", Value::from(DAYS.1)),
                        ]),
                    )]),
                ),
                ("additionalProperties", yes(false)),
            ]),
            annotations(true, false, true),
            None,
        ),
        tool(
            "get_recovery_timeline",
            "Timeline of one recovery",
            "What happened to one exact interruption and everything that continued it: detection, waits, the send, the turn it started and how that turn ended. Codes and times only.",
            with_id(&[("interruption_id", id())], &["interruption_id"]),
            annotations(true, false, true),
            None,
        ),
        tool(
            "clear_recovery_history",
            "Clear recovery history",
            "Hide finished recoveries from the history. Deletes nothing and cancels nothing; a recovery that may still change stays visible, and hidden ones still count for every safety check.",
            no_arguments(),
            annotations(false, true, true),
            None,
        ),
        tool(
            "preview_recovery_message",
            "Preview the recovery message",
            "Show the exact text Codex Auto Resume would send to continue a task after an interruption of the given kind, under the current settings or the language and style given. Read-only: it saves nothing and sends nothing.",
            object([
                ("type", text("object")),
                (
                    "properties",
                    object([
                        (
                            "category",
                            object([
                                ("type", text("string")),
                                ("enum", texts(RECOVERABLE)),
                                ("description", text("The kind of interruption to preview.")),
                            ]),
                        ),
                        (
                            "changes",
                            object([
                                ("type", text("object")),
                                (
                                    "description",
                                    text("Unsaved choices to preview with. Nothing is stored."),
                                ),
                                (
                                    "properties",
                                    object([
                                        ("interface_language", object([("type", text("string"))])),
                                        (
                                            "continuation_language",
                                            object([("type", text("string"))]),
                                        ),
                                        ("continuation_style", object([("type", text("string"))])),
                                        ("custom_message_mode", object([("type", text("string"))])),
                                    ]),
                                ),
                                ("additionalProperties", yes(false)),
                            ]),
                        ),
                    ]),
                ),
                ("required", texts(&["category"])),
                ("additionalProperties", yes(false)),
            ]),
            object([
                ("title", text("Preview the recovery message")),
                ("readOnlyHint", yes(true)),
                ("destructiveHint", yes(false)),
                ("idempotentHint", yes(true)),
                ("openWorldHint", yes(false)),
            ]),
            None,
        ),
    ]
}

/// `RESOURCES`.
pub fn resources() -> Vec<Value> {
    vec![object([
        ("uri", text(SETTINGS_UI)),
        ("name", text("Codex Auto Resume settings")),
        (
            "description",
            text("The settings panel shown by open_settings."),
        ),
        ("mimeType", text("text/html+skybridge")),
    ])]
}

/// `PLUGGED_KEYS`: what a plug's tool is let through as.
const PLUGGED_KEYS: &[&str] = &["name", "title", "description", "inputSchema", "annotations"];

/// `PLUGGED_NAME.fullmatch(name)`: `[a-z][a-z0-9_]{2,63}`.
fn plugged_name(name: &str) -> bool {
    let mut characters = name.chars();
    let Some(first) = characters.next() else {
        return false;
    };
    let rest: Vec<char> = characters.collect();
    first.is_ascii_lowercase()
        && (2..=63).contains(&rest.len())
        && rest
            .iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == '_')
}

fn declared(tool: &Value, taken: &[Str]) -> bool {
    let Value::Object(tool) = tool else {
        return false;
    };
    let name = match tool.get("name") {
        Some(Value::Str(name)) => name,
        _ => return false,
    };
    if !name.as_str().is_some_and(plugged_name) || taken.contains(name) {
        return false;
    }
    if !matches!(tool.get("description"), Some(Value::Str(_))) {
        return false;
    }
    if !matches!(tool.get("title"), None | Some(Value::Str(_))) {
        return false;
    }
    let Some(Value::Object(schema)) = tool.get("inputSchema") else {
        return false;
    };
    if schema.get("type") != Some(&Value::from("object"))
        || schema.get("additionalProperties") != Some(&Value::Bool(false))
    {
        return false;
    }
    let Some(Value::Object(properties)) = schema.get("properties") else {
        return false;
    };
    if !properties
        .values()
        .all(|value| matches!(value, Value::Object(_)))
    {
        return false;
    }
    let required = match schema.get("required") {
        None => Vec::new(),
        Some(Value::Array(items)) => {
            let mut names = Vec::new();
            for item in items {
                match item {
                    Value::Str(text) => names.push(text.clone()),
                    _ => return false,
                }
            }
            names
        }
        Some(_) => return false,
    };
    if !required.iter().all(|key| properties.contains_key(key)) {
        return false;
    }
    let Some(Value::Object(notes)) = tool.get("annotations") else {
        return false;
    };
    ["readOnlyHint", "destructiveHint"]
        .iter()
        .all(|hint| matches!(notes.get(*hint), Some(Value::Bool(_))))
}

/// `plugged_tools(declared)`: the tools a plug declared that may be offered, in its order, each once, after core's.
pub fn plugged_tools(declared_tools: Option<&Value>) -> Vec<Value> {
    let Some(Value::Array(declared_tools)) = declared_tools else {
        return Vec::new();
    };
    let mut taken: Vec<Str> = tools()
        .iter()
        .filter_map(|tool| match tool {
            Value::Object(map) => match map.get("name") {
                Some(Value::Str(name)) => Some(name.clone()),
                _ => None,
            },
            _ => None,
        })
        .collect();
    let mut kept = Vec::new();
    for tool in declared_tools {
        if declared(tool, &taken) {
            let Value::Object(map) = tool else { continue };
            if let Some(Value::Str(name)) = map.get("name") {
                taken.push(name.clone());
            }
            let mut out = Map::new();
            for key in PLUGGED_KEYS {
                if let Some(value) = map.get(*key) {
                    out.insert(Str::from(*key), value.clone());
                }
            }
            kept.push(Value::Object(out));
        }
    }
    kept
}
