// Codex Auto Resume - ending a child of the window's, with what it started (v0.6.18).
//
// The one-shot bridge (Bridge.Call in gui/SettingsApp.cs) runs controlcli in a python.exe of its own. When that child
// does not answer in time it is ended - and so is what it started and still runs, since a probe of Codex that kept
// the child's stdout open holds the window's read of it past the child's own end. .NET Framework has no
// Kill(entireProcessTree), so the tree is read from one snapshot of every process (CreateToolhelp32Snapshot): the
// child's descendants by parent id, each one started no earlier than its parent - a process id Windows has given out
// again since is someone else's.
//
// The watcher is never ended (control/watcher.py, stop_watcher: a watcher stopped mid-submission cannot prove whether
// it sent the continuation). It is the one process controlcli starts under pythonw.exe, detached and with no handle
// of the window's, so a pythonw.exe, and everything under it, is left as it is wherever it is in the tree.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace CodexAutoResume
{
    internal static class ChildTree
    {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct ProcessEntry
        {
            public int Size;
            public int Usage;
            public int ProcessId;
            public IntPtr DefaultHeap;
            public int ModuleId;
            public int Threads;
            public int ParentProcessId;
            public int BasePriority;
            public int Flags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
            public string ExeFile;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateToolhelp32Snapshot(int flags, int process);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool Process32FirstW(IntPtr snapshot, ref ProcessEntry entry);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool Process32NextW(IntPtr snapshot, ref ProcessEntry entry);

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);

        private const int TH32CS_SNAPPROCESS = 0x00000002;
        private static readonly IntPtr Invalid = new IntPtr(-1);

        /// The image the watcher runs under, which is never ended.
        internal const string Spared = "pythonw.exe";

        /// One process as the snapshot listed it.
        internal struct Listed
        {
            internal int Id, Parent;
            internal string Image;
        }

        /// Every process now, by id, parent and image; empty when Windows would not list them.
        internal static List<Listed> Snapshot()
        {
            var all = new List<Listed>();
            IntPtr snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if (snapshot == IntPtr.Zero || snapshot == Invalid) return all;
            try
            {
                var entry = new ProcessEntry();
                entry.Size = Marshal.SizeOf(typeof(ProcessEntry));
                if (!Process32FirstW(snapshot, ref entry)) return all;
                do
                {
                    var one = new Listed();
                    one.Id = entry.ProcessId;
                    one.Parent = entry.ParentProcessId;
                    one.Image = entry.ExeFile ?? "";
                    all.Add(one);
                    entry.Size = Marshal.SizeOf(typeof(ProcessEntry));
                } while (Process32NextW(snapshot, ref entry));
            }
            finally
            {
                CloseHandle(snapshot);
            }
            return all;
        }

        /// The ids under `root` in `all`, nearest first, leaving out a Spared image and everything under it. Pure, so
        /// the rule can be checked without a process; `startedAt` answers when an id was started (DateTime.MaxValue
        /// when it cannot be told), and a child started before its parent is not its child.
        internal static List<int> Under(int root, List<Listed> all, Func<int, DateTime> startedAt)
        {
            var found = new List<int>();
            var seen = new HashSet<int> { root };
            var parents = new Queue<int>();
            parents.Enqueue(root);
            while (parents.Count > 0)
            {
                int parent = parents.Dequeue();
                DateTime parentStart = startedAt(parent);
                foreach (Listed one in all)
                {
                    if (one.Parent != parent || one.Id == parent || seen.Contains(one.Id)) continue;
                    if (string.Equals(one.Image, Spared, StringComparison.OrdinalIgnoreCase)) continue;
                    DateTime start = startedAt(one.Id);
                    if (parentStart != DateTime.MaxValue && start != DateTime.MaxValue && start < parentStart) continue;
                    seen.Add(one.Id);
                    found.Add(one.Id);
                    parents.Enqueue(one.Id);
                }
            }
            return found;
        }

        /// Ends `child` and every process under it but the watcher's (Under). What has ended already, or cannot be
        /// opened, is passed over: this never throws.
        internal static void End(Process child)
        {
            if (child == null) return;
            int id;
            DateTime childStart;
            try
            {
                id = child.Id;
                childStart = child.StartTime;
            }
            catch (Exception) { return; }
            List<int> under;
            try
            {
                under = Under(id, Snapshot(), delegate(int pid)
                {
                    if (pid == id) return childStart;
                    try { using (Process one = Process.GetProcessById(pid)) return one.StartTime; }
                    catch (Exception) { return DateTime.MaxValue; }
                });
            }
            catch (Exception) { under = new List<int>(); }
            // The child first, so it starts nothing more; then what it had started.
            try { if (!child.HasExited) child.Kill(); }
            catch (Exception) { }
            foreach (int pid in under)
            {
                try
                {
                    using (Process one = Process.GetProcessById(pid))
                        if (one.StartTime >= childStart && !one.HasExited) one.Kill();
                }
                catch (Exception) { }
            }
        }
    }
}
