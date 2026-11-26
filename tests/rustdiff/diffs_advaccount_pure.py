"""S7.2b: the pure halves of `codex/account.py`, `codex/authfile.py`'s checks and names, `codex/swap.py`'s readings, the
Restart Manager and kernel32 calls of `win/appclose.py`, and `codex/restart.py`'s restart and busy rule, each held equal
to the v0.6.26 final on the same inputs - and `authfile.store_mode` over a corpus of config.toml files that holds the
port of Python 3.14's tomllib to the reference's (every rule, every refusal, the recursion limit).

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advaccount_pure`.
"""
from __future__ import annotations

import json
import random

from rustdiff.advaccount import APP, ENGINE, TUI, AdvAccountDiff

RECORD: list[str] = []

SURROGATE = "\ud800"
EMAILS = ["a@b.c", " Person@Example.COM ", "no-at", "@", "a@", "@b", "a@.b", "a@b.", "x@y@z", "", 5, None,
          "\u0130@\u212a.com", "a@" + "b" * 330, "\u00e9t\u00e9@caf\u00e9.fr", "s@e", "a@b" + SURROGATE, "\t\n a@b \u3000"]


class AccountPureDiff(AdvAccountDiff):
    def test_plan_parse_identity_digest_and_mask(self):
        plans = ["plus", " PRO ", "Team", "enterprise", "edu", "free", "business", "other", "unknown", "", " ", 7,
                 None, True, "\u212aplus", "plus\n", "PLUS\u3000"]
        cases = [["ac.plan_word", each] for each in plans]
        replies = [None, {}, [], "x", {"account": None}, {"account": 5}, {"account": []}, {"account": {}},
                   {"account": {"type": "chatGPT", "email": " a@b.c ", "planType": "Plus"}},
                   {"account": {"type": "apiKey"}}, {"account": {"type": "APIKEY", "plan_type": "pro"}},
                   {"account": {"type": "other", "email": "x", "planType": None, "plan_type": "team"}},
                   {"account": {"type": 3, "email": 5, "planType": 9}},
                   {"account": {"type": "\u212aind", "email": "a@" + "b" * 318}},
                   {"account": {"email": "a@" + "b" * 319}}, {"account": {"email": "\u3000a@b\u3000"}},
                   {"account": {"type": "chatgpt\n"}}, {"account": {"type": "ApI\u212aey"}}]
        cases += [["ac.parse", each] for each in replies]
        founds = [None, {}, {"present": True}, {"present": 1, "email": "a@b"}, {"present": True, "email": "A@B.C"},
                  {"present": True, "email": "", "kind": "apikey"}, {"present": True, "kind": "chatgpt"},
                  {"present": True, "email": None, "kind": None}, {"present": False, "email": "a@b"},
                  {"present": True, "email": 5}, {"present": True, "kind": 3}, {"present": True, "email": "\u0130X@Y"},
                  {"present": True, "email": [1]}, {"present": True, "kind": ["x"]}, {"present": True, "kind": ""}]
        cases += [["ac.identity", each] for each in founds]
        salts = ["00", "0a 0b", "zz", "0", "", " ", "0a\t0b\n", "\u00e9", "ab" * 32, "0 a", 5, None, "AB", "a" * 300]
        for text in ["a@b.c", "kind:apikey", "", 5, None, "\u00e9@x", "x" + SURROGATE]:
            for salt in salts:
                cases.append(["ac.digest", text, salt])
        cases += [["ac.mask", each] for each in EMAILS]
        RECORD.append("account pure: %d cases" % len(cases))
        self.same("account-pure", cases)

    def test_the_session_read_and_the_sign_out_and_in(self):
        signed = {"account": {"type": "chatgpt", "email": "a@b.c", "planType": "plus"}}
        cases = [["ac.read", {}], ["ac.read", {"open": ["raise"]}], ["ac.read", {"account/read": [signed]}],
                 ["ac.read", {"account/read": ["raise"]}], ["ac.read", {"account/read": [{"account": None}]}],
                 ["ac.read", {"account/read": [5]}], ["ac.read", {"open": ["raise:OSError"]}]]
        present = {"present": True, "plan_word": "plus", "email": "a@b.c", "kind": "chatgpt"}
        out = {"present": False, "plan_word": None, "email": None, "kind": None}
        runners = [{}, {"run": ["timeout"]}, {"run": [[0, "", ""], "timeout"]}, {"run": ["raise:OSError"]},
                   {"run": ["raise:ValueError"]}, {"run": [[1, "", ""], [0, "", ""]]}, {"run": [[0, "", ""], [3, "", ""]]},
                   {"run": [[True, "", ""]]}, {"run": [[0, "", ""], ["x", "", ""]]}, {"run": [[0, ""]]},
                   {"run": ["abc"]}, {"run": [[0, "", ""], "raise:ValueError"]}, {"run": [[0, "", ""], [None, 1, 2]]}]
        backends = [{}, {"argv": [["C:/codex.exe", "-c", "x=1"]], "env": [[["A", "1"], ["CODEX_HOME", "h2"]]],
                         "home": ["home2"]}, {"argv": ["raise"]}, {"env": ["raise:OSError"]}, {"env": ["raise:ValueError"]},
                    "raise"]
        readers = [{"read": [present]}, {"read": [out]}, {"read": [{"present": None}]}, {"read": [{}]},
                   {"read": [{"present": 1}]}]
        for backend in backends:
            for runner in runners:
                for reader in readers[:2]:
                    cases.append(["ac.switch", backend, runner, reader, 600])
        for reader in readers:
            cases.append(["ac.switch", {}, {}, reader, 30])
        cases.append(["ac.switch", {}, {"run": ["raise:KeyError"]}, readers[0], 600])
        cases.append(["ac.switch", {"env": ["raise:KeyError"]}, {}, readers[0], 600])
        cases.append(["ac.switch", {}, {}, {"read": [[1]]}, 600])
        RECORD.append("account sessions and switch: %d cases" % len(cases))
        self.same("account-session", cases)


