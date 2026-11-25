//! Python's Windows path algebra (`ntpath`, `pathlib.PureWindowsPath`) over plain strings, and `Path.resolve()`.
//!
//! `Paths` names every file the product owns by `Path(root).expanduser().resolve() / "config" / ...`, and the
//! names it makes are compared with the reference's (the object names of PLAN 6.2 depend on them), so the
//! normalisation is Python 3.13's, string by string: `splitroot`, `normpath`, `isabs`, `join`, `split`, the
//! pathlib parse and its case-insensitive comparison, `expanduser` and `realpath` (non-strict, the bundled 3.14.10's:
//! a link the OS cannot open is followed by hand, a component's real name asked of FindFirstFileW). The questions
//! `realpath` asks of Windows are a trait ([`NtOs`]): car-platform answers them natively and car-config through its
//! probe, so this one implementation is both crates' (it lived in car-config until review 4).
//!
//! Strings only, on any platform: the algebra is tested anywhere, the resolution only where the OS answers it.

const SEPS: [char; 2] = ['\\', '/'];

fn is_sep(c: char) -> bool {
    SEPS.contains(&c)
}

/// `ntpath.splitroot(p)`: (drive, root, tail), as slices of `p`.
pub fn splitroot(p: &str) -> (&str, &str, &str) {
    let normal: String = p.replace('/', "\\");
    let first = normal.chars().next();
    let second = normal.chars().nth(1);
    let third = normal.chars().nth(2);
    let at = |count: usize| -> usize {
        // byte index of the `count`-th character of `p`
        p.char_indices()
            .nth(count)
            .map_or(p.len(), |(index, _)| index)
    };
    if first == Some('\\') {
        if second == Some('\\') {
            // UNC and device drives: \\server\share, \\?\UNC\server\share, \\.\device, \\?\device
            let head: String = normal.chars().take(8).collect::<String>().to_uppercase();
            let start = if head == "\\\\?\\UNC\\" { 8 } else { 2 };
            let chars: Vec<char> = normal.chars().collect();
            let find = |from: usize| {
                chars[from.min(chars.len())..]
                    .iter()
                    .position(|c| *c == '\\')
                    .map(|i| i + from)
            };
            let Some(index) = find(start) else {
                return (p, "", "");
            };
            let Some(index2) = find(index + 1) else {
                return (p, "", "");
            };
            return (
                &p[..at(index2)],
                &p[at(index2)..at(index2 + 1)],
                &p[at(index2 + 1)..],
            );
        }
        return ("", &p[..at(1)], &p[at(1)..]);
    }
    if second == Some(':') {
        if third == Some('\\') {
            return (&p[..at(2)], &p[at(2)..at(3)], &p[at(3)..]);
        }
        return (&p[..at(2)], "", &p[at(2)..]);
    }
    ("", "", p)
}

/// `ntpath.splitdrive(p)`: (drive, rest).
pub fn splitdrive(p: &str) -> (&str, &str) {
    let (drive, root, tail) = splitroot(p);
    (
        drive,
        &p[drive.len()..drive.len() + root.len() + tail.len()],
    )
}

/// `ntpath.normpath(p)`.
pub fn normpath(p: &str) -> String {
    let path = p.replace('/', "\\");
    let (drive, root, rest) = splitroot(&path);
    let prefix = format!("{drive}{root}");
    let mut parts: Vec<&str> = rest.split('\\').collect();
    let mut i = 0;
    while i < parts.len() {
        if parts[i].is_empty() || parts[i] == "." {
            parts.remove(i);
        } else if parts[i] == ".." {
            if i > 0 && parts[i - 1] != ".." {
                parts.drain(i - 1..=i);
                i -= 1;
            } else if i == 0 && !root.is_empty() {
                parts.remove(i);
            } else {
                i += 1;
            }
        } else {
            i += 1;
        }
    }
    if prefix.is_empty() && parts.is_empty() {
        parts.push(".");
    }
    format!("{prefix}{}", parts.join("\\"))
}

/// `ntpath.isabs(p)` (3.13): a drive and a root, or two leading separators.
pub fn isabs(p: &str) -> bool {
    let head: String = p.chars().take(3).collect::<String>().replace('/', "\\");
    head.chars().skip(1).collect::<String>().starts_with(":\\") || head.starts_with("\\\\")
}

