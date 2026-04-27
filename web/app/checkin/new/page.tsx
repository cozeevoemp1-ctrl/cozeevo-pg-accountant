"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
import { Numpad } from "@/components/forms/numpad"
import {
  getCheckinPreview,
  recordCheckin,
  TenantSearchResult,
  CheckinPreview,
} from "@/lib/api"

type Method = "CASH" | "UPI" | "BANK" | "OTHER"

const METHODS: { value: Method; label: string; icon: string }[] = [
  { value: "CASH", label: "Cash", icon: "💵" },
  { value: "UPI",  label: "UPI",  icon: "📱" },
  { value: "BANK", label: "Bank", icon: "🏦" },
  { value: "OTHER",label: "Other",icon: "💳" },
]

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}

function fmtDate(iso: string): string {
  if (!iso) return "—"
  const [y, m, d] = iso.split("-")
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${d} ${months[parseInt(m) - 1]} ${y}`
}

export default function NewCheckinPage() {
  const router = useRouter()

  const [tenant,      setTenant]      = useState<TenantSearchResult | null>(null)
  const [preview,     setPreview]     = useState<CheckinPreview | null>(null)
  const [actualDate,  setActualDate]  = useState(todayISO())
  const [amount,      setAmount]      = useState("")
  const [method,      setMethod]      = useState<Method>("CASH")
  const [notes,       setNotes]       = useState("")
  const [loadingPrev, setLoadingPrev] = useState(false)

  const [showConfirm, setShowConfirm] = useState(false)
  const [submitting,  setSubmitting]  = useState(false)
  const [error,       setError]       = useState("")
  const [success,     setSuccess]     = useState(false)
  const [result,      setResult]      = useState<{ balanceRemaining: number } | null>(null)

  // Reload preview whenever tenant or actual date changes
  useEffect(() => {
    if (!tenant) { setPreview(null); return }
    let cancelled = false
    setLoadingPrev(true)
    getCheckinPreview(tenant.tenancy_id, actualDate)
      .then((p) => {
        if (cancelled) return
        setPreview(p)
        // Pre-fill numpad with balance due (0 if already covered by advance)
        setAmount(p.balance_due > 0 ? String(Math.round(p.balance_due)) : "0")
      })
      .catch(() => { if (!cancelled) setError("Could not load check-in preview") })
      .finally(() => { if (!cancelled) setLoadingPrev(false) })
    return () => { cancelled = true }
  }, [tenant, actualDate])

  function handleTenantSelect(t: TenantSearchResult) {
    setTenant(t)
    setPreview(null)
    setAmount("")
    setError("")
  }

  function handleReview() {
    setError("")
    if (!tenant)  { setError("Select a tenant first"); return }
    if (!preview) { setError("Loading check-in details…"); return }
    setShowConfirm(true)
  }

  async function handleConfirm() {
    if (!tenant || !preview) return
    setSubmitting(true)
    setError("")
    try {
      const res = await recordCheckin({
        tenancy_id:          tenant.tenancy_id,
        actual_checkin_date: actualDate,
        amount_collected:    Number(amount || 0),
        payment_method:      method,
        notes:               notes || undefined,
      })
      setShowConfirm(false)
      setResult({ balanceRemaining: res.balance_remaining })
      setSuccess(true)
    } catch (err) {
      setShowConfirm(false)
      setError(err instanceof Error ? err.message : "Check-in failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  function resetForm() {
    setSuccess(false); setResult(null)
    setTenant(null); setPreview(null)
    setAmount(""); setNotes(""); setActualDate(todayISO())
  }

  // ── Success screen ────────────────────────────────────────────────────────
  if (success && tenant && preview) {
    const collected = Number(amount || 0)
    return (
      <main className="min-h-screen bg-bg flex flex-col items-center justify-center px-6 gap-5">
        <div className="w-20 h-20 rounded-full bg-tile-green flex items-center justify-center text-4xl">✓</div>
        <div className="text-center">
          <h1 className="text-xl font-extrabold text-ink">Check-in Recorded!</h1>
          <p className="text-sm text-ink-muted mt-1">WhatsApp sent · Synced to DB + Sheet</p>
        </div>
        <div className="w-full max-w-sm bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-2">
          <Row label="Tenant"      value={tenant.name} />
          <Row label="Room"        value={`${tenant.room_number} · ${tenant.building_code}`} />
          <Row label="Check-in"    value={fmtDate(actualDate)} />
          {preview.date_changed && (
            <Row label="Agreed date" value={fmtDate(preview.agreed_checkin_date ?? "")} muted />
          )}
          <Row label="Monthly rent" value={`₹${preview.agreed_rent.toLocaleString("en-IN")}`} />
          <Row label="First month total" value={`₹${Math.round(preview.first_month_total).toLocaleString("en-IN")}`} />
          <Row label="Advance paid" value={`₹${Math.round(preview.booking_amount).toLocaleString("en-IN")}`} />
          {collected > 0 && (
            <Row label="Collected today" value={`₹${collected.toLocaleString("en-IN")} (${method})`} pink />
          )}
          <Row
            label="Balance remaining"
            value={result && result.balanceRemaining <= 0 ? "₹0 (Cleared)" : `₹${Math.round(result?.balanceRemaining ?? 0).toLocaleString("en-IN")}`}
          />
        </div>
        <div className="flex gap-3 w-full max-w-sm">
          <button onClick={resetForm}
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
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
        <button onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
          aria-label="Back">
          ←
        </button>
        <h1 className="text-lg font-extrabold text-ink">Physical Check-in</h1>
      </div>

      <div className="px-4 pt-4 pb-32 flex flex-col gap-4 max-w-lg mx-auto">

        {/* Tenant search */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <TenantSearch
            onSelect={handleTenantSelect}
            placeholder="Search tenant by name, room, phone…"
          />
        </div>

        {/* Actual check-in date */}
        {tenant && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
              Actual Check-in Date
            </p>
            <input
              type="date"
              value={actualDate}
              onChange={(e) => setActualDate(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink font-semibold outline-none focus:border-brand-pink"
            />
            {preview?.date_changed && (
              <div className="mt-3 rounded-tile bg-tile-orange px-3 py-2 text-xs text-ink font-medium">
                Agreed date was <span className="font-bold">{fmtDate(preview.agreed_checkin_date ?? "")}</span>.
                Rent recalculated from actual date.
              </div>
            )}
          </div>
        )}

        {/* Booking summary */}
        {preview && !loadingPrev && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
              First Month Breakdown
            </p>
            <div className="flex flex-col gap-1.5">
              <Row label="Monthly rent"      value={`₹${preview.agreed_rent.toLocaleString("en-IN")}`} />
              <Row label="Days billed"       value={`${fmtDate(actualDate)} → end of month`} muted />
              <Row label="Prorated rent"     value={`₹${Math.round(preview.prorated_rent).toLocaleString("en-IN")}`} />
              <Row label="Security deposit"  value={`₹${Math.round(preview.security_deposit).toLocaleString("en-IN")}`} />
              <div className="border-t border-[#F0EDE9] pt-1.5 mt-0.5">
                <Row label="Total due (first month)"
                  value={`₹${Math.round(preview.first_month_total).toLocaleString("en-IN")}`} />
                <Row label="Advance already paid"
                  value={`− ₹${Math.round(preview.booking_amount).toLocaleString("en-IN")}`} />
                <Row
                  label={preview.balance_due > 0 ? "Balance to collect now" : preview.overpayment > 0 ? "Credit (overpaid)" : "Fully covered"}
                  value={
                    preview.balance_due > 0
                      ? `₹${Math.round(preview.balance_due).toLocaleString("en-IN")}`
                      : preview.overpayment > 0
                        ? `₹${Math.round(preview.overpayment).toLocaleString("en-IN")} credit`
                        : "₹0"
                  }
                  pink={preview.balance_due > 0}
                />
              </div>
            </div>
          </div>
        )}

        {loadingPrev && tenant && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] text-xs text-ink-muted text-center">
            Loading check-in details…
          </div>
        )}

        {/* Amount — only show if there's something to collect (or override) */}
        {preview && (
          <Numpad
            value={amount}
            onChange={setAmount}
            suggestAmounts={preview.balance_due > 0 ? [Math.round(preview.balance_due)] : []}
          />
        )}

        {/* Method */}
        {preview && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Payment Method</p>
            <div className="grid grid-cols-4 gap-2">
              {METHODS.map((m) => (
                <button key={m.value} type="button" onClick={() => setMethod(m.value)}
                  className={`rounded-tile py-2.5 text-center border-2 transition-colors ${
                    method === m.value ? "border-brand-pink bg-tile-pink" : "border-[#E2DEDD] bg-bg"
                  }`}>
                  <div className="text-lg">{m.icon}</div>
                  <div className={`text-[10px] font-bold mt-1 ${method === m.value ? "text-brand-pink" : "text-ink"}`}>
                    {m.label}
                  </div>
                </button>
              ))}
            </div>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Note (optional)…"
              className="mt-3 w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2 text-xs text-ink outline-none focus:border-brand-pink"
            />
          </div>
        )}

        {error && <p className="text-xs text-status-warn font-medium text-center">{error}</p>}
      </div>

      {/* Sticky CTA */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-8 pt-3 bg-bg border-t border-[#F0EDE9]">
        <button
          onClick={handleReview}
          disabled={!tenant || !preview || loadingPrev}
          className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80 disabled:opacity-40"
        >
          Review &amp; Confirm →
        </button>
      </div>

      {/* Confirmation overlay */}
      {showConfirm && tenant && preview && (
        <ConfirmationCard
          title="Confirm Check-in"
          fields={[
            { label: "Tenant",     value: `${tenant.name} · Room ${tenant.room_number}` },
            { label: "Check-in",   value: fmtDate(actualDate) },
            ...(preview.date_changed
              ? [{ label: "Date updated from", value: fmtDate(preview.agreed_checkin_date ?? "") }]
              : []),
            { label: "First month total", value: `₹${Math.round(preview.first_month_total).toLocaleString("en-IN")}` },
            { label: "Advance paid",      value: `₹${Math.round(preview.booking_amount).toLocaleString("en-IN")}` },
            { label: "Collecting now",    value: `₹${Number(amount || 0).toLocaleString("en-IN")}`, highlight: true },
            { label: "Method",            value: `${METHODS.find(m => m.value === method)?.icon} ${method}` },
            ...(notes ? [{ label: "Note", value: notes }] : []),
          ]}
          onConfirm={handleConfirm}
          onEdit={() => setShowConfirm(false)}
          loading={submitting}
        />
      )}
    </main>
  )
}

function Row({
  label, value, pink, muted,
}: { label: string; value: string; pink?: boolean; muted?: boolean }) {
  return (
    <div className="flex justify-between py-1.5 border-b border-[#F5F5F5] last:border-none">
      <span className="text-xs text-ink-muted">{label}</span>
      <span className={`text-xs font-semibold ${
        pink  ? "text-brand-pink text-sm font-extrabold" :
        muted ? "text-ink-muted" :
        "text-ink"
      }`}>
        {value}
      </span>
    </div>
  )
}
