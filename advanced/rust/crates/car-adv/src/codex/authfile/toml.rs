//! `tomllib.loads` as the product's bundled Python 3.14 runs it (Lib/tomllib/_parser.py and _re.py), for the one
//! question `authfile.store_mode` asks of Codex's config.toml: does it parse, and what does its top level say under one
//! key. Every rule of the parser is kept - the statements, keys and their flags (EXPLICIT_NEST, FROZEN, the pending
//! ones), the nests and arrays of tables, strings and their escapes, numbers, dates (a date that is not one fails),
//! times, booleans, inline arrays and tables - so a document is accepted or refused exactly as the reference does.
//!
//! What a value is matters only as far as the parser itself looks at it (a table, a list, a string, anything else);
//! no number or date is computed. Python's recursion limit is kept too: every function the reference enters is a frame
//! here ([`Parser::call`]), and a frame past the limit is the RecursionError the reference raises (and `store_mode`
//! does not catch). How deep the caller already is, is the caller's to say (`base`).

use std::collections::{HashMap, HashSet};

/// `sys.getrecursionlimit()`'s default, and `MAX_KEY_PARTS`.
pub const LIMIT: usize = 1000;

/// Why a document was refused: `TOMLDecodeError`, or Python's RecursionError (or an IndexError the reference would
/// raise, which no well-formed run reaches).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Decode,
    Recursion,
    Index,
}

type Parsed<T> = Result<T, Error>;
type Key = Vec<String>;

/// A value as the parser keeps it.
#[derive(Clone, Debug)]
enum Node {
    Table(HashMap<String, usize>),
    List(Vec<usize>),
    Str(String),
    Other,
}

/// What the top level holds under a key: a string, or anything else.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Found {
    Str(String),
    Other,
}

const FROZEN: u8 = 1;
const EXPLICIT_NEST: u8 = 2;

#[derive(Default)]
struct FlagNode {
    flags: u8,
    recursive: u8,
    nested: HashMap<String, FlagNode>,
}

#[derive(Default)]
struct Flags {
    root: HashMap<String, FlagNode>,
    pending: HashSet<(Key, u8)>,
}

impl Flags {
    fn add_pending(&mut self, key: &Key, flag: u8) {
        self.pending.insert((key.clone(), flag));
    }

    fn finalize_pending(&mut self) {
        let pending: Vec<(Key, u8)> = self.pending.drain().collect();
        for (key, flag) in pending {
            self.set(&key, flag, false);
        }
    }

    fn unset_all(&mut self, key: &Key) {
        let mut cont = &mut self.root;
        for part in &key[..key.len() - 1] {
            match cont.get_mut(part) {
                Some(node) => cont = &mut node.nested,
                None => return,
            }
        }
        cont.remove(&key[key.len() - 1]);
    }

    fn set(&mut self, key: &Key, flag: u8, recursive: bool) {
        let mut cont = &mut self.root;
        for part in &key[..key.len() - 1] {
            cont = &mut cont.entry(part.clone()).or_default().nested;
        }
        let node = cont.entry(key[key.len() - 1].clone()).or_default();
        if recursive {
            node.recursive |= flag;
        } else {
            node.flags |= flag;
        }
    }

    fn is(&self, key: &Key, flag: u8) -> bool {
        if key.is_empty() {
            return false;
        }
        let mut cont = &self.root;
        for part in &key[..key.len() - 1] {
            let Some(inner) = cont.get(part) else {
                return false;
            };
            if inner.recursive & flag != 0 {
                return true;
            }
            cont = &inner.nested;
        }
        match cont.get(&key[key.len() - 1]) {
            Some(node) => (node.flags | node.recursive) & flag != 0,
            None => false,
        }
    }
}

fn ascii_ctrl(c: char) -> bool {
    (c as u32) < 32 || c as u32 == 127
}

fn illegal_basic(c: char) -> bool {
    ascii_ctrl(c) && c != '\t'
}

