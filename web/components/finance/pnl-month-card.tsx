"use client"

/**
 * SOP P&L month view (spec 01, Phase 1) — SAC-style hierarchy.
 * Collapsed = the 5-line P&L (Gross inflows → deposits → True revenue → OPEX
 * → Net operating). Every node expands into its children; drillable leaves get
 * transaction drill-down in Phase 2. All numbers come from
 * GET /finance/pnl/month — the same engine as the SOP Excel. No math here.
 */
import { useCallback, useEffect, useState } from "react"
import { getPnlMonth, type PnlMonthResponse, type PnlNode } from "@/lib/api"
import { rupeeExact } from "@/lib/format"
import { monthLabel, periodMonth } from "@/lib/date"
import { MonthNav } from "@/components/ui/month-nav"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty-state"

function NodeRow({ node, depth, expanded, onToggle }: {
  node: PnlNode
  depth: number
  expanded: Set<string>
  onToggle: (key: string) => void
}) {
  const hasChildren = (node.children?.length ?? 0) > 0
  const isOpen = expanded.has(node.key)
  const isResult = node.style === "result"

  const amountColor = node.display_only
    ? "text-ink-muted"
    : isResult
      ? node.amount >= 0 ? "text-status-paid" : "text-status-due"
      : node.amount < 0 ? "text-status-due" : "text-ink"

  return (
    <>
      <button
        type="button"
        onClick={hasChildren ? () => onToggle(node.key) : undefined}
        disabled={!hasChildren}
        className={`w-full flex items-center justify-between gap-2 py-2 text-left ${
          isResult ? "border-t border-border-strong" : ""
        } ${hasChildren ? "active:opacity-60" : "cursor-default"}`}
        style={{ paddingLeft: depth * 14 }}
      >
        <span className={`flex items-center gap-1.5 min-w-0 ${
          node.style ? "text-sm font-bold text-ink" :
          node.display_only ? "text-xs italic text-ink-muted" :
          "text-xs text-ink-muted"
        }`}>
          {hasChildren && (
            <span className="text-[9px] text-ink-muted w-3 shrink-0">{isOpen ? "▼" : "▶"}</span>
          )}
          <span className="truncate">{node.label}</span>
          {node.manual && (
            <span className="shrink-0 text-[8px] font-bold uppercase tracking-wide bg-tile-blue text-brand-blue rounded-full px-1.5 py-0.5">
              manual
            </span>
          )}
        </span>
        <span className={`shrink-0 text-xs font-mono ${node.style ? "font-bold text-sm" : ""} ${amountColor} ${node.display_only ? "italic" : ""}`}>
          {rupeeExact(node.amount)}
        </span>
      </button>
      {hasChildren && isOpen && node.children!.map((c) => (
        <NodeRow key={c.key} node={c} depth={depth + 1} expanded={expanded} onToggle={onToggle} />
      ))}
    </>
  )
}

export function PnlMonthCard() {
  const [month, setMonth] = useState(periodMonth())
  const [data, setData] = useState<PnlMonthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const load = useCallback(async (m: string) => {
    setLoading(true)
    setError("")
    try {
      setData(await getPnlMonth(m))
    } catch (e: unknown) {
      setData(null)
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(month) }, [month, load])

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <div className="bg-surface rounded-card border border-border px-4 py-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">
          P&amp;L · month view
        </p>
        {data?.is_frozen && (
          <span className="text-[8px] font-bold uppercase tracking-wide bg-tile-green text-status-paid rounded-full px-2 py-0.5">
            verified · frozen
          </span>
        )}
      </div>

      <MonthNav value={month} onChange={setMonth} maxMonth={periodMonth()} />

      {loading && (
        <div className="flex flex-col gap-2 py-2">
          {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-5 w-full" />)}
        </div>
      )}

      {!loading && error && (
        <p className="text-[11px] text-status-warn text-center py-2">
          Could not load P&amp;L — {error}
        </p>
      )}

      {!loading && !error && data && !data.has_data && (
        <EmptyState>
          No bank rows for {monthLabel(month)} yet. Upload the statement above to build this month.
        </EmptyState>
      )}

      {!loading && !error && data && data.has_data && (
        <div className="flex flex-col">
          {data.tree.map((n) => (
            <NodeRow key={n.key} node={n} depth={0} expanded={expanded} onToggle={toggle} />
          ))}
          {data.totals?.margin_pct !== null && data.totals?.margin_pct !== undefined && (
            <p className="text-[10px] text-ink-muted text-right pt-1">
              Operating margin {data.totals.margin_pct}% of true revenue
            </p>
          )}
        </div>
      )}
    </div>
  )
}
