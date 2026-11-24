//! Python's float arithmetic and formatting where Rust's differs: `repr`, `%g`, `round(x, n)`, `round(x)`,
//! `%` and `//` on floats, `max`/`min`, and `math.hypot`, `math.erfc`.
//!
//! car-brand depends on nothing, so the float repr is written here as car-machine's JSON writer writes it (the
//! same rule: the shortest digits, rounded half to even, fixed while the point is within 16 digits).

use std::fmt::Write as _;

/// `repr(x)`: the shortest digits that read back as `x`, as Python writes them.
pub fn repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_owned();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf" } else { "-inf" }.to_owned();
    }
    // `{:e}` gives the shortest length; where two forms of that length are equally near it takes the upper one and
    // Python the even one, so the digits are x rounded to that length, exactly and half to even (`{:.*e}`).
    let shortest = format!("{x:e}");
    let length = shortest.split_once('e').map_or(1, |(mantissa, _)| {
        mantissa.bytes().filter(u8::is_ascii_digit).count()
    });
    let (negative, digits, exponent) = scientific(x, length);
    let point = exponent + 1;
    let mut out = String::new();
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
    out
}

/// `x` to `count` significant digits, rounded half to even on its exact value: (negative, digits, exponent).
fn scientific(x: f64, count: usize) -> (bool, String, i32) {
    let text = format!("{x:.*e}", count.max(1) - 1);
    let (negative, rest) = match text.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, text.as_str()),
    };
    let (mantissa, exponent) = rest.split_once('e').expect("`{:e}` writes an exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    (
        negative,
        digits,
        exponent.parse().expect("a decimal exponent"),
    )
}

/// `"%g" % x`: six significant digits, trailing zeros dropped, an exponent below 1e-4 and from 1e6.
pub fn g(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_owned();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf" } else { "-inf" }.to_owned();
    }
    let precision = 6;
    let (negative, digits, exponent) = scientific(x, precision as usize);
    let point = exponent + 1;
    let mut out = String::new();
    if negative {
        out.push('-');
    }
    if point <= -4 || point > precision {
        let kept = digits.trim_end_matches('0');
        let kept = if kept.is_empty() { "0" } else { kept };
        out.push_str(&kept[..1]);
        if kept.len() > 1 {
            out.push('.');
            out.push_str(&kept[1..]);
        }
        let sign = if exponent < 0 { '-' } else { '+' };
        let _ = write!(out, "e{sign}{:02}", exponent.unsigned_abs());
    } else {
        let mut fixed = String::new();
        if point <= 0 {
            fixed.push_str("0.");
            fixed.extend(std::iter::repeat_n('0', point.unsigned_abs() as usize));
            fixed.push_str(&digits);
        } else {
            let point = point as usize;
            fixed.push_str(&digits[..point]);
            fixed.push('.');
            fixed.push_str(&digits[point..]);
        }
        let fixed = fixed.trim_end_matches('0').trim_end_matches('.');
        out.push_str(fixed);
    }
    out
}

/// `round(x, digits)` for a float: x rounded to that many decimals, exactly and half to even, read back.
pub fn round_to(x: f64, digits: usize) -> f64 {
    if !x.is_finite() || x == 0.0 || digits > 323 {
        return x;
    }
    format!("{x:.digits$}").parse().unwrap_or(x)
}

/// `round(x)`: the nearest int, half to even.
pub fn round_int(x: f64) -> i64 {
    x.round_ties_even() as i64
}

/// `"%d" % x`: the int `int(x)` writes.
pub fn d(x: f64) -> String {
    let whole = x.trunc();
    if whole == 0.0 {
        "0".to_owned()
    } else {
        format!("{whole:.0}")
    }
}

/// Python's `a % b` for floats: the sign of `b`, and a zero that takes `b`'s sign.
pub fn rem(a: f64, b: f64) -> f64 {
    let mut m = a % b;
    if m != 0.0 {
        if (b < 0.0) != (m < 0.0) {
            m += b;
        }
    } else {
        m = 0.0f64.copysign(b);
    }
    m
}

/// Python's `a // b` for floats (float_floor_div).
pub fn floordiv(a: f64, b: f64) -> f64 {
    let m = a % b;
    let mut div = (a - m) / b;
    if m != 0.0 && (b < 0.0) != (m < 0.0) {
        div -= 1.0;
    }
    if div != 0.0 {
        let mut floor = div.floor();
        if div - floor > 0.5 {
            floor += 1.0;
        }
        floor
    } else {
        0.0f64.copysign(a / b)
    }
}

/// `max(a, b)`: the first unless the second is greater.
pub fn max(a: f64, b: f64) -> f64 {
    if b > a { b } else { a }
}

/// `min(a, b)`: the first unless the second is less.
pub fn min(a: f64, b: f64) -> f64 {
    if b < a { b } else { a }
}

/// `math.floor(x)` as the int it returns.
pub fn floor(x: f64) -> i64 {
    x.floor() as i64
}