fn illegal_multiline(c: char) -> bool {
    ascii_ctrl(c) && c != '\t' && c != '\n'
}

fn bare(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '-' || c == '_'
}

fn ws(c: char) -> bool {
    c == ' ' || c == '\t'
}

fn ws_nl(c: char) -> bool {
    c == ' ' || c == '\t' || c == '\n'
}

struct Parser {
    src: Vec<char>,
    nodes: Vec<Node>,
    depth: usize,
}

/// A nest or a list behind a key that is not a table (`KeyError` in the reference), or a Python error.
enum Nest {
    Key,
    Raised(Error),
}

impl From<Error> for Nest {
    fn from(error: Error) -> Nest {
        Nest::Raised(error)
    }
}

impl Parser {
    /// One Python frame entered for `body`, and left.
    fn call<T>(&mut self, body: impl FnOnce(&mut Parser) -> Parsed<T>) -> Parsed<T> {
        if self.depth >= LIMIT {
            return Err(Error::Recursion);
        }
        self.depth += 1;
        let answer = body(self);
        self.depth -= 1;
        answer
    }

    /// `raise TOMLDecodeError(msg, src, pos)`: its `__init__` is one more frame.
    fn decode<T>(&mut self) -> Parsed<T> {
        self.call(|_| Ok(()))?;
        Err(Error::Decode)
    }

    fn at(&self, pos: usize) -> Option<char> {
        self.src.get(pos).copied()
    }

    fn starts(&self, pos: usize, text: &str) -> bool {
        let mut at = pos;
        for c in text.chars() {
            if self.at(at) != Some(c) {
                return false;
            }
            at += 1;
        }
        true
    }

    fn node(&mut self, node: Node) -> usize {
        self.nodes.push(node);
        self.nodes.len() - 1
    }

    fn is_table(&self, index: usize) -> bool {
        matches!(self.nodes[index], Node::Table(_))
    }

    fn is_list(&self, index: usize) -> bool {
        matches!(self.nodes[index], Node::List(_))
    }

    fn table_get(&self, table: usize, key: &str) -> Option<usize> {
        match &self.nodes[table] {
            Node::Table(map) => map.get(key).copied(),
            _ => None,
        }
    }

    fn table_put(&mut self, table: usize, key: &str, value: usize) {
        if let Node::Table(map) = &mut self.nodes[table] {
            map.insert(key.to_owned(), value);
        }
    }

    fn skip_chars(&mut self, pos: usize, chars: fn(char) -> bool) -> Parsed<usize> {
        self.call(|p| {
            let mut pos = pos;
            while p.at(pos).is_some_and(chars) {
                pos += 1;
            }
            Ok(pos)
        })
    }

    fn find(&self, expect: &str, pos: usize) -> Option<usize> {
        let wanted: Vec<char> = expect.chars().collect();
        if pos > self.src.len() {
            return None;
        }
        (pos..=self.src.len().saturating_sub(wanted.len()))
            .find(|start| self.src[*start..].starts_with(&wanted))
    }

    fn skip_until(
        &mut self,
        pos: usize,
        expect: &str,
        error_on: fn(char) -> bool,
        error_on_eof: bool,
    ) -> Parsed<usize> {
        self.call(|p| {
            let new_pos = match p.find(expect, pos) {
                Some(found) => found,
                None => {
                    if error_on_eof {
                        return p.decode();
                    }
                    p.src.len()
                }
            };
            if p.src[pos.min(p.src.len())..new_pos.max(pos.min(p.src.len()))]
                .iter()
                .any(|c| error_on(*c))
            {
                return p.decode();
            }
            Ok(new_pos)
        })
    }

    fn skip_comment(&mut self, pos: usize) -> Parsed<usize> {
        self.call(|p| {
            if p.at(pos) == Some('#') {
                return p.skip_until(pos + 1, "\n", illegal_basic, false);
            }
            Ok(pos)
        })
    }

