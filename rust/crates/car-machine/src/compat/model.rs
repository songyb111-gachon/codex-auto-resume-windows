//! `compat/model.py`: the Compatibility Registry's format: every closed word, the limits, parsing and validation.
//!
//! Pure: no file, no process, no clock that is not handed in. What a document may contain is decided here and
//! nowhere else. The words (states, results, tiers, checks, capabilities, reasons) are generated into
//! [`crate::vocab_gen::compat_model`] and [`crate::vocab_gen::domain_compat_vocabulary`]; the regular expressions
//! of the Python are matched by hand, with the decimal digits of every script that `\d` takes in a `str` pattern.

use crate::json::{Map, Str, Value};
use crate::pytext::{decimal_value, is_digit};
use crate::vocab_gen::compat_model as words;

pub use super::decode::{DocumentError, MAX_DOCUMENT_BYTES, decode};

pub const FORMAT_MAJOR: &str = words::FORMAT_MAJOR;
pub const MAX_CACHE_BYTES: usize = MAX_DOCUMENT_BYTES + 4 * 1024;
pub const MAX_REPORT_BYTES: usize = 64 * 1024;
pub const MAX_ENGINES: usize = 500;
pub const MAX_ADVISORIES: usize = 200;
pub const MAX_EVIDENCE: usize = 8;
/// A published_at this far ahead of the local clock is not believed.
pub const FUTURE_SKEW_SECONDS: i64 = 24 * 3600;
/// How far a refreshed document's sequence may run ahead of the bundled baseline's.
pub const MAX_SEQUENCE_LEAD: i64 = 100;
/// A report newer than the clock by more than this is not believed either.
pub const REPORT_FUTURE_SECONDS: i64 = 300;
pub const RECOMPUTE_SECONDS: i64 = 600;
pub const REPORT_MAX_AGE: i64 = RECOMPUTE_SECONDS + 3600 + 300;
/// 2000-01-01 to 2100-01-01, as Codex's history.
pub const EPOCH_MIN: i64 = 946_684_800;
pub const EPOCH_MAX: i64 = 4_102_444_800;
pub const RESTRICTING_STATES: &[&str] = &["ok", "expired", "from_the_future"];
pub const TRUSTING_STATES: &[&str] = &["ok"];

/// A capability's claim in a document.
#[derive(Clone, Debug, PartialEq)]
pub struct Claim {
    pub state: &'static str,
    pub reason: String,
    pub evidence: Vec<String>,
}

/// A range advisory (it can only restrict).
#[derive(Clone, Debug, PartialEq)]
pub struct Advisory {
    pub id: String,
    pub low: Option<[i64; 6]>,
    pub high: Option<[i64; 6]>,
    /// The known capabilities it names, sorted.
    pub capabilities: Vec<String>,
    pub reason: String,
}

/// A registry document, validated whole and normalised.
#[derive(Clone, Debug, PartialEq)]
pub struct Document {
    pub sequence: i64,
    pub published_at: f64,
    pub expires_at: Option<f64>,
    pub min_product: [i64; 3],
    pub engines: Vec<(String, Vec<(String, Claim)>)>,
    pub advisories: Vec<Advisory>,
}

fn invalid() -> DocumentError {
    DocumentError::new("invalid_field")
}

// ------------------------------------------------------------------------------ versions
struct Cursor<'a> {
    chars: &'a [char],
    at: usize,
}

impl Cursor<'_> {
    fn take(&mut self, word: &str) -> bool {
        let each: Vec<char> = word.chars().collect();
        if self.chars.get(self.at..self.at + each.len()) == Some(&each[..]) {
            self.at += each.len();
            true
        } else {
            false
        }
    }

    /// `(\d{low,high})`: the digits greedily, none left over to the next piece that is itself a digit.
    fn number(&mut self, low: usize, high: usize) -> Option<i64> {
        let start = self.at;
        let mut value: i64 = 0;
        while self.at - start < high && self.chars.get(self.at).is_some_and(|c| is_digit(*c)) {
            value = value * 10 + decimal_value(self.chars[self.at])? as i64;
            self.at += 1;
        }
        (self.at - start >= low).then_some(value)
    }

    fn done(&self) -> bool {
        self.at == self.chars.len()
    }
}

