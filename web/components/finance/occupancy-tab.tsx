"use client"

import { useEffect, useRef, useState } from "react"
import { getOccupancyData, OccupancyData } from "@/lib/api"

type Filter = "monthly" | "all"

function fmt(n: number) {
  return n.toLocaleString("en-IN")
}

function ExpandIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="15 3 21 3 21 9" />
      <polyline points="9 21 3 21 3 15" />
      <line x1="21" y1="3" x2="14" y2="10" />
      <line x1="3" y1="21" x2="10" y2="14" />
    </svg>
  )
}

function CollapseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="4 14 10 14 10 20" />
      <polyline points="20 10 14 10 14 4" />
      <line x1="10" y1="14" x2="3" y2="21" />
      <line x1="21" y1="3" x2="14" y2="10" />
    </svg>
  )
}

export function OccupancyTab() {
  const [data, setData] = useState<OccupancyData | null>(null)
  const [filter, setFilter] = useState<Filter>("monthly")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [expanded, setExpanded] = useState<null | 1 | 2>(null)

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

  // Resize charts when fullscreen state changes (after DOM updates)
  useEffect(() => {
    const t = setTimeout(() => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(chart1Inst.current as any)?.resize()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(chart2Inst.current as any)?.resize()
    }, 60)
    return () => clearTimeout(t)
  }, [expanded])

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

    // Font size scales with chart width: small on phone, larger when fullscreen
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const dynFs = (chart: any, min = 8, max = 11) =>
      Math.max(min, Math.min(max, Math.round(chart.width / 40)))

    // Inline plugin — draws value labels above line chart points
    const occLabelPlugin = {
      id: "occLabel",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      afterDatasetsDraw(chart: any) {
        const { ctx } = chart
        const fs = dynFs(chart)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        chart.data.datasets.forEach((ds: any, i: number) => {
          if (ds.yAxisID !== "yOcc") return
          const meta = chart.getDatasetMeta(i)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          meta.data.forEach((pt: any, j: number) => {
            const pct = Number(ds.data[j])
            const beds = months[j]?.occ_beds ?? 0
            ctx.save()
            ctx.fillStyle = "#ffffff"
            ctx.font = `bold ${fs}px -apple-system, BlinkMacSystemFont, sans-serif`
            ctx.textAlign = "center"
            ctx.textBaseline = "bottom"
            ctx.fillText(`${beds}`, pt.x, pt.y - Math.round(fs * 2.8))
            ctx.fillStyle = "rgba(255,255,255,0.75)"
            ctx.fillText(`${pct}%`, pt.x, pt.y - Math.round(fs * 1.2))
            ctx.restore()
          })
        })
      },
    }

    const rentLabelPlugin = {
      id: "rentLabel",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      afterDatasetsDraw(chart: any) {
        const { ctx } = chart
        const fs = dynFs(chart)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        chart.data.datasets.forEach((ds: any, i: number) => {
          if (ds.yAxisID !== "yRent") return
          const meta = chart.getDatasetMeta(i)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          meta.data.forEach((pt: any, j: number) => {
            const v = Number(ds.data[j])
            if (!v) return
            ctx.save()
            ctx.fillStyle = "#F4C842"
            ctx.font = `bold ${fs}px -apple-system, BlinkMacSystemFont, sans-serif`
            ctx.textAlign = "center"
            ctx.textBaseline = "bottom"
            ctx.fillText(`₹${fmt(Math.round(v))}`, pt.x, pt.y - Math.round(fs * 1.2))
            ctx.restore()
          })
        })
      },
    }

    const axisTitle = (text: string, color = "#9ab8cc") => ({
      display: true,
      text,
      color,
      font: { size: 10 },
    })

    import("chart.js/auto").then(({ Chart }) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(chart1Inst.current as any)?.destroy()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(chart2Inst.current as any)?.destroy()

      const darkBg = "#0d1520"
      const gridColor = "rgba(255,255,255,0.05)"

      chart1Inst.current = new Chart(chart1Ref.current!, {
        type: "bar",
        plugins: [occLabelPlugin],
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
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: {
              labels: {
                color: "#c8dae8",
                font: { size: 11 },
                boxWidth: 9,
                padding: 8,
              },
            },
            tooltip: {
              backgroundColor: darkBg,
              borderColor: "#243044",
              borderWidth: 1,
              titleColor: "#fff",
              bodyColor: "#ccd6e0",
              footerColor: "#ffffff",
              footerFont: { weight: "bold" as const },
              padding: 10,
              callbacks: {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                label: (ctx: any) => {
                  if (ctx.dataset.yAxisID === "yOcc") return ` Occupancy: ${ctx.parsed.y}%`
                  return ` ${ctx.dataset.label}: ${ctx.parsed.y}`
                },
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                footer: (items: any[]) => {
                  const total = items
                    .filter((it: any) => it.dataset.yAxisID === "yCI")
                    .reduce((sum: number, it: any) => sum + (it.parsed.y ?? 0), 0)
                  return `Total: ${total}`
                },
              },
            },
          },
          scales: {
            x: {
              stacked: true,
              ticks: { color: "#b8ccdc", font: { size: 11 } },
              grid: { color: gridColor },
            },
            yCI: {
              position: "left",
              stacked: true,
              min: 0,
              max: 100,
              title: axisTitle("Check-ins"),
              ticks: { color: "#b8ccdc", stepSize: 20 },
              grid: { color: gridColor },
            },
            yOcc: {
              position: "right",
              min: 0,
              max: 100,
              title: axisTitle("Occ %", "#c0d4e4"),
              ticks: {
                color: "#c0d4e4",
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
        plugins: [rentLabelPlugin],
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
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: {
              labels: {
                color: "#c8dae8",
                font: { size: 11 },
                boxWidth: 9,
                padding: 8,
              },
            },
            tooltip: {
              backgroundColor: darkBg,
              borderColor: "#243044",
              borderWidth: 1,
              titleColor: "#fff",
              bodyColor: "#ccd6e0",
              padding: 10,
              callbacks: {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                label: (ctx: any) => {
                  if (ctx.dataset.yAxisID === "yRent")
                    return ` Avg Rent: ₹${fmt(ctx.parsed.y)}`
                  return ` ${ctx.dataset.label}: ${ctx.parsed.y}`
                },
              },
            },
          },
          scales: {
            x: {
              ticks: { color: "#b8ccdc", font: { size: 11 } },
              grid: { color: gridColor },
            },
            yCount: {
              position: "left",
              min: 0,
              max: 120,
              title: axisTitle("Count"),
              ticks: { color: "#b8ccdc", stepSize: 20 },
              grid: { color: gridColor },
            },
            yRent: {
              position: "right",
              min: 0,
              max: 22500,
              title: axisTitle("Avg Rent", "#F4C842"),
              ticks: {
                color: "#F4C842",
                stepSize: 2500,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                callback: (v: any) => {
                  const k = v / 1000
                  return "₹" + (Number.isInteger(k) ? k.toFixed(0) : k.toFixed(1)) + "k"
                },
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
          <span style={{ color: "#EF1F9C" }} className="text-2xl font-extrabold leading-none">
            {kpi.today_occ_pct}%
          </span>
          <span className="text-[10px] text-ink-muted uppercase tracking-wide">Occupancy — Today</span>
        </div>
        <div className="rounded-xl bg-[#0F0E0D] p-4 flex flex-col gap-1">
          <span style={{ color: "#00AEED" }} className="text-2xl font-extrabold leading-none">
            {kpi.today_occ_beds}
          </span>
          <span className="text-[10px] text-ink-muted uppercase tracking-wide">
            Beds Occupied / {kpi.total_beds}
          </span>
        </div>
        <div className="rounded-xl bg-[#0F0E0D] p-4 flex flex-col gap-1">
          <span style={{ color: "#F4C842" }} className="text-2xl font-extrabold leading-none">
            ₹{fmt(kpi.current_avg_rent)}
          </span>
          <span className="text-[10px] text-ink-muted uppercase tracking-wide">Avg Rent / Bed</span>
        </div>
        <div className="rounded-xl bg-[#0F0E0D] p-4 flex flex-col gap-1">
          {/* text-white — text-ink = #0F0E0D = same as bg, invisible */}
          <span className="text-2xl font-extrabold leading-none text-white">
            {kpi.total_checkins}
          </span>
          <span className="text-[10px] text-ink-muted uppercase tracking-wide">Total Check-ins</span>
        </div>
      </div>

      {/* Filter toggle */}
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-ink-muted uppercase tracking-wide">Stay type:</span>
        <div className="flex rounded-lg overflow-hidden border border-[#2a3a50]">
          <button
            onClick={() => setFilter("monthly")}
            className={`px-3 py-1.5 text-[11px] font-semibold transition-colors ${
              filter === "monthly" ? "bg-[#1e3a5a] text-[#00AEED]" : "bg-[#0F0E0D] text-ink-muted"
            }`}
          >
            Monthly Only
          </button>
          <button
            onClick={() => setFilter("all")}
            className={`px-3 py-1.5 text-[11px] font-semibold transition-colors ${
              filter === "all" ? "bg-[#1e3a5a] text-[#00AEED]" : "bg-[#0F0E0D] text-ink-muted"
            }`}
          >
            All incl. Daily
          </button>
        </div>
      </div>

      {/* Chart 1 — booking type breakdown + occupancy line */}
      <div
        className={
          expanded === 1
            ? "fixed inset-0 z-[60] bg-[#080d14] flex flex-col p-4"
            : "rounded-xl bg-[#0F0E0D] p-4"
        }
      >
        <div className="flex items-center justify-between mb-3">
          <p className="text-[11px] font-semibold text-[#9ab8cc] uppercase tracking-wide">
            Check-ins by Type &amp; Occupancy %
          </p>
          <button
            onClick={() => setExpanded(expanded === 1 ? null : 1)}
            className="text-ink-muted hover:text-white transition-colors p-1"
            aria-label={expanded === 1 ? "Collapse" : "Expand"}
          >
            {expanded === 1 ? <CollapseIcon /> : <ExpandIcon />}
          </button>
        </div>
        <div className={expanded === 1 ? "flex-1" : ""} style={expanded !== 1 ? { height: 230 } : {}}>
          <canvas ref={chart1Ref} />
        </div>
        {expanded !== 1 && (
          <p className="text-[9px] text-[#6a8a9a] mt-2">
            Bars = new arrivals · White line = total occupancy % · Left axis = check-ins count · Right = occ %
          </p>
        )}
      </div>

      {/* Chart 2 — check-ins vs check-outs + avg rent */}
      <div
        className={
          expanded === 2
            ? "fixed inset-0 z-[60] bg-[#080d14] flex flex-col p-4"
            : "rounded-xl bg-[#0F0E0D] p-4"
        }
      >
        <div className="flex items-center justify-between mb-3">
          <p className="text-[11px] font-semibold text-[#9ab8cc] uppercase tracking-wide">
            Check-ins vs Check-outs &amp; Avg Rent / Bed
          </p>
          <button
            onClick={() => setExpanded(expanded === 2 ? null : 2)}
            className="text-ink-muted hover:text-white transition-colors p-1"
            aria-label={expanded === 2 ? "Collapse" : "Expand"}
          >
            {expanded === 2 ? <CollapseIcon /> : <ExpandIcon />}
          </button>
        </div>
        <div className={expanded === 2 ? "flex-1" : ""} style={expanded !== 2 ? { height: 210 } : {}}>
          <canvas ref={chart2Ref} />
        </div>
        {expanded !== 2 && (
          <p className="text-[9px] text-[#6a8a9a] mt-2">
            Left axis = count · Right axis = avg rent · Yellow labels = ₹/bed for each month
          </p>
        )}
      </div>

      {/* Data table */}
      <div className="rounded-xl bg-[#0F0E0D] p-4">
        <p className="text-[11px] font-semibold text-[#9ab8cc] uppercase tracking-wide mb-3">
          Monthly Breakdown
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-[10px] border-collapse min-w-[500px]">
            <thead>
              <tr className="text-ink-muted">
                <th className="py-1.5 px-2 text-left font-semibold uppercase tracking-wide">Month</th>
                <th className="py-1.5 px-2 text-right font-semibold uppercase tracking-wide">Beds</th>
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
                    <td className={`py-1.5 px-2 font-semibold ${isLast ? "text-[#F4C842]" : "text-white"}`}>
                      {m.label}{isLast ? " ★" : ""}
                    </td>
                    <td className={`py-1.5 px-2 text-right ${isLast ? "text-[#F4C842] font-bold" : "text-ink-muted"}`}>
                      {m.occ_beds}
                    </td>
                    <td className={`py-1.5 px-2 text-right ${isLast ? "text-[#F4C842] font-bold" : "text-ink-muted"}`}>
                      {m.fill_pct}%
                    </td>
                    <td className="py-1.5 px-2 text-right text-white">{ci || "—"}</td>
                    <td
                      className="py-1.5 px-2 text-right"
                      style={{ color: (m.checkouts ?? 0) > 0 ? "#EF1F9C" : "#3a5068" }}
                    >
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
        </p>
      </div>
    </div>
  )
}
