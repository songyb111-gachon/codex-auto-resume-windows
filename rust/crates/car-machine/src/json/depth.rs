//! How deep CPython 3.14's C scanner and encoder let a document nest, as the product's own interpreter meets it.
//!
//! 3.13 stopped `json.loads` at a fixed 2,998 levels. 3.14.10 (the runtime the product bundles) checks the C stack
//! pointer instead of counting calls, so the limit is not one number: it is a stack budget, and a level costs what its
//! C frames take. A list's frames are small, an object's larger. Measured on the bundled embeddable `python.exe`
//! 3.14.10, main thread, 25 processes (2026-11-26, `tests/rustdiff/diffs_nesting_314.py` measures it again each run):
//!
//! | what | levels accepted | across runs |
//! |---|---|---|
//! | `json.loads` of `[`*n | 16,917 | 16,909 - 16,920 |
//! | `json.loads` of `{"a":`*n | 14,314 | 14,308 - 14,317 |
//! | `json.loads`, `[{"a":` alternating | 15,507 | 15,501 - 15,511 |
//! | `json.dumps` (the C encoder; `indent`, `sort_keys`, `separators` change nothing) of nested lists | 15,506 | 15,500 - 15,510 |
//! | `json.dumps` of nested dicts | 9,304 | 9,300 - 9,306 |
//! | `json.dumps` alternating | 11,630 | 11,627 - 11,632 |
//!
//! Every shape fits one rule: a level costs `1 / (the levels a document of that kind alone reaches)` of the budget, the
//! levels of a mixed document add up, and it is refused when they pass the whole (the alternating row is the harmonic
//! mean of the two rows above it: 2 / (1/16,917 + 1/14,314) = 15,507). Tried on ten other patterns (`LLO`, `LOO`, `LLLLO`,
//! ...) the rule lands within three levels of the reference. The numbers move by about 20 between processes (the stack
//! starts at a different place) and a thread with a smaller stack stops about 20 levels sooner: the constants are the
//! middle of the runs, and a diff that straddles a limit stays outside that band (AUDIT-v0628).
//!
//! The count here is of nested arrays and objects, empty ones included (the C code checks before it looks inside).
//! A parse hook (`object_pairs_hook`, `parse_float`, `parse_constant`: what `compat.decode` passes) is a Python call
//! made from C at the deepest point, and costs the levels it needs: see [`Hooks`].

/// A document's stack, in units: a level of the list kind costs `object_levels` units, a level of the object kind
/// `list_levels`, and the whole budget is `list_levels * object_levels`. All integers, so no rounding decides a case.
#[derive(Clone, Copy, Debug)]
pub(crate) struct Budget {
    list_levels: u64,
    object_levels: u64,
    used: u64,
}

impl Budget {
    pub(crate) const fn new(list_levels: u64, object_levels: u64) -> Budget {
        Budget {
            list_levels,
            object_levels,
            used: 0,
        }
    }

    fn whole(&self) -> u64 {
        self.list_levels * self.object_levels
    }

    /// One more list: false (and nothing taken) when it does not fit.
    pub(crate) fn enter_list(&mut self) -> bool {
        self.enter(self.object_levels)
    }

    /// One more object: false (and nothing taken) when it does not fit.
    pub(crate) fn enter_object(&mut self) -> bool {
        self.enter(self.list_levels)
    }

    pub(crate) fn leave_list(&mut self) {
        self.used -= self.object_levels;
    }

    pub(crate) fn leave_object(&mut self) {
        self.used -= self.list_levels;
    }

    fn enter(&mut self, cost: u64) -> bool {
        if self.used + cost > self.whole() {
            return false;
        }
        self.used += cost;
        true
    }

    /// Whether `levels` more list levels fit on top of what is held: what a call made from C needs, at the deepest.
    pub(crate) fn room_for_list_levels(&self, levels: u64) -> bool {
        self.used + levels * self.object_levels <= self.whole()
    }

    /// The same in object levels.
    pub(crate) fn room_for_object_levels(&self, levels: u64) -> bool {
        self.used + levels * self.list_levels <= self.whole()
    }
}

/// `json.loads`: lists, objects (the middle of the runs above).
pub const LOADS_LIST_LEVELS: u64 = 16_917;
pub const LOADS_OBJECT_LEVELS: u64 = 14_314;
/// `json.dumps` through the C encoder.
pub const DUMPS_LIST_LEVELS: u64 = 15_506;
pub const DUMPS_OBJECT_LEVELS: u64 = 9_304;

pub(crate) const fn loads() -> Budget {
    Budget::new(LOADS_LIST_LEVELS, LOADS_OBJECT_LEVELS)
}

pub(crate) const fn dumps() -> Budget {
    Budget::new(DUMPS_LIST_LEVELS, DUMPS_OBJECT_LEVELS)
}

/// What the parse hooks of `compat.decode` take at the deepest point, measured the same way (median of 12 processes
/// against the same document without hooks): a closing object's `object_pairs_hook` 13 object levels (`{}` and
/// non-empty alike); a float's `parse_float` 16 list levels; a `NaN`/`Infinity`'s `parse_constant` 33 list levels
/// (and 3 where no hook is given: the plain decoder's own constant table).
pub(crate) struct Hooks;

impl Hooks {
    pub(crate) const OBJECT_PAIRS_OBJECT_LEVELS: u64 = 13;
    pub(crate) const PARSE_FLOAT_LIST_LEVELS: u64 = 16;
    pub(crate) const PARSE_CONSTANT_LIST_LEVELS: u64 = 33;
    pub(crate) const PLAIN_CONSTANT_LIST_LEVELS: u64 = 3;
}
