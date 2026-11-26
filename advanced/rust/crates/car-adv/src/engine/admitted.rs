//! The four admission capabilities (seat S7.2e1b; `engine/admitted.py`): failures the standard edition never recovers
//! alone, taken up at P17 and answered again at P3 known_failure.
//!
//! * `structured_rules`: a failure nothing classified whose code a person's rule names is paced as the temporary kind
//!   the rule says (an AS_ word); `rule_for` and the hit (`taken`).
//! * `unknown_failure_budget`: a failure nothing classified, ADMIT while its task has tries left (the Attempts option);
//!   `taken` keeps a sample of shapes and counts, never a word.
//! * `codex_gave_up`: Codex giving up after its own retries, ADMIT twice a task at most.
//! * `sign_in_retry`: a sign-in failure, ADMIT once a task. Core hands a chain's `categories` as a tuple; car-engine
//!   hands it as an array, which is that tuple here (AUDIT-v0628.md).
//!
//! The one seam: [`Items`], `LocalSource(told home).turn_item_counts(thread, turn)` of the Codex home the watcher told
//! of (`inuse.told(paths)`); a code made from `paths` alone knows none (None, as where nothing was told).

use std::sync::Arc;

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_policy::classify::vocab_gen::failures;
use car_policy::plug::{Alternative, Point, paced_as};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::state::scoped::Scoped;
use crate::state::sql::{self, Row};
use crate::vocabulary::OptionKey;

pub const KNOWN_FAILURE: &str = "known_failure";
pub const ATTEMPTS: [i64; 5] = [1, 2, 3, 4, 5];
pub const DEFAULT_ATTEMPTS: i64 = 1;
pub const GAVE_UP: &str = "terminal_failure";
/// How many continuations a task of Codex giving up gets at most.
pub const GAVE_UP_TRIES: i64 = 2;
pub const SIGN_IN: &str = "terminal_auth";

/// `turn_item_counts(thread, turn)` of the told Codex home: counts by kind, or None.
pub type Items = Arc<dyn Fn(&Value, &Value) -> Value + Send + Sync>;

fn word(text: &str) -> Value {
    Value::Str(text.into())
}

fn is(value: &Value, text: &str) -> bool {
    matches!(value, Value::Str(held) if held.as_str() == Some(text))
}

/// `value.get(name)`: AttributeError where `value` is no dict.
fn got<'a>(value: &'a Value, name: &str) -> Result<&'a Value, Raised> {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => Ok(map.get(name).unwrap_or(&NULL)),
        _ => Err(Raised::new("AttributeError")),
    }
}

/// `AS_FOR[kind]`: the word that paces a failure as each temporary kind.
pub fn as_for(kind: &Value) -> Option<Alternative> {
    Alternative::ALL
        .iter()
        .copied()
        .find(|answer| paced_as(*answer).is_some_and(|paced| is(kind, paced)))
}

/// Whether `code` is one the product classifies (`failures.CODES`).
fn classified(code: &str) -> bool {
    match &failures::CODES {
        car_machine::vocab::Node::Map(pairs) => pairs.iter().any(|(name, _)| *name == code),
        _ => false,
    }
}

/// `matching(rules, code, status)`: the lowest-numbered rule that names `code` exactly and, where it has a range, holds
/// `status` - never one whose code the product has come to classify since. Err where a rule cannot be compared.
pub fn matching(rules: &[Row], code: &Value, status: &Value) -> Result<Option<Row>, Raised> {
    let Value::Str(code) = code else {
        return Ok(None);
    };
    if code.as_str().is_some_and(classified) {
        return Ok(None);
    }
    let mut sorted: Vec<&Row> = rules.iter().collect();
    let mut failed = None;
    sorted.sort_by(|a, b| {
        match car_machine::pyval::order(sql::get(a, "rule_id"), sql::get(b, "rule_id")) {
            Ok(Some(order)) => order,
            _ => {
                failed = Some(Raised::new("TypeError"));
                std::cmp::Ordering::Equal
            }
        }
    });
    if let Some(raised) = failed {
        return Err(raised);
    }
    let code = Value::Str(code.clone());
    for rule in sorted {
        if !sql::py_eq(sql::get(rule, "tag"), &code)
            || car_machine::pyval::truthy(sql::get(rule, "known"))
        {
            continue;
        }
        let (low, high) = (sql::get(rule, "status_from"), sql::get(rule, "status_to"));
        if matches!(low, Value::Null) {
            return Ok(Some(rule.clone()));
        }
        if let Value::Int(_) = status {
            let at_least = car_machine::pyval::order(low, status).map_err(Raised::new)?;
            let at_most = car_machine::pyval::order(status, high).map_err(Raised::new)?;
            if matches!(
                at_least,
                Some(std::cmp::Ordering::Less | std::cmp::Ordering::Equal)
            ) && matches!(
                at_most,
                Some(std::cmp::Ordering::Less | std::cmp::Ordering::Equal)
            ) {
                return Ok(Some(rule.clone()));
            }
        }
    }
    Ok(None)
}

