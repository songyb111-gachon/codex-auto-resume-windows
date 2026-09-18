"""May a notification card be drawn right now? One pure decision, and the probes it reads.

Since v0.6.5 a notification can be drawn as the product's own card beside the notification
area (`notice_card.py`, `notice_window.py`) instead of as a Windows toast. The card is ours to
draw, so every rule Windows applies to its own banners is ours to apply as well - and the
honest way to apply them is to ask Windows, not to guess. Whenever any answer below is "no" or
"cannot tell", the notification is raised as today's toast instead, which Windows then shows,
holds back or files away by its own rules. A toast is never the wrong answer; a card over a
presentation or on a locked screen would be.

    card_allowed()      pure: the one decision, over the answers below
    snapshot()          the answers, read now; every probe fails to "cannot tell"

What each probe asks, and why it keeps the card away:

* `notification_state` - `SHQueryUserNotificationState`. Only QUNS_ACCEPTS_NOTIFICATIONS lets
  the card show. Every other value - not present (locked, the screen saver, a switched user),
  busy or full screen, a full-screen Direct3D game, presentation mode, quiet time, a full-screen
  app - means Windows itself is not popping notifications.
* `notification_mode` - `ToastNotificationManagerForUser.NotificationMode` (Windows 10 2004 and
  later), read through the WinRT ABI. Do not disturb and Focus answer PriorityOnly or AlarmsOnly
  here and nowhere in the call above. Only Unrestricted lets the card show.
* `app_notifications` - `ToastNotifier.Setting` for the product's own AppUserModelID: Windows'
  answer to "may this app notify at all". Somebody who switched Codex Auto Resume off under
  Settings > System > Notifications, or switched all notifications off, or whose policy did,
  gets nothing from Windows - and so nothing from the card either: only Enabled lets it show.
  Neither call above says so; they are about the whole desktop, not about this app.
* `screen_reader` - `SPI_GETSCREENREADER`. A card that never takes focus is not announced, and
  Windows' toast is. So with a screen reader running the toast is raised; that is the trade-off
  requirement 4's "announced to screen readers" comes to (PLAN v2, B-D7).
* `remote_session` - `SM_REMOTESESSION`. Over Remote Desktop every animated frame of a layered
  window is sent down the wire; the toast is drawn by the remote shell.
* `session_locked` - whether the input desktop is still the user's `Default` desktop. A lock,
  the sign-in screen or a UAC prompt switch it away.

`battery_saver` and `message_duration_ms` do not decide *whether* a card shows, only how it
moves (no motion on battery saver, as with Reduce motion) and how long it stays (Windows'
"Dismiss notifications after this amount of time", when longer than the card's own hold).

Everything here only reads. Nothing is written, nothing is registered, and no window other
than the product's own is touched. Imports are the standard library only.
"""
from __future__ import annotations

import ctypes as C
import os

# QUERY_USER_NOTIFICATION_STATE
QUNS_NOT_PRESENT = 1
QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4
QUNS_ACCEPTS_NOTIFICATIONS = 5
QUNS_QUIET_TIME = 6
QUNS_APP = 7
NOTIFICATION_STATES = (QUNS_NOT_PRESENT, QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN,
                       QUNS_PRESENTATION_MODE, QUNS_ACCEPTS_NOTIFICATIONS, QUNS_QUIET_TIME, QUNS_APP)

# Windows.UI.Notifications.ToastNotificationMode
MODE_UNRESTRICTED, MODE_PRIORITY_ONLY, MODE_ALARMS_ONLY = 0, 1, 2
NOTIFICATION_MODES = (MODE_UNRESTRICTED, MODE_PRIORITY_ONLY, MODE_ALARMS_ONLY)

# Windows.UI.Notifications.NotificationSetting, what ToastNotifier.Setting answers for one app
APP_ENABLED = 0
APP_DISABLED_FOR_APPLICATION = 1                # this app's switch under Settings > Notifications
APP_DISABLED_FOR_USER = 2                       # the Notifications switch itself: every app
APP_DISABLED_BY_GROUP_POLICY = 3
APP_DISABLED_BY_MANIFEST = 4
APP_SETTINGS = (APP_ENABLED, APP_DISABLED_FOR_APPLICATION, APP_DISABLED_FOR_USER,
                APP_DISABLED_BY_GROUP_POLICY, APP_DISABLED_BY_MANIFEST)

