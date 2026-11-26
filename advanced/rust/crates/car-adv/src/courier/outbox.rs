//! `courier/outbox.py` (seat S7.3b): the pushed notices waiting to go (state `outbox`) - written, tried and dropped
//! through the advanced state's own file and transaction; no network.
//!
//! One row a notice a channel: a closed event, core's category word or none, the record's place in Pending as `task N`
//! or none, when it was raised, how many tries it had, and whether it waits, went or was dropped. Bounds, all channels
//! together: at most [`HOURLY`] rows raised in any hour; [`TRIES`] tries each, the next not before `AFTER[tries]`
//! seconds from when it was raised; dropped after the last, or at [`MAX_AGE`]. A notice raised before push_notices was
//! last turned on is dropped unsent at the next pass ([`stale`]).

use car_machine::json::Value;

use crate::state::py;
use crate::state::sql::{self, Row, float, int, string};
use crate::state::{AdvancedState, Error, Result};
use crate::vocabulary::{CourierChannel, CourierEvent, OutboxState};

pub const CAPABILITY: &str = "push_notices";
pub const HOURLY: i64 = 30;
pub const TRIES: i64 = 3;
/// Seconds after a notice was raised before its first, second and third try.
pub const AFTER: [f64; 3] = [0.0, 10.0, 70.0];
pub const MAX_AGE: f64 = 7.0 * 86400.0;
pub const TRIPWIRE: i64 = 20;
pub const DAY: f64 = 86400.0;
/// How a try failed, as the journal keeps it; the two a channel's tripwire counts.
pub const FAILED: [&str; 4] = ["4xx", "5xx", "timeout", "tls"];
pub const REFUSING: [&str; 2] = ["4xx", "tls"];

/// `codes()`: push_notices' journal codes, every channel's, in a stable order.
pub fn codes() -> Vec<String> {
    let mut found = Vec::new();
    for channel in CourierChannel::ALL {
        let channel = channel.as_str();
        found.push(format!("sent_{channel}"));
        found.extend(
            FAILED
                .iter()
                .map(|word| format!("refused_{channel}_{word}")),
        );
        found.push(format!("dropped_{channel}"));
        found.push(format!("off_{channel}"));
    }
    found
}

/// `alias(index)`: a record's 1-based place in Pending as a push names it, `task N`, or None.
pub fn alias(index: &Value) -> Value {
    match index {
        Value::Int(number) => match number.as_i64() {
            Some(number) if (1..=9999).contains(&number) => Value::from(format!("task {number}")),
            _ => Value::Null,
        },
        _ => Value::Null,
    }
}

/// `CourierEvent(event)`: ValueError for anything that is not one.
pub fn event_of(event: &Value) -> Result<&'static str> {
    py::text(event)
        .and_then(|text| CourierEvent::ALL.iter().find(|each| each.as_str() == text))
        .map(|each| each.as_str())
        .ok_or_else(|| Error::python("ValueError", "is not a valid CourierEvent"))
}

/// `CourierChannel(channel)`: ValueError for anything that is not one.
pub fn channel_of(channel: &Value) -> Result<&'static str> {
    py::text(channel)
        .and_then(CourierChannel::parse)
        .map(CourierChannel::as_str)
        .ok_or_else(|| Error::python("ValueError", "is not a valid CourierChannel"))
}

fn waiting_word() -> Value {
    string(OutboxState::Waiting.as_str())
}

/// `enqueue(state, channels, event, category, task, at)`: one row for each of `channels`, as far as the hour leaves
/// room; how many were written.
pub fn enqueue(
    state: &AdvancedState,
    channels: &[Value],
    event: &Value,
    category: &Value,
    task: &Value,
    at: f64,
) -> Result<i64> {
    let event = event_of(event)?;
    let channels = channels
        .iter()
        .map(channel_of)
        .collect::<Result<Vec<&str>>>()?;
    state.writing(|connection| {
        let used = sql::number(
            connection,
            "SELECT count(*) FROM outbox WHERE at > ?",
            &[float(at - 3600.0)],
        )?;
        let room = (HOURLY - used).max(0);
        for channel in channels.iter().take(room as usize) {
            sql::exec(
                connection,
                "INSERT INTO outbox (channel, event, category, alias, at, tries, state, finished_at) \
                 VALUES (?,?,?,?,?,0,?,NULL)",
                &[
                    string(channel),
                    string(event),
                    category.clone(),
                    task.clone(),
                    float(at),
                    waiting_word(),
                ],
            )?;
        }
        Ok(room.min(channels.len() as i64))
    })
}

fn at_of(row: &Row) -> f64 {
    py::as_f64(sql::get(row, "at")).unwrap_or(f64::NAN)
}

fn tries_of(row: &Row) -> i64 {
    py::small(sql::get(row, "tries")).unwrap_or(0)
}

fn after(tries: i64) -> f64 {
    // AFTER[tries]: a negative index counts from the end, as Python's does.
    let index = if tries < 0 { tries + 3 } else { tries };
    AFTER[index.clamp(0, 2) as usize]
}

/// `due(state, now)`: the rows waiting whose next try is due at `now`, oldest first.
pub fn due(state: &AdvancedState, now: f64) -> Result<Vec<Row>> {
    let rows = state.read(|connection| match connection {
        None => Ok(Vec::new()),
        Some(connection) => sql::all(
            connection,
            "SELECT item_id, channel, event, category, alias, at, tries FROM outbox WHERE state = ? ORDER BY item_id",
            &[waiting_word()],
        ),
    })?;
    Ok(rows
        .into_iter()
        .filter(|row| {
            let (at, tries) = (at_of(row), tries_of(row));
            tries < TRIES && now - at < MAX_AGE && now >= at + after(tries)
        })
        .collect())
}

