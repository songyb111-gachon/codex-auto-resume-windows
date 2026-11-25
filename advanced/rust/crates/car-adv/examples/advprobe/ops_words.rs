//! `vocab.*`, `standards.*`, `measured.*` and `policy.*`: the words, the standards, the table and the policy.

use car_adv::jsonx::{int, object, text, texts};
use car_adv::measured;
use car_adv::policy::{self, Content, Found, Kind, Unreadable};
use car_adv::standards;
use car_adv::vocabulary::{
    self, ClosedWord, KEPT_NOTICES, NOTE_FOR_FAIL, NOTE_FOR_PASS, TRIPWIRES,
};
use car_machine::json::Value;
use car_platform::registry::{FakeRegistry, Root, Value as RegValue};

use crate::util::{Failure, Out, arg, bad, flag, list, number, text as as_text, texts as as_texts};

fn words<W: ClosedWord>(items: &[W]) -> Value {
    Value::Array(items.iter().map(|each| text(each.word())).collect())
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "vocab.enums" => Ok(object(
            vocabulary::ENUMS
                .iter()
                .map(|(name, values)| (*name, texts(values))),
        )),
        "vocab.parse" => {
            let (name, word) = (as_text(arg(args, 0)?)?, as_text(arg(args, 1)?)?);
            match vocabulary::parse_member(name, word) {
                Some(Some(found)) => Ok(text(found)),
                Some(None) => Err(Failure::new("ValueError")),
                None => Err(Failure::new("KeyError")),
            }
        }
        "vocab.constants" => Ok(object([
            ("TRIPWIRES", words(TRIPWIRES)),
            ("KEPT_NOTICES", words(KEPT_NOTICES)),
            ("NOTE_FOR_PASS", words(NOTE_FOR_PASS)),
            ("NOTE_FOR_FAIL", words(NOTE_FOR_FAIL)),
        ])),
        "standards.lists" => Ok(object([
            ("STANDARDS", texts(standards::standards())),
            ("DEPARTABLE", texts(standards::departable())),
            ("DECLARABLE", texts(standards::declarable())),
            ("BINDING", texts(standards::BINDING)),
            ("BASIS", text(standards::BASIS)),
            (
                "FAMILIES",
                Value::Array(
                    standards::FAMILIES
                        .iter()
                        .map(|(prefix, count)| {
                            Value::Array(vec![text(prefix), int(i64::from(*count))])
                        })
                        .collect(),
                ),
            ),
        ])),
        "measured.table" => Ok(Value::Array(
            measured::MEASURED
                .iter()
                .map(|(measurement, verdict, engine)| {
                    Value::Array(vec![
                        text(measurement.as_str()),
                        text(verdict.as_str()),
                        text(engine),
                    ])
                })
                .collect(),
        )),
        "policy.read" => policy_read(args),
        "policy.admits" => {
            let found = policy_of(arg(args, 0)?)?;
            Ok(Value::Bool(found.admits(as_text(arg(args, 1)?)?)))
        }
        "policy.winreg" => policy_winreg(args),
        _ => Err(Failure::new("UnknownOp")),
    }
}

/// A policy as `Policy.as_json()` writes it.
pub fn policy_of(value: &Value) -> Result<policy::Policy, Failure> {
    let map = crate::util::map(value)?;
    let allowed = match map.get("allowed").ok_or_else(bad)? {
        Value::Null => None,
        other => Some(as_texts(other)?.into_iter().collect()),
    };
    Ok(policy::Policy {
        forbid: flag(map.get("forbid").ok_or_else(bad)?)?,
        force_shadow: flag(map.get("force_shadow").ok_or_else(bad)?)?,
        allowed,
    })
}

fn kind_of(word: &str) -> Result<Kind, Failure> {
    Ok(match word {
        "dword" => Kind::Dword,
        "text" => Kind::Text,
        "list" => Kind::List,
        "other" => Kind::Other,
        _ => return Err(bad()),
    })
}

