//! The writer: `json.dumps(value, allow_nan=False, ...)`, byte for byte.

use std::fmt;

use super::depth::{self, Budget};
use super::float::push_repr;
use super::value::{Int, Str, Value, decode};

/// Python's limit on an int's decimal digits (`sys.int_info.default_max_str_digits`): past it
/// `int.__repr__`, and so `json.dumps`, raises ValueError.
pub const MAX_INT_DIGITS: usize = 4300;

// How deep arrays and objects may nest before the writer refuses, as Python raises RecursionError, is the bundled
// 3.14.10's C encoder: a stack budget that lists and dicts spend differently, `depth.rs` (DUMPS_LIST_LEVELS,
// DUMPS_OBJECT_LEVELS). `json.dump` to a stream runs the pure-Python encoder, whose limit is the interpreter's frame
// count (994-995 levels on 3.14.10, both kinds): nothing the product writes nests past ten, so this one writer takes the
// C encoder's (AUDIT-v0628).

/// How a value is written: the keyword arguments of `json.dumps`, with `allow_nan=False`
/// always. [`Options::new`] is `json.dumps`'s defaults; each place's options are in the table
/// of the module's documentation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Options {
    ensure_ascii: bool,
    sort_keys: bool,
    indent: Option<String>,
    separators: Option<(String, String)>,
}

impl Default for Options {
    fn default() -> Options {
        Options::new()
    }
}

impl Options {
    /// `json.dumps(value, allow_nan=False)`: ASCII only, keys as inserted, one line, `", "`
    /// and `": "` between items.
    pub fn new() -> Options {
        Options {
            ensure_ascii: true,
            sort_keys: false,
            indent: None,
            separators: None,
        }
    }

    /// `json.dumps(value, ensure_ascii=False, allow_nan=False)`: the bridge's and the MCP
    /// server's line (controlcli.py:183-186).
    pub fn wire() -> Options {
        Options::new().ensure_ascii(false)
    }

    /// `ensure_ascii=`: true escapes everything outside `" "`..`"~"` as `\uXXXX` (an astral
    /// character as its surrogate pair); false writes text as itself.
    pub fn ensure_ascii(mut self, on: bool) -> Options {
        self.ensure_ascii = on;
        self
    }

    /// `sort_keys=`: keys in code point order rather than insertion order.
    pub fn sort_keys(mut self, on: bool) -> Options {
        self.sort_keys = on;
        self
    }

    /// `indent=spaces`: each item on its own line (0 too: new lines, no spaces), and `","`
    /// rather than `", "` between items unless [`Options::separators`] says otherwise.
    pub fn indent(self, spaces: usize) -> Options {
        self.indent_text(&" ".repeat(spaces))
    }

    /// `indent="..."`: the same with any text as one level.
    pub fn indent_text(mut self, level: &str) -> Options {
        self.indent = Some(level.to_owned());
        self
    }

    /// `separators=(item, key)`.
    pub fn separators(mut self, item: &str, key: &str) -> Options {
        self.separators = Some((item.to_owned(), key.to_owned()));
        self
    }

    fn item_separator(&self) -> &str {
        match (&self.separators, &self.indent) {
            (Some((item, _)), _) => item,
            (None, Some(_)) => ",",
            (None, None) => ", ",
        }
    }

    fn key_separator(&self) -> &str {
        match &self.separators {
            Some((_, key)) => key,
            None => ": ",
        }
    }
}

/// Why a value could not be written.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    /// A NaN or an infinity: Python's ValueError "Out of range float values are not JSON
    /// compliant".
    NotFinite,
    /// An int past [`MAX_INT_DIGITS`]: Python's ValueError "Exceeds the limit (4300 digits)".
    IntTooLong { digits: usize },
    /// Nested past [`DUMPS_LIST_LEVELS`](super::DUMPS_LIST_LEVELS) lists or [`DUMPS_OBJECT_LEVELS`](super::DUMPS_OBJECT_LEVELS)
    /// objects, or a mix of them that spends as much of the stack: Python's RecursionError.
    TooDeep,
    /// A surrogate code point to be written as itself (`ensure_ascii=False`). Python's
    /// `json.dumps` writes it into its `str`; the product's every way out of that - stdout
    /// reconfigured to UTF-8 (strict), `write_text(encoding="utf-8")`, `.encode("utf-8")` -
    /// then raises UnicodeEncodeError. Only reported when nothing else was refused first, as
    /// Python's encoder ends before the stream is reached.
    Surrogate,
}

