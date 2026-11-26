//! `subagent_parent`'s code (seat S7.2e1b; `engine/subagent.py`): a parent conversation is told which of its subagents
//! stopped on a failure - in core's own words at P4 (5a), and, once MS passes, in a continuation of its own at P8 and P2
//! (5b).
//!
//! P4: core's words for a parent's continuation, and one line per subagent whose latest turn stopped on a failure and
//! was not told yet (at most MAX_LINES; DEFER past 2,000 characters); the children are told (`mentioned`) only once the
//! claim carrying the lines commits (`words_sent`). P8's errand: each conversation that finished a turn lately with no
//! error, whose subagent stopped, gets one continuation with the lines. Its seams are
//! [`super::emptyreply::LookWorld`]'s.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::domain::ids;
use car_machine::json::Value;
use car_policy::classify::vocab_gen::failures;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::emptyreply::{
    Continuations, LookWorld, count, due, enabled, int, key_of, part, rebind, waiting_records,
    widened, withdraw_not_own,
};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::lineage::Child;
use crate::seam_p7::words_pass;
use crate::state::errors::Result as StateResult;
use crate::state::scoped::Scoped;
use crate::vocabulary::{ContinuationKind, ContinuationReason, Measurement};

pub const CAPABILITY: &str = "subagent_parent";
pub const MAX_LINES: usize = 5;
pub const LINE_KEY: &str = "continue.subagent.line";
pub const KIND_PREFIX: &str = "continue.subagent.kind.";
/// The closed kind a subagent's stop is told as: a usage limit, a temporary failure, an interruption, or an error.
pub const KINDS: [&str; 4] = ["usage_limit", "temporary", "interrupted", "error"];
pub const LOOK_EVERY: f64 = 60.0;
pub const RECENT: f64 = 3600.0;
pub const SEEN_LIMIT: usize = 256;
/// How long a parent's words with the lines may be, at most (in characters).
pub const WORDS_LIMIT: usize = 2000;

fn is(value: &Value, word: &str) -> bool {
    matches!(value, Value::Str(text) if text.as_str() == Some(word))
}

/// `kind_of(child)`: the closed kind word a subagent's latest turn is told as, or None for one that did not stop on a
/// failure.
pub fn kind_of(child: &Child) -> Option<&'static str> {
    if is(&child.status, "interrupted") {
        return Some("interrupted");
    }
    if !is(&child.status, "failed") {
        return None;
    }
    if is(&child.category, failures::USAGE_LIMIT) {
        return Some("usage_limit");
    }
    Some(
        if failures::TRANSIENT
            .iter()
            .any(|word| is(&child.category, word))
        {
            "temporary"
        } else {
            "error"
        },
    )
}

/// `line(child, kind, locale=None)`: one subagent's line, in the catalog's words - its canonical id and its kind word.
pub fn line(world: &LookWorld, child: &Child, kind: &str) -> Option<String> {
    if !ids::is_uuid(&Value::Str(child.thread_id.as_str().into())) || !KINDS.contains(&kind) {
        return None;
    }
    let word = (world.words)(&format!("{KIND_PREFIX}{kind}"), None, &[])
        .unwrap_or_else(|| "None".to_owned());
    (world.words)(
        LINE_KEY,
        None,
        &[("child", child.thread_id.to_lowercase()), ("kind", word)],
    )
}

/// What P4 put in a parent's words, by its interruption: the parent and the children's keys.
type Pending = BTreeMap<String, (Value, Vec<Value>)>;

#[derive(Default)]
struct Memory {
    looked: Option<f64>,
    pending: Pending,
}

/// `SubagentParent(paths, home=None)`.
pub struct SubagentParent {
    pub paths: Paths,
    binding: Option<Binding>,
    world: LookWorld,
    memory: Arc<Mutex<Memory>>,
}

