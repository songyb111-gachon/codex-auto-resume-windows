"""The MCP server and the settings panel (seat S5.2, car-control `mcp/`): the same JSON-RPC streams through the
reference tag's `mcpserver.Server` and through car-control's `mcp::Server` (car-harness `bridge.run`, mode "mcp"), over
the same scratch installation and the same world (bridgeworld's, with actworld's acting stand-ins and the panel's own
answers: Windows' text size, its UI font and which letters a face lacks). Compared byte for byte: the response lines
and the exit code, every file under the workspace, every row of the state, and every call each side made through its
Host seam, in order.

* GoldenMcpDiff  - every case of `wiregolden.MCP_CASES`, `tools/list` and `PROTOCOL_CASES`, each stand-in given as the
                   world (or as files made before the stream); and the Rust responses, canonicalised as wiregolden
                   canonicalises them, are the committed `tests/golden/mcp/*.json` (D12: never regenerated).
* FramingDiff    - the transport: byte order marks, CRLF, a lone CR (also at the 8192-byte chunk boundary), padding,
                   bytes that are not UTF-8 in the first and a later chunk, deep nesting (json's own limit and the
                   batch's), ids of every kind, notifications, batches, envelopes, params and methods of every type.
* ToolsDiff      - every tool over arguments of every shape and kind, the watcher in every state, the statistics'
                   rounding, the administrator's keys, damaged and empty homes, the compatibility view of every kind.
* PanelDiff      - the panel's assets (this crate's copies are the shipped files read with universal newlines and the
                   tag's), `_STYLE`, `_SCRIPT`, `panel_keys()`, `FONT_STACK`, the design and right-to-left rules, the
                   tile elevations, and `settings_page` over themes, designs, text sizes, UI fonts, languages and days;
                   and `resources/read` over the same worlds.

Run by run.py; never by the lanes' discovery.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

from rustdiff import actworld as aw
from rustdiff import bridgeworld as bw
from rustdiff import core, reference
from rustdiff.diffs import RECORD
from rustdiff.diffs_bridge import TEMPLATES
from rustdiff.diffs_bridge_acting import ActingBase, armed, first_difference, now, power_file, write_file

ROOT = core.ROOT
for entry in (ROOT / "tests", ROOT / "build", ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import wiregolden as wg  # noqa: E402

COUNTS = {"streams": 0, "lines": 0, "calls": 0, "goldens": 0, "pages": 0}

# The reference's MCP loop, after actworld.HOOK: the panel's questions of Windows from the world, then
# `mcpserver.main`'s streams and `Server(control).serve()` (the start with Codex is ControlCallDiff's, S5.1b).
MCP_HOOK = r'''
if mode == "mcp":
    from codex_auto_resume import mcpserver as _mcpserver
    from codex_auto_resume.win import textsize as _textsize, typeface as _typeface
    _textsize.read = lambda: world.get("text_size", 1.0)
    _typeface.ui_face = lambda: world.get("ui_face")
    _lacking = world.get("lacks") or {}
    _typeface.lacks = lambda face, text: "".join(c for c in text if c in _lacking.get(face, ""))
    controlcli.use_utf8(sys.stdout)
    controlcli.use_utf8(sys.stdin, newline=None)
    sys.exit(_mcpserver.Server(control.Control(Path(home))).serve())
'''

PANEL_SCRIPT = r'''
import json, sys, time
from pathlib import Path
spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
world = spec["world"]
import os
for name in ("CODEX_AUTO_RESUME_LANG", "LANG", "LC_ALL", "LC_MESSAGES"):
    os.environ.pop(name, None)
os.environ.update(world.get("environ") or {})
from codex_auto_resume import l10n
l10n._windows_preferred = lambda: list(world.get("languages") or [])
from codex_auto_resume.mcp import panel
from codex_auto_resume.win import textsize, typeface
textsize.read = lambda: world.get("text_size", 1.0)
typeface.ui_face = lambda: world.get("ui_face")
lacking = world.get("lacks") or {}
typeface.lacks = lambda face, text: "".join(c for c in text if c in lacking.get(face, ""))
l10n.set_preference(spec.get("preference"))
pages = []
for asked in spec["pages"]:
    kwargs = dict(asked)
    try:
        pages.append(panel.settings_page(**kwargs))
    except Exception as exc:
        pages.append({"raised": type(exc).__name__})
names, prefixes = panel.panel_keys()
tiles = [panel.tile_elevation(theme, design) for theme in ("light", "dark") for design in ("soft", "classic", "plain")]
sys.stdout.write(json.dumps({"style": panel._STYLE, "script": panel._SCRIPT, "names": sorted(names),
                             "prefixes": sorted(prefixes), "font_stack": panel.FONT_STACK, "pages": pages,
                             "tile": tiles, "rules": [panel.design_rules(), panel.right_to_left_rules()]},
                            ensure_ascii=False))
'''


def mcp_lines(*messages) -> bytes:
    out = []
    for message in messages:
        out.append(message if isinstance(message, str) else json.dumps(message))
    return ("\n".join(out) + "\n").encode("utf-8")


def call(name, arguments=None, ident=1) -> dict:
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return {"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": params}


def ask_reference(home: Path, world: dict, stdin: bytes):
    folder = Path(tempfile.mkdtemp(prefix="car-v0627-mcp-spec-"))
    try:
        spec = {"world": world, "mode": "mcp", "home": str(home), "argv": [], "hooks": [aw.HOOK, MCP_HOOK],
                "calls_path": str(folder / "calls.json"), "result_path": str(folder / "result.json"),
                "method": None, "args": []}
        (folder / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        done = reference.run(bw.SCRIPT, folder / "spec.json", profile=home.parent / "profile", stdin=stdin)
        calls = (json.loads((folder / "calls.json").read_text(encoding="utf-8"))
                 if (folder / "calls.json").is_file() else None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return done.returncode, done.stdout, done.stderr, calls


def absent_view() -> dict:
    """What the golden installation's reader view is: no report yet (`compat.report.unusable_view("absent")`)."""
    from codex_auto_resume.compat import report

    return json.loads(json.dumps(report.unusable_view("absent")))


