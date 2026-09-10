"""Every word the two settings surfaces put on screen, in one table.

The standalone Windows window and the Codex panel show the same product. Until v0.5.6
they each carried their own English literals - one set in C#, one set in JavaScript - and
the plugin layer had a third set in Python for its own messages. Three copies of the same
vocabulary is how "Retry timing" becomes three different words, and it is why the two
settings surfaces were English no matter what language the rest of the product spoke.

So there is one catalog, here, and both surfaces are handed the resolved language's
strings rather than choosing for themselves:

    messages.language()          decides once, from the Windows preferred UI languages
        |
        +-- controlcli `strings` -> the standalone window, over the bridge it already uses
        +-- mcpui.settings_page  -> the Codex panel, embedded in the page it already seeds

Neither surface guesses. The C# window does not read the registry and the panel's
JavaScript does not look at `navigator.language`, because a product that speaks Korean in
its notifications and English in its settings window is worse than one that picks either.

Keys are stable identifiers and every key exists in every language; `tests/test_locale.py`
asserts that, so a missing string cannot reach a user as a blank label or an English word
in the middle of a Korean sentence.

Brand names are not translated: Codex, Codex Auto Resume, Windows, MCP. Korean particles
attach to them normally.
"""
from __future__ import annotations

from . import messages

