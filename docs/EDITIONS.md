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
minutes apart (A20).

**Warnings, not refusals.** A measurement a capability rests on that failed, or was never made for
your version of Codex, a compatibility grade of Failed here, Incompatible or Unknown, or a Codex
version not known yet is shown in its statement as a warning. It does not stop you turning the
capability on; turning it on confirms you read it (K6).

**Tripwires.** A capability turns itself off when its statement gets a new revision; when a warning
you did not confirm says that what it stands on went wrong; when one of its parts fails; when a send
it made becomes one whose delivery cannot be proven; and, while it is on, when Codex is updated. The
page says so under the capability's state, and why. You can turn it on again, with its statement as
it then reads (K7).

**Your administrator's policy.** Three values under `Software\Policies\CodexAutoResume`, in
`HKEY_LOCAL_MACHINE` or `HKEY_CURRENT_USER`, read and never written: `ForbidAdvanced` (nothing may be
on or watched), `AllowedCapabilities` (only the ids listed may be) and `ForceShadow` (watched, never
on). Both places count, together they are the stricter, and a value that cannot be read counts as
the strictest. The page says when one of them applies. Like the standard edition's policy keys,
they are what a cooperating installation obeys, not a lock (K6).

What the advanced edition keeps is its own: which capability is on, what each has spent and what it
did are kept in `config/advanced/advanced.sqlite`, in fixed words, ids and numbers, and nothing of
it is written into the standard edition's state. It adds no network code. Its archive also carries
the harness the project uses to measure whether a capability's route works on a given version of
Codex; nothing runs it unless a person asks, and [SECURITY.md](SECURITY.md) says what it does.

## Today's capabilities

Three. Each measurement named below was made once, by hand, on the owner's machine, on
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

v0.6.12 first adds two things people asked for. One is a way to install another version or
edition from the Dashboard - any release of either edition, and the pre-release the update check
would offer - which says first what the change means, as the installer does when you switch (a
change of edition turns every advanced capability off), and checks what it downloads as every
install does. It was planned for v0.6.11 and not finished in time; it is built for v0.6.12-beta
and described [above](#switching). The other is a power action - sleep, hibernate or shut down - once every recovery waiting for a usage
limit to reset has ended; which edition it belongs in is decided against the standards when it is
designed.

Then v0.6.12 brings the rest of the advanced edition, each part published as a pre-release as it is
finished. Each new capability is the advanced edition's alone, off until you turn it on, with a
statement that names the standards it departs from. This is a direction, not a promise;
[ROADMAP.md](ROADMAP.md) has the whole list in its v0.6.12 section: the two additions first, then
the rest under the same four headings as below, and one more on compatibility reports from others.

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
