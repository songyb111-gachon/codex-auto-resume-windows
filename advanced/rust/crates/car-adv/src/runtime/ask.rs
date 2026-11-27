//! `Runtime.ask` and what it calls (`runtime.py`): the answer at one point - an armed capability's, or NULL's.

use std::cell::OnceCell;

use car_machine::json::Value;
use car_policy::classify::gates::{PASS, gate_schedule};
use car_policy::plug::{Alternative, Point, alternatives};

use super::{
    Acted, KNOWN_FAILURE, Py, Raise, Runtime, SUBMISSION_UNKNOWN, caught, field, journal_word,
    key_of, number, object, said_in, sending, vouched_by,
};
use crate::capabilities::{Code, Raised, Said, Spoke};
use crate::registry::CapabilityDef;
use crate::state::sql::Row;
use crate::vocabulary::{ArmingState, ArmingWarning, JournalCode};

/// `RESTRICTIONS`.
const RESTRICTIONS: &[&str] = car_policy::plug::vocab_gen::domain_plug::RESTRICTIONS;
/// `RELAXING` = `TAKE_UP`.
const RELAXING: &[&str] = car_policy::plug::vocab_gen::domain_plug::TAKE_UP;
/// `QUEUED`.
const QUEUED: &[&str] = car_policy::plug::vocab_gen::domain_plug::QUEUED;
/// `failures.ADMISSIBLE`.
const ADMISSIBLE: &[&str] = car_policy::classify::vocab_gen::failures::ADMISSIBLE;

/// `HELD_AT_CEILING`: TAKE_UP but CAPACITY.
fn held_at_ceiling(said: &Said) -> bool {
    said.text()
        .is_some_and(|word| word != Alternative::Capacity.as_str() && RELAXING.contains(&word))
}

/// The hook of `point`, called with the point's arguments (`getattr(code, HOOKS[point])(*arguments)`).
pub(crate) fn hook(code: &mut dyn Code, point: Point, args: &[&Value]) -> Spoke {
    let arg = |index: usize| args.get(index).copied().unwrap_or(&Value::Null);
    match point {
        Point::Gates => code.gate(arg(0), arg(1), arg(2)),
        Point::Text => code.text(arg(0), arg(1)),
        Point::Sender => code.sender(arg(0)),
        Point::Outcome => code.outcome(arg(0), arg(1)),
        Point::Schedule => code.schedule(arg(0), arg(1)),
        Point::Delivery => code.delivery(arg(0)),
        Point::Unloaded => code.unloaded(arg(0)),
        Point::Admission => code.admission(arg(0)),
        Point::StartRoute => code.start_route(arg(0)),
        Point::Supervision => code.supervise(arg(0)),
        Point::Notice => code.notice(arg(0)),
        Point::Power => code.power(arg(0)),
        _ => Err(Raised::missing()),
    }
}

/// `getattr(NULL, HOOKS[point])(*arguments)`: DEFER - and at P5 the backend it was handed.
pub(crate) fn null_answer(point: Point) -> Said {
    if point == Point::Sender {
        Said::Backend
    } else {
        Said::Defer
    }
}

/// `_own_record(record)`: a record of this edition's own (P2) rather than one of core's.
pub(crate) fn own_record(record: &Value) -> bool {
    object(record)
        .is_some_and(|map| map.contains_key("record_id") && !map.contains_key("interruption_id"))
}

/// `_route_ask(record)`: P15 asked for a route that takes words - the record says `route`, True itself.
fn route_ask(record: &Value) -> bool {
    matches!(field(record, "route"), Value::Bool(true))
}

/// `_taken(point, answer)`: whether core would take `answer` at `point`, by the checks core makes itself.
fn taken(point: Point, said: &Said) -> bool {
    if let Some(accepted) = alternatives(point) {
        return said
            .text()
            .is_some_and(|word| accepted.iter().any(|each| each.as_str() == word));
    }
    match point {
        Point::Text => said.to_value().is_some_and(|words| {
            car_policy::classify::continuation::validate_custom(&words).is_ok()
        }),
        Point::Sender => matches!(said, Said::Channel(_)),
        Point::Unloaded => match said.text() {
            Some(word) => QUEUED.contains(&word),
            None => matches!(said, Said::Route(_)),
        },
        _ => true,
    }
}

/// `_restricts(answer)`.
fn restricts(said: &Said) -> bool {
    said_in(said, RESTRICTIONS)
}

