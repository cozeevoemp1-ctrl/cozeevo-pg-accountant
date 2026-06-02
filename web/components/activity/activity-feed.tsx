"use client";

import { useState, useMemo } from "react";
import type { ActivityFeedEvent } from "@/lib/api";

const TYPE_CONFIG: Record<ActivityFeedEvent["type"], { icon: string; color: string }> = {
  payment:     { icon: "₹", color: "bg-[#D1FAE5] text-[#065F46]" },
  checkin:     { icon: "→", color: "bg-[#DBEAFE] text-[#1D4ED8]" },
  checkout:    { icon: "←", color: "bg-[#FEF3C7] text-[#92400E]" },
  rent_change: { icon: "↑", color: "bg-[#EDE9FE] text-[#5B21B6]" },
  room_change: { icon: "⇄", color: "bg-[#FCE7F3] text-[#9D174D]" },
  void:        { icon: "✕", color: "bg-[#FEE2E2] text-[#991B1B]" },
  adjustment:  { icon: "~", color: "bg-[#FEF3C7] text-[#78350F]" },
  notice:      { icon: "!", color: "bg-[#FEF3C7] text-[#B45309]" },
  other:       { icon: "•", color: "bg-[#F6F5F0] text-ink-muted" },
};

const FILTERS = [
  { key: "all",         label: "All" },
  { key: "payment",     label: "Payments" },
  { key: "checkin",     label: "Check-ins" },
  { key: "checkout",    label: "Checkouts" },
  { key: "room_change", label: "Room moves" },
  { key: "rent_change", label: "Rent" },
  { key: "notice",      label: "Notices" },
  { key: "void",        label: "Voids" },
] as const;

type FilterKey = typeof FILTERS[number]["key"];

function _dayLabel(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const day   = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff  = Math.round((today.getTime() - day.getTime()) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff > 1 && diff < 7) return d.toLocaleDateString("en-IN", { weekday: "long" });
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function _timeLabel(ts: string): string {
  return new Date(ts).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
}

function _dayKey(ts: string): string {
  const d = new Date(ts);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function _daySummary(evs: ActivityFeedEvent[]): { upi: number; cash: number } | null {
  let upi = 0, cash = 0, found = false;
  for (const ev of evs) {
    if (ev.type !== "payment") continue;
    const parts = ev.label.split(" · ");
    const amt = parseInt((parts[0] || "").replace(/[₹,]/g, ""), 10);
    if (!amt || isNaN(amt)) continue;
    const mode = (parts[1] || "").toLowerCase();
    if (mode === "upi") { upi += amt; found = true; }
    else if (mode === "cash") { cash += amt; found = true; }
  }
  return found ? { upi, cash } : null;
}

function _inr(n: number): string {
  return "₹" + n.toLocaleString("en-IN");
}

export function ActivityFeed({ events }: { events: ActivityFeedEvent[] }) {
  const [filter, setFilter] = useState<FilterKey>("payment");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    let list = events;
    if (filter !== "all") {
      if (filter === "rent_change") list = list.filter(ev => ev.type === "rent_change" || ev.type === "adjustment");
      else list = list.filter(ev => ev.type === filter);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(ev =>
        ev.label?.toLowerCase().includes(q) ||
        ev.sublabel?.toLowerCase().includes(q)
      );
    }
    return list;
  }, [events, filter, search]);

  const groups = useMemo(() => {
    const sorted = [...filtered].sort((a, b) => {
      const ta = a.ts || "";
      const tb = b.ts || "";
      if (tb > ta) return 1;
      if (tb < ta) return -1;
      return 0;
    });
    const map = new Map<string, { key: string; label: string; events: ActivityFeedEvent[] }>();
    const order: string[] = [];
    for (const ev of sorted) {
      const key = _dayKey(ev.ts);
      if (!map.has(key)) {
        map.set(key, { key, label: _dayLabel(ev.ts), events: [] });
        order.push(key);
      }
      map.get(key)!.events.push(ev);
    }
    return order.map(k => map.get(k)!);
  }, [filtered]);

  return (
    <div className="flex flex-col gap-3">
      {/* Search */}
      <input
        type="text"
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search name or room…"
        className="w-full rounded-pill border border-[#E2DEDD] bg-surface px-4 py-2.5 text-sm text-ink outline-none placeholder:text-ink-muted/60"
      />

      {/* Filter chips — wrap so no scroll arrow */}
      <div className="flex flex-wrap gap-2">
        {FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
              filter === f.key
                ? "bg-[#EF1F9C] text-white"
                : "bg-[#F0EDE9] text-ink-muted"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Events grouped by day */}
      {groups.length === 0 ? (
        <p className="text-sm text-ink-muted text-center mt-8">No activity</p>
      ) : (
        groups.map((group) => {
          const summary = _daySummary(group.events);
          return (
          <section key={group.key}>
            <div className="flex items-baseline justify-between mb-2">
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">{group.label}</p>
              {summary && (
                <p className="text-[11px] text-ink-muted font-medium">
                  {summary.upi > 0 && <span>UPI {_inr(summary.upi)}</span>}
                  {summary.upi > 0 && summary.cash > 0 && <span className="mx-1.5 opacity-40">·</span>}
                  {summary.cash > 0 && <span>Cash {_inr(summary.cash)}</span>}
                </p>
              )}
            </div>
            <div className="bg-surface rounded-card border border-[#F0EDE9] divide-y divide-[#F0EDE9]">
              {group.events.map((ev) => {
                const cfg = TYPE_CONFIG[ev.type] ?? TYPE_CONFIG.other;
                return (
                  <div key={ev.id} className="flex items-start gap-3 px-4 py-3">
                    <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5 ${cfg.color}`}>
                      {cfg.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-ink leading-snug">{ev.label}</p>
                      {ev.sublabel && (
                        <p className="text-xs text-ink-muted mt-0.5 truncate">{ev.sublabel}</p>
                      )}
                      {ev.detail && (
                        <p className="text-[11px] text-ink-muted mt-0.5 truncate">{ev.detail}</p>
                      )}
                      {ev.changed_by && (
                        <p className="text-[10px] text-ink-muted/60 mt-1">
                          by {ev.changed_by}{ev.source && ev.source !== "dashboard" ? ` · ${ev.source}` : ""}
                        </p>
                      )}
                    </div>
                    <p className="text-[10px] text-ink-muted flex-shrink-0 mt-0.5">{_timeLabel(ev.ts)}</p>
                  </div>
                );
              })}
            </div>
          </section>
          );
        })
      )}
    </div>
  );
}
