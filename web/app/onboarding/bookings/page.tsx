"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { updateBookingSession, cancelBookingSession } from "@/lib/api"

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.getkozzy.com"
const ADMIN_PIN = process.env.NEXT_PUBLIC_ONBOARDING_PIN ?? "cozeevo2026"

function pinHeaders() {
  return { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN }
}

interface Booking {
  token: string
  status: string
  room: string
  tenant_phone: string
  tenant_name: string
  checkin_date: string
  created_at: string
  agreed_rent?: number
  maintenance_fee?: number
  security_deposit?: number
  is_qr?: boolean
}

function fmtDate(iso: string) {
  if (!iso) return "—"
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
}

function fmtRent(n?: number) {
  if (!n) return "—"
  return `₹${n.toLocaleString("en-IN")}/mo`
}

function isToday(iso: string) {
  if (!iso) return false
  const d = new Date(iso)
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
}

export default function BookingsPage() {
  const router = useRouter()
  const [bookings, setBookings] = useState<Booking[]>([])
  const [loading, setLoading] = useState(true)
  const [checkingIn, setCheckingIn] = useState<string | null>(null)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/admin/pending`, { headers: pinHeaders() })
      if (!res.ok) throw new Error(`Load failed: ${res.status}`)
      const d = await res.json()
      // Show both pending_tenant (awaiting form) and pending_review (ready to check in)
      const all = (d.sessions as Booking[]).filter(
        (s) => s.status === "pending_review" || s.status === "pending_tenant"
      )
      // Sort: check-in today first, then pending_review before pending_tenant, then by date
      all.sort((a, b) => {
        const aToday = isToday(a.checkin_date) ? 0 : 1
        const bToday = isToday(b.checkin_date) ? 0 : 1
        if (aToday !== bToday) return aToday - bToday
        if (a.status !== b.status) return a.status === "pending_review" ? -1 : 1
        return a.checkin_date.localeCompare(b.checkin_date)
      })
      setBookings(all)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function saveAndCheckin(token: string) {
    if (!confirm("Save details and check in this tenant now? Their status will become Active.")) return
    setCheckingIn(token)
    setError("")
    try {
      const res = await fetch(`${API_URL}/api/onboarding/${token}/approve`, {
        method: "POST",
        headers: pinHeaders(),
        body: JSON.stringify({ instant_checkin: true, approved_by_phone: "", overrides: {} }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error((d as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Check-in failed")
    } finally {
      setCheckingIn(null)
    }
  }

  const ready = bookings.filter((b) => b.status === "pending_review")
  const awaiting = bookings.filter((b) => b.status === "pending_tenant")

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
        <button onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
          aria-label="Back">←</button>
        <h1 className="text-lg font-extrabold text-ink flex-1">Bookings</h1>
        <button onClick={load} className="text-xs font-semibold text-brand-pink px-3 py-1.5 rounded-pill border border-brand-pink/30">
          Refresh
        </button>
      </div>

      <div className="px-4 pt-4 pb-32 max-w-lg mx-auto flex flex-col gap-3">
        {error && (
          <div className="rounded-tile bg-[#FFF0F0] border border-status-warn px-4 py-3 text-xs text-status-warn font-medium">
            {error}
          </div>
        )}

        {loading ? (
          <p className="text-sm text-ink-muted text-center py-10">Loading bookings…</p>
        ) : bookings.length === 0 ? (
          <div className="text-center py-16">
            <p className="text-4xl mb-3">📋</p>
            <p className="text-sm font-semibold text-ink">No pending bookings</p>
            <p className="text-xs text-ink-muted mt-1">Pre-book from vacant beds on the home screen</p>
          </div>
        ) : (
          <>
            {/* Ready to check in */}
            {ready.length > 0 && (
              <>
                <p className="text-xs text-ink-muted font-semibold uppercase tracking-wide">
                  {ready.length} ready to check in
                </p>
                {ready.map((b) => (
                  <BookingCard
                    key={b.token}
                    b={b}
                    checkingIn={checkingIn}
                    onCheckin={saveAndCheckin}
                    onReload={load}
                  />
                ))}
              </>
            )}

            {/* Awaiting form */}
            {awaiting.length > 0 && (
              <>
                <p className="text-xs text-ink-muted font-semibold uppercase tracking-wide mt-2">
                  {awaiting.length} awaiting form
                </p>
                {awaiting.map((b) => (
                  <BookingCard
                    key={b.token}
                    b={b}
                    checkingIn={checkingIn}
                    onCheckin={saveAndCheckin}
                    onReload={load}
                  />
                ))}
              </>
            )}
          </>
        )}
      </div>
    </main>
  )
}

function BookingCard({ b, checkingIn, onCheckin, onReload }: {
  b: Booking
  checkingIn: string | null
  onCheckin: (token: string) => void
  onReload: () => void
}) {
  const isPending = b.status === "pending_tenant"
  const checkinToday = isToday(b.checkin_date)

  const [editing, setEditing] = useState(false)
  const [cancelConfirm, setCancelConfirm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [err, setErr] = useState("")

  // Edit fields
  const [editRoom, setEditRoom] = useState(b.room || "")
  const [editCheckin, setEditCheckin] = useState(b.checkin_date?.slice(0, 10) || "")
  const [editRent, setEditRent] = useState(String(b.agreed_rent || ""))
  const [editMaint, setEditMaint] = useState(String(b.maintenance_fee || 5000))
  const [editDeposit, setEditDeposit] = useState(String(b.security_deposit || b.agreed_rent || ""))
  const [editPhone, setEditPhone] = useState(b.tenant_phone || "")
  const [editName, setEditName] = useState(b.tenant_name || "")

  async function saveEdit() {
    setSaving(true); setErr("")
    try {
      await updateBookingSession(b.token, {
        room_number: editRoom || undefined,
        checkin_date: editCheckin || undefined,
        agreed_rent: editRent ? parseFloat(editRent) : undefined,
        maintenance_fee: editMaint ? parseFloat(editMaint) : undefined,
        security_deposit: editDeposit ? parseFloat(editDeposit) : undefined,
        tenant_phone: editPhone || undefined,
        tenant_name: editName || undefined,
      })
      setEditing(false)
      onReload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  async function doCancel() {
    setCancelling(true); setErr("")
    try {
      await cancelBookingSession(b.token)
      onReload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Cancel failed")
      setCancelling(false)
    }
  }

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-3">
      {/* Name + badges */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-bold text-ink truncate">
            {b.tenant_name || b.tenant_phone}
          </p>
          <p className="text-xs text-ink-muted">{b.tenant_phone}</p>
        </div>
        <div className="flex gap-1.5 flex-shrink-0 flex-wrap justify-end">
          {checkinToday && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#FEE2E2] text-[#991B1B]">Today!</span>
          )}
          {b.is_qr && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#EDE9FE] text-[#5B21B6]">QR</span>
          )}
          {isPending ? (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#FEF3C7] text-[#92400E]">Awaiting form</span>
          ) : (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#D1FAE5] text-[#065F46]">Form filled</span>
          )}
        </div>
      </div>

      {/* Details row */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "Room", value: b.room || "TBD" },
          { label: "Check-in", value: fmtDate(b.checkin_date) },
          { label: "Rent", value: fmtRent(b.agreed_rent) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-[#F6F5F0] rounded-tile px-2.5 py-2">
            <p className="text-[9px] text-ink-muted font-semibold uppercase tracking-wide">{label}</p>
            <p className="text-xs font-bold text-ink mt-0.5">{value}</p>
          </div>
        ))}
      </div>

      {/* Error */}
      {err && <p className="text-xs text-status-warn font-medium">{err}</p>}

      {/* Inline edit panel */}
      {editing && (
        <div className="flex flex-col gap-2 border-t border-[#F0EDE9] pt-3">
          <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">Edit booking</p>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: "Name", val: editName, set: setEditName, type: "text", placeholder: "Full name" },
              { label: "Phone", val: editPhone, set: setEditPhone, type: "tel", placeholder: "10 digits" },
              { label: "Room", val: editRoom, set: setEditRoom, type: "text", placeholder: "e.g. 416" },
              { label: "Check-in", val: editCheckin, set: setEditCheckin, type: "date", placeholder: "" },
              { label: "Rent (₹)", val: editRent, set: setEditRent, type: "number", placeholder: "" },
              { label: "Maintenance (₹)", val: editMaint, set: setEditMaint, type: "number", placeholder: "5000" },
              { label: "Deposit (₹)", val: editDeposit, set: setEditDeposit, type: "number", placeholder: "= rent" },
            ].map(({ label, val, set, type, placeholder }) => (
              <div key={label} className={label === "Name" || label === "Check-in" ? "col-span-2" : ""}>
                <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">{label}</label>
                <input
                  type={type}
                  value={val}
                  onChange={(e) => set(e.target.value)}
                  placeholder={placeholder}
                  className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink"
                />
              </div>
            ))}
          </div>
          <div className="flex gap-2 pt-1">
            <button onClick={() => { setEditing(false); setErr("") }}
              className="flex-1 rounded-pill border border-[#E2DEDD] py-2 text-xs font-semibold text-ink-muted">
              Cancel
            </button>
            <button onClick={saveEdit} disabled={saving}
              className="flex-1 rounded-pill bg-brand-pink py-2 text-xs font-bold text-white disabled:opacity-50">
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      )}

      {/* Action row */}
      {!editing && (
        <div className="flex gap-2 pt-1">
          {isPending ? (
            <>
              <a
                href={`${API_URL}/onboard/${b.token}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex-1 text-center rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink active:opacity-70"
              >
                Copy link →
              </a>
              <button onClick={() => { setEditing(true); setCancelConfirm(false); setErr("") }}
                className="px-4 rounded-pill border border-[#00AEED] py-2.5 text-xs font-semibold text-[#00AEED] active:opacity-70">
                Edit
              </button>
              {cancelConfirm ? (
                <button onClick={doCancel} disabled={cancelling}
                  className="px-4 rounded-pill bg-[#FEE2E2] py-2.5 text-xs font-bold text-[#991B1B] disabled:opacity-50">
                  {cancelling ? "…" : "Confirm?"}
                </button>
              ) : (
                <button onClick={() => setCancelConfirm(true)}
                  className="px-4 rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink-muted active:opacity-70">
                  Cancel
                </button>
              )}
            </>
          ) : (
            <>
              <button onClick={() => { setEditing(true); setCancelConfirm(false); setErr("") }}
                className="flex-1 rounded-pill border border-[#00AEED] py-2.5 text-xs font-semibold text-[#00AEED] active:opacity-70">
                Edit
              </button>
              {cancelConfirm ? (
                <button onClick={doCancel} disabled={cancelling}
                  className="px-4 rounded-pill bg-[#FEE2E2] py-2.5 text-xs font-bold text-[#991B1B] disabled:opacity-50">
                  {cancelling ? "…" : "Confirm?"}
                </button>
              ) : (
                <button onClick={() => setCancelConfirm(true)}
                  className="px-4 rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink-muted active:opacity-70">
                  Cancel
                </button>
              )}
              <button
                onClick={() => onCheckin(b.token)}
                disabled={checkingIn === b.token}
                className="flex-1 rounded-pill bg-brand-pink py-2.5 text-xs font-bold text-white active:opacity-70 disabled:opacity-50"
              >
                {checkingIn === b.token ? "Checking in…" : "Save & Check In"}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
