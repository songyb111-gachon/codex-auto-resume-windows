# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Stop hook's format: everything about how Codex declares, calls and hears a plugin's Stop hook, in one place.

Codex's hook interface is the least stable surface this edition touches (plans/v0619-design/D-stop-hook.md, Risks),
and the measurement MHK - Codex's own generated schema, read on a scratch Codex home - is what settles it for the
engine in force: the hook event's name, the input's key names, the output's decision words, and where and how a
plugin declares the hook. Until its record is made (docs/evidence/live/measurement-mhk.json) this is the recommended
reading - the shape Codex's hooks take in its documentation - and SETTLED_BY says so. MHK's verdict changes FORMAT,
here, and nothing else: the handler reads its input and writes its answer through it (hook/handler.py), and the
declaration writer writes the file it names (control/hookplugin.py).

Pure: a table and two builders, and nothing read.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HookFormat:
    # How Codex calls the hook: the event it fires on, and the input keys the handler keeps - every other key's value
    # is dropped unread (hook/handler.py, the allow-list).
    event: str                 # the Stop event's name, as the declaration and the input's event key say it
    event_key: str             # the input key naming the event
    thread_key: str            # the input key naming the conversation (Codex's thread id)
    turn_key: str              # the input key naming the turn that stopped, where Codex gives one
    active_key: str            # the input key saying the stop follows a hook's own block, where Codex gives one
    # How it is answered: one JSON object on standard output, or nothing at all to let the turn end.
    decision_key: str
    block_word: str
    reason_key: str
    # Where and how it is declared: a file at this path under the plugin's root, optionally named by the plugin's
    # manifest under `manifest_key`; the command as the launcher's absolute path in the installation's home
    # ("absolute") or as the path inside the plugin ("contained", the rule Codex keeps for an MCP command); and the
    # plugin roots it is written into - the installation's own (`<home>/app`, the marketplace Codex was given) and the
    # copy Codex keeps of this plugin (`<CODEX_HOME>/plugins/cache/<marketplace>/<plugin>/<version>`).
    file: tuple
    manifest_key: str | None
    command: str
    roots: tuple
    timeout_seconds: int


# The reading this build declares and answers in. MHK not yet made: the shape Codex documents for its hooks.
FORMAT = HookFormat(
    event="Stop", event_key="hook_event_name", thread_key="session_id", turn_key="turn_id",
    active_key="stop_hook_active",
    decision_key="decision", block_word="block", reason_key="reason",
    file=("hooks", "hooks.json"), manifest_key=None, command="absolute", roots=("installation", "codex_copy"),
    timeout_seconds=10,
)
# The measurement record FORMAT was read from, by its file's name, or None while MHK has not been made.
SETTLED_BY = None
COMMANDS = ("absolute", "contained")
ROOTS = ("installation", "codex_copy")


def allowed_keys(found=FORMAT) -> tuple:
    """The input keys the handler keeps, and the only ones whose values it ever reads."""
    return (found.event_key, found.thread_key, found.turn_key, found.active_key)


def declaration(command, found=FORMAT) -> dict:
    """The document the declaration file holds: the one Stop hook, running `command`."""
    return {"hooks": {found.event: [{"hooks": [{"type": "command", "command": command,
                                                 "timeout": found.timeout_seconds}]}]}}


def commands_in(document, found=FORMAT) -> list | None:
    """Every command `document` declares, in the shape `declaration` writes; None for a document of any other shape -
    which is never ours to remove."""
    try:
        groups = document["hooks"]
        if not isinstance(groups, dict) or not groups:
            return None
        found_commands = []
        for event, entries in groups.items():
            if not isinstance(event, str) or not isinstance(entries, list):
                return None
            for entry in entries:
                hooks = entry["hooks"] if isinstance(entry, dict) else None
                if not isinstance(hooks, list):
                    return None
                for hook in hooks:
                    command = hook.get("command") if isinstance(hook, dict) else None
                    if not isinstance(command, str):
                        return None
                    found_commands.append(command)
        return found_commands
    except (KeyError, TypeError):
        return None


def answer(reason, found=FORMAT) -> dict:
    """The block, with `reason` - the continuation Codex goes on with."""
    return {found.decision_key: found.block_word, found.reason_key: reason}
