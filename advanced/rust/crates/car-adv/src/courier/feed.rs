//! `courier/feed.py` (seat S7.3b): OpenAI's status page, read once and reduced to two words and a count (status_feed).
//!
//! One GET of [`SUMMARY_URL`], read as Statuspage's v2 summary: `status.indicator` (none -> operational, minor ->
//! degraded, major or critical -> outage), the first component whose name starts with "Codex", and how many incidents
//! are listed (at most 99). Nothing else is kept, and what is kept is a word to show - never a gate's input. A reply that
//! cannot be read is unknown; a page that cannot be reached leaves no words, its time moved on (`touch`).

#![allow(clippy::result_unit_err)]

use car_machine::json::Value;

use crate::courier::http::{self, Opener};
use crate::courier::main::Runtime;
use crate::state::sql::{self, Row, float, int, string};
use crate::state::{AdvancedState, Result};
use crate::vocabulary::FeedWord;

pub const CAPABILITY: &str = "status_feed";
pub const SUMMARY_URL: &str = "https://status.openai.com/api/v2/summary.json";
pub const MOST_INCIDENTS: i64 = 99;
/// `http.MAX_REPLY`: a reply this long was cut, and is not read.
pub const MAX_REPLY: usize = 65536;

/// (word, codex_word, incidents).
pub type Found = (FeedWord, FeedWord, i64);
pub const UNKNOWN: Found = (FeedWord::Unknown, FeedWord::Unknown, 0);

/// `json.loads(raw.decode("utf-8"))`: the value; `Ok(None)` where it raises a ValueError (a UnicodeDecodeError, a
/// JSONDecodeError, a leading BOM); `Err(())` for the RecursionError of a document nested too deep, which goes on up.
pub fn loads_bytes(raw: &[u8]) -> std::result::Result<Option<Value>, ()> {
    let Ok(text) = std::str::from_utf8(raw) else {
        return Ok(None);
    };
    if text.starts_with('\u{FEFF}') {
        return Ok(None);
    }
    match car_machine::compat::loads(text) {
        Ok(value) => Ok(Some(value)),
        Err(car_machine::compat::LoadsError::Recursion) => Err(()),
        Err(_) => Ok(None),
    }
}

fn indicator(word: &str) -> FeedWord {
    match word {
        "none" => FeedWord::Operational,
        "minor" => FeedWord::Degraded,
        "major" | "critical" => FeedWord::Outage,
        _ => FeedWord::Unknown,
    }
}

fn component(word: &str) -> FeedWord {
    match word {
        "operational" => FeedWord::Operational,
        "degraded_performance" | "partial_outage" => FeedWord::Degraded,
        "major_outage" => FeedWord::Outage,
        _ => FeedWord::Unknown,
    }
}

fn starts_with(value: &Value, prefix: &str) -> bool {
    match value {
        Value::Str(text) => text.as_bytes().starts_with(prefix.as_bytes()),
        _ => false,
    }
}

/// `parse(raw)`: the summary's (word, codex_word, incidents); UNKNOWN for anything that is not one. `Err` is the
/// RecursionError a document nested too deep raises.
pub fn parse(raw: &[u8]) -> std::result::Result<Found, ()> {
    if raw.len() >= MAX_REPLY {
        return Ok(UNKNOWN);
    }
    let Some(Value::Object(found)) = loads_bytes(raw)? else {
        return Ok(UNKNOWN);
    };
    let word = match found.get("status") {
        Some(Value::Object(status)) => match status.get("indicator") {
            Some(Value::Str(text)) => text.as_str().map_or(FeedWord::Unknown, indicator),
            _ => FeedWord::Unknown,
        },
        _ => FeedWord::Unknown,
    };
    let mut codex = FeedWord::Unknown;
    if let Some(Value::Array(components)) = found.get("components") {
        for each in components {
            let Value::Object(each) = each else {
                continue;
            };
            if each
                .get("name")
                .is_some_and(|name| starts_with(name, "Codex"))
            {
                codex = match each.get("status") {
                    Some(Value::Str(text)) => text.as_str().map_or(FeedWord::Unknown, component),
                    _ => FeedWord::Unknown,
                };
                break;
            }
        }
    }
    let count = match found.get("incidents") {
        Some(Value::Array(incidents)) => (incidents.len() as i64).min(MOST_INCIDENTS),
        _ => 0,
    };
    Ok((word, codex, count))
}