    fn skip_comments_and_array_ws(&mut self, pos: usize) -> Parsed<usize> {
        self.call(|p| {
            let mut pos = pos;
            loop {
                let before = pos;
                pos = p.skip_chars(pos, ws_nl)?;
                pos = p.skip_comment(pos)?;
                if pos == before {
                    return Ok(pos);
                }
            }
        })
    }

    fn get_or_create_nest(
        &mut self,
        root: usize,
        key: &[String],
        access_lists: bool,
    ) -> Result<usize, Nest> {
        if self.depth >= LIMIT {
            return Err(Nest::Raised(Error::Recursion));
        }
        self.depth += 1;
        let answer = (|| {
            let mut cont = root;
            for part in key {
                let next = match self.table_get(cont, part) {
                    Some(found) => found,
                    None => {
                        let made = self.node(Node::Table(HashMap::new()));
                        self.table_put(cont, part, made);
                        made
                    }
                };
                cont = next;
                if access_lists && self.is_list(cont) {
                    cont = match &self.nodes[cont] {
                        Node::List(items) => *items.last().ok_or(Nest::Raised(Error::Index))?,
                        _ => cont,
                    };
                }
                if !self.is_table(cont) {
                    return Err(Nest::Key);
                }
            }
            Ok(cont)
        })();
        self.depth -= 1;
        answer
    }

    fn append_nest_to_list(&mut self, root: usize, key: &Key) -> Result<(), Nest> {
        if self.depth >= LIMIT {
            return Err(Nest::Raised(Error::Recursion));
        }
        self.depth += 1;
        let answer = (|| {
            let cont = self.get_or_create_nest(root, &key[..key.len() - 1], true)?;
            let last = &key[key.len() - 1];
            match self.table_get(cont, last) {
                Some(found) => {
                    if !self.is_list(found) {
                        return Err(Nest::Key);
                    }
                    let made = self.node(Node::Table(HashMap::new()));
                    if let Node::List(items) = &mut self.nodes[found] {
                        items.push(made);
                    }
                }
                None => {
                    let made = self.node(Node::Table(HashMap::new()));
                    let list = self.node(Node::List(vec![made]));
                    self.table_put(cont, last, list);
                }
            }
            Ok(())
        })();
        self.depth -= 1;
        answer
    }

    fn flags_is(&mut self, flags: &Flags, key: &Key, flag: u8) -> Parsed<bool> {
        self.call(|_| Ok(flags.is(key, flag)))
    }

    fn flags_set(&mut self, flags: &mut Flags, key: &Key, flag: u8, recursive: bool) -> Parsed<()> {
        self.call(|_| {
            flags.set(key, flag, recursive);
            Ok(())
        })
    }

    fn create_dict_rule(&mut self, pos: usize, root: usize, flags: &mut Flags) -> Parsed<(usize, Key)> {
        self.call(|p| {
            let pos = p.skip_chars(pos + 1, ws)?;
            let (pos, key) = p.parse_key(pos)?;
            if p.flags_is(flags, &key, EXPLICIT_NEST)? || p.flags_is(flags, &key, FROZEN)? {
                return p.decode();
            }
            p.flags_set(flags, &key, EXPLICIT_NEST, false)?;
            match p.get_or_create_nest(root, &key, true) {
                Ok(_) => {}
                Err(Nest::Key) => return p.decode(),
                Err(Nest::Raised(error)) => return Err(error),
            }
            if !p.starts(pos, "]") {
                return p.decode();
            }
            Ok((pos + 1, key))
        })
    }