class McpBase(ActingBase):
    def mcp_both(self, kind="acts", *, stream: bytes | callable, world=None, tune=None, label="") -> bytes:
        """One stream on both sides, each on a fresh copy at one path; everything compared. The reference's output."""
        ran = []
        for side in ("reference", "rust"):
            workspace = self.workspace(kind, tune)
            made = world(workspace) if callable(world) else dict(world or {})
            if kind in ("golden", "acts"):
                made.setdefault("now", now())
            asked_world = aw.world_for(workspace, **made)
            asked = stream(workspace) if callable(stream) else stream
            home = workspace / "home"
            if side == "reference":
                code, out, err, calls = ask_reference(home, asked_world, asked)
            else:
                err = b""
                code, out, calls, guard = aw.ask_rust(self.harness, home, asked_world, mode="mcp", stdin=asked)
                self.assertTrue(guard, "the harness must run with CAR_NO_POWER_ACTION set")
            files = {name: data for name, data in bw.files_of(workspace).items() if not name.startswith("profile/")}
            ran.append((code, out, err, files, aw.state_dump(home), calls))
        (code, expected, err, files, state, calls), (code2, actual, _, files2, state2, calls2) = ran
        label = label or "a stream"
        if actual != expected:
            at = next((index for index, (a, b) in enumerate(zip(actual, expected)) if a != b),
                      min(len(actual), len(expected)))
            self.fail("%s: the output differs at byte %d (reference exit %d, rust exit %d; reference stderr %r)\n"
                      "reference: ...%s\nrust:      ...%s" % (
                          label, at, code, code2, err[-600:],
                          expected[max(0, at - 300):at + 300].decode("utf-8", "replace"),
                          actual[max(0, at - 300):at + 300].decode("utf-8", "replace")))
        self.assertEqual(code2, code, "%s: the exit code differs (reference stderr %r)" % (label, err[-600:]))
        for what, mine, theirs in (("the files written", files2, files), ("the state written", state2, state),
                                   ("the Host calls", calls2, calls)):
            if mine != theirs:
                self.fail("%s: %s differ at %s (reference stderr %r)" % (label, what, first_difference(theirs, mine),
                                                                       err[-600:]))
        COUNTS["streams"] += 1
        COUNTS["lines"] += expected.count(b"\n")
        COUNTS["calls"] += len(calls or [])
        return expected


# ------------------------------------------------------------------------------------------ the goldens
def golden_world(case_name: str, tool: str, watching: bool) -> dict:
    """The world a golden case's stand-in (`using`) is, for the MCP cases."""
    world = {"watcher_running": watching, "compat_view": absent_view()}
    if tool == "get_status" and "administrator" in case_name:
        world["managed"] = {"force_observe_only": True, "max_recovery_attempts": 2}
    if tool == "start_watcher" and "job that ends" in case_name:
        world.update(probes=[False], watcher_running=True, launch={"pid": 4242, "polls": [None]},
                     process_context=wg.KILL_ON_CLOSE_JOB)
    if tool == "start_watcher" and "no job" in case_name:
        world.update(probes=[False], watcher_running=True, launch={"pid": 4242, "polls": [None]},
                     process_context=wg.NO_JOB)
    if tool == "start_watcher" and "install lock" in case_name:
        world["install_in_progress"] = True
    return world


