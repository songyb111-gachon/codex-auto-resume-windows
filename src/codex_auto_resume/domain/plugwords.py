"""The plug interface's own words: which edition, why a package was not loaded, where core asks, what a plug may
answer, what form a failure took and which surface it adds to.

Out of domain/plug.py, at its line budget, in v0.6.16-beta.4, and named through it still: `from .plug import Point`
reads as it did. Each is a `StrEnum` held to every rule domain/vocabulary.py's are (tests/test_vocabulary.py), and the
interface that speaks them is domain/plug.py's.

Pure: nothing here but the enums, and nothing imported back from domain/plug.py.
"""
from __future__ import annotations

from enum import StrEnum


class Edition(StrEnum):
    """Which edition an installation is (edition.EDITIONS). Nothing is stamped anywhere to say
    which: the advanced package beside core is the whole difference."""
    STANDARD = "standard"
    ADVANCED = "advanced"


class PlugFailure(StrEnum):
    """Why an advanced installation's package was not loaded (edition.PLUG_FAILURES). Each one
    leaves the installation doing exactly what the standard edition does, and saying so."""
    SHADOWED = "shadowed"                    # Python would import another copy first
    IMPORT_FAILED = "import_failed"          # its plug module raised while it was imported
    API_MISMATCH = "api_mismatch"            # it was written for another PLUG_API
    FACTORY_FAILED = "factory_failed"        # its factory raised, or made no plug


class Point(StrEnum):
    """Where core asks the plug (POINTS), numbered P2-P13 as the v0.6.11 plan numbers them, and
    P14 and P15, which the plan did not have.

    There is no P1. Classifying a turn into a core category would write a category that does
    not describe it, so an advanced record stays in the advanced store and reaches core through
    RECORDS instead, which core carries out from v0.6.14 (engine/plugrecords.py): each record is
    tried through core's gates, its one claim and its one send, and its moves are told at P14 in
    RecordMove's words.

    P14 is not a question: the engine tells the plug a record core holds has moved, as it writes
    the move. A person's own moves - a cancel, the attempts given back, or a waiting record a
    person's Rescan and reconcile retired as superseded_by_user (store/actions.py, and an older
    watcher's cancel, store/legacy.py) - are not told: what the person acted through
    wrote them, most often in a process that holds no engine. None moves a record into or out of
    submission_unknown, and a plug finds where they left it at its next P2 or P8. Read back out of
    the journal instead, a move would be a second source of truth a pruned entry changes; and at
    P8 the record's state alone has already moved on when the watch before it settled it.

    P15 (v0.6.11 stage 3) is how a continuation is carried and how its arrival is proven. Core
    has always ended the words with the record's marker and proven delivery by finding it in
    Codex's history (A4); a plug may answer CLIENT_ID instead, and core sends the words with no
    marker, under a client id it derives from the interruption, and proves delivery by that id.

    P16 (v0.6.11 stage 3a) is what continues a record whose conversation the app does not hold.
    Core has always waited for the app to open it (A11); a plug may name a route instead - an
    object with a `resume` - and core carries it out itself, as it carries out the send: its one
    claim, its pre-send look and its launch guard, the route called once, and what came of it
    settled by core's own rules (engine/delivery.py).

    P17 (v0.6.14 stage 3b) is whether a failure core never recovers alone is taken up, asked with
    the answers core would carry out for it (failures.takes): taken, it is a core record of its true
    category, which core follows as its own and known_failure (P3) puts to the plug again.

    P20 (v0.6.19) is not a question either: core tells the plug each notice it raises, as P14 tells a move - its kind,
    its category word, its record's place in Pending and when, closed words and numbers only (Guarded.notice), and
    only while the plug wants it. Its answer is not read."""
    RECORDS = "records"                      # P2  records of the advanced store, due now
    GATES = "gates"                          # P3  the gates a record passes before it is sent
    TEXT = "text"                            # P4  what the continuation says
    SENDER = "sender"                        # P5  what the one send is handed to
    OUTCOME = "outcome"                      # P6  what follows a turn that ended
    SCHEDULE = "schedule"                    # P7  when a record is looked at next
    TICK = "tick"                            # P8  once a tick, after everything is observed
    START_ROUTE = "start_route"              # P9  how the watcher is started for Codex
    SURFACES = "surfaces"                    # P10 what the status, the bridge and the panel show
    CLAIM_LEDGER = "claim_ledger"            # P11 the caps counted inside the one claim
    CONCURRENCY = "concurrency"              # P12 how due records are divided for dispatch
    SUPERVISION = "supervision"              # P13 how the launcher keeps the watcher running
    MOVED = "moved"                          # P14 a record core holds moved to another state
    DELIVERY = "delivery"                    # P15 how a continuation is carried and proven
    UNLOADED = "unloaded"                    # P16 what continues one the app does not hold
    ADMISSION = "admission"                  # P17 a failure core never recovers alone, taken up
    SESSIONS = "sessions"                    # P18 which conversations besides the app's core watches
    ELIGIBILITY = "eligibility"              # P19 which of the app's conversations core takes up
    NOTICE = "notice"                        # P20 a notice core raised, told


