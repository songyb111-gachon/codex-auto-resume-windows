//! Continue inside the turn (`stop_hook_continuation`): the claim the Stop hook shares with the watcher, and the capability's
//! answers at P3 and P8 (`engine/hookclaims.py`).
//!
//! The hook runs in a process Codex starts, not in the watcher, so it cannot be asked through core's claim. It claims in the
//! same file and under the same lock instead: core's `state.sqlite` with this edition's state attached, in one `BEGIN
//! IMMEDIATE` - exactly the transaction core's own claim takes, with the claim ledger's file attached there too. Whichever
//! begins first is the one that takes the failure: the watcher first - its claim has moved core's record past waiting, which
//! the hook reads, and the hook passes (a `passed` row); the hook first - its `blocked` row stands under the interruption id
//! core derives from the same turn, and core is held twice: at P3, by this capability's gate, for [`HOLD_SECONDS`], and at P11,
//! inside core's claim, by the ledger ([`held`]), whatever the capability's state.
//!
//! The hook's continuation is a continuation like any other to the caps on one conversation (standard A20): one unit of this
//! capability's is spent with its claim, and the ledger counts those units beside core's own claims and this edition's
//! records ([`spent_on`]). Once a turn: a turn that has had a block is refused another, under any interruption id.
//!
//! What holds core's own sends back holds the hook's too: an administrator's DisableAutoResume or ForceObserveOnly, Observe
//! only and quiet hours from the settings file and the policy keys (`policy`: nothing is written, the hook passes), and, on
//! core's record of the interruption where there is one, its consent and budget gates.
//!
//! SEAT S7.3c. `held` and `spent_on` are moved here from `state/seam/hooks.rs` (which re-exports them); the administrator's
//! policy keys are the seam [`World::managed`] (`control/policy.managed_policy`, read from the registry by car-control's host).
//! `StopHook` (P3's gate, P8's `tick`) is the plug-side half: it asks the plug trait of S7.2a and is not here; what it calls is
//! [`blocked_at`] and `hookplugin::follow`.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use car_codex::system::PolicyOs;
use car_config::Paths;
use car_machine::domain::ids;
use car_machine::json::{Map, Value};
use car_machine::localclock::LocalClock;
use car_machine::pyval;
use car_machine::vocab_gen::domain_states::{TERMINAL, WAITING};
use car_policy::classify::gates::{self, Limits, PASS};
use car_policy::classify::{ladder, quiet};
use car_policy::settings::config::{Home, load_settings};
use car_policy::settings::managed::{self, Managed};
use rusqlite::Connection;

use crate::ledger::{ceiling_reached, held_by_records};
use crate::registry::{CORE_COOLDOWN_SECONDS, CORE_DAILY_CAP, Registry};
use crate::state::errors::{Error, Result};
use crate::state::records::own_paced;
use crate::state::schema::ATTACHED;
use crate::state::seam::Tokens;
use crate::state::{AdvancedState, py, spend, sql};
use crate::vocabulary::{ArmingState, HookOutcome};

pub const CAPABILITY: &str = "stop_hook_continuation";
pub const DAY: f64 = 86400.0;
/// How long a block holds core back from the same interruption: core's own spacing between two claims on one conversation.
pub const HOLD_SECONDS: f64 = 900.0;
/// How long the hook waits for the claim's lock before it passes.
pub const BUSY_SECONDS: f64 = 0.5;
pub const CORE_FILE: &str = "state.sqlite";

/// What the claim reads of the machine: the administrator's policy keys, the local clock quiet hours are read by, and the
/// advanced state's randomness (`secrets`).
pub struct World<'a> {
    /// `control/policy.managed_policy()`: `Err` where it cannot be had.
    pub managed: &'a dyn Fn() -> Result<Managed>,
    pub clock: &'a dyn LocalClock,
    pub tokens: Arc<dyn Tokens>,
}

/// `held(connection, schema, interruption_id, now)`: P11, inside core's claim with this edition's file attached as `schema`:
/// whether the hook blocked the turn of `interruption_id` within HOLD_SECONDS - then core's claim of it is held, whatever the
/// capability's state.
pub fn held(
    connection: &Connection,
    schema: &str,
    interruption_id: &Value,
    now: f64,
) -> Result<bool> {
    let row = sql::first(
        connection,
        &format!("SELECT at FROM {schema}.hook_claims WHERE interruption_id=? AND outcome=?"),
        &[
            interruption_id.clone(),
            py::word(HookOutcome::Blocked.as_str()),
        ],
    )?;
    Ok(match row {
        None => false,
        Some(values) => match py::as_f64(&values[0]) {
            Some(at) => (0.0..HOLD_SECONDS).contains(&(now - at)),
            None if matches!(values[0], Value::Null) => {
                return Err(Error::type_error(
                    "unsupported operand type(s) for -: 'float' and 'NoneType'",
                ));
            }
            None => return Err(Error::type_error("unsupported operand type(s) for -")),
        },
    })
}

