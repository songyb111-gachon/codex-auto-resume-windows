//! Seat S7.4b: `measure.py`'s probes that look at who holds a conversation and follow a queue or a turn - M4, MQO,
//! MQP (its adds on threads of their own), MQG, MC1, MOPEN, MSTEER, MSTEER2 - and their helpers (`_lock_users`,
//! `_look`, `_holds`, `_held`, `_queued_ids`, `_recorded_in`, `_client_recorded`, `_fresh_client_ids`, `_seconds`,
//! `_loaded_bucket`, `_plugin_stop_hooks`, `_stop_runs`, `_letters`), a child of [`crate::measure`].
//!
//! The Codex home is read only through the history readers core and the edition already have (car-codex's
//! `LocalSource.marker_rows`, car-adv's `Turns`); who holds a lock is the run's `resource_users` seam (car-platform's
//! Restart Manager where none is given); nothing here starts or signals a process.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use car_machine::json::{Map, Value};
use car_machine::pyval::{self, Num};

use super::history::{latest_kinds, turns_after};
use super::stage4::app_running;
use super::{
    Context, Found, M2B_PROMPT, MeasureSession, Raised, Res, as_text, await_taken_on, await_turn,
    blocked, get, goal_status, is_dict, is_str_eq, key, object, observed, text,
};
use crate::codex::turns::{SharedOs, Turn, Turns};
use crate::vocabulary::{Measurement, ObservedWord, Verdict};

pub const SAMPLE_MC1_CLIENT_ID: &str = "00000000-0000-7000-8000-000000000004";
pub const SAMPLE_MQO_CLIENT_ID: &str = "00000000-0000-7000-8000-000000000005";
pub const SAMPLE_MQG_CLIENT_ID: &str = "00000000-0000-7000-8000-00000000000a";
pub const SAMPLE_MSTEER_CLIENT_ID: &str = "00000000-0000-7000-8000-00000000000d";
pub const SAMPLE_MSTEER2_CLIENT_ID: &str = "00000000-0000-7000-8000-00000000000e";
pub const M4_MODEL: &str = "car-m4-no-such-model";
pub const M4_PROMPT: &str = "Reply with the single word: ok.";
pub const M4_RUNS: [&str; 2] = ["trusted", "managed"];
pub const MSTEER_TEXT: &str = "Also end your reply with the single word: ok.";
pub const HOOK_INPUT_KEYS: [&str; 5] = [
    "session_id",
    "turn_id",
    "hook_event_name",
    "transcript_path",
    "stop_hook_active",
];
const IPC_STEERED: &str = "steered";
const IPC_UNCERTAIN: [&str; 2] = ["unconfirmed", "broken"];
const IPC_REFUSED: [&str; 2] = ["refused", "version_mismatch"];

// ------------------------------------------------------------------------------------------------ the home
impl Context<'_> {
    /// What reads Codex's files: the run's, else car-codex's `PolicyOs`.
    pub(super) fn os(&self) -> SharedOs {
        match &self.seams.os {
            Some(os) => Arc::clone(os),
            None => Arc::new(car_codex::system::PolicyOs),
        }
    }

    /// `getattr(ctx.backend, "codex_home", None)`.
    pub(super) fn home(&self) -> Option<PathBuf> {
        self.seams.backend.as_ref()?.codex_home.clone()
    }

    pub(super) fn home_text(&self) -> Option<String> {
        self.home().map(|home| home.to_string_lossy().into_owned())
    }

    /// `turns.Turns(home)`.
    pub(super) fn turns_of(&self, home: &str) -> Turns {
        Turns::new(home, self.os())
    }

    /// `windows.resource_users(path)`.
    fn resource_users(&mut self, path: &Path) -> Res<Vec<Value>> {
        if let Some(users) = self.seams.resource_users.as_mut() {
            return users(path);
        }
        use car_codex::system::System;
        car_codex::system::Platform::new()
            .resource_users(&[path.to_string_lossy().into_owned()])
            .map_err(|error| Raised::Other(error.class().into()))
    }

    /// `pairing.session_kind(pairing.inventory(), user, ctx.backend.codex_exe)`.
    pub(super) fn holder_kind(&mut self, user: &Value) -> Res<bool> {
        let exe = self
            .seams
            .backend
            .as_ref()
            .and_then(|backend| backend.codex_exe.clone());
        if let Some(kind) = self.seams.holder_kind.as_mut() {
            return kind(user, exe.as_ref());
        }
        let platform = car_codex::system::Platform::new();
        let rows = car_codex::pairing::inventory(&platform)
            .map_err(|error| Raised::Other(error.class().into()))?;
        let Some(exe) = exe else {
            return Err(Raised::Other("AttributeError".into()));
        };
        let exe = match &exe {
            Value::Str(found) => found.as_str().unwrap_or_default().to_owned(),
            other => car_machine::pytext::py_str(other),
        };
        car_codex::pairing::session_kind(&platform, Some(&rows), user, &exe)
            .map_err(|error| Raised::Other(error.class().into()))
    }

    /// The conversation's writer lock in the Codex home.
    pub(super) fn lock_path(home: &Path, thread: &str) -> PathBuf {
        home.join("thread-writer-locks")
            .join(format!("{thread}.lock"))
    }

    /// `windows.resource_users` of the conversation's lock, as `_holder` asks it.
    pub(super) fn lock_holders(&mut self, home: &Path, thread: &str) -> Res<Vec<Value>> {
        let path = Self::lock_path(home, thread);
        self.resource_users(&path)
    }
}

/// `_lock_users(ctx, thread)`: how many processes hold the conversation's writer lock, None where it could not be read.
pub(super) fn lock_users(ctx: &mut Context<'_>, thread: &str) -> Option<usize> {
    let home = ctx.home()?;
    ctx.lock_holders(&home, thread)
        .ok()
        .map(|users| users.len())
}

/// `_look(ctx, thread)`: (core's loaded check finds the app holding it, the lock's holder count or None).
pub(super) fn look(ctx: &mut Context<'_>, thread: &str) -> (bool, Option<usize>) {
    let app = app_holds(ctx, thread);
    (app, lock_users(ctx, thread))
}

