//! `compatdata.py`: the advanced edition's compatibility data - the owner's measurement verdicts for each Codex engine,
//! published between releases - read whole or not at all, and laid over this build's table by the five trust rules
//! (seat S7.2c).
//!
//! 1. a fail in this build's own table (`measured::MEASURED`) always wins: data never turns it into a pass;
//! 2. only the entry for the EXACT engine in force counts;
//! 3. a data fail on that engine narrows;
//! 4. a data pass on that engine stands in only where this build has no verdict for that engine;
//! 5. a document that is expired, malformed in any part, meant for a newer product, or older than what is in force is
//!    ignored whole, and the table alone stands.
//!
//! [`table_for`] is the one seam `arming` reads (`seam::Edges::table_for`); [`in_force`] and [`adopt`] judge the file the
//! bootstrap downloads (`config/compat-advanced.download.json`) and adopt it into `config/compat-advanced.json`. The
//! product's own version (`codex_auto_resume.__version__`, the tag's `this_product()`) is handed in by the caller, never
//! read here. The reference's `_SEEN` keeps parsed documents by their bytes' digest: a memo whose answers are those of a
//! fresh parse, so it is not kept here.

use std::path::{Path, PathBuf};

use car_machine::compat::decode;
use car_machine::compat::model::parse_version;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pytext::{decimal_value, strip};

use crate::measured::Table;
use crate::pytime::timegm;
use crate::vocabulary::{Measurement, Verdict, parse};

pub const FORMAT: &str = "codex-auto-resume-compat-advanced/1";
pub const REPOSITORY_PATH: &str = "advanced/compat/codex_compat_advanced.json";
pub const DOWNLOAD: &str = "compat-advanced.download.json";
pub const ADOPTED: &str = "compat-advanced.json";
pub const MAX_BYTES: usize = 256 * 1024;
pub const MAX_ENGINES: usize = 64;
pub const MAX_MEASUREMENTS: usize = 128;
pub const TOP_KEYS: [&str; 6] = [
    "format",
    "sequence",
    "published_at",
    "expires_at",
    "min_product",
    "engines",
];
pub const EDITION_KEY: &str = "_edition";
pub const EDITION_MARK: &str =
    "ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.";
pub const ENGINE_KEYS: [&str; 2] = ["version", "measurements"];
pub const ENTRY_KEYS: [&str; 3] = ["verdict", "recorded_at", "evidence"];
pub const EVIDENCE: &str = "docs/evidence/advanced/%s/measurement-%s.json";

/// `this_product()`'s tuple: MAJOR, MINOR, PATCH.
pub type Product = (i64, i64, i64);

/// `Refused`: a document that is not read at all, with one closed code.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Refused(pub &'static str);

/// One engine's verdicts in a document: `{Measurement: (Verdict, recorded_at)}` in the document's order.
pub type Verdicts = Vec<(Measurement, (Verdict, f64))>;

/// A validated document: `{"sequence", "published_at", "expires_at", "engines": {version: {Measurement: (Verdict,
/// recorded_at)}}}`.
#[derive(Clone, Debug, PartialEq)]
pub struct Document {
    pub sequence: i64,
    pub published_at: f64,
    pub expires_at: f64,
    /// `{version: verdicts}` in the document's order; the version as the document wrote it.
    pub engines: Vec<(Str, Verdicts)>,
}

impl Document {
    /// `document["engines"].get(engine, {})`.
    pub fn engine(&self, engine: &str) -> Option<&Verdicts> {
        self.engines
            .iter()
            .find(|(version, _)| version.as_bytes() == engine.as_bytes())
            .map(|(_, found)| found)
    }
}

/// `slug(version)`: the folder an engine's frozen records are kept in (`codex-cli 0.165.0` is `codex-cli-0.165.0`).
pub fn slug(version: &str) -> String {
    version.replace(' ', "-")
}

/// `evidence_path(version, measurement)`.
pub fn evidence_path(version: &str, measurement: &str) -> String {
    format!(
        "docs/evidence/advanced/{}/measurement-{measurement}.json",
        slug(version)
    )
}

/// `evidence_path` over a version that may hold half a surrogate pair (the document's own text, byte for byte).
fn evidence_bytes(version: &Str, measurement: &str) -> Vec<u8> {
    let mut made = b"docs/evidence/advanced/".to_vec();
    made.extend(
        version
            .as_bytes()
            .iter()
            .map(|byte| if *byte == b' ' { b'-' } else { *byte }),
    );
    made.extend_from_slice(b"/measurement-");
    made.extend_from_slice(measurement.as_bytes());
    made.extend_from_slice(b".json");
    made
}

