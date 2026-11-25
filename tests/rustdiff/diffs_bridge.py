"""car-control's quiet bridge commands (seat S5.1a): each runs the same requests through the reference tag's
`controlcli` (bridgeworld.SCRIPT) and through car-control (`car-harness serve`, `bridge.run`) over the same scratch
installation and the same world, and holds the reply bytes, the exit code and every file the commands wrote equal.

* FramingDiff - `serve`'s framing over recorded request streams: the goldens' framing cases, partial lines (no final
  newline), two requests in one write, CRLF, blank and padded lines, a byte order mark, invalid JSON, NaN and lone
  surrogates, an id of 5,000 digits, a line past the limit, bytes that are not UTF-8, an unknown command.
* SettingsDiff - settings, describe, strings, defaults, update, check-setting over every installation kind and the
  administrator's keys; the files written equal.

Run by run.py with diffs.py; never by the lanes' discovery (tests/rustdiff has no __init__.py).
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from rustdiff import bridgeworld as bw
from rustdiff import core, reference
from rustdiff.diffs import RECORD, Base

ROOT = core.ROOT
TEMPLATES: dict = {}


def lines(*requests) -> bytes:
    """Request lines as a stream: each a JSON object (or the text as given) and a newline."""
    out = []
    for request in requests:
        out.append(request if isinstance(request, str) else json.dumps(request))
    return ("\n".join(out) + "\n").encode("utf-8")


def sized(characters: int) -> str:
    """One request line of exactly `characters` characters: a settings request whose argument is a text of a's."""
    head, tail = '{"id": 1, "command": "settings", "argument": "', '"}'
    return head + "a" * (characters - len(head) - len(tail)) + tail


def request(command, argument=None, ident=1, **more) -> dict:
    body = {"id": ident, "command": command}
    if argument is not None:
        body["argument"] = argument
    body.update(more)
    return body


class BridgeBase(Base):
    """Each side runs in a copy of one template at one and the same path: a home's key is a hash of its path, so two
    folders of different names would differ in every reply that names a Codex home."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        profile = Path(tempfile.mkdtemp(prefix="rustdiff-bridge-profile-"))
        cls.addClassCleanup(shutil.rmtree, profile, True)
        # The harness is started as the reference is: every home variable points into a scratch profile.
        cls.harness = core.Harness(reference.scratch_environment(profile)).__enter__()
        cls.addClassCleanup(cls.harness.__exit__, None, None, None)

    def template(self, kind: str) -> Path:
        if kind not in TEMPLATES:
            folder = Path(tempfile.mkdtemp(prefix="rustdiff-bridge-template-"))
            bw.installation(folder, kind)
            TEMPLATES[kind] = folder
        return TEMPLATES[kind]

    def workspace(self, kind: str, tune=None) -> Path:
        """A fresh copy of the `kind` template at the one path both sides use, `tune` applied."""
        target = self.scratch / "ws"
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(self.template(kind), target)
        (target / "profile").mkdir(exist_ok=True)
        if tune is not None:
            tune(target)
        return target

    def same(self, kind: str, stdin=b"", *, mode="serve", argv=(), world=None, tune=None, files=True, label=""):
        """Run one stream on both sides, each in a fresh copy at the same path; assert the output, the exit code and
        the files written equal. `stdin` is bytes, or a function of the workspace giving them. Returns the
        reference's output."""
        label = label or "a stream"
        ran = []
        for side in ("reference", "rust"):
            target = self.workspace(kind, tune)
            asked = stdin(target) if callable(stdin) else stdin
            asked_world = bw.world_for(target, **dict((world(target) if callable(world) else world) or {}))
            if side == "reference":
                code, out, stderr = bw.ask_reference(target / "home", asked_world, mode=mode, stdin=asked, argv=argv)
            else:
                code, out = bw.ask_rust(self.harness, target / "home", asked_world, mode=mode, stdin=asked, argv=argv)
                stderr = b""
            ran.append((code, out, stderr, bw.files_of(target / "home")))
        (code, expected, stderr, theirs), (actual_code, actual, _, mine) = ran
        if actual != expected:
            at = next((index for index, (a, b) in enumerate(zip(actual, expected)) if a != b),
                      min(len(actual), len(expected)))
            self.fail("%s: the output differs at byte %d (reference exit %d, rust exit %d; reference stderr %r)\n"
                      "reference: ...%s\nrust:      ...%s" % (
                          label, at, code, actual_code, stderr[-300:],
                          expected[max(0, at - 200):at + 200].decode("utf-8", "replace"),
                          actual[max(0, at - 200):at + 200].decode("utf-8", "replace")))
        self.assertEqual(actual_code, code, "%s: the exit code differs" % label)
        if files:
            self.assertEqual(sorted(mine), sorted(theirs), "%s: the files written differ" % label)
            for name, data in theirs.items():
                self.assertEqual(mine[name], data, "%s: %s differs" % (label, name))
        return expected


