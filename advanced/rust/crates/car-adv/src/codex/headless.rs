//! `codex/headless.py`: one turn of a conversation nothing holds, run here on our own app server, every approval
//! declined (v0.6.16-beta.4; seat adv72d).
//!
//! [`HeadlessRun::resume`] is the route core calls at P16, inside its launch guard: a session of the asking
//! capability's own methods, `thread/resume` with no override, the saved settings checked against an allow-list
//! ([`settings_allowed`]), core's look asked again, then `turn/start` (or `thread/compact/start`) - and the open session
//! handed to the one [`Follower`] of the process, which follows that turn to its end on a thread of its own and never
//! starts another, interrupting it at its cap, at a person's Stop and when the Codex app starts, putting back a model a
//! fallback turn changed, always unsubscribing and closing. The end is one closed word on an in-memory queue
//! ([`Follower::drain`]).
//!
//! The session is any [`Channel`] (car-adv's `session::Session` live, a stand-in in a test); the follower's clock and
//! poll are its own, as the reference's are. The reference's `atexit` hook ([`stop_all`]) is the runtime's to call at
//! exit (S7.2a): Rust has no `atexit`.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_policy::classify::continuation::PROMPT_SEND_LIMIT;

use super::session::{Channel, SessionError};
use crate::vocabulary::RunEnd;

pub const SANDBOXES: [&str; 2] = ["readOnly", "workspaceWrite"];
pub const POLICIES: [&str; 4] = ["untrusted", "on-failure", "on-request", "never"];
pub const REVIEWERS: [&str; 1] = ["user"];
pub const PROFILES: [&str; 2] = [":workspace", ":read-only"];
pub const INTERRUPT_SECONDS: f64 = 15.0;
pub const COMPACT_SECONDS: f64 = 600.0;
pub const POLL_SECONDS: f64 = 0.5;
pub const APP_LOOK_SECONDS: f64 = 10.0;
pub const TURN: &str = "turn";
pub const COMPACT: &str = "compact";
pub const FALLBACK: &str = "fallback";
/// How the Codex app starts its engine on Windows, and so how a turn run here starts its own (M6B).
pub const HEADLESS_CONFIG: [(&str, &str); 2] = [
    ("windows.sandbox", "\"mxc\""),
    ("features.prefer_mxc", "true"),
];

/// Whether Codex refused a turn with no input in this process (silent_continuation, M3B).
pub static EMPTY_REFUSED: AtomicBool = AtomicBool::new(false);

/// What `resume` answers.
pub type Answer = Map;

fn answer(pairs: &[(&str, Value)]) -> Answer {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(*key), value.clone());
    }
    map
}

pub fn preflight() -> Answer {
    answer(&[
        ("outcome", "not_started".into()),
        ("error_code", "queue_preflight_failed".into()),
    ])
}

pub fn spawn_failed() -> Answer {
    answer(&[
        ("outcome", "not_started".into()),
        ("error_code", "queue_spawn_failed".into()),
    ])
}

fn unknown() -> Answer {
    answer(&[
        ("outcome", "unknown".into()),
        ("error_code", "queue_result_unknown".into()),
    ])
}

// ------------------------------------------------------------------------------------------------ the retry settings
struct Retry {
    settings: Vec<(String, String)>,
    until: f64,
}

static RETRY: Mutex<Retry> = Mutex::new(Retry {
    settings: Vec::new(),
    until: 0.0,
});

fn monotonic() -> f64 {
    static START: OnceLock<std::time::Instant> = OnceLock::new();
    START
        .get_or_init(std::time::Instant::now)
        .elapsed()
        .as_secs_f64()
        + 1000.0
}

/// `hold_retry_settings(settings, until)`.
pub fn hold_retry_settings(settings: Vec<(String, String)>, until: f64) {
    let mut held = RETRY.lock().unwrap_or_else(PoisonError::into_inner);
    held.settings = settings;
    held.until = until;
}

