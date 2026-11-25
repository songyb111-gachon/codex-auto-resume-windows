//! SEAM (seat S7.1a): the registry as the advanced store asks it - `registry.get(id)` and the few facts of a
//! definition the state, the ledger and the watch log read. Seat S7.1b ports `registry.py` into car-adv beside this
//! seat; the integration implements [`Registry`] over its `REGISTRY` (or replaces this module), and
//! `registry_gen.rs`, the tag's table, goes.

use car_machine::json::Value;

use super::registry_gen::SHIPPED;

/// One choice a capability offers (`registry.Option`).
#[derive(Clone, Copy, Debug)]
pub struct OptionDef {
    pub key: &'static str,
    /// The values it may take: whole numbers from 1, smallest first.
    pub choices: &'static [i64],
    pub default: i64,
    /// (lowest, highest) a person may type in beside the choices, or None.
    pub custom: Option<(i64, i64)>,
}

impl OptionDef {
    /// `takes(value)`: one of its choices, or a whole number in its custom range - `type(value) is int` first.
    pub fn takes(&self, value: &Value) -> bool {
        let Value::Int(number) = value else {
            return false;
        };
        let Some(number) = number.as_i64() else {
            return false;
        };
        self.choices.contains(&number)
            || self
                .custom
                .is_some_and(|(low, high)| low <= number && number <= high)
    }
}

/// What the store reads of one capability (`registry.CapabilityDef`).
#[derive(Clone, Copy, Debug)]
pub struct Definition {
    pub id: &'static str,
    /// Its points, sorted (a frozenset in the reference).
    pub points: &'static [&'static str],
    pub departs_from: &'static [&'static str],
    /// (per_day, per_conversation), or None for an action.
    pub ceilings: Option<(i64, i64)>,
    pub journal_prefix: &'static str,
    pub codes: &'static [&'static str],
    pub options: &'static [OptionDef],
    pub rules_editor: bool,
    pub samples: bool,
    pub resends: bool,
    pub wordings: &'static [&'static str],
}

impl Definition {
    /// `option(key)`: the choice of `key` it offers, or None (`option.key == key`: only a `str` equal to it).
    pub fn option(&self, key: &Value) -> Option<&OptionDef> {
        let Value::Str(key) = key else {
            return None;
        };
        let key = key.as_str()?;
        self.options.iter().find(|option| option.key == key)
    }

    /// `word in codes`.
    pub fn has_code(&self, word: &Value) -> bool {
        matches!(word, Value::Str(text) if text.as_str().is_some_and(|text| self.codes.contains(&text)))
    }

    /// `code(word)`: `<prefix>.<word>` for one of its own codes, or None.
    pub fn code(&self, word: &Value) -> Option<String> {
        if !self.has_code(word) {
            return None;
        }
        let Value::Str(text) = word else {
            return None;
        };
        Some(format!(
            "{}.{}",
            self.journal_prefix,
            text.as_str().unwrap_or_default()
        ))
    }

    /// `rule in departs_from`.
    pub fn departs(&self, rule: &str) -> bool {
        self.departs_from.contains(&rule)
    }

    /// `point in points`.
    pub fn has_point(&self, point: &str) -> bool {
        self.points.contains(&point)
    }

    /// `key in wordings`.
    pub fn keeps_wording(&self, key: &Value) -> bool {
        matches!(key, Value::Str(text) if text.as_str().is_some_and(|text| self.wordings.contains(&text)))
    }
}

/// A closed set of capabilities (`registry.Registry`): `get` and the definitions in order.
pub trait Registry: Send + Sync {
    /// Every definition, in the registry's order (`iter(registry)`).
    fn definitions(&self) -> &[Definition];

    /// `get(capability)`: the definition of an id it holds, None for anything else (a non-`str` included).
    fn get(&self, capability: &Value) -> Option<&Definition> {
        let Value::Str(id) = capability else {
            return None;
        };
        let id = id.as_str()?;
        self.definitions()
            .iter()
            .find(|definition| definition.id == id)
    }

    /// `get` by a word the code holds.
    fn by_id(&self, capability: &str) -> Option<&Definition> {
        self.definitions()
            .iter()
            .find(|definition| definition.id == capability)
    }
}

/// The capabilities the tag ships (`registry.REGISTRY`).
#[derive(Clone, Copy, Debug, Default)]
pub struct Shipped;

impl Registry for Shipped {
    fn definitions(&self) -> &[Definition] {
        SHIPPED
    }
}

/// A registry of the given definitions (a test's, the diffs' "nothing offered").
#[derive(Clone, Debug, Default)]
pub struct Listed(pub Vec<Definition>);

impl Registry for Listed {
    fn definitions(&self) -> &[Definition] {
        &self.0
    }
}
