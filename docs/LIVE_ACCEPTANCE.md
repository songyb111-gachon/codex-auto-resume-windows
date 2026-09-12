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
  number that is about to be released.
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

The five steps that say **Yes** need one detected interruption between them, not five.
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
running. Find the icon in the notification area, hover for the tooltip, and open its menu.
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
chain. Then, in the disposable conversation, start a turn that will run for a while and
take the network away until it fails. Put the network back. Watch the Pending page, or
run `auto_resume pending`.

If a real usage limit has happened to you instead, that is the stronger evidence and this
is the step to record it in: everything else follows the same path.

**A pass.** A record appears with a category the engine chose from Codex's own
`codexErrorInfo` and a public code that says what it is waiting for. A category of
`unknown` is also a correct outcome — an error the engine cannot place is never retried —
but it ends the interrupted-path steps, so record this step as it happened and mark the
rest `blocked`.

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
neither. If a person's turn arrived first and the engine calls the record `handed_over`,
that is also a pass: it is the engine refusing to claim a turn it did not start.

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

**Proves.** That the Dashboard reads the same control layer as everything else, so the
window, the Codex panel and the command line cannot disagree about what a recovery is
doing — and that a part which cannot be read is shown as unreadable rather than as empty.

**Do.** Open the window and visit Overview, Pending, History, Statistics and Diagnostics.
Find the record from the steps above on History, open its Timeline, and compare its code
with `auto_resume pending` or `auto_resume status` in a terminal. Then, with the window
open, stop the watcher and look at the pages again.

**A pass.** The same code in the window and on the command line. The Timeline shows the
chain in the same words the lists use. With the watcher stopped, nothing claims that
nothing is waiting; what cannot be read says so.

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
is switched off; confirm it is absent in one of those situations too.

**A pass.** The check happens at once and the record either moves on or goes back to
waiting for the same reason. Nothing is sent because the button was pressed.

**Record.** `code_before`; `code_after`; `continuation_sent` as `false`; `offered_when`
as a short machine value describing where you found the button absent, such as
`"absent-while-paused"`.

### 11. Giving attempts back is explicit, limited, and not a send — `give-attempts-back`

**Proves.** That an exhausted recovery re-enters the wait its kind of failure needs rather
than being sent again, that it does not switch a conversation back on, and that it stops
after three.

**Do.** With **Attempts per interruption** at 1, let a record reach `exhausted`. Turn that
conversation off with **Turn off for this conversation**, then press **Give attempts back**
on History and read what it says.
Press it until the button goes quiet.

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
