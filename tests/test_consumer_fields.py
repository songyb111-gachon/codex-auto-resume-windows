"""Every field the window and the panel read from the wire, held to the wire goldens.

The Settings window (`gui/*.cs`) and the Codex panel (the script `mcpui` serves) read the bridge's
and the MCP server's answers by field name, and nothing but the name connects the two sides: the
C# is compiled separately, and the panel's script is a string. A renamed field therefore passes
every Python test that reads it back through the renamed code, and the window draws a blank. So
every name either front end reads is found here, and must be a key of the answer it is read from,
as `tests/golden` records that answer (`tests/wiregolden.py` makes them, from the code as it was
before v0.6.5 moved anything).

How a read is found:

* the window: `Str`, `Get`, `Map`, `Items` or `Number(<receiver>, "<name>")` - the accessors every
  read of a reply goes through - and `<receiver>["<name>"]`, `.TryGetValue("<name>"` and
  `.ContainsKey("<name>"` on a receiver that holds a reply. A receiver is a variable, whose shape
  RECEIVERS says, or a read itself (`Map(view, "data")`), which is followed. A name built at run
  time checks its literal prefix (`"custom_message_" + category`); `c ? "a" : "b"` checks both.
* the panel: `payload.<name>`, `row.<name>`, `DATA.<name>`, `status.<name>`, `view.<name>` and
  `preview.<name>`, followed along a chain (`DATA.status.enabled`), in the served script with its
  strings, comments and regular expressions blanked out. A name that is called (`.forEach(`) or
  read off something that is not an object here (`.length`) is JavaScript's, not the wire's.

Which reply a `reply`, `result` or `payload` is depends on what was asked, so it is narrowed by
the requests the enclosing C# method or top-level script function makes itself - a method that
calls `Call("stop-watcher")` reads `result` from stop-watcher's reply - and is every reply when it
makes none (a helper handed a reply from elsewhere).

A read of a receiver this file does not know fails, and so does a read by a name computed from
nothing literal: each has to be placed on purpose, in RECEIVERS, LOCAL or UNCHECKED. A read whose
name no golden answer carries is drift: it fails unless KNOWN_DRIFT names it with its decision,
and KNOWN_DRIFT may not name one that has gone.

Step 4 gives each wire shape a TypedDict; TYPED then names it, and each read is held to its keys
too.
"""
from __future__ import annotations

from collections import namedtuple
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import guiscan  # noqa: E402
GOLDEN = ROOT / "tests" / "golden"
GUI = ROOT / "gui"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# One read: which front end, where, of what, along which keys, and by which name(s).
Read = namedtuple("Read", "file receiver path names kind scope line")

# "@" is the requests the enclosing method or function makes (every reply when it makes none).
ROW = [("bridge:pending", "pending[]"), ("bridge:pending-all", "pending[]"),
       ("bridge:history", "history[]"), ("bridge:dashboard", "pending[]"),
       ("bridge:dashboard", "history[]")]
COMPAT_VIEW = [("bridge:compatibility", "compatibility"),
               ("bridge:compat-refresh", "result.compatibility")]
SETTINGS = [("bridge:settings", "settings"), ("bridge:update", "settings"),
            ("bridge:defaults", "settings"), ("bridge:status", "status.settings")]
# Any request may be refused instead, and a refusal has one shape whatever was asked
# (`controlcli._rejected`): the `serve` loop's own refusals are that shape.
REFUSAL = ("bridge:_framing", "cases[].replies[].reply")
PANEL_ROW = [("mcp:list_pending", "pending[]"), ("mcp:open_settings", "pending[]")]


def _under(shape, suffix):
    return [(source, path + suffix) for source, path in shape]


