//! `compact_continue`'s code (seat S7.2e1; `engine/compact.py`): compact a full conversation, then continue (P17, P3,
//! P16, and P8 for its runs).
//!
//! P17 admits Codex's own `contextWindowExceeded` alone; P3 known_failure admits again while worth going on (under a
//! day since taken up, and no failed compaction after it); P3 thread_available holds until a compaction turn is the
//! latest; P16 - nothing holding it while Codex is closed - is the headless route in compact mode, then once compacted
//! its turn mode. Its seams are [`super::headless::RunWorld`]'s.

use std::collections::BTreeMap;

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Alternative, View};

use super::headless::{
    HOUR, RunWorld, SharedRoute, field, follow_up, interruption_key, is_text, key_text, unheld,
};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};

pub const CAPABILITY: &str = "compact_continue";
pub const KIND: &str = "terminal_invalid";
pub const CODE: &str = "contextWindowExceeded";
/// How long after it was taken up a full conversation is still continued, at most.
pub const GIVE_UP_SECONDS: f64 = 24.0 * HOUR;
/// The kinds a compaction turn leaves.
pub const COMPACTION_KINDS: [&str; 2] = ["contextCompaction", "reasoning"];

/// What `_compacted` found: True, False, "failed", or None (unreadable, or still running).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Compacted {
    Yes,
    No,
    Failed,
    Unknown,
}

/// `CompactContinue(paths, turns=..., session=..., follower=..., app_running=...)`.
pub struct CompactContinue {
    pub paths: Paths,
    binding: Option<Binding>,
    world: RunWorld,
    routes: BTreeMap<String, SharedRoute>,
}

impl CompactContinue {
    pub fn new(paths: Paths, world: RunWorld) -> CompactContinue {
        CompactContinue {
            paths,
            binding: None,
            world,
            routes: BTreeMap::new(),
        }
    }

    /// `_compacted(record)`: whether the latest turn after `record`'s failure is a compaction alone that completed.
    /// Err is the reference's TypeError (a record ordinal that cannot be compared with a turn's).
    fn compacted(&self, record: &Value) -> Result<Compacted, Raised> {
        let Ok(Some(latest)) = self.world.turns.latest(field(record, "thread_id")) else {
            return Ok(Compacted::Unknown);
        };
        let ordinal = field(record, "ordinal");
        let ordinal = if car_machine::pyval::truthy(ordinal) {
            ordinal.clone()
        } else {
            Value::from(0)
        };
        let theirs = Value::Int(
            car_machine::json::Int::parse(&latest.ordinal.to_string()).unwrap_or(0.into()),
        );
        match car_machine::pyval::order(&theirs, &ordinal) {
            Ok(Some(std::cmp::Ordering::Greater)) => {}
            Ok(Some(_)) => return Ok(Compacted::No),
            Ok(None) => {}
            Err(class) => return Err(Raised::new(class)),
        }
        let kinds: Vec<&str> = latest
            .kinds
            .iter()
            .filter(|(_, count)| *count != 0)
            .map(|(kind, _)| kind.as_str())
            .collect();
        if kinds.is_empty()
            || !kinds.iter().all(|kind| COMPACTION_KINDS.contains(kind))
            || !kinds.contains(&"contextCompaction")
        {
            return Ok(Compacted::No);
        }
        Ok(match latest.status.as_str() {
            "failed" => Compacted::Failed,
            "completed" => Compacted::Yes,
            "interrupted" => Compacted::No,
            _ => Compacted::Unknown,
        })
    }

    /// `_taken_at(record)`: when its admission row was made, or None.
    fn taken_at(&self, record: &Value) -> Value {
        let Some(binding) = &self.binding else {
            return Value::Null;
        };
        binding
            .with(
                |scoped| match scoped.admission(field(record, "interruption_id")) {
                    Ok(Some(row)) => row.get("created_at").cloned().unwrap_or(Value::Null),
                    _ => Value::Null,
                },
            )
            .unwrap_or(Value::Null)
    }

    fn follow(&mut self) -> Spoke {
        let routes: Vec<SharedRoute> = self.routes.values().cloned().collect();
        follow_up(
            self.binding.as_ref(),
            self.world.follows.as_ref(),
            CAPABILITY,
            &routes,
            None,
        );
        Ok(Said::Defer)
    }
}

/// `failure.get(name)`, raising AttributeError where `failure` is not a dict.
fn got<'a>(failure: &'a Value, name: &str) -> Result<&'a Value, Raised> {
    match failure {
        Value::Object(_) => Ok(field(failure, name)),
        _ => Err(Raised::new("AttributeError")),
    }
}

impl Code for CompactContinue {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P17: ADMIT for a full context window - Codex's contextWindowExceeded - and nothing else.
    fn admission(&mut self, failure: &Value) -> Spoke {
        if !is_text(got(failure, "category")?, KIND) || !is_text(got(failure, "code")?, CODE) {
            return Ok(Said::Defer);
        }
        Ok(Said::Word(Alternative::Admit))
    }

    /// P3: ADMIT again at known_failure while it is worth going on; at thread_available, HOLD until the person's
    /// /compact is the latest turn.
    fn gate(&mut self, name: &Value, record: &Value, _facts: &Value) -> Spoke {
        if !matches!(record, Value::Object(_)) || !is_text(field(record, "category"), KIND) {
            return Ok(Said::Defer);
        }
        if is_text(name, "known_failure") {
            let taken = self.taken_at(record);
            let now = self
                .binding
                .as_ref()
                .and_then(|binding| binding.with(|scoped| scoped.now()));
            let (Some(now), false) = (now, matches!(taken, Value::Null)) else {
                return Ok(Said::Defer);
            };
            let since =
                car_machine::pyval::minus(&Value::Float(now), &taken).map_err(Raised::new)?;
            if since >= GIVE_UP_SECONDS {
                return Ok(Said::Defer);
            }
            return Ok(if self.compacted(record)? == Compacted::Failed {
                Said::Defer
            } else {
                Said::Word(Alternative::Admit)
            });
        }
        if is_text(name, "thread_available") {
            return Ok(if self.compacted(record)? == Compacted::Yes {
                Said::Defer
            } else {
                Said::Word(Alternative::Hold)
            });
        }
        Ok(Said::Defer)
    }

    /// P16, nothing holding it while Codex is closed: compact it here, or - once compacted - continue it here.
    fn unloaded(&mut self, record: &Value) -> Spoke {
        let (key, valid) = interruption_key(record);
        if !unheld(record)
            || !is_text(field(record, "category"), KIND)
            || !valid
            || self.world.follows.live().is_some()
        {
            return Ok(Said::Defer);
        }
        let compacted = self.compacted(record)?;
        if matches!(compacted, Compacted::Unknown | Compacted::Failed) {
            return Ok(Said::Defer);
        }
        let mode = if compacted == Compacted::Yes {
            crate::codex::headless::TURN
        } else {
            crate::codex::headless::COMPACT
        };
        let route = self.world.route(CAPABILITY, key.clone(), HOUR, mode);
        self.world.made(&route);
        let shared = SharedRoute::new(route);
        self.routes = BTreeMap::from([(key_text(&key), shared.clone())]);
        Ok(Said::Route(Box::new(shared)))
    }

    /// P8: the run kinds' one path (`follow_up`).
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        self.follow()
    }

    /// Turned off or watched, the same bookkeeping (`tend = tick`).
    fn tend(&mut self, _view: &dyn View) -> Option<Spoke> {
        Some(self.follow())
    }
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, RunWorld::bare())
}

/// `CompactContinue(paths, ...)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: RunWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(CompactContinue::new(paths.clone(), world)))
}
