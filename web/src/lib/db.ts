import "server-only";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";

export type Row = Record<string, any>;

/** The Speeds folder: the one holding data\ and tools\. Works whether Next runs from Speeds or Speeds\web. */
function findRoot(): string {
  const cands = [process.env.SPEEDS_ROOT, process.cwd(), path.resolve(process.cwd(), "..")].filter(Boolean) as string[];
  for (const d of cands) {
    if (fs.existsSync(path.join(d, "data")) || fs.existsSync(path.join(d, "tools", "sl_cards.py"))) return d;
  }
  return process.cwd();
}

export const ROOT = findRoot();
export const CARDS = path.join(ROOT, "data", "cards.sqlite");
export const CACHE = path.join(ROOT, "data", "site_cache.sqlite");

/** Open read-only, run, close straight away (so the scraper / cache builder can replace the files on Windows). */
export function q(file: string, sql: string, args: (string | number | null)[] = []): Row[] {
  if (!fs.existsSync(file)) return [];
  const db = new DatabaseSync(file, { readOnly: true });
  try {
    return db.prepare(sql).all(...args).map((r) => ({ ...(r as Row) }));
  } finally {
    db.close();
  }
}

export function hasTable(file: string, name: string): boolean {
  return q(file, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]).length > 0;
}
