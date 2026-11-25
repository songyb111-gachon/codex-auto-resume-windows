//! `registry.*`: the shipped definitions, the rules a definition keeps, the registry that holds them.

use car_adv::jsonx::{int, object, text, texts};
use car_adv::measured::Table;
use car_adv::registry::{self, CapabilityDef, Registry};
use car_adv::vocabulary::{Measurement, Verdict, parse};
use car_machine::json::Value;
use car_policy::plug::Point;

use crate::defs;
use crate::util::{Failure, Out, arg, bad, flag, list, number, text as as_text};

fn definitions_of(value: &Value) -> Result<Vec<CapabilityDef>, Failure> {
    list(value)?.iter().map(defs::from_json).collect()
}

/// A table of measurements: `[[measurement, verdict, engine], ...]`.
pub fn table_of(value: &Value) -> Result<Table, Failure> {
    let mut table = Table::new();
    for row in list(value)? {
        let row = list(row)?;
        let measurement: Measurement = parse(as_text(arg(row, 0)?)?).ok_or_else(bad)?;
        let verdict: Verdict = parse(as_text(arg(row, 1)?)?).ok_or_else(bad)?;
        table.insert(measurement, (verdict, as_text(arg(row, 2)?)?.to_owned()));
    }
    Ok(table)
}

fn dump(registry: &Registry) -> Value {
    Value::Array(registry.iter().map(defs::to_json).collect())
}

fn ids_of(found: &[&CapabilityDef]) -> Value {
    texts(
        &found
            .iter()
            .map(|each| each.id.as_str())
            .collect::<Vec<_>>(),
    )
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "registry.constants" => Ok(object([
            ("GLOBAL_HOURLY", int(registry::GLOBAL_HOURLY)),
            ("CORE_DAILY_CAP", int(registry::CORE_DAILY_CAP)),
            (
                "CORE_COOLDOWN_SECONDS",
                int(registry::CORE_COOLDOWN_SECONDS),
            ),
            ("SHOWN_ORDER", texts(registry::SHOWN_ORDER)),
            ("CAPABILITY_POINTS", {
                let mut names: Vec<&str> = registry::capability_points()
                    .iter()
                    .map(|point| point.as_str())
                    .collect();
                names.sort_unstable();
                texts(&names)
            }),
        ])),
        "registry.definitions" => Ok(Value::Array(
            registry::definitions().iter().map(defs::to_json).collect(),
        )),
        "registry.waiting" => Ok(Value::Array(
            registry::waiting()
                .iter()
                .map(|(definition, needs)| {
                    Value::Array(vec![
                        defs::to_json(definition),
                        texts(&needs.iter().map(|each| each.as_str()).collect::<Vec<_>>()),
                    ])
                })
                .collect(),
        )),
        "registry.installed_only" => Ok(Value::Array(
            registry::installed_only()
                .iter()
                .map(defs::to_json)
                .collect(),
        )),
        // The registry this edition runs for a table of measurements and an installation (or not).
        "registry.shipped" => {
            let table = table_of(arg(args, 0)?)?;
            let made = match registry::registry_for(&table, flag(arg(args, 1)?)?) {
                Ok(made) => made,
                Err(refused) => return Ok(object([("refused", text(&refused.0))])),
            };
            Ok(object([
                ("ids", texts(&made.ids())),
                ("shown", ids_of(&registry::shown(&made))),
                ("definitions", dump(&made)),
            ]))
        }
        "registry.offered" => {
            let table = table_of(arg(args, 0)?)?;
            Ok(texts(
                &registry::offered(&table)
                    .iter()
                    .map(|each| each.id.as_str())
                    .collect::<Vec<_>>(),
            ))
        }
        "registry.shapes" => {
            let probe = as_text(arg(args, 0)?)?;
            Ok(object([
                ("id", Value::Bool(registry::id_shape(probe))),
                ("prefix", Value::Bool(registry::prefix_shape(probe))),
                ("code", Value::Bool(registry::code_shape(probe))),
            ]))
        }
        "registry.problems" => Ok(texts(&registry::problems(&defs::from_json(arg(args, 0)?)?))),
        // [definition, key, value]: takes() of the option of that key, or null where the capability has none.
        "registry.option" => {
            let definition = defs::from_json(arg(args, 0)?)?;
            let key = parse(as_text(arg(args, 1)?)?).ok_or_else(bad)?;
            let value = number(arg(args, 2)?)?;
            Ok(match definition.option(key) {
                Some(option) => Value::Bool(option.takes(value)),
                None => Value::Null,
            })
        }
        "registry.code" => {
            let definition = defs::from_json(arg(args, 0)?)?;
            Ok(match definition.code(as_text(arg(args, 1)?)?) {
                Some(found) => text(&found),
                None => Value::Null,
            })
        }
        // [definitions]: a registry made of them, and what it answers about itself.
        "registry.make" => {
            let made = match Registry::new(definitions_of(arg(args, 0)?)?) {
                Ok(made) => made,
                Err(refused) => return Ok(object([("refused", text(&refused.0))])),
            };
            let mut requires = Vec::new();
            let mut required_by = Vec::new();
            let mut names: Vec<&str> = made.ids();
            names.push("no_such_capability");
            for id in names {
                requires.push(object([
                    ("id", text(id)),
                    ("requires", texts(&made.requires(id))),
                ]));
                required_by.push(object([
                    ("id", text(id)),
                    ("required_by", texts(&made.required_by(id))),
                ]));
            }
            let at: Vec<Value> = Point::ALL
                .iter()
                .map(|point| {
                    object([
                        ("point", text(point.as_str())),
                        ("at", ids_of(&made.at(*point))),
                    ])
                })
                .collect();
            Ok(object([
                ("ids", texts(&made.ids())),
                ("len", int(made.len() as i64)),
                ("requires", Value::Array(requires)),
                ("required_by", Value::Array(required_by)),
                ("at", Value::Array(at)),
                ("shown", ids_of(&registry::shown(&made))),
                (
                    "get_missing",
                    Value::Bool(made.get("no_such_capability").is_none()),
                ),
            ]))
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}
