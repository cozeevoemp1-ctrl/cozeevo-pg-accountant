"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.getkozzy.com"
const ADMIN_PIN = process.env.NEXT_PUBLIC_ONBOARDING_PIN ?? "cozeevo2026"

type StayType = "monthly" | "daily"

const SHARING_OPTIONS = [
  { value: "", label: "Auto (from room)" },
  { value: "single", label: "Single" },
  { value: "double", label: "Double" },
  { value: "triple", label: "Triple" },
  { value: "premium", label: "Premium (solo in multi-bed)" },
]

function todayISO() {
  return new Date().toISOString().slice(0, 10)
}

function addDays(iso: string, days: number): string {
  const d = new Date(iso)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

function daysBetween(from: string, to: string): number {
  const a = new Date(from), b = new Date(to)
  return Math.max(Math.round((b.getTime() - a.getTime()) / 86400000), 1)
}

export default function NewOnboardingPage() {
  const router = useRouter()

  const [stayType, setStayType]         = useState<StayType>("monthly")
  const [roomNumber, setRoomNumber]     = useState("")
  const [sharingType, setSharingType]   = useState("")
  const [tenantPhone, setTenantPhone]   = useState("")
  const [checkinDate, setCheckinDate]   = useState(todayISO())

  // Monthly fields
  const [rent, setRent]                 = useState("")
  const [deposit, setDeposit]           = useState("")
  const [maintenance, setMaintenance]   = useState("")
  const [booking, setBooking]           = useState("")
  const [advanceMode, setAdvanceMode]   = useState<"cash" | "upi" | "bank">("cash")
  const [lockIn, setLockIn]             = useState("0")

  // Daily fields
  const [checkoutDate, setCheckoutDate] = useState(addDays(todayISO(), 1))
  const [dailyRate, setDailyRate]       = useState("")

  const [submitting, setSubmitting] = useState(false)
  const [error, setError]           = useState("")
  const [success, setSuccess]       = useState<{ token: string; phone: string } | null>(null)

  const numDays   = stayType === "daily" ? daysBetween(checkinDate, checkoutDate) : 0
  const totalCost = stayType === "daily" && dailyRate ? numDays * Number(dailyRate) : 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")

    if (!tenantPhone.trim()) { setError("Tenant phone is required"); return }
    if (stayType === "monthly" && !rent) { setError("Monthly rent is required"); return }
    if (stayType === "daily" && !dailyRate) { setError("Daily rate is required"); return }

    const body: Record<string, unknown> = {
      room_number:      roomNumber.trim(),
      sharing_type:     sharingType,
      tenant_phone:     tenantPhone.trim().replace(/\s+/g, ""),
      checkin_date:     checkinDate,
      stay_type:        stayType,
      agreed_rent:      stayType === "monthly" ? Number(rent) : Number(dailyRate) * numDays,
      security_deposit: Number(deposit || 0),
      maintenance_fee:  Number(maintenance || 0),
      booking_amount:   Number(booking || 0),
      advance_mode:     Number(booking || 0) > 0 ? advanceMode : "",
      lock_in_months:   Number(lockIn || 0),
      // daily
      checkout_date:    stayType === "daily" ? checkoutDate : "",
      num_days:         stayType === "daily" ? numDays : 0,
      daily_rate:       stayType === "daily" ? Number(dailyRate) : 0,
    }

    setSubmitting(true)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/create`, {
        method:  "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN },
        body:    JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error((err as { detail?: string }).detail ?? `Error ${res.status}`)
      }
      const data = await res.json()
      setSuccess({ token: data.token, phone: tenantPhone.trim() })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed")
    } finally {
      setSubmitting(false)
    }
  }

  // ── Success screen ────────────────────────────────────────────────────────
  if (success) {
    const formLink = `${API_URL}/onboard/${success.token}`
    return (
      <main className="min-h-screen bg-bg flex flex-col items-center justify-center px-6 gap-5">
        <div className="w-20 h-20 rounded-full bg-tile-green flex items-center justify-center text-4xl">✓</div>
        <div className="text-center">
          <h1 className="text-xl font-extrabold text-ink">Session Created!</h1>
          <p className="text-sm text-ink-muted mt-1">WhatsApp link sent to {success.phone}</p>
        </div>
        <div className="w-full max-w-sm bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-3">
          <p className="text-xs text-ink-muted font-medium">Tenant form link (also sent via WhatsApp):</p>
          <p className="text-xs font-mono text-brand-pink break-all bg-[#F6F5F0] rounded-tile px-3 py-2">{formLink}</p>
          <p className="text-xs text-ink-muted">After tenant fills the form, approve in the admin panel:</p>
          <a
            href={`${API_URL}/admin/onboarding`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-semibold text-brand-blue underline"
          >
            Open admin panel →
          </a>
        </div>
        <div className="flex gap-3 w-full max-w-sm">
          <button onClick={() => setSuccess(null)}
            className="flex-1 rounded-pill border border-[#E2DEDD] py-3 text-ink font-semibold text-sm">
            + New
          </button>
          <button onClick={() => router.push("/")}
            className="flex-1 rounded-pill bg-brand-pink py-3 text-white font-bold text-sm">
            ← Home
          </button>
        </div>
      </main>
    )
  }

  // ── Form ─────────────────────────────────────────────────────────────────
  return (
    <main className="min-h-screen bg-bg">
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
        <button onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
          aria-label="Back">←</button>
        <h1 className="text-lg font-extrabold text-ink">New Tenant Onboarding</h1>
      </div>

      <form onSubmit={handleSubmit} className="px-4 pt-4 pb-32 flex flex-col gap-4 max-w-lg mx-auto">

        {/* Stay type toggle */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Stay Type</p>
          <div className="flex gap-2">
            {(["monthly", "daily"] as StayType[]).map((t) => (
              <button key={t} type="button" onClick={() => setStayType(t)}
                className={`flex-1 rounded-pill py-2.5 text-sm font-bold border-2 transition-colors ${
                  stayType === t
                    ? "bg-brand-pink text-white border-brand-pink"
                    : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"
                }`}>
                {t === "monthly" ? "Regular" : "Day-wise"}
              </button>
            ))}
          </div>
        </div>

        {/* Room + sharing */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-3">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Room Details</p>
          <Field label="Room number" required>
            <input required value={roomNumber} onChange={e => setRoomNumber(e.target.value)}
              placeholder="e.g. 101"
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
          </Field>
          <Field label="Sharing type">
            <select value={sharingType} onChange={e => setSharingType(e.target.value)} className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink">
              {SHARING_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
        </div>

        {/* Tenant phone */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Tenant Contact</p>
          <Field label="Tenant phone (WhatsApp)" required>
            <input required value={tenantPhone} onChange={e => setTenantPhone(e.target.value)}
              placeholder="10-digit mobile number" type="tel"
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
          </Field>
        </div>

        {/* Dates */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-3">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Dates</p>
          <Field label="Check-in date" required>
            <input required type="date" value={checkinDate}
              onChange={e => { setCheckinDate(e.target.value); if (stayType === "daily") setCheckoutDate(addDays(e.target.value, 1)) }}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
          </Field>
          {stayType === "daily" && (
            <Field label="Check-out date" required>
              <input required type="date" value={checkoutDate} min={addDays(checkinDate, 1)}
                onChange={e => setCheckoutDate(e.target.value)}
                className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
            </Field>
          )}
        </div>

        {/* Financial — monthly */}
        {stayType === "monthly" && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-3">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Financials</p>
            <Field label="Monthly rent (₹)" required>
              <input required type="number" min="0" value={rent} onChange={e => setRent(e.target.value)}
                placeholder="e.g. 12000" className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
            </Field>
            <Field label="Security deposit (₹)">
              <input type="number" min="0" value={deposit} onChange={e => setDeposit(e.target.value)}
                placeholder="0" className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
            </Field>
            <Field label="Maintenance fee (₹/mo)">
              <input type="number" min="0" value={maintenance} onChange={e => setMaintenance(e.target.value)}
                placeholder="0" className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
            </Field>
            <Field label="Booking advance (₹)">
              <input type="number" min="0" value={booking} onChange={e => setBooking(e.target.value)}
                placeholder="0" className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
            </Field>
            {Number(booking) > 0 && (
              <Field label="Advance payment method">
                <div className="flex gap-2">
                  {(["cash", "upi", "bank"] as const).map((m) => (
                    <button key={m} type="button" onClick={() => setAdvanceMode(m)}
                      className={`flex-1 rounded-pill py-2 text-xs font-bold border-2 transition-colors ${
                        advanceMode === m
                          ? "bg-brand-pink text-white border-brand-pink"
                          : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"
                      }`}>
                      {m === "cash" ? "💵 Cash" : m === "upi" ? "📱 UPI" : "🏦 Bank"}
                    </button>
                  ))}
                </div>
              </Field>
            )}
            <Field label="Lock-in months">
              <input type="number" min="0" value={lockIn} onChange={e => setLockIn(e.target.value)}
                placeholder="0" className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
            </Field>
          </div>
        )}

        {/* Financial — daily */}
        {stayType === "daily" && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-3">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Financials</p>
            <Field label="Daily rate (₹/day)" required>
              <input required type="number" min="0" value={dailyRate} onChange={e => setDailyRate(e.target.value)}
                placeholder="e.g. 500" className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
            </Field>
            {dailyRate && numDays > 0 && (
              <div className="rounded-tile bg-tile-blue px-3 py-2 flex justify-between">
                <span className="text-xs text-ink-muted">{numDays} days × ₹{Number(dailyRate).toLocaleString("en-IN")}</span>
                <span className="text-xs font-bold text-brand-blue">₹{totalCost.toLocaleString("en-IN")} total</span>
              </div>
            )}
            <Field label="Booking advance (₹)">
              <input type="number" min="0" value={booking} onChange={e => setBooking(e.target.value)}
                placeholder="0" className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2.5 text-sm text-ink outline-none focus:border-brand-pink" />
            </Field>
            {Number(booking) > 0 && (
              <Field label="Advance payment method">
                <div className="flex gap-2">
                  {(["cash", "upi", "bank"] as const).map((m) => (
                    <button key={m} type="button" onClick={() => setAdvanceMode(m)}
                      className={`flex-1 rounded-pill py-2 text-xs font-bold border-2 transition-colors ${
                        advanceMode === m
                          ? "bg-brand-pink text-white border-brand-pink"
                          : "bg-[#F6F5F0] text-ink-muted border-[#E0DDD8]"
                      }`}>
                      {m === "cash" ? "💵 Cash" : m === "upi" ? "📱 UPI" : "🏦 Bank"}
                    </button>
                  ))}
                </div>
              </Field>
            )}
          </div>
        )}

        {error && <p className="text-xs text-status-warn font-medium text-center">{error}</p>}
      </form>

      {/* Sticky CTA */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-28 pt-3 bg-bg border-t border-[#F0EDE9]">
        <button
          onClick={handleSubmit as unknown as React.MouseEventHandler}
          disabled={submitting}
          className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80 disabled:opacity-40"
        >
          {submitting ? "Creating session…" : "Create & Send WhatsApp Link →"}
        </button>
      </div>
    </main>
  )
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-ink-muted">
        {label}{required && <span className="text-status-due ml-0.5">*</span>}
      </label>
      {children}
    </div>
  )
}
