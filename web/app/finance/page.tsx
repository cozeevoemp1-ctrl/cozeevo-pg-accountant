"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { UpiReconcileTab } from "@/components/finance/upi-reconcile-tab"
import { OccupancyTab } from "@/components/finance/occupancy-tab"
import { supabase } from "@/lib/supabase"

export default function FinancePage() {
  const router = useRouter()
  const [tab, setTab] = useState<"reconcile" | "occupancy">("occupancy")

  // Admin gate — client-side check
  useEffect(() => {
    supabase().auth.getSession().then(({ data: s }) => {
      const role = s.session?.user.user_metadata?.role
      if (role !== "admin") router.replace("/")
    })
  }, [router])

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

      {/* Tab bar */}
      <div className="flex border-b border-[#F0EDE9]">
        {(["occupancy", "reconcile"] as const).map(key => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-3 py-3 text-sm font-bold border-b-2 transition-colors ${
              tab === key
                ? "text-[#EF1F9C] border-[#EF1F9C]"
                : "text-[#999] border-transparent"
            }`}
          >
            {key === "reconcile" ? "UPI" : "Occ."}
          </button>
        ))}
      </div>

      {tab === "reconcile" && <UpiReconcileTab />}
      {tab === "occupancy" && <OccupancyTab />}
    </main>
  )
}
