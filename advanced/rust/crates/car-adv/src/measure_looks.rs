//! Seat S7.4: `measure.py`'s read-only probes of v0.6.16-beta.3 - MIPC (a look at the Desktop's pipe, never written
//! to), MAWS and MCLOUD (the engine's own CLI help, read for words and never recorded) - a child of
//! [`crate::measure`].

use super::{Context, Found, Res, blocked, get, observed};
use car_machine::json::Value;
use car_machine::pytext::strip;
use car_machine::pyval::truthy;

pub const WS_URL: &str = "CODEX_APP_SERVER_WS_URL";
pub const SHARED_SWITCH_WORDS: [&str; 7] = [
    "shared app-server",
    "shared-app-server",
    "shared backend",
    "shared-backend",
    "app-server-ws",
    "app_server_ws",
    "shared local app-server",
];
pub const CLOUD_STATE_WORDS: [&str; 6] = ["status", "state", "show", "list", "watch", "logs"];

/// `str.splitlines()`: every line boundary Python knows, `\r\n` as one.
pub fn splitlines(text: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = text.char_indices().peekable();
    while let Some((at, c)) = chars.next() {
        let boundary = matches!(
            c,
            '\n' | '\r'
                | '\u{0b}'
                | '\u{0c}'
                | '\u{1c}'
                | '\u{1d}'
                | '\u{1e}'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        );
        if !boundary {
            continue;
        }
        lines.push(&text[start..at]);
        let mut end = at + c.len_utf8();
        if c == '\r'
            && let Some((next, '\n')) = chars.peek().copied()
        {
            chars.next();
            end = next + 1;
        }
        start = end;
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}

pub(super) fn mipc(ctx: &mut Context<'_>) -> Res<Found> {
    let look = Value::Object(ctx.ipc_look());
    let flag = |name: &str| Value::Bool(get(&look, name).is_some_and(truthy));
    blocked(
        "a read-only look at the Desktop's IPC pipe: it is never written to. Confirm whether a turn of a conversation the app holds can be started, interrupted, or added to through it - stop-now and send-now wait on this answer - then set the verdict",
        observed(vec![
            ("pipe_exists", flag("exists")),
            ("pipe_opened", flag("opened")),
            ("frame_read", flag("frame_read")),
            ("no_answer", flag("no_answer")),
        ]),
    )
}

pub(super) fn maws(ctx: &mut Context<'_>) -> Res<Found> {
    let text = ctx.cli_help(&["app-server", "--help"]);
    let read = text.is_some();
    let help = text.unwrap_or_default();
    let lowered = help.to_lowercase();
    blocked(
        "a read-only look at the engine's help for a documented shared app-server. Confirm against Codex's own documentation, then set the verdict",
        observed(vec![
            ("help_read", Value::Bool(read)),
            (
                "ws_url_documented",
                Value::Bool(read && help.contains(WS_URL)),
            ),
            (
                "shared_switch_documented",
                Value::Bool(
                    read && SHARED_SWITCH_WORDS
                        .iter()
                        .any(|word| lowered.contains(word)),
                ),
            ),
        ]),
    )
}

pub(super) fn mcloud(ctx: &mut Context<'_>) -> Res<Found> {
    let text = ctx.cli_help(&["cloud", "--help"]);
    let read = text.is_some();
    let help = text.unwrap_or_default();
    let lowered = help.to_lowercase();
    let top = if read {
        ctx.cli_help(&["--help"])
    } else {
        None
    };
    let own_usage = splitlines(&lowered)
        .iter()
        .any(|line| strip(line).starts_with("usage:") && line.contains(" cloud"));
    let present = read
        && own_usage
        && top.as_deref().is_none_or(|top| strip(&help) != strip(top))
        && !lowered.contains("unrecognized")
        && !lowered.contains("unknown")
        && !lowered.contains("no such");
    blocked(
        "a read-only look for a `codex cloud` command and a supported way to read a cloud task's state. Confirm against Codex, then set the verdict",
        observed(vec![
            ("cloud_help_read", Value::Bool(read)),
            ("cloud_command_present", Value::Bool(present)),
            (
                "state_read_present",
                Value::Bool(present && CLOUD_STATE_WORDS.iter().any(|word| lowered.contains(word))),
            ),
        ]),
    )
}
