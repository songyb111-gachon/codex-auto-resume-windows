//! Seat S7.4: `measure.py` - the measurement harness: what the owner runs by hand to find whether a capability can
//! work on the Codex in force, one content-free record per run ([`crate::evidence`]).
//!
//! Nothing here runs unless a person asks for it, and every external effect is a seam the caller hands in: the
//! session factory, the launcher, the engine's CLI, the Desktop's IPC look, the named hands, the clock and the random
//! ids. A seat proves it only over the tests' fakes (the owner's Q2 (a)); no seat ever runs it for real.
//!
//! The Python exceptions a probe lets out are [`Raised`]: what `probe()` turns into a verdict (an `AdapterError`, an
//! `EvidenceUnavailable`, a `SessionRefused`) and what `run()` lets out (anything else, by class).
//!
//! Ported here (the diffs hold each to the tag): `Context` and its hands, `probe`, `run`, `complete`,
//! `_threads_valid`, `_versions`, `_iso`, `_completed_status`, `_await_turn`, `_await_taken`, `_goal_status` and the
//! probes named in [`ported`]. The others answer [`Raised::Unported`] (GROUNDWORK, seat S7.4: what each waits for).

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use car_machine::domain::ids::is_uuid;
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::py_str;

use crate::codex::protocol::methods_for;
use crate::codex::session::SessionError;
use crate::evidence::{self, Envelope, Fault};
use crate::vocabulary::{Measurement, Verdict};

#[path = "measure_looks.rs"]
mod looks;
#[path = "measure_usage.rs"]
mod usage;

// ------------------------------------------------------------------------------------------------ the raised
/// A Python exception out of a probe or a seam, by what the reference does with it.
#[derive(Clone, Debug, PartialEq)]
pub enum Raised {
    /// `AdapterError` and its subclasses: `class` is the class's name, `method` the attribute a `RefusedByCodex`
    /// carries (`hasattr(exc, "method")`), `code` its `code`.
    Adapter {
        class: String,
        method: Option<String>,
        code: Value,
    },
    /// `EvidenceUnavailable(reason)`.
    Unavailable(&'static str),
    /// `SessionRefused`.
    Refused,
    /// `EvidenceError` (evidence.build/write) or another error class out of them.
    Evidence(Fault),
    /// Any other exception, by class: it leaves `run()`.
    Other(String),
    /// A probe this seat has not ported (GROUNDWORK, seat S7.4).
    Unported(Measurement),
}

impl Raised {
    pub fn class(&self) -> String {
        match self {
            Raised::Adapter { class, .. } => class.clone(),
            Raised::Unavailable(_) => "EvidenceUnavailable".into(),
            Raised::Refused => "SessionRefused".into(),
            Raised::Evidence(fault) => fault.class().into(),
            Raised::Other(class) => class.clone(),
            Raised::Unported(_) => "NotPorted".into(),
        }
    }