_RECEIVERS = {
    "gui/Dashboard.cs": {
        "reply": [("@", ""), REFUSAL],
        "result": [("@", "result")],
        # The `serve` loop's line around every reply.
        "envelope": [("bridge:_framing", "cases[].replies[]")],
        "snapshot": [("bridge:dashboard", "")],
        "status": [("bridge:status", "status"), ("bridge:dashboard", "status")],
        "watcher": [("bridge:status", "status.watcher"), ("bridge:dashboard", "status.watcher")],
        # A pending or history row, however it was reached: the list's own, the one chosen, the
        # one a list item carries in its Tag, the fresh list compared with the shown one.
        "row": ROW, "chosen": ROW, "fresh": ROW, "Tag": ROW,
        "gates": _under(ROW, ".gates"),
        "item": [("bridge:timeline", "result.events[]")],
        "view": COMPAT_VIEW, "live": COMPAT_VIEW, "report": COMPAT_VIEW, "compatLive": COMPAT_VIEW,
        "engine": _under(COMPAT_VIEW, ".engine"),
        "data": _under(COMPAT_VIEW, ".data"),
        "capabilities": _under(COMPAT_VIEW, ".capabilities"),
        "entry": _under(COMPAT_VIEW, ".capabilities.*"),
        # v0.6.10: what others report, beside the version (the bridge's only; never the MCP summary).
        "reported": _under(COMPAT_VIEW, ".reported"),
        "week": [("bridge:dashboard", "week")],
        "stats": [("bridge:statistics", "result"), ("bridge:dashboard", "week")],
        "outcomes": [("bridge:statistics", "result.outcomes"), ("bridge:dashboard", "week.outcomes")],
    },
    "gui/SettingsApp.cs": {
        "reply": [("@", ""), REFUSAL],
        "result": [("@", "result")],
        "response": [("bridge:start-watcher", ""), REFUSAL],
        "described": [("bridge:describe", "")],
        "settings": [("bridge:settings", "")],
        "updated": [("bridge:update", "")],
        "status": [("bridge:status", "status")],
        "current": SETTINGS,
        # The settings file on disk, whose names are the stored settings'.
        "map": SETTINGS,
        "field": [("bridge:describe", "schema[]")],
        "styleField": [("bridge:describe", "schema[]")],
        # The schema by field name, as BuildEditors indexes it.
        "fields": [("bridge:describe", "schema{name}")],
        # The Save request, built by setting name: each must be a setting the bridge stores.
        "jsonValues": SETTINGS,
        # LayoutAudit's input: a dashboard reply, with the compatibility reply's view beside it.
        "snapshot": [("bridge:dashboard", ""), ("bridge:compatibility", "")],
    },
    "gui/SoftTheme.cs": {
        # Theme.Stored reads the settings file for the theme before the window has a bridge.
        "map": SETTINGS,
    },
    "panel": {
        "payload": [("@", "")],
        "row": PANEL_ROW,
        "DATA": [("mcp:open_settings", "")],
        "status": [("mcp:get_status", ""), ("mcp:open_settings", "status")],
        "view": [("mcp:get_status", "watcher.compatibility"),
                 ("mcp:open_settings", "status.watcher.compatibility")],
        "preview": [("mcp:preview_recovery_message", "preview")],
    },
}

# Dictionaries the window indexes that hold no reply: its own pages, editors and sections, the
# brand's motion table, a process's environment, the strings cache's entries, a reply copy it is
# writing into.
_LOCAL = {
    "gui/Dashboard.cs": {"pages", "EnvironmentVariables", "map"},
    "gui/SettingsApp.cs": {"pages", "editors", "sections", "entry", "empty", "baseline"},
    "gui/SoftTheme.cs": {"MOTION"},
}

# The window was two files until v0.6.10-alpha, when each became several. The three tables above
# are keyed by file, and a read in `gui/DashboardPages.cs` is the read it was in
# `gui/Dashboard.cs` - so each file is named as the half it came out of, and each table is
# expanded over it. The distinction that matters is kept: the Dashboard and the Settings page
# read different shapes. `UNCHECKED` and `KNOWN_DRIFT` below are keyed by the exact read
# instead, so each of those names the file its read is in.
HALVES = {
    "gui/SettingsApp.cs": tuple(name for name in guiscan.group("settings")
                                if name != "gui/SettingsApp.cs"),
    "gui/Dashboard.cs": tuple(name for name in guiscan.group("dashboard")
                              if name != "gui/Dashboard.cs"),
}


def _spread(table):
    """One entry per file, from an entry per half."""
    spread = dict(table)
    for half, names in HALVES.items():
        for name in names:
            if half in table:
                spread[name] = table[half]
    return spread


RECEIVERS = _spread(_RECEIVERS)
LOCAL = _spread(_LOCAL)