def toml_corpus() -> list:
    key = "cli_auth_credentials_store"
    docs = [b"", b"\n", b"# a comment\n", ("%s = \"file\"\n" % key).encode(), ("%s = 'keyring'" % key).encode(),
            ("%s=\"auto\"" % key).encode(), ("%s = \"ephemeral\"\n" % key).encode(), ("%s = \"other\"" % key).encode(),
            ("%s = 1" % key).encode(), ("%s = [\"file\"]" % key).encode(), ("%s = true" % key).encode(),
            ("[section]\n%s = \"keyring\"\n" % key).encode(), ("%s.x = 1" % key).encode(),
            ("\"%s\" = \"auto\"" % key).encode(), ("'%s' = \"keyring\"" % key).encode(),
            ("%s = \"\"\"file\"\"\"" % key).encode(), ("%s = '''auto'''" % key).encode(),
            ("%s = \"fi\\u006ce\"" % key).encode(), ("%s = \"FILE\"" % key).encode(),
            ("model = \"o3\"\n%s = \"keyring\"\n[profiles.x]\nmodel = \"y\"\n" % key).encode(),
            ("%s = \"file\"\n%s = \"auto\"" % (key, key)).encode(),
            b"a = 1\r\nb = 2\r\n", b"a = 1\rb = 2", b"a = \"x\r\ny\"", b"\xef\xbb\xbfa = 1", b"a = \xff", b"\xc3\x28 = 1",
            b"a = ", b"= 1", b"a = \"x", b"a = 1\na = 2", b"[a]\n[a]", b"a.b = 1\n[a]", b"[a]\nb.c = 1\n[a.b]",
            b"[a.b]\n[a]", b"[a]\n[a.b]", b"d = 2023-02-30", b"d = 2024-02-29", b"d = 2023-02-29", b"d = 0000-01-01",
            b"d = 1979-05-27T07:32:00Z", b"d = 1979-05-27 07:32:00.999999-07:00", b"d = 1979-05-27T07:32:00.",
            b"d = 1979-05-27T25:32:00", b"d = 1979-05-27T07:32", b"d = 1979-05-27 x", b"d = 1979-05-27t07:32:00z",
            b"d = 1979-05-27T07:32:00+24:00", b"t = 07:32:00", b"t = 25:00:00", b"t = 07:32:00.1234567",
            b"x = 0x", b"x = 0x1F", b"x = 0X1F", b"x = 0o17", b"x = 0b102", b"x = 1_000", b"x = 1__0", b"x = 01",
            b"x = +inf", b"x = -nan", b"x = nan", b"x = inf", b"x = 1e10", b"x = 1.", b"x = .5", b"x = 1.5e-3",
            b"x = 1_0.5_0e1_0", b"x = 1e_1", b"x = -0", b"x = +0x1", b"x = 1_", b"x = truex", b"x = tru",
            b"s = \"\\u00e9\"", b"s = \"\\uD800\"", b"s = \"\\x41\"", b"s = 'a\\b'", b"s = \"\"\"a\n  b\"\"\"",
            b"s = \"\"\"a \\\n   b\"\"\"", b"s = \"\"\"a \\  \n b\"\"\"", b"s = \"\"\"a \\ b\"\"\"", b"s = '''x'''''",
            b"s = '''x''''''", b"s = \"\"\"x\"\"\"\"\"", b"s = \"a\x01b\"", b"s = \"a\tb\"", b"s = '\x7f'",
            b"# bad \x01 comment", b"# ok \t comment", b"s = \"\\U0001F600\"", b"s = \"\\U00110000\"", b"s = \"\\",
            b"s = \"\"\"", b"s = '''", b"s = '", b"s = \"\"\"\nx\"\"\"", b"t = {a = 1, b.c = 2}", b"t = {a = 1,}",
            b"t = {a = 1}\nt.b = 2", b"t = {}", b"t = {a.b = 1, a.c = 2}", b"t = {a = {b = 1}, a.c = 2}",
            b"t = {a = 1, a = 2}", b"a = [1, [2, 3], {x = 1},]", b"a = [1 2]", b"a = [\n1, # c\n2\n]", b"a = [,]",
            b"a = []", b"[[p]]\nx = 1\n[[p]]\nx = 2", b"[[p]]\n[p]", b"p = []\n[[p]]", b"[p]\n[[p]]", b"[[p.q]]\n[p]",
            b"[ a . b ]\nc = 1", b"[a]b = 1", b"a = 1 b = 2", b"a = 1 # c", b"\"\" = 1", b"'' = 1", b"a.\"b.c\" = 1",
            b"a. = 1", b".a = 1", b"[]", b"[[]]", b"[a]]", b"[[a]", b"a = { b = 1 }\n[a]", b"a = [{b = 1}]\n[a.c]",
            b"[[a]]\nb = 1\n[a.b]", b"[a]\nb = 1\n[a.b]", b"a.b.c = 1\na.b.d = 2", b"a.b = 1\na.b.c = 2",
            b"[x]\ny.z = 1\n[x.y]", b"[x.y.z]\n[x]\n[x.y]", b"k = 1\n\n\n", b"   \t  k = 1", b"k\t=\t1",
            b"k = \"\\b\\t\\n\\f\\r\\\"\\\\\"", b"k = \"\\e\"", b"k=-1979-05-27", b"k = 1979-05-27T", b"k = 9999-12-31",
            b"k = 1900-02-29", b"k = 2000-02-29", b"k = 2100-02-29", b"k = 07:32:00Z", b"k = 1979-05-27 ",
            b"k = 1979-05-27 # x", b"k = 1979-05-27T07:32:00.5Z", b"k = 12:30", b"[a.\"b\".'c']\n", b"k = [[1], [2]]"]
    for depth in (100, 300, 320, 325, 328, 329, 330, 331, 332, 333, 334, 336, 340, 400):
        docs.append(("x = " + "[" * depth + "]" * depth).encode())
    for depth in (100, 200, 220, 230, 240, 245, 246, 247, 248, 249, 250, 260, 300):
        docs.append(("x = " + "{a = " * depth + "1" + "}" * depth).encode())
    for parts in (998, 999, 1000, 1002):
        docs.append((".".join(["a"] * parts) + " = 1").encode())
    rng = random.Random(72)
    alphabet = ["a", "b", ".", "=", " ", "\n", "[", "]", "{", "}", ",", "\"", "'", "1", "#", "\t", "\\", "x", "-", ":"]
    for _ in range(200):
        docs.append("".join(rng.choice(alphabet) for _ in range(rng.randint(1, 24))).encode())
    return docs


