//! `codex/lineage.py`: which subagents a conversation spawned, and how each one's latest turn ended, read-only - never
//! what either says (seat S7.2c). A failed turn's error is classified by core (car-codex `values::normalize`) and dropped
//! to its category word at once.

use car_codex::sql::{self, Cell, Param};
use car_machine::domain::ids;
use car_machine::json::{Map, Value};

use super::turns::{Failure, Read, SharedOs, connect, thread_id_text, unavailable};

pub const EDGE_COLUMNS: &[&str] = &["parent_thread_id", "child_thread_id", "status"];
pub const CHILDREN: &str = "SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=? ORDER BY rowid LIMIT ?";
pub const CHILD_TURN: &str = "SELECT thread_id, turn_id, status, error_json, started_at, completed_at, rollout_ordinal FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal DESC LIMIT 1";
pub const STATEMENTS: [&str; 2] = [CHILDREN, CHILD_TURN];
pub const TURN_COLUMNS: &[&str] = &[
    "thread_id",
    "turn_id",
    "status",
    "error_json",
    "started_at",
    "completed_at",
    "rollout_ordinal",
];
pub const CHILDREN_LIMIT: i64 = 20;

/// One subagent: its id, its latest turn, that turn's status and a failed one's category word.
#[derive(Clone, Debug, PartialEq)]
pub struct Child {
    pub thread_id: String,
    pub turn_id: Value,
    pub status: Value,
    pub category: Value,
}

/// The spawn edges and the children's latest turns of the Codex home `home`.
pub struct Lineage {
    pub home: String,
    pub os: SharedOs,
}

impl Lineage {
    /// `children(parent)`: the subagents `parent` spawned, oldest first, at most CHILDREN_LIMIT.
    pub fn children(&self, parent: &Value) -> Read<Vec<Child>> {
        if !ids::is_uuid(parent) {
            return Err(unavailable("not a conversation"));
        }
        let parent = thread_id_text(parent);
        let connection = connect(
            self.os.as_ref(),
            &self.home,
            "state",
            &[("thread_spawn_edges", EDGE_COLUMNS)],
        )?;
        let rows = sql::query(
            &connection,
            CHILDREN,
            &[Param::Text(&parent), Param::Int(CHILDREN_LIMIT)],
        )
        .map_err(|_| unavailable("the spawn edges cannot be read"))?;
        drop(connection);
        let found: Vec<String> = rows
            .iter()
            .map(|row| row.at(0).value())
            .filter(|child| ids::is_uuid(child) && thread_id_text(child) != parent)
            .map(|child| thread_id_text(&child))
            .collect();
        if found.is_empty() {
            return Ok(Vec::new());
        }
        let connection = connect(
            self.os.as_ref(),
            &self.home,
            "history",
            &[("thread_turns", TURN_COLUMNS)],
        )?;
        let failed = |_| unavailable("the turn history cannot be read");
        let mut children = Vec::new();
        for child in found {
            let none = |child: &str| Child {
                thread_id: child.to_owned(),
                turn_id: Value::Null,
                status: Value::Null,
                category: Value::Null,
            };
            let Some(row) =
                sql::first(&connection, CHILD_TURN, &[Param::Text(&child)]).map_err(failed)?
            else {
                children.push(none(&child));
                continue;
            };
            let names = [
                "thread_id",
                "turn_id",
                "status",
                "error_json",
                "started_at",
                "completed_at",
                "rollout_ordinal",
            ];
            let mut dict = Map::new();
            for (index, name) in names.iter().enumerate() {
                dict.insert((*name).into(), cell_value(row.at(index)));
            }
            let turn =
                car_codex::values::normalize(&Value::Object(dict)).map_err(
                    |class| match class {
                        "ValueError" => unavailable("the turn history cannot be read"),
                        other => Failure::Raised(other),
                    },
                )?;
            match turn {
                None => children.push(none(&child)),
                Some(turn) => children.push(Child {
                    thread_id: child,
                    turn_id: turn.get("turn_id").cloned().unwrap_or(Value::Null),
                    status: turn.get("status").cloned().unwrap_or(Value::Null),
                    category: turn.get("category").cloned().unwrap_or(Value::Null),
                }),
            }
        }
        Ok(children)
    }
}

fn cell_value(cell: &Cell) -> Value {
    cell.value()
}
