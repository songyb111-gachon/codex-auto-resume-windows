"""This PC's own compatibility report (v0.6.19, both editions): written on request from the product's
own records, shown whole with its SHA-256 in the Dashboard's Diagnostics page and put in the
diagnostics export - and sent nowhere.

    reading    the files read for it, read-only: the state, the logs and the watcher's own report
    evidence   what those records say, counted as codex-compat-reporter counts them: pure
    document   the file: every version's body in an envelope that names nobody, and the self-check
               every report passes before it is shown or exported

The advanced edition's report, which a person can send, reads and counts with the same code and adds
its spend ledger, Codex's history for the progress counts, a GitHub login and a send of its own.
"""


def write(paths, *, now=None, view=None) -> dict:
    """The report for the installation at `paths`, as the Dashboard is given it (document.written), or
    {"refusal": code} when the records cannot be read or the report would be more than a report holds."""
    from . import document, reading
    try:
        made = document.assemble(reading.read_all(paths, view=view), now=now)
    except (reading.ReadRefused, document.DocumentRefused) as refused:
        return {"refusal": str(refused.code)}
    return document.written(made)


def for_bundle(paths):
    """What the diagnostics export asks for its `compatibility_report` (diagnostics.collect `report`): the
    report written for the bundle, whole - its SHA-256, its size and the report itself - or the refusal."""
    def report() -> dict:
        import json
        found = write(paths)
        if "refusal" in found:
            return {"refusal": found["refusal"]}
        return {"sha256": found["sha256"], "bytes": found["bytes"], "report": json.loads(found["text"])}
    return report
