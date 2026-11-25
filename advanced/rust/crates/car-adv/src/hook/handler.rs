//! The Stop hook's handler (`hook/handler.py`): what runs when Codex ends a turn, while "Continue inside the turn" is on.
//!
//! Codex starts the hook launcher, which starts this and hands it Codex's one JSON object. It answers within
//! [`BUDGET_SECONDS`] or passes - exits 0 having written nothing, which lets the turn end as it would have - and passes on
//! every doubt.
//!
//! What it reads of the input: the keys [`allowed_keys`] names, and no other key's value, ever - the last assistant message,
//! the transcript's path and the prompt are dropped as the JSON is parsed (B9). Input over [`MAX_INPUT`] bytes, or not one
//! JSON object, passes.
//!
//! What it decides, for a Stop of the conversation the input names: the capability is on and automatic recovery is on for
//! that conversation; the conversation's latest turn in Codex's history failed, is the turn the input names, and core's own
//! detection takes it; its kind is one a hook can wait for (a transient one whose first wait is [`FIRST_WAIT_MOST`] seconds
//! or less - never a usage limit); the shared claim grants it. Then, and only then, it prints the block, whose reason is the
//! standard continuation in the person's language with the record's marker after it.
//!
//! SEAT S7.3c. The tag's `Hands.live` (the capability's state read through `Arming`, Codex's history through `LocalSource`,
//! the settings through `config`, the claim through `engine/hookclaims.claim`) is [`Hands`] here, a trait: the live one is
//! S7.3d's, over S7.2a's runtime; the diffs hand it the data of a case. `main`'s budget, its worker thread and what it writes
//! are the tag's.

