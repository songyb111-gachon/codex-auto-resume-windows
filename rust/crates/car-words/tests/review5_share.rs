//! Review 5: `share` and `countdown` on the numbers the harness's JSON channel cannot carry (REVIEW-int5.md).
//!
//! ui/words.py's `share` is `100 if used >= 100 else int(used // 1)`: a NaN is not >= 100, and `int(nan)` raises
//! ValueError; `-inf // 1` is a NaN in Python, so that is a ValueError too. `countdown` is `int(seconds)`, which reads a
//! digit string ("45" -> "45s"). The diffs send their cases as JSON with `allow_nan=False`, so no generator can give a
//! NaN or an infinity, and none gives a string. Each expectation below is Python 3.13.15's answer.

use car_machine::json::{Map, Str, Value};
use car_words::words::{countdown, share};

fn window(used: Value) -> Value {
    let mut map = Map::new();
    map.insert(Str::from("used_percent"), used);
    Value::Object(map)
}

#[test]
fn a_nan_share_is_a_value_error() {
    assert_eq!(share(&window(Value::Float(f64::NAN))), Err("ValueError"));
}

#[test]
fn a_minus_infinite_share_is_a_value_error() {
    assert_eq!(
        share(&window(Value::Float(f64::NEG_INFINITY))),
        Err("ValueError")
    );
}

#[test]
fn a_countdown_reads_a_digit_string_as_int_does() {
    assert_eq!(countdown(&Value::from("45")), Ok("45s".to_owned()));
}
