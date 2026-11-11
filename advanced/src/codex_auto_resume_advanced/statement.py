# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What a person reads before a capability is turned on: its statement, in their own language.

Every capability has one, in five fields - what it does, what the standard edition does
instead, the standards it departs from, what can go wrong and how to stop it - and in every one
of the product's languages (l10n.LOCALES, the held ones too). It has a revision (registry.CapabilityDef.revision): arming names
the revision the person read, and a statement that changes afterwards turns the capability off
until they have read the new one.

The words live in this package's own catalogs, `locales/<locale>.json`, one per language, and
are held to core's rules by core's own code (`l10n.read_catalog`, `l10n.fill`): UTF-8 JSON, text
only, no key twice, English as the layer every other language is laid over, `{name}`
placeholders filled and nothing else touched. A capability's fields are the keys
`statement.<id>.<field>`; the titles of the fields, the words for the three states and the
kill switch's name are this edition's own and ship now, with no capability yet. So do the words
of the warnings a statement shows above its fields (`warning.<word>`, vocabulary.ArmingWarning),
with their title and the note that none of them stops the person turning the capability on.

The first key of every catalog is `_edition`, which holds the line every shipped file of this
edition carries, for the audit of the standard archive to look for.
"""
from __future__ import annotations

from pathlib import Path

from codex_auto_resume import l10n

from .vocabulary import ArmingWarning, Field, ReportRefusal, ReportWrite, SteerReason, WebReason

DIRECTORY = Path(__file__).resolve().parent / "locales"
FIELDS = tuple(Field)
SENTINEL_KEY = "_edition"
ALL_OFF_KEY = "all_off"
# The edition badge, in this package's own words (decision C12). The status carries the code
# `advanced` and the count of what is armed; a surface turns them into these. `summary` takes
# `{n}`, the count. `not_loaded` is the word an installation whose package could not be loaded
# shows - it is the standard edition then, and says so.
BADGE_KEY = "edition.badge"
NOT_LOADED_KEY = "edition.not_loaded"
SUMMARY_KEY = "edition.summary"
EDITION_KEYS = (BADGE_KEY, NOT_LOADED_KEY, SUMMARY_KEY)
# The warnings' words: a title, the note under it, and one line for each warning.
WARNING_TITLE_KEY = "warning.title"
WARNING_NOTE_KEY = "warning.note"


def key(capability, field) -> str:
    """The catalog key of one field of one capability's statement."""
    return "statement.%s.%s" % (capability, Field(field))


def title_key(field) -> str:
    return "field.%s" % Field(field)


def warning_key(warning) -> str:
    return "warning.%s" % ArmingWarning(warning)


WARNING_KEYS = (WARNING_TITLE_KEY, WARNING_NOTE_KEY) + tuple(warning_key(word) for word in ArmingWarning)