def golden_tune(case_name: str, tool: str):
    """What a golden case's stand-in writes before its request, through the worktree's own code as wiregolden's."""
    if tool == "release_hold" and case_name.startswith("a held recovery"):
        def held(workspace):
            from codex_auto_resume import config
            from codex_auto_resume.store import Store

            with Store(config.Paths(workspace / "home").state_dir) as store:
                store.set_thread_tier(wg.T1, "ask_first", now(), actor="gui")
        return held
    if tool == "turn_off_power_action" and case_name.startswith("armed"):
        # The Dashboard's arming as power-action.json holds it, under a fixed nonce (S5.1b's helper).
        return power_file(armed())
    if tool == "start_watcher" and not case_name.startswith("a watcher already"):
        # An installation whose stable launcher is there, as the golden's checkout has its entry script.
        return write_file("home/watcher-launcher.py", "# the stable launcher\n")
    return None


def golden_streams(tool: str):
    """(cases, world, tune) streams, in the golden's order: the cases of a group that share one world in one stream."""
    streams = []
    for case in wg.MCP_CASES[tool]:
        world = golden_world(case.name, tool, case.watching)
        tune = golden_tune(case.name, tool)
        if streams and streams[-1][1] == world and tune is None and not _alone(tool, case.name):
            streams[-1][0].append(case)
        else:
            streams.append(([case], world, tune))
    return streams


def _alone(tool, case_name) -> bool:
    # A case whose stand-in in wiregolden is a fresh context of its own, on an installation no earlier case changed.
    return tool in ("turn_off_power_action", "start_watcher", "get_status")


def rewriting(workspace: Path, version: str) -> list:
    """wiregolden's rewriting: the pinned directories, and the version - the tag's, which the world says, and this
    checkout's, which the golden installation's heartbeat was written with - as `<version>`."""
    import make_screenshots as generator
    from codex_auto_resume import config

    spelled = generator.workspace_spellings(workspace)
    for each in sorted({version, config.version()}, key=len, reverse=True):
        marker = re.compile(r"(?<![0-9.])" + re.escape(each) + r"(?!\.?[0-9])")
        spelled.append((marker, "<version>"))
    return spelled


class GoldenMcpDiff(McpBase):
    def _check(self, name: str, made: str):
        recorded = wg.recorded("mcp/%s.json" % name)
        self.assertIsNotNone(recorded, name)
        if made != recorded:
            at = next((index for index, (a, b) in enumerate(zip(made, recorded)) if a != b),
                      min(len(made), len(recorded)))
            self.fail("mcp/%s.json: Rust's document differs from the golden at character %d\ngolden: ...%s\nrust:   ...%s"
                      % (name, at, recorded[max(0, at - 300):at + 300], made[max(0, at - 300):at + 300]))
        COUNTS["goldens"] += 1

    def test_every_tool(self):
        version = bw.tag_version()
        for tool in sorted(wg.MCP_CASES):
            with self.subTest(tool):
                cases = []
                for group, world, tune in golden_streams(tool):
                    messages = [call(tool, case.value(None), ident=1) for case in group]
                    # Each case is its own request with id 1, as wiregolden asks it.
                    stream = mcp_lines(*messages)
                    out = self.mcp_both(stream=stream, world=world, tune=tune, label="%s: %s" % (tool, group[0].name))
                    lines = out.decode("utf-8").split("\n")[:-1]
                    self.assertEqual(len(lines), len(group), "%s: one response per case" % tool)
                    spelled = rewriting(self.scratch / "ws", version)
                    for case, line in zip(group, lines):
                        cases.append({"case": case.name, "arguments": wg.canonical(case.value(None), spelled),
                                      "response": wg.canonical(json.loads(line), spelled)})
                self._check(tool, wg._render({"tool": tool, "cases": cases}))
        RECORD.append("MCP goldens: %d tool files equal to the reference and to tests/golden/mcp" % len(wg.MCP_CASES))

    def test_tool_list_and_protocol(self):
        version = bw.tag_version()
        world = {"watcher_running": True, "compat_view": absent_view()}
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        out = self.mcp_both(stream=mcp_lines(request), world=world, label="tools/list")
        spelled = rewriting(self.scratch / "ws", version)
        self._check(wg.MCP_TOOL_LIST, wg._render({"method": "tools/list", "request": request,
                                                  "response": wg.canonical(json.loads(out), spelled)}))
        cases = []
        for name, message in wg.PROTOCOL_CASES:
            out = self.mcp_both(stream=mcp_lines(message), world=world, label="protocol: " + name)
            spelled = rewriting(self.scratch / "ws", version)
            responses = [json.loads(line) for line in out.decode("utf-8").split("\n")[:-1]]
            cases.append({"case": name, "request": message, "responses": wg.canonical(responses, spelled)})
        self._check(wg.MCP_PROTOCOL, wg._render({"cases": cases}))
        RECORD.append("MCP goldens: tools-list.json and _protocol.json (%d cases) equal" % len(wg.PROTOCOL_CASES))


