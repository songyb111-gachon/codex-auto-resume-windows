//! A capability's definition as JSON (the shape `gen_advpolicy.py` dumps, and the diffs make mutants of), both ways.

use car_adv::jsonx::{int, maybe_text, object, text, texts};
use car_adv::registry::{CapabilityDef, Ceilings, OptionDef};
use car_adv::vocabulary::{CapabilityKind, ClosedWord, Measurement, OptionKey, WordingKey, parse};
use car_machine::json::Value;
use car_policy::plug::Point;

use crate::util::{
    Failure, arg, bad, flag, list, map, maybe_text as opt_text, number, text as as_text,
    texts as as_texts,
};

fn word<W: ClosedWord>(value: &Value) -> Result<W, Failure> {
    parse::<W>(as_text(value)?).ok_or_else(bad)
}

pub fn from_json(value: &Value) -> Result<CapabilityDef, Failure> {
    let fields = map(value)?;
    let get = |name: &str| fields.get(name).ok_or_else(bad);
    let ceilings = match get("ceilings")? {
        Value::Null => None,
        other => {
            let pair = list(other)?;
            Some(Ceilings {
                per_day: number(arg(pair, 0)?)?,
                per_conversation: number(arg(pair, 1)?)?,
            })
        }
    };
    let mut options = Vec::new();
    for each in list(get("options")?)? {
        let each = map(each)?;
        let custom = match each.get("custom").ok_or_else(bad)? {
            Value::Null => None,
            other => {
                let pair = list(other)?;
                Some((number(arg(pair, 0)?)?, number(arg(pair, 1)?)?))
            }
        };
        options.push(OptionDef {
            key: word::<OptionKey>(each.get("key").ok_or_else(bad)?)?,
            choices: list(each.get("choices").ok_or_else(bad)?)?
                .iter()
                .map(number)
                .collect::<Result<_, _>>()?,
            default: number(each.get("default").ok_or_else(bad)?)?,
            custom,
        });
    }
    let measurements = |name: &str| -> Result<Vec<Measurement>, Failure> {
        list(get(name)?)?.iter().map(word::<Measurement>).collect()
    };
    Ok(CapabilityDef {
        id: as_text(get("id")?)?.to_owned(),
        kind: word::<CapabilityKind>(get("kind")?)?,
        points: list(get("points")?)?
            .iter()
            .map(|each| Point::parse(as_text(each)?).ok_or_else(bad))
            .collect::<Result<_, _>>()?,
        revision: number(get("revision")?)?,
        departs_from: as_texts(get("departs_from")?)?,
        compat: opt_text(get("compat")?)?.map(str::to_owned),
        ceilings,
        journal_prefix: as_text(get("journal_prefix")?)?.to_owned(),
        codes: as_texts(get("codes")?)?,
        measurements: measurements("measurements")?,
        options,
        rules_editor: flag(get("rules_editor")?)?,
        samples: flag(get("samples")?)?,
        resends: flag(get("resends")?)?,
        requires: as_texts(get("requires")?)?,
        wordings: list(get("wordings")?)?
            .iter()
            .map(word::<WordingKey>)
            .collect::<Result<_, _>>()?,
        narrowed_by: measurements("narrowed_by")?,
        sends: match get("sends")? {
            Value::Null => None,
            other => Some(flag(other)?),
        },
    })
}

fn words<W: ClosedWord>(items: &[W]) -> Value {
    texts(&items.iter().map(|each| each.word()).collect::<Vec<_>>())
}

pub fn to_json(definition: &CapabilityDef) -> Value {
    let mut points: Vec<&str> = definition
        .points
        .iter()
        .map(|point| point.as_str())
        .collect();
    points.sort_unstable();
    points.dedup();
    let options: Vec<Value> = definition
        .options
        .iter()
        .map(|option| {
            object([
                ("key", text(option.key.as_str())),
                (
                    "choices",
                    Value::Array(option.choices.iter().map(|each| int(*each)).collect()),
                ),
                ("default", int(option.default)),
                (
                    "custom",
                    match option.custom {
                        None => Value::Null,
                        Some((low, high)) => Value::Array(vec![int(low), int(high)]),
                    },
                ),
            ])
        })
        .collect();
    object([
        ("id", text(&definition.id)),
        ("kind", text(definition.kind.as_str())),
        ("points", texts(&points)),
        ("revision", int(definition.revision)),
        ("departs_from", texts(&definition.departs_from)),
        ("compat", maybe_text(definition.compat.as_deref())),
        (
            "ceilings",
            match definition.ceilings {
                None => Value::Null,
                Some(each) => Value::Array(vec![int(each.per_day), int(each.per_conversation)]),
            },
        ),
        ("journal_prefix", text(&definition.journal_prefix)),
        ("codes", texts(&definition.codes)),
        ("measurements", words(&definition.measurements)),
        ("options", Value::Array(options)),
        ("rules_editor", Value::Bool(definition.rules_editor)),
        ("samples", Value::Bool(definition.samples)),
        ("resends", Value::Bool(definition.resends)),
        ("requires", texts(&definition.requires)),
        ("wordings", words(&definition.wordings)),
        ("narrowed_by", words(&definition.narrowed_by)),
        (
            "sends",
            match definition.sends {
                None => Value::Null,
                Some(each) => Value::Bool(each),
            },
        ),
    ])
}
