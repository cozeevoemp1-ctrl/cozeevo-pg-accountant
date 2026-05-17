"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { useRouter } from "next/navigation"
import { updateBookingSession, cancelBookingSession } from "@/lib/api"
import { supabase } from "@/lib/supabase"

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
  booking_amount?: number
  daily_rate?: number
  stay_type?: string
  tenancy_id?: number
  expires_at?: string
  expired_ago?: string
  is_qr?: boolean
  notes?: string
}

function fmtDate(iso: string) {
  if (!iso) return "—"
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
}

function fmtRent(n?: number) {
  if (!n) return "—"
  return `₹${n.toLocaleString("en-IN")}/mo`
}

function proratedRent(rent: number, checkinIso: string): number {
  const d = new Date(checkinIso)
  const day = d.getDate()
  if (day === 1) return rent
  const daysInMonth = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()
  return Math.floor(rent * (daysInMonth - day + 1) / daysInMonth)
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
  const [filter, setFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState<"all" | "pending_review" | "pending_tenant" | "expired">("all")

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/admin/pending`, { headers: pinHeaders() })
      if (!res.ok) throw new Error(`Load failed: ${res.status}`)
      const d = await res.json()
      // Show pending_review, pending_tenant (awaiting form), and expired
      const all = (d.sessions as Booking[]).filter(
        (s) => s.status === "pending_review" || s.status === "pending_tenant" || s.status === "expired"
      )
      // Sort: check-in today first, then pending_review → pending_tenant → expired, then by date
      const statusOrder: Record<string, number> = { pending_review: 0, pending_tenant: 1, expired: 2 }
      all.sort((a, b) => {
        const aToday = isToday(a.checkin_date) ? 0 : 1
        const bToday = isToday(b.checkin_date) ? 0 : 1
        if (aToday !== bToday) return aToday - bToday
        const so = (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3)
        if (so !== 0) return so
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

  async function saveAndCheckin(token: string, collection?: {
    collected_rent_dues: number
    rent_dues_mode: string
    collected_deposit_dues: number
  }) {
    if (!confirm("Save details and check in this tenant now? Their status will become Active.")) return
    setCheckingIn(token)
    setError("")
    try {
      const res = await fetch(`${API_URL}/api/onboarding/${token}/approve`, {
        method: "POST",
        headers: pinHeaders(),
        body: JSON.stringify({
          instant_checkin: true, approved_by_phone: "", overrides: {},
          ...(collection ?? {}),
        }),
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

  const q = filter.trim().toLowerCase()
  const match = (b: Booking) =>
    !q ||
    (b.tenant_name || "").toLowerCase().includes(q) ||
    (b.room || "").toLowerCase().includes(q)

  const statusMatch = (b: Booking) => statusFilter === "all" || b.status === statusFilter
  const ready    = bookings.filter((b) => b.status === "pending_review" && match(b) && statusMatch(b))
  const awaiting = bookings.filter((b) => b.status === "pending_tenant" && match(b) && statusMatch(b))
  const expired  = bookings.filter((b) => b.status === "expired"        && match(b) && statusMatch(b))

  return (
    <main className="min-h-screen bg-bg overflow-y-auto" style={{ WebkitOverflowScrolling: "touch" }}>
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
        <input
          type="text"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Name or room…"
          className="w-full rounded-xl border border-[#E5E1DC] bg-bg px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:ring-2 focus:ring-brand-pink/40"
        />

        {/* Totals summary + filter chips */}
        {!loading && bookings.length > 0 && (
          <div className="flex gap-2 flex-wrap">
            {[
              { label: "All", count: bookings.length, key: "all" as const, color: "bg-[#F6F5F0] text-ink border-[#E0DDD8]", activeColor: "bg-ink text-white border-ink" },
              { label: "Ready", count: bookings.filter(b => b.status === "pending_review").length, key: "pending_review" as const, color: "bg-[#D1FAE5] text-[#065F46] border-[#6EE7B7]", activeColor: "bg-[#065F46] text-white border-[#065F46]" },
              { label: "Awaiting form", count: bookings.filter(b => b.status === "pending_tenant").length, key: "pending_tenant" as const, color: "bg-[#FEF3C7] text-[#92400E] border-[#FDE68A]", activeColor: "bg-[#92400E] text-white border-[#92400E]" },
              { label: "Expired", count: bookings.filter(b => b.status === "expired").length, key: "expired" as const, color: "bg-[#FEE2E2] text-[#991B1B] border-[#FECACA]", activeColor: "bg-[#991B1B] text-white border-[#991B1B]" },
            ].filter(s => s.count > 0 || s.key === "all").map(s => (
              <button
                key={s.key}
                onClick={() => setStatusFilter(s.key)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border text-xs font-semibold transition-colors ${statusFilter === s.key ? s.activeColor : s.color}`}
              >
                <span className="text-base font-extrabold leading-none">{s.count}</span>
                <span className="font-medium opacity-90">{s.label}</span>
              </button>
            ))}
          </div>
        )}

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

            {/* Pre-booked — link sent, form not filled yet */}
            {awaiting.length > 0 && (
              <>
                <p className="text-xs text-ink-muted font-semibold uppercase tracking-wide mt-2">
                  {awaiting.length} pre-booked
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

            {/* Expired — link expired, tenant never filled */}
            {expired.length > 0 && (
              <>
                <p className="text-xs text-ink-muted font-semibold uppercase tracking-wide mt-2">
                  {expired.length} link expired
                </p>
                {expired.map((b) => (
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

function ModeToggle({ mode, setMode }: { mode: "cash" | "upi"; setMode: (m: "cash" | "upi") => void }) {
  return (
    <div className="flex gap-1 mt-1">
      {(["cash", "upi"] as const).map((m) => (
        <button key={m} onClick={() => setMode(m)}
          className={`px-2 py-0.5 rounded text-[9px] font-bold border transition-colors ${mode === m ? "bg-brand-pink text-white border-brand-pink" : "border-[#E0DDD8] text-ink-muted"}`}>
          {m.toUpperCase()}
        </button>
      ))}
    </div>
  )
}

function BookingCard({ b, checkingIn, onCheckin, onReload }: {
  b: Booking
  checkingIn: string | null
  onCheckin: (token: string, collection?: { collected_rent_dues: number; rent_dues_mode: string; collected_deposit_dues: number }) => void
  onReload: () => void
}) {
  const isPending = b.status === "pending_tenant"
  const isExpired = b.status === "expired"
  const isReady   = b.status === "pending_review"
  const checkinToday = isToday(b.checkin_date)

  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [cancelConfirm, setCancelConfirm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [resending, setResending] = useState(false)
  const [err, setErr] = useState("")

  // Edit fields
  const [editRoom, setEditRoom] = useState(b.room || "")
  const [editCheckin, setEditCheckin] = useState(b.checkin_date?.slice(0, 10) || "")
  const [editRent, setEditRent] = useState(String(b.agreed_rent || ""))
  const [editMaint, setEditMaint] = useState(String(b.maintenance_fee || 5000))
  const [editDeposit, setEditDeposit] = useState(String(b.security_deposit || b.agreed_rent || ""))
  const [editPhone, setEditPhone] = useState(b.tenant_phone || "")
  const [editName, setEditName] = useState(b.tenant_name || "")

  // Collection at check-in
  const proRata = b.agreed_rent && b.checkin_date ? proratedRent(b.agreed_rent, b.checkin_date) : 0
  const [collectRentDues, setCollectRentDues] = useState("")
  const [rentDuesMode, setRentDuesMode] = useState<"cash" | "upi">("cash")
  const [collectDepositDues, setCollectDepositDues] = useState("")
  const [totalDues, setTotalDues] = useState(0)  // frozen at first pre-fill, never changes
  const prefillDone = useRef(false)
  const defaultRentDues = useRef("")
  const defaultDepositDues = useRef("")

  // Pre-fill outstanding dues once on mount — never overwrites user edits
  useEffect(() => {
    if (prefillDone.current || b.status !== "pending_review") return

    if (b.tenancy_id) {
      supabase().auth.getSession().then(({ data }) => {
        const token = data.session?.access_token
        if (!token) return
        fetch(`${API_URL}/api/v2/app/tenants/${b.tenancy_id}/dues`, {
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        })
          .then((r) => r.ok ? r.json() : null)
          .then((d) => {
            if (!d) return
            const rentDue = d.dues ?? 0
            const depDue = d.deposit_due ?? 0
            if (rentDue > 0) { const v = String(Math.round(rentDue)); setCollectRentDues(v); defaultRentDues.current = v }
            if (depDue > 0) { const v = String(Math.round(depDue)); setCollectDepositDues(v); defaultDepositDues.current = v }
            setTotalDues(rentDue + depDue)
            prefillDone.current = true
          })
          .catch(() => {})
      })
    } else {
      // Advance (booking_amount) deducted from deposit, not rent
      const rentDue = proRata
      const depositDue = Math.max(0, (b.security_deposit || 0) - (b.booking_amount || 0))
      if (rentDue > 0) { const v = String(rentDue); setCollectRentDues(v); defaultRentDues.current = v }
      if (depositDue > 0) { const v = String(depositDue); setCollectDepositDues(v); defaultDepositDues.current = v }
      setTotalDues(rentDue + depositDue)
      prefillDone.current = true
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

  async function doResend() {
    setResending(true); setErr("")
    try {
      const res = await fetch(`${API_URL}/api/onboarding/admin/${b.token}/resend`, {
        method: "POST", headers: pinHeaders(),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error((d as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      onReload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Resend failed")
    } finally {
      setResending(false)
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
          {isExpired ? (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#FEE2E2] text-[#991B1B]">
              Link expired{b.expired_ago ? ` · ${b.expired_ago}` : ""}
            </span>
          ) : isPending ? (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#FEF3C7] text-[#92400E]">Awaiting form</span>
          ) : (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#D1FAE5] text-[#065F46]">Form filled</span>
          )}
        </div>
      </div>

      {/* Details row */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-[#F6F5F0] rounded-tile px-2.5 py-2">
          <p className="text-[9px] text-ink-muted font-semibold uppercase tracking-wide">Room</p>
          <p className="text-xs font-bold text-ink mt-0.5">{b.room || "TBD"}</p>
        </div>
        <div className="bg-[#F6F5F0] rounded-tile px-2.5 py-2">
          <p className="text-[9px] text-ink-muted font-semibold uppercase tracking-wide">Check-in</p>
          <p className="text-xs font-bold text-ink mt-0.5">{fmtDate(b.checkin_date)}</p>
        </div>
        <div className="bg-[#F6F5F0] rounded-tile px-2.5 py-2">
          <p className="text-[9px] text-ink-muted font-semibold uppercase tracking-wide">Rent</p>
          {b.stay_type === "daily" ? (
            <>
              <p className="text-xs font-bold text-ink mt-0.5">
                {b.daily_rate ? `₹${b.daily_rate.toLocaleString("en-IN")}/day` : "—"}
              </p>
              {b.booking_amount ? (
                <p className="text-[9px] text-brand-pink font-semibold mt-0.5">
                  Adv: ₹{b.booking_amount.toLocaleString("en-IN")}
                </p>
              ) : null}
            </>
          ) : (
            <>
              <p className="text-xs font-bold text-ink mt-0.5">{fmtRent(b.agreed_rent)}</p>
              {b.agreed_rent && b.checkin_date && new Date(b.checkin_date).getDate() !== 1 && (
                <p className="text-[9px] text-brand-pink font-semibold mt-0.5">
                  1st mo: ₹{proratedRent(b.agreed_rent, b.checkin_date).toLocaleString("en-IN")}
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {/* Admin notes */}
      {b.notes && !editing && (
        <div className="flex items-start gap-1.5 bg-[#FFFBEB] border border-[#FDE68A] rounded-lg px-2.5 py-2 -mt-1">
          <span className="text-[10px] font-bold text-[#92400E] flex-shrink-0 mt-0.5">NOTE</span>
          <p className="text-[11px] text-[#78350F] leading-snug">{b.notes}</p>
        </div>
      )}

      {/* Pre-booked info line — show when booked and when link expires */}
      {isPending && !editing && (
        <p className="text-[10px] text-ink-muted -mt-1">
          Booked {b.created_at ? new Date(b.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—"}
          {b.expires_at ? ` · Link expires ${new Date(b.expires_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : ""}
        </p>
      )}

      {/* Expand toggle — only for ready-to-check-in cards */}
      {isReady && !editing && (
        <button
          onClick={() => setExpanded(v => !v)}
          className="text-[11px] font-semibold text-brand-pink text-left -mt-1"
        >
          {expanded ? "▲ Hide details" : "▼ View details & collect"}
        </button>
      )}

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
              ...(b.stay_type !== "daily" ? [{ label: "Maintenance (₹)", val: editMaint, set: setEditMaint, type: "number", placeholder: "5000" }] : []),
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

      {/* Collection at check-in (form-filled, expanded only) */}
      {!editing && isReady && expanded && (
        <div className="border-t border-[#F0EDE9] pt-3 flex flex-col gap-2">
          <p className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">Agreed terms</p>

          {/* Reference info — display only */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[#F6F5F0] rounded-tile px-2.5 py-2">
              <p className="text-[9px] text-ink-muted font-semibold uppercase tracking-wide">1st Month Rent</p>
              <p className="text-xs font-bold text-ink mt-0.5">
                {proRata ? `₹${proRata.toLocaleString("en-IN")}` : "—"}
              </p>
              <p className="text-[9px] text-ink-muted">Reference only</p>
            </div>
            <div className="bg-[#F6F5F0] rounded-tile px-2.5 py-2">
              <p className="text-[9px] text-ink-muted font-semibold uppercase tracking-wide">Advance Paid</p>
              <p className="text-xs font-bold text-ink mt-0.5">
                {b.booking_amount ? `₹${b.booking_amount.toLocaleString("en-IN")}` : "—"}
              </p>
              <p className="text-[9px] text-ink-muted">Auto-recorded · UPI</p>
            </div>
          </div>

          {/* Deposit — reference only, always UPI */}
          <div className="bg-[#F6F5F0] rounded-tile px-2.5 py-2">
            <p className="text-[9px] text-ink-muted font-semibold uppercase tracking-wide">Deposit</p>
            <p className="text-xs font-bold text-ink mt-0.5">
              {b.security_deposit ? `₹${b.security_deposit.toLocaleString("en-IN")}` : "—"}
            </p>
            <p className="text-[9px] text-ink-muted">Auto-recorded · UPI</p>
          </div>

          {/* Against dues — split into rent (selectable mode) + deposit (always UPI) */}
          <div className="flex flex-col gap-1.5">
            <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">Collected at check-in</p>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Rent (₹)</label>
                <input type="number" inputMode="decimal" value={collectRentDues} onChange={(e) => setCollectRentDues(e.target.value)}
                  onBlur={() => { if (collectRentDues === "" && defaultRentDues.current) setCollectRentDues(defaultRentDues.current) }}
                  className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink"
                />
                <ModeToggle mode={rentDuesMode} setMode={setRentDuesMode} />
              </div>
              <div>
                <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Deposit (₹)</label>
                <input type="number" inputMode="decimal" value={collectDepositDues} onChange={(e) => setCollectDepositDues(e.target.value)}
                  onBlur={() => { if (collectDepositDues === "" && defaultDepositDues.current) setCollectDepositDues(defaultDepositDues.current) }}
                  className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink"
                />
                <span className="text-[9px] font-bold text-[#00AEED] px-2 py-0.5 rounded border border-[#00AEED]/30 mt-1 inline-block">UPI</span>
              </div>
            </div>
          </div>

          {/* Collection summary */}
          {(() => {
            const rd = parseFloat(collectRentDues) || 0
            const dd = parseFloat(collectDepositDues) || 0
            const collecting = rd + dd
            const remaining = Math.max(0, totalDues - collecting)
            return (
              <div className="rounded-tile bg-[#F6F5F0] px-3 py-2.5 flex flex-col gap-1">
                {[
                  { label: "Total outstanding", value: totalDues, muted: false, warn: false },
                  { label: "Collecting now",     value: collecting, muted: false, warn: false },
                  { label: "Remaining after",    value: remaining, muted: true, warn: remaining > 0 },
                ].map(({ label, value, muted, warn }) => (
                  <div key={label} className="flex items-center justify-between">
                    <span className="text-[11px] text-ink-muted">{label}</span>
                    <span className={`text-[11px] font-bold ${warn ? "text-status-due" : muted ? "text-ink-muted" : "text-ink"}`}>
                      ₹{value.toLocaleString("en-IN")}
                    </span>
                  </div>
                ))}
              </div>
            )
          })()}
        </div>
      )}

      {/* Action row */}
      {!editing && (
        <div className="flex gap-2 pt-1 flex-wrap">
          {isExpired ? (
            /* Expired: Regenerate & send + Edit + Cancel */
            <>
              <button onClick={doResend} disabled={resending}
                className="flex-1 rounded-pill bg-brand-pink py-2.5 text-xs font-bold text-white disabled:opacity-50">
                {resending ? "Sending…" : "Regenerate & send →"}
              </button>
              <button onClick={() => { setEditing(true); setCancelConfirm(false); setErr("") }}
                className="px-4 rounded-pill border border-[#00AEED] py-2.5 text-xs font-semibold text-[#00AEED]">
                Edit
              </button>
              {cancelConfirm ? (
                <button onClick={doCancel} disabled={cancelling}
                  className="px-4 rounded-pill bg-[#FEE2E2] py-2.5 text-xs font-bold text-[#991B1B] disabled:opacity-50">
                  {cancelling ? "…" : "Confirm?"}
                </button>
              ) : (
                <button onClick={() => setCancelConfirm(true)}
                  className="px-3 rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink-muted">
                  Cancel
                </button>
              )}
            </>
          ) : isPending ? (
            /* Awaiting form: Copy link + Resend + Edit + Cancel */
            <>
              <a href={`${API_URL}/onboard/${b.token}`} target="_blank" rel="noopener noreferrer"
                className="flex-1 text-center rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink active:opacity-70">
                Copy link →
              </a>
              <button onClick={doResend} disabled={resending}
                className="px-3 rounded-pill border border-brand-pink py-2.5 text-xs font-semibold text-brand-pink disabled:opacity-50">
                {resending ? "…" : "Resend"}
              </button>
              <button onClick={() => { setEditing(true); setCancelConfirm(false); setErr("") }}
                className="px-3 rounded-pill border border-[#00AEED] py-2.5 text-xs font-semibold text-[#00AEED]">
                Edit
              </button>
              {cancelConfirm ? (
                <button onClick={doCancel} disabled={cancelling}
                  className="px-3 rounded-pill bg-[#FEE2E2] py-2.5 text-xs font-bold text-[#991B1B] disabled:opacity-50">
                  {cancelling ? "…" : "Sure?"}
                </button>
              ) : (
                <button onClick={() => setCancelConfirm(true)}
                  className="px-3 rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink-muted">
                  Cancel
                </button>
              )}
            </>
          ) : (
            /* Form filled: Edit + Cancel + Check In (expand to collect first) */
            <>
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
              {expanded ? (
                <button
                  onClick={() => onCheckin(b.token, {
                    collected_rent_dues: parseFloat(collectRentDues) || 0,
                    rent_dues_mode: rentDuesMode,
                    collected_deposit_dues: parseFloat(collectDepositDues) || 0,
                  })}
                  disabled={checkingIn === b.token}
                  className="flex-1 rounded-pill bg-brand-pink py-2.5 text-xs font-bold text-white active:opacity-70 disabled:opacity-50"
                >
                  {checkingIn === b.token ? "Checking in…" : "Save & Check In"}
                </button>
              ) : (
                <button
                  onClick={() => setExpanded(true)}
                  className="flex-1 rounded-pill bg-brand-pink py-2.5 text-xs font-bold text-white active:opacity-70"
                >
                  Check In →
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
