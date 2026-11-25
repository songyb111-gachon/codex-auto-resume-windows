//! The float repr against Python's own `repr`, over every power of two, the subnormals, every decimal exponent's
//! boundary and a million random values (`support/float_corpus.rs` says what and why). Both of car-machine's
//! writers of it are held: the JSON writer (`json.dumps` of a float is `float.__repr__`) and `pytext::float_repr`,
//! which car-store's schedule files and the words' keys use.
//!
//! ```text
//! cargo test --release --locked -p car-machine --test float_repr_reference -- --nocapture
//! ```

#[path = "support/float_corpus.rs"]
mod float_corpus;

use car_machine::json::{Options, Value, to_string};
use car_machine::pytext::float_repr;

#[test]
fn the_json_writer_writes_every_float_as_python_does() {
    float_corpus::hold("json writer", |x| {
        let text = to_string(&Value::Float(x), &Options::new()).expect("a finite float is written");
        // A writer's text must also read back as the float itself.
        assert_eq!(
            text.parse::<f64>().ok().map(f64::to_bits),
            Some(x.to_bits()),
            "{text} reads back"
        );
        text
    });
}

#[test]
fn pytext_float_repr_writes_every_float_as_python_does() {
    float_corpus::hold("pytext::float_repr", float_repr);
}