use std::io::{Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use car_codex::payload::detect;
use car_machine::compat::loads;
use car_machine::domain::ids;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;
use car_policy::classify::continuation::{self, Environ};
use car_policy::classify::ladder;
use car_policy::settings::category_enabled;

use super::format::{FORMAT, allowed_keys, answer};
use crate::vocabulary::HookOutcome;

pub const CAPABILITY: &str = "stop_hook_continuation";
/// Bytes of input read at most; more passes.
pub const MAX_INPUT: usize = 1024 * 1024;
/// An answer within this, or the turn ends as it would have.
pub const BUDGET_SECONDS: f64 = 2.0;
/// No claim begun with less of the budget left than this.
pub const CLAIM_MARGIN_SECONDS: f64 = 0.6;
/// A claim begun is let finish, and its answer written, within this.
pub const COMMIT_GRACE_SECONDS: f64 = 3.0;
/// The kinds a hook may continue: core's transient ones whose first step waits a minute at most.
pub const ALLOWED: [&str; 4] = [
    "network_transient",
    "timeout",
    "server_5xx",
    "stream_interrupted",
];
pub const FIRST_WAIT_MOST: i64 = 60;

/// `pick(document)`: the allowed keys of `document`, read by name and no other: None for anything that is not one object.
pub fn pick(document: &Value) -> Option<Map> {
    let Value::Object(found) = document else {
        return None;
    };
    let mut kept = Map::new();
    for key in allowed_keys(&FORMAT) {
        if let Some(value) = found.get(key) {
            kept.insert(Str::from(key), value.clone());
        }
    }
    Some(kept)
}

/// `read_input(stream)` over the bytes it read: the one JSON object, as `pick` keeps it, or None: over MAX_INPUT bytes, not
/// UTF-8, not JSON, not an object.
pub fn read_input(data: &[u8]) -> Option<Map> {
    if data.len() > MAX_INPUT {
        return None;
    }
    let text = std::str::from_utf8(data).ok()?;
    let document = loads(text).ok()?;
    pick(&document)
}

/// `stop_of(picked)`: (thread id, turn id or None) for a Stop the handler may look at, or None: another event, a stop that
/// follows a hook's own block, or a conversation not named by its id.
pub fn stop_of(picked: &Map) -> Option<(String, Option<String>)> {
    if !picked
        .get(FORMAT.event_key)
        .is_some_and(|event| pyval::is(event, FORMAT.event))
        || matches!(picked.get(FORMAT.active_key), Some(Value::Bool(true)))
    {
        return None;
    }
    let null = Value::Null;
    let thread = picked.get(FORMAT.thread_key).unwrap_or(&null);
    let turn = picked.get(FORMAT.turn_key).unwrap_or(&null);
    if !ids::is_uuid(thread) || !(matches!(turn, Value::Null) || ids::is_uuid(turn)) {
        return None;
    }
    let text = |value: &Value| pyval::text(value).map(str::to_owned);
    Some((text(thread)?, text(turn)))
}

/// `turn_key(turn_id)`: the digest the claim keeps a turn under: never the turn's id itself.
pub fn turn_key(turn_id: &str) -> String {
    car_machine::hash::hex(&car_machine::hash::sha256(
        format!("turn:{turn_id}").as_bytes(),
    ))
}

/// What the decision reads and the one write it makes, each replaceable by a test (`Hands`).
pub trait Hands: Send + Sync {
    /// Whether the capability is on.
    fn armed(&self) -> Result<bool, String>;
    /// The person's settings.
    fn settings(&self) -> Result<Value, String>;
    /// Codex's latest turn of a conversation, as core's reader gives it (`Null` for none).
    fn latest(&self, thread: &str) -> Result<Value, String>;
    /// The shared claim (`engine/hookclaims.claim`): what it wrote, or None where nothing was written.
    fn claim(&self, failure: &Map, turn_key: &str, now: f64)
    -> Result<Option<HookOutcome>, String>;
    /// `time.time()`.
    fn clock(&self) -> f64;
    /// The environment and Windows' preferred languages the continuation's language is read from.
    fn variable(&self, name: &str) -> Option<String>;
    fn languages(&self) -> Vec<String>;
}

/// `continues(failure, values)`: whether `failure` (core's detection of a latest turn) is one a hook may continue under the
/// settings `values`.
pub fn continues(failure: &Map, values: &Value) -> bool {
    let category = failure.get("category").cloned().unwrap_or(Value::Null);
    let Some(word) = pyval::text(&category) else {
        return false;
    };
    if !ALLOWED.contains(&word) || !category_enabled(values, word).unwrap_or(false) {
        return false;
    }
    ladder::wait_before(values, &Value::from(1), &category)
        .is_ok_and(|waited| waited <= FIRST_WAIT_MOST)
}

/// `reason_for(failure, values)`: the block's reason: the standard continuation for the failure, in the person's language and
/// style, and the record's marker after it, as core ends every continuation it sends with one.
pub fn reason_for(failure: &Map, values: &Value, hands: &dyn Hands) -> Result<String, String> {
    let get = |name: &str| failure.get(name).cloned().unwrap_or(Value::Null);
    let mut row = Map::new();
    row.insert(Str::from("thread_id"), get("thread_id"));
    row.insert(Str::from("category"), get("category"));
    row.insert(Str::from("recovery_attempts"), Value::from(0));
    let row = Value::Object(row);
    let variable = |name: &str| hands.variable(name);
    let languages = || hands.languages();
    let environ = Environ {
        variable: &variable,
        windows: &languages,
    };
    let null = Value::Null;
    let clock = car_platform::localclock::Crt;
    let settings = continuation::Settings {
        values,
        row: &row,
        limits: &null,
        environ: &environ,
        clock: &clock,
    };
    let text = continuation::for_settings(&get("category"), &settings).map_err(str::to_owned)?;
    let key = pyval::text(&get("interruption_id"))
        .map(str::to_owned)
        .ok_or_else(|| "KeyError".to_owned())?;
    Ok(format!("{text}\n\n{}", ids::short_marker(&key)))
}

/// `decide(picked, hands, started=, claiming=)`: the block's reason, or None to pass. `started` is when the handler began
/// (the budget runs from it), and `claiming` is set the moment a claim begins - past it, the answer is let finish.
pub fn decide(
    picked: &Map,
    hands: &dyn Hands,
    started: Option<f64>,
    claiming: Option<&AtomicBool>,
) -> Result<Option<String>, String> {
    let started = started.unwrap_or_else(|| hands.clock());
    let Some((thread, turn)) = stop_of(picked) else {
        return Ok(None);
    };
    if !hands.armed()? {
        return Ok(None);
    }
    let values = hands.settings()?;
    let latest = hands.latest(&thread)?;
    let Some(failure) = detect(&latest).map_err(str::to_owned)? else {
        return Ok(None);
    };
    let same = |name: &str, wanted: &str| {
        failure
            .get(name)
            .is_some_and(|found| pyval::is(found, wanted))
    };
    if !same("thread_id", &thread) || turn.as_deref().is_some_and(|turn| !same("turn_id", turn)) {
        return Ok(None);
    }
    if !continues(&failure, &values) {
        return Ok(None);
    }
    let reason = reason_for(&failure, &values, hands)?;
    let now = hands.clock();
    if now - started > BUDGET_SECONDS - CLAIM_MARGIN_SECONDS {
        return Ok(None);
    }
    if let Some(claiming) = claiming {
        claiming.store(true, Ordering::SeqCst);
    }
    let turn_id = failure
        .get("turn_id")
        .and_then(pyval::text)
        .ok_or_else(|| "KeyError".to_owned())?
        .to_owned();
    let outcome = hands.claim(&failure, &turn_key(&turn_id), now)?;
    Ok((outcome == Some(HookOutcome::Blocked)).then_some(reason))
}

/// `argparse`'s `_negative_number_matcher`: `^-\d+$|^-\d*\.\d+$`; the parser has no option that looks like one, so such an
/// argument is a value, not a flag.
fn negative_number(text: &str) -> bool {
    let Some(rest) = text.strip_prefix('-') else {
        return false;
    };
    let digits = |part: &str| {
        part.chars()
            .all(|each| car_machine::pytext::decimal_value(each).is_some())
    };
    match rest.split_once('.') {
        None => !rest.is_empty() && digits(rest),
        Some((whole, fraction)) => digits(whole) && !fraction.is_empty() && digits(fraction),
    }
}

/// `argparse`'s `parse_known_args` of `--home <path>` (no help, abbreviations of `--home` of at least `--h` taken), or None
/// where argparse would exit: the option without its value.
fn home_argument(argv: &[String]) -> Option<Option<String>> {
    let mut home = None;
    let mut at = 0;
    while at < argv.len() {
        let arg = &argv[at];
        let (name, inline) = match arg.split_once('=') {
            Some((name, value)) if name.starts_with("--") => (name, Some(value.to_owned())),
            _ => (arg.as_str(), None),
        };
        if name.starts_with("--") && name.len() >= 3 && "--home".starts_with(name) {
            match inline {
                Some(value) => home = Some(value),
                None => {
                    at += 1;
                    match argv.get(at) {
                        Some(value)
                            if !value.starts_with('-')
                                || value.len() == 1
                                || negative_number(value) =>
                        {
                            home = Some(value.clone());
                        }
                        _ => return None,
                    }
                }
            }
        }
        at += 1;
    }
    Some(home)
}

/// `main(argv, stdin=, stdout=, hands=)`: the handler, as the launcher runs it: `--home <installation home>`. Always 0; the
/// block on standard output only where `decide` granted one. Past the budget with no claim begun it passes at once, whatever
/// is still being read. `hands_for` makes the live hands of a `--home` (S7.3d's); a test hands `hands` instead.
pub fn main(
    argv: &[String],
    stdin: Box<dyn Read + Send>,
    stdout: &mut dyn Write,
    hands: Option<Arc<dyn Hands>>,
    hands_for: Option<&dyn Fn(&str) -> Option<Arc<dyn Hands>>>,
) -> i32 {
    let Some(home) = home_argument(argv) else {
        return 0;
    };
    let started = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0.0, |found| found.as_secs_f64());
    let begun = Instant::now();
    let done = Arc::new((Mutex::new(false), Condvar::new()));
    let claiming = Arc::new(AtomicBool::new(false));
    let found: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));
    let used = match (hands, home, hands_for) {
        (Some(hands), _, _) => Some(hands),
        (None, Some(home), Some(make)) if !home.is_empty() => make(&home),
        _ => None,
    };
    let (done2, claiming2, found2) = (Arc::clone(&done), Arc::clone(&claiming), Arc::clone(&found));
    let mut stdin = stdin;
    let worker = std::thread::Builder::new()
        .name("stop-hook".to_owned())
        .spawn(move || {
            let work = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let mut data = Vec::new();
                let read = (&mut stdin)
                    .take(MAX_INPUT as u64 + 1)
                    .read_to_end(&mut data);
                if read.is_err() {
                    return;
                }
                let Some(picked) = read_input(&data) else {
                    return;
                };
                let Some(used) = used else {
                    return;
                };
                if let Ok(Some(reason)) = decide(&picked, &*used, Some(started), Some(&claiming2)) {
                    *found2
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(reason);
                }
            }));
            let _ = work;
            let (flag, cv) = &*done2;
            *flag
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) = true;
            cv.notify_all();
        });
    if worker.is_err() {
        return 0;
    }
    let wait = |seconds: f64| {
        let (flag, cv) = &*done;
        let held = flag
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let (held, _) = cv
            .wait_timeout_while(
                held,
                Duration::from_secs_f64(seconds.max(0.0)),
                |finished| !*finished,
            )
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *held
    };
    if !wait(BUDGET_SECONDS) && (!claiming.load(Ordering::SeqCst) || !wait(COMMIT_GRACE_SECONDS)) {
        let _ = begun;
        return 0;
    }
    let reason = found
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .clone();
    if let Some(reason) = reason.filter(|each| !each.is_empty()) {
        let text = to_string(
            &answer(&reason, &FORMAT),
            &Options::new().ensure_ascii(false),
        );
        if let Ok(text) = text {
            if stdout.write_all(text.as_bytes()).is_err() || stdout.flush().is_err() {
                return 0;
            }
        }
    }
    0
}
