//! `compatdata`'s ops: `cd.validate`, `cd.read`, `cd.adopt`, `cd.in_force`, `cd.overlay`, `cd.table_for`, `cd.summary`,
//! `cd.dumps`, `cd.slug`, `cd.evidence_path`, `cd.product`.

use std::path::{Path, PathBuf};

use car_adv::compatdata::{self, Document, Product};
use car_adv::jsonx::object;
use car_adv::measured::{self, Table};
use car_adv::vocabulary::{Measurement, Verdict, parse};
use car_machine::json::{Map, Value};

use crate::{Context, Failure, Out, arg, bad, float, maybe_text, text};

fn hex(value: &Value) -> Result<Vec<u8>, Failure> {
    let text = text(value)?;
    (0..text.len() / 2)
        .map(|at| u8::from_str_radix(&text[at * 2..at * 2 + 2], 16).map_err(|_| bad()))
        .collect()
}

/// A case's product: `null` is the reference's own `this_product()` (the product version the probe is told), a list the
/// tuple handed in, `"none"` a product whose version could not be read.
fn product(context: &Context, value: &Value) -> Result<Option<Product>, Failure> {
    match value {
        Value::Null => Ok(compatdata::this_product(&context.product_version)),
        Value::Str(word) if word.as_bytes() == b"none" => Ok(None),
        Value::Array(parts) if parts.len() == 3 => {
            let part = |at: usize| match &parts[at] {
                Value::Int(n) => n.as_i64().ok_or_else(bad),
                _ => Err(bad()),
            };
            Ok(Some((part(0)?, part(1)?, part(2)?)))
        }
        _ => Err(bad()),
    }
}

pub fn document(found: Option<&Document>) -> Value {
    let Some(found) = found else {
        return Value::Null;
    };
    let engines: Map = found
        .engines
        .iter()
        .map(|(version, verdicts)| {
            let inner: Map = verdicts
                .iter()
                .map(|(measurement, (verdict, recorded))| {
                    (
                        measurement.as_str().into(),
                        Value::Array(vec![Value::from(verdict.as_str()), Value::Float(*recorded)]),
                    )
                })
                .collect();
            (version.clone(), Value::Object(inner))
        })
        .collect();
    object([
        ("sequence", Value::from(found.sequence)),
        ("published_at", Value::Float(found.published_at)),
        ("expires_at", Value::Float(found.expires_at)),
        ("engines", Value::Object(engines)),
    ])
}

/// A table as the diffs write one: `[[measurement, verdict, engine], ...]`.
pub fn table_in(value: &Value) -> Result<Table, Failure> {
    let Value::Array(rows) = value else {
        return Err(bad());
    };
    let mut table = Table::new();
    for row in rows {
        let Value::Array(parts) = row else {
            return Err(bad());
        };
        let measurement = parse::<Measurement>(&text(arg(parts, 0))?).ok_or_else(bad)?;
        let verdict = parse::<Verdict>(&text(arg(parts, 1))?).ok_or_else(bad)?;
        table.insert(measurement, (verdict, text(arg(parts, 2))?));
    }
    Ok(table)
}

pub fn table_out(table: &Table) -> Value {
    let mut rows: Vec<(&str, Value)> = table
        .iter()
        .map(|(measurement, (verdict, engine))| {
            (
                measurement.as_str(),
                Value::Array(vec![
                    Value::from(measurement.as_str()),
                    Value::from(verdict.as_str()),
                    Value::from(engine.as_str()),
                ]),
            )
        })
        .collect();
    rows.sort_by(|a, b| a.0.cmp(b.0));
    Value::Array(rows.into_iter().map(|(_, row)| row).collect())
}

fn path(value: &Value) -> Result<Option<PathBuf>, Failure> {
    Ok(maybe_text(value)?.map(PathBuf::from))
}

