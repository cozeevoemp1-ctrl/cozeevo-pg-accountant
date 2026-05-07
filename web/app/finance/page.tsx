"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { getFinancePnl, getDepositReconciliation, downloadPnlExcel, downloadPnlLive, getUnitEconomics, FinanceMonthData, FinanceUploadResult, DepositReconcileRow, UnitEconomics } from "@/lib/api"
import { KpiTiles, IncomeCard, ExpenseCard } from "@/components/finance/pnl-cards"
import { UploadCard } from "@/components/finance/upload-card"
import { ReconcileCard } from "@/components/finance/reconcile-card"
import { UnitEconomicsCard } from "@/components/finance/unit-economics-card"
import { supabase } from "@/lib/supabase"

function prevMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number)
  if (mo === 1) return `${y - 1}-12`
  return `${y}-${String(mo - 1).padStart(2, "0")}`
}

function nextMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number)
  if (mo === 12) return `${y + 1}-01`
  return `${y}-${String(mo + 1).padStart(2, "0")}`
}

function monthLabel(m: string): string {
  const [y, mo] = m.split("-").map(Number)
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${months[mo - 1]} ${y}`
}

export default function FinancePage() {
  const router = useRouter()
  const now = new Date()
  const [month, setMonth] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
  )
  const [data, setData] = useState<FinanceMonthData | null>(null)
  const [reconcileRows, setReconcileRows] = useState<DepositReconcileRow[]>([])
  const [unitEcon, setUnitEcon] = useState<UnitEconomics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [downloading, setDownloading] = useState(false)
  const [downloadingLive, setDownloadingLive] = useState(false)

  // Admin gate — client-side check
  useEffect(() => {
    supabase().auth.getSession().then(({ data: s }) => {
      const role = s.session?.user.user_metadata?.role
      if (role !== "admin") router.replace("/")
    })
  }, [router])

  const loadPnl = useCallback(async (m: string) => {
    setLoading(true)
    setError("")
    const [pnlResult, reconcileResult, ueResult] = await Promise.allSettled([
      getFinancePnl(m),
      getDepositReconciliation(m),
      getUnitEconomics(m),
    ])
    if (pnlResult.status === "fulfilled") {
      setData(pnlResult.value.data[m] ?? null)
    } else {
      setData(null)
      setError(pnlResult.reason instanceof Error ? pnlResult.reason.message : "Failed to load")
    }
    if (reconcileResult.status === "fulfilled") setReconcileRows(reconcileResult.value.rows)
    if (ueResult.status === "fulfilled") setUnitEcon(ueResult.value)
    setLoading(false)
  }, [])

  useEffect(() => { loadPnl(month) }, [month, loadPnl])

  async function handleDownload() {
    setDownloading(true)
    try {
      await downloadPnlExcel()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed")
    } finally {
      setDownloading(false)
    }
  }

  async function handleDownloadLive() {
    setDownloadingLive(true)
    try {
      await downloadPnlLive()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed")
    } finally {
      setDownloadingLive(false)
    }
  }

  function handleUploaded(result: FinanceUploadResult) {
    if (result.months_affected.includes(month)) {
      loadPnl(month)
    }
  }

  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-32 max-w-lg mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => router.back()} className="text-ink-muted text-lg font-bold">←</button>
        <h1 className="text-lg font-extrabold text-ink flex-1">Finance</h1>
        <span className="text-[9px] font-bold px-2 py-1 rounded-full bg-tile-pink text-brand-pink uppercase tracking-wide">
          Owner
        </span>
      </div>

      {/* Month picker */}
      <div className="flex items-center justify-between bg-[#0F0E0D] rounded-pill px-5 py-3">
        <button onClick={() => setMonth(prevMonth(month))} className="text-[#6F655D] text-sm font-bold">←</button>
        <span className="text-white text-sm font-bold">{monthLabel(month)}</span>
        <button onClick={() => setMonth(nextMonth(month))} className="text-[#6F655D] text-sm font-bold">→</button>
      </div>

      {/* P&L content */}
      {loading && (
        <div className="py-12 text-center text-xs text-ink-muted">Loading…</div>
      )}

      {!loading && !data && (
        <div className="py-12 text-center">
          <p className="text-sm text-ink-muted font-medium">No data for {monthLabel(month)}</p>
          <p className="text-xs text-ink-muted mt-1">Upload a bank statement below to generate P&L</p>
        </div>
      )}

      {!loading && data && (
        <>
          <KpiTiles data={data} />
          <IncomeCard data={data} />
          <ExpenseCard data={data} />
          <ReconcileCard rows={reconcileRows} />
        </>
      )}

      {/* Unit Economics — always shown (occupancy/rent from DB; per-bed figures need bank data) */}
      {!loading && unitEcon && (
        <>
          <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide px-1 mt-2">Unit Economics</p>
          <UnitEconomicsCard data={unitEcon} />
        </>
      )}

      {/* Upload */}
      <UploadCard onUploaded={handleUploaded} />

      {/* Downloads */}
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          className="w-full rounded-pill border border-[#E2DEDD] py-3 text-sm font-semibold text-ink disabled:opacity-50 active:opacity-70"
        >
          {downloading ? "Preparing…" : "↓ P&L Report (Oct'25–Apr'26)"}
        </button>
        <button
          type="button"
          onClick={handleDownloadLive}
          disabled={downloadingLive}
          className="w-full rounded-pill border border-[#E2DEDD] py-3 text-sm font-semibold text-ink disabled:opacity-50 active:opacity-70 text-ink-muted"
        >
          {downloadingLive ? "Recalculating…" : "↓ Recalculate from Latest Uploads"}
        </button>
      </div>

      {error && (
        <p className="text-[10px] text-status-warn font-medium text-center">{error}</p>
      )}
    </main>
  )
}
