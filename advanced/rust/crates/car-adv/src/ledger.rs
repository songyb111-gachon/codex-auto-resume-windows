//! P11: the one claim, counted across both editions' records and paid for before it is granted (`ledger.py`).
//!
//! Core asks the plug's ledger last, inside its claim's `BEGIN IMMEDIATE` and on its connection, once every check of
//! core's own has passed (car-store's claim, the transaction rules of `store/claims.py`). The ledger ATTACHes
//! advanced.sqlite to that connection there, so everything below is read and written under the one lock the claim
//! already holds, and commits with the claim or not at all - core takes back what it wrote when it holds.
//!
//! HOLD is all this can say. It never grants anything core would refuse.

use car_machine::json::Value;
use car_policy::classify::ladder::RESET_PER_DAY;
use rusqlite::Connection;

use crate::registry::{CORE_COOLDOWN_SECONDS, CORE_DAILY_CAP, CapabilityDef};
use crate::state::ask::{DefinitionAsked, RegistryAsked};
use crate::state::errors::{Error, Result};
use crate::state::py;
use crate::state::records::{not_among, own_paced};
use crate::state::schema::ATTACHED;
use crate::state::seam::hooks;
use crate::state::session::AdvancedState;
use crate::state::spend;
use crate::state::sql::{self, Row, float, int, py_eq, string};
use crate::vocabulary::{ArmingState, Ceiling, KeepOn, OverrideKind, RecordState, RuleState};

pub const DAY: f64 = 86400.0;

/// What the ledger answers: HOLD, or DEFER (core decides, as if there were no plug).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Answer {
    Hold,
    Defer,
}

impl Answer {
    /// The reference's word for it (`Alternative.HOLD`, and `repr(DEFER)` as the harness writes it).
    pub fn word(self) -> &'static str {
        match self {
            Answer::Hold => "hold",
            Answer::Defer => "DEFER",
        }
    }
}

/// `ceiling_reached(counts, definition, global_hourly, verified=False)`: the ceiling that leaves `definition` no
/// unit, or None - the global one first.
pub fn ceiling_reached(
    counts: &Row,
    definition: &CapabilityDef,
    global_hourly: &Value,
    verified: bool,
) -> Result<Option<&'static str>> {
    let at_least = |name: &str, limit: &Value| -> Result<bool> {
        car_machine::pyval::less_or_equal(limit, sql::get(counts, name))
            .map_err(|class| Error::python(class, "'>='"))
    };
    if at_least("global_hour", global_hourly)? {
        return Ok(Some(Ceiling::GlobalHour.as_str()));
    }
    let Some(ceilings) = definition.ceilings else {
        return Err(Error::python(
            "AttributeError",
            "'NoneType' object has no attribute 'per_day'",
        ));
    };
    if at_least("capability_day", &int(ceilings.per_day))? {
        return Ok(Some(Ceiling::CapabilityDay.as_str()));
    }
    if at_least("conversation_day", &int(ceilings.per_conversation))?
        && !(verified && definition.departs("A20"))
    {
        return Ok(Some(Ceiling::ConversationDay.as_str()));
    }
    Ok(None)
}

/// `core_claims(connection, thread_id, now)`: core's count of the conversation's claims in the last day.
pub fn core_claims(connection: &Connection, thread_id: &Value, now: f64) -> Result<Value> {
    sql::scalar(
        connection,
        "SELECT coalesce(sum(max(attempt_count, 1)), 0) FROM main.interruptions \
         WHERE thread_id=? AND coalesce(submitted_at, last_claim_at) > ?",
        &[thread_id.clone(), float(now - DAY)],
    )
}

fn plus(a: &Value, b: &Value) -> Result<Value> {
    match (py::as_f64(a), py::as_f64(b)) {
        (Some(x), Some(y)) => Ok(match (a, b) {
            (Value::Int(_), Value::Int(_)) => int((x + y) as i64),
            _ => Value::Float(x + y),
        }),
        _ => Err(Error::type_error("unsupported operand type(s) for +")),
    }
}