/// `retry_settings(now)`: the retry settings in force now, or none.
pub fn retry_settings(now: Option<f64>) -> Vec<(String, String)> {
    let moment = now.unwrap_or_else(monotonic);
    let held = RETRY.lock().unwrap_or_else(PoisonError::into_inner);
    if moment < held.until {
        held.settings.clone()
    } else {
        Vec::new()
    }
}

// ------------------------------------------------------------------------------------------------ the allow-list
fn get<'a>(map: &'a Map, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map.get(key).unwrap_or(&NULL)
}

/// `settings_allowed(resumed)`: an `Err` is the TypeError an unhashable word raises at a set's `in`.
pub fn settings_allowed(resumed: &Value) -> Result<bool, &'static str> {
    let Value::Object(resumed) = resumed else {
        return Ok(false);
    };
    let Value::Object(sandbox) = get(resumed, "sandbox") else {
        return Ok(false);
    };
    if !pyval::in_set(get(sandbox, "type"), &SANDBOXES)? {
        return Ok(false);
    }
    let policy = get(resumed, "approvalPolicy");
    if !matches!(policy, Value::Str(_)) || !pyval::in_set(policy, &POLICIES)? {
        return Ok(false);
    }
    if !pyval::in_set(get(resumed, "approvalsReviewer"), &REVIEWERS)? {
        return Ok(false);
    }
    profile_allowed(get(resumed, "activePermissionProfile"))
}

fn profile_allowed(profile: &Value) -> Result<bool, &'static str> {
    match profile {
        Value::Null => Ok(true),
        Value::Object(map) => {
            if !map.keys().all(|key| {
                key.as_str()
                    .is_some_and(|key| key == "id" || key == "extends")
            }) {
                return Ok(false);
            }
            if !pyval::in_set(get(map, "id"), &PROFILES)? {
                return Ok(false);
            }
            Ok(matches!(get(map, "extends"), Value::Null))
        }
        _ => Ok(false),
    }
}

fn model_text(value: &Value) -> Option<String> {
    match value {
        Value::Str(text) => {
            let count = text.code_points().count();
            (0 < count && count <= 128)
                .then(|| String::from_utf8_lossy(text.as_bytes()).into_owned())
        }
        _ => None,
    }
}

/// `_model(resumed)`.
pub fn model_of(resumed: &Value) -> Option<String> {
    match resumed {
        Value::Object(map) => model_text(get(map, "model")),
        _ => None,
    }
}

/// `_default_model(listed)`: the model Codex marks its default in a model/list answer.
pub fn default_model(listed: &Value) -> Option<String> {
    let Value::Object(listed) = listed else {
        return None;
    };
    let Value::Array(data) = get(listed, "data") else {
        return None;
    };
    for entry in data {
        if let Value::Object(entry) = entry
            && matches!(get(entry, "isDefault"), Value::Bool(true))
        {
            let model = get(entry, "model");
            let model = if pyval::truthy(model) {
                model
            } else {
                get(entry, "id")
            };
            return model_text(model);
        }
    }
    None
}

/// `_turn_id(started)`.
pub fn turn_id_of(started: &Value) -> Option<String> {
    let Value::Object(started) = started else {
        return None;
    };
    let Value::Object(turn) = get(started, "turn") else {
        return None;
    };
    match get(turn, "id") {
        Value::Str(text) if !text.is_empty() => {
            Some(String::from_utf8_lossy(text.as_bytes()).into_owned())
        }
        _ => None,
    }
}

/// `_completed(events, thread, turn_id)`: the status of the turn/completed for that turn, or None.
pub fn completed(
    events: &[Value],
    thread: &Value,
    turn_id: Option<&Value>,
) -> Option<&'static str> {
    for event in events {
        let Value::Object(event) = event else {
            continue;
        };
        if !pyval::is(get(event, "method"), "turn/completed") {
            continue;
        }
        let Value::Object(params) = get(event, "params") else {
            continue;
        };
        let Value::Object(turn) = get(params, "turn") else {
            continue;
        };
        if !pyval::eq(get(params, "threadId"), thread) {
            continue;
        }
        if let Some(wanted) = turn_id
            && !pyval::eq(get(turn, "id"), wanted)
        {
            continue;
        }
        let status = get(turn, "status");
        return Some(
            ["completed", "failed", "interrupted"]
                .into_iter()
                .find(|word| pyval::is(status, word))
                .unwrap_or("other"),
        );
    }
    None
}