/// `_relaxes(answer)`.
fn relaxes(said: &Said) -> bool {
    said_in(said, RELAXING)
}

/// `_not_ordinary(point, answer)`: any channel at P5 and a client id at P15 keep a send from core's ordinary way.
fn not_ordinary(point: Point, said: &Said) -> bool {
    point == Point::Sender
        || (point == Point::Delivery && said.text() == Some(Alternative::ClientId.as_str()))
}

/// `CONFLICTS`' one line: (UNLOADED, QUEUED, {SENDER, DELIVERY}, `_not_ordinary`, SPLIT).
fn conflict_line_covers(point: Point) -> bool {
    matches!(point, Point::Sender | Point::Delivery)
}

/// The admission row of a record, read once and only if something asks (`_admission_of`): (row, whether the read
/// failed).
pub(crate) struct Admission<'a> {
    record: &'a Value,
    memo: OnceCell<(Option<Row>, bool)>,
}

impl<'a> Admission<'a> {
    fn new(record: &'a Value) -> Admission<'a> {
        Admission {
            record,
            memo: OnceCell::new(),
        }
    }

    fn get(&self, runtime: &Runtime) -> Py<&(Option<Row>, bool)> {
        if let Some(found) = self.memo.get() {
            return Ok(found);
        }
        let found = match caught(runtime.faulted("admission").and_then(|()| {
            runtime
                .state
                .admission(field(self.record, "interruption_id"))
        }))? {
            Some(row) => (row, false),
            None => (None, true),
        };
        Ok(self.memo.get_or_init(|| found))
    }
}

impl Runtime {
    /// `ask(point, *arguments)`: the answer at `point`. `args` are the hook's arguments, the backend left out at P5.
    pub fn ask(&self, point: Point, args: &[&Value]) -> Py<Said> {
        let definitions = self.registry.at(point);
        if super::own_record_point(point) && args.first().is_some_and(|record| own_record(record)) {
            return self.own_record_answer(point, args);
        }
        if definitions.is_empty() {
            return Ok(null_answer(point));
        }
        let states = self.states(false, &[]);
        let record: Option<&Value> =
            sending(point).map(|index| args.get(index).copied().unwrap_or(&Value::Null));
        if point == Point::Schedule
            && let Some(record) = record
            && object(record).is_some()
            && field(record, "state").as_str_value() == Some(SUBMISSION_UNKNOWN)
            && let Some(again) = self.send_again(record, &states)?
        {
            return Ok(again);
        }
        let relaxing = point == Point::Gates
            && args.first().and_then(|name| name.as_str_value()) == Some(KNOWN_FAILURE)
            && record.is_some_and(|record| object(record).is_some());
        let admission = if relaxing {
            record.map(Admission::new)
        } else {
            None
        };
        let key = record.map_or_else(|| "None".to_owned(), key_of);
        let kept = point == Point::Unloaded && record.is_some_and(crate::engine::foropen::watching);
        let earlier = self.earlier(&key, point);
        let mut chosen: Option<(Said, &CapabilityDef)> = None;
        for definition in definitions.iter().copied() {
            let state = states.state_of(&definition.id);
            if state == ArmingState::Off || self.is_skipped(&definition.id, &key) {
                continue;
            }
            let answer = match self.call(definition, |code| hook(code, point, args)) {
                Ok(answer) => answer,
                Err(raised) => {
                    self.tripped(definition, record, &raised);
                    continue;
                }
            };
            if answer.is_defer()
                || (point == Point::Sender && matches!(answer, Said::Backend))
                || !self.takes(definition, point, &answer, args, admission.as_ref())?
            {
                continue;
            }
            if state == ArmingState::Shadow {
                self.once(
                    JournalCode::WouldHave,
                    definition,
                    point,
                    &journal_word(&answer, point),
                    record,
                )?;
                continue;
            }
            if let Some((entry, why)) = self.conflict(definition, &earlier, point, &answer)? {
                // Taken, core could carry neither: it stands aside for this record, and says for whom and why.
                self.paired(
                    JournalCode::Overruled,
                    definition,
                    point,
                    &entry.1,
                    record.unwrap_or(&Value::Null),
                    why.as_deref(),
                )?;
                continue;
            }
            if restricts(&answer) {
                self.once(
                    JournalCode::Acted,
                    definition,
                    point,
                    &journal_word(&answer, point),
                    record,
                )?;
                return Ok(answer);
            }
            if let Some((earlier_answer, _)) = &chosen
                && !preferred(point, earlier_answer, &answer, record, self.now())
            {
                continue;
            }
            if sending(point).is_some() && !kept {
                let reached = match record {
                    Some(record) if object(record).is_some() => {
                        let verified = self.verified(definition, point, &answer, &key);
                        self.ceiling(definition, record, verified)?
                    }
                    _ => true,
                };
                if reached {
                    self.once(
                        JournalCode::Ceiling,
                        definition,
                        point,
                        &journal_word(&answer, point),
                        record,
                    )?;
                    if relaxing && held_at_ceiling(&answer) {
                        return Ok(Said::Word(Alternative::Hold)); // it waits for a unit, and does not end
                    }
                    continue;
                }
            }
            chosen = Some((answer, definition));
        }
        let Some((chosen, chooser)) = chosen else {
            if relaxing
                && let (Some(record), Some(admission)) = (record, admission.as_ref())
                && self.unsure(record, admission)?
            {
                return Ok(Said::Word(Alternative::Hold));
            }
            return Ok(null_answer(point));
        };
        if point == Point::Schedule
            && let Some(record) = record
        {
            self.not_taken(&definitions, chooser, record, &states);
        }
        if point == Point::Admission
            && !self.remember(
                chooser,
                args.first().copied().unwrap_or(&Value::Null),
                &chosen,
            )?
        {
            return Ok(null_answer(point));
        }
        if relaxing
            && relaxes(&chosen)
            && !self.first(chooser, &chosen, args, admission.as_ref())?
        {
            return Ok(null_answer(point));
        }
        if sending(point).is_some() && !kept {
            let word = journal_word(&chosen, point);
            let key = key_of(record.unwrap_or(&Value::Null));
            self.acted.borrow_mut().entry(key).or_default().insert((
                point,
                chooser.id.clone(),
                Some(word),
            ));
        }
        if point == Point::Sender
            && let Some(record) = record
        {
            self.alone(chooser, &chosen, record)?;
        }
        let word = journal_word(&chosen, point);
        if point == Point::StartRoute {
            let me = self.me.borrow().clone();
            let capability = chooser.id.clone();
            let told_word = word.clone();
            let told: Box<dyn FnOnce() + Send> = Box::new(move || {
                if let Some(shared) = me.upgrade() {
                    shared.enter(|runtime| {
                        if let Some(definition) = runtime.registry.get(&capability) {
                            let _ = runtime.once(
                                JournalCode::Acted,
                                definition,
                                Point::StartRoute,
                                &told_word,
                                None,
                            );
                        }
                    });
                }
            });
            match self.call_own(chooser, |code| code.acted_when_told(told)) {
                Ok(Some(Ok(()))) => return Ok(chosen),
                Ok(Some(Err(raised))) | Err(raised) => return Err(Raise(class_of(&raised))),
                Ok(None) => {}
            }
        }
        self.once(JournalCode::Acted, chooser, point, &word, record)?;
        Ok(chosen)
    }