    fn is_adapter(&self) -> bool {
        matches!(self, Raised::Adapter { .. })
    }
}

impl From<SessionError> for Raised {
    fn from(error: SessionError) -> Raised {
        match error {
            SessionError::Refused => Raised::Refused,
            SessionError::Adapter(code) => Raised::Adapter {
                class: "AdapterError".into(),
                method: None,
                code: Value::Str(Str::new(code)),
            },
            SessionError::ByCodex { method, code } => Raised::Adapter {
                class: "RefusedByCodex".into(),
                method: Some(method),
                code: code.map_or(Value::Null, Value::from),
            },
            SessionError::Raised(class) => Raised::Other(class.into()),
        }
    }
}

pub type Res<T> = Result<T, Raised>;

// ------------------------------------------------------------------------------------------------ the seams
/// A one-turn session as a probe uses it (`codex/protocol.Session` or a test's fake).
pub trait MeasureSession {
    /// `__enter__`.
    fn enter(&mut self) -> Res<()>;
    fn call(&mut self, method: &str, params: Option<Value>) -> Res<Value>;
    fn drain_events(&mut self) -> Vec<Value>;
    fn declined_count(&mut self) -> Value;
    /// `__exit__`: never raises.
    fn exit(&mut self);
}

impl MeasureSession for crate::codex::session::Session {
    fn enter(&mut self) -> Res<()> {
        crate::codex::session::Channel::enter(self).map_err(Raised::from)
    }
    fn call(&mut self, method: &str, params: Option<Value>) -> Res<Value> {
        crate::codex::session::Channel::call(self, method, params).map_err(Raised::from)
    }
    fn drain_events(&mut self) -> Vec<Value> {
        crate::codex::session::Channel::drain_events(self)
    }
    fn declined_count(&mut self) -> Value {
        Value::from(crate::codex::session::Session::declined_count(self))
    }
    fn exit(&mut self) {
        crate::codex::session::Channel::exit(self);
    }
}

/// `session_factory(measurement[, home=...][, config=...])`. `takes_home` / `takes_config` answer what
/// `inspect.signature(factory).parameters` holds.
pub trait SessionFactory {
    fn open(
        &mut self,
        measurement: Measurement,
        home: Option<&Path>,
        config: Option<Vec<String>>,
    ) -> Res<Box<dyn MeasureSession>>;
    fn takes_home(&self) -> bool;
    fn takes_config(&self) -> bool;
}

/// The run's clock and random ids: `time.time`, `time.monotonic`, `time.sleep`, `uuid.uuid4`.
pub trait World {
    fn time(&mut self) -> f64;
    fn monotonic(&mut self) -> f64;
    fn sleep(&mut self, seconds: f64);
    fn uuid4(&mut self) -> String;
}

/// The system's clock and ids (the product's; never a diff's).
pub struct SystemWorld;

impl World for SystemWorld {
    fn time(&mut self) -> f64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0.0, |elapsed| elapsed.as_secs_f64())
    }
    fn monotonic(&mut self) -> f64 {
        use std::sync::OnceLock;
        static START: OnceLock<std::time::Instant> = OnceLock::new();
        START
            .get_or_init(std::time::Instant::now)
            .elapsed()
            .as_secs_f64()
    }
    fn sleep(&mut self, seconds: f64) {
        if seconds.is_finite() && seconds > 0.0 {
            std::thread::sleep(std::time::Duration::from_secs_f64(seconds));
        }
    }
    fn uuid4(&mut self) -> String {
        let mut bytes = [0u8; 16];
        if car_platform::random::fill(&mut bytes).is_err() {
            return "00000000-0000-4000-8000-000000000000".into();
        }
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
        format!(
            "{}-{}-{}-{}-{}",
            &hex[..8],
            &hex[8..12],
            &hex[12..16],
            &hex[16..20],
            &hex[20..]
        )
    }
}

/// A named hand (`open_link`, `power`, `wake_after`, `scratch_cli`, `anchor_request`, `stop_hook`, `steer_ipc`,
/// `m4_hook_note`, ...): called with the reference's arguments as values.
pub type Hand = Box<dyn FnMut(&[Value]) -> Res<Value>>;
/// `cli(arguments)` / `ipc()` / `launcher()`.
pub type Cli = Box<dyn FnMut(&[String]) -> Res<Value>>;
pub type Look = Box<dyn FnMut() -> Res<Value>>;

/// The backend as a measurement reads it: `engine_version` and `codex_home` (`getattr(..., None)`).
#[derive(Clone, Debug)]
pub struct BackendView {
    pub engine_version: Value,
    pub codex_home: Option<PathBuf>,
}

impl Default for BackendView {
    fn default() -> BackendView {
        BackendView {
            engine_version: Value::Null,
            codex_home: None,
        }
    }
}

/// The module's timing constants, which the tests patch (`_M6_TURN_SECONDS`, ...): the reference's values by default.
#[derive(Clone, Debug)]
pub struct Timing {
    pub m2b_queue: f64,
    pub m2b_poll: f64,
    pub m6_turn: f64,
    pub m6_interrupt: f64,
    pub m6_poll: f64,
    pub mu_spacing: f64,
}

impl Default for Timing {
    fn default() -> Timing {
        Timing {
            m2b_queue: 60.0,
            m2b_poll: 1.0,
            m6_turn: 180.0,
            m6_interrupt: 15.0,
            m6_poll: 0.25,
            mu_spacing: 60.0,
        }
    }
}

/// What `run` is handed besides the measurement (its keyword arguments).
#[derive(Default)]
pub struct Seams {
    pub session_factory: Option<Box<dyn SessionFactory>>,
    pub launcher: Option<Look>,
    pub backend: Option<BackendView>,
    pub cli: Option<Cli>,
    pub ipc: Option<Look>,
    pub hands: BTreeMap<String, Hand>,
}

// ------------------------------------------------------------------------------------------------ the context
pub const SAMPLE_THREAD: &str = "00000000-0000-7000-8000-000000000000";
pub const SAMPLE_CLIENT_ID: &str = "00000000-0000-7000-8000-000000000001";
pub const SAMPLE_M2B_CLIENT_ID: &str = "00000000-0000-7000-8000-000000000002";
pub const M2B_PROMPT: &str = "Reply with the single word: ok.";
pub const M6_PROMPT: &str = "Run the harmless command `whoami` and report what it prints. If running it is not approved, say so and stop.";
pub const MQP_MOST: usize = 4;

