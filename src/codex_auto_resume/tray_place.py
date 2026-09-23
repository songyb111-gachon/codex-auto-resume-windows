"""Where Windows keeps the notification-area icon, and whether the machine is saving power.

The two questions `tray.py` asks Windows before it moves the icon that are about neither the
icon's own drawing nor this product's settings, and the reading they take:

  * where Windows keeps the icon. Rule 2 of v0.6.5's motion holds the icon still in the overflow
    flyout, where nobody would see it move and every frame still costs explorer.exe the work of
    drawing it. The shell cannot be asked: on Windows 11 (build 26200) `Shell_NotifyIconGetRect`
    gives an icon in the flyout the overflow button's own rectangle rather than nothing, so the
    rectangle said the icon was on the taskbar and it moved unseen. Windows' own settings for the
    icon say it instead (`IconPlacement`);
  * whether Windows' battery saver is on, which holds every surface's motion still.

Everything here reads: nothing writes a registry value or changes a Windows setting, and nothing
it reads is stored or sent (PRIVACY.md, "Notifications"). Off Windows every answer is the one that
changes nothing.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import sys
import time

from . import win

_dll = win.library()      # handles of this module's own


class GUID(C.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", C.c_ubyte * 8)]


# One key per notification-area icon, holding the path of the program that added it, the icon's uID, and
# `IsPromoted` 1 for an icon Windows shows on the taskbar; an icon it has not promoted is in the overflow flyout.
# `TRAY_NOTIFY`'s `SystemTrayChevronVisibility` is 0 where the flyout is turned off and every icon is on the taskbar.
NOTIFY_ICON_SETTINGS = r"Control Panel\NotifyIconSettings"
TRAY_NOTIFY = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\TrayNotify"


def process_image() -> str:
    """This process's program, as Windows writes it in an icon's settings."""
    if os.name == "nt":
        try:
            buffer = C.create_unicode_buffer(32768)
            if _dll("kernel32").GetModuleFileNameW(None, buffer, len(buffer)):
                return buffer.value
        except Exception:
            pass
    return sys.executable


def known_folder(guid: str):
    """The folder Windows means by a known-folder GUID, or None where it will not say."""
    try:
        shell32, ole32 = _dll("shell32"), _dll("ole32")
        folder = GUID()
        if ole32.CLSIDFromString(guid, C.byref(folder)) != 0:
            return None
        path = C.c_wchar_p()
        if shell32.SHGetKnownFolderPath(C.byref(folder), 0, None, C.byref(path)) != 0:
            return None
        try:
            return path.value
        finally:
            ole32.CoTaskMemFree(path)
    except Exception:
        return None


class CurrentUserKeys:
    """HKEY_CURRENT_USER, read only: the names of a key's subkeys, and one value of a key."""

    def subkeys(self, path: str) -> list:
        import winreg                                    # noqa: WPS433 - Windows-only module
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
            return [winreg.EnumKey(key, index) for index in range(winreg.QueryInfoKey(key)[0])]

    def value(self, path: str, name: str):
        import winreg                                    # noqa: WPS433 - Windows-only module
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
                return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None


class IconPlacement:
    """Whether Windows keeps this process's icon in the overflow flyout, from Windows' own settings for it.

    The entries for this icon - this program's path and this uID - are looked for once and then read on each tick,
    so a person dragging the icon onto the taskbar, or off it, is seen within a second. An icon Windows has not
    written settings for yet is looked for again, but no oftener than LOOK_AGAIN_S; anything else it will not answer
    - Windows 10, which keeps no such key, a key that cannot be read - leaves the rule as it was.
    """

    LOOK_AGAIN_S = 30.0

    def __init__(self, executable=None, uid=1, *, reader=None, folders=None, clock=time.monotonic):
        self.executable = _same_path(executable if executable is not None else process_image())
        self.uid = int(uid)
        self.clock = clock
        self._reader = reader if reader is not None else CurrentUserKeys()
        self._folders = folders if folders is not None else known_folder
        self._entries = []          # the settings keys of this icon, once they have been found
        self._looked = None         # when they were last looked for

    def overflowed(self):
        """True while Windows says the icon is in the overflow flyout, False while it says the icon is on the
        taskbar or shows every icon, None where Windows does not say."""
        try:
            if self._reader.value(TRAY_NOTIFY, "SystemTrayChevronVisibility") == 0:
                return False                             # no flyout at all: every icon is on the taskbar
            promoted = self._promoted()
            if promoted is None:
                now = self.clock()
                if self._looked is not None and now - self._looked < self.LOOK_AGAIN_S:
                    return None
                self._looked = now
                self._entries = self._find()
                promoted = self._promoted()
            return None if promoted is None else not promoted
        except Exception:
            return None

    def _promoted(self):
        """True where Windows shows one of this icon's entries on the taskbar, False where it shows none of them,
        None where there is no entry of this icon's left to say."""
        answer = None
        for path in self._entries:
            if self._reader.value(path, "ExecutablePath") is None:
                return None                              # the entry is gone: look for it again
            answer = bool(self._reader.value(path, "IsPromoted")) or bool(answer)
        return answer

    def _find(self):
        """The settings keys this icon's own: the same program, the same uID, and no GUID of their own."""
        found = []
        for name in self._reader.subkeys(NOTIFY_ICON_SETTINGS):
            path = NOTIFY_ICON_SETTINGS + "\\" + name
            if self._reader.value(path, "IconGuid") is not None or self._reader.value(path, "UID") != self.uid:
                continue
            stored = self._reader.value(path, "ExecutablePath")
            if isinstance(stored, str) and self._ours(stored):
                found.append(path)
        return found

    def _ours(self, stored: str) -> bool:
        """Whether a settings entry's path is this program's. Windows writes a path under a known folder as that
        folder's GUID and the rest of the path."""
        if stored.startswith("{") and "}" in stored:
            guid, _, rest = stored.partition("}")
            folder = self._folders(guid + "}")
            if folder is None:
                return False
            stored = folder + rest
        return _same_path(stored) == self.executable


def _same_path(value: str) -> str:
    """A path as it is compared: Windows' own case and separators."""
    return os.path.normcase(os.path.normpath(value))


class SYSTEM_POWER_STATUS(C.Structure):
    _fields_ = [("ACLineStatus", C.c_ubyte), ("BatteryFlag", C.c_ubyte), ("BatteryLifePercent", C.c_ubyte),
                ("SystemStatusFlag", C.c_ubyte), ("BatteryLifeTime", W.DWORD), ("BatteryFullLifeTime", W.DWORD)]


def battery_saver() -> bool:
    """True while Windows' battery saver (energy saver) is on; False where Windows cannot say."""
    if os.name != "nt":
        return False
    try:
        status = SYSTEM_POWER_STATUS()
        get = _dll("kernel32").GetSystemPowerStatus
        get.argtypes, get.restype = (C.POINTER(SYSTEM_POWER_STATUS),), W.BOOL
        if not get(C.byref(status)):
            return False
        return bool(status.SystemStatusFlag & 1)
    except Exception:
        return False