SPI_GETSCREENREADER = 0x0046
SPI_GETMESSAGEDURATION = 0x2016
SM_REMOTESESSION = 0x1000
DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2
INPUT_DESKTOP = "Default"

# The WinRT ABI for two properties. IToastNotificationManagerStatics5 has GetDefault() in its
# first slot after IInspectable's six; IToastNotificationManagerForUser3 has get_NotificationMode
# in the same place. IToastNotificationManagerStatics has CreateToastNotifier() there and
# CreateToastNotifierWithId(HSTRING) next; IToastNotifier has Show, Hide, then get_Setting - Show
# is never called here, only the third. The interface identifiers are the platform's published
# constants, written as the SDK's DEFINE_GUID writes them (Data1, Data2, Data3, Data4). Every one
# of them, and every slot, was read from the running system's own metadata (the WinRT types'
# interfaces and their methods in declaration order), and both calls were checked against
# PowerShell's projection of the same property on Windows 11 build 26200.
TOAST_MANAGER_CLASS = "Windows.UI.Notifications.ToastNotificationManager"
IID_MANAGER_STATICS = (0x50AC103F, 0xD235, 0x4598, (0xBB, 0xEF, 0x98, 0xFE, 0x4D, 0x1A, 0x3A, 0xD4))
IID_MANAGER_STATICS5 = (0xD6F5F569, 0xD40D, 0x407C, (0x89, 0x89, 0x88, 0xCA, 0xB4, 0x2C, 0xFD, 0x14))
IID_MANAGER_FOR_USER3 = (0x3EFCB176, 0x6CC1, 0x56DC, (0x97, 0x3B, 0x25, 0x1F, 0x7A, 0xAC, 0xB1, 0xC5))
INSPECTABLE_SLOTS = 6
SLOT_CREATE_NOTIFIER_WITH_ID = INSPECTABLE_SLOTS + 1     # IToastNotificationManagerStatics
SLOT_NOTIFIER_SETTING = INSPECTABLE_SLOTS + 2            # IToastNotifier: after Show and Hide
RO_INIT_MULTITHREADED = 1
RPC_E_CHANGED_MODE = -2147417850            # 0x80010106: COM is already up on this thread


def card_allowed(*, setting, tray_present, notification_state, notification_mode, app_notifications,
                 screen_reader, remote_session, session_locked) -> bool:
    """True only when the card may be drawn. Every other answer raises today's toast.

    Strict on purpose: each input has to be the one exact value that allows the card, so an
    unknown (None) or a malformed answer from any probe keeps the card away. `setting` is the
    `notification_card` setting; `tray_present` says the icon - the card's host (B-D1) - is up.
    """
    return (setting is True
            and tray_present is True
            and screen_reader is False
            and remote_session is False
            and session_locked is False
            and notification_state == QUNS_ACCEPTS_NOTIFICATIONS
            and type(notification_state) is int
            and notification_mode == MODE_UNRESTRICTED
            and type(notification_mode) is int
            and app_notifications == APP_ENABLED
            and type(app_notifications) is int)


# ------------------------------------------------------------------------- the probes
_DLLS = {}


def _dll(name):
    """This module's own handles, so the argument types declared here reach no other module."""
    if name not in _DLLS:
        _DLLS[name] = C.WinDLL(name, use_last_error=True)
    return _DLLS[name]


def _signature(function, result, *arguments):
    function.restype = result
    function.argtypes = list(arguments)
    return function


def notification_state():
    """One of NOTIFICATION_STATES, or None when Windows could not be asked."""
    if os.name != "nt":
        return None
    try:
        state = C.c_int(0)
        query = _signature(_dll("shell32").SHQueryUserNotificationState, C.c_long, C.POINTER(C.c_int))
        if query(C.byref(state)) != 0:
            return None
        return state.value if state.value in NOTIFICATION_STATES else None
    except Exception:
        return None


class _GUID(C.Structure):
    _fields_ = [("Data1", C.c_uint32), ("Data2", C.c_uint16), ("Data3", C.c_uint16),
                ("Data4", C.c_ubyte * 8)]


def _guid(parts):
    data1, data2, data3, data4 = parts
    guid = _GUID(data1, data2, data3)
    guid.Data4[:] = list(data4)
    return guid


def _method(pointer, slot, *arguments):
    """A COM method by its vtable slot: `this` first, an HRESULT back."""
    table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p)))[0]
    return C.WINFUNCTYPE(C.c_long, C.c_void_p, *arguments)(table[slot])


def _release(pointer):
    if pointer:
        _method(pointer, 2)(pointer)


