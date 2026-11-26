// Codex Auto Resume - the watcher host's six imports of car_core.dll (v0.6.27, P6 step 0).
//
// CodexAutoResume.exe is the C# watcher host and car_core.dll the Rust core it loads, in one process. Between the two
// there are exactly six exports, and this file is the host's whole view of them: each DllImport below matches
// rust/crates/car-host/src/abi.rs (export_core!) name for name and type for type, and no other file of ours imports
// car_core.dll (tests/test_host_contract.py holds both).
//
//   Rust (extern "C")                                              C#
//   car_start(*const u8, usize, *mut usize) -> *mut u8             IntPtr car_start(byte[], UIntPtr, out UIntPtr)
//   car_stop() -> i32                                              int car_stop()
//   car_bridge(*const u8, usize, *mut usize) -> *mut u8            IntPtr car_bridge(byte[], UIntPtr, out UIntPtr)
//   car_next_event(u32, *mut usize) -> *mut u8                     IntPtr car_next_event(uint, out UIntPtr)
//   car_post_action(*const u8, usize, *mut usize) -> *mut u8       IntPtr car_post_action(byte[], UIntPtr, out UIntPtr)
//   car_free(*mut u8, usize)                                       void car_free(IntPtr, UIntPtr)
//
// The rules the wrappers keep:
//   * Every request and reply is UTF-8 JSON. A reply is a buffer the core allocated; it is copied out and handed back
//     to car_free exactly once, with its own length, in a finally. No pointer is kept across calls.
//   * car_next_event answers NULL when nothing came within its timeout; NextEvent returns null then.
//   * car_start's reply carries "abi": 1 (Abi). A host given any other number exits 1 (the caller's check, S6.2b).
//   * The core never calls back into managed code, so there is no delegate here to keep alive.
//   * Cdecl is stated for each import: on x64 there is one calling convention and it is Rust's extern "C" too.
//
// The DLL is loaded by full path from the host's own folder before any import binds (P6-DESIGN 1.6, the host's Main,
// S6.2b); these imports then resolve to that module. This file is not part of the settings window: it is compiled by
// tests/test_host_contract.py alone and, from S6.2b, into the host through gui/host.sources.
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace CodexAutoResume
{
    internal static class HostCore
    {
        /// The core's file name, beside the host in app\bin.
        internal const string Dll = "car_core.dll";

        /// The contract's version: car_start's reply carries it (abi.rs ABI).
        internal const int Abi = 1;

        /// UTF-8 without a byte order mark; what cannot be encoded becomes U+FFFD rather than an exception.
        private static readonly Encoding Utf8 = new UTF8Encoding(false, false);

        [DllImport(Dll, EntryPoint = "car_start", CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        private static extern IntPtr car_start(byte[] request, UIntPtr requestLen, out UIntPtr outLen);

        [DllImport(Dll, EntryPoint = "car_stop", CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        private static extern int car_stop();

        [DllImport(Dll, EntryPoint = "car_bridge", CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        private static extern IntPtr car_bridge(byte[] line, UIntPtr len, out UIntPtr outLen);

        [DllImport(Dll, EntryPoint = "car_next_event", CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        private static extern IntPtr car_next_event(uint timeoutMs, out UIntPtr outLen);

        [DllImport(Dll, EntryPoint = "car_post_action", CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        private static extern IntPtr car_post_action(byte[] request, UIntPtr len, out UIntPtr outLen);

        [DllImport(Dll, EntryPoint = "car_free", CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
        private static extern void car_free(IntPtr buffer, UIntPtr len);

        /// car_start: {"argv": [...], "home": ..., "image": ...} -> {"abi": 1, "ok": ...}.
        internal static string Start(string request)
        {
            byte[] bytes = Bytes(request);
            UIntPtr length;
            IntPtr reply = car_start(bytes, Length(bytes), out length);
            return Take(reply, length);
        }

        /// car_stop: the in-process stop. 0 once it is signalled, -1 when the core caught a panic.
        internal static int Stop()
        {
            return car_stop();
        }

        /// car_bridge: one bridge request line -> its reply, the bytes `bridge serve` writes for it.
        internal static string Bridge(string line)
        {
            byte[] bytes = Bytes(line);
            UIntPtr length;
            IntPtr reply = car_bridge(bytes, Length(bytes), out length);
            return Take(reply, length);
        }

        /// car_next_event: the next event, {"kind": ...}, or null when none came within timeoutMs.
        internal static string NextEvent(uint timeoutMs)
        {
            UIntPtr length;
            IntPtr reply = car_next_event(timeoutMs, out length);
            return Take(reply, length);
        }

        /// car_post_action: one action of the closed table (HostActions) -> the core's answer.
        internal static string PostAction(string request)
        {
            byte[] bytes = Bytes(request);
            UIntPtr length;
            IntPtr reply = car_post_action(bytes, Length(bytes), out length);
            return Take(reply, length);
        }

        private static byte[] Bytes(string text)
        {
            return Utf8.GetBytes(text ?? "");
        }

        private static UIntPtr Length(byte[] bytes)
        {
            return new UIntPtr((ulong)bytes.LongLength);
        }

        /// The reply's text, its buffer handed back to car_free once whatever happens; null for a NULL reply.
        private static string Take(IntPtr buffer, UIntPtr length)
        {
            if (buffer == IntPtr.Zero) return null;
            try
            {
                ulong size = length.ToUInt64();
                if (size > int.MaxValue) return null;
                byte[] copy = new byte[(int)size];
                Marshal.Copy(buffer, copy, 0, copy.Length);
                return Utf8.GetString(copy);
            }
            finally
            {
                car_free(buffer, length);
            }
        }
    }
}