/// `_stopped(parent)`: [(key, line)] for each of `parent`'s subagents whose latest turn stopped on a failure and was not
/// told yet, at most MAX_LINES; empty where the children cannot be read. Err: a read of its own state that raised.
fn stopped(
    world: &LookWorld,
    handle: &Continuations<'_, '_>,
    parent: &Value,
) -> StateResult<Vec<(Value, String)>> {
    let Ok(children) = world.looks.children(parent) else {
        return Ok(Vec::new());
    };
    let mut found = Vec::new();
    for child in &children {
        let Some(kind) = kind_of(child) else {
            continue;
        };
        if matches!(child.turn_id, Value::Null) {
            continue;
        }
        let key = key_of(&[
            CAPABILITY.to_owned(),
            part(parent),
            child.thread_id.clone(),
            part(&child.turn_id),
        ]);
        if handle.get(&key)?.is_some() {
            continue;
        }
        if let Some(text) = line(world, child, kind) {
            found.push((key, text));
        }
        if found.len() >= MAX_LINES {
            break;
        }
    }
    Ok(found)
}

fn joined(found: &[(Value, String)]) -> String {
    found
        .iter()
        .map(|(_, text)| text.as_str())
        .collect::<Vec<_>>()
        .join("\n")
}

struct Look {
    binding: Binding,
    world: LookWorld,
    memory: Arc<Mutex<Memory>>,
}

impl Errand for Look {
    fn run(&self, view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        match self.binding.with(|scoped| self.look(scoped, view)) {
            Some(Err(_)) => Err(HookFailed),
            _ => Ok(Value::Null),
        }
    }
}

impl Look {
    /// `look(view)` (5b): each conversation that finished a turn lately, with no error, whose subagent stopped - one
    /// continuation to it, with the lines.
    fn look(&self, scoped: &Scoped<'_>, view: &dyn View) -> StateResult<()> {
        let handle = Continuations { scoped };
        if !handle.on() {
            return Ok(());
        }
        let now = scoped.now();
        self.memory
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .looked = Some(now);
        let looks = self.world.looks.as_ref();
        let Ok(candidates) = looks.recent(now - RECENT) else {
            return Ok(());
        };
        let wide = widened(scoped);
        withdraw_not_own(&handle, looks, wide);
        for parent in candidates {
            if enabled(view, &parent) != Some(true) || !matches!(looks.own(&parent, wide), Ok(true))
            {
                continue;
            }
            let Ok(Some(turn)) = looks.latest(&parent) else {
                continue;
            };
            if turn.status != "completed" || turn.errored {
                continue;
            }
            let found = stopped(&self.world, &handle, &parent)?;
            if found.is_empty() {
                continue;
            }
            let words = Value::Str(joined(&found).as_str().into());
            let key = key_of(&[
                CAPABILITY.to_owned(),
                "followed_up".to_owned(),
                part(&parent),
                turn.turn_id.clone(),
            ]);
            if handle.get(&key)?.is_some() || !words_pass(&words) {
                continue;
            }
            let ordinal = int(turn.ordinal);
            if handle.add(
                &key,
                ContinuationKind::Subagent,
                &parent,
                &words,
                &ordinal,
                &Value::from(1),
            )? {
                for (child, _) in &found {
                    handle.note(
                        child,
                        ContinuationKind::Subagent,
                        &parent,
                        ContinuationReason::Mentioned,
                        &ordinal,
                        &Value::from(0),
                    )?;
                }
                count(scoped, "followed_up");
            }
        }
        Ok(())
    }
}

impl SubagentParent {
    pub fn new(paths: Paths, world: LookWorld) -> SubagentParent {
        SubagentParent {
            paths,
            binding: None,
            world,
            memory: Arc::new(Mutex::new(Memory::default())),
        }
    }

