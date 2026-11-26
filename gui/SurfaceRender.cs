// Codex Auto Resume - the host's render mode: the surfaces laid out (and drawn) into memory, never on a screen
// (v0.6.27, S6.3; P6-DESIGN 3.2).
//
// With CODEX_AR_RENDER_PLAN naming a job, CodexAutoResume.exe loads no DLL and makes no window anybody sees (the host's
// Main, S6.2b, hands the job here before anything else: SurfaceRender.Run). A job is JSON:
//
//   {"format": "car-surface-job/1",
//    "tables": {name: {"measure": [[role, text, width, flags, w, h], ...], "metrics": {role: [ascent, x]},
//                      "ink": [[role, text, first, last], ...]}},
//    "cases": [{"id": ..., "surface": "popup" | "menu" | "tip" | "card" | "icon" | ..., "table": name, ...}, ...]}
//
// and the answer, written to CODEX_AR_RENDER_OUT (or the job's path with ".out.json"), is the plan dump: for every case
// its plan as JSON - every rectangle, every text run with its role, colour and alignment, every target - under the
// Python's own keys, or the error that stopped it. Text is measured from the job's table (TableTextCalc), so a plan is
// the reference's exactly when the arithmetic is, whatever fonts the machine has (comparison A,
// tests/test_surface_parity.py). Nothing here shows, posts or starts anything.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace CodexAutoResume
{
    internal static class SurfaceRender
    {
        /// The variable that names a job.
        internal const string JobVariable = "CODEX_AR_RENDER_PLAN";
        /// The variable that names where the answer goes.
        internal const string OutVariable = "CODEX_AR_RENDER_OUT";
        internal const string Format = "car-surface-job/1";

        /// The host's Main asks this first: the exit code of the job CODEX_AR_RENDER_PLAN names, or null when none does.
        internal static int? Run()
        {
            string job = Environment.GetEnvironmentVariable(JobVariable);
            if (string.IsNullOrEmpty(job)) return null;
            string output = Environment.GetEnvironmentVariable(OutVariable);
            return RunJob(job, string.IsNullOrEmpty(output) ? job + ".out.json" : output);
        }

        /// One job from `jobPath` into `outPath`: 0 when every case was laid out, 1 when any case failed (its error is
        /// in the answer), 2 when the job could not be read at all.
        internal static int RunJob(string jobPath, string outPath)
        {
            Dictionary<string, object> job;
            try
            {
                job = (Dictionary<string, object>)Json.Parse(File.ReadAllText(jobPath, new UTF8Encoding(false)));
                if ((job["format"] as string) != Format) throw new FormatException("not a " + Format + " job");
            }
            catch (Exception exc)
            {
                Write(outPath, new Dictionary<string, object> { { "error", exc.GetType().Name + ": " + exc.Message } });
                return 2;
            }
            var tables = new Dictionary<string, TableTextCalc>();
            object tableValue;
            if (job.TryGetValue("tables", out tableValue) && tableValue != null)
                foreach (KeyValuePair<string, object> pair in (Dictionary<string, object>)tableValue)
                {
                    var table = (Dictionary<string, object>)pair.Value;
                    tables[pair.Key] = new TableTextCalc(Field(table, "measure") as List<object>,
                                                         Field(table, "metrics") as Dictionary<string, object>,
                                                         Field(table, "ink") as List<object>);
                }
            var answers = new List<object>();
            bool failed = false;
            foreach (object entry in (List<object>)job["cases"])
            {
                var task = (Dictionary<string, object>)entry;
                var answer = new Dictionary<string, object>();
                answer["id"] = Field(task, "id");
                try
                {
                    answer["plan"] = Dump(Case(task, tables));
                }
                catch (Exception exc)
                {
                    failed = true;
                    answer["error"] = exc.GetType().Name + ": " + exc.Message;
                }
                answers.Add(answer);
            }
            Write(outPath, new Dictionary<string, object> { { "format", Format }, { "cases", answers } });
            return failed ? 1 : 0;
        }

        private static void Write(string path, Dictionary<string, object> value)
        {
            File.WriteAllText(path, Json.Write(value), new UTF8Encoding(false));
        }

        internal static object Field(Dictionary<string, object> map, string key)
        {
            object value;
            return map != null && map.TryGetValue(key, out value) ? value : null;
        }

        private static double Number(Dictionary<string, object> map, string key)
        {
            return (double)map[key];
        }

        private static SurfaceText Measure(Dictionary<string, object> task, Dictionary<string, TableTextCalc> tables,
                                           string locale)
        {
            object name = Field(task, "table");
            if (name == null) return null;
            return new SurfaceText(tables[(string)name], locale);
        }

        /// One case's plan (or plans), as the surface's own layout makes it.
        private static object Case(Dictionary<string, object> task, Dictionary<string, TableTextCalc> tables)
        {
            string surface = (string)task["surface"];
            string locale = Field(task, "locale") as string;
            SurfaceText measure = Measure(task, tables, locale);
            switch (surface)
            {
                case "popup":
                    return PopupLayout.Plan((Dictionary<string, object>)task["vm"], Number(task, "scale"), locale, measure);
            }
            throw new NotSupportedException("no surface " + surface);
        }

        // ----------------------------------------------------------------------------- the dump

        /// Any plan value as Json.Write takes it: numbers as doubles, arrays and tuples as lists, a plan as the Python's
        /// dictionary.
        internal static object Dump(object value)
        {
            if (value == null || value is string || value is bool || value is double) return value;
            if (value is int) return (double)(int)value;
            if (value is long) return (double)(long)value;
            if (value is uint) return (double)(uint)value;
            if (value is float) return (double)(float)value;
            var target = value as SurfaceTarget;
            if (target != null) return Dump(target.ToList());
            var plan = value as SurfacePlan;
            if (plan != null) return DumpPlan(plan);
            var map = value as IDictionary<string, object>;
            if (map != null)
            {
                var dumped = new Dictionary<string, object>();
                foreach (KeyValuePair<string, object> pair in map) dumped[pair.Key] = Dump(pair.Value);
                return dumped;
            }
            if (value is KeyValuePair<object, int[]>)
            {
                var pair = (KeyValuePair<object, int[]>)value;
                return new List<object> { Dump(pair.Key), Dump(pair.Value) };
            }
            var list = value as IEnumerable;
            if (list != null)
            {
                var dumped = new List<object>();
                foreach (object entry in list) dumped.Add(Dump(entry));
                return dumped;
            }
            throw new FormatException("cannot dump a " + value.GetType().Name);
        }

        private static Dictionary<string, object> DumpPlan(SurfacePlan plan)
        {
            var dumped = new Dictionary<string, object>();
            dumped["size"] = Dump(plan.Size);
            dumped["card"] = Dump(plan.Card);
            dumped["items"] = Dump(plan.Items);
            dumped["targets"] = Dump(plan.Targets);
            dumped["scale"] = plan.Scale;
            if (plan.Rows != null) dumped["rows"] = Dump(plan.Rows);
            if (plan.Rtl.HasValue) dumped["rtl"] = plan.Rtl.Value;
            return dumped;
        }
    }
}
