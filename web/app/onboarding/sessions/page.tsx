"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.getkozzy.com"
const ADMIN_PIN = process.env.NEXT_PUBLIC_ONBOARDING_PIN ?? "cozeevo2026"

function pinHeaders() {
  return { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN }
}

type SessionStatus = "pending_review" | "pending_tenant" | "approved" | "cancelled" | "expired"

interface SessionItem {
  token: string
  status: SessionStatus
  room: string
  tenant_phone: string
  tenant_name: string
  checkin_date: string
  created_at: string
  approved_at: string
  approved_by_phone: string
  agreed_rent: number
  checkin_status: string
  expires_at: string
  expired_ago: string
}

interface SessionDetail {
  status: string
  token: string
  stay_type: string
  room: { number: string; building: string; floor: string; sharing: string }
  agreed_rent: number
  security_deposit: number
  maintenance_fee: number
  booking_amount: number
  advance_mode: string
  checkin_date: string
  lock_in_months: number
  tenant_data: Record<string, string>
  approved_by_name: string
  created_at: string
  approved_at: string
}

const STATUS_LABELS: Record<string, string> = {
  pending_review:  "Pending Review",
  pending_tenant:  "Awaiting Tenant",
  approved:        "Approved",
  cancelled:       "Cancelled",
  expired:         "Expired",
}
const STATUS_COLORS: Record<string, string> = {
  pending_review: "bg-[#FFF3CD] text-[#856404]",
  pending_tenant: "bg-[#E8F4FD] text-[#0C63A5]",
  approved:       "bg-tile-green text-status-paid",
  cancelled:      "bg-[#F0EDE9] text-ink-muted",
  expired:        "bg-[#F0EDE9] text-ink-muted",
}
const CHECKIN_LABELS: Record<string, string> = {
  active:   "Checked In",
  no_show:  "No Show",
  checked_out: "Checked Out",
  inactive: "Inactive",
}
const CHECKIN_COLORS: Record<string, string> = {
  active:   "bg-tile-green text-status-paid",
  no_show:  "bg-[#FFF3CD] text-[#856404]",
  checked_out: "bg-[#F0EDE9] text-ink-muted",
  inactive: "bg-[#F0EDE9] text-ink-muted",
}

const TABS: { key: string; label: string }[] = [
  { key: "",                label: "All" },
  { key: "pending_review",  label: "Pending Review" },
  { key: "pending_tenant",  label: "Awaiting Tenant" },
  { key: "approved",        label: "Approved" },
  { key: "cancelled",       label: "Cancelled" },
  { key: "expired",         label: "Expired" },
]

