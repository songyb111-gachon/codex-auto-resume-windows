"""What a screen reader is told of the popup (v0.6.11): its rows and buttons, by name and role.

The popup draws itself. Its card, its rows, their switches and its two buttons are rectangles in
one window rather than windows of their own, so what Windows can tell Narrator of it by itself is
the window and nothing in it. So when a screen reader asks the window for what is in it
(WM_GETOBJECT, OBJID_CLIENT), it is handed an IAccessible here - Microsoft Active Accessibility,
which Narrator and every other screen reader read - whose children are what the popup draws, in the
order they are drawn and the keyboard reaches them: the three counts, each task's row and its
switch, the notes under them, and the two buttons.

Two halves, as the popup is. `accessible_items(vm, plan, focus)` says what each child is - its
role, its name, what it says besides, its state and where it is - as a pure function of what is on
screen; `PopupAccessible` answers MSAA's questions from that, through ctypes, on the popup's own
thread, and `changes` says which of Windows' accessibility events a new frame raises. Nothing here
decides anything: a child's default action is a click on it - the popup's own `_activate`, for the
target that was drawn, exactly as a click and a key reach it - and nothing is read that is not
already on screen.
"""
from __future__ import annotations

from ctypes import wintypes as W
import ctypes as C
import threading

from ...win.dll import GUID, library
from .win32 import _PerMonitorDpi
from .words import say

_com = library()

# The roles and states a child can have, by their MSAA numbers (oleacc.h).
A11Y_ROLES = {"dialog": 0x12, "text": 0x29, "row": 0x22, "switch": 0x2C, "button": 0x2B}
A11Y_STATES = {"unavailable": 0x1, "focused": 0x4, "checked": 0x10, "hot": 0x80, "focusable": 0x100000,
          "readonly": 0x40}
OBJID_CLIENT, OBJID_WINDOW, CHILDID_SELF = -4, 0, 0
WM_GETOBJECT = 0x003D
EVENT_FOCUS, EVENT_REORDER, EVENT_STATECHANGE, EVENT_NAMECHANGE = 0x8005, 0x8004, 0x800A, 0x800C

# The children a hit lands on first: a switch or a button inside a row or over its words.
_PICKED_FIRST = ("switch", "button")

# What a state change does not announce: where the keyboard is (a focus event says that) and where the
# pointer is.
_PASSING = ("focused", "hot")


# ------------------------------------------------------------------------------ the pure half
def accessible_items(vm, plan, focus=None, hover=None, strings=None) -> list:
    """The popup's children for a screen reader, in the order it draws them.

    Each is a dict: `role` (a key of A11Y_ROLES), `name`, `value`, `description`, `states` (keys of
    A11Y_STATES), `rect` (client pixels, as drawn), `target` (what a click on it presses, or None) and
    `action` (the name of that press, or None). Every word is one the popup draws or one of its
    catalog's; an empty `vm` or `plan` has none.
    """
    if not vm or not plan:
        return []
    items, texts = [], [item for item in plan.get("items", ()) if item.get("kind") == "text"]
    targets = dict(plan.get("targets") or ())

    def text_rect(value, role=None):
        for item in texts:
            if item["text"] == value and (role is None or item["role"] == role):
                return tuple(item["rect"])
        return None

    def add(role, name, rect, *, value=None, description=None, states=(), target=None, action=None):
        states = set(states)
        if target is not None:
            states.add("focusable")
            if target == focus:
                states.add("focused")
            if target == hover:
                states.add("hot")
        else:
            states.add("readonly")
        items.append({"role": role, "name": name or "", "value": value, "description": description,
                      "states": sorted(states), "rect": rect, "target": target, "action": action})

    labels = [item for item in texts if item["role"] == "label"]
    values = [item for item in texts if item["role"] == "value"]
    for index, (label, value) in enumerate(vm.get("counts") or ()):
        rect = None
        if index < len(labels) and index < len(values):
            first, second = labels[index]["rect"], values[index]["rect"]
            rect = (min(first[0], second[0]), first[1], max(first[2], second[2]), second[3])
        add("text", label, rect, value=value)
    rows = dict(plan.get("rows") or ())
    for task in vm.get("tasks") or ():
        key = task.get("interruption_id")
        add("row", task.get("name"), rows.get(key), value=task.get("status"), description=task.get("reason"))
        target = ("check", key)
        checked = bool(task.get("checked"))
        # Named with its task, as the panel names the same switch (panel.js threadSwitch): tabbing from one
        # switch to the next says whose it is, not the same word again.
        add("switch", switch_name(task), targets.get(target),
            states=(["checked"] if checked else []) + (["unavailable"] if task.get("busy") else []),
            target=target, action=say(strings, "popup.a11y_off" if checked else "popup.a11y_on"))
    for note in (vm.get("more"), vm.get("error") or vm.get("empty"), vm.get("zero_note"), vm.get("observe_note"),
                 vm.get("usage_note"), vm.get("notice")):
        if note:
            add("text", note, text_rect(note))
    for key, name, busy in (("toggle", vm.get("toggle_text"), vm.get("toggle_busy")),
                            ("dashboard", vm.get("dashboard_text"), False)):
        target = (key,)
        add("button", name, targets.get(target), states=["unavailable"] if busy else [], target=target,
            action=say(strings, "popup.a11y_press"))
    return items