    fn create_list_rule(&mut self, pos: usize, root: usize, flags: &mut Flags) -> Parsed<(usize, Key)> {
        self.call(|p| {
            let pos = p.skip_chars(pos + 2, ws)?;
            let (pos, key) = p.parse_key(pos)?;
            if p.flags_is(flags, &key, FROZEN)? {
                return p.decode();
            }
            p.call(|_| {
                flags.unset_all(&key);
                Ok(())
            })?;
            p.flags_set(flags, &key, EXPLICIT_NEST, false)?;
            match p.append_nest_to_list(root, &key) {
                Ok(()) => {}
                Err(Nest::Key) => return p.decode(),
                Err(Nest::Raised(error)) => return Err(error),
            }
            if !p.starts(pos, "]]") {
                return p.decode();
            }
            Ok((pos + 2, key))
        })
    }

    fn key_value_rule(&mut self, pos: usize, root: usize, flags: &mut Flags, header: &Key) -> Parsed<usize> {
        self.call(|p| {
            let (pos, key, value) = p.parse_key_value_pair(pos)?;
            let stem = key[key.len() - 1].clone();
            let mut absolute = header.clone();
            absolute.extend_from_slice(&key[..key.len() - 1]);
            for index in 1..key.len() {
                // The generator expression's frame, entered for each item it gives.
                p.call(|_| Ok(()))?;
                let mut cont_key = header.clone();
                cont_key.extend_from_slice(&key[..index]);
                if p.flags_is(flags, &cont_key, EXPLICIT_NEST)? {
                    return p.decode();
                }
                p.call(|_| {
                    flags.add_pending(&cont_key, EXPLICIT_NEST);
                    Ok(())
                })?;
            }
            // The generator's last step: the one that finds it exhausted.
            if key.len() > 1 {
                p.call(|_| Ok(()))?;
            }
            if p.flags_is(flags, &absolute, FROZEN)? {
                return p.decode();
            }
            let nest = match p.get_or_create_nest(root, &absolute, true) {
                Ok(nest) => nest,
                Err(Nest::Key) => return p.decode(),
                Err(Nest::Raised(error)) => return Err(error),
            };
            if p.table_get(nest, &stem).is_some() {
                return p.decode();
            }
            if p.is_table(value) || p.is_list(value) {
                let mut whole = header.clone();
                whole.extend_from_slice(&key);
                p.flags_set(flags, &whole, FROZEN, true)?;
            }
            p.table_put(nest, &stem, value);
            Ok(pos)
        })
    }

    fn parse_key_value_pair(&mut self, pos: usize) -> Parsed<(usize, Key, usize)> {
        self.call(|p| {
            let (pos, key) = p.parse_key(pos)?;
            if p.at(pos) != Some('=') {
                return p.decode();
            }
            let pos = p.skip_chars(pos + 1, ws)?;
            let (pos, value) = p.parse_value(pos)?;
            Ok((pos, key, value))
        })
    }

    fn parse_key(&mut self, pos: usize) -> Parsed<(usize, Key)> {
        self.call(|p| {
            let (pos, part) = p.parse_key_part(pos)?;
            let mut key = vec![part];
            let mut pos = p.skip_chars(pos, ws)?;
            loop {
                if p.at(pos) != Some('.') {
                    return Ok((pos, key));
                }
                pos = p.skip_chars(pos + 1, ws)?;
                let (next, part) = p.parse_key_part(pos)?;
                key.push(part);
                if key.len() > LIMIT {
                    return Err(Error::Recursion);
                }
                pos = p.skip_chars(next, ws)?;
            }
        })
    }

    fn parse_key_part(&mut self, pos: usize) -> Parsed<(usize, String)> {
        self.call(|p| match p.at(pos) {
            Some(c) if bare(c) => {
                let end = p.skip_chars(pos, bare)?;
                Ok((end, p.src[pos..end].iter().collect()))
            }
            Some('\'') => p.parse_literal_str(pos),
            Some('"') => p.parse_one_line_basic_str(pos),
            _ => p.decode(),
        })
    }

    fn parse_one_line_basic_str(&mut self, pos: usize) -> Parsed<(usize, String)> {
        self.call(|p| p.parse_basic_str(pos + 1, false))
    }