def write_corpus(root, docs):
    for index, data in enumerate(docs):
        folder = root / ("t%d" % index)
        folder.mkdir()
        (folder / "config.toml").write_bytes(data)


class StoreModeDiff(AdvAccountDiff):
    def test_store_mode_over_the_corpus(self):
        docs = toml_corpus()
        cases = [["af.store_mode", "t%d" % index] for index in range(len(docs))]
        cases += [["af.store_mode", "missing"], ["af.store_mode", "t0/config.toml"]]
        RECORD.append("store_mode: %d config files" % len(docs))
        self.same("store-mode", cases, setup=lambda root: write_corpus(root, docs))

    def test_usable_and_its_files(self):
        def setup(root):
            (root / "plain").mkdir()
            (root / "plain" / "auth.json").write_text("{}", encoding="utf-8")
            (root / "keyring").mkdir()
            (root / "keyring" / "config.toml").write_text("cli_auth_credentials_store = \"keyring\"\n", encoding="utf-8")
            (root / "keyring" / "auth.json").write_text("{}", encoding="utf-8")
            (root / "bad").mkdir()
            (root / "bad" / "config.toml").write_text("= 1", encoding="utf-8")
            (root / "nofile").mkdir()
            (root / "dir").mkdir()
            (root / "dir" / "auth.json").mkdir()
            (root / "binary").mkdir()
            (root / "binary" / "config.toml").write_bytes(b"\xff\xfe")
            (root / "configdir").mkdir()
            (root / "configdir" / "config.toml").mkdir()
        cases = [["af.usable", name] for name in ("plain", "keyring", "bad", "nofile", "dir", "binary", "configdir",
                                                   "missing")]
        self.same("usable", cases, setup=setup)

    def test_checks_and_names(self):
        values = [{"hex": ""}, {"hex": b"{}".hex()}, {"hex": b'{"a": 1}'.hex()}, {"hex": b"[1]".hex()},
                  {"hex": b"\xff".hex()}, {"hex": b"\xef\xbb\xbf{\"a\":1}".hex()}, {"hex": b'{"a": NaN}'.hex()},
                  {"hex": (b'{"a": "' + b"x" * 65520 + b'"}').hex()}, {"hex": (b'{"a": "' + b"x" * 65530 + b'"}').hex()},
                  {"hex": ("[" * 2000 + "]" * 2000).encode().hex()}, {"hex": ('{"a":' * 1100 + "1" + "}" * 1100).encode().hex()},
                  "text", 5, None, {"hex": b" {\"a\":1} ".hex()}, {"hex": b"{\"a\":1}x".hex()}]
        cases = [["af.check", each] for each in values]
        names = ["scratch-0123456789ab", "scratch-0123456789AB", "scratch-0123456789abc", "scratch-", "x.car-0123abcd",
                 ".car-0123abcd", "x.car-0123abc", "x.car-0123abcde", "auth.json.car-0123abcd", "auth.json.car-0123ABCD",
                 "a.b.car-01234567", "x.car-01234567.car-89abcdef", "\u00e9.car-00000000", "x.car-0000000g", ""]
        cases += [["af.names", each] for each in names]
        self.same("checks", cases)


