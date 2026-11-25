//! The four command lines `codex-auto-resume.exe` takes, parsed as the reference's argparse parses them (3.13/3.14,
//! which agree on every text here): the tables are the tag's own parsers (`parsers_gen.rs`, written by
//! `tests/rustdiff/gen_cli.py`), and this is argparse's algorithm for the actions they use - `-h`, store_true, store
//! (with a type and choices), a positional of one or `?`, and a required subparser - with long options taken by any
//! unambiguous prefix, `--name=value`, `-nVALUE`, `--`, negative numbers as values, and every error argparse would
//! write: the parser's usage and `prog: error: message` on stderr, and the exit code 2.

use std::collections::BTreeMap;

use car_machine::pytext;

/// What an action does.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Help,
    Flag,
    Store,
    Commands,
}

/// `nargs`: None, `?`, 0 (a flag or help) and argparse's PARSER (a subparser).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Nargs {
    One,
    Optional,
    Zero,
    Parser,
}

/// `type=`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ty {
    Str,
    Int,
    Float,
}

/// One `add_argument` (or `add_subparsers`).
#[derive(Debug)]
pub struct Action {
    pub kind: Kind,
    pub strings: &'static [&'static str],
    pub dest: &'static str,
    pub nargs: Nargs,
    pub required: bool,
    pub metavar: Option<&'static str>,
    /// The default as `str(default)`, None for None and for a flag's False.
    pub default: Option<&'static str>,
    pub ty: Ty,
    /// `[str(choice) ...]`.
    pub choices: Option<&'static [&'static str]>,
    /// A subparser action's names and the index of each one's parser.
    pub commands: &'static [(&'static str, usize)],
}

/// One parser: its prog, its usage and help as argparse formats them, and its actions in order.
#[derive(Debug)]
pub struct Parser {
    pub prog: &'static str,
    pub usage: &'static str,
    pub help: &'static str,
    pub actions: &'static [Action],
}

/// A value an argument gave.
#[derive(Clone, Debug, PartialEq)]
pub enum Got {
    None,
    Bool(bool),
    Text(String),
    /// An int, as Python's `int()` read it (its decimal text, any size).
    Int(String),
    Float(f64),
}

impl Got {
    pub fn text(&self) -> Option<&str> {
        match self {
            Got::Text(text) => Some(text),
            _ => None,
        }
    }

    pub fn on(&self) -> bool {
        matches!(self, Got::Bool(true))
    }

    pub fn int(&self) -> Option<i128> {
        match self {
            Got::Int(text) => text.parse::<i128>().ok().or_else(|| {
                // Beyond i128: saturate, which every reader here treats as "very many".
                Some(if text.starts_with('-') {
                    i128::MIN
                } else {
                    i128::MAX
                })
            }),
            _ => None,
        }
    }
}

/// What parsing gave: every dest's value, and the commands chosen, outermost first.
#[derive(Clone, Debug, Default)]
pub struct Namespace {
    pub values: BTreeMap<&'static str, Got>,
    pub commands: Vec<&'static str>,
}

impl Namespace {
    pub fn get(&self, dest: &str) -> &Got {
        self.values.get(dest).unwrap_or(&Got::None)
    }
}

/// How parsing ended without a namespace.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Exit {
    /// `-h`: the help on stdout, exit 0.
    Help(String),
    /// `parser.error(message)`: usage and `prog: error: message` on stderr, exit 2.
    Error(String),
}

impl Exit {
    pub fn code(&self) -> i32 {
        match self {
            Exit::Help(_) => 0,
            Exit::Error(_) => 2,
        }
    }
}