function fmtDate(iso: string) {
  if (!iso) return "—"
  const [y, m, d] = iso.split("T")[0].split("-")
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${d} ${months[parseInt(m) - 1]}`
}
function fmtINR(n: number) {
  return n > 0 ? `₹${n.toLocaleString("en-IN")}` : "—"
}

export default function OnboardingSessionsPage() {
  const router = useRouter()
  const [activeTab, setActiveTab] = useState("")
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [expandedToken, setExpandedToken] = useState<string | null>(null)
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [toast, setToast] = useState("")

  const loadSessions = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const url = `${API_URL}/api/onboarding/admin/all${activeTab ? `?status=${activeTab}` : ""}`
      const res = await fetch(url, { headers: { "X-Admin-Pin": ADMIN_PIN } })
      if (!res.ok) throw new Error(`Error ${res.status}`)
      const data = await res.json()
      setSessions(data.sessions ?? [])
    } catch {
      setError("Failed to load sessions")
    } finally {
      setLoading(false)
    }
  }, [activeTab])

  useEffect(() => { loadSessions() }, [loadSessions])

  async function loadDetail(token: string) {
    setDetailLoading(true)
    setDetail(null)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/admin/${token}/detail`, {
        headers: { "X-Admin-Pin": ADMIN_PIN }
      })
      if (!res.ok) throw new Error()
      setDetail(await res.json())
    } catch {
      setDetail(null)
    } finally {
      setDetailLoading(false)
    }
  }

  function toggleExpand(token: string) {
    if (expandedToken === token) {
      setExpandedToken(null)
      setDetail(null)
    } else {
      setExpandedToken(token)
      loadDetail(token)
    }
  }

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(""), 2500)
  }

  async function handleCancel(token: string) {
    if (!confirm("Cancel this session?")) return
    setActionLoading(`cancel-${token}`)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/admin/${token}/cancel`, {
        method: "POST", headers: pinHeaders()
      })
      if (!res.ok) throw new Error()
      showToast("Session cancelled")
      loadSessions()
      setExpandedToken(null)
    } catch {
      showToast("Cancel failed")
    } finally {
      setActionLoading(null)
    }
  }

  async function handleResend(token: string) {
    setActionLoading(`resend-${token}`)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/admin/${token}/resend`, {
        method: "POST", headers: pinHeaders()
      })
      if (!res.ok) throw new Error()
      showToast("WhatsApp link resent")
    } catch {
      showToast("Resend failed")
    } finally {
      setActionLoading(null)
    }
  }

  async function handleApprove(token: string) {
    if (!confirm("Approve this session and create the tenancy?")) return
    setActionLoading(`approve-${token}`)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/${token}/approve`, {
        method: "POST",
        headers: pinHeaders(),
        body: JSON.stringify({ approved_by_phone: "7845952289", entry_source: "onboarding_form" }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error((err as { detail?: string }).detail ?? "Approve failed")
      }
      showToast("Approved! Tenancy created.")
      loadSessions()
      setExpandedToken(null)
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Approve failed")
    } finally {
      setActionLoading(null)
    }
  }

  function copyLink(token: string) {
    const link = `${API_URL}/onboard/${token}`
    navigator.clipboard.writeText(link).then(() => showToast("Link copied"))
  }

  // Count per tab (from loaded sessions when on All tab)
  const counts = sessions.reduce<Record<string, number>>((acc, s) => {
    acc[s.status] = (acc[s.status] ?? 0) + 1
    return acc
  }, {})
  const pendingCount = (counts["pending_review"] ?? 0) + (counts["pending_tenant"] ?? 0)

  return (
    <main className="min-h-screen bg-bg pb-32">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9] sticky top-0 z-10">
        <button onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold">
          ←
        </button>
        <h1 className="text-lg font-extrabold text-ink flex-1">Onboarding Sessions</h1>
        {pendingCount > 0 && activeTab === "" && (
          <span className="w-6 h-6 rounded-full bg-brand-pink text-white text-xs font-bold flex items-center justify-center">
            {pendingCount}
          </span>
        )}
        <button onClick={loadSessions}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted text-sm font-bold">
          ↻
        </button>
      </div>

      {/* Status tabs */}
      <div className="flex gap-2 px-4 py-3 overflow-x-auto scrollbar-none border-b border-[#F0EDE9] bg-surface">
        {TABS.map((tab) => (
          <button key={tab.key} type="button" onClick={() => { setActiveTab(tab.key); setExpandedToken(null) }}
            className={`flex-shrink-0 px-3 py-1.5 rounded-full text-xs font-bold border-2 transition-colors ${
              activeTab === tab.key
                ? "border-brand-pink bg-brand-pink text-white"
                : "border-[#E2DEDD] bg-bg text-ink-muted"
            }`}>
            {tab.label}
          </button>
        ))}
      </div>

      <div className="px-4 pt-3 flex flex-col gap-2 max-w-lg mx-auto">

        {loading && (
          <div className="text-center text-xs text-ink-muted py-8">Loading…</div>
        )}
        {error && (
          <div className="text-center text-xs text-status-warn py-4">{error}</div>
        )}
        {!loading && !error && sessions.length === 0 && (
          <div className="text-center text-xs text-ink-muted py-8">No sessions found</div>
        )}

        {sessions.map((s) => {
          const isExpanded = expandedToken === s.token
          const name = s.tenant_name || "Pending fill"
          const hasPendingFill = !s.tenant_name

          return (
            <div key={s.token} className="bg-surface rounded-card border border-[#F0EDE9] overflow-hidden">
              {/* Row */}
              <button type="button" onClick={() => toggleExpand(s.token)}
                className="w-full flex items-start gap-3 p-4 text-left active:bg-[#FAF9F7]">
                {/* Avatar */}
                <div className="w-9 h-9 rounded-full bg-[#F0EDE9] flex items-center justify-center text-ink-muted font-bold text-sm flex-shrink-0">
                  {hasPendingFill ? "?" : name[0].toUpperCase()}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-sm font-bold ${hasPendingFill ? "text-ink-muted italic" : "text-ink"}`}>
                      {name}
                    </span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${STATUS_COLORS[s.status] ?? "bg-[#F0EDE9] text-ink-muted"}`}>
                      {STATUS_LABELS[s.status] ?? s.status}
                    </span>
                    {s.checkin_status && CHECKIN_LABELS[s.checkin_status] && (
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${CHECKIN_COLORS[s.checkin_status] ?? "bg-[#F0EDE9] text-ink-muted"}`}>
                        {CHECKIN_LABELS[s.checkin_status]}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-ink-muted mt-0.5">
                    Room {s.room || "—"} · {s.tenant_phone}
                    {s.checkin_date ? ` · Check-in ${fmtDate(s.checkin_date)}` : ""}
                  </p>
                  <p className="text-[10px] text-ink-muted mt-0.5">
                    Created {fmtDate(s.created_at)}
                    {s.agreed_rent > 0 ? ` · ${fmtINR(s.agreed_rent)}/mo` : ""}
                    {s.expired_ago ? ` · Expired ${s.expired_ago}` : ""}
                  </p>
                </div>

                <span className={`text-ink-muted text-xs mt-1 flex-shrink-0 transition-transform duration-150 ${isExpanded ? "rotate-90" : ""}`}>▶</span>
              </button>

              {/* Expanded detail */}
              {isExpanded && (
                <div className="border-t border-[#F0EDE9] px-4 pb-4">
                  {detailLoading && <p className="text-xs text-ink-muted text-center py-4">Loading…</p>}

                  {detail && detail.token === s.token && (
                    <>
                      {/* Room & Booking */}
                      <div className="mt-3 mb-3">
                        <p className="text-[10px] font-bold text-ink-muted uppercase tracking-wide mb-2">Room &amp; Booking</p>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                          <DetailField label="Room" value={`${detail.room.number}${detail.room.building ? ` · ${detail.room.building}` : ""}`} />
                          <DetailField label="Floor" value={detail.room.floor || "—"} />
                          <DetailField label="Sharing type" value={detail.sharing_type || detail.room.sharing || "—"} />
                          <DetailField label="Check-in" value={fmtDate(detail.checkin_date)} />
                          <DetailField label="Stay type" value={detail.stay_type === "daily" ? "Day-wise" : "Monthly"} />
                          <DetailField label="Agreed rent" value={fmtINR(detail.agreed_rent)} />
                          {detail.security_deposit > 0 && <DetailField label="Security deposit" value={fmtINR(detail.security_deposit)} />}
                          {detail.maintenance_fee > 0 && <DetailField label="Maintenance" value={fmtINR(detail.maintenance_fee)} />}
                          {detail.booking_amount > 0 && <DetailField label="Booking amount" value={fmtINR(detail.booking_amount)} />}
                        </div>
                      </div>

                      {/* Tenant data (if filled) */}
                      {detail.tenant_data && Object.keys(detail.tenant_data).length > 0 && (
                        <div className="mb-3">
                          <p className="text-[10px] font-bold text-ink-muted uppercase tracking-wide mb-2">Tenant Details</p>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                            {detail.tenant_data.name && <DetailField label="Name" value={detail.tenant_data.name} />}
                            {detail.tenant_data.gender && <DetailField label="Gender" value={detail.tenant_data.gender} />}
                            {detail.tenant_data.occupation && <DetailField label="Occupation" value={detail.tenant_data.occupation} />}
                            {detail.tenant_data.email && <DetailField label="Email" value={detail.tenant_data.email} />}
                          </div>
                        </div>
                      )}

                      {/* Status note */}
                      {s.status === "pending_tenant" && (
                        <p className="text-xs text-ink-muted italic mb-3">Tenant hasn&apos;t filled the form yet.<br />Waiting for tenant to fill the form.</p>
                      )}
                      {s.status === "pending_review" && (
                        <p className="text-xs text-ink-muted italic mb-3">Tenant has filled the form. Ready for your approval.</p>
                      )}
                      {s.status === "approved" && detail.approved_by_name && (
                        <p className="text-xs text-ink-muted mb-3">Approved by {detail.approved_by_name} on {fmtDate(detail.approved_at)}</p>
                      )}

                      {/* Actions */}
                      <div className="flex flex-wrap gap-2">
                        {s.status === "pending_review" && (
                          <button
                            onClick={() => handleApprove(s.token)}
                            disabled={actionLoading === `approve-${s.token}`}
                            className="rounded-pill bg-brand-pink text-white px-4 py-2 text-xs font-bold active:opacity-80 disabled:opacity-40">
                            {actionLoading === `approve-${s.token}` ? "Approving…" : "Approve"}
                          </button>
                        )}
                        {(s.status === "pending_tenant" || s.status === "pending_review") && (
                          <button
                            onClick={() => handleResend(s.token)}
                            disabled={actionLoading === `resend-${s.token}`}
                            className="rounded-pill bg-[#25D366] text-white px-4 py-2 text-xs font-bold active:opacity-80 disabled:opacity-40">
                            {actionLoading === `resend-${s.token}` ? "Sending…" : "Resend WhatsApp"}
                          </button>
                        )}
                        <button
                          onClick={() => copyLink(s.token)}
                          className="rounded-pill border border-[#E2DEDD] text-ink px-4 py-2 text-xs font-semibold active:opacity-70">
                          Copy Link
                        </button>
                        {(s.status === "pending_tenant" || s.status === "pending_review") && (
                          <button
                            onClick={() => handleCancel(s.token)}
                            disabled={actionLoading === `cancel-${s.token}`}
                            className="rounded-pill border border-status-warn text-status-warn px-4 py-2 text-xs font-semibold active:opacity-70 disabled:opacity-40">
                            {actionLoading === `cancel-${s.token}` ? "Cancelling…" : "Cancel"}
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-36 left-1/2 -translate-x-1/2 bg-[#1C1C1E] text-white text-xs font-semibold px-4 py-2 rounded-full shadow-lg z-50">
          {toast}
        </div>
      )}
    </main>
  )
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">{label}</p>
      <p className="text-xs font-medium text-ink mt-0.5">{value || "—"}</p>
    </div>
  )
}
