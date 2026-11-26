//! How deep `json.loads` and `json.dumps` let a document nest on the bundled Python 3.14.10 (`src/json/depth.rs`
//! holds the measurement). Each limit is held from both sides, on a thread that has the stack to drop what it reads.

use car_machine::compat::{DocumentError, LOADS_LIST_LEVELS, LOADS_OBJECT_LEVELS, LoadsError};
use car_machine::compat::{decode, loads, raw_decode};
use car_machine::json::to_string;
use car_machine::json::{DUMPS_LIST_LEVELS, DUMPS_OBJECT_LEVELS, Error, Map, Options, Str, Value};
use car_machine::stack::run_deep;

fn lists(n: u64) -> String {
    "[".repeat(n as usize) + &"]".repeat(n as usize)
}

fn objects(n: u64) -> String {
    "{\"a\":".repeat(n as usize) + "0" + &"}".repeat(n as usize)
}

/// `n` containers, a list first, then an object, and so on, round a leaf.
fn alternating(n: u64, leaf: &str) -> String {
    let kinds: Vec<bool> = (0..n).map(|each| each % 2 == 0).collect();
    let open: String = kinds
        .iter()
        .map(|list| if *list { "[" } else { "{\"a\":" })
        .collect();
    let close: String = kinds
        .iter()
        .rev()
        .map(|list| if *list { "]" } else { "}" })
        .collect();
    format!("{open}{leaf}{close}")
}

fn plain_accepts(text: &str) -> bool {
    match loads(text) {
        Ok(_) => true,
        Err(LoadsError::Recursion) => false,
        Err(other) => panic!("not a depth question: {other:?}"),
    }
}

fn hooked_code(text: &str) -> Option<&'static str> {
    match decode(text.as_bytes(), usize::MAX) {
        Ok(_) => None,
        Err(DocumentError { code }) => Some(code),
    }
}

#[test]
fn loads_lists_and_objects_stop_where_3_14_stops() {
    run_deep(|| {
        assert!(plain_accepts(&lists(LOADS_LIST_LEVELS - 1)));
        assert!(plain_accepts(&lists(LOADS_LIST_LEVELS)));
        assert!(!plain_accepts(&lists(LOADS_LIST_LEVELS + 1)));
        assert!(plain_accepts(&objects(LOADS_OBJECT_LEVELS - 1)));
        assert!(plain_accepts(&objects(LOADS_OBJECT_LEVELS)));
        assert!(!plain_accepts(&objects(LOADS_OBJECT_LEVELS + 1)));
    });
}

#[test]
fn a_mix_spends_the_budget_as_its_levels_cost() {
    // The reference's alternating limit is the harmonic mean of the two: 2 / (1/16917 + 1/14314) = 15507.
    run_deep(|| {
        assert!(plain_accepts(&alternating(15_507, "0")));
        assert!(!plain_accepts(&alternating(15_508, "0")));
        // The cost rule, worked out here apart from the code: n levels, list first.
        let whole = u128::from(LOADS_LIST_LEVELS) * u128::from(LOADS_OBJECT_LEVELS);
        for n in [3_u64, 4, 5, 15_000, 15_506, 15_507, 15_508, 15_509] {
            let lists = n.div_ceil(2);
            let objects = n / 2;
            let cost = u128::from(lists) * u128::from(LOADS_OBJECT_LEVELS)
                + u128::from(objects) * u128::from(LOADS_LIST_LEVELS);
            assert_eq!(plain_accepts(&alternating(n, "0")), cost <= whole, "{n}");
        }
    });
}

#[test]
fn an_empty_container_counts_as_a_level() {
    run_deep(|| {
        let n = LOADS_LIST_LEVELS as usize;
        let at_the_limit = "[".repeat(n - 1) + "[]" + &"]".repeat(n - 1);
        assert!(plain_accepts(&at_the_limit));
        let over = "[".repeat(n) + "[]" + &"]".repeat(n);
        assert!(!plain_accepts(&over));
        // The object closes at its level, so `{}` is one more level too.
        let m = LOADS_OBJECT_LEVELS as usize;
        let objects_over = "{\"a\":".repeat(m) + "{}" + &"}".repeat(m);
        assert!(!plain_accepts(&objects_over));
    });
}

#[test]
fn raw_decode_has_the_plain_limit() {
    run_deep(|| {
        let at: Vec<char> = lists(LOADS_LIST_LEVELS).chars().collect();
        assert!(raw_decode(&at, 0).is_ok());
        let over: Vec<char> = lists(LOADS_LIST_LEVELS + 1).chars().collect();
        assert_eq!(raw_decode(&over, 0), Err(LoadsError::Recursion));
    });
}

