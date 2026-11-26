//! Seat S7.4: `evidence.py` - one content-free record per measurement, in the live-acceptance envelope, in
//! `docs/evidence/live/`.
//!
//! A record holds booleans, counts, the engine's own closed words, verdicts, and ids only as the aliases the
//! diagnostics export writes; anything else is refused before a byte is written. The files are written as the
//! reference's `Path.write_text` writes them: `json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False)` and a
//! newline, in text mode (each `\n` written `\r\n`), UTF-8 - a lone surrogate fails after the file was opened (and so
//! emptied), as Python's encoder does.
//!
//! The one change of place: the reference's default directory is four parents above its own source file. A Rust
//! binary has no source file at run time and must not carry its build path (check_rebuild), so [`default_directory`]
//! is the first `docs/evidence/live` above the running program, and where there is none a path that is not there, so
//! [`write`] refuses as the reference refuses an installed copy.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use car_machine::json::{Map, Options, Str, Value, from_str, to_string};
use car_machine::pytext::py_str;
use car_machine::vocab_gen::domain_public::TURN_STATUSES;
use car_policy::classify::failures::CATEGORIES;
use car_policy::classify::text::is_word;

use crate::codex::protocol;
use crate::vocabulary::{
    AutoResult, CheckGrade, ClosedWord, Measurement, NoteCode, ObservedWord, PlanWord,
    SpendOutcome, Verdict,
};

/// The tag `scripts/live_evidence.py` skips these files by.
pub const MEASUREMENT_FORMAT: &str = "codex-auto-resume-measurement/1";
/// codex/authfile's four words (`USABLE`, `NOT_FILE`, `NO_FILE`, `UNREADABLE`): S7.2b's module is not on this base.
pub const AUTHFILE_WORDS: [&str; 4] = ["usable", "not_file", "no_file", "unreadable"];

/// What a record or a completion was refused with.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Fault {
    /// `EvidenceError(reason)`: a static reason only, never the value refused.
    Evidence(&'static str),
    /// Any other exception the reference lets out, by class (`ValueError` from `allow_nan=False`, `OSError`, ...).
    Raised(&'static str),
}

impl Fault {
    pub fn class(&self) -> &'static str {
        match self {
            Fault::Evidence(_) => "EvidenceError",
            Fault::Raised(class) => class,
        }
    }
}

/// `DEFAULT_DIRECTORY` (see the module's note).
pub fn default_directory() -> PathBuf {
    let tail = Path::new("docs").join("evidence").join("live");
    if let Ok(exe) = std::env::current_exe() {
        for folder in exe.ancestors().skip(1) {
            let candidate = folder.join(&tail);
            if candidate.is_dir() {
                return candidate;
            }
        }
        if let Some(folder) = exe.parent() {
            return folder.join(&tail);
        }
    }
    tail
}

/// `CLOSED_WORDS`.
pub fn closed_words() -> BTreeSet<&'static str> {
    fn all<W: ClosedWord>(words: &mut BTreeSet<&'static str>) {
        words.extend(W::all().iter().map(|each| each.word()));
    }
    let mut words: BTreeSet<&'static str> = BTreeSet::new();
    words.extend(TURN_STATUSES.iter().copied());
    words.extend(CATEGORIES.iter().copied());
    all::<Verdict>(&mut words);
    all::<SpendOutcome>(&mut words);
    all::<ObservedWord>(&mut words);
    all::<PlanWord>(&mut words);
    all::<AutoResult>(&mut words);
    all::<CheckGrade>(&mut words);
    words.extend(AUTHFILE_WORDS);
    words
}

/// `_closed(value)`: a closed word or a method some measurement declared.
pub fn closed(value: &str) -> bool {
    closed_words().contains(value) || protocol::measured_methods().contains(value)
}

