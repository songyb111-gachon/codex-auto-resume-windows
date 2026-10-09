# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The in-app compatibility report: this PC's own records, written up as codex-compat-reporter
writes them, for the person to read whole and, only if they type send, send to the project.

    records    the files read for it, read-only: the state, the spend ledger, the logs, the
               watcher's own report and Codex's history, for counts alone
    evidence   what those records say, counted as the reporter counts them: pure
    document   the file: that body in the reporter's envelope, naming this product as its writer,
               and the self-check every report passes before it is shown, saved or sent
    github     gh, the GitHub CLI the person installed: found, pinned to github.com and run as the
               reporter runs it, each in a job that ends with the process, the file on its stdin
    flow       the capability's code: the Dashboard's jobs - write, check, send - one at a time per
               home across windows, each stopped by a turn-off, a policy or a pause

Nothing is imported here: core imports the advanced package before it knows whether it will take
the plug, and a report is written only when a person asks for one. `make`, the capability's factory
(registry.COMPAT_REPORT), imports the flow only when a surface first asks for it.
"""


def make(paths):
    """The compatibility report's code for the installation at `paths` (registry.CapabilityDef.make)."""
    from .flow import Flow
    return Flow(paths)
