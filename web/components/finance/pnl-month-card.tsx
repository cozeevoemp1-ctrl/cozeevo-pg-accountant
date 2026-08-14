"use client"

/**
 * SOP P&L month view (spec 01, Phase 1) — SAC-style hierarchy.
 * Collapsed = the 5-line P&L (Gross inflows → deposits → True revenue → OPEX
 * → Net operating). Every node expands into its children; drillable leaves get
 * transaction drill-down in Phase 2. All numbers come from
 * GET /finance/pnl/month — the same engine as the SOP Excel. No math here.
 */
import { useCallback, useEffect, useState } from "react"
import {
  getPnlLineItems, getPnlMonth, reclassifyTransaction,
  type PnlLineItemsResponse, type PnlMonthResponse, type PnlNode,
} from "@/lib/api"
import { rupeeExact } from "@/lib/format"
import { fmtDateShort, monthLabel, periodMonth } from "@/lib/date"
import { MonthNav } from "@/components/ui/month-nav"
import { Sheet } from "@/components/ui/modal"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { EmptyState } from "@/components/ui/empty-state"

function NodeRow({ node, depth, expanded, onToggle, onDrill }: {
  node: PnlNode
  depth: number
  expanded: Set<string>
  onToggle: (key: string) => void
  onDrill: (node: PnlNode) => void
}) {
  const hasChildren = (node.children?.length ?? 0) > 0
  const isOpen = expanded.has(node.key)
  const isResult = node.style === "result"
  const canDrill = !hasChildren && node.drillable

  const amountColor = node.display_only
    ? "text-ink-muted"
    : isResult
      ? node.amount >= 0 ? "text-status-paid" : "text-status-due"
      : node.amount < 0 ? "text-status-due" : "text-ink"

  return (
    <>
      <button
        type="button"
        onClick={hasChildren ? () => onToggle(node.key) : canDrill ? () => onDrill(node) : undefined}
        disabled={!hasChildren && !canDrill}
        className={`w-full flex items-center justify-between gap-2 py-2 text-left ${
          isResult ? "border-t border-border-strong" : ""
        } ${hasChildren || canDrill ? "active:opacity-60" : "cursor-default"}`}
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
          {canDrill && (
            <span className="shrink-0 text-[9px] text-ink-muted">›</span>
          )}
        </span>
        <span className={`shrink-0 text-xs font-mono ${node.style ? "font-bold text-sm" : ""} ${amountColor} ${node.display_only ? "italic" : ""}`}>
          {rupeeExact(node.amount)}
        </span>
      </button>
      {hasChildren && isOpen && node.children!.map((c) => (
        <NodeRow key={c.key} node={c} depth={depth + 1} expanded={expanded} onToggle={onToggle} onDrill={onDrill} />
      ))}
    </>
  )
}