/// `held_by_records(connection, thread_id, now, own=(), cap=CORE_DAILY_CAP)`: whether this edition's records on
/// `thread_id`, and the Stop hook's continuations there, hold a claim core's own rows allow.
pub fn held_by_records(
    connection: &Connection,
    thread_id: &Value,
    now: f64,
    own: &[&str],
    cap: i64,
) -> Result<bool> {
    let (hooks, hooked) = hooks::spent_on(connection, ATTACHED, thread_id, now)?;
    let mut parameters = vec![string(RecordState::InFlight.as_str()), float(now - DAY)];
    parameters.extend(own.iter().map(|id| string(id)));
    parameters.extend(own.iter().map(|id| string(id)));
    parameters.push(thread_id.clone());
    let row = sql::first(
        connection,
        &format!(
            "SELECT coalesce(sum(state=?), 0), \
             coalesce(sum(CASE WHEN claimed_at > ? AND {among} THEN max(claims, 1) ELSE 0 END), 0), \
             max(CASE WHEN {among} THEN claimed_at END) FROM {ATTACHED}.records WHERE thread_id=?",
            among = not_among(own)
        ),
        &parameters,
    )?
    .unwrap_or_default();
    let in_flight = row.first().cloned().unwrap_or(Value::Null);
    if sql::truthy(&in_flight) {
        return Ok(true);
    }
    let recent = plus(row.get(1).unwrap_or(&int(0)), &int(hooks))?;
    let mut last = row.get(2).cloned().unwrap_or(Value::Null);
    let later = |a: &Value, b: &Value| -> Result<bool> {
        car_machine::pyval::greater(a, b).map_err(|class| Error::python(class, "'>'"))
    };
    if matches!(last, Value::Null) || (!matches!(hooked, Value::Null) && later(&hooked, &last)?) {
        last = hooked;
    }
    if sql::truthy(&recent) {
        let total = plus(&core_claims(connection, thread_id, now)?, &recent)?;
        if car_machine::pyval::less_or_equal(&int(cap), &total)
            .map_err(|class| Error::python(class, "'>='"))?
        {
            return Ok(true);
        }
    }
    Ok(match last {
        Value::Null => false,
        last => now - py::minus_operand(&last)? < CORE_COOLDOWN_SECONDS as f64,
    })
}

/// The claim ledger of one advanced state (`ClaimLedger`).
pub struct ClaimLedger<'a> {
    pub state: &'a AdvancedState,
}

/// `acted` as `claim` reads it: {capability: the words it answered}.
fn acted_of(acted: &Value) -> Result<Vec<(Value, Vec<Value>)>> {
    match acted {
        Value::Object(map) => Ok(map
            .iter()
            .map(|(capability, words)| {
                let words = match words {
                    Value::Array(words) => words.clone(),
                    _ => Vec::new(),
                };
                (Value::Str(capability.clone()), words)
            })
            .collect()),
        other => Ok(crate::state::arming::iterate(other)?
            .into_iter()
            .map(|capability| (capability, Vec::new()))
            .collect()),
    }
}

fn answered(words: &[Value], word: &str) -> bool {
    words.iter().any(|each| py::is_word(each, &[word]))
}

