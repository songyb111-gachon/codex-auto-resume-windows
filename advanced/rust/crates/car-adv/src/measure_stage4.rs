//! Seat S7.4: `measure.py`'s stage-4 probes (v0.6.16-beta.4) that need nothing of an unported seat - M6B so far -
//! and their helpers (`_word`, `_settings`, `_follow`, `_unsubscribed`, `_app_running`), a child of
//! [`crate::measure`].

use super::{
    Context, Found, M6_PROMPT, MeasureSession, Res, await_turn, blocked, get, is_dict, key, object,
    observed, started_turn_id, text,
};
use car_machine::json::{Map, Value};

pub const SANDBOXES: [&str; 4] = [
    "readOnly",
    "workspaceWrite",
    "externalSandbox",
    "dangerFullAccess",
];
pub const POLICIES: [&str; 4] = ["untrusted", "on-failure", "on-request", "never"];

/// `_word(value, known)`: one of `known`, or `other`.
pub fn word(value: Option<&Value>, known: &[&str]) -> Value {
    match value {
        Some(Value::Str(found)) if known.iter().any(|each| found.as_bytes() == each.as_bytes()) => {
            Value::Str(found.clone())
        }
        _ => text("other"),
    }
}

/// `_settings(resumed)`.
pub fn settings(resumed: &Value) -> Map {
    let empty = Value::Object(Map::new());
    let resumed = if is_dict(resumed) { resumed } else { &empty };
    let sandbox = get(resumed, "sandbox");
    let policy = get(resumed, "approvalPolicy");
    let kind = sandbox
        .filter(|each| is_dict(each))
        .and_then(|each| get(each, "type"));
    observed(vec![
        ("sandbox", word(kind, &SANDBOXES)),
        (
            "approval_policy",
            if policy.is_some_and(is_dict) {
                text("granular")
            } else {
                word(policy, &POLICIES)
            },
        ),
        (
            "reviewer",
            word(get(resumed, "approvalsReviewer"), &["user"]),
        ),
        (
            "permission_profile_set",
            Value::Bool(!matches!(
                get(resumed, "activePermissionProfile"),
                None | Some(Value::Null)
            )),
        ),
    ])
}

/// `_follow(session, thread, turn_id, seconds)`: (status, whether it ended by itself).
pub(super) fn follow(
    ctx: &mut Context<'_>,
    session: &mut dyn MeasureSession,
    turn_id: Option<&str>,
    seconds: f64,
) -> Res<(Option<String>, bool)> {
    let mut status = await_turn(ctx, session, turn_id, seconds, None);
    let ended = status.is_some();
    if let (false, Some(turn)) = (ended, turn_id) {
        match session.call(
            "turn/interrupt",
            Some(object(vec![
                ("threadId", ctx.thread_value()),
                ("turnId", text(turn)),
            ])),
        ) {
            Ok(_) => {
                let bound = ctx.timing.m6_interrupt;
                status = await_turn(ctx, session, Some(turn), bound, None);
            }
            Err(raised) if raised.is_adapter() => {}
            Err(raised) => return Err(raised),
        }
    }
    Ok((status, ended))
}

/// `_unsubscribed(session, thread)`.
pub(super) fn unsubscribed(ctx: &Context<'_>, session: &mut dyn MeasureSession) -> Res<bool> {
    match session.call(
        "thread/unsubscribe",
        Some(object(vec![("threadId", ctx.thread_value())])),
    ) {
        Ok(_) => Ok(true),
        Err(raised) if raised.is_adapter() => Ok(false),
        Err(raised) => Err(raised),
    }
}

/// `_app_running(ctx)`: False where it cannot say.
pub(super) fn app_running(ctx: &Context<'_>) -> bool {
    let Some(backend) = ctx.seams.backend.as_ref() else {
        return false;
    };
    let Some(identity) = backend.app_identity.as_ref() else {
        return false;
    };
    matches!(identity(), Ok(found) if found != Value::Null)
}

pub(super) fn m6b(ctx: &mut Context<'_>) -> Res<Found> {
    let (resumed, status, ended, unsubscribed_now, declined) =
        ctx.with_session(|ctx, session| {
            let resumed = session.call(
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
                ])),
            )?;
            let turn_id = started_turn_id(&started);
            let bound = ctx.timing.m6_turn;
            let (status, ended) = follow(ctx, session, turn_id.as_deref(), bound)?;
            let unsubscribed_now = unsubscribed(ctx, session)?;
            Ok((
                resumed,
                status,
                ended,
                unsubscribed_now,
                session.declined_count(),
            ))
        })?;
    let mut seen = settings(&resumed);
    seen.insert(key("approvals_declined"), declined);
    seen.insert(key("turn_ended_by_itself"), Value::Bool(ended));
    seen.insert(key("unsubscribed"), Value::Bool(unsubscribed_now));
    seen.insert(key("app_running_after"), Value::Bool(app_running(ctx)));
    if let Some(status) = status {
        seen.insert(key("turn_status"), text(&status));
    }
    blocked(
        "confirm no window or console appeared and the turn shows in Codex afterwards; start the Codex app during a second run, open the conversation and say what it showed, then set the verdict",
        seen,
    )
}
