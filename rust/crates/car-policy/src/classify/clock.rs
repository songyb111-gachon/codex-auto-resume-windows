//! The local clock, as quiet hours, a postponement and a reset time read it: `time.localtime` and `time.mktime`.
//!
//! The trait and its `struct_time` are car-machine's (`car_machine::localclock`), named here as the policy has always
//! named them; the product's clock, the C runtime's, is car-platform's `localclock::Crt` (D3), handed in by the binaries.

pub use car_machine::localclock::{LocalClock, Tm};
