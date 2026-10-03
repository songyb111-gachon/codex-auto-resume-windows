# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The standards a capability may say it departs from: every id the standards file numbers.

A capability belongs in this edition only because it breaks at least one of the standards the
standard edition keeps, and its statement names which (registry.CapabilityDef.departs_from). A
capability that names none keeps every standard, so it belongs in the standard edition; one that
names an id this file does not hold names nothing a person can look up. The registry refuses
both.

The ids are those of the reconciled standards, BASIS below: the edition frame 0.1-0.7, the
families A-J, and family K, each numbered from 1 without gaps. The file is public from v0.6.11:
docs/STANDARDS.md at the repository's root - with a Korean twin on dev; main, English only, has
none - where each rule says how it is held and which tests hold it. It is not in either edition's
archive, so nothing here reads it at run time; advanced/tests/test_advanced_registry.py does, and
requires exactly these ids, family by family, and that every test the file names is in the
repository. A new
standard takes the next number in its family and is a new count here, in the same commit
(docs/CONTRIBUTING.md).

Family K (2026-09-28) is the advanced edition's own rules - the standard archive holds none of its
code, updates stay within an edition, arming only in the Dashboard, off by default, pause and
consent first, warnings rather than refusals, tripwires - so it binds every capability rather than
being something one may break. A capability departs only from the standards the standard edition
keeps, DEPARTABLE below; one that named a K id would be naming a rule of the edition it is in.
"""
from __future__ import annotations

# Repository-relative: the standards file the registry's test reads these ids from, reconciled
# on 2026-09-23 and kept by the owner, with family K added on 2026-09-28.
BASIS = "docs/STANDARDS.md"

# (prefix, how many) in the order the file has them.
FAMILIES = (
    ("0.", 7),   # the edition boundary
    ("A", 30),   # what it may send to Codex, and when
    ("B", 17),   # what it reads, and how
    ("C", 13),   # network
    ("D", 13),   # privacy and the data it keeps
    ("E", 14),   # failure behaviour
    ("F", 15),   # footprint on the machine
    ("G", 13),   # the Compatibility Registry's authority
    ("H", 14),   # user control
    ("I", 17),   # release and supply chain
    ("J", 14),   # presentation rules that are promises
    ("K", 7),    # the advanced edition's own rules, which every capability keeps
)

STANDARDS = tuple(prefix + str(number) for prefix, count in FAMILIES
                  for number in range(1, count + 1))

# The families a capability may say it departs from: every one but K.
BINDING = ("K",)
DEPARTABLE = tuple(standard for standard in STANDARDS if standard[0] not in BINDING)
