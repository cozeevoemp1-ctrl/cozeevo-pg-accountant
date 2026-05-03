"use client";

import { useState } from "react";
import { rupee } from "@/lib/format";
import type { ActivityItem } from "@/lib/api";

interface ActivityFeedProps {
  items: ActivityItem[];
}

function _shortDate(iso: string): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

const METHOD_LABEL: Record<string, string> = {
  upi: "UPI",
  cash: "Cash",
  bank: "Bank",
  card: "Card",
};

export function ActivityFeed({ items }: ActivityFeedProps) {
  const [search, setSearch] = useState("");
  const [newestFirst, setNewestFirst] = useState(true);

  const filtered = items
    .filter((it) => {
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return it.tenant_name.toLowerCase().includes(q) || it.room_number.toLowerCase().includes(q);
    })
    .sort((a, b) => {
      const diff = new Date(b.payment_date).getTime() - new Date(a.payment_date).getTime();
      return newestFirst ? diff : -diff;
    });

  return (
    <div>
      {/* Controls */}
      <div className="flex gap-2 pt-3 pb-2">
        <input
          type="text"
          placeholder="Name or room…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 text-xs rounded-pill bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2 text-ink placeholder:text-ink-muted outline-none focus:ring-1 focus:ring-brand-pink"
        />
        <button
          onClick={() => setNewestFirst((v) => !v)}
          className="flex-shrink-0 text-[10px] font-semibold px-3 py-2 rounded-pill border border-[#E0DDD8] bg-[#F6F5F0] text-ink-muted active:bg-[#EEDFE8] transition-colors"
        >
          {newestFirst ? "Newest ↓" : "Oldest ↑"}
        </button>
      </div>

      {/* List */}
      {filtered.length === 0 ? (
        <p className="text-center text-sm text-ink-muted py-6">No payments found</p>
      ) : (
        <div className="flex flex-col divide-y divide-[#F0EDE9]">
          {filtered.map((item, i) => (
            <div key={i} className="flex items-center gap-3 py-3">
              <div className="w-9 h-9 rounded-full bg-tile-blue flex items-center justify-center text-sm font-bold text-[#0077B6] flex-shrink-0">
                {(item.tenant_name[0] ?? "?").toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-ink truncate">{item.tenant_name}</p>
                <p className="text-xs text-ink-muted">
                  Room {item.room_number} · {METHOD_LABEL[item.method] ?? item.method}
                </p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="text-sm font-bold text-status-paid">{rupee(item.amount)}</p>
                <p className="text-xs text-ink-muted">{_shortDate(item.payment_date)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
