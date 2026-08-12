"use client";

import Link from "next/link";
import { rupee } from "@/lib/format";
import { fmtDateShort } from "@/lib/date";
import { EmptyState } from "@/components/ui/empty-state";
import type { RecentCheckinItem } from "@/lib/api";

interface RecentCheckinsProps {
  items: RecentCheckinItem[];
}

export function RecentCheckins({ items }: RecentCheckinsProps) {
  if (items.length === 0) {
    return <EmptyState>No check-ins in the last 45 days</EmptyState>;
  }

  return (
    <div className="flex flex-col divide-y divide-border">
      {items.map((item) => {
        const paid = item.balance === 0;
        const partial = !paid && item.first_month_paid > 0;

        return (
          <Link
            key={item.tenancy_id}
            href={paid ? `/tenants/${item.tenancy_id}/edit` : `/payment/new?tenancy_id=${item.tenancy_id}`}
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
                Room {item.room} · {fmtDateShort(item.checkin_date)}
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
                    {rupee(item.balance)}
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
