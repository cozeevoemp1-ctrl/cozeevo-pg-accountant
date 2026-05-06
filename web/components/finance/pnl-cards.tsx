"use client"

import type { FinanceMonthData } from "@/lib/api"

function rupee(n: number): string {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`
  if (n >= 1000) return `₹${Math.round(n / 1000)}K`
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

function rupeeExact(n: number): string {
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

interface KpiTilesProps {
  data: FinanceMonthData
}

export function KpiTiles({ data }: KpiTilesProps) {
  return (
    <div className="grid grid-cols-3 gap-2">
      <div className="bg-tile-green rounded-tile p-3">
        <p className="text-[11px] font-extrabold text-status-paid">{rupee(data.income.true_revenue)}</p>
        <p className="text-[9px] text-ink-muted font-semibold mt-0.5">True Revenue</p>
      </div>
      <div className="bg-tile-orange rounded-tile p-3">
        <p className="text-[11px] font-extrabold text-status-due">{rupee(data.total_expense)}</p>
        <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Expense</p>
      </div>
      <div className="bg-tile-pink rounded-tile p-3">
        <p className={`text-[11px] font-extrabold ${data.operating_profit >= 0 ? "text-brand-pink" : "text-status-warn"}`}>
          {rupee(Math.abs(data.operating_profit))}
        </p>
        <p className="text-[9px] text-ink-muted font-semibold mt-0.5">
          {data.operating_profit >= 0 ? "Profit" : "Loss"} · {data.margin_pct}%
        </p>
      </div>
    </div>
  )
}

export function IncomeCard({ data }: KpiTilesProps) {
  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
      <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-2">Gross Inflows</p>
      {data.income.upi_batch > 0 && (
        <div className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0]">
          <span className="text-xs text-ink-muted">Bank — UPI batch settlements</span>
          <span className="text-xs font-bold text-status-paid">{rupeeExact(data.income.upi_batch)}</span>
        </div>
      )}
      {data.income.direct_neft > 0 && (
        <div className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0]">
          <span className="text-xs text-ink-muted">Bank — direct + NEFT</span>
          <span className="text-xs font-bold text-status-paid">{rupeeExact(data.income.direct_neft)}</span>
        </div>
      )}
      {data.income.cash_db > 0 && (
        <div className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0]">
          <span className="text-xs text-ink-muted">Cash (rent only)</span>
          <span className="text-xs font-bold text-status-paid">{rupeeExact(data.income.cash_db)}</span>
        </div>
      )}
      <div className="flex items-center justify-between pt-1.5 border-t border-[#E8E4E0]">
        <span className="text-xs text-ink-muted">Total Gross Inflows</span>
        <span className="text-xs font-bold text-ink">{rupeeExact(data.income.total)}</span>
      </div>
      {data.income.security_deposits > 0 && (
        <div className="flex items-center justify-between py-1">
          <span className="text-xs text-ink-muted italic">Less: Security Deposits (refundable)</span>
          <span className="text-xs text-status-due italic">−{rupeeExact(data.income.security_deposits)}</span>
        </div>
      )}
      <div className="flex items-center justify-between pt-1.5 border-t border-[#E8E4E0]">
        <span className="text-xs font-bold text-ink">True Rent Revenue</span>
        <span className="text-sm font-extrabold text-ink">{rupeeExact(data.income.true_revenue)}</span>
      </div>
    </div>
  )
}

export function ExpenseCard({ data }: KpiTilesProps) {
  const opex    = data.expenses.filter((e) => e.amount > 0)
  const capex   = (data.capex_items   ?? []).filter((e) => e.amount > 0)
  const excl    = (data.excluded_items ?? []).filter((e) => e.amount > 0)
  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
      <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-2">Operating Expenses</p>
      {opex.map((row) => (
        <div key={row.category} className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0] last:border-none">
          <span className="text-xs text-ink-muted">{row.category}</span>
          <span className="text-xs font-bold text-status-due">−{rupeeExact(row.amount)}</span>
        </div>
      ))}
      <div className="flex items-center justify-between pt-2 mt-1">
        <span className="text-xs font-bold text-ink">Total Operating Expenses</span>
        <span className="text-sm font-extrabold text-status-due">−{rupeeExact(data.total_expense)}</span>
      </div>

      {capex.length > 0 && (
        <>
          <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mt-4 mb-2">One-time CAPEX</p>
          {capex.map((row) => (
            <div key={row.category} className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0] last:border-none">
              <span className="text-xs text-ink-muted">{row.category}</span>
              <span className="text-xs font-bold text-ink-muted">−{rupeeExact(row.amount)}</span>
            </div>
          ))}
          {data.total_capex > 0 && (
            <div className="flex items-center justify-between pt-2 mt-1">
              <span className="text-xs font-bold text-ink">Total CAPEX</span>
              <span className="text-sm font-extrabold text-ink-muted">−{rupeeExact(data.total_capex)}</span>
            </div>
          )}
        </>
      )}

      {excl.length > 0 && (
        <>
          <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mt-4 mb-1">Balance Sheet Items (not deducted)</p>
          {excl.map((row) => (
            <div key={row.category} className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0] last:border-none">
              <span className="text-xs text-ink-muted">{row.category}</span>
              <span className="text-xs text-ink-muted">{rupeeExact(row.amount)}</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