# Reads by a name computed from nothing literal, which no golden can check, each with its reason.
UNCHECKED = {
    ("gui/DashboardData.cs", "map", "key"): "the accessor helpers themselves (Number, Str, Items, Map)",
    ("gui/DashboardCompat.cs", "capabilities", "name"): "each capability the report carries, in the "
                                                   "order the window lists them",
    ("gui/DashboardActions.cs", "gates", "name"): "each gate, in GateOrder, which "
                                            "tests/test_gui_decisions.py holds to machine.GATES",
    ("gui/SettingsPage.cs", "current", "name"): "each field the schema names, read back by that name",
}

# Dictionaries the window writes a request into, by setting name: a name written there is one the
# bridge must store, or the whole Save is refused as an unknown setting.
_REQUESTS = {"gui/SettingsApp.cs": {"jsonValues"}}
REQUESTS = _spread(_REQUESTS)

# Names a front end reads that no golden answer carries, each with what was decided about it:
# (file, method or function, receiver, the keys and name read) -> the decision.
KNOWN_DRIFT = {
    ("gui/DashboardMaintenance.cs", "AfterUpdate", "reply", "result"):
        "status answers under `status`, never `result`; the next line falls back to `status`, so the "
        "read costs a lookup and nothing else. Kept: phase B changes no C#; the window's next change "
        "can drop it",
    ("gui/DashboardData.cs", "UpdateCountdowns", "snapshot", "pending_error"):
        "carried only when the dashboard's Pending part fails (dispatch writes `<part>_error` beside "
        "the parts that did not); no golden fails a part on purpose, and tests/test_control.py's "
        "test_a_dashboard_part_that_fails_costs_only_that_part pins that shape",
}

# The typed contracts (control/wire.py, v0.6.10-alpha), by the receiver they type. Every name a
# receiver here is read by has to be a key of its contract; tests/test_wire_types.py holds each
# contract to the goldens the other way. A receiver whose shape has no contract - a whole reply,
# the settings map, which the schema types instead - is simply not listed.
from codex_auto_resume.control import wire  # noqa: E402

_ROW, _COMPAT = wire.PendingRow, wire.CompatView
_TYPED = {
    "gui/Dashboard.cs": {
        "row": _ROW, "chosen": _ROW, "fresh": _ROW, "Tag": _ROW,
        "item": wire.TimelineEvent,
        "status": wire.StatusSnapshot, "watcher": wire.WatcherView,
        "view": _COMPAT, "live": _COMPAT, "report": _COMPAT, "compatLive": _COMPAT,
        "engine": wire.CompatEngine, "data": wire.CompatData, "entry": wire.CompatCapability,
        "reported": wire.CompatReported,
        "week": wire.Statistics, "stats": wire.Statistics, "outcomes": wire.Outcomes,
    },
    "gui/SettingsApp.cs": {
        "status": wire.StatusSnapshot,
        "field": wire.SchemaField, "styleField": wire.SchemaField,
    },
}
TYPED = {(name, receiver): contract for name, table in _spread(_TYPED).items()
         for receiver, contract in table.items()}


# ------------------------------------------------------------------------------ the goldens
def _golden(name):
    path = GOLDEN / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def roots(source: str) -> list:
    """Every answer `source` names: `bridge:<command>` (each case's reply; for `_framing` the file
    itself, whose reply lines are at `cases[].replies[]`) or `mcp:<tool>` (each case's
    structuredContent); `*` for the command or tool is all of them."""
    kind, _, name = source.partition(":")
    if kind == "bridge":
        if name == "*":
            return [reply for path in sorted((GOLDEN / "bridge").glob("*.json")) if path.stem != "_framing"
                    for reply in roots("bridge:" + path.stem)]
        document = _golden("bridge/%s.json" % name)
        if document is None:
            return []
        if name == "_framing":
            return [document]
        return [case["reply"] for case in document["cases"]]
    if kind == "mcp":
        if name == "*":
            return [content for path in sorted((GOLDEN / "mcp").glob("*.json")) if not path.stem.startswith("_")
                    for content in roots("mcp:" + path.stem)]
        document = _golden("mcp/%s.json" % name)
        if document is None:
            return []
        responses = [case["response"] for case in document.get("cases", [])]
        return [response["result"]["structuredContent"] for response in responses
                if isinstance(response.get("result"), dict) and "structuredContent" in response["result"]]
    raise ValueError(source)


