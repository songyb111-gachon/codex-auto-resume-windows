//! The writer against the reference: Python's own `json.dumps`, byte for byte (PLAN 5.3, S0.2).
//!
//! Values are generated here from a seed, sent to `python -I` in a lossless form of our own
//! (below), written there by the standard library's `json` with each place's options, and the
//! bytes compared with ours. A refusal is compared too: which error, not only that there was one.
//!
//! `CAR_JSON_COUNT` (default 20000) and `CAR_JSON_SEED` (default `SEED`) choose the run;
//! `CAR_JSON_PYTHON` the interpreter (default `python`). The done-check is a million:
//!
//! ```text
//! CAR_JSON_COUNT=1000000 cargo test --release --locked --test json_reference -- --nocapture
//! ```
//!
//! The lossless form, one value a line, ASCII:
//! `n` `t` `f`; `i<decimal>;`; `d<16 hex digits: the f64's bits>`; `s<hex of the bytes
//! s.encode("utf-8", "surrogatepass") gives>;`; `[<count>;` and the items; `{<count>;` and each
//! key (an `s`) followed by its value.

use std::fmt::Write as _;
use std::io::{BufReader, BufWriter, Read, Write};
use std::process::{Command, Stdio};

use car_machine::json::{Error, Int, Map, Options, Str, Value, to_string};

const SEED: u64 = 0x5EED_2026_1124_0627;