def switch_name(task) -> str:
    """What a screen reader calls a task's switch: its label and the task it belongs to, "Auto-resume: Docs" -
    the panel's aria-label for it, word for word."""
    label, name = task.get("check_label") or "", task.get("name") or ""
    return label + ": " + name if label and name else label or name


def pick(items, x, y):
    """The child at client point (x, y), 1-based as MSAA counts them, or 0 for none: a switch or a
    button before the row or the words it lies in."""
    for picked_first in (True, False):
        for index, item in enumerate(items):
            rect = item["rect"]
            if rect is None or (item["role"] in _PICKED_FIRST) != picked_first:
                continue
            if rect[0] <= x < rect[2] and rect[1] <= y < rect[3]:
                return index + 1
    return 0


def changes(before, after) -> list:
    """The accessibility events a new set of children raises over the last one, as (event, child)
    pairs: a reorder when what is there changed, a name or a state change for a child that
    changed in place, and the focus on the child that has it now if that moved. A value - a countdown
    that moves every second - raises nothing: a screen reader reads it when it is asked for it."""
    events = []
    shape = [(item["role"], item["target"]) for item in after]
    if [(item["role"], item["target"]) for item in before] != shape:
        events.append((EVENT_REORDER, CHILDID_SELF))
    else:
        for index, (old, new) in enumerate(zip(before, after)):
            if old["name"] != new["name"]:
                events.append((EVENT_NAMECHANGE, index + 1))
            if [state for state in old["states"] if state not in _PASSING] != \
                    [state for state in new["states"] if state not in _PASSING]:
                events.append((EVENT_STATECHANGE, index + 1))
    was = next((index for index, item in enumerate(before) if "focused" in item["states"]), None)
    now = next((index for index, item in enumerate(after) if "focused" in item["states"]), None)
    if now is not None and (now != was or events[:1] == [(EVENT_REORDER, CHILDID_SELF)]):
        events.append((EVENT_FOCUS, now + 1))
    return events


# ---------------------------------------------------------------------------- MSAA, through COM
S_OK, S_FALSE = 0, 1
E_NOINTERFACE, E_NOTIMPL, E_FAIL = -2147467262, -2147467263, -2147467259
E_INVALIDARG, DISP_E_MEMBERNOTFOUND = -2147024809, -2147352573
VT_EMPTY, VT_I4 = 0, 3
NAVIGATE_NEXT = (2, 4, 5)            # NAVDIR_DOWN, NAVDIR_RIGHT, NAVDIR_NEXT
NAVIGATE_PREVIOUS = (1, 3, 6)        # NAVDIR_UP, NAVDIR_LEFT, NAVDIR_PREVIOUS
NAVIGATE_FIRST, NAVIGATE_LAST = 7, 8


def _guid(data1, data2, data3, data4) -> GUID:
    value = GUID(data1, data2, data3)
    value.Data4[:] = list(data4)
    return value


