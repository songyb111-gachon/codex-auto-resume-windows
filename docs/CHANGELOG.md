# Changelog

## Unreleased — Reports filed with no step by the maintainer

**Not in a release yet.** This is the repository's own machinery, working from the day it is on
`main`; what the next release carries of it is the counts file's new comment, and this entry moves
into that release's when it is opened.

- **A compatibility report that passes is filed with no step by the maintainer.**
  `.github/workflows/community-file.yml` wakes when a report's check finishes, and once a day. It
  judges each open report pull request again, against `main` as it is by then, and files this
  project's own regeneration of the report - never the sender's bytes - in one commit that adds
  exactly that report and writes the index, the folder's README and the counts again. The pull
  request is closed, not merged, with one comment saying where the report went, or why it waits,
  or what to do about a refusal. A report used to wait for the maintainer to run their tool.
- **What the maintainer judged is written down as rules**, counted from `main`'s own history and
  keyed by numeric account id: accounts at least 30 days old, one open report per account, at most
  3 filings per account and 5 per Codex version in any 7 days, a budget of Codex versions the
  project's data does not name, half the counts file's room kept free, and a failure on a version
  this project verifies held for the maintainer. A report that meets a limit waits, with the date
  it is looked at again. The repository variable `COMMUNITY_AUTOFILE` pauses filing on anything but
  unset or `on`, `COMMUNITY_BLOCKED` refuses an account, and a withdrawn report's account is listed
  in `docs/evidence/community/withdrawn.json` so it is not filed again.
- **Nothing a stranger sends can reach the write access.** The job that reads their files holds no
  write access and no token while Python runs; the job that writes starts on a fresh runner, runs
  no Python and no repository code, re-derives every commit from git, and moves `main` only
  forward, only from the commit the plan was made on and only onto the tree that was tested - hash
  for hash. [SECURITY.md](SECURITY.md) has the whole list.
- **Two holes the review found are closed for good.** A login Windows keeps for a device (`nul`,
  `con`, `com1`...) is refused as a report's folder: one such file on `main` would have stopped
  every Windows checkout of it. And a Codex version has one spelling: `0.1.0`, `00.1.0` and
  `0.01.0` are one engine to the product, and a report now has to write it the product's way.
- The folder's README is written by `build/community_report.py` from the index, and
  `tests/test_reported_data.py` holds it to that; the maintainer's tool imports that code from
  `main` instead of keeping a copy of its own, which had drifted.

## v0.6.10 — The design settled, and what others report

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.10-alpha...v0.6.10)

### The repository's front page, in one language

- `main` - the front page, the plugin's install route, where releases are tagged - is English only.
  `dev` keeps every document in English and Korean, written and reviewed together, and a
  promotion (`scripts/promote.py`) brings dev to main without the Korean files; the generated `ko`
  branch is built from main's code and the Korean sources of the dev commit it came from.
- The front page lists sixteen entries: `CHANGELOG`, `PRIVACY` and `CONTRIBUTORS` are in `docs/`,
  the installer's source in `build/install/`, and the MCP declaration's in `build/plugin-mcp.json`.
  In the release archive the installer and the MCP declaration stand where they stood, so no
  published bootstrap sees a difference. The archive carries `CHANGELOG`, `PRIVACY` and
  `CONTRIBUTORS` in `docs/`, where its README links them, and, built on English-only `main`, no
  longer the Korean `README`, `SECURITY` and `CONTRIBUTORS`.
- A section-by-section review of all sixteen document pairs found 62 places where the English and
  the Korean said different things; each is fixed in the language that was wrong, and the Korean
  guide now has every section the English one has.

### The design settled

The look was audited as one product, with the Codex panel as the reference, from light and dark
contact sheets of all four surfaces side by side. What people know stays. Each header keeps its
composition, its words and its places: the popup is titled *Codex Auto Resume* over its state, written
in the state's colour; the Dashboard's light spans its headline and the line under it; and every light
stands where it stood beside its words. The popup's and the card's buttons and chips stay bold, and the
Pending page's check results still read *OK*, *Waiting*, *Blocked* and *Unknown*. What changed:

- **One rule for a header's light.** The Dashboard, the popup and the panel light the same moment the
  same way, and the popup and the panel say the same word beside it, by one rule written down as 40
  test vectors that each surface's own code is run against. A watcher that is not running, or not
  known to be, is a grey light that does not move - the popup used to breathe amber for a stopped
  watcher - and a record held for a watcher that has stopped counts as one; a watcher that runs but is
  not well is amber and breathing. The notification-area icon and the taskbar button keep their own
  rule, in which a failure nobody has seen yet is red.
- **Never "recovery is on" for a watcher that is not well.** Where the watcher runs but has stopped
  responding, an older watcher still owns the state, or the Codex version is not supported or failed
  its checks here, the Dashboard's line under its headline and the panel's facts name that cause -
  *Watcher not responding* is new - where they said *Automatic recovery is on*. The Dashboard keeps its
  own words around it: *Watching for interruptions* over *… · 2 recoveries pending*.
- **A state nobody confirmed is not called fine.** The popup read a status it could not read, or one
  that did not say the watcher runs, as *Monitoring* or *Waiting*; it says *Needs your attention*
  now, beside the grey light. The panel asks for attention, ranked above a pause, for a watcher that
  runs but is not well, where it said *Monitoring*, *Waiting*, *Recovering* or *Paused*, and both it
  and the popup do for an older watcher still owning the state. Where the status did not say whether
  recovery is on, the popup took it as on; it says *Paused* now, and its button offers to resume. And
  it says *Recovering* when the status counts records in Codex, not only when its list shows one.
- **Every light that says the product is running moves.** The panel's Automatic recovery tile carries
  the state's light at a smaller size, where a dot that never moved used to be, and it breathes with the
  one above it, on one cycle that a redraw no longer sends back to the top. The panel's light dims
  toward the ground it stands on, so its glow is no longer a fifth weaker than the Dashboard's halfway
  down a breath. While the panel is open, a clock of its own turns it to *Checking*, with its turning
  arc, when a waiting task's time comes, and that task's row to *due now*; since the panel reads its
  records once and never sees the watcher's next pass, it says so for one pass and then *Waiting*
  again.
- **One button size, one chip size, one callout.** Buttons are 34 px high on every surface, where the
  popup's and the card's were 32 px, and chips have one height and one padding; the popup's and the
  card's keep their bold words. The Diagnostics page's compatibility notices are the panel's callouts,
  where they were a block of accent-coloured text.
- **One name for the window.** The window is the Dashboard wherever it is named - the icon's menu
  says *Open Dashboard*, as the popup and the card do - the popup's switch is *Auto-resume*, as the
  Pending page's column is, and its rows count down to the *Next check*, in all nine languages. The
  Settings help that the panel shows as well says *the Dashboard* where it said *this window* and
  *here*, which in the panel meant the panel, and Reduce motion's help names everything it stops, the
  panel in Codex included.
- **The card's light costs less.** It is drawn as the popup draws its own, only the band of rows it
  stands in, at about twice the frames for between a quarter and a third of the processor time.
  Hovering over it no longer sends its breath back to the top, and it rises in, comes back from a fade
  and slides on the popup's own easing curve.

### Four designs

- **Design**, under Settings > Appearance in the Dashboard, draws the Dashboard, the popup, the
  notification card and the panel in Codex one of four ways, each in light or dark as the Theme says:
  *Soft*, the default and everything above; *Soft, without motion*, the same look held still - what
  Reduce motion draws, chosen as a look; *Classic (v0.6.2)*, v0.6.2's flat cards with a hairline and a
  3 px accent bar down their left edge, its colours read from that release's tag, the current tab
  underlined, and the light breathing with its glow; and *Plain*, flat and neutral grey with the
  product's accent, whose light dims with no glow. Classic and Plain move as Soft does - switches
  glide and the notification card rises in; only *Soft, without motion* takes motion away. [BRAND.md](BRAND.md#four-designs) sets them out and
  the [guide](GUIDE.md) shows the popup in each.
- **A design changes paint, never layout.** Sizes, paddings, the light and the room kept for shadows
  are the same in all four, and corners are only ever smaller than Soft's; the Dashboard's layout
  audit finds every control where Soft's is in every design. The Pending and History lists stay flat
  rows in each.
- **No design can loosen a stopper.** High Contrast replaces every design, and Reduce motion, Windows'
  animation setting and every other reason something holds still hold it in every design: a design
  can take motion away, never add it. The notification-area icon holds still within a second of
  *Soft, without motion* being saved, as it does for Reduce motion, and the panel now follows the
  product's own Reduce motion as well as Codex's reduced-motion preference.
- **Set in the Dashboard only.** Like Reduce motion, the Design decides what moves, so Codex cannot
  change it: `update_settings` neither offers nor accepts it, and the panel draws in it and never sends
  it. `restore_default_settings` puts it back to Soft. An upgrade changes nothing anyone can see: a
  settings file without it reads as Soft. It is in all nine languages; in German it is *Stil*, since
  *Design* is German's word for the Theme.
- **On the wire.** Every reply that carries the settings carries `design`, and the wire goldens were
  regenerated on purpose for it. The tool list did not change.
- **Kept in step from one table.** What a design draws in the Dashboard - its colours and check box
  in each theme, its depth, glow, motion and corners - is generated from the same design table and
  colours the panel and the popup read (`Brand.LookOf` in `gui/Brand.cs`), where the Dashboard's own
  code chose them in ten branches by the design's name; a test now fails if any of its own code names
  a design. It draws exactly what it drew.

### The pictures

- **One set of records, one moment.** The panel, the popup, the card and the Dashboard are pictured
  from one set of records at one set of offsets, so a countdown, a chip and a count say the same on
  all four; until now the panel's rows both said *due now* and the popup had a row the others did not.
- **The same window, the same picture.** The Dashboard is photographed with Windows' keyboard cues
  hidden, as it looks to a person using the mouse. A new window takes the focus ring's state from how
  the last input reached the machine, so the Settings picture had a ring round the Overview tab in some
  releases and none in others, with nothing in the source changed.
- **Every light that moves, moving.** A picture's status lights move as the product moves them: the
  popup and the card frame by frame by their own renderers, and the panel's two lights and the
  Dashboard's drawn over the capture, each on the ground it stands on, for exactly one cycle - a
  4.4-second breath takes 4.4 seconds, where it took 4.356. Until now one light a picture moved, and
  in the panel's pictures not the one that moves in the product.
- **Each design, pictured.** The Dashboard's Overview, the panel, the popup and the card in Soft,
  without motion, Classic and Plain, in English and the light theme, beside Soft's own pictures.
- **Before and after, light and dark.** `build/make_screenshots.py --audit` draws, for developers,
  light and dark contact sheets of the four surfaces, and a before-and-after sheet of each, without
  touching anything published.

### What others report

- **Reported, beside the version.** The Dashboard's Diagnostics page says, in one muted line
  directly under *Codex version*, what other people report about that exact version: *Reported by
  others: worked 3 · failed 1 · neither 1*, with *counted in both* when a report saw both and *none
  yet* when nobody has filed one. It is a grade of its own beside Verified, Checked, Compatible and
  Failed here, and never one of them: no chip, never the success or danger colour, and a version
  whose own evidence says nothing stays Compatible however many reports say it works. `doctor` and
  `compat` print the same counts. The Codex panel points to the row, because the summary a model
  reads stays codes only, and the popup, the notification card and the icon never show it.
- **Counts of reports, not machines.** One report per GitHub login per Codex version. A report
  counts as worked when a record it delivered ended recovered, as failed when one ended in a failed
  recovery, as neither when none ended either way - a report that delivered nothing included - and
  in both columns when its records say both, so worked + failed - both + neither = reports. Only
  filed reports count.
- **Shipped with the release, never fetched, and deciding nothing.** The counts are
  `src/codex_auto_resume/data/reported.json`, a file of their own beside the compatibility data and
  never inside it, read by a hardened reader of their own. No request fetches it: the refresh a
  person asks for still fetches the compatibility data alone, so a report filed later waits for the
  next release. Only the view a person reads imports it, and a test grid holds that no counts - a
  thousand reports that worked, a thousand that failed, a broken file - move any state, permit or
  anything the watcher writes. No compatibility claim may cite someone else's report.
- **A report arrives as a pull request, and is read as data.** `build/community_report.py` is the
  one reader of a report: capped, exact about its keys, its times and its fingerprint - the setup
  that measured it - and recomputing the levels and verdict it claims, which can only go down.
  `.github/workflows/community-report.yml` judges a report's pull request with `main`'s own check,
  under a read-only token, reading the head with git plumbing only: one new file at
  `docs/evidence/community/<login>/codex-cli-<version>.json`, add-only, at most 1 MB, and not a
  copy of a filed report. Tests hold the filed reports, their index and the shipped counts to each
  other. [CONTRIBUTING.md](CONTRIBUTING.md#sending-a-compatibility-report) says how to send one.
- **On the wire.** The bridge's `compatibility` and `compat-refresh` views carry `reported` - its
  state and five counts, every key always there - and `control/wire.py` names it
  (`CompatReported`). The MCP replies do not change.

### Two claims corrected

- **A check box that could never do anything is gone.** *Sign-in service failures*
  (`auth_service_transient`) sat under Automatic recovery from v0.6.3, with a Custom message and a
  place in the Preview, for a kind of interruption nothing produced: no error code, HTTP status or
  message Codex records was ever classified as it. v0.6.3's entry below and the guide said it had been
  recovered through v0.6.2 with no way to turn it off; it never was. The check box, its Custom message,
  its place in the Preview and its switch in `update_settings` are gone from the Dashboard, the panel
  and the MCP schema. The word stays, so a record that names it still reads, and a settings file that
  carries `recover_auth_service_transient` or its Custom message loads as before, the two keys dropped;
  a write that names either is refused. A test now fails if a kind nothing produces is made
  recoverable again, and this one comes back only when a real Codex error is seen to carry it. On the
  wire, every reply that carries the settings or their schema has the two fields fewer, the Preview's
  kinds one fewer, and the two continuation sentences for it left the nine catalogs; the wire goldens
  were regenerated on purpose.
- **Start watcher, asked from Codex, says how long the watcher will run.** A watcher started with
  the panel's Start watcher or the `start_watcher` tool runs in the job Codex runs this plugin's
  server in, and Codex 26.915 ends everything in that job when it ends the server - measured for
  v0.6.9-alpha. The reply said *The watcher is running.* as though it would stay. Now, where the job
  ends what it holds, it adds that the watcher stops when Codex closes, if not sooner, and how to get
  one that outlives Codex: once Codex has closed, open Codex Auto Resume from the Start menu and start
  it there, or turn on Run at Windows sign-in in the Dashboard. (Not the Dashboard opened from that
  watcher's own icon: it runs inside Codex's job too, and while the watcher runs it has nothing to
  start.) Where Windows will not describe the job, it says the watcher may stop, with the same way
  out. The panel says the same in all nine languages, after a start that is running or not yet
  confirmed, and the tool's description says it too. The reply carries `ends_with_codex` - true,
  false or null, read from the job each time - whenever it started a watcher, and the MCP wire golden
  now holds a start in such a job and one in no job. The job is read by the one function the start
  with Codex refuses by.

## v0.6.10-alpha — Where every file goes when the core is Rust

[The commits in this pre-release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.9...v0.6.10-alpha)

**A pre-release, published from `main`.** It is a GitHub pre-release, so `releases/latest` never
answers with it and an installed copy's update check never offers it. It is on `main`, though, and
the plugin's own route installs what `main`'s manifest says, so an installation made that way gets
it - and behaves as v0.6.9 did. It is here because it is a stage the v0.6.10 work has to be split
into and is not a release on its own: nothing a person can see changes but the version it names. The window draws what it drew, the popup renders the same pixels, the panel serves the
same script, and every reply on the wire carries the same fields - `tests/golden/` holds each one
to the byte. To leave it, run `Install.cmd` from any later release's archive.

`docs/ROADMAP.md` says v0.6.13 replaces the Python core with Rust under one rule - **replace the
implementation, not the behavior** - and names the eight parts it is built from. That rule can only
be kept if each part's behaviour is in one place first: a file that does two parts' work is read
twice, ported twice and kept in step twice, and the second port is where behaviour quietly changes.
This release is that groundwork.

### The map

`tests/test_stack.py` places every module on exactly one of the eight Rust parts, on one of the
parts the Windows interface keeps, or on the few that are neither, and holds the placement four
ways, each of which only ever shrinks: parts with no package of their own, packages that hold two
parts, single modules that do two parts' work, and the graph of which part calls which. An entry
that stops being true fails the test, so the lists cannot go stale while the tree moves.
`tests/test_layers.py` has held the direction of every import since v0.6.5; this is the other
question - not which way a call points, but which binary the code ends up inside.

### The Python package, in the plan's layout

The layout the v0.6.5 plan drew is the tree now: `domain/ store/ codex/ compat/ win/ engine/
control/ mcp/ commands/ runtime/ ui/`. What moved in this release, each by line range and never
retyped, each old module kept as a front that re-exports every name it had:

- `windows.py` (989 lines, two parts at once) is the Codex adapter in `codex/` - `transport.py`,
  `appserver.py`, `pairing.py`, `usage.py` - and the Windows platform in `win/` - `kernel.py`,
  `sync.py`, `homelock.py`, `inventory.py`.
- `machine.py` is `domain/states.py`, `domain/gates.py` and `domain/public.py`: the stored states,
  the gates a record passes before anything is sent, and what a person is shown. Its docstring had
  always called them "three layers, kept apart on purpose".
- `app.py` is `runtime/`: the composition root, the watcher's loop, and the toasts it raises. The
  watcher has a package of its own for the first time.
- `cli.py` is the parser and the command table; the fifteen command bodies are `commands/`.
- `compat.py` and `compatio.py` are `compat/`, nine files: the registry's model, what a document
  says about a version, the report, what may be done at a tier, and the io half.
- `notice_window.py`, the notification card's window code, is `ui/card/`, beside the icon and the
  popup.
- Before this: `store/`, `engine/`, `control/`, `brand/`, `codex/`, `ui/popup/`, `ui/tray/` and
  `mcp/`, and the popup's, panel's and server's large files.

No module is over the 700-line budget now, down from ten, and none does two parts' work. And the
product has no import cycle left: the last one ran through the registry, and closed when the adapter began
reading the bundled registry from the file that holds it rather than through a front that loaded
all of it.

### The window, in nineteen files

`gui/Controls.cs` was 6,753 lines; `gui/SettingsApp.cs` and `gui/Dashboard.cs` were 4,150 and
4,353, holding one `partial class` in four declarations. They are nineteen sources now: the
Settings half, the Dashboard half, the soft controls both are drawn with, and the generated
palette. Every type and member moved as its own text; the compiler is handed the same code, and
the pictures are byte for byte what they were. `gui/window.sources` is the compile list and the only
place it is written, divided into `[settings]`, `[dashboard]`, `[controls]` and `[generated]`, and
every rule the suite holds the window's code to asks for a group rather than a file.

### The wire, as types

`control/wire.py` writes down the shapes the control layer hands every surface - a record, a row of
Pending or History, the watcher, the status, the statistics, the Compatibility card's view, a
setting as `describe` publishes it - as twelve typed contracts. `tests/test_wire_types.py` holds each
one to the golden replies both ways: every key on the wire is declared, every declared key is on the
wire, and every value fits its type. 144 fields the window reads are held to a declared key. These
are what a Rust port declares as structs, and they keep what a port would be tempted to lose:
"cannot tell" as its own value where a question can go unanswered, and not as false.

### Found while doing it

Splitting a module into a package fails in ways that say nothing at the time, and this release
built a test for each before moving anything - `tests/test_names.py`, `tests/test_reexports.py`,
`tests/guiscan.py` - and then an adversarial review of the result. What they found before any of
it reached anyone:

- A relative import inside a moved function means something else one package level down. In the
  Codex adapter it made the list of versions the bundled registry verifies silently empty; in the
  watcher's composition root it would have started the watcher without its notification-area icon.
  Every in-function import in moved code is now rewritten a level up, and `tests/test_names.py`
  fails on one that names a module that is not there.
- A test patch aimed at a front reaches nothing. Five tests had been checking the real thing instead
  of the stand-in they named - the installer's lock among them - and are aimed at the module that
  looks each name up.
- The release build would have failed copying the moved documents, and the picture generator's
  fake Codex reached no process.
- The wire goldens read the live compatibility data, so any data publish broke the suite; the first
  one since they were made did. They read the frozen copy now. (This one is also on `main`.)

### The repository's front page

`CONTRIBUTING`, `SECURITY` and `SUPPORT` moved to `docs/`, in both languages. GitHub reads all three
from there, so its security policy tab and the contributing link on a new issue are unchanged, and
the list of files above the README is thirteen instead of nineteen.

## v0.6.9 — The window stops making you wait, and a question answered by measuring

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.8...v0.6.9)

### The window is faster, and looks exactly the same

The window lagged, worst on some pages, and it was worse in every language but English. It was not
drawing too much - it was doing the same work again and again:

- The watcher's snapshot arrives every five seconds whether or not anything moved, and every time it
  did, both lists rewrote every cell, invalidated themselves and re-measured up to 200 rows across
  six columns - on pages nobody was looking at, because a snapshot is applied to every page that has
  been built. The thirteen safety checks on Pending were rebuilt the same way, each rebuild handing
  its card a full layout. Now each keeps a signature of what it drew, and identical rows and checks
  are nothing to do.
- Text was measured over and over: a label that wraps Korean never reached Windows' own measurement
  cache, so every layout pass measured it again, and the cache that holds a wrapped line was smaller
  than the Korean catalog, so it emptied itself in the middle of a page. Measurements are cached now,
  and the wrap cache is eight times larger.
- The countdowns were written into the Pending list every second whether or not that page was in
  front; they are written where they can be seen, and once when it comes back.
- Saving any setting - a theme, a limit - threw away the cache of the window's own words, so the next
  open waited on a fresh interpreter. Only the Interface language does that now.
- The shadow templates dropped all 128 of them on overflow and re-blurred everything; the oldest half
  goes instead. A visibility check on a dozen hot paths went through reflection on every call; it is
  bound once. A list drew two new brushes for every cell of every row, on every repaint; one brush
  per colour is kept.

Measured on the real compiled window, laying out every page and section, median of three runs:

| | before | after |
| --- | --- | --- |
| English, 100% | 5.6 s | 2.8 s |
| English, 150% | 6.4 s | 2.8 s |
| Korean, 100% | 17.3 s | 3.5 s |
| Korean, 150% | 13.3 s | 3.7 s |

Korean was three times English; it is about a fifth slower now. **Nothing about the design changed.**
Not a shadow, not a radius, not a light: the speed comes from doing the work once, not from drawing
less. The pictures in this repository are made again from the same window, and the suite reads their
pixels - the cards, the hairlines, the status light - as it always has.

### Starting with Codex: asked, built, measured, and not shipped

Starting the watcher when Codex starts - rather than only at Windows sign-in - was built for
v0.6.9-alpha and measured on a real machine, because two things about it cannot be read out of any
source. Codex 26.915 answered both: it starts a plugin's MCP server about 22 seconds after the app
opens, several times, and cancels each within seconds; and it runs each one inside a Windows job
object that ends everything that server started and forbids leaving it. Six starts were measured; six
watchers, each dead within about six seconds.

A watcher that is killed seconds after it starts, again and again, is the opposite of what this
product is - one stopped mid-tick cannot prove whether it sent a continuation. So the switch is not
offered. The code refuses where the job would end the watcher, and writes what the job said to
`logs\codex-start.log`, so the next Codex is one line away from being measured again. The advanced
edition (v0.6.11) is where starting a process outside the host's job belongs, for a person who turns
it on.

### The waiting light breathes, and the pictures show the right light

A light that says the watcher is waiting for a reset held lit and still, while the notification-area
icon - which draws that same state as watching - kept moving. It breathes now, on watching's rhythm,
in the Dashboard, the panel in Codex, the notification-area popup and the notification card. And the
animated pictures breathed the wrong dot: in the panel's they moved the small dot in the Automatic
recovery tile, which never moves in the product, while the status light at the top stayed still. The
generator takes the topmost light now, at any point of its breath, and the notification card's
picture breathes with the rest.

### Also here

- Codex ignores a plugin's suggested prompts entirely when there are more than three, and this one
  offered four, so none of them ever appeared. It offers three.
- The README is the short version - what it does, how to install it, the one limitation, where
  everything else is - and everything it used to hold is in [the guide](GUIDE.md).
- The roadmap gives the design audit and the choice of appearance a release of their own (v0.6.10's
  final), which moves the advanced features and the two editions to v0.6.11 and everything after it
  one number on.

## v0.6.9-alpha — Starting with Codex, measured

[The commits in this pre-release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.8...v0.6.9-alpha)

**A pre-release, and nothing is served it.** It is published from the `dev` branch as a GitHub
pre-release, so `releases/latest` never answers with it and no installation is offered it; the
plugin's own route installs what `main` says, which is still v0.6.8. It is here because two facts
about starting with Codex can only be measured on a machine running the real thing. To leave it,
run `Install.cmd` from any later release's archive.

### Start when Codex starts

The watcher has always started when you sign in to Windows. This adds the other choice: start it
when Codex starts. Codex starts this plugin's MCP server whenever it opens, so that server starts
the watcher when none is running - through the same launcher sign-in uses, only while the switch is
on and never while an installation holds its lock. Codex starts the server more than once as it
opens, so two of them can ask at the same moment; the watcher's own single-instance mutex answers
that, and the second one exits without doing anything. Nothing new is registered with Windows for
it: no scheduled task, no subscription, no process left resident to wait for Codex.
The switch is off until you turn it on, in the Dashboard under Settings > Windows; it is not offered
to Codex, so nothing a model does can turn it on.

Each time Codex starts the server, one line goes into `logs\codex-start.log`: what Windows wrapped
that process in, and what was decided. It carries no path, no name and nothing from a conversation.

### The waiting light breathes

A light that says the watcher is waiting for a reset held lit and still, while the notification-area
icon - which draws that same state as watching - kept moving. It breathes now, on watching's rhythm,
in the Dashboard, the panel in Codex, the notification-area popup and the notification card. Only the
word beside it tells waiting and watching apart, as the icon has always had it.

### The panel's picture shows the right light

The animated pictures of the panel breathed the small dot in the Automatic recovery tile - which does
not move in the product - and left the status light at the top still. The generator now animates the
topmost status light on each surface, which is the one the product moves.

### Also here

- Codex accepts at most three suggested prompts and ignores the lot when there are more; this plugin
  offered four, so none of them ever appeared. It offers three.
- The README is the short version, and everything it used to hold is in `docs/GUIDE.md`.

The archive's digest is in the release notes on GitHub; a pre-release is not pinned in
`scripts/release.json`, so the bootstrap checks it against the published `.sha256` beside it and
says so.

## v0.6.8 — A tray icon without its badge, and lights that never stop

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.7...v0.6.8)