/// `math.ceil(x)` as the int it returns.
pub fn ceil(x: f64) -> i64 {
    x.ceil() as i64
}

/// `frexp(x)`'s exponent for a finite, non-zero x: x = m * 2**e with 0.5 <= |m| < 1.
fn frexp_exponent(x: f64) -> i32 {
    let bits = x.abs().to_bits();
    let biased = (bits >> 52) as i32;
    if biased == 0 {
        // subnormal: the highest set bit of the mantissa
        let mantissa = bits & ((1u64 << 52) - 1);
        let top = 63 - mantissa.leading_zeros() as i32;
        top - 1074 + 1
    } else {
        biased - 1022
    }
}

/// `ldexp(1.0, e)` for e from -1074 to 1023.
fn power_of_two(e: i32) -> f64 {
    if e >= -1022 {
        f64::from_bits(((e + 1023) as u64) << 52)
    } else {
        f64::from_bits(1u64 << (e + 1074))
    }
}

/// `math.hypot(*coordinates)`: CPython's own (mathmodule.c's vector_norm since 3.10 - the squares summed
/// losslessly and the root corrected once), not the C library's `hypot`, which can differ in the last bit.
pub fn hypot_all(coordinates: &[f64]) -> f64 {
    let mut vec: Vec<f64> = coordinates.iter().map(|x| x.abs()).collect();
    let mut max = 0.0f64;
    let mut found_nan = false;
    for x in &vec {
        found_nan |= x.is_nan();
        if *x > max {
            max = *x;
        }
    }
    vector_norm(&mut vec, max, found_nan)
}

/// `math.hypot(x, y)`.
pub fn hypot(x: f64, y: f64) -> f64 {
    hypot_all(&[x, y])
}

fn vector_norm(vec: &mut [f64], max: f64, found_nan: bool) -> f64 {
    if max.is_infinite() {
        return max;
    }
    if found_nan {
        return f64::NAN;
    }
    if max == 0.0 || vec.len() <= 1 {
        return max;
    }
    let max_e = frexp_exponent(max);
    if max_e < -1023 {
        for x in vec.iter_mut() {
            *x /= f64::MIN_POSITIVE;
        }
        return f64::MIN_POSITIVE * vector_norm(vec, max / f64::MIN_POSITIVE, found_nan);
    }
    let scale = power_of_two(-max_e);
    let (mut csum, mut frac1, mut frac2) = (1.0f64, 0.0f64, 0.0f64);
    for x in vec.iter() {
        let x = *x * scale;
        let (hi, lo) = dl_mul(x, x);
        let (sum, low) = dl_fast_sum(csum, hi);
        csum = sum;
        frac1 += lo;
        frac2 += low;
    }
    let mut h = (csum - 1.0 + (frac1 + frac2)).sqrt();
    let (hi, lo) = dl_mul(-h, h);
    let (sum, low) = dl_fast_sum(csum, hi);
    csum = sum;
    frac1 += lo;
    frac2 += low;
    let x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    h / scale
}

fn dl_mul(x: f64, y: f64) -> (f64, f64) {
    let z = x * y;
    (z, x.mul_add(y, -z))
}

fn dl_fast_sum(a: f64, b: f64) -> (f64, f64) {
    let hi = a + b;
    (hi, (a - hi) + b)
}

// math.erfc: Rust's std has none, and CPython calls the C library's (ucrt's on Windows), so this one calls the same
// function: one extern declaration, held to the tag by the diff over elevation_colour and shadow_alpha.
unsafe extern "C" {
    #[link_name = "erfc"]
    fn c_erfc(x: f64) -> f64;
}

/// `math.erfc(x)`: the C runtime's, as CPython's.
pub fn erfc(x: f64) -> f64 {
    // SAFETY: erfc is a pure function of one double in the C runtime every Rust program on Windows links.
    unsafe { c_erfc(x) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats_as_python() {
        for (x, want) in [
            (0.0, "0.0"),
            (1.0, "1.0"),
            (0.3, "0.3"),
            (1e-5, "1e-05"),
            (1e16, "1e+16"),
            (12.5, "12.5"),
        ] {
            assert_eq!(repr(x), want);
        }
        for (x, want) in [
            (0.0, "0"),
            (-0.0, "-0"),
            (5.0, "5"),
            (1.5, "1.5"),
            (1e-5, "1e-05"),
            (0.0001, "0.0001"),
            (100000.0, "100000"),
            (1234567.0, "1.23457e+06"),
            (0.123456789, "0.123457"),
            (12345.25, "12345.2"),
            (999999.5, "1e+06"),
        ] {
            assert_eq!(g(x), want, "%g of {x}");
        }
        assert_eq!(round_to(0.125, 2), 0.12);
        assert_eq!(round_to(2.675, 2), 2.67);
        assert_eq!(rem(-1.0, 4400.0), 4399.0);
        assert_eq!(floordiv(96.0, 2.0), 48.0);
        assert_eq!(hypot(3.0, 4.0), 5.0);
    }
}
