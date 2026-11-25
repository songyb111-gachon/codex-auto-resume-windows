//! How the surfaces speak: the language this process renders in (`l10n.current()`, which the caller resolves through
//! car-words with the platform's languages) and the local clock (`time.localtime`, car-policy's `LocalClock`), handed
//! in once instead of read from process globals.

use car_machine::json::Value;
use car_machine::pyval::Py;
use car_policy::classify::clock::LocalClock;
use car_words::l10n;

use crate::py::str_of;

/// The language and the clock every sentence of a surface is said in.
#[derive(Clone, Copy)]
pub struct Speech<'a> {
    /// `l10n.current()`: a locale of `l10n::LOCALES`.
    pub locale: &'a str,
    pub clock: &'a dyn LocalClock,
}

impl<'a> Speech<'a> {
    pub fn new(locale: &'a str, clock: &'a dyn LocalClock) -> Speech<'a> {
        Speech { locale, clock }
    }

    /// `l10n.text(key, current(), **fields)`: a KeyError for a key no catalog has.
    pub fn text(&self, key: &str, fields: &[(&str, String)]) -> Py<String> {
        l10n::text(key, self.locale, fields).ok_or("KeyError")
    }

    /// `l10n.message(key)`.
    pub fn message(&self, key: &str) -> Py<String> {
        self.text(&format!("msg.{key}"), &[])
    }

    /// `notify._run(value)`: `l10n.embedded(value, current())`.
    pub fn run(&self, value: &Value) -> String {
        l10n::embedded(&Value::from(str_of(value)), self.locale)
    }

    /// `notify._local_time(when)`: `time.strftime("%H:%M", time.localtime(when))`, kept one run.
    pub fn local_time(&self, when: &Value) -> Py<String> {
        let tm = match when {
            Value::Null => self.clock.localtime_now()?,
            Value::Bool(on) => self.clock.localtime(f64::from(u8::from(*on)))?,
            Value::Int(int) => {
                let whole = int.as_i64().ok_or("OverflowError")?;
                // Past 2**53 a time_t is centuries past the C runtime's last day (3000-12-31): its refusal.
                if whole.unsigned_abs() > 1 << 53 {
                    return Err("OSError");
                }
                self.clock.localtime(whole as f64)?
            }
            Value::Float(x) => self.clock.localtime(*x)?,
            _ => return Err("TypeError"),
        };
        Ok(self.run(&Value::from(format!("{:02}:{:02}", tm.hour, tm.min))))
    }
}

/// `template.format(**fields)` as `str.format` reads a catalog's sentence: `{name}` filled, `{{` and `}}` one brace;
/// a field this call does not name is a KeyError, a numbered or empty one an IndexError, a lone brace a ValueError.
/// A field's conversion (`!s`, `!r`) and a text's fill, alignment and width are kept; any other format is a
/// ValueError (no catalog has one: `tests/rustdiff/diffs_surface_notify.py` formats every catalog's three).
pub fn format(template: &str, fields: &[(&str, String)]) -> Py<String> {
    let chars: Vec<char> = template.chars().collect();
    let mut out = String::new();
    let mut at = 0;
    while at < chars.len() {
        let c = chars[at];
        if c == '}' {
            if chars.get(at + 1) == Some(&'}') {
                out.push('}');
                at += 2;
                continue;
            }
            return Err("ValueError");
        }
        if c != '{' {
            out.push(c);
            at += 1;
            continue;
        }
        if chars.get(at + 1) == Some(&'{') {
            out.push('{');
            at += 2;
            continue;
        }
        let Some(end) = chars[at + 1..].iter().position(|each| *each == '}') else {
            return Err("ValueError");
        };
        let field: String = chars[at + 1..at + 1 + end].iter().collect();
        at += end + 2;
        let (head, spec) = field.split_once(':').unwrap_or((field.as_str(), ""));
        let (name, conversion) = head.split_once('!').unwrap_or((head, ""));
        if name.is_empty()
            || name
                .chars()
                .next()
                .is_some_and(|first| first.is_ascii_digit())
        {
            return Err("IndexError");
        }
        if name.contains(['.', '[']) {
            return Err("ValueError");
        }
        let value = fields
            .iter()
            .find(|(each, _)| *each == name)
            .map(|(_, value)| value.clone())
            .ok_or("KeyError")?;
        let value = match conversion {
            "" | "s" => value,
            "r" => crate::py::repr(&Value::from(value.as_str())),
            _ => return Err("ValueError"),
        };
        out.push_str(&pad(&value, spec)?);
    }
    Ok(out)
}

/// `format(text, spec)` for `[[fill]align][width]`.
fn pad(value: &str, spec: &str) -> Py<String> {
    if spec.is_empty() {
        return Ok(value.to_owned());
    }
    let chars: Vec<char> = spec.chars().collect();
    let aligns = ['<', '>', '^'];
    let (fill, align, rest) = if chars.len() >= 2 && aligns.contains(&chars[1]) {
        (chars[0], chars[1], &chars[2..])
    } else if aligns.contains(&chars[0]) {
        (' ', chars[0], &chars[1..])
    } else {
        (' ', '<', &chars[..])
    };
    let width: String = rest.iter().collect();
    let width: usize = if width.is_empty() {
        0
    } else if width.bytes().all(|b| b.is_ascii_digit()) {
        width.parse().map_err(|_| "ValueError")?
    } else {
        return Err("ValueError");
    };
    let length = value.chars().count();
    if length >= width {
        return Ok(value.to_owned());
    }
    let space = width - length;
    let filler = |n: usize| std::iter::repeat_n(fill, n).collect::<String>();
    Ok(match align {
        '>' => format!("{}{value}", filler(space)),
        '^' => format!("{}{value}{}", filler(space / 2), filler(space - space / 2)),
        _ => format!("{value}{}", filler(space)),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats() {
        let fields = [("time", "09:05".to_owned())];
        assert_eq!(format("Resets {time}", &fields).unwrap(), "Resets 09:05");
        assert_eq!(format("{{time}} {time}", &fields).unwrap(), "{time} 09:05");
        assert_eq!(format("{other}", &fields), Err("KeyError"));
        assert_eq!(format("{0}", &fields), Err("IndexError"));
        assert_eq!(format("{", &fields), Err("ValueError"));
        assert_eq!(format("}", &fields), Err("ValueError"));
        assert_eq!(format("[{time:>7}]", &fields).unwrap(), "[  09:05]");
    }
}