Three things about lights, each asked for by name, and nothing about what recovery does.

### One icon, not two

The notification-area icon wore a small status dot in its bottom-right corner - cyan while a
recovery ran, amber for attention, grey when paused - that the settings window's taskbar button
never had. So during a recovery the tray showed a second light beside the mark's own moving head,
and the two icons looked as if they said different things. The dot is gone. The head of the mark
alone says the state, as it already did on the taskbar button, and the tray icon and the taskbar
button are the same picture, frame for frame. The states are still told apart by the head: its
colour, its breath and its sweep.

### Lights that never stop

Needing attention and a failure each pulsed once when they appeared and then held still. Now neither
stops for as long as it lasts, with the same curve and glow as every other light:

- **Needing attention** breathes slowly - every 5.6 seconds, slower than monitoring's 4.4 - in amber.
- **A failure** breathes quickly - every 1.2 seconds, quicker than a recovery's 2.8 - in red. On the
  tray icon and the taskbar button its head sweeps out along the ring and back as a recovery's does,
  twice as quickly - once every 1.98 seconds - and blinks as it goes, on that same 1.2-second breath:
  the one state whose head breathes while it travels.

The window, the notification-area popup, the panel in Codex, the notification card, the tray icon
and the taskbar button all take it from one table. Reduce motion, Windows' animation setting and High
Contrast still hold every light still.

### Red until you have seen it

Until now nothing ever put the tray icon or the taskbar button in the failed state: a failed
recovery was red on its notification card and in the lists' state chips, and never on either icon. Now a recovery that ends in a certain failure
turns both red, sweeping, and they stay red until you have seen it - click the icon to open the
popup, or bring the Dashboard to the front - or until a recovery is on its way afterwards (one that
is handed back before anything is sent does not count). Hovering over
the icon says *A recovery failed*, in all nine languages. When you last saw a failure is kept as one
time in `config/failure-seen.json`, which the watcher sets when it starts, so failures from before
this update never turn the icon red; PRIVACY.md lists what it holds.

### Also

- The README's picture of the icon's motion has a fifth column, the failed icon sweeping, and no
  badges.
- The roadmap: **v0.6.9** is the window's lag, on its own. **v0.6.10-alpha**, a pre-release, is the
  Python modularization and nothing else; the final **v0.6.10** is advanced features - as many as any
  program like this offers, and more: everything the product does today keeps today's constraints,
  and everything they made impossible is built, off until you turn it on - in an advanced edition
  released beside the standard one, which does not contain that code at all. **v0.6.11** is the bug
  hunt over both editions, the last Python release. **v0.6.12-alpha** replaces the core with Rust as it
  is, the final **v0.6.12** makes it Rust-native, and **v0.6.13** is the Rust bug hunt. A pre-release
  is only ever a stage the work has to be split into that is not a release on its own.

## v0.6.7 — Compatibility in tiers, Failed here, and a notification card that breathes

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.6...v0.6.7)

What the compatibility data can say grew by one word, what a failure can say grew by one more, and the
notification card's light now does what every other light does. Nothing about recovery changed: the
same classifier, the same gates, the same one watcher that is the only thing allowed to send.

### Verified, Checked, Compatible

Each capability, for the exact Codex version on this computer, is now one of six states rather than
four, in this order:

- **Verified** - a real recovery on this exact Codex version exercised the capability, and none failed it.
- **Checked** - new: the maintainer's local checks passed on this exact version, and nothing confirmed more.
- **Compatible** - the data says nothing about this version, and this computer's own checks pass.
- **Failed here**, **Incompatible** and **Unknown**, below.

The two rules are the ones v0.6.5 introduced. A failed local check always wins, and the data can only
restrict, or raise a local pass - now to Checked or to Verified - for an exact version. A Checked
capability needs a cited recording, as a Verified one does, and stops counting when a fetched copy
expires. It sends exactly as a Compatible or a Verified one does; only the advanced tier, which nothing
offers yet, still asks for Verified alone. The window's Diagnostics card, the panel in Codex, `status`,
`doctor` and the watcher's log say the new word in all nine languages, and the word the watcher's gate
reads for an engine can now be `checked`.

### Failed here

A local check that fails on a version the data checked or verified used to read as Incompatible, the
same word as a Codex version that does not work. It reads **Failed here** now: the data vouches for
that version, so the cause is most likely this computer - where Codex is installed, a file it is
missing - and not the Codex version. It holds every send and refuses every capability exactly as
Incompatible does, the watcher's engine state reads `failed_here`, the Diagnostics card shows the part
in the blocking tone, and a waiting interruption carries its own overlay, *Codex checks failed on this
computer*, which makes the popup and the notification-area icon ask for attention. A local failure on
a version nobody has checked, and a version the data marks incompatible, are still Incompatible.

### Older releases take the newer data

The data on `main` is fetched by every installation, whichever release it runs. v0.6.5 and v0.6.6 take
data carrying Checked claims whole: their validator passes over a state it does not know, so nothing
they decide moves, and a Verified claim reaches them as it always did. The suite now proves it with
their own code rather than by reading it: `OlderReleasesTests` loads each release's `compat.py` from
its tag and runs it on the data. The tool that publishes the data checks the same way before it opens
anything.

### The notification card breathes

The card's status light is the popup's now: it breathes on the one table the window, the popup and the
panel breathe on - a breath every 4.4 s while monitoring and every 2.8 s while recovering - a problem
pulses once and then holds lit, and an interruption waiting for its reset holds lit and still, as it
does everywhere. The card's face is drawn again for the light at most every 80 ms. Reduce motion and
High Contrast hold it lit and still with no glow, which is what v0.6.6 drew for every card on purpose.
`notice_window.py` grew by seven lines for it, and its line ceiling was raised to match: the split that
brings those ceilings down is v0.6.8.

### Compatibility data between releases

The data file on `main` is live: it changes whenever compatibility data is published, between releases.
The behaviour tests and the documentation's pictures read v0.6.6's bundled document, frozen beside them
(`tests/fixtures/codex_compat_frozen.json`), so a publication cannot turn `main` red or mark a picture
stale; `BundledBaselineTests` still hold the live file to its rules. The first publication since v0.6.6
verified codex-cli 0.153.4, 0.154.0-alpha.6.2 and 0.155.0-alpha.9.2 and checked 0.155.0-alpha.2.6,
each from one machine's own records of real recoveries, with the recordings under `docs/evidence/compat/`.

### Fixed

- **Main went red once on the commit a release is tagged at.** The check that a tagged version's digest
  is pinned now skips the commit the tag points at, which cannot carry its own digest; a later commit
  without the pin still fails.

### Documents

- The roadmap's planned releases each move one number on: the Python modularization that was v0.6.7 is
  v0.6.8, the GitHub landing-page tidy goes with it, and everything after follows.
- The feature matrix, the security and support notes, the brand document, the README and the plugin,
  live-acceptance and verification guides say the six states and the breathing card, in English and Korean.

### Evidence

Everything below was run on one Windows 11 machine (Home, build 26200, Korean system language). The
suite passes on this tree; the tests named above are the ones that hold each change: `ResolveTests`,
`PermitTests`, `EvaluatorTests`, `CardTests`, `OlderReleasesTests`, `BundledBaselineTests` and the
card's two light tests. The pictures were made again for this version.

Not verified, and not claimed: a real Codex showing Checked or Failed here, which needs a version the
data checks on a computer whose check fails; the card's light breathing on a real desktop, which is
drawn off-screen and read at single moments; and the Failed here overlay asked for by a test.

## v0.6.6 — A status light that breathes, a taskbar button that moves where it is installed, a theme of the panel's own, and pictures that show it

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.5...v0.6.6)

What a day of real use turned up. Nothing about recovery changed: the same classifier, the same
gates, the same one watcher that is the only thing allowed to send. One new setting, the panel's
own theme, whose default changes nothing.

### The status light is the ordinary breath now

Three cuts were wrong in three directions, and each was named: v0.6.4's glow was too big, v0.6.5's
blink too quick and too hard, and this release's first answer - a smaller swing - too faint to see.
The fourth is how a status light of this size is ordinarily built, and nothing of ours:

- **One cycle near a resting breath**, 4.4 s, about fourteen a minute. Recovering runs it every
  2.8 s; a problem runs it once, over 1.4 s, and then holds lit.
- **One symmetric cosine across the whole cycle**, so the light is never not moving and has a
  corner nowhere - half of it down, half back.
- **A deep swing**: the dot keeps 35% of its light at the bottom, 62% of its colour as drawn.
  Gentleness comes from the speed and the curve, not from a small swing, which is what the first
  answer got backwards.
- **Taken in light and drawn through the screen's gamma**, because a cosine walked straight along
  an alpha bunches at the top and rushes at the bottom.
- **A glow that rides the brightness** rather than taking a turn of its own: out at the top at
  opacity 0.50, gone at the bottom.
- **A reach that is a share of the dot**, 0.6 of its radius, rather than the flat 3 px it had been
  - which was two thirds of the popup's radius and half of the panel's, the same light in two
  strengths. The window's is unchanged at 3 px; the panel's is 3.6 and the popup's 2.7.

One table serves every surface, so the window, the notification-area popup and the panel in Codex
breathe alike; the notification card draws its light from the same table at one moment of the
breath, because a card that is on the screen for a few seconds does not breathe at all. The
notification-area icon and the window's taskbar button read the same rhythm, so the mark's head
breathes with it and its sweep comes every 22 s rather than every 16 s; the head keeps its own
deeper fall, because sixteen pixels need it.

### The last controls that were not ours

Two native controls were still showing through the design, and a third was ours only where somebody
had remembered to ask for it.

- **Every scroll bar is the product's own**, wherever one appears and on either axis. The panel's
  rules had been written for one class - the drop-down's list - so a wide table, a long page or any
  box added later got the browser's grey; they are global now, with a corner and a Firefox
  fallback. In the window the message box was the last control still scrolling on Windows' bar: it
  keeps that bar, because that is what scrolls the text and what the wheel and the keys talk to,
  and hides it outside a clip, while ours is drawn in the gutter that leaves, from the box's own
  scroll position, exactly as a list's is.
- **A scroll bar's track takes its colour from the ground it runs over.** Over a card the groove is
  `inset`, as it always was; in a well that is itself `inset` - the message box - an inset track
  would be the ground and the pill would float on nothing, so there it is `surface`. High Contrast
  keeps its system colours either way.
- **Windows' message box is gone from the window.** Fourteen of the fifteen are now a dialog in the
  material the rest of the window is made of, and they say what will happen: instead of "Yes" and
  "No", which name nothing, the affirming button carries the words of the button that was pressed
  to ask - *Clear history*, *Stop watcher*, *Install* - beside Cancel, which is the pattern the
  panel settled first. The fifteenth is kept on purpose: it is raised before there is a window, a
  theme or a catalog, to say that nothing is installed in that location.
- **Every drop-down the panel makes is the panel's own**, which was true and is now held to by a
  test that reads each one by name rather than counting them.

Deliberately unchanged: the notification area's right-click menu, which Windows draws and which
already follows the theme, and the file picker the diagnostics export opens, which is the one every
other application opens.

### The panel in Codex has a theme of its own

The panel sits inside Codex and everything else sits on Windows. *Use system setting* already let
each follow its own host, but a Light or Dark Theme drew them all alike: nobody could keep the window
dark and let the panel follow Codex, or pin the panel whatever Codex does. **Theme in Codex**, under
Settings > Appearance right under the Theme, is the panel's own: *Same as Theme*, *Codex's theme*,
*Light* or *Dark*.

- *Same as Theme* is the default, and it is exactly what every panel did before: the Theme's choice,
  with *Use system setting* following Codex there as it always has. An upgrade changes nothing
  anybody can see; the new setting only matters once somebody chooses it.
- The Theme itself now draws the window, the popup and the notification card, and draws the panel
  only while Theme in Codex is Same as Theme. Its help in both places says so.
- It is offered in the window and in the panel, and Codex may change it too (`panel_theme` in the
  settings tool). A save sends it only when it was changed where the save was made, as the Theme and
  the Interface language are sent, so one changed elsewhere is not put back.
- A watcher too old to know the setting sends none, and the panel draws itself in the Theme's choice,
  as it did. A value it does not know is Same as Theme.
- Its words are in all nine languages, and the Theme's help is rewritten in all nine, because it no
  longer colours the panel outright.

### The documentation moves

- The pictures a reader meets first are animated PNGs now: every dashboard page, the settings
  window, the panel in Codex and the notification-area popup, in each language, with their status
  light redrawn from `brand.glow` at the rate the window itself repaints. Nothing else in them
  moves, they keep every colour they had, and a viewer without animation sees the still picture
  that was always there.
- The icon's motion and the light's own picture are animated PNGs too, in place of the GIFs they
  were: a GIF holds 256 colours, which is not enough for the badge's gradient or the card's
  ground.
- The pictures are the light theme's only. The dark theme is described rather than pictured, which
  halves what a reader scrolls past.
- **Every window picture had a black band down each side and along its bottom** - 11 px at 100%,
  16 at 150% - and nobody had looked at the edge of a 1522-pixel picture. It was not the window:
  `PrintWindow` returns the window without its frame, because the frame is Windows' to draw, and
  the bitmap it is drawn into starts black. The picture is now cut to what was actually drawn,
  measured from the window's own client rectangle.
- **And the corners Windows rounds are rounded in the picture**, at the system's own radius for
  this window's DPI, left transparent so the page behind shows through them. A screenshot of a
  Windows 11 window with square corners is a screenshot of a window nobody has.

### The taskbar button moves where it is installed

- v0.6.5 moved the mark on the window's taskbar button, and on an installed window it never moved
  once. Measured here: the published executable, byte for byte, moved the button from a scratch
  folder and did not move it from the installed one, where an instrumented build showed the window
  setting frame after frame into a button that stayed pixel-identical for twenty-four seconds.
  What decides it is where the window is installed, not what it does: Windows files an installed
  window under the application registered at that location and paints its button from that
  application's icon, which no window can change. A Start Menu shortcut alone does not do it - one
  written for a scratch folder, with the same identity and the same icon, left the button moving.
