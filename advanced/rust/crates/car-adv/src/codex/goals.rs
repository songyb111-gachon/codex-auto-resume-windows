//! `codex/goals.py`: Codex's goals database, read-only - which goal a conversation has, and its status; never what it
//! says (seat S7.2c). The newest `goals_<N>.sqlite` in the Codex home (N read as `int()` reads a Unicode digit), never a
//! link, its three columns required. Anything that goes wrong is `GoalsUnavailable` ([`Failure::Unavailable`]).

use std::path::Path;

use car_codex::paths::{child, parent_of, safe_path};
use car_codex::sql::{self, Cell, Param};
use car_config::winpath;
use car_machine::pytext::decimal_value;
use car_machine::json::Value;

use super::turns::{Failure, Read, SharedOs, raised, unavailable};
use crate::vocabulary::{GoalStatus, parse};

pub const TABLE: &str = "thread_goals";
pub const COLUMNS: &[&str] = &["thread_id", "goal_id", "status", "updated_at_ms"];
pub const SELECT: &str = "SELECT goal_id, status, updated_at_ms FROM thread_goals WHERE thread_id=?";
pub const MAX_GOAL_ID: usize = 128;

/// A conversation's goal: its id, its status, when it last changed.
#[derive(Clone, Debug, PartialEq)]
pub struct Goal {
    pub goal_id: String,
    pub status: GoalStatus,
    pub updated_at_ms: i64,
}

/// `PATTERN.fullmatch(name)`: `goals_(\d+)\.sqlite`, its number as `int()` reads it.
fn generation(name: &str) -> Option<u128> {
    let digits = name.strip_prefix("goals_")?.strip_suffix(".sqlite")?;
    if digits.is_empty() {
        return None;
    }
    digits.chars().try_fold(0u128, |sum, c| {
        decimal_value(c).map(|digit| sum.saturating_mul(10).saturating_add(u128::from(digit)))
    })
}

/// The goals database of the Codex home `home`.
pub struct Goals {
    /// `_safe_path(Path(home))`.
    pub home: String,
    pub os: SharedOs,
}

impl Goals {
    /// `Goals(home)`: the home resolved, or the class `_safe_path` raises.
    pub fn new(home: &str, os: SharedOs) -> Read<Goals> {
        let home = safe_path(os.as_ref(), home).map_err(raised)?;
        Ok(Goals { home, os })
    }

    /// `_path()`: the newest generation's file.
    fn path(&self) -> Read<String> {
        let entries = std::fs::read_dir(&self.home).map_err(|_| unavailable("the Codex home cannot be listed"))?;
        let mut best: Option<(u128, String)> = None;
        for entry in entries {
            let entry = entry.map_err(|_| unavailable("the Codex home cannot be listed"))?;
            let name = entry.file_name().to_string_lossy().into_owned();
            let Some(number) = generation(&name) else {
                continue;
            };
            let full = child(&self.home, &name);
            if Path::new(&full).is_file() && !car_platform::links::is_symlink(Path::new(&full)) {
                // `max` keeps the first of equals.
                if best.as_ref().is_none_or(|(held, _)| number > *held) {
                    best = Some((number, full));
                }
            }
        }
        let Some((_, path)) = best else {
            return Err(unavailable("no goals database"));
        };
        let path = safe_path(self.os.as_ref(), &path).map_err(raised)?;
        if !winpath::same_path(&parent_of(&path), &self.home) {
            return Err(unavailable("the goals database is outside the Codex home"));
        }
        Ok(path)
    }

    /// `read(thread_id)`: the goal of a conversation, or none where it has none.
    pub fn read(&self, thread_id: &Value) -> Read<Option<Goal>> {
        let cannot = || unavailable("the goals database cannot be read");
        let path = self.path()?;
        let connection = sql::connect(Path::new(&path)).map_err(|_| cannot())?;
        let found = sql::columns(&connection, TABLE).map_err(|_| cannot())?;
        if !COLUMNS.iter().all(|column| found.iter().any(|each| each == column)) {
            return Err(unavailable("the goals table has moved on"));
        }
        // Bound as Python's `sqlite3` binds a value: half a surrogate pair cannot be encoded (a ValueError) and a list or
        // a dict is no parameter (a sqlite3.Error), both caught; an int past 64 bits is the OverflowError it lets out.
        let parameter = match thread_id {
            Value::Str(id) => Param::Text(id.as_str().ok_or_else(cannot)?),
            Value::Int(number) => Param::Int(number.as_i64().ok_or(Failure::Raised("OverflowError"))?),
            Value::Bool(on) => Param::Int(i64::from(*on)),
            Value::Float(number) => Param::Real(*number),
            Value::Null => Param::Null,
            _ => return Err(cannot()),
        };
        let row = sql::first(&connection, SELECT, &[parameter]).map_err(|_| cannot())?;
        let Some(row) = row else {
            return Ok(None);
        };
        let shapeless = || unavailable("a goal of no shape this knows");
        let goal_id = match row.at(0) {
            Cell::Text(id) if !id.is_empty() && id.chars().count() <= MAX_GOAL_ID => id.clone(),
            _ => return Err(shapeless()),
        };
        let Cell::Int(updated) = row.at(2) else {
            return Err(shapeless());
        };
        let status = match row.at(1) {
            Cell::Text(word) => parse::<GoalStatus>(word),
            _ => None,
        }
        .ok_or_else(|| unavailable("a goal status this does not know"))?;
        Ok(Some(Goal {
            goal_id,
            status,
            updated_at_ms: *updated,
        }))
    }
}