fn app_holds(ctx: &Context<'_>, thread: &str) -> bool {
    let Some(backend) = ctx.seams.backend.as_ref() else {
        return false;
    };
    let Some(identity) = backend.app_identity.as_ref() else {
        return false;
    };
    let Ok(identity) = identity() else {
        return false;
    };
    if !pyval::truthy(&identity) {
        return false;
    }
    let Some(loaded) = backend.loaded.as_ref() else {
        return false;
    };
    matches!(loaded(thread, &identity), Ok(Value::Str(word)) if word.as_bytes() == b"loaded")
}

/// `_holds(look)`.
pub(super) fn holds(look: &(bool, Option<usize>)) -> bool {
    look.0 || look.1.is_some_and(|count| count > 0)
}

/// `_held(ctx, threads)`: (the threads something holds, whether every one could be looked at).
fn held(ctx: &mut Context<'_>, threads: &[String]) -> (Vec<String>, bool) {
    let looks: Vec<(String, (bool, Option<usize>))> = threads
        .iter()
        .map(|thread| (thread.clone(), look(ctx, thread)))
        .collect();
    let read = looks.iter().all(|(_, look)| look.1.is_some() || look.0);
    (
        looks
            .into_iter()
            .filter(|(_, look)| holds(look))
            .map(|(thread, _)| thread)
            .collect(),
        read,
    )
}

/// `_queued_ids(session, thread)`.
fn queued_ids(session: &mut dyn MeasureSession, thread: &str) -> Res<Option<Vec<Value>>> {
    let listed = session.call(
        "thread/queue/list",
        Some(object(vec![("threadId", text(thread))])),
    )?;
    let Some(Value::Array(items)) = get(&listed, "data") else {
        return Ok(None);
    };
    Ok(Some(
        items
            .iter()
            .filter(|item| is_dict(item))
            .map(|item| {
                get(item, "clientUserMessageId")
                    .cloned()
                    .unwrap_or(Value::Null)
            })
            .collect(),
    ))
}

fn holds_id(found: &[Value], wanted: &str) -> bool {
    found.iter().any(|each| is_str_eq(Some(each), wanted))
}

/// `_recorded_in(ctx, thread, client_id)`: core's own read of the history.
pub(super) fn recorded_in(ctx: &Context<'_>, thread: &str, client_id: &str) -> bool {
    let Some(home) = ctx.home_text() else {
        return false;
    };
    let Ok(source) = car_codex::source::LocalSource::new(ctx.os(), &home, None) else {
        return false;
    };
    matches!(source.marker_rows(thread, client_id), Ok(rows) if !rows.is_empty())
}

/// `_client_recorded(ctx, client_id)`.
pub(super) fn client_recorded(ctx: &Context<'_>, client_id: &str) -> bool {
    let thread = ctx.probe_thread.clone();
    recorded_in(ctx, &thread, client_id)
}

/// `_seconds(span)`: a bucket, never the number.
pub(super) fn seconds(span: f64) -> Value {
    text(
        if span < 10.0 {
            ObservedWord::Under10s
        } else if span < 60.0 {
            ObservedWord::Under60s
        } else if span < 600.0 {
            ObservedWord::Under600s
        } else {
            ObservedWord::Over600s
        }
        .as_str(),
    )
}

/// `_loaded_bucket(seconds)`.
fn loaded_bucket(seconds: Option<f64>) -> Value {
    text(
        match seconds {
            None => ObservedWord::Never,
            Some(span) if span < 2.0 => ObservedWord::Under2s,
            Some(span) if span <= 10.0 => ObservedWord::S2To10,
            Some(span) if span <= 20.0 => ObservedWord::S10To20,
            Some(_) => ObservedWord::S20To30,
        }
        .as_str(),
    )
}

/// `str.isalnum()` of one character, as Python's Unicode database says.
fn is_alnum(c: char) -> bool {
    let mut buffer = [0u8; 4];
    crate::codex::turns::is_alpha(c.encode_utf8(&mut buffer)) || c.is_numeric()
}

/// `_letters(word)`: its letters and digits, lower case; "" for anything but a text.
pub(super) fn letters(word: Option<&Value>) -> String {
    match word {
        Some(Value::Str(found)) => car_machine::pytext::py_str(&Value::Str(found.clone()))
            .to_lowercase()
            .chars()
            .filter(|c| is_alnum(*c))
            .collect(),
        _ => String::new(),
    }
}

fn input_text(words: &str) -> Value {
    Value::Array(vec![object(vec![
        ("type", text("text")),
        ("text", text(words)),
    ])])
}

fn queue_add(thread: &str, client_id: &str) -> Value {
    object(vec![
        ("threadId", text(thread)),
        ("clientUserMessageId", text(client_id)),
        ("input", input_text(M2B_PROMPT)),
    ])
}

/// The wait after a take: `_latest_kinds(ctx)[0] in ("inProgress", "completed")` every poll until the bound (MC1,
/// MIMG).
pub(super) fn turn_started_after(ctx: &mut Context<'_>, taken: bool) -> bool {
    let mut started = false;
    let deadline = ctx.world.monotonic() + ctx.timing.mc1_start;
    while taken {
        started = matches!(latest_kinds(ctx), Ok((Some(status), _, _)) if status == "inProgress" || status == "completed");
        if started || ctx.world.monotonic() >= deadline {
            break;
        }
        let poll = ctx.timing.m2b_poll;
        ctx.world.sleep(poll);
    }
    started
}