    /// P4's body inside its own Scoped: Ok(None) is DEFER, Err a raise.
    fn words(
        &self,
        scoped: &Scoped<'_>,
        record: &Value,
        text: &str,
        thread: &Value,
    ) -> StateResult<Option<String>> {
        let handle = Continuations { scoped };
        let found = stopped(&self.world, &handle, thread)?;
        if found.is_empty() {
            return Ok(None);
        }
        let words = format!("{text}\n\n{}", joined(&found));
        if words.chars().count() > WORDS_LIMIT {
            return Ok(None);
        }
        let key = match record {
            Value::Object(map) => map.get("interruption_id").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        if !ids::is_interruption_id(&key, false) || !handle.on() {
            return Ok(None);
        }
        let mut memory = self.memory.lock().unwrap_or_else(PoisonError::into_inner);
        if memory.pending.len() >= SEEN_LIMIT {
            memory.pending.clear();
        }
        let name = part(&key);
        memory.pending.insert(
            name,
            (
                thread.clone(),
                found.into_iter().map(|(child, _)| child).collect(),
            ),
        );
        Ok(Some(words))
    }
}

impl Code for SubagentParent {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P4 (5a): core's own words and a line for each subagent that stopped - or DEFER.
    fn text(&mut self, record: &Value, text: &Value) -> Spoke {
        let thread = match record {
            Value::Object(map) => map.get("thread_id").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let (Some(binding), Value::Str(text)) = (&self.binding, text) else {
            return Ok(Said::Defer);
        };
        if !ids::is_uuid(&thread) {
            return Ok(Said::Defer);
        }
        let text = text.as_str().unwrap_or_default().to_owned();
        match binding.with(|scoped| self.words(scoped, record, &text, &thread)) {
            None | Some(Ok(None)) => Ok(Said::Defer),
            Some(Ok(Some(words))) => Ok(Said::Value(Value::Str(words.as_str().into()))),
            Some(Err(error)) => Err(Raised::new(error.class())),
        }
    }

    /// The claim that carried P4's lines for `record` committed: each child told.
    fn words_sent(&mut self, record: &Value) -> Option<Result<(), Raised>> {
        let key = match record {
            Value::Object(map) => map.get("interruption_id").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let pending = self
            .memory
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .pending
            .remove(&part(&key));
        let Some((thread, children)) = pending else {
            return Some(Ok(()));
        };
        let Some(binding) = &self.binding else {
            return Some(Err(Raised::new("AttributeError")));
        };
        let told = binding.with(|scoped| -> StateResult<()> {
            let handle = Continuations { scoped };
            for child in &children {
                handle.note(
                    child,
                    ContinuationKind::Subagent,
                    &thread,
                    ContinuationReason::Mentioned,
                    &Value::Null,
                    &Value::from(0),
                )?;
            }
            count(scoped, "told");
            Ok(())
        });
        Some(match told {
            Some(Err(error)) => Err(Raised::new(error.class())),
            _ => Ok(()),
        })
    }

    /// P8 (5b): the look, at most once a minute, once MS passed.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let found = binding.with(|scoped| {
            (
                scoped.passed(&Value::Str(Measurement::Ms.as_str().into())),
                scoped.now(),
            )
        });
        let Some((true, now)) = found else {
            return Ok(Said::Defer);
        };
        let looked = self
            .memory
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .looked;
        if !due(looked, now, LOOK_EVERY) {
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(Look {
            binding: rebind(binding),
            world: self.world.clone(),
            memory: self.memory.clone(),
        })))
    }

    /// P2 (5b): every continuation of this capability waiting, with its words.
    fn records(&mut self, _view: &dyn View) -> Spoke {
        waiting_records(self.binding.as_ref())
    }
}

/// `make(paths)`: the capability's code with the world a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, LookWorld::bare())
}

/// `SubagentParent(paths, home=...)` with an entry point's or a test's own world.
pub fn make_with(paths: &Paths, world: LookWorld) -> Option<Box<dyn Code>> {
    Some(Box::new(SubagentParent::new(paths.clone(), world)))
}
