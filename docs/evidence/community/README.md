# Reported: what other people's machines say

Written by [codex-compat-reporter](https://github.com/songyb111-gachon/codex-compat-reporter), the tool anyone can run on their own Windows machine. Each file holds counts, states and times from that machine - no conversation text, no identifiers, no paths.

**Reported is a grade of its own.** What is known about a Codex version is said with four words, and they are a ladder: *verified*, *checked*, *compatible*, and *failed here*. Reported is not one of them and never becomes one. Nothing can prove that a report was not written by hand on the machine that sent it, so a report never moves a version up the ladder. It is shown beside the version, with the number of reports that said the same thing. A version whose own evidence says nothing stays *compatible* however many reports arrive.

A report is counted as **worked** when at least one of its records was delivered and ended in the state `recovered`; as **failed** when at least one delivered record ended in `recovery_turn_failed`, `failed` or `terminal_failure`; and as **neither** when no delivered record ended in either, which includes a report that delivered nothing. One report can be counted as both, and that is shown rather than resolved. There is one report per GitHub login per Codex version, so these are reports, not machines.

Every conclusion in a report is recomputed from the records it carries when it is filed, and every sentence in it is replaced by one of ours, so nothing here is displayed as its sender wrote it.

| Codex version | Reports | Worked | Failed | Neither | Both |
| --- | --- | --- | --- | --- | --- |
| - | none yet | - | - | - | - |

### Every report

| Codex version | Reported by | Says | Records | Delivered | Recorded |
| --- | --- | --- | --- | --- | --- |
| - | - | - | - | - | - |

Written by build/community_report.py whenever a report is filed or withdrawn - by .github/workflows/community-file.yml, or by the maintainer's tool - from index.json. Do not edit it by hand: tests/test_reported_data.py holds it equal to what that code writes.
