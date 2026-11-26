//! `keep_going`'s code (seat S7.2e1b; `engine/keepgoing.py`): a conversation a person picked keeps going after a turn
//! that ended well, up to the count they chose, and stops on no progress, a finished plan or an active goal - at P8 and
//! P2.
//!
//! P8's errand, at most once a minute while a conversation is kept going: each one's latest turn - completed with no
//! error, idle IDLE_FOR since, not continued already - gets one continuation of the edition's own words; or its row is
//! stopped, said why (`state/continuations.py` keep_going). Until MK passes, no more than UNMEASURED_COUNT. P2 is
//! empty_response's. Its seams are [`super::emptyreply::LookWorld`]'s.

use std::sync::{Arc, Mutex, PoisonError};

use car_codex::values::PROGRESS_ITEM_TYPES;
use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::emptyreply::{
    Continuations, LookWorld, count, due, enabled, int, key_of, kinds_of, part, rebind,
    waiting_records, word,
};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::seam_p7::words_pass;
use crate::state::scoped::Scoped;
use crate::state::sql::{self, Row};
use crate::vocabulary::{ContinuationKind, GoalStatus, KeepReason, KeepState, Measurement};

pub const CAPABILITY: &str = "keep_going";
pub const WORDS_KEY: &str = "continue.keep_going";
pub const IDLE_FOR: f64 = 60.0;
pub const LOOK_EVERY: f64 = 60.0;
/// Until MK - a throwaway conversation with a plan, its steps' statuses read - passes for the Codex in force.
pub const UNMEASURED_COUNT: i64 = 3;

/// `allowed(count, measured)`: its count, or no more than UNMEASURED_COUNT until MK passed.
pub fn allowed(count: i64, measured: bool) -> i64 {
    if measured {
        count
    } else {
        count.min(UNMEASURED_COUNT)
    }
}

fn is_on_row(row: &Row) -> bool {
    sql::py_eq(sql::get(row, "state"), &word(KeepState::On.as_str()))
}

/// A row's int column (`count`, `used`); Err where it is none (the reference's compare would raise).
fn column(row: &Row, name: &str) -> Result<i64, ()> {
    match sql::get(row, name) {
        Value::Int(held) => held.as_i64().ok_or(()),
        _ => Err(()),
    }
}

/// `KeepGoing(paths, home=None)`.
pub struct KeepGoing {
    pub paths: Paths,
    binding: Option<Binding>,
    world: LookWorld,
    looked: Arc<Mutex<Option<f64>>>,
}

struct Look {
    binding: Binding,
    world: LookWorld,
    looked: Arc<Mutex<Option<f64>>>,
}

impl Errand for Look {
    fn run(&self, view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        match self.binding.with(|scoped| self.look(scoped, view)) {
            Some(Err(())) => Err(HookFailed),
            _ => Ok(Value::Null),
        }
    }
}

impl Look {
    /// `look(view)`: every conversation kept going, looked at; one that cannot be read is looked at again in a minute.
    /// Err is a raise out of the errand (the rows that cannot be read).
    fn look(&self, scoped: &Scoped<'_>, view: &dyn View) -> Result<(), ()> {
        let handle = Continuations { scoped };
        if !handle.on() {
            return Ok(());
        }
        let now = scoped.now();
        *self.looked.lock().unwrap_or_else(PoisonError::into_inner) = Some(now);
        let measured = scoped.passed(&word(Measurement::Mk.as_str()));
        for row in handle.kept().map_err(|_| ())? {
            if !is_on_row(&row) {
                continue;
            }
            let _ = self.one(scoped, &handle, view, &row, now, measured);
        }
        Ok(())
    }