impl Error {
    /// Whether `json.dumps` itself refuses it (`controlcli.UNWRITABLE`: TypeError, ValueError,
    /// RecursionError), so the bridge's `encode` falls back to its next candidate. A
    /// [`Error::Surrogate`] is not: there `json.dumps` succeeded and the write after it raises.
    pub fn is_unwritable(&self) -> bool {
        !matches!(self, Error::Surrogate)
    }
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::NotFinite => {
                formatter.write_str("Out of range float values are not JSON compliant")
            }
            Error::IntTooLong { digits } => write!(
                formatter,
                "Exceeds the limit ({MAX_INT_DIGITS} digits) for integer string conversion: value has {digits} digits"
            ),
            Error::TooDeep => {
                formatter.write_str("maximum recursion depth exceeded while encoding a JSON object")
            }
            Error::Surrogate => {
                formatter.write_str("'utf-8' codec can't encode character: surrogates not allowed")
            }
        }
    }
}

impl std::error::Error for Error {}

/// `json.dumps(value, allow_nan=False, **options)`, as UTF-8.
pub fn to_string(value: &Value, options: &Options) -> Result<String, Error> {
    let mut writer = Writer {
        out: String::new(),
        options,
        budget: depth::dumps(),
        surrogate: false,
    };
    writer.run(value)?;
    if writer.surrogate {
        return Err(Error::Surrogate);
    }
    Ok(writer.out)
}

struct Writer<'a> {
    out: String,
    options: &'a Options,
    budget: Budget,
    surrogate: bool,
}

/// A container being written: what is left of it.
enum Frame<'v> {
    Array {
        items: &'v [Value],
        next: usize,
    },
    Object {
        entries: Vec<(&'v Str, &'v Value)>,
        next: usize,
    },
}

impl<'v> Writer<'_> {
    /// Writes `root` with an explicit stack of the containers it is inside, so a document nested thousands deep costs
    /// no Rust stack (Python's own limit is the nesting `depth.rs` records, far past what a thread's stack holds as
    /// recursion).
    fn run(&mut self, root: &'v Value) -> Result<(), Error> {
        let mut stack: Vec<Frame<'v>> = Vec::new();
        let mut value = root;
        loop {
            // One value: a scalar is written; a container that holds something opens, and its first item comes next.
            let mut descended = true;
            while descended {
                descended = false;
                match value {
                    Value::Null => self.out.push_str("null"),
                    Value::Bool(true) => self.out.push_str("true"),
                    Value::Bool(false) => self.out.push_str("false"),
                    Value::Int(int) => self.int(int)?,
                    Value::Float(x) => {
                        if !x.is_finite() {
                            return Err(Error::NotFinite);
                        }
                        push_repr(&mut self.out, *x);
                    }
                    Value::Str(text) => self.string(text),
                    Value::Array(items) => {
                        // The C encoder checks the depth before it looks inside: an empty list counts too.
                        if !self.budget.enter_list() {
                            return Err(Error::TooDeep);
                        }
                        if items.is_empty() {
                            self.budget.leave_list();
                            self.out.push_str("[]");
                        } else {
                            self.out.push('[');
                            stack.push(Frame::Array { items, next: 1 });
                            self.break_line(stack.len());
                            value = &items[0];
                            descended = true;
                        }
                    }
                    Value::Object(map) => {
                        if !self.budget.enter_object() {
                            return Err(Error::TooDeep);
                        }
                        if map.is_empty() {
                            self.budget.leave_object();
                            self.out.push_str("{}");
                        } else {
                            let mut entries: Vec<(&Str, &Value)> = map.iter().collect();
                            if self.options.sort_keys {
                                entries.sort_by(|a, b| a.0.cmp(b.0));
                            }
                            self.out.push('{');
                            self.break_line(stack.len() + 1);
                            let (key, first) = entries[0];
                            self.key(key);
                            value = first;
                            stack.push(Frame::Object { entries, next: 1 });
                            descended = true;
                        }
                    }
                }
            }
            // A value is written: the next item of the container it is in, or the end of that container, upward.
            loop {
                let Some(top) = stack.last_mut() else {
                    return Ok(());
                };
                match top {
                    Frame::Array { items, next } => {
                        if *next < items.len() {
                            value = &items[*next];
                            *next += 1;
                            self.out.push_str(self.options.item_separator());
                            self.break_line(stack.len());
                            break;
                        }
                        stack.pop();
                        self.budget.leave_list();
                        self.break_line(stack.len());
                        self.out.push(']');
                    }
                    Frame::Object { entries, next } => {
                        if *next < entries.len() {
                            let (key, item) = entries[*next];
                            *next += 1;
                            value = item;
                            self.out.push_str(self.options.item_separator());
                            self.break_line(stack.len());
                            self.key(key);
                            break;
                        }
                        stack.pop();
                        self.budget.leave_object();
                        self.break_line(stack.len());
                        self.out.push('}');
                    }
                }
            }
        }
    }

