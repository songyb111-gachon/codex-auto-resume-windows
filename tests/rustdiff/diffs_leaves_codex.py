"""S1.1, car-config's installation root, product version and Codex discovery, held to the reference tag.

Each case names a scratch tree (`@` is its root, made once for the reference and once for Rust); the answers are equal
with the root as `@`. Covered: `_project_root` over the layouts it was written for (a checkout, an installed `app/`, a
copy of the sources with no manifest, a module moved deeper, a manifest above a module that is not in its `src/`, too
shallow a path), `read_version` over a manifest of every kind (BOM, CRLF, not UTF-8, not JSON, NaN, a list, no version,
a blank one, a directory), `version()` and the one warning it tells, `codex_home`, the candidate engines under a
scratch `LOCALAPPDATA`, and `discover_codex_exe` with every rule of its docstring (named paths, ambiguity, the app's
own server, the engines the app runs outside `bin`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from rustdiff.diffs_leaves_config import ENV, ConfigBase

RECORD: list[str] = []


def write(path: Path, body, binary: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(body, encoding="utf-8", newline="")


class CodexDiff(ConfigBase):
    def test_root_version_discovery(self):
        manifest = ".codex-plugin/plugin.json"
        package = "codex_auto_resume"

        def tree(root: Path):
            for place in ("inst", "deep", "outer"):
                write(root / place / manifest, json.dumps({"version": "1.2.3"}))
                write(root / place / "src" / package / "config.py", "")
            write(root / "deep/src" / package / "sub/deeper/config.py", "")
            write(root / "nomanifest/src" / package / "config.py", "")
            write(root / "other" / manifest, json.dumps({"version": "9"}))
            write(root / "other/src/else/config.py", "")
            write(root / "outer/inner/src" / package / "config.py", "")
            write(root / "outer/inner" / manifest, "{}")
            write(root / "shallow.py", "")
            kinds = {
                "ok": json.dumps({"version": "0.6.26-beta.2"}), "bom": b"\xef\xbb\xbf" + json.dumps({"version": "1.0"}).encode(),
                "crlf": '{\r\n "version": "2.0"\r\n}\r\n', "bad_utf8": b'{"version": "\xff"}', "not_json": "version: 1", "nan": '{"version": "1", "x": NaN}',
                "infinity": '{"x": [Infinity, -Infinity], "version": "1.5"}', "list": "[1]", "no_version": "{}", "number": '{"version": 1}',
                "blank": '{"version": "   "}', "padded": '{"version": " 1.0 "}', "null": '{"version": null}', "empty": "", "twice": '{"version": "a", "version": "b"}',
                "deep": "[" * 5000 + "]" * 5000, "string_root": '"x"', "bom_twice": b"\xef\xbb\xbf\xef\xbb\xbf{}", "trailing": '{"version": "1"} x',
                "unicode": json.dumps({"version": "\u00e9\u4e2d"}, ensure_ascii=False).encode("utf-8"),
            }
            for name, body in kinds.items():
                write(root / "manifests" / (name + ".json"), body)
                write(root / "v" / name / manifest, body)
            (root / "manifests" / "folder.json").mkdir()
            (root / "v" / "none").mkdir()
            # engines under a scratch LOCALAPPDATA
            def engine(local: str, build: str, exe: bool = True):
                (root / local / "OpenAI/Codex/bin" / build).mkdir(parents=True, exist_ok=True)
                if exe:
                    write(root / local / "OpenAI/Codex/bin" / build / "codex.exe", "MZ")
            engine("local1", "aa11")
            engine("local1", "Cc33")
            engine("local1", "zz9")
            engine("local1", "dd44", exe=False)
            (root / "local1/OpenAI/Codex/bin/ee55/codex.exe").mkdir(parents=True)
            write(root / "local1/OpenAI/Codex/bin/loose.txt", "x")
            for build in ("aa11", "bb22"):
                engine("local2", build)
            engine("local4", "ff66")
            for build in ("0a", "1b", "2c"):
                engine("local5", build)
            (root / "local3/OpenAI/Codex/bin").mkdir(parents=True)
            write(root / "local6/OpenAI/Codex/bin", "a file, not a folder")
            (root / "local7").mkdir()
            write(root / "named/codex.exe", "MZ")
            write(root / "named2/codex.exe", "MZ")
            (root / "named3").mkdir()
            write(root / "elsewhere/app1/codex.exe", "MZ")
            write(root / "elsewhere/app2/codex.exe", "MZ")
            write(root / "elsewhere/aa11/codex.exe", "MZ")
        template = []
        for module in ("@/inst/src/%s/config.py" % package, "@/deep/src/%s/sub/deeper/config.py" % package, "@/nomanifest/src/%s/config.py" % package,
                       "@/other/src/else/config.py", "@/outer/inner/src/%s/config.py" % package, "@/shallow.py", "@/inst/config.py",
                       "@/inst/src/%s/missing/deeper/than/five/levels/config.py" % package, "@/INST/SRC/%s/CONFIG.py" % package.upper()):
            for levels in (1, 2, 3, 5, 8):
                template.append(["config.project_root", module, levels, package])
        template += [["config.project_root", "C:\\x.py", 5, package], ["config.project_root", "x.py", 5, package]]
        for name in ("ok", "bom", "crlf", "bad_utf8", "not_json", "nan", "infinity", "list", "no_version", "number", "blank", "padded", "null", "empty",
                     "twice", "deep", "string_root", "bom_twice", "trailing", "unicode", "folder", "missing"):
            template.append(["config.read_version", "@/manifests/%s.json" % name])
        for name in ("ok", "bom", "crlf", "bad_utf8", "not_json", "nan", "list", "no_version", "blank", "empty", "deep", "none", "missing"):
            template.append(["config.version", "@/v/" + name])
        for env in (dict(ENV), dict(ENV, CODEX_HOME="@/profile/.mycodex"), dict(ENV, CODEX_HOME="~\\viaprofile"), dict(ENV, CODEX_HOME=""),
                    {"SYSTEMROOT": ENV["SYSTEMROOT"]}, {"SYSTEMROOT": ENV["SYSTEMROOT"], "HOMEPATH": "@\\hp", "HOMEDRIVE": ""}):
            template.append(["config.codex_home", env, "@/", False])
        for local in ("local1", "local2", "local3", "local4", "local5", "local6", "local7", "missing", ""):
            env = dict(ENV, LOCALAPPDATA="@/" + local) if local else {"SYSTEMROOT": ENV["SYSTEMROOT"]}
            template += [["config.codex_bin_dir", env], ["config.candidates", env, "@/", False]]
        running = ["@/local2/OpenAI/Codex/bin/bb22/codex.exe", "@/elsewhere/app1/codex.exe", "@/elsewhere/aa11/codex.exe",
                   "@/local2/OpenAI/Codex/bin/BB22/CODEX.EXE", "@/elsewhere/app1/codex.exe", "@/nowhere/codex.exe"]
        def case(explicit, local, rules, runs, ask=False, ask_none=False, env_extra=None):
            env = dict(ENV, LOCALAPPDATA="@/" + local) if local else {"SYSTEMROOT": ENV["SYSTEMROOT"]}
            env.update(env_extra or {})
            return ["config.discover", explicit, env, "@/", rules, runs, ask, ask_none, False]
        for local in ("local1", "local2", "local3", "local4", "local5", "local6", "local7", "missing", ""):
            for rules in ({}, {"aa11": "version_runs"}, {"aa11": "version_runs", "bb22": "queue_flags"}, {"aa11": "x" * 60}, {"aa11": "Bad Reason", "bb22": "version_runs"},
                          {"0a": "a", "1b": "b", "2c": "a"}, {"ff66": "official_location"}):
                template.append(case(None, local, rules, None))
        for runs in (None, [], ["@/local2/OpenAI/Codex/bin/bb22/codex.exe"], ["@/local2/OpenAI/Codex/bin/aa11/codex.exe", "@/local2/OpenAI/Codex/bin/bb22/codex.exe"],
                     ["@/elsewhere/app1/codex.exe"], ["@/elsewhere/app1/codex.exe", "@/elsewhere/app2/codex.exe"], running, "fail", ["@/LOCAL2/openai/codex/BIN/bb22/Codex.exe"]):
            for ask, ask_none in ((False, False), (True, False), (False, True), (True, True)):
                for local, rules in (("local2", {}), ("local2", {"aa11": "version_runs"}), ("local3", {}), ("local3", {"app1": "queue_flags"}),
                                     ("local1", {"aa11": "stale"}), ("local5", {"0a": "q"})):
                    template.append(case(None, local, rules, runs, ask, ask_none))
        for explicit in ("@/named/codex.exe", "@/named2/codex.exe", "@/named3/codex.exe", "@/missing.exe", "@/named", "~\\nothing", "", None):
            for rules in ({}, {"named": "queue_flags"}, {"named": "Not A Code"}):
                template.append(case(explicit, "local1", rules, None))
                template.append(case(explicit, "local1", rules, ["@/elsewhere/app1/codex.exe"], True, True,
                                     {"CODEX_AUTO_RESUME_CODEX_EXE": "@/named2/codex.exe"}))
        template.append(case(None, "local2", {}, None, env_extra={"CODEX_AUTO_RESUME_CODEX_EXE": "@/named2/codex.exe"}))
        template.append(case(None, "local2", {}, None, env_extra={"CODEX_AUTO_RESUME_CODEX_EXE": "@/named3"}))
        expected = self.pair("codex", template, tree=tree)
        errors = sorted({result["ok"]["config_error"] for result in expected if isinstance(result.get("ok"), dict) and "config_error" in result["ok"]})
        self.assertGreaterEqual(len(errors), 8, errors)
        RECORD.append("config: %d cases of _project_root, read_version, version() (told once), codex_home, codex_bin_dir, the candidate engines "
                      "and discover_codex_exe equal the tag's; %d different ConfigError sentences reached" % (len(template), len(errors)))
