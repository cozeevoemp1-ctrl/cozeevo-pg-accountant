"use client"

import type { UnitEconomics } from "@/lib/api"

function rupee(n: number): string {
  if (Math.abs(n) >= 100000) return `₹${(n / 100000).toFixed(1)}L`
  if (Math.abs(n) >= 1000) return `₹${Math.round(n / 1000)}K`
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

function pct(n: number, decimals = 1): string {
  return `${n.toFixed(decimals)}%`
}

interface Props {
  data: UnitEconomics
}

export function UnitEconomicsCard({ data }: Props) {
  const ebitdaPositive = data.ebitda >= 0
  const collectionGood = data.collection_rate >= 90
  const collectionOk = data.collection_rate >= 70
  const vacantBeds = data.total_beds - data.occupied_beds
  const occupancyBar = Math.round(data.occupancy_pct)

  // Investment yield benchmarks
  const yieldPct = data.investment_yield_pct ?? 0
  const yieldBeatsEquity = yieldPct >= 12
  const yieldBeatsFD = yieldPct >= 7
  const yieldColor = yieldBeatsEquity
    ? "text-status-paid"
    : yieldBeatsFD
    ? "text-[#00AEED]"
    : "text-status-warn"

  // Revenue leakage severity
  const leakagePct = data.total_billed > 0
    ? (data.revenue_leakage / data.total_billed) * 100
    : 0
  const leakageSevere = leakagePct > 20
  const leakageOk = leakagePct <= 10

  // Economic vs physical occupancy gap
  const econGap = data.occupancy_pct - data.economic_occupancy_pct

  return (
    <div className="flex flex-col gap-3">

      {/* ── HERO: EBITDA margin ── */}
      {data.bank_available && (
        <div className={`rounded-card px-5 py-4 flex items-center justify-between ${ebitdaPositive ? "bg-[#0F0E0D]" : "bg-[#2D1010]"}`}>
          <div>
            <p className="text-[9px] font-bold uppercase tracking-widest text-[#6F655D] mb-1">EBITDA / Bed · Month</p>
            <p className={`text-3xl font-extrabold ${ebitdaPositive ? "text-white" : "text-status-warn"}`}>
              {rupee(data.ebitda_per_bed)}
            </p>
          </div>
          <div className="text-right">
            <p className={`text-2xl font-extrabold ${ebitdaPositive ? "text-status-paid" : "text-status-warn"}`}>
              {pct(data.ebitda_margin)}
            </p>
            <p className="text-[9px] font-semibold text-[#6F655D] mt-0.5">margin</p>
          </div>
        </div>
      )}

      {/* ── P&L WATERFALL ── */}
      {data.bank_available ? (
        <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
          <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-3">P&amp;L Waterfall</p>

          <div className="flex items-center justify-between py-1.5">
            <span className="text-xs text-ink-muted">Gross Bank Income</span>
            <span className="text-xs font-bold text-ink">{rupee(data.gross_income)}</span>
          </div>

          {data.deposits_held > 0 && (
            <div className="flex items-center justify-between py-1.5">
              <span className="text-xs text-ink-muted pl-3">− Security Deposits</span>
              <span className="text-xs font-semibold text-status-warn">−{rupee(data.deposits_held)}</span>
            </div>
          )}

          <div className="flex items-center justify-between py-1.5 bg-[#F6F5F0] rounded-lg px-2 -mx-2 my-1">
            <span className="text-xs font-bold text-ink">True Revenue</span>
            <span className="text-xs font-extrabold text-status-paid">{rupee(data.true_revenue)}</span>
          </div>

          <div className="flex items-center justify-between py-1.5">
            <span className="text-xs text-ink-muted pl-3">− Operations (OPEX)</span>
            <span className="text-xs font-semibold text-ink-muted">−{rupee(data.total_opex)}</span>
          </div>

          <div className={`flex items-center justify-between py-2 rounded-lg px-2 -mx-2 mt-1 ${ebitdaPositive ? "bg-tile-green" : "bg-tile-orange"}`}>
            <div>
              <span className="text-xs font-extrabold text-ink">EBITDA</span>
              <span className="text-[9px] text-ink-muted ml-2">{pct(data.ebitda_margin)} margin</span>
            </div>
            <span className={`text-sm font-extrabold ${ebitdaPositive ? "text-status-paid" : "text-status-warn"}`}>
              {ebitdaPositive ? "" : "−"}{rupee(Math.abs(data.ebitda))}
            </span>
          </div>
        </div>
      ) : (
        <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-4 text-center">
          <p className="text-[11px] text-ink-muted">Upload bank statement to unlock revenue &amp; EBITDA</p>
        </div>
      )}

      {/* ── CONCEPT A: INVESTMENT RETURN ── */}
      {data.bank_available && data.investment_yield_pct !== null && (
        <div className="bg-[#0A1628] rounded-card px-4 py-3">
          <p className="text-[9px] font-bold uppercase tracking-widest text-[#4A6A8A] mb-3">Investment Return · ₹2.59Cr Deployed</p>

          {/* Yield hero + benchmarks */}
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className={`text-3xl font-extrabold ${yieldColor}`}>
                {pct(data.investment_yield_pct, 1)}
              </p>
              <p className="text-[9px] text-[#4A6A8A] font-semibold mt-0.5">annual yield</p>
            </div>
            <div className="flex flex-col gap-1 items-end">
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${yieldBeatsFD ? "bg-[#0F2A1A] text-status-paid" : "bg-[#2A1A0A] text-status-warn"}`}>
                {yieldBeatsFD ? "▲" : "▼"} FD 7%
              </span>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${yieldBeatsEquity ? "bg-[#0F2A1A] text-status-paid" : "bg-[#1A1A2A] text-[#4A6A8A]"}`}>
                {yieldBeatsEquity ? "▲" : "▼"} Equity 12%
              </span>
            </div>
          </div>

          {/* Payback + Breakeven tiles */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[#0F1F35] rounded-tile p-2.5">
              <p className="text-sm font-extrabold text-white">
                {data.payback_months !== null ? `${data.payback_months}mo` : "—"}
              </p>
              <p className="text-[9px] text-[#4A6A8A] font-semibold mt-0.5">Payback Period</p>
              {data.payback_months !== null && (
                <p className="text-[9px] text-[#4A6A8A]">{(data.payback_months / 12).toFixed(1)} yrs</p>
              )}
            </div>
            <div className="bg-[#0F1F35] rounded-tile p-2.5">
              <p className="text-sm font-extrabold text-white">
                {data.breakeven_occupancy_pct !== null ? pct(data.breakeven_occupancy_pct, 0) : "—"}
              </p>
              <p className="text-[9px] text-[#4A6A8A] font-semibold mt-0.5">Break-even Occ.</p>
              {data.breakeven_occupancy_pct !== null && (
                <p className="text-[9px] text-[#4A6A8A]">
                  {(data.occupancy_pct - data.breakeven_occupancy_pct).toFixed(0)}% buffer
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── PER-BED KPIs ── */}
      {data.bank_available && (
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-tile-green rounded-tile p-2.5 text-center">
            <p className="text-sm font-extrabold text-status-paid">{rupee(data.revenue_per_bed)}</p>
            <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Rev / Bed</p>
          </div>
          <div className="bg-tile-orange rounded-tile p-2.5 text-center">
            <p className="text-sm font-extrabold text-status-due">{rupee(data.opex_per_bed)}</p>
            <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Cost / Bed</p>
          </div>
          <div className="bg-[#F6F5F0] rounded-tile p-2.5 text-center">
            <p className="text-xs font-extrabold text-ink">{pct(data.ebitda_margin, 0)}</p>
            <p className="text-[9px] text-ink-muted font-semibold mt-0.5">EBITDA %</p>
          </div>
        </div>
      )}

      {/* ── OCCUPANCY + RENT ── */}
      <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-3">Occupancy &amp; Rent</p>

        <div className="mb-3">
          <div className="flex justify-between text-[10px] font-semibold mb-1">
            <span className="text-ink">{data.occupied_beds} of {data.total_beds} beds occupied</span>
            <span className={data.occupancy_pct >= 90 ? "text-status-paid" : data.occupancy_pct >= 70 ? "text-ink" : "text-status-warn"}>
              {pct(data.occupancy_pct, 0)}
            </span>
          </div>
          <div className="w-full h-2 bg-[#F0EDE9] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${data.occupancy_pct >= 90 ? "bg-status-paid" : data.occupancy_pct >= 70 ? "bg-brand-blue" : "bg-status-warn"}`}
              style={{ width: `${occupancyBar}%` }}
            />
          </div>
          {vacantBeds > 0 && (
            <p className="text-[10px] text-status-warn font-semibold mt-1">{vacantBeds} vacant bed{vacantBeds > 1 ? "s" : ""}</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="bg-[#F6F5F0] rounded-tile p-2.5">
            <p className="text-sm font-extrabold text-ink">{rupee(data.avg_agreed_rent)}</p>
            <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Avg Rent / Bed</p>
          </div>
          <div className={`${collectionGood ? "bg-tile-green" : collectionOk ? "bg-[#F6F5F0]" : "bg-tile-orange"} rounded-tile p-2.5`}>
            <p className={`text-sm font-extrabold ${collectionGood ? "text-status-paid" : collectionOk ? "text-ink" : "text-status-warn"}`}>
              {pct(data.collection_rate, 0)}
            </p>
            <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Collection Rate</p>
          </div>
        </div>

        <div className="flex items-center justify-between mt-2.5 pt-2.5 border-t border-[#F0EDE9]">
          <span className="text-[10px] text-ink-muted">Collected</span>
          <span className="text-[10px] font-bold text-ink">
            {rupee(data.total_collected)} <span className="font-normal text-ink-muted">of {rupee(data.total_billed)}</span>
          </span>
        </div>
      </div>

      {/* ── CONCEPT B: REVENUE QUALITY ── */}
      <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-3">Revenue Quality</p>

        {/* Economic Occupancy vs Physical */}
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-ink-muted">Economic Occupancy</span>
            <span className={`text-xs font-extrabold ${data.economic_occupancy_pct >= 80 ? "text-status-paid" : data.economic_occupancy_pct >= 60 ? "text-ink" : "text-status-warn"}`}>
              {pct(data.economic_occupancy_pct, 0)}
            </span>
          </div>
          <div className="w-full h-1.5 bg-[#F0EDE9] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${data.economic_occupancy_pct >= 80 ? "bg-status-paid" : data.economic_occupancy_pct >= 60 ? "bg-brand-blue" : "bg-status-warn"}`}
              style={{ width: `${Math.min(data.economic_occupancy_pct, 100)}%` }}
            />
          </div>
          {econGap > 2 && (
            <p className="text-[9px] text-ink-muted mt-1">
              {pct(econGap, 0)} below physical occ — collection gap
            </p>
          )}
          <p className="text-[9px] text-ink-muted mt-0.5">Collected ÷ all {data.total_beds} beds × avg rent</p>
        </div>

        {/* Revenue Leakage */}
        <div className={`flex items-center justify-between py-2 px-2.5 rounded-lg ${leakageOk ? "bg-tile-green" : leakageSevere ? "bg-tile-orange" : "bg-[#F6F5F0]"}`}>
          <div>
            <span className="text-xs font-bold text-ink">Revenue Leakage</span>
            <p className="text-[9px] text-ink-muted">Billed but uncollected this month</p>
          </div>
          <span className={`text-sm font-extrabold ${leakageOk ? "text-status-paid" : leakageSevere ? "text-status-warn" : "text-ink"}`}>
            {data.revenue_leakage <= 0 ? "₹0" : rupee(data.revenue_leakage)}
          </span>
        </div>

        {/* RevPOB vs ADR gap (bank only) */}
        {data.bank_available && data.revenue_per_bed > 0 && data.avg_agreed_rent > 0 && (
          <div className="mt-2.5 pt-2.5 border-t border-[#F0EDE9]">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-ink-muted">Bank Rev / Occ. Bed</span>
              <span className="text-[10px] font-bold text-ink">{rupee(data.revenue_per_bed)}</span>
            </div>
            <div className="flex items-center justify-between mt-1">
              <span className="text-[10px] text-ink-muted">Avg Agreed Rent</span>
              <span className="text-[10px] font-bold text-ink">{rupee(data.avg_agreed_rent)}</span>
            </div>
            {data.revenue_per_bed < data.avg_agreed_rent * 0.95 && (
              <p className="text-[9px] text-status-warn font-semibold mt-1">
                ↓ {rupee(data.avg_agreed_rent - data.revenue_per_bed)} gap — possible discounting or vacancies
              </p>
            )}
          </div>
        )}
      </div>

    </div>
  )
}