// ------------------------------------------------------------------------------------------------ the follower
/// The look at whether the Codex app has started: Ok(the answer) or Err (it raised).
pub type AppLook = Box<dyn FnMut() -> Result<Value, ()> + Send>;
/// A clock in seconds.
pub type Clock = Arc<dyn Fn() -> f64 + Send + Sync>;

/// What the live run is: key, capability, thread, when it started and when it ends by.
#[derive(Clone, Debug, PartialEq)]
pub struct Shown {
    pub key: Value,
    pub capability: String,
    pub thread_id: Value,
    pub started_at: f64,
    pub ends_by: f64,
}

/// How one run ended, for its capability's tick.
#[derive(Clone, Debug, PartialEq)]
pub struct Ended {
    pub key: Value,
    pub capability: String,
    pub end: RunEnd,
    pub model_restored: Option<bool>,
}

struct Live {
    stop: Option<RunEnd>,
    shown: Shown,
}

#[derive(Default)]
struct State {
    run: Option<Live>,
    ends: VecDeque<Ended>,
}

/// The one run a process may have, followed to its end on a thread of its own.
pub struct Follower {
    state: Mutex<State>,
    clock: Clock,
    poll: f64,
}

/// What a run is started with.
pub struct Run {
    pub key: Value,
    pub capability: String,
    pub thread_id: Value,
    pub turn_id: Option<Value>,
    pub seconds: f64,
    pub mode: &'static str,
    pub restore: Option<String>,
    pub app_running: Option<AppLook>,
}

impl Follower {
    pub fn new(clock: Clock, poll: f64) -> Arc<Follower> {
        Arc::new(Follower {
            state: Mutex::new(State::default()),
            clock,
            poll,
        })
    }

    fn held(&self) -> std::sync::MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn now(&self) -> f64 {
        (self.clock)()
    }

    /// `live()`.
    pub fn live(&self) -> Option<Shown> {
        self.held().run.as_ref().map(|run| run.shown.clone())
    }

    /// `stop(key, reason)`: whether a run was asked.
    pub fn stop(&self, key: Option<&Value>, reason: RunEnd) -> bool {
        let mut state = self.held();
        let Some(run) = state.run.as_mut() else {
            return false;
        };
        if let Some(key) = key
            && !pyval::eq(&run.shown.key, key)
        {
            return false;
        }
        if run.stop.is_none() {
            run.stop = Some(reason);
        }
        true
    }

    /// `told(key, capability, end, model_restored)`: kept 64 at most.
    pub fn told(&self, key: Value, capability: &str, end: RunEnd, model_restored: Option<bool>) {
        let mut state = self.held();
        if state.ends.len() == 64 {
            state.ends.pop_front();
        }
        state.ends.push_back(Ended {
            key,
            capability: capability.to_owned(),
            end,
            model_restored,
        });
    }

    /// `drain(capability)`.
    pub fn drain(&self, capability: &str) -> Vec<Ended> {
        let mut state = self.held();
        let (taken, kept): (Vec<Ended>, Vec<Ended>) = state
            .ends
            .drain(..)
            .partition(|end| end.capability == capability);
        state.ends.extend(kept);
        taken
    }