/// `MAJOR.MINOR.PATCH[-alpha.N[.M]]` after an optional prefix, as an ordering key: a pre-release sorts before its
/// release.
fn release_key(cursor: &mut Cursor) -> Option<[i64; 6]> {
    let major = cursor.number(1, 6)?;
    cursor.take(".").then_some(())?;
    let minor = cursor.number(1, 6)?;
    cursor.take(".").then_some(())?;
    let patch = cursor.number(1, 6)?;
    if cursor.take("-alpha.") {
        let alpha = cursor.number(1, 9)?;
        let sub = if cursor.take(".") {
            cursor.number(1, 9)?
        } else {
            0
        };
        return Some([major, minor, patch, 0, alpha, sub]);
    }
    Some([major, minor, patch, 1, 0, 0])
}

fn fully(text: &str, prefix: &str) -> Option<[i64; 6]> {
    let chars: Vec<char> = text.chars().collect();
    let mut cursor = Cursor {
        chars: &chars,
        at: 0,
    };
    if !prefix.is_empty() && !cursor.take(prefix) {
        return None;
    }
    let key = release_key(&mut cursor)?;
    cursor.done().then_some(key)
}

/// `parse_version(text)`: `codex-cli MAJOR.MINOR.PATCH[-alpha.N[.M]]` to an ordering key, or none.
pub fn parse_version(text: &Value) -> Option<[i64; 6]> {
    let Value::Str(found) = text else { return None };
    fully(crate::pytext::strip(found.as_str()?), "codex-cli ")
}

/// `_bound(text)`: a range's bound.
fn bound(text: &Value) -> Result<[i64; 6], DocumentError> {
    match text {
        Value::Str(found) => found
            .as_str()
            .and_then(|each| fully(each, ""))
            .ok_or_else(invalid),
        _ => Err(invalid()),
    }
}

/// `product_key(text)`: `MAJOR.MINOR.PATCH` of this product.
pub fn product_key(text: &Value) -> Option<[i64; 3]> {
    let Value::Str(found) = text else { return None };
    let chars: Vec<char> = crate::pytext::strip(found.as_str()?).chars().collect();
    let mut cursor = Cursor {
        chars: &chars,
        at: 0,
    };
    let major = cursor.number(1, 6)?;
    cursor.take(".").then_some(())?;
    let minor = cursor.number(1, 6)?;
    cursor.take(".").then_some(())?;
    let patch = cursor.number(1, 6)?;
    cursor.done().then_some([major, minor, patch])
}

/// `safe_version(text)`: the version string if it is one a report may carry.
pub fn safe_version(text: &Value) -> Option<&str> {
    let Value::Str(found) = text else { return None };
    let each = found.as_str()?;
    let mut chars = each.chars();
    let first = chars.next()?;
    let allowed = |c: char| c.is_ascii_alphanumeric() || " ._+()-".contains(c);
    (first.is_ascii_alphanumeric() && each.chars().count() <= 80 && chars.all(allowed))
        .then_some(each)
}

/// Days in a month of the proleptic Gregorian calendar.
fn month_days(year: i64, month: i64) -> i64 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ => {
            if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) {
                29
            } else {
                28
            }
        }
    }
}