// ------------------------------------------------------------------------------------------------ MC1
pub(super) fn mc1(ctx: &mut Context<'_>) -> Res<Found> {
    let (added, began, taken) = ctx.with_session(|ctx, session| {
        let thread = ctx.probe_thread.clone();
        let added = session.call(
            "thread/queue/add",
            Some(queue_add(&thread, SAMPLE_MC1_CLIENT_ID)),
        )?;
        let began = ctx.world.monotonic();
        let bound = ctx.timing.mc1_queue;
        let taken = await_taken_on(ctx, session, &thread, SAMPLE_MC1_CLIENT_ID, bound)?;
        Ok((added, began, taken))
    })?;
    let waited = ctx.world.monotonic() - began;
    let started = turn_started_after(ctx, taken);
    let recorded = client_recorded(ctx, SAMPLE_MC1_CLIENT_ID);
    blocked(
        "confirm the message showed at once as your own, nothing marked it as sent by a program, and the turn ran as one you typed, then set the verdict",
        observed(vec![
            ("add_accepted", Value::Bool(is_dict(&added))),
            ("taken", Value::Bool(taken)),
            ("taken_seconds", seconds(waited)),
            ("turn_started", Value::Bool(started)),
            ("client_id_on_user_item", Value::Bool(recorded)),
        ]),
    )
}

// ------------------------------------------------------------------------------------------------ MQO
fn count_or_null(found: Option<usize>) -> Value {
    found.map_or(Value::Null, |count| Value::from(count as i64))
}

pub(super) fn mqo(ctx: &mut Context<'_>) -> Res<Found> {
    let thread = ctx.probe_thread.clone();
    let seen = look(ctx, &thread);
    if seen.1.is_none() && !seen.0 {
        return blocked(
            "who holds the conversation could not be read",
            observed(vec![("holders_read", Value::Bool(false))]),
        );
    }
    if holds(&seen) {
        return blocked(
            "the app holds the throwaway conversation: quit and reopen the Codex app without opening it, then run mqo again",
            observed(vec![
                ("holders_read", Value::Bool(true)),
                ("held_before", Value::Bool(true)),
                ("holders", count_or_null(seen.1)),
            ]),
        );
    }
    let (added, waiting, began, taken) = ctx.with_session(|ctx, session| {
        let added = session.call(
            "thread/queue/add",
            Some(queue_add(&thread, SAMPLE_MQO_CLIENT_ID)),
        )?;
        let listed = session.call(
            "thread/queue/list",
            Some(object(vec![("threadId", text(&thread))])),
        )?;
        let waiting = match get(&listed, "data") {
            Some(Value::Array(items)) => items.iter().any(|item| {
                is_dict(item) && is_str_eq(get(item, "clientUserMessageId"), SAMPLE_MQO_CLIENT_ID)
            }),
            _ => false,
        };
        let began = ctx.world.monotonic();
        let bound = ctx.timing.mqo_open;
        let taken = waiting && await_taken_on(ctx, session, &thread, SAMPLE_MQO_CLIENT_ID, bound)?;
        Ok((added, waiting, began, taken))
    })?;
    let waited = ctx.world.monotonic() - began;
    let mut found = false;
    let deadline = ctx.world.monotonic() + ctx.timing.mqo_find;
    while taken {
        found = client_recorded(ctx, SAMPLE_MQO_CLIENT_ID);
        if found || ctx.world.monotonic() >= deadline {
            break;
        }
        let poll = ctx.timing.m2b_poll;
        ctx.world.sleep(poll);
    }
    blocked(
        "open the throwaway conversation in the Desktop within five minutes of starting this; confirm the message ran there once, as your own, with no marker, then set the verdict",
        observed(vec![
            ("holders_read", Value::Bool(true)),
            ("held_before", Value::Bool(false)),
            ("holders", count_or_null(seen.1)),
            ("add_accepted", Value::Bool(is_dict(&added))),
            ("queued_while_not_held", Value::Bool(waiting)),
            ("taken", Value::Bool(taken)),
            ("taken_seconds", seconds(waited)),
            ("client_id_on_user_item", Value::Bool(found)),
        ]),
    )
}

// ------------------------------------------------------------------------------------------------ MQP
/// One add of MQP's, in a session of its own: `isinstance(answer, dict)`, False for anything raised.
fn add_one(session: Res<Box<dyn MeasureSession + Send>>, thread: &str, client_id: &str) -> bool {
    let Ok(mut session) = session else {
        return false;
    };
    if session.enter().is_err() {
        return false;
    }
    let answer = session.call("thread/queue/add", Some(queue_add(thread, client_id)));
    session.exit();
    matches!(answer, Ok(found) if is_dict(&found))
}

/// MQP's adds: each on a thread of its own, all started, then each waited for at most `mqp_add` seconds in turn
/// (`worker.join(_MQP_ADD_SECONDS)`); one that answers later still counts where it answered before `accepted` is
/// read, as the reference's list is read at the end.
fn add_all(ctx: &mut Context<'_>, threads: &[String], ids: &[String]) -> Arc<Vec<AtomicBool>> {
    let accepted: Arc<Vec<AtomicBool>> =
        Arc::new(threads.iter().map(|_| AtomicBool::new(false)).collect());
    let shared = ctx
        .seams
        .session_factory
        .as_mut()
        .and_then(|factory| factory.shared());
    let Some(open) = shared else {
        // No factory to share: each add in turn, here (none at all: every `ctx.open()` raises, nothing accepted).
        for (index, thread) in threads.iter().enumerate() {
            let answer = match ctx.open() {
                Ok(mut session) => {
                    if session.enter().is_err() {
                        false
                    } else {
                        let answer =
                            session.call("thread/queue/add", Some(queue_add(thread, &ids[index])));
                        session.exit();
                        matches!(answer, Ok(found) if is_dict(&found))
                    }
                }
                Err(_) => false,
            };
            accepted[index].store(answer, Ordering::SeqCst);
        }
        return accepted;
    };
    let measurement = ctx.measurement;
    let mut done = Vec::new();
    for (index, thread) in threads.iter().enumerate() {
        let (tell, heard) = std::sync::mpsc::channel::<()>();
        let open = Arc::clone(&open);
        let accepted = Arc::clone(&accepted);
        let (thread, client_id) = (thread.clone(), ids[index].clone());
        let spawned = std::thread::Builder::new()
            .name("car-measure-mqp".into())
            .spawn(move || {
                let answer = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    add_one(open(measurement), &thread, &client_id)
                }))
                .unwrap_or(false);
                accepted[index].store(answer, Ordering::SeqCst);
                let _ = tell.send(());
            });
        done.push(spawned.ok().map(|_| heard));
    }
    let bound = ctx.timing.mqp_add;
    for heard in done.into_iter().flatten() {
        if bound.is_finite() && bound > 0.0 {
            let _ = heard.recv_timeout(std::time::Duration::from_secs_f64(bound.min(1.0e9)));
        } else if bound.is_infinite() && bound > 0.0 {
            let _ = heard.recv();
        }
    }
    accepted
}