impl ClaimLedger<'_> {
    /// `claim(connection, record, now, acted=(), verified=frozenset(), unvouched=False)`: HOLD or DEFER for one claim
    /// of core's.
    pub fn claim(
        &self,
        connection: &Connection,
        record: &Value,
        now: f64,
        acted: &Value,
        verified: &Value,
        unvouched: bool,
    ) -> Result<Answer> {
        let mut acted = acted_of(acted)?;
        let verified: Vec<Value> = match verified {
            Value::Null => Vec::new(),
            other => crate::state::arming::iterate(other)?,
        };
        let Value::Object(fields) = record else {
            return Ok(if acted.is_empty() {
                Answer::Defer
            } else {
                Answer::Hold
            });
        };
        if !self.state.attach(connection)? {
            return Ok(if acted.is_empty() {
                Answer::Defer
            } else {
                Answer::Hold
            });
        }
        let field = |name: &str| fields.get(name).cloned().unwrap_or(Value::Null);
        let (thread_id, key) = (field("thread_id"), field("interruption_id"));
        if hooks::held(connection, ATTACHED, &key, now)? {
            return Ok(Answer::Hold);
        }
        let own = own_paced(self.state.registry.as_ref());
        let cap = if verified.is_empty() {
            CORE_DAILY_CAP
        } else {
            RESET_PER_DAY
        };
        if held_by_records(connection, &thread_id, now, &own, cap)? {
            return Ok(Answer::Hold);
        }
        if unvouched
            && car_machine::pyval::less_or_equal(
                &int(CORE_DAILY_CAP),
                &core_claims(connection, &thread_id, now)?,
            )
            .map_err(|class| Error::python(class, "'>='"))?
        {
            return Ok(Answer::Hold);
        }
        if acted.is_empty() {
            return Ok(Answer::Defer);
        }
        let global_hourly = sql::scalar(
            connection,
            &format!("SELECT global_hourly FROM {ATTACHED}.meta"),
            &[],
        )?;
        let mut paid: Vec<i64> = Vec::new();
        let mut at: Option<f64> = None;
        acted.sort_by_key(|a| py::py_str(&a.0));
        for (capability, words) in &acted {
            let definition = self.state.registry.get_value(capability).cloned();
            let row = sql::first(
                connection,
                &format!("SELECT state, since FROM {ATTACHED}.arming WHERE capability=?"),
                std::slice::from_ref(capability),
            )?;
            let (Some(definition), Some(row)) = (definition, row) else {
                return Ok(Answer::Hold);
            };
            if !py_eq(&row[0], &string(ArmingState::Armed.as_str())) {
                return Ok(Answer::Hold);
            }
            let counts = spend::counts(connection, ATTACHED, capability, &thread_id, now, &paid)?;
            let is_verified = verified.iter().any(|each| py_eq(each, capability));
            if ceiling_reached(&counts, &definition, &global_hourly, is_verified)?.is_some() {
                return Ok(Answer::Hold);
            }
            if answered(words, "resend") && !resend(connection, &definition, &key, now)? {
                return Ok(Answer::Hold);
            }
            if answered(words, "send_now") && !sent_now(connection, capability, &key, &row[1], now)?
            {
                return Ok(Answer::Hold);
            }
            if answered(words, "queue_for_open") && !for_open(connection, &definition, &key, now)? {
                return Ok(Answer::Hold);
            }
            let time = match at {
                Some(time) => time,
                None => {
                    let time = spend::claim_time(connection, ATTACHED, &key, &float(now))?;
                    at = Some(time);
                    time
                }
            };
            paid.push(self.state.record_spend(
                connection,
                ATTACHED,
                capability,
                &thread_id,
                &key,
                &float(time),
            )?);
        }
        Ok(Answer::Defer)
    }

    /// `record(connection, record, now)`: P11 for a record of this edition's own - core's claim of it, or its launch.
    pub fn record(&self, connection: &Connection, record: &Value, now: f64) -> Result<Answer> {
        let Value::Object(fields) = record else {
            return Ok(Answer::Hold);
        };
        if !self.state.attach(connection)? {
            return Ok(Answer::Hold);
        }
        let field = |name: &str| fields.get(name).cloned().unwrap_or(Value::Null);
        let (key, phase) = (field("record_id"), field("phase"));
        let Some(found) = owned(connection, &key)? else {
            return Ok(Answer::Hold);
        };
        if !py_eq(&found.thread, &field("thread_id")) {
            return Ok(Answer::Hold);
        }
        let definition = self.state.registry.get_value(&found.capability).cloned();
        let armed = sql::first(
            connection,
            &format!("SELECT state FROM {ATTACHED}.arming WHERE capability=?"),
            std::slice::from_ref(&found.capability),
        )?;
        let (Some(definition), Some(armed)) = (definition, armed) else {
            return Ok(Answer::Hold);
        };
        if !py_eq(&armed[0], &string(ArmingState::Armed.as_str())) {
            return Ok(Answer::Hold);
        }
        if py::is_word(&phase, &["claim"]) {
            if !py_eq(&found.state, &string(RecordState::Waiting.as_str())) {
                return Ok(Answer::Hold);
            }
            let global_hourly = sql::scalar(
                connection,
                &format!("SELECT global_hourly FROM {ATTACHED}.meta"),
                &[],
            )?;
            let counts = spend::counts(
                connection,
                ATTACHED,
                &found.capability,
                &found.thread,
                now,
                &[],
            )?;
            if ceiling_reached(&counts, &definition, &global_hourly, false)?.is_some() {
                return Ok(Answer::Hold);
            }
            if !self
                .state
                .claim_record(connection, &key, &float(now), definition.departs("A20"))?
            {
                return Ok(Answer::Hold);
            }
            self.state.record_spend(
                connection,
                ATTACHED,
                &found.capability,
                &found.thread,
                &Value::Null,
                &float(now),
            )?;
            return Ok(Answer::Defer);
        }
        if py::is_word(&phase, &["launch"])
            && py_eq(&found.state, &string(RecordState::InFlight.as_str()))
        {
            sql::exec(
                connection,
                &found.launch.replace("%s", ATTACHED),
                &[float(now), found.row.clone()],
            )?;
            return Ok(Answer::Defer);
        }
        Ok(Answer::Hold)
    }
}