/// `ALIAS_RE.match`: `^(?:thread|record|chain)-[0-9a-f]{8}$` - `$` also before one final newline.
pub fn is_alias(value: &str) -> bool {
    let body = value.strip_suffix('\n').unwrap_or(value);
    let Some((prefix, hex)) = body.split_once('-') else {
        return false;
    };
    matches!(prefix, "thread" | "record" | "chain")
        && hex.len() == 8
        && hex
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// `_content_free(value)`.
pub fn content_free(value: &Value) -> bool {
    match value {
        Value::Null | Value::Bool(_) | Value::Int(_) => true,
        Value::Str(text) => match text.as_str() {
            Some(text) => is_alias(text) || closed(text),
            None => false,
        },
        _ => false,
    }
}

// ------------------------------------------------------------------ diagnostics' four expressions, as `search`
fn word_at(chars: &[char], at: usize) -> bool {
    chars.get(at).is_some_and(|c| is_word(*c as u32))
}

fn boundary(chars: &[char], at: usize) -> bool {
    let before = at > 0 && word_at(chars, at - 1);
    before != word_at(chars, at)
}

fn hex_lower(c: char) -> bool {
    c.is_ascii_digit() || ('a'..='f').contains(&c)
}

/// `UUID_RE`: `\b[0-9a-fA-F]{8}-...-[0-9a-fA-F]{12}\b`.
fn uuid_at(chars: &[char], at: usize) -> bool {
    if !boundary(chars, at) {
        return false;
    }
    let mut end = at;
    for (index, size) in [8usize, 4, 4, 4, 12].iter().enumerate() {
        if index > 0 {
            if chars.get(end) != Some(&'-') {
                return false;
            }
            end += 1;
        }
        for _ in 0..*size {
            if !chars.get(end).is_some_and(char::is_ascii_hexdigit) {
                return false;
            }
            end += 1;
        }
    }
    boundary(chars, end)
}

/// `KEY_RE`: `\b[0-9a-f]{12,64}\b`.
fn key_at(chars: &[char], at: usize) -> bool {
    if !boundary(chars, at) {
        return false;
    }
    let run = chars[at..].iter().take_while(|c| hex_lower(**c)).count();
    (12..=run.min(64)).any(|length| boundary(chars, at + length))
}

/// `EMAIL_RE`: `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`.
fn email_at(chars: &[char], at: usize) -> bool {
    let local = chars[at..]
        .iter()
        .take_while(|c| c.is_ascii_alphanumeric() || "._%+-".contains(**c))
        .count();
    for split in (1..=local).rev() {
        if chars.get(at + split) != Some(&'@') {
            continue;
        }
        let start = at + split + 1;
        let domain = chars[start..]
            .iter()
            .take_while(|c| c.is_ascii_alphanumeric() || ".-".contains(**c))
            .count();
        for length in (1..=domain).rev() {
            let dot = start + length;
            if chars.get(dot) != Some(&'.') {
                continue;
            }
            let letters = chars[dot + 1..]
                .iter()
                .take_while(|c| c.is_ascii_alphabetic())
                .count();
            if letters >= 2 {
                return true;
            }
        }
    }
    false
}

/// `PATH_RE`: `(?:[A-Za-z]:[\\/]|\\\\\?\\|\\\\)...` - a match needs only its lead.
fn path_at(chars: &[char], at: usize) -> bool {
    (chars.get(at).is_some_and(char::is_ascii_alphabetic)
        && chars.get(at + 1) == Some(&':')
        && chars.get(at + 2).is_some_and(|c| *c == '\\' || *c == '/'))
        || (chars.get(at) == Some(&'\\') && chars.get(at + 1) == Some(&'\\'))
}

fn search(text: &str, matcher: fn(&[char], usize) -> bool) -> bool {
    let chars: Vec<char> = text.chars().collect();
    (0..=chars.len()).any(|at| matcher(&chars, at))
}

/// `_no_content(text)`.
pub fn no_content(text: &str) -> bool {
    !(search(text, uuid_at)
        || search(text, key_at)
        || search(text, path_at)
        || search(text, email_at)
        || text.contains('\\'))
}

/// `re.fullmatch(r"[a-z][a-z0-9_]{0,47}", key)`.
fn plain_key(key: &str) -> bool {
    let bytes = key.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 48
        && bytes[0].is_ascii_lowercase()
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'_')
}

fn text(value: &str) -> Value {
    Value::Str(Str::new(value))
}

/// The envelope's text fields as handed in (`str()` of each is written).
pub struct Envelope<'a> {
    pub product_version: &'a Value,
    pub codex_version: &'a Value,
    pub windows_build: &'a Value,
    pub recorded_at: &'a Value,
}

