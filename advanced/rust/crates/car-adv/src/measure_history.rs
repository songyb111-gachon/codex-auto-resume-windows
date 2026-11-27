//! Seat S7.4b: `measure.py`'s probes that read what a Codex home kept - ME, MS, MK, MO, MX, MXA, MC2 (`_Watch`), M3B,
//! MTOK, MGAVE - and their helpers (`_latest_kinds`, `_item_kind`, `_turn_in_history`, `_turns_after`, `_holder`,
//! `_token_events`, `_tokens_used`, `_code_word`, `_turn_retries`, `_scan_turn`), a child of [`crate::measure`].
//!
//! Every read is of the Codex home the backend names, through the edition's own readers (`Turns`, `Lineage`,
//! `Origins`) and car-codex's connection; nothing is written there. The rollouts are read as bytes, as the reference
//! reads them.

use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};

use car_machine::json::{Map, Value};
use car_machine::pyval::{self, Num};

use super::held::{client_recorded, seconds};
use super::stage4::{follow, unsubscribed, word};
use super::{
    Context, Found, Raised, Res, as_text, await_turn, blocked, get, is_dict, is_str_eq, key,
    object, observed, started_turn_id, text,
};
use crate::codex::lineage::Lineage;
use crate::codex::sessions::Origins;
use crate::codex::turns::{self, Turn};
use crate::vocabulary::{Measurement, ObservedWord, Verdict};

pub const SAMPLE_M3B_CLIENT_ID: &str = "00000000-0000-7000-8000-000000000003";
pub const SOURCES: [&str; 4] = ["cli", "vscode", "exec", "mcp"];
pub const COMPACTION_KINDS: [&str; 2] = ["contextCompaction", "reasoning"];
pub const TOKEN_KEYS: [&str; 5] = [
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
];
pub const TOKEN_SCAN_BYTES: u64 = 16 * 1024 * 1024;
pub const TOKENS_USED: &str = "SELECT tokens_used FROM threads WHERE id=?";
pub const MGAVE_DAYS: i64 = 90;
pub const MGAVE_TURNS: i64 = 2000;
pub const MGAVE_SCAN_BYTES: u64 = 4 * 1024 * 1024;
pub const MGAVE_FAILED: &str = "SELECT thread_id, turn_id, error_json, rollout_end_byte_offset FROM thread_turns WHERE status='failed' AND completed_at >= ? ORDER BY completed_at DESC LIMIT ?";
pub const MGAVE_COLUMNS: [&str; 6] = [
    "thread_id",
    "turn_id",
    "status",
    "error_json",
    "completed_at",
    "rollout_end_byte_offset",
];
const CAPACITY: &str = "serverOverloaded";
const GAVE_UP: &str = "responseTooManyFailedAttempts";

fn thread_text(ctx: &Context<'_>) -> Value {
    text(&ctx.probe_thread)
}

// ------------------------------------------------------------------------------------------------ the helpers
/// `_latest_kinds(ctx)`: (the latest turn's status or None, only compaction and reasoning, a person's message there).
pub(super) fn latest_kinds(ctx: &Context<'_>) -> Res<(Option<String>, bool, bool)> {
    let Some(home) = ctx.home_text() else {
        return Ok((None, false, false));
    };
    let Some(found) = ctx.turns_of(&home).latest(&thread_text(ctx))? else {
        return Ok((None, false, false));
    };
    let kinds: Vec<&str> = found
        .kinds
        .iter()
        .filter(|(_, count)| *count != 0)
        .map(|(kind, _)| kind.as_str())
        .collect();
    Ok((
        Some(found.status.clone()),
        !kinds.is_empty() && kinds.iter().all(|kind| COMPACTION_KINDS.contains(kind)),
        kinds.contains(&"userMessage"),
    ))
}

/// `_turn_in_history(ctx, turn_id)`.
fn turn_in_history(ctx: &Context<'_>, turn_id: Option<&str>) -> bool {
    let (Some(home), Some(turn_id)) = (ctx.home_text(), turn_id) else {
        return false;
    };
    matches!(ctx.turns_of(&home).latest(&thread_text(ctx)), Ok(Some(latest)) if latest.turn_id == turn_id)
}

/// `_turns_after(home, thread, first)`: 0 where none or it cannot be read.
pub(super) fn turns_after(
    ctx: &Context<'_>,
    home: Option<&str>,
    thread: &str,
    first: Option<&Turn>,
) -> i64 {
    let Some(home) = home else {
        return 0;
    };
    let reader = ctx.turns_of(home);
    let Ok(Some(latest)) = reader.latest(&text(thread)) else {
        return 0;
    };
    let Some(first) = first else {
        return 1;
    };
    if latest.turn_id == first.turn_id {
        return 0;
    }
    let ordinal = |value: i128| match i64::try_from(value) {
        Ok(small) => Value::from(small),
        Err(_) => Value::Float(value as f64),
    };
    match reader.between(
        &text(thread),
        &ordinal(first.ordinal),
        &ordinal(latest.ordinal),
    ) {
        Ok(count) => count + 1,
        Err(_) => 0,
    }
}