pub(super) fn mqp(ctx: &mut Context<'_>) -> Res<Found> {
    let threads = ctx.probe_threads.clone();
    if threads.len() < 2 {
        return blocked(
            "name two to four throwaway conversations the Desktop does not hold, comma-separated, then run mqp again",
            observed(vec![("conversations", Value::from(threads.len() as i64))]),
        );
    }
    let ids: Vec<String> = threads.iter().map(|_| ctx.world.uuid4()).collect();
    let (held_now, read) = held(ctx, &threads);
    if !read {
        return blocked(
            "who holds the conversations could not be read",
            observed(vec![("holders_read", Value::Bool(false))]),
        );
    }
    if !held_now.is_empty() {
        return blocked(
            "the app holds one of the throwaway conversations: quit and reopen the Codex app without opening them, then run mqp again",
            observed(vec![
                ("holders_read", Value::Bool(true)),
                ("held_before", Value::from(held_now.len() as i64)),
            ]),
        );
    }
    let accepted = add_all(ctx, &threads, &ids);
    let (own_queued, misplaced, taken) = ctx.with_session(|ctx, session| {
        let (mut own_queued, mut misplaced, mut taken) = (0i64, 0i64, 0i64);
        for (index, thread) in threads.iter().enumerate() {
            let found = queued_ids(session, thread)?.unwrap_or_default();
            own_queued += i64::from(holds_id(&found, &ids[index]));
            misplaced += ids
                .iter()
                .filter(|other| **other != ids[index] && holds_id(&found, other))
                .count() as i64;
        }
        let began = ctx.world.monotonic();
        for (index, thread) in threads.iter().enumerate() {
            let left = (ctx.timing.mqo_open - (ctx.world.monotonic() - began)).max(0.0);
            let left = if left.is_nan() { 0.0 } else { left };
            taken += i64::from(await_taken_on(ctx, session, thread, &ids[index], left)?);
        }
        Ok((own_queued, misplaced, taken))
    })?;
    let mut found: Vec<usize> = Vec::new();
    let deadline = ctx.world.monotonic() + ctx.timing.mqo_find;
    while taken != 0 {
        let fresh: Vec<usize> = threads
            .iter()
            .enumerate()
            .filter(|(index, thread)| {
                !found.contains(index) && recorded_in(ctx, thread, &ids[*index])
            })
            .map(|(index, _)| index)
            .collect();
        found.extend(fresh);
        if found.len() == threads.len() || ctx.world.monotonic() >= deadline {
            break;
        }
        let poll = ctx.timing.m2b_poll;
        ctx.world.sleep(poll);
    }
    let found_elsewhere = if taken != 0 {
        let mut count = 0i64;
        for thread in &threads {
            let own = threads.iter().position(|each| each == thread).unwrap_or(0);
            for other in &ids {
                if *other != ids[own] {
                    count += i64::from(recorded_in(ctx, thread, other));
                }
            }
        }
        count
    } else {
        0
    };
    let accepted_count = accepted
        .iter()
        .filter(|each| each.load(Ordering::SeqCst))
        .count() as i64;
    blocked(
        "open each of the throwaway conversations in the Desktop within five minutes of starting this; confirm each message ran once, in its own conversation only, then set the verdict",
        observed(vec![
            ("conversations", Value::from(threads.len() as i64)),
            ("held_before", Value::from(0i64)),
            ("accepted", Value::from(accepted_count)),
            ("queued_in_own", Value::from(own_queued)),
            ("queued_elsewhere", Value::from(misplaced)),
            ("taken", Value::from(taken)),
            ("found_in_own", Value::from(found.len() as i64)),
            ("found_elsewhere", Value::from(found_elsewhere)),
        ]),
    )
}

// ------------------------------------------------------------------------------------------------ MQG
pub(super) fn mqg(ctx: &mut Context<'_>) -> Res<Found> {
    let home = ctx.home_text();
    let thread = ctx.probe_thread.clone();
    let (held_now, read) = held(ctx, std::slice::from_ref(&thread));
    if !read {
        return blocked(
            "who holds the conversation could not be read",
            observed(vec![("holders_read", Value::Bool(false))]),
        );
    }
    if !held_now.is_empty() {
        return blocked(
            "the app holds the throwaway conversation: quit and reopen the Codex app without opening it, then run mqg again",
            observed(vec![
                ("holders_read", Value::Bool(true)),
                ("held_before", Value::Bool(true)),
            ]),
        );
    }
    let goal = |thread: &str| Some(object(vec![("threadId", text(thread))]));
    let answer = ctx.with_session(|ctx, session| {
        let before = goal_status(&session.call("thread/goal/get", goal(&thread))?);
        if before.is_none() {
            return Ok(None);
        }
        session.call(
            "thread/goal/set",
            Some(object(vec![
                ("threadId", text(&thread)),
                ("status", text("active")),
            ])),
        )?;
        let set_active = goal_status(&session.call("thread/goal/get", goal(&thread))?);
        let first: Option<Turn> = match home.as_deref() {
            Some(home) => ctx.turns_of(home).latest(&text(&thread)).ok().flatten(),
            None => None,
        };
        let added = session.call(
            "thread/queue/add",
            Some(queue_add(&thread, SAMPLE_MQG_CLIENT_ID)),
        )?;
        let waiting = holds_id(
            &queued_ids(session, &thread)?.unwrap_or_default(),
            SAMPLE_MQG_CLIENT_ID,
        );
        let bound = ctx.timing.mqo_open;
        let taken = waiting && await_taken_on(ctx, session, &thread, SAMPLE_MQG_CLIENT_ID, bound)?;
        let mut ran = 0i64;
        let deadline = ctx.world.monotonic() + ctx.timing.mqg_settle;
        while taken {
            ran = turns_after(ctx, home.as_deref(), &thread, first.as_ref());
            if ctx.world.monotonic() >= deadline {
                break;
            }
            let poll = ctx.timing.m2b_poll;
            ctx.world.sleep(poll);
        }
        let after = goal_status(&session.call("thread/goal/get", goal(&thread))?);
        Ok(Some((set_active, added, waiting, taken, ran, after)))
    })?;
    let Some((set_active, added, waiting, taken, ran, after)) = answer else {
        return blocked(
            "give the throwaway conversation a goal and pause it, close the conversation, then run mqg again",
            observed(vec![
                ("holders_read", Value::Bool(true)),
                ("held_before", Value::Bool(false)),
                ("goal_found", Value::Bool(false)),
            ]),
        );
    };
    let recorded = taken && client_recorded(ctx, SAMPLE_MQG_CLIENT_ID);
    let active = |found: &Option<String>| Value::Bool(found.as_deref() == Some("active"));
    blocked(
        "open the throwaway conversation in the Desktop within five minutes of starting this and watch it for two more; say whether two turns ran (the goal's and the queued message) or one, then set the verdict",
        observed(vec![
            ("holders_read", Value::Bool(true)),
            ("held_before", Value::Bool(false)),
            ("goal_found", Value::Bool(true)),
            ("goal_set_active", active(&set_active)),
            ("add_accepted", Value::Bool(is_dict(&added))),
            ("queued_while_not_held", Value::Bool(waiting)),
            ("taken", Value::Bool(taken)),
            ("turns_after_open", Value::from(ran)),
            ("client_id_on_user_item", Value::Bool(recorded)),
            ("goal_active_after", active(&after)),
        ]),
    )
}

