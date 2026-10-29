# The two editions

From v0.6.11 Codex Auto Resume is built and released as two editions, from one repository, with one
version, at the same time: the **standard** edition and the **advanced** edition. This page says
what each is, what each of the advanced edition's capabilities does and what it risks, how to choose
and switch between them, and what comes next. The rules both editions are held to are listed by id
in [STANDARDS.md](STANDARDS.md); where this page names one, it says in a few words what it is.

## The standard edition

The standard edition is the product as it is, plus only what keeps every standard in families 0
and A to J ([0.1](STANDARDS.md#0-the-edition-boundary)). What a release adds to it keeps them too:
each addition is off, or does what the release before it did, until you change it, and nothing it
already did is loosened (0.2). Among what it keeps:

- it sends a continuation through one channel only, Codex's own `codex queue`, to one conversation
  named by its exact id, and ends it with a marker by which it proves the continuation arrived (A2,
  A3, A4);
- it never sends again when the first continuation may already have been delivered (A6);
- it sends only while the Codex app has the conversation open (A11);
- it starts nothing on its own, and nothing when Codex starts (C4, F14);
- it never changes a Codex goal, retries a failure it cannot name, or wakes a conversation the app
  does not hold (0.5, A14).

It holds none of the advanced edition's code. Its archive and its setup program are built from
trees that do not include `advanced/`, and `build/edition_audit.py` proves from their own bytes, in
every release build, that nothing of the advanced edition is in them ([K1](STANDARDS.md#k-the-advanced-editions-own-rules)).
Everything the [guide](GUIDE.md) describes is the standard edition, and the plugin added to Codex
from GitHub installs it.

## The advanced edition

The advanced edition is the standard edition plus capabilities that each depart, on purpose, from
at least one of those standards, and say which (K4). A capability that kept every standard would
belong in the standard edition instead. Until you turn one on or have one watched, the advanced
edition does what the standard edition does; the plugin's name in Codex carries the word *Advanced*.

**Everything is off until you turn it on, one at a time, in the Dashboard.** Every capability
starts off, and installing the edition, or switching to it, turns every one off - except installing it
again over what its own uninstall kept, which, like an update, keeps every choice (K2). The Dashboard has
one more page in this edition, **Advanced features**, the last tab after Settings. Choose a
capability there and read its statement: what it does, what the standard edition does instead,
which standards it departs from, what can go wrong and how to stop it, and any warnings it carries
now. **Turn on** asks once more, with the statement and every warning in front of you; saying yes
confirms them, for the version of Codex shown. **Watch first** instead has it asked wherever it
would act, and note what it would have done, while it does nothing. What it would have done is
counted on its page, under its other cards, for the last 30 days: each answer in words, once for
each recovery it would have acted on, how many times and when last; a diagnostics export you ask
for includes the same. A capability that acts on what you set up for it - a message or a credit at a
reset, a conversation kept going, a queued message - can be set up while it is watched as well: what
it would have sent, and when, is counted there, nothing is sent, spent or read for it, and turning it
on keeps what you set up (from v0.6.16-beta.3). If anything changed while you
were reading, the page reads it again and asks again with what holds now (K3); where it cannot read
it again, or your administrator's policy now refuses it, it says that nothing was turned on, and why.
The page reads the list again after everything you do there, and whenever the watcher says a
capability was turned on or off, here or anywhere else.

**What one needs, it turns on with it.** A capability can need another: Wrap up near a limit and Stop
near a limit both need the usage meter. Turning one on when what it needs is off asks once, with every
statement involved in front of you - its own, then each one it needs - and that one yes turns them all on;
if your administrator's policy refuses any of them, or any statement changed, nothing is turned on. Its
page says what it needs. Turning a needed one off turns off first what needs it, and the page names those
first. A capability whose need is no longer on - turned off, watched, refused by the policy, or failed here
- turns itself off, and says why (K3, as the owner amended it on 2026-10-15).

**Everywhere else, only off.** Nothing else - the panel inside Codex, the notification-area icon,
a card - can turn a capability on. Codex's tools (MCP) can list the capabilities and turn one, or
all of them, off, and no MCP tool turns one on, whatever a client sends (K3). **Turn every advanced
feature off** on the page turns them all off at once.

**Pause stops everything.** While recovery is paused, no capability is asked anything; a
conversation you switched off and a recovery you cancelled are never handed to one; and a pause
that arrives just before a send still stops it at the last moment. Every check a send passes, the
record that it was claimed and the last look before it stay the standard edition's (K5).

**Ceilings.** Each capability may send only so many times a day, in all and in any one
conversation, counted when the send is claimed. Over them stands one ceiling for all capabilities
together, 12 sends an hour - a send counts once, however many capabilities answered for it - which you can
lower on the page, as far as one an hour, and never raise past 12. The page shows a capability's own ceilings beside its statement. Every send also counts
against the standard edition's own limits for the conversation: five in any 24 hours, at least 15
minutes apart (A20) - except where a capability says it departs from A20: a send of the short retries
when Codex is at capacity counts against the program's own capacity limits instead, 48 a day, a minute
apart, and Send now skips the 15 minutes for the one recovery you choose, still within the five a day.

**Two capabilities, one send.** Two capabilities may answer for the same send in ways Codex cannot carry together.
Then the one asked later stands aside for that send - never the one already taken - and the journal says so, on a line
that names the capability it stood aside for and why, instead of recording the send as acted. Each goes on serving
its own cases; where a capability's section below says two apply together, both do.

**Warnings, not refusals.** A measurement a capability rests on that failed, or was never made for
your version of Codex, a compatibility grade of Failed here, Incompatible or Unknown, or a Codex
version not known yet is shown in its statement as a warning. It does not stop you turning the
capability on; turning it on confirms you read it (K6).

**Tripwires.** A capability turns itself off when its statement gets a new revision; when a warning
you did not confirm says that what it stands on went wrong; when one of its parts fails; when a send
it made becomes one whose delivery cannot be proven; and, while it is on, when Codex is updated. The
page says so under the capability's state, and why. You can turn it on again, with its statement as
it then reads (K7). A continuation sent once more and then found twice turns off what sent it again:
Once more when unsure itself, or the *Also send again when unsure* of a capability kept on.

**Keep it on.** On the page, any capability can be kept on: *Keep it on...* turns it on as well, in the one
confirmation turning it on asks - its warning, then its statement and what it needs - and is refused as
turning it on is, and also where its own compatibility check failed on this PC. Kept on is on: the list
and the page say *Keep it on* for it, and setting it to watch takes Keep it on away. Kept on, it does not
turn itself off for any of the tripwires above, nor for a new version of Codex:
the page notes the most serious of them under its state until you turn it on again; a part of it that
fails skips only that one recovery; and a send it made whose delivery cannot be proven is held, as the
standard edition holds one. A Codex version or a compatibility grade that cannot be read still holds
it back, its ceilings stay, and turning it off - here, from Codex or with every advanced feature at
once - always works and lets it turn itself off again. With it you can also choose *Also send again
when unsure*, after a warning of its own: such a send is then sent once more under the rules of Once
more when unsure below, so the capability departs from what that one departs from too, and only where
your administrator's policy allows Once more when unsure as well; a continuation sent again and found
twice turns that choice off, and the capability stays on. The compatibility report sends nothing to
Codex, so it has no such choice. Every capability offers Keep it on, and none is kept on until you choose it on
that capability's card. The policy reads a kept-on capability down
as any other, by the capability's own id: no policy value reaches Keep it on alone (K8).

**Your administrator's policy.** Three values under `Software\Policies\CodexAutoResume`, in
`HKEY_LOCAL_MACHINE` or `HKEY_CURRENT_USER`, read and never written: `ForbidAdvanced` (nothing may be
on or watched), `AllowedCapabilities` (only the ids listed may be) and `ForceShadow` (watched, never
on). Both places count, together they are the stricter, and a value that cannot be read counts as
the strictest. The page says when one of them applies. Like the standard edition's policy keys,
they are what a cooperating installation obeys, not a lock (K6).

What the advanced edition keeps is its own: which capability is on, what each has spent and what it
did, the choices you made for a capability, the rules you wrote, which capability took up which
interruption, the samples of failures it could not classify, the reset rules and what it counted of
the usage windows - and, until each is sent, cancelled or ended, the words of a message you wrote for a
reset - are kept in
`config/advanced/advanced.sqlite`, in fixed words, ids, numbers and Codex's own error codes - never a
word of an error or a conversation, and of yours only a message waiting for a reset - and nothing of it is written into the standard edition's state. It adds no network code. Two capabilities cause GitHub traffic: the compatibility report asks gh - the GitHub CLI you
installed - to reach GitHub, and only when you start it in the Dashboard (below), and
*Check for updates once a week* runs the installed `bootstrap.ps1 -CheckOnly` once a week (below). Its archive also carries
the harness the project uses to measure whether a capability's route works on a given version of
Codex; nothing runs it unless a person asks, and [SECURITY.md](SECURITY.md) says what it does.

No capability stores a secret today. The package carries one way to keep a capability's secret, in Windows'
Credential Manager under a name of its own and never in its database, a settings file or a log, for a capability
that will need one; nothing calls it, and it never reads Codex's own credentials.

## Today's capabilities

Thirty-five: twenty-two that change how a recovery is made, which conversations are recovered or what
follows a turn, three that send at a time you pick - the two at a usage reset, and queued messages - three
before a usage limit is reached - the usage meter, and the wrap-up and the forced stop that need it - one that
checks for updates once a week, two that look after the watcher and the PC - restart the watcher if it stops unexpectedly,
and wake this PC for a reset (v0.6.19) - and four actions: Longer messages, which only lets a message be longer, Open Codex on a notice, which only makes a click on a notice
show a conversation, chat with a conversation in the Dashboard (v0.6.19), which sends a message of yours, and the
compatibility report, which only you start. Four rest on a measurement each that was made - the first three, and queue for when a conversation
is opened. All five added in v0.6.16-beta.4 rest on measurements that were made - running a conversation
here, the other sessions, compacting a full conversation, another model at capacity and a continuation with
no words - and four more (the reset credit, the reset message, the usage meter and the forced stop) rest on
measurements made on `codex-cli 0.162.0-alpha.17.2` and, for the forced stop, again on the newer one. Seven rest on
measurements not made yet - wake this PC for a reset is the new one, on MWAKE - the chat rests on M7, MC1 and MC2, which were made, as its own
section below says, and the other fourteen on none. Each measurement made was made by hand, on the
owner's machine, first on `codex-cli 0.158.0-alpha.2.1`, again on `codex-cli 0.162.0-alpha.17.2` and, for those this release's
capabilities rest on, once more on `codex-cli 0.163.0-alpha.10.2` (2026-10-17) - and MQO, MQP and MQG, which decide how
the continuation with no marker, several conversations at once and the goal continuation sit beside the queue for
when a conversation is opened, on the same version on 2026-10-20;
its record is in [`docs/evidence/live/`](evidence/live/). On any other version of Codex, and for a
measurement not made yet, a capability's statement carries the warning that it was not measured there.

### Start with Codex

**What it does.** When Codex starts the plugin's server, recovery is not paused, no watcher is
running and no installation is in progress, it starts the watcher, through Windows' WMI, outside
the job Codex closes when it quits, so the watcher keeps running after Codex closes. It starts this
installation's own launcher and nothing else, never a second watcher, and it sends nothing itself.

**When it helps.** When you do not have the watcher start at sign-in and want it running whenever
Codex is. The standard edition starts nothing here: a watcher started from inside Codex ends when
Codex closes, so it says so and waits for you to start the watcher yourself (F14).

**What it risks.** Its whole purpose is to step outside a limit Codex places on its plugins on
purpose. If WMI is off, or a policy blocks starting processes through it, nothing starts and the
reason is logged; you are never asked to change that policy.

**Departs from** [C4](STANDARDS.md#c-network) (nothing happens on its own, nothing at start) and
[F6](STANDARDS.md#f-footprint-on-the-machine) (the processes the product starts are a fixed list,
and a route through WMI is not on it).

**Ceilings.** None come into play: it sends nothing.

**Measurement MW: passed.** A process started through WMI from inside a job built as Codex builds
its plugins' jobs landed outside that job and was still running after the job was closed. Nobody has
yet watched a watcher started this way outlive Codex itself; [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md)
asks for that.

### Restart the watcher if it stops unexpectedly

**What it does.** The watcher's launcher stays running beside the watcher, as its parent. When the watcher
stops unexpectedly - not stopped by you, by an update or the uninstaller, by the memory guard, or because
another watcher already runs for this installation - the launcher starts it again five seconds later, at
most three times an hour. After the third restart in an hour it is left stopped: the Dashboard says it
*stopped unexpectedly*, as in the standard edition, and one notification, *The watcher was left stopped*,
says so. The notification is a kind of its own in **Keep on screen until clicked**. A watcher started again
checks what it was doing before it sends anything, as every watcher does when it starts.

**When it helps.** When the watcher should keep recovering while you are away, even if something makes it
crash.

**What it risks.** A watcher that fails again each time it starts is started three times in the hour before
it is left stopped, so the same fault can happen three times. The launcher stays in memory, small, for as
long as the watcher runs. It never ends anything itself; it only starts again what ended. Each restart is
kept, with its exit code, in the advanced state for seven days.

**Departs from** [F6](STANDARDS.md#f-footprint-on-the-machine) (the processes the product starts are a
fixed list, and a second `pythonw.exe` of its own - the launcher kept beside the watcher - is not on it) and
[F8](STANDARDS.md#f-footprint-on-the-machine) (no resident helpers: the launcher stays as the watcher's
parent).

**Ceilings.** None come into play: it sends nothing to Codex. It rests on no measurement.

### Wake this PC for a reset

**What it does.** When a usage limit, a reset credit or a message of your own waits for a reset, it sets a
wake timer for that time, less the minutes you choose (**Minutes before the reset to wake it**: 1, 2 or 5; 2
by default), so a PC asleep wakes and the watcher looks at once. It does so only where Windows' **Allow wake
timers** already allows it for the power source in use (Control Panel > Power Options > Change plan settings >
Change advanced power settings > Sleep > Allow wake timers); the product reads that setting and never changes
it. The timer is moved when the time changes, and taken back when nothing waits, when recovery is paused,
when the feature is turned off or when the watcher stops - the timer belongs to the watcher's process, so
Windows drops it when the watcher ends. Waking changes nothing else: every recovery is checked as before.

**When it helps.** When this PC sleeps while a usage limit waits to reset, and you would rather the work went
on at the reset than when you next wake it.

**What it risks.** A laptop may wake in a bag or with its lid closed - on battery too, where Windows allows
wake timers on battery - and stays awake until it sleeps again by its own settings. Some PCs that sleep the
modern way (Modern Standby) are not woken by such a timer at all; there, the standard edition's **Keep this PC
awake while a task waits** is the way.

**Departs from** [C4](STANDARDS.md#c-network) (nothing happens on its own, on a schedule: it wakes the PC at
a time of its own) and [B16](STANDARDS.md#b-what-it-reads-and-how) (Windows is asked only the listed questions; the
power plan's Allow wake timers value is asked too). It changes nothing machine-wide (F1 kept).

**Ceilings.** None come into play: it sends nothing to Codex. **Measurement MWAKE: not made yet** - whether
such a timer wakes this PC (Modern Standby, the lid, the battery); until it is, the statement carries the
warning that it was not measured.

### Marker-free continuation

**What it does.** Sends each continuation without the marker the standard edition ends it with. The
message is added to the conversation's queue through Codex's own app server (`thread/queue/add`),
under an id made from the interruption, and that id, which Codex keeps on the message, is what proves
it arrived. Past its ceilings, a continuation goes with the marker, as in the standard edition.

It serves every send that carries words. A continuation queued for when a conversation is opened it
carries with no marker too, under its id, where measurement MQO passed on your Codex: the message is found in the
conversation's history by that id when you open it. Where MQO did not pass, and for a continuation sent to another
Codex session, it stands aside and the ordinary send goes with its marker. The sends of Several conversations at once
wait for their receipts together where MQP passed, and one at a time elsewhere. Beside Continue with no words, which
serves the routes that go without words, it serves the sends that carry words.

**When it helps.** When you would rather the continuation read as plain words in the conversation,
without `[codex-auto-resume:…]` at the end.

**What it risks.** It rests on one app-server request, measured on one version of Codex; another
version may refuse it or stop keeping the id. When arrival cannot be proven - the app server
refuses or does not answer, or the message never shows - the continuation is treated as uncertain,
exactly as the standard edition treats one: it is never sent again, and the capability turns itself
off. Every check and limit stays as it is.

**Departs from** [A2](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (one channel only,
`codex queue`), A4 (every continuation carries its marker, and counts as delivered only when the
marker is found), [B3](STANDARDS.md#b-what-it-reads-and-how) (Codex's state changes only through its
queue, the withdrawal of a queued message and the plugin commands) and B4 (the app server is asked
only for usage and to withdraw a queued message).

**Ceilings.** 24 a day, and 5 in any one conversation - the standard edition's own limit for a
conversation.

**Measurement M7: passed.** The app server accepted a message added with such an id, and delivered
the words `/compact` as plain text rather than running them as a command. **MQO: passed** on
`codex-cli 0.163.0-alpha.10.2`: such a message, queued for opening while nothing held the conversation, ran once
when it was opened, as your own message, and was found by its id. **MQP: passed** there too: two added at once, each
in a session of its own, each landed only in its own conversation. On any other version the queue carries its
message with its marker and the sends go one at a time.

### Goal continuation

**What it does.** For a usage limit only. When the limit paused a conversation's Codex goal and the
conversation is due to continue while the Codex app does not have it open, it sets that existing
goal active again through Codex's own app server (`thread/goal/set`), so that Codex carries the goal
on when the app next opens the conversation. It never creates a goal and never reads or changes what
the goal says. While the app has the conversation open, the continuation goes through Codex's queue
as in the standard edition, except where measurement M2b passed for your version of Codex - so far
`codex-cli 0.163.0-alpha.10.2`: there it sets the paused goal active first and then adds the
continuation to the conversation's queue, as M2b did. While a goal it set active carries the
conversation on, the standard continuation waits, for up to ten minutes, so the two do not both run. A conversation
another Codex session holds is not its to wake: that continuation goes to that session, as without it.

**When it helps.** When a usage limit stopped work under a goal and you do not keep that
conversation open: in the standard edition the goal stays paused until you resume it yourself.

**What it risks.** Measurement M2 found that a goal set active this way is not taken up while the app
has the conversation open, which is why, unless M2b passed for your version of Codex, it acts only
where the app does not; where M2b passed it acts there too, setting the goal active and then queueing
the continuation. In the same measurement
the goal was live again once the app loaded the conversation, as its statement says, though the
record in [`docs/evidence/live/`](evidence/live/) keeps only the failing verdict; nobody has yet
followed Codex carrying such a goal on by itself as the app opens the conversation. Another version
of Codex may handle goals differently. When the result cannot be confirmed - Codex does not answer,
or the goal does not read back as active - that interruption is not tried again and the capability
turns itself off. Turning it off leaves a goal it already set active as it is: pause the goal in
Codex to stop it.

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary) (a goal's state is never changed), A2
(one channel only), A11 (nothing is done for a conversation the app does not have open), B3 and B4.

**Ceilings.** 12 a day, and 3 in any one conversation.

**Measurement M2: failed**, for a conversation the app holds; its statement shows that as a warning.
**Measurement M2b: passed** on `codex-cli 0.163.0-alpha.10.2` - a goal set active beside a queued turn
carries on while the app holds the conversation - so on that version it acts there too; on any other,
a conversation the app holds gets the standard continuation alone.

Where the goal continuation and the marker-free continuation are both on and the goal applies, the
goal continuation carries the send.

### Short retries when Codex is at capacity

**What it does.** When Codex says it is at capacity - its own error code `serverOverloaded`, a server
error the standard edition recovers already - it tries again sooner and more often: about a minute
after the failure, then two, four and five minutes, each lengthened by up to a fifth, at least a
minute apart and at most 48 times a day in one conversation. It keeps this up for as long as you
choose on the page, one to twelve hours (two by default), counted on the clock from the task's first
failure; after that the standard edition's waits and limits apply again, and they may end the task.
Each try is the ordinary continuation through Codex's queue, with its marker. Other server errors,
rate limits and usage limits keep the standard edition's waits.

**When it helps.** When Codex is busy for a while and you would rather it kept trying than waited the
standard edition's retry timing and stopped after four attempts.

**What it risks.** Retrying a busy service often adds to its load and spends usage on continuations
that may fail again, and each try is a visible message in the conversation. While the ceiling for
all capabilities together is reached, a capacity error is handled as the standard edition handles
it. However long it keeps answering, the program itself never retries one task for more than twelve
hours on the clock, 48 times a day, or sooner than a minute apart.

**Departs from** [A20](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (five continuations a
conversation in 24 hours, 15 minutes apart), A21 (the attempt, no-progress and continuation budgets),
A22 (waits come only from the retry timing you chose), [B9](STANDARDS.md#b-what-it-reads-and-how)
(only a failure's kind is kept: this also reads Codex's own error code, never its words) and
[H2](STANDARDS.md#h-user-control) (nothing can move a limit the program fixes: A20's are the engine's).

**Ceilings.** 48 a day, and 48 in any one conversation - the one capability whose conversation
ceiling is above the standard edition's five, because it departs from A20.

### Compact a full conversation, then continue

**What it does.** When a turn fails because the conversation is longer than its model's context window, the
conversation is compacted and then continued once. If the Codex app has the conversation open, the recovery
waits, shown in Pending as scheduled, until you run `/compact` in Codex yourself; once you have, the ordinary
continuation follows. If nothing has it open
and Codex is closed, it is compacted here, on Codex's own app server, then continued here as Run a
conversation here while Codex is closed would. Codex's own automatic compaction comes first; this is for when
it did not. The program never sends `/compact` itself: a queued `/compact` reaches Codex as plain text.

**When it helps.** When a conversation has grown too long, Codex's own compaction did not save it, and you
would rather it were compacted and carried on than left stopped.

**What it risks.** A compaction loses detail of the earlier conversation. If the compaction fails or does not
end within ten minutes, or none comes within a day, the recovery ends as the failure it is. That a
compaction behaves here (MX) and after your own `/compact` (MXA) was measured, but not on every version of Codex.

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary), A2, A11, B3, B4, E8 and F8 (as Run a
conversation here while Codex is closed), A13 and A14 (a context-length failure is taken up), A16 (the
continuation follows the compaction turn, so the failure is no longer the latest turn), A17 (a compaction
turn does not supersede the record) and A26 (the continuation's words for a failure the standard edition does
not recover).

**Ceilings.** 6 a day, and 2 in any one conversation - the compaction's and its continuation's.
**Measurement M7: made** (a queued `/compact` reaches Codex as plain text) and **MX: passed** on `codex-cli
0.163.0-alpha.10.2`; **MXA: passed** on `codex-cli 0.162.0-alpha.17.2`. On any other version, a warning each.

### Use Codex's default model when one is at capacity

**What it does.** When a turn keeps failing because its model is at capacity, for as many attempts as you
choose (one to three, two by default), and nothing has the conversation open while Codex is closed, it runs
the next turn here on Codex's default model instead, then puts the conversation's own model back. Only where
the conversation is on another model than the default; never for a usage, rate, sign-in or billing failure.

**When it helps.** When a model stays at capacity and you would rather the conversation went on, on another
model, than waited.

**What it risks.** The turn runs on another model, which may answer differently. If Codex refuses to put the
conversation's model back, Pending and History say so, and you switch it back in Codex. Putting it back
through `thread/settings/update`, and reading it back, was measured (MF).

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary) (it changes and replays a model setting, and runs
a turn of its own), A2, A11, B3, B4, E8 and F8 (as Run a conversation here while Codex is closed) and
[B9](STANDARDS.md#b-what-it-reads-and-how) (it reads Codex's error code, not only a kind).

**Ceilings.** 6 a day, and 2 in any one conversation. **Measurement MF: passed** on `codex-cli 0.163.0-alpha.10.2`; on any other version, a warning.

### Rules for Codex's error codes

**What it does.** Lets you write up to ten rules on the page. Each names one of Codex's own error
codes, and if you like a range of status numbers, and the kind of temporary failure to treat it as: a
dropped connection, a timeout, a rate limit, a server error or a broken stream. A rule applies only
to a failure the program could not classify; it then waits as that kind waits in your retry timing,
counts against that kind's budget and follows that kind's switch in Settings. A code the program
already knows can never be a rule, nor one whose name speaks of a policy, budget, quota, permission,
approval, sign-in or cancellation, and no rule makes a failure a usage limit. Rules read codes, never
the words of an error. The page lists each rule with how many failures it took up in the last 30
days, and offers the codes the samples (below) saw.

**When it helps.** When you know that a code Codex sends, which this program does not know yet, is
temporary.

**What it risks.** A rule is your judgement that a code is temporary. A wrong one retries failures
that retrying cannot fix, until that kind's budget runs out, and Codex may rename or reuse a code in
another version. Removing a rule ends what it took up and has not sent.

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary) (a failure it cannot classify is never
retried), A13 (only the classified kinds are recovered), A14 (anything unclassified is never
retried), A26 (continuation text only for a kind that is recovered), B9 and
[H2](STANDARDS.md#h-user-control) (nothing can retry an unknown failure: a rule is a setting of yours).

**Ceilings.** 24 a day, and 5 in any one conversation.

### Retry failures it cannot name

**What it does.** When a turn fails with an error code of Codex's that the program cannot classify,
it continues the conversation anyway, on a budget of its own: one to three tries a task, as you
choose on the page (one by default), the first ten minutes after the failure, then 15 and 30. It
never takes up a failure that came with no code, or a code whose name speaks of a policy, budget,
quota, permission, approval, sign-in or cancellation; a rule that names the code comes first. Each
failure it takes up leaves a sample: Codex's error code, the status number, the form of the error,
how many items of each kind the turn left, a time rounded to the minute and how long the turn ran -
never a word of the error, the conversation or the reply. The page lists them for the last 30 days,
and a diagnostics export you ask for includes them; nothing sends them.

**When it helps.** When Codex fails in a way nobody has classified yet, and you would rather the
conversation tried again than waited for you.

**What it risks.** A failure nobody classified may be one retrying cannot help, or one where trying
again repeats something a person should have decided. A sample keeps a code Codex chose, which may say
more than the program's own words. Samples are kept 90 days at most.

**Departs from** 0.5, A13, A14, A26, B9, [D2](STANDARDS.md#d-privacy-and-the-data-it-keeps)
(state holds only the program's own fixed words, never a code Codex chose) and
[H2](STANDARDS.md#h-user-control) (nothing can retry an unknown failure).

**Ceilings.** 12 a day, and 3 in any one conversation.

### Retry when Codex gave up

**What it does.** When Codex ended a turn after its own retries failed (its error code
`responseTooManyFailedAttempts`) and the last answer it had was a server error or none at all, it
continues the conversation once Codex has had time to recover: ten minutes after the failure, then
15, and at most twice a task. When the last answer was a rate limit, the standard edition already
retries it.

**When it helps.** When Codex gave up during an outage that has since passed.

**What it risks.** Codex already tried several times, so trying again is not a fresh attempt: it may
fail the same way and use your usage.

**Departs from** A14 (Codex giving up without a 429 is never retried), A26 and B9.

**Ceilings.** 12 a day, and 2 in any one conversation.

### Retry a sign-in failure after proof

**What it does.** When a turn fails because Codex was not signed in (its error code `unauthorized`, or
status 401), it waits at least ten minutes and continues the conversation once - and only when the
usage read every continuation already needs shows Codex is signed in again. Once a task and twice a
day in all; if the continuation fails at sign-in again, it stops there, and after a day without a
working usage read it gives up. It never reads or changes Codex's sign-in, its `auth.json` or any
token, and never asks Codex to sign in or out. A permission refusal (403) is never retried.

**When it helps.** When Codex's sign-in lapsed and you signed in again, and you would rather the
conversation went on by itself than you continued it.

**What it risks.** A usage read proves Codex reaches your account, not that every request will be
accepted, so the continuation may fail again. If you signed in with another account, the
conversation continues under that one.

**Departs from** 0.5 (a sign-in failure is never retried), A14 (401 and 403 are never retried) and
A26.

**Ceilings.** 2 a day, and 2 in any one conversation.

### Notice a usage limit that lifts early

**What it does.** While a conversation waits for a usage limit to reset, it asks Codex every five
minutes whether usage is available - one question for every conversation waiting - and when two
answers at least five minutes apart both say yes, it continues the waiting conversations then,
before the reset time Codex gave. A postponement and quiet hours still hold, and a look that finds no
usage changes nothing about the conversation: it keeps its state and its next look. It only reads: it
never sends anything to start a usage window or keep one open. While it is on, Pending's **Why it is
waiting** says, for a conversation that waits for a usage limit and under the other usage readings, when
it last asked, what the answer was and whether anything was continued. It has no line or button of its
own on Pending (from v0.6.19; the Check now and Early reset settings buttons of v0.6.19-beta.2 are gone):
a **Retry now** or a **Rescan** there reads usage at once, and while this is on that reading counts as
one of its questions, for every waiting conversation together - the next one at least five minutes
after it. If that reading says usage is available, the conversations it was asked for go on through
every check, as they would without this; every other check still runs. It is turned on and off only on
the Advanced features page.

**When it helps.** When Codex lifts a limit before the time it gave.

**What it risks.** Each question is a request to OpenAI through Codex. Usage that reads as available
may be available for another model or plan than the one the conversation uses, and the continuation
may meet the limit again; the usage check every continuation makes still applies.

**Departs from** [A12](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (never before the real reset
time) and [C9](STANDARDS.md#c-network) (Codex is asked about usage only when a recovery is due).

**Ceilings.** 12 a day, and 3 in any one conversation.

### Once more when unsure

**What it does.** When it cannot be proven that a continuation arrived - the queue command's answer
was lost, or no receipt came - it sends it once more, its words built the same way and with the same
marker, between 15 minutes and 6 hours after the first: only if Codex was never seen holding it in
its queue, neither Codex's history nor its queue holds the marker, the history was current at every
look since, the conversation has no later turn and nothing queued, its attempts are not used up and
every check a send passes still holds. A continuation is sent again at most once, one that Pause or
Observe only takes back is never sent again, and nothing is sent again after the watcher restarts. A
continuation another advanced feature carried by a route or a channel of its own is never sent again
by this one.

**When it helps.** When a continuation never reached Codex and nothing could say so.

**What it risks.** If the first continuation did arrive late, the conversation gets the same
continuation twice and Codex may do the same work twice; if the marker is then found twice, it turns
itself off. The words are built again from your settings as they are then.

**Departs from** [0.2](STANDARDS.md#0-the-edition-boundary) (never again when the first may already have been delivered),
[A6](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (an uncertain delivery is never sent again), [E2](STANDARDS.md#e-failure-behaviour) (better to miss a resume than resume
twice) and [H2](STANDARDS.md#h-user-control) (nothing can resend an uncertain submission).

**Ceilings.** 6 a day, and 2 in any one conversation.

### Send now

**What it does.** While it is on, the page lists the recoveries waiting now, each with *Send now...*.
For the one you choose, the watcher sends its continuation at its next look instead of when its
schedule says: it passes the wait before the next try, a postponement, the minutes before a first
send, the 15 minutes between two continuations in one conversation and an attempt budget you set that
is used up - never one your administrator set. Where an early look - the look a reset credit allows before the reset
time - could answer for the same recovery, your request wins where Send now can send; before a usage reset, which
Send now never passes, the early look sends it. Every other check still runs. A request not used within
15 minutes lapses, and turning it off, or setting it to watch, voids one not yet used.

**When it helps.** When the cause of a failure is gone and you do not want to wait for the schedule.

**What it risks.** A continuation sent sooner may meet the same failure again and use an attempt the
schedule would have kept for later. It never sends before a usage limit resets, in quiet hours, past an
attempt limit your administrator set, past five continuations in a conversation in a day, while
recovery is paused or the conversation is off, before the app has the conversation open, while
something else is queued for it, or without usage.

**Departs from** [A8](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (the claim checks the schedule and the budgets again, passing none),
[A20](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (at least 15 minutes between two continuations in a conversation), [A21](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (the attempt
budget stops a recovery) and [H2](STANDARDS.md#h-user-control) (nothing can force a send).

**Ceilings.** 24 a day, and 5 in any one conversation.

None of the eight rests on a measurement: what each sends is the continuation the standard edition sends.
Each of the four that take up a failure the standard edition leaves for you takes up only failures
from the last hour, and none from before it was turned on or set to watch; turning it off or setting
it to watch only ends what it took up and has not sent, and the program ends such a recovery unsent a
day on the clock after the failure in any case.

### Open Codex on a notice

**What it does.** While it is on, every notice about one conversation - a usage limit detected, a
continuation being sent, how one ended - opens Codex when it is clicked, on the program's card and on
Windows' own notification alike (no button is added: the buttons stay as they were, and the click that
would have opened a page of the Dashboard opens Codex instead). The click shows that conversation in the
Codex app through Codex's own link to it: a running or minimized app comes to the front at that
conversation, and a closed one starts there (measured on Codex app 26.1007). A click you sent to the
conversation's chat in the Dashboard's chat card stays there. It applies only where Windows has something
registered for `codex:` links, which is read and never written. A notice about no one conversation - a
warning near a limit, the memory guard, the power action - never has it.

**When it helps.** When a notice says something about a conversation and you want to look at it at once.

**What it risks.** The link is Codex's, not this program's: a version of the Codex app that changes it may
open without the conversation, or not at all. Nothing is sent and nothing in the conversation changes.

**Departs from** [A28](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (a notice's button only cancels
one interruption or opens one page of the Dashboard), [B16](STANDARDS.md#b-what-it-reads-and-how) (Windows
is asked only the listed questions; whether something is registered for Codex's links is read too) and
[F6](STANDARDS.md#f-footprint-on-the-machine) (starting explorer.exe with a Codex link, which hands the link to Windows, is not one of
its listed uses: showing the logs folder).

**Ceilings.** None: it is an action, and sends nothing. It rests on no measurement of its own.

### Use a reset credit at the limit you pick

**What it does.** On the page you pick a usage limit ahead of time - the next time the 5-hour limit
is reached, a later time up to nine from now, or the next weekly limit - once or every time, and
whether it asks you first. When that limit is reached while a recovery waits for usage, it uses one of
your reset credits, so the recovery can go on. While a rule waits it reads usage every 15 minutes, at
most once in five minutes, and counts each window's fills and resets itself, from the first reading
after you added the rule: a limit reached when you add it is not the next one. Before it spends a
credit it reads usage again: the window must still be full, a recovery must still be waiting for
usage, and how many credits you have and when the soonest expires must both be readable. Until
measurement MR has passed on your version of Codex it never spends on its own: the rule waits for
you to press *Use a reset credit now...*, which the page also offers whenever a limit is reached. The
page shows how many credits you have, when the soonest expires and when one was last used; Pending
lists each rule still waiting as a row of its own, with Cancel.

**When it helps.** When your account has reset credits and you would rather spend one than wait for a
limit you know is coming, without watching for it.

**What it risks.** A credit spent cannot be given back, and one may be spent shortly before the window
would have reset anyway. If you redeem two credits yourself in Codex's `/usage` inside one window, its
count can run one window late. If this PC is off or recovery is paused for longer than the window, the
rule is held until you say *Go on counting* or cancel it, rather than guess. It never spends more than
one credit for one filling of a window, two in a day or seven in a week; never while recovery is
paused, in Observe only, in quiet hours or with no recovery waiting; and never when the count or the
expiry cannot be read. A spend whose result cannot be known turns it off.

**Departs from** [A12](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (a look before the real
reset time, once a credit reset the window), [B3 and B4](STANDARDS.md#b-what-it-reads-and-how) (it
changes your account, through Codex's `account/rateLimitResetCredit/consume`, a method beyond the
app server's three requests), [B10](STANDARDS.md#b-what-it-reads-and-how) (it keeps how many credits
you have and when the soonest expires), [C4](STANDARDS.md#c-network) (it reads usage and spends on
its own, at the time you chose) and [C9](STANDARDS.md#c-network) (it reads usage when no recovery is
due).

**Ceilings.** 12 a day, and 3 in any one conversation; and never more than one credit for one filling
of a window, two a day or seven a week. Four rules may wait at once.

**Measurements MU, MN and MR: passed** on codex-cli 0.162.0-alpha.17.2 (2026-10-10,
[`docs/evidence/live/`](evidence/live/)). MU reads usage as this capability reads it - with the
credits' count, and without their details - and how still a window's reset time stays; MN asks for a
credit on an account with none and checks that nothing is spent; MR, at a real limit and only with
the person's own second yes, spent exactly one credit, which lifted the limit, and asking again with
the same key spent no second one. On that version of Codex the statement carries none of them as a
warning, and a credit is used at the limit you picked by itself, unless you chose *Ask me first*; on
any other version each is a warning until it is measured there, and a credit is spent only when you
press *Use a reset credit now...*.

### Send your own message when a limit resets

**What it does.** On the page you write a message of your own, up to 2,000 characters, for one
conversation that is switched on, and pick when it goes: when the 5-hour limit next resets, a later
reset up to nine from now, or the weekly limit's next reset. The page offers the conversations the Dashboard knows from Pending and History that are switched on; one that has never appeared in either is not offered yet. At that reset the watcher sends it once,
exactly as you wrote it, with its marker after a blank line, through every check a continuation passes
- the conversation open in the app, nothing else queued there, usage available. A recovery waiting in
that conversation for the same reset sends your message in its place, at the very moment the window
resets too; it waits for your message up to 30 minutes after the reset, and then goes on. It counts from the first reading after you added it, so the window open
then is the first to reset; a window not used yet counts once it is. While a message waits it reads
usage every 15 minutes, at most once in five minutes. One message may wait for a conversation, and
ten in all; the page lists each with its words, and Pending lists each as a row of its own, with
Cancel - its words are never shown there.

**When it helps.** When you know what a conversation should do once the limit is gone - "carry on with
the release notes", "run the tests again" - and want it said as soon as it can be, in your words.

**What it risks.** Your message may arrive when you no longer want it: it goes as written, whatever the
conversation has become. If you redeem two credits yourself inside one window, it can go one window
late. If this PC is off or recovery is paused for longer than the window, it waits for you to say *Go
on counting*. It is never sent twice; one that cannot be proven to have arrived a day after it was
sent turns this off. Your words are kept in the advanced edition's state until they are sent,
cancelled or ended, and then deleted.

**Departs from** [A8](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (its message passes the
checks that apply to it; a recovery's budgets and failure checks are not run),
[A17](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (a turn after it does not take it back),
[A26](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (the words are yours, not a template, and
recover no failure), [C4](STANDARDS.md#c-network) (it sends at a time you chose),
[C9](STANDARDS.md#c-network) (it reads usage when no recovery is due),
[D2](STANDARDS.md#d-privacy-and-the-data-it-keeps) (your words are kept until they are sent),
[H4](STANDARDS.md#h-user-control) (a Pause takes back a message Codex already holds and cancels it, rather
than returning it to waiting; revision 2, from v0.6.16-beta, first published as v0.6.15-beta) and
[H6](STANDARDS.md#h-user-control) (Cancel no longer reaches a message being sent). It keeps A27: a
message is at most 2,000 characters, as the Custom message is, unless Longer reset messages is on.
Switching its conversation off cancels it (H5).

**Ceilings.** 10 a day, and 2 in any one conversation.

**Measurement MU: passed** on codex-cli 0.162.0-alpha.17.2 (2026-10-10). It counts resets from the same
usage readings as the reset credit, so it rests on MU; on any other version of Codex, until MU is made
there, the statement carries it as a warning.

### Longer messages

**What it does.** An action: it sends nothing and answers at no point of a recovery. While it is on, a
message you schedule for a reset, and from v0.6.16-beta (revision 2) a message you queue, may be up to
8,154 characters - the most one continuation can carry - instead of 2,000. Turned off, every waiting
message longer than 2,000 characters is cancelled.

**When it helps.** When what you want a conversation to do after a reset takes more than 2,000
characters to say.

**What it risks.** A long message uses more of the window it starts than a short one.

**Departs from** [A27](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (a message a person writes
is at most 2,000 characters), and from nothing else: on its own it does nothing.

**Ceilings.** None of its own: it sends nothing. **No measurement.**

### Several conversations at once

**What it does.** The standard edition sends one continuation at a time and waits up to 45 seconds for
Codex's answer before it looks at the next. With this on, two to four continuations wait for Codex's
answer at once, each in a conversation of its own - one conversation still never has two on their way -
while every check, every claim and the last look before each send still run one at a time. You choose
how many (2 by default); until MQ passes on your version of Codex, never more than 2.

**When it helps.** When several conversations hit the same usage limit and should all go on as soon as it
resets.

**What it risks.** Several Codex queue processes start close together, which a busy Codex may answer late.
A continuation whose arrival cannot be proven is never sent again, and this turns itself off.

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary) (one recovery is dispatched at a time) and
[A19](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (continuations are dispatched in sequence, under
one lock). It keeps A19's one continuation in flight per conversation.

The sends of the continuation with no marker are pooled with the rest where MQP passed on your Codex; where it
has not, they go one at a time, and the journal says so.

**Ceilings.** 48 a day, and core's 5 in any one conversation. **Measurement MQ: not made yet;
MQP: passed** on `codex-cli 0.163.0-alpha.10.2`.

### Queue for when a conversation is opened

**What it does.** When a usage limit has reset in a conversation the Codex app does not have open, it sends
the ordinary continuation anyway - the program's own words and marker, through every check; with the
continuation with no marker on, and MQO passed on your Codex, with no marker, under its id - and leaves it
in Codex's queue, so Codex runs it when you open the conversation. It stays there for the days you choose (3
by default, 7 at most); the program takes it back at seven days and an hour whatever it is told, and at once
when this is turned off. An interruption is queued this way once; taken back, it waits for the app as usual.
It takes up conversations a usage limit stopped, and no others: a full context window waits for its compaction,
and a network or server failure waits for the app. Beside the goal continuation: where MQG passed on your Codex - a
queued message runs once when the conversation is opened, and the goal carries on after it - both apply; where it
has not, a conversation whose goal is active is left to the goal continuation alone, one continuation, and the
journal says why.

**When it helps.** When you will come back to a conversation later and want it to go on the moment you open
it.

**What it risks.** A message may wait in Codex for days, and while it waits its recovery counts as open, so
an action set for after every recovery has finished waits too. Opened and not run within three minutes, it
is taken back, sent the ordinary way, and this turns itself off.

**Departs from** [A11](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (nothing is queued on the off
chance that a conversation will be opened). It keeps A17, H4 and H6: every withdrawal still happens at once.

**Ceilings.** 12 a day, and 3 in any one conversation. **Measurement M1: made** on `codex-cli
0.163.0-alpha.10.2`; on any other version, a warning. **MQO and MQG: passed** there too (MQO is described
under Marker-free continuation).

### Open a waiting conversation in Codex

**What it does.** When a recovery or a scheduled message is due and waits only because the Codex app does not have
its conversation open, it opens that exact conversation once, through Codex's own link (`codex://threads/<id>`,
the one Open Codex on a notice uses), and the next ordinary check finds it loaded and sends as always - opening is
never taken as proof of loading. It opens only where the app is known not to hold the conversation, never where
that is unknown; only while this PC has been idle for the minutes you choose (2, 5 or 15; 5 by default - opening
brings Codex to the front); only while a handler for `codex:` links is registered; and only while Codex is running,
unless **Also start Codex when it is closed** is on (off by default). A Pause, Observe only and quiet hours hold
it. Beside Queue for when a conversation is opened, the opening delivers what that queued - nothing is sent twice;
a conversation another session holds is never opened.

**When it helps.** When you are away and the only thing between a recovery or a scheduled message and Codex is that
nobody opened the conversation.

**What it risks.** Codex comes to the front when it opens a conversation - which is why it waits until the PC is
idle. If opening does not load the conversation, nothing is sent; it tries again later, three times for one
message at most.

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary) (it wakes a conversation the app does not hold, through
the app's own link), [B16](STANDARDS.md#b-what-it-reads-and-how) (it asks Windows when this PC was last used - a time,
nothing of what was typed - and reads whether the `codex:` handler is registered),
[C4](STANDARDS.md#c-network) (it acts on its own) and [F6](STANDARDS.md#f-footprint-on-the-machine) (Windows opens
the link). It keeps B13 - it simulates no input and drives no window - and A11: nothing is sent until the ordinary
check finds the conversation loaded.

**Ceilings.** Ten minutes between any two opens, an hour between two of one conversation, three for one message and
twelve a day - kept on disk, so they hold after a restart. **Measurement MOPEN: passed** on `codex-cli
0.165.0-alpha.1.2` - a conversation the app did not hold, opened through its link, brought Codex to the front and
was held by the app within ten seconds (thirty are allowed); on any other version, a warning.

### Run a conversation here while Codex is closed

**What it does.** When a recovery is due in a conversation that nothing has open - the Codex app is closed
and no terminal or VS Code session holds it - it runs that one turn here, on Codex's own app server on this
PC, with the program's ordinary continuation, marker included, and the settings Codex saved for that
conversation. Every approval the turn asks for is declined: open the conversation in Codex to approve. The
turn runs for the hours you choose at most, one to six (one by default), and is stopped at once when the
Codex app starts. A running turn can be stopped from the Dashboard (the Advanced features page); no Codex
tool (MCP) can stop it.

**When it helps.** When a limit resets or a request fails while Codex is closed, and you want the
conversation to go on without opening the app.

**What it risks.** Work is done while nobody watches, within the conversation's own saved permissions: a
command those settings allow can run. A conversation saved with full access, with an outside sandbox or
with approvals that go to anyone but you is refused before anything starts. While the turn runs, the
conversation is busy for Codex. That a turn on a conversation's own settings behaves was measured (M6B).

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary) (it wakes a conversation and runs a turn of
its own), A2 (a way to Codex beside `codex queue`), [A11](STANDARDS.md#a-what-it-may-send-to-codex-and-when)
(something is done for a conversation the app does not hold), [B3 and B4](STANDARDS.md#b-what-it-reads-and-how)
(more of Codex's app server) and [E8 and F8](STANDARDS.md#e-failure-behaviour) (a Codex helper process that
lives for the turn, which this program ends). It keeps A4: the continuation carries its marker, and the
marker proves its arrival.

**Ceilings.** 12 a day, and 3 in any one conversation. **Measurement M6: made** on `codex-cli
0.163.0-alpha.10.2`. **M6B: passed** there too; on any other version, a warning.

### Recover CLI, TUI and VS Code conversations

**What it does.** Also finds the failures of conversations you run in a terminal (the Codex CLI and TUI) or
in the VS Code extension, and recovers them as it recovers the Codex app's. While another Codex session
holds such a conversation, the continuation goes through `codex queue` for that session to take; if that
session ends first, the continuation is taken back and waits again. With Run a conversation here while Codex
is closed also on, a conversation nothing holds is run here.

**When it helps.** When you work in a terminal or in VS Code and want those conversations to go on after a
usage limit or a failure as the app's do. The standard edition looks only at the app's conversations, and a
conversation held by another session waits with a reason of its own.

**What it risks.** The words Codex uses to tell these conversations apart (MO) were measured on
`codex-cli 0.163.0-alpha.10.2` and may differ in another version of Codex: a wrong word finds nothing, never the wrong conversation. A session that ends with
the continuation still queued leaves it to be taken back, and one that cannot be taken back is never sent
twice. A session that did not take a queued message within three minutes turns this off; kept on, it stays on and
the page notes it, and the message is still taken back and waits again.

**Departs from** [A15](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (only the desktop app's
conversations are detected) and A11 (it sends while a Codex session other than the app holds the
conversation). It keeps A2, A3, A4, A17, H4 and H6: one channel, the exact conversation, the marker, newer
work wins, and Pause and Cancel take a queued continuation back.

**Ceilings.** 24 a day, and 3 in any one conversation. **Measurement M5: made** on `codex-cli
0.163.0-alpha.10.2`. **MO: passed** there too; on any other version, a warning.

### Continue a turn that ended with no reply

**What it does.** When a turn in a conversation of yours ended with no reply - Codex completed it with only
your message and its reasoning in it, which is all it judges by, never the words - it sends one short
continuation of its own: "The last turn ended without a reply. Please continue from where you stopped." It
looks twice, half a minute apart, before it decides; a conversation whose goal Codex is keeping going, or
has stopped, is left alone. Each such turn is answered once, and a run of them twice at most.

**When it helps.** When Codex sometimes stops a turn with nothing said, and you would rather it carried on.

**What it risks.** Codex may have meant to end the turn quietly. It is sent only while that turn is still
the conversation's latest, and never twice for one turn.

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary) (only failed turns are recovered),
[A13](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (only failures the product can classify) and
[A26](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (its continuations are its fixed templates or your
Custom message).

**Ceilings.** 12 a day, and 2 in any one conversation. **Measurement ME: not made yet.**

### Tell a parent which of its subagents stopped

**What it does.** When a subagent of one of your conversations stops on a failure, the parent is told in
fixed words, one line for each subagent, five at most: "Subagent <its id> stopped: <why>. Resume or respawn
it only if it is still needed." If the parent failed too, the lines are added to the continuation the program
sends it anyway; if it finished normally, it is sent one continuation with the lines - only once MS passes
on your Codex. Nothing is ever written to a subagent, and each stop is told once.

**When it helps.** When a parent goes on without knowing that work it handed out stopped.

**What it risks.** The parent may resume or respawn work you meant to drop. Only a subagent's id and a fixed
word for why it stopped are told - never anything it said.

**Departs from** [0.5](STANDARDS.md#0-the-edition-boundary), [A15](STANDARDS.md#a-what-it-may-send-to-codex-and-when)
(subagent conversations are never detected or recovered) and
[A26](STANDARDS.md#a-what-it-may-send-to-codex-and-when).

**Ceilings.** 12 a day, and 3 in any one conversation. **Measurement MS: not made yet** - until it is, a
parent that finished normally is told nothing.

### Keep a conversation going

**What it does.** For a conversation you pick on the page - one the Dashboard knows from Pending and
History that is switched on - with a count of 1 to 10: when its latest turn
ended well and it has been idle for a minute, it sends one continuation of its own - "Carry on with the next
step of the plan." - up to the count you chose. It stops when a turn made no progress, when every step of
the plan is completed, when a plan cannot be read, when a goal of Codex's own is keeping it going, when a
turn failed or was interrupted, or when the count is used. It reads only the kinds of item a turn left and
the status of each plan step, never their words. Until MK passes on your Codex, no more than 3 are sent.

**When it helps.** When a long plan should go on step by step while you are away. Codex's own goals
(`/goal`) are the first thing to try: they keep a conversation going within Codex's own limits.

**What it risks.** Work goes on when you might have wanted it to stop: stop it on the page, or switch the
conversation off. It is paced like every recovery.

**Departs from** [A13](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (only failures are recovered),
[A26](STANDARDS.md#a-what-it-may-send-to-codex-and-when) and [B9](STANDARDS.md#b-what-it-reads-and-how) (nothing is
read from the content of a conversation's items).

**Ceilings.** 24 a day, and core's 5 in any one conversation. **Measurement MK: not made yet.**

### Queue messages for later

**What it does.** You queue messages of your own for one conversation - one the Dashboard knows from Pending
and History that is switched on: to go after the turn now running, at a
time you pick, or every day or week from a time - 30 times and 30 days at most. They go in the order you queued
them, each once, exactly as you wrote them, and one can wait for the one before it to arrive. For a message at a
time or on a schedule you choose what it does while a turn is running in that conversation: **Wait until it ends**
(recommended, and what a new message does unless you choose otherwise) or **Add it to Codex's queue now**, for
Codex to run after that turn; a message queued before this choice existed goes into Codex's queue, as every message
did. They are paced like every recovery: fifteen minutes apart and five a day in one conversation. Codex's own
automations are the official way to schedule work; these wait for usage and go to one exact conversation.

A message is scheduled with **Schedule...** - on this capability's card on the Advanced features page, or under
Pending's list, where it stands in one place after Cancel all and Rescan whatever row is chosen - both opening the same
editor. From then on it is managed on Pending, whose one list holds
every message still to go and every reset rule still to act as rows after the recoveries (from v0.6.19; v0.6.19-beta.2 had a Scheduled tab for them).
There is no tab strip and the list stays flat; its **Kind** column tells a recovery, a scheduled message (with what it
does while a turn runs) and a reset rule apart, and a row says the conversation, where it stands and when it goes,
never its words. The buttons under the list follow the row you choose: for a recovery, Retry now, Cancel, Timeline and
Turn off for this conversation; for a message, **Edit...** (while it is still waiting), **Go on** and **Cancel**; for
a rule, **Go on** and **Cancel** - the others are hidden, Cancel all and Rescan never move, and the row stands on one
line in every language. A double-click on a waiting message opens its editor. The editor shows the words larger
than the rest of the window, marks the recommended mode and chooses it for a new message, and has **Save and return**:
saved, it closes and the saved row is chosen; refused, every field stays as you typed it and the reason is said above
the buttons. An edit reaches only a message still waiting, and is refused if anything changed since the list was
read. A reset rule's row says where it stands in a word, and Why it is waiting says it in full. Completed messages
are history: the History page lists the messages of the last 30 days that were delivered, their times written as a
recovery's are, and its one **Clear history** clears them with the finished recoveries: it asks first, saying how many
of each; hides the recoveries as it always did; deletes only the completed messages it shows that are unchanged
since; says how many it deleted and how many it kept because they changed; and never touches a waiting, held,
cancelled or failed message or anything of Codex's. The Advanced features page's card for
this capability keeps its switch and limits, and **Schedule...**, and says that a message is scheduled there or on
Pending and managed on Pending.

**When it helps.** When you want the next instruction to be there as soon as Codex can take it.

**What it risks.** A queued message can go when you no longer want it: cancel it. One Codex already holds
is taken back out of its queue; if Codex will not give it back, its row says so and it is never sent again. One
added to Codex's queue while a turn runs waits there - Codex decides when it runs it; one that waits for a running
turn keeps waiting while whether a turn is running cannot be read. Both still pass every check a message passes.
Your words are kept in the advanced edition's state until each has arrived, been cancelled or ended -
while Codex holds one, so that Go on after a Pause can send it again - and then deleted.

**Departs from** [A8](STANDARDS.md#a-what-it-may-send-to-codex-and-when),
[A17](STANDARDS.md#a-what-it-may-send-to-codex-and-when), [A26](STANDARDS.md#a-what-it-may-send-to-codex-and-when),
[A27](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (longer than 2,000 characters while Longer messages
is on), [C4](STANDARDS.md#c-network), [D2](STANDARDS.md#d-privacy-and-the-data-it-keeps),
[H4](STANDARDS.md#h-user-control) (a Pause takes back a message Codex already holds and holds it for you to go
on or cancel) and [H6](STANDARDS.md#h-user-control) (Cancel no longer reaches a message being sent). It keeps
A20.

**Ceilings.** 30 a day, and core's 5 in any one conversation. **Measurement MT: not made yet** - "after this
turn" says it is unproven until it is. Its statement is at revision 2 since the send mode (v0.6.19): if it was on,
you read the new statement once and turn it on again.

### Chat with a conversation in the Dashboard

**What it does.** A **Chat** tab beside **Advanced features**, there only while this is on, opens a **Chat**
page of its own, and is marked as the chosen tab while that page is on screen (from v0.6.19; v0.6.19-beta.2's tab
went to a card on the Advanced features page). That page's card for this capability keeps its switch, its limits
and its statement, with a button that opens the chat; a notification whose click goes to a conversation's chat opens
the Chat page at that conversation. You pick a conversation - one the Dashboard knows from Pending and History that is switched
on, or the one a notice opened the chat on - and read its last twenty turns - your messages
and Codex's replies, read from Codex's history on this PC while the chat is open, with a turn's commands and
file changes as counts - and send a message of up to 2,000 characters. It goes into the conversation exactly
as you typed it, with no marker, through Codex's own queue (`thread/queue/add`), and shows there as your own
message. While its turn runs the chat says "in progress"; the reply shows once the turn ends. Approvals are
still answered in Codex. A message written while the usage limit is full waits - at the same usage check every
send waits at, with no schedule of its own - and goes when the limit resets. While it is on you also pick where a
click on a notification goes: its page, that conversation's chat here, or Codex at that conversation.

**When it helps.** When you want to tell a conversation what to do next without switching to Codex, or to
leave the next instruction for when the limit resets.

**What it risks.** Messages and replies are read and shown on this PC, never kept, logged or sent anywhere
else. Your words are kept in the advanced edition's state only until the message is sent, and deleted then.
A message Codex does not take within three minutes is taken back and never sent again by itself. It works
only where the Codex app has the conversation open - with Codex closed nothing is sent - and on this PC only.

**Departs from** [A2](STANDARDS.md#a-what-it-may-send-to-codex-and-when), [A4](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (no marker: it is proven by its id), [A8](STANDARDS.md#a-what-it-may-send-to-codex-and-when), [A17](STANDARDS.md#a-what-it-may-send-to-codex-and-when),
[A20](STANDARDS.md#a-what-it-may-send-to-codex-and-when) and [H2](STANDARDS.md#h-user-control) (its own pace), [A26](STANDARDS.md#a-what-it-may-send-to-codex-and-when), [A27](STANDARDS.md#a-what-it-may-send-to-codex-and-when), [B3](STANDARDS.md#b-what-it-reads-and-how) and [B4](STANDARDS.md#b-what-it-reads-and-how) (the app
server's queue), [B7](STANDARDS.md#b-what-it-reads-and-how) (it reads messages and replies), [D2](STANDARDS.md#d-privacy-and-the-data-it-keeps), [H4](STANDARDS.md#h-user-control) and [H6](STANDARDS.md#h-user-control).

**Ceilings.** 60 a day, 30 in one conversation, one in flight in a conversation at a time - its own pace, not
core's fifteen minutes and five a day. **Measurements M7, MC1 and MC2.** MC1 (a message shows as your own and
starts a turn) passed on `codex-cli 0.162.0-alpha.17.2`; MC2 (where a turn's progress is read) found that the
history says first that a turn started and ended but shows no wait for an approval, so the chat says only "in
progress" - recorded as a fail, which is the warning its statement carries on every Codex; on any other
version MC1 is unmeasured too.

### Recover every conversation but Codex's own

**What it does.** Takes up a failed turn in every conversation of the Codex app except the ones Codex makes
for itself: subagents (Tell a parent which of its subagents stopped handles those), reviews
(`guardian_review`), memory passes (`memory_consolidation`) and conversations an agent created
(`agent_created_thread`) - except a failed turn in one of those that the person started from the input box,
which is theirs and is taken up in both editions, whatever this switch says (a turn Codex queued, a goal's
turn, or one whose start Codex did not record is not). A conversation with a label Codex adds later is taken
up too, instead of left alone. Archived conversations, those of another Codex home, and those of a terminal or VS Code are still
never taken up.

**When it helps.** When a conversation of yours carries a label the standard edition does not know, so its
failures are left alone.

**What it risks.** A conversation Codex uses for itself under a new label could be continued, which may cost
usage or add a message where none was wanted. Every recovery gate still applies: the conversation must be
switched on and open in the app before anything is sent.

**Departs from** [A15](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (only the desktop app's own user
conversations are detected).

**Ceilings.** None of its own come into play: what it takes up is recovered under the standard limits.
It rests on no measurement.

### Usage meter

**What it does.** While the Codex app runs, reads your Codex usage on its own every 5 to 60 minutes, as you
choose or type in - 15 by default - and shows it in the icon's tooltip and the popup. When a window reaches
the percentage you set for a warning (85% by default, each window its own), it shows a notice, once for that
window. Each window - the five-hour and the weekly - can be switched off on its own (*Act on the five-hour
window*, *Act on the weekly window*): it is still read and shown, and no warning is shown for it. These two
switches decide only the warnings: Wrap up near a limit and Stop near a limit each have a pair of their own.
Every on/off choice on the page is a switch; every number on the page has *Custom...* beside its choices,
which opens a small dialog for a number of your own, as on the Settings page, checked before it is saved - a
whole percentage from 1 to 100, a spacing from 5 to 60 minutes - and for each window the warning stays at or
below the wrap-up, and the wrap-up below the stop its words ask for.
The reading is only shown: whether a recovery may go is still decided by the reading the program makes when
a recovery is due.

**When it helps.** When you want to see how close a limit is before it is reached.

**What it risks.** Each reading is one short request to Codex's own app server, as a recovery's is. A
reading that cannot be read is shown as nothing and warns of nothing.

**Departs from** [C4](STANDARDS.md#c-network) (nothing happens on its own, on a schedule) and
[C9](STANDARDS.md#c-network) (usage is read only when a recovery is due).

**Ceilings.** None come into play: it sends nothing. **Measurement MU: passed** on codex-cli
0.162.0-alpha.17.2 (2026-10-10).

### Wrap up near a limit

**What it does.** Needs the usage meter, which turns on with it. Its own switches, *Act on the five-hour
window* and *Act on the weekly window* (both on by default), say which windows it acts on - apart from the
meter's, which decide only the warnings; with both off it acts on neither, and the page says so. When a window
it may act on reaches the percentage you set (90% by default, each window its own), each conversation that is switched on and has a
turn running is sent one message, once for that window, in the wording you pick: the standard "Please finish
the current step, then stop.", the short "Please stop now.", the detailed "Commit what is pending, write down
where you are and what is left, then stop.", one with the numbers - "You have used 90% of the five-hour limit.
Get ready to stop safely, and stop when it reaches 95%." (the stop it asks for is its own number, apart from
Stop near a limit's) - or your own words for each window, which may hold {percent}, {window}, {stop_at} and
{reset} and are checked as a custom continuation message is. *Include the reset time* (on by default) adds
when that window resets. The page shows, under the choice, exactly what would be sent for each window, in
your continuation language. It goes through Codex's queue as every continuation does, so Codex delivers it
when the current turn ends. With *Continue after the reset* (on by default), a conversation that then ended
well is sent one continuation once the window resets - only if nothing newer happened there, and while the
app has it open.

**When it helps.** When you would rather a long turn stopped at a good place than ran into the limit.

**What it risks.** The message arrives only when the current turn ends, which may be after the limit is
reached: it cannot stop a turn midway - Stop near a limit can. A turn that ended before the message went
gets none. Your own words are sent as you wrote them, with only the numbers filled in.

**Departs from** [A13](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (only failures are recovered) and
[A26](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (words of its own).

**Ceilings.** 12 a day, and 2 in any one conversation - the five-hour and the weekly window's. **Measurement
MT: not made yet.**

### Stop near a limit

**What it does.** Needs the usage meter, which turns on with it. (Pause near a limit until v0.6.16-beta.4.)
Its own switches, *Act on the five-hour window* and *Act on the weekly window* (both on by default), say which
windows it acts on, as the wrap-up's do; with both off it acts on neither, and the page says so. A window
switched off in the meter's choices before this version is switched off here and in Wrap up near a limit too,
once, when the program first opens its state after the update - so nothing starts acting on a window you had
off. When a window it may act on reaches the stop percentage you set (97% by default, each window its own), each
conversation that is switched on and has a turn running is stopped, as the Stop button in the Codex app
stops one - through the app's own internal channel, the `\\.\pipe\codex-ipc` pipe, once for that window -
and the program sends no further continuation until that window resets: recoveries wait, and the advanced
edition's own continuations are held. A reset credit spent for that window - yours, or a rule's - lets the hold go,
since the credit empties the window; one Codex has not answered yet, one that reset nothing, and a credit for the
other window leave it. It works only for a conversation the Codex app has open; where it
cannot stop a turn - the app does not have the conversation open, is not running, or its build no longer
answers this request as measured - it only holds, and a notice says the turn could not be stopped. Codex
pauses a stopped conversation's queue, and that survives the app's restart, until the turn started after the
reset lets it go; with Continue after the reset off, a notice asks you to press Resume in Codex. When the window resets, a conversation it stopped is continued once (*Continue after the reset*, a
choice of Wrap up near a limit, on by default) by a turn started through the same channel - past the paused
queue - only if nothing newer happened there and the app has it open; otherwise it waits, and a notice says
to open it in Codex. Messages you queued yourself, and anything you type in Codex, are not touched. Each of
these three notices, and the meter's warning, is a kind of its own under *Keep on screen until clicked*
(Settings > General > Notifications), and a click on one opens the Dashboard.

**When it helps.** When you would rather a turn stopped before the limit than ran into it.

**What it risks.** A stopped turn may leave work half done; the wrap-up's words ask Codex to stop safely
first. The app's internal channel is not a documented interface: a new Codex app may change it, and then
nothing is stopped. Work may wait that could still have run in the usage left, and an old or wrong reading
may stop a turn or hold recoveries too early.

**Departs from** [A2](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (its continuation after the reset
is a turn started through the app's channel, not `codex queue`), [B3](STANDARDS.md#b-what-it-reads-and-how)
(Codex's state changed through that channel), [C9](STANDARDS.md#c-network) (it decides on the usage meter's
reading) and [H6](STANDARDS.md#h-user-control) (a running turn is stopped).

**Ceilings.** One stop and one continuation a conversation a window. **Measurement MIPC: passed** (codex-cli
0.162.0-alpha.17.2, app 26.1007.9446.0; again on 0.163.0-alpha.10.2, app 26.1013.3656.0, with the stop that
names its turn - f16c9ca2 on measure-20261017); **MU: passed** (codex-cli 0.162.0-alpha.17.2, 2026-10-10).

### Continue with no words

**What it does.** When a conversation is run here while Codex is closed, its continuation is started with no
words at all, so nothing extra appears in the conversation; the id it was started under proves its arrival.
It continues nothing by itself: it changes only how Run a conversation here while Codex is closed, or a
compacted conversation's continuation, starts its turn. Where Codex refuses a turn with no words, that turn
is started with the usual words instead, and this turns itself off. It yields where a continuation carries words
beyond the program's own template - another capability's words, or the message you wrote for this time: that
continuation goes with its marker, and your words are never taken or lost for it. Beside the continuation with no
marker, this serves the routes and that one the sends that carry words.

**When it helps.** When you would rather the program's sentence did not appear in a conversation.

**What it risks.** That Codex starts and ends a turn with no words was measured (M3B).
Where Codex refuses it, this stops answering for that version of Codex. Kept on, it stays on after such a refusal
and the page notes it; the next continuation still carries words.

**Departs from** [A4](STANDARDS.md#a-what-it-may-send-to-codex-and-when) (no marker: the turn is proven by
its id) and A26 (no words at all).

**Ceilings.** 24 a day, and 5 in any one conversation. **Measurement M3B: passed** on `codex-cli 0.163.0-alpha.10.2`; on any other version, a warning.

### Check for updates once a week

**What it does.** At most once a week, while no recovery is waiting, being sent or being watched, the
watcher runs the same check the Dashboard's **Check for updates** runs: the installed copy's own
`scripts/bootstrap.ps1 -CheckOnly`, with the same two-minute limit and no window. When it finds a newer
release - or a newer pre-release, where a check you start would offer one - it shows one notification,
*A newer version is available*, whose **Open Dashboard** button opens the Diagnostics page, where you
install it as always. It never downloads or installs anything itself. The notification is a kind of its own
in **Keep on screen until clicked**. While recovery is paused, or `DisableUpdateCheck` is set, no check is
made.

**When it helps.** When you would rather hear of a new version than remember to look.

**What it risks.** Each check makes the requests a check you start makes - to github.com, to GitHub's list
of this project's releases, and for the Codex compatibility data - so GitHub sees this PC's address and the
time, once a week. A check that fails, that GitHub refuses or that has not finished in time says nothing
and waits for the next week; the time of the last check is kept in the advanced state, so turning it off
and on again does not check sooner. A version it found is kept there too and shown again each time the
watcher starts, until that version is installed, a later check finds nothing newer, or you turn the feature
off.

**Departs from** [C4](STANDARDS.md#c-network) (nothing happens on its own, on a schedule),
[C5](STANDARDS.md#c-network) (the update check runs when a button is pressed) and
[C7](STANDARDS.md#c-network) (the compatibility data is refreshed only on request, never by the watcher).

**Ceilings.** None come into play: it sends nothing to Codex. It rests on no measurement.

### Compatibility report

**What it does.** Writes a compatibility report from this PC's own records, as codex-compat-reporter
does - counts, states and times for the version of Codex in use, with no conversation text, id or
path - and shows the whole file in the Dashboard, with its SHA-256. Watched, that is all: the file
can be read and saved wherever you choose. On, it also asks GitHub what sending would write, through
gh, the GitHub CLI you installed, signed in as you; it shows every write, and sends only after you
type `send`: it forks the project, adds the file on a branch and opens a public pull request.
Without gh, or with gh signed in as someone else, it shows the four steps to send it on the web. It
is an action: it answers at no point of a recovery, sends nothing to Codex and spends nothing, and a
report grants nothing - it counts towards the Reported grade beside its version of Codex and nothing
else ([G13](STANDARDS.md#g-the-compatibility-registrys-authority)).

**When it helps.** When you want to tell the project how recovery went with your Codex without a
second program. The standard edition sends nothing for a report; codex-compat-reporter, a separate
program, writes and sends the same report from the same records. Both editions' Dashboards also
write each version's part of it for every version of Codex on this PC, with one code, under
Diagnostics > Compatibility report from this PC... - shown and exported, never sent.

**What it risks.** The pull request, the fork and your GitHub login are public, and a pull request
cannot be unpublished; the report's times are published to the second. A send cut off part way -
the window closed, the network lost - can leave a fork or a branch behind: checking again shows what
is on GitHub, and sending again is safe. Whatever gh.exe is first in a full folder on PATH is trusted
to be the GitHub CLI. While recovery is paused nothing is checked or sent ([K5](STANDARDS.md#k-the-advanced-editions-own-rules)),
and one check or send runs at a time for an installation, whichever Dashboard window started it.

**Departs from** [B11](STANDARDS.md#b-what-it-reads-and-how) (gh reads your GitHub sign-in on the
product's behalf), [C1, C2, C3 and C8](STANDARDS.md#c-network) (network work by delegation, from a
second shipped file, to GitHub addresses beyond the two lists of releases, as your GitHub account
with gh's own User-Agent), [D1](STANDARDS.md#d-privacy-and-the-data-it-keeps) (the report's counts
go to the project), [E8](STANDARDS.md#e-failure-behaviour) (a gh that has not answered in two
minutes, or is still running when the Dashboard's service ends, is ended),
[F3 and F6](STANDARDS.md#f-footprint-on-the-machine) (the file saved where you choose; gh is not one
of the listed processes).

**Ceilings.** None of its own: it sends nothing to Codex. Each send needs its own typed `send` for
exactly the file and the writes shown, and the project takes one report per GitHub login for each
version of Codex.

**No measurement.** It rests on no route of Codex's, so nothing about your version of Codex is
measured for it, and a failing Codex - when a report matters most - never holds it back.

## Choosing an edition

- **Standard**, if you want every promise in [PRIVACY.md](PRIVACY.md) and [SECURITY.md](SECURITY.md)
  to hold in the code itself, not in a setting. It is what the plugin in Codex installs.
- **Advanced**, if you want one of the capabilities above and accept what its statement says. Until
  you turn one on or have one watched, it behaves as the standard edition.

Two editions installed side by side are not supported: one installation is one edition.

## Switching

Changing edition is a reinstall, never an update. Run the other edition's setup program, or its
archive's `Install.cmd`: the installer says which edition is installed, what the change keeps and
what it changes, and asks before it replaces anything: the setup program in its window, where *Change the
edition* has to be chosen before it will start, and `Install.cmd` with `Change the edition? [y/N]`, where
anything but yes changes nothing. With `-Silent` nobody can be asked, so nothing is changed and it ends with
exit code 14. From a command line, `scripts/bootstrap.ps1 -Edition Standard` or `-Edition
Advanced` chooses the edition, and over the other edition it needs `-Force` as well. The change keeps
your settings, your pause, everything waiting to resume and the sign-in choice, and every advanced
capability starts off (K2). An uninstall that keeps your data notes which edition it removed: the same
edition installed again afterwards is no change, and like an update it keeps what you turned on, what you
kept on and every choice; the advanced edition installed after the standard one was removed is a change,
and every advanced capability starts off. Codex's own copy of the plugin can stay the old edition's until Codex
lets it be replaced; the installer and the Dashboard's Diagnostics page say so while it is.

The Dashboard has a way too: **Install another version...** on the Diagnostics page lists every
version of both editions from v0.6.2 on (the advanced edition's from v0.6.11-alpha), and a row of
the other edition is a change of edition. Its confirmation says what the change means, as the
installer does - to the standard edition the advanced features go, and their code with them; to the
advanced edition every advanced feature starts off - and it passes the change to that version's own
installer only after the archive passed its checks. From the advanced edition, a standard version
before v0.6.11-alpha is greyed: its installer predates editions and cannot change one. The [guide](GUIDE.md#installing-another-version)
says what else it asks and keeps.

## Updates and pre-releases

An update stays in the edition you have. **Check for updates** fetches the installed edition's
archive, and an archive of the other edition is refused. Like every download, the archive is checked
against the digest pinned for that edition and version in the installed copy's `scripts/release.json`
where there is one, and otherwise against the `.sha256` published beside it, as the [guide](GUIDE.md)
explains. A pre-release never has a pinned digest, so it is checked against its published checksum;
finals are pinned for both editions from v0.6.11 on. A pre-release it offers is your edition's too, and is installed only if you
say yes (C5, I12, K2). *Install another version...* offers the pre-releases of either edition as it
offers releases, and installs one only after you confirm it; an older one, or one of the other
edition, takes `-Force`, which the confirmation passes (I12, amended by the owner on 2026-10-03).

## Verifying

Each release publishes four files to install from - each edition's archive and setup program - each
with its `.sha256` beside it, and one build attestation names all four. `scripts/release.json` keeps
a table of pinned digests for each edition; the advanced edition's starts with v0.6.11.
[VERIFY.md](VERIFY.md) says how to check them, and how to rebuild either edition yourself.

## What comes next

v0.6.12 added two things people asked for. One is a way to install another version or edition from
the Dashboard - any release or pre-release of either edition - which says first what the change
means, as the installer does when you switch (a change of edition turns every advanced capability
off), and checks what it downloads as every install does. It was planned for v0.6.11 and not
finished in time; it was built for v0.6.12 and is described [above](#switching). The
other is a power action - sleep, hibernate or shut down - once every recovery waiting for a usage
limit to reset has ended. It keeps every standard (H14 and F15 in [STANDARDS.md](STANDARDS.md), with
A28 amended by the owner for its stop button), so it is in the standard edition, off until a person
turns it on in the Dashboard.

Then, after v0.6.13's fix of how Codex's engine is found, v0.6.14 brought the first part of the rest
of the advanced edition: the six capabilities [above](#todays-capabilities) that follow the goal
continuation, and with them Once more when unsure, Send now, Keep it on, the compatibility report
and the three for a usage reset you pick. It was to be the first of several pre-releases and was
published as a final instead (owner, 2026-10-10). v0.6.15 was a fix alone (owner, 2026-10-13), so the
rest went to v0.6.16, which came in four pre-releases and is out: its first, v0.6.16-beta, built the
six capabilities of stage 3c, and the next three a route of its own, other kinds of session and the
usage capabilities. v0.6.18 then took two small capabilities of stage 5, Open Codex on a notice and the weekly
update check, and published them as a final (owner, 2026-10-21). v0.6.19 then came in four pre-releases and is out (owner, 2026-10-26): its first, v0.6.19-beta, carried the chat inside the Dashboard, the restart of the watcher and the wake for a reset, and the others the rest of what it built. What is left of stage 5 is v0.6.20 (owner, 2026-10-26), which publishes each part as a pre-release as it is finished. Each new capability is the advanced edition's alone, off until you
turn it on, with a statement that names the standards it departs from. This is a direction, not a
promise; [ROADMAP.md](ROADMAP.md) has the whole list: the two additions in its v0.6.12 section, what
is built in its v0.6.14, v0.6.16, v0.6.18 and v0.6.19 sections, and the rest in its v0.6.20 section, under the same
headings as the last four bullets below.

- **Recovery through the channels already in use** - several conversations at once,
  empty-response recovery, an unloaded conversation through a queue that waits for it, a subagent
  through its parent, keep going after a normal completion, and a prompt queue and recurring
  wakes - all six built in v0.6.16's first pre-release, v0.6.16-beta (published first as v0.6.15-beta), and described
  [above](#todays-capabilities).
- **A route of its own, and other kinds of session** - a conversation nothing holds, run through
  Codex's app server; CLI, TUI and IDE sessions; a full context compacted, then continued; another
  model at capacity; a continuation with no words - all built in v0.6.16-beta.4, described
  [above](#todays-capabilities); and a continuation inside the turn through a Codex Stop hook, planned for
  v0.6.20. (Codex's own retry settings are offered only once a measurement passes.)
- **Around recovery** - usage analytics (the live usage meter and the wrap-up near a limit are built,
  described [above](#todays-capabilities)); a provider status feed and push notifications through one courier process, the advanced edition's only
  outbound network code; a local API and web view, remote control over Telegram and a read-only view
  of other PCs; switching the Codex account on your command. *Open Codex* on a notice and a weekly update check while idle are
  built in v0.6.18, and crash supervision and a wake timer for a reset in v0.6.19-beta, described
  [above](#todays-capabilities).
- **The chat inside the Dashboard** - chatting with a Codex conversation inside the Dashboard, reading it and
  sending it a message: advanced only, off by default, on this PC only and never through a remote channel, with
  "in progress" while a turn runs and the result once it ends, and approvals still answered in Codex. Built in
  v0.6.19-beta, described [above](#todays-capabilities).
- **Compatibility data for the advanced edition** - verdicts for each Codex engine in a file of its own, which
  installed advanced editions fetch, and the compatibility reporter counting the advanced edition's outcomes as
  "reported" without ever raising a verdict.
- **Also moved here** - a continuation inside the turn through a Codex Stop hook, and Arabic and Hebrew. Watching
  several Codex homes, which the standard edition gains, was built in v0.6.16-beta, and the winget manifests for both
  editions in v0.6.16 ([WINGET.md](WINGET.md)).