fn content_of(value: &Value) -> Result<Content, Failure> {
    Ok(match value {
        Value::Int(_) => Content::Int(number(value)?),
        Value::Str(_) => Content::Text(as_text(value)?.to_owned()),
        Value::Array(_) => Content::List(as_texts(value)?),
        _ => Content::Other,
    })
}

/// `[entries, raises]`: each entry `[hive, name, kind, value]`, each raise `[hive, name]`.
fn policy_read(args: &[Value]) -> Out {
    let mut table: Vec<(String, String, Found)> = Vec::new();
    for entry in list(arg(args, 0)?)? {
        let entry = list(entry)?;
        table.push((
            as_text(arg(entry, 0)?)?.to_owned(),
            as_text(arg(entry, 1)?)?.to_owned(),
            Found {
                kind: kind_of(as_text(arg(entry, 2)?)?)?,
                value: content_of(arg(entry, 3)?)?,
            },
        ));
    }
    let mut raises: Vec<(String, String)> = Vec::new();
    for entry in list(arg(args, 1)?)? {
        let entry = list(entry)?;
        raises.push((
            as_text(arg(entry, 0)?)?.to_owned(),
            as_text(arg(entry, 1)?)?.to_owned(),
        ));
    }
    let reader = |hive: &str, name: &str| -> Result<Option<Found>, Unreadable> {
        if raises.iter().any(|(h, n)| h == hive && n == name) {
            return Err(Unreadable("denied".into()));
        }
        Ok(table
            .iter()
            .find(|(h, n, _)| h == hive && n == name)
            .map(|(_, _, found)| found.clone()))
    };
    Ok(policy::read(&reader).as_json())
}

fn root_of(hive: &str) -> Result<Root, Failure> {
    match hive {
        "HKLM" => Ok(Root::LocalMachine),
        "HKCU" => Ok(Root::CurrentUser),
        _ => Err(bad()),
    }
}

/// `[seeds, denied_keys, denied_values]`: each seed `[hive, name, registry type, payload]`; a denied key is a hive, a denied
/// value `[hive, name]`. The read goes through car-platform's in-memory registry and the real `windows_reader`.
fn policy_winreg(args: &[Value]) -> Out {
    let registry = FakeRegistry::new();
    for seed in list(arg(args, 0)?)? {
        let seed = list(seed)?;
        let (root, name, kind) = (
            root_of(as_text(arg(seed, 0)?)?)?,
            as_text(arg(seed, 1)?)?,
            number(arg(seed, 2)?)?,
        );
        let payload = arg(seed, 3)?;
        let value = match kind {
            1 | 2 => RegValue::Str(as_text(payload)?.to_owned()),
            4 => RegValue::Int(u32::try_from(number(payload)?).map_err(|_| bad())?),
            11 => RegValue::Qword(u64::try_from(number(payload)?).map_err(|_| bad())?),
            7 => {
                let mut units: Vec<u16> = Vec::new();
                for each in as_texts(payload)? {
                    units.extend(each.encode_utf16());
                    units.push(0);
                }
                units.push(0);
                RegValue::Bytes(units.iter().flat_map(|unit| unit.to_le_bytes()).collect())
            }
            _ => RegValue::Bytes(vec![1, 2, 3]),
        };
        registry.seed(
            root,
            policy::KEY,
            &[(name, value, u32::try_from(kind).map_err(|_| bad())?)],
        );
    }
    for hive in list(arg(args, 1)?)? {
        registry.deny_key(root_of(as_text(hive)?)?, policy::KEY);
    }
    for entry in list(arg(args, 2)?)? {
        let entry = list(entry)?;
        registry.deny_value(
            root_of(as_text(arg(entry, 0)?)?)?,
            policy::KEY,
            as_text(arg(entry, 1)?)?,
        );
    }
    let reader = |hive: &str, name: &str| policy::windows_reader(&registry, hive, name);
    Ok(policy::read(&reader).as_json())
}
