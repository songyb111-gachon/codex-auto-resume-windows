//! What the store asks of the capability registry (`crate::registry`, S7.1b's port of `registry.py`).
//!
//! The reference's state calls `registry.get(x)` and a definition's `option`, `code`, `takes` and `in` tests with whatever
//! the wire gave it, a value of any type: only a `str` that names one is a hit. The registry port is typed (a `&str` id, an
//! `OptionKey`, a number), so these are the same questions asked of a `Value`, kept here so that `registry` stays the tag's
//! module and the state's callers read as the reference does.

use car_machine::json::Value;

use crate::registry::{CapabilityDef, OptionDef, Registry};
use crate::vocabulary::{ClosedWord, OptionKey};

/// `registry.get(capability)` for a value of any type.
pub trait RegistryAsked {
    /// The definition of an id the registry holds, `None` for anything else (a non-`str` included).
    fn get_value(&self, capability: &Value) -> Option<&CapabilityDef>;
}

impl RegistryAsked for Registry {
    fn get_value(&self, capability: &Value) -> Option<&CapabilityDef> {
        let Value::Str(id) = capability else {
            return None;
        };
        self.get(id.as_str()?)
    }
}

/// A definition's questions, asked of a `Value`.
pub trait DefinitionAsked {
    /// `option(key)`: the choice of `key` it offers (`option.key == key`: only a `str` equal to it).
    fn option_of(&self, key: &Value) -> Option<&OptionDef>;
    /// `word in codes`.
    fn has_code(&self, word: &Value) -> bool;
    /// `code(word)`: `<prefix>.<word>` for one of its own codes, or `None`.
    fn code_of(&self, word: &Value) -> Option<String>;
    /// `rule in departs_from`.
    fn departs(&self, rule: &str) -> bool;
    /// `point in points`.
    fn has_point(&self, point: car_policy::plug::Point) -> bool;
    /// `key in wordings`.
    fn keeps_wording(&self, key: &Value) -> bool;
}

fn word_of(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

impl DefinitionAsked for CapabilityDef {
    fn option_of(&self, key: &Value) -> Option<&OptionDef> {
        let key = crate::vocabulary::parse::<OptionKey>(word_of(key)?)?;
        self.option(key)
    }

    fn has_code(&self, word: &Value) -> bool {
        word_of(word).is_some_and(|text| self.codes.iter().any(|code| code == text))
    }

    fn code_of(&self, word: &Value) -> Option<String> {
        self.has_code(word)
            .then(|| self.code(word_of(word)?))
            .flatten()
    }

    fn departs(&self, rule: &str) -> bool {
        self.departs_from.iter().any(|each| each == rule)
    }

    fn has_point(&self, point: car_policy::plug::Point) -> bool {
        self.points.contains(&point)
    }

    fn keeps_wording(&self, key: &Value) -> bool {
        word_of(key).is_some_and(|text| self.wordings.iter().any(|each| each.word() == text))
    }
}

/// `OptionDef.takes(value)`: one of its choices, or a whole number in its custom range - `type(value) is int` first.
pub fn takes(option: &OptionDef, value: &Value) -> bool {
    let Value::Int(number) = value else {
        return false;
    };
    number.as_i64().is_some_and(|number| option.takes(number))
}