/// `waiting(state, now)`: whether a row waits whose try is due, or one has grown too old to wait.
pub fn waiting(state: &AdvancedState, now: f64) -> Result<bool> {
    let rows = state.read(|connection| match connection {
        None => Ok(Vec::new()),
        Some(connection) => sql::all(
            connection,
            "SELECT at, tries FROM outbox WHERE state = ?",
            &[waiting_word()],
        ),
    })?;
    Ok(rows.iter().any(|row| {
        let at = at_of(row);
        now - at >= MAX_AGE || now >= at + after(tries_of(row).min(TRIES - 1))
    }))
}

/// `settle(state, item_id, sent, now)`: what a try of row `item_id` came to; the row's state after.
pub fn settle(
    state: &AdvancedState,
    item_id: &Value,
    sent: bool,
    now: f64,
) -> Result<&'static str> {
    state.writing(|connection| {
        let row = sql::one(
            connection,
            "SELECT tries FROM outbox WHERE item_id = ? AND state = ?",
            &[item_id.clone(), waiting_word()],
        )?;
        let Some(row) = row else {
            return Ok(OutboxState::Dropped.as_str());
        };
        let tries = tries_of(&row);
        if sent {
            sql::exec(
                connection,
                "UPDATE outbox SET tries = ?, state = ?, finished_at = ? WHERE item_id = ?",
                &[
                    int((tries + 1).min(TRIES)),
                    string(OutboxState::Sent.as_str()),
                    float(now),
                    item_id.clone(),
                ],
            )?;
            return Ok(OutboxState::Sent.as_str());
        }
        let tries = tries + 1;
        if tries >= TRIES {
            sql::exec(
                connection,
                "UPDATE outbox SET tries = ?, state = ?, finished_at = ? WHERE item_id = ?",
                &[
                    int(TRIES),
                    string(OutboxState::Dropped.as_str()),
                    float(now),
                    item_id.clone(),
                ],
            )?;
            return Ok(OutboxState::Dropped.as_str());
        }
        sql::exec(
            connection,
            "UPDATE outbox SET tries = ? WHERE item_id = ?",
            &[int(tries), item_id.clone()],
        )?;
        Ok(OutboxState::Waiting.as_str())
    })
}

fn drop_where(state: &AdvancedState, select: &str, bound: f64, now: f64) -> Result<Vec<Value>> {
    let rows = state.writing(|connection| {
        let rows = sql::all(connection, select, &[waiting_word(), float(bound)])?;
        for row in &rows {
            sql::exec(
                connection,
                "UPDATE outbox SET state = ?, finished_at = ? WHERE item_id = ?",
                &[
                    string(OutboxState::Dropped.as_str()),
                    float(now),
                    sql::get(row, "item_id").clone(),
                ],
            )?;
        }
        Ok(rows)
    })?;
    Ok(rows
        .iter()
        .map(|row| sql::get(row, "channel").clone())
        .collect())
}

/// `expire(state, now)`: every row waiting MAX_AGE or longer, dropped; their channels.
pub fn expire(state: &AdvancedState, now: f64) -> Result<Vec<Value>> {
    drop_where(
        state,
        "SELECT item_id, channel FROM outbox WHERE state = ? AND at <= ?",
        now - MAX_AGE,
        now,
    )
}

/// `stale(state, since, now)`: every row waiting raised before `since`, dropped; nothing where `since` is no time.
pub fn stale(state: &AdvancedState, since: &Value, now: f64) -> Result<Vec<Value>> {
    let since = match since {
        Value::Int(_) | Value::Float(_) => py::as_f64(since).unwrap_or(f64::NAN),
        _ => return Ok(Vec::new()),
    };
    drop_where(
        state,
        "SELECT item_id, channel FROM outbox WHERE state = ? AND at < ?",
        since,
        now,
    )
}

/// `refusals_today(state, channel, now)`: how many tries `channel` had refused today (4xx or TLS).
pub fn refusals_today(state: &AdvancedState, channel: &Value, now: f64) -> Result<i64> {
    let channel = channel_of(channel)?;
    let names: Vec<Value> = REFUSING
        .iter()
        .map(|word| string(&format!("refused_{channel}_{word}")))
        .collect();
    state.read(|connection| match connection {
        None => Ok(0),
        Some(connection) => {
            let found = sql::scalar(
                connection,
                "SELECT sum(count) FROM sampler WHERE capability = ? AND day = ? AND code IN (?, ?)",
                &[
                    string(CAPABILITY),
                    int(py::floordiv(now, DAY) as i64),
                    names[0].clone(),
                    names[1].clone(),
                ],
            )?;
            Ok(py::small(&found).unwrap_or(0))
        }
    })
}

/// `OutboxHandle`: push_notices' view of the outbox, as its code is given it (`Scoped.outbox`): rows written only while
/// it stands on and only by push_notices; whether one waits, read always.
pub struct OutboxHandle<'a> {
    pub state: &'a AdvancedState,
    pub capability: &'a Value,
    pub on: Option<&'a dyn Fn() -> bool>,
}

impl OutboxHandle<'_> {
    fn ours(&self) -> bool {
        py::text(self.capability) == Some(CAPABILITY)
    }

    pub fn enqueue(
        &self,
        channels: &[Value],
        event: &Value,
        category: &Value,
        task: &Value,
        at: f64,
    ) -> Result<i64> {
        if !self.ours() || !self.on.is_some_and(|on| on()) {
            return Ok(0);
        }
        enqueue(self.state, channels, event, category, task, at)
    }

    pub fn waiting(&self, now: f64) -> Result<bool> {
        Ok(self.ours() && waiting(self.state, now)?)
    }
}