// ------------------------------------------------------------------------------------------------ MOPEN
pub(super) fn mopen(ctx: &mut Context<'_>) -> Res<Found> {
    if !ctx.thread_given {
        return blocked(
            "name a throwaway conversation the app does not hold",
            observed(vec![("holders_read", Value::Bool(false))]),
        );
    }
    let thread = ctx.probe_thread.clone();
    let running = app_running(ctx);
    let Some(before) = lock_users(ctx, &thread) else {
        return blocked(
            "who holds the conversation could not be read",
            observed(vec![("holders_read", Value::Bool(false))]),
        );
    };
    if before > 0 {
        return blocked(
            "something holds the throwaway conversation: quit and reopen the Codex app without opening it, then run mopen again",
            observed(vec![
                ("holders_read", Value::Bool(true)),
                ("held_before", Value::Bool(true)),
                ("holders", Value::from(before as i64)),
            ]),
        );
    }
    let began = ctx.world.monotonic();
    let opened = matches!(
        ctx.hand("open_link", &[text(&thread)]),
        Some(Value::Bool(true))
    );
    let (mut loaded, mut holders, mut read) = (None, 0usize, false);
    while opened {
        let count = lock_users(ctx, &thread);
        if let Some(count) = count {
            read = true;
            holders = count;
        }
        if count.is_some_and(|count| count > 0) {
            loaded = Some(ctx.world.monotonic() - began);
            break;
        }
        if ctx.world.monotonic() - began >= ctx.timing.mopen {
            break;
        }
        let poll = ctx.timing.mopen_poll;
        ctx.world.sleep(poll);
    }
    let by_app = loaded.is_some() && look(ctx, &thread).0;
    let seen = observed(vec![
        ("holders_read", Value::Bool(read || !opened)),
        ("held_before", Value::Bool(false)),
        ("codex_running", Value::Bool(running)),
        ("link_opened", Value::Bool(opened)),
        ("loaded_by_app", Value::Bool(by_app)),
        ("holders", Value::from(holders as i64)),
        ("loaded_seconds", loaded_bucket(loaded)),
    ]);
    if !opened {
        return blocked(
            "the conversation's link could not be handed to Windows",
            seen,
        );
    }
    if loaded.is_none() {
        return Ok((
            Verdict::Fail,
            seen,
            Some(
                "no process held the conversation within the limit of its link being opened".into(),
            ),
        ));
    }
    if !by_app {
        return blocked(
            "a process took the conversation's lock but core's check does not find it to be the app: look at the Codex app, then set the verdict",
            seen,
        );
    }
    blocked(
        "the app held it within the limit: confirm whether the Codex window came to the front, then set the verdict",
        seen,
    )
}

// ------------------------------------------------------------------------------------------------ M4
/// `_plugin_stop_hooks(listed)`: (Stop hooks from a plugin, how many of them are on and trusted).
fn plugin_stop_hooks(listed: &Value) -> (i64, i64) {
    let (mut found, mut trusted) = (0i64, 0i64);
    let Some(Value::Array(entries)) = get(listed, "data") else {
        return (0, 0);
    };
    for entry in entries {
        let Some(Value::Array(hooks)) = get(entry, "hooks") else {
            continue;
        };
        for hook in hooks {
            if !is_dict(hook)
                || letters(get(hook, "eventName")) != "stop"
                || !is_str_eq(get(hook, "source"), "plugin")
            {
                continue;
            }
            found += 1;
            let enabled = !matches!(get(hook, "enabled"), Some(Value::Bool(false)));
            let runs = get(hook, "trustStatus").is_some_and(|word| pyval::in_tuple(word, &M4_RUNS));
            trusted += i64::from(enabled && runs);
        }
    }
    (found, trusted)
}