/// `pattern.fullmatch(text)` of `\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ` (`seconds`) or `\d{4}-\d\d-\d\dT\d\d:\d\dZ`, `\d` a Unicode digit.
fn shaped(text: &str, seconds: bool) -> bool {
    let shape = if seconds {
        "dddd-dd-ddTdd:dd:ddZ"
    } else {
        "dddd-dd-ddTdd:ddZ"
    };
    let chars: Vec<char> = text.chars().collect();
    chars.len() == shape.len()
        && shape.chars().zip(&chars).all(|(want, c)| {
            if want == 'd' {
                decimal_value(*c).is_some()
            } else {
                *c == want
            }
        })
}

/// `_moment(text, pattern, form)`.
fn moment(value: &Value, seconds: bool) -> Result<f64, Refused> {
    let Value::Str(text) = value else {
        return Err(Refused("invalid_time"));
    };
    let Some(text) = text.as_str().filter(|text| shaped(text, seconds)) else {
        return Err(Refused("invalid_time"));
    };
    let form = if seconds {
        "%Y-%m-%dT%H:%M:%SZ"
    } else {
        "%Y-%m-%dT%H:%MZ"
    };
    timegm(text, form)
        .map(|at| at as f64)
        .ok_or(Refused("invalid_time"))
}

/// `PRODUCT.fullmatch(text)` of `(\d{1,6})\.(\d{1,6})\.(\d{1,6})` (where `_product`'s `match` reads the same groups).
fn product_of(text: &str) -> Option<Product> {
    let mut groups = text.split('.');
    let mut take = || -> Option<i64> {
        let group: Vec<char> = groups.next()?.chars().collect();
        if group.is_empty() || group.len() > 6 {
            return None;
        }
        group.iter().try_fold(0i64, |sum, c| {
            decimal_value(*c).map(|digit| sum * 10 + i64::from(digit))
        })
    };
    let found = (take()?, take()?, take()?);
    groups.next().is_none().then_some(found)
}

/// `this_product()` of the product's own version text (`codex_auto_resume.__version__`): `_product`, a `match` at its
/// start, so `0.6.27-alpha` reads `(0, 6, 27)`.
pub fn this_product(version: &str) -> Option<Product> {
    // The longest prefix that is three groups: the third takes as many digits (at most six) as follow.
    let chars: Vec<char> = version.chars().collect();
    let mut at = 0;
    let mut numbers = Vec::new();
    for group in 0..3 {
        let start = at;
        while at < chars.len() && at - start < 6 && decimal_value(chars[at]).is_some() {
            at += 1;
        }
        if at == start {
            return None;
        }
        numbers.push(chars[start..at].iter().fold(0i64, |sum, c| {
            sum * 10 + i64::from(decimal_value(*c).unwrap_or(0))
        }));
        if group < 2 {
            if chars.get(at) != Some(&'.') {
                return None;
            }
            at += 1;
        }
    }
    Some((numbers[0], numbers[1], numbers[2]))
}

/// `set(mapping) == keys`.
fn keys_are(map: &Map, keys: &[&str]) -> bool {
    map.len() == keys.len() && keys.iter().all(|key| map.contains_key(*key))
}

/// `ID.fullmatch(name)`: `m[a-z0-9]{1,15}`.
fn is_id(name: &str) -> bool {
    let bytes = name.as_bytes();
    (2..=16).contains(&bytes.len())
        && bytes[0] == b'm'
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
}