    /// `_one`: Err is the reference's raise, caught by `look` (nothing this look).
    fn one(
        &self,
        scoped: &Scoped<'_>,
        handle: &Continuations<'_, '_>,
        view: &dyn View,
        row: &Row,
        now: f64,
        measured: bool,
    ) -> Result<(), ()> {
        let thread = sql::get(row, "thread_id").clone();
        match enabled(view, &thread) {
            None => return Err(()),
            Some(false) => return stop(scoped, handle, &thread, KeepReason::ConversationOff),
            Some(true) => {}
        }
        let looks = self.world.looks.as_ref();
        let Ok(Some(turn)) = looks.latest(&thread) else {
            return Ok(());
        };
        match turn.status.as_str() {
            "inProgress" | "other" => return Ok(()),
            "interrupted" => return stop(scoped, handle, &thread, KeepReason::ByPerson),
            "failed" => return stop(scoped, handle, &thread, KeepReason::Failed),
            _ if turn.errored => return stop(scoped, handle, &thread, KeepReason::Failed),
            _ => {}
        }
        let Some(completed) = turn.completed_at else {
            return Ok(());
        };
        if now - (completed as f64) < IDLE_FOR {
            return Ok(());
        }
        let key = key_of(&[CAPABILITY.to_owned(), part(&thread), turn.turn_id.clone()]);
        if handle.get(&key).map_err(|_| ())?.is_some() {
            return Ok(());
        }
        let kinds = kinds_of(&turn);
        if !PROGRESS_ITEM_TYPES
            .iter()
            .any(|kind| kinds.get(*kind).copied().unwrap_or(0) != 0)
        {
            return stop(scoped, handle, &thread, KeepReason::NoProgress);
        }
        let goal = looks.goal(&thread).map_err(|_| ())?;
        if goal.as_deref() == Some(GoalStatus::Active.as_str()) {
            return stop(scoped, handle, &thread, KeepReason::GoalActive);
        }
        let statuses = match looks.plan_statuses(&thread) {
            Ok(statuses) => statuses,
            Err(_) => return stop(scoped, handle, &thread, KeepReason::PlanUnreadable),
        };
        if statuses.is_some_and(|statuses| statuses.iter().all(|status| status == "completed")) {
            return stop(scoped, handle, &thread, KeepReason::PlanDone);
        }
        if column(row, "used")? >= allowed(column(row, "count")?, measured) {
            return stop(scoped, handle, &thread, KeepReason::CountSpent);
        }
        let words = self.world.text(WORDS_KEY);
        if words_pass(&words)
            && handle
                .add(
                    &key,
                    ContinuationKind::KeepGoing,
                    &thread,
                    &words,
                    &int(turn.ordinal),
                    &Value::from(1),
                )
                .map_err(|_| ())?
        {
            count(scoped, "found");
        }
        Ok(())
    }
}

/// `_stop`: the conversation's row stopped, said why; counted when it was.
fn stop(
    scoped: &Scoped<'_>,
    handle: &Continuations<'_, '_>,
    thread: &Value,
    reason: KeepReason,
) -> Result<(), ()> {
    if handle.stop_kept(reason.as_str(), thread).map_err(|_| ())? != 0 {
        count(scoped, "stopped");
    }
    Ok(())
}

impl KeepGoing {
    pub fn new(paths: Paths, world: LookWorld) -> KeepGoing {
        KeepGoing {
            paths,
            binding: None,
            world,
            looked: Arc::new(Mutex::new(None)),
        }
    }
}

impl Code for KeepGoing {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P8: the look, at most once a minute, while a conversation is kept going.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let found = binding.with(|scoped| {
            let rows = Continuations { scoped }.kept().ok()?;
            Some((rows.iter().any(is_on_row), scoped.now()))
        });
        let Some(Some((any, now))) = found else {
            return Ok(Said::Defer);
        };
        let looked = *self.looked.lock().unwrap_or_else(PoisonError::into_inner);
        if !any || !due(looked, now, LOOK_EVERY) {
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(Look {
            binding: rebind(binding),
            world: self.world.clone(),
            looked: self.looked.clone(),
        })))
    }

    /// P2: every continuation of this capability waiting, with its words.
    fn records(&mut self, _view: &dyn View) -> Spoke {
        waiting_records(self.binding.as_ref())
    }
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, LookWorld::bare())
}

/// `KeepGoing(paths, home=...)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: LookWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(KeepGoing::new(paths.clone(), world)))
}