# ------------------------------------------------------------------------------------------ the transport
PING = {"jsonrpc": "2.0", "id": 7, "method": "ping"}


def deep_batch(depth: int) -> str:
    return "[" * depth + json.dumps(PING) + "]" * depth


class FramingDiff(McpBase):
    def test_streams(self):
        ping = json.dumps(PING).encode("utf-8")
        filler = mcp_lines(*[dict(PING, id=index) for index in range(1, 80)])
        cases = {
            "an empty stream": b"",
            "blank lines only": b"\n \n\t\n\r\n",
            "no final newline": ping,
            "CRLF": ping + b"\r\n" + ping + b"\r\n",
            "a lone CR between two": ping + b"\r" + ping + b"\n",
            "a lone CR at the end": ping + b"\r",
            "a CR at the first chunk's end, LF after it": filler + b" " * (8191 - len(filler) - len(ping)) + ping
            + b"\r\n" + ping + b"\n",
            "a CR at the first chunk's end, a bad byte after it": filler + b" " * (8191 - len(filler) - len(ping))
            + ping + b"\r\xff\n",
            "a byte order mark first": b"\xef\xbb\xbf" + ping + b"\n",
            "two byte order marks": b"\xef\xbb\xbf\xef\xbb\xbf" + ping + b"\n",
            "a byte order mark on a later line": ping + b"\n\xef\xbb\xbf" + ping + b"\n",
            "padded with Unicode spaces and file separators": b"\x1c\x1f \xc2\xa0" + ping + b"\xe3\x80\x80\x85\n",
            "a bad byte first": b"\xff" + ping + b"\n",
            "a bad byte after a good line": ping + b"\n\xff\n",
            "a bad byte in the second chunk": filler + b" " * (9000 - len(filler)) + b"\n\xc3\x28\n",
            "a cut character at the end": ping + b"\n\xe3\x81",
            "not JSON": b"{not json\n" + ping + b"\n",
            "NaN, Infinity and a trailing comma": b'{"jsonrpc": "2.0", "id": NaN, "method": "ping"}\n'
            b'{"jsonrpc": "2.0", "id": Infinity, "method": "ping"}\n{"jsonrpc": "2.0", "id": 1, "method": "ping",}\n',
            "json's own nesting limit": ("[" * 100000).encode("ascii") + b"\n" + ping + b"\n",
            "nesting of 200 around an object": mcp_lines(deep_batch(200)),
            "a duplicate id": b'{"jsonrpc": "2.0", "id": 1, "id": 2, "method": "ping"}\n',
            "a duplicate method": b'{"jsonrpc": "2.0", "id": 1, "method": "tools/run", "method": "ping"}\n',
        }
        for depth in (980, 990, 993, 994, 995, 996, 1000):
            cases["a batch nested %d deep" % depth] = mcp_lines(deep_batch(depth), PING)
        ids = ['1', '-1', '0', '1.5', '-0.0', '1e308', '1e400', 'true', 'false', 'null', '"x"', '"\\ud800"',
               '"\\ud83d\\ude00"', '[1]', '{"a": 1}', '123456789012345678901234567890', '9' * 5000, '""']
        for ident in ids:
            cases["the id %s" % ident[:40]] = ('{"jsonrpc": "2.0", "id": %s, "method": "ping"}\n' % ident).encode()
            cases["a refused envelope with the id %s" % ident[:40]] = (
                '{"jsonrpc": "1.0", "id": %s, "method": "ping"}\n' % ident).encode()
            cases["an unknown method with the id %s" % ident[:40]] = (
                '{"jsonrpc": "2.0", "id": %s, "method": "nope"}\n' % ident).encode()
        envelopes = [
            {"id": 1, "method": "ping"}, {"jsonrpc": 2.0, "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 1}, {"jsonrpc": "2.0", "id": 1, "method": 5},
            {"jsonrpc": "2.0", "id": 1, "method": None}, {"jsonrpc": "2.0", "id": 1, "method": ["ping"]},
            {"jsonrpc": "2.0", "method": "ping"}, {"jsonrpc": "2.0", "method": "tools/call"},
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": None},
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []},
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": "x"},
            {"jsonrpc": "2.0", "id": 1, "method": "nope", "params": 5},
            {"jsonrpc": "2.0", "id": 1, "method": "PING"}, {"jsonrpc": "2.0", "id": 1, "method": ""},
            {"jsonrpc": "2.0", "id": 1, "method": "unknown \ud800 method"},
            {"jsonrpc": "2.0", "id": 1, "method": "été/ "},
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": ["2025-06-18"]}},
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": None}},
            {"jsonrpc": "2.0", "id": 1, "method": "resources/read"},
            {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": ["x"]}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": None}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": 5, "arguments": {}}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_status", "arguments": None}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_status", "arguments": "{}"}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"arguments": {}}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "GET_STATUS"}},
            {"jsonrpc": "2.0", "id": 1, "method": "prompts/list", "params": {"cursor": "x"}},
        ]
        for index, message in enumerate(envelopes):
            cases["envelope %d" % index] = mcp_lines(message)
        cases["a batch of every kind"] = mcp_lines([PING, 5, [], None, "x", {"jsonrpc": "2.0", "method": "ping"},
                                                    [[PING]], {"jsonrpc": "1.0", "id": 3}, dict(PING, id=9)])
        cases["an empty batch, then a ping"] = mcp_lines([], PING)
        cases["a request that is a number, a text, null"] = mcp_lines("5", '"ping"', "null", PING)
        for name, stream in cases.items():
            with self.subTest(name):
                self.mcp_both(stream=stream, world={"watcher_running": False}, label=name)
        RECORD.append("MCP framing: %d streams equal" % len(cases))

    def test_long_stream(self):
        stream = mcp_lines(*[dict(PING, id=index) for index in range(1, 600)]
                           + [call("get_status", ident=600), call("list_pending", ident=601)])
        self.mcp_both(stream=stream, world={"watcher_running": True}, label="600 requests")


