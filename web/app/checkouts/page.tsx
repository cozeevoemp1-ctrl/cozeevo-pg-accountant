"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { getCheckouts, CheckoutListItem } from "@/lib/api";

function fmtDate(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });
}

function fmtINR(n: number) {
  return `₹${n.toLocaleString("en-IN")}`;
}

function monthLabel(ym: string) {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-IN", { month: "long", year: "numeric" });
}

function prevMonth(ym: string) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 2, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function nextMonth(ym: string) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function currentYM() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

type StayFilter = "all" | "monthly" | "daily";

export default function CheckoutsPage() {
  const router = useRouter();
  const [month, setMonth] = useState(currentYM());
  const [items, setItems] = useState<CheckoutListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [stayFilter, setStayFilter] = useState<StayFilter>("all");

  useEffect(() => {
    setLoading(true);
    setError("");
    getCheckouts(month)
      .then(setItems)
      .catch(() => setError("Failed to load checkouts"))
      .finally(() => setLoading(false));
  }, [month]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return items.filter(i => {
      if (stayFilter !== "all" && i.stay_type !== stayFilter) return false;
      if (!q) return true;
      return i.name.toLowerCase().includes(q) || i.room_number.toLowerCase().includes(q);
    });
  }, [items, search, stayFilter]);

  const isCurrentMonth = month === currentYM();

  return (
    <main className="min-h-screen bg-bg pb-32">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9] sticky top-0 z-10">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-ink flex-1">Checkouts</h1>
        {!loading && (
          <span className="w-6 h-6 rounded-full bg-brand-pink text-white text-xs font-bold flex items-center justify-center">
            {items.length}
          </span>
        )}
      </div>

      <div className="px-4 pt-4 flex flex-col gap-3 max-w-lg mx-auto">
        {/* Month picker */}
        <div className="flex items-center gap-2 bg-surface rounded-card border border-[#F0EDE9] px-3 py-2.5">
          <button
            onClick={() => setMonth(prevMonth(month))}
            className="w-8 h-8 rounded-full flex items-center justify-center text-ink-muted font-bold active:bg-[#F0EDE9]"
          >
            ‹
          </button>
          <p className="flex-1 text-center text-sm font-bold text-ink">{monthLabel(month)}</p>
          <button
            onClick={() => setMonth(nextMonth(month))}
            disabled={isCurrentMonth}
            className="w-8 h-8 rounded-full flex items-center justify-center text-ink-muted font-bold active:bg-[#F0EDE9] disabled:opacity-30"
          >
            ›
          </button>
        </div>

        {/* Search + filter */}
        <div className="bg-surface rounded-card border border-[#F0EDE9] px-3 pt-3 pb-2 flex flex-col gap-2">
          <input
            type="text"
            placeholder="Name or room…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full rounded-xl border border-[#E5E1DC] bg-bg px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-brand-pink/40"
          />
          <div className="flex gap-2">
            {(["all", "monthly", "daily"] as StayFilter[]).map(f => (
              <button
                key={f}
                onClick={() => setStayFilter(f)}
                className={`rounded-full px-4 py-1 text-xs font-bold transition-colors ${
                  stayFilter === f
                    ? "bg-brand-pink text-white"
                    : "bg-bg border border-[#E5E1DC] text-ink-muted"
                }`}
              >
                {f === "all" ? "All" : f === "monthly" ? "Regular" : "Day-wise"}
              </button>
            ))}
          </div>
        </div>

        {/* Summary row */}
        {!loading && filtered.length > 0 && (
          <div className="flex gap-2">
            <div className="flex-1 bg-surface rounded-card border border-[#F0EDE9] px-3 py-2 text-center">
              <p className="text-[10px] text-ink-muted uppercase tracking-wide font-semibold">Checkouts</p>
              <p className="text-lg font-extrabold text-ink">{filtered.length}</p>
            </div>
            <div className="flex-1 bg-surface rounded-card border border-[#F0EDE9] px-3 py-2 text-center">
              <p className="text-[10px] text-ink-muted uppercase tracking-wide font-semibold">Refunded</p>
              <p className="text-lg font-extrabold text-status-paid">
                {fmtINR(filtered.reduce((s, i) => s + i.refund_amount, 0))}
              </p>
            </div>
          </div>
        )}

        {/* List */}
        {loading && (
          <div className="flex flex-col gap-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-surface rounded-card border border-[#F0EDE9] h-20 animate-pulse" />
            ))}
          </div>
        )}

        {error && <p className="text-xs text-status-warn text-center py-4">{error}</p>}

        {!loading && !error && filtered.length === 0 && (
          <p className="text-sm text-ink-muted text-center py-8">
            {items.length === 0 ? `No checkouts in ${monthLabel(month)}` : "No results for this filter"}
          </p>
        )}

        {!loading && filtered.map(item => (
          <div key={item.tenancy_id} className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3 flex flex-col gap-2">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-extrabold text-ink">{item.name}</p>
                <p className="text-xs text-ink-muted">Room {item.room_number} · {item.phone}</p>
              </div>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                item.stay_type === "daily"
                  ? "bg-[#EEF6FF] text-[#0070C0]"
                  : "bg-[#F0EDE9] text-ink-muted"
              }`}>
                {item.stay_type === "daily" ? "Day-wise" : "Regular"}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <div>
                <p className="text-ink-muted">Checkout date</p>
                <p className="font-semibold text-ink">{fmtDate(item.checkout_date)}</p>
              </div>
              <div>
                <p className="text-ink-muted">Security deposit</p>
                <p className="font-semibold text-ink">{fmtINR(item.security_deposit)}</p>
              </div>
              <div>
                <p className="text-ink-muted">Agreed rent</p>
                <p className="font-semibold text-ink">{fmtINR(item.agreed_rent)}/mo</p>
              </div>
              <div>
                <p className="text-ink-muted">Refund</p>
                <p className={`font-semibold ${item.refund_amount > 0 ? "text-status-paid" : "text-ink-muted"}`}>
                  {item.refund_amount > 0 ? fmtINR(item.refund_amount) : "—"}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
