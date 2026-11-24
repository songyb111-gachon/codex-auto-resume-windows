//! `codex/eligibility.py`: which kinds of Codex conversation this product takes up: the checks of a `threads` row's
//! source and its rollout's first line, pure (v0.6.16-beta.4).
//!
//! The Codex app's own conversations always (A15): source vscode, an originator of the app's, its first line's source
//! vscode. Beside them, only while the edition's plug names them (P18), a terminal's Codex TUI and the VS Code
//! extension's. A word not on these lists takes nothing up, never another conversation; `codex exec` runs and every
//! kind Codex makes for itself stay out - but for a fork a person made of one in the app (issue #66, "exec_forked").
//! Every statement sent to Codex stays in `history.rs`; this only judges what it read.
//!
//! Pure: nothing here reads or writes.

use std::collections::BTreeSet;

use car_machine::compat::model::parse_version;
use car_machine::domain::ids;
use car_machine::json::Value;
use car_machine::pyval::{self, Py};

use crate::sql::Cell;
use crate::values::{
    ADOPTED_ORIGINATORS, DESKTOP_ORIGINATORS, EXEC_FORK_ORIGINATORS, NOT_DESKTOP_ORIGINATORS,
    taken_thread_source,
};

pub const ORIGINATORS_CLI: [&str; 1] = ["codex-tui"];
pub const ORIGINATORS_IDE: [&str; 1] = ["codex_vscode"];

/// One kind's shape: (threads.source, the first line's source, its originators).
pub struct Shape {
    pub source: &'static str,
    pub first_source: &'static str,
    pub originators: &'static [&'static str],
}

/// `KINDS`: the app's, the two a plug may name, and the three the app took over or forked.
pub fn shape(kind: &str) -> Option<Shape> {
    Some(match kind {
        "desktop" => Shape {
            source: "vscode",
            first_source: "vscode",
            originators: &DESKTOP_ORIGINATORS,
        },
        "cli" => Shape {
            source: "cli",
            first_source: "cli",
            originators: &ORIGINATORS_CLI,
        },
        "ide" => Shape {
            source: "vscode",
            first_source: "vscode",
            originators: &ORIGINATORS_IDE,
        },
        // issue #37: a CLI conversation the Desktop app took over - the app's own, always.
        "adopted" => Shape {
            source: "vscode",
            first_source: "cli",
            originators: &ADOPTED_ORIGINATORS,
        },
        // and one the app forked from it ("continue in a new chat").
        "forked" => Shape {
            source: "vscode",
            first_source: "vscode",
            originators: &ADOPTED_ORIGINATORS,
        },
        // issue #66 (v0.6.24): a fork a person made in the app of a `codex exec` run.
        "exec_forked" => Shape {
            source: "vscode",
            first_source: "vscode",
            originators: &EXEC_FORK_ORIGINATORS,
        },
        _ => return None,
    })
}

/// The kinds whose first line must name the conversation it was forked from.
pub const FORKS_ONLY: [&str; 1] = ["exec_forked"];
/// The kinds taken up whatever the plug names.
pub const APPS: [&str; 4] = ["desktop", "adopted", "forked", "exec_forked"];

/// `_shapes(kinds)`: the kinds taken up, in the fixed order (`kinds` are the plug's).
fn shapes(kinds: &BTreeSet<String>) -> Vec<(&'static str, Shape)> {
    ["desktop", "adopted", "forked", "exec_forked", "cli", "ide"]
        .into_iter()
        .filter(|kind| APPS.contains(kind) || kinds.contains(*kind))
        .filter_map(|kind| shape(kind).map(|found| (kind, found)))
        .collect()
}

/// The shape a conversation is taken up in while the plug widens to every desktop conversation (P19).
pub const WIDENED: (&str, &str) = ("vscode", "vscode");

fn widened_on(widened: &BTreeSet<String>) -> bool {
    widened.contains("every_desktop")
}

/// `widened_originator(originator, widened)`: whether `originator` is taken up on the app's row because the plug
/// widens to every desktop conversation: a word (1 to 64 characters) not on the closed deny-list.
pub fn widened_originator(originator: &Value, widened: &BTreeSet<String>) -> bool {
    widened_on(widened)
        && match originator {
            Value::Str(text) => {
                let length = text.len();
                0 < length
                    && length <= 64
                    && !text
                        .as_str()
                        .is_some_and(|word| NOT_DESKTOP_ORIGINATORS.contains(&word))
            }
            _ => false,
        }
}

/// `forked(first)`: whether a rollout's first line (its session_meta payload) names the conversation it was forked
/// from.
pub fn forked(first: &Value) -> bool {
    match first {
        Value::Object(map) => map.get("forked_from_id").is_some_and(ids::is_uuid),
        _ => false,
    }
}

/// `source_taken(source, kinds)`: whether a `threads` row's source is one of a kind taken up.
pub fn source_taken(source: &Value, kinds: &BTreeSet<String>) -> bool {
    shapes(kinds)
        .iter()
        .any(|(_, found)| pyval::is(source, found.source))
}

