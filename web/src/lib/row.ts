export type Row = Record<string, any>;

/** Dates from Postgres come back as YYYY-MM-DD; keep SQLite-style strings everywhere. */
export function asDate(v: any): any {
  if (v == null) return v;
  if (v instanceof Date) return v.toISOString().slice(0, 10);
  const s = String(v);
  return s.length >= 10 ? s.slice(0, 10) : s;
}

export function normRow(row: Row, dateKeys: string[] = ["date"]): Row {
  const out: Row = { ...row };
  for (const k of dateKeys) if (k in out) out[k] = asDate(out[k]);
  return out;
}
