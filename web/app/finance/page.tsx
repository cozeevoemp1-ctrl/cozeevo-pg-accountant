"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { OccupancyTab } from "@/components/finance/occupancy-tab"
import { InvestmentSection } from "@/components/finance/investment-section"
import { ThreeStatementTab } from "@/components/finance/three-statement-tab"
import { UploadCard } from "@/components/finance/upload-card"
import { FinanceUploadResult } from "@/lib/api"
import { supabase } from "@/lib/supabase"

export default function FinancePage() {
  const router = useRouter()
  // Bump on every successful upload → remounts ThreeStatementTab so it refetches
  const [refreshKey, setRefreshKey] = useState(0)
  const [lastUpload, setLastUpload] = useState<FinanceUploadResult | null>(null)

  // Admin gate — client-side check
  useEffect(() => {
    supabase().auth.getSession().then(({ data: s }) => {
      const role = s.session?.user.user_metadata?.role
      if (role !== "admin") router.replace("/")
    })
  }, [router])

  function handleUploaded(res: FinanceUploadResult) {
    setLastUpload(res)
    setRefreshKey(k => k + 1)
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

      <UploadCard onUploaded={handleUploaded} />
      {lastUpload && lastUpload.months_affected.length > 0 && (
        <p className="text-[11px] text-ink-muted text-center -mt-2">
          Pick a month below to view its P&amp;L · updated {lastUpload.months_affected.join(", ")}
        </p>
      )}

      <ThreeStatementTab key={refreshKey} />
      <OccupancyTab />
      <InvestmentSection />
    </main>
  )
}
