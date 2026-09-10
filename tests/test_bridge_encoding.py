"""The control bridge's wire is UTF-8, and says so.

The standalone settings window starts `controlcli` with its output redirected and decodes
what comes back as UTF-8. Python, given a redirected stdout on Windows, encodes with the
machine's ANSI code page - CP949 on a Korean install, CP1252 on a Western one - so the two
ends disagreed and every Korean label in the window arrived as mojibake. The Codex panel
was correct throughout, because the MCP server has always reconfigured its streams
explicitly; the window was the one caller that inherited whatever it was given.

What makes this worth a test rather than a one-line fix is how it hides. A developer
machine with `PYTHONIOENCODING=utf-8` in the environment runs the broken code perfectly:
the bug reproduces for users and not for the person looking for it. That is exactly what
happened here - the window was photographed rendering correct Korean from a shell that had
that variable set, while a user on the same machine saw it garbled.

So these tests run the bridge in a subprocess with the ambient configuration forced
*hostile*: `PYTHONIOENCODING=cp949` and UTF-8 mode off. Under those conditions the old
code emits CP949 bytes that do not decode as UTF-8 at all. Nothing here is Korean-specific;
the round-trip covers several scripts, because the contract is Unicode, not Korean.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# One string per script, plus a symbol and an astral character. If the wire is UTF-8 these
# all survive; under any single-byte or CJK code page at least one of them cannot even be
# encoded, which is the point.
SAMPLES = {
    "korean_ui": "자동 복구",
    "korean_status": "워처가 실행 중입니다",
    "korean_setting": "사용량 제한",
    "korean_action": "설정 저장",
    "korean_check": "테스트 ✓",
    "japanese": "再開しました",
    "chinese": "自动恢复",
    "russian": "автоматическое восстановление",
    "greek": "επανάληψη",
    "french": "réessai différé",
    "symbols": "→ ✓ ✗ · —",
    "astral": "🧩",
}

HOSTILE = {
    # The condition a Korean Windows install produces on its own, made explicit so the
    # test does not depend on the machine it runs on.
    "PYTHONIOENCODING": "cp949",
    "PYTHONUTF8": "0",
}


def run_bridge(script: str, extra_env=None) -> subprocess.CompletedProcess:
    """Run a snippet against the real module, with a hostile ambient encoding."""
    env = dict(os.environ)
    env.update(HOSTILE)
    env["PYTHONPATH"] = str(ROOT / "src")
    env.update(extra_env or {})
    return subprocess.run([sys.executable, "-c", script],
                          capture_output=True, env=env, cwd=str(ROOT), timeout=120)


class WireEncodingTests(unittest.TestCase):
    def test_the_emitted_bytes_are_utf8_whatever_the_code_page_says(self):
        payload = json.dumps(SAMPLES, ensure_ascii=True)
        script = (
            "import json,sys;"
            "from codex_auto_resume import controlcli;"
            "controlcli._use_utf8();"
            "controlcli._emit(json.loads(%r))" % payload)
        result = run_bridge(script)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        # Decoded here, deliberately, rather than trusting Python's own view of it.
        decoded = result.stdout.decode("utf-8")
        self.assertEqual(json.loads(decoded), SAMPLES,
                         "every sample must survive the wire unchanged")

    def test_the_bytes_are_not_the_ambient_code_page(self):
        """The failure this replaces: CP949 bytes read as UTF-8 by the other end."""
        script = ("from codex_auto_resume import controlcli;"
                  "controlcli._use_utf8();"
                  "controlcli._emit({'ko': %r})" % SAMPLES["korean_ui"])
        raw = run_bridge(script).stdout
        self.assertIn(SAMPLES["korean_ui"].encode("utf-8"), raw,
                      "the UTF-8 encoding of the string is not in the output")
        self.assertNotIn(SAMPLES["korean_ui"].encode("cp949"), raw,
                         "the output carries the ambient code page's bytes")

    def test_a_real_command_round_trips_the_interface_catalog(self):
        """End to end: the command the settings window actually calls."""
        script = ("import sys;"
                  "from codex_auto_resume.controlcli import main;"
                  "sys.exit(main(['--home', 'nowhere', 'strings']))")
        result = run_bridge(script, {"CODEX_AUTO_RESUME_LANG": "ko"})
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(payload["language"], "ko")
        from codex_auto_resume import interface
        self.assertEqual(payload["strings"], interface.STRINGS["ko"],
                         "the catalog did not survive the wire intact")

    def test_the_window_and_the_panel_agree_on_the_encoding(self):
        """Both callers redirect these streams; only one of them used to say so."""
        control = (ROOT / "src" / "codex_auto_resume" / "controlcli.py").read_text(encoding="utf-8")
        server = (ROOT / "src" / "codex_auto_resume" / "mcpserver.py").read_text(encoding="utf-8")
        for name, body in (("controlcli", control), ("mcpserver", server)):
            with self.subTest(name):
                self.assertIn('encoding="utf-8"', body,
                              "a redirected stream on Windows takes the ANSI code page "
                              "unless the protocol states otherwise")

    def test_the_settings_window_decodes_what_the_bridge_encodes(self):
        """The other half of the contract, in the caller that reads it."""
        source = (ROOT / "gui" / "SettingsApp.cs").read_text(encoding="utf-8")
        self.assertIn("StandardOutputEncoding = Encoding.UTF8", source,
                      "the window must decode the encoding the bridge declares")


if __name__ == "__main__":
    unittest.main()
