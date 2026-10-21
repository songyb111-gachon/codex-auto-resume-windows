# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What the capabilities that take failures up keep (v0.6.14, stage 3b): choices, rules, admissions
and samples, and the one view of them a capability's own code is given.

    options     a capability's own choices (registry.Option), set by a person in the Dashboard: a
                value it offers, or the default where none was set or one stored is not offered
    rules       up to ten rules a person wrote: one of Codex's own error codes, if they like a range
                of status numbers, and the temporary kind to treat it as. A code the product already
                classifies, one that may name a person's decision, a kind that is not temporary, a
                second rule over the same code and numbers - each is refused (`rule_problem`)
    admissions  which capability took up which interruption at P17, with the word, and the rule or
                the failure's shape where it keeps one - upserted, so a failure asked again is taken up
                again and never twice counted
    samples     what a capability that samples keeps of a failure it took up and nothing classified:
                Codex's code, a status number, the error's form, whether a message existed, item
                counts, a time to the minute and a duration - never a word of the error or the
                conversation

Choices and rules are written only by a person in the Dashboard (arming.py), against the generation
the page read, and each write moves the generation like any move: a page showing old choices cannot
arm against new ones. Admissions and samples are the runtime's (runtime.py); a capability's code reads
its own through `Scoped`, and writes nothing.
"""
from __future__ import annotations

import time

from codex_auto_resume import failures
from codex_auto_resume.domain.plug import TAKE_UP, Alternative, FailureForm

from ..vocabulary import Actor, JournalCode, OptionKey, Refusal
from .journal import prune_every
from .schema import WINDOW_CHOICES, WINDOW_FOLLOWERS
from .session import StaleGeneration, StateError, _key, _word

# The names a person's choice may be stored under: the vocabulary's, checked here and nowhere in the file (v0.6.17).
OPTION_WORDS = frozenset(str(word) for word in OptionKey)
# The choices whose missing row is not their default, so a choice of the default is still written for them: the wrap-up's
# and the stop's window switches, which an opening writes from the usage meter's where it finds none (session._carry_windows).
CARRIED = frozenset((capability, choice) for capability in WINDOW_FOLLOWERS for choice in WINDOW_CHOICES)
# v0.6.18: the times a capability's own code keeps in `options` beside its choices (ChoicesMixin.stamp): the weekly update
# check's last run, and the newest version it offered and when. Nothing else is ever written so.
STAMPS = {"idle_update_check": (str(OptionKey.LAST_CHECK), str(OptionKey.OFFERED_VERSION),
                                str(OptionKey.OFFERED_AT))}
RULES_LIMIT = 10
STATUS_RANGE = (100, 599)
# How far back the Dashboard counts a rule's hits and shows samples.
RECENT_DAYS = 30
DAY = 86400
# A sample's columns for what the turn left (codex/history.turn_item_counts' kinds, in that order).
ITEM_COLUMNS = {"agentMessage": "items_agent", "commandExecution": "items_command",
                "fileChange": "items_file", "mcpToolCall": "items_tool", "userMessage": "items_user",
                "other": "items_other"}


class Refused(StateError):
    """A choice or a rule a person asked for that is not one this edition takes: `refusal` says why."""

    def __init__(self, refusal):
        super().__init__("refused")
        self.refusal = Refusal(refusal)


def _status(value) -> bool:
    return type(value) is int and STATUS_RANGE[0] <= value <= STATUS_RANGE[1]


def _overlaps(one, other) -> bool:
    """Whether two status ranges - (from, to), or (None, None) for every status - share a number."""
    if one[0] is None or other[0] is None:
        return True
    return one[0] <= other[1] and other[0] <= one[1]


def tag_problem(tag):
    """Why `tag` may not be a rule's code, or None (rule_problem's first three refusals). Pure."""
    if not isinstance(tag, str) or not failures.TAG_SHAPE.fullmatch(tag):
        return Refusal.RULE_SHAPE
    if tag in failures.CODES:
        return Refusal.RULE_KNOWN
    if failures.decision_tag(tag):
        return Refusal.RULE_DECISION
    return None


def aggregated(samples, *, day=DAY) -> list:
    """Samples as the Dashboard and a diagnostics export show them: one entry for each code, status
    number and form, with how many there were and the last day one was kept (UTC, YYYY-MM-DD) - most
    seen first. Codes and numbers only: no time finer than the day, no id of anything. Pure."""
    found = {}
    for sample in samples:
        key = (sample.get("tag"), sample.get("status"), sample.get("form"))
        count, last = found.get(key, (0, None))
        at = sample.get("at")
        found[key] = (count + 1, at if last is None or (at is not None and at > last) else last)
    shown = [{"tag": tag, "status": status, "form": form, "count": count,
              "last": None if last is None else time.strftime("%Y-%m-%d", time.gmtime(int(last // day) * day))}
             for (tag, status, form), (count, last) in found.items()]
    return sorted(shown, key=lambda entry: (-entry["count"], entry["tag"] or "", entry["status"] or 0,
                                            entry["form"] or ""))


def rule_problem(tag, status_from, status_to, category, rules):
    """Why a rule may not be added beside `rules`, or None. Pure.

    A code Codex chose, of its own shape (failures.TAG_SHAPE); never one the product classifies
    already (failures.CODES - every code that needs a person among them), never one that may name a
    decision (failures.DECISION_FRAGMENTS); status numbers from 100 to 599, both or neither, the first
    no larger; a temporary kind (failures.TRANSIENT), never a usage limit; at most ten rules, no two
    over the same code and a status they share."""
    problem = tag_problem(tag)
    if problem is not None:
        return problem
    if (status_from is None) != (status_to is None) or (
            status_from is not None and not (_status(status_from) and _status(status_to)
                                             and status_from <= status_to)):
        return Refusal.RULE_RANGE
    if category not in failures.TRANSIENT:
        return Refusal.INVALID_REQUEST
    if len(rules) >= RULES_LIMIT:
        return Refusal.RULES_FULL
    if any(rule["tag"] == tag and _overlaps((rule["status_from"], rule["status_to"]),
                                            (status_from, status_to)) for rule in rules):
        return Refusal.RULE_OVERLAP
    return None


def _shape(shape) -> tuple:
    """A failure's shape (failures.shape) as an admission row keeps it: (tag, status, form, message)."""
    if shape is None:
        return None, None, None, None
    if not isinstance(shape, dict):
        raise StateError("invalid shape")
    tag, status, form, message = (shape.get("code"), shape.get("status"), shape.get("form"),
                                  shape.get("has_message"))
    if tag is not None and not (isinstance(tag, str) and failures.TAG_SHAPE.fullmatch(tag)):
        raise StateError("invalid shape")
    if status is not None and not _status(status):
        raise StateError("invalid shape")
    return tag, status, str(_word(form, FailureForm, "form")), int(message is True)


