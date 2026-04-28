"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
import { Numpad } from "@/components/forms/numpad"
import {
  getCheckoutPrefetch,
  createCheckout,
  getCheckoutStatus,
  TenantSearchResult,
  CheckoutPrefetch,
  CheckoutCreateResponse,
} from "@/lib/api"

type RefundMode = "CASH" | "UPI" | "BANK"

const REFUND_MODES: { value: RefundMode; label: string; icon: string }[] = [
  { value: "CASH", label: "Cash",  icon: "💵" },
  { value: "UPI",  label: "UPI",   icon: "📱" },
  { value: "BANK", label: "Bank",  icon: "🏦" },
]

function fmtINR(n: number) {
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}

function fmtDate(iso: string): string {
  if (!iso) return "—"
  const [y, m, d] = iso.split("-")
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${d} ${months[parseInt(m) - 1]} ${y}`
}

function CheckBox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 py-2.5 w-full text-left"
    >
      <span className={`w-5 h-5 rounded-[5px] flex items-center justify-center border-2 flex-shrink-0 transition-colors ${
        checked ? "bg-brand-pink border-brand-pink" : "bg-bg border-[#E2DEDD]"
      }`}>
        {checked && (
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M2 6l3 3 5-5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        )}
      </span>
      <span className="text-sm font-medium text-ink">{label}</span>
    </button>
  )
}

export default function NewCheckoutPage() {
  const router = useRouter()

  const [tenant,       setTenant]       = useState<TenantSearchResult | null>(null)
  const [prefetch,     setPrefetch]     = useState<CheckoutPrefetch | null>(null)
  const [checkoutDate, setCheckoutDate] = useState(todayISO())
  const [loadingPre,   setLoadingPre]   = useState(false)

  // Checklist
  const [roomKey,      setRoomKey]      = useState(false)
  const [wardrobeKey,  setWardrobeKey]  = useState(false)
  const [biometric,    setBiometric]    = useState(false)
  const [conditionOk,  setConditionOk]  = useState(true)
  const [damageNotes,  setDamageNotes]  = useState("")

  // Financials
  const [deductions,      setDeductions]      = useState("0")
  const [deductionReason, setDeductionReason] = useState("")
  const [refundMode,      setRefundMode]      = useState<RefundMode>("CASH")

  // Form flow
  const [showConfirm,  setShowConfirm]  = useState(false)
  const [submitting,   setSubmitting]   = useState(false)
  const [error,        setError]        = useState("")
  const [result,       setResult]       = useState<CheckoutCreateResponse | null>(null)
  const [pollStatus,   setPollStatus]   = useState<string>("")

  // Derived: refund = max(deposit - dues - deductions, 0)
  const deductionsNum  = Number(deductions) || 0
  const refundAmount   = prefetch
    ? Math.max(prefetch.security_deposit - prefetch.pending_dues - deductionsNum, 0)
    : 0

  // Load prefetch when tenant selected
  useEffect(() => {
    if (!tenant) { setPrefetch(null); return }
    let cancelled = false
    setLoadingPre(true)
    getCheckoutPrefetch(tenant.tenancy_id)
      .then((p) => { if (!cancelled) setPrefetch(p) })
      .catch(() => { if (!cancelled) setError("Could not load tenant details") })
      .finally(() => { if (!cancelled) setLoadingPre(false) })
    return () => { cancelled = true }
  }, [tenant])

  function handleTenantSelect(t: TenantSearchResult) {
    setTenant(t)
    setPrefetch(null)
    setError("")
    setDeductions("0")
    setRoomKey(false)
    setWardrobeKey(false)
    setBiometric(false)
    setConditionOk(true)
    setDamageNotes("")
  }

  function handleReview() {
    setError("")
    if (!tenant)   { setError("Select a tenant first"); return }
    if (!prefetch) { setError("Loading tenant details…"); return }
    if (refundAmount > 0 && !refundMode) { setError("Select refund mode"); return }
    setShowConfirm(true)
  }

  async function handleConfirm() {
    if (!tenant || !prefetch) return
    setSubmitting(true)
    setError("")
    try {
      const res = await createCheckout({
        tenancy_id:            tenant.tenancy_id,
        checkout_date:         checkoutDate,
        room_key_returned:     roomKey,
        wardrobe_key_returned: wardrobeKey,
        biometric_removed:     biometric,
        room_condition_ok:     conditionOk,
        damage_notes:          conditionOk ? "" : damageNotes,
        security_deposit:      prefetch.security_deposit,
        pending_dues:          prefetch.pending_dues,
        deductions:            deductionsNum,
        deduction_reason:      deductionReason || undefined,
        refund_amount:         refundAmount,
        refund_mode:           refundMode.toLowerCase(),
      })
      setShowConfirm(false)
      setResult(res)
      setPollStatus("pending")
    } catch (err) {
      setShowConfirm(false)
      setError(err instanceof Error ? err.message : "Checkout failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  // Poll status every 5 seconds after submission
  const pollFn = useCallback(async () => {
    if (!result?.token) return
    try {
      const s = await getCheckoutStatus(result.token)
      setPollStatus(s.status)
    } catch { /* ignore */ }
  }, [result?.token])

  useEffect(() => {
    if (!result) return
    const id = setInterval(pollFn, 5000)
    return () => clearInterval(id)
  }, [result, pollFn])

  function resetForm() {
    setTenant(null); setPrefetch(null)
    setCheckoutDate(todayISO())
    setDeductions("0"); setDeductionReason("")
    setRoomKey(false); setWardrobeKey(false)
    setBiometric(false); setConditionOk(true); setDamageNotes("")
    setResult(null); setPollStatus(""); setError("")
  }

  // ── Success screen ──────────────────────────────────────────────────────
  if (result && tenant && prefetch) {
    const statusColor =
      pollStatus === "confirmed" ? "text-status-paid" :
      pollStatus === "rejected"  ? "text-status-warn" :
      "text-ink-muted"
    const statusLabel =
      pollStatus === "confirmed" ? "Confirmed by tenant" :
      pollStatus === "rejected"  ? "Disputed by tenant" :
      "Waiting for tenant confirmation…"

    return (
      <main className="min-h-screen bg-bg flex flex-col items-center justify-center px-6 gap-5">
        <div className="w-20 h-20 rounded-full bg-tile-orange flex items-center justify-center text-4xl">✓</div>
        <div className="text-center">
          <h1 className="text-xl font-extrabold text-ink">Checkout Initiated!</h1>
          <p className="text-sm text-ink-muted mt-1">WhatsApp sent · Link shared with tenant</p>
        </div>
        <div className="w-full max-w-sm bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-2">
          <Row label="Tenant"           value={tenant.name} />
          <Row label="Room"             value={tenant.room_number} />
          <Row label="Checkout date"    value={fmtDate(checkoutDate)} />
          <Row label="Security deposit" value={fmtINR(prefetch.security_deposit)} />
          <Row label="Pending dues"     value={fmtINR(prefetch.pending_dues)} muted={prefetch.pending_dues === 0} />
          {deductionsNum > 0 && (
            <Row label="Deductions" value={`− ${fmtINR(deductionsNum)}`} />
          )}
          <Row label="Refund amount"
               value={refundAmount > 0 ? `${fmtINR(refundAmount)} (${refundMode})` : "₹0 (no refund)"}
               pink={refundAmount > 0} />
          <div className="border-t border-[#F0EDE9] pt-2 mt-1">
            <p className={`text-xs font-semibold text-center ${statusColor}`}>{statusLabel}</p>
          </div>
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

  // ── Form ────────────────────────────────────────────────────────────────
  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
        <button onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
          aria-label="Back">
          ←
        </button>
        <h1 className="text-lg font-extrabold text-ink">Physical Check-out</h1>
      </div>

      <div className="px-4 pt-4 pb-32 flex flex-col gap-4 max-w-lg mx-auto">

        {/* Tenant search */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <TenantSearch
            onSelect={handleTenantSelect}
            placeholder="Search tenant by name, room, phone…"
          />
        </div>

        {/* Checkout date */}
        {tenant && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
              Checkout Date
            </p>
            <input
              type="date"
              value={checkoutDate}
              onChange={(e) => setCheckoutDate(e.target.value)}
              className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink font-semibold outline-none focus:border-brand-pink"
            />
          </div>
        )}

        {loadingPre && tenant && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] text-xs text-ink-muted text-center">
            Loading tenant details…
          </div>
        )}

        {/* Physical handover checklist */}
        {prefetch && !loadingPre && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">
              Handover Checklist
            </p>
            <div className="divide-y divide-[#F5F5F5]">
              <CheckBox label="Room key returned"     checked={roomKey}     onChange={setRoomKey} />
              <CheckBox label="Wardrobe key returned" checked={wardrobeKey} onChange={setWardrobeKey} />
              <CheckBox label="Biometric removed"     checked={biometric}   onChange={setBiometric} />
              <CheckBox label="Room condition OK"      checked={conditionOk} onChange={setConditionOk} />
            </div>
            {!conditionOk && (
              <textarea
                value={damageNotes}
                onChange={(e) => setDamageNotes(e.target.value)}
                placeholder="Describe damage or issues…"
                rows={2}
                className="mt-3 w-full rounded-tile border border-[#E2DEDD] bg-bg px-3 py-2 text-xs text-ink outline-none focus:border-brand-pink resize-none"
              />
            )}
          </div>
        )}

        {/* Financial summary */}
        {prefetch && !loadingPre && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
              Refund Calculation
            </p>
            <div className="flex flex-col gap-1.5 mb-3">
              <Row label="Security deposit" value={fmtINR(prefetch.security_deposit)} />
              <Row label="Pending dues"     value={`− ${fmtINR(prefetch.pending_dues)}`} />
              {deductionsNum > 0 && (
                <Row label="Deductions" value={`− ${fmtINR(deductionsNum)}`} />
              )}
              <div className="border-t border-[#F0EDE9] pt-1.5 mt-0.5">
                <Row
                  label="Refund to tenant"
                  value={refundAmount > 0 ? fmtINR(refundAmount) : "₹0"}
                  pink={refundAmount > 0}
                />
              </div>
            </div>
          </div>
        )}

        {/* Deductions numpad */}
        {prefetch && !loadingPre && (
          <>
            <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
                Deductions (damage / dues)
              </p>
              <Numpad
                value={deductions === "0" ? "" : deductions}
                onChange={(v) => setDeductions(v || "0")}
                suggestAmounts={[]}
              />
              <input
                type="text"
                value={deductionReason}
                onChange={(e) => setDeductionReason(e.target.value)}
                placeholder="Reason for deduction (optional)…"
                className="mt-3 w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2 text-xs text-ink outline-none focus:border-brand-pink"
              />
            </div>

            {/* Refund mode — only when there's a refund */}
            {refundAmount > 0 && (
              <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
                <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
                  Refund Mode
                </p>
                <div className="grid grid-cols-3 gap-2">
                  {REFUND_MODES.map((m) => (
                    <button key={m.value} type="button" onClick={() => setRefundMode(m.value)}
                      className={`rounded-tile py-2.5 text-center border-2 transition-colors ${
                        refundMode === m.value ? "border-brand-pink bg-tile-pink" : "border-[#E2DEDD] bg-bg"
                      }`}>
                      <div className="text-lg">{m.icon}</div>
                      <div className={`text-[10px] font-bold mt-1 ${refundMode === m.value ? "text-brand-pink" : "text-ink"}`}>
                        {m.label}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {error && <p className="text-xs text-status-warn font-medium text-center">{error}</p>}
      </div>

      {/* Sticky CTA */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-8 pt-3 bg-bg border-t border-[#F0EDE9]">
        <button
          onClick={handleReview}
          disabled={!tenant || !prefetch || loadingPre}
          className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80 disabled:opacity-40"
        >
          Review &amp; Confirm →
        </button>
      </div>

      {/* Confirmation overlay */}
      {showConfirm && tenant && prefetch && (
        <ConfirmationCard
          title="Confirm Check-out"
          fields={[
            { label: "Tenant",     value: `${tenant.name} · Room ${tenant.room_number}` },
            { label: "Checkout",   value: fmtDate(checkoutDate) },
            { label: "Deposit",    value: fmtINR(prefetch.security_deposit) },
            ...(prefetch.pending_dues > 0 ? [{ label: "Pending dues", value: `− ${fmtINR(prefetch.pending_dues)}` }] : []),
            ...(deductionsNum > 0 ? [{ label: "Deductions", value: `− ${fmtINR(deductionsNum)}` }] : []),
            { label: "Refund",     value: refundAmount > 0 ? `${fmtINR(refundAmount)} · ${refundMode}` : "₹0 (no refund)", highlight: refundAmount > 0 },
            { label: "Checklist",  value: [roomKey && "Key", wardrobeKey && "Wardrobe", biometric && "Biometric", conditionOk && "Condition OK"].filter(Boolean).join(" · ") || "—" },
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