/// `Context`: what one measurement is run with.
pub struct Context<'w> {
    pub measurement: Measurement,
    pub seams: &'w mut Seams,
    pub versions: Map,
    pub thread_given: bool,
    pub probe_threads: Vec<String>,
    pub probe_thread: String,
    pub may_spend: bool,
    pub world: &'w mut dyn World,
    pub timing: Timing,
}

impl Context<'_> {
    /// `ctx.open()`.
    fn open(&mut self) -> Res<Box<dyn MeasureSession>> {
        let methods = methods_for(self.measurement);
        if methods
            .iter()
            .all(|method| *method == "initialize" || *method == "initialized")
        {
            return Err(Raised::Unavailable("this measurement opens no session"));
        }
        let Some(factory) = self.seams.session_factory.as_mut() else {
            return Err(Raised::Unavailable("no session was provided"));
        };
        factory.open(self.measurement, None, None)
    }

    /// `with ctx.open() as session: body(session)`: `__exit__` runs however the body ends; a failed `__enter__`
    /// runs none.
    fn with_session<T>(
        &mut self,
        body: impl FnOnce(&mut Self, &mut dyn MeasureSession) -> Res<T>,
    ) -> Res<T> {
        let mut session = self.open()?;
        session.enter()?;
        let answer = body(self, session.as_mut());
        session.exit();
        answer
    }

    /// `ctx.given(observed)`.
    fn given(&self, mut observed: Map) -> Map {
        observed.insert(Str::new("thread_given"), Value::Bool(self.thread_given));
        observed
    }

    fn thread_value(&self) -> Value {
        Value::Str(Str::new(&self.probe_thread))
    }

    /// `ctx.cli_help(arguments)`.
    pub fn cli_help(&mut self, arguments: &[&str]) -> Option<String> {
        let cli = self.seams.cli.as_mut()?;
        let arguments: Vec<String> = arguments.iter().map(|each| (*each).to_owned()).collect();
        match cli(&arguments) {
            Ok(Value::Str(found)) => Some(py_str(&Value::Str(found))),
            _ => None,
        }
    }

    /// `ctx._hand(name, *arguments)`: None where there is no hand or it raised.
    pub fn hand(&mut self, name: &str, arguments: &[Value]) -> Option<Value> {
        let hand = self.seams.hands.get_mut(name)?;
        hand(arguments).ok()
    }

    /// `ctx.ipc_look()`.
    pub fn ipc_look(&mut self) -> Map {
        let Some(ipc) = self.seams.ipc.as_mut() else {
            return Map::new();
        };
        match ipc() {
            Ok(Value::Object(found)) => found,
            _ => Map::new(),
        }
    }
}

// ------------------------------------------------------------------------------------------------ helpers
fn key(name: &str) -> Str {
    Str::new(name)
}

fn text(value: &str) -> Value {
    Value::Str(Str::new(value))
}

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(key(name), value);
    }
    Value::Object(map)
}

fn observed(pairs: Vec<(&str, Value)>) -> Map {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(key(name), value);
    }
    map
}

/// `value.get(name) if isinstance(value, dict) else None`.
pub fn get<'a>(value: &'a Value, name: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(&key(name)),
        _ => None,
    }
}

fn is_dict(value: &Value) -> bool {
    matches!(value, Value::Object(_))
}

fn is_str_eq(value: Option<&Value>, wanted: &str) -> bool {
    matches!(value, Some(Value::Str(found)) if found.as_bytes() == wanted.as_bytes())
}

fn as_text(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::Str(found)) => Some(py_str(&Value::Str(found.clone()))),
        _ => None,
    }
}

/// A probe's answer: (verdict, observed, note).
pub type Found = (Verdict, Map, Option<String>);

fn blocked(note: &str, observed: Map) -> Res<Found> {
    Ok((Verdict::Blocked, observed, Some(note.to_owned())))
}

/// `codex.values._turn_status`: the engine's closed word, `other` for anything else.
fn core_status(status: &str) -> &'static str {
    match status {
        "completed" => "completed",
        "failed" => "failed",
        "inProgress" => "inProgress",
        "interrupted" => "interrupted",
        _ => "other",
    }
}

/// `_completed_status(events, thread, turn_id)`.
pub fn completed_status(events: &[Value], thread: &str, turn_id: Option<&str>) -> Option<String> {
    for event in events {
        if !is_dict(event) || !is_str_eq(get(event, "method"), "turn/completed") {
            continue;
        }
        let Some(params) = get(event, "params").filter(|each| is_dict(each)) else {
            continue;
        };
        if !is_str_eq(get(params, "threadId"), thread) {
            continue;
        }
        let Some(turn) = get(params, "turn").filter(|each| is_dict(each)) else {
            continue;
        };
        if let Some(wanted) = turn_id
            && !is_str_eq(get(turn, "id"), wanted)
        {
            continue;
        }
        return Some(match as_text(get(turn, "status")) {
            Some(status) => core_status(&status).to_owned(),
            None => "other".to_owned(),
        });
    }
    None
}