class FramingDiff(BridgeBase):
    def test_goldens_framing_cases(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import wiregolden

        for name, line in wiregolden.FRAMING_CASES:
            with self.subTest(name):
                self.same("golden", (line + "\n").encode("utf-8"), label=name)
        RECORD.append("framing: %d of the goldens' cases equal" % len(wiregolden.FRAMING_CASES))

    def test_streams(self):
        read = request("settings", ident=7)
        cases = {
            "an empty stream": b"",
            "only blank lines": b"\n\n   \n\t\n",
            "no final newline": json.dumps(read).encode("utf-8"),
            "two requests in one write": lines(read, request("describe", ident=8)),
            "two requests on one line": json.dumps(read).encode("utf-8") + json.dumps(read).encode("utf-8") + b"\n",
            "CRLF": json.dumps(read).encode("utf-8") + b"\r\n" + json.dumps(request("describe", ident=2)).encode(
                "utf-8") + b"\r\n",
            "a lone CR": json.dumps(read).encode("utf-8") + b"\r" + json.dumps(read).encode("utf-8") + b"\n",
            "padded with spaces and a no-break space": b"  \xc2\xa0" + json.dumps(read).encode("utf-8")
            + b" \xe3\x80\x80\n",
            "padded with file separator controls": b"\x1c\x1d\x1e\x1f" + json.dumps(read).encode("utf-8") + b"\x1f\n",
            "a byte order mark at the start": b"\xef\xbb\xbf" + lines(read),
            "a byte order mark twice": b"\xef\xbb\xbf\xef\xbb\xbf" + lines(read),
            "a byte order mark on the second line": lines(read) + b"\xef\xbb\xbf" + lines(read),
            "an id of 30 digits": lines('{"id": 123456789012345678901234567890, "command": "settings"}'),
            "an id of 5000 digits": lines('{"id": %s, "command": "settings"}' % ("9" * 5000)),
            "a negative id": lines('{"id": -5, "command": "settings"}'),
            "a float id": lines('{"id": 1.5, "command": "settings"}'),
            "NaN as the id": lines('{"id": NaN, "command": "settings"}'),
            "Infinity as the id": lines('{"id": Infinity, "command": "settings"}'),
            "1e999 as the id": lines('{"id": 1e999, "command": "settings"}'),
            "an id that is an object": lines('{"id": {"a": [1, 2]}, "command": "settings"}'),
            "an id that is null": lines('{"id": null, "command": "settings"}'),
            "a lone surrogate in the id": lines('{"id": "\\ud800", "command": "settings"}'),
            "a lone surrogate before good lines": lines(read, '{"id": "\\udc00", "command": "settings"}', read),
            "a paired surrogate in the id": lines('{"id": "\\ud83d\\ude00", "command": "settings"}'),
            "a lone surrogate in the command": lines('{"id": 3, "command": "\\ud800"}'),
            "a command that is a number": lines('{"id": 3, "command": 5}'),
            "a command that is a list": lines('{"id": 3, "command": ["settings"]}'),
            "no command": lines('{"id": 3}'),
            "an empty command": lines('{"id": 3, "command": ""}'),
            "a command in capitals": lines('{"id": 3, "command": "SETTINGS"}'),
            "a command with a space": lines('{"id": 3, "command": "settings "}'),
            "an argument of zero": lines('{"id": 3, "command": "settings", "argument": 0}'),
            "an argument of false": lines('{"id": 3, "command": "settings", "argument": false}'),
            "an argument that is a list": lines('{"id": 3, "command": "settings", "argument": []}'),
            "an argument that is an empty text": lines('{"id": 3, "command": "settings", "argument": ""}'),
            "an argument that is null": lines('{"id": 3, "command": "settings", "argument": null}'),
            "an argument that is JSON text with NaN": lines(
                '{"id": 3, "command": "timeline", "argument": "{\\"interruption_id\\": NaN}"}'),
            "an argument that is JSON text of a list": lines(
                '{"id": 3, "command": "timeline", "argument": "[1]"}'),
            "an argument that is JSON text with a lone surrogate": lines(
                '{"id": 3, "command": "timeline", "argument": "{\\"interruption_id\\": \\"\\\\ud800\\"}"}'),
            "an argument that is a lone surrogate": lines(
                '{"id": 3, "command": "timeline", "argument": "\\ud800"}'),
            "a request that is a number": lines("5"),
            "a request that is null": lines("null"),
            "a request that is a text": lines('"settings"'),
            "a trailing comma": lines('{"id": 1, "command": "settings",}'),
            "a duplicate key": lines('{"id": 1, "id": 2, "command": "settings"}'),
            "a duplicate command": lines('{"id": 1, "command": "format-disk", "command": "settings"}'),
            "a leading zero": lines('{"id": 01, "command": "settings"}'),
            "a control character in a text": b'{"id": 1, "command": "set\x01tings"}\n',
            "nesting of 1000 in the argument": lines(
                '{"id": 1, "command": "settings", "argument": %s%s}' % ("[" * 1000, "]" * 1000)),
            "nesting of 100000": lines("[" * 100000),
            "a line of 1,048,576 characters": lines(sized(1024 * 1024)),
            "a line of 1,048,577 characters": lines(sized(1024 * 1024 + 1)),
            "a line of 1,048,577 characters with padding": lines(" " + sized(1024 * 1024 + 1) + " "),
            "bytes that are not UTF-8 first": b"\xff\xfe" + lines(read),
            "bytes that are not UTF-8 after a good line": lines(read) + b"\xff\n",
            "a cut multibyte character at the end": lines(read) + b"\xe3\x81",
            "an unknown command among good ones": lines(read, request("format-disk", ident=9), read),
            "a command that only the plug could answer": lines(request("shutdown", ident=9)),
            "the whole of PLAIN's unported-looking names": lines(request("nonsense", {"a": 1}, ident=4)),
        }
        for name, stream in cases.items():
            with self.subTest(name):
                self.same("golden", stream, label=name)
        RECORD.append("framing: %d request streams (partial lines, two in one write, CRLF, padding, a BOM, NaN, lone "
                      "surrogates, huge ids, a line past the limit, invalid UTF-8, unknown commands) equal"
                      % (len(cases) + 1))

    def test_long_stream(self):
        stream = lines(*[request("settings", ident=index) for index in range(1, 400)])
        self.same("golden", stream, label="400 requests")

    def test_a_stream_past_one_chunk_of_invalid_bytes(self):
        # Python reads 8192 bytes at a time: the lines of the chunks before one holding a bad byte are answered.
        filler = lines(*[request("settings", ident=index) for index in range(1, 12)])
        self.assertGreater(len(filler), 0)
        stream = filler + b" " * (9000 - len(filler)) + b"\n" + b"\xff\n"
        self.same("golden", stream, label="a bad byte in the second chunk")


if __name__ == "__main__":
    unittest.main()
