"""User-facing strings for the plugin layer, in English by default.

Korean is used only when the locale *explicitly* says Korean. Detection reuses the
same source the ChatGPT desktop app itself uses to pick its display language
(``app.getPreferredSystemLanguages()`` -> ``GetUserPreferredUILanguages`` on Windows),
so this tool speaks whatever the app speaks. Nothing here infers a language from an
IP address, a time zone, a user name, a country or a keyboard layout.
"""
from __future__ import annotations

import os

ENV_LANG = "CODEX_AUTO_RESUME_LANG"
DEFAULT = "en"
SUPPORTED = ("en", "ko")

# Small table on purpose: no i18n framework, no external dependency. Keys are stable
# identifiers; every key must exist in every language so a lookup can never fall back
# to a missing string at runtime.
MESSAGES = {
    "en": {
        "ready_title": "Codex Auto Resume is ready to be configured.",
        "ready_defaults": "Default behavior:",
        "ready_b1": "Resume after a usage-limit reset",
        "ready_b2": "Resume only the exact interrupted task",
        "ready_b3": "Wait until usage becomes available",
        "ready_b4": "Do not resume when state is uncertain",
        "setup_done": "Auto resume is set up and the watcher is running.",
        "setup_autostart": "It will also start automatically when you sign in to Windows.",
        "enabled": "Auto resume is on.",
        "disabled": "Auto resume is off. Nothing will be resumed until it is turned on again.",
        "watcher_running": "Watcher: running",
        "watcher_stopped": "Watcher: not running",
        "watcher_unknown": "Watcher: unknown",
        "no_pending": "No tasks are waiting to be resumed.",
        "cancelled": "Automatic resume disabled for this task.",
        "resumed": "Automatically resumed",
        "uninstalled": "Auto resume has been removed. Your Codex conversations were not touched.",
        "restart_required": "Restart Codex to finish setup.",
        "python_missing": "Python 3.12 or newer is required to run the auto-resume watcher.",
        "conflict": ("Another auto-resume installation is already registered to start at sign-in. "
                     "Running two watchers could resume the same task twice, so setup stopped. "
                     "Remove the other installation first, then run setup again."),
        "conflict_other": ("Another auto-resume installation is also registered to start at sign-in. "
                           "Two watchers could resume the same task twice; keep only one."),
        "waiting_loaded": "Waiting for this conversation to be loaded",
        "waiting_reset": "Task will resume after the usage reset",
        "toast_title": "Auto resume scheduled",
        "toast_body_at": "This conversation will continue at {time}. (conversation {short})",
        "toast_body_soon": "This conversation will continue once usage is available. (conversation {short})",
        "toast_button_cancel": "Don't resume",
        "toast_cancelled_title": "Auto resume cancelled",
        "toast_cancelled_body": "Conversation {short} will not be resumed automatically.",
    },
    "ko": {
        "ready_title": "자동 재개를 설정할 수 있습니다.",
        "ready_defaults": "기본 동작:",
        "ready_b1": "사용량 제한 후 자동 재개",
        "ready_b2": "정확한 중단 작업만 재개",
        "ready_b3": "사용량 초기화까지 대기",
        "ready_b4": "불확실한 상태에서는 재개하지 않음",
        "setup_done": "자동 재개가 설정되었고 워처가 실행 중입니다.",
        "setup_autostart": "Windows에 로그인할 때도 자동으로 시작됩니다.",
        "enabled": "자동 재개가 켜졌습니다.",
        "disabled": "자동 재개가 꺼졌습니다. 다시 켜기 전까지 아무것도 재개하지 않습니다.",
        "watcher_running": "워처: 실행 중",
        "watcher_stopped": "워처: 실행 중 아님",
        "watcher_unknown": "워처: 알 수 없음",
        "no_pending": "재개를 기다리는 작업이 없습니다.",
        "cancelled": "이 작업의 자동 재개가 비활성화되었습니다.",
        "resumed": "자동 재개됨",
        "uninstalled": "자동 재개가 제거되었습니다. Codex 대화는 그대로입니다.",
        "restart_required": "설정을 완료하려면 Codex를 다시 시작해야 합니다.",
        "python_missing": "자동 재개 워처를 실행하려면 Python 3.12 이상이 필요합니다.",
        "conflict": ("이미 다른 자동 재개 설치가 로그인 시 시작되도록 등록되어 있습니다. "
                     "워처가 두 개면 같은 작업을 두 번 재개할 수 있어 설정을 중단했습니다. "
                     "기존 설치를 먼저 제거한 뒤 다시 설정하세요."),
        "conflict_other": ("다른 자동 재개 설치도 로그인 시 시작되도록 등록되어 있습니다. "
                           "워처가 두 개면 같은 작업을 두 번 재개할 수 있으니 하나만 남기세요."),
        "waiting_loaded": "이 대화가 열리기를 기다리는 중",
        "waiting_reset": "사용량 초기화 후 작업이 재개됩니다",
        "toast_title": "자동 재개 예정",
        "toast_body_at": "{time}에 이 대화를 이어서 진행합니다. (대화 {short})",
        "toast_body_soon": "사용량이 열리면 이 대화를 이어서 진행합니다. (대화 {short})",
        "toast_button_cancel": "재개 안 함",
        "toast_cancelled_title": "자동 재개를 취소했습니다",
        "toast_cancelled_body": "대화 {short}은 자동으로 재개되지 않습니다.",
    },
}


def _windows_preferred() -> list[str]:
    """The Windows user's preferred UI languages, most preferred first.

    This is the exact API behind Electron's ``app.getPreferredSystemLanguages()``,
    which is how the ChatGPT desktop app chooses its own display language.
    """
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        MUI_LANGUAGE_NAME = 0x8
        count = wintypes.ULONG(0)
        size = wintypes.ULONG(0)
        if not kernel32.GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, ctypes.byref(count), None, ctypes.byref(size)):
            return []
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, ctypes.byref(count), buffer, ctypes.byref(size)):
            return []
        return [tag for tag in "".join(buffer[:size.value]).split("\x00") if tag]
    except Exception:
        return []    # An unavailable probe means English, never a guess.


def preferred_languages(environ=None) -> list[str]:
    environ = os.environ if environ is None else environ
    override = (environ.get(ENV_LANG) or "").strip()
    if override:
        return [override]
    tags = _windows_preferred()
    if tags:
        return tags
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = (environ.get(name) or "").strip()
        if value and value not in ("C", "POSIX"):
            return [value.split(".")[0].replace("_", "-")]
    return []


def language(environ=None) -> str:
    """Korean only when the *most preferred* language is Korean; English otherwise.

    A locale that merely lists Korean after another language is not an explicit
    request for Korean, so it stays on the English default.
    """
    tags = preferred_languages(environ)
    if not tags:
        return DEFAULT
    primary = tags[0].replace("_", "-").split("-")[0].lower()
    return primary if primary in SUPPORTED else DEFAULT


def text(key: str, environ=None) -> str:
    return MESSAGES[language(environ)][key]
