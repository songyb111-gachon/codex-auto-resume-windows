//! The pure pieces of car-control, held to Python's own answers (the whole bridge is held to the reference by
//! `tests/rustdiff/diffs_bridge*.py`; these run with `cargo test`).

use car_control::aside::stamp;
use car_control::bridge::{
    DAYS, GENERIC_ERROR, PLAIN, WITH_ARGUMENT, encode, flag, payload, rejected, statistics_days,
};
use car_control::error::{
    Failure, MAX_BUDGET_RESETS, REFUSALS_RESTORE, interruption_id, refusal, thread_id,
};
use car_control::tools::splitlines;
use car_machine::json::{Map, Str, Value};

fn object(pairs: &[(&str, Value)]) -> Map {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(*key), value.clone());
    }
    map
}

#[test]
fn the_command_lists_are_the_references() {
    assert_eq!(PLAIN.len(), 23);
    assert_eq!(WITH_ARGUMENT.len(), 28);
    assert!(PLAIN.iter().all(|name| !WITH_ARGUMENT.contains(name)));
}

#[test]
fn the_set_aside_stamp_is_time_strftime_of_gmtime() {
    assert_eq!(stamp(0.0), "19700101T000000Z");
    assert_eq!(stamp(1_700_000_000.9), "20231114T221320Z");
    assert_eq!(stamp(951_782_400.0), "20000229T000000Z");
}

#[test]
fn splitlines_cuts_where_python_does() {
    assert_eq!(splitlines("a\r\nb\rc\nd"), ["a", "b", "c", "d"]);
    assert_eq!(
        splitlines("a\u{b}b\u{1c}c\u{85}d\u{2028}e\u{2029}f"),
        ["a", "b", "c", "d", "e", "f"]
    );
    assert_eq!(splitlines("a\n"), ["a"]);
    assert_eq!(splitlines("\n\nx"), ["", "", "x"]);
    assert!(splitlines("").is_empty());
}

#[test]
fn a_payload_is_nothing_an_object_or_a_refusal() {
    assert_eq!(payload(&Value::Null).unwrap(), Map::new());
    assert_eq!(payload(&Value::from("")).unwrap(), Map::new());
    assert_eq!(
        payload(&Value::from("{\"a\": 1}")).unwrap(),
        object(&[("a", Value::from(1))])
    );
    let wrong = |value: Value| {
        payload(&value)
            .unwrap_err()
            .message
            .as_str()
            .unwrap()
            .to_owned()
    };
    assert_eq!(wrong(Value::from(0)), "argument must be a JSON object");
    assert_eq!(wrong(Value::Bool(false)), "argument must be a JSON object");
    assert_eq!(
        wrong(Value::Array(vec![])),
        "argument must be a JSON object"
    );
    assert_eq!(wrong(Value::from("[1]")), "argument must be a JSON object");
    assert_eq!(wrong(Value::from("{")), "argument must be JSON");
    assert_eq!(wrong(Value::from(" ")), "argument must be JSON");
}

#[test]
fn the_wire_writes_one_candidate_that_can_be_written() {
    let fine = rejected("x", "request_failed");
    assert_eq!(
        encode(&[fine.clone(), fine.clone()]).unwrap(),
        "{\"ok\": false, \"error\": \"x\", \"error_code\": \"request_failed\"}"
    );
    let infinite = Value::Float(f64::INFINITY);
    assert_eq!(
        encode(&[infinite, rejected(GENERIC_ERROR, "request_failed")]).unwrap(),
        "{\"ok\": false, \"error\": \"the request could not be completed\", \"error_code\": \"request_failed\"}"
    );
    // A text holding half of a surrogate pair is written by json.dumps and refused by the stream: the loop dies.
    let half = Value::Str(Str::from_code_points([0xD800]).unwrap());
    assert!(encode(&[half.clone(), fine]).is_err());
}

#[test]
fn days_and_flags_are_checked_as_the_reference_checks_them() {
    let days = |value: Value| statistics_days(&object(&[("days", value)])).is_ok();
    assert!(
        days(Value::from(1))
            && days(Value::from(3650))
            && days(Value::Float(7.5))
            && days(Value::Null)
    );
    assert!(!days(Value::from(0)) && !days(Value::from(3651)) && !days(Value::Bool(true)));
    assert!(
        !days(Value::from("7"))
            && !days(Value::Float(f64::NAN))
            && !days(Value::Float(f64::INFINITY))
    );
    assert_eq!(DAYS, (1, 3650));
    assert!(statistics_days(&Map::new()).unwrap().is_none());
    assert_eq!(
        flag(&object(&[("enabled", Value::Bool(true))])).unwrap(),
        true
    );
    let Err(Failure::Control(error)) = flag(&object(&[("enabled", Value::from("false"))])) else {
        panic!("a text is not a switch")
    };
    assert_eq!(error.code, "invalid_enabled");
}

#[test]
fn identities_are_read_as_the_reference_reads_them() {
    let key = "7".repeat(64);
    assert_eq!(
        interruption_id(&Value::from(format!("  {}\n", key.to_uppercase()))).unwrap(),
        key
    );
    for bad in [
        Value::Null,
        Value::from(5),
        Value::from("x"),
        Value::from("g".repeat(64)),
    ] {
        let Err(Failure::Control(error)) = interruption_id(&bad) else {
            panic!("not an id")
        };
        assert_eq!(
            (error.message.as_str().unwrap(), error.code.as_str()),
            ("invalid interruption id", "invalid_id")
        );
    }
    let thread = "11111111-1111-7111-8111-111111111111";
    assert_eq!(thread_id(&Value::from(thread)).unwrap(), thread);
    let Err(Failure::Control(error)) = thread_id(&Value::from("0A1B2C3D-0001-7000-8000-000000000001")) else {
        panic!("capitals are not canonical")
    };
    assert_eq!(
        error.message.as_str().unwrap(),
        "thread id must be lowercase canonical UUID text"
    );
    let Err(Failure::Control(error)) = thread_id(&Value::from("latest")) else {
        panic!("not a UUID")
    };
    assert_eq!(
        error.message.as_str().unwrap(),
        "thread id must be a canonical UUID"
    );
}

#[test]
fn a_refusal_is_its_sentence_or_the_tables_last_resort() {
    assert_eq!(
        refusal(REFUSALS_RESTORE, Some("finished")).1,
        "already_finished"
    );
    assert_eq!(
        refusal(REFUSALS_RESTORE, Some("something new")).1,
        "cannot_continue"
    );
    assert_eq!(refusal(REFUSALS_RESTORE, None).1, "cannot_continue");
    assert_eq!(
        refusal(REFUSALS_RESTORE, Some("reset_limit")).0,
        format!(
            "its budget was already reset {MAX_BUDGET_RESETS} times; continue this task in Codex yourself"
        )
    );
}
