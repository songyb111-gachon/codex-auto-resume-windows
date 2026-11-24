//! The closed vocabularies, as data the Rust side holds beside the Python's (`build/vocab_export.py`).
//!
//! The generated files (`vocab_gen.rs` in this crate, car-config and car-words) are written by
//! `tests/rustdiff/gen_vocab.py` from the tag's `vocab.json`; this module is what they are made of and
//! what [`export`] writes them back out as, in the exporter's own structure, so a difference with the tag
//! is a difference of bytes.

use crate::json::{Map, Str, Value};

/// A constant that is not a plain string or a list of strings: a dict, or lists in lists.
#[derive(Debug)]
pub enum Node {
    Str(&'static str),
    List(&'static [Node]),
    Map(&'static [(&'static str, Node)]),
}

impl Node {
    pub fn to_value(&self) -> Value {
        match self {
            Node::Str(text) => Value::from(*text),
            Node::List(items) => Value::Array(items.iter().map(Node::to_value).collect()),
            Node::Map(pairs) => {
                let mut map = Map::new();
                for (key, item) in *pairs {
                    map.insert(Str::from(*key), item.to_value());
                }
                Value::Object(map)
            }
        }
    }

    /// The text of a `Node::Str`.
    pub fn as_str(&self) -> Option<&'static str> {
        match self {
            Node::Str(text) => Some(text),
            _ => None,
        }
    }

    /// The members of a `Node::List`.
    pub fn items(&self) -> &'static [Node] {
        match self {
            Node::List(items) => items,
            _ => &[],
        }
    }

    /// The value under `key` of a `Node::Map`.
    pub fn get(&self, key: &str) -> Option<&'static Node> {
        match self {
            Node::Map(pairs) => pairs
                .iter()
                .find(|(name, _)| *name == key)
                .map(|(_, node)| node),
            _ => None,
        }
    }
}

/// One constant of a Python module.
#[derive(Debug)]
pub enum Const {
    Str(&'static str),
    Strs(&'static [&'static str]),
    Node(&'static Node),
}

/// A Python `enum.StrEnum`: its members in definition order, as (name, value).
#[derive(Debug)]
pub struct EnumDef {
    pub name: &'static str,
    pub base: &'static str,
    pub members: &'static [(&'static str, &'static str)],
}

/// One Python module's enums and constants.
#[derive(Debug)]
pub struct ModuleDef {
    pub name: &'static str,
    pub enums: &'static [EnumDef],
    pub constants: &'static [(&'static str, Const)],
}

impl ModuleDef {
    /// `{"enums": {...}, "constants": {...}}` as the exporter writes a module (a part with nothing in
    /// it is left out).
    pub fn export(&self) -> Value {
        let mut module = Map::new();
        if !self.enums.is_empty() {
            let mut enums = Map::new();
            for found in self.enums {
                let mut entry = Map::new();
                entry.insert("base".into(), Value::from(found.base));
                let members = found
                    .members
                    .iter()
                    .map(|(name, value)| {
                        Value::Array(vec![Value::from(*name), Value::from(*value)])
                    })
                    .collect();
                entry.insert("members".into(), Value::Array(members));
                enums.insert(Str::from(found.name), Value::Object(entry));
            }
            module.insert("enums".into(), Value::Object(enums));
        }
        if !self.constants.is_empty() {
            let mut constants = Map::new();
            for (name, value) in self.constants {
                let value = match value {
                    Const::Str(text) => Value::from(*text),
                    Const::Strs(items) => {
                        Value::Array(items.iter().map(|each| Value::from(*each)).collect())
                    }
                    Const::Node(node) => node.to_value(),
                };
                constants.insert(Str::from(*name), value);
            }
            module.insert("constants".into(), Value::Object(constants));
        }
        Value::Object(module)
    }
}

/// `{module: export}` for each of `modules`, in the order given.
pub fn export(modules: &[&[ModuleDef]]) -> Value {
    let mut all = Map::new();
    for group in modules {
        for module in *group {
            all.insert(Str::from(module.name), module.export());
        }
    }
    Value::Object(all)
}
