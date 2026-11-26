//! A scripted plug (review 6, S3): a test double of car-policy's [`Plug`] whose answers come from a script, so that every
//! path of car-engine a plug other than NULL opens can be traced against the reference (`tests/rustdiff/plugscript.py`).
//!
//! The script is one object on the test's side (`enginerun.Script`), and the reference's own Engine is handed a
//! `domain.plug.Plug` that asks that same object; this plug asks it too, over the same pipe the backend is asked over
//! (`plug.<hook>`, the hook's arguments as the engine handed them), so both engines get the very same answer to the
//! very same question, and the script writes every question down. A question that differs between the two - another
//! record, another point, a hook asked twice or not at all - is a difference of the traces.
//!
//! An answer is a JSON value: `null` is DEFER; a word is an [`Alternative`] (one outside the point's set is DEFER, as
//! `Guarded` holds it); a list is a set of kinds; `raise` is a hook that failed, `panic` a hook that panicked
//! (D15: `Guarded` catches both, and counts them in `failures`). What this plug does not script: P2 (records), P5's
//! channel, P8 and P22's errands, P9-P13, P16's route, P21 - they need the advanced plug (S7.2) and answer DEFER; P5,
//! P2 and P8 are asked and DEFER, which is what NULL does and what the traces then hold equal.

use car_machine::json::{Str, Value};
use car_machine::pyval::Py;
use car_policy::plug::{
    Alternative, Answer, Channel, Edition, Hook, HookFailed, Plug, Point, Unloaded,
};

/// How a hook asks the script: the hook's name and arguments, the script's answer (or the class that raised).
pub type Asker = Box<dyn Fn(&str, Vec<Value>) -> Py<Value> + Send + Sync>;

pub struct Scripted {
    asker: Asker,
}

impl Scripted {
    pub fn new(asker: Asker) -> Scripted {
        Scripted { asker }
    }

    /// A plug whose script is the test's object, asked back over the harness pipe (`engine::ask`).
    pub fn asking() -> Scripted {
        Scripted::new(Box::new(crate::engine::ask))
    }

    fn call(&self, hook: &str, args: Vec<Value>) -> Result<Value, HookFailed> {
        match (self.asker)(&format!("plug.{hook}"), args) {
            Ok(answer) => Ok(answer),
            // A panic that unwinds without the panic hook: no message on stderr, which the traces' pipe does not drain
            // (a walk with a hook panicking a thousand times filled it and stopped the harness). `Guarded` catches it.
            Err("ScriptPanic") => {
                std::panic::resume_unwind(Box::new(format!("the scripted plug's {hook} panicked")))
            }
            Err(_) => Err(HookFailed),
        }
    }

    fn word(&self, hook: &str, args: Vec<Value>) -> Hook<Alternative> {
        Ok(match self.call(hook, args)? {
            Value::Str(word) => word
                .as_str()
                .and_then(Alternative::parse)
                .map_or(Answer::Defer, Answer::Is),
            _ => Answer::Defer,
        })
    }

    fn kinds(&self, hook: &str) -> Hook<Vec<Value>> {
        Ok(match self.call(hook, Vec::new())? {
            Value::Array(found) => Answer::Is(found),
            _ => Answer::Defer,
        })
    }
}

impl Plug for Scripted {
    fn edition(&self) -> Edition {
        Edition::Standard
    }

    fn gate(&self, name: &str, record: &Value, facts: &Value) -> Hook<Alternative> {
        self.word(
            "gate",
            vec![Value::from(name), record.clone(), facts.clone()],
        )
    }

    fn text(&self, record: &Value, text: &Str) -> Hook<Str> {
        Ok(
            match self.call("text", vec![record.clone(), Value::Str(text.clone())])? {
                Value::Str(words) => Answer::Is(words),
                _ => Answer::Defer,
            },
        )
    }

    fn sender(&self, record: &Value) -> Hook<Box<dyn Channel>> {
        // A channel needs the advanced plug (S7.2); the question is asked, and written down, and answered DEFER.
        self.call("sender", vec![record.clone()])?;
        Ok(Answer::Defer)
    }

    fn outcome(&self, record: &Value, outcome: &str) -> Hook<Alternative> {
        self.word("outcome", vec![record.clone(), Value::from(outcome)])
    }

    fn schedule(&self, record: &Value, due: &Value) -> Hook<Alternative> {
        self.word("schedule", vec![record.clone(), due.clone()])
    }

    fn moved(&self, record: &Value, state: &str) -> Hook<()> {
        self.call("moved", vec![record.clone(), Value::from(state)])?;
        Ok(Answer::Defer)
    }

    fn delivery(&self, record: &Value) -> Hook<Alternative> {
        self.word("delivery", vec![record.clone()])
    }

    fn unloaded(&self, record: &Value) -> Hook<Unloaded> {
        Ok(match self.word("unloaded", vec![record.clone()])? {
            Answer::Is(word) => Answer::Is(Unloaded::Queued(word)),
            Answer::Defer => Answer::Defer,
        })
    }

    fn admission(&self, failure: &Value) -> Hook<Alternative> {
        self.word("admission", vec![failure.clone()])
    }

    fn sessions(&self) -> Hook<Vec<Value>> {
        self.kinds("sessions")
    }

    fn eligibility(&self) -> Hook<Vec<Value>> {
        self.kinds("eligibility")
    }

    fn records(&self, _view: &dyn car_policy::plug::View) -> Hook<Vec<Value>> {
        // P2 (seat S7.2a2): the records the script hands over, each carried out by core.
        Ok(match self.call("records", Vec::new())? {
            Value::Array(found) => Answer::Is(found),
            _ => Answer::Defer,
        })
    }

    fn claim_ledger(
        &self,
        _connection: &mut dyn car_policy::plug::Ledger,
        record: &Value,
        now: f64,
        carried: &[Point],
    ) -> Hook<Alternative> {
        // P11 (seat S7.2a2): HOLD, a raise or DEFER, the points carried as sorted words.
        let mut words: Vec<&str> = carried.iter().map(|point| point.as_str()).collect();
        words.sort_unstable();
        self.word(
            "claim_ledger",
            vec![
                record.clone(),
                Value::Float(now),
                Value::Array(words.into_iter().map(Value::from).collect()),
            ],
        )
    }

    fn notice(&self, facts: &Value) -> Hook<()> {
        self.call("notice", vec![facts.clone()])?;
        Ok(Answer::Defer)
    }

    fn wants(&self, point: Point) -> Result<bool, HookFailed> {
        Ok(matches!(
            self.call("wants", vec![Value::from(point.as_str())])?,
            Value::Bool(true)
        ))
    }
}