/// `ntpath.join(a, b)`.
pub fn join(a: &str, b: &str) -> String {
    let (mut drive, mut root, mut path) = {
        let (d, r, t) = splitroot(a);
        (d.to_owned(), r.to_owned(), t.to_owned())
    };
    let (p_drive, p_root, p_path) = splitroot(b);
    if !p_root.is_empty() {
        if !p_drive.is_empty() || drive.is_empty() {
            drive = p_drive.to_owned();
        }
        root = p_root.to_owned();
        path = p_path.to_owned();
        return finish_join(drive, root, path);
    }
    if !p_drive.is_empty() && p_drive != drive {
        if p_drive.to_lowercase() != drive.to_lowercase() {
            return finish_join(p_drive.to_owned(), p_root.to_owned(), p_path.to_owned());
        }
        drive = p_drive.to_owned();
    }
    if !path.is_empty() && !path.ends_with(is_sep) {
        path.push('\\');
    }
    path.push_str(p_path);
    finish_join(drive, root, path)
}

fn finish_join(drive: String, root: String, path: String) -> String {
    if !path.is_empty()
        && root.is_empty()
        && !drive.is_empty()
        && !drive.ends_with([':', '\\', '/'])
    {
        return format!("{drive}\\{path}");
    }
    format!("{drive}{root}{path}")
}

/// `ntpath.split(p)`: (head, tail).
pub fn split(p: &str) -> (String, String) {
    let (drive, root, rest) = splitroot(p);
    let chars: Vec<char> = rest.chars().collect();
    let mut i = chars.len();
    while i > 0 && !is_sep(chars[i - 1]) {
        i -= 1;
    }
    let head: String = chars[..i].iter().collect();
    let tail: String = chars[i..].iter().collect();
    (
        format!("{drive}{root}{}", head.trim_end_matches(is_sep)),
        tail,
    )
}

/// The pathlib parse of a string: (drive, root, components), the form `str(Path(p))` and path equality read.
pub fn parse(p: &str) -> (String, String, Vec<String>) {
    if p.is_empty() {
        return (String::new(), String::new(), Vec::new());
    }
    let path = p.replace('/', "\\");
    let (drive, root, rest) = splitroot(&path);
    let mut root = root.to_owned();
    if root.is_empty() && drive.starts_with('\\') && !drive.ends_with('\\') {
        let pieces: Vec<&str> = drive.split('\\').collect();
        if (pieces.len() == 4 && !"?.".contains(pieces[2])) || pieces.len() == 6 {
            root = "\\".to_owned();
        }
    }
    let tail = rest
        .split('\\')
        .filter(|part| !part.is_empty() && *part != ".")
        .map(str::to_owned)
        .collect();
    (drive.to_owned(), root, tail)
}

/// `str(Path(p))`.
pub fn path_str(p: &str) -> String {
    let (drive, root, tail) = parse(p);
    if !drive.is_empty() || !root.is_empty() {
        return format!("{drive}{root}{}", tail.join("\\"));
    }
    let mut tail = tail;
    if tail
        .first()
        .is_some_and(|first| !splitdrive(first).0.is_empty())
    {
        tail.insert(0, ".".to_owned());
    }
    if tail.is_empty() {
        ".".to_owned()
    } else {
        tail.join("\\")
    }
}

/// Two paths equal as pathlib's Windows flavour compares them: drive, root and every component, lower-cased.
pub fn same_path(a: &str, b: &str) -> bool {
    let (da, ra, ta) = parse(a);
    let (db, rb, tb) = parse(b);
    da.to_lowercase() == db.to_lowercase()
        && ra.to_lowercase() == rb.to_lowercase()
        && ta.len() == tb.len()
        && ta
            .iter()
            .zip(&tb)
            .all(|(x, y)| x.to_lowercase() == y.to_lowercase())
}