class Alternative(StrEnum):
    """What a plug may answer at a decision point instead of DEFER (ANSWERS). Core carries out
    every one of them itself."""
    HOLD = "hold"                            # not now: the record keeps waiting, as on a WAIT
    # P15: no marker; queued under the client id core derives from the interruption
    # (ids.continuation_client_id), which is what proves it arrived.
    CLIENT_ID = "client_id"
    # P15 (v0.6.16-beta.4): no words at all, only through a route that takes words - which core then calls with none,
    # under the client id it derives, its proof (engine/routes.py). Through a channel or core's queue, ignored.
    SILENT = "silent"
    # P16 (v0.6.15-beta): the ordinary send to a conversation the app does not hold, left in Codex's queue for
    # when it is opened - kept there only while the plug says so, and seven days and an hour at most.
    QUEUE_FOR_OPEN = "queue_for_open"
    # P16 (v0.6.16-beta.4): the ordinary send to a conversation another Codex session holds - a terminal's, VS
    # Code's - left in Codex's queue for that session to take, and taken back when it ends (engine/tosession.py).
    TO_SESSION = "to_session"
    # P17, and P3 at known_failure: take a failure up, waiting as core waits for an admitted one
    # (ladder.ADMITTED_WAITS), or as a temporary failure of the kind named (PACED_AS).
    ADMIT = "admit"
    AS_NETWORK_TRANSIENT = "as_network_transient"
    AS_TIMEOUT = "as_timeout"
    AS_RATE_LIMIT_TRANSIENT = "as_rate_limit_transient"
    AS_SERVER_5XX = "as_server_5xx"
    AS_STREAM_INTERRUPTED = "as_stream_interrupted"
    CAPACITY = "capacity"                    # and a capacity error retried sooner, in core's limits
    EARLY = "early"                          # P7: a usage-limited record looked at before its time
    RESEND = "resend"                        # P7: an uncertain submission sent once more, if core may
    SEND_NOW = "send_now"                    # P7: a waiting record sent now, as a person asked
    # P13 (v0.6.19): asked at the watcher's start, run it as the launcher's child and stay; asked once a child ended,
    # start it once more. Core asks both and carries neither out yet: that is the commit that builds the supervisor's.
    SUPERVISE = "supervise"
    RESTART = "restart"


class FailureForm(StrEnum):
    """What form a failure's structured error took (failures.shape), as P17 is told it."""
    TAGGED = "tagged"                        # a code of Codex's, known or of the shape of one
    STATUS_ONLY = "status_only"              # a status number and no code
    UNRECOGNISED = "unrecognised"            # something, and neither
    MESSAGE_ONLY = "message_only"            # no structured error, only a message
    ABSENT = "absent"                        # nothing at all


class Surface(StrEnum):
    """What a plug may add to at P10 (SURFACES). What it adds sits under the one key EXTRA,
    beside everything core shows there and never in place of any of it."""
    STATUS = "status"                        # the status the Dashboard, the panel and get_status show
    BRIDGE = "bridge"                        # a bridge command core has none of its own for
    DIAGNOSTICS = "diagnostics"              # the diagnostics export
    TRAY = "tray"                            # what the icon draws from
    MCP = "mcp"                              # tools after core's own, and a call to one of them