# The Dashboard's Advanced features page (advanced/gui/AdvancedPage.cs): its own words, each
# capability's name (`name.<id>`) and the three states' words, handed over whole by the bridge's
# advanced-words (`words`). The window's catalog is core's, so a word of this page lives here and
# nowhere in core, and the standard edition carries none of them.
PAGE_PREFIX = "page."
NAME_PREFIX = "name."
PAGE_KEYS = tuple(PAGE_PREFIX + name for name in (
    "nav", "col_feature", "col_state", "choose", "unavailable",
    "policy.forbid", "policy.not_allowed", "policy.shadow_only",
    "about", "limits", "per_day", "per_conversation", "nominal", "hourly", "hourly_note",
    "turn_on", "watch", "turn_off", "all_off",
    "confirm.on", "confirm.watch", "confirm.changed", "confirm.version",
    "done.on", "done.watch", "done.off", "done.all_off", "done.hourly",
    "refused.changed", "refused.unavailable", "refused.other", "refused.hourly",
    "statement_unavailable", "refused.unread",
    "tripped", "tripped.measurement_failed", "tripped.failed_here", "tripped.incompatible",
    "tripped.local_check_failed", "tripped.submission_unknown", "tripped.hook_exception",
    "tripped.statement_changed", "tripped.engine_changed",
    # v0.6.22: the automatic check (autocheck.py) - a call gone, and each line a capability's grade is said in.
    "tripped.auto_check_failed", "kept.auto_check_failed",
    "check.measured", "check.auto_checked", "check.auto_checked_whole", "check.offered_only",
    "check.failed_still_offered",
    # v0.6.14: a capability's own choices, the rules for Codex's error codes and the samples of what nothing
    # classified, and what the page says of each.
    "options", "option.attempts", "option.ceiling_hours", "option.workers", "option.days", "option.hours", "done.option", "refused.option",
    "refused.choice", "rules", "rules.none", "rules.full", "rule.code", "rule.sampled", "rule.status",
    "rule.any_status", "rule.kind", "rule.hits", "rule.add", "rule.remove", "rule.known", "done.rule_added",
    "done.rule_removed", "refused.rule_shape", "refused.rule_known", "refused.rule_decision",
    "refused.rule_range", "refused.rule_overlap", "samples", "samples.none", "sample.code", "sample.no_code",
    "sample.status", "sample.count",
    # v0.6.14: Keep it on, what a kept-on capability noted instead of turning itself off, and Send now.
    "keep_on", "keep_on.off", "keep_on.on", "keep_on.again", "keep_on.turn_on", "keep_on.send_again",
    "keep_on.turn_off", "confirm.keep_on", "confirm.send_again", "done.keep_on", "done.keep_on_off",
    # v0.6.22: Turn on's Keep it on check box, ticked unless unticked.
    "confirm.keep_choice", "confirm.keep_failed_here", "confirm.keep_needs", "done.keep_on_with",
    "refused.not_on", "kept.statement_changed", "kept.measurement_failed", "kept.failed_here", "kept.incompatible",
    "kept.local_check_failed", "kept.hook_exception", "kept.submission_unknown", "kept.engine_changed",
    "kept.duplicate_seen", "tripped.duplicate_seen", "kept.not_delivered_on_open", "tripped.not_delivered_on_open", "send_now.title", "send_now.none", "send_now.button",
    "confirm.send_now", "done.send_now",
    # In place of the limits, for an action (the compatibility report), which sends nothing to Codex: what bounds it.
    "action_limits",
    # v0.6.14: the watch log (watchlog.py) - what a watched capability would have done, its card's words and one
    # word for each answer the log names (watchlog.WORDS, and "other" for the rest). `page.watch` is the Watch first
    # button's word, so these are `page.watchlog...`; the test ties the answers to watchlog.WORDS.
    "watchlog", "watchlog.since", "watchlog.none", "watchlog.note", "watchlog.times", "watchlog.last", "watchlog.from",
    "watchlog.answer.hold", "watchlog.answer.client_id", "watchlog.answer.admit",
    "watchlog.answer.as_network_transient", "watchlog.answer.as_timeout", "watchlog.answer.as_rate_limit_transient",
    "watchlog.answer.as_server_5xx", "watchlog.answer.as_stream_interrupted", "watchlog.answer.capacity",
    "watchlog.answer.early", "watchlog.answer.resend", "watchlog.answer.send_now", "watchlog.answer.text",
    "watchlog.answer.sender", "watchlog.answer.tick", "watchlog.answer.start_route", "watchlog.answer.unloaded",
    "watchlog.answer.concurrency", "watchlog.answer.queue_for_open", "watchlog.answer.to_session",
    "watchlog.answer.silent",
    # v0.6.19 (the groundwork): P13's two words, which a watched supervisor would answer.
    "watchlog.answer.supervise", "watchlog.answer.restart",
    # v0.6.20 (push_notices): a notice it would have pushed.
    "watchlog.answer.notice",
    # v0.6.20 (power_after_tasks): how the tasks a person picked stand, said to the power action.
    "watchlog.answer.power",
    # v0.6.22 (#59): a failure a watched goal continuation would take up at a reset the watcher saw (VERIFIED_RESET).
    "watchlog.answer.verified_reset",
    # v0.6.16-beta.3: a message a watched capability would have sent.
    "watchlog.answer.records",
    "watchlog.answer.other",
    # v0.6.14: the reset actions (advanced/gui/AdvancedResets.cs) - the rules of a reset credit and of a message at a
    # reset, the form they are added with, each word a rule's state and reason can be said in, the questions, notes
    # and refusals - and Longer reset messages' words in place of the limits. (Pending's Scheduled group's title went with
    # it: the rules are rows of Pending's one list from v0.6.19.)
    "confirm.reset_credit", "confirm.reset_message", "done.reset_added", "done.reset_cancelled", "done.go_on",
    "confirm.credit_now", "done.credit_now", "refused.occasion_invalid", "refused.resets_full",
    "refused.message_refused", "refused.already_scheduled", "refused.being_sent", "refused.conversation_off",
    "long_limits"))
