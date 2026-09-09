"use client";

import { useEffect, useMemo, useState } from "react";
import { indianNumber } from "@/lib/format";
import { fmtDateShort, fmtTime, monthLabel, periodMonth } from "@/lib/date";
import { Spinner } from "@/components/ui/spinner";
import { DatePickerInput } from "@/components/ui/date-picker-input";
import { EmptyState } from "@/components/ui/empty-state";
import { getMonthPayments, downloadMonthPaymentsExcel, type MonthPayment } from "@/lib/api";

const FILTERS = [
  { key: "all",     label: "All" },
  { key: "rent",    label: "Rent" },
  { key: "deposit", label: "Deposit" },
  { key: "booking", label: "Advance" },
  { key: "cash",    label: "Cash" },
  { key: "upi",     label: "UPI" },
] as const;

type FilterKey = typeof FILTERS[number]["key"];

const TYPE_LABEL: Record<string, string> = {
  rent: "rent", deposit: "deposit", booking: "advance", maintenance: "maintenance",
};

/** One shared column track. The header row and every data row use this exact string,
 *  so the vertical rules can never drift apart.
 *  NOTE: no `items-center` — that shrinks each cell to its content height and the
 *  border-l segments stop touching, which reads as a dotted line. Cells must stretch. */
const COLS = "grid grid-cols-[1fr_76px_76px_64px]";

/** Vertical rule + stretch. Content is centred inside the cell, not by the grid. */
const CELL = "border-l border-border-strong flex flex-col justify-center";

/** Cash or UPI collected across a set of rows. */
function total(list: MonthPayment[], mode: "cash" | "upi"): number {
  return list.reduce((s, r) => s + (r.mode === mode ? r.amount : 0), 0);
}

/** Every elapsed day of `month`, newest first. The current month stops at today. */
function daysOf(month: string): string[] {
  const [y, m] = month.split("-").map(Number);
  const now = new Date();
  const isCurrent = y === now.getFullYear() && m === now.getMonth() + 1;
  const last = isCurrent ? now.getDate() : new Date(y, m, 0).getDate();
  return Array.from({ length: last }, (_, i) =>
    `${month}-${String(last - i).padStart(2, "0")}`);
}

function todayISOLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dayLabel(iso: string): string {
  return iso === todayISOLocal() ? "Today" : fmtDateShort(iso);
}