def _sample_row(sample, now) -> tuple:
    """One sample's columns, every one checked, `at` rounded down to the minute."""
    if not isinstance(sample, dict):
        raise StateError("invalid sample")
    tag, status, form, message = _shape(sample)
    counts = sample.get("items")
    counts = counts if isinstance(counts, dict) else {}
    items = []
    for kind in ITEM_COLUMNS:
        value = counts.get(kind)
        items.append(value if type(value) is int and value >= 0 else None)
    duration = sample.get("duration")
    duration = (float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool)
                and 0 <= duration < 86400 * 7 else None)
    return (float(int(now // 60) * 60), tag, status, form, message, *items, duration)


class Scoped:
    """One capability's view of the state, as its code is given it (runtime.Runtime._code_of): its
    own choices, the rules where it is the one they are written for, its own admission rows, and the
    runtime's clock - and (v0.6.14) whether a standard record was sent once more by this edition,
    whether a capability that is a channel or a route paid for one of its sends, its own request about a
    record and since when it has stood where it stands. Reads, and one write:
    `count`, one of its own closed words (registry codes)
    counted with its journal line, and only while the runtime has it on (`on`) - what a watched or
    turned-off capability notices is not something that happened. What it takes up and what it keeps
    of it are the runtime's to write, so a capability is never journalled or sampled for a failure
    core did not carry out.

    The state is held in a closure, not on an attribute, as core's StoreView holds the store
    (engine/options.py): what is taken away is the plain way to a write a capability did not mean."""
    __slots__ = ("capability", "_reads")

    def __init__(self, state, capability, on=None, verdict=None, armed=None):
        self.capability = capability
        definition = state.registry.get(capability)
        rules_editor = definition is not None and definition.rules_editor

        def admission(interruption_id):
            row = state.admission(interruption_id)
            return row if row is not None and row["capability"] == capability else None

        def count(code):
            return on is not None and on() is True and state.counted(capability, code)

        def since():
            row = state.arming().get(capability) or {}
            return row.get("since") if row.get("state") not in (None, "off") else None
        self._reads = {
            "now": lambda: state.clock(),
            "options": lambda: state.options(capability),
            # v0.6.16-beta.4: its own wordings (the wrap-up's Custom text), and another capability's choices read -
            # the wrap-up's Continue after the reset, which the stop follows.
            "wordings": lambda: state.wordings(capability),
            "options_of": lambda other: state.options(other),
            "rules": lambda: state.rules() if rules_editor else [],
            "admission": admission,
            "count": count,
            "resent": lambda interruption_id: state.resent(interruption_id),
            "channel_paid": lambda interruption_id, claimed_at: state.channel_paid(interruption_id, claimed_at),
            "request": lambda interruption_id: state.override(interruption_id, capability),
            "since": lambda: since(),
            # v0.6.18: a time its own code keeps (ChoicesMixin.stamp) - read always, written only while it is on.
            "stamped": lambda key: state.stamped(capability, key),
            "stamp": lambda key, value: on is not None and on() is True and state.stamp(capability, key, value),
            "unstamp": lambda key: on is not None and on() is True and state.unstamp(capability, key),
        }
        # v0.6.14, the reset actions: their rules, windows and spends (state/resets.ResetsHandle - writes only while
        # on), whether a measurement passed or failed on the Codex in force (arming.Arming.verdict), and whether
        # another capability stands on now.
        from .continuations import ContinuationsHandle
        from .meter import MeterHandle
        from .runs import RunsHandle
        from .prompts import PromptsHandle
        from .resets import ResetsHandle
        self._reads.update({
            "resets": ResetsHandle(state, capability, on),
            # v0.6.15-beta: a continuation capability's own continuations (state/continuations.py).
            "continuations": ContinuationsHandle(state, capability, on),
            # and prompt_queue's prompts (state/prompts.py).
            "prompts": PromptsHandle(state, capability, on),
            # v0.6.16-beta.3: the usage meter's last reading (state/meter.py) - read by the wrap-up and the pause too.
            "meter": MeterHandle(state, capability, on),
            # v0.6.16-beta.4: a headless capability's own runs (state/runs.py).
            "runs": RunsHandle(state, capability, on),
            "passed": lambda measurement: verdict is not None and verdict(measurement) == "pass",
            "failed": lambda measurement: verdict is not None and verdict(measurement) == "fail",
            "armed": lambda other: armed is not None and armed(other) is True,
        })
        # v0.6.19 (push_notices, status_feed - the courier, plans/v0619-design/D-courier.md): push_notices' outbox, written
        # only while it is on, and the status feed's last reading, read always. Neither loads a networking module.
        from ..courier.feed import read as feed_read
        from ..courier.outbox import OutboxHandle
        self._reads.update({"outbox": OutboxHandle(state, capability, on), "feed": lambda: feed_read(state)})

    def __getattr__(self, name):
        reads = object.__getattribute__(self, "_reads")
        if name in reads:
            return reads[name]
        raise AttributeError(name)


class ChoicesMixin:
    def scoped(self, capability, on=None, verdict=None, armed=None) -> Scoped:
        return Scoped(self, capability, on, verdict, armed)

    # ------------------------------------------------------------------ options
    def options(self, capability) -> dict:
        """{key: value} for every choice `capability` offers: the stored one where it is one it
        offers, its default otherwise. With no file, every default."""
        definition = self.registry.get(capability)
        if definition is None or not definition.options:
            return {}
        found = {option.key: option.default for option in definition.options}
        with self._read() as connection:
            rows = [] if connection is None else connection.execute(
                "SELECT choice, value FROM options WHERE capability=?", (capability,)).fetchall()
        for row in rows:
            option = definition.option(row["choice"])
            if option is not None and option.takes(row["value"]):
                found[option.key] = row["value"]
        return found

    def stamped(self, capability, key) -> int | None:
        """A time `capability`'s own code keeps under `key` (STAMPS), or None: none kept, no file, or a key that is not
        one of its stamps."""
        if str(key) not in STAMPS.get(capability, ()):
            return None
        with self._read() as connection:
            row = None if connection is None else connection.execute(
                "SELECT value FROM options WHERE capability=? AND choice=?", (capability, str(key))).fetchone()
        return row["value"] if row is not None and type(row["value"]) is int else None

    def stamp(self, capability, key, value) -> bool:
        """Keep `value`, a whole number from 1, as `capability`'s stamp `key` (STAMPS), in `options` beside its choices
        (v0.6.18): a row no reader of a person's choices takes - no capability offers it as a choice, so `options`
        passes it over and set_option refuses it - and no move to off takes away, so the time outlives a turn off and on.
        Written by the capability's own code, not a person, so the generation does not move: a page that shows the
        choices is not made stale by it. Whether it was kept."""
        if str(key) not in STAMPS.get(capability, ()) or type(value) is not int or value < 1:
            return False
        with self._transaction() as connection:
            connection.execute("INSERT INTO options (capability, choice, value) VALUES (?,?,?) "
                               "ON CONFLICT (capability, choice) DO UPDATE SET value=excluded.value",
                               (capability, str(key), value))
        return True

    def unstamp(self, capability, key) -> bool:
        """Take `capability`'s stamp `key` (STAMPS) away. Whether there was one."""
        if str(key) not in STAMPS.get(capability, ()):
            return False
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute("DELETE FROM options WHERE capability=? AND choice=?",
                                      (capability, str(key))).rowcount == 1

    def set_option(self, capability, key, value, *, generation, actor, at=None) -> int:
        """One choice set, against the generation the Dashboard read. The generation after.
        Refused (OPTION_INVALID) for a choice the capability does not offer or a value it does not
        offer for it; StaleGeneration where anything moved since. The name is the vocabulary's too
        (OptionKey): since v0.6.17 no CHECK of the file's names it (schema.FREE_OPTIONS), so the code
        is what keeps a word it does not know out.

        A choice of the default stores nothing (v0.6.17): its row is taken away, and `options` reads the
        default where there is none - so a later release that changes the default reaches this person too.
        A row stored before, of any value, stays until the choice is set again; and a choice whose missing
        row is not its default (CARRIED) is written as any other value is."""
        definition = self.registry.get(capability)
        option = definition.option(key) if definition is not None else None
        if option is None or not option.takes(value) or str(option.key) not in OPTION_WORDS:
            raise Refused(Refusal.OPTION_INVALID)
        actor = _word(actor, Actor, "actor")
        now = self._now(at)
        with self._transaction() as connection:
            current = self._current_generation(connection, generation)
            if value == option.default and (capability, str(option.key)) not in CARRIED:
                connection.execute("DELETE FROM options WHERE capability=? AND choice=?",
                                   (capability, str(option.key)))
            else:
                connection.execute("INSERT INTO options (capability, choice, value) VALUES (?,?,?) "
                                   "ON CONFLICT (capability, choice) DO UPDATE SET value=excluded.value",
                                   (capability, str(option.key), value))
            connection.execute("UPDATE meta SET generation = generation + 1")
            self._note(connection, now, JournalCode.OPTION_CHANGED, capability=capability, actor=actor)
            return current + 1

    # ------------------------------------------------------------------ wordings (v0.6.16-beta.4)
    def wordings(self, capability) -> dict:
        """{WordingKey: text} of `capability`'s own wordings a person wrote - only the keys it keeps. Never logged."""
        definition = self.registry.get(capability)
        if definition is None or not definition.wordings:
            return {}
        with self._read() as connection:
            rows = [] if connection is None else connection.execute(
                "SELECT choice, words FROM wordings WHERE capability=?", (capability,)).fetchall()
        return {row["choice"]: row["words"] for row in rows if row["choice"] in definition.wordings}

    def set_wording(self, capability, key, words, *, generation, actor, at=None) -> int:
        """A person's own wording set - or, with `words` None, taken away - against the generation the Dashboard read.
        The generation after. Refused (WORDING_INVALID) for a key the capability does not keep; the words themselves
        are the caller's to check (wrapwords.check_custom), the file's CHECK their length. Journalled as a choice
        changed - the words never."""
        definition = self.registry.get(capability)
        if definition is None or key not in definition.wordings or not (words is None or isinstance(words, str)):
            raise Refused(Refusal.WORDING_INVALID)
        actor = _word(actor, Actor, "actor")
        now = self._now(at)
        with self._transaction() as connection:
            current = self._current_generation(connection, generation)
            if words is None:
                connection.execute("DELETE FROM wordings WHERE capability=? AND choice=?", (capability, str(key)))
            else:
                connection.execute("INSERT INTO wordings (capability, choice, words, changed_at) VALUES (?,?,?,?) "
                                   "ON CONFLICT (capability, choice) DO UPDATE SET words=excluded.words, "
                                   "changed_at=excluded.changed_at", (capability, str(key), words, now))
            connection.execute("UPDATE meta SET generation = generation + 1")
            self._note(connection, now, JournalCode.OPTION_CHANGED, capability=capability, actor=actor)
            return current + 1

    @staticmethod
    def _current_generation(connection, generation) -> int:
        current = connection.execute("SELECT generation FROM meta").fetchone()[0]
        if type(generation) is not int or generation != current:
            raise StaleGeneration("stale generation")
        return current

    # ------------------------------------------------------------------ rules
    def rules(self) -> list:
        """Every rule, oldest first, with whether the product has come to know its code since - a
        rule that never matches again (`known`)."""
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT * FROM rules ORDER BY rule_id").fetchall()
        return [dict(row, known=row["tag"] in failures.CODES) for row in rows]

    def add_rule(self, tag, status_from, status_to, category, *, generation, actor, at=None) -> tuple:
        """A rule, refused as `rule_problem` says. (its id, the generation after)."""
        actor = _word(actor, Actor, "actor")
        now = self._now(at)
        with self._transaction() as connection:
            current = self._current_generation(connection, generation)
            rules = [dict(row) for row in connection.execute("SELECT * FROM rules")]
            problem = rule_problem(tag, status_from, status_to, category, rules)
            if problem is not None:
                raise Refused(problem)
            rule_id = connection.execute(
                "INSERT INTO rules (tag, status_from, status_to, category, created_at) VALUES (?,?,?,?,?)",
                (tag, status_from, status_to, category, now)).lastrowid
            connection.execute("UPDATE meta SET generation = generation + 1")
            self._note(connection, now, JournalCode.RULE_ADDED, actor=actor)
            return rule_id, current + 1

    def remove_rule(self, rule_id, *, generation, actor, at=None) -> int:
        """A rule removed. The generation after; UNKNOWN_RULE for one that is not there."""
        actor = _word(actor, Actor, "actor")
        now = self._now(at)
        if type(rule_id) is not int:
            raise Refused(Refusal.UNKNOWN_RULE)
        with self._transaction(create=False) as connection:
            if connection is None:
                raise Refused(Refusal.UNKNOWN_RULE)
            current = self._current_generation(connection, generation)
            if not connection.execute("DELETE FROM rules WHERE rule_id=?", (rule_id,)).rowcount:
                raise Refused(Refusal.UNKNOWN_RULE)
            connection.execute("UPDATE meta SET generation = generation + 1")
            self._note(connection, now, JournalCode.RULE_REMOVED, actor=actor)
            return current + 1

    def rule_hits(self, since) -> dict:
        """{rule id: how many failures it took up since `since`} - counted once each, when core first
        went on with one (`taken`)."""
        with self._read() as connection:
            if connection is None:
                return {}
            rows = connection.execute(
                "SELECT rule_id, count(*) FROM admissions WHERE rule_id IS NOT NULL AND sampled=1 "
                "AND created_at>=? GROUP BY rule_id", (since,)).fetchall()
        return {row[0]: int(row[1]) for row in rows}

    # ------------------------------------------------------------------ admissions
    def admission(self, interruption_id) -> dict | None:
        """The admission row of one interruption, of a capability this registry holds, or None."""
        _key(interruption_id, "interruption id")
        with self._read() as connection:
            if connection is None:
                return None
            row = connection.execute("SELECT * FROM admissions WHERE interruption_id=?",
                                     (interruption_id,)).fetchone()
        if row is None or self.registry.get(row["capability"]) is None or row["answer"] not in TAKE_UP:
            return None
        return dict(row, sampled=bool(row["sampled"]))

    def admit(self, interruption_id, capability, answer, *, rule_id=None, shape=None, at=None) -> bool:
        """Remember that `capability` took up `interruption_id` with `answer`: the row upserted, its
        capability, word, rule and shape replaced and its first time and `sampled` kept - so a
        failure taken up again after a restart, or after core skipped it, is one row, sampled once.
        False where there is no file: nothing armed, nothing to remember."""
        _key(interruption_id, "interruption id")
        if self.registry.get(capability) is None:
            raise StateError("unknown capability")
        answer = _word(answer, Alternative, "answer")
        if answer not in TAKE_UP:
            raise StateError("invalid answer")
        if rule_id is not None and type(rule_id) is not int:
            raise StateError("invalid rule")
        tag, status, form, message = _shape(shape)
        now = self._now(at)
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            connection.execute(
                "INSERT INTO admissions (interruption_id, capability, answer, rule_id, tag, status, "
                "form, has_words, sampled, created_at) VALUES (?,?,?,?,?,?,?,?,0,?) "
                "ON CONFLICT (interruption_id) DO UPDATE SET capability=excluded.capability, "
                "answer=excluded.answer, rule_id=excluded.rule_id, tag=excluded.tag, "
                "status=excluded.status, form=excluded.form, has_words=excluded.has_words",
                (interruption_id, capability, str(answer), rule_id, tag, status, form,
                 None if form is None else message, now))
            return True

    def taken(self, interruption_id, capability, code=None, *, sample=None, at=None) -> bool:
        """What `capability` keeps of the first time core went on with a failure it took up, in one
        transaction: its admission row marked so (`sampled`), its own code counted and journalled,
        and - for one that samples - the sample. Once an interruption: False, and nothing written,
        where it was marked already or the row is another capability's."""
        _key(interruption_id, "interruption id")
        definition = self.registry.get(capability)
        if definition is None:
            raise StateError("unknown capability")
        if code is not None and code not in definition.codes:
            raise StateError("not its own code")
        now = self._now(at)
        row = _sample_row(sample, now) if sample is not None and definition.samples else None
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            if not connection.execute(
                    "UPDATE admissions SET sampled=1 WHERE interruption_id=? AND capability=? AND sampled=0",
                    (interruption_id, capability)).rowcount:
                return False
            if row is not None:
                made = connection.execute(
                    "INSERT INTO samples (at, tag, status, form, has_words, %s, duration) "
                    "VALUES (%s)" % (", ".join(ITEM_COLUMNS.values()), ",".join("?" for _ in row)),
                    row).lastrowid
                if prune_every(made):
                    self._prune(connection, now)
            if code is not None:
                connection.execute(
                    "INSERT INTO sampler (capability, code, day, count) VALUES (?,?,?,1) "
                    "ON CONFLICT (capability, code, day) DO UPDATE SET count = count + 1",
                    (capability, code, int(now // DAY)))
                self._note(connection, now, definition.code(code), capability=capability)
            return True

    def failure_samples(self, since) -> list:
        """The samples kept since `since`, oldest first: codes, numbers, forms and times only."""
        with self._read() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT * FROM samples WHERE at>=? ORDER BY sample_id",
                                      (since,)).fetchall()
        return [{key: row[key] for key in row.keys() if key != "sample_id"} for row in rows]