# The reset actions' own words, `page.resets.<name>`.
RESETS_PREFIX = PAGE_PREFIX + "resets."
RESETS_KEYS = tuple(RESETS_PREFIX + name for name in (
    "window.300", "window.10080", "window.other", "ordinal.1", "ordinal.n", "state.being_sent",
    "state.window_gone", "state.count_gap", "state.ask_first", "state.count_unknown", "state.expiry_unknown",
    "state.bound", "state.no_method", "state.nothing_waiting", "state.due", "state.counting", "state.starting",
    "state.next", "state.conversation_off", "state.turned_off", "state.by_person", "state.spent",
    "state.nothing_to_reset", "state.no_credit", "state.lapsed", "state.delivered", "state.expired",
    "state.not_started", "state.unknown", "state.done", "rule.now", "rule.credit", "rule.message", "credit.title",
    "message.title", "credit.none", "message.none", "now.none", "now.note", "now", "credit.add", "message.add",
    "field.conversation", "no_conversation", "field.words", "field.window", "field.which_reached", "field.which",
    "field.repeat", "repeat.once", "repeat.every", "field.ask", "ask.no", "ask.yes", "ask.note", "credit.button",
    "message.button", "credit.note", "message.note", "go_on", "cancel", "reading.unknown", "reading",
    "reading.no_expiry", "reading.last", "count", "unproven", "unproven_failed", "ask.note_failed"))
PAGE_KEYS = PAGE_KEYS + RESETS_KEYS
# The compatibility report's card on that page (advanced/gui/AdvancedReport.cs): its own words, one for each
# write sending makes (vocabulary.ReportWrite), one for each reason it has to be sent on the web (WebReason) and
# one for each word it refuses with (ReportRefusal) - so a word the flow can answer with is one the page can say.
REPORT_PREFIX = PAGE_PREFIX + "report."
REPORT_KEYS = (tuple(REPORT_PREFIX + name for name in (
    "title", "intro", "login", "version", "write", "writing", "records", "verdict", "size", "sha256", "left_out",
    "file", "save", "saved", "watched", "check", "checking", "gh", "signed_in", "interrupted", "writes", "type",
    "send", "sending", "sent", "already", "after", "partial", "again", "lost", "last",
    "web.intro", "web.1", "web.2", "web.3", "web.4"))
    + tuple(REPORT_PREFIX + "w." + str(write) for write in ReportWrite)
    + tuple(REPORT_PREFIX + "web." + str(reason) for reason in WebReason)
    + tuple(REPORT_PREFIX + "refused." + str(code) for code in ReportRefusal))
PAGE_KEYS = PAGE_KEYS + REPORT_KEYS
# Keep going's card and the prompt queue's, on the page and Pending (v0.6.15-beta: advanced/gui/AdvancedKeepGoing.cs,
# AdvancedQueue.cs).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "keep.title", "keep.none", "keep.count", "keep.button", "keep.line",
    "keep.stop", "keep.capped", "keep.capped_failed", "confirm.keep_going", "done.keep_going", "refused.keep_count_invalid",
    "queue.title", "queue.none", "queue.add", "queue.when", "queue.when.after_turn",
    "queue.when.at_time", "queue.when.daily", "queue.when.weekly", "queue.hour", "queue.times",
    "queue.depends", "queue.depends.no", "queue.depends.yes", "queue.button", "queue.line",
    "queue.at", "queue.series", "queue.state.waiting", "queue.state.held", "queue.state.in_codex",
    "queue.state.being_sent", "queue.state.refused", "queue.unproven", "queue.unproven_failed", "queue.go_on", "confirm.prompt",
    "done.prompt_added", "refused.prompt_refused", "refused.queue_full", "refused.dependency_unknown",))
# Steer the running turn (v0.6.20, issue #50 - steer_send): the editor's When choice, its warning and its button, what a
# steer refused at once says, and History's row for a steer - its kind, its states, the words sent and what each outcome
# and each refusal means (advanced/gui/AdvancedEditor.cs, AdvancedSchedule.cs; vocabulary.SteerState, SteerReason).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "editor.when.steer", "editor.steer.warning", "editor.steer.send", "done.steer_sent", "refused.no_turn_running",
    "refused.steer_waiting", "refused.steer_full",
    "pending.kind.steer", "steer.state.waiting", "steer.state.accepted", "steer.state.unconfirmed", "steer.state.refused",
    "steer.sent", "steer.note.waiting", "steer.note.accepted", "steer.note.unconfirmed")) + tuple(
    PAGE_PREFIX + "steer.reason." + str(reason) for reason in SteerReason)
# A capability that needs another (v0.6.16-beta.3, registry.CapabilityDef.requires): what its card says it needs, the
# one confirmation that turns on what it needs too, what turning a requirement off turned off first, and the words for
# a dependent read down because what it needs is off.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "requires", "confirm.requires", "confirm.requirement", "done.on_with", "done.also_off", "refused.requirement", "refused.requirement_failed_here", "refused.failed_here",
    "tripped.requirement_off", "kept.requirement_off"))