/// `repr(str)`: Python's quoting of a text.
pub fn repr(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(text.len() + 2);
    out.push(quote);
    for c in text.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if !printable(c) => {
                let code = c as u32;
                if code < 0x100 {
                    out.push_str(&format!("\\x{code:02x}"));
                } else if code < 0x10000 {
                    out.push_str(&format!("\\u{code:04x}"));
                } else {
                    out.push_str(&format!("\\U{code:08x}"));
                }
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `str.isprintable()` for one character, as far as a command line can hold one: not a control, a format character,
/// a separator other than the space, a surrogate or a private-use character.
fn printable(c: char) -> bool {
    if c == ' ' {
        return true;
    }
    let code = c as u32;
    !(c.is_control()
        || (c.is_whitespace())
        || (0xE000..=0xF8FF).contains(&code)
        || (0xF0000..=0x10FFFF).contains(&code)
        || matches!(code, 0xAD | 0x600..=0x605 | 0x61C | 0x6DD | 0x70F | 0x180E | 0x200B..=0x200F
            | 0x202A..=0x202E | 0x2060..=0x2064 | 0x2066..=0x206F | 0xFEFF | 0xFFF9..=0xFFFB))
}

/// Which kind each argument is: an option (`O`), an argument (`A`), or the first `--` (`-`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Shape {
    O,
    A,
    Dash,
}

/// `(action, option_string, sep, explicit_arg)`; the action None for an option the parser does not have.
#[derive(Clone, Debug)]
struct Tuple {
    action: Option<usize>,
    option: String,
    sep: Option<String>,
    explicit: Option<String>,
}

fn option_strings(parser: &Parser) -> Vec<(&'static str, usize)> {
    let mut found = Vec::new();
    for (index, action) in parser.actions.iter().enumerate() {
        for each in action.strings {
            found.push((*each, index));
        }
    }
    found
}

fn partition(text: &str) -> (String, Option<String>, Option<String>) {
    match text.split_once('=') {
        Some((head, tail)) => (head.to_owned(), Some("=".to_owned()), Some(tail.to_owned())),
        None => (text.to_owned(), None, None),
    }
}

/// `_negative_number_matcher`: `^-\d+$|^-\d*\.\d+$` (`\d` any decimal digit).
fn negative_number(text: &str) -> bool {
    let Some(rest) = text.strip_prefix('-') else {
        return false;
    };
    let digits = |part: &str| part.chars().all(pytext::is_digit);
    if !rest.is_empty() && digits(rest) {
        return true;
    }
    match rest.split_once('.') {
        Some((whole, fraction)) => digits(whole) && !fraction.is_empty() && digits(fraction),
        None => false,
    }
}

fn get_option_tuples(parser: &Parser, text: &str) -> Vec<Tuple> {
    let strings = option_strings(parser);
    let mut result = Vec::new();
    let chars: Vec<char> = text.chars().collect();
    if chars.len() >= 2 && chars[0] == '-' && chars[1] == '-' {
        let (prefix, sep, explicit) = partition(text);
        for (each, index) in &strings {
            if each.starts_with(prefix.as_str()) {
                result.push(Tuple {
                    action: Some(*index),
                    option: (*each).to_owned(),
                    sep: sep.clone(),
                    explicit: explicit.clone(),
                });
            }
        }
    } else if chars.len() >= 2 && chars[0] == '-' {
        let (prefix, sep, explicit) = partition(text);
        let short: String = chars[..2].iter().collect();
        let short_explicit: String = chars[2..].iter().collect();
        for (each, index) in &strings {
            if *each == short {
                result.push(Tuple {
                    action: Some(*index),
                    option: (*each).to_owned(),
                    sep: Some(String::new()),
                    explicit: Some(short_explicit.clone()),
                });
            } else if each.starts_with(prefix.as_str()) {
                result.push(Tuple {
                    action: Some(*index),
                    option: (*each).to_owned(),
                    sep: sep.clone(),
                    explicit: explicit.clone(),
                });
            }
        }
    }
    result
}

/// `_parse_optional(arg)`: None for an argument, else the option tuples.
fn parse_optional(parser: &Parser, text: &str) -> Option<Vec<Tuple>> {
    if !text.starts_with('-') {
        return None;
    }
    let strings = option_strings(parser);
    if let Some((_, index)) = strings.iter().find(|(each, _)| *each == text) {
        return Some(vec![Tuple {
            action: Some(*index),
            option: text.to_owned(),
            sep: None,
            explicit: None,
        }]);
    }
    if text.chars().count() == 1 {
        return None;
    }
    let (head, sep, explicit) = partition(text);
    if sep.is_some()
        && let Some((_, index)) = strings.iter().find(|(each, _)| *each == head)
    {
        return Some(vec![Tuple {
            action: Some(*index),
            option: head,
            sep,
            explicit,
        }]);
    }
    let tuples = get_option_tuples(parser, text);
    if !tuples.is_empty() {
        return Some(tuples);
    }
    if negative_number(text) {
        return None;
    }
    if text.contains(' ') {
        return None;
    }
    Some(vec![Tuple {
        action: None,
        option: text.to_owned(),
        sep: None,
        explicit: None,
    }])
}

/// `_get_action_name(action)`.
fn action_name(action: &Action) -> String {
    if !action.strings.is_empty() {
        action.strings.join("/")
    } else if let Some(metavar) = action.metavar {
        metavar.to_owned()
    } else {
        action.dest.to_owned()
    }
}

fn argument_error(action: Option<&Action>, message: String) -> String {
    match action {
        Some(action) => format!("argument {}: {message}", action_name(action)),
        None => message,
    }
}

/// `_get_value` and `_check_value` for one string.
fn value_of(action: &Action, text: &str) -> Result<Got, String> {
    let got = match action.ty {
        Ty::Str => Got::Text(text.to_owned()),
        Ty::Int => match pytext::parse_int(text, 10) {
            Some(parsed) => Got::Int(int_text(text, parsed)),
            None => {
                return Err(argument_error(
                    Some(action),
                    format!("invalid int value: {}", repr(text)),
                ));
            }
        },
        Ty::Float => match pytext::float_from_text(text) {
            Ok(x) => Got::Float(x),
            Err(_) => {
                return Err(argument_error(
                    Some(action),
                    format!("invalid float value: {}", repr(text)),
                ));
            }
        },
    };
    if let Some(choices) = action.choices {
        let shown = match &got {
            Got::Text(text) => text.clone(),
            Got::Int(text) => text.clone(),
            Got::Float(x) => car_machine::pytext::float_repr(*x),
            _ => String::new(),
        };
        if !choices.contains(&shown.as_str()) {
            return Err(argument_error(
                Some(action),
                format!(
                    "invalid choice: {} (choose from {})",
                    repr(&shown),
                    choices
                        .iter()
                        .map(|each| repr(each))
                        .collect::<Vec<_>>()
                        .join(", ")
                ),
            ));
        }
    }
    Ok(got)
}

/// `str(int(text))`: the sign and the digits, any size.
fn int_text(text: &str, parsed: pytext::Parsed) -> String {
    let sign = if parsed.negative { "-" } else { "" };
    match parsed.magnitude {
        Some(0) => "0".to_owned(),
        Some(magnitude) => format!("{sign}{magnitude}"),
        None => {
            let digits: String = pytext::strip(text)
                .chars()
                .filter_map(pytext::decimal_value)
                .map(|digit| char::from_digit(digit, 10).unwrap_or('0'))
                .collect();
            format!("{sign}{}", digits.trim_start_matches('0'))
        }
    }
}

/// The length of what `nargs` takes at the start of `pattern`, as `re.match(_get_nargs_pattern(action), pattern)`.
fn match_nargs(action: &Action, pattern: &[Shape]) -> Option<usize> {
    let optional = !action.strings.is_empty();
    let dashes = |from: usize| {
        pattern[from..]
            .iter()
            .take_while(|each| **each == Shape::Dash)
            .count()
    };
    match (action.nargs, optional) {
        (Nargs::Zero, _) => Some(0),
        (Nargs::One, true) => (pattern.first() == Some(&Shape::A)).then_some(1),
        (Nargs::Optional, true) => Some(usize::from(pattern.first() == Some(&Shape::A))),
        (Nargs::One, false) => {
            let lead = dashes(0);
            (pattern.get(lead) == Some(&Shape::A)).then(|| lead + 1 + dashes(lead + 1))
        }
        (Nargs::Optional, false) => {
            let lead = dashes(0);
            if pattern.get(lead) == Some(&Shape::A) {
                Some(lead + 1 + dashes(lead + 1))
            } else {
                Some(lead)
            }
        }
        (Nargs::Parser, _) => {
            let lead = if optional { 0 } else { dashes(0) };
            (pattern.get(lead) == Some(&Shape::A)).then_some(pattern.len())
        }
    }
}

struct Run<'a> {
    parsers: &'static [Parser],
    parser: &'static Parser,
    args: &'a [String],
    pattern: Vec<Shape>,
    namespace: Namespace,
    seen: Vec<usize>,
    extras: Vec<String>,
    positionals: Vec<usize>,
}