/// `a.is_relative_to(b)`: `b`'s drive, root and components are a prefix of `a`'s (case-insensitively).
pub fn is_relative_to(a: &str, b: &str) -> bool {
    let (da, ra, ta) = parse(a);
    let (db, rb, tb) = parse(b);
    da.to_lowercase() == db.to_lowercase()
        && ra.to_lowercase() == rb.to_lowercase()
        && ta.len() >= tb.len()
        && ta
            .iter()
            .zip(&tb)
            .all(|(x, y)| x.to_lowercase() == y.to_lowercase())
}

/// The environment a path is expanded in.
pub type Env<'a> = &'a dyn Fn(&str) -> Option<String>;

/// `ntpath.expanduser(path)` of a first path component.
fn expand_component(path: &str, env: Env) -> String {
    if !path.starts_with('~') {
        return path.to_owned();
    }
    let chars: Vec<char> = path.chars().collect();
    let mut i = 1;
    while i < chars.len() && !is_sep(chars[i]) {
        i += 1;
    }
    let mut userhome = match env("USERPROFILE") {
        Some(home) => home,
        None => match env("HOMEPATH") {
            None => return path.to_owned(),
            Some(homepath) => join(&env("HOMEDRIVE").unwrap_or_default(), &homepath),
        },
    };
    if i != 1 {
        let target: String = chars[1..i].iter().collect();
        let current = env("USERNAME");
        if current.as_deref() != Some(target.as_str()) {
            let base = split(&userhome).1;
            if current.as_deref() != Some(base.as_str()) {
                return path.to_owned();
            }
            userhome = join(&split(&userhome).0, &target);
        }
    }
    let rest: String = chars[i..].iter().collect();
    format!("{userhome}{rest}")
}

/// `Path(p).expanduser()` as a string; `Err` is the RuntimeError of an unknown home.
pub fn expanduser(p: &str, env: Env) -> Result<String, &'static str> {
    let (drive, root, tail) = parse(p);
    if drive.is_empty()
        && root.is_empty()
        && tail.first().is_some_and(|first| first.starts_with('~'))
    {
        let home = expand_component(&tail[0], env);
        if home.starts_with('~') {
            return Err("RuntimeError");
        }
        let mut parts = vec![home];
        parts.extend(tail[1..].iter().cloned());
        return Ok(path_str(&parts.join("\\")));
    }
    Ok(path_str(p))
}

/// What the OS says of a path: its final form (`\\?\` prefix included), or the Windows error number.
pub type FinalPath<'a> = &'a dyn Fn(&str) -> Result<String, i32>;

/// `_getfinalpathname` through the standard library: the final path name with its verbatim prefix.
pub fn os_final_path(path: &str) -> Result<String, i32> {
    match std::fs::canonicalize(path) {
        Ok(found) => Ok(found.to_string_lossy().into_owned()),
        Err(error) => Err(error.raw_os_error().unwrap_or(0)),
    }
}

/// What `os.readlink` (`_nt_readlink`) answers of a path.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Readlink {
    /// The link's target as the link holds it (`\??\` given as `\\?\`; a relative symbolic link's text as it is).
    Target(String),
    /// OSError with this Windows error number (4390: not a reparse point).
    Os(i32),
    /// ValueError: a reparse point that is neither a symbolic link nor a junction.
    NotALink,
}

/// `os.readlink` through the standard library, which reads the reparse data as CPython does (a junction's or a
/// symbolic link's substitute name, `\??\` turned into `\\?\`); an error without a Windows number is std's
/// "unsupported reparse point", CPython's ValueError.
pub fn os_readlink(path: &str) -> Readlink {
    match std::fs::read_link(path) {
        Ok(target) => Readlink::Target(target.to_string_lossy().into_owned()),
        Err(error) => match error.raw_os_error() {
            Some(code) => Readlink::Os(code),
            None => Readlink::NotALink,
        },
    }
}