/// `_goal_status(result)`.
pub fn goal_status(result: &Value) -> Option<String> {
    let goal = get(result, "goal")?;
    as_text(get(goal, "status"))
}

/// `_await_taken(session, thread, client_id, seconds)`.
fn await_taken(
    ctx: &mut Context<'_>,
    session: &mut dyn MeasureSession,
    client_id: &str,
    seconds: f64,
) -> Res<bool> {
    let deadline = ctx.world.monotonic() + seconds;
    loop {
        let listed = match session.call(
            "thread/queue/list",
            Some(object(vec![("threadId", ctx.thread_value())])),
        ) {
            Ok(listed) => listed,
            Err(raised) if raised.is_adapter() => return Ok(false),
            Err(raised) => return Err(raised),
        };
        if let Some(Value::Array(items)) = get(&listed, "data") {
            let waiting = items.iter().any(|item| {
                is_dict(item) && is_str_eq(get(item, "clientUserMessageId"), client_id)
            });
            if !waiting {
                return Ok(true);
            }
        }
        if ctx.world.monotonic() >= deadline {
            return Ok(false);
        }
        let poll = ctx.timing.m2b_poll;
        ctx.world.sleep(poll);
    }
}

/// `_await_turn(session, thread, turn_id, seconds, seen)`.
fn await_turn(
    ctx: &mut Context<'_>,
    session: &mut dyn MeasureSession,
    turn_id: Option<&str>,
    seconds: f64,
    mut seen: Option<&mut Vec<Value>>,
) -> Option<String> {
    let deadline = ctx.world.monotonic() + seconds;
    loop {
        let events = session.drain_events();
        if let Some(seen) = seen.as_deref_mut() {
            seen.extend(events.iter().cloned());
        }
        if let Some(status) = completed_status(&events, &ctx.probe_thread, turn_id) {
            return Some(status);
        }
        if ctx.world.monotonic() >= deadline {
            return None;
        }
        let poll = ctx.timing.m6_poll;
        ctx.world.sleep(poll);
    }
}

/// `turn.get("id") if isinstance(turn, dict) and isinstance(turn.get("id"), str) else None` of a turn/start answer.
fn started_turn_id(started: &Value) -> Option<String> {
    let turn = get(started, "turn")?;
    as_text(get(turn, "id"))
}

// ------------------------------------------------------------------------------------------------ the probes
fn m1(ctx: &mut Context<'_>) -> Res<Found> {
    let (loaded, queued) = ctx.with_session(|ctx, session| {
        let loaded = session.call("thread/loaded/list", None)?;
        let queued = session.call(
            "thread/queue/list",
            Some(object(vec![("threadId", ctx.thread_value())])),
        )?;
        Ok((loaded, queued))
    })?;
    blocked(
        "open the notLoaded thread in the Desktop and confirm the queued item is delivered, then set the verdict",
        observed(vec![
            ("loaded_listed", Value::Bool(is_dict(&loaded))),
            ("queue_listed", Value::Bool(is_dict(&queued))),
        ]),
    )
}

fn m2(ctx: &mut Context<'_>) -> Res<Found> {
    let (before, after) = ctx.with_session(|ctx, session| {
        let thread = || object(vec![("threadId", ctx.thread_value())]);
        let before = session.call("thread/goal/get", Some(thread()))?;
        session.call(
            "thread/goal/set",
            Some(object(vec![
                ("threadId", ctx.thread_value()),
                ("objective", Value::Null),
                ("status", text("active")),
            ])),
        )?;
        let after = session.call("thread/goal/get", Some(thread()))?;
        Ok((before, after))
    })?;
    blocked(
        "confirm the Desktop continued the goal at its next idle, then set the verdict",
        observed(vec![
            ("goal_read", Value::Bool(is_dict(&before))),
            ("goal_set", Value::Bool(is_dict(&after))),
        ]),
    )
}