/// `spent_on(connection, schema, thread_id, now)`: (the hook's continuations in `thread_id` in the last day, when the latest
/// was or None): what the caps on one conversation count of it, beside core's claims and this edition's records.
pub fn spent_on(
    connection: &Connection,
    schema: &str,
    thread_id: &Value,
    now: f64,
) -> Result<(i64, Value)> {
    let row = sql::first(
        connection,
        &format!("SELECT count(*), max(at) FROM {schema}.spend WHERE capability=? AND thread_id=? AND at>?"),
        &[py::word(CAPABILITY), thread_id.clone(), sql::float(now - DAY)],
    )?
    .unwrap_or_default();
    let count = row.first().and_then(py::small).unwrap_or(0);
    Ok((count, row.get(1).cloned().unwrap_or(Value::Null)))
}

fn readable(path: &Path) -> bool {
    path.is_file()
        && !car_config::paths::is_link(&path.to_string_lossy())
        && !path
            .parent()
            .is_some_and(|parent| car_config::paths::is_link(&parent.to_string_lossy()))
}

/// `blocked_at(paths, interruption_id)`: when the hook blocked the turn of `interruption_id`, or None: read-only, from this
/// edition's state as it stands on disk, with nothing made, migrated or written.
pub fn blocked_at(paths: &Paths, interruption_id: &Value) -> Option<f64> {
    if !ids::is_interruption_id(interruption_id, false) {
        return None;
    }
    let path = Path::new(&paths.advanced_dir).join(crate::state::schema::FILE_NAME);
    if !readable(&path) {
        return None;
    }
    let connection =
        Connection::open_with_flags(&path, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).ok()?;
    connection.busy_timeout(Duration::from_secs(1)).ok()?;
    let row = sql::first(
        &connection,
        "SELECT at FROM hook_claims WHERE interruption_id=? AND outcome=?",
        &[
            interruption_id.clone(),
            py::word(HookOutcome::Blocked.as_str()),
        ],
    )
    .ok()??;
    match row.first() {
        Some(Value::Int(_) | Value::Float(_)) => py::as_f64(&row[0]),
        _ => None,
    }
}

/// `_core_holds(connection, thread_id, now, registry)`: core's own caps on one conversation, read on its file: a record of its
/// in flight there, a claim within its spacing, or five in the day once the hook's units and this edition's records are counted
/// with them.
fn core_holds(
    connection: &Connection,
    thread_id: &Value,
    now: f64,
    registry: &Registry,
) -> Result<bool> {
    let rows = sql::tuples(
        connection,
        "SELECT state, max(attempt_count, 1), coalesce(submitted_at, last_claim_at) FROM main.interruptions WHERE thread_id=?",
        std::slice::from_ref(thread_id),
    )?;
    let settled = |state: &Value| {
        pyval::text(state).is_some_and(|word| WAITING.contains(&word) || TERMINAL.contains(&word))
    };
    if rows.iter().any(|row| !settled(&row[0])) {
        return Ok(true);
    }
    let recent: Vec<&Vec<Value>> = rows
        .iter()
        .filter(|row| {
            matches!(row[2], Value::Int(_) | Value::Float(_))
                && py::as_f64(&row[2]).is_some_and(|at| at > now - DAY)
        })
        .collect();
    if recent
        .iter()
        .any(|row| py::as_f64(&row[2]).is_some_and(|at| now - at < CORE_COOLDOWN_SECONDS as f64))
    {
        return Ok(true);
    }
    let (hooks, _last) = spent_on(connection, ATTACHED, thread_id, now)?;
    let attempts: i64 = recent
        .iter()
        .map(|row| py::small(&row[1]).unwrap_or(0))
        .sum();
    if attempts + hooks >= CORE_DAILY_CAP {
        return Ok(true);
    }
    held_by_records(
        connection,
        thread_id,
        now,
        &own_paced(registry),
        CORE_DAILY_CAP,
    )
}

struct SettingsHome<'a>(&'a Paths);

impl Home for SettingsHome<'_> {
    fn settings_file(&self) -> PathBuf {
        PathBuf::from(&self.0.settings_file)
    }
    fn ensure(&self) -> std::result::Result<(), car_policy::settings::config::ConfigFailure> {
        Ok(())
    }
}