/// The questions `os.path.realpath` asks Windows (3.14's `ntpath`): one implementation of the algorithm for every
/// crate, each asking through what it has (car-platform natively, car-config through its probe).
pub trait NtOs {
    /// `_getfinalpathname(path)`.
    fn final_path(&self, path: &str) -> Result<String, i32>;
    /// `_nt_readlink(path)`.
    fn readlink(&self, path: &str) -> Readlink {
        os_readlink(path)
    }
    /// `islink(path)`: a symbolic link (never a junction), as `os.lstat` reads the tag.
    fn is_symlink(&self, path: &str) -> bool;
    /// `_findfirstfile(path)`: the name FindFirstFileW gives the last component, or its error number.
    fn find_first_file(&self, path: &str) -> Result<String, i32>;
    /// Whether a path past 260 characters is taken without its `\\?\` prefix (LongPathsEnabled; Python is
    /// long-path aware), which decides whether the prefix is stripped from a long path.
    fn long_paths(&self) -> bool;
}

const ALLOWED: [i32; 16] = [
    1, 2, 3, 5, 21, 32, 50, 53, 65, 67, 87, 123, 161, 1005, 1920, 1921,
];
/// The errors after which `_getfinalpathname_nonstrict` asks `_findfirstfile` for the component's real name.
const FIND_FIRST: [i32; 7] = [1, 5, 32, 50, 87, 1920, 1921];
/// The errors that end `_readlink_deep`'s walk with the path it has.
const READLINK_STOPS: [i32; 12] = [1, 2, 3, 5, 21, 32, 50, 67, 87, 4390, 4392, 4393];

/// `_getfinalpathname_nonstrict`'s own `join` (3.14.10; 3.13 used `ntpath.join`): the two texts with one separator
/// between them, never a drive or root of the tail taken as one.
fn glue(path: &str, tail: &str) -> String {
    if path.ends_with('\\') || tail.is_empty() {
        format!("{path}{tail}")
    } else {
        format!("{path}\\{tail}")
    }
}

/// `dirname(p)`: `split(p)[0]`.
fn dirname(p: &str) -> String {
    split(p).0
}

/// `_readlink_deep(path)`: the link followed, link after link, until what it names is no link; Err is an OSError
/// the walk does not stop at.
fn readlink_deep(mut path: String, os: &dyn NtOs) -> Result<String, i32> {
    let mut seen: Vec<String> = Vec::new();
    while !seen.contains(&normcase(&path)) {
        seen.push(normcase(&path));
        let old = path.clone();
        match os.readlink(&path) {
            Readlink::Target(target) => {
                path = target;
                if !isabs(&path) {
                    // Something other than a symbolic link: what it is resolved against is unknown.
                    if !os.is_symlink(&old) {
                        path = old;
                        break;
                    }
                    path = normpath(&join(&dirname(&old), &path));
                }
            }
            Readlink::Os(code) if READLINK_STOPS.contains(&code) => break,
            Readlink::Os(code) => return Err(code),
            Readlink::NotALink => break,
        }
    }
    Ok(path)
}

/// `ntpath.normcase`: separators as `\`, lower case.
fn normcase(p: &str) -> String {
    p.replace('/', "\\").to_lowercase()
}

fn nonstrict(mut path: String, os: &dyn NtOs) -> Result<String, i32> {
    let mut tail = String::new();
    while !path.is_empty() {
        let code = match os.final_path(&path) {
            Ok(found) => return Ok(if tail.is_empty() { found } else { glue(&found, &tail) }),
            Err(code) => code,
        };
        if !ALLOWED.contains(&code) {
            return Err(code);
        }
        // The OS could not resolve this path fully: the link is followed by hand (an error of it is passed over).
        if let Ok(followed) = readlink_deep(path.clone(), os)
            && followed != path
        {
            return Ok(if tail.is_empty() { followed } else { glue(&followed, &tail) });
        }
        let name;
        if FIND_FIRST.contains(&code) {
            match os.find_first_file(&path) {
                Ok(real) => {
                    name = real;
                    path = split(&path).0;
                }
                Err(_) => (path, name) = split(&path),
            }
        } else {
            (path, name) = split(&path);
        }
        if !path.is_empty() && name.is_empty() {
            return Ok(format!("{path}{tail}"));
        }
        tail = if tail.is_empty() { name } else { glue(&name, &tail) };
    }
    Ok(tail)
}

