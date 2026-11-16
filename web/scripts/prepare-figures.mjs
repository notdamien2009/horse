// Runs automatically before `npm run dev` and `npm run build` (also: `npm run figures`).
// Builds / refreshes data/site_cache.sqlite from data/speed_v3 (or speed_v2) speed_figures.csv using
// site/figcache.py. It only rebuilds when the CSV changes (first build takes about a minute), then checks
// the cache really has figures in it. If anything is wrong it stops with a clear message instead of
// starting a site with no figures. Emergency bypass: set SKIP_FIGURES=1.
// On Vercel the site reads from Supabase, so this step is skipped (no local CSV / SQLite there).
import { spawnSync } from "node:child_process";
import { existsSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (process.env.VERCEL) {
  console.log("[figures] Vercel build — skipping local figure cache (the live site reads from Supabase).");
  process.exit(0);
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const data = path.join(root, "data");
const cache = path.join(data, "site_cache.sqlite");
const script = path.join(root, "site", "figcache.py");
const line = "=".repeat(78);

function fail(msg) {
  console.error(`\n${line}\n  FIGURES NOT READY - the site was not started\n${line}\n${msg}\n${line}\n`);
  if (process.env.SKIP_FIGURES === "1") { console.error("SKIP_FIGURES=1 set - starting without figures."); process.exit(0); }
  process.exit(1);
}

console.log(`[figures] Speeds folder: ${root}`);
const csv = ["speed_v3", "speed_v2", "speed_v1", "speed"].map((d) => path.join(data, d, "speed_figures.csv")).find(existsSync);
if (!csv) fail(`No speed_figures.csv found in ${path.join(data, "speed_v3")} or ${path.join(data, "speed_v2")}.\nRun RUN_SPEED_FIGURES_V3.bat first.`);
console.log(`[figures] Source: ${csv} (${(statSync(csv).size / 1e6).toFixed(0)} MB)`);
if (!existsSync(script)) fail(`Missing ${script} (the figure cache builder). Put site\\figcache.py back from the site files.`);

const tries = process.platform === "win32" ? [["python"], ["py", "-3"], ["python3"]] : [["python3"], ["python"]];
let ran = false;
const t0 = Date.now();
for (const [cmd, ...pre] of tries) {
  const r = spawnSync(cmd, [...pre, "-u", script], { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (r.error?.code === "ENOENT") continue; // that Python launcher isn't installed - try the next one
  ran = true;
  if (r.stdout) process.stdout.write(r.stdout.trimEnd().replace(/^/gm, "[figures] ") + "\n");
  if (r.status !== 0) {
    const err = (r.stderr || "").trim();
    const hint = /No module named ['"]?pandas/.test(err) ? "\nFix: run   pip install pandas   then npm run dev again." : "";
    fail(`site\\figcache.py failed (exit code ${r.status}) using "${cmd}":\n\n${err.split("\n").slice(-15).join("\n")}${hint}`);
  }
  break;
}
if (!ran) fail("Python was not found (tried python, py -3, python3). Install Python 3 with pandas, or add it to PATH.");

// Check the cache with Node itself - the same way the site reads it. Dynamic import so Vercel never loads node:sqlite.
if (!existsSync(cache)) fail(`The builder finished but ${cache} was not created.`);
let meta, n;
try {
  const { DatabaseSync } = await import("node:sqlite");
  const db = new DatabaseSync(cache, { readOnly: true });
  meta = Object.fromEntries(db.prepare("SELECT k, v FROM meta").all().map((r) => [r.k, r.v]));
  n = db.prepare("SELECT COUNT(*) AS n, COUNT(fig) AS f FROM figs").get();
  db.close();
} catch (e) {
  fail(`Could not read ${cache}: ${e.message}\nDelete that file and run npm run dev again to rebuild it.`);
}
if (!n.f) fail(`${cache} has ${n.n} rows but no figures in it. Check ${csv}.`);
if (path.resolve(meta.src) !== path.resolve(csv)) console.warn(`[figures] Note: cache was built from ${meta.src}, expected ${csv}.`);
console.log(`[figures] READY: ${meta.version} - ${Number(n.n).toLocaleString("en-GB")} runs (${Number(n.f).toLocaleString("en-GB")} with a figure), races up to ${meta.max_date}, 2yo scale ${meta.has_2yo === "1" ? "yes" : "no"} (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
