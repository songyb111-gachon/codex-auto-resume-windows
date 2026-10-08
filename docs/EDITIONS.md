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
starts off, and installing the edition, or switching to it, turns every one off. The Dashboard has
one more page in this edition, **Advanced features**, the last tab after Settings. Choose a
capability there and read its statement: what it does, what the standard edition does instead,
which standards it departs from, what can go wrong and how to stop it, and any warnings it carries
now. **Turn on** asks once more, with the statement and every warning in front of you; saying yes
confirms them, for the version of Codex shown. **Watch first** instead has it asked wherever it
would act, and note what it would have done, while it does nothing. If anything changed while you
were reading, the page reads it again and asks again with what holds now (K3); where it cannot read
it again, or your administrator's policy now refuses it, it says that nothing was turned on, and why.
The page reads the list again after everything you do there, and whenever the watcher says a
capability was turned on or off, here or anywhere else.

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
together, 12 sends an hour, which you can lower on the page, as far as one an hour, and never raise
past 12. The page shows a capability's own ceilings beside its statement. Every send also counts
against the standard edition's own limits for the conversation: five in any 24 hours, at least 15
minutes apart (A20) - except where a capability says it departs from A20: a send of the short retries
when Codex is at capacity counts against the program's own capacity limits instead, 48 a day, a minute
apart, and Send now skips the 15 minutes for the one recovery you choose, still within the five a day.

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

**Keep it on.** On the page, a capability that is on or watched can be kept on, after its own warning.
Kept on, it does not turn itself off for any of the tripwires above, nor for a new version of Codex:
the page notes the most serious of them under its state until you turn it on again; a part of it that
fails skips only that one recovery; and a send it made whose delivery cannot be proven is held, as the
standard edition holds one. A Codex version or a compatibility grade that cannot be read still holds
it back, its ceilings stay, and turning it off - here, from Codex or with every advanced feature at
once - always works and lets it turn itself off again. With it you can also choose *Also send again
when unsure*, after a warning of its own: such a send is then sent once more under the rules of Once
more when unsure below, so the capability departs from what that one departs from too, and only where
your administrator's policy allows Once more when unsure as well; a continuation sent again and found
twice turns that choice off, and the capability stays on. The compatibility report sends nothing to
Codex, so it has no such choice. The policy reads a kept-on capability down
as any other, by the capability's own id: no policy value reaches Keep it on alone (K8).

**Your administrator's policy.** Three values under `Software\Policies\CodexAutoResume`, in
`HKEY_LOCAL_MACHINE` or `HKEY_CURRENT_USER`, read and never written: `ForbidAdvanced` (nothing may be
on or watched), `AllowedCapabilities` (only the ids listed may be) and `ForceShadow` (watched, never
on). Both places count, together they are the stricter, and a value that cannot be read counts as
the strictest. The page says when one of them applies. Like the standard edition's policy keys,
they are what a cooperating installation obeys, not a lock (K6).

What the advanced edition keeps is its own: which capability is on, what each has spent and what it
did, the choices you made for a capability, the rules you wrote, which capability took up which
interruption and the samples of failures it could not classify are kept in
`config/advanced/advanced.sqlite`, in fixed words, ids, numbers and Codex's own error codes - never a
word of an error or a conversation - and nothing of it is written into the standard edition's state. It adds no network code; one capability,
the compatibility report, asks gh - the GitHub CLI you installed - to reach GitHub, and only when
you start it in the Dashboard (below). Its archive also carries
the harness the project uses to measure whether a capability's route works on a given version of
Codex; nothing runs it unless a person asks, and [SECURITY.md](SECURITY.md) says what it does.

## Today's capabilities

Twelve: eleven that change how a recovery is made, and the compatibility report, which only you
start. The first three rest on a measurement each, the other nine on none. Each measurement named below was made once, by hand, on the owner's machine, on
`codex-cli 0.158.0-alpha.2.1`; its record is in [`docs/evidence/live/`](evidence/live/). On any
other version of Codex a capability's statement carries the warning that it was not measured there.

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

### Marker-free continuation

**What it does.** Sends each continuation without the marker the standard edition ends it with. The
message is added to the conversation's queue through Codex's own app server (`thread/queue/add`),
under an id made from the interruption, and that id, which Codex keeps on the message, is what proves
it arrived. Past its ceilings, a continuation goes with the marker, as in the standard edition.

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
the words `/compact` as plain text rather than running them as a command.

### Goal continuation