    /// `start(session, ...)`: follow the session's turn on a thread of its own; the session handed back where a run is
    /// live already (one at a time).
    pub fn start(
        self: &Arc<Self>,
        session: Box<dyn Channel>,
        run: Run,
        wall: &dyn Fn() -> f64,
    ) -> Result<(), Box<dyn Channel>> {
        {
            let mut state = self.held();
            if state.run.is_some() {
                return Err(session);
            }
            let now = wall();
            state.run = Some(Live {
                stop: None,
                shown: Shown {
                    key: run.key.clone(),
                    capability: run.capability.clone(),
                    thread_id: run.thread_id.clone(),
                    started_at: now,
                    ends_by: now + run.seconds,
                },
            });
        }
        let follower = Arc::clone(self);
        let worker = std::thread::Builder::new()
            .name("car-headless".into())
            .spawn(move || follower.follow(session, run));
        if worker.is_err() {
            self.held().run = None;
        }
        Ok(())
    }

    fn stopping(&self) -> Option<RunEnd> {
        self.held().run.as_ref().and_then(|run| run.stop)
    }

    fn follow(&self, mut session: Box<dyn Channel>, mut run: Run) {
        // D15: a panic in the follower costs its own run, as the reference's `except Exception` does.
        let done = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            self.until_end(session.as_mut(), &mut run)
        }));
        let end = done.unwrap_or(RunEnd::Lost);
        let restored = run
            .restore
            .as_deref()
            .map(|model| restore(session.as_mut(), &run.thread_id, model));
        let mut params = Map::new();
        params.insert("threadId".into(), run.thread_id.clone());
        let _ = session.call("thread/unsubscribe", Some(Value::Object(params)));
        session.exit();
        self.held().run = None;
        self.told(run.key.clone(), &run.capability, end, restored);
    }

    fn until_end(&self, session: &mut dyn Channel, run: &mut Run) -> RunEnd {
        let deadline = self.now() + run.seconds;
        let mut next_app = self.now();
        loop {
            let events = session.drain_events();
            if let Some(status) = completed(&events, &run.thread_id, run.turn_id.as_ref()) {
                return match status {
                    "completed" => RunEnd::Completed,
                    "failed" => RunEnd::Failed,
                    _ => RunEnd::Interrupted,
                };
            }
            let mut stop = self.stopping();
            if stop.is_none()
                && let Some(look) = run.app_running.as_mut()
                && self.now() >= next_app
            {
                next_app = self.now() + APP_LOOK_SECONDS;
                if let Ok(answer) = look()
                    && pyval::truthy(&answer)
                {
                    stop = Some(RunEnd::Yielded);
                }
            }
            if stop.is_none() && self.now() >= deadline {
                stop = Some(RunEnd::Capped);
            }
            if let Some(why) = stop {
                return self.interrupt(session, run, why);
            }
            std::thread::sleep(std::time::Duration::from_secs_f64(self.poll.max(0.0)));
        }
    }

    fn interrupt(&self, session: &mut dyn Channel, run: &Run, why: RunEnd) -> RunEnd {
        let Some(turn) = run.turn_id.as_ref().filter(|_| run.mode != COMPACT) else {
            return why;
        };
        let mut params = Map::new();
        params.insert("threadId".into(), run.thread_id.clone());
        params.insert("turnId".into(), turn.clone());
        if session
            .call("turn/interrupt", Some(Value::Object(params)))
            .is_err()
        {
            return RunEnd::Lost;
        }
        let deadline = self.now() + INTERRUPT_SECONDS;
        while self.now() < deadline {
            if completed(&session.drain_events(), &run.thread_id, Some(turn)).is_some() {
                return why;
            }
            std::thread::sleep(std::time::Duration::from_secs_f64(self.poll.max(0.0)));
        }
        why
    }
}

/// `Follower._restore(session, thread_id, model)`: the conversation's own model put back and read back.
pub fn restore(session: &mut dyn Channel, thread_id: &Value, model: &str) -> bool {
    let mut update = Map::new();
    update.insert("threadId".into(), thread_id.clone());
    update.insert("model".into(), model.into());
    if session
        .call("thread/settings/update", Some(Value::Object(update)))
        .is_err()
    {
        return false;
    }
    let mut again = Map::new();
    again.insert("threadId".into(), thread_id.clone());
    again.insert("excludeTurns".into(), Value::Bool(true));
    match session.call("thread/resume", Some(Value::Object(again))) {
        Ok(resumed) => model_of(&resumed).as_deref() == Some(model),
        Err(_) => false,
    }
}