/// `_item_kind(event)`.
fn item_kind(event: &Value) -> Option<String> {
    let method = get(event, "method")?;
    if !(is_str_eq(Some(method), "item/started") || is_str_eq(Some(method), "item/completed")) {
        return None;
    }
    let item = get(event, "params").and_then(|params| get(params, "item"))?;
    as_text(get(item, "type"))
}

// ------------------------------------------------------------------------------------------------ ME, MS, MK
pub(super) fn me(ctx: &mut Context<'_>) -> Res<Found> {
    let home = ctx.home_text();
    let (true, Some(home)) = (ctx.thread_given, home) else {
        return blocked(
            "name a conversation whose last turn ended with no reply",
            observed(vec![("history_read", Value::Bool(false))]),
        );
    };
    let Ok(found) = ctx.turns_of(&home).latest(&thread_text(ctx)) else {
        return blocked(
            "the turn history could not be read",
            observed(vec![("history_read", Value::Bool(false))]),
        );
    };
    let mut seen = observed(vec![
        ("history_read", Value::Bool(true)),
        ("turn_found", Value::Bool(found.is_some())),
    ]);
    if let Some(found) = found {
        let empty = &crate::engine::emptyreply::EMPTY_KINDS;
        seen.insert(key("completed"), Value::Bool(found.status == "completed"));
        seen.insert(key("final_agent"), Value::Bool(found.final_agent));
        seen.insert(
            key("empty_kinds_only"),
            Value::Bool(
                found
                    .kinds
                    .iter()
                    .all(|(kind, _)| empty.contains(&kind.as_str())),
            ),
        );
    }
    blocked(
        "confirm the turn ended with no reply, then set the verdict",
        seen,
    )
}

pub(super) fn ms(ctx: &mut Context<'_>) -> Res<Found> {
    let home = ctx.home_text();
    let (true, Some(home)) = (ctx.thread_given, home) else {
        return blocked(
            "name a throwaway parent whose subagent failed",
            observed(vec![("edges_read", Value::Bool(false))]),
        );
    };
    let lineage = Lineage { home, os: ctx.os() };
    let Ok(children) = lineage.children(&thread_text(ctx)) else {
        return blocked(
            "the spawn edges could not be read",
            observed(vec![("edges_read", Value::Bool(false))]),
        );
    };
    let kinds: Vec<Option<&'static str>> = children
        .iter()
        .map(crate::engine::subagent::kind_of)
        .collect();
    let first = kinds.iter().flatten().next().copied();
    let mut seen = observed(vec![
        ("edges_read", Value::Bool(true)),
        ("edge_present", Value::Bool(!children.is_empty())),
        ("child_classified", Value::Bool(first.is_some())),
    ]);
    if let Some(kind) = first {
        seen.insert(key("child_kind"), text(kind));
    }
    blocked(
        "confirm the parent was told which subagent stopped, then set the verdict",
        seen,
    )
}

pub(super) fn mk(ctx: &mut Context<'_>) -> Res<Found> {
    let home = ctx.home_text();
    let (true, Some(home)) = (ctx.thread_given, home) else {
        return blocked(
            "name a throwaway conversation with a plan",
            observed(vec![("plan_read", Value::Bool(false))]),
        );
    };
    let Ok(statuses) = ctx.turns_of(&home).plan_statuses(&thread_text(ctx)) else {
        return blocked(
            "the plan's steps could not be read",
            observed(vec![("plan_read", Value::Bool(false))]),
        );
    };
    let mut seen = observed(vec![
        ("plan_read", Value::Bool(true)),
        ("plan_found", Value::Bool(statuses.is_some())),
    ]);
    let mut words: Vec<&str> = turns::STEP_STATUSES.to_vec();
    words.push(turns::UNKNOWN);
    words.sort_unstable();
    words.dedup();
    for name in words {
        let count = statuses
            .iter()
            .flatten()
            .filter(|status| status.as_str() == name)
            .count();
        seen.insert(key(&format!("steps_{name}")), Value::from(count as i64));
    }
    blocked(
        "confirm the counts match the plan Codex shows, then set the verdict",
        seen,
    )
}

// ------------------------------------------------------------------------------------------------ MO
/// `_holder(ctx, home)`: none, app, session or unknown.
fn holder(ctx: &mut Context<'_>, home: &str) -> &'static str {
    let thread = ctx.probe_thread.clone();
    let found = (|| -> Res<Option<&'static str>> {
        let users = ctx.lock_holders(std::path::Path::new(home), &thread)?;
        if users.is_empty() {
            return Ok(Some(ObservedWord::None.as_str()));
        }
        let Some(identity) = ctx
            .seams
            .backend
            .as_ref()
            .and_then(|backend| backend.app_identity.clone())
        else {
            return Err(Raised::Other("AttributeError".into()));
        };
        let app = identity()?;
        if let Some(server) = get(&app, "server").filter(|server| is_dict(server)) {
            let wanted = Value::Array(vec![object(vec![
                ("pid", get(server, "pid").cloned().unwrap_or(Value::Null)),
                (
                    "created",
                    get(server, "created").cloned().unwrap_or(Value::Null),
                ),
            ])]);
            if pyval::eq(&Value::Array(users.clone()), &wanted) {
                return Ok(Some(ObservedWord::App.as_str()));
            }
        }
        if users.len() == 1 && ctx.holder_kind(&users[0])? {
            return Ok(Some(ObservedWord::Session.as_str()));
        }
        Ok(None)
    })();
    match found {
        Ok(Some(word)) => word,
        _ => ObservedWord::Unknown.as_str(),
    }
}