    /// `_takes(definition, point, answer, arguments, admission)`: whether an answer is one to take at all.
    fn takes(
        &self,
        definition: &CapabilityDef,
        point: Point,
        said: &Said,
        args: &[&Value],
        admission: Option<&Admission<'_>>,
    ) -> Py<bool> {
        if !taken(point, said) {
            return Ok(false);
        }
        if point == Point::Delivery && args.first().is_some_and(|record| route_ask(record)) {
            // v0.6.17 (#47 P-6): a route's P15 takes SILENT alone.
            return Ok(said.is(Alternative::Silent));
        }
        if point == Point::Admission {
            let facts = args.first().copied().unwrap_or(&Value::Null);
            let offered = match object(facts).and_then(|map| map.get("takes")) {
                Some(Value::Array(takes)) => said
                    .text()
                    .is_some_and(|word| takes.iter().any(|each| each.as_str_value() == Some(word))),
                _ => false,
            };
            return Ok(offered && self.since_armed(definition, facts));
        }
        if point == Point::Gates && relaxes(said) {
            let Some(admission) = admission else {
                return Ok(false);
            };
            let (row, _failed) = admission.get(self)?;
            let Some(row) = row else {
                return Ok(false);
            };
            let same = row.get("capability").and_then(|value| value.as_str_value())
                == Some(definition.id.as_str())
                && row.get("answer").and_then(|value| value.as_str_value()) == said.text();
            return Ok(same && self.on_since_taken(definition, row));
        }
        Ok(true)
    }