- The window now asks Windows to file it under an identity of its own, which nothing registers, and
  the button falls back to the icon the window itself sets. With that one call the same build moved
  74 of 163 filmed frames in the installed location. Notifications are unaffected: they are raised
  by the watcher under the watcher's own AppUserModelID, which is what makes them attributable.
- The notification-area icon is unchanged, including where it holds still on purpose: an icon
  Windows keeps in the overflow flyout does not move, because nobody sees it there. Dragging it onto
  the taskbar brings its motion back within a second.

### Documents

- The changelog, the roadmap, the brand notes and the feature matrix carry the new numbers, in
  English and Korean. The roadmap's planned releases each move one number on: the Python
  modularization that was v0.6.6 is v0.6.7, and everything after it follows.

### Two builds before this one

v0.6.6 was published twice before this, and both builds are kept as pre-releases, each on a release
page of its own and with an entry of its own right after this one in the changelog:
[`v0.6.6-beta`](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/tag/v0.6.6-beta), the build announced as `v0.6.6` on 2026-09-20, and
[`v0.6.6-alpha`](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/tag/v0.6.6-alpha), the first candidate. All three archives are called `CodexAutoResume-v0.6.6-win-x64.zip`, because
renaming a tag does not rename what is already attached to a release - the same name for different
bytes. The digest pinned in `scripts/release.json` is this release's, and it is the one to check
against.

### Evidence

Everything below was run on one Windows 11 machine (Home, build 26200, 3840 x 2160 at 150%, Korean
system language, Windows' apps set to dark and the product's Theme set to Light). The suite, the
build, the archive, the light, the pictures, the dialog and the panel's own theme were measured on
this tree. Two things were measured on the first candidate, `v0.6.6-alpha`, and not again: the
taskbar button filmed in the installed location, whose code has not changed since by a byte, and
the upgrade over v0.6.5, which this release made over the beta instead.

- **The suite.** 2,580 tests, no failures, under Python 3.13 here (900 s, 8 skipped), and green on
  GitHub's Windows runners for 3.12, 3.13, 3.14 and 3.15. The skips are the opt-in live checks and
  the pin check that waits for the tag.
- **The window, built here and on GitHub.** The `CodexAutoResumeSettings.exe` built from these
  sources on this machine and the one GitHub's runner built into the published archive are
  byte-identical (`db7257ee…`, 388,096 bytes). The archive's own digest is not written here - this
  file ships inside the archive, so naming it would change it - it is published beside the release
  and pinned in `scripts/release.json` afterwards, which is what `docs/VERIFY.md` compares.
- **The taskbar button, in the installed location.** This is the claim v0.6.5 could not make. With
  v0.6.6 installed over v0.6.5 here, the window's button was filmed at ten frames a second for
  twenty-four seconds: 92 of 198 frames differ from the one before, and the mark's head is at
  different places and brightnesses through the loop. The same measurement on the published v0.6.5
  build, in the same place, found not one changed pixel in twenty-four seconds; the same executable
  moved the button from a scratch folder. An instrumented build showed the window setting frames
  throughout (state=watching, allowed=True, interval 156 then 62) - the frames simply never reached
  the button.
- **Installed on this machine.** The first candidate was installed over v0.6.5: the installer
  answered *Updated. Your settings and pending recoveries were kept.*; `config\settings.json` was
  byte for byte what it had been; the watcher restarted and reported 0.6.6. This release was
  installed over the beta from its own archive's `Install.cmd`, with the same answer; the 154
  files it installed are byte for byte the archive's, and the watcher restarted on them.
- **The archive.** `build/smoke_archive.py` passed every check on the published archive, including that both
  executables report 0.6.6 and that this machine's registrations and state were left as they were.
- **The light.** Its numbers are held by the suite on the drawn pixels of every surface - the
  window, the popup, the panel and the card - and every picture in the documentation was drawn
  again from the new table by the product's own code, in the five languages they are made in, in the light theme.
- **The icon's motion.** The animated PNG in the documentation is composed from the icon's own
  frames at the new rhythm, and the suite holds every frame of it against the icon's table.
- **The pictures' edges.** Every window picture is 22 px narrower and 11 shorter than it was: the
  frame Windows draws and PrintWindow does not is gone, measured away rather than trimmed by eye,
  and the four corners Windows rounds are rounded and clear, which the suite reads off the pixels.
- **The dialog.** It is opened for real by the suite - the compiled window, a dialog asked for, a
  timer that reads it while it is up and presses one of its buttons - and what is read back is where
  the buttons are, which one Enter and Escape press, that it belongs to the window and carries no
  second button on the taskbar, and the answer each press gave. Nobody has yet used it with a screen
  reader, and no capture shows it.
- **Theme in Codex.** The panel's own `applyTheme` is run in Node over thirteen pairs of the two
  themes, and the panel's row is driven there: its four choices, a save that sends it alone, and
  the stamp changing in place. The compiled window is driven too - it sends the setting only when
  it was changed there, and its drop-down follows a change made in the panel or by Codex. The
  settings panel's picture shows the row, in the five languages the pictures are made in.

Not verified, and not claimed: the notification-area icon's own motion on this machine (Windows
keeps it in the overflow flyout, where this release still holds it still on purpose); High Contrast
on a real system; a real Codex interruption recovered by this build; the panel drawn in a theme of
its own inside a real Codex; any machine but this one, and
any scaling but 150 per cent.

## v0.6.6-beta — The build announced as v0.6.6, before the panel had a theme of its own

**A pre-release, kept on [its own page](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/tag/v0.6.6-beta).** Built from `b17076d`, published and
announced as `v0.6.6` on 2026-09-20 and renamed `v0.6.6-beta` on 2026-09-21. It went out without the panel's own
theme, which was asked for the same day, so v0.6.6 was cut a third time. Its notes are v0.6.6's
above less *The panel in Codex has a theme of its own*: the ordinary breath, the taskbar button that
moves where it is installed, the product's own scroll bars and dialog, and the pictures cut to the
window. Its evidence was measured on its own tree: 2,572 tests, and a window built twice to
`c572844e…`, 387,072 bytes.

- It was announced, so it is said plainly: **the tag `v0.6.6` has named three archives**, and this
  was the first announced under it. Its digest is
  `e620280bd5b40ad354d767fe22dd65ec8ed3eefe6b2f0af20d20759fca7e81a3`; `scripts/release.json` pins v0.6.6's, so a copy taken from the beta's page fails the
  comparison, which is the comparison doing its job.
- Nothing is served it: the update check reads the tag out of the URL `releases/latest` ends at and
  accepts `vMAJOR.MINOR.PATCH` alone. A machine running it keeps it and is not moved back to v0.6.5.
  Because the number is the same, the update check does not offer it v0.6.6 either: the v0.6.6
  archive's `Install.cmd` installs over it, and so does the setup script given `-Force`.

## v0.6.6-alpha — The first candidate, set aside before it was announced

**A pre-release, kept on [its own page](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/tag/v0.6.6-alpha).** Built from `f63d904`, tagged
`v0.6.6` and published on 2026-09-20, then stopped before it was announced: its gentler light - a
smaller swing - was too faint to see, and the scroll bars, the dialog and the pictures' edges had not
been made the product's own yet. It carried two things: a slower, shallower status light (a 4.4 s
cycle, the dot dimming 38% of the way rather than 60%, the glow peaking at 0.30), and the taskbar
button that moves where it is installed, which v0.6.6 carries too.

- Its archive is called `CodexAutoResume-v0.6.6-win-x64.zip` as well, and its digest is
  `3b99217b084148111d07cfc51c9ad8f5bddb6fd50029979ed1b1b6796be0b956`. Nothing is served it, for the same reason as the beta.

## v0.6.5 — A light you can see, notifications in the product's own card, and a Codex Compatibility Registry

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.4...v0.6.5)

A design and safety release. With the compatibility data this release ships, recovery decides
what it decided in v0.6.4: the same classifier, the same gates, the same one watcher that is the
only thing allowed to send. The one difference is a check: codex-cli 0.153.4, which v0.6.4 trusted
by its version, now has to show that `codex queue` still takes a conversation and a message, as
every other build always had to (below). What changed is how much of it you can see - a status light and an
icon that visibly move, notifications drawn in the product's own design, controls that answer as
they change - and a Codex Compatibility Registry, whose data can only ever make the watcher more
careful. The one new setting, **Show notifications as a card beside the notification area**, is on
by default and changes where a notification appears, never whether there is one or what it says.

### The status light

- v0.6.4's light was too quiet to be seen. It now blinks the way the notification-area icon's head
  does: while the watcher is watching, every 3.2 s the dot itself dims to 60% of the way toward the
  card it sits on and comes back, with nothing spreading, and only once it is fully lit does a small
  glow spread from its edge - opacity 0.34, 3 px past the dot at most - and draw back in. A first cut
  breathed a glow reaching 7 px round a dot that never changed; this one was chosen after it, from
  previews at 2, 3 and 4 px. While a recovery is being sent the same cycle runs every 2 s.
- Waiting and checking hold lit with no glow, and a problem runs the cycle once, over 1.4 s, then
  holds lit. The colours, the words beside the light and its size are unchanged, and it is the same
  light in the Dashboard, the popup and the panel; the notification card shows it lit and still.
- Reduce motion and Windows' animation setting hold it lit and still with no glow, and High Contrast
  still draws a solid dot with no glow.

### The notification-area icon moves

- While the watcher is watching, the bright head of the mark breathes on the status light's 3.2 s
  rhythm - dimming toward the badge's deep blue and back - three times, and then sweeps along the
  ring's white stroke and back in a slot of two more breaths, at full brightness: 2.56 s out,
  a moment at the stroke's far end, 2.56 s back, and 1.12 s at home - a loop of five 3.2 s slots,
  16 s in all. It leaves its place clockwise and stays on the stroke, never crossing the gap at the
  top of the ring. It never breathes while it travels, and a breath and the sweep's slot both begin
  and end at full brightness, so nothing jumps where one gives way to the other.
- While a recovery is in progress - a continuation being sent, or the turn it started still being
  followed - the head sweeps out and back over and over, twice as quickly: 1.28 s out, a moment at
  the far end, 1.28 s back and 0.24 s at home, a sweep every 2.88 s, at full brightness and without
  breathing.
- Paused, the head is grey and still. When something needs you it turns amber - the danger colour
  for a failure - pulses once and holds.
- The head moves in 24 steps of 15 degrees round the ring - the 20 of them from its own place
  clockwise to the stroke's far end - and breathes through 24 levels of brightness, a tint of the
  head rather than stored frames: about 16 frames a second while it travels, one for each step of
  watching's sweep, and about 6 while it breathes. Each frame costs explorer.exe the work of drawing
  the icon again, so the rates were chosen by measuring that - each candidate for 60 s against 60 s at
  rest, on one machine (Windows 11 build 26200, 3840 x 2160 at 150%). While it watches, the
  notification-area icon - measured where Windows had put it, in the overflow area - costs
  explorer.exe about 1.3 points of one core above rest at these rates, against 1.1 at the 3 and 5
  frames a second it had before and 2.2 with a breath of 11 a second; the taskbar button costs about
  2 at every rate tried, and was seen redrawn no more than about eight times a second whatever it
  was sent. Travelling all the time, while a recovery is in progress, each costs about 2.5 to 3.
  These were measured while watching turned a whole way round in the last slot of five; it now
  travels in two of them, so what watching costs sits a little nearer the travelling figure.
- It holds still under Reduce motion, Windows' animation setting, High Contrast and battery saver,
  while the session is locked, and while the icon sits in the overflow area where nobody sees it.
  Where the icon is cannot be asked of the shell: Windows 11 build 26200 gives an icon in the
  overflow area the overflow button's own place rather than none, and the icon moved there unseen,
  at explorer.exe's cost. What Windows itself wrote about this icon says it instead - its own
  per-icon setting, read and never written - and an icon it says nothing about is left to the
  shell's answer, as before. At rest it is exactly the icon it has always been; the badge and the
  shape are unchanged.
- While the settings window is open, its taskbar button moves the same way, with the same rhythms
  and frames. Its state is the icon's for the same watcher, as the icon has it while the popup is
  open: the window, like the popup, reads the watcher as it is now. It holds still under the same
  settings, while the session is locked or disconnected - which it asks Windows once a second, where
  the icon hears Windows say it - and while the window is hidden. The title bar's icon does not move, and at
  rest the button is the icon it has always been.

### Notifications in the product's own card

- A notification now appears as a card in the product's own design beside the notification area:
  the popup's card, with the product's name, a status light and, for a detected interruption, the
  kind of interruption on a chip. It says exactly what the Windows notification says - the same
  three lines, in the Interface language - and offers exactly its buttons: **Don't resume** and
  **Open Dashboard** for a detected interruption, none for anything else. A button does what the
  notification's button does, and nothing more: it cancels that one recovery or opens that one page.
- The card rises out of the corner the notification area is in, fading in and growing from 98% to
  full size in about a third of a second, and never takes the keyboard focus. It stays at least 6
  seconds - longer if Windows is set to keep notifications longer - and while the pointer is over
  it, then fades. Up to three stack, the newest nearest the corner, and a newer card about the same
  conversation replaces the older one. Under Reduce motion, Windows' animation setting, battery
  saver or High Contrast it appears and disappears in place.
- Once the card has been on screen, the same Windows notification is added to Windows'
  notification center silently, with no banner and no sound, so the history is what it always was.
  If a card cannot be drawn, Windows' own notification is raised instead.
- Windows' own notification, exactly as before, is used whenever a card must not show: the setting
  is off; the notification-area icon is off; Do not disturb or Focus is on; an app is full screen or
  presenting; the session is locked or remote; a screen reader is running, because Windows'
  notification is announced and a card that never takes the focus is not; or Codex Auto Resume's
  notifications are switched off in Windows' Settings, in which case Windows shows nothing, as it
  always did.
- The setting is under Settings > General > Windows in the Dashboard, beside the notification-area
  icon, with a line saying what it does. Codex cannot change it.
- Which events notify and their wording did not change: the **Notifications** switch and the event
  check boxes still decide whether there is a notification at all.

### Depth in the popup

- What stands on the popup's card is now raised and what holds a value is sunken: each waiting
  task is a tile lifted off the card - a soft drop and highlight in light; in dark, a faint drop and
  a one-pixel light along its top edge on a slightly brighter ground - the three counts sit in one
  sunken well with a hairline between them, "nothing waiting" and a failed read are said from a well
  too, and a button sinks into a well while it is pressed. High Contrast draws none of it.
- In the panel in Codex, each waiting conversation's row and the Automatic recovery switch's tile
  are lifted the same way.
- The Dashboard's Pending and History lists stay flat rows with a hairline between them, as in
  v0.6.4.
- A count's label is never cut inside a word: a column whose longest word needs more room gets it.

### The window's first screen

- The Overview's **Pause recovery** or **Resume recovery**, **Pending** and **History** are back at
  the bottom left of their cards, in a row of their own under what the card says, as in v0.6.2. The
  header's **Start watcher** and the Custom messages' **Clear** buttons stay at the bottom right.
- The window opens at 1000 × 664 instead of 1000 × 632. The Overview's rows are as tall as their
  cards need and a little more, never more than 24 px past it, with the page's own 14 px gap under
  the last row rather than cards stretched to the footer. On a screen whose work area is shorter -
  1920 × 1080 at 150% with the taskbar, for one - it opens as tall as the work area, and the
  Overview still fits there in every language.

### Lists, drop-down lists and switches

- Lists in the window no longer overflow sideways at ordinary sizes. As a list narrows, a
  conversation's name gives way first, then what a column holds past a readable width, then
  headings wider than what they head, the widest first, and last the cells, the widest first; what
  no longer fits ends in an ellipsis, so a time or a count stays whole while a long name or state is
  shortened. Only a list narrower than its columns can shrink to scrolls sideways, on the window's
  own soft bar; Windows' white horizontal bar no longer shows.
- Drop-down lists are drawn by the product, in the window and in the panel: a card of the cards'
  own material floating under the field with the soft shadow, its items pills - the chosen one
  sunken, the one under the pointer raised, the one the keyboard is on ringed. It opens where there
  is room, shows up to twelve rows and scrolls the rest, rises into place unless motion is reduced,
  and is drawn in system colours with no shadow in High Contrast. The keys are Windows': it opens on
  a click, F4, Alt+Up, Alt+Down or Space, the arrows, Home, End, Page Up and Page Down move, typing
  finds the next item that starts with what was typed, Enter or Tab takes an item and Escape closes
  it unchanged. A screen reader hears it as a combo box with its choice and the item the keyboard is
  on. In dark the open list is dark: v0.6.4 left it in Windows' light frame.
- Switches glide when they change - the knob slides and the track cross-fades in 160 ms, on one
  ease-out curve - in the window, the popup and the panel, and check boxes fade in the window and
  the panel. A switch whose change has to be confirmed first - by you, or by the watcher - moves once,
  when it is confirmed, and never slides and snaps back. Nothing moves under Reduce motion, Windows'
  animation setting or High Contrast.

### Words

- The panel in Codex keeps Korean words whole when it wraps a line, and Japanese phrases; the
  window breaks Korean lines only at spaces, where Windows used to break them inside a word.
- The popup and the notification card set Latin text in Windows' UI font, as the window and the
  panel do.
- Everything new is in all nine languages.

### Codex Compatibility Registry

- For the Codex engine on this machine, the product now says which of the things it does can be
  relied on, in four words: **verified** - the maintainer tested this exact Codex version, with
  recorded evidence; **compatible** - the checks on this computer pass, and nobody has verified this
  exact version; **incompatible** - a check on this computer failed, or the compatibility data says
  this version does not work; **unknown** - it could not be established, because a check could not
  run. It is on a new **Codex compatibility** card on the Diagnostics page, read-only in a card in
  the panel, in `status` and `doctor`, in a new `compat` command, and in the diagnostics export.
- The watcher does the checking as it runs: the checks the engine it drives has already passed,
  the column names of Codex's databases (never a row), the folders recovery reads and the Windows
  interface that tells whether a conversation is open. It writes what it found to
  `config\compatibility.json`. Everything that shows it checks the file again as it reads it, and
  shows unknown, saying why, for one that is damaged, too old, or about a Codex binary that has
  since changed.
- The data ships inside the release. The data this release ships marks no capability verified: a
  verified entry has to cite a recording made on that exact Codex version, and none of the
  repository's recordings says which version it was made on yet. So every capability is decided by
  the checks on this computer - compatible where they pass - which is what the product did before
  the registry existed. Its one restriction, for codex-cli 0.153.4, is on recovering a conversation
  that is not open in the app, which this product does not do.
- The one build v0.6.4 called verified, codex-cli 0.153.4, is now shown as compatible, and like
  every other build it has to show that `codex queue` still offers `--thread` and `--message` before
  anything is sent to it; v0.6.4 skipped that check for it.
- The data is refreshed only when you ask: **Refresh compatibility data** on the Diagnostics card,
  or **Check for updates** once github.com has answered it, whether or not an update exists. The
  update check skips the refresh when github.com could not be reached and when too little of its
  time is left, and its answer about updates is the same either way. Nothing polls, the watcher
  never asks, and neither the panel nor Codex can ask. A refresh is one HTTPS GET to one fixed
  address on raw.githubusercontent.com - this repository's own data file on its main branch - with
  no query string and nothing about this machine in it.
- What arrives is handed to this installation's own validator, which keeps it, as
  `config\compat-cache.json`, only if it is compatibility data this version can read and no older
  than what is in force; anything else is refused, and a refresh that fails or is refused changes
  nothing. The card says what happened: refreshed with the data's number, refused and why, could
  not be fetched, or busy while an installation or a repair is running.
- Refreshed data can only make the watcher more careful. It can mark a Codex version incompatible,
  and then nothing is sent while it is in force. It can mark something verified only for an exact
  version whose checks on this computer already pass, which changes the word and not what is sent.
  A check that fails on this computer always wins. Refreshed data past its expiry, about 90 days,
  keeps its restrictions and loses its verifications.
- Codex sees a summary: `get_status`, and `open_settings` with it, now carries the compatibility
  summary as codes only - the overall result and the one the watcher acts on, whether the report
  could be used, which data is in force and its number, the refreshed data's standing, when it was
  checked, and each capability's state and reason. No version string, no path, no free text. No
  tool can refresh or import the data.

### Fixed

