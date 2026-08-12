"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import { getTenantsList, TenantListItem, TenantSearchResult } from "@/lib/api"
import { LogoutButton } from "@/components/home/logout-avatar"
import { rupee } from "@/lib/format"
import { PageHeader } from "@/components/ui/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty-state"

const QUICK_ACTIONS = [
  {
    label: "New Check-in",
    href: "/checkin/new",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
        <polyline points="10 17 15 12 10 7" />
        <line x1="15" y1="12" x2="3" y2="12" />
      </svg>
    ),
    textColor: "text-brand-blue",
    bg: "bg-tile-blue",
  },
  {
    label: "New Check-out",
    href: "/checkout/new",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
        <polyline points="16 17 21 12 16 7" />
        <line x1="21" y1="12" x2="9" y2="12" />
      </svg>
    ),
    textColor: "text-status-warn",
    bg: "bg-tile-orange",
  },
  {
    label: "Overdue Dues",
    href: "/reminders",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
    ),
    textColor: "text-[#F59E0B]",
    bg: "bg-tile-yellow",
  },
  {
    label: "Collection Report",
    href: "/collection/breakdown",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </svg>
    ),
    textColor: "text-brand-pink",
    bg: "bg-tile-pink",
  },
  {
    label: "Notices",
    href: "/notices",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
    textColor: "text-status-warn",
    bg: "bg-tile-orange",
  },
]

export default function ManageTenantsPage() {
  const router = useRouter()

  const [tenants, setTenants] = useState<TenantListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    getTenantsList()
      .then(setTenants)
      .catch(() => setError("Could not load tenants"))
      .finally(() => setLoading(false))
  }, [])

  function handleTenantSelect(t: TenantSearchResult) {
    router.push(`/tenants/${t.tenancy_id}/edit`)
  }

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="px-5 pt-12 bg-surface border-b border-border">
        <PageHeader title="Manage Tenants" right={<LogoutButton />} />
      </div>

      <div className="px-4 pt-4 pb-32 flex flex-col gap-5 max-w-lg mx-auto">
        {/* Search */}
        <div className="bg-surface rounded-card p-4 border border-border">
          <TenantSearch
            onSelect={handleTenantSelect}
            placeholder="Search by name, room, phone…"
          />
        </div>

        {/* Quick actions */}
        <section>
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Quick Actions</p>
          <div className="grid grid-cols-2 gap-3">
            {QUICK_ACTIONS.map((action, i) => (
              <button
                key={action.label}
                onClick={() => router.push(action.href)}
                className={`${action.bg} rounded-card p-4 flex flex-col items-start gap-2 active:opacity-80 border border-border ${i === QUICK_ACTIONS.length - 1 && QUICK_ACTIONS.length % 2 !== 0 ? "col-span-2" : ""}`}
              >
                <span className={action.textColor}>{action.icon}</span>
                <span className="text-sm font-bold text-ink leading-tight">{action.label}</span>
              </button>
            ))}
          </div>
        </section>

        {/* Active tenants list */}
        <section>
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Active Tenants</p>

          {loading && (
            <div className="flex flex-col gap-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="bg-surface rounded-card border border-border p-4 flex justify-between items-center">
                  <div className="flex flex-col gap-2">
                    <Skeleton className="h-3.5 w-32" />
                    <Skeleton className="h-2.5 w-20" />
                  </div>
                  <div className="h-6 w-16 bg-border rounded-pill animate-pulse" />
                </div>
              ))}
            </div>
          )}

          {!loading && error && (
            <div className="bg-surface rounded-card border border-border p-6 text-center">
              <p className="text-sm text-status-warn">{error}</p>
            </div>
          )}

          {!loading && !error && tenants.length === 0 && (
            <EmptyState>No active tenants found</EmptyState>
          )}

          {!loading && !error && tenants.length > 0 && (
            <div className="flex flex-col gap-2">
              {tenants.map((t) => (
                <button
                  key={t.tenancy_id}
                  onClick={() => router.push(`/tenants/${t.tenancy_id}/edit`)}
                  className="bg-surface rounded-card border border-border p-4 flex justify-between items-center active:opacity-70 text-left w-full"
                >
                  <div>
                    <p className="text-sm font-semibold text-ink">{t.name}</p>
                    <p className="text-xs text-ink-muted mt-0.5">Room {t.room_number} · {t.building_code}</p>
                  </div>
                  <span
                    className={`text-xs font-bold px-2.5 py-1 rounded-pill ${
                      t.dues > 0
                        ? "bg-red-50 text-status-warn"
                        : "bg-tile-green text-status-paid"
                    }`}
                  >
                    {t.dues > 0 ? rupee(t.dues) : "Paid"}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}