# ------------------------------------------------------------------------------------------ the tools
RESET, BACKOFF, RECOVERED, EXHAUSTED, NO_SUCH = (wg.WAITING_RESET, wg.WAITING_BACKOFF, wg.RECOVERED, wg.EXHAUSTED,
                                                 wg.NO_SUCH)
T1, T2, T3 = wg.T1, wg.T2, wg.T3


def calls(*pairs) -> bytes:
    return mcp_lines(*[call(name, arguments, ident=index) for index, (name, arguments) in enumerate(pairs, 1)])


class ToolsDiff(McpBase):
    def test_arguments_of_every_shape(self):
        odd = [None, 5, 1.5, True, "x", "", [], {}, "\ud800", RESET.upper(), RESET[:-1], "g" * 64, T1.upper()]
        pairs = []
        for tool in ("cancel_recovery", "reset_recovery_budget", "retry_now", "get_recovery_timeline"):
            pairs += [(tool, {"interruption_id": value}) for value in odd]
            pairs += [(tool, {}), (tool, {"interruption_id": RESET, "extra": 1}), (tool, None)]
        for tool in ("disable_conversation_recovery", "enable_conversation_recovery"):
            pairs += [(tool, {"thread_id": value}) for value in odd + [T1, T2]]
        pairs += [("postpone_recovery", {"interruption_id": RESET, "thread_id": T1, **more}) for more in (
            {}, {"preset": "1_hour"}, {"preset": "tomorrow_morning"}, {"preset": "nope"}, {"preset": 5},
            {"minutes": 0}, {"minutes": 1}, {"minutes": 10080}, {"minutes": 10081}, {"minutes": 1.5},
            {"minutes": True}, {"minutes": "30"}, {"preset": "1_hour", "minutes": 30}, {"preset": None})]
        pairs += [("release_hold", {"interruption_id": value, "thread_id": T1}) for value in (RESET, BACKOFF, 5)]
        pairs += [("list_pending", {"include_finished": value}) for value in (True, False, 1, 0, None, "true")]
        pairs += [("get_recovery_statistics", {"days": value}) for value in (
            1, 3650, 0, 3651, 0.5, 1.5, 7.0, -1, True, False, None, "7", [7], 1e308, 1e-300)]
        pairs += [("get_recovery_statistics", None), ("get_recovery_statistics", {"days": 7, "x": 1})]
        pairs += [("preview_recovery_message", arguments) for arguments in (
            {"category": "usage_limit"}, {"category": "timeout", "changes": None}, {"category": "timeout", "changes": []},
            {"category": "timeout", "changes": {}}, {"category": "timeout", "changes": {"continuation_language": "ar"}},
            {"category": "timeout", "changes": {"continuation_style": "nope"}},
            {"category": "timeout", "changes": {"interface_language": "ko", "custom_message_mode": "custom"}},
            {"category": 5}, {"category": None}, {"category": "unclassified"}, {}, {"changes": {}},
            {"category": "timeout", "changes": {"theme": "dark"}})]
        pairs += [("update_settings", arguments) for arguments in (
            {}, {"notifications": True}, {"theme": "dark"}, {"panel_theme": "light"}, {"codex_homes": []},
            {"codex_exe": "x"}, {"max_recovery_attempts": 3}, {"max_recovery_attempts": "3"},
            {"quiet_hours_start": "22:00", "quiet_hours_end": "06:30"}, {"quiet_hours_start": "25:00"},
            {"interface_language": "ko"}, {"interface_language": "xx"}, {"continuation_style": "detailed"},
            {"retry_wait_1": "m45"}, {"stall_after": "h2"}, {"recover_timeout": False}, {"design": "plain"})]
        pairs += [("get_status", {}), ("open_settings", {}), ("open_settings", {"x": 1}),
                  ("clear_recovery_history", {}), ("clear_recovery_history", {}), ("restore_default_settings", {}),
                  ("pause_auto_recovery", {}), ("resume_auto_recovery", {}), ("turn_off_power_action", {}),
                  ("unknown_tool", {}), ("send_message", {"thread_id": T1})]
        for start in range(0, len(pairs), 40):
            with self.subTest(start=start):
                self.mcp_both(stream=calls(*pairs[start:start + 40]), world={"watcher_running": True},
                              label="tools %d-%d" % (start, start + 40))

    def test_watcher_states(self):
        worlds = {
            "running": {"watcher_running": True},
            "not running": {"watcher_running": False},
            "unknown": {"watcher_running": None},
            "launched and exited": {"watcher_running": False, "launch": {"pid": 4242, "polls": [1]}},
            "launched, never seen": {"watcher_running": False, "launch": {"pid": 4242, "polls": [None]}},
            "came up, job unknown": {"probes": [False], "watcher_running": True,
                                     "launch": {"pid": 4242, "polls": [None]}, "process_context": {"raise": "OSError"}},
            "came up in a job": {"probes": [False], "watcher_running": True, "launch": {"pid": 9, "polls": [None]},
                                 "process_context": wg.KILL_ON_CLOSE_JOB},
            "launch refused": {"watcher_running": False, "launch": {"raise": ["OSError", "[WinError 5] denied"]}},
            "no launcher": {"watcher_running": False, "launcher": {"raise": ["StartupError", "no pythonw.exe"]}},
            "install lock": {"watcher_running": False, "install_in_progress": True},
            "install lock unknown": {"watcher_running": False, "install_in_progress": None},
        }
        stream = calls(("start_watcher", {}), ("get_status", {}), ("open_settings", {}))
        for name, world in worlds.items():
            with self.subTest(name):
                self.mcp_both(stream=stream, world=world, label="watcher " + name)

    def test_homes_and_policies(self):
        stream = calls(("get_status", {}), ("open_settings", {}), ("list_pending", {"include_finished": True}),
                       ("get_recovery_statistics", {}), ("pause_auto_recovery", {}), ("resume_auto_recovery", {}),
                       ("cancel_recovery", {"interruption_id": BACKOFF}), ("retry_now", {"interruption_id": RESET}),
                       ("reset_recovery_budget", {"interruption_id": EXHAUSTED}),
                       ("clear_recovery_history", {}), ("update_settings", {"notifications": False}))
        for kind in ("acts", "golden", "empty", "fresh"):
            with self.subTest(kind):
                self.mcp_both(kind, stream=stream, world={"watcher_running": False}, label="home " + kind)
        managed = [{"disable_auto_resume": True}, {"force_observe_only": True, "max_recovery_attempts": 1},
                   {"disable_power_action": True}, {"quiet_hours": [{"start": "22:00", "end": "07:00"}]}]
        for held in managed:
            with self.subTest(managed=held):
                self.mcp_both(stream=stream, world={"watcher_running": True, "managed": held}, label="managed %r" % held)
        damaged = {"garbage state": lambda ws: (ws / "home" / "config" / "state.sqlite").write_bytes(b"not a database"),
                   "garbage settings": lambda ws: (ws / "home" / "config" / "settings.json").write_bytes(b"{")}
        for name, tune in damaged.items():
            with self.subTest(name):
                self.mcp_both(stream=stream, world={"watcher_running": True}, tune=tune, label=name)

    def test_compatibility_views(self):
        unusable = absent_view()
        views = [None, "x", [], {}, unusable,
                 dict(unusable, status="ok", overall="verified", acting="checked", checked_at=1799999000,
                      data={"source": "cache", "cache_sequence": 7, "bundled_sequence": 3, "cache": "ok"}),
                 dict(unusable, status="bogus", overall=5, acting=[], checked_at=float("1e308"),
                      data={"source": "bundled", "bundled_sequence": -1, "cache": "nope"}),
                 dict(unusable, data={"source": "bundled", "bundled_sequence": True}),
                 dict(unusable, checked_at=10 ** 400), dict(unusable, checked_at=True), dict(unusable, data=[]),
                 dict(unusable, capabilities=None), dict(unusable, capabilities=[]), dict(unusable, capabilities="x"),
                 dict(unusable, capabilities={"engine_present": {"state": "VERIFIED", "reason": ["x"]}}),
                 dict(unusable, capabilities={"engine_present": {"state": "nope", "reason": ["x"]}}),
                 dict(unusable, capabilities={"engine_present": [1]}),
                 dict(unusable, capabilities={"other": [1], "usage_probe": {"state": "CHECKED",
                                                                            "reason": "registry_checked"}})]
        stream = calls(("get_status", {}), ("open_settings", {}))
        for index, view in enumerate(views):
            with self.subTest(index):
                world = {"watcher_running": True, "compat_view": view}
                # 10 ** 400 cannot be a JSON world value written by json.dumps as a float: it is an int, kept.
                self.mcp_both(stream=stream, world=world, label="view %d" % index)

    def test_statistics_over_clocks(self):
        stream = calls(("get_recovery_statistics", {"days": 1}), ("get_recovery_statistics", {"days": 30}),
                       ("get_recovery_statistics", {}), ("get_recovery_timeline", {"interruption_id": RECOVERED}))
        for clock in (now(), now() + 86400 * 2, now() - 86400 * 400):
            with self.subTest(clock):
                self.mcp_both(stream=stream, world={"watcher_running": True, "now": clock}, label="stats %r" % clock)


