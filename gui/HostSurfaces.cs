// Codex Auto Resume - the surfaces as the host's pump drives them: the class that implements ISurfaces (v0.6.27, S6.3e).
//
// runtime/app.py's _start_tray / _update_tray / refresh_settings and ui/tray/icon.py's start, update, set_strings and stop,
// over the host's surfaces: one TrayIcon (its popup, drawn menu, tip card and notification cards are its own, made as the
// reference makes them). Every method runs on the UI thread, which owns every window; what the surfaces ask of the core
// they post through the event's IHostActions on a worker thread (P6-DESIGN 1.4, 1.5; DECISIONS.md "The popup's model at
// the host boundary" and its addendum: the first frame is drawn in SurfacesEvent.Locale with its Letters).
using System;
using System.Collections.Generic;
using System.Threading;

namespace CodexAutoResume
{
    internal sealed class HostSurfaces : ISurfaces
    {
        /// The host's log line (the watcher's log takes it through the core; the probe keeps it).
        internal Action<string> Log = unused => { };
        /// How a post runs off the UI thread.
        internal Action<Action> Worker = work => ThreadPool.QueueUserWorkItem(unused => work());
        /// How the icon is made (the probe hands one whose calls are recorded).
        internal Func<TrayIcon> MakeTray = () => new TrayIcon();

        private IHostActions actions;
        internal TrayIcon Tray;
        private bool closedPosted;

        /// "surfaces": the icon made with what the core sent - the catalog, its locale and letters, the adopted look - and
        /// tray_started posted once it is up (Tray.start's True). One that cannot be made costs the icon only, as the
        /// reference's _run says: logged, and nothing posted (the core's wait for tray_started ends unanswered).
        public void Start(SurfacesEvent surfaces)
        {
            actions = surfaces.Actions;
            SurfaceTheme.AdoptSettings(surfaces.Settings);
            TrayIcon tray = MakeTray();
            tray.IconPath = surfaces.Icon;
            tray.Strings = surfaces.Strings != null ? new Dictionary<string, object>(surfaces.Strings) : new Dictionary<string, object>();
            tray.Locale = string.IsNullOrEmpty(surfaces.Locale) ? "en" : surfaces.Locale;
            tray.Letters = surfaces.Letters ?? "";
            tray.Edition = surfaces.Edition;
            tray.Days = true;                   // only the watcher's own icon looks at the date (app.py: days=True)
            tray.DemoName = surfaces.Demo;
            tray.Actions = actions;
            tray.Inbox = true;                  // the watcher always has its inbox (App._inbox)
            tray.Pending = true;
            tray.Log = Log;
            tray.Worker = Worker;
            tray.Ended = Ended;
            try
            {
                tray.Create();
            }
            catch (Exception exc)
            {
                Log("tray unavailable (" + TipCard.PythonName(exc) + ")");
                tray.Unregister();
                return;
            }
            Tray = tray;
            Post(HostActions.TrayStarted, new Dictionary<string, object>());
        }

        /// "snapshot": icon_tray.update(snapshot), and the popup's ready view.
        public void Snapshot(SnapshotEvent snapshot)
        {
            if (Tray != null) Tray.Update(snapshot.Snapshot, snapshot.Popup);
        }

        /// "strings": set_strings - the catalog, its locale and its letters.
        public void Strings(StringsEvent strings)
        {
            if (Tray != null) Tray.SetStrings(strings.Strings, strings.Locale, strings.Letters);
        }

        /// "settings": popup.adopt_settings(values), which the popup, the menu and the cards draw with from now.
        public void Settings(Dictionary<string, object> settings)
        {
            SurfaceTheme.AdoptSettings(settings);
            if (Tray != null && Tray.Popup != null) Tray.Popup.FollowSettings(settings);
        }

        /// "notice": one card, on the stack the icon hosts.
        public void Notice(Dictionary<string, object> notice)
        {
            if (Tray != null && Tray.Cards != null) Tray.Cards.Show(notice);
        }

        /// "demo": one made-up card, shown as a notice is.
        public void Demo(Dictionary<string, object> notice)
        {
            Notice(notice);
        }

        /// "close": Tray.stop - the window told to close; its end posts closed. With no icon, closed at once.
        public void Close()
        {
            if (Tray != null && Tray.Hwnd != IntPtr.Zero) Tray.Stop();
            else Ended();
        }

        /// Where the reference's icon thread ended (and Tray.stop returned): the class freed, closed posted once.
        private void Ended()
        {
            if (Tray != null) Tray.Unregister();
            if (closedPosted) return;
            closedPosted = true;
            Post(HostActions.Closed, new Dictionary<string, object>());
        }

        private void Post(string action, Dictionary<string, object> fields)
        {
            IHostActions to = actions;
            if (to == null) return;
            Worker(() =>
            {
                try
                {
                    to.Post(action, fields);
                }
                catch (Exception exc)
                {
                    Log("tray action failed (" + TipCard.PythonName(exc) + ")");
                }
            });
        }
    }
}
