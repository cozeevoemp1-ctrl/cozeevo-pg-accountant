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

          {/* Gross Revenue */}
          <div className="flex items-center justify-between py-1.5">
            <span className="text-xs text-ink-muted">Gross Bank Income</span>
            <span className="text-xs font-bold text-ink">{rupee(data.gross_income)}</span>
          </div>

          {/* Deposits deducted */}
          {data.deposits_held > 0 && (
            <div className="flex items-center justify-between py-1.5">
              <span className="text-xs text-ink-muted pl-3">− Security Deposits</span>
              <span className="text-xs font-semibold text-status-warn">−{rupee(data.deposits_held)}</span>
            </div>
          )}

          {/* True Revenue — highlighted */}
          <div className="flex items-center justify-between py-1.5 bg-[#F6F5F0] rounded-lg px-2 -mx-2 my-1">
            <span className="text-xs font-bold text-ink">True Revenue</span>
            <span className="text-xs font-extrabold text-status-paid">{rupee(data.true_revenue)}</span>
          </div>

          {/* OPEX */}
          <div className="flex items-center justify-between py-1.5">
            <span className="text-xs text-ink-muted pl-3">− Operations (OPEX)</span>
            <span className="text-xs font-semibold text-ink-muted">−{rupee(data.total_opex)}</span>
          </div>

          {/* EBITDA — highlighted */}
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

        {/* Occupancy bar */}
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

        {/* Rent + Collection row */}
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

        {/* Collected vs billed */}
        <div className="flex items-center justify-between mt-2.5 pt-2.5 border-t border-[#F0EDE9]">
          <span className="text-[10px] text-ink-muted">Collected</span>
          <span className="text-[10px] font-bold text-ink">
            {rupee(data.total_collected)} <span className="font-normal text-ink-muted">of {rupee(data.total_billed)}</span>
          </span>
        </div>
      </div>

    </div>
  )
}