/// The product's option sets (src/json/mod.rs lists each place), as Rust and as Python's
/// keyword arguments. `_stream` writes through `json.dump` into a stream, which is Python's
/// pure-Python encoder, as compat/files.py, oncewords.py, poweraction.py and seen.py do.
fn configs() -> Vec<(Options, &'static str)> {
    let wire = Options::wire;
    vec![
        (wire(), r#"{"ensure_ascii": False}"#),
        (
            wire().indent(2).sort_keys(true),
            r#"{"ensure_ascii": False, "indent": 2, "sort_keys": True}"#,
        ),
        (wire().indent(2), r#"{"ensure_ascii": False, "indent": 2}"#),
        (wire().indent(1), r#"{"ensure_ascii": False, "indent": 1}"#),
        (
            wire().separators(",", ":").sort_keys(true),
            r#"{"ensure_ascii": False, "separators": (",", ":"), "sort_keys": True}"#,
        ),
        (
            wire().separators(",", ":").sort_keys(true),
            r#"{"ensure_ascii": False, "separators": (",", ":"), "sort_keys": True, "_stream": True}"#,
        ),
        (
            wire().sort_keys(true),
            r#"{"ensure_ascii": False, "sort_keys": True}"#,
        ),
        (
            wire().sort_keys(true),
            r#"{"ensure_ascii": False, "sort_keys": True, "_stream": True}"#,
        ),
        (Options::new().sort_keys(true), r#"{"sort_keys": True}"#),
        (
            Options::new().sort_keys(true),
            r#"{"sort_keys": True, "_stream": True}"#,
        ),
        (Options::new(), r#"{}"#),
        (Options::new(), r#"{"_stream": True}"#),
        (Options::new().indent(2), r#"{"indent": 2}"#),
        (
            Options::new().separators(",", ":"),
            r#"{"separators": (",", ":")}"#,
        ),
        (
            Options::new().separators(",", ":").sort_keys(true),
            r#"{"separators": (",", ":"), "sort_keys": True}"#,
        ),
    ]
}

/// Python's side. Reads the configurations, then one value a line; answers, for each value and
/// each configuration in order, `O` + 4-byte length + the UTF-8 bytes, or `E` + a code: `N` a
/// NaN or infinity, `L` an int past the digit limit, `R` too deep, `U` the UTF-8 write refused
/// (a surrogate), `X` + length + message for anything else.
const SCRIPT: &str = r#"
import ast, io, json, struct, sys

DIGITS = sys.get_int_max_str_digits()

def parse(b, i):
    c = b[i]
    if c == 110:
        return None, i + 1
    if c == 116:
        return True, i + 1
    if c == 102:
        return False, i + 1
    if c == 105:
        j = b.index(59, i)
        text = b[i + 1:j]
        if len(text) > 4000:
            sys.set_int_max_str_digits(0)
            value = int(text)
            sys.set_int_max_str_digits(DIGITS)
        else:
            value = int(text)
        return value, j + 1
    if c == 100:
        return struct.unpack(">d", bytes.fromhex(b[i + 1:i + 17].decode("ascii")))[0], i + 17
    if c == 115:
        j = b.index(59, i)
        return bytes.fromhex(b[i + 1:j].decode("ascii")).decode("utf-8", "surrogatepass"), j + 1
    if c == 91:
        j = b.index(59, i)
        count, i = int(b[i + 1:j]), j + 1
        items = []
        for _ in range(count):
            item, i = parse(b, i)
            items.append(item)
        return items, i
    if c == 123:
        j = b.index(59, i)
        count, i = int(b[i + 1:j]), j + 1
        entries = {}
        for _ in range(count):
            key, i = parse(b, i)
            entries[key], i = parse(b, i)
        return entries, i
    raise SystemExit("unknown tag %r at %d" % (chr(c), i))

def main():
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    plan = []
    for kw in ast.literal_eval(source.readline().decode("ascii")):
        kw = dict(kw)
        stream = kw.pop("_stream", False)
        plan.append((stream, dict(kw, allow_nan=False)))
    for line in source:
        value, _ = parse(line, 0)
        chunks = []
        for stream, kw in plan:
            try:
                if stream:
                    buffer = io.StringIO()
                    json.dump(value, buffer, **kw)
                    text = buffer.getvalue()
                else:
                    text = json.dumps(value, **kw)
            except RecursionError:
                chunks.append(b"ER")
                continue
            except ValueError as error:
                message = str(error)
                if message.startswith("Out of range float values"):
                    chunks.append(b"EN")
                elif message.startswith("Exceeds the limit"):
                    chunks.append(b"EL")
                else:
                    data = message.encode("utf-8", "backslashreplace")
                    chunks.append(b"EX" + struct.pack("<I", len(data)) + data)
                continue
            try:
                data = text.encode("utf-8")
            except UnicodeEncodeError:
                chunks.append(b"EU")
                continue
            chunks.append(b"O" + struct.pack("<I", len(data)) + data)
        sink.write(b"".join(chunks))
    sink.flush()

main()
"#;

/// SplitMix64: small, seeded, the same on every machine.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn below(&mut self, bound: u64) -> u64 {
        self.next() % bound
    }

    fn range(&mut self, low: u32, high: u32) -> u32 {
        low + self.below(u64::from(high - low + 1)) as u32
    }

    fn chance(&mut self, percent: u64) -> bool {
        self.below(100) < percent
    }
}

/// The floats where Python's repr changes form, and its neighbours' anchors.
const SPECIAL_FLOATS: &[f64] = &[
    0.0,
    -0.0,
    1.0,
    -1.0,
    0.1,
    0.5,
    0.2 + 0.1,
    1e16,
    1e15,
    9999999999999998.0,
    1e17,
    1e-4,
    1e-5,
    0.00011,
    0.000099,
    1e-7,
    1e22,
    1e23,
    5e-324,
    f64::MIN_POSITIVE,
    f64::MAX,
    f64::MIN,
    f64::EPSILON,
    9007199254740992.0,
    9007199254740993.0,
    9223372036854775808.0,
    18446744073709551616.0,
    1799999999.0,
    1799999999.5,
    1e100,
    1e-100,
    123456789012345680.0,
    4.35,
    2.675,
];

struct Generator {
    rng: Rng,
    surrogates: bool,
}

impl Generator {
    fn value(&mut self, depth: u32) -> Value {
        let roll = if depth >= 4 {
            self.rng.below(70)
        } else {
            self.rng.below(100)
        };
        match roll {
            0..=4 => Value::Null,
            5..=9 => Value::Bool(self.rng.chance(50)),
            10..=24 => Value::Int(self.int()),
            25..=44 => Value::Float(self.float()),
            45..=69 => Value::Str(self.text(12)),
            70..=84 => {
                let count = self.rng.below(6);
                Value::Array((0..count).map(|_| self.value(depth + 1)).collect())
            }
            _ => {
                let count = self.rng.below(7);
                let mut map = Map::new();
                for _ in 0..count {
                    let key = self.text(6);
                    let item = self.value(depth + 1);
                    map.insert(key, item);
                }
                Value::Object(map)
            }
        }
    }

    fn top(&mut self) -> Value {
        self.surrogates = self.rng.chance(4);
        match self.rng.below(10) {
            0..=3 => {
                let count = self.rng.below(8);
                let mut map = Map::new();
                for _ in 0..count {
                    let key = self.text(10);
                    let item = self.value(1);
                    map.insert(key, item);
                }
                Value::Object(map)
            }
            4..=5 => Value::Array((0..self.rng.below(8)).map(|_| self.value(1)).collect()),
            _ => self.value(4),
        }
    }

    fn digits(&mut self, count: usize) -> String {
        let mut text = String::with_capacity(count + 1);
        if self.rng.chance(40) {
            text.push('-');
        }
        text.push(char::from(b'1' + self.rng.below(9) as u8));
        for _ in 1..count {
            text.push(char::from(b'0' + self.rng.below(10) as u8));
        }
        text
    }

    fn int(&mut self) -> Int {
        match self.rng.below(1000) {
            0..=399 => Int::from(self.rng.below(2001) as i64 - 1000),
            400..=599 => Int::from(self.rng.next() as i64),
            600..=699 => {
                let edges = [
                    i64::MIN,
                    i64::MAX,
                    0,
                    -1,
                    1,
                    1 << 53,
                    (1 << 53) + 1,
                    -(1 << 53) - 1,
                ];
                Int::from(edges[self.rng.below(edges.len() as u64) as usize])
            }
            700..=799 => Int::from(u64::MAX - self.rng.below(1 << 62)),
            800..=997 => {
                let count = self.rng.range(19, 60) as usize;
                Int::parse(&self.digits(count)).unwrap()
            }
            // Python's digit limit, either side of it.
            _ => {
                let count = self.rng.range(4295, 4305) as usize;
                Int::parse(&self.digits(count)).unwrap()
            }
        }
    }

    fn float(&mut self) -> f64 {
        match self.rng.below(1000) {
            0..=2 => [f64::NAN, f64::INFINITY, f64::NEG_INFINITY][self.rng.below(3) as usize],
            3..=299 => loop {
                let x = f64::from_bits(self.rng.next());
                if x.is_finite() {
                    break x;
                }
            },
            300..=449 => SPECIAL_FLOATS[self.rng.below(SPECIAL_FLOATS.len() as u64) as usize],
            450..=599 => {
                let anchor = SPECIAL_FLOATS[self.rng.below(SPECIAL_FLOATS.len() as u64) as usize];
                let step = self.rng.below(4) as i64 - 2;
                let x = f64::from_bits(anchor.to_bits().wrapping_add_signed(step));
                if x.is_finite() { x } else { anchor }
            }
            600..=799 => {
                let width = self.rng.range(1, 17);
                let mantissa = self.rng.below(10u64.pow(width));
                let exponent = self.rng.range(0, 60) as i32 - 30;
                format!("{mantissa}e{exponent}").parse().unwrap()
            }
            800..=899 => ((self.rng.next() >> 4) as i64 - (1 << 59)) as f64,
            _ => {
                let unit = (self.rng.next() >> 11) as f64 / (1u64 << 53) as f64;
                unit * 10f64.powi(self.rng.range(0, 40) as i32 - 20)
            }
        }
    }

    fn code_point(&mut self) -> Vec<u32> {
        let roll = self.rng.below(100);
        let point = match roll {
            0..=39 => self.rng.range(0x20, 0x7E),
            40..=44 => [0x22, 0x5C, 0x2F, 0x3C, 0x27][self.rng.below(5) as usize],
            45..=52 => {
                if self.rng.chance(85) {
                    self.rng.range(0, 0x1F)
                } else {
                    0x7F
                }
            }
            53..=57 => self.rng.range(0x80, 0xFF),
            58..=72 => loop {
                let point = self.rng.range(0x100, 0xFFFF);
                if !(0xD800..=0xDFFF).contains(&point) {
                    break point;
                }
            },
            73..=79 => {
                let specials = [
                    0x2028, 0x2029, 0xFEFF, 0xFFFE, 0xFFFF, 0xFFFD, 0xAC00, 0x0085, 0x00A0,
                ];
                specials[self.rng.below(specials.len() as u64) as usize]
            }
            80..=91 => {
                if self.rng.chance(20) {
                    [0x10000, 0x1F600, 0x10FFFF, 0x1D11E][self.rng.below(4) as usize]
                } else {
                    self.rng.range(0x10000, 0x10FFFF)
                }
            }
            _ if self.surrogates => match self.rng.below(3) {
                0 => self.rng.range(0xD800, 0xDBFF),
                1 => self.rng.range(0xDC00, 0xDFFF),
                // Two halves side by side: two code points in Python, never joined.
                _ => {
                    return vec![
                        self.rng.range(0xD800, 0xDBFF),
                        self.rng.range(0xDC00, 0xDFFF),
                    ];
                }
            },
            _ => self.rng.range(0x61, 0x7A),
        };
        vec![point]
    }

    fn text(&mut self, longest: u64) -> Str {
        let length = if self.rng.chance(15) {
            0
        } else {
            self.rng.below(longest) + 1
        };
        let mut points = Vec::new();
        for _ in 0..length {
            points.extend(self.code_point());
        }
        Str::from_code_points(points).unwrap()
    }
}

fn lossless(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push('n'),
        Value::Bool(true) => out.push('t'),
        Value::Bool(false) => out.push('f'),
        Value::Int(int) => {
            let _ = write!(out, "i{int};");
        }
        Value::Float(x) => {
            let _ = write!(out, "d{:016x}", x.to_bits());
        }
        Value::Str(text) => lossless_text(text, out),
        Value::Array(items) => {
            let _ = write!(out, "[{};", items.len());
            for item in items {
                lossless(item, out);
            }
        }
        Value::Object(map) => {
            let _ = write!(out, "{{{};", map.len());
            for (key, item) in map {
                lossless_text(key, out);
                lossless(item, out);
            }
        }
    }
}

fn lossless_text(text: &Str, out: &mut String) {
    out.push('s');
    for byte in text.as_bytes() {
        let _ = write!(out, "{byte:02x}");
    }
    out.push(';');
}

enum Answer {
    Bytes(Vec<u8>),
    Refused(u8, String),
}

fn read_answer(source: &mut impl Read) -> Answer {
    let mut tag = [0u8; 1];
    source
        .read_exact(&mut tag)
        .expect("Python answered every configuration");
    let length = |source: &mut dyn Read| {
        let mut bytes = [0u8; 4];
        source.read_exact(&mut bytes).unwrap();
        let mut data = vec![0u8; u32::from_le_bytes(bytes) as usize];
        source.read_exact(&mut data).unwrap();
        data
    };
    match tag[0] {
        b'O' => Answer::Bytes(length(source)),
        b'E' => {
            source.read_exact(&mut tag).unwrap();
            let message = if tag[0] == b'X' {
                String::from_utf8_lossy(&length(source)).into_owned()
            } else {
                String::new()
            };
            Answer::Refused(tag[0], message)
        }
        other => panic!("Python answered with tag {other}"),
    }
}

fn code_of(error: Error) -> u8 {
    match error {
        Error::NotFinite => b'N',
        Error::IntTooLong { .. } => b'L',
        Error::TooDeep => b'R',
        Error::Surrogate => b'U',
    }
}

fn setting(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|value| !value.is_empty())
}

#[test]
fn the_writer_writes_what_python_writes() {
    let count: u64 =
        setting("CAR_JSON_COUNT").map_or(20_000, |text| text.parse().expect("CAR_JSON_COUNT"));
    let seed: u64 = setting("CAR_JSON_SEED").map_or(SEED, |text| {
        let text = text.trim_start_matches("0x");
        u64::from_str_radix(text, 16).expect("CAR_JSON_SEED, in hex")
    });
    let python = setting("CAR_JSON_PYTHON").unwrap_or_else(|| "python".to_owned());
    let configs = configs();

    let mut command = Command::new(&python);
    command
        .args(["-I", "-c", SCRIPT])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = command
        .spawn()
        .unwrap_or_else(|error| panic!("the reference, `{python} -I`, did not start: {error}"));
    let version = Command::new(&python)
        .args(["-I", "-c", "import sys; print(sys.version.split()[0])"])
        .output();
    let version = version
        .map(|out| String::from_utf8_lossy(&out.stdout).trim().to_owned())
        .unwrap_or_default();

    let header: Vec<&str> = configs.iter().map(|(_, python)| *python).collect();
    let mut stdin = BufWriter::with_capacity(1 << 20, child.stdin.take().unwrap());
    let feeder = std::thread::spawn(move || {
        writeln!(stdin, "[{}]", header.join(", ")).unwrap();
        let mut generator = Generator {
            rng: Rng(seed),
            surrogates: false,
        };
        let mut line = String::new();
        for _ in 0..count {
            line.clear();
            lossless(&generator.top(), &mut line);
            line.push('\n');
            stdin.write_all(line.as_bytes()).unwrap();
        }
        stdin.flush().unwrap();
    });

    let mut answers = BufReader::with_capacity(1 << 20, child.stdout.take().unwrap());
    let mut generator = Generator {
        rng: Rng(seed),
        surrogates: false,
    };
    let (mut equal, mut mismatches) = (0u64, Vec::new());
    let mut refusals = [0u64; 4];
    for index in 0..count {
        let value = generator.top();
        for (options, python) in &configs {
            let ours = to_string(&value, options);
            let theirs = read_answer(&mut answers);
            let same = match (&ours, &theirs) {
                (Ok(text), Answer::Bytes(bytes)) => text.as_bytes() == bytes.as_slice(),
                (Err(error), Answer::Refused(code, _)) => code_of(*error) == *code,
                _ => false,
            };
            if same {
                equal += 1;
                if let Err(error) = ours {
                    refusals[b"NLRU".iter().position(|c| *c == code_of(error)).unwrap()] += 1;
                }
            } else if mismatches.len() < 10 {
                let mut line = String::new();
                lossless(&value, &mut line);
                let theirs = match theirs {
                    Answer::Bytes(bytes) => format!("{:?}", String::from_utf8_lossy(&bytes)),
                    Answer::Refused(code, message) => format!("refused {} {message}", code as char),
                };
                mismatches.push(format!("value {index} with {python}:\n  form {line}\n  ours {ours:?}\n  python {theirs}"));
            } else {
                mismatches.push(String::new());
            }
        }
    }
    feeder.join().unwrap();
    let mut rest = Vec::new();
    answers.read_to_end(&mut rest).unwrap();
    let status = child.wait().unwrap();

    eprintln!(
        "json reference: Python {version}, seed {seed:#x}, {count} values x {} option sets = {} writes; \
         {equal} equal, {} differ; refused alike: {} NaN/infinity, {} int past the limit, {} too deep, {} surrogate",
        configs.len(),
        count * configs.len() as u64,
        mismatches.len(),
        refusals[0],
        refusals[1],
        refusals[2],
        refusals[3],
    );
    assert!(status.success(), "the reference ended with {status}");
    assert!(
        rest.is_empty(),
        "the reference wrote {} bytes past the last answer",
        rest.len()
    );
    let shown: Vec<&String> = mismatches.iter().filter(|text| !text.is_empty()).collect();
    assert!(
        mismatches.is_empty(),
        "{} writes differ; the first:\n{}",
        mismatches.len(),
        shown
            .iter()
            .map(|s| s.as_str())
            .collect::<Vec<_>>()
            .join("\n")
    );
}
