//! The four small tables (`state/restarts.py`, `state/opens.py`, `state/account.py`, `state/steers.py`): the
//! watcher's restarts after it stopped unexpectedly, the conversations opened for a waiting message, the account
//! last seen signed in (a keyed digest), and the lines a person asked to be added to a running turn.

use car_machine::json::Value;
use rusqlite::Connection;

use super::errors::{Error, Result};
use super::py;
use super::schema::STEER_WORDS;
use super::session::AdvancedState;
use super::sql::{self, Row, float, int, string};
use crate::vocabulary::{OpenOutcome, PlanWord, SteerReason, SteerState};

pub const RESTARTER: &str = "crash_restart";
pub const ACCOUNT: &str = "account_switch";
/// `opens.SETTLED`: what an open may settle as.
pub const SETTLED: &[&str] = &[
    OpenOutcome::Loaded.as_str(),
    OpenOutcome::NotLoaded.as_str(),
    OpenOutcome::Refused.as_str(),
];
/// `steers.WAITING` and `steers.SETTLED`.
pub const STEER_WAITING: &[&str] = &[SteerState::Requested.as_str(), SteerState::Sending.as_str()];
pub const STEER_SETTLED: &[&str] = &[
    SteerState::Accepted.as_str(),
    SteerState::Unconfirmed.as_str(),
    SteerState::Refused.as_str(),
];
const STEER_COLUMNS: &str =
    "steer_id, thread_id, words, client_id, state, reason, created_at, finished_at";

/// `isinstance(value, bool) or not isinstance(value, (int, float))` refused: a time a read takes.
fn time_or_refuse(value: &Value) -> Result<f64> {
    if !py::is_number(value) {
        return Err(Error::state("invalid time"));
    }
    py::float_of(value)
}