# Stage 4's tripwires (v0.6.16-beta.4): another session that did not take what was queued for it (other_sessions), and
# Codex refusing a turn with no words (silent_continuation).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "tripped.not_dispatched_by_session", "kept.not_dispatched_by_session", "tripped.refused_by_codex",
    "kept.refused_by_codex",
    # The turns run here, each with its Stop (advanced/gui/AdvancedRuns.cs).
    "runs.title", "runs.none", "runs.until", "runs.stopping", "runs.stop", "runs.conversation", "confirm.run_stop",
    "done.run_stop",
    # What Pending and History say beside a row this edition had a hand in (AdvancedRuns.cs, CellsWritten).
    "row.kind.cli", "row.kind.ide", "row.compact", "row.model_not_restored",
    "row.silent"))
# Chat with a conversation (v0.6.19, advanced/gui/AdvancedChat.cs): its tab, its card, a message's states, the limit it
# waits for, and where a click on a notice goes while it is on.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "chat.nav", "chat.title", "chat.open", "chat.none", "chat.unread", "chat.you", "chat.codex", "chat.counts",
    "chat.in_progress",
    "chat.sending", "chat.sent", "chat.not_taken", "chat.words", "chat.send", "chat.cancel", "confirm.chat",
    "done.chat", "chat.limit", "chat.click", "chat.click.page", "chat.click.chat", "chat.click.codex"))
# The usage meter's, the wrap-up's and the pause's choices (v0.6.16-beta.3, issue #29): each OptionKey's label, and
# how its values are said.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "option.poll_minutes", "option.warn_five_hour", "option.warn_weekly", "option.wrap_five_hour",
    "option.wrap_weekly", "option.wrap_style", "option.pause_five_hour", "option.pause_weekly",
    "option.minutes", "option.percent", "option.style.1", "option.style.2", "option.style.3",
    # v0.6.16-beta.4: the wording with the numbers, and the stop percentage the words name, each window its own.
    "option.style.4", "option.stop_words_five_hour", "option.stop_words_weekly",
    # (i) Include the reset time, and Continue after the reset - each a switch on the page (v0.6.16 final), which says
    # its two values itself, as every switch of the window does.
    "option.wrap_reset_time", "option.wrap_after_reset",
    # (b) the Custom wording: its boxes, what they may hold, Save words, and each check that refuses one.
    "option.style.5", "wording.help", "wording.wrap_custom_five_hour", "wording.wrap_custom_weekly", "wording.save",
    "done.wording", "refused.wording.empty", "refused.wording.too_long", "refused.wording.control",
    "refused.wording.marker", "refused.wording.placeholder",
    # (a) what is sent, exactly, for each window, under the wording choice.
    "preview.title", "preview.300", "preview.10080",
    # (e) each window acted on or not - and (v0.6.16 final) a capability with both its windows off says it acts on
    # neither.
    "option.window_five_hour", "option.window_weekly", "option.no_window",
    # (f) a number of one's own beside the presets: Custom..., which opens the Settings page's dialog for one, in that
    # page's words (v0.6.16 final).
    "option.custom",
    # (j) the percentages of a window in order, and the forced stop below the words' stop only said.
    "refused.option_order", "warn.stop_before_words"))
# usage_analytics (v0.6.20): how many days its card shows (OptionKey.ANALYTICS_DAYS).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in ("option.analytics_days",))
# Its cards (advanced/gui/AdvancedAnalytics.cs): the pace of each window, the tokens of each project and the total, the
# conversations under a project, the narrower route's note, and Save as CSV....
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + "analytics." + name for name in (
    "pace", "used", "change", "eta", "not_enough", "resets", "no_reading", "tokens", "lifetime_only", "behind",
    "other", "hide", "show", "none", "total", "save", "numbers", "lifetime"))
# v0.6.19 (wake_for_reset): its one choice's label, how many minutes before a reset the PC is woken.
PAGE_KEYS = PAGE_KEYS + (PAGE_PREFIX + "option.wake_lead_minutes",)
# v0.6.20 (window_anchor): its three times of day and its After a reset switch, a time switched off, and the line on its
# card that says the reset its last start fixed, and that it starts nothing with no time picked and no After a reset.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "option.anchor_at_1", "option.anchor_at_2", "option.anchor_at_3", "option.anchor_after_reset", "option.off",
    "anchor.fixed", "anchor.needs_occasion", "anchor.retrying", "anchor.stopped", "crash.unsupervised"))
# open_to_send's two choices (v0.6.19, #50): how long the PC has been idle first, and Also start Codex (a switch).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in ("option.open_idle_minutes", "option.open_start_codex"))
# The prompt queue's editor (v0.6.19, #50: advanced/gui/AdvancedEditor.cs): Schedule a message..., Edit..., the dialog's
# titles, its send mode, Save and return, and what it says.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "scheduled.add", "queue.edit", "editor.title_new", "editor.title_edit",
    "editor.mode", "editor.mode.wait", "editor.mode.queue", "editor.mode.after_turn", "editor.save", "done.prompt_saved",
    "refused.prompt_moved"))