# The three interfaces the object is: IUnknown, IDispatch (whose name this file does not spell out in full) and
# IAccessible - Windows' own identifiers, as win/network.py writes its.
IID_IUNKNOWN = _guid(0x00000000, 0x0000, 0x0000, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))
IID_AUTOMATION = _guid(0x00020400, 0x0000, 0x0000, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))
IID_IACCESSIBLE = _guid(0x618736E0, 0x3C3D, 0x11CF, (0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71))


class _Value(C.Union):
    _fields_ = [("lVal", C.c_long), ("pointer", C.c_void_p), ("record", C.c_void_p * 2)]


class VARIANT(C.Structure):
    _fields_ = [("vt", C.c_ushort), ("reserved1", C.c_ushort), ("reserved2", C.c_ushort),
                ("reserved3", C.c_ushort), ("value", _Value)]


# A VARIANT passed by value: on x64 the caller passes a pointer to its copy (it is 24 bytes); on x86
# its 16 bytes are on the stack, four DWORDs, the vt in the first and the long in the third.
_WIDE = C.sizeof(C.c_void_p) == 8
_VARIANT_IN = (C.c_void_p,) if _WIDE else (C.c_ulong,) * 4
_BSTR_OUT = C.POINTER(C.c_void_p)
_VARIANT_OUT = C.POINTER(VARIANT)
_LONG_OUT = C.POINTER(C.c_long)


def _child_of(arguments):
    """The child id a VARIANT argument carries, or None when it is not a VT_I4."""
    if _WIDE:
        pointer = arguments[0]
        if not pointer:
            return None
        variant = VARIANT.from_address(pointer)
        return variant.value.lVal if variant.vt == VT_I4 else None
    vt, _, low, _ = arguments
    return C.c_long(low).value if (vt & 0xFFFF) == VT_I4 else None


_msaa_lock = threading.Lock()
_msaa_declared = []


def _declare_msaa():
    with _msaa_lock:
        if _msaa_declared:
            return
        oleacc, oleaut32, ole32, user32 = _com("oleacc"), _com("oleaut32"), _com("ole32"), _com("user32")
        oleacc.LresultFromObject.restype = C.c_ssize_t
        oleacc.LresultFromObject.argtypes = [C.POINTER(GUID), W.WPARAM, C.c_void_p]
        oleacc.CreateStdAccessibleObject.restype = C.c_long
        oleacc.CreateStdAccessibleObject.argtypes = [W.HWND, C.c_long, C.POINTER(GUID), C.POINTER(C.c_void_p)]
        oleaut32.SysAllocString.restype = C.c_void_p
        oleaut32.SysAllocString.argtypes = [W.LPCWSTR]
        ole32.CoInitializeEx.restype = C.c_long
        ole32.CoInitializeEx.argtypes = [C.c_void_p, C.c_uint32]
        user32.NotifyWinEvent.restype = None
        user32.NotifyWinEvent.argtypes = [W.DWORD, W.HWND, C.c_long, C.c_long]
        user32.GetWindowRect.restype = W.BOOL
        user32.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        user32.ClientToScreen.restype = W.BOOL
        user32.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
        user32.ScreenToClient.restype = W.BOOL
        user32.ScreenToClient.argtypes = [W.HWND, C.POINTER(W.POINT)]
        user32.GetForegroundWindow.restype = W.HWND
        user32.GetForegroundWindow.argtypes = []
        _msaa_declared.append(True)


def _prototype(*arguments):
    return C.WINFUNCTYPE(C.c_long, C.c_void_p, *arguments)