- **`"enabled": "false"` turned automatic recovery on.** The window's bridge read its switches'
  value with a plain truth test, so any non-empty text counted as yes: a request carrying `"false"`
  switched recovery on and, for Run at Windows sign-in, wrote this product's sign-in autostart value;
  a request with no value switched them off. The settings window always sends a real true or false,
  so its own switches were not affected. Anything else is now refused, with the message and code
  the control layer gives.
- **Settings accepted or refused a value of the wrong type depending on the default.** An update
  was compared with what it coerced to, so `{"notifications": 1}` was accepted and
  `{"notifications": 0}` refused, and `{"reduce_motion": 0}` was accepted. A value is now checked
  for the type the settings schema publishes first and refused if it is the wrong one, whatever it
  equals. A settings file with such a value is still read as the default rather than refused.
- **The log left out the reason for 14 of the 27 states a recovery can be in**, every outcome of a
  recovery turn among them, and wrote the bare state name. Every state line now carries its reason
  code, and still codes only.
- **The release job did not check three things every installed copy requires of an update**:
  `.codex-plugin/plugin.json`, `scripts/plugin_setup.py` and the icon at the payload's root. An
  archive missing one would have been published and then refused by every installed copy. It checks
  all ten entries now, and tests hold its list to what the bootstrap requires in both directions.
- **A damaged plugin manifest passed as version "unknown", with nothing said.** The installation's
  root is now found by its manifest rather than by counting folders, and a manifest that is there
  but cannot be read logs a warning saying why, once, before the version reads unknown. A missing
  manifest still reads unknown quietly.

### Groundwork for splitting the Python code

Nothing a user sees. Every safety scan in the tests now reads the whole package, recursively, so
moving code into a subpackage can never take it out of a check's sight; the package's layers, each
module's size and its structural invariants are held by tests; and the screenshot checks are keyed
on what the window is shown rather than on which files changed. The split itself, and the golden
replies, gathered rules and typed contracts that come before it, are v0.6.7.

### Documents

- `PRIVACY.md` and `SECURITY.md` describe the compatibility refresh - when it happens, its one
  address, what is and is not sent, which file holds what and who writes it - the summary
  `get_status` carries, and the notification card. The feature matrix, the brand document and the
  roadmap describe the rest.
- The README pictures a notification as the card it now is, in the light and the dark theme, in
  place of a capture of Windows' notification taken before Open Dashboard existed, which no
  manifest pinned. The card's pictures are drawn off-screen by the card's own code and pinned as
  the popup's are, so a change to what the card says or how it is drawn fails the suite until they
  are made again. The old capture is gone.

### Evidence

Everything below was run on the release candidate built from this tree, on one Windows 11 machine
(Home, build 26200, 3840 x 2160 at 150%, Korean system language, Windows' apps set to dark and the
product's Theme set to Light).

- **The suite.** 2,555 tests, no failures, under Python 3.13 (966 s, 8 skipped) and 3.12 (952 s, 7
  skipped) here, and green on GitHub's Windows runners for 3.12, 3.13, 3.14 and 3.15. The skips are
  the opt-in live checks, the pin check that waits for the tag, and, on one interpreter here, the
  workflow parser that wants PyYAML.
- **The window, built twice.** Two builds of `CodexAutoResumeSettings.exe` from these sources are
  byte-identical (`e634e921…`, 382,976 bytes), and `build/normalize_pe.py` accepts both.
- **Clipping.** The layout audit builds the window hidden in all nine languages at 100, 125, 150,
  175 and 200 per cent, in every watcher state, and reports anything cut off, any pinned button away
  from its corner, any text under one, and an Overview that scrolls. It reports nothing.
- **Installed over v0.6.4 on this machine.** The installer answered *Updated. Your settings and
  pending recoveries were kept.*; `config\settings.json` held every value it had before, byte for
  byte on the first install and with only this release's new setting added afterwards; the watcher
  restarted and the plugin manifest read 0.6.5. The installed MCP server introduced itself as 0.6.5
  with its seventeen tools, previewed a continuation in Korean, still refused to let
  `update_settings` write a Custom message, and carried the compatibility summary as codes only,
  with no tool that could refresh or import data.
- **The compatibility card and its refresh, for real.** The watcher checked the Codex on this
  machine - `codex-cli 0.155.0-alpha.9.2` - found every local check passing and the bundled data
  verifying nothing, called it compatible and wrote `config\compatibility.json`. **Refresh
  compatibility data** then fetched the published file: `compatibility: refreshed 1`, written to
  `config\compat-cache.json` by this installation's own validator.
- **Check for updates, and the refresh that rides on it.** With v0.6.5 installed and v0.6.4 the
  newest published release, the check answered `update: newer-local 0.6.5 0.6.4` and still refreshed
  the compatibility data on the way (`compatibility: refreshed 1`) - the refresh happens whether or
  not there is an update, and it never changes the update's own answer.
- **The notification card, on a real desktop.** Three cards stacked in the notification area's
  corner, drawn by the installed build's own code in dark and in light: the product's name, the
  status light, the reason chip, the three lines and the two buttons, with the entrance and the
  stack as designed.
- **The icon's motion.** On this machine the notification-area icon sits in Windows 11's overflow
  flyout, where this release holds it still on purpose: the watcher used 1.1 s of processor time in
  its first 40 minutes. The motion itself - the breath, the clockwise sweep along the mark's stroke
  and back, and the states - was captured from a real taskbar button with the window built into a
  scratch folder, and is held by tests frame for frame against the icon's own table.
- **The status light.** Drawn through a whole cycle on every surface - the window, the popup, the
  panel in Codex and the notification card - in light and dark at 100% and 150%, and compared side
  by side with the design it was approved from; the suite also reads the drawn pixels for the dot's
  dimming and the glow's three-pixel reach.
- **Drop-down lists, switches and a screen reader.** The probes open the real drop-down list, walk
  it with the keys, type to find, close it on an outside click, glide the switches and read the list
  and its highlighted item through Windows' own UI Automation. No screen reader was run.
- **Korean and Latin text.** The window breaks Korean at spaces only (71 strings across four widths
  and three scalings), the panel keeps Korean words whole, and the popup and the card set Latin text
  in Windows' UI font, as the window and the panel do; the Korean pictures show it.

Not verified, and not claimed: High Contrast on a real system (it is rendered and asserted, never
switched on here); a real Codex interruption recovered by this build; the card's fallbacks on a
locked, full-screen or Do Not Disturb desktop, or with a screen reader running (the rule is held by
tests only); the taskbar button's motion in the installed window (the window open on this machine
was opened before the update; the motion was captured from a scratch build instead); any machine but
this one, and any scaling but 150 per cent.

## v0.6.4 — One look in light and dark, a quieter status light, and a window that arrives ready

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.3...v0.6.4)

A design and speed release. Recovery decides exactly what it decided in v0.6.3: the same
classifier, the same gates, the same one watcher that is the only thing allowed to send. The one
new setting, **Theme**, changes how the product looks and nothing it does.

### One design

- The Dashboard and the notification-area popup now use the materials of the panel in Codex:
  the same raised cards and sunken fields, the same soft shadows, corner radii and controls.
  State chips have no border, and buttons stand out and sink when pressed. The text sizes, the
  Dashboard's pages and Settings sections, and the popup's layout - apart from where buttons and
  switches sit, below - are unchanged, and so are the notification-area icon and its badge.
- The Dashboard's header and footer are floating cards, and the page tabs sit on the canvas.
- High Contrast: the popup follows it now too - system colours, no shadows, no motion - and
  the panel has a forced-colors style, so its lights, switch knobs and select arrows no longer
  disappear.

### Light and dark

- A new **Theme** setting, first under Settings > Appearance in the Dashboard and in a new
  Appearance card at the end of the panel: **Use system setting**, the default, **Light** or
  **Dark**. In the Dashboard and the popup, *Use system setting* follows the app mode Windows is
  set to (Settings > Personalization > Colors); in the panel it follows Codex's own theme, as the
  panel always has. **Light** and **Dark** hold on every surface, whatever Windows or Codex use.
- Because the default follows Windows, on a PC whose apps are set to dark the Dashboard and the
  popup are dark after this update. Choose **Light** to keep them as they were.
- Dark is the panel's dark theme, now on all three surfaces: the same palette, cards lifted a
  step off a near-black canvas by a faint drop shadow and a one-pixel light along their top edge,
  and the same wells, switches, check boxes, buttons and scroll bars. The Dashboard's title bar
  goes dark with it, and so does the notification-area icon's right-click menu whenever the popup
  is dark, on Windows 10 version 1903 and later.
- High Contrast wins over any theme, on every surface.
- Some things Windows draws itself stay light in dark: the Dashboard's message boxes - its
  confirmations and reports - the file dialog of **Export diagnostics...**, a text box's
  right-click menu and the frame of an open drop-down list. Windows notifications look as Windows
  draws them, and the notification-area icon and its badge do not change with the theme.
- Codex can change the theme too: `update_settings` accepts `theme`. The notification-area icon and
  Reduce motion are still not offered to Codex.

### Changing the language or the theme

- The Dashboard builds its words and colours when it opens. When a Save changes the Interface
  language or the theme, the window now closes and opens again by itself, in the new language or
  theme, on the same page and Settings section, in the same place and at the same size - maximized
  if it was - with the keyboard where it was. It used to say that the change would show the next
  time it opened.
- It does the same when either is changed somewhere else while it is open - in the panel, through
  Codex, on the command line or in another Dashboard window - when Windows switches its apps
  between light and dark while the theme follows Windows, and when High Contrast is turned on or
  off.
- It never reopens over changes that are not saved. A note in the save card then says the window
  will reopen once you save or discard them, and it reopens as soon as you do. If the new window
  cannot start, the old one stays open and goes on working.
- A Save sends the Interface language and the theme only when they were changed on that page, in
  the Dashboard and in the panel, so saving something else cannot put back a language or a theme
  that was changed elsewhere in the meantime.
- The popup and the right-click menu use a new language or theme the next time they open, without
  a restart of the watcher, and an open popup redraws when Windows switches between light and dark.
- The panel applies a saved language or theme at once, where it is. To speak any of the nine
  languages without asking again, it now carries all of their words, which takes the page Codex is
  served from about 105 KB to about 205 KB.

### Switches and check boxes

- A switch now always turns something that runs on or off: notifications, the notification-area
  icon, Reduce motion, Run at Windows sign-in, and automatic recovery for one conversation. A check
  box picks which items of a list apply: which kinds of interruption are recovered and, under the
  notifications switch, which events notify. A setting is the same kind in the Dashboard and in the
  panel, and a check box sits to the left of its label everywhere.
- The check box is new, in the same material: empty, it is a sunken well; ticked, it is filled
  with the accent and carries a tick; disabled, it is muted; in High Contrast it is drawn in system
  colours.

### Buttons and switches at the bottom right

- A button or an on/off switch at the right of a card or a row is now pinned to its bottom-right
  corner, in the Dashboard, the popup and the panel. What the card or row says comes first, from
  the top left, and the control closes it. Text beside a control wraps, or the control moves under
  the text and stays on the right, so nothing runs underneath it; in the Dashboard and the panel
  the keyboard and screen readers reach the control after the text. Buttons that were already
  along the bottom, drop-downs, chips, check boxes and the Dashboard's switches - before their
  labels in Settings, in their column on Pending - stay where they were.
- In the Dashboard, **Pause recovery** or **Resume recovery**, **Pending** and **History** sit at
  the bottom right of their Overview cards rather than at the left under the cards' content, and
  **Start watcher** sits at the bottom right of the header. **History** stands under the finished
  conversations when their outcomes reach the card's edge.
- **Right now** keeps its order - automatic recovery, the watcher, the Codex engine, the last
  check - with the button that pauses and resumes recovery under them at the card's bottom right.
  The card is laid out for the longest words it can show, so it does not move when the watcher's
  state changes or its last check grows older, and the Overview still fits the window whatever
  state the watcher is in.
- In the popup, each task's switch has moved to the right end of its row, level with the last line
  of its label however far the label wraps, and the label wraps in the room left of it.
- In the panel, the **Pause recovery** or **Resume recovery** button at the top of the Automatic
  recovery card sits at the bottom right of its tile, beside the state and, when a pause fails,
  the message under it. The **Show notifications** switch sits beside the last line of its label,
  and each waiting conversation's **Auto-resume** switch beside the line with its next check and
  attempts. In a narrow panel each moves under its text and stays on the right.

### The status light

- While the watcher is running and recovery is on, the light is cyan again - the colour it had
  before v0.6.3 - whether the watcher is watching, waiting, checking a task or recovering; the
  word beside it says which. It glows softly and breathes slowly.
- A paused or stopped watcher shows the same grey as before, with no glow. A stopped watcher
  is grey again rather than amber; amber is for a running watcher that needs you.
- Reduce motion, Windows' animation setting and High Contrast still hold it still.

### The window

- It opens at 1000 × 632 instead of growing to fit the longest Settings section: as tall as fits
  a 1920 × 1080 screen at 150% with the taskbar, less a few pixels, and a size the Overview fits
  without scrolling in all nine languages at scalings from 100% to 200%. A Settings section taller
  than the window scrolls. On a screen with less room, it opens no larger than the screen's work
  area.
- The Overview's four cards share the height of the page: its two rows reach from under the tabs
  to just above the footer, both rows are the same height and so are the cards in each, so the
  cards are taller and no empty band is left above the footer. What a card says stays at its top,
  and a card's button moves down with its bottom-right corner. In a window too short for rows of
  one height, each row keeps what its own cards need, and the Overview scrolls only when they need
  more than the window has.
- On Pending, **Why it is waiting** is as tall as the list beside it and scrolls inside its own
  card, so the page does not.
- Pages, Settings sections and lists scroll on a soft bar made of the same material instead of
  Windows' own scroll bar. It shows only while there is more than fits, darkens a step under the
  pointer, glides unless motion is reduced, brings a control the keyboard moves to into view, and
  is drawn in system colours in High Contrast.
- It waits until it has a page to show, and it gets there sooner. Measured at 150% scaling on an
  empty installation during development, inside the window: the first painted header went from
  1.46-1.54 s to 0.44-0.45 s, later page switches from a median of about 100 ms (at most 203 ms)
  to 22 ms (at most 59 ms), the Continuation message section from 222-241 ms to 74-82 ms, and the
  bridge's status check from 341 ms to 168 ms. Measured from outside on a real installation with
  real history, the window is on screen about 0.3 s later than v0.6.3's empty frame was - and
  holds a page people can use about 3 s sooner. The Evidence section gives the numbers.
- To get there, pages and Settings sections are built when they are first shown, a page that
  was refreshed in the last two seconds is not asked again, and the window keeps its interface
  text in `config\strings-cache.json`, beside the settings. That file is used only when the product version,
  the stored interface language and the Windows language all still match; otherwise the window
  asks, as it always did, before it shows a word.
- The bridge's status check no longer loads the watcher to find out whether one is running.

### Fixed

- **Combo boxes lost their bottom edge.** Continuation language, Preview for, Use the message
  for, Message for, Retry timing and the Statistics period were drawn with the bottom border
  cut off. A settings row measured its height before the window's font reached it, and the box
  grew afterwards. Rows now measure again when the box or the font changes, and a test builds
  the window at five scalings in all nine languages and reports anything cut off.
- In the panel, a primary button pressed from the keyboard showed white text on a light
  field, and disabled controls used half-transparent text; they now use readable muted text.

### Documents

- A roadmap, `docs/ROADMAP.md` and its Korean translation, says where the project is heading
  release by release: a direction, not a promise.

### Evidence

Everything below was run on the release candidate built from this tree, on one Windows 11 machine
(24H2 build 26200, 3840 x 2160 at 150%, Korean system language, dark app mode).

- **The suite.** 1,820 tests, no failures, under Python 3.13 (710 s, 8 skipped) and 3.12 (715 s,
  7 skipped) here, and green on GitHub's Windows runners for 3.12, 3.13, 3.14 and 3.15. The skips
  are the six opt-in live checks, the pin check that waits for the tag, and, on 3.13 here, the
  workflow parser that wants PyYAML.
- **The window, built twice.** Two builds of `CodexAutoResumeSettings.exe` from the same sources are
  byte-identical, and `build/normalize_pe.py` accepts both.
- **Clipping.** The layout audit builds the window hidden in all nine languages at 100, 125, 150,
  175 and 200 per cent, in every watcher state, and reports anything cut off, any pinned button away
  from its corner, any text under one, and an Overview that scrolls. It reports nothing.
- **Installed over v0.6.3 on this machine.** The installer answered *Updated. Your settings and
  pending recoveries were kept.*; `config\settings.json` was byte-identical afterwards, the watcher
  kept running, and the plugin manifest read 0.6.4. The installed MCP server introduced itself as
  0.6.4 with its seventeen tools, previewed a continuation in Korean, and still refused to let
  `update_settings` write a Custom message.
- **A theme change, on the real window.** Settings > Appearance > Theme from *Use system setting* to
  *Light*, then Save: the window closed and came back by itself in light, on the same page, at the
  same size and place. Setting it back returned it to dark.
- **The popup, from a real click.** Clicking the notification-area icon opened the popup in dark:
  the state line, the three counts, the empty-state note and its two buttons, 564 x 438 device px.
- **First-window timing, from outside.** Process start until the window is on screen, then until it
  has drawn its page, no input sent, warm, on a copy of a real installation: v0.6.3 830-1035 ms and
  5.1-7.6 s; v0.6.4 1.2-1.3 s and 1.8-2.0 s. Inside v0.6.4 the largest costs are the process's first
  font (215 ms on this machine's 610 font files), building and laying out the Overview (600 ms) and
  Windows showing the finished window (333 ms).

Not verified, and not claimed: High Contrast on a real system (it is rendered and asserted, never
switched on here), a real Codex interruption recovered by this build, any machine but this one, and
any scaling but 150 per cent.

## v0.6.3 — Nine languages, your own words, and a window that shows it is alive

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.2...v0.6.3)

A feature and design release. Recovery itself decides exactly what it decided in v0.6.2:
the same classifier, the same gates, the same one watcher that is the only thing allowed to
send. What changed is what it says, in which language, and how much of what it is doing
you can see.

### Languages

- **Nine interface languages**: English, 한국어, 日本語, 简体中文, 繁體中文, Español, Deutsch,
  Français and Português (Brasil). The Dashboard, the notification-area popup and menu,
  Windows notifications and the panel in Codex all speak the same one.
- **Interface language setting** (Settings > General). The default, *System*, follows the
  first language Windows lists, as before; a language this product does not ship is English.
  An explicit choice wins over Windows and survives restarts, repairs and updates.
  `CODEX_AUTO_RESUME_LANG` still replaces what Windows reports, so it decides the language
  only while the setting is *System*.
- Catalogs are plain JSON, one per language, with English as the source and the fallback
  for any key a translation has not reached. Nothing is fetched from the network. The
  translations are tracked against the English they were made from, so a sentence changed
  in English shows up as stale in every language until it is looked at again.

### The continuation message

- **Continuation language** (default: the interface language) and **Message style**:
  *Minimal* only asks Codex to retry; *Standard* (the default) says why the task stopped;
  *Detailed* also asks Codex to check the work so far and not repeat what is done.
- **Custom** sends your own words, exactly as typed - one message for every interruption,
  or one per kind of interruption, falling back to the message for every interruption and
  then to Standard. It may use `{reason}`, `{category}`, `{attempt}`, `{max_attempts}` and
  `{reset_time}` and nothing else; a placeholder that would put your prompt, the reply, a
  title, a path, an account or a token into the message is refused by name. At most 2000
  characters. Nothing about the text can make a failure recoverable, skip a check, or
  choose a different conversation. A placeholder with no value for that interruption is
  left out, closing only the gap it leaves; a message left with nothing to say falls back
  as if it were empty, rather than sending Codex a turn with nothing in it. `{attempt}` and
  `{max_attempts}` count what the attempt budget counts, and a usage limit, which spends no
  attempts, has neither.
- **Preview** shows the exact text that would be sent, built by the same function the
  watcher sends with, for each kind of interruption and for choices not yet saved.
- Custom text is written only in the Windows Dashboard. It cannot be set from Codex - not
  through `update_settings` and not through the new read-only `preview_recovery_message`
  tool - because text sent automatically into your conversations must not be something a
  model can be talked into changing. It can be *read* there: the panel shows it, and
  `get_status` and `open_settings` return it with the other settings, so whatever it says
  becomes part of that conversation. A diagnostics export records only whether each
  Custom message is set, never its text.