/// `save(state, found, now)`: the one `feed` row.
pub fn save(state: &AdvancedState, found: Found, now: f64) -> Result<()> {
    let (word, codex, count) = found;
    state.writing(|connection| {
        sql::exec(
            connection,
            "INSERT INTO feed (singleton, checked_at, word, codex_word, incidents) VALUES (1,?,?,?,?) \
             ON CONFLICT(singleton) DO UPDATE SET checked_at = excluded.checked_at, word = excluded.word, \
             codex_word = excluded.codex_word, incidents = excluded.incidents",
            &[
                float(now),
                string(word.as_str()),
                string(codex.as_str()),
                int(count),
            ],
        )?;
        Ok(())
    })
}

/// `touch(state, now)`: a read that could not reach the page - the time moved on, and no words.
pub fn touch(state: &AdvancedState, now: f64) -> Result<()> {
    state.writing(|connection| {
        sql::exec(
            connection,
            "INSERT INTO feed (singleton, checked_at) VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE \
             SET checked_at = excluded.checked_at, word = NULL, codex_word = NULL, incidents = NULL",
            &[float(now)],
        )?;
        Ok(())
    })
}

/// `unreached(row)`: a kept row that is a read that could not reach the page - a time and no words.
pub fn unreached(row: &Value) -> bool {
    let Value::Object(row) = row else {
        return false;
    };
    let get = |key: &str| row.get(key).cloned().unwrap_or(Value::Null);
    matches!(get("checked_at"), Value::Int(_) | Value::Float(_))
        && matches!(get("word"), Value::Null)
        && matches!(get("codex_word"), Value::Null)
}

/// `read(state)`: the `feed` row, or None.
pub fn read(state: &AdvancedState) -> Result<Option<Row>> {
    state.read(|connection| match connection {
        None => Ok(None),
        Some(connection) => sql::one(
            connection,
            "SELECT checked_at, word, codex_word, incidents FROM feed",
            &[],
        ),
    })
}

/// What `refresh` raised: the state's error, or the RecursionError of a page nested too deep.
#[derive(Debug)]
pub enum Raised {
    State(crate::state::Error),
    Recursion,
    Http(http::Failure),
}

/// `refresh(runtime, opener=, now=)`: one read of the page, kept and counted; what was kept (None for no reply).
pub fn refresh(
    runtime: &dyn Runtime,
    opener: &dyn Opener,
    now: Option<f64>,
) -> std::result::Result<Option<Found>, Raised> {
    let state = runtime.state();
    let now = now.unwrap_or_else(|| runtime.clock());
    let capability = string(CAPABILITY);
    let reply = match http::get(SUMMARY_URL, http::TIMEOUT, opener, http::MAX_REPLY) {
        Ok(reply) => reply,
        Err(http::Failure::Failed { .. }) => {
            touch(state, now).map_err(Raised::State)?;
            state
                .counted(&capability, &string("refused"), &Value::Null)
                .map_err(Raised::State)?;
            return Ok(None);
        }
        Err(other) => return Err(Raised::Http(other)),
    };
    let found = parse(&reply).map_err(|()| Raised::Recursion)?;
    save(state, found, now).map_err(Raised::State)?;
    let code = if found == UNKNOWN {
        "unknown"
    } else {
        "checked"
    };
    state
        .counted(&capability, &string(code), &Value::Null)
        .map_err(Raised::State)?;
    Ok(Some(found))
}