/// `_policy(paths, now)`: core's budget limits as its engine adopts them (the settings file clamped by an administrator's
/// policy keys), or None where nothing may be sent now - an administrator's DisableAutoResume or ForceObserveOnly, Observe
/// only, or quiet hours, a person's own or an administrator's - or where either cannot be read.
pub fn policy(paths: &Paths, now: f64, world: &World<'_>) -> Option<Limits> {
    let held = (world.managed)().ok()?;
    let os = PolicyOs;
    let loaded = load_settings(&os, &SettingsHome(paths)).ok()?;
    let own = car_policy::settings::coerce(&os, &Value::Object(loaded));
    let values = managed::clamp(&own, &held);
    let observe = values.get("observe_only").is_some_and(pyval::truthy);
    if held.disable_auto_resume || held.force_observe_only || observe {
        return None;
    }
    let own_value = Value::Object(own.clone());
    let values_value = Value::Object(values.clone());
    let sources = if held.quiet_hours.is_empty() {
        vec![values_value.clone()]
    } else {
        managed::quiet_sources(&own_value, &held)
    };
    let now_value = Value::Float(now);
    for source in &sources {
        match quiet::quiet_until(&now_value, source, world.clock) {
            Ok(None) => {}
            _ => return None,
        }
    }
    let number = |name: &str| -> Option<f64> {
        match values.get(name)? {
            Value::Int(each) => each.as_i64().map(|n| n as f64),
            Value::Float(each) => Some(*each),
            _ => None,
        }
    };
    Some(Limits {
        max_no_progress: number("max_no_progress")?,
        max_chain_continuations: number("max_chain_continuations")?,
        max_recovery_attempts: number("max_recovery_attempts")?,
        max_chain_seconds: ladder::ceiling(&values_value).map(|seconds| seconds as f64),
        managed_max_recovery_attempts: None,
    })
}

/// `_core_refuses(connection, key, limits, now)`: whether core's own record of the interruption, where there is one, refuses a
/// continuation now: its consent gate (a Cancel, a hold for a person), a postponement still to come, or its budgets.
fn core_refuses(connection: &Connection, key: &Value, limits: &Limits, now: f64) -> Result<bool> {
    let rows = sql::all(
        connection,
        "SELECT * FROM main.interruptions WHERE interruption_id=?",
        std::slice::from_ref(key),
    )?;
    let Some(row) = rows.into_iter().next() else {
        return Ok(false);
    };
    let get = |name: &str| row.get(name).cloned().unwrap_or(Value::Null);
    let consent = gates::gate_consent(
        true,
        true,
        pyval::truthy(&get("cancel_requested")),
        false,
        &get("hold"),
    );
    if consent.0 != PASS {
        return Ok(true);
    }
    if matches!(get("not_before"), Value::Int(_) | Value::Float(_))
        && py::as_f64(&get("not_before")).is_some_and(|until| until > now)
    {
        return Ok(true);
    }
    let usage = pyval::is(&get("category"), "usage_limit");
    Ok(gates::gate_budgets(&row, limits, usage)
        .iter()
        .any(|(_, answer)| answer.0 != PASS))
}

