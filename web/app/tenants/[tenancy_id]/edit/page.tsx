"use client"

import { useState, useEffect } from "react"
import { useRouter, useParams } from "next/navigation"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
import { getTenantDues, patchTenant, checkRoom, transferRoom, TenantDues, PatchTenantBody, RoomCheckResult } from "@/lib/api"

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

  // Transfer Room panel
  const [showTransfer, setShowTransfer] = useState(false)
  const [transferStep, setTransferStep] = useState<1 | 2 | 3 | 4>(1)
  const [destRoom, setDestRoom] = useState("")
  const [roomCheck, setRoomCheck] = useState<RoomCheckResult | null>(null)
  const [roomCheckLoading, setRoomCheckLoading] = useState(false)
  const [roomCheckError, setRoomCheckError] = useState("")
  const [transferNewRent, setTransferNewRent] = useState("")
  const [transferExtraDeposit, setTransferExtraDeposit] = useState("0")
  const [transferSubmitting, setTransferSubmitting] = useState(false)
  const [transferError, setTransferError] = useState("")
  const [transferSuccess, setTransferSuccess] = useState(false)

  useEffect(() => {
    if (!tenancyId) return
    getTenantDues(tenancyId)
      .then((d) => {
        setOriginal(d)
        setName(d.name)
        setPhone(d.phone)
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

  async function handleCheckRoom() {
    if (!destRoom.trim()) return
    setRoomCheckLoading(true)
    setRoomCheckError("")
    setRoomCheck(null)
    try {
      const result = await checkRoom(destRoom.trim())
      setRoomCheck(result)
      if (!result.is_available) setRoomCheckError(`Room ${result.room_number} is full (${result.max_occupancy - result.free_beds}/${result.max_occupancy} beds)`)
    } catch (err) {
      setRoomCheckError(err instanceof Error ? err.message : "Room not found")
    } finally {
      setRoomCheckLoading(false)
    }
  }

  async function handleTransferConfirm() {
    if (!original) return
    setTransferSubmitting(true)
    setTransferError("")
    try {
      const result = await transferRoom(tenancyId, {
        to_room_number: roomCheck!.room_number,
        new_rent: transferNewRent ? Number(transferNewRent) : null,
        extra_deposit: Number(transferExtraDeposit) || 0,
      })
      if (!result.success) {
        setTransferError(result.message)
        setTransferStep(1)
        setRoomCheck(null)
        return
      }
      setTransferSuccess(true)
      const updated = await getTenantDues(tenancyId)
      setOriginal(updated)
      setRoomNumber(updated.room_number)
      setAgreedRent(String(updated.rent))
      setSecurityDeposit(String(updated.security_deposit))
    } catch (err) {
      setTransferError(err instanceof Error ? err.message : "Transfer failed")
    } finally {
      setTransferSubmitting(false)
    }
  }

  function resetTransferPanel() {
    setShowTransfer(false)
    setTransferStep(1)
    setDestRoom("")
    setRoomCheck(null)
    setRoomCheckError("")
    setTransferNewRent("")
    setTransferExtraDeposit("0")
    setTransferError("")
    setTransferSuccess(false)
  }

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
      if (proratedInfo) {
        const today = new Date()
        fields.push({ label: `${today.toLocaleString("en-IN", { month: "short" })} prorated (auto)`, value: `₹${proratedInfo.amount.toLocaleString("en-IN")} (${proratedInfo.remaining}/${proratedInfo.daysInMonth} days)`, highlight: true })
      }
    }
    if (changes.agreed_rent !== undefined)
      fields.push({ label: "Agreed Rent", value: `₹${Number(changes.agreed_rent).toLocaleString("en-IN")}`, highlight: true })
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

  // Prorated calc for mid-month room transfer (read-only)
  const proratedInfo = (() => {
    if (!roomChanged) return null
    const rent = Number(agreedRent) || 0
    if (!rent) return null
    const today = new Date()
    const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate()
    const checkinIso = original?.checkin_date
    let pivotDay = today.getDate()
    if (checkinIso) {
      const checkin = new Date(checkinIso + "T00:00:00")
      const sameMonth = checkin.getFullYear() === today.getFullYear() && checkin.getMonth() === today.getMonth()
      if (sameMonth) pivotDay = checkin.getDate()
    }
    const remaining = daysInMonth - pivotDay + 1
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
          {proratedInfo && (
            <div className="rounded-tile bg-tile-green border border-[#D1FAE5] px-3 py-2.5 mt-1">
              <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">This month prorated (auto)</p>
              <p className="text-sm font-extrabold text-status-paid">₹{proratedInfo.amount.toLocaleString("en-IN")}</p>
              <p className="text-[10px] text-ink-muted mt-0.5">{proratedInfo.remaining}/{proratedInfo.daysInMonth} days × ₹{Number(agreedRent).toLocaleString("en-IN")}/mo</p>
            </div>
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

        {/* Transfer Room button */}
        {!showTransfer && !transferSuccess && (
          <button
            type="button"
            onClick={() => {
              setShowTransfer(true)
              setTransferNewRent(String(original?.rent ?? ""))
            }}
            className="w-full mt-3 py-3 rounded-2xl border-2 border-brand-pink text-brand-pink font-bold text-base"
          >
            Transfer Room
          </button>
        )}

        {/* Transfer Room panel */}
        {showTransfer && !transferSuccess && (
          <div className="mt-4 rounded-2xl border border-[#F0EDE9] bg-surface p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-extrabold text-ink text-base">Transfer Room</h3>
              <button type="button" onClick={resetTransferPanel} className="text-ink-muted text-sm">Cancel</button>
            </div>

            {transferStep === 1 && (
              <div className="space-y-3">
                <p className="text-sm text-ink-muted">Current room: <strong>{original?.room_number}</strong></p>
                <div className="flex gap-2">
                  <input
                    className="flex-1 border border-[#E2DEDD] rounded-xl px-4 py-3 text-base"
                    placeholder="New room number"
                    value={destRoom}
                    onChange={e => { setDestRoom(e.target.value.toUpperCase()); setRoomCheck(null); setRoomCheckError("") }}
                  />
                  <button
                    type="button"
                    onClick={handleCheckRoom}
                    disabled={roomCheckLoading || !destRoom.trim()}
                    className="px-4 py-3 rounded-xl bg-brand-pink text-white font-bold text-sm disabled:opacity-50"
                  >
                    {roomCheckLoading ? "..." : "Check"}
                  </button>
                </div>
                {roomCheckError && <p className="text-sm text-red-500">{roomCheckError}</p>}
                {roomCheck && roomCheck.is_available && (
                  <div className="rounded-xl bg-green-50 border border-green-200 px-4 py-3">
                    <p className="text-sm font-semibold text-green-700">
                      Room {roomCheck.room_number} — {roomCheck.free_beds} bed{roomCheck.free_beds !== 1 ? "s" : ""} free
                      {roomCheck.occupants.length > 0 && ` (sharing with ${roomCheck.occupants.map(o => o.name).join(", ")})`}
                    </p>
                  </div>
                )}
                {transferError && <p className="text-sm text-red-500">{transferError}</p>}
                <button
                  type="button"
                  onClick={() => setTransferStep(2)}
                  disabled={!roomCheck?.is_available}
                  className="w-full py-3 rounded-2xl bg-brand-pink text-white font-bold disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            )}

            {transferStep === 2 && (
              <div className="space-y-3">
                <label className="text-sm text-ink-muted">Rent for new room <span className="text-ink">(current: ₹{Number(original?.rent ?? 0).toLocaleString("en-IN")}/mo)</span></label>
                <input
                  type="number"
                  className="w-full border border-[#E2DEDD] rounded-xl px-4 py-3 text-base"
                  value={transferNewRent}
                  onChange={e => setTransferNewRent(e.target.value)}
                />
                <div className="flex gap-2">
                  <button type="button" onClick={() => setTransferStep(1)} className="flex-1 py-3 rounded-2xl border border-[#E2DEDD] text-ink font-bold">Back</button>
                  <button type="button" onClick={() => setTransferStep(3)} disabled={!transferNewRent} className="flex-1 py-3 rounded-2xl bg-brand-pink text-white font-bold disabled:opacity-40">Next</button>
                </div>
              </div>
            )}

            {transferStep === 3 && (
              <div className="space-y-3">
                <label className="text-sm text-ink-muted">Additional deposit to collect <span className="text-ink">(current: ₹{Number(original?.security_deposit ?? 0).toLocaleString("en-IN")})</span></label>
                <input
                  type="number"
                  className="w-full border border-[#E2DEDD] rounded-xl px-4 py-3 text-base"
                  value={transferExtraDeposit}
                  onChange={e => setTransferExtraDeposit(e.target.value)}
                  placeholder="0 = no change"
                />
                <div className="flex gap-2">
                  <button type="button" onClick={() => setTransferStep(2)} className="flex-1 py-3 rounded-2xl border border-[#E2DEDD] text-ink font-bold">Back</button>
                  <button type="button" onClick={() => setTransferStep(4)} className="flex-1 py-3 rounded-2xl bg-brand-pink text-white font-bold">Review</button>
                </div>
              </div>
            )}

            {transferStep === 4 && (
              <div className="space-y-3">
                {(() => {
                  const rentChanged = Number(transferNewRent) !== original?.rent
                  const depositAmt = Number(transferExtraDeposit) || 0
                  const fields = [
                    { label: "Room", value: `${original?.room_number} → ${roomCheck?.room_number}`, highlight: true },
                    { label: "Rent", value: rentChanged
                      ? `₹${Number(original?.rent).toLocaleString("en-IN")} → ₹${Number(transferNewRent).toLocaleString("en-IN")}/mo`
                      : `₹${Number(transferNewRent).toLocaleString("en-IN")}/mo (no change)`,
                      highlight: rentChanged },
                    ...(depositAmt > 0 ? [{ label: "Extra deposit", value: `₹${depositAmt.toLocaleString("en-IN")}` }] : []),
                  ]
                  return (
                    <>
                      {fields.map(f => (
                        <div key={f.label} className="flex justify-between py-2 border-b border-[#F0EDE9]">
                          <span className="text-sm text-ink-muted">{f.label}</span>
                          <span className={`text-sm font-semibold ${f.highlight ? "text-brand-pink font-extrabold" : "text-ink"}`}>{f.value}</span>
                        </div>
                      ))}
                    </>
                  )
                })()}
                {transferError && <p className="text-sm text-red-500">{transferError}</p>}
                <div className="flex gap-2 pt-2">
                  <button type="button" onClick={() => setTransferStep(3)} className="flex-1 py-3 rounded-2xl border border-[#E2DEDD] text-ink font-bold">Back</button>
                  <button
                    type="button"
                    onClick={handleTransferConfirm}
                    disabled={transferSubmitting}
                    className="flex-1 py-3 rounded-2xl bg-brand-pink text-white font-bold disabled:opacity-50"
                  >
                    {transferSubmitting ? "Transferring..." : "Confirm Transfer"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {transferSuccess && (
          <div className="mt-4 rounded-2xl bg-green-50 border border-green-200 px-5 py-4 text-center">
            <p className="font-bold text-green-700">Room transferred successfully</p>
            <button type="button" onClick={resetTransferPanel} className="mt-2 text-sm text-ink-muted underline">Done</button>
          </div>
        )}
      </div>

      {/* Sticky CTA */}
      <div className="fixed bottom-[80px] left-0 right-0 px-4 pb-2 pt-3 bg-bg border-t border-[#F0EDE9]">
        <button
          onClick={handleReview}
          className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80"
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