fn m2b(ctx: &mut Context<'_>) -> Res<Found> {
    ctx.with_session(|ctx, session| {
        let thread = |ctx: &Context<'_>| object(vec![("threadId", ctx.thread_value())]);
        let before = goal_status(&session.call("thread/goal/get", Some(thread(ctx)))?);
        if before.is_none() {
            return blocked(
                "give the throwaway conversation a goal, pause it, keep the conversation open in the Desktop, then run m2b again",
                observed(vec![("goal_found", Value::Bool(false))]),
            );
        }
        session.call(
            "thread/goal/set",
            Some(object(vec![
                ("threadId", ctx.thread_value()),
                ("status", text("active")),
            ])),
        )?;
        let set_active = goal_status(&session.call("thread/goal/get", Some(thread(ctx)))?);
        let added = session.call(
            "thread/queue/add",
            Some(object(vec![
                ("threadId", ctx.thread_value()),
                ("clientUserMessageId", text(SAMPLE_M2B_CLIENT_ID)),
                (
                    "input",
                    Value::Array(vec![object(vec![
                        ("type", text("text")),
                        ("text", text(M2B_PROMPT)),
                    ])]),
                ),
            ])),
        )?;
        let seconds = ctx.timing.m2b_queue;
        let taken = await_taken(ctx, session, SAMPLE_M2B_CLIENT_ID, seconds)?;
        let after = goal_status(&session.call("thread/goal/get", Some(thread(ctx)))?);
        let active = |found: &Option<String>| Value::Bool(found.as_deref() == Some("active"));
        blocked(
            "watch the conversation: confirm the queued turn ran and the goal stayed active and carried on after it, then set the verdict",
            observed(vec![
                ("goal_found", Value::Bool(true)),
                ("goal_was_active", active(&before)),
                ("goal_set_active", active(&set_active)),
                ("queue_add_accepted", Value::Bool(is_dict(&added))),
                ("queued_turn_taken", Value::Bool(taken)),
                ("goal_active_after", active(&after)),
            ]),
        )
    })
}

fn m3(ctx: &mut Context<'_>) -> Res<Found> {
    let (added, listed) = ctx.with_session(|ctx, session| {
        let added = session.call(
            "thread/queue/add",
            Some(object(vec![
                ("threadId", ctx.thread_value()),
                ("clientUserMessageId", text(SAMPLE_CLIENT_ID)),
                ("input", Value::Array(vec![])),
            ])),
        )?;
        let listed = session.call(
            "thread/queue/list",
            Some(object(vec![("threadId", ctx.thread_value())])),
        )?;
        Ok((added, listed))
    })?;
    let seen = observed(vec![
        ("queue_add_accepted", Value::Bool(is_dict(&added))),
        ("correlatable", Value::Bool(is_dict(&listed))),
    ]);
    if is_dict(&added) && is_dict(&listed) {
        Ok((Verdict::Pass, seen, None))
    } else {
        Ok((
            Verdict::Fail,
            seen,
            Some("the empty queue add was not accepted or not listed".into()),
        ))
    }
}