pub fn run(context: &Context, op: &str, args: &[Value]) -> Out {
    match op {
        "cd.validate" => {
            let raw = hex(arg(args, 0))?;
            Ok(
                match compatdata::validate(&raw, product(context, arg(args, 1))?) {
                    Ok(found) => document(Some(&found)),
                    Err(refused) => object([("refused", Value::from(refused.0))]),
                },
            )
        }
        "cd.read" => {
            let at = path(arg(args, 0))?.ok_or_else(bad)?;
            Ok(document(
                compatdata::read(&at, product(context, arg(args, 1))?).as_ref(),
            ))
        }
        "cd.adopt" => {
            let folder = path(arg(args, 0))?.ok_or_else(bad)?;
            let bundled = path(arg(args, 1))?;
            compatdata::adopt(
                &folder,
                bundled.as_deref(),
                float(arg(args, 2))?,
                product(context, arg(args, 3))?,
            );
            Ok(Value::Null)
        }
        "cd.in_force" => {
            let folder = path(arg(args, 0))?;
            let bundled = path(arg(args, 1))?;
            let found = compatdata::in_force(
                folder.as_deref(),
                bundled.as_deref(),
                float(arg(args, 2))?,
                product(context, arg(args, 3))?,
            );
            Ok(document(found.as_ref()))
        }
        "cd.overlay" => {
            let table = table_in(arg(args, 0))?;
            let found = match arg(args, 1) {
                Value::Null => None,
                raw => compatdata::validate(&hex(raw)?, product(context, arg(args, 2))?).ok(),
            };
            let engine = match arg(args, 3) {
                Value::Str(engine) => engine.as_str(),
                _ => None,
            };
            Ok(table_out(&compatdata::overlay(
                &table,
                found.as_ref(),
                engine,
            )))
        }
        "cd.table_for" => {
            let folder = path(arg(args, 0))?;
            let engine = match arg(args, 1) {
                Value::Str(engine) => engine.as_str(),
                _ => None,
            };
            let table = match arg(args, 2) {
                Value::Null => measured::table(),
                other => table_in(other)?,
            };
            let product = compatdata::this_product(&context.product_version);
            Ok(table_out(&compatdata::table_for(
                folder.as_deref(),
                engine,
                &table,
                float(arg(args, 3))?,
                product,
            )))
        }
        "cd.summary" => {
            let found = match arg(args, 0) {
                Value::Null => None,
                raw => compatdata::validate(&hex(raw)?, product(context, arg(args, 1))?).ok(),
            };
            Ok(compatdata::summary(found.as_ref()))
        }
        "cd.dumps" => compatdata::dumps(arg(args, 0))
            .map(Value::from)
            .ok_or_else(|| Failure::new("RecursionError")),
        "cd.slug" => Ok(Value::from(compatdata::slug(&text(arg(args, 0))?))),
        "cd.evidence_path" => Ok(Value::from(compatdata::evidence_path(
            &text(arg(args, 0))?,
            &text(arg(args, 1))?,
        ))),
        "cd.product" => Ok(match compatdata::this_product(&text(arg(args, 0))?) {
            Some((a, b, c)) => Value::Array(vec![a.into(), b.into(), c.into()]),
            None => Value::Null,
        }),
        "cd.files" => {
            // Every file left in a folder, by name, with its bytes as hex: what an adopt or a read left behind.
            let folder = path(arg(args, 0))?.ok_or_else(bad)?;
            Ok(listing(&folder))
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}

pub fn listing(folder: &Path) -> Value {
    let mut names: Vec<(String, Value)> = std::fs::read_dir(folder)
        .map(|entries| {
            entries
                .flatten()
                .map(|entry| {
                    let bytes = std::fs::read(entry.path()).ok();
                    let shown = bytes.map_or(Value::Null, |bytes| {
                        Value::from(bytes.iter().map(|b| format!("{b:02x}")).collect::<String>())
                    });
                    (entry.file_name().to_string_lossy().into_owned(), shown)
                })
                .collect()
        })
        .unwrap_or_default();
    names.sort_by(|a, b| a.0.cmp(&b.0));
    Value::Object(
        names
            .into_iter()
            .map(|(name, value)| (name.into(), value))
            .collect(),
    )
}