# ------------------------------------------------------------------------------------------ the panel
LOOKS_AT = {}


def special_day_clock(look: str) -> float:
    """A moment on a day of `look`, UTC (the world's local zone)."""
    import calendar
    from codex_auto_resume.brand import days

    if look in LOOKS_AT:
        return LOOKS_AT[look]
    for year in (2026, 2027, 2028):
        for month in range(1, 13):
            for day in range(1, 29):
                if days.day_look(year, month, day) == look:
                    LOOKS_AT[look] = float(calendar.timegm((year, month, day, 12, 0, 0)))
                    return LOOKS_AT[look]
    raise LookupError(look)


class PanelDiff(McpBase):
    def test_assets(self):
        import released

        crate = ROOT / "rust" / "crates" / "car-control" / "assets"
        shipped = ROOT / "src" / "codex_auto_resume" / "mcp" / "assets"
        tag = released.package(reference.TAG) / "codex_auto_resume" / "mcp" / "assets"
        for name in ("panel.css", "panel.js"):
            mine = (crate / name).read_bytes()
            self.assertEqual(mine, (shipped / name).read_text(encoding="utf-8").encode("utf-8"),
                             "%s: car-control's copy is not the shipped file read with universal newlines" % name)
            self.assertEqual(mine, (tag / name).read_text(encoding="utf-8").encode("utf-8"),
                             "%s: car-control's copy is not the reference tag's" % name)
        RECORD.append("panel assets: car-control/assets/panel.css and panel.js are the shipped and the tag's files, "
                      "read with universal newlines")

    def pages(self):
        pages = [{}, {"theme": "light"}, {"theme": "dark"}, {"theme": "Dark"}, {"design": "soft"},
                 {"design": "classic"}, {"design": "plain"}, {"design": "still"}, {"theme": "dark", "design": "plain"},
                 {"text": 1}, {"text": 1.25}, {"text": 1.5}, {"text": 2.25}, {"text": 3}, {"text": True}, {"text": "2"},
                 {"text": 0.5}, {"text": 1.001}, {"face": None}, {"face": "Segoe UI"}, {"face": "Malgun Gothic"},
                 {"face": "  "}, {"face": "Some Face"},
                 {"data": {"settings": {"theme": "dark"}, "note": "</script><b>"}}, {"data": None}]
        from codex_auto_resume.brand import days
        pages += [{"day": look} for look in days.DAY_LOOKS]
        return pages

    def test_pieces_and_pages(self):
        worlds = [
            ({}, None),
            ({"languages": ["ko-KR"]}, None),
            ({"languages": ["ar-SA"]}, None),
            ({}, "he"),
            ({}, "ja"),
            ({"ui_face": "Malgun Gothic", "lacks": {"Malgun Gothic": "ابپتث", "Segoe UI": ""}}, "en"),
            ({"ui_face": "Some Face", "lacks": {"Some Face": "가나다abc", "Segoe UI": "가"}}, "ko"),
            ({"text_size": 1.75}, "fr"),
        ]
        pages = self.pages()
        for index, (world, preference) in enumerate(worlds):
            with self.subTest(index):
                spec_dir = Path(tempfile.mkdtemp(prefix="car-v0627-mcp-panel-"))
                try:
                    full = bw.world_for(spec_dir)
                    full.update(world)
                    (spec_dir / "spec.json").write_text(json.dumps({"world": full, "preference": preference,
                                                                    "pages": pages}), encoding="utf-8")
                    done = reference.run(PANEL_SCRIPT, spec_dir / "spec.json", profile=spec_dir)
                    self.assertEqual(done.returncode, 0, done.stderr[-3000:].decode("utf-8", "replace"))
                    expected = json.loads(done.stdout.decode("utf-8"))
                    _, line = self.harness.call("mcp.panel", world=full, preference=preference, pages=pages)
                    reply = json.loads(line.decode("utf-8"))["reply"]
                    self.assertTrue(reply.get("ok"), line[:500])
                    actual = reply["value"]
                finally:
                    shutil.rmtree(spec_dir, ignore_errors=True)
                for key in ("style", "script", "names", "prefixes", "font_stack", "tile", "rules"):
                    self.assertEqual(actual[key], expected[key], "%s differs (world %d)" % (key, index))
                for number, (want, got) in enumerate(zip(expected["pages"], actual["pages"])):
                    if want != got:
                        if isinstance(want, str) and isinstance(got, str):
                            at = next((i for i, (a, b) in enumerate(zip(want, got)) if a != b), min(len(want), len(got)))
                            self.fail("page %r (world %d) differs at %d\nreference ...%s\nrust      ...%s" % (
                                pages[number], index, at, want[max(0, at - 200):at + 200], got[max(0, at - 200):at + 200]))
                        self.fail("page %r (world %d): reference %r, rust %r" % (pages[number], index, str(want)[:300],
                                                                                str(got)[:300]))
                self.assertEqual(len(actual["pages"]), len(expected["pages"]))
                COUNTS["pages"] += len(pages)
        RECORD.append("panel: _STYLE, _SCRIPT, panel_keys, FONT_STACK, tiles and rules equal; %d pages over %d worlds "
                      "byte for byte" % (len(pages), len(worlds)))

    def test_resource_read(self):
        read = {"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                "params": {"uri": "ui://codex-auto-resume/settings"}}
        worlds = [{}, {"languages": ["ko-KR"]}, {"text_size": 1.5, "ui_face": "Some Face",
                                                  "lacks": {"Some Face": "한국"}}]
        from codex_auto_resume.brand import days
        worlds += [{"now": special_day_clock(look)} for look in days.DAY_LOOKS]
        for index, world in enumerate(worlds):
            with self.subTest(index):
                self.mcp_both(stream=mcp_lines(read, call("update_settings", {"interface_language": "ar"}), read),
                              world=dict(world, watcher_running=True), label="resources/read %d" % index)
        RECORD.append("resources/read: %d worlds (languages, text size, UI font, every special day) equal; %d streams, "
                      "%d response lines and %d Host calls equal in all" % (len(worlds), COUNTS["streams"],
                                                                           COUNTS["lines"], COUNTS["calls"]))


TEMPLATES  # noqa: B018 - shared with the bridge diffs (one template per kind for the whole run)