/// M5, M7, MH, MA, MQ, MT: one call, one boolean, blocked with the person's step.
fn one_call(
    ctx: &mut Context<'_>,
    method: &str,
    params: fn(&Context<'_>) -> Option<Value>,
    field: &str,
    note: &str,
) -> Res<Found> {
    let answer = ctx.with_session(|ctx, session| session.call(method, params(ctx)))?;
    blocked(note, observed(vec![(field, Value::Bool(is_dict(&answer)))]))
}

fn m5(ctx: &mut Context<'_>) -> Res<Found> {
    one_call(
        ctx,
        "thread/queue/list",
        |ctx| Some(object(vec![("threadId", ctx.thread_value())])),
        "queue_listed",
        "with a TUI server and an IDE server each holding a thread, confirm each dispatches a codex queue item, then set the verdict",
    )
}

fn m7(ctx: &mut Context<'_>) -> Res<Found> {
    one_call(
        ctx,
        "thread/queue/add",
        |ctx| {
            Some(object(vec![
                ("threadId", ctx.thread_value()),
                ("clientUserMessageId", text(SAMPLE_CLIENT_ID)),
                (
                    "input",
                    Value::Array(vec![object(vec![
                        ("type", text("text")),
                        ("text", text("/compact")),
                    ])]),
                ),
            ]))
        },
        "queue_add_accepted",
        "confirm the queued '/compact' was delivered as plain text, not run as a command, then set the verdict",
    )
}

fn mh(ctx: &mut Context<'_>) -> Res<Found> {
    one_call(
        ctx,
        "thread/loaded/list",
        |_| None,
        "second_home_reached",
        "point the Desktop at a second CODEX_HOME and confirm it runs there, then set the verdict",
    )
}

fn ma(ctx: &mut Context<'_>) -> Res<Found> {
    one_call(
        ctx,
        "account/read",
        |_| Some(Value::Object(Map::new())),
        "account_read",
        "sign out and back in in the app, then confirm the running app picked it up and set the verdict",
    )
}

fn mq(ctx: &mut Context<'_>) -> Res<Found> {
    one_call(
        ctx,
        "thread/loaded/list",
        |_| None,
        "loaded_listed",
        "send one short message to each of two to four throwaway conversations at once, confirm each receipt is matched and each marker is in its own history once, then set the verdict",
    )
}

fn mt(ctx: &mut Context<'_>) -> Res<Found> {
    one_call(
        ctx,
        "thread/loaded/list",
        |_| None,
        "loaded_listed",
        "queue one short message while a turn runs in a throwaway conversation, confirm it was delivered once after that turn ended, then set the verdict",
    )
}

fn m6(ctx: &mut Context<'_>) -> Res<Found> {
    let (declined, ended, unsubscribed, status) = ctx.with_session(|ctx, session| {
        session.call(
            "thread/resume",
            Some(object(vec![
                ("threadId", ctx.thread_value()),
                ("excludeTurns", Value::Bool(true)),
            ])),
        )?;
        let started = session.call(
            "turn/start",
            Some(object(vec![
                ("threadId", ctx.thread_value()),
                (
                    "input",
                    Value::Array(vec![object(vec![
                        ("type", text("text")),
                        ("text", text(M6_PROMPT)),
                    ])]),
                ),
                ("approvalPolicy", text("untrusted")),
                ("approvalsReviewer", text("user")),
                (
                    "sandboxPolicy",
                    object(vec![
                        ("type", text("readOnly")),
                        ("networkAccess", Value::Bool(false)),
                    ]),
                ),
            ])),
        )?;
        let turn_id = started_turn_id(&started);
        let seconds = ctx.timing.m6_turn;
        let mut status = await_turn(ctx, session, turn_id.as_deref(), seconds, None);
        let ended = status.is_some();
        if let (false, Some(turn)) = (ended, turn_id.as_deref()) {
            match session.call(
                "turn/interrupt",
                Some(object(vec![
                    ("threadId", ctx.thread_value()),
                    ("turnId", text(turn)),
                ])),
            ) {
                Ok(_) => {
                    let seconds = ctx.timing.m6_interrupt;
                    status = await_turn(ctx, session, Some(turn), seconds, None);
                }
                Err(raised) if raised.is_adapter() => {}
                Err(raised) => return Err(raised),
            }
        }
        let unsubscribed = match session.call(
            "thread/unsubscribe",
            Some(object(vec![("threadId", ctx.thread_value())])),
        ) {
            Ok(_) => true,
            Err(raised) if raised.is_adapter() => false,
            Err(raised) => return Err(raised),
        };
        Ok((session.declined_count(), ended, unsubscribed, status))
    })?;
    let mut seen = observed(vec![
        ("approvals_declined", declined),
        ("turn_ended_by_itself", Value::Bool(ended)),
        ("unsubscribed", Value::Bool(unsubscribed)),
    ]);
    if let Some(status) = status {
        seen.insert(key("turn_status"), text(&status));
    }
    blocked(
        "confirm no window or prompt appeared and the headless turn behaved as expected with its approvals declined, then set the verdict",
        seen,
    )
}

fn mw(ctx: &mut Context<'_>) -> Res<Found> {
    let Some(launcher) = ctx.seams.launcher.as_mut() else {
        return blocked(
            "wire the WMI launcher and run this from the source tree",
            observed(vec![("wmi_started", Value::Bool(false))]),
        );
    };
    let facts = launcher()?;
    if !is_dict(&facts) {
        return blocked(
            "the launcher reported nothing",
            observed(vec![("wmi_started", Value::Bool(false))]),
        );
    }
    let flag = |name: &str| car_machine::pyval::truthy(get(&facts, name).unwrap_or(&Value::Null));
    let started = flag("started");
    let job_kills = flag("job_kills_on_close");
    let kill = flag("kill_on_close");
    let survived = flag("survived");
    let seen = observed(vec![
        ("wmi_started", Value::Bool(started)),
        ("in_job", Value::Bool(flag("in_job"))),
        ("job_kills_on_close", Value::Bool(job_kills)),
        ("kill_on_close", Value::Bool(kill)),
        ("survived_codex_close", Value::Bool(survived)),
    ]);
    if started && kill && survived && !job_kills {
        return Ok((Verdict::Pass, seen, None));
    }
    blocked(
        "the WMI-started watcher did not leave Codex's job, sits in a job that would end it, or did not survive; re-measure before offering start-with-Codex",
        seen,
    )
}

/// The measurements whose probe this seat has ported.
pub fn ported() -> Vec<Measurement> {
    use Measurement as M;
    vec![
        M::M1,
        M::M2,
        M::M2b,
        M::M3,
        M::M5,
        M::M6,
        M::M7,
        M::Mh,
        M::Ma,
        M::Mq,
        M::Mt,
        M::Mw,
        M::Mp1,
        M::Mp2,
        M::Mp3,
        M::Mu,
        M::Mn,
        M::Mr,
        M::Mipc,
        M::Maws,
        M::Mcloud,
    ]
}

/// `PROBES[measurement](ctx)`.
fn dispatch(ctx: &mut Context<'_>) -> Res<Found> {
    use Measurement as M;
    match ctx.measurement {
        M::M1 => m1(ctx),
        M::M2 => m2(ctx),
        M::M2b => m2b(ctx),
        M::M3 => m3(ctx),
        M::M5 => m5(ctx),
        M::M6 => m6(ctx),
        M::M7 => m7(ctx),
        M::Mh => mh(ctx),
        M::Ma => ma(ctx),
        M::Mq => mq(ctx),
        M::Mt => mt(ctx),
        M::Mw => mw(ctx),
        M::Mp1 => usage::mp1(ctx),
        M::Mp2 => usage::mp2(ctx),
        M::Mp3 => usage::mp3(ctx),
        M::Mu => usage::mu(ctx),
        M::Mn => usage::mn(ctx),
        M::Mr => usage::mr(ctx),
        M::Mipc => looks::mipc(ctx),
        M::Maws => looks::maws(ctx),
        M::Mcloud => looks::mcloud(ctx),
        other => Err(Raised::Unported(other)),
    }
}

// ------------------------------------------------------------------------------------------------ probe and run
/// `probe(ctx)`: a protocol that could not be reached becomes a blocked verdict; anything else a probe raises leaves.
pub fn probe(ctx: &mut Context<'_>) -> Res<Found> {
    match dispatch(ctx) {
        Ok((verdict, seen, note)) => Ok((verdict, ctx.given(seen), note)),
        Err(Raised::Adapter {
            method: Some(method),
            code,
            ..
        }) => Ok((
            Verdict::Fail,
            ctx.given(observed(vec![
                ("refused_method", text(&method)),
                ("refusal_code", code),
            ])),
            Some("Codex refused a call this measurement needs".into()),
        )),
        Err(raised @ (Raised::Adapter { .. } | Raised::Unavailable(_) | Raised::Refused)) => Ok((
            Verdict::Blocked,
            observed(vec![("thread_given", Value::Bool(ctx.thread_given))]),
            Some(format!("not reached: {}", raised.class())),
        )),
        Err(raised) => Err(raised),
    }
}

/// `_threads_valid(measurement, thread)`.
pub fn threads_valid(measurement: Measurement, thread: &Value) -> bool {
    let Value::Str(found) = thread else {
        return false;
    };
    if measurement != Measurement::Mqp {
        return is_uuid(thread);
    }
    let whole = py_str(&Value::Str(found.clone()));
    let parts: Vec<&str> = whole.split(',').collect();
    let unique: std::collections::BTreeSet<&str> = parts.iter().copied().collect();
    (2..=MQP_MOST).contains(&parts.len())
        && unique.len() == parts.len()
        && parts.iter().all(|part| is_uuid(&text(part)))
}

/// `_versions(backend)`: the product's version and this Windows' build are the caller's (`config.version()`,
/// `sys.getwindowsversion()`), handed in.
pub fn versions(
    backend: Option<&BackendView>,
    product_version: &str,
    windows_build: Option<&str>,
) -> Map {
    let mut codex = "unknown".to_owned();
    if let Some(backend) = backend
        && car_machine::pyval::truthy(&backend.engine_version)
    {
        codex = py_str(&backend.engine_version);
    }
    observed(vec![
        ("product_version", text(product_version)),
        ("codex_version", text(&codex)),
        ("windows_build", text(windows_build.unwrap_or("10.0.0"))),
    ])
}

/// `time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(now))`: `gmtime` floors; on Windows the reference (3.14.10) takes
/// -43200 to 32536850399 and raises OSError outside (OverflowError for an infinity, ValueError for a NaN).
pub fn iso(now: f64) -> Res<String> {
    if now.is_nan() {
        return Err(Raised::Other("ValueError".into()));
    }
    let seconds = now.floor();
    if !(-43_200.0..=32_536_850_399.0).contains(&seconds) {
        return Err(Raised::Other(
            if seconds.is_finite() {
                "OSError"
            } else {
                "OverflowError"
            }
            .into(),
        ));
    }
    let seconds = seconds as i64;
    let days = seconds.div_euclid(86_400);
    let rest = seconds.rem_euclid(86_400);
    // Howard Hinnant's civil_from_days.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    Ok(format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}Z",
        rest / 3600,
        rest % 3600 / 60
    ))
}