/// `build(measurement, verdict, observed, ..., note=note)`. `observed` is any value (a non-object is refused); the
/// note any value or none.
pub fn build(
    measurement: Measurement,
    verdict: Verdict,
    observed: &Value,
    envelope: &Envelope<'_>,
    note: Option<&Value>,
) -> Result<Map, Fault> {
    let Value::Object(observed) = observed else {
        return Err(Fault::Evidence(
            "an observation is an object of what was seen",
        ));
    };
    for (key, value) in observed {
        if !key.as_str().is_some_and(plain_key) {
            return Err(Fault::Evidence("an observed field's name is a plain word"));
        }
        if !content_free(value) {
            return Err(Fault::Evidence(
                "an observed value is not a boolean, a count, an alias or a closed word; the record holds nothing else",
            ));
        }
    }
    let mut record = Map::new();
    record.insert(Str::new("format"), text(MEASUREMENT_FORMAT));
    record.insert(Str::new("step"), text(measurement.as_str()));
    record.insert(Str::new("verdict"), text(verdict.as_str()));
    for (field, value) in [
        ("recorded_at", envelope.recorded_at),
        ("product_version", envelope.product_version),
        ("codex_version", envelope.codex_version),
        ("windows_build", envelope.windows_build),
    ] {
        record.insert(Str::new(field), text(&py_str(value)));
    }
    record.insert(Str::new("observed"), Value::Object(observed.clone()));
    let note_text = match note {
        Some(Value::Str(found)) => found.as_str().map(str::to_owned),
        _ => None,
    };
    let noted = note_text
        .as_deref()
        .is_some_and(|found| !car_machine::pytext::strip(found).is_empty());
    if verdict != Verdict::Pass && !noted {
        return Err(Fault::Evidence(
            "a verdict that is not a pass needs a note saying what happened",
        ));
    }
    if let Some(found) = note {
        if !matches!(found, Value::Str(_)) {
            return Err(Fault::Evidence("a note is text"));
        }
        record.insert(Str::new("note"), found.clone());
    }
    let mut fields = vec![
        "recorded_at",
        "product_version",
        "codex_version",
        "windows_build",
    ];
    if note_text.as_deref().is_some_and(|found| !found.is_empty()) {
        fields.push("note");
    }
    for field in fields {
        let value = record.get(&Str::new(field)).map(py_str).unwrap_or_default();
        if !no_content(&value) {
            return Err(Fault::Evidence(
                "a field holds something that identifies a person, a path or a conversation; a record never does",
            ));
        }
    }
    Ok(record)
}

/// `path_for(measurement, directory=directory)`.
pub fn path_for(measurement: Measurement, directory: Option<&Path>) -> PathBuf {
    let directory = directory.map_or_else(default_directory, Path::to_path_buf);
    directory.join(format!("measurement-{}.json", measurement.as_str()))
}

/// `json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"`.
fn dumps(record: &Map) -> Result<Str, Fault> {
    let written = to_string(
        &Value::Object(record.clone()),
        &Options::new().ensure_ascii(false).indent(2),
    )
    .map_err(|_| Fault::Raised("ValueError"))?;
    let mut bytes = written.into_bytes();
    bytes.push(b'\n');
    Str::from_surrogatepass(bytes).ok_or(Fault::Raised("ValueError"))
}

/// `Path.write_text(text, encoding="utf-8")` in text mode on Windows: opened (emptied) first, each `\n` written
/// `\r\n`; a lone surrogate is a UnicodeEncodeError after the open.
fn write_text(target: &Path, text: &Str) -> Result<(), Fault> {
    let mut file =
        std::fs::File::create(target).map_err(|error| Fault::Raised(os_class(&error)))?;
    let Some(text) = text.as_str() else {
        return Err(Fault::Raised("UnicodeEncodeError"));
    };
    let translated = text.replace('\n', "\r\n");
    std::io::Write::write_all(&mut file, translated.as_bytes())
        .map_err(|error| Fault::Raised(os_class(&error)))
}

/// The OSError subclass Python raises for an I/O failure, as the diffs compare it.
pub fn os_class(error: &std::io::Error) -> &'static str {
    match error.kind() {
        std::io::ErrorKind::NotFound => "FileNotFoundError",
        std::io::ErrorKind::PermissionDenied => "PermissionError",
        std::io::ErrorKind::AlreadyExists => "FileExistsError",
        _ => match error.raw_os_error() {
            Some(267) => "NotADirectoryError",
            _ => "OSError",
        },
    }
}

