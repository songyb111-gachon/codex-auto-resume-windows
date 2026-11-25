"""S7.2c: codex/inuse.py as the v0.6.26 final has it, and codex/protocol.py's tables and refusals, held equal to the tag.

inuse: random walks of `tell`, `told`, `forget`, `saw`, `elsewhere` and `home` over two installations (each named in
several spellings: case, slashes), three engines (case and slash variants of the told one, and others) and the paths a
look saw the app main run instead - the final's units (FINAL-DELTA rows 20-23): what is kept only where the look was
made on the told codex.exe (case-folded), forgotten on every new telling and on `forget`, and what core's
`_served_elsewhere` would read back through the plug (`elsewhere`). The cases of advanced/tests/
test_advanced_meter_engine_elsewhere.py's `LiveCaseTests` (:125, :163, :171) are walks of these. Then `backend`: the
told engine checked (fake engines signed and not), and, told nothing, the `codex_exe` setting, and discovery under a
scratch LOCALAPPDATA with none, one, two and failing official engines.

protocol: every table (each measurement's and capability's methods, the forbidden ones, the refusals and the accepting
words), `reply_to` over every request shape, `_grants_nothing`, `methods_for` and `methods_for_capability`.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advcodex_inuse`.
"""
from __future__ import annotations

import json
from pathlib import Path
import random

from rustdiff.advcodex import AdvCodexDiff, Engine
from rustdiff.diffs_advcodex_autocheck import SIGNER, engine_script

RECORD: list = []
MEASUREMENTS = ["m1", "m2", "m2b", "m3", "m4", "m5", "m6", "m7", "mh", "ma", "mw", "mp1", "mp2", "mp3", "mu", "mn", "mr",
                "mq", "me", "ms", "mk", "mt", "mipc", "maws", "mcloud", "m6b", "mo", "mx", "mxa", "mf", "m3b", "mb", "mc1",
                "mc2", "mqo", "mqp", "mqg", "mtok", "mopen", "mal", "malr", "mwake", "mhk", "m4b", "manchor", "mimg",
                "msteer", "msteer2", "mgave", "mb2", "mprofile", "mswap", "mauto"]
CAPABILITIES = ["marker_free_continuation", "goal_continuation", "reset_credit", "reset_message", "headless_run",
                "compact_continue", "model_fallback", "codex_chat", "prompt_queue", "usage_meter", "window_anchor",
                "account_switch", "codex_retry_settings", "account_auto_switch", "nothing", ""]
REQUESTS = ["item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval",
            "execCommandApproval", "applyPatchApproval", "item/tool/requestUserInput", "mcpServer/elicitation/request",
            "account/chatgptAuthTokens/refresh", "attestation/generate", "item/tool/call", "account/login", "x"]


def spellings(path: Path) -> list:
    text = str(path)
    return [text, text.upper(), text.lower(), text.replace("\\", "/"), text + "\\", text.replace("\\", "\\\\")]