fn originator_word(value: Option<&Value>) -> &'static str {
    match value {
        Some(Value::Str(found)) => match found.as_bytes() {
            b"codex-tui" => ObservedWord::CliOriginator.as_str(),
            b"codex_vscode" => ObservedWord::IdeOriginator.as_str(),
            b"Codex Desktop" => ObservedWord::Desktop.as_str(),
            _ => ObservedWord::Other.as_str(),
        },
        _ => ObservedWord::Other.as_str(),
    }
}

pub(super) fn mo(ctx: &mut Context<'_>) -> Res<Found> {
    let home = ctx.home_text();
    let (true, Some(home)) = (ctx.thread_given, home) else {
        return blocked(
            "run one TUI and open one VS Code conversation, then name one of them",
            observed(vec![("row_read", Value::Bool(false))]),
        );
    };
    let origins = Origins {
        home: home.clone(),
        os: ctx.os(),
    };
    let Ok((row, first)) = origins.origin(&thread_text(ctx)) else {
        return blocked(
            "the conversation's row or its first line could not be read",
            observed(vec![("row_read", Value::Bool(false))]),
        );
    };
    let mut seen = observed(vec![
        ("row_read", Value::Bool(row.is_some())),
        ("first_line_read", Value::Bool(first.is_some())),
    ]);
    if let Some(row) = row {
        let row = Value::Object(row);
        seen.insert(key("source"), word(get(&row, "source"), &SOURCES));
        seen.insert(
            key("thread_source"),
            word(get(&row, "thread_source"), &["user"]),
        );
        seen.insert(
            key("history_mode"),
            word(get(&row, "history_mode"), &["paginated"]),
        );
    }
    if let Some(first) = first {
        let first = Value::Object(first);
        seen.insert(
            key("originator"),
            text(originator_word(get(&first, "originator"))),
        );
        seen.insert(key("meta_source"), word(get(&first, "source"), &SOURCES));
        seen.insert(
            key("cli_version_present"),
            Value::Bool(matches!(get(&first, "cli_version"), Some(Value::Str(_)))),
        );
    }
    seen.insert(key("holder"), text(holder(ctx, &home)));
    blocked(
        "run it for the TUI's conversation and for VS Code's, confirm each is held by a session, then set the verdict",
        seen,
    )
}

// ------------------------------------------------------------------------------------------------ MX, MXA
pub(super) fn mx(ctx: &mut Context<'_>) -> Res<Found> {
    let began = ctx.world.monotonic();
    let mut seen_events: Vec<Value> = Vec::new();
    let (accepted, status, unsubscribed_now) = ctx.with_session(|ctx, session| {
        session.call(
            "thread/resume",
            Some(object(vec![
                ("threadId", thread_text(ctx)),
                ("excludeTurns", Value::Bool(true)),
            ])),
        )?;
        let accepted = session.call(
            "thread/compact/start",
            Some(object(vec![("threadId", thread_text(ctx))])),
        )?;
        let bound = ctx.timing.m6_turn;
        let status = await_turn(ctx, session, None, bound, Some(&mut seen_events));
        let unsubscribed_now = unsubscribed(ctx, session)?;
        Ok((accepted, status, unsubscribed_now))
    })?;
    let span = ctx.world.monotonic() - began;
    let only = latest_kinds(ctx).map(|found| found.1).unwrap_or(false);
    let mut seen = observed(vec![
        ("compact_accepted", Value::Bool(is_dict(&accepted))),
        (
            "compaction_item_seen",
            Value::Bool(
                seen_events
                    .iter()
                    .any(|event| item_kind(event).as_deref() == Some("contextCompaction")),
            ),
        ),
        ("turn_ended", Value::Bool(status.is_some())),
        ("seconds", seconds(span)),
        ("latest_compaction_only", Value::Bool(only)),
        ("unsubscribed", Value::Bool(unsubscribed_now)),
    ]);
    if let Some(status) = status {
        seen.insert(key("turn_status"), text(&status));
    }
    blocked(
        "confirm the conversation shows as compacted in Codex afterwards, then set the verdict",
        seen,
    )
}

pub(super) fn mxa(ctx: &mut Context<'_>) -> Res<Found> {
    if !ctx.thread_given {
        return blocked(
            "run /compact in a throwaway conversation the app holds, then name it",
            observed(vec![("history_read", Value::Bool(false))]),
        );
    }
    let Ok((status, only, user)) = latest_kinds(ctx) else {
        return blocked(
            "the turn history could not be read",
            observed(vec![("history_read", Value::Bool(false))]),
        );
    };
    let mut seen = observed(vec![
        ("history_read", Value::Bool(true)),
        ("compaction_only", Value::Bool(only)),
        ("user_item_present", Value::Bool(user)),
    ]);
    if let Some(status) = status {
        seen.insert(key("turn_status"), text(&status));
    }
    blocked(
        "confirm the latest turn is the /compact you ran, then set the verdict",
        seen,
    )
}

