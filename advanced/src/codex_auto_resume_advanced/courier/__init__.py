# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The courier (v0.6.20, plans/v0619-design/D-courier.md): the advanced edition's only network code.

One short-lived process, `pythonw.exe -m codex_auto_resume_advanced.courier --home <home>`, started by the watcher at
P8 (launch.py) - windowless, suspended until it is in the starting process's job object made KILL_ON_JOB_CLOSE, so it
ends with that process however that process ends - and refused a second time for one home by a named mutex. It sends
what the outbox holds (push_notices: ntfy, a webhook, Telegram, e-mail) and reads OpenAI's status page (status_feed),
then exits. It never listens and never decides or delays a recovery: what it sends was written by the watcher, and
what it reads is shown, never a gate's input.

    address   the checks every address a person types meets before it is kept or used (no network)
    http      the one HTTPS request function: verification on, no redirect, no userinfo, capped bodies
    outbox    the pushed notices waiting, tried and dropped, through the advanced state (no network)
    launch    starting the process from the watcher or the Dashboard's service (no network)
    __main__  the process: its arguments, its mutex, one drain, its exit codes

Only this package may import a networking module (tests/test_privacy_claims.py, ADVANCED_NETWORK_MODULES). Importing
the package imports nothing: each module is taken where it is needed, so the watcher, which writes the outbox, never
loads the code that sends it.
"""
