//! `compat/cache.py`: the fetched copy of the data - read, judged against the bundled baseline, imported - and the
//! local checks' helpers.

use std::path::Path;

use car_machine::compat::model::{
    Document, EPOCH_MAX, EPOCH_MIN, MAX_CACHE_BYTES, MAX_DOCUMENT_BYTES, decode, validate_document,
};
use car_machine::domain::states::epoch;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;
use car_machine::vocab_gen::compat_model as words;

use super::files::{load_bundled, read_capped, write_json_atomic};
use super::standing::{RESULTS, Source, UNAVAILABLE, accepted_word, document_standing};

/// The cache as a reader may use it (the reference's dict).
#[derive(Clone, Debug, PartialEq)]
pub struct Cache {
    /// Set only when its data may apply (a restricting standing).
    pub document: Option<Document>,
    pub state: &'static str,
    pub sequence: Option<i64>,
    pub fetched_at: Option<f64>,
    pub origin: Option<String>,
    pub raw: Value,
    /// The document as validated, for `judge_cache`.
    pub validated: Option<Document>,
}

impl Cache {
    /// The dict the reference returns, documents as `Document::to_value` writes them.
    pub fn to_value(&self) -> Value {
        let mut out = Map::new();
        let document =
            |found: &Option<Document>| found.as_ref().map_or(Value::Null, Document::to_value);
        out.insert(Str::from("document"), document(&self.document));
        out.insert(Str::from("state"), Value::from(self.state));
        out.insert(
            Str::from("sequence"),
            self.sequence.map_or(Value::Null, Value::from),
        );
        out.insert(
            Str::from("fetched_at"),
            self.fetched_at.map_or(Value::Null, Value::Float),
        );
        out.insert(
            Str::from("origin"),
            self.origin.as_deref().map_or(Value::Null, Value::from),
        );
        out.insert(Str::from("raw"), self.raw.clone());
        out.insert(Str::from("validated"), document(&self.validated));
        Value::Object(out)
    }
}

/// `_cache_empty(state)`.
pub fn cache_empty(state: &'static str) -> Cache {
    Cache {
        document: None,
        state,
        sequence: None,
        fetched_at: None,
        origin: None,
        raw: Value::Null,
        validated: None,
    }
}

fn get<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// `read_cache(path, bundled=, product=, now=)`: validated whole, then judged against the baseline and the clock.
pub fn read_cache(path: &str, bundled: Option<&Document>, product: &str, now: f64) -> Cache {
    if !Path::new(path).exists() {
        return cache_empty("absent");
    }
    let read = (|| {
        let envelope = decode(&read_capped(path, MAX_CACHE_BYTES)?, MAX_CACHE_BYTES)?;
        if !matches!(envelope, Value::Object(_))
            || !pyval::is(get(&envelope, "format"), words::CACHE_FORMAT)
            || !pyval::in_tuple(get(&envelope, "origin"), words::CACHE_ORIGINS)
        {
            return Ok(None);
        }
        let fetched = get(&envelope, "fetched_at");
        if !epoch(fetched, EPOCH_MIN, EPOCH_MAX, false, false).unwrap_or(false) {
            return Ok(None);
        }
        let document = validate_document(get(&envelope, "document"))?;
        Ok::<_, car_machine::compat::model::DocumentError>(Some((envelope.clone(), document)))
    })();
    let Ok(Some((envelope, document))) = read else {
        return cache_empty("rejected");
    };
    let fetched = pyval::Num::of(get(&envelope, "fetched_at")).map(pyval::Num::as_f64);
    let cache = Cache {
        document: None,
        state: "absent",
        sequence: Some(document.sequence),
        fetched_at: fetched,
        origin: pyval::text(get(&envelope, "origin")).map(str::to_owned),
        raw: get(&envelope, "document").clone(),
        validated: Some(document),
    };
    judge_cache(&cache, bundled, product, now)
}

/// `judge_cache(cache, bundled=, product=, now=)`: a cache `read_cache` returned, judged again at `now`.
pub fn judge_cache(cache: &Cache, bundled: Option<&Document>, product: &str, now: f64) -> Cache {
    let Some(validated) = &cache.validated else {
        return cache.clone();
    };
    let standing = document_standing(validated, product, bundled, now, false);
    Cache {
        state: standing,
        document: words::RESTRICTING_STATES
            .contains(&standing)
            .then(|| validated.clone()),
        ..cache.clone()
    }
}

/// `_sources_of(bundled, cache)`: the documents in force, as `evidence_for` weighs them.
pub fn sources_of<'a>(bundled: Option<&'a Document>, cache: &'a Cache) -> Vec<Source<'a>> {
    vec![
        ("bundled", bundled, true),
        (
            "cache",
            cache.document.as_ref(),
            words::TRUSTING_STATES.contains(&cache.state),
        ),
    ]
}