# Find a conversation (v0.6.20, #50: advanced/gui/AdvancedFind.cs): the button beside a conversation picker, the dialog it opens
# with its search box and its list, and what it says when nothing matches or the list could not be read.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "find.button", "find.title", "find.search", "find.use", "find.none", "find.failed"))
# A delivered message followed through (v0.6.20, #50: advanced/gui/AdvancedFollow.cs): History's Follow through..., the
# dialog's title, its rows - sent, delivered, each cut-off, the reset waited for, where the recovery stands - how the work
# ended, how the turn was tied to the message, a series' last occurrence, and the line for an answer that did not come.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + "follow." + name for name in (
    "button", "title", "failed", "sent", "delivered_turn", "delivered", "cut", "reset", "recovery", "end.still_running",
    "end.finished", "end.waiting", "end.recovering", "end.recovered", "end.ended", "end.unknown", "link.exact", "link.time",
    "link.ambiguous", "link.no_record", "link.not_found", "series"))
# Pictures in a scheduled message (v0.6.20, #50 item 1: advanced/gui/AdvancedEditor.cs, AdvancedSchedule.cs): the editor's
# block - its caption, Add a picture..., the line on what it takes, each thumbnail's name and Remove - the count a row
# says, and each word the bridge refuses a picture with.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "editor.images", "editor.images.add", "editor.images.help", "editor.images.kept", "editor.images.remove", "editor.images.picture",
    "queue.images", "refused.image_refused", "refused.image_too_large", "refused.images_full",
    "refused.images_unavailable"))
# Pending's one list (v0.6.19, #50; the owner's decision of 2026-10-24: advanced/gui/AdvancedSchedule.cs): the Kind of a
# message's and a rule's row, what a message does while a turn runs, History's completed messages and Delete completed,
# and the prompt queue's card pointing to Pending. The tab strip's words went with the strip.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "pending.kind.message", "pending.kind.rule", "pending.rule.held", "confirm.clear_both",
    "confirm.clear", "done.cleared", "done.cleared_kept", "scheduled.state.delivered",
    "scheduled.state.handed_over", "scheduled.mode.wait", "scheduled.mode.queue", "queue.moved"))
# See an example (v0.6.20, the owner's decision of 2026-10-29: advanced/gui/AdvancedExamples.cs): the button at the end of a
# capability's About this feature card, and the view it opens - its title, its note that the sample is made up, and its two
# panes' captions.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "example.button", "example.title", "example.before", "example.after", "example.note"))
# early_reset on Pending (v0.6.19, #50: advanced/gui/AdvancedEarly.cs): what Why it is waiting says of its last reading. Its
# line's Check now and settings button went with the line (the owner's decision of 2026-10-24), and their words.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "early.none", "early.available_first", "early.lifted", "early.limited", "early.unknown", "early.not_read"))
# v0.6.20 (push_notices, status_feed - the courier): what a push says (its event in words and the edition, also the card's
# event switches), the courier's card - its channels, fields, buttons, outcomes and refusals - and the status feed's line
# on the Overview with its choice.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "push.usage_limit_detected",
    "push.recovered",
    "push.failed",
    "push.needs_you",
    "push.stopped_unexpectedly",
    "push.restarted",
    "push.update_offered",
    "push.test",
    "push.edition",
    "courier.title",
    "courier.events",
    "courier.channel.ntfy",
    "courier.channel.webhook",
    "courier.channel.telegram",
    "courier.channel.email",
    "courier.saved",
    "courier.not_saved",
    "courier.tripped",
    "courier.secret_note",
    "courier.field.url",
    "courier.field.token",
    "courier.field.bot_token",
    "courier.field.host",
    "courier.field.port",
    "courier.field.user",
    "courier.field.password",
    "courier.field.from",
    "courier.field.to",
    "courier.save",
    "courier.replace",
    "courier.forget",
    "courier.test",
    "courier.pair",
    "courier.pair_code",
    "courier.paired",
    "courier.not_paired",
    "courier.result.sent",
    "courier.result.refused",
    "courier.result.server_error",
    "courier.result.timed_out",
    "courier.result.tls",
    "courier.result.busy",
    "courier.result.not_saved",
    "courier.result.no_answer",
    "refused.address_refused",
    "refused.secret_unavailable",
    "refused.not_saved",
    "refused.courier_unavailable",
    "done.courier_saved",
    "done.courier_forgotten",
    "confirm.courier_forget",
    "feed.label",
    "feed.degraded",
    "feed.outage",
    "option.feed_minutes",
))
# The Codex account card (v0.6.20, account_switch: advanced/gui/AdvancedAccount.cs): the account signed in, how to switch in
# Codex, the button that runs Codex's own sign-out and sign-in, its question, its wait, how it ended and its refusals.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "account.title", "account.signed_in", "account.signed_in_only", "account.api_key", "account.plan_other",
    "account.signed_out", "account.unknown", "account.guidance", "account.guidance_failed", "account.waiting", "account.button",
    "account.button_help", "confirm.account_switch", "account.result.signed_in", "account.result.cancelled",
    "account.result.timed_out", "account.result.failed", "refused.switch_unmeasured", "refused.switch_running"))