class AppCloseDiff(AdvAccountDiff):
    def test_the_restart_manager_and_kernel32_calls(self):
        pids = [1234, 0, -5, True, 1.5, "7", None, 2 ** 32 + 5, 2 ** 70 + 9]
        createds = [133_000_000_000_000_000, 0, -1, False, 2 ** 64 + 3, 2 ** 64 - 1, "x"]
        scripts = [{}, {"RmStartSession": [5]}, {"RmStartSession": [[0, 77]]}, {"RmRegisterResources": [87]},
                   {"RmShutdown": [5]}, {"RmShutdown": [0], "RmEndSession": [3]}]
        cases = []
        for pid in pids:
            for created in createds:
                cases.append(["ap.ask_close", pid, created, scripts[0]])
        for script in scripts:
            cases.append(["ap.ask_close", 1234, 133_000_000_000_000_000, script])
        kernels = [{}, {"OpenProcess": [44]}, {"OpenProcess": [44], "WaitForSingleObject": [258]},
                   {"OpenProcess": [44], "WaitForSingleObject": [258], "GetProcessTimes": [133_000_000_000_000_000]},
                   {"OpenProcess": [44], "WaitForSingleObject": [258], "GetProcessTimes": [133_000_000_000_000_000],
                    "TerminateProcess": [1]},
                   {"OpenProcess": [44], "WaitForSingleObject": [258], "GetProcessTimes": [133_000_000_000_000_001],
                    "TerminateProcess": [1]},
                   {"OpenProcess": [44], "WaitForSingleObject": [0]},
                   {"OpenProcess": [44], "WaitForSingleObject": [258], "GetProcessTimes": [0]},
                   {"OpenProcess": [44], "WaitForSingleObject": [258], "GetProcessTimes": [133_000_000_000_000_000],
                    "TerminateProcess": [0]}]
        for kernel in kernels:
            cases.append(["ap.end_process", 1234, 133_000_000_000_000_000, kernel])
        for pid in pids:
            for created in createds:
                cases.append(["ap.end_process", pid, created, kernels[4]])
        RECORD.append("appclose: %d cases" % len(cases))
        self.same("appclose", cases)