// ------------------------------------------------------------------------------------------------ MC2
const STARTED: [&str; 1] = ["task_started"];
const ENDED: [&str; 2] = ["task_complete", "turn_aborted"];
const APPROVAL: [&str; 3] = [
    "exec_approval_request",
    "apply_patch_approval_request",
    "request_permissions",
];

/// `_Watch`: what MC2 sees of one conversation, look after look.
struct Watch {
    turns: turns::Turns,
    origins: Origins,
    thread: Value,
    first_turn: Option<String>,
    db_start: Option<f64>,
    db_end: Option<f64>,
    rollout_start: Option<f64>,
    rollout_end: Option<f64>,
    reply_ready: bool,
    waited_db: bool,
    waited_rollout: bool,
    looked: bool,
    offset: Option<i64>,
}

impl Watch {
    fn look(&mut self, now: f64) -> Res<()> {
        let found = self.turns.latest(&self.thread)?;
        let (kinds, offset) = self.origins.events_since(&self.thread, self.offset)?;
        self.offset = offset;
        let kind = kinds.last().cloned();
        if !self.looked {
            self.looked = true;
            self.first_turn = found.as_ref().map(|found| found.turn_id.clone());
            return Ok(());
        }
        for seen in kinds.iter().take(kinds.len().saturating_sub(1)) {
            self.event(Some(seen), now);
        }
        let fresh = found
            .as_ref()
            .filter(|found| Some(&found.turn_id) != self.first_turn.as_ref());
        if let Some(found) = fresh {
            if found.status == "inProgress" && self.db_start.is_none() {
                self.db_start = Some(now);
            }
            if ["completed", "failed", "interrupted"].contains(&found.status.as_str())
                && self.db_end.is_none()
            {
                self.db_start = self.db_start.or(Some(now));
                self.db_end = Some(now);
                self.reply_ready = found
                    .kinds
                    .iter()
                    .find(|(kind, _)| kind == "agentMessage")
                    .is_some_and(|(_, count)| *count > 0);
            }
            if found.status == "other" {
                self.waited_db = true;
            }
        }
        self.event(kind.as_ref(), now);
        Ok(())
    }

    fn event(&mut self, kind: Option<&String>, now: f64) {
        let Some(kind) = kind.map(String::as_str) else {
            return;
        };
        if STARTED.contains(&kind) && self.rollout_start.is_none() {
            self.rollout_start = Some(now);
        }
        if ENDED.contains(&kind) && self.rollout_start.is_some() && self.rollout_end.is_none() {
            self.rollout_end = Some(now);
        }
        if APPROVAL.contains(&kind) {
            self.waited_rollout = true;
        }
    }

    fn settled(&self) -> bool {
        self.db_end.is_some() && self.rollout_end.is_some()
    }

    fn first(db: Option<f64>, rollout: Option<f64>) -> &'static str {
        match (db, rollout) {
            (None, None) => ObservedWord::Neither.as_str(),
            (Some(_), None) => ObservedWord::Db.as_str(),
            (Some(db), Some(rollout)) if db < rollout => ObservedWord::Db.as_str(),
            (None, Some(_)) => ObservedWord::Rollout.as_str(),
            (Some(db), Some(rollout)) if rollout < db => ObservedWord::Rollout.as_str(),
            _ => ObservedWord::Same.as_str(),
        }
    }

    fn observed(&self) -> Vec<(&'static str, Value)> {
        let mut found = vec![
            (
                "started_first",
                text(Self::first(self.db_start, self.rollout_start)),
            ),
            (
                "finished_first",
                text(Self::first(self.db_end, self.rollout_end)),
            ),
            ("reply_item_ready_at_final", Value::Bool(self.reply_ready)),
            ("approval_wait_seen_db", Value::Bool(self.waited_db)),
            (
                "approval_wait_seen_rollout",
                Value::Bool(self.waited_rollout),
            ),
        ];
        if let (Some(db), Some(rollout)) = (self.db_end, self.rollout_end) {
            let lag = (db - rollout).abs();
            found.push((
                "finished_lag",
                text(
                    if lag < 1.0 {
                        ObservedWord::Under1s
                    } else if lag <= 5.0 {
                        ObservedWord::S1To5
                    } else {
                        ObservedWord::Over5s
                    }
                    .as_str(),
                ),
            ));
        }
        found
    }
}

