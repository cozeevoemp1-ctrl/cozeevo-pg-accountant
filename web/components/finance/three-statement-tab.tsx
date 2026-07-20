"use client"

import { useEffect, useState } from "react"
import { supabase } from "@/lib/supabase"

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.getkozzy.com"

function inr(n: number) {
  if (n === 0) return "0"
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  if (abs >= 1_00_00_000) return `${sign}₹${(abs / 1_00_00_000).toFixed(2)}Cr`
  if (abs >= 1_00_000)    return `${sign}₹${(abs / 1_00_000).toFixed(1)}L`
  if (abs >= 1_000)       return `${sign}₹${(abs / 1_000).toFixed(1)}K`
  return `${sign}₹${abs.toFixed(0)}`
}

function inrFull(n: number) {
  const sign = n < 0 ? "-" : ""
  return `${sign}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function Row({ label, value, bold, indent, positive, negative, muted }: {
  label: string
  value: number
  bold?: boolean
  indent?: boolean
  positive?: boolean
  negative?: boolean
  muted?: boolean
}) {
  const color = positive && value > 0 ? "text-green-600" :
                negative && value < 0 ? "text-red-500" :
                muted ? "text-ink-muted" : ""
  return (
    <div className={`flex justify-between items-center py-1.5 ${bold ? "border-t border-ink-muted/20 mt-1 pt-2" : ""}`}>
      <span className={`text-sm ${indent ? "pl-3" : ""} ${bold ? "font-bold text-ink" : "text-ink-muted"} ${muted ? "text-xs" : ""}`}>
        {label}
      </span>
      <span className={`text-sm font-mono ${bold ? "font-bold" : ""} ${color || (value < 0 ? "text-red-500" : "text-ink")}`}>
        {inrFull(value)}
      </span>
    </div>
  )
}

function Section({ title, color, children }: { title: string; color: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-white shadow-sm border border-ink-muted/10 overflow-hidden">
      <div className={`px-4 py-2.5 ${color}`}>
        <span className="text-xs font-bold uppercase tracking-widest text-white">{title}</span>
      </div>
      <div className="px-4 py-2 pb-3">{children}</div>
    </div>
  )
}

function Divider() {
  return <div className="border-t border-ink-muted/10 my-1" />
}

interface ThreeStatement {
  month: string
  pnl: {
    bank_rent: number
    cash_rent: number
    other_income: number
    total_revenue: number
    opex_breakdown: Record<string, number>
    total_opex: number
    net_income: number
  }
  balance_sheet: {
    assets: {
      cash_and_bank: number
      net_fixed_assets: number
      gross_fixed_assets: number
      accumulated_depreciation: number
      lease_deposit: number
    }
    total_assets: number
    liabilities: { tenant_deposits_held: number }
    total_liabilities: number
    equity: {
      investor_capital: number
      investor_breakdown: Record<string, number>
      retained_earnings: number
    }
    total_equity: number
    total_liabilities_equity: number
    check_balanced: boolean
  }
  cash_flow: {
    operating: { net_income: number; depreciation: number; change_in_deposits_held: number }
    total_operating: number
    investing: { capex: number; deposit_refunds_paid: number }
    total_investing: number
    financing: { investor_capital_received: number }
    total_financing: number
    net_cash_flow: number
    beginning_cash: number
    ending_cash: number
    cash_reconciled: boolean
  }
}

function currentMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
}

export function ThreeStatementTab() {
  const [month, setMonth] = useState(currentMonth())
  const [data, setData] = useState<ThreeStatement | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [expandOpex, setExpandOpex] = useState(false)
  const [expandInvestors, setExpandInvestors] = useState(false)

  async function load(m: string) {
    setLoading(true)
    setError("")
    setData(null)
    try {
      const { data: { session } } = await supabase().auth.getSession()
      const token = session?.access_token
      const res = await fetch(
        `${BASE_URL}/api/v2/app/finance/three-statement?month=${m}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: "no-store" }
      )
      if (!res.ok) throw new Error(`${res.status}`)
      setData(await res.json())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(month) }, [month])

  return (
    <div className="flex flex-col gap-4">
      {/* Month picker */}
      <div className="flex items-center gap-3">
        <span className="text-xs font-bold text-ink-muted uppercase tracking-wide">Month</span>
        <input
          type="month"
          value={month}
          onChange={e => setMonth(e.target.value)}
          className="flex-1 rounded-xl border border-ink-muted/20 px-3 py-2 text-sm bg-white text-ink focus:outline-none focus:border-brand-pink"
        />
      </div>

      {loading && (
        <div className="text-center py-10 text-ink-muted text-sm">Loading...</div>
      )}
      {error && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-600">{error}</div>
      )}

      {data && (
        <>
          {/* ── P&L ── */}
          <Section title="Profit & Loss" color="bg-brand-pink">
            <Row label="UPI / Bank Rent" value={data.pnl.bank_rent} indent />
            <Row label="Cash Rent" value={data.pnl.cash_rent} indent />
            <Row label="Other Income" value={data.pnl.other_income} indent />
            <Row label="Total Revenue" value={data.pnl.total_revenue} bold positive />
            <Divider />
            {/* OPEX summary + expand */}
            <button
              className="w-full flex justify-between items-center py-1.5 text-sm text-ink-muted"
              onClick={() => setExpandOpex(x => !x)}
            >
              <span>Operating Expenses {expandOpex ? "▲" : "▼"}</span>
              <span className="font-mono text-red-500">{inrFull(-data.pnl.total_opex)}</span>
            </button>
            {expandOpex && Object.entries(data.pnl.opex_breakdown)
              .sort((a, b) => b[1] - a[1])
              .map(([cat, val]) => (
                <Row key={cat} label={cat} value={-val} indent muted />
              ))
            }
            <Divider />
            <Row
              label="Net Income"
              value={data.pnl.net_income}
              bold
              positive={data.pnl.net_income > 0}
              negative={data.pnl.net_income < 0}
            />
          </Section>

          {/* ── Balance Sheet ── */}
          <Section title="Balance Sheet" color="bg-[#6C47FF]">
            <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">Assets</span>
            <Row label="Cash & Bank" value={data.balance_sheet.assets.cash_and_bank} indent />
            <Row label="Fixed Assets (net)" value={data.balance_sheet.assets.net_fixed_assets} indent />
            <Row label="  Gross" value={data.balance_sheet.assets.gross_fixed_assets} indent muted />
            <Row label="  Accum. Depreciation" value={-data.balance_sheet.assets.accumulated_depreciation} indent muted />
            <Row label="Lease Deposit" value={data.balance_sheet.assets.lease_deposit} indent />
            <Row label="Total Assets" value={data.balance_sheet.total_assets} bold />
            <Divider />
            <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">Liabilities</span>
            <Row label="Tenant Deposits Held" value={data.balance_sheet.liabilities.tenant_deposits_held} indent />
            <Row label="Total Liabilities" value={data.balance_sheet.total_liabilities} bold />
            <Divider />
            <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">Equity</span>
            <button
              className="w-full flex justify-between items-center py-1.5 text-sm text-ink-muted"
              onClick={() => setExpandInvestors(x => !x)}
            >
              <span>Investor Capital {expandInvestors ? "▲" : "▼"}</span>
              <span className="font-mono text-ink">{inrFull(data.balance_sheet.equity.investor_capital)}</span>
            </button>
            {expandInvestors && Object.entries(data.balance_sheet.equity.investor_breakdown)
              .sort((a, b) => b[1] - a[1])
              .map(([name, val]) => (
                <Row key={name} label={name} value={val} indent muted />
              ))
            }
            <Row label="Retained Earnings" value={data.balance_sheet.equity.retained_earnings} indent />
            <Row label="Total Equity" value={data.balance_sheet.total_equity} bold />
            <Divider />
            <Row label="Liabilities + Equity" value={data.balance_sheet.total_liabilities_equity} bold />
            <div className={`mt-2 rounded-lg px-3 py-2 text-xs font-bold text-center ${data.balance_sheet.check_balanced ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
              {data.balance_sheet.check_balanced ? "Balance Sheet Balanced" : `Gap: ${inr(data.balance_sheet.total_assets - data.balance_sheet.total_liabilities_equity)}`}
            </div>
          </Section>

          {/* ── Cash Flow ── */}
          <Section title="Cash Flows" color="bg-[#00AEED]">
            <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">Operating</span>
            <Row label="Net Income" value={data.cash_flow.operating.net_income} indent />
            <Row label="Depreciation (add back)" value={data.cash_flow.operating.depreciation} indent />
            <Row label="Change in Deposits Held" value={data.cash_flow.operating.change_in_deposits_held} indent />
            <Row label="Cash from Operations" value={data.cash_flow.total_operating} bold />
            <Divider />
            <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">Investing</span>
            <Row label="CapEx (furniture/assets)" value={data.cash_flow.investing.capex} indent />
            <Row label="Deposit Refunds Paid" value={data.cash_flow.investing.deposit_refunds_paid} indent />
            <Row label="Cash from Investing" value={data.cash_flow.total_investing} bold />
            <Divider />
            <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">Financing</span>
            <Row label="Investor Capital Received" value={data.cash_flow.financing.investor_capital_received} indent />
            <Row label="Cash from Financing" value={data.cash_flow.total_financing} bold />
            <Divider />
            <Row label="Net Cash Flow" value={data.cash_flow.net_cash_flow} bold />
            <Row label="Beginning Cash" value={data.cash_flow.beginning_cash} indent muted />
            <Row label="Ending Cash" value={data.cash_flow.ending_cash} indent muted />
            <div className={`mt-2 rounded-lg px-3 py-2 text-xs font-bold text-center ${data.cash_flow.cash_reconciled ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
              {data.cash_flow.cash_reconciled ? "Cash Flow Reconciled" : "Cash Flow Gap — Check Bank Data"}
            </div>
          </Section>
        </>
      )}
    </div>
  )
}
