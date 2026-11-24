//! `poweraction.py`: the power action after usage-limit recoveries - what it waits for, and when it may act (v0.6.12).
//!
//! Pure: the arming, the records, the times and what was read come in; a decision goes out. Every value is taken as
//! the Python takes it - a dict of anything - and a question Python would answer with an exception answers with that
//! exception's class ([`Py`]). The order of the checks is the module's own (`decide`, steps 1-10; T1-T4 for an
//! arming for tasks a person picked, whose word is the plug's P21).

use car_machine::domain::{ids, states};
use car_machine::json::{Map, Str, Value};
use car_machine::pyval::{self, Num, Py};

use super::vocab_gen::poweraction as words;

pub const FORMAT: &str = words::FORMAT;
pub const TASKS_KEY: &str = words::TASKS_KEY;
pub const ACTIONS: &[&str] = &["sleep", "hibernate", "shut_down"];
pub const AFTERS: &[&str] = &["all_recovered", "handed_over_too", "any_end"];
pub const REPEATS: &[&str] = &["once", "always"];
pub const TASKS: &[&str] = words::TASKS;
pub const PHASES: &[&str] = &["waiting", "grace"];
pub const WAITS: &[&str] = &[
    "no_batch",
    "recovery_open",
    "delivery_unknown",
    "turn_running",
    "queued_input",
    "codex_unknown",
    "history_behind",
    "other_people",
    "person_active",
    "idle_unknown",
    "paused",
    "watcher",
    "tasks_running",
    "tasks_unknown",
];
pub const ENDS: &[&str] = &[
    "done",
    "failed",
    "skipped",
    "not_met",
    "stale",
    "lapsed",
    "unavailable",
];
pub const GRACE_MINUTES: &[i64] = &[2, 5, 10, 15, 30];
pub const CHOICE_KEYS: &[&str] = words::CHOICE_KEYS;
pub const MAX_CARRIED: usize = 256;
pub const SINCE_SKEW: f64 = 300.0;
pub const LAPSE_SECONDS: f64 = 24.0 * 3600.0;
pub const STALE_SECONDS: f64 = 3600.0;
pub const FOLLOW_SECONDS: f64 = 24.0 * 3600.0;
pub const IDLE_SECONDS: f64 = 120.0;
pub const COUNTDOWN_LOOK_SECONDS: f64 = 15.0;
pub const GAP_SECONDS: f64 = 90.0;
pub const READ_OK: &str = "ok";
pub const READ_MISSING: &str = "missing";
pub const READ_INVALID: &str = "invalid";
pub const READ_UNREADABLE: &str = "unreadable";
pub const OFF: &str = "off";
pub const WAIT: &str = "wait";
pub const END: &str = "end";
pub const GO: &str = "go";
pub const OFF_INVALID: &str = "invalid";
pub const OFF_MANAGED: &str = "managed";
const SUCCESS_STATES: &[&str] = words::SUCCESS_STATES;
const PERSON_STATES: &[&str] = words::PERSON_STATES;
const PERSON_SUPERSEDED: &[&str] = words::PERSON_SUPERSEDED;
const TOP: &[&str] = &["format", "armed", "shown", "last"];
const ARMED: &[&str] = &[
    "nonce",
    "action",
    "after",
    "repeat",
    "grace_seconds",
    "armed_at",
    "since",
    "carried",
    "stop_at",
];
const SHOWN: &[&str] = &["nonce", "phase", "waiting_for", "grace_until"];
const LAST: &[&str] = &["action", "result", "at"];
const VIEW_ARMED: &[&str] = &[
    "action",
    "after",
    "repeat",
    "grace_seconds",
    "armed_at",
    "since",
];
const VIEW_SHOWN: &[&str] = &["phase", "waiting_for", "grace_until"];

static NULL: Value = Value::Null;

