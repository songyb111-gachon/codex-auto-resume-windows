"""Opening the settings window from the icon.

The one file of this package that starts a process, which is why `subprocess` is imported
here and why `tests/test_structural_invariants.py` names this path rather than the package.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

from ... import machine
from ...win import handover



# The pages the window will open on, from the one closed list (machine.PAGES): the value is
# spliced into a command line, so nothing else may ever reach it, whatever a caller passes.
PAGES = machine.PAGES

# v0.6.23 (the owner, 2026-11-11): the Dashboard's own dialogs a row of the popup's menu can open it on - Message for this
# conversation... and Add (or Change) words for this time... - by the names its `--dialog=` argument takes
# (gui/WindowReopen.cs RowDialogs). Like the page, nothing else may ever reach its command line.
ROW_DIALOGS = ("message", "once_words")


def row_argument(row) -> str:
    """`row` - (dialog, interruption id, thread id) - as the window's `--dialog=` value and its open request's second line:
    `<dialog>:<interruption id>:<thread id>`. Each part is checked first, strictly, because it is spliced into a command
    line: a dialog of ROW_DIALOGS, an interruption id as the product makes one (64 lowercase hex digits) and a
    conversation's UUID in its canonical text. Anything else is a mistake in the caller, and refused (ValueError)."""
    try:
        dialog, interruption_id, thread_id = row
    except (TypeError, ValueError):
        raise ValueError("not a row of the window") from None
    if dialog not in ROW_DIALOGS:
        raise ValueError("not a dialog of the window")
    if not machine.is_interruption_id(interruption_id):
        raise ValueError("not a row of the window")
    if not machine.is_uuid(thread_id):
        raise ValueError("not a row of the window")
    return "%s:%s:%s" % (dialog, interruption_id, thread_id)


def open_dashboard(home: Path, page: str = None, row=None) -> bool:
    """Start the settings window, if it is installed beside the watcher. v0.6.23: `row` - (dialog, interruption id,
    thread id), the popup's row menu's - opens it on Pending with that row and that dialog of its own for it; the window
    checks the row against the record, and a row no longer waiting opens Pending with nothing more."""
    # The page is checked before anything else, including whether there is a window to
    # open: a value that is not one of ours is a mistake in this file, and a mistake that
    # only shows up on machines where the window happens to be installed is a worse one.
    if page is not None and page not in PAGES:
        raise ValueError("not a page of the window")
    asked = None
    if row is not None:
        if page not in (None, "pending"):
            raise ValueError("a row is on Pending")
        page, asked = "pending", row_argument(row)
    exe = Path(home) / "CodexAutoResumeSettings.exe"
    if not exe.is_file():
        return False
    # v0.6.20 (issue #55): the window has no single-instance rule of its own, so every open from the icon, its
    # popup or a notification started one more window beside the one on screen. One of this installation that is
    # already open is asked first to come forward on the page (win/handover.py); only where none takes it is one
    # started.
    if (handover.hand_over(exe, page, asked) if asked is not None else handover.hand_over(exe, page)):
        return True
    arguments = [str(exe)]
    if page is not None:
        arguments.append("--page=" + page)
    if asked is not None:
        arguments.append("--dialog=" + asked)
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
    # A UUID's canonical text, the only thing put on its command line - the one check notify.chat_uri makes too
    # (domain/ids.py, through machine as the UI reads the domain), made again here because the value is spliced in.
    if not machine.is_uuid(thread_id):
        raise ValueError("not a conversation")
    exe = Path(home) / "CodexAutoResumeSettings.exe"
    if not exe.is_file():
        return False
    subprocess.Popen([str(exe), "--page=advanced", "--capability=codex_chat", "--chat=" + thread_id], cwd=str(home),
                     close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True
