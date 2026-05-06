"use client"

import type { UnitEconomics } from "@/lib/api"

function rupee(n: number): string {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`
  if (n >= 1000) return `₹${Math.round(n / 1000)}K`
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

function pct(n: number): string {
  return `${n.toFixed(1)}%`
}

interface RowProps {
  label: string
  value: string
  sub?: string
  highlight?: "green" | "red" | "neutral"
}

function Row({ label, value, sub, highlight }: RowProps) {
  const valueColor =
    highlight === "green" ? "text-status-paid" :
    highlight === "red"   ? "text-status-warn" :
    "text-ink"
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-[#F6F5F0] last:border-0">
      <div>
        <span className="text-xs text-ink-muted">{label}</span>
        {sub && <span className="text-[10px] text-ink-muted ml-1 opacity-60">{sub}</span>}
      </div>
      <span className={`text-xs font-bold ${valueColor}`}>{value}</span>
    </div>
  )
}

interface Props {
  data: UnitEconomics
}

export function UnitEconomicsCard({ data }: Props) {
  const collectionColor = data.collection_rate >= 90 ? "green" : data.collection_rate >= 70 ? "neutral" : "red"
  const ebitdaColor = data.ebitda >= 0 ? "green" : "red"

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3 flex flex-col gap-4">

      {/* Section 1 — Occupancy & Rent (always available) */}
      <div>
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-2">Occupancy &amp; Rent</p>
        <div className="grid grid-cols-3 gap-2 mb-3">
          <div className="bg-tile-green rounded-tile p-2.5 text-center">
            <p className="text-sm font-extrabold text-status-paid">{pct(data.occupancy_pct)}</p>
            <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Occupancy</p>
          </div>
          <div className="bg-[#F6F5F0] rounded-tile p-2.5 text-center">
            <p className="text-sm font-extrabold text-ink">{data.occupied_beds}</p>
            <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Beds Occ.</p>
          </div>
          <div className="bg-[#F6F5F0] rounded-tile p-2.5 text-center">
            <p className="text-sm font-extrabold text-ink">{data.total_beds - data.occupied_beds}</p>
            <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Vacant</p>
          </div>
        </div>
        <Row label="Avg Agreed Rent" value={rupee(data.avg_agreed_rent)} sub="(monthly, excl. deposits)" />
        <Row
          label="Collection Rate"
          value={pct(data.collection_rate)}
          sub={`${rupee(data.total_collected)} of ${rupee(data.total_billed)}`}
          highlight={collectionColor}
        />
      </div>

      {/* Section 2 — Per-Bed Unit Economics (bank data required) */}
      {data.bank_available ? (
        <div>
          <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mb-2">Unit Economics</p>
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div className="bg-tile-green rounded-tile p-2.5 text-center">
              <p className="text-sm font-extrabold text-status-paid">{rupee(data.revenue_per_bed)}</p>
              <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Rev / Bed</p>
            </div>
            <div className="bg-tile-orange rounded-tile p-2.5 text-center">
              <p className="text-sm font-extrabold text-status-due">{rupee(data.opex_per_bed)}</p>
              <p className="text-[9px] text-ink-muted font-semibold mt-0.5">Cost / Bed</p>
            </div>
            <div className={`${data.ebitda_per_bed >= 0 ? "bg-tile-pink" : "bg-tile-orange"} rounded-tile p-2.5 text-center`}>
              <p className={`text-sm font-extrabold ${data.ebitda_per_bed >= 0 ? "text-brand-pink" : "text-status-warn"}`}>
                {rupee(Math.abs(data.ebitda_per_bed))}
              </p>
              <p className="text-[9px] text-ink-muted font-semibold mt-0.5">EBITDA / Bed</p>
            </div>
          </div>
          <Row label="True Revenue" value={rupee(data.true_revenue)} highlight="green" />
          <Row label="Less: OPEX" value={rupee(data.total_opex)} />
          <Row
            label="EBITDA"
            value={`${rupee(Math.abs(data.ebitda))} (${pct(data.ebitda_margin)})`}
            highlight={ebitdaColor}
          />
          {data.deposits_held > 0 && (
            <Row label="Security Deposits deducted" value={rupee(data.deposits_held)} />
          )}
        </div>
      ) : (
        <div className="py-2">
          <p className="text-[11px] text-ink-muted text-center">
            Upload bank statement to see revenue &amp; cost per bed
          </p>
        </div>
      )}
    </div>
  )
}