/// `validate(raw, product=product)`: a document's bytes, judged whole. `product` is what the caller's `this_product()`
/// gave where none was handed in (`None`: the product's version could not be read, and every document is too new).
pub fn validate(raw: &[u8], product: Option<Product>) -> Result<Document, Refused> {
    let document = decode(raw, MAX_BYTES).map_err(|error| Refused(error.code))?;
    let Value::Object(document) = document else {
        return Err(Refused("keys"));
    };
    let has_mark = document.contains_key(EDITION_KEY);
    let others = document.len() - usize::from(has_mark);
    if others != TOP_KEYS.len() || !TOP_KEYS.iter().all(|key| document.contains_key(*key)) {
        return Err(Refused("keys"));
    }
    if has_mark
        && !matches!(&document[EDITION_KEY], Value::Str(mark) if mark.as_bytes() == EDITION_MARK.as_bytes())
    {
        return Err(Refused("keys"));
    }
    if !matches!(&document["format"], Value::Str(format) if format.as_bytes() == FORMAT.as_bytes())
    {
        return Err(Refused("unknown_format"));
    }
    let sequence = match &document["sequence"] {
        Value::Int(number) => number.as_i64().filter(|n| (1..=2_147_483_647).contains(n)),
        _ => None,
    }
    .ok_or(Refused("invalid_sequence"))?;
    let published = moment(&document["published_at"], true)?;
    let expires = moment(&document["expires_at"], true)?;
    if expires <= published {
        return Err(Refused("invalid_time"));
    }
    let minimum = match &document["min_product"] {
        Value::Str(text) => text.as_str().and_then(product_of),
        _ => None,
    }
    .ok_or(Refused("invalid_product"))?;
    match product {
        Some(product) if minimum <= product => {}
        _ => return Err(Refused("newer_product")),
    }
    let Value::Array(engines_in) = &document["engines"] else {
        return Err(Refused("invalid_engines"));
    };
    if engines_in.len() > MAX_ENGINES {
        return Err(Refused("invalid_engines"));
    }
    let mut engines: Vec<(Str, Verdicts)> = Vec::new();
    for engine in engines_in {
        let Value::Object(engine) = engine else {
            return Err(Refused("invalid_engine"));
        };
        if !keys_are(engine, &ENGINE_KEYS) {
            return Err(Refused("invalid_engine"));
        }
        let version = match &engine["version"] {
            Value::Str(version) => version,
            _ => return Err(Refused("invalid_version")),
        };
        let shaped_version = parse_version(&engine["version"]).is_some()
            && version.as_str().is_some_and(|text| {
                strip(text) == text && text.starts_with("codex-cli ") && text.chars().count() <= 60
            });
        if !shaped_version {
            return Err(Refused("invalid_version"));
        }
        if engines.iter().any(|(seen, _)| seen == version) {
            return Err(Refused("duplicate_engine"));
        }
        let Value::Object(measurements) = &engine["measurements"] else {
            return Err(Refused("invalid_measurements"));
        };
        if measurements.len() > MAX_MEASUREMENTS {
            return Err(Refused("invalid_measurements"));
        }
        let mut found: Verdicts = Vec::new();
        for (name, entry) in measurements {
            let Some(name) = name.as_str().filter(|name| is_id(name)) else {
                return Err(Refused("invalid_measurement"));
            };
            let Value::Object(entry) = entry else {
                return Err(Refused("invalid_entry"));
            };
            if !keys_are(entry, &ENTRY_KEYS) {
                return Err(Refused("invalid_entry"));
            }
            let verdict = match &entry["verdict"] {
                Value::Str(word) if word.as_bytes() == b"pass" => Verdict::Pass,
                Value::Str(word) if word.as_bytes() == b"fail" => Verdict::Fail,
                _ => return Err(Refused("invalid_verdict")),
            };
            let recorded = moment(&entry["recorded_at"], false)?;
            if recorded > published {
                return Err(Refused("invalid_time"));
            }
            let evidence_matches = matches!(&entry["evidence"], Value::Str(evidence) if evidence.as_bytes() == evidence_bytes(version, name).as_slice());
            if !evidence_matches {
                return Err(Refused("invalid_evidence"));
            }
            if let Some(measurement) = parse::<Measurement>(name) {
                match found.iter_mut().find(|(seen, _)| *seen == measurement) {
                    Some(slot) => slot.1 = (verdict, recorded),
                    None => found.push((measurement, (verdict, recorded))),
                }
            }
        }
        engines.push((version.clone(), found));
    }
    Ok(Document {
        sequence,
        published_at: published,
        expires_at: expires,
        engines,
    })
}

/// `_read(path, product=product)`: the document at `path`, validated, or none where there is none or it is refused.
pub fn read(path: &Path, product: Option<Product>) -> Option<Document> {
    let size = std::fs::metadata(path).ok()?.len();
    if size > MAX_BYTES as u64 {
        return None;
    }
    let raw = car_machine::pyfile::read(path).ok()?;
    validate(&raw, product).ok()
}

/// `_fresh(document, now)`.
fn fresh(document: Option<&Document>, now: f64) -> bool {
    document.is_some_and(|document| {
        document.published_at <= now + 86_400.0 && now < document.expires_at
    })
}

/// `adopt(state_dir, bundled=bundled, now=now, product=product)`: a download the bootstrap left, adopted (an atomic
/// replace of ADOPTED) only when valid, unexpired and newer than both what is adopted and what is bundled; then removed,
/// whatever it was.
pub fn adopt(state_dir: &Path, bundled: Option<&Path>, now: f64, product: Option<Product>) {
    let download = state_dir.join(DOWNLOAD);
    if !download.is_file() {
        return;
    }
    let found = read(&download, product);
    let floor = [
        Some(state_dir.join(ADOPTED)),
        bundled.map(Path::to_path_buf),
    ]
    .iter()
    .flatten()
    .filter_map(|path| read(path, product))
    .map(|document| document.sequence)
    .max()
    .unwrap_or(0);
    if fresh(found.as_ref(), now)
        && found
            .as_ref()
            .is_some_and(|document| document.sequence > floor)
        && car_machine::pyfile::replace(&download, state_dir.join(ADOPTED)).is_ok()
    {
        return;
    }
    let _ = std::fs::remove_file(&download);
}