    fn parse_array(&mut self, pos: usize) -> Parsed<(usize, usize)> {
        self.call(|p| {
            let mut items = Vec::new();
            let mut pos = p.skip_comments_and_array_ws(pos + 1)?;
            if p.starts(pos, "]") {
                return Ok((pos + 1, p.node(Node::List(items))));
            }
            loop {
                let (next, value) = p.parse_value(pos)?;
                items.push(value);
                pos = p.skip_comments_and_array_ws(next)?;
                match p.at(pos) {
                    Some(']') => return Ok((pos + 1, p.node(Node::List(items)))),
                    Some(',') => {}
                    _ => return p.decode(),
                }
                pos = p.skip_comments_and_array_ws(pos + 1)?;
                if p.starts(pos, "]") {
                    return Ok((pos + 1, p.node(Node::List(items))));
                }
            }
        })
    }

    fn parse_inline_table(&mut self, pos: usize) -> Parsed<(usize, usize)> {
        self.call(|p| {
            p.call(|_| Ok(()))?; // NestedDict()
            let table = p.node(Node::Table(HashMap::new()));
            p.call(|_| Ok(()))?; // Flags()
            let mut flags = Flags::default();
            let mut pos = p.skip_chars(pos + 1, ws)?;
            if p.starts(pos, "}") {
                return Ok((pos + 1, table));
            }
            loop {
                let (next, key, value) = p.parse_key_value_pair(pos)?;
                let stem = key[key.len() - 1].clone();
                if p.flags_is(&flags, &key, FROZEN)? {
                    return p.decode();
                }
                let nest = match p.get_or_create_nest(table, &key[..key.len() - 1], false) {
                    Ok(nest) => nest,
                    Err(Nest::Key) => return p.decode(),
                    Err(Nest::Raised(error)) => return Err(error),
                };
                if p.table_get(nest, &stem).is_some() {
                    return p.decode();
                }
                p.table_put(nest, &stem, value);
                pos = p.skip_chars(next, ws)?;
                match p.at(pos) {
                    Some('}') => return Ok((pos + 1, table)),
                    Some(',') => {}
                    _ => return p.decode(),
                }
                if p.is_table(value) || p.is_list(value) {
                    p.flags_set(&mut flags, &key, FROZEN, true)?;
                }
                pos = p.skip_chars(pos + 1, ws)?;
            }
        })
    }

    fn parse_basic_str_escape(&mut self, pos: usize, multiline: bool) -> Parsed<(usize, String)> {
        self.call(|p| {
            let first = p.at(pos);
            let second = p.at(pos + 1);
            let pos = pos + 2;
            let escape = (first, second);
            if multiline && matches!(escape, (Some('\\'), Some(' ' | '\t' | '\n'))) {
                let mut pos = pos;
                if second != Some('\n') {
                    pos = p.skip_chars(pos, ws)?;
                    match p.at(pos) {
                        None => return Ok((pos, String::new())),
                        Some('\n') => {}
                        Some(_) => return p.decode(),
                    }
                    pos += 1;
                }
                let pos = p.skip_chars(pos, ws_nl)?;
                return Ok((pos, String::new()));
            }
            match escape {
                (Some('\\'), Some('u')) => p.parse_hex_char(pos, 4),
                (Some('\\'), Some('U')) => p.parse_hex_char(pos, 8),
                (Some('\\'), Some(c @ ('b' | 't' | 'n' | 'f' | 'r' | '"' | '\\'))) => {
                    let replaced = match c {
                        'b' => '\u{8}',
                        't' => '\t',
                        'n' => '\n',
                        'f' => '\u{c}',
                        'r' => '\r',
                        other => other,
                    };
                    Ok((pos, replaced.to_string()))
                }
                _ => p.decode(),
            }
        })
    }