/// `_time(value)`: a time in the store's window; an int too large to be a float is not one.
fn time(value: &Value) -> bool {
    let (low, high) = states::EPOCH_STORE;
    states::epoch(value, low, high, false, true).unwrap_or(false)
}

fn word(value: &Value, words: &[&str]) -> bool {
    pyval::text(value).is_some_and(|text| words.contains(&text))
}

/// `_exact(value, keys)`: a dict with exactly these keys.
fn exact<'a>(value: &'a Value, keys: &[&str]) -> Option<&'a Map> {
    match value {
        Value::Object(map)
            if map.len() == keys.len() && keys.iter().all(|key| map.contains_key(*key)) =>
        {
            Some(map)
        }
        _ => None,
    }
}

fn count(value: &Value) -> bool {
    matches!(value, Value::Int(int) if !int.to_string().starts_with('-'))
}

fn number(value: &Value) -> Py<Num> {
    Num::of(value).ok_or("TypeError")
}

fn float(x: f64) -> Num {
    Num::Real(x)
}

fn cmp(a: Num, b: Num) -> Option<std::cmp::Ordering> {
    pyval::compare(a, b)
}

fn plus(a: &Value, b: f64) -> Py<Num> {
    Ok(Num::Real(number(a)?.as_f64() + b))
}

fn armed_ok(armed: &Value, now: &Value) -> Py<bool> {
    let mut armed = armed.clone();
    if let Value::Object(map) = &armed
        && map.contains_key(TASKS_KEY)
    {
        let carried_empty =
            matches!(map.get("carried"), Some(Value::Array(items)) if items.is_empty());
        if !matches!(map[TASKS_KEY], Value::Bool(true))
            || !map
                .get("repeat")
                .is_some_and(|repeat| pyval::is(repeat, "once"))
            || !carried_empty
        {
            return Ok(false);
        }
        let mut without = map.clone();
        without.shift_remove(TASKS_KEY);
        armed = Value::Object(without);
    }
    let Some(map) = exact(&armed, ARMED) else {
        return Ok(false);
    };
    if !ids::is_power_nonce(&map["nonce"]) {
        return Ok(false);
    }
    if !(word(&map["action"], ACTIONS)
        && word(&map["after"], AFTERS)
        && word(&map["repeat"], REPEATS))
    {
        return Ok(false);
    }
    let grace = match &map["grace_seconds"] {
        Value::Int(int) => int.as_i64(),
        _ => None,
    };
    if !grace.is_some_and(|seconds| GRACE_MINUTES.iter().any(|minutes| minutes * 60 == seconds)) {
        return Ok(false);
    }
    let (armed_at, since, stop) = (&map["armed_at"], &map["since"], &map["stop_at"]);
    if !(time(armed_at) && time(since)) {
        return Ok(false);
    }
    let since_n = number(since)?;
    if cmp(since_n, number(armed_at)?).is_some_and(|order| order.is_lt())
        || cmp(since_n, plus(now, SINCE_SKEW)?).is_some_and(|order| order.is_gt())
    {
        return Ok(false);
    }
    if !matches!(stop, Value::Null) && !time(stop) {
        return Ok(false);
    }
    let Value::Array(carried) = &map["carried"] else {
        return Ok(false);
    };
    if carried.len() > MAX_CARRIED || !carried.iter().all(ids::is_digest) {
        return Ok(false);
    }
    let mut keys: Vec<&Value> = carried.iter().collect();
    keys.sort_by(|a, b| pyval::text(a).cmp(&pyval::text(b)));
    keys.dedup_by(|a, b| a == b);
    Ok(keys.len() == carried.len())
}

fn shown_ok(shown: &Value, armed: &Value) -> bool {
    let Some(map) = exact(shown, SHOWN) else {
        return false;
    };
    let Value::Object(armed) = armed else {
        return false;
    };
    if !pyval::eq(&map["nonce"], armed.get("nonce").unwrap_or(&NULL)) {
        return false;
    }
    if !word(&map["phase"], PHASES) {
        return false;
    }
    if !matches!(map["waiting_for"], Value::Null) && !word(&map["waiting_for"], WAITS) {
        return false;
    }
    let until = &map["grace_until"];
    if pyval::is(&map["phase"], "grace") {
        return time(until);
    }
    matches!(until, Value::Null)
}