/// `in_force(state_dir, bundled=bundled, now=now, product=product)`: the document in force now - the adopted one or the
/// bundled one, whichever valid and unexpired one has the higher sequence - or none.
pub fn in_force(
    state_dir: Option<&Path>,
    bundled: Option<&Path>,
    now: f64,
    product: Option<Product>,
) -> Option<Document> {
    if let Some(folder) = state_dir {
        adopt(folder, bundled, now, product);
    }
    let mut candidates: Vec<Option<Document>> = Vec::new();
    if let Some(bundled) = bundled {
        candidates.push(read(bundled, product));
    }
    if let Some(folder) = state_dir {
        candidates.push(read(&folder.join(ADOPTED), product));
    }
    let mut best: Option<Document> = None;
    for document in candidates.into_iter().flatten() {
        if !fresh(Some(&document), now) {
            continue;
        }
        // `max` keeps the first of equals.
        if best
            .as_ref()
            .is_none_or(|held| document.sequence > held.sequence)
        {
            best = Some(document);
        }
    }
    best
}

/// `overlay(table, document, engine)`: `table` with `document`'s verdicts for exactly `engine` laid over it by the trust
/// rules. Pure.
pub fn overlay(table: &Table, document: Option<&Document>, engine: Option<&str>) -> Table {
    let mut found = table.clone();
    let (Some(document), Some(engine)) = (document, engine) else {
        return found;
    };
    for (measurement, (verdict, _recorded)) in document.engine(engine).into_iter().flatten() {
        let built = found.get(measurement).cloned();
        let (built_verdict, built_on) = match &built {
            Some((verdict, on)) => (Some(*verdict), Some(on.as_str())),
            None => (None, None),
        };
        if built_verdict == Some(Verdict::Fail) {
            continue;
        }
        if *verdict == Verdict::Fail {
            found.insert(*measurement, (Verdict::Fail, engine.to_owned()));
        } else if built_verdict.is_none() || built_on != Some(engine) {
            found.insert(*measurement, (Verdict::Pass, engine.to_owned()));
        }
    }
    found
}

/// `table_for(paths, engine, table=table, now=now)`: this build's table with the data in force laid over it, for the
/// Codex `engine` in force on the installation whose state folder is `state_dir`.
pub fn table_for(
    state_dir: Option<&Path>,
    engine: Option<&str>,
    table: &Table,
    now: f64,
    product: Option<Product>,
) -> Table {
    overlay(
        table,
        in_force(state_dir, None, now, product).as_ref(),
        engine,
    )
}

/// `summary(document)`: what the Dashboard may say of the data in force.
pub fn summary(document: Option<&Document>) -> Value {
    let mut out = Map::new();
    match document {
        None => {
            out.insert("sequence".into(), Value::Null);
        }
        Some(document) => {
            out.insert("sequence".into(), Value::from(document.sequence));
            out.insert("published_at".into(), Value::Float(document.published_at));
            out.insert("expires_at".into(), Value::Float(document.expires_at));
            out.insert("engines".into(), Value::from(document.engines.len() as i64));
        }
    }
    Value::Object(out)
}

/// Stand-ins for what `json.dumps` writes as `NaN`, `Infinity` and `-Infinity` (its default `allow_nan=True`), which
/// car-machine's writer refuses: written as these words, then put back as Python's literals.
const NOT_FINITE: [(&str, &str); 3] = [
    ("\u{e000}compatdata NaN\u{e000}", "NaN"),
    ("\u{e000}compatdata Infinity\u{e000}", "Infinity"),
    ("\u{e000}compatdata -Infinity\u{e000}", "-Infinity"),
];

fn finite(value: &Value) -> Value {
    match value {
        Value::Float(number) if !number.is_finite() => {
            let index = if number.is_nan() {
                0
            } else if *number > 0.0 {
                1
            } else {
                2
            };
            Value::from(NOT_FINITE[index].0)
        }
        Value::Array(items) => Value::Array(items.iter().map(finite).collect()),
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(key, item)| (key.clone(), finite(item)))
                .collect(),
        ),
        other => other.clone(),
    }
}

/// `dumps(document)`: a document as the admin program writes it - two-space JSON, ASCII, keys in order, one newline at
/// the end; `NaN` and the infinities as Python writes them. `None` where `json.dumps` raises (a nesting past its reach).
pub fn dumps(document: &Value) -> Option<String> {
    let options = Options::new().indent(2).ensure_ascii(true);
    let mut text = to_string(&finite(document), &options).ok()?;
    for (stand_in, literal) in NOT_FINITE {
        let written = to_string(&Value::from(stand_in), &options).ok()?;
        text = text.replace(&written, literal);
    }
    Some(text + "\n")
}

/// Where the paths of an installation keep the data: its state folder (`paths.state_dir`).
pub fn state_dir(paths: &car_config::Paths) -> PathBuf {
    PathBuf::from(&paths.state_dir)
}
