//! The tables' shape: Python's values as the brand holds them (tables_gen.rs), and the numbers they hold.
//!
//! A Python number is an int or a float, and the answers the panel, the window and the diffs read carry which:
//! `16` is not `16.0`. So a number here is a [`Num`], and the arithmetic the scenes do on one is Python's - an int
//! with an int stays an int, anything with a float is a float, `/` is always a float.

use std::cmp::Ordering;

/// A Python int or float.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Num {
    I(i64),
    F(f64),
}

impl Num {
    /// `float(self)`.
    pub fn f(self) -> f64 {
        match self {
            Num::I(int) => int as f64,
            Num::F(x) => x,
        }
    }

    pub fn is_int(self) -> bool {
        matches!(self, Num::I(_))
    }

    fn both(self, other: Num, int: fn(i64, i64) -> Option<i64>, float: fn(f64, f64) -> f64) -> Num {
        match (self, other) {
            (Num::I(a), Num::I(b)) => {
                int(a, b).map_or_else(|| Num::F(float(a as f64, b as f64)), Num::I)
            }
            _ => Num::F(float(self.f(), other.f())),
        }
    }

    pub fn plus(self, other: Num) -> Num {
        self.both(other, i64::checked_add, |a, b| a + b)
    }

    pub fn minus(self, other: Num) -> Num {
        self.both(other, i64::checked_sub, |a, b| a - b)
    }

    pub fn times(self, other: Num) -> Num {
        self.both(other, i64::checked_mul, |a, b| a * b)
    }

    /// `self / other`: always a float (both small ints are exact doubles, so their quotient is Python's).
    pub fn over(self, other: Num) -> f64 {
        self.f() / other.f()
    }

    /// Python's comparison of two numbers (exact for the ints a table holds).
    pub fn compare(self, other: Num) -> Option<Ordering> {
        match (self, other) {
            (Num::I(a), Num::I(b)) => Some(a.cmp(&b)),
            _ => self.f().partial_cmp(&other.f()),
        }
    }

    pub fn lt(self, other: Num) -> bool {
        self.compare(other) == Some(Ordering::Less)
    }

    pub fn gt(self, other: Num) -> bool {
        self.compare(other) == Some(Ordering::Greater)
    }

    pub fn le(self, other: Num) -> bool {
        matches!(self.compare(other), Some(Ordering::Less | Ordering::Equal))
    }

    pub fn ge(self, other: Num) -> bool {
        matches!(
            self.compare(other),
            Some(Ordering::Greater | Ordering::Equal)
        )
    }

    /// `max(self, other)`: the first unless the second is greater.
    pub fn max(self, other: Num) -> Num {
        if other.gt(self) { other } else { self }
    }

    /// `min(self, other)`: the first unless the second is less.
    pub fn min(self, other: Num) -> Num {
        if other.lt(self) { other } else { self }
    }

    /// `round(self, digits)`: an int as it is, a float rounded as Python rounds it.
    pub fn round_to(self, digits: usize) -> Num {
        match self {
            Num::I(_) => self,
            Num::F(x) => Num::F(crate::pyfmt::round_to(x, digits)),
        }
    }
}

impl From<f64> for Num {
    fn from(x: f64) -> Num {
        Num::F(x)
    }
}

impl From<i64> for Num {
    fn from(int: i64) -> Num {
        Num::I(int)
    }
}

/// One Python value in a table: None, a bool, a number, a str, a tuple or list, or a dict in its key order.
#[derive(Debug)]
pub enum D {
    Null,
    B(bool),
    N(Num),
    S(&'static str),
    L(&'static [D]),
    M(&'static [(&'static str, D)]),
}

impl D {
    /// `self.get(key)`.
    pub fn find(&'static self, key: &str) -> Option<&'static D> {
        self.items()
            .iter()
            .find(|(name, _)| *name == key)
            .map(|(_, value)| value)
    }

    /// `self[key]`, for a key the table has.
    pub fn at(&'static self, key: &str) -> &'static D {
        self.find(key)
            .unwrap_or_else(|| panic!("the brand's table has no {key:?}"))
    }

    /// The dict's items in order (empty for anything else).
    pub fn items(&'static self) -> &'static [(&'static str, D)] {
        match self {
            D::M(items) => items,
            _ => &[],
        }
    }

    /// The dict's keys in order.
    pub fn keys(&'static self) -> impl Iterator<Item = &'static str> {
        self.items().iter().map(|(name, _)| *name)
    }

    /// The tuple's members (empty for anything else).
    pub fn list(&'static self) -> &'static [D] {
        match self {
            D::L(items) => items,
            _ => &[],
        }
    }

    pub fn n(&self) -> Num {
        match self {
            D::N(number) => *number,
            D::B(flag) => Num::I(i64::from(*flag)),
            _ => panic!("not a number: {self:?}"),
        }
    }

    pub fn f(&self) -> f64 {
        self.n().f()
    }

    pub fn i(&self) -> i64 {
        match self.n() {
            Num::I(int) => int,
            Num::F(x) => x as i64,
        }
    }

    pub fn s(&self) -> &'static str {
        match self {
            D::S(text) => text,
            _ => panic!("not a str: {self:?}"),
        }
    }

    /// The str, or None for None.
    pub fn opt_s(&self) -> Option<&'static str> {
        match self {
            D::S(text) => Some(text),
            _ => None,
        }
    }

    pub fn b(&self) -> bool {
        match self {
            D::B(flag) => *flag,
            _ => panic!("not a bool: {self:?}"),
        }
    }

    /// Whether the tuple holds `text`.
    pub fn has(&'static self, text: &str) -> bool {
        self.list()
            .iter()
            .any(|each| matches!(each, D::S(member) if *member == text))
    }

    /// The strs of a tuple of strs.
    pub fn strs(&'static self) -> impl Iterator<Item = &'static str> {
        self.list().iter().map(D::s)
    }
}
