//! `codex/conversation.py`: a conversation's messages and replies, read-only, for the Dashboard's Chat page alone (seat
//! S7.2c): the last TURNS turns, each turn's status, the text of its `userMessage` and `agentMessage` items (each cut at
//! ITEM_BYTES, a view at VIEW_BYTES, this product's marker taken out) and how many commands, file changes and tool calls
//! it made, as counts.

use car_codex::sql::{self, Cell, Param};
use car_machine::compat::loads;
use car_machine::domain::ids;
use car_machine::json::{Map, Value};

use super::turns::{Read, SharedOs, connect, thread_id_text, unavailable};

pub const TURNS: i64 = 20;
pub const ITEM_BYTES: usize = 16 * 1024;
pub const VIEW_BYTES: i64 = 256 * 1024;
pub const TEXT_KINDS: [&str; 2] = ["userMessage", "agentMessage"];
pub const COUNTED: [(&str, &str); 3] = [("commandExecution", "commands"), ("fileChange", "files"), ("mcpToolCall", "tools")];
pub const TURN_COLUMNS: &[&str] = &["thread_id", "turn_id", "status", "rollout_ordinal", "started_at", "completed_at"];
pub const ITEM_COLUMNS: &[&str] = &["thread_id", "turn_id", "item_type", "item_json", "rollout_ordinal"];
pub const LAST_TURNS: &str = "SELECT turn_id, status, started_at, completed_at FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal DESC LIMIT ?";
pub const TEXTS: &str = "SELECT item_type, item_json FROM thread_items WHERE thread_id=? AND turn_id=? AND item_type IN (?, ?) ORDER BY rollout_ordinal";
pub const COUNTS: &str = "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? GROUP BY item_type";
pub const STATEMENTS: [&str; 3] = [LAST_TURNS, TEXTS, COUNTS];
pub const STATUSES: [&str; 4] = ["completed", "failed", "interrupted", "inProgress"];

/// `MARKER.sub("", words)` over code points: `\s*\[codex-auto-resume:[0-9a-f]{16}\]\s*$` taken off the end. The leftmost
/// start from which the pattern reaches the end wins; the spaces before the bracket are taken greedily, and fewer of
/// them would leave a space where the bracket must be.
fn without_marker(words: &[u32]) -> Vec<u32> {
    let space = |point: u32| char::from_u32(point).is_some_and(car_machine::pytext::is_space);
    let prefix: Vec<u32> = "[codex-auto-resume:".chars().map(|c| c as u32).collect();
    for start in 0..words.len() {
        let mut at = start;
        while at < words.len() && space(words[at]) {
            at += 1;
        }
        let rest = &words[at..];
        if !rest.starts_with(&prefix) {
            continue;
        }
        let rest = &rest[prefix.len()..];
        if rest.len() < 17
            || !rest[..16].iter().all(|point| matches!(char::from_u32(*point), Some('0'..='9' | 'a'..='f')))
            || rest[16] != u32::from(b']')
        {
            continue;
        }
        if rest[17..].iter().all(|point| space(*point)) {
            return words[..start].to_vec();
        }
    }
    words.to_vec()
}

fn points(text: &car_machine::json::Str) -> Vec<u32> {
    text.code_points().collect()
}

/// `_text(kind, raw)`: the words of one item, cut at ITEM_BYTES, the marker taken out - or none. Words that hold half a
/// surrogate pair cannot be encoded: the ValueError (`UnicodeEncodeError`) the reference's `encode` raises. A content that
/// is a truthy number cannot be iterated: the TypeError. A nesting too deep: the RecursionError.
pub fn text(kind: &str, raw: &Value) -> Result<Option<String>, &'static str> {
    let Value::Str(raw) = raw else {
        return Ok(None);
    };
    let item = match loads(raw.as_str().unwrap_or("")) {
        Ok(item) => item,
        Err(car_machine::compat::LoadsError::Recursion) => return Err("RecursionError"),
        Err(_) => return Ok(None),
    };
    let Value::Object(item) = item else {
        return Ok(None);
    };
    let words: Vec<u32> = if kind == "userMessage" {
        let mut parts: Vec<Vec<u32>> = Vec::new();
        match item.get("content") {
            Some(content) if car_machine::pyval::truthy(content) => match content {
                Value::Array(content) => {
                    for part in content {
                        if let Value::Object(part) = part
                            && matches!(part.get("type"), Some(Value::Str(word)) if word.as_bytes() == b"text")
                            && let Some(Value::Str(text)) = part.get("text")
                        {
                            parts.push(points(text));
                        }
                    }
                }
                Value::Str(_) | Value::Object(_) => {}
                _ => return Err("TypeError"),
            },
            _ => {}
        }
        parts.join(&10u32)
    } else {
        match item.get("text") {
            Some(Value::Str(text)) => points(text),
            _ => Vec::new(),
        }
    };
    let words = without_marker(&words);
    if words.iter().any(|point| (0xD800..0xE000).contains(point)) {
        return Err("ValueError");
    }
    let mut words: String = words.iter().filter_map(|point| char::from_u32(*point)).collect();
    if words.len() > ITEM_BYTES {
        let mut cut = ITEM_BYTES;
        while !words.is_char_boundary(cut) {
            cut -= 1;
        }
        words.truncate(cut);
    }
    Ok((!words.is_empty()).then_some(words))
}

