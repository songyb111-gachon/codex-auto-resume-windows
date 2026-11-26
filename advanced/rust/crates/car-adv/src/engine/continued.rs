//! `engine/continued.py` (seat S7.2d): what the edition's own continuations share - the key one is kept under, whether
//! words pass core's check, and what core is handed of one (P2's CONTINUATION).
//!
//! S7.2a's skeleton ported the three functions into `seam_p7` faithfully, for the runtime's P2 before this seat existed;
//! they are this module's, and the integration points `seam_p7` here (P7-DESIGN 2.1). Until then the one body is
//! `seam_p7`'s, so the two can never differ.

use car_machine::json::Value;

/// `answer_key(*parts)`: 64 hex digits of `json.dumps([str(part) ...], separators=(",", ":"))`. Each part is written
/// as Python's `str` writes it (`str(None)` is `None`, `str(300)` is `300`).
pub fn answer_key(parts: &[Value]) -> String {
    let texts: Vec<String> = parts.iter().map(car_machine::pytext::py_str).collect();
    crate::seam_p7::answer_key(&texts)
}

/// `words_pass(words)`: words core sends as a continuation (`continuation.validate_continuation`).
pub fn words_pass(words: &Value) -> bool {
    crate::seam_p7::words_pass(words)
}

/// `handed(row)`: what core is handed of one continuation - one waiting, with its words; one in flight, to be
/// watched - or None.
pub fn handed(row: &Value) -> Option<Value> {
    crate::seam_p7::continued_handed(row)
}