class InuseDiff(AdvCodexDiff):
    def test_the_walks(self):
        rng = random.Random(7206)
        homes = [self.root / "inst-a", self.root / "inst-b"]
        exes = [self.root / "engines" / "bin" / "codex.exe", self.root / "engines" / "pkg" / "app" / "codex.exe",
                self.root / "engines" / "other.exe"]
        for each in exes:
            each.parent.mkdir(parents=True, exist_ok=True)
            each.write_bytes(b"MZ")
        codex = self.root / "codex-home"
        codex.mkdir(exist_ok=True)
        cases = [["iu.reset"]]
        for _ in range(1500):
            home = rng.choice(spellings(rng.choice(homes)) + [None])
            exe = rng.choice(spellings(rng.choice(exes)) + [None])
            op = rng.choice(["tell", "tell", "told", "forget", "saw", "saw", "saw", "elsewhere", "elsewhere", "home"])
            if op == "tell" and home is not None and exe is not None:
                cases.append(["iu.tell", home, exe, str(codex)])
            elif op == "forget" and home is not None:
                cases.append(["iu.forget", home])
            elif op == "saw":
                served = rng.choice([[], [str(exes[1])], [str(exes[1]), str(exes[2])], [str(exes[1]).upper()], None])
                cases.append(["iu.saw", home, {"codex_exe": exe, "served_elsewhere": served}])
            elif op in ("told", "elsewhere", "home"):
                cases.append(["iu.%s" % op, home])
        self.same("walks", cases)
        RECORD.append("inuse: %d steps of tell/told/forget/saw/elsewhere/home" % len(cases))

    def test_backend(self):
        good = Engine(self.root / "be-good", *engine_script("whole"))
        flagless = Engine(self.root / "be-flag", *engine_script("flag"))
        unsigned = Engine(self.root / "be-unsigned", *engine_script("whole"))
        world = {"signers": {good.exe.lower(): SIGNER, flagless.exe.lower(): SIGNER}}
        codex = self.root / "be-codex"
        codex.mkdir(exist_ok=True)
        home = self.root / "be-home"
        cases = [["iu.reset"], ["iu.backend", None], ["iu.backend", str(home)], ["iu.home", None], ["iu.pinned", str(home)]]
        for engine in (good, flagless, unsigned):
            cases += [["iu.tell", str(home), engine.exe, str(codex)], ["iu.backend", str(home)],
                      ["iu.saw", str(home), {"codex_exe": engine.exe.upper(), "served_elsewhere": [good.exe]}],
                      ["iu.elsewhere", str(home)], ["iu.home", str(home)]]
        cases.append(["iu.forget", str(home)])
        for pinned in (good.exe, flagless.exe, str(self.root / "missing.exe"), ""):
            settings = home / "config"

            def setup(settings=settings, pinned=pinned):
                settings.mkdir(parents=True, exist_ok=True)
                (settings / "settings.json").write_text(json.dumps({"codex_exe": pinned}), encoding="utf-8")

            self.scene("pinned %s" % Path(pinned).parent.name, [["iu.reset"], ["iu.pinned", str(home)],
                                                                  ["iu.backend", str(home)]],
                       setup, [home], world=world, engines=[good, flagless])
        self.scene("told", cases, lambda: home.mkdir(parents=True, exist_ok=True), [home], world=world,
                   engines=[good, flagless, unsigned])

    def test_discovery(self):
        """Told nothing and pinned nothing: the official folder under the scratch LOCALAPPDATA (the profile)."""
        for count in (0, 1, 2):
            for failing in (False, True):
                profile = self.fresh("discovery-%d-%s" % (count, failing))
                engines = []
                for index in range(count):
                    kind = "flag" if failing and index == 0 else "whole"
                    folder = profile / "OpenAI" / "Codex" / "bin" / ("%040x" % (index + 1))
                    engines.append(Engine(folder, *engine_script(kind)))
                self.scene("discovery %d %s" % (count, failing), [["iu.reset"], ["iu.backend", None], ["iu.home", None]],
                           lambda: None, [], engines=engines, profile=profile)

    def test_protocol(self):
        rng = random.Random(7207)
        cases = [["pr.tables"]]
        cases += [["pr.methods_for", m] for m in MEASUREMENTS + ["mzz"]]
        cases += [["pr.methods_for_capability", c] for c in CAPABILITIES]
        for method in REQUESTS + [5, None]:
            for ident in (1, "x", None, [1], 2.5):
                cases.append(["pr.reply_to", {"id": ident, "method": method, "params": {"decision": "accept"}}])
        cases += [["pr.reply_to", value] for value in (None, [], "x", {}, {"method": "execCommandApproval"})]
        values = [{}, {"decision": "decline"}, {"decision": "accept"}, {"permissions": {}, "scope": "turn"},
                  {"permissions": {"x": 1}}, {"scope": "session"}, {"scope": None}, {"answers": {}}, {"answers": {"a": 1}},
                  {"content": None}, {"content": 1}, {"x": ["allow"]}, {"allow": 1}, [], None, "decline",
                  {"decision": {"denied": {"rejection": "approved"}}}, {"permissions": [], "answers": None}]
        cases += [["pr.grants_nothing", value] for value in values]
        for _ in range(200):
            value = {rng.choice(["decision", "permissions", "answers", "content", "scope", "x"]):
                     rng.choice([{}, [], None, "turn", "accept", {"session": 1}, ["approved"], 0]) for _ in range(rng.randint(0, 3))}
            cases.append(["pr.grants_nothing", value])
        self.same("protocol", cases)
        RECORD.append("protocol: the tables, %d replies and refusals" % len(cases))
