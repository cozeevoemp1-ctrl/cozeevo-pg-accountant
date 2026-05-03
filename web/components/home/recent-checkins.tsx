"use client";

import Link from "next/link";
import type { RecentCheckinItem } from "@/lib/api";

interface RecentCheckinsProps {
  items: RecentCheckinItem[];
}

function _shortDate(iso: string): string {
  if (!iso) return "";
  return new Date(iso + "T00:00:00").toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}

function _inr(n: number): string {
  return `₹${n.toLocaleString("en-IN")}`;
}

export function RecentCheckins({ items }: RecentCheckinsProps) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-ink-muted text-center py-4">
        No check-ins in the last 45 days
      </p>
    );
  }

  return (
    <div className="flex flex-col divide-y divide-[#F0EDE9]">
      {items.map((item) => {
        const paid = item.balance === 0;
        const partial = !paid && item.first_month_paid > 0;

        return (
          <Link
            key={item.tenancy_id}
            href={`/tenants/${item.tenancy_id}/edit`}
            className="flex items-center gap-3 py-3 active:opacity-70"
          >
            {/* Avatar */}
            <div
              className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0 ${
                paid
                  ? "bg-tile-green text-status-paid"
                  : "bg-tile-orange text-status-due"
              }`}
            >
              {(item.name[0] ?? "?").toUpperCase()}
            </div>

            {/* Name + room + date */}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-ink truncate">{item.name}</p>
              <p className="text-xs text-ink-muted">
                Room {item.room} · {_shortDate(item.checkin_date)}
                {item.stay_type === "daily" && " · Day-wise"}
              </p>
            </div>

            {/* Payment status */}
            <div className="text-right flex-shrink-0">
              {paid ? (
                <span className="text-xs font-bold text-status-paid bg-tile-green px-2 py-0.5 rounded-pill">
                  Paid
                </span>
              ) : (
                <>
                  <p className="text-sm font-bold text-status-due">
                    {_inr(item.balance)}
                  </p>
                  <p className="text-[10px] text-ink-muted">
                    {partial ? "partial" : "unpaid"}
                  </p>
                </>
              )}
            </div>
          </Link>
        );
      })}
    </div>
  );
}