/// `complete(measurement, verdict, note, codex_version=..., recorded_at=..., directory=...)`: the file written.
/// `note` is the person's word, refused unless a `NoteCode`; `str()` of `codex_version` is compared.
pub fn complete(
    measurement: Measurement,
    verdict: Verdict,
    note: &str,
    codex_version: &Value,
    recorded_at: &str,
    directory: Option<&Path>,
) -> Result<PathBuf, Fault> {
    if !matches!(verdict, Verdict::Pass | Verdict::Fail) {
        return Err(Fault::Evidence("a completion is a pass or a fail"));
    }
    let Some(note) = crate::vocabulary::parse::<NoteCode>(note) else {
        return Err(Fault::Evidence(
            "a completion's note is one of the closed note codes",
        ));
    };
    let target = path_for(measurement, directory);
    if !target.is_file() {
        return Err(Fault::Evidence(
            "there is no blocked record of this measurement to complete",
        ));
    }
    let unreadable = Fault::Evidence("the record could not be read to complete it");
    let bytes = std::fs::read(&target).map_err(|_| unreadable.clone())?;
    let decoded = String::from_utf8(bytes).map_err(|_| unreadable.clone())?;
    // Text mode reads `\r\n` and a lone `\r` as `\n`.
    let decoded = decoded.replace("\r\n", "\n").replace('\r', "\n");
    let record = from_str(&decoded).map_err(|_| unreadable)?;
    let Value::Object(mut record) = record else {
        return Err(Fault::Evidence("the file is not a measurement record"));
    };
    let is = |record: &Map, name: &str, wanted: &str| matches!(record.get(&Str::new(name)), Some(Value::Str(found)) if found.as_bytes() == wanted.as_bytes());
    if !is(&record, "format", MEASUREMENT_FORMAT) {
        return Err(Fault::Evidence("the file is not a measurement record"));
    }
    if !is(&record, "step", measurement.as_str()) {
        return Err(Fault::Evidence("the record is of another measurement"));
    }
    if !is(&record, "verdict", "blocked") {
        return Err(Fault::Evidence(
            "only a blocked record can be completed by hand",
        ));
    }
    let recorded = record
        .get(&Str::new("codex_version"))
        .cloned()
        .unwrap_or(Value::Null);
    if py_str(&recorded) != py_str(codex_version) {
        return Err(Fault::Evidence(
            "the blocked record was measured on another Codex; re-measure first",
        ));
    }
    let mut completion = Map::new();
    completion.insert(Str::new("verdict"), text(verdict.as_str()));
    completion.insert(Str::new("note"), text(note.as_str()));
    completion.insert(Str::new("recorded_at"), text(recorded_at));
    for value in [verdict.as_str(), note.as_str(), recorded_at] {
        if !no_content(value) {
            return Err(Fault::Evidence(
                "a completion field holds something that identifies a person, a path or a conversation; a record never does",
            ));
        }
    }
    record.insert(Str::new("completion"), Value::Object(completion));
    let written = dumps(&record)?;
    write_text(&target, &written)?;
    Ok(target)
}

/// `outcome(record)`: (verdict, Codex version) the record settles, or None.
pub fn outcome(record: &Value) -> Option<(Verdict, String)> {
    let Value::Object(record) = record else {
        return None;
    };
    let get = |name: &str| record.get(&Str::new(name));
    if !matches!(get("format"), Some(Value::Str(found)) if found.as_bytes() == MEASUREMENT_FORMAT.as_bytes())
    {
        return None;
    }
    let mut verdict = get("verdict").cloned().unwrap_or(Value::Null);
    if matches!(&verdict, Value::Str(found) if found.as_bytes() == b"blocked")
        && let Some(Value::Object(completion)) = get("completion")
    {
        verdict = completion
            .get(&Str::new("verdict"))
            .cloned()
            .unwrap_or(Value::Null);
    }
    let verdict = match &verdict {
        Value::Str(found) if found.as_bytes() == b"pass" => Verdict::Pass,
        Value::Str(found) if found.as_bytes() == b"fail" => Verdict::Fail,
        _ => return None,
    };
    match get("codex_version") {
        Some(Value::Str(version)) => version.as_str().map(|found| (verdict, found.to_owned())),
        _ => None,
    }
}

/// `write(record, directory=directory)`: the directory must be there already.
pub fn write(record: &Map, directory: Option<&Path>) -> Result<PathBuf, Fault> {
    let directory = directory.map_or_else(default_directory, Path::to_path_buf);
    if !directory.is_dir() {
        return Err(Fault::Evidence(
            "docs/evidence/live/ is not here; run the measurement from the source tree, not an installed copy",
        ));
    }
    let step = record
        .get(&Str::new("step"))
        .map(py_str)
        .unwrap_or_default();
    let target = directory.join(format!("measurement-{step}.json"));
    let written = dumps(record)?;
    write_text(&target, &written)?;
    Ok(target)
}