/// The one follower of this process.
pub fn follower() -> &'static Arc<Follower> {
    static FOLLOWER: OnceLock<Arc<Follower>> = OnceLock::new();
    FOLLOWER.get_or_init(|| Follower::new(Arc::new(monotonic), POLL_SECONDS))
}

/// `stop_all(follower, seconds)`: the live run interrupted and let go, waited for at most `seconds`. The runtime
/// calls it as the watcher leaves.
pub fn stop_all(follower: &Follower, seconds: f64) {
    if !follower.stop(None, RunEnd::Interrupted) {
        return;
    }
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs_f64(seconds.max(0.0));
    while follower.live().is_some() && std::time::Instant::now() < deadline {
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

// ------------------------------------------------------------------------------------------------ the route
/// Opens a session for the asking capability: Err where it cannot be made.
pub type Opener = Box<dyn FnMut(&str) -> Result<Box<dyn Channel>, ()> + Send>;
/// A look core asks again (`still_unloaded`), or core's launch guard's `__enter__` (what it gives as `permitted`):
/// Ok(the answer) or Err (it raised).
pub type Look<'a> = &'a mut dyn FnMut() -> Result<Value, ()>;
/// `owe(thread_id, model, seconds)`: Ok(the answer) or Err (it raised).
pub type Owe = Box<dyn FnMut(&Value, &str, f64) -> Result<Value, ()> + Send>;

/// The route core calls (P16).
pub struct HeadlessRun {
    pub capability: String,
    pub key: Value,
    open: Opener,
    pub follower: Arc<Follower>,
    pub seconds: f64,
    pub mode: &'static str,
    pub model: Option<String>,
    pub app_running: Option<Box<dyn FnMut() -> AppLook + Send>>,
    pub owe: Option<Owe>,
    /// What the last resume came to before a turn started: refused_settings, or none.
    pub refused: Option<RunEnd>,
    /// A fallback route's conversation found on Codex's default model already: its thread id.
    pub on_default: Option<Value>,
    /// The wall clock a run's start is shown by.
    pub wall: Box<dyn Fn() -> f64 + Send>,
}

fn yes(look: &mut dyn FnMut() -> Result<Value, ()>) -> bool {
    matches!(look(), Ok(Value::Bool(true)))
}

impl HeadlessRun {
    pub const TAKES_WORDS: bool = true;

    pub fn new(capability: &str, key: Value, open: Opener, follower: Arc<Follower>) -> HeadlessRun {
        HeadlessRun {
            capability: capability.to_owned(),
            key,
            open,
            follower,
            seconds: 3600.0,
            mode: TURN,
            model: None,
            app_running: None,
            owe: None,
            refused: None,
            on_default: None,
            wall: Box::new(|| {
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_or(0.0, |since| since.as_secs_f64())
            }),
        }
    }

    /// `resume(thread_id, launch_guard, still_unloaded, words, client_id)`: run the one turn core asked for. Never
    /// raises.
    pub fn resume(
        &mut self,
        thread_id: &Value,
        launch_guard: Option<Look>,
        still_unloaded: Option<Look>,
        words: &Value,
        client_id: &Value,
    ) -> Answer {
        if !ids::is_uuid(thread_id) || self.follower.live().is_some() {
            return preflight();
        }
        if self.mode != COMPACT {
            let fits = match words {
                Value::Str(text) => text.code_points().count() <= PROMPT_SEND_LIMIT,
                _ => false,
            };
            if !fits || !(matches!(client_id, Value::Null) || ids::is_client_id(client_id)) {
                return preflight();
            }
        }
        if let Some(guard) = launch_guard {
            match guard() {
                Ok(Value::Bool(true)) => {}
                Ok(_) => {
                    return answer(&[
                        ("outcome", "not_started".into()),
                        ("error_code", "queue_consent_refused".into()),
                    ]);
                }
                Err(()) => return spawn_failed(),
            }
        }
        let Ok(mut session) = (self.open)(&self.capability) else {
            return spawn_failed();
        };
        if session.enter().is_err() {
            return spawn_failed();
        }
        let mut owing: Option<String> = None;
        let mut answered: Option<Answer> = None;
        let (outcome, handed_session) = self.run(
            &mut session,
            thread_id,
            still_unloaded,
            words,
            client_id,
            &mut owing,
            &mut answered,
        );
        match handed_session {
            Some(()) => outcome,
            None => {
                if let Some(original) = owing {
                    let refused = answered
                        .as_ref()
                        .is_some_and(|found| pyval::is(get(found, "outcome"), "not_started"));
                    let restored = restore(session.as_mut(), thread_id, &original);
                    self.follower.told(
                        self.key.clone(),
                        &self.capability,
                        if refused {
                            RunEnd::Failed
                        } else {
                            RunEnd::Lost
                        },
                        Some(restored),
                    );
                }
                session.exit();
                outcome
            }
        }
    }

    /// The body of `resume` after the session opened: its answer, and Some where the session was handed over (taken
    /// out of `session`, which is then a spent placeholder).
    #[allow(clippy::too_many_arguments)]
    fn run(
        &mut self,
        session: &mut Box<dyn Channel>,
        thread_id: &Value,
        still_unloaded: Option<Look>,
        words: &Value,
        client_id: &Value,
        owing: &mut Option<String>,
        answered: &mut Option<Answer>,
    ) -> (Answer, Option<()>) {
        let mut params = Map::new();
        params.insert("threadId".into(), thread_id.clone());
        params.insert("excludeTurns".into(), Value::Bool(true));
        let Ok(resumed) = session.call("thread/resume", Some(Value::Object(params))) else {
            return (preflight(), None);
        };
        match settings_allowed(&resumed) {
            Err(_) => return (unknown(), None),
            Ok(false) => {
                self.refused = Some(RunEnd::RefusedSettings);
                return (preflight(), None);
            }
            Ok(true) => {}
        }
        let original = model_of(&resumed);
        if self.mode == FALLBACK {
            self.model = session
                .call("model/list", Some(Value::Object(Map::new())))
                .ok()
                .and_then(|listed| default_model(&listed));
            if self.model.is_some() && self.model == original {
                self.on_default = Some(thread_id.clone());
            }
            if self.model.is_none() || original.is_none() || self.model == original {
                return (preflight(), None);
            }
        }
        if let Some(look) = still_unloaded
            && !yes(look)
        {
            return (preflight(), None);
        }
        if self.mode == FALLBACK {
            let seconds = self.seconds;
            let original_text = original.clone().unwrap_or_default();
            if let Some(owe) = self.owe.as_mut()
                && !matches!(
                    owe(thread_id, &original_text, seconds),
                    Ok(Value::Bool(true))
                )
            {
                return (preflight(), None);
            }
            *owing = original.clone();
        }
        let started = self.start_turn(session.as_mut(), thread_id, words, client_id);
        *answered = Some(started.clone());
        if !(pyval::is(get(&started, "outcome"), "ran")
            || pyval::is(get(&started, "outcome"), "accepted"))
        {
            return (started, None);
        }
        let turn = started
            .get("turn_id")
            .cloned()
            .filter(|turn| !matches!(turn, Value::Null));
        let run = Run {
            key: self.key.clone(),
            capability: self.capability.clone(),
            thread_id: thread_id.clone(),
            turn_id: turn,
            seconds: if self.mode == COMPACT {
                COMPACT_SECONDS
            } else {
                self.seconds
            },
            mode: self.mode,
            restore: if self.mode == FALLBACK {
                original
            } else {
                None
            },
            app_running: self.app_running.as_mut().map(|make| make()),
        };
        let taken = std::mem::replace(session, Box::new(Spent));
        match self.follower.start(taken, run, &*self.wall) {
            Ok(()) => (started, Some(())),
            Err(back) => {
                *session = back;
                (unknown(), None)
            }
        }
    }

    /// `_start(session, thread_id, words, client_id)`: turn/start or thread/compact/start.
    fn start_turn(
        &mut self,
        session: &mut dyn Channel,
        thread_id: &Value,
        words: &Value,
        client_id: &Value,
    ) -> Answer {
        let mut params = Map::new();
        params.insert("threadId".into(), thread_id.clone());
        let method = if self.mode == COMPACT {
            "thread/compact/start"
        } else {
            let input = if pyval::truthy(words) {
                let mut item = Map::new();
                item.insert("type".into(), "text".into());
                item.insert("text".into(), words.clone());
                vec![Value::Object(item)]
            } else {
                Vec::new()
            };
            params.insert("input".into(), Value::Array(input));
            if !matches!(client_id, Value::Null) {
                params.insert("clientUserMessageId".into(), client_id.clone());
            }
            if self.mode == FALLBACK {
                params.insert(
                    "model".into(),
                    self.model.as_deref().map_or(Value::Null, Value::from),
                );
            }
            "turn/start"
        };
        let started = match session.call(method, Some(Value::Object(params))) {
            Ok(started) => started,
            Err(SessionError::Refused) => return preflight(),
            Err(error) => {
                if error.method() == Some(method) {
                    if method == "turn/start" && !pyval::truthy(words) {
                        EMPTY_REFUSED.store(true, Ordering::SeqCst);
                    }
                    return answer(&[
                        ("outcome", "not_started".into()),
                        ("error_code", "queue_preflight_failed".into()),
                        ("refused_by_codex", Value::Bool(true)),
                    ]);
                }
                return answer(&[
                    ("outcome", "unknown".into()),
                    (
                        "error_code",
                        if error.text() == "protocol_timeout" {
                            "queue_timeout"
                        } else {
                            "queue_result_unknown"
                        }
                        .into(),
                    ),
                ]);
            }
        };
        if self.mode == COMPACT {
            return answer(&[
                ("outcome", "accepted".into()),
                ("queue_id", Value::Null),
                ("turn_id", Value::Null),
            ]);
        }
        match turn_id_of(&started) {
            Some(turn) if ids::is_uuid(&Value::from(turn.as_str())) => {
                answer(&[("outcome", "ran".into()), ("turn_id", turn.into())])
            }
            _ => unknown(),
        }
    }
}

/// A session already handed to the follower: what `resume` holds in its place.
struct Spent;

impl Channel for Spent {
    fn enter(&mut self) -> Result<(), SessionError> {
        Err(SessionError::Raised("ValueError"))
    }
    fn submit(&mut self, _: &str, _: Option<Value>) -> Result<i64, SessionError> {
        Err(SessionError::Raised("ValueError"))
    }
    fn receive(&mut self, _: &str, _: i64, _: Option<&Value>) -> Result<Value, SessionError> {
        Err(SessionError::Raised("ValueError"))
    }
    fn drain_events(&mut self) -> Vec<Value> {
        Vec::new()
    }
    fn exit(&mut self) {}
}

/// `live_session(paths)`: a factory of live sessions against the Codex the watcher drives (`backend`), each restricted
/// to the asking capability's methods, started with HEADLESS_CONFIG and the retry settings in force.
pub fn live_session(
    backend: Box<dyn Fn() -> Option<car_codex::transport::Backend> + Send>,
) -> Opener {
    Box::new(move |capability: &str| {
        let made = backend().ok_or(())?;
        let mut config: Vec<(String, String)> = HEADLESS_CONFIG
            .iter()
            .map(|(key, value)| ((*key).to_owned(), (*value).to_owned()))
            .collect();
        config.extend(retry_settings(None));
        super::session::Session::new(made, None, Some(capability), config)
            .map(|session| Box::new(session) as Box<dyn Channel>)
            .map_err(|_| ())
    })
}
