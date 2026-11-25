//! `time.strptime` for the few forms this edition reads, and `calendar.timegm` (seat S7.2c).
//!
//! CPython's `_strptime` turns a form into a regular expression, matched with `re.IGNORECASE` at the start of the text and
//! then required to reach its end: `%Y` is `\d\d\d\d`, `%m` `1[0-2]|0[1-9]|[1-9]`, `%d` `3[01]|[12]\d|0[1-9]|[1-9]| [1-9]`,
//! `%H` `2[0-3]|[0-1]\d|\d`, `%M` `[0-5]\d|\d`, `%S` `6[0-1]|[0-5]\d|\d`, and `\d` is any Unicode decimal digit (a `str`
//! pattern), read by `int()`. The alternatives are tried in that order and a later failure backtracks into them, as `re`
//! does. A date that is no day of the calendar (`datetime_date(year, month, day)`, so year 0 too) is the ValueError.
//! `calendar.timegm` adds the seconds as they are (60 and 61 included).

use car_machine::pytext::decimal_value;

/// One part of a form.
#[derive(Clone, Copy)]
enum Part {
    Year,
    Month,
    Day,
    Hour,
    Minute,
    Second,
    Literal(char),
}

/// One character class of an alternative: a Unicode digit, an ASCII range, or a space.
#[derive(Clone, Copy)]
enum Class {
    Digit,
    Range(char, char),
    Space,
}

impl Class {
    fn takes(self, c: char) -> bool {
        match self {
            Class::Digit => decimal_value(c).is_some(),
            Class::Range(low, high) => (low..=high).contains(&c),
            Class::Space => c == ' ',
        }
    }
}

const D: Class = Class::Digit;
const fn r(low: char, high: char) -> Class {
    Class::Range(low, high)
}

const YEAR: &[&[Class]] = &[&[D, D, D, D]];
const MONTH: &[&[Class]] = &[
    &[r('1', '1'), r('0', '2')],
    &[r('0', '0'), r('1', '9')],
    &[r('1', '9')],
];
const DAY: &[&[Class]] = &[
    &[r('3', '3'), r('0', '1')],
    &[r('1', '2'), D],
    &[r('0', '0'), r('1', '9')],
    &[r('1', '9')],
    &[Class::Space, r('1', '9')],
];
const HOUR: &[&[Class]] = &[&[r('2', '2'), r('0', '3')], &[r('0', '1'), D], &[D]];
const MINUTE: &[&[Class]] = &[&[r('0', '5'), D], &[D]];
const SECOND: &[&[Class]] = &[&[r('6', '6'), r('0', '1')], &[r('0', '5'), D], &[D]];

fn alternatives(part: Part) -> &'static [&'static [Class]] {
    match part {
        Part::Year => YEAR,
        Part::Month => MONTH,
        Part::Day => DAY,
        Part::Hour => HOUR,
        Part::Minute => MINUTE,
        Part::Second => SECOND,
        Part::Literal(_) => &[],
    }
}

fn parts(form: &str) -> Vec<Part> {
    let mut found = Vec::new();
    let mut chars = form.chars();
    while let Some(c) = chars.next() {
        if c == '%' {
            found.push(match chars.next() {
                Some('Y') => Part::Year,
                Some('m') => Part::Month,
                Some('d') => Part::Day,
                Some('H') => Part::Hour,
                Some('M') => Part::Minute,
                Some('S') => Part::Second,
                other => panic!("a form this module does not read: %{other:?}"),
            });
        } else {
            found.push(Part::Literal(c));
        }
    }
    found
}

/// `int(text)` of a field: its digits' values (a leading space is white space `int()` strips).
fn value(field: &[char]) -> i64 {
    field
        .iter()
        .filter_map(|c| decimal_value(*c))
        .fold(0, |sum, digit| sum * 10 + i64::from(digit))
}

/// The fields of `text` by `form`, in the form's order, or none where the form's expression does not match it whole.
fn matched(text: &[char], form: &[Part]) -> Option<Vec<(usize, i64)>> {
    fn walk(
        text: &[char],
        at: usize,
        form: &[Part],
        index: usize,
        out: &mut Vec<(usize, i64)>,
    ) -> bool {
        let Some(part) = form.get(index) else {
            return at == text.len();
        };
        if let Part::Literal(want) = part {
            let same = text.get(at).is_some_and(|c| {
                c == want || (want.is_ascii_alphabetic() && c.eq_ignore_ascii_case(want))
            });
            return same && walk(text, at + 1, form, index + 1, out);
        }
        for alternative in alternatives(*part) {
            let end = at + alternative.len();
            if end > text.len() {
                continue;
            }
            if alternative
                .iter()
                .zip(&text[at..end])
                .all(|(class, c)| class.takes(*c))
            {
                out.push((index, value(&text[at..end])));
                if walk(text, end, form, index + 1, out) {
                    return true;
                }
                out.pop();
            }
        }
        false
    }
    let mut out = Vec::new();
    walk(text, 0, form, 0, &mut out).then_some(out)
}

/// Days in a month of the proleptic Gregorian calendar.
fn month_days(year: i64, month: i64) -> i64 {
    match month {
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

/// Days from 1970-01-01 to a civil date.
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let of_era = year - era * 400;
    let of_year = (153 * (month + if month > 2 { -3 } else { 9 }) + 2) / 5 + day - 1;
    let of_era_days = of_era * 365 + of_era / 4 - of_era / 100 + of_year;
    era * 146_097 + of_era_days - 719_468
}

/// `calendar.timegm(time.strptime(text, form))`, or `None` for the ValueError `strptime` raises.
pub fn timegm(text: &str, form: &str) -> Option<i64> {
    let chars: Vec<char> = text.chars().collect();
    let form = parts(form);
    let fields = matched(&chars, &form)?;
    let (mut year, mut month, mut day, mut hour, mut minute, mut second) = (1900, 1, 1, 0, 0, 0);
    for (index, number) in fields {
        match form[index] {
            Part::Year => year = number,
            Part::Month => month = number,
            Part::Day => day = number,
            Part::Hour => hour = number,
            Part::Minute => minute = number,
            Part::Second => second = number,
            Part::Literal(_) => {}
        }
    }
    if !(1..=9999).contains(&year) || day > month_days(year, month) {
        return None;
    }
    Some(days_from_civil(year, month, day) * 86_400 + hour * 3_600 + minute * 60 + second)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_forms_read_as_python_reads_them() {
        assert_eq!(
            timegm("1970-01-01T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ"),
            Some(0)
        );
        assert_eq!(
            timegm("2026-10-30T00:00Z", "%Y-%m-%dT%H:%MZ"),
            Some(1_761_782_400)
        );
        assert_eq!(timegm("2024-02-30T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ"), None);
        assert_eq!(timegm("0000-01-01T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ"), None);
        assert_eq!(
            timegm("2026-1-2t3:4:5", "%Y-%m-%dT%H:%M:%S"),
            timegm("2026-01-02T03:04:05", "%Y-%m-%dT%H:%M:%S")
        );
        assert_eq!(
            timegm("2026-01-01T00:00:61Z", "%Y-%m-%dT%H:%M:%SZ"),
            Some(1_767_225_661)
        );
    }
}