/// `_sent_now(connection, capability, key, since, now)`.
fn sent_now(
    connection: &Connection,
    capability: &Value,
    key: &Value,
    since: &Value,
    now: f64,
) -> Result<bool> {
    let found = sql::first(
        connection,
        &format!(
            "SELECT kind, created_at, used_at FROM {ATTACHED}.overrides WHERE interruption_id=? AND capability=?"
        ),
        &[key.clone(), capability.clone()],
    )?;
    let Some(found) = found else { return Ok(false) };
    if !crate::control::sendnow::fresh_columns(&found[0], &found[1], &found[2], since, now) {
        return Ok(false);
    }
    sql::exec(
        connection,
        &format!(
            "UPDATE {ATTACHED}.overrides SET used_at=? WHERE interruption_id=? AND capability=?"
        ),
        &[float(now), key.clone(), capability.clone()],
    )?;
    Ok(true)
}

/// `_resend(connection, definition, key, now)`.
fn resend(
    connection: &Connection,
    definition: &CapabilityDef,
    key: &Value,
    now: f64,
) -> Result<bool> {
    if !definition.resends {
        let kept: Vec<Value> = sql::tuples(
            connection,
            &format!("SELECT choice FROM {ATTACHED}.options WHERE capability=?"),
            &[string(&definition.id)],
        )?
        .into_iter()
        .filter_map(|row| row.into_iter().next())
        .collect();
        let has = |word: &str| kept.iter().any(|each| py::is_word(each, &[word]));
        if !(has(KeepOn::KeepOn.as_str()) && has(KeepOn::SendAgain.as_str())) {
            return Ok(false);
        }
    }
    if sql::exists(
        connection,
        &format!("SELECT 1 FROM {ATTACHED}.overrides WHERE interruption_id=? AND kind=?"),
        &[key.clone(), string(OverrideKind::ResendOnce.as_str())],
    )? {
        return Ok(false);
    }
    sql::exec(
        connection,
        &format!(
            "INSERT OR REPLACE INTO {ATTACHED}.overrides (interruption_id, capability, kind, created_at, used_at) \
             VALUES (?,?,?,?,NULL)"
        ),
        &[
            key.clone(),
            string(&definition.id),
            string(OverrideKind::ResendOnce.as_str()),
            float(now),
        ],
    )?;
    Ok(true)
}