fn answer(found: Option<Alternative>) -> Said {
    found.map_or(Said::Defer, Said::Word)
}

/// What the four share: their view of the state, given by `bind`.
struct Taking {
    binding: Option<Binding>,
}

impl Taking {
    fn with<R>(&self, f: impl FnOnce(&Scoped<'_>) -> R) -> Option<R> {
        self.binding.as_ref().and_then(|binding| binding.with(f))
    }
}

// ------------------------------------------------------------------ structured_rules

/// `StructuredRules(paths)`.
pub struct StructuredRules {
    pub paths: Paths,
    taking: Taking,
}

impl StructuredRules {
    /// `_rules()`: the rules as they stand; none where the state cannot be read.
    fn rules(&self) -> Vec<Row> {
        self.taking
            .with(|scoped| scoped.rules().unwrap_or_default())
            .unwrap_or_default()
    }
}

impl Code for StructuredRules {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.taking.binding = Some(binding);
        Some(Ok(()))
    }

    /// P17: the word of the rule this failure matches - only for one nothing classified - or DEFER.
    fn admission(&mut self, failure: &Value) -> Spoke {
        if !is(got(failure, "category")?, failures::UNKNOWN) {
            return Ok(Said::Defer);
        }
        let rule = matching(
            &self.rules(),
            got(failure, "code")?,
            got(failure, "status")?,
        )?;
        Ok(answer(
            rule.and_then(|rule| as_for(sql::get(&rule, "category"))),
        ))
    }

    fn rule_for(&mut self, facts: &Value, said: &Value) -> Option<Result<Value, Raised>> {
        let found = (|| -> Result<Value, Raised> {
            let rule = matching(&self.rules(), got(facts, "code")?, got(facts, "status")?)?;
            Ok(match rule {
                Some(rule)
                    if as_for(sql::get(&rule, "category"))
                        .is_some_and(|word| is(said, word.as_str())) =>
                {
                    sql::get(&rule, "rule_id").clone()
                }
                _ => Value::Null,
            })
        })();
        Some(found)
    }

    /// P3 known_failure: the word of the rule that took the record up, while it is there and still applies; HOLD
    /// where the state cannot be read.
    fn gate(&mut self, name: &Value, record: &Value, _facts: &Value) -> Spoke {
        if !is(name, KNOWN_FAILURE) || !is(got(record, "category")?, failures::UNKNOWN) {
            return Ok(Said::Defer);
        }
        let key = got(record, "interruption_id")?.clone();
        let Some(found) = self.taking.with(|scoped| -> Result<Said, ()> {
            let row = scoped.admission(&key).map_err(|_| ())?;
            let rules = scoped.rules().map_err(|_| ())?;
            let Some(row) = row else {
                return Ok(Said::Defer);
            };
            let rule = rules
                .into_iter()
                .find(|found| sql::py_eq(sql::get(found, "rule_id"), sql::get(&row, "rule_id")));
            Ok(match rule {
                Some(rule) if !car_machine::pyval::truthy(sql::get(&rule, "known")) => {
                    answer(as_for(sql::get(&rule, "category")))
                }
                _ => Said::Defer,
            })
        }) else {
            return Ok(Said::Defer);
        };
        Ok(found.unwrap_or(Said::Word(Alternative::Hold)))
    }

    fn taken(
        &mut self,
        _point: Point,
        _said: &Value,
        _arguments: &[&Value],
    ) -> Option<Result<Value, Raised>> {
        let mut map = Map::new();
        map.insert("code".into(), word("matched"));
        Some(Ok(Value::Object(map)))
    }
}

/// `make_structured_rules(paths)`.
pub fn make_structured_rules(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(StructuredRules {
        paths: paths.clone(),
        taking: Taking { binding: None },
    }))
}