/// `run`'s and `complete`'s keyword arguments besides the seams: `versions` (None or empty reads them here: the
/// product's version and this Windows' build are the caller's), the thread, MR's second yes, the directory, the
/// timing constants.
pub struct Request<'a> {
    pub versions: Option<Map>,
    pub product_version: &'a str,
    pub windows_build: Option<&'a str>,
    pub thread: Option<&'a Value>,
    pub may_spend: bool,
    pub directory: Option<&'a Path>,
    pub timing: Timing,
}

/// `run(measurement, ...)`'s answer: `{"measurement", "verdict", "recorded", "observed"}`.
pub fn run(
    measurement: Measurement,
    seams: &mut Seams,
    request: Request<'_>,
    world: &mut dyn World,
) -> Res<Map> {
    let Request {
        versions: versions_given,
        product_version,
        windows_build,
        thread,
        may_spend,
        directory,
        timing,
    } = request;
    let defaults = (product_version, windows_build);
    if let Some(thread) = thread
        && !threads_valid(measurement, thread)
    {
        return Err(Raised::Unavailable(
            "the conversation id is not a Codex thread id",
        ));
    }
    let versions_found = match versions_given {
        Some(given) if !given.is_empty() => given,
        _ => versions(seams.backend.as_ref(), defaults.0, defaults.1),
    };
    let codex = versions_found.get(&key("codex_version"));
    let unknown = match codex {
        None | Some(Value::Null) => true,
        Some(Value::Str(found)) => found.is_empty() || found.as_bytes() == b"unknown",
        _ => false,
    };
    if unknown {
        return Err(Raised::Unavailable(
            "the Codex version this would measure could not be read",
        ));
    }
    let thread_text = thread.map(py_str);
    let probe_threads: Vec<String> = match thread_text.as_deref() {
        Some(found) if !found.is_empty() => found.split(',').map(str::to_owned).collect(),
        _ => vec![SAMPLE_THREAD.to_owned()],
    };
    let mut ctx = Context {
        measurement,
        seams,
        versions: versions_found.clone(),
        thread_given: thread_text
            .as_deref()
            .is_some_and(|found| !found.is_empty()),
        probe_thread: probe_threads[0].clone(),
        probe_threads,
        may_spend,
        world,
        timing,
    };
    let (verdict, seen, note) = probe(&mut ctx)?;
    let field = |name: &str, default: &str| {
        versions_found
            .get(&key(name))
            .cloned()
            .unwrap_or_else(|| text(default))
    };
    let now = ctx.world.time();
    let recorded_at = text(&iso(now)?);
    let (product, codex, windows) = (
        field("product_version", "0.0.0"),
        field("codex_version", "unknown"),
        field("windows_build", "10.0.0"),
    );
    let note = note.map(|found| text(&found));
    let record = evidence::build(
        measurement,
        verdict,
        &Value::Object(seen.clone()),
        &Envelope {
            product_version: &product,
            codex_version: &codex,
            windows_build: &windows,
            recorded_at: &recorded_at,
        },
        note.as_ref(),
    )
    .map_err(Raised::Evidence)?;
    let written = evidence::write(&record, directory).map_err(Raised::Evidence)?;
    Ok(observed(vec![
        ("measurement", text(measurement.as_str())),
        ("verdict", text(verdict.as_str())),
        ("recorded", text(&written.to_string_lossy())),
        ("observed", Value::Object(seen)),
    ]))
}

