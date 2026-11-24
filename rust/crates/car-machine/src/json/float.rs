//! Python's `float.__repr__`, which is what `json.dumps` writes for a float.

use std::fmt::Write as _;

/// Appends `repr(x)` for a finite `x`: the shortest digits that read back as `x`, in fixed
/// notation while the decimal point falls within 16 digits of the start (`1e-05` and `1e+16`
/// are the first in exponent form), with `.0` added to a whole number and an exponent of at
/// least two digits with its sign (`1e-05`, `1.5e+300`).
pub(crate) fn push_repr(out: &mut String, x: f64) {
    debug_assert!(x.is_finite());
    // Rust's `{:e}` is the shortest round-trip form too, as `d.ddde-5` (`0e0` for zero).
    let scientific = format!("{x:e}");
    let (negative, rest) = match scientific.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, scientific.as_str()),
    };
    let (mantissa, exponent) = rest
        .split_once('e')
        .expect("`{:e}` always writes an exponent");
    let exponent: i32 = exponent.parse().expect("`{:e}` writes a decimal exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    // Where the decimal point falls, counted from the first digit (Python's `decpt`).
    let point = exponent + 1;
    if negative {
        out.push('-');
    }
    if !(-4 < point && point <= 16) {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        let sign = if exponent < 0 { '-' } else { '+' };
        let _ = write!(out, "e{sign}{:02}", exponent.unsigned_abs());
    } else if point <= 0 {
        out.push_str("0.");
        out.extend(std::iter::repeat_n('0', point.unsigned_abs() as usize));
        out.push_str(&digits);
    } else {
        let point = point as usize;
        if point >= digits.len() {
            out.push_str(&digits);
            out.extend(std::iter::repeat_n('0', point - digits.len()));
            out.push_str(".0");
        } else {
            out.push_str(&digits[..point]);
            out.push('.');
            out.push_str(&digits[point..]);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::push_repr;

    fn repr(x: f64) -> String {
        let mut out = String::new();
        push_repr(&mut out, x);
        out
    }

    #[test]
    fn as_python_writes_them() {
        let cases: &[(f64, &str)] = &[
            (0.0, "0.0"),
            (-0.0, "-0.0"),
            (1.0, "1.0"),
            (-1.5, "-1.5"),
            (0.1, "0.1"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (0.000015, "1.5e-05"),
            (1e16, "1e+16"),
            (1e15, "1000000000000000.0"),
            (9999999999999998.0, "9999999999999998.0"),
            (1.2345678901234568e17, "1.2345678901234568e+17"),
            (1e22, "1e+22"),
            (1e100, "1e+100"),
            (1.5e300, "1.5e+300"),
            (f64::MAX, "1.7976931348623157e+308"),
            (f64::MIN_POSITIVE, "2.2250738585072014e-308"),
            (5e-324, "5e-324"),
            (123.456, "123.456"),
            (1799999999.0, "1799999999.0"),
            (1799999999.25, "1799999999.25"),
            (2f64.powi(53), "9007199254740992.0"),
            (0.3, "0.3"),
            (0.1 + 0.2, "0.30000000000000004"),
        ];
        for (x, want) in cases {
            assert_eq!(repr(*x), *want, "repr of {x:e}");
        }
    }
}
