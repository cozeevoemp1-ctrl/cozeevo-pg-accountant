"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { getOverdueTenants, OverdueTenant } from "@/lib/api"
import { rupee } from "@/lib/format"
import { fmtDateShort } from "@/lib/date"
import { PageHeader } from "@/components/ui/page-header"
import { Skeleton } from "@/components/ui/skeleton"

// Read-only overdue list. The send-reminder actions were removed 2026-08-07:
// the backend endpoint is permanently 410 (no automated tenant messages —
// hard rule), so the buttons only ever produced error toasts.

export default function RemindersPage() {
  const router = useRouter()

  const [tenants, setTenants] = useState<OverdueTenant[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState("")

  useEffect(() => {
    getOverdueTenants()
      .then(setTenants)
      .catch(() => setFetchError("Could not load overdue tenants"))
      .finally(() => setLoading(false))
  }, [])

  const totalDues = tenants.reduce((sum, t) => sum + t.dues, 0)

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="px-5 pt-12 bg-surface border-b border-border">
        <PageHeader title="Overdue dues" />
      </div>

      <div className="px-4 pt-4 pb-32 flex flex-col gap-4 max-w-lg mx-auto">
        {/* Summary banner */}
        {!loading && !fetchError && (
          <div className="bg-surface rounded-card border border-border px-4 py-3 flex items-center justify-between">
            <div>
              <p className="text-xs text-ink-muted">Overdue tenants</p>
              <p className="text-lg font-extrabold text-status-warn">{tenants.length}</p>
            </div>
            {tenants.length > 0 && (
              <div className="text-right">
                <p className="text-xs text-ink-muted">Total outstanding</p>
                <p className="text-lg font-extrabold text-status-warn">{rupee(totalDues)}</p>
              </div>
            )}
          </div>
        )}

        {/* Loading skeletons */}
        {loading && (
          <div className="flex flex-col gap-2">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="bg-surface rounded-card border border-border p-4 flex justify-between items-center">
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-3.5 w-28" />
                  <Skeleton className="h-2.5 w-40" />
                </div>
                <Skeleton className="h-3.5 w-16" />
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {!loading && fetchError && (
          <div className="bg-surface rounded-card border border-border p-6 text-center">
            <p className="text-sm text-status-warn">{fetchError}</p>
          </div>
        )}

        {/* Empty */}
        {!loading && !fetchError && tenants.length === 0 && (
          <div className="bg-surface rounded-card border border-border p-8 flex flex-col items-center gap-3">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#22C55E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <p className="text-sm font-semibold text-ink">All clear!</p>
            <p className="text-xs text-ink-muted text-center">No tenants with overdue rent</p>
          </div>
        )}

        {/* Tenant rows */}
        {!loading && !fetchError && tenants.length > 0 && (
          <div className="flex flex-col gap-2">
            {tenants.map((t) => (
              <button
                key={t.tenancy_id}
                onClick={() => router.push(`/payment/new?tenancy_id=${t.tenancy_id}`)}
                className="bg-surface rounded-card border border-border p-4 flex items-center justify-between gap-3 text-left active:opacity-80"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-ink truncate">{t.name}</p>
                  <p className="text-xs text-ink-muted mt-0.5">Room {t.room}</p>
                  <p className="text-xs text-ink-muted mt-0.5">
                    Reminded {t.reminder_count} time{t.reminder_count !== 1 ? "s" : ""}
                    {t.last_reminded_at ? ` · last ${fmtDateShort(t.last_reminded_at)}` : ""}
                  </p>
                </div>
                <span className="text-sm font-bold text-status-warn shrink-0">
                  {rupee(t.dues)}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