    fn parse_hex_char(&mut self, pos: usize, length: usize) -> Parsed<(usize, String)> {
        self.call(|p| {
            let end = (pos + length).min(p.src.len());
            let text: String = p.src[pos.min(end)..end].iter().collect();
            if text.chars().count() != length || !text.chars().all(|c| c.is_ascii_hexdigit()) {
                return p.decode();
            }
            let value = u32::from_str_radix(&text, 16).map_err(|_| Error::Decode)?;
            let scalar = p.call(|_| Ok(value <= 55295 || (57344..=1_114_111).contains(&value)))?;
            if !scalar {
                return p.decode();
            }
            Ok((
                pos + length,
                char::from_u32(value).map(String::from).unwrap_or_default(),
            ))
        })
    }

    fn parse_literal_str(&mut self, pos: usize) -> Parsed<(usize, String)> {
        self.call(|p| {
            let start = pos + 1;
            let end = p.skip_until(start, "'", illegal_basic, true)?;
            Ok((end + 1, p.src[start..end].iter().collect()))
        })
    }

    fn parse_multiline_str(&mut self, pos: usize, literal: bool) -> Parsed<(usize, String)> {
        self.call(|p| {
            let mut pos = pos + 3;
            if p.starts(pos, "\n") {
                pos += 1;
            }
            let (delim, mut result);
            if literal {
                delim = '\'';
                let end = p.skip_until(pos, "'''", illegal_multiline, true)?;
                result = p.src[pos..end].iter().collect::<String>();
                pos = end + 3;
            } else {
                delim = '"';
                (pos, result) = p.parse_basic_str(pos, true)?;
            }
            for _ in 0..2 {
                if p.at(pos) != Some(delim) {
                    return Ok((pos, result));
                }
                pos += 1;
                result.push(delim);
            }
            Ok((pos, result))
        })
    }

    fn parse_basic_str(&mut self, pos: usize, multiline: bool) -> Parsed<(usize, String)> {
        self.call(|p| {
            let error_on: fn(char) -> bool = if multiline {
                illegal_multiline
            } else {
                illegal_basic
            };
            let mut result = String::new();
            let mut pos = pos;
            let mut start = pos;
            loop {
                let Some(c) = p.at(pos) else {
                    return p.decode();
                };
                if c == '"' {
                    if !multiline {
                        result.extend(&p.src[start..pos]);
                        return Ok((pos + 1, result));
                    }
                    if p.starts(pos, "\"\"\"") {
                        result.extend(&p.src[start..pos]);
                        return Ok((pos + 3, result));
                    }
                    pos += 1;
                    continue;
                }
                if c == '\\' {
                    result.extend(&p.src[start..pos]);
                    let (next, escaped) = if multiline {
                        // parse_basic_str_escape_multiline: one frame more.
                        p.call(|p| p.parse_basic_str_escape(pos, true))?
                    } else {
                        p.parse_basic_str_escape(pos, false)?
                    };
                    result.push_str(&escaped);
                    pos = next;
                    start = pos;
                    continue;
                }
                if error_on(c) {
                    return p.decode();
                }
                pos += 1;
            }
        })
    }

