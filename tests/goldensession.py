"""The replies the window and the panel receive, produced from one frozen machine.

v0.6.10-alpha splits the Python implementation, and the one thing it must not do is change
what a front end is handed. So before anything moves, both surfaces are recorded here, byte
for byte, and `test_golden_replies.py` fails on a single byte of difference.

A reply is only worth freezing if it is the same reply twice. Everything this machine would
otherwise put into one is pinned:

- the clock, to `NOW`, so every stored and echoed time is the same;
- the product version, to `VERSION`, so the golden does not churn on a release;
- the interface language, to English, so the vocabulary is not the machine's Windows setting;
- the compatibility document, to the frozen fixture the rest of the suite reads;
- the registry, to a fake key tree, and the watcher probe to "not running";
- the watcher launch, which would otherwise start a real process;
- the home directory, which is a temporary path, written out as `<HOME>`.

Rerun it with `python tests/goldensession.py --write` when a reply is *meant* to change, and
the diff in `fixtures/golden/` is then the review: every line of it has to be a change
somebody asked for.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
for entry in (str(SRC), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

GOLDEN = HERE / "fixtures" / "golden"
WINDOW = GOLDEN / "window.jsonl"
PANEL = GOLDEN / "panel.jsonl"

NOW = 1_800_000_000.0          # a fixed moment, so "7 days" and "until the reset" are fixed too
VERSION = "0.0.0-golden"
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER_THREAD = "0a1b2c3d-0003-7000-8000-000000000003"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
KEY = "a" * 64
OTHER_KEY = "b" * 64


def detection(key=KEY, thread_id=THREAD, category="usage_limit", ago=3600.0):
    return {"thread_id": thread_id, "turn_id": TURN, "completed_at": NOW - ago,
            "started_at": NOW - ago - 300.0, "ordinal": 2, "interruption_id": key,
            "reset_at": NOW + 1800.0, "limit_type": "codex.primary", "uncertain": False,
            "category": category}


# --------------------------------------------------------------------------- the window
# Reads first, then everything that changes something, then the same reads again, so the
# golden holds the transitions and not only the resting shapes.
WINDOW_SESSION = [
    ("status", None),
    ("settings", None),
    ("describe", None),
    ("strings", None),
    ("pending", None),
    ("pending-all", None),
    ("history", None),
    ("dashboard", None),
    ("statistics", {"days": 7}),
    ("timeline", {"interruption_id": KEY}),
    ("compatibility", {"live": False}),
    ("compat-import", {"path": "<HOME>/downloaded_compat.json"}),
    ("compat-refresh", {"live": False}),
    ("preview-continuation", {"interruption_id": KEY}),
    ("update", {"notifications": False, "max_recovery_attempts": 2}),
    ("enabled", {"enabled": False}),
    ("enabled", {"enabled": True}),
    ("startup", {"enabled": False}),
    ("interruption-recovery", {"category": "timeout", "enabled": False}),
    ("thread-enabled", {"thread_id": THREAD, "enabled": False}),
    ("failure-seen", None),
    ("reset-budget", {"interruption_id": KEY}),
    ("retry-now", {"interruption_id": KEY}),
    ("cancel", {"interruption_id": KEY}),
    ("cancel-thread", {"thread_id": OTHER_THREAD}),
    ("cancel-all", None),
    ("start-watcher", None),
    ("stop-watcher", None),
    ("clear-history", None),
    ("defaults", None),
    ("diagnostics", {"path": "<HOME>/diagnostics.json"}),
    ("status", None),
    ("pending-all", None),
    ("dashboard", None),
]
# Refusals belong in the golden too: their wording and their codes are what a front end shows.
WINDOW_REFUSALS = [
    '{"id": 900, "command": "no-such-command"}',
    '{"id": 901, "command": "cancel", "argument": {"interruption_id": "nope"}}',
    '{"id": 902, "command": "statistics", "argument": {"days": "soon"}}',
    "not json at all",
    '["a list, not an object"]',
]

# --------------------------------------------------------------------------- the panel
PANEL_SESSION = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "golden", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
    {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"},
]
PANEL_CALLS = [
    ("get_status", {}),
    ("list_pending", {}),
    ("list_pending", {"include_finished": True}),
    ("get_recovery_statistics", {"days": 7}),
    ("get_recovery_timeline", {"interruption_id": KEY}),
    ("preview_recovery_message", {"category": "usage_limit"}),
    ("open_settings", {}),
    ("update_settings", {"notifications": False}),
    ("pause_auto_recovery", {}),
    ("resume_auto_recovery", {}),
    ("disable_conversation_recovery", {"thread_id": THREAD}),
    ("enable_conversation_recovery", {"thread_id": THREAD}),
    ("reset_recovery_budget", {"interruption_id": KEY}),
    ("retry_now", {"interruption_id": KEY}),
    ("cancel_recovery", {"interruption_id": KEY}),
    ("clear_recovery_history", {}),
    ("restore_default_settings", {}),
    ("start_watcher", {}),
    ("cancel_recovery", {"interruption_id": "nope"}),          # the refusal shape
    ("no_such_tool", {}),
]


class _FakeProcess:
    """What a launch returns, without launching anything."""
    pid = 4242

    def poll(self):
        return None


def _settle(control):
    """The reply to `start-watcher` without a process to confirm: one fixed answer."""
    return {"confirmed": False, "state": "unconfirmed", "reason": "not confirmed in a golden run"}


class Frozen:
    """One machine, held still, with a home that is thrown away afterwards."""

    def __init__(self):
        self.stack = ExitStack()

    def __enter__(self):
        from codex_auto_resume import config, control as control_module, startup
        from codex_auto_resume.store import Store
        import frozen_registry
        from test_cli import FakeWinreg

        self.temporary = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.home = Path(self.temporary)
        self.paths = config.Paths(self.home)
        self.paths.ensure()

        self.stack.enter_context(patch.dict(os.environ, {"CODEX_AUTO_RESUME_LANG": "en"}))
        self.stack.enter_context(patch("time.time", lambda: NOW))
        self.stack.enter_context(patch.object(config, "version", lambda: VERSION))
        self.stack.enter_context(patch.object(control_module.Control, "watcher_running",
                                              return_value=False))
        self.stack.enter_context(patch.object(control_module.Control, "startup_enabled",
                                              return_value=False))
        self.stack.enter_context(patch.object(startup, "_winreg", return_value=FakeWinreg()))
        self.stack.enter_context(patch.object(control_module.Control, "_launch_watcher",
                                              lambda self, *a, **k: _FakeProcess()))
        self.stack.enter_context(patch.object(control_module.Control, "_confirm_watcher",
                                              lambda self, process: _settle(self)))
        self.stack.enter_context(frozen_registry.frozen())
        # What a bootstrap download leaves for `compat-import` to read: the frozen document.
        (self.home / "downloaded_compat.json").write_bytes(frozen_registry.FROZEN.read_bytes())

        with Store(self.paths.state_dir) as store:
            store.register(detection(), NOW - 3600.0)
            store.register(detection(key=OTHER_KEY, thread_id=OTHER_THREAD,
                                     category="network_transient", ago=7200.0), NOW - 7200.0)
        self.control = control_module.Control(self.paths)
        return self

    def __exit__(self, *exc):
        self.stack.close()
        return False

    def tidy(self, text: str) -> str:
        """The temporary home, however it was written, becomes <HOME>."""
        home = str(self.home)
        for form in (json.dumps(home)[1:-1], home.replace("\\", "/"), home):
            text = text.replace(form, "<HOME>")
        return text


def window_lines(frozen) -> str:
    from codex_auto_resume import controlcli
    requests = []
    for number, (command, argument) in enumerate(WINDOW_SESSION, 1):
        request = {"id": number, "command": command}
        if argument is not None:
            request["argument"] = json.loads(json.dumps(argument).replace(
                "<HOME>", json.dumps(str(frozen.home))[1:-1]))
        requests.append(json.dumps(request))
    requests += WINDOW_REFUSALS
    out = io.StringIO()
    controlcli.serve(frozen.control, io.StringIO("\n".join(requests) + "\n"), out)
    return frozen.tidy(out.getvalue())


def panel_lines(frozen) -> str:
    from codex_auto_resume import mcpserver
    messages = list(PANEL_SESSION)
    for number, (name, arguments) in enumerate(PANEL_CALLS, 100):
        messages.append({"jsonrpc": "2.0", "id": number, "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}})
    messages.append({"jsonrpc": "2.0", "id": 500, "method": "resources/read",
                     "params": {"uri": mcpserver.SETTINGS_UI}})
    lines = "".join(json.dumps(message) + "\n" for message in messages) + "not json at all\n"
    out = io.StringIO()
    mcpserver.Server(frozen.control, io.StringIO(lines), out).serve()
    return frozen.tidy(digest_the_document(out.getvalue()))


def digest_the_document(text: str) -> str:
    """The settings page is one HTML document of its own; the line keeps its fingerprint.

    Freezing 150 KB of HTML in a fixture would make every honest edit to the panel a wall of
    diff and every review of it a formality. Its length and digest change on one byte just
    the same, which is all this net is for.
    """
    import hashlib
    kept = []
    for line in text.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            kept.append(line)
            continue
        contents = (message.get("result") or {}).get("contents") if isinstance(message, dict) else None
        for item in contents or []:
            body = item.get("text")
            if isinstance(body, str):
                raw = body.encode("utf-8")
                item["text"] = "<document sha256=%s bytes=%d>" % (
                    hashlib.sha256(raw).hexdigest(), len(raw))
        kept.append(json.dumps(message, ensure_ascii=False, default=str) if contents else line)
    return "\n".join(kept) + "\n"


def produce() -> dict:
    with Frozen() as frozen:
        window = window_lines(frozen)
    with Frozen() as frozen:                     # the panel gets its own untouched machine
        panel = panel_lines(frozen)
    return {WINDOW: window, PANEL: panel}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    produced = produce()
    if "--write" in argv:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for path, text in produced.items():
            path.write_text(text, encoding="utf-8", newline="\n")
            print("wrote %s (%d lines)" % (path.name, len(text.splitlines())))
        return 0
    for path, text in produced.items():
        stored = path.read_text(encoding="utf-8") if path.exists() else ""
        print("%s: %s" % (path.name, "same" if stored == text else "DIFFERENT"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
