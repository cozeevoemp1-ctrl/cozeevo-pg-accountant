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

/** One shared column track — the header row and every data row use this exact string,
 *  so the vertical rules can never drift apart. */
const COLS = "grid grid-cols-[1fr_76px_76px_64px]";

/** Cash or UPI collected across a day's rows. */
function dayTotal(list: MonthPayment[], mode: "cash" | "upi"): number {
  return list.reduce((s, r) => s + (r.mode === mode ? r.amount : 0), 0);
}

/** Every elapsed day of `month`, newest first. Current month stops at today. */
function daysOf(month: string): string[] {
  const [y, m] = month.split("-").map(Number);
  const now = new Date();
  const isCurrent = y === now.getFullYear() && m === now.getMonth() + 1;
  const last = isCurrent ? now.getDate() : new Date(y, m, 0).getDate();
  return Array.from({ length: last }, (_, i) =>
    `${month}-${String(last - i).padStart(2, "0")}`);
}

function dayLabel(iso: string): string {
  return iso === todayISOLocal() ? "Today" : fmtDateShort(iso);
}

function todayISOLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function PaymentsTable() {
  // Derived on the client so the month rolls over on its own with no deploy.
  const month = periodMonth();

  const [rows, setRows] = useState<MonthPayment[] | null>(null);
  const [error, setError] = useState(false);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [q, setQ] = useState("");
  const [day, setDay] = useState("");   // "" = whole month
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
    const count = new Map<string, number>();
    (rows ?? []).forEach(r => {
      const k = `${r.tenant_name}|${r.amount}|${r.for_type}|${r.date}`;
      count.set(k, (count.get(k) ?? 0) + 1);
    });
    return new Set(
      (rows ?? [])
        .filter(r => (count.get(`${r.tenant_name}|${r.amount}|${r.for_type}|${r.date}`) ?? 0) > 1)
        .map(r => r.id),
    );
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
          <DatePickerInput value={day} onChange={setDay} />
        </div>
        {day && (
          <button
            onClick={() => setDay("")}
            className="px-3 py-2 rounded-xl border border-border-strong bg-surface text-xs font-medium text-ink-muted"
          >
            Clear
          </button>
        )}
      </div>

      <p className="mt-4 px-3 text-[10px] uppercase tracking-[0.1em] font-semibold text-ink-muted">
        Payments · {day ? fmtDateShort(day) : monthLabel(month)}
      </p>

      {shown.length === 0 ? (
        <div className="mt-2"><EmptyState>No payments match</EmptyState></div>
      ) : (
        <div className="mt-2 bg-surface border border-border-strong rounded-[10px] overflow-hidden">
          {(day ? [day] : daysOf(month)).map(d => {
            const list = byDay.get(d) ?? [];
            return (
              <div key={d}>
                {/* Header row repeats per day and shares COLS, so labels always sit over their columns */}
                <div className={`${COLS} items-end bg-bg border-t border-b border-border-strong first:border-t-0`}>
                  <span className="pl-3 pr-2 pt-2 pb-1.5 text-[10px] uppercase tracking-[0.09em] font-bold text-ink-muted">
                    {dayLabel(d)}
                  </span>
                  <span className="border-l border-border-strong px-2 pt-2 pb-1.5 text-right text-[10px] uppercase tracking-[0.1em] font-bold text-method-cash">
                    Cash
                  </span>
                  <span className="border-l border-border-strong px-2 pt-2 pb-1.5 text-right text-[10px] uppercase tracking-[0.1em] font-bold text-method-upi">
                    UPI
                  </span>
                  <span className="border-l border-border-strong px-2 pr-3 pt-2 pb-1.5 text-right text-[10px] uppercase tracking-[0.1em] font-bold text-ink-muted">
                    Date
                  </span>
                </div>

                {list.length === 0 ? (
                  <p className="px-3 py-2.5 text-[11.5px] text-ink-muted">
                    Nothing collected on this day.
                  </p>
                ) : <>{list.map(r => {
                  const dup = dupIds.has(r.id);
                  const backdated = r.logged_at.slice(0, 10) !== r.date;
                  return (
                    <div
                      key={r.id}
                      className={`${COLS} items-center border-b border-border-strong last:border-b-0
                                  ${dup ? "bg-[#FDF3E6]" : ""}`}
                    >
                      <div className="min-w-0 pl-3 pr-2 py-2">
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
                      <div className={`border-l border-border-strong px-2 py-2 text-right text-[13.5px] font-semibold tabular-nums ${
                        r.mode === "cash" ? "text-method-cash" : "text-border-strong font-normal"
                      }`}>
                        {r.mode === "cash" ? indianNumber(r.amount) : "·"}
                      </div>
                      <div className={`border-l border-border-strong px-2 py-2 text-right text-[13.5px] font-semibold tabular-nums ${
                        r.mode === "upi" ? "text-method-upi" : "text-border-strong font-normal"
                      }`}>
                        {r.mode === "upi" ? indianNumber(r.amount) : "·"}
                      </div>
                      <div className="border-l border-border-strong px-2 pr-3 py-2 text-right text-[10.5px] leading-tight text-ink-muted tabular-nums">
                        <span className="block font-semibold text-ink">{fmtDateShort(r.date)}</span>
                        {fmtTime(r.logged_at)}
                      </div>
                    </div>
                  );
                })}
                  {/* Day subtotal — what should be in the cash box at close of day. */}
                  <div className={`${COLS} items-center border-b border-border-strong last:border-b-0 bg-bg`}>
                    <span className="pl-3 pr-2 py-2 text-[11px] font-semibold text-ink-muted">
                      {dayLabel(d)} total · {list.length} {list.length === 1 ? "payment" : "payments"}
                    </span>
                    <span className="border-l border-border-strong px-2 py-2 text-right text-[13px] font-bold tabular-nums text-method-cash">
                      {dayTotal(list, "cash") ? indianNumber(dayTotal(list, "cash")) : "·"}
                    </span>
                    <span className="border-l border-border-strong px-2 py-2 text-right text-[13px] font-bold tabular-nums text-method-upi">
                      {dayTotal(list, "upi") ? indianNumber(dayTotal(list, "upi")) : "·"}
                    </span>
                    <span className="border-l border-border-strong px-2 pr-3 py-2" />
                  </div>
                </>}
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
        {/* Exports the full month, not the filtered view — the .xlsx carries an
            autofilter so you slice it in Excel. */}
        {downloading ? "Preparing…" : `Download Excel · ${monthLabel(month)}`}
      </button>
    </div>
  );
}