# Ordinary UI vocabulary. The `field.*` keys are the settings schema's own names, so a
# setting added to `settings.py` needs a line here and nowhere else; a missing one shows
# the humanised English name rather than a blank, and the test says so out loud.
STRINGS = {
    "en": {
        # Cards.
        "group.recovery": "Automatic recovery",
        "group.limits": "Limits",
        "group.notifications": "Notifications",
        "group.windows": "Windows",

        # Settings, keyed by their schema name.
        "field.recover_usage_limit": "Usage limits",
        "field.recover_network_transient": "Network failures",
        "field.recover_timeout": "Timeouts",
        "field.recover_rate_limit_transient": "Temporary rate limits",
        "field.recover_server_5xx": "Server errors",
        "field.recover_stream_interrupted": "Stream interruptions",
        "field.notifications": "Show notifications",
        "field.notify_interruption": "Interruption detected",
        "field.notify_starting": "Recovery starting",
        "field.notify_result": "Recovery result",
        "field.notify_stopped": "Stopped or out of attempts",
        "field.max_recovery_attempts": "Attempts per interruption",
        "field.max_no_progress": "Stop after no progress",
        "field.retry_timing": "Retry timing",
        "field.detection_lookback_hours": "Look back",
        "field.startup": "Run at Windows sign-in",

        # Retry timing. The stored value stays English; only the label is translated.
        "choice.conservative": "conservative",
        "choice.normal": "normal",
        "choice.aggressive": "aggressive",

        # The status line, which is the reason either surface gets opened.
        "status.watching": "Watching for interruptions",
        "status.not_running": "Watcher not running",
        "status.unknown": "Watcher status unknown",
        "status.paused": "Watching paused",
        "status.recovery_on": "Automatic recovery is on",
        "status.recovery_paused": "Automatic recovery is paused",
        "status.recovery_idle": "Nothing will be recovered until it is running",
        "status.pending_none": "Nothing pending",
        "status.pending_one": "1 recovery pending",
        "status.pending_many": "{n} recoveries pending",
        "status.unavailable": "Status unavailable",
        "status.unavailable_detail": "Settings can still be changed and saved",

        # Actions.
        "action.save": "Save",
        "action.close": "Close",
        "action.restore": "Restore defaults",
        "action.start": "Start watcher",
        "action.pause": "Pause recovery",
        "action.resume": "Resume recovery",

        # Starting the watcher, and the four things that can come of it.
        "start.working": "Starting the watcher...",
        "start.waiting": "Waiting for it to report in",
        "start.exited": "It started and stopped again - see the logs in the installation folder",
        "start.unconfirmed": "Started, but not confirmed running yet",
        "start.failed": "Could not start the watcher.",

        # The panel's pending table.
        "panel.pending_title": "Waiting to resume",
        "panel.col_conversation": "Conversation",
        "panel.col_state": "State",
        "panel.col_attempts": "Attempts",
        "panel.more": "and {n} more",
        "panel.saving": "Saving...",
        "panel.saved": "Saved.",
        "panel.not_saved": "Not saved: {reason}",
        "panel.refused": "refused",
        "panel.readonly": "Read-only here. Use the Codex Auto Resume settings window to change these.",
        "panel.unavailable": "Settings are not available in this view.",
        "panel.starting": "Starting...",
        "panel.start_failed": "Could not start it: {reason}",
        "panel.start_exited": "It started and stopped again; nothing is watching.",
        "panel.start_unconfirmed": "Started, but not confirmed running yet. Ask for the status again.",

        # What a queued recovery is waiting for. Shown as a pill, so they stay short.
        "state.waiting_reset": "waiting reset",
        "state.waiting_poll": "waiting",
        "state.waiting_for_app": "waiting for Codex",
        "state.waiting_for_loaded_thread": "waiting for the thread",
        "state.waiting_for_usage": "waiting for usage",
        "state.waiting_retry": "waiting to retry",
        "state.waiting_backoff": "backing off",
        "state.queued": "queued",
        "state.submitting": "submitting",
        "state.resumed": "resumed",
        "state.cancelled": "cancelled",
        "state.superseded": "superseded",
        "state.superseded_by_user": "superseded",
        "state.failed": "failed",
        "state.submission_unknown": "outcome unknown",
        "state.retry_budget_exhausted": "out of attempts",
        "state.no_progress_exhausted": "no progress",
        "state.terminal_failure": "stopped",
    },
    "ko": {
        "group.recovery": "자동 복구",
        "group.limits": "제한",
        "group.notifications": "알림",
        "group.windows": "Windows",

        "field.recover_usage_limit": "사용량 제한",
        "field.recover_network_transient": "네트워크 오류",
        "field.recover_timeout": "시간 초과",
        "field.recover_rate_limit_transient": "일시적 요청 제한",
        "field.recover_server_5xx": "서버 오류",
        "field.recover_stream_interrupted": "스트림 중단",
        "field.notifications": "알림 표시",
        "field.notify_interruption": "중단 감지",
        "field.notify_starting": "복구 시작",
        "field.notify_result": "복구 결과",
        "field.notify_stopped": "중지 또는 시도 소진",
        "field.max_recovery_attempts": "중단당 시도 횟수",
        "field.max_no_progress": "진전 없이 반복되면 중지",
        "field.retry_timing": "재시도 간격",
        "field.detection_lookback_hours": "확인 범위",
        "field.startup": "Windows 로그인 시 실행",

        "choice.conservative": "여유롭게",
        "choice.normal": "보통",
        "choice.aggressive": "촘촘하게",

        "status.watching": "중단을 감시하는 중",
        "status.not_running": "워처가 실행 중이 아님",
        "status.unknown": "워처 상태를 알 수 없음",
        "status.paused": "감시 일시 중지됨",
        "status.recovery_on": "자동 복구가 켜져 있습니다",
        "status.recovery_paused": "자동 복구가 일시 중지되었습니다",
        "status.recovery_idle": "워처가 실행 중이어야 복구할 수 있습니다",
        "status.pending_none": "대기 중인 작업 없음",
        "status.pending_one": "복구 1건 대기 중",
        "status.pending_many": "복구 {n}건 대기 중",
        "status.unavailable": "상태를 읽을 수 없음",
        "status.unavailable_detail": "설정은 계속 변경하고 저장할 수 있습니다",

        "action.save": "저장",
        "action.close": "닫기",
        "action.restore": "기본값으로",
        "action.start": "워처 시작",
        "action.pause": "복구 일시 중지",
        "action.resume": "복구 다시 시작",

        "start.working": "워처를 시작하는 중...",
        "start.waiting": "워처가 응답하기를 기다리는 중",
        "start.exited": "시작했다가 곧 종료되었습니다 - 설치 폴더의 로그를 확인하세요",
        "start.unconfirmed": "시작했지만 실행 중인지 아직 확인되지 않았습니다",
        "start.failed": "워처를 시작하지 못했습니다.",

        "panel.pending_title": "재개 대기 중",
        "panel.col_conversation": "대화",
        "panel.col_state": "상태",
        "panel.col_attempts": "시도",
        "panel.more": "외 {n}건",
        "panel.saving": "저장하는 중...",
        "panel.saved": "저장했습니다.",
        "panel.not_saved": "저장하지 못했습니다: {reason}",
        "panel.refused": "거부됨",
        "panel.readonly": "여기서는 읽기 전용입니다. 변경하려면 Codex Auto Resume 설정 창을 사용하세요.",
        "panel.unavailable": "이 화면에서는 설정을 사용할 수 없습니다.",
        "panel.starting": "시작하는 중...",
        "panel.start_failed": "시작하지 못했습니다: {reason}",
        "panel.start_exited": "시작했다가 곧 종료되었습니다. 아무것도 감시하고 있지 않습니다.",
        "panel.start_unconfirmed": "시작했지만 실행 중인지 아직 확인되지 않았습니다. 상태를 다시 확인하세요.",

        "state.waiting_reset": "초기화 대기",
        "state.waiting_poll": "대기 중",
        "state.waiting_for_app": "Codex 대기",
        "state.waiting_for_loaded_thread": "대화 열기 대기",
        "state.waiting_for_usage": "사용량 대기",
        "state.waiting_retry": "재시도 대기",
        "state.waiting_backoff": "백오프 대기",
        "state.queued": "대기열",
        "state.submitting": "전송 중",
        "state.resumed": "재개됨",
        "state.cancelled": "취소됨",
        "state.superseded": "대체됨",
        "state.superseded_by_user": "대체됨",
        "state.failed": "실패",
        "state.submission_unknown": "결과 불명",
        "state.retry_budget_exhausted": "시도 소진",
        "state.no_progress_exhausted": "진전 없음",
        "state.terminal_failure": "중지됨",
    },
}


def catalog(environ=None) -> dict:
    """The strings for the language this machine resolves to, as a plain dict.

    Handed whole to each surface rather than looked up key by key across a process
    boundary: the standalone window makes one bridge call at startup and the panel is
    seeded once, so neither can end up rendering half of one language.
    """
    return dict(STRINGS[messages.language(environ)])


def language(environ=None) -> str:
    return messages.language(environ)