def row(pid, parent, path, created=None, family=None):
    found = {"pid": pid, "parent": parent, "path": path, "family": family}
    if created is not None:
        found["created"] = created
    return found


MAIN = row(100, 4, APP, 1000, "OpenAI.Codex_2p2nqsd0c76g0")
SERVER = row(101, 100, ENGINE, 1001)
MAIN2 = row(200, 4, APP, 2000, "OpenAI.Codex_2p2nqsd0c76g0")
OTHER = row(300, 50, TUI, 3000)


class RestartDiff(AdvAccountDiff):
    def test_the_restart(self):
        running = [[MAIN, SERVER]]
        back = [[MAIN2]]
        hands = [
            {},
            {"inventory": ["raise:AdapterError"]},
            {"inventory": ["raise"]},
            {"inventory": [[MAIN, MAIN2]]},
            {"inventory": [[OTHER]]},
            {"inventory": running, "created": [None]},
            {"inventory": running, "created": [1000, 1000, 1000]},
            {"inventory": running + running + back, "created": [1000, None], "ask_close": [True], "newest": ["11111111-1c2d-7e3f-8a9b-0c1d2e3f4a5b"]},
            {"inventory": running + back, "created": [1000, None], "ask_close": [True], "newest": [None]},
            {"inventory": running + back, "created": [1000, None], "ask_close": [True], "newest": ["not-an-id"]},
            {"inventory": running + back, "created": [1000, None], "ask_close": ["raise"], "newest": ["raise"]},
            {"inventory": running + back, "created": [1000, 1000, 1000, None], "ask_close": [False],
             "end_process": [True], "newest": ["11111111-1c2d-7e3f-8a9b-0c1d2e3f4a5b"], "open": [False]},
            {"inventory": running + running + running + back, "created": [1000, 1000, None],
             "ask_close": [False], "end_process": ["raise"]},
            {"inventory": [[MAIN, SERVER]] * 3 + [[MAIN, SERVER]] * 70 + back, "created": [1000, None],
             "ask_close": [True], "newest": ["11111111-1c2d-7e3f-8a9b-0c1d2e3f4a5b"], "read": [{"present": False}]},
            {"inventory": running + back, "created": [1000, None], "ask_close": [True],
             "newest": ["11111111-1c2d-7e3f-8a9b-0c1d2e3f4a5b"], "read": [5]},
            {"inventory": running + back, "created": [1000, None], "ask_close": [True],
             "newest": ["11111111-1c2d-7e3f-8a9b-0c1d2e3f4a5b"], "read": ["raise:KeyError"]},
            {"inventory": running + running + [[]], "created": [1000, None], "ask_close": [True],
             "newest": ["11111111-1c2d-7e3f-8a9b-0c1d2e3f4a5b"]},
            {"inventory": running + ["raise"] + back, "created": [1000, None], "ask_close": [True],
             "newest": ["11111111-1c2d-7e3f-8a9b-0c1d2e3f4a5b"]},
            {"inventory": running * 50, "created": [1000] * 40 + [None]},
            {"inventory": running, "created": [1000, "raise", None], "ask_close": [True]},
        ]
        cases = []
        for hand in hands:
            for between in (None, {}, {"between": ["raise"]}):
                cases.append(["rs.restart", hand, between])
        RECORD.append("restart: %d cases" % len(cases))
        self.same("restart", cases)

    def test_the_busy_rule(self):
        quiet = {"history": True, "running": 0, "queued": 0}
        sources = [{"activity": [quiet]}, {"activity": [{"history": True, "running": 2, "queued": 0}]},
                   {"activity": [{"history": True, "running": 0, "queued": 1}]},
                   {"activity": [{"history": False, "running": 0, "queued": 0}]}, {"activity": [None]},
                   {"activity": ["raise"]}, {"activity": [{"history": True, "running": None, "queued": 0}]},
                   {"activity": [{"history": True, "running": -1, "queued": 0}]},
                   {"activity": [{"history": True, "running": 1.5, "queued": 0}]}]
        waiting = {"category": "usage_limit", "state": "waiting_for_usage"}
        stores = [{}, {"pending": ["raise"]}, {"status": ["raise"]}, {"status": [{"booted_at": 1767000000.0}]},
                  {"status": [5]}, {"status": [0]}, {"pending": [[waiting]]}, {"pending": [[dict(waiting, hold="x")]]},
                  {"pending": [[dict(waiting, cancel_requested=1)]]}, {"pending": [[dict(waiting, state="submitting")]]},
                  {"pending": [[dict(waiting, category="network")]]}, {"pending": [[5]]},
                  {"pending": [[dict(waiting, state=["x"])]]}, {"pending": [[dict(waiting, hold=True), 5]]},
                  {"pending": [[waiting, 5]]}]
        cases = []
        for store in stores:
            for source in sources[:3] + [sources[4]]:
                for ok in (True, False):
                    cases.append(["rs.busy", store, source, 1767225600.0, ok])
        for source in sources:
            cases.append(["rs.busy", {}, source, 1767225600, True])
        RECORD.append("busy: %d cases" % len(cases))
        self.same("busy", cases)