- **Changed default:** the continuation used to be one fixed English sentence per kind of
  interruption. It is now the Standard message in the continuation language, which on an
  English system reads almost the same.

### The Dashboard

- A new visual language shared with the popup and the panel: soft raised cards, rounded
  controls, state words on tinted chips, a keyboard focus ring, and no colour without a
  word beside it. High Contrast mode drops shadows and tints and uses system colours.
  Light theme; the panel in Codex follows Codex's own theme.
- The header's status dot shows what the watcher is doing - monitoring (a slow breath),
  waiting, checking a task that has come due, recovering, paused, or needing you (one
  pulse). **Reduce motion** (Settings > Appearance) stops every animation, and Windows'
  own animation setting is always honoured.
- **Settings** is split into General, Automatic recovery, Continuation message, Appearance
  and Advanced.
- **Pending** gains an **Auto-resume** check box for each task, bound to that task's exact
  interruption and conversation. A click that reaches a record which has since finished,
  disappeared or turned out to belong to another conversation is refused and changes
  nothing. It changes policy only; the watcher still decides, and still sends.
- **Why it is waiting** lists the watcher's safety checks for the chosen task as it last
  recorded them.
- **Cancel all** stops every pending recovery, one exact record at a time. There is
  deliberately no "retry all".

### Notifications

- A transient interruption's notification names the kind of interruption.
- Both interruption notifications gain **Open Dashboard**, which opens the Pending page and
  can do nothing else.

### Fixed

- **A recoverable kind of interruption had no switch.** `auth_service_transient` (a
  sign-in service that is temporarily unavailable) became recoverable after the settings'
  list of switchable categories was last changed, so it was recovered with no way to turn
  it off and no name in any window. It now has a switch, on by default, and a test holds
  the classifier and the list of switches to each other in both directions.

### Python

- CI now runs every non-live test on Python 3.12, 3.13 and 3.14 as blocking jobs, and on
  the 3.15 pre-release as an advisory job whose result is shown but does not block. 3.11
  and older are not supported. The release still bundles Python 3.13.15, so installing it
  needs no Python at all.

### Evidence

What was run for this release, and what was not. Unless it says otherwise, everything below
was run on the code this tag was made from, with one exception: three `switch` statements in
the window's code were rewritten as plain comparisons, with no change in behaviour, after the
local test runs and the Windows checks below (see the first release run, below); CI ran the
whole suite again on the tagged commit. The other later commits changed only documents - this
section and the feature matrix's record of the run - and one test, so that it reads the
Korean documents where the generated `ko` branch keeps them.

- **The first release run stopped itself.** Tagging this version started a release run that
  builds the settings window twice and compares the two, and they differed, so nothing was
  published. The in-box C# compiler names one class with a fresh random GUID when a string
  `switch` has six or more cases, and three written for this release did. They are now plain
  comparisons. `build/normalize_pe.py` refuses an executable that still holds such a class, so
  the build fails on the machine that made it rather than in a release run, and a test compiles
  a program with one and checks the refusal. The tag was then placed on the fixed commit;
  nothing had been published under it.

- **Tests.** The whole non-live suite passed on Windows 11 under Python 3.12 and 3.13
  (1,508 tests each), and in CI on 3.12, 3.13 and 3.14 as blocking jobs; the advisory 3.15
  pre-release job passed too. The icon test used to compare compressed bytes and failed on
  3.14 and 3.15 with identical pixels, because those Pythons deflate with a different zlib;
  it now compares what each icon decodes to.
- **A pre-release review.** Every change in this release was reviewed adversarially by
  area, and each finding was checked by a second reviewer who tried to refute it. Eighteen
  findings; one was refuted, and the other seventeen - fourteen distinct - are fixed here,
  each with a test. The ones that could change what is sent or what a switch does:
  - Custom text made only of placeholders - `{reset_time}` for an interruption with no
    reset time - was sent as a turn holding nothing but the marker, and spent an attempt.
  - A right-click on a task's Auto-resume box switched automatic recovery off for that
    conversation.
  - Holding Space or Enter on a switch in the notification-area popup flipped it back and
    forth, and where it stopped was chance.
  - A closed popup kept the icon's badge on "needs attention" after the problem cleared.
  - The one-shot bridge put Custom message text on a `python.exe` command line.

  The rest were wording and display defects: `{attempt}` counting claims rather than
  attempts, filling a placeholder reflowing the whole message, High Contrast text drawn on
  a Highlight fill, an alarm that pulsed again every refresh, a halo that stayed frozen
  after a restore, a card that measured its text wider than it drew it, a counter that
  counted emoji twice, the diagnostics export recording the wrong language, and the
  translation export's own output refused by its import. Reviewing the fixes found one
  more: the long-lived bridge refused a valid Save of long Custom messages as too large.
- **On a real Windows 11 machine** (150% scaling). A release candidate built from this code
  passed `build/smoke_archive.py` and was installed over an earlier candidate: the installer
  reported the update and did not rewrite the settings file, the installed files matched the
  archive, the installed MCP server reported 0.6.3 and 17 tools, `preview_recovery_message`
  returned the Standard message in Korean, and `update_settings` refused `custom_message`.
  The upgrade from v0.6.2 was performed with that earlier candidate, built before the review
  fixes: it kept the settings file byte for byte and every pending and history record, and
  its Dashboard showed the preserved history in Korean.
- **The popup, by hand**, on the earlier candidate. A person clicked the notification-area
  icon and the popup opened. With their permission Claude then drove the mouse and keyboard:
  a click opened it, Open Dashboard opened the Pending page and closed it, and a click
  elsewhere closed it. In a copy of the popup running against a stand-in control layer, real
  Tab, Shift+Tab and Space presses moved the focus ring and switched the focused button.
  Escape could not be pressed for real: while Claude's computer control was active, another
  process held plain Escape as a global hotkey, so no window received its key-down. The
  popup's Escape handling is covered by a test that delivers the key to the real window.
- **Not verified.** The popup was not driven by hand again on the final candidate. The High
  Contrast, right-click and minimize-and-restore fixes were not seen in a running window;
  they are covered by the build, by tests that run the window's own code, and by checks on
  its source. No Windows notification with Open Dashboard was raised, because no real
  interruption happened and none was made up. No Codex conversation was continued with the
  new messages, and the panel was not opened inside Codex. No real Codex visual recovery is
  claimed. The screenshots are rendered from sample data, not from anyone's conversations.

## v0.6.2 — The update could not check what it had downloaded

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.1...v0.6.2)

One fix, in the step that decides whether anything gets installed.

- **Fixed: the Dashboard's update downloaded the archive and then could not verify it.**
  The verification step used `Get-FileHash`, and on a real machine that cmdlet did not
  resolve in the process the update button starts, so the run ended with "'Get-FileHash'
  is not recognized as a cmdlet" and installed nothing. Refusing to install something it
  could not verify was right; naming a cmdlet as the reason was not, and the feature was
  unusable either way. The digest is now computed with the SHA-256 in the runtime
  PowerShell is already hosted in, so there is nothing left to autoload. `make_gui.ps1`
  had already moved off that cmdlet after meeting the same thing under the release
  runner's module path; the shipped script had not, and this is the second time it has
  cost something. Tests lift the function out of the shipped script and run it with
  `Get-FileHash` removed from the session.

  This does not repair an installation that already has the old script: the copy doing the
  updating is the one with the defect. Reaching a build with the fix means installing it
  the ordinary way rather than through the button.

## v0.6.1 — What running it for real found

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.6.0...v0.6.1)

Every change here came from the first live acceptance of v0.6.0: installing the published
archive on a machine somebody uses and watching it work. The published v0.6.0 archive and
tag are untouched - a correction gets a new version, which is what this is.

- **Fixed: a recovery that worked was recorded as a failure.** The engine read the status
  Codex puts on the recovery turn and nothing else. But the commonest way a recovery turn
  ends is the *next* usage limit, and Codex records the turn a limit interrupted as
  `failed` - so a continuation that was delivered, ran, and carried the task forward was
  filed as `recovery_failed`. Three real recoveries in a row, two of them recorded as
  failures, in the History, the statistics and the success rate. The outcome now asks the
  question the completed branch already asked - did this turn do anything? - and a turn
  that made progress is `recovered` whatever ended it. The raw status stays on the record
  and in the journal, so nothing is lost by calling the recovery what it was. Recovery
  itself was never affected: the chain continued correctly throughout, which is why only
  the reporting was wrong, and why the numbers a person reads were the part that lied.
- Require current, readable Codex projection data before a new continuation; never use
  an older database after a newer unsupported generation appears.
- Recheck pause, cancellation and conversation consent under the state write lock through
  queue-process launch. Release that lock before waiting for a receipt.
- Count repeated claims of one interruption toward the daily cap. Schema 3 retains only
  the latest claim timestamp, so the count deliberately errs toward waiting longer.
- Refuse unreadable or malformed installation journals before restoring or sweeping files.
  Keep an uninstall retryable after plugin removal fails or a root program file is locked.
- Reject malformed MCP envelopes and arguments before invoking controls. Do not show a
  successful save or pause change after a refused call; preserve acknowledged settings.
- Show the Dashboard's budget-reset explanation when the conversation is still disabled.
- Correct release wording, approval-hint claims and the English/Korean live procedure.

Live acceptance is incomplete, and the evidence for v0.6.0 does not carry over: evidence
belongs to one build, so the records that described v0.6.0 are kept as history under
`docs/evidence/live-0.6.0/` rather than inherited by this one. Of the fifteen steps there,
one passed and fourteen were blocked, because no genuine interruption was exercised in the
disposable acceptance conversation and no failure was fabricated to make one. The defect at
the top of this list was found outside that procedure, in ordinary use, which is its own
argument for running the procedure. No real Codex visual recovery is claimed.

## v0.6.0 — It follows its own turn, and it shows you the work

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.5.7...v0.6.0)

Two changes, and most of the rest follows from them. The engine no longer reads the
conversation for signs that a recovery worked: it follows the continuation it sent to the
exact Codex turn that continuation started, and reads the outcome from that turn alone. And
the window from the Start Menu, which was a settings page, now shows what the watcher has
seen and done — Overview, Pending, History, Statistics and Diagnostics, beside the settings
that were already there.

In short, and each of these has its own section below:

- **It follows its own turn.** A turn you started yourself can no longer be read as the
  recovery working, and an outcome that could not be established is called unverified
  rather than a success.
- **A Dashboard, not a settings page.** Six pages, and every one of them is now captured
  from the real window in both languages.
- **An icon in the notification area**, owned by the watcher itself, with a live countdown
  to the next check — and a route from its menu to the exact work that is waiting.
- **Safety gates and a timeline.** Why a recovery is waiting, in the same 22 public words
  everywhere, over a content-free journal that nothing reads back to decide anything.
- **History, statistics and a redacted diagnostics export**, none of which can carry a
  prompt, a reply, a path or an account.
- **It can tell you a new version exists** — when you ask it, never on its own — and
  install one through the same checksum-verified installer, keeping your pause, your
  per-conversation decisions and everything waiting.
- **Installing and repairing are harder to break**: a crash journal, a payload root copied
  by name, an upgrade that repairs without deciding anything, and a watcher handover that
  is checked rather than assumed.
- **The supply chain is checkable**: every Action pinned to a commit, the build split from
  the publish, reproducible executables, and a feature matrix that says for every capability
  what evidence it has actually earned.

The state file moves to schema 3 the first time the new watcher opens it. The last section
says what works in between.

### Recovery follows the continuation it sent

- **Fixed: a turn you started yourself could be read as the recovery working.** The engine
  called a recovery delivered once its message appeared anywhere in the conversation, and
  judged progress from any later turn — which can be a turn you started yourself. Each
  continuation carries a marker built from the interruption's own id; the turn it started is
  the turn of the history row that holds that marker, and a unique index in the state file
  makes it impossible for two records to own one Codex turn. The outcome is read from that
  turn and no other: recovered, no progress, failed, stopped by the user, handed over — a
  person started or joined that turn, or edited the queued message before it ran — or
  unverified, which is what an outcome that could not be established is called, rather
  than a success.
- **A failure of our own recovery turn is the same task failing again.** The record that
  follows continues its parent's chain instead of starting a new one: it inherits every
  counter in the one transaction that creates it, and is created already stopped when the
  parent was cancelled, was taken over by a person, or had used up a budget. By default one
  task gets at most six continuations; the setting that governs it accepts one to ten and
  nothing outside that.
- **Stable words for what a recovery is doing.** The engine's own vocabulary is 27 stored
  states in five classes, and the window and the Codex panel never show one of them: they
  read the same 22 public codes, and those never depend on a setting — a recovery that
  failed stays failed even if you raise the attempt limit afterwards. The command line
  still prints the stored state beside the code, for whoever is debugging a recovery.
  Facts about the surroundings that change what a waiting recovery will do next — recovery
  is paused, the conversation is switched off, the watcher is not ticking — are shown
  beside the code
  instead of folded into it, and never on a record that may already have been sent.
- **A journal, and a timeline that reads it.** What happened to a recovery is written down
  as codes, ids, counters and times; no prompt, no reply, no error text can reach it. The
  timeline shows one recovery's whole chain in the same words the lists use, rather than in
  the engine's state names. The journal is bounded at 5,000 entries and 90 days and never
  drops an entry belonging to a recovery that is still running, and nothing reads it back
  to decide anything — the decisions are made from the records.
- **Clear history hides and never deletes.** It changes the History view and nothing else.
  Anything that may still change stays visible — a recovery still running, an unconfirmed
  submission still being reconciled — and hidden rows still count for every cap, cooldown
  and duplicate check, which is what stops a finished failure from being detected all over
  again.
- **Cancel stops one task and everything that continues it.** A record that was never sent
  is cancelled outright; anything that may already be in Codex is marked, and the watcher
  takes back whatever is still queued. A turn already running in Codex is not stopped, and
  the confirmation says so. A record that has already finished is marked too, so no later
  failure of that task can start a new chain from it. Cancelling only ever reduces
  automation, so it does not need Codex to be running, and it is retried for up to thirty
  seconds rather than refused when the watcher happens to be writing.
- **Giving attempts back is explicit, limited, and not a send.** An exhausted recovery
  re-enters the wait its kind of failure needs, and every check runs again from the top. It
  does not switch a conversation back on: if that conversation is off, it says so and
  nothing will run until you switch it on. It can be done three times for one task, after
  which the window says to continue that task in Codex yourself.
- **Retry now is a re-check.** It brings the schedule forward and wakes the watcher. It
  does not send, does not skip the loaded-thread requirement, does not open a usage window
  and does not skip revalidation; a recovery whose usage limit has not lifted simply goes
  back to waiting.
- **Statistics, over the last 7 days, the last 30 or all of it**: how many interruptions
  were detected, how many continuations were sent, how they ended, the median wait before
  sending and the median time to recover, a count by kind, and how many times Retry now was
  used. One final outcome per record, so a late receipt moves a record from unknown to what
  really happened instead of counting it twice. The success rate appears only once five
  recoveries have ended in one of the outcomes it counts; below that it says there is not
  enough data yet.

### The window shows the work

- **Six pages instead of one.** Overview, Pending, History, Statistics, Diagnostics and the
  settings that were already there. They read the same control layer the Codex panel and
  the tools read, and the same state machine the command line reads, so the surfaces cannot
  disagree about what a recovery is doing.
- **No local web server, and nothing opens in a browser.** The pages are native controls,
  and the window talks to one long-lived bridge process — one JSON line per request — in
  place of a process per call. The whole Overview arrives in one round trip, with each part
  failing on its own: a state that cannot be read must not take the status away with it.
- **Every action names the conversation it acts on.** The lists refresh every five seconds,
  so a confirmation that named nothing could be answered about a record that had moved
  underneath it. Each action addresses a recovery by its exact interruption id, and each
  confirmation names the conversation.
- **Retry now is offered only where it can do something.** Not on a recovery whose usage
  reset is still ahead, not while recovery is paused, and not on a conversation that is
  switched off. Giving attempts back is gated differently, and deliberately: it is offered
  on a recovery that stopped at its limit, was not cancelled, and still has resets left,
  including while
  recovery is paused and on a conversation that is switched off, because it sends nothing
  — and where that conversation is off it says so, and that nothing will run until you
  switch it on. Once a task has had its three the button goes quiet and a note says to
  continue that task in Codex yourself.
- **A part that cannot be read is shown as unreadable, not as empty.** "Nothing is waiting"
  over a list that failed to load is the one wrong answer this page must not give:
  recoveries may well be waiting. Nothing that talks to the bridge runs on the window's
  thread, so a slow read cannot stop the window painting.
- **Diagnostics writes a file you can read before you send it.** Export diagnostics... on
  the Diagnostics page writes one JSON file where you choose. It holds the versions, the
  watcher's health, your settings, every record's state, reason and gates, the content-free
  journal and the last 300 lines of each log — enough to explain a recovery that went
  wrong. Conversation and interruption ids become aliases that hold together inside that one
  file and lead nowhere outside it, because the key is random and thrown away with the
  bundle; file-system paths, your Windows user name and anything shaped like an e-mail
  address are replaced. It sends nothing, and it refuses to overwrite an existing file. The
  exception is `errors.log`: it carries exception messages this product did not write, so
  they are redacted the same way but not filtered, and the file says so at the top. Once the
  file is saved, the window says so too: "Diagnostics saved. Ids are aliases and paths are
  removed; read the file before sharing it." `auto_resume diagnostics` writes the same
  bundle from the command line.

### Codex can turn automation down on its own; turning it up asks you first

- **Pause and resume are two tools, and only resume asks.** They were one tool,
  `set_auto_recovery`, that took the direction as an argument — and Codex runs a tool
  without asking unless it is marked destructive, so a conversation carrying someone else's
  instructions could undo your pause in silence. `pause_auto_recovery` still runs without a
  prompt, because pausing only ever reduces automation; `resume_auto_recovery` is marked
  destructive, and so now are `reset_recovery_budget`, `start_watcher` and
  `update_settings`. The prompt is Codex's to show, though: the mark is a request, not a
  lock. That is why `update_settings` offers only the settings the window and the panel
  offer, and refuses the advanced ones — which engine binary to run, how far back to
  look — even from a client that ignores the schema.
- **`get_status` no longer returns where this is installed.** It returned the installation
  directory, which normally contains your Windows user name, into a conversation Codex
  sends to OpenAI. Everything else it returns still goes there, and the skill's commands
  still print local paths; PRIVACY.md lists what each one says.

### Names, caches and replies that came from somewhere else

- **A mutex or stop event created by a lower-integrity process is refused.** Both have
  predictable names in the session namespace, where a Low-integrity process — a browser
  renderer, say — may create objects, and getting there first was enough: a planted mutex
  made every status read say a watcher was running when none was and made the real one exit
  as a duplicate, and a planted stop event made a real watcher quit at startup, silently. An
  object that already exists is now checked, and one labelled below Medium is refused: the
  status reads unknown rather than running, and the watcher refuses to run and writes why in
  its log. What it cannot do is recover anyway — while such a process holds the name,
  nothing at this level can — but it is no longer invisible.
- **The watcher launcher accepts only this product's marketplace.** With no installed
  application it fell back to the newest plugin of the same name in any marketplace's cache:
  another publisher's code, started at sign-in. It now fails closed and reports that it found
  no engine — which means someone who installed from a renamed marketplace has to
  reinstall, rather than have it quietly keep working.
- **The installer no longer upgrades every marketplace on the machine.** It ran `codex plugin
  marketplace upgrade` with no name, and without a name Codex refreshes every Git marketplace
  you have configured and reinstalls those vendors' plugins — other people's software,
  changed by an install that promised to touch only its own. It now names its own
  marketplace, which for the local one it registers does nothing at all.
- **A malformed reply can no longer end the window.** Its JSON reader had no depth limit, so
  a deeply nested document ended the process with a StackOverflowException, which .NET cannot
  catch and which leaves no message behind. It now fails at 64 levels as an ordinary format
  error, and so does truncated input.

### Both programs say which version they are

- **The two executables carry a version resource.** They reported 0.0.0.0, with no product
  and no publisher, in Explorer's Properties and in the SmartScreen and Smart App Control
  prompts — which is exactly where someone decides whether to trust a file they have just
  downloaded. Product, publisher, description, file and product version and copyright are now
  generated from `.codex-plugin/plugin.json`, so they cannot drift from the release, and
  because they are a pure function of the manifest they cost the build nothing that had been
  measured: two builds from fresh clones of one commit, on one machine with the same compiler,
  produced a byte-identical archive. That is all that has been shown - another machine has not
  been compared, and no archive published up to v0.5.7 is reproducible at all. The files are still unsigned: this is what a signature
  would have displayed, not a substitute for one.