    /// `_since_armed(definition, facts)`: the failure completed once `definition` stood where it stands now.
    fn since_armed(&self, definition: &CapabilityDef, facts: &Value) -> bool {
        let since = self.since_of(&definition.id).flatten();
        let completed = number(field(facts, "completed_at"));
        matches!((since, completed), (Some(since), Some(completed)) if completed >= since)
    }

    /// `_on_since_taken(definition, row)`: on ever since it took the failure up, and never read down since.
    fn on_since_taken(&self, definition: &CapabilityDef, row: &Row) -> bool {
        let since = self.since_of(&definition.id).flatten();
        let taken = row.get("created_at").and_then(number);
        let down = self
            .down_at
            .borrow()
            .get(&definition.id)
            .copied()
            .unwrap_or(f64::NEG_INFINITY);
        matches!((since, taken), (Some(since), Some(taken)) if taken >= since && taken >= down)
    }

    /// `_unsure(record, admission)`: a record core never recovers alone that this runtime could not look at.
    fn unsure(&self, record: &Value, admission: &Admission<'_>) -> Py<bool> {
        let category = field(record, "category").as_str_value();
        if !category.is_some_and(|category| ADMISSIBLE.contains(&category)) {
            return Ok(false);
        }
        Ok(self.unreadable.get() || admission.get(self)?.1)
    }

    /// `_remember(definition, facts, answer)`: P17's answer taken - which capability took the failure up, with which
    /// word, and the rule or the shape. A write that fails takes nothing up.
    fn remember(&self, definition: &CapabilityDef, facts: &Value, answer: &Said) -> Py<bool> {
        let mut rule = Value::Null;
        match self.call_own(definition, |code| {
            code.rule_for(facts, &answer.to_value().unwrap_or(Value::Null))
        }) {
            Ok(Some(Ok(found))) => {
                if matches!(found, Value::Int(_)) {
                    rule = found;
                }
            }
            Ok(Some(Err(raised))) | Err(raised) => {
                self.tripped(definition, Some(facts), &raised);
                return Ok(false);
            }
            Ok(None) => {}
        }
        let Some(map) = object(facts) else {
            return Err(Raise("AttributeError"));
        };
        let shape = if definition.samples {
            let mut shape = car_machine::json::Map::new();
            for name in ["code", "status", "form", "has_message"] {
                shape.insert(name.into(), map.get(name).cloned().unwrap_or(Value::Null));
            }
            Value::Object(shape)
        } else {
            Value::Null
        };
        Ok(caught(self.faulted("admit").and_then(|()| {
            self.state.admit(
                map.get("interruption_id").unwrap_or(&Value::Null),
                &Value::Str(definition.id.as_str().into()),
                &answer.to_value().unwrap_or(Value::Null),
                &rule,
                &shape,
                &Value::Float(self.now()),
            )
        }))?
        .unwrap_or(false))
    }

    /// `_first(definition, answer, arguments, admission)`: the first time core goes on with a record it took up.
    fn first(
        &self,
        definition: &CapabilityDef,
        answer: &Said,
        args: &[&Value],
        admission: Option<&Admission<'_>>,
    ) -> Py<bool> {
        let row = match admission {
            Some(admission) => admission.get(self)?.0.clone(),
            None => None,
        };
        let Some(row) = row else {
            return Ok(true);
        };
        if car_machine::pyval::truthy(row.get("sampled").unwrap_or(&Value::Null)) {
            return Ok(true);
        }
        let word = answer.to_value().unwrap_or(Value::Null);
        let kept = match self.call_own(definition, |code| code.taken(Point::Gates, &word, args)) {
            Ok(None) => return Ok(true),
            Ok(Some(Ok(kept))) => kept,
            Ok(Some(Err(raised))) | Err(raised) => {
                self.tripped(definition, args.get(1).copied(), &raised);
                return Ok(false);
            }
        };
        let kept = if object(&kept).is_some() {
            kept
        } else {
            Value::Object(Default::default())
        };
        caught(self.state.taken(
            row.get("interruption_id").unwrap_or(&Value::Null),
            &Value::Str(definition.id.as_str().into()),
            field(&kept, "code"),
            field(&kept, "sample"),
            &Value::Float(self.now()),
        ))?;
        Ok(true)
    }