# v0.6.20 final: the restart after a sign-in - its question, why it waits, its buttons, its wait, how it ended, and its
# question and refusals (advanced/gui/AdvancedAccount.cs, control/account.restart).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "account.restart.ask", "account.restart.needed", "account.restart.help", "account.restart.busy",
    "account.restart.button", "account.restart.not_now", "account.restart.restarting", "account.restart.result.restarted",
    "account.restart.result.signed_out", "account.restart.result.not_running", "account.restart.result.not_ended",
    "account.restart.result.not_started", "account.restart.result.failed", "confirm.account_restart",
    "refused.restart_running", "refused.nothing_to_restart"))
# v0.6.20 (power_after_tasks, Discussion #57): the tasks the power action waits for, or the form they are picked with
# (advanced/gui/AdvancedPowerTasks.cs).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "powertasks.title", "powertasks.help", "powertasks.none", "powertasks.failed", "powertasks.interrupted",
    "powertasks.button", "powertasks.off", "powertasks.line", "powertasks.end.running", "powertasks.end.completed",
    "powertasks.end.failed", "powertasks.end.interrupted", "powertasks.end.unknown", "confirm.power_after_tasks",
    "done.power_after_tasks", "refused.power_no_turn", "refused.power_refused"))
# v0.6.22 (account_auto_switch): the saved accounts, their state words, the line for a sign-in kept outside a file,
# Add an account..., Save the account in use, Delete and Delete all, their questions and what came of them
# (advanced/gui/AdvancedAccounts.cs, control/autoswitch.py).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "accounts.title", "accounts.help", "accounts.not_file", "accounts.none", "accounts.state.ready",
    "accounts.state.exhausted", "accounts.state.needs_sign_in", "accounts.state.damaged", "accounts.added",
    "accounts.not_added", "accounts.add", "accounts.save", "accounts.delete", "accounts.delete_all",
    "confirm.accounts_add", "confirm.accounts_delete", "confirm.accounts_delete_all", "done.accounts_saved",
    "done.accounts_deleted", "refused.accounts_not_saved",
    # v0.6.22 final: the usage meters under each row, the line under them and Read usage (advanced/gui/AdvancedMeter.cs).
    "accounts.read", "accounts.read_wait", "accounts.reading", "accounts.read_held", "accounts.read_unknown",
    "accounts.in_use", "accounts.five_hour", "accounts.weekly", "accounts.percent", "accounts.meter", "accounts.not_read",
    "accounts.unread", "accounts.read_at", "accounts.candidate", "accounts.candidate_none",
    # and the reachability audit's R4, M10 and M11: the true reason under the heading, a Delete held by a switch or a read,
    # and Save's question.
    "accounts.no_file", "accounts.unreadable", "confirm.accounts_save", "refused.accounts_held",
    # and Switch to this account (the owner, 2026-11-08): the button, its question, how it stands and ended, what refuses
    # it, and the help line under account_switch's card, where the same saved accounts show (control/autoswitch.switch).
    "accounts.help_switch", "accounts.switch", "confirm.accounts_switch", "accounts.switching", "accounts.switched",
    "accounts.switch_not_started", "accounts.switch_undone", "accounts.switch_not_put_back", "accounts.switch_not_done",
    "refused.account_in_use", "refused.account_not_ready", "refused.accounts_switch_busy", "refused.other_engine",
))
# v0.6.23 (python_choice): the Python version card (advanced/gui/AdvancedPythons.cs, control/pythons.py).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + "python." + name for name in (
    "title", "help", "in_use", "in_use_none", "bundled", "chosen", "check", "checking", "version", "preview", "use", "current", "back",
    "none", "downloading", "verifying", "restarting", "done", "next_start", "done_back",
    "failed.list", "failed.source", "failed.download", "failed.digest", "failed.unpack", "failed.signature",
    "failed.import", "failed.start", "returned.start", "returned.line", "returned.off",
    # Its Limits card's sentence (AdvancedPage.ActionLimits): an action's own, not Longer reset messages'.
    "limits",
    # v0.6.23 final: a line python.org has no Windows embeddable package of, after a Check.
    "no_package")) + tuple(PAGE_PREFIX + name for name in (
    "confirm.python_use", "confirm.python_back", "refused.python_busy"))
