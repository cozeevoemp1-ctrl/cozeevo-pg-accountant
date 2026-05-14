"use client"

import { useEffect, useRef, useState } from "react"
import { getOccupancyData, OccupancyData } from "@/lib/api"

type Filter = "monthly" | "all"

function fmt(n: number) {
  return n.toLocaleString("en-IN")
}

export function OccupancyTab() {
  const [data, setData] = useState<OccupancyData | null>(null)
  const [filter, setFilter] = useState<Filter>("monthly")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const chart1Ref = useRef<HTMLCanvasElement>(null)
  const chart2Ref = useRef<HTMLCanvasElement>(null)
  const chart1Inst = useRef<unknown>(null)
  const chart2Inst = useRef<unknown>(null)

  useEffect(() => {
    getOccupancyData()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!data || !chart1Ref.current || !chart2Ref.current) return

    const months = data.months
    const labels = months.map((m) => m.label)
    const fillPct = months.map((m) => m.fill_pct)
    const ciSingle = months.map((m) => m.ci_single)
    const ciDouble = months.map((m) => m.ci_double)
    const ciTriple = months.map((m) => m.ci_triple)
    const ciPremium = months.map((m) => m.ci_premium)
    const ciDaily = months.map((m) => m.ci_daily)
    const ciMonthly = months.map((_, i) => ciSingle[i] + ciDouble[i] + ciTriple[i] + ciPremium[i])
    const ciTotal = months.map((_, i) => ciMonthly[i] + ciDaily[i])
    const checkouts = months.map((m) => m.checkouts ?? 0)
    const avgRent = months.map((m) => m.avg_rent)
    const showDaily = filter === "all"

    import("chart.js/auto").then(({ Chart }) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(chart1Inst.current as any)?.destroy()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(chart2Inst.current as any)?.destroy()

      const darkBg = "#0d1520"
      const gridColor = "rgba(255,255,255,0.05)"

      chart1Inst.current = new Chart(chart1Ref.current!, {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              type: "bar" as const,
              label: "Single",
              data: ciSingle,
              backgroundColor: "rgba(239,31,156,0.85)",
              stack: "ci",
              yAxisID: "yCI",
            },
            {
              type: "bar" as const,
              label: "Double",
              data: ciDouble,
              backgroundColor: "rgba(0,174,237,0.85)",
              stack: "ci",
              yAxisID: "yCI",
            },
            {
              type: "bar" as const,
              label: "Triple",
              data: ciTriple,
              backgroundColor: "rgba(26,188,156,0.85)",
              stack: "ci",
              yAxisID: "yCI",
            },
            {
              type: "bar" as const,
              label: "Premium",
              data: ciPremium,
              backgroundColor: "rgba(243,156,18,0.90)",
              stack: "ci",
              yAxisID: "yCI",
            },
            {
              type: "bar" as const,
              label: "Daily",
              data: ciDaily,
              backgroundColor: "rgba(149,165,166,0.75)",
              stack: "ci",
              yAxisID: "yCI",
              hidden: !showDaily,
            },
            {
              type: "line" as const,
              label: "Occupancy %",
              data: fillPct,
              borderColor: "#ffffff",
              backgroundColor: "rgba(255,255,255,0.04)",
              pointBackgroundColor: "#ffffff",
              pointBorderColor: darkBg,
              pointBorderWidth: 2,
              borderWidth: 2.5,
              pointRadius: 5,
              tension: 0.35,
              fill: false,
              yAxisID: "yOcc",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: {
              labels: {
                color: "#8899aa",
                font: { size: 10 },
                boxWidth: 10,
                padding: 10,
              },
            },
            tooltip: {
              backgroundColor: darkBg,
              borderColor: "#243044",
              borderWidth: 1,
              titleColor: "#fff",
              bodyColor: "#ccd6e0",
              padding: 10,
            },
          },
          scales: {
            x: {
              stacked: true,
              ticks: { color: "#8899aa", font: { size: 10 } },
              grid: { color: gridColor },
            },
            yCI: {
              position: "left",
              stacked: true,
              min: 0,
              max: 140,
              ticks: { color: "#8899aa", stepSize: 20 },
              grid: { color: gridColor },
            },
            yOcc: {
              position: "right",
              min: 0,
              max: 120,
              ticks: {
                color: "#aabbcc",
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                callback: (v: any) => v + "%",
                stepSize: 20,
              },
              grid: { drawOnChartArea: false },
            },
          },
        },
      })

      chart2Inst.current = new Chart(chart2Ref.current!, {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              type: "bar" as const,
              label: "Check-ins",
              data: showDaily ? ciTotal : ciMonthly,
              backgroundColor: "rgba(0,174,237,0.70)",
              borderColor: "#00AEED",
              borderWidth: 1,
              borderRadius: 4,
              yAxisID: "yCount",
            },
            {
              type: "bar" as const,
              label: "Check-outs",
              data: checkouts,
              backgroundColor: "rgba(239,31,156,0.70)",
              borderColor: "#EF1F9C",
              borderWidth: 1,
              borderRadius: 4,
              yAxisID: "yCount",
            },
            {
              type: "line" as const,
              label: "Avg Rent/Bed",
              data: avgRent,
              borderColor: "#F4C842",
              backgroundColor: "rgba(244,200,66,0.06)",
              pointBackgroundColor: "#F4C842",
              pointBorderColor: darkBg,
              pointBorderWidth: 2,
              borderWidth: 2,
              pointRadius: 5,
              tension: 0.3,
              fill: true,
              yAxisID: "yRent",
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: {
              labels: {
                color: "#8899aa",
                font: { size: 10 },
                boxWidth: 10,
                padding: 10,
              },
            },
            tooltip: {
              backgroundColor: darkBg,
              borderColor: "#243044",
              borderWidth: 1,
              titleColor: "#fff",
              bodyColor: "#ccd6e0",
              padding: 10,
            },
          },
          scales: {
            x: {
              ticks: { color: "#8899aa", font: { size: 10 } },
              grid: { color: gridColor },
            },
            yCount: {
              position: "left",
              min: 0,
              max: 120,
              ticks: { color: "#8899aa", stepSize: 20 },
              grid: { color: gridColor },
            },
            yRent: {
              position: "right",
              min: 0,
              max: 22000,
              ticks: {
                color: "#F4C842",
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                callback: (v: any) => "₹" + (v / 1000).toFixed(0) + "k",
              },
              grid: { drawOnChartArea: false },
            },
          },
        },
      })
    })

    return () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(chart1Inst.current as any)?.destroy()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(chart2Inst.current as any)?.destroy()
    }
  }, [data, filter])

  if (loading) {
    return <div className="py-16 text-center text-xs text-ink-muted">Loading occupancy data…</div>
  }

  if (error || !data) {
    return <div className="py-16 text-center text-xs text-status-warn">{error || "No data"}</div>
  }

  const { kpi, months } = data

  return (
    <div className="flex flex-col gap-4">
      {/* KPI row */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-[#0F0E0D] p-4 flex flex-col gap-1">
          <span
            style={{ color: "#EF1F9C" }}
            className="text-2xl font-extrabold leading-none"
          >
            {kpi.today_occ_pct}%
          </span>
          <span className="text-[10px] text-ink-muted uppercase tracking-wide">
            Occupancy — Today
          </span>
        </div>
        <div className="rounded-xl bg-[#0F0E0D] p-4 flex flex-col gap-1">
          <span
            style={{ color: "#00AEED" }}
            className="text-2xl font-extrabold leading-none"
          >
            {kpi.today_occ_beds}
          </span>
          <span className="text-[10px] text-ink-muted uppercase tracking-wide">
            Beds Occupied / {kpi.total_beds}
          </span>
        </div>
        <div className="rounded-xl bg-[#0F0E0D] p-4 flex flex-col gap-1">
          <span
            style={{ color: "#F4C842" }}
            className="text-2xl font-extrabold leading-none"
          >
            ₹{fmt(kpi.current_avg_rent)}
          </span>
          <span className="text-[10px] text-ink-muted uppercase tracking-wide">
            Avg Rent / Bed
          </span>
        </div>
        <div className="rounded-xl bg-[#0F0E0D] p-4 flex flex-col gap-1">
          <span className="text-2xl font-extrabold leading-none text-ink">
            {kpi.total_checkins}
          </span>
          <span className="text-[10px] text-ink-muted uppercase tracking-wide">
            Total Check-ins
          </span>
        </div>
      </div>

      {/* Filter toggle */}
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-ink-muted uppercase tracking-wide">Stay type:</span>
        <div className="flex rounded-lg overflow-hidden border border-[#2a3a50]">
          <button
            onClick={() => setFilter("monthly")}
            className={`px-3 py-1.5 text-[11px] font-semibold transition-colors ${
              filter === "monthly"
                ? "bg-[#1e3a5a] text-[#00AEED]"
                : "bg-[#0F0E0D] text-ink-muted"
            }`}
          >
            Monthly Only
          </button>
          <button
            onClick={() => setFilter("all")}
            className={`px-3 py-1.5 text-[11px] font-semibold transition-colors ${
              filter === "all"
                ? "bg-[#1e3a5a] text-[#00AEED]"
                : "bg-[#0F0E0D] text-ink-muted"
            }`}
          >
            All incl. Daily
          </button>
        </div>
      </div>

      {/* Chart 1 — booking type breakdown + occupancy line */}
      <div className="rounded-xl bg-[#0F0E0D] p-4">
        <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide mb-3">
          Check-ins by Type &amp; Occupancy %
        </p>
        <canvas ref={chart1Ref} height={220} />
        <p className="text-[9px] text-ink-muted mt-2">
          Bars = new arrivals that month · White line = total occupancy % · Premium booking = 2 beds
        </p>
      </div>

      {/* Chart 2 — check-ins vs check-outs + avg rent */}
      <div className="rounded-xl bg-[#0F0E0D] p-4">
        <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide mb-3">
          Check-ins vs Check-outs &amp; Avg Rent / Bed
        </p>
        <canvas ref={chart2Ref} height={200} />
      </div>

      {/* Data table */}
      <div className="rounded-xl bg-[#0F0E0D] p-4">
        <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide mb-3">
          Monthly Breakdown
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-[10px] border-collapse min-w-[500px]">
            <thead>
              <tr className="text-ink-muted">
                <th className="py-1.5 px-2 text-left font-semibold uppercase tracking-wide">Month</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">Occ</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">Fill%</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">In</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">Out</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">S</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">D</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">T</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">P</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">Day</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">₹/Bed</th>
              </tr>
            </thead>
            <tbody>
              {months.map((m, i) => {
                const isLast = i === months.length - 1
                const ci = m.ci_single + m.ci_double + m.ci_triple + m.ci_premium + m.ci_daily
                return (
                  <tr
                    key={m.month}
                    className={`border-t border-[#1a2535] ${isLast ? "bg-[#1a2a1a]" : ""}`}
                  >
                    <td className={`py-1.5 px-2 font-semibold ${isLast ? "text-[#F4C842]" : "text-ink"}`}>
                      {m.label}{isLast ? " ★" : ""}
                    </td>
                    <td className={`py-1.5 px-2 text-right ${isLast ? "text-[#F4C842] font-bold" : "text-ink-muted"}`}>
                      {m.occ_beds}
                    </td>
                    <td className={`py-1.5 px-2 text-right ${isLast ? "text-[#F4C842] font-bold" : "text-ink-muted"}`}>
                      {m.fill_pct}%
                    </td>
                    <td className="py-1.5 px-2 text-right text-ink">{ci || "—"}</td>
                    <td className="py-1.5 px-2 text-right" style={{ color: (m.checkouts ?? 0) > 0 ? "#EF1F9C" : "#3a5068" }}>
                      {m.checkouts === null ? "—" : m.checkouts || "—"}
                    </td>
                    <td className="py-1.5 px-2 text-right text-ink-muted">{m.ci_single || "—"}</td>
                    <td className="py-1.5 px-2 text-right text-ink-muted">{m.ci_double || "—"}</td>
                    <td className="py-1.5 px-2 text-right text-ink-muted">{m.ci_triple || "—"}</td>
                    <td className="py-1.5 px-2 text-right text-ink-muted">{m.ci_premium || "—"}</td>
                    <td className="py-1.5 px-2 text-right text-ink-muted">{m.ci_daily || "—"}</td>
                    <td className="py-1.5 px-2 text-right" style={{ color: "#F4C842" }}>
                      {m.avg_rent > 0 ? `₹${fmt(m.avg_rent)}` : "—"}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[9px] text-ink-muted mt-2">
          ★ Current month (partial) · S=Single D=Double T=Triple P=Premium Day=Daily
          · Nov check-outs: no data (historical import)
        </p>
      </div>
    </div>
  )
}
