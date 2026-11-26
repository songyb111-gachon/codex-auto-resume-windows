//! The writer's edge cases, each with the bytes Python 3.13 and 3.14 write for it.

use car_machine::json::{
    DUMPS_LIST_LEVELS, Error, Int, Map, Options, Str, Value, from_str, to_string,
};

fn wire(value: &Value) -> String {
    to_string(value, &Options::wire()).unwrap()
}

fn object(entries: &[(&str, Value)]) -> Value {
    let mut map = Map::new();
    for (key, value) in entries {
        map.insert(Str::new(key), value.clone());
    }
    Value::Object(map)
}

fn text(points: &[u32]) -> Value {
    Value::Str(Str::from_code_points(points.iter().copied()).unwrap())
}

#[test]
fn the_wire_line() {
    let value = object(&[
        ("ok", true.into()),
        (
            "b",
            vec![
                Value::from(1),
                2.5.into(),
                Value::Null,
                false.into(),
                "x".into(),
            ]
            .into(),
        ),
        ("a", object(&[]).clone()),
        ("e", Value::Array(vec![])),
    ]);
    assert_eq!(
        wire(&value),
        r#"{"ok": true, "b": [1, 2.5, null, false, "x"], "a": {}, "e": []}"#
    );
}

#[test]
fn indents_and_separators() {
    let value = object(&[
        (
            "a",
            vec![Value::from(1), object(&[("k", "v".into())])].into(),
        ),
        ("e", object(&[])),
    ]);
    let two = to_string(&value, &Options::wire().indent(2)).unwrap();
    assert_eq!(
        two,
        "{\n  \"a\": [\n    1,\n    {\n      \"k\": \"v\"\n    }\n  ],\n  \"e\": {}\n}"
    );
    let zero = to_string(&value, &Options::wire().indent(0)).unwrap();
    assert_eq!(
        zero,
        "{\n\"a\": [\n1,\n{\n\"k\": \"v\"\n}\n],\n\"e\": {}\n}"
    );
    let compact = to_string(&value, &Options::new().separators(",", ":")).unwrap();
    assert_eq!(compact, r#"{"a":[1,{"k":"v"}],"e":{}}"#);
    // Explicit separators win over the indent's own.
    let both = to_string(
        &vec![Value::from(1), 2.into()].into(),
        &Options::new().indent(1).separators(", ", ":"),
    )
    .unwrap();
    assert_eq!(both, "[\n 1, \n 2\n]");
    let tab = to_string(
        &vec![Value::from(1)].into(),
        &Options::new().indent_text("\t"),
    )
    .unwrap();
    assert_eq!(tab, "[\n\t1\n]");
}

#[test]
fn sorted_keys_go_by_code_point() {
    let mut map = Map::new();
    for key in [
        &[0x62][..],
        &[0xE000],
        &[0x10000],
        &[0xD800],
        &[0x61],
        &[0x41],
        &[0xFF],
    ] {
        map.insert(
            Str::from_code_points(key.iter().copied()).unwrap(),
            Value::Null,
        );
    }
    let value = Value::Object(map);
    let sorted = to_string(&value, &Options::new().sort_keys(true).separators(",", ":")).unwrap();
    assert_eq!(
        sorted,
        r#"{"A":null,"a":null,"b":null,"\u00ff":null,"\ud800":null,"\ue000":null,"\ud800\udc00":null}"#
    );
    let kept = to_string(&value, &Options::new().separators(",", ":")).unwrap();
    assert_eq!(
        kept,
        r#"{"b":null,"\ue000":null,"\ud800\udc00":null,"\ud800":null,"a":null,"A":null,"\u00ff":null}"#
    );
}

#[test]
fn every_escape() {
    let all: Vec<u32> = (0..0x20)
        .chain([0x22, 0x5C, 0x2F, 0x7F, 0x80, 0x9F])
        .collect();
    let raw = wire(&text(&all));
    assert_eq!(
        raw,
        "\"\\u0000\\u0001\\u0002\\u0003\\u0004\\u0005\\u0006\\u0007\\b\\t\\n\\u000b\\f\\r\\u000e\\u000f\
         \\u0010\\u0011\\u0012\\u0013\\u0014\\u0015\\u0016\\u0017\\u0018\\u0019\\u001a\\u001b\\u001c\\u001d\\u001e\\u001f\
         \\\"\\\\/\u{7f}\u{80}\u{9f}\""
    );
    let ascii = to_string(&text(&all), &Options::new()).unwrap();
    assert!(
        ascii.ends_with("\\u001f\\\"\\\\/\\u007f\\u0080\\u009f\""),
        "{ascii}"
    );
}

#[test]
fn text_outside_ascii() {
    let value = text(&[
        0xAC00, 0x2028, 0x2029, 0xFEFF, 0xFFFF, 0x1F600, 0x10FFFF, 0x3C,
    ]);
    assert_eq!(
        wire(&value),
        "\"\u{ac00}\u{2028}\u{2029}\u{feff}\u{ffff}\u{1f600}\u{10ffff}<\""
    );
    assert_eq!(
        to_string(&value, &Options::new()).unwrap(),
        r#""\uac00\u2028\u2029\ufeff\uffff\ud83d\ude00\udbff\udfff<""#
    );
}

#[test]
fn surrogates_escape_in_ascii_and_refuse_the_utf8_write() {
    let lone = text(&[0x61, 0xD800, 0x62, 0xDFFF]);
    assert_eq!(
        to_string(&lone, &Options::new()).unwrap(),
        r#""a\ud800b\udfff""#
    );
    assert_eq!(to_string(&lone, &Options::wire()), Err(Error::Surrogate));
    // Two halves side by side are two code points, not the astral character they would pair to.
    let halves = text(&[0xD83D, 0xDE00]);
    assert_eq!(
        to_string(&halves, &Options::new()).unwrap(),
        r#""\ud83d\ude00""#
    );
    assert_eq!(to_string(&halves, &Options::wire()), Err(Error::Surrogate));
    // json.dumps raises at a NaN wherever the surrogate is; the write never comes.
    let both = Value::Array(vec![lone.clone(), f64::NAN.into()]);
    assert_eq!(to_string(&both, &Options::wire()), Err(Error::NotFinite));
    assert!(!Error::Surrogate.is_unwritable());
    assert!(Error::NotFinite.is_unwritable());
    // A key too.
    let mut map = Map::new();
    map.insert(Str::from_code_points([0xDC00]).unwrap(), Value::Null);
    assert_eq!(
        to_string(&Value::Object(map.clone()), &Options::new()).unwrap(),
        r#"{"\udc00": null}"#
    );
    assert_eq!(
        to_string(&Value::Object(map), &Options::wire()),
        Err(Error::Surrogate)
    );
}

#[test]
fn floats_and_the_refused_ones() {
    let floats = Value::Array(
        [
            0.0,
            -0.0,
            1.0,
            1e16,
            1e-5,
            0.0001,
            1e15,
            5e-324,
            f64::MAX,
            1799999999.5,
        ]
        .map(Value::from)
        .to_vec(),
    );
    assert_eq!(
        wire(&floats),
        "[0.0, -0.0, 1.0, 1e+16, 1e-05, 0.0001, 1000000000000000.0, 5e-324, 1.7976931348623157e+308, 1799999999.5]"
    );
    for refused in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert_eq!(
            to_string(&refused.into(), &Options::wire()),
            Err(Error::NotFinite)
        );
    }
}