fn last_ok(last: &Value) -> bool {
    exact(last, LAST).is_some_and(|map| {
        word(&map["action"], ACTIONS) && word(&map["result"], ENDS) && time(&map["at"])
    })
}

/// `read_document(value, now)`: the power-action file's contents as they may be believed, or None.
pub fn read_document(value: &Value, now: &Value) -> Py<Value> {
    let Some(top) = exact(value, TOP) else {
        return Ok(Value::Null);
    };
    if !pyval::is(&top["format"], FORMAT) {
        return Ok(Value::Null);
    }
    let (armed, shown, last) = (&top["armed"], &top["shown"], &top["last"]);
    if !matches!(armed, Value::Null) && !armed_ok(armed, now)? {
        return Ok(Value::Null);
    }
    if !matches!(shown, Value::Null) && !shown_ok(shown, armed) {
        return Ok(Value::Null);
    }
    if !matches!(last, Value::Null) && !last_ok(last) {
        return Ok(Value::Null);
    }
    let mut out = Map::new();
    out.insert(Str::from("format"), Value::from(FORMAT));
    out.insert(Str::from("armed"), armed.clone());
    out.insert(Str::from("shown"), shown.clone());
    out.insert(Str::from("last"), last.clone());
    Ok(Value::Object(out))
}

/// `blank()`: a file with nothing armed, shown or remembered.
pub fn blank() -> Value {
    let mut out = Map::new();
    out.insert(Str::from("format"), Value::from(FORMAT));
    for key in ["armed", "shown", "last"] {
        out.insert(Str::from(key), Value::Null);
    }
    Value::Object(out)
}

/// `for_tasks(armed)`: an arming for tasks a person picked - its `tasks` key, True.
pub fn for_tasks(armed: &Value) -> bool {
    matches!(armed, Value::Object(map) if matches!(map.get(TASKS_KEY), Some(Value::Bool(true))))
}

fn pick(source: &Value, keys: &[&str]) -> Py<Value> {
    let mut out = Map::new();
    for key in keys {
        let found = match source {
            Value::Object(map) => map.get(*key).ok_or("KeyError")?,
            Value::Array(_) => return Err("TypeError"),
            Value::Str(_) => return Err("TypeError"),
            _ => return Err("TypeError"),
        };
        out.insert(Str::from(*key), found.clone());
    }
    Ok(Value::Object(out))
}

/// `view(document)`: what every surface is told of the file - never the nonce.
pub fn view(document: &Value) -> Py<Value> {
    let get = |key: &str| match document {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let (armed, shown, last) = (get("armed"), get("shown"), get("last"));
    let mut viewed = if matches!(armed, Value::Null) {
        Value::Null
    } else {
        pick(&armed, VIEW_ARMED)?
    };
    if let Value::Object(map) = &mut viewed
        && for_tasks(&armed)
    {
        map.insert(Str::from(TASKS_KEY), Value::Bool(true));
    }
    let mut out = Map::new();
    out.insert(Str::from("armed"), viewed);
    out.insert(
        Str::from("shown"),
        if matches!(shown, Value::Null) {
            Value::Null
        } else {
            pick(&shown, VIEW_SHOWN)?
        },
    );
    out.insert(
        Str::from("last"),
        if matches!(last, Value::Null) {
            Value::Null
        } else {
            pick(&last, LAST)?
        },
    );
    Ok(Value::Object(out))
}

/// `choice_problem(choice)`: why `choice` is not an arming a person may make, or None.
pub fn choice_problem(choice: &Value) -> Option<String> {
    let Some(map) = exact(choice, CHOICE_KEYS) else {
        return Some(format!("exactly {}", CHOICE_KEYS.join(", ")));
    };
    for (name, allowed) in [("action", ACTIONS), ("after", AFTERS), ("repeat", REPEATS)] {
        if !word(&map[name], allowed) {
            return Some(format!("{name} is one of {}", allowed.join(", ")));
        }
    }
    let minutes = match &map["grace_minutes"] {
        Value::Int(int) => int.as_i64(),
        _ => None,
    };
    if !minutes.is_some_and(|minutes| GRACE_MINUTES.contains(&minutes)) {
        let listed: Vec<String> = GRACE_MINUTES.iter().map(i64::to_string).collect();
        return Some(format!("grace_minutes is one of {}", listed.join(", ")));
    }
    None
}

fn item<'a>(map: &'a Value, key: &str) -> Py<&'a Value> {
    match map {
        Value::Object(found) => found.get(key).ok_or("KeyError"),
        _ => Err("TypeError"),
    }
}

