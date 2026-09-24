"""The exact continuation the watcher would send, under settings that are being edited.

Read-only, and the one place this layer builds a message at all: it saves nothing, sends
nothing, and is why a person can see what a setting will do before storing it.
"""
from __future__ import annotations

import time

from .. import continuation, reasons, settings
from .errors import ControlError


class PreviewMixin:
    """Showing the message without sending it."""

    # ------------------------------------------------------------ continuation
    def preview_continuation(self, category, changes=None, *, now=None) -> dict:
        """The exact continuation the watcher would send, under the settings being edited.

        `changes` are unsaved edits layered over the stored settings, so a Preview follows
        what somebody is choosing or typing before anything is saved. A Custom message that
        would be refused is reported beside the preview rather than previewed: what the
        preview then shows is what would really be sent, which is the fallback. Previewing
        text that could never be stored would show a message nobody will ever receive.

        The text comes from `continuation.for_settings`, the same function the watcher calls
        when it sends. There is no second rendering of a continuation anywhere.
        """
        # Malformed requests, which only a front end with a bug can make. Like a value the
        # settings validator refuses, they carry the generic code and say exactly what was
        # wrong in the sentence.
        if category not in reasons.RECOVERABLE:
            problem = "a preview is only available for a recoverable kind of interruption"
            raise ControlError(problem, code="request_failed")
        values = dict(self.get_settings())
        refusal = refusal_code = refusal_detail = None
        if changes is not None:
            if not isinstance(changes, dict):
                problem = "changes must be an object"
                raise ControlError(problem, code="request_failed")
            unknown = sorted(set(changes) - set(settings.FIELDS))
            if unknown:
                problem = "unknown setting: %s" % ", ".join(unknown)
                raise ControlError(problem, code="request_failed")
            for name, value in changes.items():
                is_text = settings.is_custom_text(name)
                if is_text and value is not None and not (isinstance(value, str) and not value.strip()):
                    try:
                        continuation.validate_custom(value)
                    except continuation.CustomMessageError as exc:
                        if refusal is None:
                            refusal, refusal_code, refusal_detail = str(exc), exc.code, exc.detail
                        continue
                    values[name] = value
                elif is_text:
                    values[name] = None
                else:
                    values[name] = value
            values = settings.coerce(values)
        moment = time.time() if now is None else float(now)
        # A stand-in record with only the fields a message may refer to. A usage limit
        # previews with a reset an hour away, so {reset_time} shows a real time.
        sample = {"category": category, "recovery_attempts": 0,
                  "reset_at": moment + 3600 if reasons.has_reset_time(category) else None}
        limits = {"max_recovery_attempts": values["max_recovery_attempts"]}
        text = continuation.for_settings(category, values, row=sample, limits=limits)
        return {"category": category, "locale": continuation.resolve_locale(values),
                "style": continuation.style_from(values),
                "source": continuation.source_for(category, values, row=sample, limits=limits),
                "text": text, "refusal": refusal, "refusal_code": refusal_code,
                "refusal_detail": refusal_detail}
