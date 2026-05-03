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
        <p className="text-[11px] font-extrabold text-status-paid">{rupee(data.income.total)}</p>
        <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Income</p>
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
  const rows = [
    { label: "Bank — UPI batch settlements", amount: data.income.upi_batch },
    { label: "Bank — direct + NEFT", amount: data.income.direct_neft },
    { label: "Cash (PWA recorded)", amount: data.income.cash_db },
  ]
  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
      <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-2">Income</p>
      {rows.map((row) => (
        <div key={row.label} className="flex items-center justify-between py-2 border-b border-[#F6F5F0] last:border-none">
          <span className="text-xs text-ink-muted">{row.label}</span>
          <span className="text-xs font-bold text-status-paid">{rupeeExact(row.amount)}</span>
        </div>
      ))}
      <div className="flex items-center justify-between pt-2 mt-1">
        <span className="text-xs font-bold text-ink">Total Revenue</span>
        <span className="text-sm font-extrabold text-ink">{rupeeExact(data.income.total)}</span>
      </div>
    </div>
  )
}

export function ExpenseCard({ data }: KpiTilesProps) {
  const nonEmpty = data.expenses.filter((e) => e.amount > 0)
  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
      <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-2">Expenses</p>
      {nonEmpty.map((row) => (
        <div key={row.category} className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0] last:border-none">
          <span className="text-xs text-ink-muted">{row.category}</span>
          <span className="text-xs font-bold text-status-due">−{rupeeExact(row.amount)}</span>
        </div>
      ))}
      <div className="flex items-center justify-between pt-2 mt-1">
        <span className="text-xs font-bold text-ink">Total Expenses</span>
        <span className="text-sm font-extrabold text-status-due">−{rupeeExact(data.total_expense)}</span>
      </div>
    </div>
  )
}
