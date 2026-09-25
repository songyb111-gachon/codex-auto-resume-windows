# Accepting a release on a real machine

The automated suite proves that the engine does what its tests say, against a Codex-shaped
SQLite home the tests build themselves. It never starts the desktop app, never sends a
continuation and never watches one arrive. Everything in this document is the other half:
what a person does on a real Windows machine, against a real Codex installation, before a
release is published — and what they write down afterwards, so that months later anyone
can tell a step that was performed from a step that was described.

Each step below says what it proves, exactly what to do, what a pass looks like, and what
to record. Each one ends in a single JSON file under `docs/evidence/live/`, in the schema
this document defines, and `python scripts/live_evidence.py` refuses the shapes that make
a record of a procedure indistinguishable from a record of nothing.

An empty `docs/evidence/live/` is not a pass. It means nothing has been accepted yet.

## Before you start

- **A real machine and a real Codex.** A Windows machine you are willing to install on,
  the ChatGPT/Codex desktop app signed in, and the `codex` CLI on `PATH`. A virtual
  machine is fine and is the better choice, because the last step here uninstalls the
  product and the one before it installs over an existing copy.
- **A disposable conversation.** This procedure makes the product send real messages into
  a real conversation. Start a new conversation in the desktop app, do the whole
  acceptance in it, and never point any of it at work you care about.
- **The release candidate.** The archive built for the version you are accepting, and the
  `.sha256` published beside it. The version in `.codex-plugin/plugin.json` is the version
  every evidence file has to claim, so accept a build whose manifest already says the
  number that is about to be released. The installation step 13 upgrades from is the last
  published release that is not a pre-release - the one `releases/latest` answers with.
