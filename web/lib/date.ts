/**
 * Canonical date/month helpers — THE single source for date display and month
 * arithmetic in the PWA. Never re-implement these in a page/component.
 * See docs/UI_SYSTEM.md.
 *
 * All parsers split ISO strings manually — never `new Date("YYYY-MM-DD")` —
 * to avoid the UTC-midnight timezone off-by-one on IST devices.
 */

const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function parseISO(iso: string): { y: number; m: number; d: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  return { y: +m[1], m: +m[2], d: +m[3] };
}

/** "2026-01-05" → "5 Jan 2026". Empty/null/invalid → "". */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const p = parseISO(iso);
  if (!p) return iso;
  return `${p.d} ${MONTHS_SHORT[p.m - 1]} ${p.y}`;
}

/** "2026-01-05" → "5 Jan". */
export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "";
  const p = parseISO(iso);
  if (!p) return iso;
  return `${p.d} ${MONTHS_SHORT[p.m - 1]}`;
}

/** ISO datetime → "5 Jan 2026, 3:42 PM". Date-only input → fmtDate. */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = /[T ](\d{2}):(\d{2})/.exec(iso);
  if (!t) return fmtDate(iso);
  let h = +t[1];
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${fmtDate(iso)}, ${h}:${t[2]} ${ampm}`;
}

/** Today's local date as "YYYY-MM-DD". */
export function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Current local time as "HH:MM" (24h) — for time inputs. */
export function nowTime(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** "2026-01" → "Jan 2026" (default) or "January 2026" (long). */
export function monthLabel(ym: string, opts?: { long?: boolean }): string {
  const m = /^(\d{4})-(\d{2})/.exec(ym);
  if (!m) return ym;
  const names = opts?.long ? MONTHS_LONG : MONTHS_SHORT;
  return `${names[+m[2] - 1]} ${m[1]}`;
}

/** "2026-01" + delta months → "YYYY-MM". addMonths("2026-01", -1) → "2025-12". */
export function addMonths(ym: string, delta: number): string {
  const m = /^(\d{4})-(\d{2})/.exec(ym);
  if (!m) return ym;
  const total = +m[1] * 12 + (+m[2] - 1) + delta;
  const y = Math.floor(total / 12);
  const mo = (total % 12) + 1;
  return `${y}-${String(mo).padStart(2, "0")}`;
}

/** Date (default now) → "YYYY-MM" period key. */
export function periodMonth(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Date (default now) → bare short month name, e.g. "Aug". */
export function monthShortName(d: Date = new Date()): string {
  return MONTHS_SHORT[d.getMonth()];
}

/** Date (default now) → bare long month name, e.g. "August". */
export function monthLongName(d: Date = new Date()): string {
  return MONTHS_LONG[d.getMonth()];
}
