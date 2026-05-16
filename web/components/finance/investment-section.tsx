"use client"

import { useEffect, useState } from "react"
import { getInvestments, type InvestmentsData } from "@/lib/api"

const inr = (n: number) => "₹" + Math.round(n).toLocaleString("en-IN")
const inrShort = (n: number) => {
  const abs = Math.abs(n)
  if (abs >= 100000) return `₹${(abs / 100000).toFixed(1)}L`
  if (abs >= 1000) return `₹${(abs / 1000).toFixed(0)}K`
  return inr(n)
}

export function InvestmentSection() {
  const [data, setData] = useState<InvestmentsData | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getInvestments()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-ink-muted text-sm py-4 text-center">Loading investments…</div>
  if (!data || data.count === 0) return null

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-bold text-ink uppercase tracking-wide">Whitefield Investment</h2>
        <span className="text-xs text-ink-muted">{data.count} transactions</span>
      </div>

      {data.groups.map(group => (
        <div key={group.investor} className="bg-[#0d1520] rounded-2xl overflow-hidden">
          {/* Investor header row */}
          <button
            className="w-full flex items-center justify-between px-4 py-3 gap-2"
            onClick={() => setExpanded(expanded === group.investor ? null : group.investor)}
          >
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-brand-pink uppercase tracking-wide">
                {group.investor}
              </span>
              <span className="text-[10px] text-ink-muted">
                {group.rows.length} txn{group.rows.length !== 1 ? "s" : ""}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-white">{inrShort(group.total)}</span>
              <span className="text-ink-muted text-xs">{expanded === group.investor ? "▲" : "▼"}</span>
            </div>
          </button>

          {/* Transaction rows */}
          {expanded === group.investor && (
            <div className="border-t border-white/5">
              {group.rows.map((row, i) => (
                <div
                  key={row.id}
                  className={`px-4 py-2.5 flex flex-col gap-0.5 ${i % 2 === 0 ? "bg-white/[0.02]" : ""}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-ink truncate">{row.purpose}</p>
                      {row.vendor && (
                        <p className="text-[10px] text-ink-muted truncate">→ {row.vendor}</p>
                      )}
                    </div>
                    <span className="text-xs font-semibold text-white shrink-0">
                      {inr(row.amount)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-ink-muted">{row.date}</span>
                    {row.utr && (
                      <span className="text-[10px] text-ink-muted font-mono truncate max-w-[140px]">
                        {row.utr}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      {/* Grand total */}
      <div className="flex items-center justify-between px-4 py-3 bg-[#0d1520] rounded-2xl border border-brand-pink/20">
        <span className="text-xs font-bold text-ink-muted uppercase tracking-wide">Total Invested</span>
        <span className="text-base font-extrabold text-brand-pink">{inr(data.grand_total)}</span>
      </div>
    </section>
  )
}
