"""The notification-area popup: what it shows, where it goes, and how it is drawn.

`tray_popup.py` was 2,851 lines - the largest file in the package. It is the same popup in
twelve files, and every `tray_popup.<name>` reads as it did.

The six that ask Windows nothing, which is why the documentation's pictures can be taken
without a screen:

    words       the catalogue, and how a line is cut and broken
    model       what it is showing, as a pure function of the snapshot
    placement   where it goes, and what is under the pointer
    motion      what moves, and how far along it is
    elevation   how far a shadow reaches, and how much of each pixel it covers
    layout      where every piece goes, in one pass

Then Windows, and what is drawn with it:

    win32       the numbers, the structures, and one declaration pass
    fonts       which face each script is drawn in, and what Windows has
    theme       light or dark, motion or none, and High Contrast
    gdiplus     the surfaces drawn on, and the counting that proves nothing leaks
    renderer    drawing it into memory
    window      the window itself, and the life of one popup

That is the order they are imported in below, and it is their dependency order: each file
uses only what is above it. `tests/test_popup_shape.py` holds it that way.
"""
from __future__ import annotations

from .words import locale_of, one_line, say, unbroken, vocabulary  # noqa: F401
from .model import (ATTENTION_OVERLAYS,
                    CLICK_AWAY_SECONDS,
                    CONTROL_CALLS,
                    DOUBLE_CLICK_SECONDS,
                    KEY_REPEAT_SECONDS,
                    MAX_TASKS,
                    NOTICE_SECONDS,
                    PopupModel,
                    STALE_CODES,
                    STATES,
                    activity,
                    busy_key,
                    is_waiting,
                    perform,
                    select_action,
                    snapshot_activity,
                    task_item,
                    urgency,
                    view_model)  # noqa: F401
from .placement import focus_order, hit_test, next_focus, place, taskbar_edge  # noqa: F401
from .motion import animates, glide_amount, halo, next_glides  # noqa: F401
from .elevation import (DEPTH,
                        lift_coverage,
                        recipe_shadows,
                        shadow_step,
                        tile_ground,
                        well_coverage)  # noqa: F401
from .layout import (MARK,
                     SHADOW_MARGIN,
                     STATE_INK,
                     SWITCH_GAP,
                     WIDTH,
                     layout,
                     share_columns)  # noqa: F401
from .win32 import (BITMAP,
                    BITMAPINFO,
                    BITMAPINFOHEADER,
                    CS_DROPSHADOW,
                    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
                    DT_CALCRECT,
                    DT_CENTER,
                    DT_EDITCONTROL,
                    DT_END_ELLIPSIS,
                    DT_NOPREFIX,
                    DT_SINGLELINE,
                    DT_VCENTER,
                    DT_WORDBREAK,
                    DWMWA_USE_IMMERSIVE_DARK_MODE,
                    DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    DWMWCP_ROUND,
                    GR_GDIOBJECTS,
                    GR_USEROBJECTS,
                    GdiplusStartupInput,
                    HCF_HIGHCONTRASTON,
                    HIGHCONTRASTW,
                    HKEY_CURRENT_USER,
                    HWND_TOPMOST,
                    ICONINFO,
                    IDC_ARROW,
                    INTERPOLATION_NEAREST,
                    KEY_WAS_DOWN,
                    LOGFONTW,
                    MONITORINFO,
                    MONITOR_DEFAULTTONEAREST,
                    NONCLIENTMETRICSW,
                    NOTIFYICONIDENTIFIER,
                    PAINTSTRUCT,
                    PointF,
                    RRF_RT_REG_DWORD,
                    SPI_GETCLIENTAREAANIMATION,
                    SPI_GETHIGHCONTRAST,
                    SPI_GETNONCLIENTMETRICS,
                    SWP_NOACTIVATE,
                    SW_HIDE,
                    SW_SHOW,
                    SW_SHOWNOACTIVATE,
                    TIMER_FIRST,
                    TIMER_FRAME,
                    TIMER_TICK,
                    TME_LEAVE,
                    TRACKMOUSEEVENT,
                    UNIT_PIXEL,
                    VK_DOWN,
                    VK_ESCAPE,
                    VK_RETURN,
                    VK_SHIFT,
                    VK_SPACE,
                    VK_TAB,
                    VK_UP,
                    WA_INACTIVE,
                    WM_ACTIVATE,
                    WM_APP,
                    WM_CLOSE,
                    WM_DPICHANGED,
                    WM_ERASEBKGND,
                    WM_KEYDOWN,
                    WM_LBUTTONDOWN,
                    WM_LBUTTONUP,
                    WM_MOUSELEAVE,
                    WM_MOUSEMOVE,
                    WM_PAINT,
                    WM_POPUP_RESULT,
                    WM_POPUP_STRINGS,
                    WM_SETTINGCHANGE,
                    WM_SYSCOLORCHANGE,
                    WM_TIMER,
                    WS_EX_TOOLWINDOW,
                    WS_EX_TOPMOST,
                    WS_POPUP,
                    _PerMonitorDpi,
                    _declare,
                    _dll,
                    _icon_from_pixels,
                    _pack,
                    gui_resources,
                    icon_rect)  # noqa: F401
from .fonts import (ROLES,
                    _Fonts,
                    font_candidates,
                    font_faces,
                    message_face,
                    role_size)  # noqa: F401
from .theme import (APP_MODE_VALUE,
                    CONTRAST_COLOURS,
                    PERSONALIZE_KEY,
                    SYSTEM_COLOURS,
                    THEME_CHOICES,
                    THEME_SYSTEM,
                    adopt_settings,
                    appearance,
                    apps_use_light_theme,
                    contrast_colour,
                    effective_theme,
                    high_contrast,
                    reduced_motion,
                    set_reduce_motion,
                    set_theme,
                    system_rgb,
                    theme_choice,
                    theme_setting)  # noqa: F401
from .gdiplus import (PIXEL_FORMAT_32BPP_PARGB,
                      PIXEL_FORMAT_32BPP_RGB,
                      _Canvas,
                      _Painter,
                      _ShadowImage,
                      _gdiplus_acquire,
                      _gdiplus_release,
                      gdiplus_objects)  # noqa: F401
from .renderer import CHIP_ALPHA, DOT_FILL, Renderer  # noqa: F401
from .window import FIRST_READ_WAIT_MS, FRAME_MS, Popup, REFRESH_TICKS  # noqa: F401