    fn parse_value(&mut self, pos: usize) -> Parsed<(usize, usize)> {
        self.call(|p| {
            let c = p.at(pos);
            if c == Some('"') {
                let (end, text) = if p.starts(pos, "\"\"\"") {
                    p.parse_multiline_str(pos, false)?
                } else {
                    p.parse_one_line_basic_str(pos)?
                };
                return Ok((end, p.node(Node::Str(text))));
            }
            if c == Some('\'') {
                let (end, text) = if p.starts(pos, "'''") {
                    p.parse_multiline_str(pos, true)?
                } else {
                    p.parse_literal_str(pos)?
                };
                return Ok((end, p.node(Node::Str(text))));
            }
            if c == Some('t') && p.starts(pos, "true") {
                return Ok((pos + 4, p.node(Node::Other)));
            }
            if c == Some('f') && p.starts(pos, "false") {
                return Ok((pos + 5, p.node(Node::Other)));
            }
            if c == Some('[') {
                return p.parse_array(pos);
            }
            if c == Some('{') {
                return p.parse_inline_table(pos);
            }
            if let Some((end, valid)) = datetime(&p.src, pos) {
                p.call(|_| Ok(()))?; // match_to_datetime
                if !valid {
                    return p.decode();
                }
                return Ok((end, p.node(Node::Other)));
            }
            if let Some(end) = time(&p.src, pos) {
                p.call(|_| Ok(()))?; // match_to_localtime
                return Ok((end, p.node(Node::Other)));
            }
            if let Some(end) = number(&p.src, pos) {
                p.call(|_| Ok(()))?; // match_to_number
                return Ok((end, p.node(Node::Other)));
            }
            for word in ["inf", "nan"] {
                if p.starts(pos, word) {
                    return Ok((pos + 3, p.node(Node::Other)));
                }
            }
            for word in ["-inf", "+inf", "-nan", "+nan"] {
                if p.starts(pos, word) {
                    return Ok((pos + 4, p.node(Node::Other)));
                }
            }
            p.decode()
        })
    }

    fn loads(&mut self, root: usize) -> Parsed<()> {
        self.call(|p| {
            // make_safe_parse_float, Output(...), NestedDict(), Flags(): frames entered and left at the start.
            for _ in 0..4 {
                p.call(|_| Ok(()))?;
            }
            let mut flags = Flags::default();
            let mut header: Key = Vec::new();
            let mut pos = 0usize;
            loop {
                pos = p.skip_chars(pos, ws)?;
                let Some(c) = p.at(pos) else {
                    break;
                };
                if c == '\n' {
                    pos += 1;
                    continue;
                }
                if bare(c) || c == '"' || c == '\'' {
                    pos = p.key_value_rule(pos, root, &mut flags, &header)?;
                    pos = p.skip_chars(pos, ws)?;
                } else if c == '[' {
                    let second = p.at(pos + 1);
                    p.call(|_| {
                        flags.finalize_pending();
                        Ok(())
                    })?;
                    (pos, header) = if second == Some('[') {
                        p.create_list_rule(pos, root, &mut flags)?
                    } else {
                        p.create_dict_rule(pos, root, &mut flags)?
                    };
                    pos = p.skip_chars(pos, ws)?;
                } else if c != '#' {
                    return p.decode();
                }
                pos = p.skip_comment(pos)?;
                match p.at(pos) {
                    None => break,
                    Some('\n') => pos += 1,
                    Some(_) => return p.decode(),
                }
            }
            Ok(())
        })
    }
}

/// `(?:_?[digit])*` from `pos`, greedy: where it ends.
fn underscored(src: &[char], mut pos: usize, digit: fn(char) -> bool) -> usize {
    loop {
        match (src.get(pos), src.get(pos + 1)) {
            (Some('_'), Some(next)) if digit(*next) => pos += 2,
            (Some(c), _) if digit(*c) => pos += 1,
            _ => return pos,
        }
    }
}

fn decimal(c: char) -> bool {
    c.is_ascii_digit()
}