class _Refused(Exception):
    """A WinRT call answered with a failure: the property cannot be read now."""


class _WinRT:
    """One WinRT read on the calling thread, and everything it made undone on the way out.

    COM comes up multithreaded for the read - or is used as it is when the thread already has
    it in another mode - and goes down again only if this brought it up. Every interface
    pointer and string handed out is released or deleted, newest first, whatever happens.
    """

    def __init__(self):
        self.combase = _dll("combase")
        self.started = None
        self._pointers = []
        self._strings = []

    def __enter__(self):
        combase = self.combase
        _signature(combase.RoInitialize, C.c_long, C.c_int)
        _signature(combase.RoUninitialize, None)
        _signature(combase.WindowsCreateString, C.c_long, C.c_wchar_p, C.c_uint32, C.POINTER(C.c_void_p))
        _signature(combase.WindowsDeleteString, C.c_long, C.c_void_p)
        _signature(combase.RoGetActivationFactory, C.c_long, C.c_void_p, C.POINTER(_GUID),
                   C.POINTER(C.c_void_p))
        started = combase.RoInitialize(RO_INIT_MULTITHREADED)
        if started not in (0, 1, RPC_E_CHANGED_MODE):        # S_OK, S_FALSE, already up differently
            raise _Refused("RoInitialize")
        self.started = started
        return self

    def string(self, text):
        handle = C.c_void_p()
        self._strings.append(handle)
        if self.combase.WindowsCreateString(text, len(text.encode("utf-16-le")) // 2, C.byref(handle)) != 0:
            raise _Refused("WindowsCreateString")
        return handle

    def pointer(self):
        """A place for an interface pointer, released on the way out once something fills it."""
        handle = C.c_void_p()
        self._pointers.append(handle)
        return handle

    def factory(self, class_name, iid):
        factory = self.pointer()
        if self.combase.RoGetActivationFactory(self.string(class_name), C.byref(_guid(iid)),
                                               C.byref(factory)) != 0:
            raise _Refused("RoGetActivationFactory")
        return factory

    @staticmethod
    def check(result, what):
        if result != 0:
            raise _Refused(what)

    def __exit__(self, *unused):
        for pointer in reversed(self._pointers):
            try:
                _release(pointer)
            except Exception:
                pass
        for handle in self._strings:
            if handle:
                try:
                    self.combase.WindowsDeleteString(handle)
                except Exception:
                    pass
        if self.started in (0, 1):
            try:
                self.combase.RoUninitialize()
            except Exception:
                pass
        return False


def notification_mode():
    """One of NOTIFICATION_MODES - Do not disturb and Focus are not Unrestricted - or None.

    None on a Windows without the property (before 10 2004) and on any failure, which keeps
    the card away: the toast Windows raises instead follows Do not disturb by itself.
    """
    if os.name != "nt":
        return None
    try:
        with _WinRT() as runtime:
            statics = runtime.factory(TOAST_MANAGER_CLASS, IID_MANAGER_STATICS5)
            manager, modes = runtime.pointer(), runtime.pointer()
            runtime.check(_method(statics, INSPECTABLE_SLOTS, C.POINTER(C.c_void_p))(statics, C.byref(manager)),
                          "GetDefault")
            runtime.check(_method(manager, 0, C.POINTER(_GUID), C.POINTER(C.c_void_p))(
                manager, C.byref(_guid(IID_MANAGER_FOR_USER3)), C.byref(modes)), "QueryInterface")
            mode = C.c_int(-1)
            runtime.check(_method(modes, INSPECTABLE_SLOTS, C.POINTER(C.c_int))(modes, C.byref(mode)),
                          "get_NotificationMode")
            return mode.value if mode.value in NOTIFICATION_MODES else None
    except Exception:
        return None


def app_notifications(aumid):
    """One of APP_SETTINGS - Windows' own "may this app notify" for `aumid` - or None.

    `ToastNotificationManager.CreateToastNotifier(aumid).Setting`: a notifier object is made
    in this process and asked one property; nothing is shown, registered or changed (Show is
    the slot before Hide, two before the one read here). None without an identity to ask
    about, on a Windows without the call, and on any failure - which keeps the card away, and
    the toast raised instead is then dropped or shown by Windows' own switches, as in v0.6.4.
    """
    if os.name != "nt" or not isinstance(aumid, str) or not aumid.strip():
        return None
    try:
        with _WinRT() as runtime:
            statics = runtime.factory(TOAST_MANAGER_CLASS, IID_MANAGER_STATICS)
            notifier = runtime.pointer()
            runtime.check(_method(statics, SLOT_CREATE_NOTIFIER_WITH_ID, C.c_void_p, C.POINTER(C.c_void_p))(
                statics, runtime.string(aumid), C.byref(notifier)), "CreateToastNotifierWithId")
            setting = C.c_int(-1)
            runtime.check(_method(notifier, SLOT_NOTIFIER_SETTING, C.POINTER(C.c_int))(notifier, C.byref(setting)),
                          "get_Setting")
            return setting.value if setting.value in APP_SETTINGS else None
    except Exception:
        return None


def screen_reader():
    """True while a screen reader says it is running, False when none is, None if unknown."""
    if os.name != "nt":
        return None
    try:
        value = C.c_int(0)
        call = _signature(_dll("user32").SystemParametersInfoW, C.c_int, C.c_uint, C.c_uint,
                          C.c_void_p, C.c_uint)
        if not call(SPI_GETSCREENREADER, 0, C.byref(value), 0):
            return None
        return bool(value.value)
    except Exception:
        return None


def remote_session():
    """True in a Remote Desktop session, False at the console, None if unknown."""
    if os.name != "nt":
        return None
    try:
        return bool(_signature(_dll("user32").GetSystemMetrics, C.c_int, C.c_int)(SM_REMOTESESSION))
    except Exception:
        return None


def session_locked():
    """True unless the desktop receiving input is the user's own `Default` desktop.

    The lock screen, the sign-in screen and the secure desktop of an elevation prompt are all
    other desktops, and a process cannot open them - both read as locked here, which is the
    answer that raises a toast. None when not on Windows.
    """
    if os.name != "nt":
        return None
    user32 = _dll("user32")
    try:
        _signature(user32.OpenInputDesktop, C.c_void_p, C.c_uint32, C.c_int, C.c_uint32)
        _signature(user32.CloseDesktop, C.c_int, C.c_void_p)
        _signature(user32.GetUserObjectInformationW, C.c_int, C.c_void_p, C.c_int, C.c_void_p,
                   C.c_uint32, C.POINTER(C.c_uint32))
        desktop = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
        if not desktop:
            return True
        try:
            buffer = C.create_unicode_buffer(64)
            needed = C.c_uint32(0)
            if not user32.GetUserObjectInformationW(desktop, UOI_NAME, buffer, C.sizeof(buffer),
                                                    C.byref(needed)):
                return True
            return buffer.value.lower() != INPUT_DESKTOP.lower()
        finally:
            user32.CloseDesktop(desktop)
    except Exception:
        return True


class _POWER(C.Structure):
    _fields_ = [("ACLineStatus", C.c_ubyte), ("BatteryFlag", C.c_ubyte), ("BatteryLifePercent", C.c_ubyte),
                ("SystemStatusFlag", C.c_ubyte), ("BatteryLifeTime", C.c_uint32),
                ("BatteryFullLifeTime", C.c_uint32)]


def battery_saver() -> bool:
    """True while Windows' battery saver (energy saver) is on; False where it cannot say."""
    if os.name != "nt":
        return False
    try:
        status = _POWER()
        get = _signature(_dll("kernel32").GetSystemPowerStatus, C.c_int, C.POINTER(_POWER))
        return bool(get(C.byref(status))) and bool(status.SystemStatusFlag & 1)
    except Exception:
        return False


def message_duration_ms():
    """Windows' "Dismiss notifications after this amount of time", in ms, or None."""
    if os.name != "nt":
        return None
    try:
        value = C.c_uint32(0)
        call = _signature(_dll("user32").SystemParametersInfoW, C.c_int, C.c_uint, C.c_uint,
                          C.c_void_p, C.c_uint)
        if not call(SPI_GETMESSAGEDURATION, 0, C.byref(value), 0) or not value.value:
            return None
        return int(value.value) * 1000
    except Exception:
        return None


def snapshot(aumid=None) -> dict:
    """The probes `card_allowed` reads, read now, keyed by its argument names. `aumid` is the
    product's AppUserModelID (startup.AUMID, which the toast is raised under); without it
    Windows cannot be asked about this app, and the answer is the toast."""
    return {"notification_state": notification_state(), "notification_mode": notification_mode(),
            "app_notifications": app_notifications(aumid), "screen_reader": screen_reader(),
            "remote_session": remote_session(), "session_locked": session_locked()}
