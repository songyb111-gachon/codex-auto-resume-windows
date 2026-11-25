"""S3.3: car-codex's reading of the App Server's lines held to the reference (`codex/appserver.py`).

`next_message` over byte streams a text-mode pipe hands it - lines whole and split, CRLF and a lone CR, bytes that
are no UTF-8, a BOM, lines that are no JSON object, NaN, nesting past the reader's depth, and lines at and past
LINE_LIMIT: oversize answers with their id first and errors with it last (escaped string ids, ids that are no int or
text, Codex's numeric code in the head), requests, notifications and lines that are none of these, each followed by an
answer that must still be read, and the log line the reference's logger is told for a line it drops. Then the pure
rules: `_unknown` (method not found, the serde "unknown variant" of the very method), `last_result` over results the
helper could have met, and `offers` over `--help` texts.
"""
from __future__ import annotations

import json
import random

from rustdiff.appserverdiff import AppBase, op

RECORD: list[str] = []
LIMIT = 1024 * 1024
KEPT = 64 * 1024


def answer(ident, result):
    return json.dumps({"id": ident, "result": result}) + "\n"


def streams():
    """(name, bytes) of every stream read."""
    tail = answer(9, {"ok": True})
    yield "plain", (answer(1, {"a": 1}) + json.dumps({"method": "x", "params": {}}) + "\n" + tail).encode()
    yield "crlf", (answer(1, 1).replace("\n", "\r\n") + "\r" + answer(2, 2).replace("\n", "\r") + tail).encode()
    yield "no newline at the end", answer(1, "x").rstrip("\n").encode()
    yield "not utf-8", b'{"id": 1, "result": "\xff\xfe\xed\xa0\x80"}\n' + tail.encode() + b"\xf0\x9f\x98"
    yield "bom", b"\xef\xbb\xbf" + answer(1, 1).encode() + tail.encode()
    yield "not objects", b"[1, 2]\n\"text\"\n5\nnull\n\n   \n{bad json\n" + tail.encode()
    yield "nan and big numbers", b'{"id": 1, "result": NaN}\n{"id": 2, "result": 1e999}\n{"id": 3, "result": ' + \
        b"9" * 5000 + b"}\n" + tail.encode()
    yield "deep", b"[" * 4000 + b"]" * 4000 + b"\n" + tail.encode()
    yield "deep object", b'{"a": ' * 3500 + b"1" + b"}" * 3500 + b"\n" + tail.encode()
    yield "surrogate escapes", b'{"id": 1, "result": "\\ud83d \\ude00 \\ud83d\\ude00"}\n' + tail.encode()
    # around the limit: exactly LIMIT characters with and without the newline, one more, multi-byte characters
    body = lambda size: '{"id": 4, "result": "%s"}' % ("A" * (size - len('{"id": 4, "result": ""}')))
    for size in (LIMIT - 1, LIMIT, LIMIT + 1, LIMIT + 2):
        yield "size %d" % size, (body(size) + "\n" + tail).encode()
    yield "size LIMIT no newline", body(LIMIT + 1).encode()
    wide = '{"id": 5, "result": "%s"}\n' % ("é" * (LIMIT + 10))
    yield "wide characters", (wide + tail).encode()
    yield "crlf past the limit", (body(LIMIT + 5) + "\r\n" + tail).encode()
    big = "B" * (LIMIT * 2 + 12345)
    yield "oversize result, id first", ('{"id": 7, "result": {"x": "%s"}}\n' % big + tail).encode()
    yield "oversize result, string id", ('{"id": "a\\"b", "result": "%s"}\n' % big + tail).encode()
    yield "oversize result, no id", ('{"result": "%s"}\n' % big + tail).encode()
    yield "oversize error, id last", ('{"error": {"code": -32600, "message": "%s"}, "id": 8}\n' % big + tail).encode()
    yield "oversize error, string id last", ('{"error": {"code": 5, "message": "%s"}, "id": "x\\\\y"}  \n'
                                             % big + tail).encode()
    yield "oversize error, no code", ('{"error": {"message": "%s"}, "id": 8}\n' % big + tail).encode()
    yield "oversize error, unicode digits", ('{"error": {"code": ١٢, "m": "%s"}, "id": 8}\n'
                                             % big + tail).encode()
    yield "oversize error, id a float", ('{"error": {"code": 1, "m": "%s"}, "id": 8.5}\n' % big + tail).encode()
    yield "oversize request", ('{"id": 11, "method": "item/tool/call", "params": {"x": "%s"}}\n' % big + tail).encode()
    yield "oversize request, method first", ('{"method": "item/x", "id": 12, "params": "%s"}\n' % big + tail).encode()
    yield "oversize notification", ('{"method": "thread/queue/changed", "params": {"image": "%s"}}\n'
                                    % big + tail).encode()
    yield "oversize notification, long method", ('{"method": "%s", "params": "%s"}\n' % ("m" * 200, big) + tail).encode()
    yield "oversize junk", ("x" * (LIMIT * 3) + "\n" + tail).encode()
    yield "oversize with the id cut", ('{"id": ' + "1" * (KEPT + 10) + ', "result": 1}' + " " * LIMIT + "\n"
                                       + tail).encode()
    yield "oversize, the value ends at the head", ('{"result": "' + "C" * (KEPT - 13) + '", "id": 3, "x": "'
                                                   + "D" * LIMIT + '"}\n' + tail).encode()
    yield "oversize, the tail split", ('{"error": {"code": 1}, "x": "' + "E" * LIMIT + '", "id": 5}' + "\n"
                                       + tail).encode()
    yield "oversize at the end", ('{"id": 13, "result": "%s"}' % big).encode()
    yield "two oversize lines", ('{"id": 14, "result": "%s"}\n{"id": 15, "result": "%s"}\n' % (big, big)
                                 + tail).encode()
    yield "oversize, a newline in a tail piece", ('{"id": 16, "result": "' + "F" * (LIMIT * 2) + '"}\r\n'
                                                  + tail).encode()