/// `RE_NUMBER.match(src, pos)`: where the match ends.
fn number(src: &[char], pos: usize) -> Option<usize> {
    if src.get(pos) == Some(&'0') {
        let digit: Option<fn(char) -> bool> = match src.get(pos + 1) {
            Some('x') => Some(|c: char| c.is_ascii_hexdigit()),
            Some('b') => Some(|c: char| c == '0' || c == '1'),
            Some('o') => Some(|c: char| ('0'..='7').contains(&c)),
            _ => None,
        };
        if let Some(digit) = digit
            && src.get(pos + 2).is_some_and(|c| digit(*c))
        {
            return Some(underscored(src, pos + 3, digit));
        }
    }
    let mut at = pos;
    if matches!(src.get(at), Some('+' | '-')) {
        at += 1;
    }
    match src.get(at) {
        Some('0') => at += 1,
        Some(c) if ('1'..='9').contains(c) => at = underscored(src, at + 1, decimal),
        _ => return None,
    }
    if src.get(at) == Some(&'.') && src.get(at + 1).is_some_and(|c| decimal(*c)) {
        at = underscored(src, at + 2, decimal);
    }
    if matches!(src.get(at), Some('e' | 'E')) {
        let mut exponent = at + 1;
        if matches!(src.get(exponent), Some('+' | '-')) {
            exponent += 1;
        }
        if src.get(exponent).is_some_and(|c| decimal(*c)) {
            at = underscored(src, exponent + 1, decimal);
        }
    }
    Some(at)
}

fn digits(src: &[char], pos: usize, count: usize) -> Option<u32> {
    let mut value = 0u32;
    for index in 0..count {
        let c = *src.get(pos + index)?;
        value = value * 10 + c.to_digit(10).filter(|_| c.is_ascii_digit())?;
    }
    Some(value)
}

/// `_TIME_RE_STR` from `pos`: where it ends.
fn time(src: &[char], pos: usize) -> Option<usize> {
    let hour = digits(src, pos, 2)?;
    if hour > 23 || src.get(pos + 2) != Some(&':') {
        return None;
    }
    if digits(src, pos + 3, 2)? > 59 || src.get(pos + 5) != Some(&':') {
        return None;
    }
    if digits(src, pos + 6, 2)? > 59 {
        return None;
    }
    let mut end = pos + 8;
    if src.get(end) == Some(&'.') && src.get(end + 1).is_some_and(|c| decimal(*c)) {
        end += 1;
        while src.get(end).is_some_and(|c| decimal(*c)) {
            end += 1;
        }
    }
    Some(end)
}

/// `RE_DATETIME.match(src, pos)`: where it ends, and whether `match_to_datetime` takes it as a date (a year 1-9999, a
/// day the month has).
fn datetime(src: &[char], pos: usize) -> Option<(usize, bool)> {
    let year = digits(src, pos, 4)?;
    if src.get(pos + 4) != Some(&'-') {
        return None;
    }
    let month = digits(src, pos + 5, 2)?;
    if !(1..=12).contains(&month) || src.get(pos + 7) != Some(&'-') {
        return None;
    }
    let day = digits(src, pos + 8, 2)?;
    if !(1..=31).contains(&day) {
        return None;
    }
    let mut end = pos + 10;
    if matches!(src.get(end), Some('T' | 't' | ' '))
        && let Some(after) = time(src, end + 1)
    {
        end = after;
        match src.get(end) {
            Some('Z' | 'z') => end += 1,
            Some('+' | '-') => {
                if let (Some(hours), Some(':'), Some(minutes)) = (
                    digits(src, end + 1, 2),
                    src.get(end + 3),
                    digits(src, end + 4, 2),
                ) && hours <= 23
                    && minutes <= 59
                {
                    end += 6;
                }
            }
            _ => {}
        }
    }
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let days = match month {
        2 if leap => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    };
    Some((end, year >= 1 && day <= days))
}

/// `tomllib.loads(text).get(key)`, the caller already `base` Python frames deep (loads itself not counted): the value
/// at the top level under `key` (None where there is none), or why the document was refused.
pub fn top_level(text: &str, key: &str, base: usize) -> Result<Option<Found>, Error> {
    let mut parser = Parser {
        src: text.replace("\r\n", "\n").chars().collect(),
        nodes: vec![Node::Table(HashMap::new())],
        depth: base,
    };
    parser.loads(0)?;
    Ok(parser.table_get(0, key).map(|index| match &parser.nodes[index] {
        Node::Str(text) => Found::Str(text.clone()),
        _ => Found::Other,
    }))
}