/// `is_member(row, armed)`: carried by the arming, or a usage limit detected since.
pub fn is_member(row: &Value, armed: &Value) -> Py<bool> {
    let id = pyval::get(row, "interruption_id")?;
    let Value::Array(carried) = item(armed, "carried")? else {
        return Err("TypeError");
    };
    if carried.iter().any(|each| pyval::eq(each, id)) {
        return Ok(true);
    }
    let detected = pyval::get(row, "detected_at")?;
    if !(pyval::is(pyval::get(row, "category")?, "usage_limit") && time(detected)) {
        return Ok(false);
    }
    pyval::less_or_equal(item(armed, "since")?, detected)
}

/// `members(rows, armed)`.
pub fn members(rows: &[Value], armed: &Value) -> Py<Vec<Value>> {
    let mut found = Vec::new();
    for row in rows {
        if is_member(row, armed)? {
            found.push(row.clone());
        }
    }
    Ok(found)
}

/// `is_open(row)`: still waiting or running - any state that is not a stop.
pub fn is_open(row: &Value) -> Py<bool> {
    Ok(!pyval::in_set(
        pyval::get(row, "state")?,
        states_terminal(),
    )?)
}

fn states_terminal() -> &'static [&'static str] {
    car_machine::vocab_gen::domain_states::TERMINAL
}

/// `classify(row)`: a finished record's PowerClass, or None while it has not finished.
pub fn classify(row: &Value) -> Py<Option<&'static str>> {
    let state = pyval::get(row, "state")?;
    if !pyval::in_set(state, states_terminal())? {
        return Ok(None);
    }
    if pyval::in_set(state, SUCCESS_STATES)? {
        return Ok(Some("success"));
    }
    if pyval::in_set(state, PERSON_STATES)?
        || (pyval::is(state, "superseded")
            && pyval::in_set(pyval::get(row, "last_error")?, PERSON_SUPERSEDED)?)
    {
        return Ok(Some("person"));
    }
    Ok(Some("other"))
}

/// `met(after, classes)`: whether a batch whose members ended as `classes` meets the policy. Never for none.
pub fn met(after: &Value, classes: &[Option<&str>]) -> bool {
    if classes.is_empty() || classes.iter().any(Option::is_none) {
        return false;
    }
    if pyval::is(after, "all_recovered") {
        return classes.iter().all(|found| *found == Some("success"));
    }
    if pyval::is(after, "handed_over_too") {
        return classes
            .iter()
            .all(|found| matches!(found, Some("success" | "person")))
            && classes.contains(&Some("success"));
    }
    pyval::is(after, "any_end")
}

/// `newest(rows)`: when the newest of `rows` last moved - its outcome, or its detection.
pub fn newest(rows: &[Value]) -> Py<Value> {
    let mut best: Option<Value> = None;
    for row in rows {
        let outcome = pyval::get(row, "outcome_at")?;
        let found = if time(outcome) {
            outcome
        } else {
            pyval::get(row, "detected_at")?
        };
        if !time(found) {
            continue;
        }
        best = Some(match best {
            Some(held) if !pyval::greater(found, &held)? => held,
            _ => found.clone(),
        });
    }
    Ok(best.unwrap_or(Value::Null))
}