def _prototypes():
    """IAccessible's vtable, in order: IUnknown's three, IDispatch's four, then its own twenty-one."""
    variant = _VARIANT_IN
    return [
        _prototype(C.POINTER(GUID), C.POINTER(C.c_void_p)),                   # QueryInterface
        C.WINFUNCTYPE(C.c_ulong, C.c_void_p),                                  # AddRef
        C.WINFUNCTYPE(C.c_ulong, C.c_void_p),                                  # Release
        _prototype(C.POINTER(C.c_uint)),                                       # GetTypeInfoCount
        _prototype(C.c_uint, C.c_ulong, C.POINTER(C.c_void_p)),                # GetTypeInfo
        _prototype(C.c_void_p, C.c_void_p, C.c_uint, C.c_ulong, C.c_void_p),   # GetIDsOfNames
        _prototype(C.c_long, C.c_void_p, C.c_ulong, C.c_ushort, C.c_void_p, C.c_void_p, C.c_void_p,
                   C.c_void_p),                                                # Invoke
        _prototype(C.POINTER(C.c_void_p)),                                     # get_accParent
        _prototype(_LONG_OUT),                                                 # get_accChildCount
        _prototype(*variant, C.POINTER(C.c_void_p)),                           # get_accChild
        _prototype(*variant, _BSTR_OUT),                                       # get_accName
        _prototype(*variant, _BSTR_OUT),                                       # get_accValue
        _prototype(*variant, _BSTR_OUT),                                       # get_accDescription
        _prototype(*variant, _VARIANT_OUT),                                    # get_accRole
        _prototype(*variant, _VARIANT_OUT),                                    # get_accState
        _prototype(*variant, _BSTR_OUT),                                       # get_accHelp
        _prototype(_BSTR_OUT, *variant, _LONG_OUT),                            # get_accHelpTopic
        _prototype(*variant, _BSTR_OUT),                                       # get_accKeyboardShortcut
        _prototype(_VARIANT_OUT),                                              # get_accFocus
        _prototype(_VARIANT_OUT),                                              # get_accSelection
        _prototype(*variant, _BSTR_OUT),                                       # get_accDefaultAction
        _prototype(C.c_long, *variant),                                        # accSelect
        _prototype(_LONG_OUT, _LONG_OUT, _LONG_OUT, _LONG_OUT, *variant),      # accLocation
        _prototype(C.c_long, *variant, _VARIANT_OUT),                          # accNavigate
        _prototype(C.c_long, C.c_long, _VARIANT_OUT),                          # accHitTest
        _prototype(*variant),                                                  # accDoDefaultAction
        _prototype(*variant, C.c_void_p),                                      # put_accName
        _prototype(*variant, C.c_void_p),                                      # put_accValue
    ]


_WIDTH_OF_VARIANT = len(_VARIANT_IN)


def _guarded(method):
    """A COM method that never lets a Python exception out: it answers E_FAIL instead."""
    def call(*arguments):
        try:
            return method(*arguments)
        except Exception:
            return E_FAIL
    return call