/// `complete(measurement, verdict, note, *, backend, versions, clock, directory)`: a person's completion of a blocked
/// record. A note that is no `NoteCode` is the reference's ValueError, before anything is read.
pub fn complete(
    measurement: Measurement,
    verdict: Verdict,
    note: &str,
    backend: Option<&BackendView>,
    request: Request<'_>,
    world: &mut dyn World,
) -> Res<Map> {
    let (versions_given, defaults, directory) = (
        request.versions,
        (request.product_version, request.windows_build),
        request.directory,
    );
    let Some(word) = crate::vocabulary::parse::<crate::vocabulary::NoteCode>(note) else {
        return Err(Raised::Other("ValueError".into()));
    };
    let found = match versions_given {
        Some(given) if !given.is_empty() => given,
        _ => versions(backend, defaults.0, defaults.1),
    };
    let codex = found.get(&key("codex_version")).cloned();
    let unknown = match &codex {
        None | Some(Value::Null) => true,
        Some(Value::Str(found)) => found.is_empty() || found.as_bytes() == b"unknown",
        _ => false,
    };
    let Some(codex) = codex.filter(|_| !unknown) else {
        return Err(Raised::Unavailable(
            "the Codex version this would complete could not be read",
        ));
    };
    let now = world.time();
    let recorded_at = iso(now)?;
    let written = evidence::complete(
        measurement,
        verdict,
        word.as_str(),
        &codex,
        &recorded_at,
        directory,
    )
    .map_err(Raised::Evidence)?;
    Ok(observed(vec![
        ("measurement", text(measurement.as_str())),
        ("verdict", text(verdict.as_str())),
        ("note", text(word.as_str())),
        ("recorded", text(&written.to_string_lossy())),
    ]))
}
