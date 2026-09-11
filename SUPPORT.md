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

Run the built-in check and paste its output. None of the checks below asks Codex to change
anything, and none prints conversation content. The terminal commands do print local paths, which
contain your Windows user name; redact it if you would rather not publish it.

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

Log files are in `%USERPROFILE%\.codex-auto-resume\logs\` by default. They record state names, reason
codes and conversation UUIDs, not conversation content. They also contain local paths with your
Windows user name, and `errors.log` holds full tracebacks — so read before pasting, and redact
anything you would rather not publish.

## Known behaviour that is not a bug

**A task waits until you open the conversation.** After the Codex app restarts, the target
conversation is `notLoaded`, and there is no verified way for this tool to wake it. The
candidate App Server routes, such as `thread/resume`, are ones this tool deliberately does not
use. The watcher waits at `waiting_for_loaded_thread` until you open that conversation
yourself, then continues on its own. This is documented in the
[README](README.md#please-read-this-limitation-first) with the measurement behind it.

**An unclassified failure is never retried.** If Codex failed in a way this tool cannot name, it
deliberately does nothing. That is the core design choice, not an oversight — but if you think a
failure *should* be classifiable, please report it with what Codex recorded.

**A recovery stopped after a few attempts.** Recovery is bounded. For a temporary failure it
makes, by default, at most four attempts per interruption. A usage limit has no limit on
recovery attempts; it is limited instead by the cap every recovery is under, five sends per
conversation in any 24 hours, at least 15 minutes apart. For either kind, recovery stops, by
default, after three recoveries in a row on the same conversation that were followed by neither
a reply nor a completed turn, and a usage-limit recovery ends as `failed` after five failed
launches of `codex queue` (a temporary failure reaches its attempt limit first, unless that
setting is above four). The attempt count and the no-progress count are settings; the send cap,
the 15 minutes and the five launches are not. An interruption stopped by the attempt count or
the no-progress count can be given its attempts back by asking Codex to run the plugin's
`reset_recovery_budget` tool with that interruption's id from `list_pending`. Neither the
settings panel nor the settings window has a control for it.

**Windows warns about the installer, or blocks it.** Nothing this project builds is
Authenticode-signed: not `Install.cmd` or `Uninstall.cmd`, not the PowerShell scripts, and not
the two small programs in the release - the settings window and the MCP launcher. A `.cmd` file
cannot carry an embedded signature. SmartScreen may warn when you run them from a ZIP you
downloaded and extracted with Explorer, because the extracted files keep the download's mark of
the web, and Smart App Control, where it is on, may block the unsigned programs. The process
that runs at sign-in is the bundled `pythonw.exe`, which keeps the Python Software Foundation's
signature, as do `python.exe` and the interpreter's DLLs and extension modules (its two Visual
C++ runtime DLLs are signed by Microsoft). Before you allow anything, check the archive
as described in
[Verifying a release](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md).

**The watcher will not start, or its state reads `unknown`.** If the log says
`named_object_squatted`, another program running with fewer rights than you created the
watcher's lock or its stop signal first. The watcher refuses to run under an object that program
controls, rather than let it fake a running watcher or stop the real one; that refusal is on the
main branch and ships in the release after v0.5.7. Signing out and back in ends every program in
your session, which clears it; if it comes back, report it with those log lines.

## Security issues

Open an issue like any other: that is how [SECURITY.md](SECURITY.md) asks for security reports,
and the project names no private channel. Read it first anyway: it sets out what the tool is
allowed to touch, which is usually enough to tell a finding from expected behaviour.