#[test]
fn integers_of_any_size() {
    let ints = Value::Array(vec![
        i64::MIN.into(),
        i64::MAX.into(),
        u64::MAX.into(),
        Value::Int(Int::parse("-123456789012345678901234567890").unwrap()),
        Value::Int(Int::parse("-0").unwrap()),
        Value::Int(Int::parse("007").unwrap()),
        true.into(),
    ]);
    assert_eq!(
        wire(&ints),
        "[-9223372036854775808, 9223372036854775807, 18446744073709551615, -123456789012345678901234567890, 0, 7, true]"
    );
    let limit = Value::Int(Int::parse(&format!("-{}", "9".repeat(4300))).unwrap());
    assert_eq!(wire(&limit).len(), 4301);
    let past = Value::Int(Int::parse(&"1".repeat(4301)).unwrap());
    assert_eq!(
        to_string(&past, &Options::wire()),
        Err(Error::IntTooLong { digits: 4301 })
    );
    assert_eq!(Int::parse("1.0"), None);
    assert_eq!(Int::parse(""), None);
    assert_eq!(Int::parse("-"), None);
    assert_eq!(Int::parse("18446744073709551616").unwrap().as_u64(), None);
    assert_eq!(
        Int::parse("18446744073709551615").unwrap().as_u64(),
        Some(u64::MAX)
    );
    assert_eq!(
        Int::from(u64::MAX),
        Int::parse("18446744073709551615").unwrap()
    );
}

#[test]
fn nesting_past_the_depth_is_refused() {
    // A value this deep is dropped by a thread that has the stack for it (car_machine::stack).
    car_machine::stack::run_deep(|| {
        let levels = DUMPS_LIST_LEVELS as usize;
        let mut value = Value::Array(vec![1.into()]);
        for _ in 1..levels {
            value = Value::Array(vec![value]);
        }
        let written = wire(&value);
        assert_eq!(written.len(), 2 * levels + 1);
        let deeper = Value::Array(vec![value]);
        assert_eq!(to_string(&deeper, &Options::wire()), Err(Error::TooDeep));
    });
}

#[test]
fn texts_from_windows_and_from_python() {
    let wide = Str::from_wide(&[0x61, 0xD83D, 0xDE00, 0xD800, 0x62]);
    assert_eq!(
        wide.code_points().collect::<Vec<_>>(),
        [0x61, 0x1F600, 0xD800, 0x62]
    );
    assert_eq!(wide.len(), 4);
    assert!(wide.has_surrogate());
    assert_eq!(
        Str::from_surrogatepass(b"\xed\xa0\x80".to_vec())
            .unwrap()
            .code_points()
            .next(),
        Some(0xD800)
    );
    assert_eq!(Str::from_surrogatepass(b"\xc0\x80".to_vec()), None);
    assert_eq!(Str::from_surrogatepass(b"\xf4\x90\x80\x80".to_vec()), None);
    assert_eq!(Str::from_surrogatepass(b"\xe0\x80".to_vec()), None);
    assert_eq!(Str::from_code_points([0x110000]), None);
    assert_eq!(Str::new("\u{ac00}").as_str(), Some("\u{ac00}"));
}

#[test]
fn a_map_is_looked_up_by_str() {
    let Value::Object(map) = from_str(r#"{"ok": true, "가": 1}"#).unwrap() else {
        panic!("an object")
    };
    assert_eq!(map.get("ok"), Some(&Value::Bool(true)));
    assert_eq!(map.get("가"), Some(&Value::from(1)));
    assert_eq!(map.get("no"), None);
}

#[test]
fn read_then_written_back() {
    let line = r#"{"id": 1, "reply": {"ok": false, "error": "bad \"x\"\n", "n": [1.5, -0.0, 1e+16, 12345678901234567890123]}}"#;
    assert_eq!(wire(&from_str(line).unwrap()), line);
}
