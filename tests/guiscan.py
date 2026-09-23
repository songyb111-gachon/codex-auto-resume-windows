"""The scanner every test of the settings window reads its C# through.

`tests/srcscan.py` does this for the Python package, and the reason is the same: a rule about
the window is only as good as the list of files it was looked for in. Until v0.6.10-alpha that
list was written out by hand in seventeen places - the build script, the release measurement,
and fifteen tests that compile the window to look at it - so a file added to the window was a
file added seventeen times, and a test that missed the edit went on compiling a window that
was not the one being shipped, while passing.

`gui/window.sources` is the one list now. This reads it, and reads the files it names.

It also answers the other question those tests ask badly. Twenty test classes take a slice of
`Controls.cs` or `SettingsApp.cs` by searching for text - a declaration, then the next
declaration - and at least two of them re-aim silently when the text between moves: a slice
that ends at "the next `private void `" widens to the end of the file the day that string
stops appearing, and every assertion inside it goes on passing over the wrong code. `type_body`
and `member_body` below find a block by its braces instead, and raise where they cannot.

Not named `test_guiscan.py`, so discovery does not collect it; `tests/test_guiscan.py` is the
file that holds it to its own rules.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"
MANIFEST = GUI / "window.sources"

# Built by the same script from its own single source, and not part of the window.
SEPARATE = ("gui/McpLauncher.cs",)


class ScanError(RuntimeError):
    """The window could not be listed. Never caught: a scan over nothing proves nothing."""


@lru_cache(maxsize=None)
def tracked() -> tuple[str, ...]:
    """Every tracked path under `gui/`, as git spells it."""
    try:
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "gui"],
                                 capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScanError("cannot list the window's sources: %s" % exc) from None
    if listing.returncode != 0:
        raise ScanError("git ls-files failed: %s"
                        % listing.stderr.decode("utf-8", "replace").strip())
    names = tuple(sorted(name for name in listing.stdout.decode("utf-8").split("\0") if name))
    if not any(name.endswith(".cs") for name in names):
        raise ScanError("git lists no C# file under gui/")
    return names


@lru_cache(maxsize=None)
def manifest() -> tuple[str, ...]:
    """The compile list, in the order csc is given it."""
    if not MANIFEST.is_file():
        raise ScanError("gui/window.sources is missing")
    names = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    if not names:
        raise ScanError("gui/window.sources names no source")
    return tuple(names)


def sources() -> list[Path]:
    """The compiled sources as paths, in compile order."""
    return [ROOT / name for name in manifest()]


def on_disk() -> list[Path]:
    """Every `.cs` file under `gui/`, tracked or not."""
    return sorted(path for path in GUI.rglob("*.cs"))


def relative(path: Path) -> str:
    return Path(path).resolve().relative_to(ROOT).as_posix()


@lru_cache(maxsize=None)
def read(name: str) -> str:
    """One compiled source by its repository-relative path, or by its bare file name."""
    if "/" not in name:
        matches = [entry for entry in manifest() if entry.rsplit("/", 1)[-1] == name]
        if len(matches) != 1:
            raise ScanError("%r names %d of the window's sources" % (name, len(matches)))
        name = matches[0]
    if name not in manifest():
        raise ScanError("%s is not one of the window's sources" % name)
    return (ROOT / name).read_text(encoding="utf-8")


def whole() -> str:
    """Every compiled source, concatenated in compile order.

    For the rules that are about the window rather than about one of its files - no browser
    control, no keyboard automation - which is most of them."""
    return "\n".join(read(name) for name in manifest())


def _block(text: str, start: int) -> str:
    """From `start` to the end of the brace-delimited block that follows it."""
    opened = text.find("{", start)
    if opened < 0:
        raise ScanError("no block opens after position %d" % start)
    depth, index = 0, opened
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
        index += 1
    raise ScanError("the block opened at %d never closes" % opened)


def _declaration(name: str) -> re.Pattern:
    return re.compile(r"(?m)^[ \t]*(?:\w+[ \t]+)*(?:class|struct|enum|interface)[ \t]+%s\b"
                      % re.escape(name))


def parts_of(name: str) -> list[str]:
    """Every declaration of `name`, with its body, in compile order.

    A list rather than one block, because the window's main type really is several. The window
    is one `partial class SettingsForm` written across `SettingsApp.cs` and `Dashboard.cs` in
    four parts, and a rule about "the form" that read one of them would be reading a quarter
    of it. Nested private types repeat legitimately too - three `struct`s share a name with
    another class's, and each is that class's own.
    """
    found = []
    pattern = _declaration(name)
    for source in manifest():
        text = read(source)
        at = 0
        while True:
            match = pattern.search(text, at)
            if match is None:
                break
            found.append(_block(text, match.start()))
            at = match.end()
    if not found:
        raise ScanError("no type named %s in the window's sources" % name)
    return found


def type_body(name: str, source: str | None = None) -> str:
    """One `class`, `struct` or `enum` with its declaration line, found by its braces.

    Raises where the type is not there, and where it is there more than once without a source
    to narrow it to. That is the point: the slices this replaces ended at the next occurrence
    of some other text, so a type that stopped being followed by that text silently grew to
    the end of the file and took every assertion about it along.
    """
    if source is not None:
        text = read(source) if source.endswith(".cs") else source
        match = _declaration(name).search(text)
        if match is None:
            raise ScanError("no type named %s in %s" % (name, source[:40]))
        return _block(text, match.start())
    found = parts_of(name)
    if len(found) > 1:
        raise ScanError("%s is declared %d times; name the source it is wanted from"
                        % (name, len(found)))
    return found[0]


MODIFIERS = ("public", "private", "internal", "protected", "static", "sealed", "override",
             "virtual", "abstract", "async", "new", "partial", "readonly", "unsafe", "extern",
             "const", "volatile")


def member_body(type_name: str, member: str) -> str:
    """One method or property of one type, by its braces, within that type's own body.

    Searched across every part of the type, so a member of a partial class is found wherever
    that class was written.

    A declaration, never a call. The pattern insists on a return type - one token with no
    space in it - immediately before the name, because a pattern that allowed spaces there
    matched the indentation of `BuildFooter();` and handed back the body of whatever method
    was calling it.
    """
    pattern = re.compile(r"(?m)^[ \t]*(?:(?:%s)[ \t]+)*[\w<>,\[\]\.\?]+[ \t]+%s[ \t]*[\(\{]"
                         % ("|".join(MODIFIERS), re.escape(member)))
    for body in parts_of(type_name):
        found = pattern.search(body)
        if found is not None:
            return _block(body, found.start())
    raise ScanError("%s has no member named %s" % (type_name, member))


def types(source: str | None = None) -> list[str]:
    """Every type the window declares, nested ones included, in the order they are written."""
    text = read(source) if source else whole()
    return re.findall(r"(?m)^[ \t]*(?:\w+[ \t]+)*(?:class|struct|enum|interface)[ \t]+(\w+)", text)


def top_level(source: str) -> list[str]:
    """The types one source declares directly inside its namespace, by their indentation.

    What a split moves: a nested type travels with the type around it, and a file's size is
    the sum of these.
    """
    return re.findall(r"(?m)^ {4}(?:\w+ )*(?:class|struct|enum|interface) (\w+)", read(source))
