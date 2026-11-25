//! `statement.*`: the catalogs of a directory, the keys, and the statement a definition shows.

use car_adv::jsonx::{object, text, texts};
use car_adv::statement::{self, Catalogs, Undecodable};
use car_adv::vocabulary::{ArmingWarning, Field, parse};
use car_machine::json::Value;

use crate::defs;
use crate::util::{Failure, Out, arg, bad, flag, list, maybe_text, number, text as as_text};

fn catalogs(directory: &str, current: &str) -> Catalogs {
    let current = current.to_owned();
    Catalogs::new(directory, Box::new(move || current.clone()))
}

/// What the tag raises where a catalog is not UTF-8.
fn undecodable(_: Undecodable) -> Failure {
    Failure::new(Undecodable::CLASS)
}

fn dump(catalog: &car_words::l10n::Catalog) -> Value {
    Value::Array(
        catalog
            .iter()
            .map(|(key, value)| Value::Array(vec![text(key), text(value)]))
            .collect(),
    )
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "statement.keys" => {
            let capability = as_text(arg(args, 0)?)?;
            let fields: Vec<Value> = Field::ALL
                .iter()
                .map(|field| {
                    object([
                        ("key", text(&statement::key(capability, *field))),
                        ("title", text(&statement::title_key(*field))),
                    ])
                })
                .collect();
            let warnings: Vec<Value> = ArmingWarning::ALL
                .iter()
                .map(|warning| text(&statement::warning_key(*warning)))
                .collect();
            Ok(object([
                ("fields", Value::Array(fields)),
                ("warnings", Value::Array(warnings)),
                ("name", text(&statement::name_key(capability))),
                ("PAGE_KEYS", texts(statement::PAGE_KEYS)),
                ("CONTINUATION_KEYS", texts(statement::CONTINUATION_KEYS)),
                ("EDITION_KEYS", texts(statement::EDITION_KEYS)),
                ("WARNING_KEYS", texts(statement::WARNING_KEYS)),
            ]))
        }
        // [directory, current, locale|null] -> the catalog (every key in order) and the words.
        "statement.catalog" => {
            let found = catalogs(as_text(arg(args, 0)?)?, as_text(arg(args, 1)?)?);
            let locale = maybe_text(arg(args, 2)?)?;
            let table = found
                .catalog(locale.unwrap_or(as_text(arg(args, 1)?)?))
                .map_err(undecodable)?;
            let words = found.words(locale).map_err(undecodable)?;
            Ok(object([("catalog", dump(&table)), ("words", dump(&words))]))
        }
        // [directory, current, name, locale|null, fields] -> text or null.
        "statement.text" => {
            let found = catalogs(as_text(arg(args, 0)?)?, as_text(arg(args, 1)?)?);
            let mut fields: Vec<(String, String)> = Vec::new();
            for pair in list(arg(args, 4)?)? {
                let pair = list(pair)?;
                fields.push((
                    as_text(arg(pair, 0)?)?.to_owned(),
                    as_text(arg(pair, 1)?)?.to_owned(),
                ));
            }
            let fields: Vec<(&str, String)> = fields
                .iter()
                .map(|(name, value)| (name.as_str(), value.clone()))
                .collect();
            let done = found
                .text(as_text(arg(args, 2)?)?, maybe_text(arg(args, 3)?)?, &fields)
                .map_err(undecodable)?;
            Ok(done.map_or(Value::Null, |done| text(&done)))
        }
        // [directory, current, on, locale|null, loaded]
        "statement.badge" => {
            let found = catalogs(as_text(arg(args, 0)?)?, as_text(arg(args, 1)?)?);
            let done = found
                .badge(
                    number(arg(args, 2)?)?,
                    maybe_text(arg(args, 3)?)?,
                    flag(arg(args, 4)?)?,
                )
                .map_err(undecodable)?;
            Ok(done.map_or(Value::Null, |done| text(&done)))
        }
        // [directory, current, definition] -> missing, and complete_in for every locale and a stranger.
        "statement.missing" => {
            let found = catalogs(as_text(arg(args, 0)?)?, as_text(arg(args, 1)?)?);
            let definition = defs::from_json(arg(args, 2)?)?;
            let mut complete: Vec<Value> = Vec::new();
            for locale in car_words::l10n::LOCALES.iter().chain(["xx"].iter()) {
                let held = found
                    .complete_in(&definition, locale)
                    .map_err(undecodable)?;
                complete.push(Value::Array(vec![text(locale), Value::Bool(held)]));
            }
            let missing: Vec<Value> = found
                .missing(&definition)
                .map_err(undecodable)?
                .iter()
                .map(|(locale, field)| Value::Array(vec![text(locale), text(field)]))
                .collect();
            Ok(object([
                ("missing", Value::Array(missing)),
                ("complete_in", Value::Array(complete)),
            ]))
        }
        // [directory, current, definition, locale|null, warnings] -> the statement.
        "statement.statement" => {
            let found = catalogs(as_text(arg(args, 0)?)?, as_text(arg(args, 1)?)?);
            let definition = defs::from_json(arg(args, 2)?)?;
            let mut warnings = Vec::new();
            for word in list(arg(args, 4)?)? {
                warnings.push(parse::<ArmingWarning>(as_text(word)?).ok_or_else(bad)?);
            }
            found
                .statement(&definition, maybe_text(arg(args, 3)?)?, &warnings)
                .map_err(undecodable)
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}
