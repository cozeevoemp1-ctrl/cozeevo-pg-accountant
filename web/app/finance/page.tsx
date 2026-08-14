"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { OccupancyTab } from "@/components/finance/occupancy-tab"
import { InvestmentSection } from "@/components/finance/investment-section"
import { PnlMonthCard } from "@/components/finance/pnl-month-card"
import { UploadCard } from "@/components/finance/upload-card"
import { FinanceUploadResult, downloadPnlExcel } from "@/lib/api"
import { PnlAdjustmentsCard } from "@/components/finance/pnl-adjustments-card"
import { PageHeader } from "@/components/ui/page-header"
import { supabase } from "@/lib/supabase"

export default function FinancePage() {
  const router = useRouter()
  // Bumped after CSV upload / manual-figures save → PnlMonthCard jumps to that
  // month and refetches (the server computes live; a refetch IS the recalc).
  const [pnlSignal, setPnlSignal] = useState<{ month?: string; n: number }>({ n: 0 })
  const [lastUpload, setLastUpload] = useState<FinanceUploadResult | null>(null)
  const [pnlState, setPnlState] = useState<"idle" | "loading" | "error">("idle")
  const [pnlError, setPnlError] = useState("")

  async function handleGeneratePnl() {
    setPnlState("loading")
    setPnlError("")
    try {
      await downloadPnlExcel()
      setPnlState("idle")
    } catch (e: unknown) {
      setPnlError(e instanceof Error ? e.message : "unknown error")
      setPnlState("error")
    }
  }

  // Admin gate — client-side check
  useEffect(() => {
    supabase().auth.getSession().then(({ data: s }) => {
      // role from app_metadata ONLY — user_metadata is self-editable.
      const role = s.session?.user.app_metadata?.role
      if (role !== "admin") router.replace("/")
    })
  }, [router])

  function handleUploaded(res: FinanceUploadResult) {
    setLastUpload(res)
    const latest = res.months_affected[res.months_affected.length - 1]
    setPnlSignal(s => ({ month: latest, n: s.n + 1 }))
  }

  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-32 max-w-lg mx-auto">
      {/* Header */}
      <PageHeader
        title="Finance"
        right={
          <span className="text-[9px] font-bold px-2 py-1 rounded-full bg-tile-pink text-brand-pink uppercase tracking-wide">
            Owner
          </span>
        }
      />

      <UploadCard onUploaded={handleUploaded} />
      {lastUpload && lastUpload.months_affected.length > 0 && (
        <p className="text-[11px] text-ink-muted text-center -mt-2">
          Pick a month below to view its P&amp;L · updated {lastUpload.months_affected.join(", ")}
        </p>
      )}

      {/* Generate full P&L Excel — identical to the verified accountant output */}
      <div className="bg-surface rounded-card border border-border px-4 py-3 flex flex-col gap-2">
        <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">Profit &amp; Loss</p>
        <button
          onClick={handleGeneratePnl}
          disabled={pnlState === "loading"}
          className="flex items-center justify-center gap-2 rounded-pill bg-ink py-3 text-sm font-bold text-white disabled:opacity-50 active:opacity-80"
        >
          <span>📊</span>
          <span>{pnlState === "loading" ? "Generating…" : "Generate P&L (all uploaded months)"}</span>
        </button>
        {pnlState === "error" && (
          <p className="text-[10px] text-status-warn text-center">Could not generate — {pnlError || "try again"}</p>
        )}
        <p className="text-[10px] text-ink-muted text-center">
          SOP-format Excel. Verified months stay frozen; every uploaded month after is
          computed live from the bank statement + the cash figures below.
        </p>
      </div>

      <PnlAdjustmentsCard onSaved={(m) => setPnlSignal(s => ({ month: m, n: s.n + 1 }))} />

      {/* SOP P&L hierarchy — same engine as the Excel (spec 01 Phase 1).
          Balance Sheet + Cash Flow return in Phases 5–6, rebuilt on SOP outputs
          (the old three-statement card deviated from the SOP and was retired). */}
      <PnlMonthCard refreshSignal={pnlSignal} />
      <OccupancyTab />
      <InvestmentSection />
    </main>
  )
}