    fn int(&mut self, int: &Int) -> Result<(), Error> {
        let digits = int.digits();
        if digits > MAX_INT_DIGITS {
            return Err(Error::IntTooLong { digits });
        }
        use std::fmt::Write as _;
        let _ = write!(self.out, "{int}");
        Ok(())
    }

    /// Between two items, and after the opening bracket when indenting: the line break and
    /// the indent of the level the items are at (`depth` containers deep).
    fn break_line(&mut self, depth: usize) {
        if let Some(level) = &self.options.indent {
            self.out.push('\n');
            for _ in 0..depth {
                self.out.push_str(level);
            }
        }
    }

    /// An object's key and the separator after it.
    fn key(&mut self, key: &Str) {
        self.string(key);
        self.out.push_str(self.options.key_separator());
    }

    /// A string as `encode_basestring` (or `encode_basestring_ascii`) writes it.
    fn string(&mut self, text: &Str) {
        self.out.push('"');
        let mut bytes = text.as_bytes();
        while !bytes.is_empty() {
            let (point, length) = decode(bytes).expect("a Str holds only well-formed bytes");
            bytes = &bytes[length..];
            match point {
                0x22 => self.out.push_str("\\\""),
                0x5C => self.out.push_str("\\\\"),
                0x0A => self.out.push_str("\\n"),
                0x0D => self.out.push_str("\\r"),
                0x09 => self.out.push_str("\\t"),
                0x08 => self.out.push_str("\\b"),
                0x0C => self.out.push_str("\\f"),
                0x00..=0x1F => self.escape(point),
                0x20..=0x7E => self.out.push(point as u8 as char),
                _ if self.options.ensure_ascii => {
                    if point >= 0x10000 {
                        let offset = point - 0x10000;
                        self.escape(0xD800 | (offset >> 10));
                        self.escape(0xDC00 | (offset & 0x3FF));
                    } else {
                        self.escape(point);
                    }
                }
                _ => match char::from_u32(point) {
                    Some(c) => self.out.push(c),
                    None => {
                        // A surrogate: Python's str holds it, and the write after it fails.
                        self.surrogate = true;
                        self.out.push(char::REPLACEMENT_CHARACTER);
                    }
                },
            }
        }
        self.out.push('"');
    }

    /// `\uXXXX`, lowercase, as Python writes it.
    fn escape(&mut self, unit: u32) {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        self.out.push_str("\\u");
        for shift in [12, 8, 4, 0] {
            self.out.push(HEX[((unit >> shift) & 0xF) as usize] as char);
        }
    }
}