    /// `_ceiling(definition, record, verified=False)`: whether a ceiling leaves it nothing to spend on `record` now
    /// (a state that cannot be read leaves nothing).
    pub(crate) fn ceiling(
        &self,
        definition: &CapabilityDef,
        record: &Value,
        verified: bool,
    ) -> Py<bool> {
        let Some(counts) = caught(self.state.spent(
            &Value::Str(definition.id.as_str().into()),
            field(record, "thread_id"),
            &Value::Null,
        ))?
        else {
            return Ok(true);
        };
        let Some(meta) = caught(self.state.meta())? else {
            return Ok(true);
        };
        let hourly = meta.get("global_hourly").cloned().unwrap_or(Value::Null);
        match caught(crate::ledger::ceiling_reached(
            &counts, definition, &hourly, verified,
        ))? {
            Some(found) => Ok(found.is_some()),
            None => Ok(true),
        }
    }

    /// `_verified(definition, point, answer, key)` (v0.6.22, #59).
    fn verified(&self, definition: &CapabilityDef, point: Point, said: &Said, key: &str) -> bool {
        if point == Point::Gates {
            return said.is(Alternative::VerifiedReset);
        }
        vouched_by(point)
            && self.acted.borrow().get(key).is_some_and(|entries| {
                entries.contains(&(
                    Point::Gates,
                    definition.id.clone(),
                    Some(Alternative::VerifiedReset.as_str().to_owned()),
                ))
            })
    }

    /// `_earlier(key, point)`: each answer taken this tick for the record that CONFLICTS says an answer at `point` may
    /// not be carried with.
    fn earlier(&self, key: &str, point: Point) -> Vec<Acted> {
        if !conflict_line_covers(point) {
            return Vec::new();
        }
        self.acted
            .borrow()
            .get(key)
            .map(|entries| {
                entries
                    .iter()
                    .filter(|entry| {
                        entry.0 == Point::Unloaded
                            && entry
                                .2
                                .as_deref()
                                .is_some_and(|word| QUEUED.contains(&word))
                    })
                    .cloned()
                    .collect()
            })
            .unwrap_or_default()
    }

    /// `_conflict(earlier, point, answer, carries)`: the first earlier answer `answer` cannot be carried with, and why.
    fn conflict(
        &self,
        definition: &CapabilityDef,
        earlier: &[Acted],
        point: Point,
        said: &Said,
    ) -> Py<Option<(Acted, Option<String>)>> {
        for entry in earlier {
            if !not_ordinary(point, said) {
                continue;
            }
            let word = entry
                .2
                .clone()
                .map_or(Value::Null, |word| Value::Str(word.into()));
            let why = match self.call_own(definition, |code| code.carries(&word)) {
                Ok(Some(Ok(why))) => Some(why),
                Ok(Some(Err(_))) => None,
                Ok(None) => None,
                Err(raised) => return Err(Raise(class_of(&raised))),
            };
            if matches!(why, Some(Value::Bool(true))) {
                continue;
            }
            let reason = why
                .and_then(|why| why.as_str_value().map(str::to_owned))
                .filter(|why| {
                    ArmingWarning::ALL
                        .iter()
                        .any(|warning| warning.as_str() == why)
                });
            return Ok(Some((entry.clone(), reason)));
        }
        Ok(None)
    }

    /// `_not_taken(definitions, chooser, record, states)`: at P7, every capability on with a `not_taken` whose answer
    /// was not the one taken is told so.
    fn not_taken(
        &self,
        definitions: &[&CapabilityDef],
        chooser: &CapabilityDef,
        record: &Value,
        states: &crate::arming::States,
    ) {
        for definition in definitions.iter().copied() {
            if std::ptr::eq(definition, chooser)
                || states.state_of(&definition.id) != ArmingState::Armed
            {
                continue;
            }
            match self.call_own(definition, |code| code.not_taken(record)) {
                Ok(None) | Ok(Some(Ok(()))) => {}
                Ok(Some(Err(raised))) | Err(raised) => {
                    self.tripped(definition, Some(record), &raised)
                }
            }
        }
    }