- **The App Server client tells Codex its real version.** It introduced itself as
  `codex_auto_resume` version "0.1" in every release since the first, and now sends the version from the
  manifest. Codex reports `clientInfo` to OpenAI as the client's identity, so this changes
  what leaves the machine: the name was already going, and the number beside it is now true
  rather than wrong.

### The notification area shows it without opening anything

- **An icon is there while the watcher runs.** It belongs to the watcher process itself, so it
  cannot show a watcher that is not there: it appears when one starts and goes when it stops.
  Its tooltip says whether recovery is paused, how many recoveries are waiting, how many are
  running in Codex, and how long until the next check - counted down on your machine, and
  reaching zero only means the watcher looks again, not that anything is sent. Its menu opens
  the window, pauses or resumes recovery, and stops the watcher. It decides nothing itself:
  everything it offers goes through the same control layer every other interface uses. It is
  on by default and can be switched off in the settings.

### Pause and resume say one thing in Korean

- The Korean labels of pause and resume are now 자동 복구 일시 정지 and 자동 복구 다시 켜기
  everywhere. The window's and the Codex panel's buttons said 복구 일시 중지 and
  복구 다시 시작; both were brought to the words the notification-area menu already used.
  English is unchanged.

### An upgrade repairs; it does not decide

- **Fixed: an upgrade switched automatic recovery back on.** Plain `setup` runs the engine's
  `enable`, so upgrading over an installation whose owner had paused recovery switched it
  back on, silently, under the name of an update. The installer now runs setup with
  `--keep-state` whenever the program directory is already there, and the bootstrap does the
  same on the branch that skips the download because the installed version already matches.
  A first install still enables recovery: there is no decision to preserve, and it has to
  end up watching or nothing is.
- **Fixed: an upgrade put back a sign-in start that had been removed.** With `--keep-state`,
  setup re-registers the sign-in entry only when the entry registered is already this
  installation's — which still repairs its path after the runtime moves — and adds none
  where there is none.