// ------------------------------------------------------------------ unknown_failure_budget

/// `chain.get("recovery_attempts")` held to `limit`: Ok(true) where the task has tries left (or there is no chain).
fn tries_left(failure: &Value, limit: &Value) -> Result<bool, Raised> {
    let chain = got(failure, "chain")?;
    if matches!(chain, Value::Null) {
        return Ok(true);
    }
    let attempts = match chain {
        Value::Object(map) => map.get("recovery_attempts").cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    if !matches!(attempts, Value::Int(_)) {
        return Ok(false);
    }
    Ok(matches!(
        car_machine::pyval::order(&attempts, limit).map_err(Raised::new)?,
        Some(std::cmp::Ordering::Less)
    ))
}

fn number(value: &Value) -> bool {
    matches!(value, Value::Int(_) | Value::Float(_))
}

/// `completed - started` of two numbers, as Python subtracts them.
fn minus(completed: &Value, started: &Value) -> Value {
    match (completed, started) {
        (Value::Int(a), Value::Int(b)) => match (a.as_i64(), b.as_i64()) {
            (Some(a), Some(b)) => Value::from(a - b),
            _ => Value::Float(car_machine::pyval::minus(completed, started).unwrap_or(0.0)),
        },
        _ => Value::Float(car_machine::pyval::minus(completed, started).unwrap_or(0.0)),
    }
}

/// `UnknownFailureBudget(paths)`.
pub struct UnknownFailureBudget {
    pub paths: Paths,
    taking: Taking,
    items: Items,
}

impl UnknownFailureBudget {
    /// `_attempts()`: the person's choice, one by default.
    fn attempts(&self) -> Value {
        self.taking
            .with(|scoped| {
                scoped
                    .options()
                    .ok()
                    .map(|options| options.get(OptionKey::Attempts.as_str()).cloned())
            })
            .flatten()
            .flatten()
            .unwrap_or(Value::from(DEFAULT_ATTEMPTS))
    }
}

impl Code for UnknownFailureBudget {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.taking.binding = Some(binding);
        Some(Ok(()))
    }

    /// P17: ADMIT for a failure nothing classified while its task has tries left.
    fn admission(&mut self, failure: &Value) -> Spoke {
        if !is(got(failure, "category")?, failures::UNKNOWN) {
            return Ok(Said::Defer);
        }
        if matches!(got(failure, "chain")?, Value::Null) {
            return Ok(Said::Word(Alternative::Admit));
        }
        let limit = self.attempts();
        Ok(if tries_left(failure, &limit)? {
            Said::Word(Alternative::Admit)
        } else {
            Said::Defer
        })
    }

    /// P3 known_failure: ADMIT again for what it took up.
    fn gate(&mut self, name: &Value, record: &Value, _facts: &Value) -> Spoke {
        if !is(name, KNOWN_FAILURE) || !is(got(record, "category")?, failures::UNKNOWN) {
            return Ok(Said::Defer);
        }
        Ok(Said::Word(Alternative::Admit))
    }

    /// The sample, the first time core goes on: the shape its admission kept, the items the failed turn left, and how
    /// long the turn ran.
    fn taken(
        &mut self,
        _point: Point,
        _said: &Value,
        arguments: &[&Value],
    ) -> Option<Result<Value, Raised>> {
        let record = match arguments.get(1) {
            Some(record @ Value::Object(_)) => (*record).clone(),
            _ => Value::Object(Map::new()),
        };
        let field = |name: &str| got(&record, name).cloned().unwrap_or(Value::Null);
        let row = match self
            .taking
            .with(|scoped| scoped.admission(&field("interruption_id")))
        {
            None => None,
            Some(Ok(row)) => row,
            Some(Err(error)) => return Some(Err(Raised::new(error.class()))),
        };
        let mut found = Map::new();
        found.insert("code".into(), word("sampled"));
        let Some(row) = row else {
            return Some(Ok(Value::Object(found)));
        };
        let (started, completed) = (field("started_at"), field("completed_at"));
        let duration = if number(&started)
            && number(&completed)
            && matches!(
                car_machine::pyval::order(&completed, &started),
                Ok(Some(
                    std::cmp::Ordering::Greater | std::cmp::Ordering::Equal
                ))
            ) {
            minus(&completed, &started)
        } else {
            Value::Null
        };
        let mut sample = Map::new();
        sample.insert("code".into(), sql::get(&row, "tag").clone());
        sample.insert("status".into(), sql::get(&row, "status").clone());
        sample.insert("form".into(), sql::get(&row, "form").clone());
        sample.insert(
            "has_message".into(),
            Value::Bool(car_machine::pyval::eq(
                sql::get(&row, "has_words"),
                &Value::from(1),
            )),
        );
        sample.insert(
            "items".into(),
            (self.items)(&field("thread_id"), &field("turn_id")),
        );
        sample.insert("duration".into(), duration);
        found.insert("sample".into(), Value::Object(sample));
        Some(Ok(Value::Object(found)))
    }
}