    /// `_send_again(record, states)`: Keep on's Send again at P7 for an uncertain submission.
    fn send_again(&self, record: &Value, states: &crate::arming::States) -> Py<Option<Said>> {
        let Some((capability, state)) = self.arming.resender(record, states) else {
            return Ok(None);
        };
        let Some(definition) = self.registry.get(&capability) else {
            return Ok(None);
        };
        let key = key_of(record);
        if self.is_skipped(&definition.id, &key) {
            return Ok(None);
        }
        let word = Alternative::Resend.as_str();
        if state == ArmingState::Shadow {
            self.once(
                JournalCode::WouldHave,
                definition,
                Point::Schedule,
                word,
                Some(record),
            )?;
            return Ok(None);
        }
        if self.ceiling(definition, record, false)? {
            self.once(
                JournalCode::Ceiling,
                definition,
                Point::Schedule,
                word,
                Some(record),
            )?;
            return Ok(None);
        }
        self.acted.borrow_mut().entry(key).or_default().insert((
            Point::Schedule,
            definition.id.clone(),
            Some(word.to_owned()),
        ));
        self.once(
            JournalCode::Acted,
            definition,
            Point::Schedule,
            word,
            Some(record),
        )?;
        Ok(Some(Said::Word(Alternative::Resend)))
    }

    /// `_alone(chooser, channel, record)` (v0.6.17, #47 P-7): where P12 answered for `record` this tick and the channel
    /// cannot wait beside others, the capability that answered P12 stood aside.
    fn alone(&self, chooser: &CapabilityDef, channel: &Said, record: &Value) -> Py<()> {
        let entries: Vec<Acted> = self
            .acted
            .borrow()
            .get(&key_of(record))
            .map(|entries| entries.iter().cloned().collect())
            .unwrap_or_default();
        let pooled: Vec<String> = entries
            .iter()
            .filter(|entry| entry.0 == Point::Concurrency)
            .map(|entry| entry.1.clone())
            .collect();
        let resent = entries.iter().any(|entry| {
            entry.0 == Point::Schedule && entry.2.as_deref() == Some(Alternative::Resend.as_str())
        });
        if pooled.is_empty() || resent {
            return Ok(());
        }
        let why: Option<Value> = match channel {
            Said::Channel(channel) => {
                match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    channel.pools_said()
                })) {
                    Ok(None) => Some(Value::Str(ArmingWarning::Unmeasured.as_str().into())),
                    Ok(Some(Ok(said))) => Some(said),
                    _ => None,
                }
            }
            _ => Some(Value::Str(ArmingWarning::Unmeasured.as_str().into())),
        };
        if matches!(why, Some(Value::Bool(true))) {
            return Ok(());
        }
        let reason = why
            .and_then(|why| why.as_str_value().map(str::to_owned))
            .filter(|why| {
                ArmingWarning::ALL
                    .iter()
                    .any(|warning| warning.as_str() == why)
            });
        for capability in pooled {
            if let Some(definition) = self.registry.get(&capability) {
                self.paired(
                    JournalCode::Overruled,
                    definition,
                    Point::Concurrency,
                    &chooser.id,
                    record,
                    reason.as_deref(),
                )?;
            }
        }
        Ok(())
    }
}

/// `_preferred(point, chosen, answer, record, now)`: at P7, a person's Send now over an early look - where core would
/// carry the Send now out (its own schedule gate for a forced send passes).
fn preferred(point: Point, chosen: &Said, answer: &Said, record: Option<&Value>, now: f64) -> bool {
    point == Point::Schedule
        && chosen.is(Alternative::Early)
        && answer.is(Alternative::SendNow)
        && record
            .and_then(object)
            .is_some_and(|map| gate_schedule(map, now, None, false, true).0 == PASS)
}

/// The class a raise carries out of the runtime.
pub(crate) fn class_of(raised: &Raised) -> &'static str {
    match raised.class.as_str() {
        "AttributeError" => "AttributeError",
        "TypeError" => "TypeError",
        "ValueError" => "ValueError",
        "KeyError" => "KeyError",
        "RuntimeError" => "RuntimeError",
        "RecursionError" => "RecursionError",
        _ => "Exception",
    }
}

/// A text of a value (`isinstance(value, str)`).
pub(crate) trait StrValue {
    fn as_str_value(&self) -> Option<&str>;
}

impl StrValue for Value {
    fn as_str_value(&self) -> Option<&str> {
        match self {
            Value::Str(text) => text.as_str(),
            _ => None,
        }
    }
}
