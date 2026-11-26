// Codex Auto Resume - what the watcher host's surfaces are to the core (v0.6.27, P6 step 0).
//
// The surfaces are the icon, its popup and menu, the tip and the notification cards: drawn by C# (Q1: C# owns their
// layout, motion, stack, shadow and corner), told what to show by the Rust core. ISurfaces is the interface S6.3's
// designer implements; the host's pump (S6.2b) calls it. The names here are the closed tables of
// rust/crates/car-host/src/abi.rs, word for word (tests/test_host_contract.py holds them):
//
//   * events, Rust to C# (HostEvents): each one is {"kind": ..., <fields>}, pulled by HostCore.NextEvent on the pump
//     thread and handed to the UI thread with one posted message. Every kind but "ended" is one ISurfaces method;
//     "ended" is the pump's own (the host exits with its exit_code).
//   * actions, C# to Rust (HostActions): each one is {"action": ..., <fields>}, posted through IHostActions on a worker
//     thread, never the UI thread (a popup call waits for the control layer). A name outside the table is refused by
//     the core ("unknown_action"); a popup call is only one of HostActions.PopupCalls. Q2: the actors stay as today.
//
// Every JSON value arrives as Json.Parse gives it (gui/WindowJson.cs): an object is a Dictionary<string, object>.
// This file is not part of the settings window: it is compiled by tests/test_host_contract.py alone and, from S6.2b,
// into the host through gui/host.sources.
using System.Collections.Generic;

namespace CodexAutoResume
{
    /// The kinds car_next_event hands the host (abi.rs EventKind), in the table's order.
    internal static class HostEvents
    {
        /// icon, strings, settings, edition, demo: build the surfaces, then post tray_started.
        internal const string Surfaces = "surfaces";
        /// snapshot: what the icon and the popup draw from, once per tick.
        internal const string Snapshot = "snapshot";
        /// strings: a new catalog after a language change.
        internal const string Strings = "strings";
        /// settings: the settings the surfaces adopt (theme, design, reduce_motion).
        internal const string Settings = "settings";
        /// notice: one card (its id, view and buttons), only while the cards are attached.
        internal const string Notice = "notice";
        /// notice: one made-up card.
        internal const string Demo = "demo";
        /// Take the surfaces down, then post closed (the core waits up to 5 s).
        internal const string Close = "close";
        /// exit_code: the core's run ended. Always the last event; the pump's, not the surfaces'.
        internal const string Ended = "ended";

        internal static readonly string[] All = { Surfaces, Snapshot, Strings, Settings, Notice, Demo, Close, Ended };
    }

    /// The actions car_post_action takes (abi.rs ActionKind), in the table's order, and the popup's calls.
    internal static class HostActions
    {
        /// The surfaces are up (Tray.start's result).
        internal const string TrayStarted = "tray_started";
        /// The surfaces are down (Tray.stop returning).
        internal const string Closed = "closed";
        /// The card stack attached to the core's inbox.
        internal const string CardsAttached = "cards_attached";
        /// The card stack detached; the core hands what it had not taken on as toasts.
        internal const string CardsDetached = "cards_detached";
        /// paused: the icon's switch (Control.set_enabled).
        internal const string Toggle = "toggle";
        /// The menu's Stop.
        internal const string Stop = "stop";
        /// page, row: open the Dashboard (on a page, at a row).
        internal const string OpenDashboard = "open_dashboard";
        /// thread: open the Dashboard's chat on a conversation.
        internal const string OpenChat = "open_chat";
        /// uri: a card's button, done as its toast button would be (actor "toast").
        internal const string NoticeAction = "notice_action";
        /// id, shown: a card the stack took is ended (notifier.complete).
        internal const string NoticeComplete = "notice_complete";
        /// call, args: one of PopupCalls, done as the popup does it today.
        internal const string Popup = "popup";
        /// The menu's disarm of the power action (actor "tray").
        internal const string DisarmPower = "disarm_power";
        /// The popup marked what it showed as seen.
        internal const string MarkSeen = "mark_seen";
        /// The popup marked the failure it showed as seen.
        internal const string FailureSeen = "failure_seen";

        internal static readonly string[] All = {
            TrayStarted, Closed, CardsAttached, CardsDetached, Toggle, Stop, OpenDashboard, OpenChat, NoticeAction,
            NoticeComplete, Popup, DisarmPower, MarkSeen, FailureSeen };

        /// The whole of what the popup may ask of the control layer (abi.rs POPUP_CALLS, CONTROL_CALLS today).
        internal static readonly string[] PopupCalls = {
            "list_pending", "get_status", "set_enabled", "set_interruption_recovery", "postpone", "unpostpone",
            "release_hold", "set_thread_tier", "set_project_rule", "set_once_words" };
    }

    /// How the surfaces speak to the core: one action of HostActions.All with its fields (a field left out is null).
    /// The answer is the core's JSON text, {"ok": ...}. Called on a worker thread, never the UI thread.
    internal interface IHostActions
    {
        string Post(string action, IDictionary<string, object> fields);
    }

    /// The "surfaces" event: what Start builds the surfaces from.
    internal sealed class SurfacesEvent
    {
        /// The icon file's path.
        internal string Icon { get; set; }
        /// The catalog the surfaces' words come from.
        internal Dictionary<string, object> Strings { get; set; }
        /// The settings the surfaces adopt: theme, design, reduce_motion.
        internal Dictionary<string, object> Settings { get; set; }
        /// The edition the tooltip names (the core's: one host serves both editions, Q3).
        internal string Edition { get; set; }
        /// The demo's name.
        internal string Demo { get; set; }
        /// Where the surfaces post their actions. Set by the pump; not on the wire.
        internal IHostActions Actions { get; set; }
    }

    /// The surfaces as the host's pump drives them. Every method runs on the UI thread, which owns every window.
    internal interface ISurfaces
    {
        /// "surfaces": build the icon, popup, menu, tip and card stack; post tray_started once they are up.
        void Start(SurfacesEvent surfaces);

        /// "snapshot": what the icon and the popup draw from now.
        void Snapshot(Dictionary<string, object> snapshot);

        /// "strings": the words in a new language.
        void Strings(Dictionary<string, object> strings);

        /// "settings": theme, design and reduce_motion, adopted.
        void Settings(Dictionary<string, object> settings);

        /// "notice": one card to show.
        void Notice(Dictionary<string, object> notice);

        /// "demo": one made-up card to show.
        void Demo(Dictionary<string, object> notice);

        /// "close": take every surface down; post closed when they are.
        void Close();
    }
}
