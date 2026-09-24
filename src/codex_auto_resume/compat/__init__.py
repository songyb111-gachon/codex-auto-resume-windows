"""Codex Compatibility Registry: the model and the data format. Pure - no file, process or
network access happens in this module.

What it answers is narrow: for the Codex engine on this machine, which of the things this
product does can be relied on, and why. Every answer is one of six states (v0.6.7):
* ``VERIFIED`` a real recovery on this exact version exercised it; ``CHECKED`` the maintainer's
  checks passed on it, nothing more; ``COMPATIBLE`` the local checks pass, no claim either way;
* ``FAILED_HERE`` a local check failed on a version the data checked or verified - this machine;
* ``INCOMPATIBLE`` a local check failed, or registry data says this build is unsafe;
* ``UNKNOWN``      - it cannot be established, because a check could not run.

Two rules decide every answer, and they are the whole reason the registry can be fed data
from outside the release without that data being able to make anything less careful:

1. **A failed local check always wins.** Nothing a registry document says can turn a local
   FAIL into anything that sends: INCOMPATIBLE, or FAILED_HERE where the data vouched for it.
2. **Registry data can never raise a capability above what the local checks allow.** It can
   restrict anything (INCOMPATIBLE, for an exact version or a range of them); it can elevate
   only a local PASS, only to CHECKED or VERIFIED, for an exact version string. An unrunnable
   check stays UNKNOWN whatever the data claims. `resolve()` is those two rules, in that order.

The data format carries one integer major (`codex-auto-resume-compat/1`). An unknown major,
a malformed document, a duplicate key, a non-finite number, a range that tries to grant
trust, or a document that says it requires a signature (nothing verifies one yet) is
rejected *whole* - never partly read. Unknown keys, unknown capability ids and unknown state
names are ignored, and an unknown state is never treated as VERIFIED. Every reason that
reaches a person or a model is a code from a closed vocabulary; no free text from a registry
document goes anywhere.

The signature slot (`signature`, `key_id`, `requires_signature`) is reserved in format 1 so
that signing can arrive as a data change rather than a format major: a document that sets
`requires_signature` is rejected entirely until a verifier exists, and a cached document may
not lower it relative to the bundled baseline.

Since v0.6.10-alpha this is the front of compat/, and the model is four files:
model.py (the format), standing.py (what a document says about a version),
report.py (the report and its views) and permits.py (what may be done at a tier).
The io half is compatio.py's, in the same package. Every name the module had is
re-exported here, so `compat.X` reads as it did.
"""
from __future__ import annotations

from .model import (ADVISORY_ID_RE, BOUND_RE, BUNDLED_STATES, CACHE_FORMAT, CACHE_ORIGINS,
                    CACHE_STATES, CAPABILITIES, CHECKED, CHECKS, COARSE, COMPATIBLE, DATA_SOURCES,
                    DATE_RE, DocumentError, ENGINE_STATES, EPOCH_MAX, EPOCH_MIN, EVIDENCE_RE,
                    FAIL, FAILED_HERE, FORMAT, FORMAT_MAJOR, FORMAT_PREFIX, FUTURE_SKEW_SECONDS,
                    HEX64_RE, IMPORT_REASONS, INCOMPATIBLE, MAX_ADVISORIES, MAX_CACHE_BYTES,
                    MAX_DOCUMENT_BYTES, MAX_ENGINES, MAX_EVIDENCE, MAX_REPORT_BYTES,
                    NOT_APPLICABLE, PASS, PRODUCT_RE, REASONS, RECOMPUTE_SECONDS,
                    REGISTRY_REASONS, REPORT_FORMAT, REPORT_FUTURE_SECONDS, REPORT_MAX_AGE,
                    RESOLUTION_REASONS, RESTRICTING_STATES, RESULTS, SAFE_VERSION_RE, SEND_GATE,
                    SOURCES, STATES, TIERS, TIMESTAMP_RE, TRUSTING_STATES, UNAVAILABLE, UNKNOWN,
                    VERIFIED, VERSION_RE, VIEW_REASONS, VIEW_STATUSES, _ORDER, _OWN_REASON,
                    _bound, _finite_float, _integer, _key, _registry_reason, _reject_constant,
                    _reject_duplicates, _timestamp, decode, parse_document, parse_version,
                    product_key, safe_version, validate_document)  # noqa: F401
from .standing import (ACCEPTED_CHECKS, _in_range, accepted_word, aggregate, combine,
                       document_standing, evaluate, evidence_for, resolve, verified_versions)  # noqa: F401
from .report import (_all_unknown, _clean_capabilities, _clean_data, _clean_engine,
                     _epoch_or_none, _finite_number, _small_int_or_none, build_report, mcp_view,
                     unusable_view, validate_report, view_of)  # noqa: F401
from .permits import (PERMIT_REASONS, permits)  # noqa: F401

__all__ = ["ACCEPTED_CHECKS", "ADVISORY_ID_RE", "BOUND_RE", "BUNDLED_STATES", "CACHE_FORMAT",
           "CACHE_ORIGINS", "CACHE_STATES", "CAPABILITIES", "CHECKED", "CHECKS", "COARSE",
           "COMPATIBLE", "DATA_SOURCES", "DATE_RE", "DocumentError", "ENGINE_STATES", "EPOCH_MAX",
           "EPOCH_MIN", "EVIDENCE_RE", "FAIL", "FAILED_HERE", "FORMAT", "FORMAT_MAJOR",
           "FORMAT_PREFIX", "FUTURE_SKEW_SECONDS", "HEX64_RE", "IMPORT_REASONS", "INCOMPATIBLE",
           "MAX_ADVISORIES", "MAX_CACHE_BYTES", "MAX_DOCUMENT_BYTES", "MAX_ENGINES",
           "MAX_EVIDENCE", "MAX_REPORT_BYTES", "NOT_APPLICABLE", "PASS", "PERMIT_REASONS",
           "PRODUCT_RE", "REASONS", "RECOMPUTE_SECONDS", "REGISTRY_REASONS", "REPORT_FORMAT",
           "REPORT_FUTURE_SECONDS", "REPORT_MAX_AGE", "RESOLUTION_REASONS", "RESTRICTING_STATES",
           "RESULTS", "SAFE_VERSION_RE", "SEND_GATE", "SOURCES", "STATES", "TIERS",
           "TIMESTAMP_RE", "TRUSTING_STATES", "UNAVAILABLE", "UNKNOWN", "VERIFIED", "VERSION_RE",
           "VIEW_REASONS", "VIEW_STATUSES", "_ORDER", "_OWN_REASON", "_all_unknown", "_bound",
           "_clean_capabilities", "_clean_data", "_clean_engine", "_epoch_or_none",
           "_finite_float", "_finite_number", "_in_range", "_integer", "_key", "_registry_reason",
           "_reject_constant", "_reject_duplicates", "_small_int_or_none", "_timestamp",
           "accepted_word", "aggregate", "build_report", "combine", "decode", "document_standing",
           "evaluate", "evidence_for", "mcp_view", "parse_document", "parse_version", "permits",
           "product_key", "resolve", "safe_version", "unusable_view", "validate_document",
           "validate_report", "verified_versions", "view_of"]