def follow(values, path: str) -> list:
    """The values at `path` below each of `values`: keys by dots, `[]` a list's items, `*` an
    object's values, `{name}` a list of objects keyed by their `name`."""
    for step in re.findall(r"[^.\[\]{}]+|\[\]|\{[a-z_]+\}", path):
        if step == "[]":
            values = [item for value in values if isinstance(value, list) for item in value]
        elif step == "*":
            values = [item for value in values if isinstance(value, dict) for item in value.values()]
        elif step.startswith("{"):
            field = step[1:-1]
            values = [{entry[field]: entry for entry in value if isinstance(entry, dict) and field in entry}
                      for value in values if isinstance(value, list)]
        else:
            values = [value[step] for value in values if isinstance(value, dict) and step in value]
    return values


# ------------------------------------------------------------------------------- the window
ACCESSOR = re.compile(r"\b(Str|Get|Map|Items|Number)\(")
INDEXED = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?:\[\"([^\"]*)\"\]|\.(TryGetValue|ContainsKey)\(\"([^\"]*)\")")
MEMBER = re.compile(r"^ {8}(?:(?:private|public|internal|protected|static|override|virtual|sealed|readonly"
                    r"|async|unsafe|new|extern)\s+)+[^=;(]*?\b(\w+)\s*\(", re.M)
ASKED = re.compile(r"\b(?:Call|CallAsync|CallOnce|Send)\(\"([a-z-]+)\"")


def _arguments(text: str, start: int):
    """The top-level arguments of the call whose `(` ends just before `start`."""
    depth, index, parts, begun, quote = 0, start, [], start, None
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                parts.append(text[begun:index])
                return [part.strip() for part in parts]
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[begun:index])
            begun = index + 1
        index += 1
    return None


def _names(expression: str):
    """(names, kind) for the name argument of a read."""
    literal = re.fullmatch(r'"([^"]*)"', expression)
    if literal:
        return (literal.group(1),), "exact"
    prefix = re.fullmatch(r'"([^"]+)"\s*\+.*', expression, re.S)
    if prefix:
        return (prefix.group(1),), "prefix"
    choice = re.fullmatch(r'[^?]*\?\s*"([^"]*)"\s*:\s*"([^"]*)"', expression, re.S)
    if choice:
        return (choice.group(1), choice.group(2)), "exact"
    return (expression,), "dynamic"


def _receiver(expression: str):
    """(variable, keys) for a receiver: a variable, or a read of one, whose keys are followed."""
    expression = re.sub(r"^\((?:Dictionary<string, object>|List<object>)\)\s*", "", expression.strip())
    expression = re.sub(r"\s+as\s+(?:Dictionary<string, object>|List<object>)$", "", expression)
    nested = ACCESSOR.match(expression)
    if nested:
        arguments = _arguments(expression, nested.end())
        if arguments and len(arguments) == 2:
            inner, keys = _receiver(arguments[0])
            names, kind = _names(arguments[1])
            if inner is not None and kind == "exact" and len(names) == 1:
                return inner, keys + (names[0],)
        return None, ()
    plain = re.sub(r"\[[^\]]*\]", "", expression)
    if re.fullmatch(r"[A-Za-z_][\w.]*", plain):
        return plain.split(".")[-1], ()
    return None, ()


def _members(text: str):
    return [(match.start(), match.group(1)) for match in MEMBER.finditer(text)]


def _scope(members, text, offset):
    """(member name, the bridge commands it asks) for the member holding `offset`."""
    name, start, end = None, 0, len(text)
    for index, (begun, member) in enumerate(members):
        if begun > offset:
            end = begun
            break
        name, start = member, begun
    return name, tuple(sorted(set(ASKED.findall(text[start:end]))))