/// Parse `args` with parser `index` of `parsers` as `parse_args` does.
pub fn parse_args(
    parsers: &'static [Parser],
    index: usize,
    args: &[String],
) -> Result<Namespace, Exit> {
    let (namespace, extras) = parse_known(parsers, index, args)?;
    if !extras.is_empty() {
        return Err(error(
            &parsers[index],
            &format!("unrecognized arguments: {}", extras.join(" ")),
        ));
    }
    Ok(namespace)
}

fn error(parser: &Parser, message: &str) -> Exit {
    Exit::Error(format!(
        "{}{}: error: {message}\n",
        parser.usage, parser.prog
    ))
}

fn parse_known(
    parsers: &'static [Parser],
    index: usize,
    args: &[String],
) -> Result<(Namespace, Vec<String>), Exit> {
    let parser = &parsers[index];
    let mut namespace = Namespace::default();
    for action in parser.actions {
        if action.kind == Kind::Help {
            continue;
        }
        let value = match (action.kind, action.default) {
            (Kind::Flag, _) => Got::Bool(false),
            (_, None) => Got::None,
            (_, Some(text)) => match action.ty {
                Ty::Int => Got::Int(text.to_owned()),
                Ty::Float => Got::Float(text.parse().unwrap_or(0.0)),
                Ty::Str => Got::Text(text.to_owned()),
            },
        };
        namespace.values.insert(action.dest, value);
    }
    let mut run = Run {
        parsers,
        parser,
        args,
        pattern: Vec::new(),
        namespace,
        seen: Vec::new(),
        extras: Vec::new(),
        positionals: parser
            .actions
            .iter()
            .enumerate()
            .filter(|(_, action)| action.strings.is_empty())
            .map(|(index, _)| index)
            .collect(),
    };
    match run.go() {
        Ok(()) => Ok((run.namespace, run.extras)),
        Err(Stop::Message(message)) => Err(error(parser, &message)),
        Err(Stop::Exit(exit)) => Err(exit),
    }
}