class LinesDiff(AppBase):
    def test_next_message(self):
        folder = self.profile("streams")
        cases = []
        for number, (name, data) in enumerate(streams()):
            path = folder / ("stream-%d.bin" % number)
            path.write_bytes(data)
            cases.append({"world": {}, "ops": [op("messages", str(path))], "name": name})
        count, calls = self.script(cases, "app server lines", chunk=8)
        RECORD.append("appserver: next_message over %d streams (around and past LINE_LIMIT, oversize answers, errors, "
                      "requests, notifications), every message and log line equal" % count)

    def test_rules(self):
        rng = random.Random(267)
        methods = ["initialize", "account/rateLimits/read", "thread/queue/delete", "thread/start", "", "x`y"]
        errors = [None, 5, "text", [], {}, {"code": -32601}, {"code": -32601.0}, {"code": True}, {"code": "-32601"},
                  {"code": -32600}, {"code": -32600, "message": None}]
        for method in methods:
            errors += [{"code": -32600, "message": "Invalid request: unknown variant `%s`, expected one of" % method},
                       {"code": -32600, "message": "unknown variant `%s`" % method.upper()},
                       {"code": -32600, "message": "Unknown variant `%s`" % method},
                       {"code": -32602, "message": "unknown variant `%s`" % method},
                       {"code": -32600, "message": "unknown variant %s" % method}]
        ops = [op("unknown", error, method) for error in errors for method in methods]
        codes = ["ok", "protocol_home_mismatch", "protocol_method_unknown", "protocol_request_refused",
                 "protocol_reply_unknown", "protocol_unavailable", "protocol_timeout"]
        for _ in range(3000):
            results = {}
            for method in rng.sample(methods[:4], rng.randint(0, 4)):
                results[method] = [rng.choice(codes), rng.randint(1, 6)]
            ops.append(op("last_result", rng.choice(methods), results))
        words = ["--thread", "--message", "--remote", "--remote-auth-token", "--thread-id", "--messages", "-thread",
                 "x--thread", "--thread=", "--thread\n", "é--thread", "_--thread", "--THREAD"]
        for _ in range(2000):
            text = " ".join(rng.choice(words + ["  ", "\t", "Usage:", "[OPTIONS]"]) for _ in range(rng.randint(0, 8)))
            ops.append(op("offers", text, rng.choice(["--thread", "--message", "--remote"])))
        count, calls = self.script([{"world": {}, "ops": ops}], "app server rules")
        RECORD.append("appserver: _unknown, last_result and offers, %d cases equal" % calls)
