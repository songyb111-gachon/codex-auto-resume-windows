// The host's stand-ins for S6.3's surfaces (v0.6.27, seat S6.2b): until Integration 10 brings car-v0627-s63's
// [surface] group in, HostMain is compiled and run against these two, which draw nothing and show nothing.
//
//   SurfaceRender  the render and probe modes' entry (S6.3: gui/SurfaceRender.cs): no job and no probe is ever named
//                  here, so both answer null and Main goes on to the core;
//   HostSurfaces   ISurfaces with no icon (S6.3: gui/HostSurfaces.cs): it makes no window, so it never says
//                  tray_started (the core's 5 s wait then reads "no icon", as the reference's Tray.start that could
//                  not start); "close" is answered "closed" at once.
//
// Integration 10 deletes this file and the [standin] group of gui/host.sources; nothing else names it.

using System.Collections.Generic;

namespace CodexAutoResume
{
    internal static class SurfaceRender
    {
        internal static int? Run()
        {
            return null;
        }

        internal static int? Probe(string[] args)
        {
            return null;
        }
    }

    internal sealed class HostSurfaces : ISurfaces
    {
        private IHostActions actions;

        public void Start(SurfacesEvent surfaces)
        {
            actions = surfaces == null ? null : surfaces.Actions;
        }

        public void Snapshot(SnapshotEvent snapshot)
        {
        }

        public void Strings(StringsEvent strings)
        {
        }

        public void Settings(Dictionary<string, object> settings)
        {
        }

        public void Notice(Dictionary<string, object> notice)
        {
        }

        public void Demo(Dictionary<string, object> notice)
        {
        }

        public void Close()
        {
            IHostActions way = actions;
            if (way != null) System.Threading.ThreadPool.QueueUserWorkItem(_ => way.Post(HostActions.Closed, new Dictionary<string, object>()));
        }
    }
}