class PopupAccessible:
    """The popup's client object for MSAA: one per popup, made the first time a screen reader asks,
    answered on the popup's own thread from what that popup has on screen."""

    def __init__(self, popup):
        _declare_msaa()
        self.popup = popup
        self.references = 1
        methods = [self._query, self._add_ref, self._release, self._type_info_count, self._not_implemented,
                   self._not_implemented, self._not_implemented, self._parent, self._child_count, self._child,
                   self._name, self._value, self._description, self._role, self._state, self._nothing,
                   self._help_topic, self._nothing, self._focus, self._selection, self._default_action,
                   self._select, self._location, self._navigate, self._hit_test, self._do_default_action,
                   self._not_implemented, self._not_implemented]
        guarded = [method if index in (1, 2) else _guarded(method) for index, method in enumerate(methods)]
        self._callbacks = [prototype(method) for prototype, method in zip(_prototypes(), guarded)]
        self._vtable = (C.c_void_p * len(self._callbacks))(*[C.cast(callback, C.c_void_p).value
                                                             for callback in self._callbacks])
        self._object = (C.c_void_p * 1)(C.addressof(self._vtable))
        self.pointer = C.addressof(self._object)

    # ---- what is on screen
    def items(self):
        """The children as the popup lays itself out now: its view and the plan made from it, together."""
        popup = self.popup
        return accessible_items(popup._vm, popup._plan, popup.focus if popup.keyboard else None, popup.hover,
                                popup.model.strings)

    def _item(self, arguments):
        """(child id, item): item None for the popup itself; (None, None) for an id that is not a child."""
        child = _child_of(arguments)
        if child is None:
            return None, None
        if child == CHILDID_SELF:
            return CHILDID_SELF, None
        items = self.items()
        return (child, items[child - 1]) if 1 <= child <= len(items) else (None, None)

    # ---- IUnknown and IDispatch
    def _query(self, this, riid, out):
        if not out:
            return E_INVALIDARG
        wanted = bytes(riid.contents)
        if wanted in (bytes(IID_IUNKNOWN), bytes(IID_AUTOMATION), bytes(IID_IACCESSIBLE)):
            out[0] = self.pointer
            self.references += 1
            return S_OK
        out[0] = None
        return E_NOINTERFACE

    def _add_ref(self, this):
        self.references += 1
        return self.references

    def _release(self, this):
        # Never freed here: the popup keeps the object for as long as its window lives.
        self.references = max(0, self.references - 1)
        return self.references

    def _type_info_count(self, this, out):
        if out:
            out[0] = 0
        return S_OK

    def _not_implemented(self, this, *unused):
        return E_NOTIMPL

    # ---- IAccessible
    def _parent(self, this, out):
        out[0] = None
        hwnd = self.popup.hwnd
        if not hwnd:
            return S_FALSE
        found = C.c_void_p()
        if _com("oleacc").CreateStdAccessibleObject(hwnd, OBJID_WINDOW, C.byref(IID_AUTOMATION), C.byref(found)) != 0:
            return S_FALSE
        out[0] = found.value
        return S_OK

    def _child_count(self, this, out):
        out[0] = len(self.items())
        return S_OK

    def _child(self, this, *arguments):
        *variant, out = arguments
        child, _ = self._item(variant)
        out[0] = None
        return E_INVALIDARG if child is None else S_FALSE     # every child is a simple element

    def _string(self, arguments, read):
        *variant, out = arguments
        out[0] = None
        child, item = self._item(variant)
        if child is None:
            return E_INVALIDARG
        text = read(item)
        if not text:
            return S_FALSE
        out[0] = _com("oleaut32").SysAllocString(text)
        return S_OK

    def _name(self, this, *arguments):
        return self._string(arguments, lambda item: self.popup._vm and self.popup._vm.get("title") if item is None
                            else item["name"])

    def _value(self, this, *arguments):
        return self._string(arguments, lambda item: None if item is None else item["value"])

    def _description(self, this, *arguments):
        return self._string(arguments, lambda item: self.popup._vm and self.popup._vm.get("state_text")
                            if item is None else item["description"])

    def _default_action(self, this, *arguments):
        return self._string(arguments, lambda item: None if item is None else item["action"])

    def _nothing(self, this, *arguments):
        return self._string(arguments, lambda item: None)

    def _help_topic(self, this, *arguments):
        arguments[0][0] = None
        arguments[-1][0] = 0
        return S_FALSE

    def _number(self, out, number):
        out.contents.vt = VT_I4
        out.contents.value.lVal = number
        return S_OK

    def _empty(self, out):
        out.contents.vt = VT_EMPTY
        out.contents.value.lVal = 0
        return S_FALSE

    def _role(self, this, *arguments):
        *variant, out = arguments
        child, item = self._item(variant)
        if child is None:
            return E_INVALIDARG
        return self._number(out, A11Y_ROLES["dialog" if item is None else item["role"]])

    def _state(self, this, *arguments):
        *variant, out = arguments
        child, item = self._item(variant)
        if child is None:
            return E_INVALIDARG
        if item is None:
            states = ["focusable"]
            if self._foreground() and not any("focused" in entry["states"] for entry in self.items()):
                states.append("focused")
        else:
            states = item["states"]
        value = 0
        for state in states:
            value |= A11Y_STATES[state]
        return self._number(out, value)

    def _foreground(self):
        hwnd = self.popup.hwnd
        return bool(hwnd) and self.popup.visible and _com("user32").GetForegroundWindow() == hwnd

    def _focus(self, this, out):
        items = self.items()
        for index, item in enumerate(items):
            if "focused" in item["states"]:
                return self._number(out, index + 1)
        return self._number(out, CHILDID_SELF) if self._foreground() else self._empty(out)

    def _selection(self, this, out):
        return self._empty(out)

    def _select(self, this, flags, *variant):
        return DISP_E_MEMBERNOTFOUND

    def _location(self, this, left, top, width, height, *variant):
        child, item = self._item(variant)
        hwnd = self.popup.hwnd
        if child is None or not hwnd:
            return E_INVALIDARG
        with _PerMonitorDpi():
            if item is None:
                rect = W.RECT()
                _com("user32").GetWindowRect(hwnd, C.byref(rect))
                box = (rect.left, rect.top, rect.right, rect.bottom)
            elif item["rect"] is None:
                left[0] = top[0] = width[0] = height[0] = 0
                return S_FALSE
            else:
                corner = W.POINT(item["rect"][0], item["rect"][1])
                _com("user32").ClientToScreen(hwnd, C.byref(corner))
                box = (corner.x, corner.y, corner.x + item["rect"][2] - item["rect"][0],
                       corner.y + item["rect"][3] - item["rect"][1])
        left[0], top[0], width[0], height[0] = box[0], box[1], box[2] - box[0], box[3] - box[1]
        return S_OK

    def _navigate(self, this, direction, *arguments):
        *variant, out = arguments
        child, _ = self._item(variant)
        if child is None:
            return E_INVALIDARG
        count = len(self.items())
        if child == CHILDID_SELF and direction in (NAVIGATE_FIRST, NAVIGATE_LAST):
            return self._number(out, 1 if direction == NAVIGATE_FIRST else count) if count else self._empty(out)
        if child != CHILDID_SELF and direction in NAVIGATE_NEXT + NAVIGATE_PREVIOUS:
            other = child + (1 if direction in NAVIGATE_NEXT else -1)
            return self._number(out, other) if 1 <= other <= count else self._empty(out)
        return self._empty(out) if child != CHILDID_SELF else DISP_E_MEMBERNOTFOUND

    def _hit_test(self, this, x, y, out):
        hwnd = self.popup.hwnd
        if not hwnd:
            return self._empty(out)
        with _PerMonitorDpi():
            rect = W.RECT()
            _com("user32").GetWindowRect(hwnd, C.byref(rect))
            if not (rect.left <= x < rect.right and rect.top <= y < rect.bottom):
                return self._empty(out)
            point = W.POINT(x, y)
            _com("user32").ScreenToClient(hwnd, C.byref(point))
        return self._number(out, pick(self.items(), point.x, point.y))

    def _do_default_action(self, this, *variant):
        child, item = self._item(variant)
        if child is None or item is None or item["target"] is None:
            return DISP_E_MEMBERNOTFOUND if child is not None else E_INVALIDARG
        if "unavailable" in item["states"]:
            return S_OK
        self.popup._activate(item["target"])
        return S_OK