**What it does.** For a usage limit only. When the limit paused a conversation's Codex goal and the
conversation is due to continue while the Codex app does not have it open, it sets that existing
goal active again through Codex's own app server (`thread/goal/set`), so that Codex carries the goal
on when the app next opens the conversation. It never creates a goal and never reads or changes what
the goal says. While the app has the conversation open, the continuation goes through Codex's queue
as in the standard edition; setting the goal active first there waits for measurement M2b to pass
for your version of Codex, which has not been made yet. While a goal it set active carries the
conversation on, the standard continuation waits, for up to ten minutes, so the two do not both run.

**When it helps.** When a usage limit stopped work under a goal and you do not keep that
conversation open: in the standard edition the goal stays paused until you resume it yourself.

**What it risks.** Measurement M2 found that a goal set active this way is not taken up while the app
has the conversation open, which is why it acts only where the app does not. In the same measurement
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
M2b, which would let it act while the app holds the conversation, has not been made.

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
A22 (waits come only from the retry timing you chose) and [B9](STANDARDS.md#b-what-it-reads-and-how)
(only a failure's kind is kept: this also reads Codex's own error code, never its words).

**Ceilings.** 48 a day, and 48 in any one conversation - the one capability whose conversation
ceiling is above the standard edition's five, because it departs from A20.

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
retried), A26 (continuation text only for a kind that is recovered) and B9.

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

**Departs from** 0.5, A13, A14, A26, B9 and [D2](STANDARDS.md#d-privacy-and-the-data-it-keeps)
(state holds only the program's own fixed words, never a code Codex chose).

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
never sends anything to start a usage window or keep one open.

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
is used up - never one your administrator set. Every other check still runs. A request not used within
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
program, writes and sends the same report from the same records.

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
what it changes, and asks before it replaces anything (`Change the edition? [y/N]`; anything but yes
changes nothing). From a command line, `scripts/bootstrap.ps1 -Edition Standard` or `-Edition
Advanced` chooses the edition, and over the other edition it needs `-Force` as well. The change keeps
your settings, your pause, everything waiting to resume and the sign-in choice, and every advanced
capability starts off (K2). Codex's own copy of the plugin can stay the old edition's until Codex
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

v0.6.12 adds two things people asked for. One is a way to install another version or edition from
the Dashboard - any release or pre-release of either edition - which says first what the change
means, as the installer does when you switch (a change of edition turns every advanced capability
off), and checks what it downloads as every install does. It was planned for v0.6.11 and not
finished in time; it is built for v0.6.12 and described [above](#switching). The
other is a power action - sleep, hibernate or shut down - once every recovery waiting for a usage
limit to reset has ended. It keeps every standard (H14 and F15 in [STANDARDS.md](STANDARDS.md), with
A28 amended by the owner for its stop button), so it is in the standard edition, off until a person
turns it on in the Dashboard.

Then, after v0.6.13's fix of how Codex's engine is found, v0.6.14 brings the rest of the advanced
edition, each part published as a pre-release as it is finished. Its first part, from v0.6.14-beta
on, is the six capabilities [above](#todays-capabilities) that follow the goal continuation, and with
them Once more when unsure, Send now and Keep it on, in the same beta. Each new capability is the
advanced edition's alone, off until you turn it on, with a
statement that names the standards it departs from. This is a direction, not a promise;
[ROADMAP.md](ROADMAP.md) has the whole list: the two additions in its v0.6.12 section, and the rest
in its v0.6.14 section, under the same four headings as below and one more on compatibility reports
from others.

- **Recovery through the channels already in use** - short retries for capacity errors, failures it
  cannot name on a budget of their own, rules over Codex's own error tags, a request Codex gave up
  on, a sign-in failure retried once after proof, an early usage reset, one resend when delivery is
  uncertain and the message is nowhere, *Send now*, several conversations at once, empty-response
  recovery, an unloaded conversation through a queue that waits for it, a subagent through its
  parent, keep going after a normal completion, a prompt queue and recurring wakes, and a
  compatibility report sent from the app.
- **A route of its own, and other kinds of session** - a conversation nothing holds, run through
  Codex's app server; CLI, TUI and IDE sessions; a full context compacted, then continued; another
  model at capacity; a continuation with no words; a continuation inside the turn through a Codex
  Stop hook; and Codex's own retry settings.
- **Around recovery** - a live usage meter, a wrap-up nudge near a limit, reset credits and usage
  analytics; a provider status feed and push notifications through one courier process, the
  advanced edition's only outbound network code; a local API and web view, remote control over
  Telegram and a read-only view of other PCs; switching the Codex account on your command; a weekly
  update check while idle; crash supervision, a wake timer for a reset and *Open Codex* on the card.
- **Also moved here** - watching several Codex homes, which the standard edition gains; Arabic and
  Hebrew; winget manifests for both editions.
