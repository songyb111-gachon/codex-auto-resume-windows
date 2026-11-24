//! car-machine's calls: the domain's ids, states, usage, public codes, the registry's format, Python's text.

use car_machine::compat::model;
use car_machine::domain::{ids, public, skips, states, usage};
use car_machine::hash;
use car_machine::json::{Map, Str, Value};
use car_machine::pytext;
use car_machine::pyval::Py;
use car_machine::vocab;

use super::Args;

fn text(found: Option<String>) -> Value {
    found.map_or(Value::Null, Value::from)
}

fn array(items: Vec<Value>) -> Value {
    Value::Array(items)
}

fn numbers(items: &[i64]) -> Value {
    array(items.iter().map(|each| Value::from(*each)).collect())
}

/// `{code point: class}` for every code point: `S` white space, a digit for a decimal digit, `-` neither.
fn classes() -> String {
    let mut out = String::with_capacity(0x110000);
    for point in 0..0x110000u32 {
        out.push(match char::from_u32(point) {
            None => '-',
            Some(c) if pytext::is_space(c) => 'S',
            Some(c) => match pytext::decimal_value(c) {
                Some(value) => char::from_digit(value, 10).unwrap_or('-'),
                None => '-',
            },
        });
    }
    out
}

pub fn case(name: &str, a: &Args) -> Option<Py<Value>> {
    Some(match name {
        "vocab.export" => Ok(vocab::export(&[
            car_machine::vocab_gen::MODULES,
            car_config::vocab_gen::MODULES,
            car_words::vocab_gen::MODULES,
        ])),
        // Python's text
        "pytext.classes" => Ok(Value::from(classes())),
        "pytext.strip" => a.text(0).map(|each| Value::from(pytext::strip(each))),
        "pytext.int16" => a
            .text(0)
            .and_then(|each| match pytext::parse_int(each, 16) {
                None => Err("ValueError"),
                Some(parsed) => Ok(array(vec![
                    Value::Bool(parsed.negative && parsed.magnitude != Some(0)),
                    parsed
                        .magnitude
                        .map_or(Value::Null, |each| Value::from(each.to_string())),
                ])),
            }),
        "pytext.float_hex" => a.float(0).map(|each| Value::from(pytext::float_hex(each))),
        "pytext.float_from_text" => a
            .text(0)
            .and_then(pytext::float_from_text)
            .map(|each| Value::from(pytext::float_hex(each))),
        "hash.sha256" => a
            .bytes(0)
            .map(|each| Value::from(hash::hex(&hash::sha256(&each)))),
        "hash.sha1" => a
            .bytes(0)
            .map(|each| Value::from(hash::hex(&hash::sha1(&each)))),
        // ids
        "ids.uuid_problem" => Ok(uuid_problem(a)),
        "ids.is_uuid" => Ok(Value::Bool(ids::is_uuid(a.get(0)))),
        "ids.uuid_pattern" => Ok(Value::from(ids::uuid_pattern(a.flag(0)))),
        "ids.interruption_id" => {
            ids::interruption_id(a.get(0), a.get(1), a.get(2), a.get(3), a.get(4)).map(Value::from)
        }
        "ids.stalled_id" => ids::stalled_id(a.get(0), a.get(1), a.get(2)).map(Value::from),
        "ids.is_digest" => Ok(Value::Bool(ids::is_digest(a.get(0)))),
        "ids.is_interruption_id" => Ok(Value::Bool(ids::is_interruption_id(a.get(0), a.flag(1)))),
        "ids.is_power_nonce" => Ok(Value::Bool(ids::is_power_nonce(a.get(0)))),
        "ids.read_interruption_id" => a.text(0).map(|each| text(ids::read_interruption_id(each))),
        "ids.marker" => a.text(0).map(|each| Value::from(ids::marker(each))),
        "ids.short_marker" => a.text(0).map(|each| Value::from(ids::short_marker(each))),
        "ids.record_markers" => a.text(0).map(|each| {
            array(
                ids::record_markers(each)
                    .into_iter()
                    .map(Value::from)
                    .collect(),
            )
        }),
        "ids.is_marker" => Ok(Value::Bool(ids::is_marker(a.get(0)))),
        "ids.is_client_id" => Ok(Value::Bool(ids::is_client_id(a.get(0)))),
        "ids.continuation_client_id" => a
            .text(0)
            .map(|each| Value::from(ids::continuation_client_id(each))),
        "ids.is_delivery_proof" => Ok(Value::Bool(ids::is_delivery_proof(a.get(0)))),
        "skips.kind" => Ok(Value::from(skips::kind(a.get(0)))),
        // states
        "states.may_be_queued" => states::may_be_queued(a.get(0), a.get(1)).map(Value::Bool),
        "states.still_followed" => {
            states::still_followed(a.get(0), a.get(1), a.get(2)).map(Value::Bool)
        }
        "states.plain_move_allowed" => {
            states::plain_move_allowed(a.get(0), a.get(1)).map(Value::Bool)
        }
        "states.epoch" => (|| {
            states::epoch(a.get(0), a.int(1)?, a.int(2)?, a.flag(3), a.flag(4)).map(Value::Bool)
        })(),
        "states.waiting_state" => states::waiting_state(a.get(0), a.get(1)).map(Value::from),
        "states.ended_by_boot" => states::ended_by_boot(a.get(0), a.get(1)).map(Value::Bool),
        // usage
        "usage.windows_of" => {
            usage::windows_of(a.get(0)).map(|found| found.map_or(Value::Null, Value::Array))
        }
        "usage.encode" => usage::encode(a.get(0)).map(text),
        "usage.decode" => {
            usage::decode(a.get(0)).map(|found| found.map_or(Value::Null, Value::Array))
        }
        // public
        "public.event_code" => Ok(public::event_code(a.get(0))),
        "public.reason_code" => Ok(public::reason_code(a.get(0))),
        "public.actor_code" => Ok(public::actor_code(a.get(0))),
        "public.turn_status" => Ok(public::turn_status(a.get(0))),
        "public.hold_for_tier" => Ok(public::hold_for_tier(a.get(0))),
        "public.public_code" => public::public_code(a.get(0)).map(Value::from),
        "public.eligible_at" => public::eligible_at(a.get(0)),
        "public.own_postponement" => public::own_postponement(a.get(0), a.get(1)),
        "public.public_reason" => public::public_reason(a.get(0)),
        "public.blocked" => Ok(public::blocked(a.get(0))),
        "public.overlays" => public::overlays(a.get(0), a.get(1), a.get(2), a.get(3))
            .map(|found| array(found.into_iter().map(Value::from).collect())),
        "public.describe" => public::describe(a.get(0), a.get(1), a.get(2), a.get(3)),
        "public.version_word" => Ok(text(public::version_word(a.get(0)))),
        "public.self_check_note" => {
            public::self_check_note(a.get(0), a.get(1), a.get(2), a.get(3), a.get(4))
        }
        // the registry's format
        "compat.parse_version" => {
            Ok(model::parse_version(a.get(0)).map_or(Value::Null, |key| numbers(&key)))
        }
        "compat.product_key" => {
            Ok(model::product_key(a.get(0)).map_or(Value::Null, |key| numbers(&key)))
        }
        "compat.safe_version" => Ok(model::safe_version(a.get(0)).map_or(Value::Null, Value::from)),
        "compat.decode" => (|| {
            let raw = a.bytes(0)?;
            let limit = a.int(1)? as usize;
            Ok(match model::decode(&raw, limit) {
                Ok(value) => value,
                Err(refused) => refusal(refused.code),
            })
        })(),
        "compat.decode_probe" => {
            a.bytes(0)
                .map(|raw| match model::decode(&raw, model::MAX_DOCUMENT_BYTES) {
                    Ok(_) => array(vec![Value::from("parsed"), Value::Bool(true)]),
                    Err(refused) => refusal(refused.code),
                })
        }
        "compat.parse_document" => (|| {
            let raw = a.bytes(0)?;
            let limit = a.int(1)? as usize;
            Ok(match model::parse_document(&raw, limit) {
                Ok(document) => document.to_value(),
                Err(refused) => refusal(refused.code),
            })
        })(),
        _ => return None,
    })
}

/// A DocumentError, as the reference script writes it: `{"refused": code}`.
fn refusal(code: &str) -> Value {
    let mut entry = Map::new();
    entry.insert(Str::from("refused"), Value::from(code));
    Value::Object(entry)
}

fn uuid_problem(a: &Args) -> Value {
    ids::uuid_problem(a.get(0), a.flag(1)).map_or(Value::Null, Value::from)
}