/// `account._DIGEST.match(value)`: 16 lowercase hex digits and the end (`\Z`).
fn digest16(value: &Value) -> bool {
    py::text(value).is_some_and(|text| {
        text.len() == 16
            && text
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}

/// `steers._client(client_id)`: 36 characters of hex digits and dashes.
fn client(value: &Value) -> Result<Value> {
    let fits = match value {
        Value::Str(text) => {
            let points: Vec<u32> = text.code_points().collect();
            points.len() == 36
                && points.iter().all(|point| {
                    char::from_u32(*point).is_some_and(|c| "0123456789abcdef-".contains(c))
                })
        }
        _ => false,
    };
    if fits {
        Ok(value.clone())
    } else {
        Err(Error::state("invalid client id"))
    }
}

/// `not words.strip()` of a text: nothing but white space.
pub(crate) fn blank(text: &car_machine::json::Str) -> bool {
    text.code_points()
        .all(|point| char::from_u32(point).is_some_and(car_machine::pytext::is_space))
}

impl AdvancedState {
    // ------------------------------------------------------------------ restarts
    /// `restart_noted(exit_code, restarted, at=None)`: one abnormal end decided on.
    pub fn restart_noted(&self, exit_code: &Value, restarted: &Value, at: &Value) -> Result<bool> {
        if !matches!(exit_code, Value::Null) && !py::is_int(exit_code) {
            return Err(Error::state("invalid exit code"));
        }
        let Value::Bool(restarted) = restarted else {
            return Err(Error::state("invalid restarted"));
        };
        let now = self.now(at)?;
        self.writing(|connection| {
            sql::exec(
                connection,
                "INSERT OR REPLACE INTO restarts (at, exit_code, restarted) VALUES (?,?,?)",
                &[float(now), exit_code.clone(), int(i64::from(*restarted))],
            )?;
            Ok(())
        })?;
        Ok(true)
    }

    /// `restarts_since(since)`: the rows since `since`, oldest first.
    pub fn restarts_since(&self, since: &Value) -> Result<Vec<Row>> {
        py::timestamp(since, "since")?;
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                "SELECT at, exit_code, restarted FROM restarts WHERE at >= ? ORDER BY at",
                &[float(py::float_of(since)?)],
            ),
        })
    }

    // ------------------------------------------------------------------ opens
    /// `opens(since)`: the opens at `since` or later, oldest first.
    pub fn opens(&self, since: &Value) -> Result<Vec<Row>> {
        let since = time_or_refuse(since)?;
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                "SELECT open_id, thread_id, record_id, at, outcome FROM opens WHERE at >= ? ORDER BY at, open_id",
                &[float(since)],
            ),
        })
    }

    /// `add_open(thread_id, record_id, at=None)`: an open about to be made, written first; its id.
    pub fn add_open(&self, thread_id: &Value, record_id: &Value, at: &Value) -> Result<i64> {
        py::thread(thread_id)?;
        py::key(record_id, "record id")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            sql::insert(
                connection,
                "INSERT INTO opens (thread_id, record_id, at, outcome) VALUES (?,?,?,?)",
                &[
                    thread_id.clone(),
                    record_id.clone(),
                    float(now),
                    string(OpenOutcome::Opened.as_str()),
                ],
            )
        })
    }

    /// `settle_open(open_id, outcome)`: what came of an open still `opened`.
    pub fn settle_open(&self, open_id: &Value, outcome: &Value) -> Result<bool> {
        if !py::is_int(open_id) {
            return Err(Error::state("invalid open id"));
        }
        let outcome = py::closed(outcome, OpenOutcome::ALL, "outcome")?;
        if !SETTLED.contains(&outcome) {
            return Err(Error::state("invalid outcome"));
        }
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE opens SET outcome=? WHERE open_id=? AND outcome=?",
                &[
                    string(outcome),
                    open_id.clone(),
                    string(OpenOutcome::Opened.as_str()),
                ],
            )? == 1),
        })
    }

    // ------------------------------------------------------------------ the account seen
    /// `account_seen()`: identity_digest, plan, read_at - or None.
    pub fn account_seen(&self) -> Result<Option<Row>> {
        self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                "SELECT identity_digest, plan, read_at FROM account_seen WHERE singleton=1",
                &[],
            ),
        })
    }

    /// `save_account_seen(identity_digest, plan, at=None)`.
    pub fn save_account_seen(
        &self,
        identity_digest: &Value,
        plan: &Value,
        at: &Value,
    ) -> Result<()> {
        if !digest16(identity_digest) {
            return Err(Error::state("invalid digest"));
        }
        if !matches!(plan, Value::Null) && !py::is_word(plan, PlanWord::ALL) {
            return Err(Error::state("invalid plan"));
        }
        let now = self.now(at)?;
        self.writing(|connection| {
            sql::exec(
                connection,
                "INSERT INTO account_seen (singleton, identity_digest, plan, read_at) VALUES (1,?,?,?) \
                 ON CONFLICT(singleton) DO UPDATE SET identity_digest=excluded.identity_digest, \
                 plan=excluded.plan, read_at=excluded.read_at",
                &[identity_digest.clone(), plan.clone(), float(now)],
            )?;
            Ok(())
        })
    }

    /// `end_account_seen()`: the row taken away; whether there was one.
    pub fn end_account_seen(&self) -> Result<bool> {
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(connection, "DELETE FROM account_seen", &[])? > 0),
        })
    }

    // ------------------------------------------------------------------ steers
    /// `steers(since=0.0)`: every steer asked at `since` or later, oldest first, with its words.
    pub fn steers(&self, since: &Value) -> Result<Vec<Row>> {
        let since = time_or_refuse(since)?;
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                &format!("SELECT {STEER_COLUMNS} FROM steers WHERE created_at >= ? ORDER BY created_at, steer_id"),
                &[float(since)],
            ),
        })
    }

    /// `waiting_steers()`: requested or sending, oldest first.
    pub fn waiting_steers(&self) -> Result<Vec<Row>> {
        self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                &format!("SELECT {STEER_COLUMNS} FROM steers WHERE state IN (?, ?) ORDER BY created_at, steer_id"),
                &sql::words(STEER_WAITING),
            ),
        })
    }

    /// `add_steer(thread_id, words, client_id, at=None, bounds=None)`: a steer asked for; its id.
    pub fn add_steer(
        &self,
        thread_id: &Value,
        words: &Value,
        client_id: &Value,
        at: &Value,
        bounds: &Value,
    ) -> Result<i64> {
        py::thread(thread_id)?;
        let fits = match words {
            Value::Str(text) => !blank(text) && text.len() as i64 <= STEER_WORDS,
            _ => false,
        };
        if !fits {
            return Err(Error::state("invalid words"));
        }
        let now = self.now(at)?;
        self.writing(|connection| {
            if !matches!(bounds, Value::Null) {
                let parts = super::arming::iterate(bounds)?;
                if parts.len() != 3 {
                    return Err(Error::python("ValueError", "wrong number of values to unpack"));
                }
                let day = py::minus_operand(&parts[0])?;
                let since = (now - day).max(0.0);
                let mut parameters = vec![float(since), thread_id.clone()];
                parameters.extend(sql::words(STEER_WAITING));
                if sql::exists(
                    connection,
                    "SELECT 1 FROM steers WHERE created_at >= ? AND thread_id = ? AND state IN (?, ?)",
                    &parameters,
                )? {
                    return Err(Error::steer_refused("being_sent"));
                }
                let row = sql::first(
                    connection,
                    "SELECT count(*), coalesce(sum(thread_id = ?), 0) FROM steers WHERE created_at >= ?",
                    &[thread_id.clone(), float(since)],
                )?
                .unwrap_or_default();
                let total = row.first().cloned().unwrap_or(Value::Null);
                let mine = row.get(1).cloned().unwrap_or(Value::Null);
                let at_least = |a: &Value, b: &Value| {
                    car_machine::pyval::less_or_equal(b, a).map_err(|class| Error::python(class, "'>='"))
                };
                if at_least(&total, &parts[1])? || at_least(&mine, &parts[2])? {
                    return Err(Error::steer_refused("queue_full"));
                }
            }
            let client_id = client(client_id)?;
            sql::insert(
                connection,
                "INSERT INTO steers (thread_id, words, client_id, state, created_at) VALUES (?,?,?,?,?)",
                &[
                    thread_id.clone(),
                    words.clone(),
                    client_id,
                    string(SteerState::Requested.as_str()),
                    float(now),
                ],
            )
        })
    }

    /// `claim_steer(steer_id)`: `requested -> sending`, true only for the one call that moved it.
    pub fn claim_steer(&self, steer_id: &Value) -> Result<bool> {
        if !py::is_int(steer_id) {
            return Err(Error::state("invalid steer id"));
        }
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE steers SET state=? WHERE steer_id=? AND state=?",
                &[
                    string(SteerState::Sending.as_str()),
                    steer_id.clone(),
                    string(SteerState::Requested.as_str()),
                ],
            )? == 1),
        })
    }

    /// `settle_steer(steer_id, state, reason=None, at=None)`.
    pub fn settle_steer(
        &self,
        steer_id: &Value,
        state: &Value,
        reason: &Value,
        at: &Value,
    ) -> Result<bool> {
        if !py::is_int(steer_id) {
            return Err(Error::state("invalid steer id"));
        }
        let state = py::closed(state, SteerState::ALL, "state")?;
        if !STEER_SETTLED.contains(&state) {
            return Err(Error::state("invalid state"));
        }
        let (reason, before) = if state == SteerState::Refused.as_str() {
            (
                string(py::closed(reason, SteerReason::ALL, "reason")?),
                STEER_WAITING.to_vec(),
            )
        } else {
            if !matches!(reason, Value::Null) {
                return Err(Error::state("only a refusal has a reason"));
            }
            (
                Value::Null,
                vec![SteerState::Sending.as_str(), SteerState::Sending.as_str()],
            )
        };
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let mut parameters = vec![string(state), reason.clone(), float(now), steer_id.clone()];
            parameters.extend(sql::words(&before));
            Ok(sql::exec(
                connection,
                "UPDATE steers SET state=?, reason=?, finished_at=? WHERE steer_id=? AND state IN (?, ?)",
                &parameters,
            )? == 1)
        })
    }

    /// `end_requested_steers(reason, at=None)`: every steer still `requested` refused; how many.
    pub fn end_requested_steers(&self, reason: &Value, at: &Value) -> Result<i64> {
        let reason = py::closed(reason, SteerReason::ALL, "reason")?;
        let now = self.now(at)?;
        self.transaction(false, |connection| match connection {
            None => Ok(0),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE steers SET state=?, reason=?, finished_at=? WHERE state=?",
                &[
                    string(SteerState::Refused.as_str()),
                    string(reason),
                    float(now),
                    string(SteerState::Requested.as_str()),
                ],
            )? as i64),
        })
    }

    /// `settle_cut_short(at=None)`: every steer left `sending` settled unconfirmed; how many.
    pub fn settle_cut_short(&self, at: &Value) -> Result<i64> {
        let now = self.now(at)?;
        self.transaction(false, |connection| match connection {
            None => Ok(0),
            Some(connection) => Ok(sql::exec(
                connection,
                "UPDATE steers SET state=?, finished_at=? WHERE state=?",
                &[
                    string(SteerState::Unconfirmed.as_str()),
                    float(now),
                    string(SteerState::Sending.as_str()),
                ],
            )? as i64),
        })
    }
}

/// `steers.prune(connection, now, max_age, limit)`: the settled steers older than `max_age`, then the oldest settled
/// beyond `limit`; never one still waiting.
pub fn prune_steers(connection: &Connection, now: f64, max_age: f64, limit: i64) -> Result<()> {
    let settled = format!(
        "state NOT IN ('{}', '{}')",
        SteerState::Requested.as_str(),
        SteerState::Sending.as_str()
    );
    sql::exec(
        connection,
        &format!("DELETE FROM steers WHERE {settled} AND created_at < ?"),
        &[float(now - max_age)],
    )?;
    let excess = sql::number(connection, "SELECT count(*) FROM steers", &[])? - limit;
    if excess > 0 {
        sql::exec(
            connection,
            &format!(
                "DELETE FROM steers WHERE steer_id IN (SELECT steer_id FROM steers WHERE {settled} \
                 ORDER BY created_at, steer_id LIMIT ?)"
            ),
            &[int(excess)],
        )?;
    }
    Ok(())
}
