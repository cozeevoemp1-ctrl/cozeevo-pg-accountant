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
  const [agreedRent, setAgreedRent] = useState("")
  const [securityDeposit, setSecurityDeposit] = useState("")
  const [expectedCheckout, setExpectedCheckout] = useState("")
  const [notes, setNotes] = useState("")

  const [showConfirm, setShowConfirm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (!tenancyId) return
    getTenantDues(tenancyId)
      .then((d) => {
        setOriginal(d)
        setName(d.name)
        setPhone(d.phone)
        setAgreedRent(String(d.rent))
        setSecurityDeposit(String(d.security_deposit))
        setExpectedCheckout(formatDate(null)) // not in TenantDues yet
      })
      .catch(() => setFetchError("Could not load tenant details"))
      .finally(() => setLoading(false))
  }, [tenancyId])

  function buildChanges(): PatchTenantBody {
    if (!original) return {}
    const changes: PatchTenantBody = {}
    if (name.trim() && name.trim() !== original.name) changes.name = name.trim()
    if (phone.trim() && phone.trim() !== original.phone) changes.phone = phone.trim()
    if (email.trim()) changes.email = email.trim()
    if (agreedRent && Number(agreedRent) !== original.rent) {
      changes.agreed_rent = Number(agreedRent)
    }
    if (securityDeposit && Number(securityDeposit) !== original.security_deposit) {
      changes.security_deposit = Number(securityDeposit)
    }
    if (expectedCheckout) changes.expected_checkout = expectedCheckout
    if (notes.trim()) changes.tenancy_notes = notes.trim()
    return changes
  }

  function buildConfirmFields() {
    const changes = buildChanges()
    const fields: { label: string; value: string; highlight?: boolean }[] = []
    if (changes.name) fields.push({ label: "Name", value: changes.name })
    if (changes.phone) fields.push({ label: "Phone", value: changes.phone })
    if (changes.email) fields.push({ label: "Email", value: changes.email })
    if (changes.agreed_rent !== undefined)
      fields.push({ label: "Agreed Rent", value: `₹${Number(changes.agreed_rent).toLocaleString("en-IN")}`, highlight: true })
    if (changes.security_deposit !== undefined)
      fields.push({ label: "Security Deposit", value: `₹${Number(changes.security_deposit).toLocaleString("en-IN")}` })
    if (changes.expected_checkout) fields.push({ label: "Expected Checkout", value: changes.expected_checkout })
    if (changes.tenancy_notes) fields.push({ label: "Notes", value: changes.tenancy_notes })
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
      setShowConfirm(false)
      setError(err instanceof Error ? err.message : "Update failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  const rentChanged = original && agreedRent && Number(agreedRent) !== original.rent

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
      <main className="min-h-screen bg-bg flex flex-col items-center justify-center px-6 gap-5">
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
        </div>

        {/* Stay details */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-4">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Stay Details</p>

          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1">Expected Checkout</label>
            <input
              type="date"
              value={expectedCheckout}
              onChange={(e) => setExpectedCheckout(e.target.value)}
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

        {error && <p className="text-xs text-status-warn font-medium text-center">{error}</p>}
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
          onEdit={() => setShowConfirm(false)}
          loading={submitting}
        />
      )}
    </main>
  )
}