enum Stop {
    Message(String),
    Exit(Exit),
}

impl From<Exit> for Stop {
    fn from(exit: Exit) -> Stop {
        Stop::Exit(exit)
    }
}

impl Run<'_> {
    fn go(&mut self) -> Result<(), Stop> {
        let mut options: BTreeMap<usize, Vec<Tuple>> = BTreeMap::new();
        let mut dashed = false;
        for (index, arg) in self.args.iter().enumerate() {
            if dashed {
                self.pattern.push(Shape::A);
            } else if arg == "--" {
                self.pattern.push(Shape::Dash);
                dashed = true;
            } else {
                match parse_optional(self.parser, arg) {
                    None => self.pattern.push(Shape::A),
                    Some(tuples) => {
                        options.insert(index, tuples);
                        self.pattern.push(Shape::O);
                    }
                }
            }
        }
        let max = options.keys().next_back().copied();
        let mut start = 0usize;
        if let Some(max) = max {
            while start <= max {
                let mut next = start;
                while next <= max && !options.contains_key(&next) {
                    next += 1;
                }
                if start != next {
                    let end = self.consume_positionals(start)?;
                    if end > start {
                        start = end;
                        continue;
                    }
                    start = end;
                }
                if !options.contains_key(&start) {
                    self.extras.extend(self.args[start..next].iter().cloned());
                    start = next;
                }
                start = self.consume_optional(start, &options[&start])?;
            }
        }
        let stop = self.consume_positionals(start)?;
        self.extras.extend(self.args[stop..].iter().cloned());
        let required: Vec<String> = self
            .parser
            .actions
            .iter()
            .enumerate()
            .filter(|(index, action)| action.required && !self.seen.contains(index))
            .map(|(_, action)| action_name(action))
            .collect();
        if !required.is_empty() {
            return Err(Stop::Message(format!(
                "the following arguments are required: {}",
                required.join(", ")
            )));
        }
        Ok(())
    }

    fn consume_optional(&mut self, start: usize, tuples: &[Tuple]) -> Result<usize, Stop> {
        if tuples.len() > 1 {
            let matches: Vec<&str> = tuples.iter().map(|each| each.option.as_str()).collect();
            return Err(Stop::Message(format!(
                "ambiguous option: {} could match {}",
                self.args[start],
                matches.join(", ")
            )));
        }
        let Tuple {
            action,
            mut option,
            mut sep,
            mut explicit,
        } = tuples[0].clone();
        let mut action = action;
        let mut taken: Vec<(usize, Vec<String>)> = Vec::new();
        let stop;
        loop {
            let Some(index) = action else {
                self.extras.push(self.args[start].clone());
                return Ok(start + 1);
            };
            let current = &self.parser.actions[index];
            if let Some(given) = explicit.clone() {
                let count = match_nargs(current, &[Shape::A]);
                let second = option.chars().nth(1);
                if count == Some(0) && second != Some('-') && !given.is_empty() {
                    if sep.as_deref().is_some_and(|each| !each.is_empty()) || given.starts_with('-')
                    {
                        return Err(Stop::Message(argument_error(
                            Some(current),
                            format!("ignored explicit argument {}", repr(&given)),
                        )));
                    }
                    taken.push((index, Vec::new()));
                    let first: String = given.chars().take(1).collect();
                    option = format!("-{first}");
                    let rest: String = given.chars().skip(1).collect();
                    match option_strings(self.parser)
                        .iter()
                        .find(|(each, _)| *each == option)
                    {
                        Some((_, found)) => {
                            action = Some(*found);
                            if rest.is_empty() {
                                sep = None;
                                explicit = None;
                            } else if let Some(after) = rest.strip_prefix('=') {
                                sep = Some("=".to_owned());
                                explicit = Some(after.to_owned());
                            } else {
                                sep = Some(String::new());
                                explicit = Some(rest);
                            }
                        }
                        None => {
                            self.extras.push(format!("-{given}"));
                            stop = start + 1;
                            break;
                        }
                    }
                } else if count == Some(1) {
                    stop = start + 1;
                    taken.push((index, vec![given]));
                    break;
                } else {
                    return Err(Stop::Message(argument_error(
                        Some(current),
                        format!("ignored explicit argument {}", repr(&given)),
                    )));
                }
            } else {
                let from = start + 1;
                let count = match match_nargs(current, &self.pattern[from..]) {
                    Some(count) => count,
                    None => {
                        return Err(Stop::Message(argument_error(
                            Some(current),
                            match current.nargs {
                                Nargs::Optional => "expected at most one argument".to_owned(),
                                _ => "expected one argument".to_owned(),
                            },
                        )));
                    }
                };
                stop = from + count;
                taken.push((index, self.args[from..stop].to_vec()));
                break;
            }
        }
        for (index, strings) in taken {
            self.take(index, strings)?;
        }
        Ok(stop)
    }

    fn consume_positionals(&mut self, start: usize) -> Result<usize, Stop> {
        let mut start = start;
        let selected = self.pattern[start..].to_vec();
        // `_match_arguments_partial`: as many of the positionals as can match, in order.
        let mut counts: Vec<usize> = Vec::new();
        for take in (1..=self.positionals.len()).rev() {
            let mut at = 0;
            let mut found = Vec::new();
            let mut whole = true;
            for index in &self.positionals[..take] {
                match match_nargs(&self.parser.actions[*index], &selected[at..]) {
                    Some(count) => {
                        found.push(count);
                        at += count;
                    }
                    None => {
                        whole = false;
                        break;
                    }
                }
            }
            if whole {
                if at < selected.len() && selected[at] == Shape::O {
                    while found.last() == Some(&0) {
                        found.pop();
                    }
                }
                counts = found;
                break;
            }
        }
        let used = counts.len();
        for (index, count) in self.positionals[..used]
            .to_vec()
            .iter()
            .copied()
            .zip(counts)
        {
            let mut strings: Vec<String> = self.args[start..start + count].to_vec();
            let action = &self.parser.actions[index];
            if action.nargs == Nargs::Parser {
                if self.pattern.get(start) == Some(&Shape::Dash) {
                    strings.remove(0);
                }
            } else if self.pattern[start..start + count].contains(&Shape::Dash)
                && let Some(at) = strings.iter().position(|each| each == "--")
            {
                strings.remove(at);
            }
            start += count;
            self.take(index, strings)?;
        }
        self.positionals.drain(..used);
        Ok(start)
    }

    fn take(&mut self, index: usize, strings: Vec<String>) -> Result<(), Stop> {
        self.seen.push(index);
        let action = &self.parser.actions[index];
        match action.kind {
            Kind::Help => Err(Stop::Exit(Exit::Help(self.parser.help.to_owned()))),
            Kind::Flag => {
                self.namespace.values.insert(action.dest, Got::Bool(true));
                Ok(())
            }
            Kind::Store => {
                let value = match strings.first() {
                    Some(text) => value_of(action, text).map_err(Stop::Message)?,
                    // `?` with nothing: the default, converted when it is text.
                    None => match action.default {
                        Some(text) => value_of(action, text).map_err(Stop::Message)?,
                        None => Got::None,
                    },
                };
                self.namespace.values.insert(action.dest, value);
                Ok(())
            }
            Kind::Commands => {
                let name = strings.first().cloned().unwrap_or_default();
                let Some((word, parser)) = action.commands.iter().find(|(each, _)| *each == name)
                else {
                    return Err(Stop::Message(argument_error(
                        Some(action),
                        format!(
                            "invalid choice: {} (choose from {})",
                            repr(&name),
                            action
                                .commands
                                .iter()
                                .map(|(each, _)| repr(each))
                                .collect::<Vec<_>>()
                                .join(", ")
                        ),
                    )));
                };
                self.namespace
                    .values
                    .insert(action.dest, Got::Text((*word).to_owned()));
                self.namespace.commands.push(word);
                let (inner, extras) = parse_known(self.parsers, *parser, &strings[1..])?;
                for (dest, value) in inner.values {
                    self.namespace.values.insert(dest, value);
                }
                self.namespace.commands.extend(inner.commands);
                self.extras.extend(extras);
                Ok(())
            }
        }
    }
}
