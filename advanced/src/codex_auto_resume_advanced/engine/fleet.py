# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
r"""See your other PCs (fleet_view, v0.6.22, plans/v0619-design/D-remote.md): this PC's status in a folder the person syncs
themselves, and the other PCs' files read from it. The product never talks to another PC; there is no network code here.
The folder may be a network share (`\\server\share\...`, `//server/share/...`, or a mapped drive whose real path is one):
Windows reaches it, and this module only opens files there.

At P8, at most every EVERY seconds, a thread of its own (a sync tool that holds a file, or a drive or share that stopped
answering, must never hold the watcher's tick; only one at a time, none while this is off) writes `<folder>/<alias>.json`: statusfile's
closed document, its `format` this file's provenance key, plus the alias and the edition. Nothing else leaves: no
conversation id or title, no path, no user name, no account (KEYS, `clean`). It is written whole or not at all (a
temporary file beside it, then a replace), and replaces only a regular file that says it is this PC's own (`_ours`).

The folder is checked on every pass (`folder_problem`): never a link or a junction, never inside this product's home or the
Codex home, directly or through a link, never a device path (`\\?\`, `\\.\`). A file on a cloud drive that is only a
placeholder is not a link (`_linked`).

Python's file calls on a share have no timeout of their own, and a share that stopped answering can hold one for minutes.
So nothing waits on the folder past BOUND seconds an access. The pass marks each access as it starts it, and a tick that
finds one running longer than BOUND gives that pass up (LATE: "the shared folder did not answer in time"): what it comes
to later is dropped, and the next pass, EVERY seconds on, tries again - never beside one still held, so a hung share holds
one thread, never one a pass. The Dashboard's save looks at the folder the same way (`bounded`): one access at a time in
its process, waited on BOUND seconds at most.

The peers are `*.json` in that folder, at most MOST files of at most LIMIT bytes each, this PC's alias skipped (`read_peers`).
A hostile synced file gets nowhere: one that is a link, too large, malformed or not exactly the closed shape is ignored and
counted in the journal, and what is kept is words from closed lists, an alias of letters, digits, spaces and hyphens that
matches its file's name, and bounded numbers. Nothing a peer's file says decides anything here, and nothing acts on a peer.

A folder that vanished, or a file held, waits: the next try is EVERY seconds on, its word is stamped for the Dashboard to
say, and the journal has one line each time the word changes - no loop, no storm. The alias and the folder are `wordings`:
text, never logged. Turned off, nothing here runs, and this PC's file stays in the folder (the statement says so): the
other PCs then show it greyed instead of it vanishing, and nothing outside the home is touched on the way out.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time

from codex_auto_resume import config, machine, statusfile
from codex_auto_resume.domain.plug import DEFER

from ..vocabulary import OptionKey, WordingKey

CAPABILITY = "fleet_view"
FORMAT = "codex-auto-resume/fleet/1"
EDITION = "advanced"
# Exactly what leaves this PC, in the order it is written: statusfile.KEYS, with its alias and edition.
KEYS = ("format", "alias", "edition") + statusfile.KEYS[1:]
EVERY = 5 * 60
MOST = 16
LIMIT = 16 * 1024
# How many directory entries one read looks at: a folder of a million files costs a read no more than this.
SCAN_MOST = 1024
ALIAS_MOST = 32
FOLDER_MOST = 248
STALE = 7 * 24 * 60 * 60
# How far ahead of this PC's clock a peer's file may be written before its clock is said to differ.
CLOCK_SLACK = 10 * 60
# How far on a peer's next check is shown: a usage window is at most a week, and a later time says nothing.
NEXT_MOST = 8 * 24 * 60 * 60
PENDING_MOST = 100000
# How often files ignored are told to the journal, at most: one line, whatever their count (a folder of a thousand junk
# files added and removed again and again wrote a line for each, and took the watcher's tick seconds to write them).
IGNORED_EVERY = 60 * 60
VERSION_MOST = 32
# How long, in seconds, anything waits on one access to the folder: a file call on a share that stopped answering has no
# timeout of its own (the owner, 2026-11-07: a network share may be the folder).
BOUND = 5

# What a pass came to, the word the Dashboard says. Each but OK and UNSET is stamped, by its place + 1. LATE: the shared
# folder did not answer in time.
OK, UNSET, MISSING, HELD, NOT_OURS, INSIDE, LINK, INVALID, LATE = (
    "ok", "unset", "missing", "held", "not_ours", "inside", "link", "invalid", "late")
WAITING_WORDS = (MISSING, HELD, NOT_OURS, INSIDE, LINK, INVALID, LATE)
REFUSALS = (INSIDE, LINK, INVALID)
# The journal's words: a word changed to these, and each file ignored.
WROTE, WAITING, REFUSED, IGNORED = "wrote", "waiting", "refused", "ignored"
CODES = (WROTE, WAITING, REFUSED, IGNORED)
FRESH, OLD, CLOCK = "fresh", "old", "clock"
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL"} | {"COM%d" % n for n in range(1, 10)}
                      | {"LPT%d" % n for n in range(1, 10)})
_CLOUD_MASK, _CLOUD = 0xFFFF0FFF, 0x9000001A
_ONEDRIVE = 0x80000021


# ------------------------------------------------------------------------------ what may be said
def alias_valid(value) -> bool:
    """Whether `value` is an alias: 1 to 32 letters, digits, spaces and hyphens, no space at either end, and a name
    Windows lets a file have."""
    return (isinstance(value, str) and 1 <= len(value) <= ALIAS_MOST and value == value.strip()
            and all(ch.isalnum() or ch in " -" for ch in value) and value.upper() not in _RESERVED)


def _version_valid(value) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= VERSION_MOST
            and all(ch.isascii() and (ch.isalnum() or ch in ".-+") for ch in value))


def _bounded_time(value) -> bool:
    return machine.epoch(value, *machine.EPOCH_CODEX)


def clean(value, stem=None) -> dict:
    """`value` exactly as a fleet file may hold it, in KEYS' order, or ValueError: nothing but the keys, the provenance,
    an alias (the file's own name, where `stem` says it), the closed words statusfile holds and bounded numbers."""
    if not isinstance(value, dict) or set(value) != set(KEYS) or value["format"] != FORMAT:
        raise ValueError("fleet keys")
    if not alias_valid(value["alias"]) or (stem is not None and value["alias"].casefold() != stem.casefold()):
        raise ValueError("fleet alias")
    if value["edition"] != EDITION or not _version_valid(value["version"]):
        raise ValueError("fleet words")
    if not _bounded_time(value["written_at"]) or not (value["next_check_at"] is None
                                                      or _bounded_time(value["next_check_at"])):
        raise ValueError("fleet times")
    if type(value["pending"]) is not int or not 0 <= value["pending"] <= PENDING_MOST:
        raise ValueError("fleet pending")
    statusfile.clean({key: statusfile.FORMAT if key == "format" else value[key] for key in statusfile.KEYS})
    return {key: value[key] for key in KEYS}


def document(status, alias) -> dict:
    """statusfile's document as this PC's file holds it: its provenance, the alias and the edition. A next check outside
    what a file may say is left out rather than the file."""
    made = {"format": FORMAT, "alias": alias, "edition": EDITION}
    made.update((key, status[key]) for key in statusfile.KEYS[1:])
    if made["next_check_at"] is not None and not _bounded_time(made["next_check_at"]):
        made["next_check_at"] = None
    return clean(made)


def shown(found, now) -> dict:
    """One peer as the window shows it, from a file `clean` kept. `seen` is FRESH, OLD (older than a week: greyed, "not
    seen since"), or CLOCK (written ahead of this PC's clock: no time of it means anything here, so none is given)."""
    age = now - found["written_at"]
    seen = CLOCK if age < -CLOCK_SLACK else OLD if age > STALE else FRESH
    due = found["next_check_at"]
    return {"alias": found["alias"], "watcher": found["watcher"], "recovery": found["recovery"],
            "pending": found["pending"], "seen": seen, "written_at": None if seen == CLOCK else found["written_at"],
            "next_check_at": due if seen == FRESH and due is not None and now <= due <= now + NEXT_MOST else None}


# ------------------------------------------------------------------------------ the folder
def _linked(path) -> bool:
    """Whether `path` is a symbolic link, a junction or any other reparse point but a cloud drive's own placeholder - a file
    OneDrive or the like keeps on demand, which is a file. False for a path that is not there."""
    try:
        found = os.lstat(path)
    except (OSError, ValueError):
        return False
    if stat.S_ISLNK(found.st_mode) or os.path.islink(path) or os.path.isjunction(path):
        return True
    if not getattr(found, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    tag = getattr(found, "st_reparse_tag", 0)
    return (tag & _CLOUD_MASK) != _CLOUD and tag != _ONEDRIVE


def _within(path, root) -> bool:
    path, root = os.path.normcase(str(path)), os.path.normcase(str(root))
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:                 # another drive
        return False


def _guarded(paths) -> list:
    """The folders it may never be inside: this product's home and the Codex homes it knows of."""
    from ..codex import inuse
    homes = [paths.home]
    for finding in (lambda: inuse.home(paths), config.codex_home):
        try:
            homes.append(finding())
        except Exception:
            pass
    return homes


def _share(drive) -> bool:
    r"""Whether `drive`, as os.path.splitdrive gives it, is a network share's: two separators, then a server and a share,
    each named - a '.' is no server's name (`\\.\`, a device)."""
    if len(drive) < 5 or drive[0] not in "\\/" or drive[1] not in "\\/":
        return False
    named = drive[2:].replace("/", "\\").split("\\")
    return len(named) == 2 and all(part.strip(" .") for part in named)


def _a_home_holds(path, guarded) -> bool:
    r"""Whether `path` or a folder above it is one of the homes, by what the file system says each is rather than by its
    name: a share can name this PC's own drive (an administrative share, `\\localhost\c$\...`)."""
    homes = []
    for home in guarded:
        try:
            found = os.stat(home)
        except (OSError, ValueError):
            continue
        if found.st_ino:
            homes.append(found)
    path = os.path.abspath(path)
    while homes:
        try:
            found = os.stat(path)
        except (OSError, ValueError):
            found = None
        if found is not None and found.st_ino and any(os.path.samestat(found, home) for home in homes):
            return True
        above = os.path.dirname(path)
        if above == path:
            return False
        path = above
    return False


def folder_problem(folder, paths) -> str | None:
    """The word for what is wrong with `folder`, or None. Looked at on every pass: a folder fit when it was chosen may be a
    junction by now. A folder on a drive (`C:\\...`) or on a network share (`\\\\server\\share\\...`, `//server/share/...`,
    or a mapped drive whose real path is one) may be the folder; a device path (`\\\\?\\`, `\\\\.\\`, `\\\\?\\UNC\\` written by
    hand) never - '?' is refused with the other characters no folder's name has, and '.' names no server."""
    if (not isinstance(folder, str) or not folder or len(folder) > FOLDER_MOST
            or any(ord(ch) < 32 or ch in '<>"|?*' for ch in folder)):
        return INVALID
    drive, rest = os.path.splitdrive(folder)
    share = _share(drive)
    if share:
        if rest and not rest.startswith(("\\", "/")):
            return INVALID
    elif len(drive) != 2 or drive[1] != ":" or not rest.startswith(("\\", "/")):
        return INVALID
    try:
        guarded = _guarded(paths)
        for home in guarded:
            if _within(os.path.abspath(folder), os.path.abspath(home)):
                return INSIDE
        if _linked(folder):
            return LINK
        found = os.lstat(folder)
        if not stat.S_ISDIR(found.st_mode):
            return INVALID
        real = os.path.realpath(folder)          # a mapped drive's real path may be a share's: a folder too
        for home in guarded:
            if _within(real, os.path.realpath(home)):
                return INSIDE
        if (share or real.startswith(("\\\\", "//"))) and _a_home_holds(real, guarded):
            return INSIDE
    except OSError:
        return MISSING
    return None


# ------------------------------------------------------------------------------ this PC's file
def _ours(target, alias, wrote_before) -> bool:
    """Whether the file at `target` may be replaced: there, regular, no link, no larger than one of these, saying it is
    this format and this alias - and not newer than what this PC last wrote, which is another PC under the same name.
    OSError where it cannot be read now."""
    if _linked(target):
        return False
    found = os.lstat(target)
    if not stat.S_ISREG(found.st_mode) or found.st_size > LIMIT:
        return False
    with open(target, "rb") as stream:
        raw = stream.read(LIMIT + 1)
    try:
        held = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return False
    if not isinstance(held, dict) or held.get("format") != FORMAT or held.get("alias") != alias:
        return False
    at = held.get("written_at")
    return not (wrote_before and type(at) in (int, float) and at == at and int(at) > wrote_before)


def write(folder, alias, value, wrote_before=None) -> str:
    """Replace `<folder>/<alias>.json` with `value`, whole. OK, NOT_OURS where something else stands there (nothing is
    touched), or OSError (the folder gone, the file held)."""
    target = os.path.join(folder, alias + ".json")
    text = json.dumps(clean(value), indent=2, allow_nan=False) + "\n"
    try:
        os.lstat(target)
    except FileNotFoundError:
        pass
    else:
        if not _ours(target, alias, wrote_before):
            return NOT_OURS
    descriptor, temporary = tempfile.mkstemp(dir=folder, prefix="fleet-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if _linked(target):                 # one made since it was looked at
            os.unlink(temporary)
            return NOT_OURS
        os.replace(temporary, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return OK


def remove_old_name(folder, alias) -> bool:
    """This PC's file under the name it had, once a person renamed it - only a regular file that says it is that alias's.
    Whether it went."""
    target = os.path.join(folder, alias + ".json")
    try:
        if not _ours(target, alias, None):
            return False
        os.unlink(target)
    except OSError:
        return False
    return True


# ------------------------------------------------------------------------------ the other PCs' files
def _read_one(path, stem):
    """The file at `path` as `clean` keeps it, or None where it is to be ignored. OSError where it cannot be read now."""
    if _linked(path):
        return None
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
        return None
    with open(path, "rb") as stream:
        if not os.path.samestat(before, os.fstat(stream.fileno())):       # swapped for a link since it was looked at
            return None
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        return None

    def refuse(_word):
        raise ValueError("not a number")
    try:
        return clean(json.loads(raw.decode("utf-8"), parse_constant=refuse), stem)
    except (ValueError, TypeError, RecursionError, OverflowError, KeyError):
        return None


def read_peers(folder, own, step=None) -> tuple:
    """([each other PC's file, as `clean` keeps it], how many were ignored, how many are held now), `own` skipped, in the
    aliases' order. OSError where the folder cannot be listed. `step` is called before each access: the listing, then
    each file."""
    step = step or (lambda: None)
    names = []
    ignored = held = 0
    step()
    with os.scandir(folder) as entries:
        for count, entry in enumerate(entries):
            if count >= SCAN_MOST:
                ignored += 1
                break
            if entry.name.casefold().endswith(".json"):
                names.append(entry.name)
    names.sort(key=str.casefold)
    kept = []
    looked = 0
    own = own.casefold() if isinstance(own, str) else None
    for name in names:
        stem = name[:-len(".json")]
        if stem.casefold() == own:
            continue
        if looked >= MOST:
            ignored += 1
            continue
        looked += 1
        step()
        try:
            found = _read_one(os.path.join(folder, name), stem)
        except FileNotFoundError:
            continue
        except OSError:
            held += 1
            continue
        if found is None:
            ignored += 1
        else:
            kept.append(found)
    return kept, ignored, held


# ------------------------------------------------------------------------------ what the last pass read
# The other PCs as the last pass read them, in this edition's own state folder, for the Dashboard to answer from: its
# call never waits on the synced folder (a drive that stopped answering, or online-only files a cloud tool must fetch
# first). Written whole by the pass, on its own thread; read, and every file in it checked again, by the bridge.
SEEN_NAME = "fleet-seen.json"
SEEN_FORMAT = "codex-auto-resume/fleet-seen/1"
SEEN_KEYS = ("format", "read_at", "ignored", "held", "peers")
SEEN_LIMIT = (MOST + 1) * LIMIT


def seen_path(paths):
    return os.path.join(str(paths.advanced_dir), SEEN_NAME)


def write_seen(paths, now, kept, ignored, held) -> None:
    """What a pass read, kept whole (a temporary file beside it, then a replace)."""
    value = {"format": SEEN_FORMAT, "read_at": float(now), "ignored": int(ignored), "held": int(held),
             "peers": [clean(each) for each in kept[:MOST]]}
    target = seen_path(paths)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if _linked(target):
        return
    descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(target), prefix="fleet-seen.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, allow_nan=False)
        os.replace(temporary, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def read_seen(paths):
    """{"read_at", "ignored", "held", "peers"} as the last pass kept it, each peer checked again - or None."""
    target = seen_path(paths)
    try:
        if _linked(target) or os.lstat(target).st_size > SEEN_LIMIT:
            return None
        with open(target, "rb") as stream:
            value = json.loads(stream.read(SEEN_LIMIT + 1).decode("utf-8"))
        if not isinstance(value, dict) or tuple(value) != SEEN_KEYS or value["format"] != SEEN_FORMAT:
            return None
        counts = (value["ignored"], value["held"])
        if not all(type(count) is int and 0 <= count <= SCAN_MOST for count in counts) \
                or not _bounded_time(value["read_at"]) or not isinstance(value["peers"], list):
            return None
        return {"read_at": value["read_at"], "ignored": counts[0], "held": counts[1],
                "peers": [clean(each, each.get("alias") if isinstance(each, dict) else None)
                          for each in value["peers"][:MOST]]}
    except (OSError, ValueError, TypeError, KeyError, RecursionError, AttributeError):
        return None


def forget_seen(paths) -> None:
    try:
        if not _linked(seen_path(paths)):
            os.unlink(seen_path(paths))
    except OSError:
        pass


# ------------------------------------------------------------------------------ at P8
def _status_now(paths, now):
    """statusfile's document as the watcher's own status file would say it now, from what core's store holds."""
    from codex_auto_resume.store import Store
    with Store(paths.state_dir) as store:
        stored = store.settings()
        heartbeat = store.watcher_status() or {}
        rows = store.pending()
    values = config.load_settings(paths)
    return statusfile.content(now=now, version=config.version(), running=True, enabled=bool(stored["enabled"]),
                              observe_only=bool(stored.get("observe_only") or values.get("observe_only")),
                              engine=heartbeat.get("engine_state"), rows=rows, reading=heartbeat.get("usage"))


class _Errand:
    __slots__ = ("code", "now", "alias", "folder")

    def __init__(self, code, now, alias, folder):
        self.code, self.now, self.alias, self.folder = code, now, alias, folder

    def run(self, guard):
        self.code._begin(self.now, self.alias, self.folder)
        return None


class FleetView:
    """fleet_view's code: its P8 errand. `status`, `spawn` and `clock` are the seams a test fills: what is written, how a
    pass is run, and the clock an access is timed by. What a pass came to is taken up by the next tick, which alone writes
    to the state. `_touched` is when the running pass began its latest access to the folder, and `_late` that a tick gave
    it up; `_lock` keeps what the pass came to and the tick giving it up from crossing."""
    __slots__ = ("paths", "_scoped", "_status", "_spawn", "_clock", "_worker", "_came_to", "_word", "_ignored",
                 "_ignored_told", "_touched", "_late", "_lock")

    def __init__(self, paths, *, status=None, spawn=None, clock=None):
        self.paths = paths
        self._scoped = None
        self._status = status or (lambda now: _status_now(paths, now))
        self._spawn = spawn or _thread
        self._clock = clock or time.monotonic
        self._worker = None
        self._came_to = None
        self._touched = None
        self._late = False
        self._lock = threading.Lock()
        self._word = None
        self._ignored = 0
        self._ignored_told = None

    def bind(self, scoped):
        self._scoped = scoped

    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            self._take_up()
            if self._worker is not None and self._worker.is_alive():
                self._give_up_late()
                return DEFER                       # held: never a second pass beside it
            now = scoped.now()
            last = scoped.stamped(OptionKey.LAST_FLEET_WRITE)
            if isinstance(last, (int, float)) and 0 <= now - last < EVERY:
                return DEFER
            words = scoped.wordings()
            alias, folder = words.get(WordingKey.FLEET_ALIAS), words.get(WordingKey.FLEET_FOLDER)
            return _Errand(self, now, alias, folder) if alias_valid(alias) and folder else DEFER
        except Exception:
            return DEFER

    def _begin(self, now, alias, folder):
        """The stamp first: whatever the pass comes to, the next is EVERY seconds on."""
        scoped = self._scoped
        scoped.stamp(OptionKey.LAST_FLEET_WRITE, max(1, int(now)))
        wrote_before = scoped.stamped(OptionKey.FLEET_WROTE_AT)
        with self._lock:
            self._late, self._touched = False, self._clock()
        try:
            self._worker = self._spawn(lambda: self._pass(now, alias, folder, wrote_before))
        except Exception:                          # no thread to be had now: the next try is EVERY seconds on
            self._worker = None

    def _step(self):
        """An access to the folder begins now: the tick times it from here."""
        self._touched = self._clock()

    def _pass(self, now, alias, folder, wrote_before):
        """One pass, off the watcher's tick: never raises. Given up (`_late`), it keeps nothing of what it read and says
        nothing: the tick has said LATE for it."""
        word, ignored, wrote = HELD, 0, None
        try:
            self._step()
            word = folder_problem(folder, self.paths) or OK
            if word == OK:
                value = document(self._status(now), alias)
                self._step()
                word = write(folder, alias, value, wrote_before)
                if word == OK:
                    wrote = max(1, int(value["written_at"]))
                kept, ignored, held = read_peers(folder, alias, self._step)
                if not self._late:
                    write_seen(self.paths, now, kept, ignored, held)
                if held and word == OK:
                    word = HELD
        except FileNotFoundError:
            word = MISSING
        except Exception:
            word = HELD
        with self._lock:
            if not self._late:
                self._came_to = (word, ignored, wrote)

    def _give_up_late(self):
        """A pass whose access has run longer than BOUND is given up, once: LATE is stamped and said as any word is, and
        the pass, still held, is never joined - nor another begun beside it."""
        with self._lock:
            if self._late or self._came_to is not None or self._touched is None                     or not self._clock() - self._touched > BOUND:
                return
            self._late = True
            self._came_to = (LATE, self._ignored, None)
        self._take_up()

    def _take_up(self):
        """What the last pass came to, into the stamps and the journal: one line when the word changes, and one line when
        files are ignored where none or fewer were, at most once an hour whatever their count - so a folder that stays gone,
        a bad file that stays, or a thousand that come and go, say so once and cost the tick one write."""
        with self._lock:
            came_to, self._came_to = self._came_to, None
        if came_to is None:
            return
        word, ignored, wrote = came_to
        scoped = self._scoped
        if word == OK:
            scoped.unstamp(OptionKey.FLEET_WAITING)
        else:
            scoped.stamp(OptionKey.FLEET_WAITING, WAITING_WORDS.index(word) + 1)
        if wrote is not None:
            scoped.stamp(OptionKey.FLEET_WROTE_AT, wrote)
        if word != self._word:
            self._word = word
            scoped.count(WROTE if word == OK else REFUSED if word in REFUSALS or word == NOT_OURS else WAITING)
        if ignored > self._ignored:
            now = scoped.now()
            if self._ignored_told is None or not 0 <= now - self._ignored_told < IGNORED_EVERY:
                self._ignored_told = now
                scoped.count(IGNORED)
        self._ignored = ignored


def _thread(run):
    worker = threading.Thread(target=run, daemon=True, name="car-fleet")
    worker.start()
    return worker


def waiting_word(stamp):
    """The word a FLEET_WAITING stamp stands for, or None."""
    if type(stamp) is int and 1 <= stamp <= len(WAITING_WORDS):
        return WAITING_WORDS[stamp - 1]
    return None


def make(paths) -> FleetView:
    return FleetView(paths)


# The one bounded access in flight in this process (`bounded`), and the lock its place is taken under.
_ACCESS_LOCK = threading.Lock()
_access = None


def bounded(call, bound=None):
    """call()'s answer, or what it raised, from a thread of its own waited on `bound` seconds at most - for the Dashboard's
    save, whose process answers the window (`bound`: BOUND). TimeoutError where it did not answer in time, or where the access before it
    is still held past the same bound: at most one is in flight, so a share that stopped answering holds one thread."""
    global _access
    deadline = time.monotonic() + (BOUND if bound is None else bound)
    while True:
        with _ACCESS_LOCK:
            before = _access
            if before is None or not before.is_alive():
                box = []

                def run():
                    try:
                        box.append((True, call()))
                    except BaseException as error:     # handed to the caller, never lost on the thread
                        box.append((False, error))
                worker = threading.Thread(target=run, daemon=True, name="car-fleet-access")
                worker.start()
                _access = worker
                break
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the shared folder did not answer in time")
        before.join(left)
    worker.join(max(0.0, deadline - time.monotonic()))
    if not box:
        raise TimeoutError("the shared folder did not answer in time")
    done, value = box[0]
    if done:
        return value
    raise value
