"""Rotating local log. Only static reason codes, UUIDs and timestamps are written.

Prompt text, Codex error text, usage-account fields and secrets never reach
this module: the engine passes (thread_id, code, detail) where detail is an
interruption hash or an integer timestamp string.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import sys

from . import machine
from .domain import ids

LOGGER_NAME = "codex_auto_resume"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5
# A detail is printed if it is hex no longer than an interruption id, or a count of seconds.
_HEX = re.compile(r"[0-9a-f]{1,%d}\Z" % ids.INTERRUPTION_ID_LENGTH)
_DIGITS = re.compile(r"[0-9]{1,12}\Z")


def format_local(timestamp) -> str:
    """Unix seconds -> Windows local time with explicit UTC offset."""
    try:
        moment = datetime.fromtimestamp(float(timestamp), timezone.utc).astimezone()
    except (OverflowError, OSError, ValueError, TypeError):
        return "unknown-time"
    offset = moment.strftime("%z")
    return moment.strftime("%Y-%m-%d %H:%M:%S") + " " + offset[:3] + ":" + offset[3:]


def setup_logging(log_file: Path, *, console: bool = False, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = RotatingFileHandler(log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if console and sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    return logger


def tail(path: Path, count: int) -> list[str]:
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as stream:
            lines = stream.readlines()
    except OSError:
        return []
    count = max(0, int(count))
    return [line.rstrip("\r\n") for line in lines[-count:]] if count else []


# (state-or-code, reason) -> human message. Reason None matches any reason as fallback.
_MESSAGES = {
    ("usageLimitExceeded_detected", None): "usageLimitExceeded detected (interruption {detail12})",
    ("reset_expected", None): "reset expected at {detail_time}",
    ("reset_unknown_conservative_poll", None): "no reset timestamp available; conservative polling every {detail}s",
    ("blocking_limit_uncertain", None): "blocking limit bucket uncertain; live usage will be verified before resume",
    ("checking_eligibility", None): "checking eligibility",
    ("loaded", None): "loaded",
    ("queue_submission_started", None): "reserved interruption; submitting continuation via codex queue",
    ("continuation_submitted", None): "continuation submitted",
    ("resume_confirmed", None): "resume confirmed",
    ("waiting_reset", None): "waiting for reset",
    ("waiting_poll", None): "waiting (no reset timestamp; conservative polling)",
    ("waiting_for_app", "desktop_app_unavailable"): "ChatGPT app or its Codex server not running; waiting",
    ("waiting_for_loaded_thread", "notLoaded"): "notLoaded\nwaiting until user opens this thread in ChatGPT app",
    ("waiting_for_loaded_thread", "loaded_state_unknown"): "loaded state unknown; waiting safely without queueing",
    ("waiting_for_loaded_thread", "loaded_recheck_failed"): "loaded re-check failed at dispatch time; waiting",
    ("waiting_for_usage", "usage_unavailable"): "usage still unavailable; waiting for reset",
    ("waiting_for_usage", "usage_unknown"): "usage status unknown; waiting without queueing",
    ("waiting_for_usage", "usage_recheck_failed"): "usage re-check failed at dispatch time; waiting",
    ("waiting_retry", "queue_process_not_started"): "queue process did not start; retrying with bounded backoff",
    ("waiting_retry", "thread_submission_cooldown"): "recent submission on this thread; cooling down",
    ("waiting_retry", "daily_submission_cap"): "daily submission cap reached; deferring until the 24h window rolls over",
    ("submitting", "awaiting_delivery_receipt"): "awaiting delivery receipt",
    ("queued", None): "queued; awaiting delivery receipt",
    ("resumed", None): "resumed",
    ("submission_unknown", None): "submission outcome unknown; will NOT resend automatically ({reason})",
    ("superseded", "latest_turn_changed"): "latest turn changed; interruption superseded, no resume",
    ("superseded", "owned_queue_removed"): "undelivered continuation removed from queue; interruption superseded",
    ("failed", "daily_submission_cap"): "daily submission cap reached; giving up on this interruption",
    ("failed", "queue_launch_retry_limit"): "queue launch retry limit reached; giving up on this interruption",
    ("failed", "owned_queue_removed"): "undelivered continuation removed from queue; marked failed (no resend)",
    ("cancelled", "owned_queue_removed"): "undelivered continuation removed from queue; cancelled",
    ("cancelled", None): "cancelled",
    ("reconciliation_unavailable", None): "reconciliation unavailable this tick; no submission",
    ("detection_unavailable_no_submission", None): "Codex local state unavailable; detection skipped, no submission",
    ("eligibility_check_failed_no_submission", None): "eligibility check failed; no submission",
}


def _safe_detail(detail) -> str:
    if detail is None:
        return ""
    text = str(detail)
    if _HEX.fullmatch(text) or _DIGITS.fullmatch(text):
        return text
    return "?"


def render(thread_id, code, reason, detail=None) -> str:
    """One line for one transition or event, with the reason for it whenever there is one.

    A (state, reason) pair that has been given words keeps them: those words say the
    reason better than its code would, and appending the code beside them would read like
    two reasons. Everything else - a general message for the state, or no message at all -
    gets the reason added, because a line that says only what a record became sends its
    reader back to the source for why.
    """
    template = _MESSAGES.get((code, reason))
    if template is None:
        template = _MESSAGES.get((code, None), str(code))
        if reason and "{reason}" not in template:
            template += " ({reason})"
    safe_detail = _safe_detail(detail)
    values = {
        "detail": safe_detail,
        "detail12": safe_detail[:12],
        "detail_time": format_local(int(safe_detail)) if _DIGITS.fullmatch(safe_detail) else "unknown-time",
        "reason": reason if isinstance(reason, str) and re.fullmatch(r"[A-Za-z0-9_]{1,80}", reason) else "unspecified",
    }
    text = template.format(**values)
    prefix = ""
    if ids.is_uuid(thread_id):
        prefix = "thread " + thread_id + ": "
    return "\n".join(prefix + line for line in text.split("\n"))


# Which of the engine's two logging shapes a code is: a state transition, whose second
# argument is the reason for it, or an event, whose second argument is a detail. This was
# a hand-written list of 13 names and the state machine has 27, so for the other 14 -
# every outcome of a recovery turn among them - the reason arrived in the detail slot,
# where no template prints it, and the line came out as the bare state name. Derived from
# the state machine now, so a state added there is a state here on the same commit.
STATE_CODES = frozenset(machine.STATES)


class EngineLog:
    """Callable adapter with the engine's (thread_id, code, detail) signature."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def __call__(self, thread_id, code, detail=None):
        # Engine transitions call log(thread, state, reason); events call log(thread, code, detail).
        reason = None
        if code in STATE_CODES:
            reason, detail = (detail if isinstance(detail, str) else None), None
        for line in render(thread_id, code, reason, detail).split("\n"):
            self.logger.info(line)
