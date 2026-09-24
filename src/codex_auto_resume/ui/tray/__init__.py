"""The notification-area icon: what it says, what it shows, and what a click does.

`tray.py` was 1,171 lines. It is the same icon in eleven files, and every `tray.<name>` reads
as it did.

In the order they are imported below, which is a dependency order: each file uses only what is
above it.

    words       its tooltip, and how much of one Windows will take
    model       what it shows, as a pure function of the watcher's snapshot
    motion      the states it moves in, and every frame of them
    win32       the numbers, the two structures, and a handle cache of its own
    menu        what the right-click menu offers, and asking for it to be drawn dark
    stored      the settings it reads for itself before it opens anything
    cards       hosting the notification card on this thread
    clicks      making the popup, showing it, marking what it showed as seen
    animation   the frame table's life, and the timer that draws from it
    icon        one thread, one hidden window, and `Tray` composed from the five mixins
    dashboard   opening the settings window

Four of them call Windows: `win32`, and `menu`, `animation` and `icon` through it. The other
seven do not, which is why `build/make_screenshots.py` can draw the icon's every frame with no
icon, no window and no shell - `motion` holds both the arithmetic and the pixels for exactly
that reason. `dashboard` starts a process and is the only file here that does.

`Tray` is composed from the five mixins in `icon.py` rather than here, so that this file holds
no code of its own - `tests/test_reexports.py` holds it to that, and to giving every name the
one module gave.
"""
from __future__ import annotations

from .words import TIP_CHARS, countdown, tooltip  # noqa: F401
from .model import popup_attention, snapshot_from  # noqa: F401
from .motion import (ICON_BRAND_STATE,
                     ICON_BREATHS,
                     ICON_DIM_TOWARD,
                     ICON_FOR_LIGHT,
                     ICON_HEAD_PALETTE,
                     ICON_MOTION,
                     ICON_STATES,
                     ICON_SWEEP,
                     ICON_SWEEPS,
                     ICON_TRAVEL_BREATHS,
                     IconFrames,
                     _breath_level,
                     build_icon_frames,
                     icon_brand_state,
                     icon_frame,
                     icon_frame_ms,
                     icon_head_colour,
                     icon_level_colour,
                     icon_motion_allowed,
                     icon_state,
                     icon_turn)  # noqa: F401
from .win32 import (CALLBACK,
                    IDI_APPLICATION,
                    IMAGE_ICON,
                    LR_LOADFROMFILE,
                    MF_GRAYED,
                    MF_SEPARATOR,
                    MF_STRING,
                    MSG,
                    NIF_ICON,
                    NIF_MESSAGE,
                    NIF_SHOWTIP,
                    NIF_TIP,
                    NIM_ADD,
                    NIM_DELETE,
                    NIM_MODIFY,
                    NIM_SETVERSION,
                    NIN_KEYSELECT,
                    NIN_SELECT,
                    NOTIFYICONDATAW,
                    NOTIFYICON_VERSION_4,
                    NOTIFY_FOR_THIS_SESSION,
                    SM_CXSMICON,
                    SM_CYSMICON,
                    TIMER_FRAME,
                    TIMER_TICK,
                    TPM_NONOTIFY,
                    TPM_RETURNCMD,
                    TPM_RIGHTBUTTON,
                    WM_APP,
                    WM_CLOSE,
                    WM_COMMAND,
                    WM_CONTEXTMENU,
                    WM_DESTROY,
                    WM_LBUTTONDBLCLK,
                    WM_LBUTTONUP,
                    WM_NULL,
                    WM_RBUTTONUP,
                    WM_TIMER,
                    WM_TRAY_FRAMES,
                    WM_USER,
                    WM_WTSSESSION_CHANGE,
                    WTS_CONSOLE_CONNECT,
                    WTS_CONSOLE_DISCONNECT,
                    WTS_REMOTE_CONNECT,
                    WTS_REMOTE_DISCONNECT,
                    WTS_SESSION_LOCK,
                    WTS_SESSION_UNLOCK,
                    _dll)  # noqa: F401
from .menu import (APP_MODE_DEFAULT,
                   APP_MODE_FORCE_DARK,
                   DARK_MENU_BUILD,
                   MENU_OPEN,
                   MENU_PENDING,
                   MENU_STOP,
                   MENU_TOGGLE,
                   UXTHEME_FLUSH_MENU_THEMES,
                   UXTHEME_SET_PREFERRED_APP_MODE,
                   menu_app_mode,
                   prefer_app_mode)  # noqa: F401
from .icon import Tray  # noqa: F401
from .dashboard import PAGES, open_dashboard  # noqa: F401
