# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The advanced edition's state: one file, config/advanced/advanced.sqlite, and nothing else.

Arming, the spend ledger, the edition's own records, the overrides, the journal, the sampler and -
from version 3 - the capabilities' choices, rules, admissions and samples share one file, so that arming generations, spend-before-send and the claims share one
transaction model. Nothing of it is in core's state.sqlite or settings.json, and no secret is in
it at all: a secret goes to Windows Credential Manager (credentials.py).

    session   the file, its directory and marker, the transaction, attaching it to the claim
    schema    the tables as they are created today
    arming    each capability's state, the generation and the global ceiling
    spend     the units spent, and the counts the ceilings read
    records   the edition's own records, and overrides on core's
    journal   what happened, the sampler's counts, and the bounds on every table
    choices   the capabilities' choices and rules, what they took up, and what they keep of it
    resets    the reset actions' windows, last reading, rules and spends (v0.6.14)
    continuations  the edition's own continuations, and the conversations kept going (v0.6.15-beta)
    prompts   a person's queued prompts (v0.6.15-beta)
    meter     the usage meter's last reading of each window, and what each stage acted for (v0.6.16-beta.3)
    runs      a turn run here (v0.6.16-beta.4)
    chat      the Dashboard's chat messages (v0.6.16-beta.4)
    analytics the tokens each conversation used a day, the rollouts read, and the meter's samples (v0.6.19)
"""
from __future__ import annotations

from ..registry import REGISTRY
from .analytics import AnalyticsMixin
from .arming import ArmingMixin
from .choices import ChoicesMixin, Refused, Scoped  # noqa: F401
from .continuations import ContinuationsMixin
from .meter import MeterMixin
from .journal import EVENT_LIMIT, EVENT_MAX_AGE, WATCH_LIMIT, JournalMixin  # noqa: F401
from .prompts import PromptMovesMixin, PromptsMixin
from .records import RecordsMixin
from .resets import ResetsMixin
from .runs import RunsMixin
from .chat import ChatMixin
from .schema import ATTACHED, FILE_NAME, SCHEMA_VERSION, TABLES  # noqa: F401
from .session import SessionMixin, StaleGeneration, StateError  # noqa: F401
from .spend import SpendMixin


class AdvancedState(SessionMixin, ArmingMixin, SpendMixin, RecordsMixin, JournalMixin, ChoicesMixin,
                    ResetsMixin, ContinuationsMixin, PromptsMixin, PromptMovesMixin, MeterMixin, RunsMixin,
                    ChatMixin, AnalyticsMixin):
    """One installation's advanced state, for one process: opened when first needed."""

    def __init__(self, paths, *, registry=REGISTRY, **options):
        super().__init__(paths, registry=registry, **options)