#[test]
fn decode_takes_the_room_its_hooks_need() {
    run_deep(|| {
        // Lists call no hook: the plain limit.
        assert_eq!(hooked_code(&lists(LOADS_LIST_LEVELS)), None);
        assert_eq!(hooked_code(&lists(LOADS_LIST_LEVELS + 1)), Some("too_deep"));
        // An object's `object_pairs_hook` runs at the deepest point: 13 object levels.
        assert_eq!(hooked_code(&objects(LOADS_OBJECT_LEVELS - 13)), None);
        assert_eq!(
            hooked_code(&objects(LOADS_OBJECT_LEVELS - 12)),
            Some("too_deep")
        );
        // A float's `parse_float`: 16 list levels (and an infinity is refused after it).
        let leafed =
            |n: u64, literal: &str| "[".repeat(n as usize) + literal + &"]".repeat(n as usize);
        assert_eq!(hooked_code(&leafed(LOADS_LIST_LEVELS - 16, "1.5")), None);
        assert_eq!(
            hooked_code(&leafed(LOADS_LIST_LEVELS - 15, "1.5")),
            Some("too_deep")
        );
        assert_eq!(
            hooked_code(&leafed(LOADS_LIST_LEVELS - 16, "1e999")),
            Some("not_finite")
        );
        assert_eq!(
            hooked_code(&leafed(LOADS_LIST_LEVELS - 15, "1e999")),
            Some("too_deep")
        );
        // `parse_constant`: 33 list levels, then the refusal of what it names.
        assert_eq!(
            hooked_code(&leafed(LOADS_LIST_LEVELS - 33, "NaN")),
            Some("not_finite")
        );
        assert_eq!(
            hooked_code(&leafed(LOADS_LIST_LEVELS - 32, "NaN")),
            Some("too_deep")
        );
        // The plain reader's constant table needs 3.
        assert!(plain_accepts(&leafed(LOADS_LIST_LEVELS - 3, "NaN")));
        assert!(!plain_accepts(&leafed(LOADS_LIST_LEVELS - 2, "-Infinity")));
    });
}

fn nested_lists(n: u64) -> Value {
    let mut value = Value::Array(Vec::new());
    for _ in 1..n {
        value = Value::Array(vec![value]);
    }
    value
}

fn nested_objects(n: u64) -> Value {
    let mut value = Value::Object(Map::new());
    for _ in 1..n {
        let mut map = Map::new();
        map.insert(Str::new("a"), value);
        value = Value::Object(map);
    }
    value
}

fn dumps_accepts(value: &Value, options: &Options) -> bool {
    match to_string(value, options) {
        Ok(_) => true,
        Err(Error::TooDeep) => false,
        Err(other) => panic!("not a depth question: {other:?}"),
    }
}

#[test]
fn dumps_stops_where_the_c_encoder_stops() {
    run_deep(|| {
        let plain = Options::new();
        for options in [
            plain.clone(),
            Options::wire().indent(2),
            Options::new().sort_keys(true),
            Options::new().separators(",", ":"),
        ] {
            assert!(dumps_accepts(&nested_lists(DUMPS_LIST_LEVELS), &options));
            assert!(!dumps_accepts(
                &nested_lists(DUMPS_LIST_LEVELS + 1),
                &options
            ));
            assert!(dumps_accepts(
                &nested_objects(DUMPS_OBJECT_LEVELS),
                &options
            ));
            assert!(!dumps_accepts(
                &nested_objects(DUMPS_OBJECT_LEVELS + 1),
                &options
            ));
        }
        // The innermost list holds an item here: the same limit as an empty one.
        let mut filled = Value::Array(vec![Value::from(1)]);
        for _ in 1..DUMPS_LIST_LEVELS {
            filled = Value::Array(vec![filled]);
        }
        assert!(dumps_accepts(&filled, &plain));
        let deeper = Value::Array(vec![filled]);
        assert!(!dumps_accepts(&deeper, &plain));
    });
}

#[test]
fn a_deep_value_is_written_as_the_recursive_writer_wrote_it() {
    run_deep(|| {
        let value = nested_lists(40);
        let text = to_string(&value, &Options::new()).unwrap();
        assert_eq!(text, lists(40));
        let indented = to_string(&nested_objects(2), &Options::new().indent(1)).unwrap();
        assert_eq!(indented, "{\n \"a\": {}\n}");
    });
}
