"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"

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

function BookingCard({ b, checkingIn, onCheckin }: {
  b: Booking
  checkingIn: string | null
  onCheckin: (token: string) => void
}) {
  const isPending = b.status === "pending_tenant"
  const checkinToday = isToday(b.checkin_date)

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
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#FEE2E2] text-[#991B1B]">
              Today!
            </span>
          )}
          {b.is_qr && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#EDE9FE] text-[#5B21B6]">
              QR
            </span>
          )}
          {isPending ? (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#FEF3C7] text-[#92400E]">
              Awaiting form
            </span>
          ) : (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-[#D1FAE5] text-[#065F46]">
              Form filled
            </span>
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

      {/* Action row */}
      <div className="flex gap-2 pt-1">
        {isPending ? (
          // Awaiting form — show resend link button only
          <a
            href={`${API_URL}/onboard/${b.token}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 text-center rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink active:opacity-70"
          >
            Copy form link →
          </a>
        ) : (
          // Form filled — full action row
          <>
            <a
              href={`${API_URL}/admin/onboarding#${b.token}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 text-center rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink active:opacity-70"
            >
              Review & Edit →
            </a>
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
    </div>
  )
}