# v0.6.22 (fleet_view): the Overview's Other PCs list, its columns and state words, how the folder stands, and the card
# this PC's name and folder are chosen on (advanced/gui/AdvancedFleet.cs, control/fleet.py).
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + "fleet." + name for name in (
    "title", "col.pc", "col.state", "col.waiting", "col.next", "col.written", "state.running", "state.stopped",
    "state.paused", "state.observing", "state.not_seen", "state.clock", "stand.none", "stand.unset", "stand.missing",
    "stand.held", "stand.late", "stand.not_ours", "stand.refused", "ignored", "card", "help", "alias", "alias_help",
    "folder", "no_folder", "pick", "save", "saved", "off_note", "refused_alias"))
# v0.6.22 (local_api, local_api_actions): the loopback API's card (advanced/gui/AdvancedRemote.cs), the words of its web view
# (courier/page.py) and of the example.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "option.api_port", "api.card", "api.address", "api.token_kept", "api.no_token", "api.lan", "api.copy", "api.new_token",
    "api.new_token_yes", "api.state.running", "api.state.starting", "api.state.stopped", "api.state.port_taken",
    "confirm.api_token", "done.api_copied", "done.api_token", "done.api_token_kept", "refused.api_not_copied",
    "api.title", "api.watcher", "api.recovery", "api.pending", "api.next_check", "api.ask_token", "api.refused",
    "api.word.running", "api.word.stopped", "api.word.on", "api.word.paused", "api.word.observe_only",
    "api.example.cancelled", "api.example.lan"))
# v0.6.22 (telegram_remote, telegram_continue): the remote card (advanced/gui/AdvancedRemote.cs), the answers the paired chat
# is sent (courier/telegram.py), and the tripwire of five wrong codes.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "remote.card", "remote.paired", "remote.not_paired", "remote.commands", "remote.command.status", "remote.command.list",
    "remote.command.cancel", "remote.command.pause", "remote.command.continue", "remote.command.lift_pause",
    "remote.state.running", "remote.state.starting", "remote.state.stopped", "remote.answer.help",
    "remote.answer.not_allowed", "remote.answer.paused", "remote.answer.pause_lifted", "remote.answer.list_again",
    "remote.answer.refused", "remote.answer.cancelled", "remote.answer.continued", "remote.answer.status",
    "remote.answer.list_none", "remote.answer.list_item", "remote.word.running", "remote.word.stopped", "remote.word.on",
    "remote.word.paused", "remote.word.observe_only", "tripped.bad_codes"))
# v0.6.22 final (the reachability audit's R1, M3-M7, M14): the server waiting on a watcher that is not running, Copy token,
# this PC's addresses on the local network and which to copy; the long poll's truthful states, the paired chat by its name,
# the line before a pairing and the way to the notices card; the folder typed or pasted, and a PC last heard from.
PAGE_KEYS = PAGE_KEYS + tuple(PAGE_PREFIX + name for name in (
    "api.state.no_watcher", "api.copy_token", "done.api_token_copied", "refused.api_token_not_copied", "api.lan_address",
    "api.copy_which", "remote.state.no_watcher", "remote.state.no_token", "remote.state.no_chat", "remote.paired_chat",
    "remote.not_paired_token", "remote.open_notices", "fleet.folder_help", "fleet.state.last_heard"))
# The edition's own continuations' words (v0.6.15-beta): what empty_response, subagent_parent and keep_going send -
# fixed, each passing core's continuation.validate_continuation in every language (nothing is filled in but, for a
# subagent's line, its id and a closed kind word).
CONTINUE_PREFIX = "continue."
CONTINUATION_KEYS = ((CONTINUE_PREFIX + "empty_response", CONTINUE_PREFIX + "subagent.line",
                      CONTINUE_PREFIX + "keep_going",
                      # v0.6.16-beta.3: the wrap-up's three wordings (engine/usage.py).
                      CONTINUE_PREFIX + "wrap_up.short", CONTINUE_PREFIX + "wrap_up.standard",
                      CONTINUE_PREFIX + "wrap_up.detailed",
                      # v0.6.16-beta.4: the wording with the numbers and the windows it names (engine/wrapwords.py) -
                      # filled in, so held to core's check only once filled (wrapwords.render).
                      CONTINUE_PREFIX + "wrap_up.numbers", CONTINUE_PREFIX + "wrap_up.window.five_hour",
                      CONTINUE_PREFIX + "wrap_up.window.weekly",
                      # (i): when the window resets, said with core's hour and minute; a weekly reset's date.
                      CONTINUE_PREFIX + "wrap_up.resets_at", CONTINUE_PREFIX + "wrap_up.resets_on",
                      CONTINUE_PREFIX + "wrap_up.date",
                      # (h, g): the continuation after the reset (engine/usagestop.py).
                      CONTINUE_PREFIX + "after_reset")
                     + tuple(CONTINUE_PREFIX + "subagent.kind." + kind
                             for kind in ("usage_limit", "temporary", "interrupted", "error")))