pub(super) fn mc2(ctx: &mut Context<'_>) -> Res<Found> {
    let home = ctx.home_text();
    let (true, Some(home)) = (ctx.thread_given, home) else {
        return blocked(
            "name a throwaway conversation, then send a prompt in it",
            observed(vec![("history_read", Value::Bool(false))]),
        );
    };
    let mut watch = Watch {
        turns: ctx.turns_of(&home),
        origins: Origins { home, os: ctx.os() },
        thread: thread_text(ctx),
        first_turn: None,
        db_start: None,
        db_end: None,
        rollout_start: None,
        rollout_end: None,
        reply_ready: false,
        waited_db: false,
        waited_rollout: false,
        looked: false,
        offset: None,
    };
    let deadline = ctx.world.monotonic() + ctx.timing.mc2;
    loop {
        let now = ctx.world.monotonic();
        if watch.look(now).is_err() {
            return blocked(
                "the history or the rollout could not be read",
                observed(vec![("history_read", Value::Bool(false))]),
            );
        }
        if watch.settled() || ctx.world.monotonic() >= deadline {
            break;
        }
        let poll = ctx.timing.mc2_poll;
        ctx.world.sleep(poll);
    }
    let mut pairs = vec![("history_read", Value::Bool(true))];
    pairs.extend(watch.observed());
    blocked(
        "confirm the two prompts were sent while this ran, then set the verdict",
        observed(pairs),
    )
}

// ------------------------------------------------------------------------------------------------ M3B
pub(super) fn m3b(ctx: &mut Context<'_>) -> Res<Found> {
    let (started, status, ended, unsubscribed_now) = ctx.with_session(|ctx, session| {
        session.call(
            "thread/resume",
            Some(object(vec![
                ("threadId", thread_text(ctx)),
                ("excludeTurns", Value::Bool(true)),
            ])),
        )?;
        let started = session.call(
            "turn/start",
            Some(object(vec![
                ("threadId", thread_text(ctx)),
                ("input", Value::Array(vec![])),
                ("clientUserMessageId", text(SAMPLE_M3B_CLIENT_ID)),
            ])),
        )?;
        let turn = started_turn_id(&started);
        let bound = ctx.timing.m6_turn;
        let (status, ended) = follow(ctx, session, turn.as_deref(), bound)?;
        let unsubscribed_now = unsubscribed(ctx, session)?;
        Ok((started, status, ended, unsubscribed_now))
    })?;
    let turn = started_turn_id(&started);
    let recorded = client_recorded(ctx, SAMPLE_M3B_CLIENT_ID);
    let in_history = turn_in_history(ctx, turn.as_deref());
    let mut seen = observed(vec![
        ("turn_started", Value::Bool(turn.is_some())),
        ("turn_ended_by_itself", Value::Bool(ended)),
        ("client_id_recorded", Value::Bool(recorded)),
        ("unsubscribed", Value::Bool(unsubscribed_now)),
        ("turn_in_history", Value::Bool(in_history)),
    ]);
    if let Some(status) = status {
        seen.insert(key("turn_status"), text(&status));
    }
    let passed = turn.is_some() && in_history;
    Ok((
        if passed { Verdict::Pass } else { Verdict::Fail },
        seen,
        (!passed).then(|| {
            "no turn started, or none in the history by the id it was started under".to_owned()
        }),
    ))
}

// ------------------------------------------------------------------------------------------------ MTOK
/// `json.loads(line.decode("utf-8"))`: None where the reference's `except (ValueError, UnicodeError)` passes it over;
/// the recursion limit is the reference's RecursionError, which it does not catch there.
fn line_json(line: &[u8]) -> Res<Option<Value>> {
    let Ok(decoded) = std::str::from_utf8(line) else {
        return Ok(None);
    };
    match car_machine::compat::loads(decoded) {
        Ok(found) => Ok(Some(found)),
        Err(car_machine::compat::LoadsError::Recursion) => {
            Err(Raised::Other("RecursionError".into()))
        }
        Err(_) => Ok(None),
    }
}

fn contains(line: &[u8], needle: &[u8]) -> bool {
    line.windows(needle.len()).any(|window| window == needle)
}

fn is_int(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Int(_)))
}

/// What `_token_events` reads: (counts with totals, every one keyed, never decreased, the last total).
type TokenRead = (i64, bool, bool, Option<Value>);

/// `_token_events(path)`: (counts with totals, every one keyed, the totals never decreased, the last total).
fn token_events(path: &str) -> Res<TokenRead> {
    let opened = car_machine::pyfile::open(path).map_err(|_| Raised::Other("OSError".into()))?;
    let mut data = Vec::new();
    opened
        .take(TOKEN_SCAN_BYTES)
        .read_to_end(&mut data)
        .map_err(|_| Raised::Other("OSError".into()))?;
    let (mut count, mut keyed, mut monotone, mut last): (i64, bool, bool, Option<Value>) =
        (0, true, true, None);
    for line in data.split(|byte| *byte == b'\n') {
        if !contains(line, b"\"token_count\"") {
            continue;
        }
        let Some(event) = line_json(line)? else {
            continue;
        };
        let payload = get(&event, "payload");
        let info = match payload {
            Some(payload) if is_dict(payload) && is_str_eq(get(payload, "type"), "token_count") => {
                get(payload, "info")
            }
            _ => None,
        };
        let Some(totals) = info
            .and_then(|info| get(info, "total_token_usage"))
            .filter(|totals| is_dict(totals))
        else {
            continue;
        };
        count += 1;
        keyed = keyed && TOKEN_KEYS.iter().all(|name| is_int(get(totals, name)));
        if let Some(total) = get(totals, "total_tokens").filter(|total| is_int(Some(total))) {
            let grew = match &last {
                None => true,
                Some(last) => matches!(
                    (Num::of(total), Num::of(last)),
                    (Some(a), Some(b)) if matches!(pyval::compare(a, b), Some(std::cmp::Ordering::Greater | std::cmp::Ordering::Equal))
                ),
            };
            monotone = monotone && grew;
            last = Some(total.clone());
        }
    }
    Ok((count, keyed && count > 0, monotone, last))
}

