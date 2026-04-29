"use client"

import { useState, useRef } from "react"
import { useRouter } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
import { Numpad } from "@/components/forms/numpad"
import { VoiceSheet } from "@/components/voice/voice-sheet"
import {
  createPayment,
  getTenantDues,
  uploadReceipt,
  TenantSearchResult,
  TenantDues,
  PaymentIntent,
} from "@/lib/api"

type Method = "UPI" | "CASH" | "BANK" | "CARD" | "OTHER"
type ForType = "rent" | "deposit" | "maintenance" | "booking" | "adjustment"

const METHODS: { value: Method; label: string; icon: string }[] = [
  { value: "CASH", label: "Cash", icon: "💵" },
  { value: "UPI", label: "UPI", icon: "📱" },
  { value: "BANK", label: "Bank", icon: "🏦" },
  { value: "OTHER", label: "Other", icon: "💳" },
]

const FOR_TYPES: { value: ForType; label: string }[] = [
  { value: "rent", label: "Rent" },
  { value: "deposit", label: "Deposit" },
  { value: "maintenance", label: "Maintenance" },
  { value: "booking", label: "Advance" },
  { value: "adjustment", label: "Adjustment" },
]

function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

export default function NewPaymentPage() {
  const router = useRouter()

  const [tenant, setTenant] = useState<TenantSearchResult | null>(null)
  const [dues, setDues] = useState<TenantDues | null>(null)
  const [amount, setAmount] = useState("")
  const [method, setMethod] = useState<Method>("CASH")
  const [forType, setForType] = useState<ForType>("rent")
  const [periodMonth, setPeriodMonth] = useState(currentMonth())
  const [notes, setNotes] = useState("")

  const [showConfirm, setShowConfirm] = useState(false)
  const [showVoice, setShowVoice] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)
  const [voiceHint, setVoiceHint] = useState("")

  const [receiptFile, setReceiptFile] = useState<File | null>(null)
  const [receiptUrl, setReceiptUrl] = useState<string | null>(null)
  const [uploadingReceipt, setUploadingReceipt] = useState(false)
  const [receiptError, setReceiptError] = useState("")
  const [lastPaymentId, setLastPaymentId] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleTenantSelect(t: TenantSearchResult) {
    setTenant(t)
    setDues(null)
    try {
      const d = await getTenantDues(t.tenancy_id)
      setDues(d)
      if (!amount && d.dues > 0) setAmount(String(Math.round(d.dues)))
    } catch {
      // dues preview is best-effort
    }
  }

  function handleVoiceIntent(intent: PaymentIntent) {
    setShowVoice(false)
    if (intent.amount) setAmount(String(intent.amount))
    if (intent.method) setMethod((intent.method.toUpperCase() as Method) ?? "CASH")
    if (intent.for_type) setForType(intent.for_type as ForType)
    if (intent.tenant_room) setVoiceHint(intent.tenant_room)
    else if (intent.tenant_name) setVoiceHint(intent.tenant_name)
  }

  function handleReview() {
    setError("")
    if (!tenant) { setError("Select a tenant first"); return }
    if (!amount || Number(amount) <= 0) { setError("Enter a valid amount"); return }
    if (periodMonth < currentMonth()) {
      setError(`${periodMonth} is a closed period — payments cannot be recorded for past months. Use the adjustment line to correct discrepancies.`)
      return
    }
    setShowConfirm(true)
  }

  async function handleConfirm() {
    if (!tenant) return
    setSubmitting(true)
    setError("")
    try {
      const result = await createPayment({
        tenant_id: tenant.tenant_id,
        amount: Number(amount),
        method,
        for_type: forType,
        period_month: periodMonth,
        notes: notes || undefined,
      })
      setLastPaymentId(result.payment_id)
      setShowConfirm(false)
      setSuccess(true)
    } catch (err) {
      setShowConfirm(false)
      setError(err instanceof Error ? err.message : "Payment failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReceiptChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || lastPaymentId === null) return
    setReceiptFile(file)
    setReceiptError("")
    setUploadingReceipt(true)
    try {
      const result = await uploadReceipt(lastPaymentId, file)
      setReceiptUrl(result.receipt_url)
    } catch (err) {
      setReceiptError(err instanceof Error ? err.message : "Upload failed")
    } finally {
      setUploadingReceipt(false)
    }
  }

  const balanceAfter = dues ? dues.dues - Number(amount || 0) : null

  if (success) {
    return (
      <main className="min-h-screen bg-bg flex flex-col items-center px-6 gap-5 pt-16 pb-32">
        <div className="w-20 h-20 rounded-full bg-tile-green flex items-center justify-center text-4xl">✓</div>
        <div className="text-center">
          <h1 className="text-xl font-extrabold text-ink">Payment Saved!</h1>
          <p className="text-sm text-ink-muted mt-1">Synced to Supabase + Ops Sheet</p>
        </div>
        {tenant && (
          <div className="w-full max-w-sm bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-2">
            <Row label="Tenant" value={tenant.name} />
            <Row label="Room" value={`${tenant.room_number} · ${tenant.building_code}`} />
            <Row label="Amount" value={`₹${Number(amount).toLocaleString("en-IN")}`} pink />
            <Row label="Method" value={method} />
            {dues && (
              <Row
                label="Balance"
                value={balanceAfter !== null && balanceAfter <= 0 ? "₹0 (Cleared)" : `₹${Math.max(0, balanceAfter ?? 0).toLocaleString("en-IN")} remaining`}
              />
            )}
          </div>
        )}
        {/* Receipt upload */}
        {receiptUrl ? (
          <div className="w-full max-w-sm flex items-center gap-2 px-4 py-2 rounded-pill bg-tile-green border border-[#C5E8D0]">
            <span className="text-status-paid text-sm font-semibold">Receipt saved ✓</span>
          </div>
        ) : (
          <div className="w-full max-w-sm flex flex-col gap-1">
            <input
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              ref={fileInputRef}
              onChange={handleReceiptChange}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingReceipt}
              className="w-full flex items-center justify-center gap-2 rounded-pill border border-[#E2DEDD] py-3 text-ink font-semibold text-sm active:opacity-70 disabled:opacity-50"
            >
              <span>📷</span>
              <span>{uploadingReceipt ? "Uploading…" : "Take Photo / Upload"}</span>
            </button>
            {receiptError && <p className="text-xs text-status-warn font-medium text-center">{receiptError}</p>}
          </div>
        )}

        <div className="flex gap-3 w-full max-w-sm">
          <button
            onClick={() => { setSuccess(false); setTenant(null); setDues(null); setAmount(""); setNotes(""); setReceiptUrl(null); setReceiptFile(null); setLastPaymentId(null) }}
            className="flex-1 rounded-pill border border-[#E2DEDD] py-3 text-ink font-semibold text-sm"
          >
            + New
          </button>
          <button
            onClick={() => router.push("/")}
            className="flex-1 rounded-pill bg-brand-pink py-3 text-white font-bold text-sm"
          >
            ← Home
          </button>
        </div>
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
        <h1 className="text-lg font-extrabold text-ink">Collect Payment</h1>
        <button
          onClick={() => setShowVoice(true)}
          className="ml-auto flex items-center gap-1.5 px-3 py-2 rounded-pill bg-brand-pink text-white text-xs font-bold shadow"
          aria-label="Voice input"
        >
          🎙 Hey Kozzy
        </button>
      </div>

      <div className="px-4 pt-4 pb-52 flex flex-col gap-4 max-w-lg mx-auto">
        {/* Tenant search */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <TenantSearch
            onSelect={handleTenantSelect}
            defaultValue={voiceHint}
            placeholder="Search by name, room, phone…"
          />
        </div>

        {/* Dues preview */}
        {dues && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex justify-between items-center">
            <div>
              <p className="text-xs text-ink-muted font-medium">Outstanding this month</p>
              <p className={`text-lg font-extrabold mt-0.5 ${dues.dues > 0 ? "text-status-warn" : "text-status-paid"}`}>
                {dues.dues > 0 ? `₹${dues.dues.toLocaleString("en-IN")} due` : "Fully paid ✓"}
              </p>
            </div>
            {dues.last_payment_date && (
              <div className="text-right">
                <p className="text-xs text-ink-muted">Last paid</p>
                <p className="text-xs font-semibold text-ink">₹{(dues.last_payment_amount ?? 0).toLocaleString("en-IN")}</p>
              </div>
            )}
          </div>
        )}

        {/* Numpad */}
        <Numpad
          value={amount}
          onChange={setAmount}
          suggestAmounts={dues && dues.dues > 0 ? [Math.round(dues.dues)] : []}
        />

        {/* Method pills */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Payment Method</p>
          <div className="grid grid-cols-4 gap-2">
            {METHODS.map((m) => (
              <button
                key={m.value}
                type="button"
                onClick={() => setMethod(m.value)}
                className={`rounded-tile py-2.5 text-center border-2 transition-colors ${
                  method === m.value
                    ? "border-brand-pink bg-tile-pink"
                    : "border-[#E2DEDD] bg-bg"
                }`}
              >
                <div className="text-lg">{m.icon}</div>
                <div className={`text-[10px] font-bold mt-1 ${method === m.value ? "text-brand-pink" : "text-ink"}`}>{m.label}</div>
              </button>
            ))}
          </div>
        </div>

        {/* For type + period */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Payment For</p>
          <div className="flex gap-2 flex-wrap">
            {FOR_TYPES.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => setForType(f.value)}
                className={`rounded-pill px-3 py-1.5 text-xs font-semibold border transition-colors ${
                  forType === f.value
                    ? "bg-brand-pink text-white border-brand-pink"
                    : "bg-bg text-ink border-[#E2DEDD]"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="mt-3 flex gap-2 items-center">
            <label className="text-xs text-ink-muted font-medium whitespace-nowrap">Period</label>
            <input
              type="month"
              value={periodMonth}
              min={currentMonth()}
              onChange={(e) => setPeriodMonth(e.target.value)}
              className="flex-1 rounded-pill border border-[#E2DEDD] bg-bg px-3 py-1.5 text-xs text-ink outline-none focus:border-brand-pink"
            />
          </div>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Note (optional)…"
            className="mt-2 w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2 text-xs text-ink outline-none focus:border-brand-pink"
          />
        </div>

        {error && <p className="text-xs text-status-warn font-medium text-center">{error}</p>}
      </div>

      {/* Sticky CTA */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-28 pt-3 bg-bg border-t border-[#F0EDE9]">
        <button
          onClick={handleReview}
          className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80"
        >
          Review &amp; Confirm →
        </button>
      </div>

      {showConfirm && tenant && (
        <ConfirmationCard
          title="Record Payment"
          fields={[
            { label: "Tenant", value: `${tenant.name} · Room ${tenant.room_number}` },
            { label: "Amount", value: `₹${Number(amount).toLocaleString("en-IN")}`, highlight: true },
            { label: "Method", value: `${METHODS.find(m => m.value === method)?.icon} ${method}` },
            { label: "For", value: FOR_TYPES.find(f => f.value === forType)?.label ?? forType },
            { label: "Period", value: periodMonth },
            ...(notes ? [{ label: "Note", value: notes }] : []),
            ...(balanceAfter !== null ? [{
              label: "Balance after",
              value: balanceAfter <= 0 ? "₹0 (Cleared)" : `₹${balanceAfter.toLocaleString("en-IN")} remaining`,
            }] : []),
          ]}
          onConfirm={handleConfirm}
          onEdit={() => setShowConfirm(false)}
          loading={submitting}
        />
      )}

      {showVoice && (
        <VoiceSheet
          onClose={() => setShowVoice(false)}
          onPaymentIntent={handleVoiceIntent}
        />
      )}
    </main>
  )
}

function Row({ label, value, pink }: { label: string; value: string; pink?: boolean }) {
  return (
    <div className="flex justify-between py-1.5 border-b border-[#F5F5F5] last:border-none">
      <span className="text-xs text-ink-muted">{label}</span>
      <span className={`text-xs font-semibold ${pink ? "text-brand-pink text-sm font-extrabold" : "text-ink"}`}>{value}</span>
    </div>
  )
}