export function PnlMonthCard({ refreshSignal }: {
  /** Bump `n` to refetch; set `month` to also jump the view there
      (fired after CSV upload / manual-figures save — the server computes
      live, so a refetch IS the recalculation). */
  refreshSignal?: { month?: string; n: number }
} = {}) {
  const [month, setMonth] = useState(periodMonth())
  const [data, setData] = useState<PnlMonthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  // Drill-down sheet (Phase 2) + inline reclassify (Phase 3)
  const [drillNode, setDrillNode] = useState<PnlNode | null>(null)
  const [drillData, setDrillData] = useState<PnlLineItemsResponse | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillError, setDrillError] = useState("")
  const [reclassFor, setReclassFor] = useState<number | null>(null)
  const [reclassCat, setReclassCat] = useState("")
  const [reclassBusy, setReclassBusy] = useState(false)

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

  // External refresh: after an upload or a manual-figures save the page bumps
  // the signal; jump to that month (if given) or refetch the current one.
  useEffect(() => {
    if (!refreshSignal || refreshSignal.n === 0) return
    const m = refreshSignal.month
    if (m && m !== month) setMonth(m)  // month effect triggers the load
    else load(month)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal?.n])

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function loadDrill(key: string) {
    setDrillLoading(true)
    setDrillError("")
    setReclassFor(null)
    try {
      setDrillData(await getPnlLineItems(month, key))
    } catch (e: unknown) {
      setDrillData(null)
      setDrillError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setDrillLoading(false)
    }
  }

  function openDrill(node: PnlNode) {
    setDrillNode(node)
    setDrillData(null)
    loadDrill(node.key)
  }

  async function saveReclass(txnId: number) {
    if (!reclassCat || !drillNode) return
    setReclassBusy(true)
    setDrillError("")
    try {
      await reclassifyTransaction(txnId, reclassCat)
      setReclassFor(null)
      // Refetch both: the line's rows AND the P&L tree — the amount moved.
      await Promise.all([loadDrill(drillNode.key), load(month)])
    } catch (e: unknown) {
      setDrillError(e instanceof Error ? e.message : "Reclassify failed")
    } finally {
      setReclassBusy(false)
    }
  }

  // Category options for a row: income lines get income categories, the rest expense
  const catOptions = drillData
    ? (drillNode?.key.startsWith("income.") ? drillData.reclass_categories.income : drillData.reclass_categories.expense)
    : []
  const drillMismatch = drillNode && drillData
    ? Math.abs(Math.abs(drillNode.amount) - Math.abs(drillData.total)) > 1
    : false

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
            <NodeRow key={n.key} node={n} depth={0} expanded={expanded} onToggle={toggle} onDrill={openDrill} />
          ))}
          {data.totals?.margin_pct !== null && data.totals?.margin_pct !== undefined && (
            <p className="text-[10px] text-ink-muted text-right pt-1">
              Operating margin {data.totals.margin_pct}% of true revenue
            </p>
          )}
        </div>
      )}

      {/* Drill-down: the transactions behind the tapped line */}
      <Sheet
        open={drillNode !== null}
        onClose={() => { setDrillNode(null); setDrillData(null); setReclassFor(null) }}
        title={drillNode?.label ?? ""}
      >
        <p className="text-[11px] text-ink-muted -mt-3 mb-3">
          {monthLabel(month)} · line total {drillNode ? rupeeExact(drillNode.amount) : ""}
        </p>

        {drillLoading && <div className="flex justify-center py-8"><Spinner /></div>}
        {drillError && (
          <p className="text-[11px] text-status-warn text-center py-2">{drillError}</p>
        )}

        {!drillLoading && drillData && (
          <div className="flex flex-col">
            {drillData.rows.length === 0 && (
              <EmptyState>No transactions behind this line.</EmptyState>
            )}
            {drillData.rows.map((r, i) => {
              const rowKey = r.id !== null ? `${r.source}-${r.id}` : `${r.source}-${i}`
              const pickerOpen = r.id !== null && reclassFor === r.id
              return (
                <div key={rowKey} className="border-b border-border last:border-0">
                  <button
                    type="button"
                    disabled={!r.reclassifiable}
                    onClick={() => {
                      if (r.id === null) return
                      setReclassFor(pickerOpen ? null : r.id)
                      setReclassCat(r.category ?? "")
                    }}
                    className={`w-full flex items-start justify-between gap-2 py-2.5 text-left ${r.reclassifiable ? "active:opacity-60" : "cursor-default"}`}
                  >
                    <span className="min-w-0 flex flex-col gap-0.5">
                      <span className="text-xs text-ink line-clamp-2">{r.description}</span>
                      <span className="text-[10px] text-ink-muted flex items-center gap-1.5">
                        {r.source === "bank" ? fmtDateShort(r.date) : r.source === "manual" ? "manual figure" : fmtDateShort(r.date)}
                        {r.account && <span>· {r.account}</span>}
                        {r.sub_category && <span className="truncate">· {r.sub_category}</span>}
                        {r.manual_category && (
                          <span className="shrink-0 text-[8px] font-bold uppercase tracking-wide bg-tile-blue text-brand-blue rounded-full px-1.5 py-0.5">
                            reclassified
                          </span>
                        )}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs font-mono text-ink">{rupeeExact(r.amount)}</span>
                  </button>

                  {pickerOpen && (
                    <div className="flex flex-col gap-2 pb-3">
                      <select
                        value={reclassCat}
                        onChange={(e) => setReclassCat(e.target.value)}
                        className="w-full text-xs rounded-lg bg-bg border border-border-strong px-2 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink"
                      >
                        {catOptions.map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                      <div className="flex gap-2">
                        <button
                          onClick={() => r.id !== null && saveReclass(r.id)}
                          disabled={reclassBusy || !reclassCat || reclassCat === r.category}
                          className="flex-1 rounded-pill bg-brand-pink py-2 text-xs font-bold text-white disabled:opacity-50 active:opacity-70"
                        >
                          {reclassBusy ? "Moving…" : `Move to ${reclassCat || "…"}`}
                        </button>
                        <button
                          onClick={() => setReclassFor(null)}
                          className="rounded-pill bg-bg border border-border-strong px-4 py-2 text-xs font-bold text-ink-muted"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}

            {drillData.rows.length > 0 && (
              <div className="flex items-center justify-between pt-2.5">
                <span className="text-xs font-bold text-ink">Sum of rows</span>
                <span className="text-xs font-mono font-bold text-ink">{rupeeExact(drillData.total)}</span>
              </div>
            )}
            {drillMismatch && (
              <p className="mt-2 rounded-lg bg-[#FFF5F0] border border-status-warn px-3 py-2 text-[11px] font-medium text-status-warn">
                Rows sum to {rupeeExact(drillData.total)} but the P&amp;L line shows {rupeeExact(Math.abs(drillNode?.amount ?? 0))} — engine drift, report this.
              </p>
            )}
            <p className="text-[10px] text-ink-muted mt-2">
              Tap a bank transaction to move it to another category. Reclassified rows are locked — re-uploads and auto-classification never undo them.
            </p>
          </div>
        )}
      </Sheet>
    </div>
  )
}
