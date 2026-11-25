//! car-brand's `pyfmt::repr` against Python's own `repr`, over the corpus car-machine's writer is held to
//! (`car-machine/tests/support/float_corpus.rs`: every power of two, the subnormals, every decimal exponent's
//! boundary and a million random values).
//!
//! ```text
//! cargo test --release --locked -p car-brand --test float_repr_reference -- --nocapture
//! ```

#[path = "../../car-machine/tests/support/float_corpus.rs"]
mod float_corpus;

#[test]
fn pyfmt_repr_writes_every_float_as_python_does() {
    float_corpus::hold("car-brand pyfmt::repr", car_brand::pyfmt::repr);
}