- **What v0.6.3 adds is checked inside these steps.** [What v0.6.3 adds, and where to write
  it down](#what-v063-adds-and-where-to-write-it-down) names the step each check belongs to
  and the file whose note records it; read it before step 3.
- **Time.** One step waits for a usage reset that may be hours away, and one step cannot
  be reached at all until a usage limit really happens to you. Both are described below.
- **Write each file as you finish its step**, not at the end. The whole reason this
  document exists is that evidence written from memory is a description of what should
  have happened.

Nothing here asks you to record what a conversation said. The schema has no field for a
prompt, a reply, a title, a project, a path or a person, the validator refuses a field
that looks like one, and ids are written only as the aliases the diagnostics export uses.
A step that seems to need conversation content is a step that has been misread: what is
being accepted is that the product moved a record through the states it claims, not what
anybody was working on.

## What needs a real interruption, and what does not

Three different answers, and the difference is the honest part of this document.

**A usage limit cannot be summoned.** There is no way to ask OpenAI to say you are out of
quota, and manufacturing one — editing Codex's database, or pointing the watcher at a
home we wrote ourselves — would test our reading of a file we had just written. So
`interruption-detected` is accepted with `category` recorded as `usage_limit` only when a
usage limit really happened to you. Until then, run the rest of the acceptance on an
induced transient failure and record the usage-limit half as `blocked`, with a note. It
is better to ship a release saying the usage-limit path was last watched working on a
named earlier date than to ship one saying it passed because a fixture said so.

**A transient interruption can be induced, and that is the one you can make happen.**
Start a long turn in the disposable conversation and take the network away while it is
running — flight mode, or disabling the adapter — for long enough that the turn fails,
then put it back. Codex records the failure with its own `codexErrorInfo`, and what
category the watcher gives it is part of the evidence rather than something to assume: a
transport failure normally lands in the transient family, and if this one classifies as
`unknown` the watcher will correctly refuse to retry it, which is a pass for the engine
and a `blocked` for every step downstream of it. Try again, or wait for a real one.

**Everything else needs no interruption at all**, or needs only the record the induced
failure produced. Install, the watcher and its icon, the Dashboard, cancel, retry now,
giving attempts back, pause and resume, the upgrade path, repair and uninstall are all
reachable in one sitting. Two of them need a little arranging, said where they come up:
giving attempts back needs a record that has used up its budget, which is why **Attempts
per interruption** is set to 1 before the failure is induced, and seeing a pause *withdraw*
something needs a continuation that is queued at the moment you pause.

## The steps at a glance

| Step | What it proves | `observed` must record | Needs a real interruption |
| --- | --- | --- | --- |
| `install-verify` | The archive is the one this project published, checked before anything is extracted | `archive_sha256_matches_published`, `archive_sha256_matches_pin`, `attestation` | No |
| `install-run` | Installing ends at one installation, with the plugin registered | `route`, `setup_exit_code`, `install_root`, `plugin_registered` | No |
| `watcher-starts` | A watcher is running and says so where you can see it | `watcher_running`, `tray_icon_present`, `tooltip_reports` | No |
| `interruption-detected` | A real failure is seen, classified and scheduled | `category`, `code`, `thread`, `record` | Yes |
| `continuation-exact-thread` | The continuation reached that conversation and no other | `thread`, `record`, `queue_items_owned`, `other_threads_touched` | Yes |
| `follows-its-turn` | The engine watched the turn its own continuation started | `record`, `marker_matched_turns`, `turn_status`, `code` | Yes |
| `outcome-recorded` | The outcome is read from that turn and written down | `record`, `code`, `outcome_at_recorded` | Yes |
| `dashboard-shows-it` | The window shows that record in the same words everything else uses | `pages_seen`, `code_shown`, `agrees_with_command_line` | Yes |
| `cancel` | Cancel stops one task and everything that would continue it | `code_before`, `code_after`, `queued_item`, `confirmation_named_the_conversation` | Yes |
| `retry-now` | Retry now is a re-check and never a send | `code_before`, `code_after`, `continuation_sent` | Yes |
| `give-attempts-back` | Giving attempts back is explicit, limited, and sends nothing | `code_before`, `code_after`, `budget_resets`, `continuation_sent` | Yes |
| `pause-resume` | Pause withdraws what is queued; resume picks it up again | `withdrawn_on_pause`, `code_while_paused`, `overlay_while_paused`, `code_after_resume`, `continuation_sent_while_paused` | Yes |
| `upgrade-keeps-decisions` | An upgrade repairs registrations and decides nothing | `paused_before`, `paused_after`, `startup_entry_before`, `startup_entry_after` | No |
| `repair` | Repair says which of five things happened and changes no decision | `outcome`, `paused_unchanged`, `startup_entry_unchanged` | No |
| `uninstall` | Uninstall removes what it owns and keeps what it cannot prove is its | `route`, `watcher_stopped`, `startup_entry`, `state_kept` | No |

The nine steps that say **Yes** can share a detected interruption while its state allows it.
Induce one transient failure with **Attempts per interruption** at 1 and it carries
`interruption-detected` through `pause-resume`; induce a second when a step consumes the
first, which `cancel` does.

## The evidence schema

One file per step, UTF-8 JSON, under `docs/evidence/live/`. Name it after the step —
`docs/evidence/live/cancel.json` — or add a suffix when a step is recorded more than
once; the `step` field is what counts, not the file name. `README.md` is skipped, and a
file whose name begins with `example` is read as an example of the shape and counts
towards nothing.

| Field | Required | What it holds |
| --- | --- | --- |
| `format` | Yes | `codex-auto-resume-live-acceptance/1` |
| `step` | Yes | One of the step ids in the table above |
| `verdict` | Yes | `pass`, `fail` or `blocked` |
| `recorded_at` | Yes | ISO-8601 date, or date and time with an offset |
| `product_version` | Yes | The version in `.codex-plugin/plugin.json`, which must be the version being accepted |
| `codex_version` | Yes | What `codex --version` printed |
| `windows_build` | Yes | The Windows build, as `winver` or `[System.Environment]::OSVersion.Version` gives it |
| `codex_app_version` | No | The desktop app's version, where the step depended on it |
| `observed` | Yes | An object of machine values: what was seen, in the engine's own vocabulary |
| `note` | Only when the verdict is not `pass` | What happened instead, or what could not be reached |

The rules the validator enforces, and why each one is there:

- **A `pass` records the values its step names.** Every key in that step's row of the
  table above has to be present and not null. A pass that records nothing is a
  formality, and a formality in a file is worse than an empty directory, because it
  looks like an answer.
- **Ids are aliases.** `thread` and `record` take the shape `diagnostics.py` writes —
  `thread-1a2b3c4d`, `record-9f8e7d6c` — and a raw UUID anywhere in the file is refused.
  Export diagnostics on the Diagnostics page, or run `auto_resume diagnostics`, and copy
  the aliases from that bundle: they hold together inside one bundle, which is what lets
  a reader follow one recovery through several evidence files written from it.
- **No paths, no addresses, no names.** Where something is installed is recorded as
  `default` or `custom`. There is no field for who ran the acceptance; a procedure is
  accepted by a machine and a version, not by a person's name in a public file.
- **Times are text.** ISO-8601, never an epoch — partly because a reader should not have
  to convert one, and partly because a long run of digits is exactly what a leaked id
  looks like.
- **Digests are recorded as whether they matched**, not as themselves. A SHA-256 and an
  interruption id are both 64 hexadecimal characters, and no rule can tell them apart by
  looking.
- **Codes come from the engine.** `code`, `code_before`, `code_after`, `code_shown`,
  `code_while_paused` and `code_after_resume` are public codes; `category` is a failure
  category; `turn_status` is a turn status; `overlay_while_paused` is an overlay. The
  validator reads all four vocabularies out of the product, so a code that is renamed in
  the engine stops validating here rather than quietly meaning nothing.
- **A `fail` or a `blocked` needs a note.** A step that did not pass is only useful if it
  says what happened instead, or which part of it could not be reached.

An example of the shape, which records nothing that happened, is at
[`evidence/live/example.json`](evidence/live/example.json).

## The validator

```powershell
python scripts/live_evidence.py
```

It reads every file in `docs/evidence/live/` and exits

- **0** when every step has evidence and every verdict is `pass`;
- **1** when something was refused — it prints each refusal as a sentence naming the file
  and what is wrong;
- **2** when nothing is wrong and this is still not a pass: the directory is empty, a step
  has no evidence yet, or a verdict is `fail` or `blocked`.

Exit 2 is deliberately not exit 0 and deliberately not exit 1. A caller that reads an
empty directory as success says a release passed a procedure nobody ran; one that reads
it as failure says somebody ran it badly. Neither is what happened.

What the validator cannot do is check that any of this took place. It was not there. It
checks that a file is shaped like evidence, written in the product's own vocabulary, free
of anything that should never be committed, and not contradicted by another file. The
verdict is yours.

## The steps

### 1. The archive is the one this project published — `install-verify`

**Proves.** That what you are about to run is the published build, checked before it is
extracted, which is the only moment the check is worth anything.

**Do.** Download `CodexAutoResume-vX.Y.Z-win-x64.zip` and the `.sha256` beside it. Do not
extract either. Follow [`VERIFY.md`](VERIFY.md): hash the archive, compare it with the
`.sha256`, compare it with the digest pinned for that version in `scripts/release.json`
on `main`, and — with the GitHub CLI — verify the build attestation with
`--signer-workflow` and `--source-ref`, because without them any workflow run in the
repository is accepted.

**A pass.** Every comparison you made agreed. A version published minutes ago may not
have its `release.json` pin yet; record that as `not-published-yet` rather than as a
match, because a pin that does not exist is not a check that passed.

**Record.** `archive_sha256_matches_published` and `archive_sha256_matches_pin` as `true`,
`false` or `"not-published-yet"`; `attestation` as `"verified"`, `"absent"` or
`"failed"`. Never the digest itself.

### 2. Installing ends at one installation — `install-run`

**Proves.** That the archive installs, registers the plugin from the files it carries,
and leaves one installation behind rather than a second one beside an existing install.

**Do.** Extract the archive and run `Install.cmd`. Let it finish. Then open Codex and
confirm the plugin is registered and its panel opens (*open auto resume settings*).

**A pass.** Setup ended with exit code 0, the installation is in one place — by default
`%USERPROFILE%\.codex-auto-resume` — and Codex lists the plugin at the version being
accepted. An exit code of 2 means everything asked for was done but a running watcher
could not be confirmed; that is its own answer and is not a pass for this step, so record
it and carry on to the next one, which looks at the watcher directly.

**Record.** `route` as `"Install.cmd"` or `"plugin-bootstrap"`; `setup_exit_code`;
`install_root` as `"default"` or `"custom"`; `plugin_registered`.

### 3. A watcher is running, and says so where you can see it — `watcher-starts`

**Proves.** That the watcher starts, that the notification-area icon belongs to the
watcher process itself rather than to a claim about it, and that its tooltip reports the
four things it promises.

**Do.** Open **Start Menu → Codex Auto Resume**; the Overview says whether a watcher is
running. Find the icon in the notification area, hover for the tooltip, and right-click it for its menu. From v0.6.3 a single left click opens a small window instead, which is checked under
[What v0.6.3 adds](#what-v063-adds-and-where-to-write-it-down).
Then stop the watcher from that menu and watch the icon disappear; start it again from
the window.

**A pass.** The icon is there while a watcher runs and gone once it is stopped — that is
the property worth checking, because an icon that survives its watcher is an icon that
lies. The tooltip says whether recovery is paused, how many recoveries are waiting, how
many are running in Codex, and how long until the next check. The countdown reaching zero
means the watcher looks again, and nothing else.

**Record.** `watcher_running`; `tray_icon_present`; `tooltip_reports` as the list of what
the tooltip actually named, from `"paused"`, `"waiting"`, `"running"` and `"next_check"`.

### 4. A real failure is seen, classified and scheduled — `interruption-detected`

**Proves.** That a real interrupted turn, written by Codex and not by us, is detected,
given a category, and scheduled — and that the notification names this product rather
than whatever process raised it.

**Do.** First set **Attempts per interruption** to 1 on the Settings page, so the record
this produces reaches its budget in one continuation; that setting accepts 1 to 20, and
**Continuations per task** — 1 to 10, six by default — is the separate cap on a whole
chain. In the same visit, make the continuation-message checks under
[What v0.6.3 adds](#what-v063-adds-and-where-to-write-it-down), and leave **Message style**
on the style you mean to accept with — Standard, the default, unless you are accepting a
Custom message on purpose. Then, in the disposable conversation, start a turn that will run for a while and
take the network away until it fails. Put the network back. Watch the Pending page, or
run `auto_resume pending`.

If a real usage limit has happened to you instead, that is the stronger evidence and this
is the step to record it in: everything else follows the same path.

**A pass.** A recoverable record appears with a category the engine chose from Codex's
own `codexErrorInfo` and a public code that says what it is waiting for. An `unknown` or
terminal failure is correctly excluded from registration and retrying, so it produces
no Pending row. In that case record this step and its downstream steps as `blocked`,
with the observed classification and a note that no recoverable record was registered.
Do not invent a record alias for an excluded failure.

**Record.** `category` (a failure category — `usage_limit`, a transient one, a terminal
one or `unknown`); `code` (the public code shown); `thread` and `record` as aliases from a
diagnostics export; `notification_shown` if you saw the toast.

### 5. The continuation reached that conversation and no other — `continuation-exact-thread`

**Proves.** The guarantee the whole product rests on: a conversation is identified by its
exact UUID, and a continuation is queued to that conversation alone.

**Do.** Leave the disposable conversation loaded in the desktop app — nothing can be
delivered to a conversation the app does not have loaded — and let the schedule come
round. Watch the record move to `submitted`. Then look in the desktop app: the
continuation appears in that conversation. Look at any other conversation you have open
and confirm nothing arrived there.

**A pass.** Exactly one queued item belongs to the watcher, in the conversation whose
alias matches the record, and no other conversation received anything.

**Record.** `thread` and `record` as aliases; `queue_items_owned` as the number of queued
items the watcher owned (1); `other_threads_touched` as the number of other conversations
that received anything (0); `marker_present` if you confirmed the continuation's marker.

### 6. The engine watched the turn its own continuation started — `follows-its-turn`

**Proves.** The change this release is built on. The engine does not read the conversation
for signs that a recovery worked: each continuation carries a marker built from the
interruption's own id, the turn it started is the turn of the history row holding that
marker, and the outcome is read from that turn and no other.

**Do.** While the continuation runs, start a turn of your own in the same conversation —
type something ordinary and send it. That is the exact situation the old behaviour got
wrong: a turn you started could be read as the recovery working. Then export diagnostics
and read the record's `turn_started_at` and `recovery_turn_status`, or run
`auto_resume pending` and read the state beside the code.

**A pass.** The record names one turn, and it is the turn its own continuation started —
not yours. The window shows `turn_running` and then `turn_finishing`; your turn changes
neither. If a person's turn arrived first and the engine calls the record `handed_over`
without a marker-matched recovery turn, that is correct conservative behavior but does
not prove correlation. Record this step as `blocked`, including the observed zero
matches; do not record one match merely to satisfy a pass.

**Record.** `record` as an alias; `marker_matched_turns` as the number of turns the marker
matched (1); `turn_status` (a turn status — `inProgress`, `completed`, `failed`,
`interrupted` or `other`); `code`.

### 7. The outcome is read from that turn and written down — `outcome-recorded`

**Proves.** That the record reaches one of the outcomes this release defines, that the
outcome is stored with a time, and that an outcome which could not be established is
called unverified rather than success.

**Do.** Let the recovery turn finish. Read the record on the History page and in a
diagnostics export.

**A pass.** The public code is one of `recovered`, `no_progress`, `handed_over`,
`recovery_failed`, `stopped_by_user` or `outcome_unverified`, an outcome time is stored,
and the History row says the same thing as the export. `outcome_unverified` is a pass for
this step: it is the product declining to guess.

**Record.** `record` as an alias; `code`; `outcome_at_recorded` as `true` when an outcome
time is stored; `reason` when the record shows one.

### 8. The window shows it, in the same words — `dashboard-shows-it`

**Proves.** That the Dashboard reads the same control layer as everything else and
agrees about a stable record — and that a part which cannot be read is shown as
unreadable rather than as empty. Snapshots taken at different times can differ while
a recovery changes state; the Codex panel does not refresh automatically.

**Do.** Open the window and visit Overview, Pending, History, Statistics and Diagnostics.
Find the record from the steps above on History, open its Timeline, and compare its code
with `auto_resume pending --all` in a terminal. Then, with the window
open, stop the watcher and look at the pages again.

**A pass.** The same code in the window and on the command line. The Timeline shows the
chain in the same words the lists use. Stopping the watcher leaves the local store
readable: existing records remain visible and the watcher is shown as stopped. Only
an actual read failure should be shown as unreadable; an empty readable list is empty.

**Record.** `pages_seen` as the list of pages you opened; `code_shown`;
`agrees_with_command_line` as `true` or `false`.

### 9. Cancel stops one task and everything that continues it — `cancel`

**Proves.** That cancelling reduces automation immediately, that it names the conversation
it is about, and that it is honest about a turn already running in Codex.

**Do.** Induce a second interruption (step 4 again) so there is something waiting, and
cancel it from the Pending page while it is still waiting. Read the confirmation before
you accept it. Then check the record on History.

**A pass.** The confirmation names the conversation it is about — the lists refresh every
five seconds, so a confirmation that named nothing could be answered about a record that
had moved underneath it. A record that was never sent becomes `cancelled`. If you cancel
something that may already be in Codex, the confirmation says that a turn already running
is not stopped, and anything still queued is taken back.

**Record.** `code_before`; `code_after` (`cancelled`); `queued_item` as `"withdrawn"`,
`"nothing-queued"` or `"already-running"`; `confirmation_named_the_conversation`.

### 10. Retry now is a re-check — `retry-now`

**Proves.** That Retry now brings the schedule forward and wakes the watcher, and does
nothing else: it does not send, does not skip the loaded-conversation requirement, does
not open a usage window and does not skip revalidation.

**Do.** On a waiting record, press **Retry now** and read the note the page shows
afterwards. The button is offered only where it can do something — not on a recovery whose
usage reset is still ahead, not while recovery is paused, and not on a conversation that
is switched off; confirm it is disabled in one of those situations too.

**A pass.** The check happens at once and the record either moves on or goes back to
waiting for the same reason. Nothing is sent because the button was pressed.

**Record.** `code_before`; `code_after`; `continuation_sent` as `false`; `offered_when`
as a short machine value describing where you found the button disabled, such as
`"disabled-while-paused"`.

### 11. Giving attempts back is explicit, limited, and not a send — `give-attempts-back`

**Proves.** That an exhausted recovery re-enters the wait its kind of failure needs rather
than being sent again, that it does not switch a conversation back on, and that it stops
after three.

**Do.** With **Attempts per interruption** at 1, let a record reach `exhausted`. Turn that
conversation off with **Turn off for this conversation**, then press **Give attempts back**
on History and read what it says. A successful reset changes `exhausted` to a waiting
state, so the button becomes disabled immediately; repeatedly clicking it cannot test
the three-reset limit. That limit requires additional genuine failures and exhaustion
in the same recovery chain, with the conversation explicitly re-enabled between runs.
After the third reset, let the same chain genuinely exhaust again and verify a fourth
reset is refused. Never edit state or fabricate failures to arrange this. If those
conditions cannot be reached, record the step as `blocked` with the reset count actually
observed, even if its first-reset behavior worked.

The published v0.6.0 Dashboard discarded the successful reset's explanatory note; v0.6.1
shows it. If the build you are accepting does not show it while the conversation is off,
record that missing feedback as a failure; the control result and MCP response still carry
the note.

**A pass.** The record re-enters waiting and every check runs again from the top. Because
the conversation is off, the message says so and says that nothing will run until you
switch it on. After three resets for one task the button is disabled and a note says to
continue that task in Codex yourself.

**Record.** `code_before` (`exhausted`); `code_after` (the waiting code it re-entered);
`budget_resets` as the number of resets the record had used when the button went quiet
(3); `continuation_sent` as `false`; `said_thread_is_off` as `true` when the message said
the conversation was switched off.

### 12. Pause withdraws, and resume picks up again — `pause-resume`

**Proves.** That pausing takes back what is still queued, that a paused waiting record
says it is paused rather than being rewritten, and that resuming brings it back into the
ordinary schedule.

**Do.** Two halves. For the first, watch a record until it becomes `submitted` and pause
recovery immediately — from the notification-area menu, which is the fastest route — and
see whether the queued item is taken back. If you cannot catch that moment, say so in the
note; the withdrawal half is then not accepted, and the rest of the step still stands. For
the second, with a record waiting and recovery paused, confirm nothing is sent, then
resume and watch the same record be picked up at the next check.

**A pass.** The waiting record keeps its code and carries the `paused` overlay beside it
rather than having its state rewritten — a sent record is never shown as paused, because
that would be a promise nothing can keep. Nothing is sent while paused. After resuming,
the record is checked again on the next tick.

**Record.** `withdrawn_on_pause` as `"withdrawn"` or `"nothing-queued"`;
`code_while_paused`; `overlay_while_paused` (`paused`); `code_after_resume`;
`continuation_sent_while_paused` as `false`.

### 13. An upgrade repairs; it does not decide — `upgrade-keeps-decisions`

**Proves.** The two things an upgrade used to undo: a pause the owner had chosen, and a
sign-in entry the owner had removed.

**Do.** Pause recovery, and turn off start-at-sign-in on the Settings page. Confirm the
Run value is gone (`Get-ItemProperty HKCU:\Software\Microsoft\Windows\CurrentVersion\Run`).
Then install the same or a newer archive over the installation — the ordinary upgrade
path — and look again.

Start from an installation of the last published release that is not a pre-release (the one
`releases/latest` answers with) and install the archive you are
accepting over it. Unless its CHANGELOG entry says otherwise, the release you are accepting
changes no setting you had and adds none. Read Settings afterwards —
**Interface language**, **Theme**, **Message style** and any Custom message should be what they
were before the upgrade — and put anything else in the note. Starting from v0.6.2 or earlier also changes the
one default v0.6.3 changed on purpose: the continuation used to be one fixed English sentence
per kind of interruption, and is now the Standard message in the continuation language.

**A pass.** Recovery is still paused after the upgrade, and no sign-in entry was added.
An entry that is already this installation's is re-registered, which repairs its path
after the runtime moves; that is not the same as adding one.

**Record.** `paused_before` and `paused_after` as booleans; `startup_entry_before` and
`startup_entry_after` as `"ours"`, `"other"` or `"absent"`.

### 14. Repair says which of five things happened — `repair`

**Proves.** That **Repair installation** re-registers what is broken, reports one of five
outcomes rather than a shrug, and changes no decision.

**Do.** On the Diagnostics page, press **Repair installation** and read what it reports.
Check the pause switch and the sign-in entry afterwards.

**A pass.** It reports exactly one of: it finished; it is still working; another
installation or repair is already running; this installation is missing the files setup
is made of; or it failed. The pause switch and the sign-in entry are what they were before.

**Record.** `outcome` as `"done"`, `"running"`, `"busy"`, `"incomplete"` or `"failed"`;
`paused_unchanged`; `startup_entry_unchanged`.

### 15. Uninstall removes what it owns — `uninstall`

**Proves.** That uninstall stops the watcher first, removes only what it can prove is its
own, and keeps settings and pending recoveries unless asked to delete them. Do this last:
after it, the earlier steps need an installation again.

**Do.** Run `Uninstall.cmd` from the release archive. Watch the notification-area icon go.
Afterwards, check the Run value, the Start Menu entry, and whether `config/` survived.
If you have time for the refusal as well, point the installation home at a directory that
merely contains folders called `app`, `runtime`, `config` and `logs` and confirm it is
refused and reported rather than deleted.

**A pass.** The watcher was asked to stop and stopped — if it cannot be confirmed stopped,
uninstall aborts before removing anything, which is also a pass and is recorded as such.
The sign-in entry is removed only while it is this installation's; one that starts another
copy is reported and kept. Settings and pending recoveries survive a plain uninstall.

**Record.** `route` as `"Uninstall.cmd"`, `"codex"` or `"source"`; `watcher_stopped`;
`startup_entry` as `"removed"`, `"kept-not-ours"` or `"absent"`; `state_kept`;
`refused_directories` as the number of directories it refused to delete from.

## What v0.6.3 adds, and where to write it down

v0.6.3 changes what the product says and shows, not what recovery decides: the classifier,
the gates and the one watcher allowed to send are v0.6.2's. The checks below are for the new
surfaces. None of them is a step of its own, and the validator knows nothing about them —
an `observed` value a step does not list is refused, so they cannot be recorded there.
Write each one instead as a short sentence of plain machine words in the `note` of the step
named beside it; a `pass` may carry a note. That keeps them out of the count on purpose: a
step's `pass` says nothing about these checks unless its note does.

Everything above still holds. Use only the disposable conversation. Do not manufacture a
usage limit, and do not edit Codex's databases or this product's state to reach a
situation; where one cannot be reached honestly, write that it was not seen. Click and type
yourself: none of this may be driven by a script, a macro or an accessibility tool, which is
exactly what this product refuses to do itself. And write down no text a conversation
contained, no Custom message you typed, and no screenshot.

| Check | Do it during | Note it in |
| --- | --- | --- |
| Interface language, and that it survives a restart | Step 3 | `watcher-starts` |
| The notification-area popup | Step 3 | `watcher-starts` |
| Continuation message styles and Preview | Step 4 | `interruption-detected` |
| Custom message: refusal and fallback | Step 4 | `interruption-detected` |
| A notification's Open Dashboard, and the kind of interruption it names | Step 4 | `interruption-detected` |
| The continuation that arrived is the one Preview showed | Step 5 | `continuation-exact-thread` |
| The header's activity states, and Reduce motion | Step 8 | `dashboard-shows-it` |
| The panel in Codex: Preview, and Custom text it cannot change | Step 8 | `dashboard-shows-it` |
| A stale click refused | Step 9 | `cancel` |
| Pending's Auto-resume switch | Step 10 | `retry-now` |
| Cancel all | After step 12 | `upgrade-keeps-decisions` |
| The window's own dialog, and the scroll bars | Step 9 | `cancel` |

**Interface language — step 3, noted in `watcher-starts`.** If `CODEX_AUTO_RESUME_LANG` is
set in your environment it overrides the setting, so remove it first. On **Settings →
General**, set **Interface language** to a language Windows is not using and save; the window
closes and opens again by itself, in that language and on the same section. Open the popup, and
hover over the icon. Then stop the watcher from the menu, start it again from the window, and
sign out and back in. Set it back to **System** at the end. *A pass:* the window reopened once,
in the chosen language, everything opened after the change speaks it, the choice is still there
after the watcher restart and the sign-in, and **System** brings back the first language
Windows lists.

**The notification-area popup — step 3, noted in `watcher-starts`.** Click the icon once: a
small window opens beside it. Click the icon again: it closes. Open it and click somewhere
else: it closes, and that click does not reopen it. Open it and press Esc: it closes. Press
its **Open Dashboard**. Then, with the watcher running, restart Windows Explorer from Task
Manager. *A pass:* each of those behaves as described, **Open Dashboard** opens the window
and changes nothing, and the icon comes back by itself after Explorer restarts and still
opens the popup on one click.

**Continuation message styles and Preview — step 4, noted in `interruption-detected`.** On
**Settings → Continuation message**, choose **Minimal**, then **Standard**, then
**Detailed**, and for each one open **Preview** for a usage limit and for one transient
kind, without saving. Leave the page without saving and open it again. *A pass:* Preview
changes with each unsaved choice and says the watcher adds one line after the text; leaving
without saving leaves the stored style as it was. Before you induce the failure, save the
style you mean to accept with.

**Custom message: refusal and fallback — step 4, noted in `interruption-detected`.** Choose
**Custom**. Type a short, neutral sentence containing `{reason}` and save it. Replace
`{reason}` with `{title}` and save again. Set **Use the message for** to **Each kind of
interruption separately**, leave one kind empty and preview that kind; then clear the message
for every interruption as well and preview it again. *A pass:* the first message is accepted
and Preview shows it exactly as typed with the reason filled in; the second is refused by
name, *Not saved*, and the first is still the stored one; Preview names the message for
every interruption as the first fallback and the Standard message as the second. Note the
three outcomes, never the words. Restore the style you are accepting with before you induce
the failure.

**A notification's Open Dashboard — step 4, noted in `interruption-detected`.** When the
interruption's notification appears, read it without pressing **Don't retry** or **Don't
resume**. Press **Open Dashboard**. *A pass:* a transient interruption's notification names
the kind of interruption, and the button opens the Dashboard on the Pending page with the
record still waiting and nothing cancelled. If no notification appeared, say so.

**The continuation that arrived is the one Preview showed — step 5, noted in
`continuation-exact-thread`.** Before the schedule comes round, open Preview for this
record's kind of interruption. When the continuation appears in the conversation, compare
the two by eye. *A pass:* it reads as Preview showed, followed by the watcher's one line.
Note whether they matched, never the words.

**The header's activity states, and Reduce motion — step 8, noted in
`dashboard-shows-it`.** Watch the word beside the status dot in the Dashboard's header as the
steps go by: *Monitoring* with nothing waiting, *Waiting* while a task waits for its time,
*Checking* as one comes due, *Recovering* while the continuation runs in Codex, *Paused*
while recovery is paused, and *Needs your attention* once the watcher is stopped in this
step. Then turn on **Settings → Appearance → Reduce motion**. *A pass:* each word matches
what Pending and the command line say is happening; with Reduce motion on nothing in the
window or the popup breathes or pulses, and turning it off brings the motion back. Note the
states you saw.

**The panel in Codex — step 8, noted in `dashboard-shows-it`.** In the disposable
conversation, open the panel (*open auto resume settings*) and use its Preview for the saved
style. For the Custom text half, a Custom message has to be saved: if you are accepting with
Standard, save a neutral one while recovery is paused, and restore Standard afterwards. The
panel shows the message, offers no way to edit it, and says custom messages are written in
the Dashboard. Change an ordinary setting in the panel and save, then reopen the
Dashboard. The panel does not refresh by itself, so reopen it before comparing. *A pass:* the
panel's Preview matches the Dashboard's, the Custom text cannot be changed there, and saving
in the panel left the Custom message as it was.

**The window's own dialog, and the scroll bars — step 9, noted in `cancel`.** Press **Cancel**
on the Pending page and read the dialog it raises, then press its **Close**; press **Cancel**
again and take it. Do the same with **Clear history** on the History page, and answer that one
with Esc. Then make the window narrow enough for a list to need its bar sideways, and tall
enough for a Settings section to need one down, and scroll both by dragging, by the wheel and
by the keyboard; open **Settings → Continuation message**, choose **Custom**, and scroll the
message box with more lines in it than it shows. *A pass:* each dialog is in the window's own
material, opens in the middle of the window, carries no second button on the taskbar, and has
the action's own words on the button that takes it - never *Yes* and *No*; Esc leaves it as the
other button does; and every bar you meet, in either direction and in the message box included,
is the product's own pill in its groove, never Windows' grey, with nothing left of Windows' bar
showing beside it.

**A stale click refused — step 9, noted in `cancel`.** A click is refused only when its task
changed between being drawn and being clicked, and that must not be arranged by editing
anything. The popup reads its list again every few seconds, so the moment is short: open the
popup on the task step 9 is about, cancel that task on the Pending page as step 9 says, and
at once click the task's switch in the popup. The Pending page's own switch can show the same
refusal only when a task changes inside the five seconds between its refreshes, for example
as its schedule comes round. *A pass:* the popup says *That task changed before the click
reached it, so nothing was done*, and the record is exactly as the cancel left it. If a
surface redrew first and the row had gone, write that the refusal was not seen; that is not
a failure of the step.

**Pending's Auto-resume switch — step 10, noted in `retry-now`.** With the record waiting,
turn its **Auto-resume** switch off on the Pending page, then on again, and look at the same
task in the popup each time. *A pass:* nothing is sent for that task while the switch is off;
turning it on again sends nothing because of the click and moves no schedule; the conversation
is not switched off; and the popup shows the same state once it has read the list again.
Note the code before and after each click.

**Cancel all — after step 12, noted in `upgrade-keeps-decisions`, the next file you
write.** It cancels every waiting record, so do it only when no step still needs one:
induce one more interruption, or use any still waiting, then press **Cancel all** on Pending
and read the confirmation before accepting it. *A pass:* the confirmation says anything
already handed to Codex is withdrawn only if it is still queued; the result counts what was
waiting; each of those records reads `cancelled` on History; no conversation was switched
off; and there is no button anywhere that retries everything.

## What this procedure does not prove

- **That it works for anyone else.** One machine, one Codex, one Windows build. The
  evidence files record all three so that a later reader knows exactly how narrow the
  claim is.
- **That the usage-limit path works today**, unless a usage limit really happened on the
  day it was run. Read `interruption-detected`'s `category` before you believe otherwise.
- **That nothing was misread.** The validator checks the shape of what was written, never
  its truth. Two people running the acceptance separately is worth more than any check a
  script can make.
- **That the release is safe to publish on its own.** This is the live half. The automated
  suite is the other half, and a release needs both.