/// `Facts`: what one tick knows before it reads Codex or asks Windows.
#[derive(Clone, Debug)]
pub struct Facts {
    pub now: Value,
    pub read: String,
    pub document: Value,
    pub managed: Value,
    pub ok: Value,
    pub paused: Value,
    pub rows: Vec<Value>,
    pub saw_open: bool,
    pub follow_window: Value,
    pub tasks: Value,
}

impl Facts {
    pub fn new(now: Value) -> Facts {
        Facts {
            now,
            read: READ_MISSING.into(),
            document: Value::Null,
            managed: Value::Bool(false),
            ok: Value::Bool(true),
            paused: Value::Bool(false),
            rows: Vec::new(),
            saw_open: false,
            follow_window: Value::Float(FOLLOW_SECONDS),
            tasks: Value::Null,
        }
    }
}

/// `Decision`: OFF, WAIT, END or GO; the word that says why; what the watcher keeps for this nonce.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decision {
    pub verdict: &'static str,
    pub word: Option<&'static str>,
    pub saw_open: bool,
}

fn decision(verdict: &'static str, word: Option<&'static str>, saw_open: bool) -> Py<Decision> {
    Ok(Decision {
        verdict,
        word,
        saw_open,
    })
}

/// `decide(facts)`: steps 1 to 10, the first that fails deciding.
pub fn decide(facts: &Facts) -> Py<Decision> {
    if facts.read == READ_UNREADABLE {
        return decision(WAIT, None, facts.saw_open);
    }
    if facts.read == READ_INVALID {
        return decision(OFF, Some(OFF_INVALID), false);
    }
    let armed = if facts.read == READ_OK {
        match &facts.document {
            Value::Object(map) => map.get("armed").cloned().unwrap_or(Value::Null),
            other if !pyval::truthy(other) => Value::Null,
            _ => return Err("AttributeError"),
        }
    } else {
        Value::Null
    };
    if matches!(armed, Value::Null) {
        return decision(OFF, None, false);
    }
    if pyval::truthy(&facts.managed) {
        return decision(OFF, Some(OFF_MANAGED), false);
    }
    if !matches!(item(&armed, "stop_at")?, Value::Null) {
        return decision(END, Some("skipped"), false);
    }
    let mut saw = facts.saw_open;
    if !pyval::truthy(&facts.ok) {
        return decision(WAIT, None, saw);
    }
    if pyval::truthy(&facts.paused) {
        return decision(WAIT, Some("paused"), saw);
    }
    if for_tasks(&armed) {
        return decide_tasks(facts);
    }
    let batch = members(&facts.rows, &armed)?;
    if batch.is_empty() {
        let lapsed = pyval::is(item(&armed, "repeat")?, "once")
            && cmp(
                number(&facts.now)?,
                plus(item(&armed, "armed_at")?, LAPSE_SECONDS)?,
            )
            .is_some_and(|order| order.is_gt());
        if lapsed {
            return decision(END, Some("lapsed"), false);
        }
        return decision(WAIT, Some("no_batch"), saw);
    }
    let followed = |row: &Value| states::still_followed(row, &facts.now, &facts.follow_window);
    if !saw {
        for row in &batch {
            if is_open(row)? || followed(row)? {
                saw = true;
                break;
            }
        }
    }
    for row in &facts.rows {
        if is_open(row)? {
            return decision(WAIT, Some("recovery_open"), saw);
        }
    }
    for row in &facts.rows {
        if followed(row)? {
            return decision(WAIT, Some("delivery_unknown"), saw);
        }
    }
    let after = item(&armed, "after")?;
    let mut classes = Vec::new();
    for row in &batch {
        classes.push(classify(row)?);
    }
    if !met(after, &classes) {
        return decision(END, Some("not_met"), saw);
    }
    let ended = newest(&batch)?;
    if !saw {
        let stale = match &ended {
            Value::Null => true,
            found => cmp(
                float(number(&facts.now)?.as_f64() - number(found)?.as_f64()),
                float(STALE_SECONDS),
            )
            .is_some_and(|order| order.is_gt()),
        };
        if stale {
            return decision(END, Some("stale"), saw);
        }
    }
    decision(GO, None, saw)
}

