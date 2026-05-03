"use client"

import type { DepositReconcileRow } from "@/lib/api"

function rupeeExact(n: number): string {
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

interface ReconcileCardProps {
  rows: DepositReconcileRow[]
}

export function ReconcileCard({ rows }: ReconcileCardProps) {
  if (rows.length === 0) return null

  const unmatched = rows.filter((r) => r.status === "unmatched").length

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">Deposit Refunds</p>
        {unmatched > 0 && (
          <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-tile-orange text-status-due">
            {unmatched} unmatched
          </span>
        )}
      </div>
      {rows.map((row) => (
        <div key={row.txn_id} className="flex items-center justify-between py-2 border-b border-[#F6F5F0] last:border-none gap-2">
          <div className="flex flex-col gap-0.5 flex-1 min-w-0">
            <span className="text-xs font-semibold text-ink truncate">
              {row.tenant ?? "Unknown tenant"}
            </span>
            <span className="text-[10px] text-ink-muted">{row.txn_date}</span>
          </div>
          <span className="text-xs font-bold text-status-due">-{rupeeExact(row.amount)}</span>
          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap ${
            row.status === "matched"
              ? "bg-tile-green text-status-paid"
              : "bg-tile-orange text-status-due"
          }`}>
            {row.status === "matched" ? "Matched" : "Unmatched"}
          </span>
        </div>
      ))}
    </div>
  )
}
