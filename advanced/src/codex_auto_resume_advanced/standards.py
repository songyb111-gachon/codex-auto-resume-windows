# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The standards a capability may say it departs from: every id the standards file numbers.

A capability belongs in this edition only because it breaks at least one of the standards the
standard edition keeps, and its statement names which (registry.CapabilityDef.departs_from). A
capability that names none keeps every standard, so it belongs in the standard edition; one that
names an id this file does not hold names nothing a person can look up. The registry refuses
both.

The ids are those of the reconciled standards, BASIS below: the edition frame 0.1-0.7 and the
families A-J, each numbered from 1 without gaps. The file itself is the owner's and is not
shipped; advanced/tests/test_advanced_registry.py reads it, where it is at hand, and requires
exactly these ids. A new standard is a new count here, in the commit that cites it.
"""
from __future__ import annotations

BASIS = "standards-2026-09-23.md"

# (prefix, how many) in the order the file has them.
FAMILIES = (
    ("0.", 7),   # the edition boundary
    ("A", 30),   # what it may send to Codex, and when
    ("B", 17),   # what it reads, and how
    ("C", 13),   # network
    ("D", 13),   # privacy and the data it keeps
    ("E", 14),   # failure behaviour
    ("F", 14),   # footprint on the machine
    ("G", 13),   # the Compatibility Registry's authority
    ("H", 13),   # user control
    ("I", 17),   # release and supply chain
    ("J", 14),   # presentation rules that are promises
)

STANDARDS = tuple(prefix + str(number) for prefix, count in FAMILIES
                  for number in range(1, count + 1))