/// Days from 1970-01-01 to a civil date.
fn days_from_epoch(year: i64, month: i64, day: i64) -> i64 {
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (month + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// `_timestamp(text)`: `YYYY-MM-DDTHH:MM:SSZ` (any script's digits) to seconds since 1970, or `invalid_field`.
fn timestamp(value: &Value, optional: bool) -> Result<Option<f64>, DocumentError> {
    if matches!(value, Value::Null) && optional {
        return Ok(None);
    }
    let Value::Str(found) = value else {
        return Err(invalid());
    };
    let chars: Vec<char> = found.as_str().ok_or_else(invalid)?.chars().collect();
    let mut cursor = Cursor {
        chars: &chars,
        at: 0,
    };
    let year = cursor.number(4, 4).ok_or_else(invalid)?;
    let mut field = |separator: &str, width: i64| -> Option<i64> {
        cursor.take(separator).then_some(())?;
        cursor.number(width as usize, width as usize)
    };
    let (month, day) = (
        field("-", 2).ok_or_else(invalid)?,
        field("-", 2).ok_or_else(invalid)?,
    );
    let (hour, minute) = (
        field("T", 2).ok_or_else(invalid)?,
        field(":", 2).ok_or_else(invalid)?,
    );
    let second = field(":", 2).ok_or_else(invalid)?;
    if !cursor.take("Z") || !cursor.done() {
        return Err(invalid());
    }
    let valid = year >= 1
        && (1..=12).contains(&month)
        && (1..=month_days(year, month)).contains(&day)
        && hour <= 23
        && minute <= 59
        && second <= 61;
    if !valid {
        return Err(invalid());
    }
    let seconds = ((days_from_epoch(year, month, day) * 24 + hour) * 60 + minute) * 60 + second;
    if !(EPOCH_MIN..=EPOCH_MAX).contains(&seconds) {
        return Err(invalid());
    }
    Ok(Some(seconds as f64))
}

/// `_integer(value, low=0, high=2**31-1)`.
fn integer(value: &Value) -> Result<i64, DocumentError> {
    match value {
        Value::Int(int) => int
            .as_i64()
            .filter(|each| (0..=i64::from(i32::MAX)).contains(each))
            .ok_or_else(invalid),
        _ => Err(invalid()),
    }
}

fn registry_reason(value: Option<&Value>) -> String {
    match value {
        Some(Value::Str(found)) => match found.as_str() {
            Some(each) if words::REGISTRY_REASONS.contains(&each) => each.to_owned(),
            _ => "unspecified".to_owned(),
        },
        _ => "unspecified".to_owned(),
    }
}

/// `EVIDENCE_RE.fullmatch(path)` and no `..` in it.
fn evidence_path(path: &str) -> bool {
    let Some(rest) = path.strip_prefix("docs/evidence/") else {
        return false;
    };
    let Some(body) = rest.strip_suffix(".json") else {
        return false;
    };
    let bytes = rest.as_bytes();
    if bytes.len() > 9 && bytes[..9].eq_ignore_ascii_case(b"community") && bytes[9] == b'/' {
        return false;
    }
    // `body` is the path before ".json"; the regular expression sees "<segments>.json", whose last segment may
    // itself end in a dot only if the segment before ".json" does not end with one.
    let valid = body.split('/').all(|segment| {
        !segment.is_empty()
            && segment
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || "._-".contains(c))
            && !segment.ends_with('.')
    });
    valid && !path.contains("..")
}

fn date_text(text: &str) -> bool {
    let chars: Vec<char> = text.chars().collect();
    let mut cursor = Cursor {
        chars: &chars,
        at: 0,
    };
    cursor.number(4, 4).is_some()
        && cursor.take("-")
        && cursor.number(2, 2).is_some()
        && cursor.take("-")
        && cursor.number(2, 2).is_some()
        && cursor.done()
}

fn advisory_id(text: &str) -> bool {
    let chars: Vec<char> = text.chars().collect();
    let mut cursor = Cursor {
        chars: &chars,
        at: 0,
    };
    cursor.take("CAR-")
        && cursor.number(4, 4).is_some()
        && cursor.take("-")
        && cursor.number(4, 4).is_some()
        && cursor.done()
}

fn string_of(value: &Value) -> Option<&str> {
    match value {
        Value::Str(found) => found.as_str(),
        _ => None,
    }
}

fn is_str(value: &Value) -> bool {
    matches!(value, Value::Str(_))
}

/// `validate_document(value)`: a registry document, validated whole and normalised, or the `DocumentError`.
pub fn validate_document(value: &Value) -> Result<Document, DocumentError> {
    let Value::Object(top) = value else {
        return Err(DocumentError::new("not_an_object"));
    };
    let declared = top.get("format");
    let known = declared
        .and_then(string_of)
        .is_some_and(|text| text.strip_prefix(words::FORMAT_PREFIX) == Some(FORMAT_MAJOR));
    if !known {
        return Err(DocumentError::new("unknown_format"));
    }
    match top.get("requires_signature") {
        None | Some(Value::Bool(false)) => {}
        Some(Value::Bool(true)) => return Err(DocumentError::new("signature_required")),
        Some(_) => return Err(invalid()),
    }
    for reserved in ["signature", "key_id"] {
        match top.get(reserved) {
            None | Some(Value::Null) => {}
            Some(Value::Str(slot)) if slot.code_points().count() <= 8192 => {}
            Some(_) => return Err(invalid()),
        }
    }
    let null = Value::Null;
    let sequence = integer(top.get("sequence").unwrap_or(&null))?;
    let published =
        timestamp(top.get("published_at").unwrap_or(&null), false)?.ok_or_else(invalid)?;
    let expires = timestamp(top.get("expires_at").unwrap_or(&null), true)?;
    if expires.is_some_and(|until| until <= published) {
        return Err(invalid());
    }
    let minimum = product_key(top.get("min_product").unwrap_or(&null)).ok_or_else(invalid)?;

    let engines_in: &[Value] = match top.get("engines") {
        None => &[],
        Some(Value::Array(items)) => items,
        Some(_) => return Err(invalid()),
    };
    if engines_in.len() > MAX_ENGINES {
        return Err(DocumentError::new("too_many"));
    }
    let mut engines: Vec<(String, Vec<(String, Claim)>)> = Vec::new();
    for entry in engines_in {
        let Value::Object(entry) = entry else {
            return Err(invalid());
        };
        let version = entry.get("version").unwrap_or(&null);
        if safe_version(version).is_none() || parse_version(version).is_none() {
            return Err(invalid());
        }
        let name = string_of(version).ok_or_else(invalid)?.to_owned();
        if engines.iter().any(|(seen, _)| *seen == name) {
            return Err(invalid());
        }
        let listed: &Map = match entry.get("capabilities") {
            None => &Map::new(),
            Some(Value::Object(map)) => map,
            Some(_) => return Err(invalid()),
        };
        let mut capabilities = Vec::new();
        for (capability, claim) in listed {
            let Value::Object(claim) = claim else {
                return Err(invalid());
            };
            let evidence: &[Value] = match claim.get("evidence") {
                None => &[],
                Some(Value::Array(items)) if items.len() <= MAX_EVIDENCE => items,
                Some(_) => return Err(invalid()),
            };
            for path in evidence {
                if !string_of(path).is_some_and(evidence_path) {
                    return Err(invalid());
                }
            }
            match claim.get("verified_at") {
                None | Some(Value::Null) => {}
                Some(Value::Str(day)) if day.as_str().is_some_and(date_text) => {}
                Some(_) => return Err(invalid()),
            }
            let state = claim.get("state").and_then(string_of);
            let capability_name = capability.as_str();
            let state = match (capability_name, state) {
                (Some(each), Some(state))
                    if words::CAPABILITIES.get(each).is_some()
                        && ["VERIFIED", "CHECKED", "INCOMPATIBLE"].contains(&state) =>
                {
                    state
                }
                _ => continue,
            };
            if state != "INCOMPATIBLE" && evidence.is_empty() {
                return Err(DocumentError::new("unevidenced_verified"));
            }
            capabilities.push((
                capability_name.unwrap_or_default().to_owned(),
                Claim {
                    state: match state {
                        "VERIFIED" => "VERIFIED",
                        "CHECKED" => "CHECKED",
                        _ => "INCOMPATIBLE",
                    },
                    reason: registry_reason(claim.get("reason")),
                    evidence: evidence
                        .iter()
                        .filter_map(|p| string_of(p).map(str::to_owned))
                        .collect(),
                },
            ));
        }
        engines.push((name, capabilities));
    }

    let advisories_in: &[Value] = match top.get("advisories") {
        None => &[],
        Some(Value::Array(items)) => items,
        Some(_) => return Err(invalid()),
    };
    if advisories_in.len() > MAX_ADVISORIES {
        return Err(DocumentError::new("too_many"));
    }
    let mut advisories: Vec<Advisory> = Vec::new();
    for advisory in advisories_in {
        let Value::Object(advisory) = advisory else {
            return Err(invalid());
        };
        let identifier = advisory.get("id").and_then(string_of);
        let Some(identifier) = identifier.filter(|text| advisory_id(text)) else {
            return Err(invalid());
        };
        if advisories.iter().any(|seen| seen.id == identifier) {
            return Err(invalid());
        }
        if !advisory
            .get("state")
            .is_some_and(|state| string_of(state) == Some("INCOMPATIBLE"))
        {
            return Err(DocumentError::new("range_cannot_grant"));
        }
        let Some(Value::Object(matching)) = advisory.get("match") else {
            return Err(invalid());
        };
        if !(matching.contains_key("version_gte") || matching.contains_key("version_lt")) {
            return Err(invalid());
        }
        let low = matching.get("version_gte").map(bound).transpose()?;
        let high = matching.get("version_lt").map(bound).transpose()?;
        if let (Some(low), Some(high)) = (low, high)
            && low >= high
        {
            return Err(invalid());
        }
        let names = match advisory.get("capabilities") {
            Some(Value::Array(names)) if !names.is_empty() && names.iter().all(is_str) => names,
            _ => return Err(invalid()),
        };
        let mut known: Vec<String> = names
            .iter()
            .filter_map(string_of)
            .filter(|each| words::CAPABILITIES.get(each).is_some())
            .map(str::to_owned)
            .collect();
        known.sort();
        known.dedup();
        advisories.push(Advisory {
            id: identifier.to_owned(),
            low,
            high,
            capabilities: known,
            reason: registry_reason(advisory.get("reason")),
        });
    }
    Ok(Document {
        sequence,
        published_at: published,
        expires_at: expires,
        min_product: minimum,
        engines,
        advisories,
    })
}

/// `parse_document(raw, limit)`.
pub fn parse_document(raw: &[u8], limit: usize) -> Result<Document, DocumentError> {
    validate_document(&decode(raw, limit)?)
}

impl Document {
    /// The document as the Python's dict reads once tuples are lists and the frozensets sorted.
    pub fn to_value(&self) -> Value {
        let key =
            |parts: &[i64]| Value::Array(parts.iter().map(|each| Value::from(*each)).collect());
        let mut out = Map::new();
        out.insert(Str::from("sequence"), Value::from(self.sequence));
        out.insert(Str::from("published_at"), Value::Float(self.published_at));
        out.insert(
            Str::from("expires_at"),
            self.expires_at.map_or(Value::Null, Value::Float),
        );
        out.insert(Str::from("min_product"), key(&self.min_product));
        out.insert(Str::from("requires_signature"), Value::Bool(false));
        let mut engines = Map::new();
        for (version, capabilities) in &self.engines {
            let mut each = Map::new();
            for (name, claim) in capabilities {
                let mut entry = Map::new();
                entry.insert(Str::from("state"), Value::from(claim.state));
                entry.insert(Str::from("reason"), Value::from(claim.reason.as_str()));
                entry.insert(
                    Str::from("evidence"),
                    Value::Array(
                        claim
                            .evidence
                            .iter()
                            .map(|p| Value::from(p.as_str()))
                            .collect(),
                    ),
                );
                each.insert(Str::from(name.as_str()), Value::Object(entry));
            }
            engines.insert(Str::from(version.as_str()), Value::Object(each));
        }
        out.insert(Str::from("engines"), Value::Object(engines));
        let advisories = self
            .advisories
            .iter()
            .map(|advisory| {
                let mut entry = Map::new();
                entry.insert(Str::from("id"), Value::from(advisory.id.as_str()));
                entry.insert(
                    Str::from("low"),
                    advisory.low.map_or(Value::Null, |each| key(&each)),
                );
                entry.insert(
                    Str::from("high"),
                    advisory.high.map_or(Value::Null, |each| key(&each)),
                );
                entry.insert(
                    Str::from("capabilities"),
                    Value::Array(
                        advisory
                            .capabilities
                            .iter()
                            .map(|c| Value::from(c.as_str()))
                            .collect(),
                    ),
                );
                entry.insert(Str::from("reason"), Value::from(advisory.reason.as_str()));
                Value::Object(entry)
            })
            .collect();
        out.insert(Str::from("advisories"), Value::Array(advisories));
        Value::Object(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::from_str;

    #[test]
    fn versions() {
        let version = |text: &str| parse_version(&from_str(&format!("\"{text}\"")).unwrap());
        assert_eq!(version("codex-cli 0.171.0"), Some([0, 171, 0, 1, 0, 0]));
        assert_eq!(
            version("codex-cli 0.171.0-alpha.13.2"),
            Some([0, 171, 0, 0, 13, 2])
        );
        assert_eq!(version("codex-cli 0.171"), None);
        assert_eq!(version("codex-cli 1234567.0.0"), None);
    }

    #[test]
    fn evidence() {
        assert!(evidence_path("docs/evidence/codex/0.171.json"));
        assert!(!evidence_path("docs/evidence/community/a.json"));
        assert!(!evidence_path("docs/evidence/CommunitY/x.json"));
        assert!(evidence_path("docs/evidence/community.json"));
        assert!(!evidence_path("docs/evidence/a./b.json"));
        assert!(evidence_path("docs/evidence/communityx/a.json"));
    }

    #[test]
    fn a_minimal_document() {
        let text = r#"{"format": "codex-auto-resume-compat/1", "sequence": 3, "published_at": "2026-11-01T00:00:00Z",
                        "min_product": "0.6.26"}"#;
        let document = parse_document(text.as_bytes(), MAX_DOCUMENT_BYTES).unwrap();
        assert_eq!(document.sequence, 3);
        assert_eq!(document.min_product, [0, 6, 26]);
    }
}
