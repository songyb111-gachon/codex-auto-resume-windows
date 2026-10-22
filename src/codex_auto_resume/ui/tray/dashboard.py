"""Opening the settings window from the icon.

The one file of this package that starts a process, which is why `subprocess` is imported
here and why `tests/test_structural_invariants.py` names this path rather than the package.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

from ... import machine



# The pages the window will open on, from the one closed list (machine.PAGES): the value is
# spliced into a command line, so nothing else may ever reach it, whatever a caller passes.
PAGES = machine.PAGES
# A conversation id as the chat is opened at (open_chat): a UUID's canonical text, the only thing put on its command
# line - the same shape notify.chat_uri reads, checked again here because the value is spliced into an argument.
_CONVERSATION = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def open_dashboard(home: Path, page: str = None) -> bool:
    """Start the settings window, if it is installed beside the watcher."""
    # The page is checked before anything else, including whether there is a window to
    # open: a value that is not one of ours is a mistake in this file, and a mistake that
    # only shows up on machines where the window happens to be installed is a worse one.
    if page is not None and page not in PAGES:
        raise ValueError("not a page of the window")
    exe = Path(home) / "CodexAutoResumeSettings.exe"
    if not exe.is_file():
        return False
    arguments = [str(exe)]
    if page is not None:
        arguments.append("--page=" + page)
    # The caller is the watcher, under pythonw.exe with no console. The window is a GUI program
    # (build/make_gui.ps1 compiles it /target:winexe), so no console is made for it and the flag
    # changes nothing today. It is here so this start obeys the one rule every other start does
    # (tests/test_no_console_windows.py), and stays hidden if the target is ever a console one.
    subprocess.Popen(arguments, cwd=str(home), close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True


def open_chat(home: Path, thread_id: str) -> bool:
    """Start the settings window at the advanced edition's chat with one conversation (v0.6.19): a click on a notice
    goes there while the chat is on (notifier.click_uri). Only a UUID in its canonical text is put on the command line;
    the advanced window reads `--chat=` (advanced/gui/AdvancedChat.cs) and the standard one ignores all three."""
    if not isinstance(thread_id, str) or not _CONVERSATION.fullmatch(thread_id):
        raise ValueError("not a conversation")
    exe = Path(home) / "CodexAutoResumeSettings.exe"
    if not exe.is_file():
        return False
    subprocess.Popen([str(exe), "--page=advanced", "--capability=codex_chat", "--chat=" + thread_id], cwd=str(home),
                     close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True