/// `_decide(...)`: the outcome to write, inside the claim's transaction, or None for nothing written.
#[allow(clippy::too_many_arguments)]
fn decide(
    connection: &Connection,
    state: &AdvancedState,
    definition: &crate::registry::CapabilityDef,
    key: &Value,
    thread: &Value,
    turn_key: &Value,
    now: f64,
    limits: &Limits,
) -> Result<Option<HookOutcome>> {
    let settings = sql::first(
        connection,
        "SELECT enabled, observe_only FROM main.settings",
        &[],
    )?;
    match settings {
        Some(row) if sql::truthy(&row[0]) && !sql::truthy(&row[1]) => {}
        _ => return Ok(None),
    }
    if let Some(on) = sql::first(
        connection,
        "SELECT enabled FROM main.threads WHERE thread_id=?",
        std::slice::from_ref(thread),
    )? && !sql::truthy(&on[0])
    {
        return Ok(None);
    }
    if sql::exists(
        connection,
        &format!("SELECT 1 FROM {ATTACHED}.hook_claims WHERE interruption_id=?"),
        std::slice::from_ref(key),
    )? {
        return Ok(None);
    }
    let armed = sql::first(
        connection,
        &format!("SELECT state FROM {ATTACHED}.arming WHERE capability=?"),
        &[py::word(CAPABILITY)],
    )?;
    if !armed.is_some_and(|row| pyval::is(&row[0], ArmingState::Armed.as_str())) {
        return Ok(None);
    }
    if sql::exists(
        connection,
        &format!("SELECT 1 FROM {ATTACHED}.hook_claims WHERE turn_digest=? AND outcome=?"),
        &[turn_key.clone(), py::word(HookOutcome::Blocked.as_str())],
    )? {
        return Ok(Some(HookOutcome::Refused));
    }
    let core = sql::first(
        connection,
        "SELECT state FROM main.interruptions WHERE interruption_id=?",
        std::slice::from_ref(key),
    )?;
    if let Some(row) = core
        && !pyval::text(&row[0]).is_some_and(|word| WAITING.contains(&word))
    {
        return Ok(Some(HookOutcome::Passed));
    }
    if core_refuses(connection, key, limits, now)? {
        return Ok(Some(HookOutcome::Refused));
    }
    if core_holds(connection, thread, now, &state.registry)? {
        return Ok(Some(HookOutcome::Refused));
    }
    let hourly = sql::scalar(
        connection,
        &format!("SELECT global_hourly FROM {ATTACHED}.meta"),
        &[],
    )?;
    let counts = spend::counts(
        connection,
        ATTACHED,
        &py::word(CAPABILITY),
        thread,
        now,
        &[],
    )?;
    if ceiling_reached(&counts, definition, &hourly, false)?.is_some() {
        return Ok(Some(HookOutcome::Refused));
    }
    Ok(Some(HookOutcome::Blocked))
}

/// `claim(paths, failure, turn_key, now, registry=, busy=)`: the hook's claim of `failure` - core's detection of the latest
/// turn, with its interruption id - for the turn digested as `turn_key`: the HookOutcome it wrote, or None where nothing was
/// written (recovery or the capability off, the state not there, the turn already answered, the lock not had in time). Only
/// BLOCKED lets the hook block.
///
/// One transaction on core's file with this edition's attached, BEGIN IMMEDIATE - core's claim's own lock - and nothing
/// written to core's file, ever.
pub fn claim(
    paths: &Paths,
    failure: &Map,
    turn_key: &str,
    now: f64,
    registry: &Arc<Registry>,
    busy: f64,
    world: &World<'_>,
) -> Option<HookOutcome> {
    let definition = registry.get(CAPABILITY)?;
    let key = failure
        .get("interruption_id")
        .cloned()
        .unwrap_or(Value::Null);
    let thread = failure.get("thread_id").cloned().unwrap_or(Value::Null);
    let core = Path::new(&paths.state_dir).join(CORE_FILE);
    if !ids::is_interruption_id(&key, false) || !readable(&core) {
        return None;
    }
    let limits = policy(paths, now, world)?;
    let state = AdvancedState::new(
        paths.clone(),
        Arc::clone(registry),
        Box::new(crate::state::session::wall_clock),
        Arc::clone(&world.tokens),
    );
    let outcome = (|| -> Result<Option<HookOutcome>> {
        let connection = Connection::open(&core)?;
        connection.busy_timeout(Duration::from_secs_f64(busy.max(0.0)))?;
        connection.execute_batch("PRAGMA trusted_schema=OFF")?;
        if !state.attach(&connection)? {
            return Ok(None);
        }
        connection.execute_batch("BEGIN IMMEDIATE")?;
        let inside = || -> Result<Option<HookOutcome>> {
            let digest = py::word(turn_key);
            let found = decide(
                &connection,
                &state,
                definition,
                &key,
                &thread,
                &digest,
                now,
                &limits,
            )?;
            if let Some(outcome) = found {
                sql::exec(
                    &connection,
                    &format!(
                        "INSERT INTO {ATTACHED}.hook_claims (interruption_id, turn_digest, at, outcome) VALUES (?,?,?,?)"
                    ),
                    &[
                        key.clone(),
                        digest,
                        sql::float(now),
                        py::word(outcome.as_str()),
                    ],
                )?;
                if outcome == HookOutcome::Blocked {
                    let at = spend::claim_time(&connection, ATTACHED, &key, &Value::Float(now))?;
                    state.record_spend(
                        &connection,
                        ATTACHED,
                        &py::word(CAPABILITY),
                        &thread,
                        &key,
                        &Value::Float(at),
                    )?;
                }
            }
            Ok(found)
        };
        match inside() {
            Ok(found) => {
                connection.execute_batch("COMMIT")?;
                Ok(found)
            }
            Err(error) => {
                let _ = connection.execute_batch("ROLLBACK");
                Err(error)
            }
        }
    })();
    state.close();
    outcome.ok().flatten()
}