class SwapPureDiff(AdvAccountDiff):
    def test_meters_usage_and_room(self):
        windows = [None, [], [5], [{"used_percent": 10}], [{"used_percent": True}],
                   [{"used_percent": 12.345, "window_minutes": 300, "reset_at": 100}],
                   [{"used_percent": 99.95, "window_minutes": 10080, "reset_at": 1.5}],
                   [{"used_percent": 0.25, "window": "primary"}, {"used_percent": 0.35, "window": "secondary"}],
                   [{"used_percent": 1, "bucket": "codex", "window": "primary"},
                    {"used_percent": 2, "bucket": "other", "window": "primary"}],
                   [{"used_percent": 1, "bucket": "other", "window": "primary"}],
                   [{"used_percent": 1, "window": ["x"]}], [{"used_percent": 2 ** 1100, "window": "primary"}],
                   [{"used_percent": 1, "window_minutes": 1439}, {"used_percent": 2, "window_minutes": 1440}],
                   [{"used_percent": 1, "window_minutes": True, "window": "secondary"}],
                   [{"used_percent": -0.04, "window": "primary", "reset_at": True}]]
        cases = [["sw.meters", each] for each in windows]
        replies = [None, {}, {"rateLimits": {"primary": {"usedPercent": 50, "windowDurationMins": 300,
                                                          "resetsAt": 1767230000}}},
                   {"rateLimits": {"primary": {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": 1767230000},
                                   "secondary": {"usedPercent": 40, "windowDurationMins": 10080,
                                                 "resetsAt": 1767800000}}},
                   {"rateLimitsByLimitId": {"codex": {"limitId": "codex", "primary": {"usedPercent": 101,
                                                                                      "windowDurationMins": 300}}}},
                   {"rateLimits": {"primary": {"usedPercent": "x"}}}, {"rateLimits": 5},
                   {"rateLimits": {"secondary": {"usedPercent": 100, "windowDurationMins": 10080,
                                                 "resetsAt": 1767900000}}}]
        cases += [["sw.usage_of", each] for each in replies]
        founds = [{}, {"present": True, "own": True, "available": True, "most_used": 94.9},
                  {"present": True, "own": True, "available": True, "most_used": 95},
                  {"present": True, "own": True, "available": True, "most_used": True},
                  {"present": True, "own": True, "available": True, "most_used": "1"},
                  {"present": True, "own": False, "available": True, "most_used": 1},
                  {"present": 1, "own": True, "available": True, "most_used": 1}, 5]
        cases += [["sw.has_room", each] for each in founds[:-1]]
        knowns = [None, 5, {}, {"present": False}, {"present": None}, {"present": True}, {"present": True, "email": "a@b"},
                  {"present": True, "kind": "apikey"}, {"present": True, "email": 5}]
        cases += [["sw.known", each] for each in knowns]
        RECORD.append("swap readings: %d cases" % len(cases))
        self.same("swap-pure", cases)

    def test_other_engines(self):
        rows = [None, "x", [], [5], [{"pid": 1}], [OTHER], [MAIN, SERVER], [MAIN, SERVER, OTHER],
                [MAIN, row(101, 100, ENGINE)], [MAIN, row(101, 100, ENGINE, 999)], [MAIN, row(101, 100, ENGINE, 1000)],
                [MAIN, row(102, 101, TUI, 1003), row(101, 100, ENGINE, 1001)], [MAIN, row(101, 101, TUI, 1003)],
                [MAIN, row(101, 100, ENGINE, 1001), row(101, 100, ENGINE, 1002)],
                [MAIN, row(101, [1], ENGINE, 1001)], [MAIN, row([7], 100, ENGINE, 1001)],
                [MAIN, row(101, 100, ENGINE, "x")], [row(101, 100, ENGINE, 1001)],
                [MAIN, MAIN2, row(101, 100, ENGINE, 1001)], [MAIN, row(101, 100.0, ENGINE, 1001)],
                [dict(MAIN, path=5)], [MAIN, row(105, 100, APP.replace("ChatGPT.exe", "codex.exe"), 1001)]]
        cases = []
        for found in rows:
            for app_open in (True, False):
                for own in ([], [101], [300]):
                    cases.append(["sw.other_engines", found, app_open, own])
        worlds = [{"inventory": [[]]}, {"inventory": [[OTHER], [OTHER], []]}, {"inventory": [[OTHER]]},
                  {"inventory": ["raise", []]}, {"inventory": [[MAIN, SERVER]]}]
        for world in worlds:
            for seconds in (0, 1, 15.0):
                cases.append(["sw.engines_gone", world, seconds])
        readers = [{"read": [{"present": None}, {"present": None}, {"present": True, "email": "a@b"}]},
                   {"read": [{"present": None}]}, {"read": [{"present": False}]}, {"read": [5, {"present": False}]}]
        for reader in readers:
            for tries in (0, 1, 3):
                cases.append(["sw.read_answer", {}, reader, tries])
        RECORD.append("other engines, engines gone, read answer: %d cases" % len(cases))
        self.same("swap-engines", cases)


if __name__ == "__main__":
    print(json.dumps(RECORD))