/// `data_in_force(paths, product=, now=)`: the bundled baseline and the cache, read and judged now.
pub fn data_in_force(
    bundled_path: &str,
    cache_path: &str,
    product: &str,
    now: f64,
) -> (Option<Document>, Cache) {
    let (bundled, _) = load_bundled(bundled_path, product);
    let cache = read_cache(cache_path, bundled.as_ref(), product, now);
    (bundled, cache)
}

/// `engine_word(paths, version, now=)`: what the registry data in force says about an engine that passed its checks.
pub fn engine_word(
    bundled_path: &str,
    cache_path: &str,
    version: &Value,
    product: &str,
    now: f64,
) -> &'static str {
    let (bundled, cache) = data_in_force(bundled_path, cache_path, product, now);
    accepted_word(version, &sources_of(bundled.as_ref(), &cache))
}

fn refused(reason: &str, sequence: Option<i64>) -> Value {
    let mut out = Map::new();
    out.insert(Str::from("imported"), Value::Bool(false));
    out.insert(Str::from("reason"), Value::from(reason));
    out.insert(
        Str::from("sequence"),
        sequence.map_or(Value::Null, Value::from),
    );
    out.insert(Str::from("cache"), Value::Null);
    Value::Object(out)
}

/// `Path(file).suffix` as pathlib gives it (3.13): from the last dot of the name, where that dot is neither its first
/// nor its last character.
fn suffix(file: &str) -> String {
    let name = crate::paths::name_of(file);
    let chars: Vec<char> = name.chars().collect();
    match chars.iter().rposition(|c| *c == '.') {
        Some(at) if at > 0 && at < chars.len() - 1 => chars[at..].iter().collect(),
        _ => String::new(),
    }
}

/// `import_document(paths, file, origin=, product=, now=)`: validate one document and, only if it passes, make it
/// the cache. `ensure` is `paths.ensure()`.
#[allow(clippy::too_many_arguments)]
pub fn import_document(
    bundled_path: &str,
    cache_path: &str,
    ensure: &dyn Fn() -> bool,
    file: Option<&str>,
    origin: &Value,
    product: &str,
    now: f64,
) -> Value {
    if !pyval::in_tuple(origin, words::CACHE_ORIGINS) {
        return refused("invalid_field", None);
    }
    let json = crate::refold::points(".json");
    let Some(file) = file
        .filter(|file| crate::refold::lower_points(&crate::refold::points(&suffix(file))) == json)
    else {
        return refused("not_a_json_file", None);
    };
    let (raw, document) = match read_capped(file, MAX_DOCUMENT_BYTES)
        .and_then(|bytes| decode(&bytes, MAX_DOCUMENT_BYTES))
        .and_then(|raw| validate_document(&raw).map(|document| (raw, document)))
    {
        Ok(found) => found,
        Err(refusal) => return refused(refusal.code, None),
    };
    let (bundled, _) = load_bundled(bundled_path, product);
    let standing = document_standing(&document, product, bundled.as_ref(), now, false);
    let sequence = Some(document.sequence);
    match standing {
        "from_newer_product" => return refused("from_newer_product", sequence),
        "superseded" => return refused("rollback", sequence),
        "from_the_future" => return refused("from_the_future", sequence),
        "rejected" => return refused("invalid_field", sequence),
        _ => {}
    }
    let current = read_cache(cache_path, bundled.as_ref(), product, now);
    if let Some(held) = current.sequence
        && current.state != "rejected"
        && document.sequence < held
    {
        return refused("rollback", sequence);
    }
    let mut envelope = Map::new();
    envelope.insert(Str::from("format"), Value::from(words::CACHE_FORMAT));
    envelope.insert(Str::from("fetched_at"), Value::Float(now));
    envelope.insert(Str::from("origin"), origin.clone());
    envelope.insert(Str::from("document"), raw);
    let envelope = Value::Object(envelope);
    let encoded = to_string(
        &envelope,
        &Options::wire().separators(",", ":").sort_keys(true),
    )
    .unwrap_or_default();
    if encoded.len() > MAX_CACHE_BYTES {
        return refused("too_large", sequence);
    }
    if !ensure() || write_json_atomic(cache_path, &envelope, "compat-cache.").is_err() {
        return refused("write_failed", sequence);
    }
    let mut out = Map::new();
    out.insert(Str::from("imported"), Value::Bool(true));
    out.insert(Str::from("reason"), Value::Null);
    out.insert(Str::from("sequence"), Value::from(document.sequence));
    out.insert(Str::from("cache"), Value::from(standing));
    Value::Object(out)
}

/// `_coerce(result)`: a local check's result, or UNAVAILABLE.
pub fn coerce(result: &Value) -> &'static str {
    RESULTS
        .iter()
        .copied()
        .find(|word| pyval::is(result, word))
        .unwrap_or(UNAVAILABLE)
}