/// `_tokens_used(home, thread)`: (the column is there to read, the conversation's value or None).
fn tokens_used(ctx: &Context<'_>, home: &str) -> Res<(bool, Option<Value>)> {
    let os = ctx.os();
    let connection = match turns::connect(
        os.as_ref(),
        home,
        "state",
        &[("threads", &["id", "tokens_used"])],
    ) {
        Ok(connection) => connection,
        Err(turns::Failure::Unavailable(_)) => return Ok((false, None)),
        Err(turns::Failure::Raised(class)) => return Err(Raised::Other(class.into())),
    };
    let row = car_codex::sql::first(
        &connection,
        TOKENS_USED,
        &[car_codex::sql::Param::Text(&ctx.probe_thread)],
    )
    .ok()
    .flatten();
    Ok((
        true,
        row.and_then(|row| match row.at(0) {
            car_codex::sql::Cell::Int(value) => Some(Value::from(*value)),
            _ => None,
        }),
    ))
}

pub(super) fn mtok(ctx: &mut Context<'_>) -> Res<Found> {
    let home = ctx.home_text();
    let (true, Some(home)) = (ctx.thread_given, home) else {
        return blocked(
            "name a throwaway conversation with at least two finished turns",
            observed(vec![("rollout_read", Value::Bool(false))]),
        );
    };
    let origins = Origins {
        home: home.clone(),
        os: ctx.os(),
    };
    let read = (|| -> Res<(Option<String>, TokenRead)> {
        let path = origins.rollout(&thread_text(ctx))?;
        let found = match &path {
            Some(path) => token_events(path)?,
            None => (0, false, true, None),
        };
        Ok((path, found))
    })();
    let (path, (count, keyed, monotone, last)) = read.unwrap_or((None, (0, false, true, None)));
    let (column, used) = tokens_used(ctx, &home)?;
    let documents = super::scratch::with_scratch(ctx, "car-mtok-", |ctx, scratch| {
        super::scratch::generated_schema(ctx, scratch)
    })?;
    let mut methods: Vec<String> = Vec::new();
    for (_, document) in &documents {
        super::scratch::strings(document, &mut |found: &str| {
            if found.starts_with("thread/") {
                methods.push(found.to_owned());
            }
        });
    }
    let matches_last = column
        && used.is_some()
        && match (&used, &last) {
            (Some(used), Some(last)) => pyval::eq(used, last),
            _ => false,
        };
    let seen = observed(vec![
        ("rollout_read", Value::Bool(path.is_some())),
        ("token_events", Value::from(count)),
        ("keys_present", Value::Bool(keyed)),
        ("totals_monotone", Value::Bool(monotone)),
        ("tokens_used_column", Value::Bool(column)),
        ("tokens_used_matches", Value::Bool(matches_last)),
        ("schema_read", Value::Bool(!documents.is_empty())),
        (
            "thread_token_read_listed",
            Value::Bool(
                methods
                    .iter()
                    .any(|method| method.to_lowercase().contains("token")),
            ),
        ),
    ]);
    if path.is_none() || count < 2 {
        return blocked(
            "the conversation's rollout holds fewer than two token counts: finish two turns in it, then run mtok again",
            seen,
        );
    }
    if keyed && monotone {
        return Ok((Verdict::Pass, seen, None));
    }
    Ok((
        Verdict::Fail,
        seen,
        Some("the token counts lack a kind or their totals decreased".into()),
    ))
}

// ------------------------------------------------------------------------------------------------ MGAVE
/// `str.isalnum()` of a whole text (at least one character).
fn is_alnum_text(word: &str) -> bool {
    !word.is_empty()
        && word.chars().all(|c| {
            let mut buffer = [0u8; 4];
            turns::is_alpha(c.encode_utf8(&mut buffer)) || c.is_numeric()
        })
}

/// `_code_word(info)`: a CodexErrorInfo's variant in camelCase, or None.
pub(super) fn code_word(info: Option<&Value>) -> Option<String> {
    let mut info = info?.clone();
    if let Value::Object(map) = &info
        && map.len() == 1
    {
        let name = map.keys().next().cloned()?;
        info = Value::Str(name);
    }
    let Value::Str(found) = &info else {
        return None;
    };
    let word = car_machine::pytext::py_str(&Value::Str(found.clone()));
    if word.is_empty() || word.chars().count() > 64 || !is_alnum_text(&word.replace('_', "")) {
        return None;
    }
    let mut parts = word.split('_');
    let mut made = parts.next().unwrap_or_default().to_owned();
    for part in parts {
        let mut chars = part.chars();
        if let Some(head) = chars.next() {
            made.extend(head.to_uppercase());
            made.push_str(chars.as_str());
        }
    }
    Some(made)
}

type Retries = Option<(i64, Option<String>)>;

