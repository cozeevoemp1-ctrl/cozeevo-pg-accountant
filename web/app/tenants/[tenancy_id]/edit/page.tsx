"use client"

import { useState, useEffect } from "react"
import { useRouter, useParams } from "next/navigation"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
import { getTenantDues, patchTenant, TenantDues, PatchTenantBody } from "@/lib/api"

function formatDate(iso: string | null): string {
  if (!iso) return ""
  return iso.slice(0, 10)
}

export default function EditTenantPage() {
  const router = useRouter()
  const params = useParams()
  const tenancyId = Number(params.tenancy_id)

  const [original, setOriginal] = useState<TenantDues | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState("")

  // Form fields
  const [name, setName] = useState("")
  const [phone, setPhone] = useState("")
  const [email, setEmail] = useState("")
  const [roomNumber, setRoomNumber] = useState("")
  const [agreedRent, setAgreedRent] = useState("")
  const [securityDeposit, setSecurityDeposit] = useState("")
  const [maintenanceFee, setMaintenanceFee] = useState("")
  const [lockIn, setLockIn] = useState("")
  const [expectedCheckout, setExpectedCheckout] = useState("")
  const [noticeDate, setNoticeDate] = useState("")
  const [notes, setNotes] = useState("")

  // Room occupancy check
  const [roomInfo, setRoomInfo] = useState<{ occupied: number; max_occupancy: number; is_full: boolean; occupants: string[] } | null>(null)
  const [roomInfoLoading, setRoomInfoLoading] = useState(false)
  const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.getkozzy.com"
  const ADMIN_PIN = process.env.NEXT_PUBLIC_ONBOARDING_PIN ?? "cozeevo2026"

  async function checkRoomOccupancy(room: string) {
    if (!room.trim() || room.trim() === original?.room_number) { setRoomInfo(null); return }
    setRoomInfoLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/room-lookup/${encodeURIComponent(room.trim())}`, {
        headers: { "X-Admin-Pin": ADMIN_PIN }
      })
      if (!res.ok) { setRoomInfo(null); return }
      setRoomInfo(await res.json())
    } catch { setRoomInfo(null) }
    finally { setRoomInfoLoading(false) }
  }

  const [showConfirm, setShowConfirm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)
  const [prorateChoice, setProrateChoice] = useState<"full" | "prorated">("full")

  useEffect(() => {
    if (!tenancyId) return
    getTenantDues(tenancyId)
      .then((d) => {
        setOriginal(d)
        setName(d.name)
        setPhone(d.phone)
        setEmail(d.email || "")
        setRoomNumber(d.room_number)
        setAgreedRent(String(d.rent))
        setSecurityDeposit(String(d.security_deposit))
        setMaintenanceFee(String(d.maintenance_fee))
        setLockIn(String(d.lock_in_months))
        setNotes(d.notes || "")
        setExpectedCheckout(formatDate(d.expected_checkout))
        setNoticeDate(formatDate(d.notice_date))
      })
      .catch(() => setFetchError("Could not load tenant details"))
      .finally(() => setLoading(false))
  }, [tenancyId])

  function buildChanges(): PatchTenantBody {
    if (!original) return {}
    const changes: PatchTenantBody = {}
    if (name.trim() && name.trim() !== original.name) changes.name = name.trim()
    if (phone.trim() && phone.trim() !== original.phone) changes.phone = phone.trim()
    if (roomNumber.trim() && roomNumber.trim() !== original.room_number) changes.room_number = roomNumber.trim()
    if (email.trim()) changes.email = email.trim()
    if (agreedRent && Number(agreedRent) !== original.rent)
      changes.agreed_rent = Number(agreedRent)
    if (securityDeposit && Number(securityDeposit) !== original.security_deposit)
      changes.security_deposit = Number(securityDeposit)
    if (maintenanceFee && Number(maintenanceFee) !== original.maintenance_fee)
      changes.maintenance_fee = Number(maintenanceFee)
    if (lockIn && Number(lockIn) !== original.lock_in_months)
      changes.lock_in_months = Number(lockIn)
    // Notice fields — include if changed or being cleared
    const origNotice = formatDate(original.notice_date)
    const origCheckout = formatDate(original.expected_checkout)
    if (noticeDate !== origNotice) changes.notice_date = noticeDate || null
    if (expectedCheckout !== origCheckout) changes.expected_checkout = expectedCheckout || null
    // Notes: send if changed from original (overwrites — user sees current value pre-filled)
    if (notes !== (original.notes || "")) changes.tenancy_notes = notes
    // Proration — only send when rent or room is actually changing
    const rentOrRoomChanged = changes.agreed_rent !== undefined || changes.room_number !== undefined
    if (rentOrRoomChanged && proratedInfo) {
      changes.prorate_this_month = prorateChoice === "prorated"
    }
    return changes
  }

  function buildConfirmFields() {
    const changes = buildChanges()
    const fields: { label: string; value: string; highlight?: boolean }[] = []
    if (changes.name) fields.push({ label: "Name", value: changes.name })
    if (changes.phone) fields.push({ label: "Phone", value: changes.phone })
    if (changes.email) fields.push({ label: "Email", value: changes.email })
    if (changes.room_number) {
      fields.push({ label: "New Room", value: changes.room_number, highlight: true })
      if (proratedInfo && changes.agreed_rent === undefined) {
        // Room-only change: show the chosen this-month amount
        const monthName = new Date().toLocaleString("en-IN", { month: "short" })
        const thisMonthAmt = prorateChoice === "prorated"
          ? `₹${proratedInfo.amount.toLocaleString("en-IN")} prorated (${proratedInfo.remaining}/${proratedInfo.daysInMonth} days)`
          : `₹${Number(agreedRent).toLocaleString("en-IN")} full month`
        fields.push({ label: `${monthName} this month`, value: thisMonthAmt, highlight: true })
      }
    }
    if (changes.agreed_rent !== undefined) {
      fields.push({ label: "Agreed Rent", value: `₹${Number(changes.agreed_rent).toLocaleString("en-IN")}`, highlight: true })
      if (proratedInfo) {
        const monthName = new Date().toLocaleString("en-IN", { month: "short" })
        const thisMonthAmt = prorateChoice === "prorated"
          ? `₹${proratedInfo.amount.toLocaleString("en-IN")} prorated (${proratedInfo.remaining}/${proratedInfo.daysInMonth} days)`
          : `₹${Number(changes.agreed_rent).toLocaleString("en-IN")} full month`
        fields.push({ label: `${monthName} this month`, value: thisMonthAmt })
      }
    }
    if (changes.security_deposit !== undefined)
      fields.push({ label: "Security Deposit", value: `₹${Number(changes.security_deposit).toLocaleString("en-IN")}` })
    if (changes.maintenance_fee !== undefined)
      fields.push({ label: "Maintenance Fee", value: `₹${Number(changes.maintenance_fee).toLocaleString("en-IN")}` })
    if (changes.lock_in_months !== undefined)
      fields.push({ label: "Lock-in Months", value: String(changes.lock_in_months) })
    if (changes.notice_date !== undefined)
      fields.push({ label: "Notice date", value: changes.notice_date ?? "Cleared" })
    if (changes.expected_checkout !== undefined)
      fields.push({ label: "Expected checkout", value: changes.expected_checkout ?? "Cleared" })
    if (changes.tenancy_notes !== undefined) fields.push({ label: "Notes", value: changes.tenancy_notes || "(cleared)" })
    return fields
  }

  function handleReview() {
    setError("")
    const changes = buildChanges()
    if (Object.keys(changes).length === 0) {
      setError("No changes to save")
      return
    }
    setShowConfirm(true)
  }

  async function handleConfirm() {
    const changes = buildChanges()
    if (Object.keys(changes).length === 0) return
    setSubmitting(true)
    setError("")
    try {
      await patchTenant(tenancyId, changes)
      setShowConfirm(false)
      setSuccess(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  const depositEligible = noticeDate ? new Date(noticeDate).getDate() <= 5 : null
  const rentChanged = original && agreedRent && Number(agreedRent) !== original.rent
  const roomChanged = original && roomNumber.trim() && roomNumber.trim().toUpperCase() !== original.room_number.toUpperCase()

  // Prorated calc — shown whenever rent or room changes mid-month
  const proratedInfo = (() => {
    if (!rentChanged && !roomChanged) return null
    const rent = Number(agreedRent) || 0
    if (!rent) return null
    const today = new Date()
    const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate()
    const remaining = daysInMonth - today.getDate() + 1
    const amount = Math.floor(rent * remaining / daysInMonth)
    return { amount, remaining, daysInMonth }
  })()

  if (loading) {
    return (
      <main className="min-h-screen bg-bg">
        <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
          <button onClick={() => router.back()} className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold">←</button>
          <h1 className="text-lg font-extrabold text-ink">Edit Tenant</h1>
        </div>
        <div className="px-4 pt-6 flex flex-col gap-3 max-w-lg mx-auto">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="bg-surface rounded-card border border-[#F0EDE9] h-14 animate-pulse" />
          ))}
        </div>
      </main>
    )
  }

  if (fetchError) {
    return (
      <main className="min-h-screen bg-bg flex flex-col items-center justify-center px-6 gap-4">
        <p className="text-sm text-status-warn text-center">{fetchError}</p>
        <button onClick={() => router.back()} className="rounded-pill border border-[#E2DEDD] px-6 py-3 text-sm font-semibold text-ink">
          ← Go Back
        </button>
      </main>
    )
  }

  if (success) {
    return (
      <main className="min-h-screen bg-bg flex flex-col items-center px-6 gap-5 pt-16 pb-32">
        <div className="fixed top-0 left-0 right-0 z-10 flex items-center gap-3 px-5 pt-10 pb-3 bg-bg border-b border-[#F0EDE9]">
          <button onClick={() => router.push("/tenants")} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center text-ink-muted font-bold" aria-label="Back">←</button>
          <span className="text-base font-extrabold text-ink">Changes Saved</span>
        </div>
        <div className="w-20 h-20 rounded-full bg-tile-green flex items-center justify-center">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#22C55E" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
        <div className="text-center">
          <h1 className="text-xl font-extrabold text-ink">Changes Saved</h1>
          <p className="text-sm text-ink-muted mt-1">{original?.name} updated successfully</p>
        </div>
        <button
          onClick={() => router.push("/tenants")}
          className="rounded-pill bg-brand-pink px-8 py-3 text-white font-bold text-sm"
        >
          ← Back to Manage
        </button>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
          aria-label="Back"
        >
          ←
        </button>
        <div>
          <h1 className="text-lg font-extrabold text-ink">Edit Tenant</h1>
          {original && (
            <p className="text-xs text-ink-muted">Room {original.room_number} · {original.building_code}</p>
          )}
        </div>
      </div>

      <div className="px-4 pt-4 pb-52 flex flex-col gap-4 max-w-lg mx-auto">
        {/* Room reassignment */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-2">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">Room</p>
          <input
            type="text"
            value={roomNumber}
            onChange={(e) => { setRoomNumber(e.target.value); setRoomInfo(null) }}
            onBlur={(e) => checkRoomOccupancy(e.target.value)}
            placeholder="e.g. 219"
            className={`w-full rounded-pill border bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors ${roomInfo?.is_full ? "border-status-warn" : "border-[#E2DEDD]"}`}
          />
          {roomInfoLoading && <p className="text-[10px] text-ink-muted">Checking occupancy…</p>}
          {roomInfo && !roomInfoLoading && (
            roomInfo.is_full ? (
              <div className="rounded-tile bg-[#FFF0F0] border border-status-warn px-3 py-2">
                <p className="text-xs font-bold text-status-warn">Room {roomNumber} is full ({roomInfo.occupied}/{roomInfo.max_occupancy} beds)</p>
                {roomInfo.occupants.length > 0 && (
                  <p className="text-[10px] text-ink-muted mt-0.5">Current: {roomInfo.occupants.join(", ")}</p>
                )}
              </div>
            ) : (
              <p className="text-[10px] text-status-ok font-semibold">
                Room {roomNumber}: {roomInfo.occupied}/{roomInfo.max_occupancy} beds occupied — space available
              </p>
            )
          )}
        </div>

        {/* Personal details */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-4">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Personal Details</p>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Phone</label>
            <input
              type="text"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="optional"
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
          </div>
        </div>

        {/* Financial */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-4">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Financials</p>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Agreed Rent (₹/mo)</label>
            <input
              type="text"
              inputMode="numeric"
              value={agreedRent}
              onChange={(e) => setAgreedRent(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
            {rentChanged && (
              <p className="text-xs text-status-warn mt-1.5 px-1">
                Rent change will be logged in revision history
              </p>
            )}
          </div>

          {/* Proration toggle — shown whenever rent or room changes */}
          {proratedInfo && (
            <div className="rounded-tile border border-[#E2DEDD] bg-[#FAFAF8] p-3 flex flex-col gap-2">
              <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">
                This month ({new Date().toLocaleString("en-IN", { month: "long" })}) — {proratedInfo.remaining} of {proratedInfo.daysInMonth} days remaining
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setProrateChoice("full")}
                  className={`flex-1 rounded-pill py-2.5 text-xs font-bold border-2 transition-colors ${
                    prorateChoice === "full"
                      ? "bg-brand-pink text-white border-brand-pink"
                      : "bg-bg text-ink-muted border-[#E0DDD8]"
                  }`}
                >
                  Full ₹{Number(agreedRent).toLocaleString("en-IN")}
                </button>
                <button
                  type="button"
                  onClick={() => setProrateChoice("prorated")}
                  className={`flex-1 rounded-pill py-2.5 text-xs font-bold border-2 transition-colors ${
                    prorateChoice === "prorated"
                      ? "bg-brand-pink text-white border-brand-pink"
                      : "bg-bg text-ink-muted border-[#E0DDD8]"
                  }`}
                >
                  Prorated ₹{proratedInfo.amount.toLocaleString("en-IN")}
                </button>
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Security Deposit (₹)</label>
            <input
              type="text"
              inputMode="numeric"
              value={securityDeposit}
              onChange={(e) => setSecurityDeposit(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Maintenance Fee (₹)</label>
            <input
              type="text"
              inputMode="numeric"
              value={maintenanceFee}
              onChange={(e) => setMaintenanceFee(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
          </div>
        </div>

        {/* Stay details */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-4">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Stay Details</p>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Lock-in Months</label>
            <input
              type="text"
              inputMode="numeric"
              value={lockIn}
              onChange={(e) => setLockIn(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Notes</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Any notes about this tenant or tenancy…"
              className="w-full rounded-[16px] border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors resize-none"
            />
          </div>
        </div>

        {/* Notice */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-4">
          <div className="flex justify-between items-center">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Notice</p>
            {noticeDate && (
              <span className={`text-[10px] font-bold px-2.5 py-1 rounded-pill ${
                depositEligible
                  ? "bg-[#D1FAE5] text-[#065F46]"
                  : "bg-[#FEE2E2] text-[#991B1B]"
              }`}>
                {depositEligible ? "Deposit Refundable" : "Deposit Forfeited"}
              </span>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Notice date</label>
            <input
              type="date"
              value={noticeDate}
              onChange={(e) => setNoticeDate(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
            {noticeDate && (
              <p className="text-[10px] text-ink-muted mt-1 px-1">
                {depositEligible
                  ? "Given on day ≤ 5 — deposit refundable, exits end of this month"
                  : "Given after day 5 — deposit forfeited, exits end of next month"}
              </p>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Expected checkout</label>
            <input
              type="date"
              value={expectedCheckout}
              onChange={(e) => setExpectedCheckout(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink transition-colors"
            />
          </div>

          {noticeDate && (
            <button
              type="button"
              onClick={() => { setNoticeDate(""); setExpectedCheckout("") }}
              className="rounded-pill border border-[#E2DEDD] py-2.5 text-sm font-semibold text-status-warn w-full"
            >
              Withdraw notice
            </button>
          )}
        </div>

        {error && <p className="text-xs text-status-warn font-medium text-center">{error}</p>}
      </div>

      {/* Sticky CTA */}
      <div className="fixed bottom-[80px] left-0 right-0 px-4 pb-2 pt-3 bg-bg border-t border-[#F0EDE9]">
        <button
          onClick={handleReview}
          disabled={!!roomInfo?.is_full}
          className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Review Changes →
        </button>
      </div>

      {showConfirm && (
        <ConfirmationCard
          title="Save Changes"
          fields={buildConfirmFields()}
          onConfirm={handleConfirm}
          error={error}
          onEdit={() => { setShowConfirm(false); setError("") }}
          loading={submitting}
        />
      )}
    </main>
  )
}