/// The history of the Codex home `home`, as the Chat page reads it.
pub struct Conversation {
    pub home: String,
    pub os: SharedOs,
}

impl Conversation {
    /// `view(thread_id)`: the conversation's last TURNS turns, oldest first.
    pub fn view(&self, thread_id: &Value) -> Read<Vec<Value>> {
        if !ids::is_uuid(thread_id) {
            return Err(unavailable("not a conversation"));
        }
        let thread = thread_id_text(thread_id);
        let connection = connect(
            self.os.as_ref(),
            &self.home,
            "history",
            &[("thread_turns", TURN_COLUMNS), ("thread_items", ITEM_COLUMNS)],
        )?;
        let failed = |_| unavailable("the conversation cannot be read");
        let turns = sql::query(&connection, LAST_TURNS, &[Param::Text(&thread), Param::Int(TURNS)]).map_err(failed)?;
        let mut shown = Vec::new();
        let mut budget = VIEW_BYTES;
        for turn in &turns {
            let turn_id = turn.at(0);
            let mut messages = Vec::new();
            let texts = sql::query(
                &connection,
                TEXTS,
                &[Param::Text(&thread), turn_id.param(), Param::Text(TEXT_KINDS[0]), Param::Text(TEXT_KINDS[1])],
            )
            .map_err(failed)?;
            for item in texts {
                let kind = item.at(0).text().unwrap_or("").to_owned();
                let words = text(&kind, &item.at(1).value()).map_err(|class| match class {
                    "ValueError" => unavailable("the conversation cannot be read"),
                    other => super::turns::Failure::Raised(other),
                })?;
                let Some(words) = words else {
                    continue;
                };
                if budget <= 0 {
                    continue;
                }
                budget -= words.len() as i64;
                let mut message = Map::new();
                message.insert("from".into(), Value::from(if kind == "userMessage" { "you" } else { "codex" }));
                message.insert("words".into(), Value::from(words));
                messages.push(Value::Object(message));
            }
            let mut counts: Vec<(&str, i64)> = COUNTED.iter().map(|(_, name)| (*name, 0)).collect();
            for row in sql::query(&connection, COUNTS, &[Param::Text(&thread), turn_id.param()]).map_err(failed)? {
                if let Cell::Text(kind) = row.at(0)
                    && let Some((_, name)) = COUNTED.iter().find(|(each, _)| each == kind)
                    && let Some(slot) = counts.iter_mut().find(|(each, _)| each == name)
                {
                    slot.1 += match row.at(1) {
                        Cell::Int(count) => *count,
                        _ => 0,
                    };
                }
            }
            let mut out = Map::new();
            let id = turn_id.value();
            out.insert("turn_id".into(), if ids::is_uuid(&id) { id } else { Value::Null });
            out.insert(
                "status".into(),
                match turn.at(1) {
                    Cell::Text(status) if STATUSES.contains(&status.as_str()) => Value::from(status.as_str()),
                    _ => Value::from("other"),
                },
            );
            for (index, key) in [(2, "started_at"), (3, "completed_at")] {
                out.insert(
                    key.into(),
                    match turn.at(index) {
                        Cell::Int(at) => Value::from(*at),
                        _ => Value::Null,
                    },
                );
            }
            out.insert("messages".into(), Value::Array(messages));
            out.insert(
                "counts".into(),
                Value::Object(counts.into_iter().map(|(name, count)| (name.into(), Value::from(count))).collect()),
            );
            shown.push(Value::Object(out));
        }
        shown.reverse();
        Ok(shown)
    }
}