/// `_scan_turn(stream, start, stop, turn_id)`.
fn scan_turn(
    stream: &mut BufReader<std::fs::File>,
    start: u64,
    stop: u64,
    turn_id: &Value,
) -> Res<Retries> {
    let os = |_| Raised::Other("OSError".into());
    stream.seek(SeekFrom::Start(start)).map_err(os)?;
    let mut at = start;
    let mut line = Vec::new();
    if start != 0 {
        line.clear();
        at += stream.read_until(b'\n', &mut line).map_err(os)? as u64;
    }
    let mut retries: Option<Vec<Option<String>>> = None;
    while at < stop {
        line.clear();
        let read = stream.read_until(b'\n', &mut line).map_err(os)? as u64;
        if read == 0 {
            break;
        }
        at += read;
        let over = at.saturating_sub(stop);
        if over > 0 {
            line.truncate(line.len().saturating_sub(over as usize));
        }
        if !(contains(&line, b"\"task_started\"")
            || contains(&line, b"\"stream_error\"")
            || contains(&line, b"\"task_complete\"")
            || contains(&line, b"\"turn_aborted\""))
        {
            continue;
        }
        let Some(event) = line_json(&line)? else {
            continue;
        };
        let Some(payload) = get(&event, "payload").filter(|payload| is_dict(payload)) else {
            continue;
        };
        if !is_str_eq(get(&event, "type"), "event_msg") {
            continue;
        }
        let kind = get(payload, "type");
        let own = get(payload, "turn_id").is_some_and(|found| pyval::eq(found, turn_id));
        let own = own || (get(payload, "turn_id").is_none() && matches!(turn_id, Value::Null));
        if is_str_eq(kind, "task_started") && own {
            retries = Some(vec![]);
        } else if retries.is_none() {
            continue;
        } else if is_str_eq(kind, "stream_error") {
            let info = match payload {
                Value::Object(map) => match map.get(&key("codex_error_info")) {
                    Some(found) => Some(found),
                    None => get(payload, "codexErrorInfo"),
                },
                _ => None,
            };
            if let Some(retries) = retries.as_mut() {
                retries.push(code_word(info));
            }
        } else if is_str_eq(kind, "task_started")
            || ((is_str_eq(kind, "task_complete") || is_str_eq(kind, "turn_aborted")) && own)
        {
            break;
        }
    }
    Ok(retries.map(|found| (found.len() as i64, found.last().cloned().flatten())))
}

/// `_turn_retries(path, turn_id, end)`.
fn turn_retries(path: &str, turn_id: &Value, end: &Value) -> Res<Retries> {
    let file = car_machine::pyfile::open(path).map_err(|_| Raised::Other("OSError".into()))?;
    let mut stream = BufReader::new(file);
    let size = stream
        .seek(SeekFrom::End(0))
        .map_err(|_| Raised::Other("OSError".into()))?;
    let stop = match end {
        Value::Int(found) => match found.as_i64() {
            Some(end) if end > 0 && (end as u64) <= size => end as u64,
            _ => size,
        },
        _ => size,
    };
    let start = stop.saturating_sub(MGAVE_SCAN_BYTES);
    let mut found = scan_turn(&mut stream, start, stop, turn_id)?;
    if found.is_none() && start != 0 {
        found = scan_turn(&mut stream, 0, stop, turn_id)?;
    }
    Ok(found)
}

const GAVE_FIELDS: [&str; 15] = [
    "overloaded_turns",
    "gave_up_turns",
    "overloaded_after_capacity_retries",
    "overloaded_without_retries",
    "gave_up_after_capacity_retries",
    "gave_up_after_other_retries",
    "gave_up_without_retries",
    "retries_seen",
    "rollouts_read",
    "rollouts_archived",
    "rollouts_found_by_name",
    "rollouts_missing",
    "rollouts_unread",
    "offsets_missing",
    "turn_starts_unseen",
];

/// `except (TurnsUnavailable, OSError, ValueError)`.
fn caught_find(raised: &Raised) -> bool {
    matches!(raised, Raised::Other(class) if matches!(class.as_str(), "TurnsUnavailable" | "OSError" | "ValueError" | "UnicodeDecodeError" | "FileNotFoundError" | "PermissionError"))
}