def window_reads():
    reads = []
    for path in sorted(GUI.glob("*.cs")):
        name = "gui/" + path.name
        text = path.read_text(encoding="utf-8")
        members = _members(text)
        line = lambda offset: text.count("\n", 0, offset) + 1  # noqa: E731
        for match in ACCESSOR.finditer(text):
            arguments = _arguments(text, match.end())
            if not arguments or len(arguments) != 2 or arguments[0].startswith("Dictionary<"):
                continue                                     # not a read: another Get, or a definition
            receiver, keys = _receiver(arguments[0])
            names, kind = _names(arguments[1])
            reads.append(Read(name, receiver or arguments[0], keys, names, kind,
                              _scope(members, text, match.start()), line(match.start())))
        for match in INDEXED.finditer(text):
            receiver, indexed, method, called = match.groups()
            after = text[match.end():match.end() + 3]
            if (indexed is not None and re.match(r"\s*=(?!=)", after)
                    and receiver not in REQUESTS.get(name, set())):
                continue                                     # a write into a dictionary
            reads.append(Read(name, receiver, (), (indexed if indexed is not None else called,), "exact",
                              _scope(members, text, match.start()), line(match.start())))
    return reads


# -------------------------------------------------------------------------------- the panel
PANEL_RECEIVERS = ("payload", "row", "DATA", "status", "view", "preview")
CHAIN = re.compile(r"(?<![\w$.])(%s)((?:\.[A-Za-z_$][\w$]*)+)(\s*\()?" % "|".join(PANEL_RECEIVERS))
FUNCTION = re.compile(r"^function\s+([\w$]+)\s*\(", re.M)


def panel_script() -> str:
    """The panel's own script, as `mcpui.settings_page` serves it: the one script that is not data."""
    from codex_auto_resume.mcp import panel as mcpui

    page = mcpui.settings_page()
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    code = [script for script in scripts if not script.lstrip().startswith("window.__CODEX_AUTO_RESUME")]
    if len(code) != 1:
        raise AssertionError("expected one script beside the data the page carries, found %d" % len(code))
    return code[0]


def strip_js(text: str) -> str:
    """`text` with every string, template, comment and regular expression blanked to spaces, so
    what is left is code; line breaks and offsets are kept."""
    out = list(text)
    index, length = 0, len(text)
    last = ""                                            # the last significant code character

    def blank(start, end):
        for position in range(start, end):
            if out[position] != "\n":
                out[position] = " "

    while index < length:
        char = text[index]
        pair = text[index:index + 2]
        if pair == "//":
            end = text.find("\n", index)
            end = length if end < 0 else end
            blank(index, end)
            index = end
            continue
        if pair == "/*":
            end = text.find("*/", index + 2)
            end = length if end < 0 else end + 2
            blank(index, end)
            index = end
            continue
        if char in "'\"`":
            end = index + 1
            while end < length and text[end] != char:
                end += 2 if text[end] == "\\" else 1
            blank(index + 1, min(end, length))
            index = end + 1
            last = char
            continue
        if char == "/" and (last == "" or last in "(,=:[!&|?{};+-*%<>~^"):
            end, in_class = index + 1, False
            while end < length and text[end] != "\n":
                if text[end] == "\\":
                    end += 2
                    continue
                if text[end] == "[":
                    in_class = True
                elif text[end] == "]":
                    in_class = False
                elif text[end] == "/" and not in_class:
                    break
                end += 1
            blank(index + 1, end)
            index = end + 1
            last = "/"
            continue
        if not char.isspace():
            last = char
        index += 1
    return "".join(out)