/// `_stop_runs(events, thread)`: (started, completed, the last completed one's status word).
fn stop_runs(events: &[Value], thread: &str) -> (i64, i64, Option<Value>) {
    let (mut started, mut completed, mut status) = (0i64, 0i64, None);
    for event in events {
        let method = get(event, "method");
        let hook = matches!(method, Some(Value::Str(word)) if word.as_bytes() == b"hook/started" || word.as_bytes() == b"hook/completed");
        let params = if hook { get(event, "params") } else { None };
        let run = match params {
            Some(params) if is_dict(params) && is_str_eq(get(params, "threadId"), thread) => {
                get(params, "run")
            }
            _ => None,
        };
        let Some(run) = run.filter(|run| is_dict(run)) else {
            continue;
        };
        if letters(get(run, "eventName")) != "stop" || !is_str_eq(get(run, "source"), "plugin") {
            continue;
        }
        if is_str_eq(method, "hook/started") {
            started += 1;
        } else {
            completed += 1;
            status = Some(match get(run, "status") {
                Some(Value::Str(word)) => Value::Str(word.clone()),
                _ => text("other"),
            });
        }
    }
    (started, completed, status)
}

/// `ctx.m4_hook_note()`.
fn m4_hook_note(ctx: &mut Context<'_>) -> Vec<Value> {
    match ctx.hand("m4_hook_note", &[]) {
        Some(Value::Array(found)) => found.into_iter().filter(is_dict).collect(),
        _ => vec![],
    }
}

/// `isinstance(note.get("at"), (int, float)) and note["at"] >= began`.
fn noted_since(note: &Value, began: f64) -> bool {
    let Some(at) = get(note, "at") else {
        return false;
    };
    let Some(at) = Num::of(at) else {
        return false;
    };
    matches!(
        pyval::compare(at, Num::Real(began)),
        Some(std::cmp::Ordering::Greater | std::cmp::Ordering::Equal)
    )
}

/// `{key for key in note.get("keys") or () if isinstance(key, str)}`: a list's texts, a dict's keys, a text's
/// characters; a number that is true is the reference's TypeError.
fn note_keys(note: &Value) -> Res<Vec<String>> {
    let keys = get(note, "keys").cloned().unwrap_or(Value::Null);
    if !pyval::truthy(&keys) {
        return Ok(vec![]);
    }
    Ok(match keys {
        Value::Array(items) => items
            .iter()
            .filter_map(|each| as_text(Some(each)))
            .collect(),
        Value::Object(map) => map
            .keys()
            .map(|name| car_machine::pytext::py_str(&Value::Str(name.clone())))
            .collect(),
        Value::Str(found) => car_machine::pytext::py_str(&Value::Str(found))
            .chars()
            .map(String::from)
            .collect(),
        _ => return Err(Raised::Other("TypeError".into())),
    })
}