export function PaymentsTable() {
  // Derived on the client so the month rolls over on its own with no deploy.
  const month = periodMonth();

  const [rows, setRows] = useState<MonthPayment[] | null>(null);
  const [error, setError] = useState(false);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [q, setQ] = useState("");
  const [day, setDay] = useState("");   // "" = whole month, no totals shown
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let live = true;
    getMonthPayments(month)
      .then(d => { if (live) setRows(d.payments); })
      .catch(() => { if (live) setError(true); });
    return () => { live = false; };
  }, [month]);

  /** Same tenant + amount + purpose on the same day — a likely double entry. */
  const dupIds = useMemo(() => {
    const seen = new Map<string, number>();
    const key = (r: MonthPayment) => `${r.tenant_name}|${r.amount}|${r.for_type}|${r.date}`;
    (rows ?? []).forEach(r => seen.set(key(r), (seen.get(key(r)) ?? 0) + 1));
    return new Set((rows ?? []).filter(r => (seen.get(key(r)) ?? 0) > 1).map(r => r.id));
  }, [rows]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter(r =>
      (!day || r.date === day) &&
      (filter === "all" || r.for_type === filter || r.mode === filter) &&
      (!needle ||
        r.tenant_name.toLowerCase().includes(needle) ||
        r.room_number.toLowerCase().includes(needle)),
    );
  }, [rows, filter, q, day]);

  const byDay = useMemo(() => {
    const m = new Map<string, MonthPayment[]>();
    shown.forEach(r => { if (!m.has(r.date)) m.set(r.date, []); m.get(r.date)!.push(r); });
    return m;
  }, [shown]);

  async function onDownload() {
    setDownloading(true);
    try {
      await downloadMonthPaymentsExcel(month);
    } catch {
      setError(true);
    } finally {
      setDownloading(false);
    }
  }

  if (error && !rows) return <EmptyState>Unable to load payments</EmptyState>;
  if (!rows) return <div className="flex justify-center py-12"><Spinner /></div>;

  return (
    <div>
      <input
        type="search"
        value={q}
        onChange={e => setQ(e.target.value)}
        placeholder="Search name or room…"
        className="w-full px-4 py-2.5 rounded-xl border border-border-strong bg-surface
                   text-sm text-ink placeholder:text-ink-muted
                   focus:outline-none focus:ring-2 focus:ring-brand-pink"
      />

      <div className="flex flex-wrap gap-1.5 mt-3">
        {FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            aria-pressed={filter === f.key}
            className={`px-3 py-1.5 rounded-full text-xs font-medium ${
              filter === f.key
                ? "bg-brand-pink text-white font-semibold"
                : "bg-surface text-ink-muted"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 mt-3">
        <div className="flex-1">
          {/* key resets the picker's own internal state when the filter is cleared,
              otherwise it keeps showing the old date after Clear. */}
          <DatePickerInput key={day || "none"} value={day} onChange={setDay} />
        </div>
        {day && (
          <button
            onClick={() => setDay("")}
            aria-label="Clear date filter"
            className="mt-1 h-[46px] px-4 rounded-lg border border-border-strong bg-surface
                       text-xs font-semibold text-ink-muted whitespace-nowrap
                       focus:outline-none focus:ring-2 focus:ring-brand-pink"
          >
            Clear ✕
          </button>
        )}
      </div>

      {/* Month label and export share a row, so the download is reachable without
          scrolling past the whole month. */}
      <div className="mt-4 px-1 flex items-center justify-between gap-2">
        <span className="px-2 text-[10px] uppercase tracking-[0.1em] font-semibold text-ink-muted">
          Payments · {day ? fmtDateShort(day) : monthLabel(month)}
        </span>
        <button
          onClick={onDownload}
          disabled={downloading}
          aria-label={`Download ${monthLabel(month)} payments as Excel`}
          className="px-3 py-1.5 rounded-full border border-border-strong bg-surface
                     text-[11px] font-semibold text-ink whitespace-nowrap disabled:opacity-60
                     focus:outline-none focus:ring-2 focus:ring-brand-pink"
        >
          {downloading ? "Preparing…" : "↓ Excel"}
        </button>
      </div>

      {shown.length === 0 ? (
        <div className="mt-2"><EmptyState>No payments match</EmptyState></div>
      ) : (
        <div className="mt-2 bg-surface border border-border-strong rounded-[10px] overflow-hidden">
          {(day ? [day] : daysOf(month)).map(d => {
            const list = byDay.get(d) ?? [];
            return (
              <div key={d}>
                {/* Day header — column labels AND that day's totals, at the TOP of its rows.
                    Shares COLS, so the labels and figures sit over their own columns. */}
                <div className={`${COLS} bg-bg border-t border-b border-border-strong`}>
                  <div className="pl-3 pr-2 py-2 flex flex-col justify-center">
                    <span className="text-[10px] uppercase tracking-[0.09em] font-bold text-ink-muted">
                      {dayLabel(d)}
                    </span>
                    <span className="text-[10.5px] text-ink-muted">
                      {list.length} {list.length === 1 ? "payment" : "payments"}
                    </span>
                  </div>
                  <div className={`${CELL} px-2 py-2 text-right`}>
                    <span className="text-[10px] uppercase tracking-[0.1em] font-bold text-method-cash">Cash</span>
                    <span className="text-[13.5px] font-bold tabular-nums text-method-cash">
                      {total(list, "cash") ? indianNumber(total(list, "cash")) : "·"}
                    </span>
                  </div>
                  <div className={`${CELL} px-2 py-2 text-right`}>
                    <span className="text-[10px] uppercase tracking-[0.1em] font-bold text-method-upi">UPI</span>
                    <span className="text-[13.5px] font-bold tabular-nums text-method-upi">
                      {total(list, "upi") ? indianNumber(total(list, "upi")) : "·"}
                    </span>
                  </div>
                  <div className={`${CELL} px-2 pr-3 py-2 text-right justify-end`}>
                    <span className="text-[10px] uppercase tracking-[0.1em] font-bold text-ink-muted">Date</span>
                  </div>
                </div>

                {list.length === 0 ? (
                  <p className="px-3 py-2.5 text-[11.5px] text-ink-muted">
                    Nothing collected on this day.
                  </p>
                ) : list.map(r => {
                  const dup = dupIds.has(r.id);
                  const backdated = r.logged_at.slice(0, 10) !== r.date;
                  return (
                    <div
                      key={r.id}
                      className={`${COLS} border-b border-border-strong last:border-b-0 ${dup ? "bg-tile-orange" : ""}`}
                    >
                      <div className="min-w-0 pl-3 pr-2 py-2 flex flex-col justify-center">
                        <p className="text-[13.5px] font-semibold text-ink truncate">
                          {r.tenant_name}
                          {dup && (
                            <span className="ml-1.5 align-[1px] px-1.5 py-px rounded text-[9.5px] font-bold tracking-wide bg-status-warn text-white">
                              CHECK
                            </span>
                          )}
                        </p>
                        <p className="text-[11px] text-ink-muted truncate">
                          Room {r.room_number || "—"} · {TYPE_LABEL[r.for_type] ?? r.for_type}
                          {backdated && (
                            <span className="ml-1 px-1 rounded bg-bg text-ink">
                              logged {fmtDateShort(r.logged_at.slice(0, 10))}
                            </span>
                          )}
                        </p>
                      </div>
                      <div className={`${CELL} px-2 py-2 text-right text-[13.5px] tabular-nums ${
                        r.mode === "cash" ? "text-method-cash font-semibold" : "text-border-strong"
                      }`}>
                        {r.mode === "cash" ? indianNumber(r.amount) : "·"}
                      </div>
                      <div className={`${CELL} px-2 py-2 text-right text-[13.5px] tabular-nums ${
                        r.mode === "upi" ? "text-method-upi font-semibold" : "text-border-strong"
                      }`}>
                        {r.mode === "upi" ? indianNumber(r.amount) : "·"}
                      </div>
                      <div className={`${CELL} px-2 pr-3 py-2 text-right text-[10.5px] leading-tight text-ink-muted tabular-nums`}>
                        <span className="font-semibold text-ink">{fmtDateShort(r.date)}</span>
                        <span>{fmtTime(r.logged_at)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      <button
        onClick={onDownload}
        disabled={downloading}
        className="mt-3 w-full py-3 rounded-xl border border-border-strong bg-surface
                   text-sm font-semibold text-ink disabled:opacity-60
                   focus:outline-none focus:ring-2 focus:ring-brand-pink"
      >
        {/* Same action as the ↓ Excel button at the top — kept here too so it's at hand
            after scrolling the month. Exports the full month, not the filtered view;
            the .xlsx carries an autofilter so you slice it in Excel. */}
        {downloading ? "Preparing…" : `Download Excel · ${monthLabel(month)}`}
      </button>
    </div>
  );
}