# ------------------------------------------------------------------------------------ the window
_COINIT_APARTMENTTHREADED = 0x2


_RPC_E_CHANGED_MODE = -2147417850


def answer(popup, wparam, lparam):
    """WM_GETOBJECT for the popup: its client object when that is what is asked for, else None - and
    Windows answers for the window itself. COM comes up single-threaded on the popup's thread the first
    time, where it is not up already, so every question arrives on that thread through its own messages;
    on a thread where COM is up multithreaded they would arrive on others, so there the window is left
    to Windows' own answer."""
    if C.c_long(lparam & 0xFFFFFFFF).value != OBJID_CLIENT or not popup.hwnd:
        return None
    _declare_msaa()
    if getattr(popup, "_access", None) is None:
        if _com("ole32").CoInitializeEx(None, _COINIT_APARTMENTTHREADED) == _RPC_E_CHANGED_MODE:
            return None
        popup._access = PopupAccessible(popup)
    return _com("oleacc").LresultFromObject(C.byref(IID_IACCESSIBLE), wparam, popup._access.pointer)


def disconnect(popup):
    """Cut every screen reader's hold on the popup's client object, as its window goes: a question asked
    after it is refused by COM rather than answered. The object itself is kept - it is the popup's."""
    if getattr(popup, "_access", None) is None:
        return
    try:
        ole32 = _com("ole32")
        ole32.CoDisconnectObject.restype = C.c_long
        ole32.CoDisconnectObject.argtypes = [C.c_void_p, W.DWORD]
        ole32.CoDisconnectObject(popup._access.pointer, 0)
    except Exception:
        pass


def announce(popup, before, after):
    """Tell Windows what changed on screen (changes), for whoever listens; nothing when nobody does."""
    if not popup.hwnd or not popup.visible:
        return
    _declare_msaa()
    for event, child in changes(before, after):
        _com("user32").NotifyWinEvent(event, popup.hwnd, OBJID_CLIENT, child)