/// `_for_open(connection, definition, key, now)`.
fn for_open(
    connection: &Connection,
    definition: &CapabilityDef,
    key: &Value,
    now: f64,
) -> Result<bool> {
    if sql::exists(
        connection,
        &format!("SELECT 1 FROM {ATTACHED}.overrides WHERE interruption_id=? AND capability=?"),
        &[key.clone(), string(&definition.id)],
    )? {
        return Ok(false);
    }
    sql::exec(
        connection,
        &format!(
            "INSERT INTO {ATTACHED}.overrides (interruption_id, capability, kind, created_at, used_at) \
             VALUES (?,?,?,?,NULL)"
        ),
        &[
            key.clone(),
            string(&definition.id),
            string(OverrideKind::QueueForOpen.as_str()),
            float(now),
        ],
    )?;
    Ok(true)
}

/// What `_owned` finds of a record of this edition's own still to be launched.
struct Owned {
    state: Value,
    capability: Value,
    thread: Value,
    row: Value,
    /// The statement that writes when its launch began, `%s` for the schema.
    launch: &'static str,
}

/// `_owned(connection, key)`: a message at a reset (its rule due, not launched), one of the edition's continuations
/// (not finished, not launched), a prompt's occurrence (ready, not launched) or a chat message (waiting, not sent).
fn owned(connection: &Connection, key: &Value) -> Result<Option<Owned>> {
    let joined = |table: &str,
                  alias: &str,
                  id: &str,
                  a: &str,
                  b: &str|
     -> Result<Option<Vec<Value>>> {
        sql::first(
            connection,
            &format!(
                "SELECT c.state, c.capability, c.thread_id, {alias}.{id}, {alias}.{a}, {alias}.{b} \
                 FROM {ATTACHED}.records c JOIN {ATTACHED}.{table} {alias} ON {alias}.record_id = c.record_id \
                 WHERE c.record_id=?"
            ),
            std::slice::from_ref(key),
        )
    };
    let make = |found: Vec<Value>, launch: &'static str| Owned {
        state: found[0].clone(),
        capability: found[1].clone(),
        thread: found[2].clone(),
        row: found[3].clone(),
        launch,
    };
    if let Some(found) = joined("reset_rules", "r", "rule_id", "state", "launching_at")? {
        if !py_eq(&found[4], &string(RuleState::Ready.as_str())) || !matches!(found[5], Value::Null)
        {
            return Ok(None);
        }
        return Ok(Some(make(
            found,
            "UPDATE %s.reset_rules SET launching_at=? WHERE rule_id=?",
        )));
    }
    if let Some(found) = joined(
        "continuations",
        "n",
        "answer_id",
        "finished_at",
        "launching_at",
    )? {
        if !matches!(found[4], Value::Null) || !matches!(found[5], Value::Null) {
            return Ok(None);
        }
        return Ok(Some(make(
            found,
            "UPDATE %s.continuations SET launching_at=? WHERE answer_id=?",
        )));
    }
    if let Some(found) = joined("prompts", "p", "prompt_id", "state", "launching_at")? {
        if !py_eq(&found[4], &string("ready")) || !matches!(found[5], Value::Null) {
            return Ok(None);
        }
        return Ok(Some(make(
            found,
            "UPDATE %s.prompts SET launching_at=? WHERE prompt_id=?",
        )));
    }
    if let Some(found) = joined("chat_messages", "m", "chat_id", "state", "sent_at")? {
        if !py_eq(&found[4], &string("waiting")) || !matches!(found[5], Value::Null) {
            return Ok(None);
        }
        return Ok(Some(make(
            found,
            "UPDATE %s.chat_messages SET sent_at=? WHERE chat_id=?",
        )));
    }
    Ok(None)
}