/// `os.path.realpath(path)` (non-strict) as the bundled runtime (3.14.10) has it. `cwd` is the working directory a
/// relative path is made absolute in. 3.13.15 differs only in the join of the walk (AUDIT-v0628).
pub fn realpath_os(path: &str, cwd: &str, os: &dyn NtOs) -> Result<String, i32> {
    let mut path = normpath(path);
    const PREFIX: &str = "\\\\?\\";
    const UNC_PREFIX: &str = "\\\\?\\UNC\\";
    if path.eq_ignore_ascii_case("nul") {
        return Ok("\\\\.\\NUL".to_owned());
    }
    let had_prefix = path.starts_with(PREFIX);
    if !had_prefix && !isabs(&path) {
        path = join(cwd, &path);
    }
    let mut initial = 0;
    let mut path = match os.final_path(&path) {
        Ok(found) => found,
        Err(code) if ALLOWED.contains(&code) => {
            initial = code;
            nonstrict(path, os)?
        }
        Err(code) => return Err(code),
    };
    if !had_prefix && path.starts_with(PREFIX) {
        let spath = if let Some(rest) = path.strip_prefix(UNC_PREFIX) {
            format!("\\\\{rest}")
        } else {
            path[PREFIX.len()..].to_owned()
        };
        // `_getfinalpathname(spath)`: the unprefixed form resolves where this system takes it as it is.
        let reachable = os.long_paths() || spath.chars().count() < 260;
        match if reachable { os.final_path(&spath) } else { Err(206) } {
            Ok(found) if found == path => path = spath,
            Ok(_) => {}
            Err(code) if code == initial => path = spath,
            Err(_) => {}
        }
    }
    Ok(path)
}

/// The OS of [`realpath`]: one final-path question, no link followed by hand and no real name asked (what the walk
/// had before it learned `_readlink_deep`); for a caller with no link probe, and the algebra's own tests.
struct AskOnly<'a> {
    ask: FinalPath<'a>,
    long_paths: bool,
}

impl NtOs for AskOnly<'_> {
    fn final_path(&self, path: &str) -> Result<String, i32> {
        (self.ask)(path)
    }
    fn readlink(&self, _: &str) -> Readlink {
        Readlink::Os(4390)
    }
    fn is_symlink(&self, _: &str) -> bool {
        false
    }
    fn find_first_file(&self, _: &str) -> Result<String, i32> {
        Err(50)
    }
    fn long_paths(&self) -> bool {
        self.long_paths
    }
}

/// [`realpath_os`] over one final-path question alone (no link followed by hand, no real name asked).
pub fn realpath(path: &str, cwd: &str, ask: FinalPath, long_paths: bool) -> Result<String, i32> {
    realpath_os(path, cwd, &AskOnly { ask, long_paths })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roots() {
        assert_eq!(splitroot("C:\\a\\b"), ("C:", "\\", "a\\b"));
        assert_eq!(splitroot("C:a"), ("C:", "", "a"));
        assert_eq!(
            splitroot("\\\\srv\\share\\x"),
            ("\\\\srv\\share", "\\", "x")
        );
        assert_eq!(
            splitroot("\\\\?\\UNC\\srv\\share\\x"),
            ("\\\\?\\UNC\\srv\\share", "\\", "x")
        );
        assert_eq!(splitroot("\\a"), ("", "\\", "a"));
        assert_eq!(splitroot("a\\b"), ("", "", "a\\b"));
        assert_eq!(splitroot("\\\\srv"), ("\\\\srv", "", ""));
    }

    #[test]
    fn normalising() {
        assert_eq!(normpath("C:/a//b/./c/../d"), "C:\\a\\b\\d");
        assert_eq!(normpath("C:\\.."), "C:\\");
        assert_eq!(normpath(".."), "..");
        assert_eq!(normpath(""), ".");
        assert_eq!(path_str("C:/a//b/"), "C:\\a\\b");
        assert!(isabs("C:\\a") && isabs("\\\\x\\y") && !isabs("\\a") && !isabs("a"));
        assert_eq!(join("C:\\a", "b"), "C:\\a\\b");
        assert_eq!(join("C:\\", "b"), "C:\\b");
        assert!(same_path("C:\\Users\\X", "c:/users/x/"));
        assert!(is_relative_to("C:\\a\\B\\c", "c:\\A"));
    }
}