def panel_reads(code=None):
    """The panel's reads: each step of each chain, with the tools its function asks for."""
    from codex_auto_resume import mcpserver

    script = panel_script()
    code = strip_js(script) if code is None else code
    tools = {tool["name"] for tool in mcpserver.TOOLS}
    starts = [(match.start(), match.group(1)) for match in FUNCTION.finditer(code)]
    spans = {name: (begun, starts[index + 1][0] if index + 1 < len(starts) else len(code))
             for index, (begun, name) in enumerate(starts)}
    # The tools each function names (they are strings, so they are read from the script as
    # served), and then the tools of every function it calls, so a `payload` read in a handler
    # of `saveSettings(...)` is update_settings' although the handler never names the tool.
    named = {name: {tool for tool in tools
                    if re.search(r"['\"]%s['\"]" % re.escape(tool), script[begun:end])}
             for name, (begun, end) in spans.items()}
    calls = {name: {other for other in spans if other != name
                    and re.search(r"(?<![\w$.])%s\s*\(" % re.escape(other), code[begun:end])}
             for name, (begun, end) in spans.items()}
    asks = {}
    for name in spans:
        seen, todo = set(), [name]
        while todo:
            current = todo.pop()
            if current not in seen:
                seen.add(current)
                todo.extend(calls[current])
        asks[name] = tuple(sorted(set().union(*(named[each] for each in seen))))
    reads = []
    for match in CHAIN.finditer(code):
        receiver, chain, called = match.groups()
        steps = chain.split(".")[1:]
        if called:
            steps = steps[:-1]                           # a method, not a field
        name = None
        for begun, function in starts:
            if begun > match.start():
                break
            name = function
        line = code.count("\n", 0, match.start()) + 1
        for depth, step in enumerate(steps):
            reads.append(Read("panel", receiver, tuple(steps[:depth]), (step,), "exact",
                              (name, asks.get(name, ())), line))
    return reads


# ------------------------------------------------------------------------------- the check
def _sources(read):
    shape = RECEIVERS.get(read.file, {}).get(read.receiver)
    if shape is None:
        return None
    _member, asked = read.scope
    resolved = []
    for source, path in shape:
        if source == "@":
            if read.file == "panel":
                asked_sources = ["mcp:" + tool for tool in asked] or ["mcp:*"]
            else:
                asked_sources = ["bridge:" + command for command in asked] or ["bridge:*"]
            resolved += [(each, path) for each in asked_sources]
        else:
            resolved.append((source, path))
    return resolved


def values_for(read) -> list:
    values = []
    for source, path in _sources(read) or []:
        values += follow(roots(source), path)
    for key in read.path:
        values = [value[key] for value in values if isinstance(value, dict) and key in value]
    return values


def carried(read, values) -> bool | None:
    """Whether the answers carry the read's name: True, False, or None when it is not a field
    read here (the value it is read off is a list or a string, so the name is JavaScript's)."""
    objects = [value for value in values if isinstance(value, dict)]
    if not objects:
        return None if values else False
    for name in read.names:
        if read.kind == "prefix":
            if any(key.startswith(name) and key != name for value in objects for key in value):
                continue
            return False
        if not any(name in value for value in objects):
            return False
    return True


def drift_key(read):
    """(file, the method or function it is in, receiver, the keys and name read)."""
    return (read.file, read.scope[0], read.receiver, ".".join(read.path + (read.names[0],)))


class ReadsAreFoundTests(unittest.TestCase):
    """The scanners find the reads this file is about, so the audit below is not an audit of nothing."""

    def test_the_window_reads_are_found(self):
        # By the half rather than the file: each of the two became several in v0.6.10-alpha, and
        # which of them a read ended up in is not what this is about.
        half = {name: name for name in HALVES}
        half.update({name: whole for whole, names in HALVES.items() for name in names})
        found = {(half.get(read.file, read.file), read.receiver, ".".join(read.path + read.names))
                 for read in window_reads()}
        for expected in (("gui/Dashboard.cs", "row", "interruption_id"),
                         ("gui/Dashboard.cs", "watcher", "last_tick_at"),
                         ("gui/Dashboard.cs", "reply", "result.answer"),
                         ("gui/Dashboard.cs", "view", "data.cache_sequence"),
                         ("gui/SettingsApp.cs", "result", "refusal_code"),
                         ("gui/SettingsApp.cs", "field", "choices"),
                         ("gui/SettingsApp.cs", "status", "watcher_running"),
                         ("gui/Dashboard.cs", "envelope", "reply")):
            self.assertIn(expected, found)
        self.assertGreater(len(found), 100)

    def test_the_panel_reads_are_found(self):
        found = {(read.receiver, ".".join(read.path + read.names)) for read in panel_reads()}
        for expected in (("payload", "settings"), ("payload", "error_code"), ("row", "thread_enabled"),
                         ("DATA", "status.enabled"), ("view", "capabilities"), ("preview", "text")):
            self.assertIn(expected, found)

    def test_the_script_is_read_as_code(self):
        code = strip_js("var a = 'payload.nope'; // row.nope\nvar b = /row\\.x/.test(c) ? row.name : \"x\";\n"
                        "/* DATA.nope */ var d = payload.settings.theme; e = f / 2; g = row.state;")
        found = {(read.receiver, ".".join(read.path + read.names)) for read in panel_reads(code)}
        self.assertEqual(found, {("row", "name"), ("payload", "settings"), ("payload", "settings.theme"),
                                 ("row", "state")})

    def test_a_read_is_narrowed_to_what_its_method_asks(self):
        read = next(read for read in window_reads()
                    if read.file in ("gui/Dashboard.cs",) + HALVES["gui/Dashboard.cs"] and read.receiver == "reply"
                    and read.path == ("result",) and read.names == ("state",))
        self.assertEqual(read.scope[1], ("stop-watcher",))
        # A helper handed a reply asks nothing itself, and is held to every reply.
        read = next(read for read in window_reads()
                    if read.file in ("gui/Dashboard.cs",) + HALVES["gui/Dashboard.cs"] and read.receiver == "reply"
                    and read.path == ("result",) and read.names == ("answer",))
        self.assertEqual(read.scope[1], ())
        # A script function is held to what the functions it calls ask too.
        read = next(read for read in panel_reads()
                    if read.receiver == "payload" and read.names == ("settings",)
                    and read.scope[0] == "saveSettings")
        self.assertEqual(read.scope[1], ("update_settings",))

    def test_a_request_the_window_builds_is_read_as_its_names(self):
        written = {read.names[0] for read in window_reads()
                   if read.file in ("gui/SettingsApp.cs",) + HALVES["gui/SettingsApp.cs"]
                   and read.receiver == "jsonValues"}
        self.assertIn("continuation_style", written)