pub(super) fn mgave(ctx: &mut Context<'_>) -> Res<Found> {
    let Some(home) = ctx.home_text() else {
        return blocked(
            "no Codex home to read",
            observed(vec![("history_read", Value::Bool(false))]),
        );
    };
    let unread = || {
        blocked(
            "the Codex home's history could not be read",
            observed(vec![("history_read", Value::Bool(false))]),
        )
    };
    let os = ctx.os();
    let connection = match turns::connect(
        os.as_ref(),
        &home,
        "history",
        &[("thread_turns", &MGAVE_COLUMNS)],
    ) {
        Ok(connection) => connection,
        Err(turns::Failure::Unavailable(_)) => return unread(),
        Err(turns::Failure::Raised(class)) => return Err(Raised::Other(class.into())),
    };
    let now = ctx.world.time();
    if now.is_nan() {
        return Err(Raised::Other("ValueError".into()));
    }
    if now.is_infinite() {
        return Err(Raised::Other("OverflowError".into()));
    }
    let since = (now.trunc() as i64).saturating_sub(MGAVE_DAYS * 86_400);
    let rows = car_codex::sql::query(
        &connection,
        MGAVE_FAILED,
        &[
            car_codex::sql::Param::Int(since),
            car_codex::sql::Param::Int(MGAVE_TURNS),
        ],
    );
    drop(connection);
    let Ok(rows) = rows else {
        return unread();
    };
    let origins = Origins { home, os };
    let mut names: Option<Vec<(String, String)>> = None;
    let mut found: Vec<(&'static str, i64)> = GAVE_FIELDS.iter().map(|name| (*name, 0)).collect();
    let mut bump = |name: &str, by: i64| {
        if let Some(slot) = found.iter_mut().find(|(each, _)| *each == name) {
            slot.1 += by;
        }
    };
    for row in &rows {
        let (thread, turn, raw, end) = (
            row.at(0).value(),
            row.at(1).value(),
            row.at(2).clone(),
            row.at(3).value(),
        );
        let error = match &raw {
            car_codex::sql::Cell::Text(raw) => match car_machine::compat::loads(raw) {
                Ok(found) => Some(found),
                Err(car_machine::compat::LoadsError::Recursion) => {
                    return Err(Raised::Other("RecursionError".into()));
                }
                Err(_) => None,
            },
            _ => None,
        };
        let code = code_word(
            error
                .as_ref()
                .and_then(|error| get(error, "codexErrorInfo")),
        );
        let kind = match code.as_deref() {
            Some(CAPACITY) => "overloaded",
            Some(GAVE_UP) => "gave_up",
            _ => continue,
        };
        bump(&format!("{kind}_turns"), 1);
        let located = (|| -> Res<(Option<String>, &'static str)> {
            if names.is_none() {
                names = Some(origins.names()?);
            }
            Ok(origins.find(&thread, names.as_deref())?)
        })();
        let (path, how) = match located {
            Ok(found) => found,
            Err(raised) if caught_find(&raised) => (None, "unread"),
            Err(raised) => return Err(raised),
        };
        let Some(path) = path else {
            bump(
                if how == "missing" {
                    "rollouts_missing"
                } else {
                    "rollouts_unread"
                },
                1,
            );
            continue;
        };
        let offset_ok =
            matches!(&end, Value::Int(found) if found.as_i64().is_none_or(|end| end > 0));
        if !offset_ok {
            bump("offsets_missing", 1);
        }
        let read = match turn_retries(&path, &turn, &end) {
            Ok(read) => read,
            Err(Raised::Other(class)) if class == "OSError" || class == "ValueError" => {
                bump("rollouts_unread", 1);
                continue;
            }
            Err(raised) => return Err(raised),
        };
        bump("rollouts_read", 1);
        if how == "archived" {
            bump("rollouts_archived", 1);
        } else if how == "name" {
            bump("rollouts_found_by_name", 1);
        }
        let Some((retries, last)) = read else {
            bump("turn_starts_unseen", 1);
            continue;
        };
        bump("retries_seen", retries);
        if retries == 0 {
            bump(&format!("{kind}_without_retries"), 1);
        } else if last.as_deref() == Some(CAPACITY) {
            bump(&format!("{kind}_after_capacity_retries"), 1);
        } else if kind == "gave_up" {
            bump("gave_up_after_other_retries", 1);
        }
    }
    let count = |name: &str| {
        found
            .iter()
            .find(|(each, _)| *each == name)
            .map_or(0, |(_, value)| *value)
    };
    let (gave_up_capacity, overloaded_capacity, read, unseen, retries) = (
        count("gave_up_after_capacity_retries"),
        count("overloaded_after_capacity_retries"),
        count("rollouts_read"),
        count("turn_starts_unseen"),
        count("retries_seen"),
    );
    let mut seen: Map = found
        .iter()
        .map(|(name, value)| (key(name), Value::from(*value)))
        .collect();
    seen.insert(key("history_read"), Value::Bool(true));
    seen.insert(key("failed_turns"), Value::from(rows.len() as i64));
    seen.insert(key("days_read"), Value::from(MGAVE_DAYS));
    if gave_up_capacity != 0 {
        return Ok((
            Verdict::Fail,
            seen,
            Some("a turn Codex last retried for capacity recorded responseTooManyFailedAttempts: model_fallback would also have to answer codex_gave_up's kind there".into()),
        ));
    }
    if overloaded_capacity != 0 {
        return Ok((Verdict::Pass, seen, None));
    }
    if read > unseen && retries == 0 {
        return blocked(
            "no rollout read kept a retry before its failed turn: this Codex may not write its retries into rollouts, so MGAVE cannot answer from a Codex home",
            seen,
        );
    }
    blocked(
        "no failed turn whose last retry was for capacity was found in the last ninety days: run mgave again after one",
        seen,
    )
}

/// The measurements this module answers.
pub(super) const PORTED: [Measurement; 10] = [
    Measurement::Me,
    Measurement::Ms,
    Measurement::Mk,
    Measurement::Mo,
    Measurement::Mx,
    Measurement::Mxa,
    Measurement::Mc2,
    Measurement::M3b,
    Measurement::Mtok,
    Measurement::Mgave,
];
