# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The advanced edition's state: one file, config/advanced/advanced.sqlite, and nothing else.

Arming, the spend ledger, the edition's own records, the overrides, the journal and the sampler
share one file, so that arming generations, spend-before-send and the claims share one
transaction model. Nothing of it is in core's state.sqlite or settings.json, and no secret is in
it at all: a secret goes to Windows Credential Manager (credentials.py).

    session   the file, its directory and marker, the transaction, attaching it to the claim
    schema    the tables as they are created today
    arming    each capability's state, the generation and the global ceiling
    spend     the units spent, and the counts the ceilings read
    records   the edition's own records, and overrides on core's
    journal   what happened, the sampler's counts, and the bounds on every table
"""
from __future__ import annotations

from ..registry import REGISTRY
from .arming import ArmingMixin
from .journal import EVENT_LIMIT, EVENT_MAX_AGE, JournalMixin  # noqa: F401
from .records import RecordsMixin
from .schema import ATTACHED, FILE_NAME, SCHEMA_VERSION, TABLES  # noqa: F401
from .session import SessionMixin, StaleGeneration, StateError  # noqa: F401
from .spend import SpendMixin


class AdvancedState(SessionMixin, ArmingMixin, SpendMixin, RecordsMixin, JournalMixin):
    """One installation's advanced state, for one process: opened when first needed."""

    def __init__(self, paths, *, registry=REGISTRY, **options):
        super().__init__(paths, registry=registry, **options)
