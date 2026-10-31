# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Recover every conversation but Codex's own (v0.6.16-beta.3; users asked, the owner's plan of 2026-10-13): at P19.

The standard edition takes up only what it can prove is a person's own desktop conversation - an allow-list, fail
closed: Codex's `thread_source` user, chatgpt_handoff, or none at all (core's codex/values.OWN_THREAD_SOURCES, A15).
A label Codex adds tomorrow is left alone there. With this on, core takes up every desktop conversation but the kinds
Codex makes for itself - a closed deny-list, core's codex/values.INTERNAL_THREAD_SOURCES: subagent (subagent_parent
tells the parent instead), guardian_review, memory_consolidation and agent_created_thread, the ThreadSource values
Codex writes that are not a person's own (the survey of the owner's PC, 2026-10-13: user, chatgpt_handoff,
agent_created_thread, none, subagent, guardian_review; and memory_consolidation from codex-rs). Everything else core
checks stays: the app's own originator and source, not archived, paginated, the state row and the rollout's first
line saying the same label of that very id - and every gate a recovery passes, the conversation switched on and held
by the app before anything is sent.

It answers one closed word, EVERY_DESKTOP (domain/plughands.Widening), which core reads at the one place a
conversation is judged (codex/history._eligibility) through codex/values.taken_thread_source. Its code decides nothing
else and reads nothing. Turned off (v0.6.20, the pair audit), core cancels the waiting records of the conversations only
it took up (engine/kinds.py, session_kind_off), as turning other_sessions off cancels its own.
"""
from __future__ import annotations

from codex_auto_resume.domain.plughands import Widening

CAPABILITY = "every_conversation"


class EveryConversation:
    """every_conversation's code: its answer at P19."""
    __slots__ = ("paths",)

    def __init__(self, paths):
        self.paths = paths

    def eligibility(self):
        return frozenset({Widening.EVERY_DESKTOP})


def make(paths) -> EveryConversation:
    return EveryConversation(paths)