- **Fixed: an interrupted copy was swept away by the next run.** The installer moves the old
  `app\` and `runtime\` aside before copying the new ones over, and the first thing the next
  run does is delete every `*.old-*` directory it finds. A power cut between the two left
  the only complete copy under exactly that name, so the recovery attempt was what destroyed
  the installation. The names every tree will be moved to are now decided before the first
  move and written to a small JSON journal at the installation root — written to a temporary
  name and moved over the real one, so a crash during the write leaves either the previous
  journal or none. The next run reads it before it sweeps anything: it puts back a tree
  whose target is missing, checks both ends of every move against the installation it has
  already proved is its own, and keeps the aside copies the journal still accounts for until
  this run has written a complete one. The journal is deleted once both trees are in place,
  and deliberately left behind when a run fails, because the roll-back is best effort and
  that file is then the only record of where a tree went.
- **Fixed: whatever sat at the payload root was copied into the installation home.** It was
  a wildcard copy, so a stray file in a release went straight into the home, including names
  this product reads as proof that the home is its own (`runtime.json`,
  `.owned-by-codex-auto-resume`) or as state. The two files that belong there — the settings
  window and its icon — are now copied by name, and a payload missing either fails the
  install before anything is moved. The bootstrap's archive check refuses an archive that
  carries anything else at that root.
- **Repair in the window says which of five things happened**: it finished, it is still
  working, another installation or repair is already running, this installation is missing
  the files setup is made of, or it failed — and only the failure carries the last few lines
  setup printed, with the line that is a path dropped. It takes the installer's own lock, so
  two processes cannot rewrite the same registrations at once, and a setup still working
  after two minutes is left to finish in the background rather than killed halfway. It runs
  setup with `--keep-state`, so a repair never undoes a pause or re-adds a sign-in start.
- **Stop watcher is now in the window and on the bridge.** The upgrade-pending message tells
  you to use Stop watcher and then Start watcher; Start was there and Stop lived only in the
  command line, which is the one place a person who uses the window never goes. It is the
  same named stop event the watcher already waits on, signalled once. It asks and never
  kills: a watcher stopped in the middle of submitting a continuation could not prove
  afterwards whether it sent, and a continuation that may have been sent is never sent
  again. It then waits ten seconds for the single-instance mutex — the same probe everything
  else calls "running" — and reports what that said: stopped, still finishing the check it
  is in, not running, or unknown. Unknown is its own answer and is not rounded up to
  stopped.

### It can tell you a new version exists, when you ask it

- **New: Check for updates, in Diagnostics.** Until now nothing in the product knew a newer
  release existed; a person found out by visiting the repository. The Diagnostics page now
  has a button, and `scripts/bootstrap.ps1 -CheckOnly` does the same from a command line.
  Nothing checks on its own: there is no timer, no check when the window opens and no check
  when the watcher starts, because a request to github.com is a request the person's machine
  makes and it should be one they asked for.
- **The answer comes out of a URL, not out of a page.** The check is a `HEAD` request to
  this repository's `releases/latest`, so no page is transferred and none is parsed. The
  version is read from the address the redirect ends at, whose path has to begin with this
  exact owner and repository — a fork, a mirror, or an owner whose name merely starts with
  this one is refused — and is then rebuilt from its three numbers, so what reaches a
  download URL is arithmetic rather than text somebody else chose.
- **Four answers, and four exit codes.** Up to date, an update is available, this build is
  ahead of everything published, or the question could not be asked. The last one is its own
  answer and never becomes "up to date": a machine with no network being told it is current
  is the one wrong thing an update check can say. The window believes an answer only when
  the exit code and the printed line agree.
- **Update reuses the installer rather than adding a second one.** It fetches that release's
  archive, checks it against the checksum published beside it, checks the archive really is
  this product at that version and that no entry escapes the extraction directory, and then
  runs the same `install.ps1` every install runs — which moves the old trees aside, keeps its
  journal, and runs setup with `--keep-state`, so a pause, a per-conversation decision, the
  pending recoveries, the history and the sign-in choice all survive it. A release published
  after this plugin was written cannot have been pinned before it existed, so an update is
  normally verified against the published checksum rather than a pinned digest, and the
  script says which of the two it did.
- **Fixed, before it could ship: an ordinary run after an update installed the older
  version back over it.** An update leaves the machine ahead of the plugin tree it was
  started from, because Codex's copy of the plugin is still whatever version it fetched.
  The next ordinary run of the setup script - which Codex may make on its own - saw a
  version the machine did not have and installed it, over a newer one, silently. An
  installation at the same version or a newer one is now converged rather than replaced,
  and going back happens only when `-Force` asks for it.
- **Whether the watcher actually changed hands is checked, and said.** A still-running old
  watcher reads its version out of the files underneath it, so it starts reporting the new
  version the moment they are replaced. The window compares the watcher's process identity
  and start time across the update instead, and says plainly when the watcher running
  afterwards is the one from before.

### The notification area points at the work, and does not act on it

- **The menu offers a route to what is waiting.** While something is waiting, the icon's
  menu has an item that opens the window on its Pending page, where Retry now, Cancel,
  the timeline and the per-conversation switch are, each naming the conversation it is
  about. Retry now and Cancel are deliberately not in the menu itself: a context menu
  built from a list the watcher is still changing acts on whichever record an id meant
  when the menu was drawn, and a menu item has nowhere to put the name of the
  conversation - which is the thing that stops somebody cancelling the wrong task.
- **The window is only ever opened on a page it has.** The page name reaches a command
  line, so the list of pages it may be is closed, whatever a caller passes.

### The release workflow, the first time a tag actually reached it

- **Fixed: the job that builds a release checked out no tags, and the suite it runs reads
  them.** Four tests build a database with the store code of a real tagged release - the
  upgrade and downgrade paths are tested against the bytes those releases actually shipped,
  not against a description of them - so a checkout without tags makes eight tests fail,
  with the message "CI must fetch the tags". `test.yml` and `sync-ko.yml` had fetched them
  since those tests were written; `release.yml` had not, and nothing noticed for two
  releases because a dispatch stops before publishing and no tag had ever reached the job.
  The first real tag push failed there. Nothing was published: the build job failed, the
  publish job never ran, and the release did not exist to be half-made. The workflow now
  fetches the history, which costs history and not privilege - the token is still not left
  on disk and the job still holds read access only - and a test requires every workflow
  that runs the suite to check out the tags the suite reads.

### Between the old watcher and the new one

- The state file is migrated 1 → 2 → 3 in one transaction, only by the watcher or by a
  caller holding the watcher's mutex, and a copy of the old file is taken first for
  forensics rather than as a restore path.
- Until that happens — between an upgrade and the moment the old watcher exits — the
  interfaces still do the things that only reduce automation: pause, switch a conversation
  off, and cancel a conversation's recoveries the way v0.5 did, thread-wide. Everything else
  says an older watcher still owns the state, and the window shows that sentence where a
  list would be rather than an empty list.
- `downgrade-state --to 2` rewrites the state for a v0.5 release with every interruption
  row kept — cancelled, exhausted, unknown and hidden ones included, because those rows
  are what stop an old failure from being detected and recovered a second time. It keeps
  the rows, not everything about them: the journal and the watcher's own status table are
  dropped outright, and the columns schema 3 added — which Codex turn a recovery started,
  what it inherited from its parent, when history hid it — go with them, because schema 2
  has nowhere to put them. The schema-3 file is copied first, and that copy is the only way
  back.

## v0.5.7 — Security fix

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.5.6...v0.5.7)

A security release, shipped on its own rather than held for v0.6.0, because it closes
a code injection present in v0.4.0 through v0.5.6. Recovery, settings, state and the
install layout are exactly v0.5.6's. Upgrading is the whole remedy - and, as of this
release, an upgrade replaces the running watcher, which is what makes that true.

### Security

- **Fixed: a folder or conversation name could run PowerShell commands.** Affects
  v0.4.0 through v0.5.6; earlier releases put only fixed text, a time and a short id into
  that script. Notifications and the Start Menu shortcut are
  written with a short Windows PowerShell script, and each value - the conversation's
  name, its project folder, the install path - was placed in that script as a quoted
  string with ASCII apostrophes doubled. PowerShell also treats `‘` `’` `‚` `‛` as
  single quotes, so a name containing one of them ended the string early and the rest
  of the name ran as PowerShell, from the watcher, under your account. An ordinary name
  such as `Bob’s project` was enough to stop the notification appearing; a crafted one
  was enough to run a command. Confirmed against the real interpreter before the fix.

  Values no longer become script text at all. They are handed to a constant script as
  environment variables and read with `$env:`, which PowerShell never parses as code,
  so there is no character a name could contain that changes what runs. The tests raise
  every quote-like and interpolation character through the real interpreter and fail
  on the previous code.

- **Fixed: an upgrade left the old watcher running the old code.** The installer renamed
  the program folders under the running watcher - Windows allows that - and the old
  process carried on from the renamed copy until the next sign-in, while setup saw it
  running and started nothing. For this release that would have meant the fix was
  installed and not in effect. The installer now asks the running watcher to stop
  through its own stop request, waits for it, and only then replaces the files; the new
  watcher starts at the end as before. It asks and never kills: a watcher stopped in
  the middle of sending a continuation could not prove afterwards whether it was sent.
  If it does not stop within a minute, the upgrade still completes and says plainly that
  the previous version is still running and how to switch. Measured on real Windows: a
  running watcher is handed over in under two seconds.
- **Fixed: Install.cmd and Uninstall.cmd could run a program planted next to them.** They
  started `chcp` and `powershell.exe` by bare name, and Windows looks in the current
  folder first - so a release extracted into a Downloads folder that already held a
  file called `chcp.bat` ran that file before the installer. Both are now started by
  their full path under `%SystemRoot%\System32`.

## v0.5.6 — Finished, not just working

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.5.5...v0.5.6)

The last v0.5 release, and a quality pass rather than a feature one. **Recovery is
untouched**: the same failure categories, the same refusals, the same exact-thread
identity rule, the same bounded retries, the same database. What changed is everything
around it — the two settings surfaces speak the user's language, the pictures show the
product as it is, and the Korean branch is a Korean branch.

It is also the first release to carry the fixes found after v0.5.5 was published. Those
were deliberately not used to mutate a released artefact; they ship here.

### The settings surfaces speak the language the rest of the product speaks

- **Fixed: the settings window and the Codex panel were English on a Korean machine.**
  The plugin layer resolved a language and used it for notifications and setup output,
  while the window carried its own English literals in C# and the panel carried a third
  set in JavaScript. Three copies of one vocabulary is how "Retry timing" becomes three
  different words. There is one catalog now — 79 keys, both languages — and neither
  surface chooses: the window asks the bridge it already uses, and the panel is handed
  its strings in the page it is already seeded with. Nothing consults
  `navigator.language`, because the four surfaces have to agree and only one of them can
  decide.
- **Fixed: with the window translated, the Korean arrived as mojibake.** The translation
  was correct and the bytes were not. Both front ends run the control bridge with its
  output redirected, and Python encodes a redirected stdout on Windows with the machine's
  ANSI code page — CP949 on a Korean install — while the window decoded UTF-8. The MCP
  server had always reconfigured its streams, which is why the Codex panel was right
  throughout and the window alone was wrong. The bridge now states UTF-8 rather than
  inheriting an encoding, so the protocol's contract belongs to the protocol. What made
  this worth tests rather than a one-line fix is that it hides: a machine with
  `PYTHONIOENCODING=utf-8` set runs the broken code perfectly, so it reproduces for users
  and not for whoever is looking for it — which is exactly what happened here. The round
  trip is checked under a deliberately hostile code page, in six scripts, because the
  contract is Unicode and not Korean.
- The language rule is unchanged and now has tests for the case it exists for: Korean
  when, and only when, the *most preferred* Windows UI language is Korean. Somebody whose
  interface is English and who has also added Korean is a person who reads Korean, not a
  person asking for a Korean interface.
- Retry timing's options are translated where they are shown and stored untranslated. A
  settings file whose meaning changed with the display language would be a bug the user
  could not see until the watcher read it back.

### The bottom row of buttons is drawn in full

- **Fixed: Restore defaults, Save and Close lost their bottom borders.** Reported by a
  user, reproduced, and it was not the buttons. The strip's height was a text measurement
  plus a constant, and the row inside it carries WinForms' default 3px margin, which does
  not scale with the display — so the arithmetic came out two pixels short and the last
  thing living in those two rows was every button's own border. Measured from a layout
  dump of the running window: strip 94 tall, 42 of padding, 52 given to a grid that
  wanted 54. The strip is measured from its content now.
- This is the same shape as the v0.5.5 Retry timing fix, one level up the tree. That fix
  is intact and re-checked.
- The two numbers under Limits no longer sit against the left edge of their boxes. A
  NumericUpDown paints its value hard against the frame, which reads as a number pushed
  up against the box rather than placed in it. WinForms offers the control no inner
  padding, so the space comes from the native edit underneath, through the message an
  edit control has always had for this — the value, its alignment, its range and what
  Save writes are all untouched, and the inset scales with the display like every other
  size in the window.

### The Codex panel looks like the product

- **Fixed: the panel screenshot was malformed, and the panel was why.** 550×494 collapsed
  the card grid to a single narrow column and was shorter than the content, so the image
  ended in the middle of a card with two cards and the entire footer missing. The height
  is measured from the rendered page now, the three cards flow in one grid instead of two
  hand-assigned columns that left one ending a third of the way up, and the pending table
  no longer spreads three short rows across the full width.
- The preview is given a host. Without one the panel correctly renders its read-only
  fallback — every control greyed, and a notice telling the reader to go elsewhere —
  which is a state nobody sees inside Codex. Nothing else about the render changed: it is
  still the exact resource Codex is served, and it is still described that way rather
  than as a photograph of Codex.

### One screenshot set, in the reader's language

- Screenshots are generated per locale and pinned to light. A light settings window above
  a dark panel did not look like one product, and a build on a machine in dark mode should
  not produce different bytes from a build on one in light mode. The runtime still follows
  the user's Windows and Codex themes; only the pictures are fixed.
- One picture is not pinned and cannot be: the notification is a real Windows toast, drawn
  by the shell in the machine's theme, so it is dark in a gallery that is otherwise light.
  The alternatives were to change somebody's Windows theme to take a photograph, or to
  draw a convincing toast in HTML and present it as one — a screenshot that is not a
  screenshot is worse than a mismatched one. `CONTRIBUTING.md` says how to retake it
  on a machine already in light mode.
- The Korean README shows the Korean interface. Korean prose over English screenshots was
  the documentation version of the settings window that would not translate.
- The panel gained the three theme states a themable page needs, so the capture can pin
  one without changing how the served page behaves anywhere else.

### The dark theme was rebalanced, and one part of it was declined

- The canvas and the surface were four points of lightness apart, so a card did not read
  as a card; the hairline was darker than what it enclosed, which is the wrong direction
  on a dark ground; and the cyan sat at full saturation on an 11px dot that was the
  brightest thing on screen. Same brand, less of the loudest part of it visible at once.
- **The standalone window stays light, and that is a measurement.** A probe painted a
  card, a NumericUpDown, a ComboBox, a CheckBox and a Button in the dark palette: the body
  went dark and the parts Windows draws did not, leaving three white rectangles in an
  otherwise dark window. Fixing that means owner-drawing every native control, and a
  half-dark window is worse than an honestly light one.

### The Korean branch is Korean

- **Every human-facing document is translated.** `CHANGELOG`, `CONTRIBUTING`, `PRIVACY`,
  `SUPPORT`, `docs/BRAND` and `docs/PLUGIN` join the six that were already there. The
  `not_yet_translated` list is gone, because a list of documents nobody has got to is
  indistinguishable from a list of documents nobody will. What stays English is named with
  its reason: the licence, because a translated licence is a second licence, and the Codex
  skill, because it instructs Codex rather than a person.
- **A translation cannot go stale quietly.** The English source each Korean document was
  translated from is recorded, and CI fails naming both files when the English moves.
  Nothing is machine-translated — a person decides what the Korean says, then records it.
  This is the documentation half of the screenshot freshness check, and it exists because
  ko told Korean readers the tool made no network request for three releases after it
  started making one.

### Around the repository

- The five issues opened against earlier versions are closed, each re-verified against shipped
  code rather than against the changelog. The repository has a description, topics and
  Discussions; `SUPPORT.md` now names the second door, because a question that is not a bug was
  previously only offered a bug tracker.

### Carried from after v0.5.5

- The installer no longer ends with "Installed and running." whatever the watcher did.
  Setup returns a third result for "everything was done, but the watcher was not seen
  running", which is neither success nor failure.
- The screenshot freshness check now covers the whole read path the window renders from,
  and hashes text after newline normalisation so a clone can reproduce the digest.
- The Korean sync no longer rewrites inside code fences, checks anchors as well as paths,
  lists files in a way that survives spaces and non-ASCII names, and cannot be disarmed by
  a stray local run.

## v0.5.5 — Say only what you checked

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.5.4...v0.5.5)

The last corrective release before v0.6. **Recovery is untouched** again: the same failure
categories, the same refusals, the same identity rules, the same bounded retries, the same
database. What changes is that several things which had been quietly asserting rather than
checking now check - and that the Korean branch stops being a second copy of the product.

### The watcher is reported as running only when it is

- **Fixed: starting the watcher claimed success it had not verified.** `start_watcher`
  returned as soon as Windows created a process, which proves nothing about whether the
  watcher survived its imports, took the single-instance mutex or stayed alive. Four
  surfaces turned that into a statement of fact, and the contradiction showed: the MCP
  tool said "The watcher is running." and the very next status said it was not. It now
  waits for the same probe the status line reads — on a monotonic deadline, in several
  short looks — and reports which of four things actually happened: running, already
  running, started but not confirmed, or started and exited. Only the first two are
  allowed to mention a running watcher, and a test enforces it. Measured here, the
  ordinary case now answers in about a third of a second, where the settings window used
  to sleep a fixed 1.2 s and hope.
- The watcher also now retries a momentarily busy mutex once before concluding another
  watcher owns the machine. Every status read takes that mutex for microseconds to test
  it, and a check must not be able to convince a starting watcher that it lost a race to
  itself. A real second watcher holds it for its whole life, so single-instance safety is
  unchanged.
- The settings window makes that wait somewhere other than the UI thread. Removing the
  fixed sleep had moved the wait into the bridge call rather than removing it, and a
  six-second block on a click handler is a window Windows greys out and retitles. It now
  dispatches to a worker and comes back through `BeginInvoke`; measured by forcing the
  full window, 11 of 24 samples were unresponsive before and 0 of 48 after.

### Screenshots that cannot go stale quietly

- **Fixed: every screenshot showed v0.5.2**, three releases behind, because there was no
  script that made them — only a sequence somebody had to remember. `build/make_screenshots.py`
  now renders both from the working tree: the settings window from a scratch installation
  assembled out of `src/` and the manifest, and the Codex panel from the panel's own
  source with sample data built by the real control surface. There is no version number
  in the generator and no mock JSON on disk; change `.codex-plugin/plugin.json` and both
  images say the new version.
- The same picture is no longer *captured* twice. There is one canonical asset per
  screenshot and the documentation copy is generated from it — both files are still
  committed, and a test now requires them to be byte-identical, which is the point.
  `assets/screenshots.json` records what they were rendered from, so the suite fails when
  the sources move and the images do not.
- What "rendered from" means was itself wrong at first: a hand-written list of seven files
  that missed five which visibly change the pictures, and that fired on edits which cannot
  change a pixel. The panel is no longer hashed from a file list at all — it is hashed
  from the markup it renders, so the version, the schema, the fields a row carries and the
  palette all reach it wherever they live, and a comment cannot fire it. Text inputs are
  hashed after newline normalisation, because `.gitattributes` gives `*.ps1` a different
  byte sequence on checkout than the repository stores.

### The Retry timing control is drawn in full

- **Fixed: the Retry timing box lost its bottom border at every display scaling above
  100%.** Not a drawing bug: a ComboBox under-reports its height until it is shown, then
  resizes itself to fit the font while keeping the position it was given, so it hung past
  the bottom of its own row — by 2 px at 125% and 9 px at 250% — and a child is clipped to
  its parent. The editor is now anchored to the top, and the row reserves the editor's
  measured height, which also puts the label back on its centre line.

### The Korean branch is generated, not maintained

- **Fixed: `ko` was three releases behind, and wrong in the ways that matter.** It was an
  independent fork carrying its own engine, installer, workflows and tests, kept in step
  by someone remembering to merge. It still told Korean readers the tool made no network
  request, still led installation with "download the release archive", still said there
  was no third party to report a security issue to, and still described an uninstall that
  predated every ownership rule v0.5.4 added. Its README linked to itself for the English
  version.
- There is no second copy now. `ko` is main's tree at a commit whose tests passed, with
  each Korean document put in place of its English sibling. `.github/workflows/sync-ko.yml`
  does it automatically, from the SHA that was actually tested rather than whatever main's
  head is by then, and it refuses a run from a fork or from a red main.
- The Korean text moved to main where it can be reviewed. `SECURITY.ko.md` had its three
  false claims corrected and its six-line uninstall section replaced with the current
  ownership rules before it was carried; `README.ko.md` gained the requirements, the
  two-watchers refusal, the safety model and the known limitations, so a Korean-only
  reader is no longer sent to the English page for them. `docs/PLUGIN.md` and the
  changelog are listed as untranslated rather than shipped stale — an English page is
  accurate, and a stale translation is not.
- The tests reach `ko` and now run there. They were carried unchanged, which was true of
  the files and false of the outcome: the sync deletes the Korean sources twelve of them
  read, so the suite errored on the branch it ships to and a pull request opened against
  `ko` was answered with failures about the wrong thing. Those tests skip on a generated
  checkout, and the workflow runs the suite against the tree before publishing it.
- Links to a Korean document are rewritten in both halves, target and visible label, and
  across every page rather than only the five that are translated — `CHANGELOG.md` had
  been shipping to `ko` with a live link to a file the same sync had just deleted. The
  generated tree is now checked for relative links to files it does not contain.

### Housekeeping

- **Fixed: 83 tests were skipped for anyone running a test file directly.** Six files kept
  their `unittest.main()` guard in the middle, so the classes below it never existed by
  the time it ran. `unittest discover` was never affected, which is why nothing said so.
- Both workflows now declare a concurrency group. The release workflow's refusal to
  republish a version reads the release's assets and then uploads, which two runs of the
  same tag could both pass; serialising by tag closes that window.
- Bumping the product version no longer turns the suite red for a reason that is not about
  the product: `scripts/release.json` no longer needs a placeholder entry added by hand.
  What it does check now is the direction that matters — that a version which was released
  did not stay unpinned.

## v0.5.4 — Prove it before you delete it

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.5.3...v0.5.4)

The final v0.5 hardening release. **Recovery is untouched**: the same failure categories,
the same refusals, the same identity rules, the same bounded retries, the same database.
What changes is that installing, updating and removing this product now act only on things
they can prove belong to them.

Four of the five issues this closes were the same mistake in different places — a *name*
being taken as evidence of ownership. Reviewing the fix for one of them found the same
mistake, unreported, on the install path, where it was worse.

### Nothing is destroyed without proof of ownership

- **Fixed: installing had no ownership check at all.** Issue #1 was reported against the
  uninstaller, and fixing only that left the more dangerous half in place: the install
  path also sweeps `*.old-*`, moves `app` and `runtime` aside and then deletes what it
  moved — under the same environment-variable root, with no check. The uninstaller would
  refuse a stranger's directory while an install into that same directory deleted their
  files and finished with "Installed and running." (Reproduced, on a directory holding
  real files, before and after the fix.) The install path cannot ask the uninstaller's
  question — the first install of all happens into a directory that is not ours yet — so
  it asks the other half: a directory already holding `app`, `runtime`, `config`, `logs`
  or a set-aside copy, with no proof any of it is ours, is refused and left untouched; a
  directory holding none of them has nothing to destroy and is claimed *before* the first
  file is written. Every deletion in the installer now goes through the one gate, and
  there is a test that fails if a new one does not.
- **Fixed: the uninstaller could delete directories it never created.**
  ([#1](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/1)) The
  installation root comes from an environment variable, and the PowerShell uninstaller
  removed `app`, `runtime`, every `*.old-*` and — with `-Purge` — `config` and `logs`
  beneath it, with no check at all. Pointed at a directory that merely *contained* folders
  with those names, it would have deleted them. Now the root has to be one we created, and
  the answer comes from the engine's own provenance rule rather than a second
  implementation in PowerShell that could drift from it. Every path is then re-checked
  against the canonical root before deletion, resolving each component, so a junction
  inside the installation cannot redirect a recursive delete out of it.
- **Fixed: the installer force-stopped any process named `codex-auto-resume-mcp.exe`.**
  ([#2](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/2)) A
  filename is not ownership: another installation, a build, or a test fixture running under
  that name was killed by an unrelated install. The executable's resolved path now has to
  lie inside this installation or this plugin's own Codex cache, and a process whose path
  cannot be read is skipped — not being able to tell is not permission to kill.
- **Fixed: uninstall removed the Codex marketplace by name.**
  ([#5](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/5)) If you had
  repointed `codex-auto-resume-windows` at a fork of your own, removing this product took
  your configuration with it. Both the marketplace and the installed plugin are now checked
  against where they currently point, read from `codex plugin marketplace list --json` and
  `codex plugin list --json`, and left alone with an explanation when they are no longer
  ours.
- The same rule already covered the sign-in entry, the notification identity, the Start
  Menu shortcut and the notification handler as of v0.5.3.
  [SECURITY.md](SECURITY.md) now states it once, for every kind of resource.

### Removing says what actually happened

- **Fixed: a removal Codex refused was reported as a removal.** The plugin and marketplace
  removals threw their exit codes away, so when Codex declined — it holds the plugin cache
  open while the app is running, the same refusal the install path handles by name — the
  uninstaller deleted the program files anyway and printed "Removed." over the top, leaving
  Codex pointing at a directory that no longer exists. Both are now checked, and the branch
  no longer ends on an unqualified success.
- **Fixed: a purge that could not finish could not be retried.** When files were still in
  use, uninstall correctly stopped and asked you to close Codex and run it again — but it
  had already deleted the proof of ownership the retry needs, so the second run refused the
  half-removed installation and there was no way forward. The proof is now the last thing
  to go, after the step that can still stop the run.
- **Fixed: `powershell -File build/make_gui.ps1`, the command `CONTRIBUTING.md` gives, did
  not work.** `$PSScriptRoot` is empty while parameter defaults are bound, so the two
  defaults derived from it threw. Invoked the other way — which is how CI does it — it
  happened to work, so only the documented route was broken.

### A published version is immutable

- **Fixed: a published release asset could be replaced.**
  ([#4](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/4)) The
  workflow had a path that rebuilt an existing tag and re-uploaded over its assets. Since
  the plugin's bootstrap pins that version's SHA-256, a replacement would make every
  install of that version fail — or, worse, succeed with bytes the digest does not
  describe. Publishing now refuses outright if the version already has assets; a
  correction needs a new version. What remains of the manual dispatch is a dry run that
  builds and verifies but cannot touch a release.
- Published archives now carry **build provenance**, attested before publication, so a
  download can be traced to the workflow run and commit that produced it.

### Already fixed, now proven

- **[#3](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/3) was fixed
  in v0.5.3** by explicit Windows argument quoting. It now has regression evidence rather
  than a claim: every case the issue lists — a home with a space, a folder like
  `OneDrive - Company`, a trailing backslash, an embedded quote, a non-ASCII path — is
  round-tripped through `CommandLineToArgvW`, the function Windows itself uses to split a
  command line.

### Settings at high DPI

- **Fixed: the settings window clipped its own labels at 200% scaling.** Windows Forms
  scales the font and leaves explicit pixel sizes exactly as written, so the window kept
  its width while its text doubled. Every fixed size now scales with the display, and the
  window is additionally clamped to the working area, because 780 units at 250% is wider
  than a 1920-pixel screen. The DPI comes from Windows rather than from `DeviceDpi`, which
  reports 96 on a 192-DPI screen unless a .NET Framework opt-in this product does not ship
  is present — a fix written against it changes nothing, and there is a test saying so.

## v0.5.3 — Say what the network does, and close the v0.5 line

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.5.2...v0.5.3)

The last v0.5 release. **Nothing about recovery changes** — same failure categories, same
refusals, same identity rules, same database, same bounded retries. What changes is that the
documentation now matches the product v0.5.2 turned it into.

### The privacy wording was left behind by plugin-first install

Until v0.5.2 this project made no outbound request at all, and said so in the strongest terms
available. Then the Codex plugin became the recommended way in, and the plugin installs the
product by downloading its release. Those sentences became false on the same day, in five
files and two languages.

- **[PRIVACY.md](PRIVACY.md) is restructured** around the distinction that now matters: what
  the running watcher does, and what installing it does. The watcher's promise is unchanged
  and is still the strong one — nothing under `src/` imports a networking module, so it
  cannot open a connection even by accident. Installing from the plugin fetches one archive
  (and its checksum, when no digest is pinned) from github.com and nowhere else. It uploads
  nothing, but GitHub sees the request and counts the download, and this release stops
  implying otherwise. The release-archive route still touches no network at all.
- **Fixed: "Third parties: none."** GitHub is one, at install time.
- **Fixed: "the fact that you installed it at all" never leaves your computer.** On the
  recommended route it does.
- **Fixed: the tool launches more than `codex queue`.** It also runs `codex app-server
  --stdio`, two short interface probes, and PowerShell for the Restart Manager and toasts.
- **Fixed: it keeps state outside its own directory.** The sign-in value, the notification
  sender identity, the notification button's URL handler and the Start Menu entry are all
  per-user Windows registrations, and they are now listed where the storage is described.
- **Fixed: [SUPPORT.md](SUPPORT.md) pointed at a private security channel** that
  [SECURITY.md](SECURITY.md) says does not exist.
- **Fixed: `docs/PLUGIN.md` claimed nothing downloaded is passed to a shell** — while the
  bootstrap runs the installer out of the archive it has just unpacked. The claim that holds
  is narrower: nothing from the network is *piped into* a shell.
- **Fixed: the bootstrap's own header overstated what `-ArchivePath` checks.** A local file
  has no sidecar to fetch, so without a pinned digest for that version only the contents
  checks stand behind it. It now says which of the three cases it took.

### Install and uninstall bugs an adversarial re-audit turned up

None of these change recovery. All of them are cases where the product did something
other than what it said.

- **Fixed: the plugin was never registered for anyone whose user folder has a space in
  it.** `Start-Process -ArgumentList` joins its arguments with spaces and quotes nothing,
  so a marketplace path under `C:\Users\Example User\` arrived at `codex` as two
  arguments. Registration failed, the failure was only a warning, and the installer still
  ended with "Installed and running." The watcher and the settings window worked; the
  skill and the panel the user had asked for were simply absent. The installer now quotes
  the way `CommandLineToArgvW` reads back — the same rule the sign-in entry has used since
  v0.5.0 — verified by round-tripping through that function.
- **Fixed: "uninstall aborted before deleting any state" was true only of state.** The
  fail-closed check for a running watcher ran *after* the autostart value, the
  notification identity, the Start Menu entry and the toast handler had already been
  removed. Refusing therefore left an installation that still ran and still had pending
  recoveries, but no longer started at sign-in and could no longer show a notification.
  The check is now the first thing the command does.
- **Fixed: uninstalling one copy silenced another copy's notifications.** The Start Menu
  shortcut and the notification identity are per-user singletons at fixed locations, so a
  second installation overwrites them rather than adding its own — and they were removed
  with no ownership check, unlike the autostart and the URL handler beside them. They now
  get the same check, and say whose they were when they keep them.
- **Fixed: `Uninstall.cmd` threw away the exit code of the step that refuses to remove a
  running installation**, then deleted the engine and the interpreter anyway and reported
  success.
- **Fixed: uninstall reported "Removed." after a removal that half-failed.** With Codex
  open, its MCP server holds the bundled interpreter's images open and they cannot be
  deleted. The install path has stopped those launchers first since v0.5.1; the uninstall
  path now does too, and checks afterwards rather than swallowing the error.
- **Fixed: the plugin's setup script failed every download on PowerShell 7.** The check
  on where a redirect finally landed read a property that only exists on Windows
  PowerShell 5.1, and under `Set-StrictMode` reading the other one throws. It now reads
  either, and refuses if it can read neither.
- **Fixed: the repair path took no lock.** Re-running setup on an already-installed
  version skips the installer, so it skipped the installer's lock as well and could run
  beside one.
- **Fixed: the MCP launcher was the one component that ignored the install-home
  override**, so moving the installation left the panel unable to find it.
- **Fixed: running the test suite wrote a real registry entry.** One test class guarded
  the registry function by function and had missed `install_protocol`, so every run left
  a `codex-auto-resume:` handler in the user's own HKCU pointing at a temporary directory
  that no longer existed. It was found by an uninstall correctly refusing to remove a
  handler that belonged to "a different installation" — which it did. The class now fakes
  the registry module itself, the way the other test modules already did.
- Smaller hardening in the same script: the file the install actually executes is now in
  the required-contents list; an archive whose manifest differs only in letter case is
  refused rather than crashing; a manifest with no version at all gets the intended
  message; and the case where nothing could be compared no longer prints a tick and a
  hash beside it.

### One property was undocumented rather than overstated

Every `codex` subprocess this tool starts already runs with analytics off, every
OpenTelemetry exporter off, prompt logging off, and the ChatGPT base URL pinned so a stray
local configuration cannot send a continuation somewhere else. That has been true for
several releases and appeared in no document. It does now, and a test keeps it.

### Tests that stop this happening again

`tests/test_privacy_claims.py` asserts the code property the wording rests on — which files
may reach the network, and that the watcher's cannot — and then that no absolute network
claim stands without its qualifier nearby. The checks are shape-based rather than exact
strings, so a rewrite that is still true keeps passing. It guards the other direction too:
the changelog must keep a section for every released tag, so a future sweep for a retired
phrase cannot take the history with it.

### Smaller corrections

- The README no longer implies a screenshot of the Codex panel was photographed inside
  Codex; it is a render of the exact resource the plugin serves, and now says so.
- `watcher_launcher.py` still described the engine-resolution order from before v0.5.2.
- `make_release.py` called the archive byte-identical across builds, three lines from its own
  docstring explaining why it is not.
- The README claimed Python was needed to install the plugin from a marketplace. It is not —
  the setup script is PowerShell — and a duplicated sentence left over from v0.5.2 is gone.

## v0.5.2 — Install it from Codex, and look like one product

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.5.1...v0.5.2)

A patch release. Recovery is unchanged: the same failure categories, the same refusals, the
same identity rules, the same database. What changed is how you install it and what it looks
like once you have.

### Installing it from Codex actually installs it

Adding this plugin from a marketplace used to hand you a source tree and a skill whose first
instruction was to find any Python that would run. That produced a **second, lesser
installation**: a watcher registered against whatever interpreter answered, no settings
window, no panel, an engine loaded from the plugin cache — and if the machine already had a
real installation, both of them sharing one state directory.

- **The plugin now installs the product.** Ask Codex to *set up auto resume* and it runs
  `scripts/bootstrap.ps1`, which downloads the matching release, verifies it and installs it.
  Nothing has to be installed first: no Python, no administrator rights, no manual download.
- **What it is allowed to fetch is narrow on purpose.** One URL shape, built from constants
  and this plugin's own version — no "latest", and no input that reaches a URL, so a v0.5.2
  plugin can ask for the v0.5.2 archive and nothing else. HTTPS with TLS 1.2 minimum, and the
  final response has to come from GitHub.
- **It verifies before it runs anything.** SHA-256 against a digest pinned in the plugin when
  there is one and the published `.sha256` otherwise — it prints which of the two it used
  rather than implying the stronger one — then that the archive contains what a release is
  defined to contain, that its manifest declares this product at this version, and that no
  entry escapes extraction. Any failure deletes the download and stops. Checked against a
  file that is not an archive, a genuine archive declaring the wrong version, and a correct
  archive against a wrong pinned digest.
- The README now leads with the Codex route and keeps the archive route for anyone who would
  rather nothing downloaded on their behalf. Both end at the same installation.

### One installation, whichever way you arrive

- **Fixed: a plugin update could swap the engine underneath an installation.** The watcher
  resolved its code from the newest copy in the Codex plugin cache, by modification time, so
  installing a newer plugin from a marketplace silently replaced the running engine while the
  settings window still talked to the installed one. The installed application now wins.
- **Fixed: setup would configure a watcher with nothing to run it.** It now refuses unless the
  bundled runtime and the application are both present, and prints the command that installs
  them, instead of improvising a lesser installation.
- **Fixed: the sign-in entry could name a different interpreter from the installed one.** Every
  registration setup writes — autostart, the notification handler, the watcher itself — now
  names the interpreter the installer deployed.
- **Fixed: the installer ignored the state-directory override the Python side honours**, so
  setting it deployed to one place and configured another.
- **Two installers can no longer run at once.** A double-clicked `Install.cmd` and a plugin
  bootstrap used to be able to copy over each other's half-written payload.

### A new look

- **The green is retired.** The identity is a deep-blue to cyan ramp that carries the product's
  own behaviour: deep blue while it waits, cyan the moment it acts.
- **A new mark.** Four concepts were built and compared at all nine icon sizes on light and
  dark grounds — `build/icon_concepts.py` still renders the sheet — and the winner is an open
  ring with a bright head at its leading end: the ring is the wait, the gap is the
  interruption, the head is the resume. There is a vector master at `assets/brand/icon.svg`.
- **The settings window and the Codex panel were redesigned together.** State leads on both
  now: what the watcher is doing is the first thing and the largest type, where it used to be a
  muted sentence along the bottom under sixteen checkboxes. What is waiting to resume comes
  before what is configured, and the cards run in the order the argument does — what may be
  recovered, how hard it will try, what it will tell you, when it starts.
- **The plugin card has artwork.** Codex has always validated an icon, a light and dark logo
  and screenshots; this project never supplied any of them.
- **Fixed: white text on the panel's dark-theme accent measured 2.6:1.** Found by a contrast
  assertion, not by looking at it. Text drawn on the accent is now its own colour, and it goes
  dark exactly when the accent goes light.
- **Fixed: the panel asked for a colour variable the generator never emitted.** That is not an
  error in CSS — the declaration is dropped and the text quietly inherits.

### One palette instead of four

Four surfaces carried their own copies of the colours — the settings window in C# literals,
the panel in a stylesheet, the icon renderer, the plugin manifest — and they had already
drifted. The palette now lives in one module; `gui/Brand.cs` and the panel's stylesheet are
generated from it, and tests regenerate both and compare, so a hand-edit fails the suite
instead of shipping. A test also sweeps every tracked file for the retired colours, because
that is how a colour survives a rebrand: in a document nobody reopened.
[`docs/BRAND.md`](BRAND.md) records the decisions.

## v0.5.1 — Say what the product actually is

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.5.0...v0.5.1)

A patch release. No change to how recovery works, what it will retry, or what it refuses to
retry. What changed is everything around that: the documentation was describing a version of
this project that no longer exists, and the install instructions contradicted the installer.

### Documentation that matches the product

- **Fixed: the one-click install told you to put Python on your PATH.** That archive exists
  precisely so you do not need Python — it carries its own runtime. The recommended install is
  now three steps at the top of the README, with no prerequisites, and Python appears only where
  it is genuinely needed: a source checkout, or installing the plugin straight from the
  marketplace.
- **Fixed: "there is no tray icon, no settings window, no management web UI".** Two of those
  stopped being true in v0.5. The project direction now says what is deliberately built — a
  Windows settings window, a panel inside Codex, the command line, notifications — and what is
  still deliberately refused: a tray controller, a management web UI, a supervisor, a service, a
  second recovery engine, a second database.
- **Fixed: the supported Python version was never the tested one.** Setup refused anything below
  3.10 while CI only ever ran 3.12 and 3.13, so two Python releases were accepted by the
  installer and never tested. The floor is now the lowest version that is actually tested, and a
  test ties the installer, the message the user sees, the skill and the bundled runtime together
  so they cannot drift apart again.
- The README opens with the problem and the download instead of the implementation, and states
  the loaded-conversation limitation in the same breath rather than further down.

### New public documentation

- **[PRIVACY.md](PRIVACY.md)** — what is read, what is stored, and the short answer to what is
  sent anywhere: nothing. No telemetry, no analytics, no update check, no outbound requests.
- **[SUPPORT.md](SUPPORT.md)** — where to report each kind of problem, what to include, and what
  not to paste into a public issue.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to run the tests and build a release, the fixture
  conventions, and the safety properties a change has to keep.
- **[README.ko.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/ko/README.md)** — a Korean
  README, linked from the English one.

### Repository hygiene

- A new check keeps local development environment out of the repository: home directories in
  examples must be placeholders, UUIDs in tracked files must be recognisably synthetic, and
  runtime state is never tracked. The rules describe what a fixture may look like rather than
  listing values, so the check cannot itself become a place where such values live.
- Test and documentation fixtures use the documented placeholders throughout.

### Packaging

- Plugin metadata describes the product in the words people actually search for, and the
  manifest, the skill and the release now agree on the version.

### Unchanged on purpose

Recovery is exactly as conservative as it was in v0.5.0. Same failure classification, same
bounded attempts, same fail-closed behaviour on anything unrecognised, same exact-conversation
identity, same refusal to resend a submission whose outcome is unknown. Codex still has to have
the conversation open for a recovery to be delivered; that limitation is unchanged and still
documented.

## v0.5.0 — Settings you can find, and a notification that says who it is from

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.4.1...v0.5.0)

### Settings, in three places, meaning one thing

- **A standalone Windows settings window**, on the Start Menu. It works with Codex closed, the
  plugin unloaded, the MCP server unavailable, no network, no sign-in and no system Python -
  because configuration matters most exactly when the thing it configures is unavailable.
- **A settings panel inside Codex**, over a plugin-declared MCP server. Ask to open auto resume
  settings and it renders in the conversation.
- **The command line**, unchanged.

All three read and write through one validated layer, so a value set in any of them is the value
the others show. That layer is also the fix for a real bug: the watcher used to have its own
settings reader that understood three of the sixteen fields, and a matching writer that persisted
only those three - so `enable --lookback-hours 8` silently erased every recovery category and
notification preference. There is now one reader and one writer.

### The settings finally govern the watcher

The schema described policy that nothing read. Now the engine adopts it: categories switched off
are never recorded, so nothing is scheduled, attempted or announced for them; the transient
backoff follows the chosen timing preset; and the attempt and no-progress budgets come from the
settings. Changes are picked up on the next poll, without restarting anything.

Policy stays policy. Everything a settings file can touch runs through the same coercion, so the
worst a hand-edited or hostile one can do is make recovery *more* conservative - and the engine's
safety limits are not in the schema at all. There is still no setting that retries an unclassified
failure, resolves a conversation by title, resends an uncertain submission or forces a send.

### Notifications that say who they are from, across the whole lifecycle

- **Fixed: Windows attributed our notifications to PowerShell.** They now show **Codex Auto
  Resume** with this project's own icon. That needs two registrations, not one: an
  AppUserModelID supplies the name and icon, and a Start Menu shortcut carrying the same id is
  what makes Windows *draw* the toast. Without the shortcut the platform accepts it, logs it, and
  files it in the notification centre without ever showing it. Found by looking at the screen
  rather than at the event log, which had said "delivered".
- Three more notifications join the first: recovery starting, how it turned out, and recovery
  stopping for good. Each is raised once, from the state change itself, so the notification and
  the record cannot disagree. An uncertain submission is reported as uncertain, never as a
  failure that will be retried.
- Each event has its own switch, plus a master switch, read at the moment of the event.

### Recovery

- **Fixed: an exhausted recovery could not be given its attempts back.** Running out of attempts
  leaves a record in a terminal state, and terminal records may not be reactivated - the guard
  that stops a finished, cancelled or uncertainly-submitted recovery from being restarted by a
  stray write. Resetting the budget therefore raised instead of resetting. Rather than widen that
  guard, the one stop a person may undo now has its own operation: it accepts only the two
  exhausted states, refuses anything cancelled or carrying any sign of a submission, and clears
  the budget and nothing else. The record re-enters the queue as a candidate and every gate runs
  again.
- **Retry now** brings a waiting recovery's next attempt forward. It is not a send: the watcher
  still revalidates, still needs the conversation open, still waits for usage, and still refuses
  anything uncertain.

### The usage-limit checkbox, re-investigated from scratch

Re-checked against `codex-cli 0.153.4` and ChatGPT desktop `26.901.5280.0`. The answer has not
changed: the notice is assembled from compiled message ids inside the Electron bundle, and no
manifest field, MCP surface or hook can address it. A Codex-native form at the moment of the
interruption is now technically possible and is still not shipped, for a stated reason rather
than a technical one - it would push a form into whatever conversation happens to be open, about
a different one that failed, only when Codex is running, and only where a remote feature gate is
on. Nothing was faked in its place. See [docs/PLUGIN.md](PLUGIN.md).

### Three ways an install could quietly stop working

All three were found by using the product on a real machine after a reboot, not by reading
the code. The watcher was not running, and the settings panel was the only thing that said so.

- **Fixed: the autostart command was never quoted.** `subprocess.list2cmdline` quotes only a
  token that contains a space, so an installation under a path without one produced a completely
  unquoted Run value. Under `C:\Users\Example User\...` Windows reads that as the program
  `C:\Users\Example`, and the watcher never starts at sign-in - whether the product works at all
  depended on what the user is called. Every command written to the registry is now quoted by the
  documented CommandLineToArgvW rules, including the notification button's protocol handler and
  the Start Menu entry.
- **Fixed: an upgrade could not replace an installation that was in use.** Codex keeps this
  plugin's MCP server running, which holds the bundled interpreter's DLLs open, and a loaded DLL
  cannot be deleted - so removing the runtime directory failed part-way and left the application
  updated with the interpreter gone. Windows does allow renaming a directory that contains an
  open file, so the old copy is moved aside and swept up later. Everything is moved before
  anything is copied, and a failure at either step puts the installation back exactly as it was.
- **Fixed: Codex could not update the plugin while it was running the plugin.** `plugin add`
  backs up the cache directory and failed with an access error, because the open file is our own
  MCP launcher, which lives inside the plugin - it has to, since Codex accepts only a contained
  command path. The installer now stops just its own launchers and retries once; Codex starts a
  fresh one when it next needs the server.
- The watcher launcher records that it ran before anything can fail, and catches everything on
  the way out. Under `pythonw.exe` there is no stderr, so an early failure left no log line, no
  event and no trace - which is why "did Windows start it and it died, or did Windows never start
  it" could not be answered at all.
- The settings window and the Codex panel offer to **start the watcher** when it is stopped,
  rather than reporting a dead end. It starts the same process the installer starts.

### Packaging

- The plugin now ships a small launcher so its MCP server can start from the bundled interpreter:
  Codex accepts a plugin command only as a bare name or a contained path, and a bare `python`
  would put back the system-Python requirement this product removed.
- That launcher relays the standard streams rather than letting the child inherit them. A child
  started with `CREATE_NO_WINDOW` and no explicit handles gets no usable standard handles, so the
  server waits for input that never arrives and the host waits for a handshake that never comes.

## v0.4.1 — Put the reason back in the notification

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.4.0...v0.4.1)

- **Fixed: the notification never said why it appeared.** Windows renders at most three
  `<text>` elements in a toast and silently drops a fourth, so the four-line layout lost its
  body line: the toast showed the task name, the project and the thread id, but not
  "Codex usage limit reached" or "Codex was temporarily interrupted".
  It now fits three lines - name, reason, then project and the exact thread id together -
  with the reason ordered before the identifiers, because a line that does not fit is lost
  and losing the reason makes the notification pointless. The thread id is still always shown.
  Found by looking at the actual notification, not the generated markup.

## v0.4.0 — Recover more, guess less, install in one step

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.3.2...v0.4.0)

### Recovery beyond usage limits

- **Clearly temporary failures are now recovered too**, on a policy of their own. The two
  are deliberately not merged: a usage limit waits for its real reset timestamp, a dropped
  connection waits on a bounded ladder (5s, 15s, 30s, 60s, 120s) and never longer.
- Classification is **structural, not textual**. It reads the `codexErrorInfo` variant Codex
  itself writes, then an HTTP status carried by that variant. A message is consulted only
  when there is no structured code at all, and only for transport failures that have no code
  (timeouts, DNS, TLS, broken pipe). A structured code is never overridden by message text.
- **Recovered:** usage limit, connection failure, timeout (408/425), transient rate limit
  (429), server errors (500-599, `serverOverloaded`, `internalServerError`), stream
  disconnection.
- **Not recovered:** user cancellation, permission, approval, policy, invalid request,
  context length, permanent authentication (401/403/`unauthorized`), `badRequest`,
  `sandboxError`, `responseTooManyFailedAttempts` (Codex already retried and gave up),
  and anything unrecognised.
- **Unknown is never retried.** An error this tool cannot place is never registered at all,
  so no later stage can act on it. This is the opposite of retrying by default, and it is
  the point: a missed recovery is cheaper than a wrong one.
- **Bounded budgets.** A transient chain stops after 4 recovery attempts
  (`retry_budget_exhausted`), and after 3 consecutive recoveries that produced nothing
  (`no_progress_exhausted`). Progress is judged from lifecycle metadata only: whether a
  later turn completed, and whether it recorded a final agent item. No message text is read.
- **The user always wins.** If a later turn exists on that exact thread - because the user
  carried on, or because Codex did - the old interruption becomes `superseded_by_user` and
  is never resumed on top of the newer work.
- Existing state upgrades in place. Pending recoveries survive the update.

### Notifications that say which task

- The notification now leads with a name a person recognises: the conversation title, else
  the project, else the working directory's name, else "Codex task". The **exact thread UUID
  is always shown** on its own line, because titles repeat and identity must not.
- Wording follows the failure: a usage limit says when it will resume; a temporary failure
  says it is retrying. One cancel button either way.
- Display names are read from `threads.name` only. On this schema `title`, `preview` and
  `first_user_message` all hold the raw first prompt (observed at 67 KB, multi-line), so they
  are never read. Labels are capped and must be single-line, so a schema change cannot turn a
  prompt into a notification.
- **Names are for display only.** Recovery still resolves nothing by title, project or
  recency; the exact UUID remains the sole identity.

### One-click installation

- `install/Install.cmd` registers the marketplace, installs or updates the plugin, checks for
  Python, and hands over to the plugin's own setup. It is a bootstrapper, not a runtime: no
  administrator rights, no service, no scheduled task, HKCU only, and it never deletes state.
  Re-running it upgrades in place. `Uninstall.cmd` reverses it, watcher first.
- Python is never downloaded or installed automatically; a missing interpreter is reported
  with a link and the installer stops without leaving anything running.
- Checked first and not available: this Codex build has no plugin install deep-link, and
  `codex plugin add` requires a registered marketplace, so the two commands cannot be reduced
  to one officially.
- Fixed while testing the installer for real: a single-result PowerShell pipeline is a scalar,
  so indexing it took the first character of the engine path; an already-registered marketplace
  kept a stale snapshot, so updates never arrived; the Python version probe's quoting did not
  survive argument passing; and setup compared the registered autostart by exact string, so
  upgrading Python made one installation look like two and setup refused forever.

## v0.3.2 — Make the login autostart actually start

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.3.1...v0.3.2)

- **Fixed: the registered sign-in autostart could never run.** The Run value ended in `run`, and
  the launcher appended `run` again, so the command died with an argument error at every login.
  It went unnoticed because starting the watcher from setup passes no arguments and worked fine.
  The launcher now treats its arguments as the command to run, defaulting to the watcher.
- **Fixed: the notification button broke on the next plugin update.** It was registered against
  the plugin's own directory, which is named after its version. It now goes through the same
  stable launcher as the autostart, so neither registration can be orphaned by an update.
- Both registrations are now checked by tests that parse the exact command that gets registered
  and feed it to the real argument parser.

## v0.3.1 — Keep the state out of somebody else's sandbox

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.3.0...v0.3.1)

- **Runtime state moved from `%LOCALAPPDATA%` to `%USERPROFILE%\.codex-auto-resume\`.**
  Setup may be run from a packaged (MSIX) host, and Windows silently redirects such a host's
  AppData writes into its own private `LocalCache`: the environment variable still reads as the
  normal path while the files land inside an unrelated application. Installing this way put the
  state, the logs and the autostart launcher inside another app's sandbox, where uninstalling
  that app would have taken them with it. The user profile root is not redirected, which is why
  Codex keeps its own state in `~/.codex`.
  Found by installing the plugin for real and reading back where the files actually went.

## v0.3.0 — A control at the moment it matters

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.2.0...v0.3.0)

- **Windows notification when an interruption is detected.** The watcher is running at that
  moment, so this is the one place a control can be offered in time; the Codex turn has already
  failed by then, so nothing can be added to the app's own usage-limit notice.
  The toast says when the conversation will continue and carries a single **Don't resume**
  button. Doing nothing resumes, which is the default.
- The button is handled through a per-user `codex-auto-resume:` URL protocol registered under
  `HKCU\Software\Classes`. It accepts exactly one action — cancelling — so a hostile URI can
  only ever stop a resume, never cause one. The interruption id is validated as opaque hex and
  must match a real record; nothing is resolved by thread name or recency.
- The toast shows only a shortened conversation id and a local time. Never prompt text, error
  text or account data. PowerShell is invoked with `-EncodedCommand`, so no message text can be
  reinterpreted as script.
- Delivery is best effort. A notification that cannot be shown, times out, or raises is logged
  and ignored; it never changes whether a resume happens.
- Turn it off with `"notifications": false` in `config/settings.json`.
- Fixed before release: the toast document was escaped as if it were an XML *attribute*, which
  turned its own angle brackets into entities and made every notification fail silently. The
  document is now embedded as a PowerShell string literal, and a test parses the document out of
  the command that is actually sent.

## v0.2.0 — Install and control it from inside Codex

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/compare/v0.1.0...v0.2.0)

- **Codex plugin.** The repository root is now also a Codex plugin root, with a marketplace index
  (`.agents/plugins/marketplace.json`), a manifest (`.codex-plugin/plugin.json`) and one skill.
  Install with `codex plugin marketplace add songyb111-gachon/codex-auto-resume-windows` followed by
  `codex plugin add codex-auto-resume@codex-auto-resume-windows`, then ask Codex to set it up.
  There is exactly one copy of `src/`; the engine ships with the plugin rather than being duplicated.
- The plugin is a thin front end over the existing command-line interface. It adds no MCP server, no
  second engine, no recovery logic of its own, and never queues a message to a thread.
- **Runtime state moved out of the plugin directory** for plugin installs, to
  `%USERPROFILE%\.codex-auto-resume\`. Plugin updates and removals no longer risk pending resumes.
  Autostart points at a small stable launcher that re-resolves the current plugin version at every
  launch, so an update needs no re-registration. Manual installations are unchanged.
- **Two installations are refused rather than merged.** A manual checkout and a plugin install keep
  separate state and separate single-instance locks, so both watchers would run and could each resume
  the same interruption. Setup stops when a different installation already owns the sign-in autostart.
- English by default; Korean only when Korean is the most preferred UI language, read from the same
  source the ChatGPT desktop app uses for its own display language. No language is inferred from an IP
  address, time zone, user name, country or keyboard layout.

### Fixed

- **`uninstall` deleted the Windows sign-in autostart value even when it belonged to a different
  installation**, silently disabling a watcher it did not own. It now unregisters only a value that
  starts the installation being uninstalled, and reports anything else as kept. Found by running the
  plugin's uninstall against an isolated home while a manual installation was registered.
- Setup no longer crashes on a legacy-code-page console: the check mark falls back to ASCII when the
  console cannot encode it.

### Not implemented, on purpose

- A checkbox inside the Codex usage-limit notice. There is no official plugin API that can place a
  control there, and the alternatives are all forms of injection or GUI automation this project does
  not use. No substitute GUI was built. See [docs/PLUGIN.md](PLUGIN.md) for the evidence.

### Also

- Survive Codex app updates instead of stopping at the first version change.
  - Local databases are discovered by schema generation (`state_5`, `thread_history_1`, ...) and
    validated by the columns actually read, so a generation bump no longer breaks detection. Extra
    columns are fine; a missing required column still refuses.
  - The exact engine-version equality check is replaced by a capability probe: a verified version is
    trusted, and an unrecognised one is accepted only when `codex queue` still offers `--thread` and
    `--message`. `status`, `doctor` and the watcher log say plainly when the engine is unverified.
- Report the engine pin actually in force in error messages instead of a hardcoded version.

## v0.1.0 — first public release

[The commits in this release](https://github.com/songyb111-gachon/codex-auto-resume-windows/commits/v0.1.0)

First public release of `codex-auto-resume-windows`, a local-only Windows watcher that resumes Codex
tasks interrupted by a usage limit.

### Included

- Usage-limit detection that fires only on `status=failed` together with
  `codexErrorInfo=usageLimitExceeded`. Completed, interrupted, ordinary failed, tool-error, malformed,
  and unknown states are never resumed.
- Exact-thread tracking by UUID. `--last` is never used, and one thread's failure can never resume another.
- Reset-aware waiting that uses the real reset timestamp when one is available, with conservative polling
  when it is not, and a live usage re-check immediately before sending.
- A loaded-thread safety guard: the thread must be verifiably loaded in the desktop app, determined from
  the Windows Restart Manager without ever locking the app's own files. Unknown state never sends.
- Safe waiting for unloaded threads instead of any attempt to force them open.
- Duplicate-resume protection that survives process crashes and watcher restarts.
- Durable pending state in SQLite, with support for several interrupted threads at once.
- Bounded retry backoff, a global kill switch, and per-thread enable/disable/cancel.
- CLI: `doctor`, `enable`, `disable`, `status`, `pending`, `cancel`, `logs`, `run`, `stop`, `install`,
  `uninstall`.
- Single-instance protection via a per-user named mutex.
- Optional per-user Windows login autostart, requiring no administrator rights.
- Conservative uninstall that only deletes inside directories it created, and aborts if a watcher may be
  running.
- Rotating logs that never record prompt text, error text, or account identifiers.
- Automated test suite plus an opt-in, read-only live environment check.

### Known limitations

- Only threads already loaded in the Windows ChatGPT/Codex desktop app can be auto-resumed. After an app
  restart an unloaded thread is resumed only once the user opens that conversation again. This is a
  measured limitation, not an oversight.
- The blocking usage bucket cannot always be identified from local history with certainty.
- Pinned to a verified Codex engine version and local schema; other versions are refused.
- The complete end-to-end unattended path has had limited real-world exercise so far.

### Credits

Created by Youngbin Song, with AI-assisted development by OpenAI Codex (investigation, proof of concept,
initial implementation) and Anthropic Claude Code (completion, testing, security and adversarial audit).
See `CONTRIBUTORS.md`.