/// `_decide_tasks(facts, saw)`: steps T1 to T4, with core's step 8 between them.
fn decide_tasks(facts: &Facts) -> Py<Decision> {
    let saw = facts.saw_open;
    if !pyval::in_tuple(&facts.tasks, TASKS) || pyval::is(&facts.tasks, "unknown") {
        return decision(WAIT, Some("tasks_unknown"), saw);
    }
    if pyval::is(&facts.tasks, "running") {
        return decision(WAIT, Some("tasks_running"), true);
    }
    for row in &facts.rows {
        if is_open(row)? {
            return decision(WAIT, Some("recovery_open"), true);
        }
    }
    for row in &facts.rows {
        if states::still_followed(row, &facts.now, &facts.follow_window)? {
            return decision(WAIT, Some("delivery_unknown"), true);
        }
    }
    if pyval::is(&facts.tasks, "not_met") {
        return decision(END, Some("not_met"), true);
    }
    decision(GO, None, true)
}

/// `judge_activity(found)`: step 11 - None when nothing runs in Codex, or why to wait.
pub fn judge_activity(found: &Value) -> Option<&'static str> {
    let Value::Object(map) = found else {
        return Some("codex_unknown");
    };
    match map.get("history") {
        Some(Value::Bool(false)) => return Some("history_behind"),
        Some(Value::Bool(true)) => {}
        _ => return Some("codex_unknown"),
    }
    let (running, queued) = (
        map.get("running").unwrap_or(&NULL),
        map.get("queued").unwrap_or(&NULL),
    );
    if !(count(running) && count(queued)) {
        return Some("codex_unknown");
    }
    if pyval::truthy(running) {
        return Some("turn_running");
    }
    if pyval::truthy(queued) {
        return Some("queued_input");
    }
    None
}

fn real(value: &Value) -> Option<Num> {
    match value {
        Value::Int(_) | Value::Float(_) => Num::of(value),
        _ => None,
    }
}

/// `judge_presence(action, others, idle)`: steps 13 and 14 - None when nobody is in the way, or why to wait.
pub fn judge_presence(action: &Value, others: &Value, idle: &Value) -> Option<&'static str> {
    if pyval::is(action, "shut_down") && (!count(others) || pyval::truthy(others)) {
        return Some("other_people");
    }
    let Some(idle) = real(idle) else {
        return Some("idle_unknown");
    };
    if idle.as_f64().is_nan() || cmp(idle, Num::Whole(0)).is_some_and(|order| order.is_lt()) {
        return Some("idle_unknown");
    }
    if cmp(idle, float(IDLE_SECONDS)).is_some_and(|order| order.is_lt()) {
        return Some("person_active");
    }
    None
}

/// `countdown_holds(started_at, last_look, now, idle)`: no input since the countdown began, and no gap of more than
/// GAP_SECONDS between two looks.
pub fn countdown_holds(
    started_at: &Value,
    last_look: &Value,
    now: &Value,
    idle: &Value,
) -> Py<bool> {
    let Some(idle) = real(idle) else {
        return Ok(false);
    };
    if idle.as_f64().is_nan() {
        return Ok(false);
    }
    let since = number(now)?.as_f64() - number(started_at)?.as_f64();
    if cmp(idle, float(since)).is_some_and(|order| order.is_lt()) {
        return Ok(false);
    }
    Ok((number(now)?.as_f64() - number(last_look)?.as_f64()).abs() <= GAP_SECONDS)
}