class ConsumerFieldTests(unittest.TestCase):
    # A failure lists reads by where they are; all of them, not the first 640 characters.
    maxDiff = None

    def setUp(self):
        for directory in ("bridge", "mcp"):
            if not any((GOLDEN / directory).glob("*.json")):
                self.fail("tests/golden/%s is empty; run python -X utf8 tests/wiregolden.py --write" % directory)
        self.reads = window_reads() + panel_reads()

    def test_every_receiver_is_placed(self):
        unplaced = sorted({"%s: %s (line %d)" % (read.file, read.receiver, read.line) for read in self.reads
                           if read.receiver not in RECEIVERS.get(read.file, {})
                           and read.receiver not in LOCAL.get(read.file, set())})
        self.assertEqual(unplaced, [], "say what each of these holds, in RECEIVERS or LOCAL")

    def test_every_computed_name_is_accounted_for(self):
        computed = {(read.file, read.receiver, read.names[0]) for read in self.reads if read.kind == "dynamic"}
        self.assertEqual(sorted(computed - set(UNCHECKED)), [],
                         "a read by a computed name: make the name literal, or say in UNCHECKED why not")
        self.assertEqual(sorted(set(UNCHECKED) - computed), [], "no longer read that way; take it off UNCHECKED")

    def test_every_field_read_is_one_the_wire_carries(self):
        drift = {}
        for read in self.reads:
            if read.kind == "dynamic" or read.receiver not in RECEIVERS.get(read.file, {}):
                continue
            if carried(read, values_for(read)) is False:
                drift.setdefault(drift_key(read), read)
        new = {key: "line %d, asked %s" % (read.line, ", ".join(read.scope[1]) or "anything")
               for key, read in drift.items() if key not in KNOWN_DRIFT}
        self.assertEqual(new, {}, "read by a front end, carried by no golden answer: a renamed or lost "
                                  "field, or new drift to decide on in KNOWN_DRIFT")
        self.assertEqual(sorted(set(KNOWN_DRIFT) - set(drift)), [],
                         "carried now, or no longer read; take it off KNOWN_DRIFT")

    def test_each_read_is_a_key_of_its_typed_contract(self):
        if not TYPED:
            self.skipTest("the typed contracts are step 4's; TYPED names them when they land")
        missing = []
        for read in self.reads:
            contract = TYPED.get((read.file, read.receiver))
            if contract is not None and not read.path and read.kind == "exact":
                missing += ["%s %s.%s" % (read.file, read.receiver, name) for name in read.names
                            if name not in getattr(contract, "__annotations__", {})]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