pub(super) fn m4(ctx: &mut Context<'_>) -> Res<Found> {
    if !ctx.thread_given {
        return blocked(
            "name a throwaway conversation nothing holds, with a measurement Stop hook declared and trusted, then run m4 again",
            observed(vec![("holders_read", Value::Bool(false))]),
        );
    }
    let thread = ctx.probe_thread.clone();
    let holders = lock_users(ctx, &thread);
    if holders.is_none_or(|count| count > 0) {
        return blocked(
            "something holds the throwaway conversation, or who does could not be read: quit and reopen the Codex app without opening it, then run m4 again",
            observed(vec![
                ("holders_read", Value::Bool(holders.is_some())),
                (
                    "held_before",
                    Value::Bool(holders.is_some_and(|count| count > 0)),
                ),
            ]),
        );
    }
    let began = ctx.world.time();
    let answer = ctx.with_session(|ctx, session| {
        let mut seen: Vec<Value> = Vec::new();
        let mut notes: Vec<Value> = Vec::new();
        let listed = session.call(
            "hooks/list",
            Some(object(vec![("cwds", Value::Array(vec![]))])),
        )?;
        let (found, trusted) = plugin_stop_hooks(&listed);
        let base = observed(vec![
            ("holders_read", Value::Bool(true)),
            ("held_before", Value::Bool(false)),
            ("plugin_stop_hooks", Value::from(found)),
            ("plugin_stop_hooks_trusted", Value::from(trusted)),
        ]);
        if trusted == 0 {
            return Ok(Err(base));
        }
        session.call(
            "thread/resume",
            Some(object(vec![
                ("threadId", text(&thread)),
                ("excludeTurns", Value::Bool(true)),
            ])),
        )?;
        let started = match session.call(
            "turn/start",
            Some(object(vec![
                ("threadId", text(&thread)),
                ("input", input_text(M4_PROMPT)),
                ("model", text(M4_MODEL)),
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
        ) {
            Ok(found) => found,
            Err(raised) if raised.is_adapter() => Value::Null,
            Err(raised) => return Err(raised),
        };
        let turn_id = get(&started, "turn")
            .filter(|turn| is_dict(turn))
            .and_then(|turn| as_text(get(turn, "id")));
        let bound = ctx.timing.m4_turn;
        let mut status = match turn_id.as_deref() {
            Some(turn) if !turn.is_empty() => {
                await_turn(ctx, session, Some(turn), bound, Some(&mut seen))
            }
            _ => None,
        };
        if let (None, Some(turn)) = (&status, turn_id.as_deref()) {
            match session.call(
                "turn/interrupt",
                Some(object(vec![
                    ("threadId", text(&thread)),
                    ("turnId", text(turn)),
                ])),
            ) {
                Ok(_) => {
                    let bound = ctx.timing.m6_interrupt;
                    status = await_turn(ctx, session, Some(turn), bound, Some(&mut seen));
                }
                Err(raised) if raised.is_adapter() => {}
                Err(raised) => return Err(raised),
            }
        }
        let deadline = ctx.world.monotonic() + ctx.timing.m4_note;
        while turn_id.is_some() {
            seen.extend(session.drain_events());
            notes = m4_hook_note(ctx)
                .into_iter()
                .filter(|note| noted_since(note, began))
                .collect();
            if (!notes.is_empty() && stop_runs(&seen, &thread).1 != 0)
                || ctx.world.monotonic() >= deadline
            {
                break;
            }
            let poll = ctx.timing.m6_poll;
            ctx.world.sleep(poll);
        }
        match session.call(
            "thread/unsubscribe",
            Some(object(vec![("threadId", text(&thread))])),
        ) {
            Ok(_) => {}
            Err(raised) if raised.is_adapter() => {}
            Err(raised) => return Err(raised),
        }
        Ok(Ok((base, seen, notes, turn_id, status)))
    })?;
    let (mut seen_map, events, notes, turn_id, status) = match answer {
        Err(base) => {
            return blocked(
                "no plugin Stop hook is listed as on and trusted: declare the measurement hook, trust it in Codex, then run m4 again",
                base,
            );
        }
        Ok(found) => found,
    };
    let (started, completed, run_status) = stop_runs(&events, &thread);
    let note = notes.last().cloned().unwrap_or(Value::Object(Map::new()));
    let keys = note_keys(&note)?;
    let row = get(&note, "status").cloned();
    let row_word = match &row {
        None | Some(Value::Null) => "none",
        Some(found)
            if pyval::in_tuple(found, &["completed", "failed", "inProgress", "interrupted"]) =>
        {
            match found {
                Value::Str(word) => {
                    let word = word.as_str().unwrap_or_default();
                    ["completed", "failed", "inProgress", "interrupted"]
                        .into_iter()
                        .find(|each| *each == word)
                        .unwrap_or("other")
                }
                _ => "other",
            }
        }
        Some(_) => "other",
    };
    let status_value = match &status {
        Some(found) if !found.is_empty() => text(found),
        _ => text("none"),
    };
    let hook_status = match &run_status {
        Some(found) if pyval::truthy(found) => found.clone(),
        _ => text("none"),
    };
    for (name, value) in [
        ("turn_started", Value::Bool(turn_id.is_some())),
        ("turn_status", status_value),
        ("stop_hook_started", Value::from(started)),
        ("stop_hook_completed", Value::from(completed)),
        ("stop_hook_status", hook_status),
        ("hook_noted", Value::Bool(!notes.is_empty())),
        ("history_status_when_hook_ran", text(row_word)),
    ] {
        seen_map.insert(key(name), value);
    }
    for name in HOOK_INPUT_KEYS {
        seen_map.insert(
            key(&format!("input_{name}")),
            Value::Bool(keys.iter().any(|each| each == name)),
        );
    }
    if status.as_deref() != Some("failed") {
        return blocked(
            "the turn did not fail as asked, so nothing is settled: look at the conversation, then run m4 again",
            seen_map,
        );
    }
    if started == 0 && completed == 0 && notes.is_empty() {
        return Ok((
            Verdict::Fail,
            seen_map,
            Some("a plugin Stop hook did not run after the failed turn".into()),
        ));
    }
    if notes.is_empty() {
        return blocked(
            "a plugin Stop hook ran but the measurement hook left no note: look at the hook, then run m4 again",
            seen_map,
        );
    }
    if !matches!(&row, Some(Value::Str(word)) if word.as_bytes() == b"failed") {
        return Ok((
            Verdict::Fail,
            seen_map,
            Some("the failed turn was not yet in Codex's history when the Stop hook ran".into()),
        ));
    }
    Ok((Verdict::Pass, seen_map, None))
}

// ------------------------------------------------------------------------------------------------ MSTEER, MSTEER2
/// The latest turn of the probe's conversation where Codex's history says it runs, else the probe's blocked answer.
fn running_turn(ctx: &mut Context<'_>, again: &str) -> Result<Turn, Found> {
    let home = ctx.home_text();
    let thread = ctx.probe_thread.clone();
    let running = match home.as_deref() {
        Some(home) => match ctx.turns_of(home).latest(&text(&thread)) {
            Ok(found) => found,
            Err(_) => {
                return Err((
                    Verdict::Blocked,
                    observed(vec![
                        ("history_read", Value::Bool(false)),
                        ("steer_calls", Value::from(0i64)),
                    ]),
                    Some("the history could not be read".into()),
                ));
            }
        },
        None => None,
    };
    match running {
        Some(turn) if turn.status == "inProgress" => Ok(turn),
        _ => Err((
            Verdict::Blocked,
            observed(vec![
                ("history_read", Value::Bool(true)),
                ("turn_in_progress", Value::Bool(false)),
                ("steer_calls", Value::from(0i64)),
            ]),
            Some(format!(
                "start a long turn in the throwaway conversation in the Codex app and run {again}while it runs"
            )),
        )),
    }
}

/// After an accepted steer: the history read for the client id until the bound, then whether the latest turn is
/// still the one that ran.
fn after_steer(ctx: &mut Context<'_>, client_id: &str, running: &Turn, seen_map: &mut Map) {
    let deadline = ctx.world.monotonic() + ctx.timing.msteer_look;
    let seen = loop {
        let seen = client_recorded(ctx, client_id);
        if seen || ctx.world.monotonic() >= deadline {
            break seen;
        }
        let poll = ctx.timing.msteer_poll;
        ctx.world.sleep(poll);
    };
    let thread = ctx.probe_thread.clone();
    let latest = match ctx.home_text() {
        Some(home) => ctx.turns_of(&home).latest(&text(&thread)).ok().flatten(),
        None => {
            // `Turns(None).latest(...)`: the reference's reader of no home raises, read as none.
            None
        }
    };
    seen_map.insert(key("client_id_on_user_item"), Value::Bool(seen));
    seen_map.insert(
        key("latest_turn_unchanged"),
        Value::Bool(latest.is_some_and(|latest| latest.turn_id == running.turn_id)),
    );
}

fn holders_value(found: Option<usize>) -> Value {
    count_or_null(found)
}

pub(super) fn msteer(ctx: &mut Context<'_>) -> Res<Found> {
    if !ctx.thread_given {
        return blocked(
            "name a throwaway conversation the app holds with a long turn running",
            observed(vec![("steer_calls", Value::from(0i64))]),
        );
    }
    let running = match running_turn(ctx, "msteer again ") {
        Ok(turn) => turn,
        Err(found) => return Ok(found),
    };
    let thread = ctx.probe_thread.clone();
    let seen = look(ctx, &thread);
    let mut seen_map = observed(vec![
        ("history_read", Value::Bool(true)),
        ("turn_in_progress", Value::Bool(true)),
        ("steer_calls", Value::from(0i64)),
        ("held_by_app", Value::Bool(seen.0)),
        ("holders", holders_value(seen.1)),
    ]);
    let answered = ctx.with_session(|_ctx, session| {
        Ok(session.call(
            "turn/steer",
            Some(object(vec![
                ("threadId", text(&thread)),
                ("expectedTurnId", text(&running.turn_id)),
                ("input", input_text(MSTEER_TEXT)),
                ("clientUserMessageId", text(SAMPLE_MSTEER_CLIENT_ID)),
            ])),
        ))
    });
    // `steer_calls` is set to one inside the session, before the call: a session that did not open leaves it at 0.
    let answered = match answered {
        Ok(found) => found,
        Err(raised) => return Err(raised),
    };
    seen_map.insert(key("steer_calls"), Value::from(1i64));
    let answered = match answered {
        Ok(found) => found,
        Err(Raised::Adapter {
            method: Some(_),
            code,
            ..
        }) => {
            seen_map.insert(key("steer_accepted"), Value::Bool(false));
            seen_map.insert(key("answer_uncertain"), Value::Bool(false));
            seen_map.insert(key("refusal_code"), code);
            return Ok((
                Verdict::Fail,
                seen_map,
                Some(
                    "Codex refused turn/steer for the exact active turn of the conversation".into(),
                ),
            ));
        }
        Err(Raised::Adapter { .. }) => {
            seen_map.insert(key("steer_accepted"), Value::Bool(false));
            seen_map.insert(key("answer_uncertain"), Value::Bool(true));
            return blocked(
                "the answer to turn/steer did not come: look in Codex whether the line showed in the running turn - it was not sent again - and do not run msteer again before you have looked; then set the verdict",
                seen_map,
            );
        }
        Err(raised) => return Err(raised),
    };
    let same = match get(&answered, "turnId") {
        Some(Value::Str(found)) => found.as_bytes() == running.turn_id.as_bytes(),
        _ => false,
    };
    seen_map.insert(key("steer_accepted"), Value::Bool(true));
    seen_map.insert(key("answer_uncertain"), Value::Bool(false));
    seen_map.insert(key("answer_names_same_turn"), Value::Bool(same));
    after_steer(ctx, SAMPLE_MSTEER_CLIENT_ID, &running, &mut seen_map);
    blocked(
        "confirm the line showed in Codex inside the turn that was running, as your own message, with no new turn begun by it and nothing else sent, then set the verdict",
        seen_map,
    )
}

/// `ctx.steer_over_ipc(thread, text, message)`: (the hand was there, its closed word or None).
fn steer_over_ipc(ctx: &mut Context<'_>, thread: &str) -> (bool, Option<String>) {
    let Some(hand) = ctx.seams.hands.get_mut("steer_ipc") else {
        return (false, None);
    };
    match hand(&[
        text(thread),
        text(MSTEER_TEXT),
        text(SAMPLE_MSTEER2_CLIENT_ID),
    ]) {
        Ok(Value::Str(word)) => (true, Some(car_machine::pytext::py_str(&Value::Str(word)))),
        Ok(_) | Err(_) => (true, None),
    }
}

pub(super) fn msteer2(ctx: &mut Context<'_>) -> Res<Found> {
    if !ctx.thread_given {
        return blocked(
            "name a throwaway conversation the app holds with a long turn running",
            observed(vec![("steer_calls", Value::from(0i64))]),
        );
    }
    let running = match running_turn(ctx, "again ") {
        Ok(turn) => turn,
        Err(found) => return Ok(found),
    };
    let thread = ctx.probe_thread.clone();
    let seen = look(ctx, &thread);
    let mut seen_map = observed(vec![
        ("history_read", Value::Bool(true)),
        ("turn_in_progress", Value::Bool(true)),
        ("steer_calls", Value::from(0i64)),
        ("held_by_app", Value::Bool(seen.0)),
        ("holders", holders_value(seen.1)),
    ]);
    let (called, word) = steer_over_ipc(ctx, &thread);
    if !called {
        return blocked(
            "the IPC hand was not wired: run this from the Dashboard's runtime",
            seen_map,
        );
    }
    seen_map.insert(key("steer_calls"), Value::from(1i64));
    let word = word.as_deref();
    let uncertain = word.is_none_or(|word| IPC_UNCERTAIN.contains(&word));
    let refused = word.is_some_and(|word| IPC_REFUSED.contains(&word));
    for (name, value) in [
        ("steer_accepted", word == Some(IPC_STEERED)),
        ("answer_uncertain", uncertain),
        ("pipe_reached", word != Some("no_pipe")),
        (
            "owner_found",
            !matches!(word, Some("no_pipe" | "no_client")),
        ),
        ("app_refused", refused),
        ("version_mismatch", word == Some("version_mismatch")),
    ] {
        seen_map.insert(key(name), Value::Bool(value));
    }
    if refused {
        return Ok((
            Verdict::Fail,
            seen_map,
            Some("the Desktop's IPC pipe refused the steer for the conversation".into()),
        ));
    }
    if uncertain {
        return blocked(
            "the steer may have been written and no answer came: look in Codex whether the line showed in the running turn - it was not sent again - and do not run msteer2 again before you have looked; then set the verdict",
            seen_map,
        );
    }
    if word != Some(IPC_STEERED) {
        return blocked(
            "the Desktop's IPC pipe was not reached or the app does not hold the conversation, and nothing was written: start Codex, open the throwaway conversation with its long turn, then run msteer2 again",
            seen_map,
        );
    }
    after_steer(ctx, SAMPLE_MSTEER2_CLIENT_ID, &running, &mut seen_map);
    blocked(
        "confirm the line showed in Codex inside the turn that was running, as your own message, once, with no new turn begun by it and nothing else sent, then set the verdict",
        seen_map,
    )
}

/// The measurements this module answers.
pub(super) const PORTED: [Measurement; 8] = [
    Measurement::M4,
    Measurement::Mqo,
    Measurement::Mqp,
    Measurement::Mqg,
    Measurement::Mc1,
    Measurement::Mopen,
    Measurement::Msteer,
    Measurement::Msteer2,
];