def name_key(capability) -> str:
    """The catalog key of a capability's name, as the page lists it."""
    return NAME_PREFIX + capability


class Catalogs:
    """One directory of catalogs, read once each: this package's, or a test's."""

    def __init__(self, directory=DIRECTORY):
        self.directory = Path(directory)
        self._cache = {}

    def own(self, locale) -> dict:
        """One language's own entries, exactly as its file has them. Raises l10n.CatalogError."""
        return l10n.read_catalog(self.directory / ("%s.json" % locale))

    def catalog(self, locale) -> dict:
        """Every key, in `locale` where it has one and in English where it does not. A catalog
        that cannot be read is English, as core's are (l10n.catalog): the tests fail on it, the
        runtime keeps working."""
        locale = locale if locale in l10n.LOCALES else l10n.DEFAULT
        if locale not in self._cache:
            try:
                table = dict(self.own(l10n.DEFAULT))
            except l10n.CatalogError:
                table = {}
            if locale != l10n.DEFAULT:
                try:
                    table.update(self.own(locale))
                except l10n.CatalogError:
                    pass
            self._cache[locale] = table
        return dict(self._cache[locale])

    def text(self, name, locale=None, **fields) -> str | None:
        """One entry, filled in; None when no catalog has it."""
        value = self.catalog(l10n.current() if locale is None else locale).get(name)
        return None if value is None else l10n.fill(value, **fields)

    def badge(self, on, locale=None, *, loaded=True) -> str | None:
        """The edition badge for a surface to show beside the version: the word for a loaded
        installation followed by how many capabilities are armed, or the not-loaded word for
        one whose package could not be taken. The count comes from the status's `on`; the words
        are this package's own, in `locale` or the one the process resolved to."""
        if not loaded:
            return self.text(NOT_LOADED_KEY, locale)
        return self.text(SUMMARY_KEY, locale, n=on)

    def words(self, locale=None) -> dict:
        """The Advanced features page's words in `locale`, English underneath: every `page.*`
        and `name.*` entry, and the three states' - and (v0.6.20) the edition's own continuations
        (CONTINUATION_KEYS), which See an example shows as what is sent. Unfilled - the window fills
        `{name}` and `{n}` itself, as it fills core's."""
        table = self.catalog(l10n.current() if locale is None else locale)
        return {name: value for name, value in table.items()
                if name.startswith((PAGE_PREFIX, NAME_PREFIX, "state.")) or name in CONTINUATION_KEYS}

    def missing(self, definition) -> list:
        """(locale, field) for every field of `definition`'s statement a language does not have
        in its own words. A statement is complete when this is empty."""
        found = []
        for locale in l10n.LOCALES:
            try:
                table = self.own(locale)
            except l10n.CatalogError:
                table = {}
            for field in FIELDS:
                value = table.get(key(definition.id, field))
                if not isinstance(value, str) or not value.strip():
                    found.append((locale, str(field)))
        return found

    def complete_in(self, definition, locale) -> bool:
        """Whether one language has every field of `definition`'s statement in its own words."""
        return all(found != locale for found, _field in self.missing(definition))

    def statement(self, definition, locale=None, *, warnings=()) -> dict:
        """What the Dashboard shows before the choice: the five fields, each with its title,
        the revision the choice will name, the ids of the standards it departs from, and above
        them `warnings` - the words of what holds now (arming.warnings_for), each with its line,
        which the choice confirms and never has to overcome."""
        locale = l10n.current() if locale is None else locale
        return {"capability": definition.id, "revision": definition.revision,
                "locale": locale if locale in l10n.LOCALES else l10n.DEFAULT,
                # What it needs on (v0.6.16-beta.3): the ids it requires, so the Dashboard reads their
                # statements too and turns them on in the one confirmation (surfaces.arm's `also`).
                "requires": list(definition.requires),
                "departs_from": list(definition.departs_from),
                "warnings": {"title": self.text(WARNING_TITLE_KEY, locale),
                             "note": self.text(WARNING_NOTE_KEY, locale),
                             "items": [{"warning": str(ArmingWarning(word)),
                                        "text": self.text(warning_key(word), locale)}
                                       for word in warnings]},
                "fields": [{"field": str(field), "title": self.text(title_key(field), locale),
                            "text": self.text(key(definition.id, field), locale)}
                           for field in FIELDS]}


CATALOGS = Catalogs()