/// `row_problem(row, kinds, widened, composed)`: why a `threads` row (source, archived, thread_source, history_mode)
/// is not one taken up, as the word `domain/skips.py` says it in - or None. `row` is the four cells.
pub struct ThreadRow<'a> {
    pub source: &'a Cell,
    pub archived: &'a Cell,
    pub thread_source: &'a Cell,
    pub history_mode: &'a Cell,
}

pub fn row_problem(
    row: &ThreadRow<'_>,
    kinds: &BTreeSet<String>,
    widened: &BTreeSet<String>,
    composed: bool,
) -> Py<Option<String>> {
    // The reference builds all four pairs before it looks at one, so a thread_source that cannot be hashed raises
    // even where the source is the problem.
    let source_ok = source_taken(&row.source.value(), kinds);
    // A BLOB (`bytes`) is hashable and no label of Codex's: never taken up, and never an exception.
    let thread_source_ok = if matches!(row.thread_source, Cell::Blob(_)) {
        false
    } else {
        taken_thread_source(&row.thread_source.value(), widened, composed)?
    };
    if !source_ok {
        return Ok(Some(format!("source {}", row.source.kind())));
    }
    // `row["archived"] != 0`: a number is told by value (0.0 is 0), anything else is not 0.
    let archived_zero = match row.archived {
        Cell::Int(number) => *number == 0,
        Cell::Real(number) => *number == 0.0,
        _ => false,
    };
    if !archived_zero {
        return Ok(Some("archived".to_owned()));
    }
    if !thread_source_ok {
        return Ok(Some(format!("thread_source {}", row.thread_source.kind())));
    }
    if row.history_mode.text() != Some("paginated") {
        return Ok(Some(format!("history_mode {}", row.history_mode.kind())));
    }
    Ok(None)
}

fn get<'a>(first: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match first {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// `originator_taken(source, first, kinds, widened)`: whether a first line's originator is one of a kind taken up
/// whose rows have `source` - for a kind of FORKS_ONLY, only where the line names the conversation it was forked from
/// - or, on the app's row while the plug widens to every desktop conversation, any originator but the deny-list's.
pub fn originator_taken(
    source: &Value,
    first: &Value,
    kinds: &BTreeSet<String>,
    widened: &BTreeSet<String>,
) -> Py<bool> {
    if !matches!(first, Value::Object(_)) {
        return Ok(false);
    }
    let originator = get(first, "originator");
    for (kind, found) in shapes(kinds) {
        if pyval::is(source, found.source) {
            // `originator in shape[2]` hashes the originator: a list or a dict raises.
            pyval::hashable(originator)?;
            if pyval::in_tuple(originator, found.originators)
                && (!FORKS_ONLY.contains(&kind) || forked(first))
            {
                return Ok(true);
            }
        }
    }
    Ok(pyval::is(source, WIDENED.0) && widened_originator(originator, widened))
}

/// `newer_than_engine(cli_version, engine_version)`: whether the Codex a conversation's first line says wrote it is
/// newer than the engine's own `codex --version`, both read as the compatibility data reads a version; False where
/// either cannot be read - a guard that only ever holds back, never a refusal on a guess.
pub fn newer_than_engine(cli_version: &Value, engine_version: &Value) -> bool {
    let written = match cli_version {
        Value::Str(text) => text
            .as_str()
            .and_then(|word| parse_version(&Value::from(format!("codex-cli {word}").as_str()))),
        _ => None,
    };
    let engine = parse_version(engine_version);
    matches!((written, engine), (Some(written), Some(engine)) if written > engine)
}

/// `kind_of(source, payload, kinds, widened)`: the kind - "desktop", "cli" or "ide" - a conversation is, by its row's
/// source and its first line's originator and source, of the app's and `kinds` - or "desktop" for the app's row and
/// first line with any originator but the deny-list's while the plug widens to every desktop conversation (P19); None
/// for anything else.
pub fn kind_of(
    source: &Value,
    payload: &Value,
    kinds: &BTreeSet<String>,
    widened: &BTreeSet<String>,
) -> Py<Option<&'static str>> {
    if !matches!(payload, Value::Object(_)) {
        return Ok(None);
    }
    let mut found: Option<&'static str> = None;
    for (kind, shaped) in shapes(kinds) {
        if pyval::is(source, shaped.source)
            && pyval::eq(get(payload, "source"), &Value::from(shaped.first_source))
        {
            let originator = get(payload, "originator");
            pyval::hashable(originator)?;
            if pyval::in_tuple(originator, shaped.originators)
                && (!FORKS_ONLY.contains(&kind) || forked(payload))
            {
                found = Some(kind);
                break;
            }
        }
    }
    if found.is_none()
        && pyval::is(source, WIDENED.0)
        && pyval::is(get(payload, "source"), WIDENED.1)
        && widened_originator(get(payload, "originator"), widened)
    {
        return Ok(Some("desktop"));
    }
    Ok(match found {
        Some("adopted" | "forked" | "exec_forked") => Some("desktop"),
        other => other,
    })
}