/// `make_unknown_failure_budget(paths)`: no Codex home told here, so no items.
pub fn make_unknown_failure_budget(paths: &Paths) -> Option<Box<dyn Code>> {
    make_unknown_failure_budget_with(paths, Arc::new(|_, _| Value::Null))
}

/// `UnknownFailureBudget(paths)` with an entry point's own reader of the told home's items.
pub fn make_unknown_failure_budget_with(paths: &Paths, items: Items) -> Option<Box<dyn Code>> {
    Some(Box::new(UnknownFailureBudget {
        paths: paths.clone(),
        taking: Taking { binding: None },
        items,
    }))
}

// ------------------------------------------------------------------ codex_gave_up

/// `CodexGaveUp(paths)`.
pub struct CodexGaveUp {
    pub paths: Paths,
    taking: Taking,
}

impl Code for CodexGaveUp {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.taking.binding = Some(binding);
        Some(Ok(()))
    }

    /// P17: ADMIT while the task it continues has had fewer than two continuations.
    fn admission(&mut self, failure: &Value) -> Spoke {
        if !is(got(failure, "category")?, GAVE_UP) {
            return Ok(Said::Defer);
        }
        Ok(if tries_left(failure, &Value::from(GAVE_UP_TRIES))? {
            Said::Word(Alternative::Admit)
        } else {
            Said::Defer
        })
    }

    /// P3 known_failure: ADMIT again for what it took up.
    fn gate(&mut self, name: &Value, record: &Value, _facts: &Value) -> Spoke {
        if !is(name, KNOWN_FAILURE) || !is(got(record, "category")?, GAVE_UP) {
            return Ok(Said::Defer);
        }
        Ok(Said::Word(Alternative::Admit))
    }
}

/// `make_codex_gave_up(paths)`.
pub fn make_codex_gave_up(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(CodexGaveUp {
        paths: paths.clone(),
        taking: Taking { binding: None },
    }))
}

// ------------------------------------------------------------------ sign_in_retry

/// `SignInRetry(paths)`.
pub struct SignInRetry {
    pub paths: Paths,
    taking: Taking,
}

impl Code for SignInRetry {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.taking.binding = Some(binding);
        Some(Ok(()))
    }

    /// P17: ADMIT once a task - never for a task that had a sign-in failure already, nor where that cannot be read.
    fn admission(&mut self, failure: &Value) -> Spoke {
        if !is(got(failure, "category")?, SIGN_IN) {
            return Ok(Said::Defer);
        }
        let chain = got(failure, "chain")?;
        if matches!(chain, Value::Null) {
            return Ok(Said::Word(Alternative::Admit));
        }
        let Value::Object(map) = chain else {
            return Ok(Said::Defer);
        };
        if map
            .get("category")
            .is_some_and(|category| is(category, SIGN_IN))
        {
            return Ok(Said::Defer);
        }
        Ok(match map.get("categories") {
            Some(Value::Array(kinds)) if !kinds.iter().any(|kind| is(kind, SIGN_IN)) => {
                Said::Word(Alternative::Admit)
            }
            _ => Said::Defer,
        })
    }

    /// P3 known_failure: ADMIT again for what it took up.
    fn gate(&mut self, name: &Value, record: &Value, _facts: &Value) -> Spoke {
        if !is(name, KNOWN_FAILURE) || !is(got(record, "category")?, SIGN_IN) {
            return Ok(Said::Defer);
        }
        Ok(Said::Word(Alternative::Admit))
    }
}

/// `make_sign_in_retry(paths)`.
pub fn make_sign_in_retry(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(SignInRetry {
        paths: paths.clone(),
        taking: Taking { binding: None },
    }))
}
