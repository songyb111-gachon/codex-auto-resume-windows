# Support

Something not working? Open an
[issue](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues).

Not sure it is a bug — how something works, whether a failure should be recoverable, whether
your setup is supported? Start a
[discussion](https://github.com/songyb111-gachon/codex-auto-resume-windows/discussions)
instead. Either is fine, and neither is the wrong door; nothing gets closed for being asked in
the other one.

Please **do not** include credentials or tokens, whole private conversations, private repository
contents, or unredacted logs. Nothing in this tool needs any of that to be diagnosed, and an
issue is public.

## Before you report

Run the built-in check and paste its output. It is read-only and prints no conversation content:

**Start Menu → Codex Auto Resume** shows the watcher state, what is pending and the version.

From a terminal, if you installed from source:

```bash
python src\auto_resume.py doctor
```

```bash
python src\auto_resume.py status
```

`doctor` reports the discovered Codex engine, whether the app is paired, whether the Restart
Manager probe works, and whether the local history is readable. `status` adds the watcher state,
autostart registration and record counts.

## What to include

Whichever of these apply:

| Problem | Useful to include |
| --- | --- |
| **Install, upgrade or repair failed** | The full `Install.cmd` output, your Windows version, and whether the Codex app was open |
| **Codex version compatibility** | The engine version from `doctor`, and whether it says *verified* or *unverified* |
| **A failure was recovered that should not have been** | The failure category shown in `pending` or the log line, and what you expected instead |
| **A recoverable failure was missed** | What Codex showed you, and the log lines around that time |
| **A task stayed at `waiting_for_loaded_thread`** | Whether the conversation was open in the app — see the note below |
| **Notifications not appearing** | Whether Windows shows them for other apps, and whether **Codex Auto Resume** appears under Settings → Notifications |
| **Settings window problems** | What you clicked, what happened, and your display scaling (100%, 125%, 150%…) |
| **The settings panel in Codex** | Whether `codex mcp get codex-auto-resume` reports it enabled |
| **Plugin not discovered** | The output of `codex plugin list` |

Log files are in `%USERPROFILE%\.codex-auto-resume\logs\`. They record state names and
conversation UUIDs, not conversation content — but read before pasting, and redact anything you
would rather not publish.

## Known behaviour that is not a bug

**A task waits until you open the conversation.** After the Codex app restarts, the target
conversation is `notLoaded`, and there is no supported way to wake it programmatically. The
watcher waits at `waiting_for_loaded_thread` until you open that conversation yourself, then
continues on its own. This is documented in the
[README](README.md#please-read-this-limitation-first) with the measurement behind it.

**An unclassified failure is never retried.** If Codex failed in a way this tool cannot name, it
deliberately does nothing. That is the core design choice, not an oversight — but if you think a
failure *should* be classifiable, please report it with what Codex recorded.

**A recovery stopped after a few attempts.** Recovery is bounded: at most four attempts per
interruption, and it stops after three consecutive recoveries that produced no visible progress.
You can give one interruption its attempts back from the settings panel.

## Security issues

Open an issue like any other - there is no private channel, and
[SECURITY.md](SECURITY.md) says so plainly. Read it first anyway: it sets out what the tool is
allowed to touch, which is usually enough to tell a finding from expected behaviour.
