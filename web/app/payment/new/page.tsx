"use client"

import { useState, useRef, useEffect } from "react"
import { useRouter } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
import { Numpad } from "@/components/forms/numpad"
import { VoiceSheet } from "@/components/voice/voice-sheet"
import { ReceiptScanner, ReceiptScanResult } from "@/components/forms/receipt-scanner"
import {
  createPayment,
  getTenantDues,
  patchAdjustment,
  uploadReceipt,
  TenantSearchResult,
  TenantDues,
  PaymentIntent,
} from "@/lib/api"
import { rupee, rupeeExact } from "@/lib/format"
import { monthLabel, periodMonth as currentPeriodMonth } from "@/lib/date"
import { PageHeader } from "@/components/ui/page-header"

type Method = "UPI" | "CASH"
type ForType = "rent" | "deposit" | "booking"

const METHODS: { value: Method; label: string; icon: string }[] = [
  { value: "CASH", label: "Cash", icon: "💵" },
  { value: "UPI", label: "UPI", icon: "📱" },
]

const FOR_TYPES: { value: ForType; label: string }[] = [
  { value: "rent", label: "Rent" },
  { value: "deposit", label: "Deposit" },
  { value: "booking", label: "Advance" },
]

export default function NewPaymentPage() {
  const router = useRouter()

  const [tenant, setTenant] = useState<TenantSearchResult | null>(null)
  const [dues, setDues] = useState<TenantDues | null>(null)
  const [amount, setAmount] = useState("")
  const [method, setMethod] = useState<Method>("CASH")
  const [forType, setForType] = useState<ForType>("rent")
  const [periodMonth, setPeriodMonth] = useState(currentPeriodMonth())
  const [notes, setNotes] = useState("")

  const [showConfirm, setShowConfirm] = useState(false)
  const [showVoice, setShowVoice] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)
  const [voiceHint, setVoiceHint] = useState("")
  const [waiveRemaining, setWaiveRemaining] = useState(false)

  const monthScrollRef = useRef<HTMLDivElement>(null)

  // Scroll selected month chip into view on mount
  useEffect(() => {
    const el = monthScrollRef.current?.querySelector<HTMLElement>("[data-selected=true]")
    el?.scrollIntoView({ behavior: "instant", inline: "center", block: "nearest" })
  }, [])

  // Receipt state — scanned on form, uploaded after save
  const [scannedFile, setScannedFile] = useState<File | null>(null)
  const [receiptUrl, setReceiptUrl] = useState<string | null>(null)
  const [transactionId, setTransactionId] = useState<string | null>(null)
  const [lastPaymentId, setLastPaymentId] = useState<number | null>(null)

  // Pre-fill from ?tenancy_id= (e.g. navigating from Recent Check-ins)
  useEffect(() => {
    const tid = new URLSearchParams(window.location.search).get("tenancy_id")
    if (!tid) return
    getTenantDues(Number(tid)).then((d) => {
      const t: TenantSearchResult = {
        tenancy_id: d.tenancy_id,
        tenant_id: d.tenant_id,
        name: d.name,
        phone: d.phone,
        room_number: d.room_number,
        building_code: d.building_code,
        rent: d.rent,
        status: "active",
      }
      setTenant(t)
      setDues(d)
      const total = (d.dues || 0) + (d.deposit_due || 0)
      if (total > 0) setAmount(String(Math.round(total)))
    }).catch(() => {/* ignore */})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleTenantSelect(t: TenantSearchResult) {
    setTenant(t)
    setDues(null)
    try {
      const d = await getTenantDues(t.tenancy_id)
      setDues(d)
      const total = (d.dues || 0) + (d.deposit_due || 0)
      if (!amount && total > 0) setAmount(String(Math.round(total)))
    } catch {
      // best-effort
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

  function handleScan(result: ReceiptScanResult) {
    setScannedFile(result.file)
    // Pre-fill amount if not already entered
    if (result.ocr.amount && !amount) setAmount(String(result.ocr.amount))
    // Auto-set method
    if (result.ocr.method === "CASH") setMethod("CASH")
    else if (result.ocr.method) setMethod("UPI")
    // Store transaction ID
    if (result.ocr.transaction_id) setTransactionId(result.ocr.transaction_id)
  }

  function handleReview() {
    setError("")
    if (!tenant) { setError("Select a tenant first"); return }
    if (!amount || Number(amount) <= 0) { setError("Enter a valid amount"); return }
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

      // Auto-upload scanned receipt immediately
      if (scannedFile) {
        try {
          const up = await uploadReceipt(result.payment_id, scannedFile)
          setReceiptUrl(up.receipt_url)
          if (up.transaction_id) setTransactionId(up.transaction_id)
        } catch {
          // receipt upload failure doesn't block the success screen
        }
      }

      // Waive the remaining balance if toggled
      if (waiveRemaining && balanceAfter !== null && balanceAfter > 0) {
        try {
          await patchAdjustment(tenant.tenancy_id, -Math.round(balanceAfter), "Waived rounding difference")
        } catch {
          // non-critical — payment already saved
        }
      }

      setShowConfirm(false)
      setSuccess(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  const totalDues = dues ? (dues.dues || 0) + (dues.deposit_due || 0) : 0
  const balanceAfter = dues ? totalDues - Number(amount || 0) : null

  function resetForm() {
    setSuccess(false); setTenant(null); setDues(null); setAmount(""); setNotes("")
    setScannedFile(null); setReceiptUrl(null); setTransactionId(null); setLastPaymentId(null)
    setWaiveRemaining(false)
  }

  if (success) {
    return (
      <main className="min-h-screen bg-bg flex flex-col items-center px-6 gap-5 pt-16 pb-32">
        <div className="fixed top-0 left-0 right-0 z-10 px-5 pt-10 bg-bg border-b border-border">
          <PageHeader title="Payment Saved" backHref="/" />
        </div>
        <div className="w-20 h-20 rounded-full bg-tile-green flex items-center justify-center text-4xl">✓</div>
        <div className="text-center">
          <h1 className="text-xl font-extrabold text-ink">Payment Saved!</h1>
          <p className="text-sm text-ink-muted mt-1">Synced to Supabase + Ops Sheet</p>
        </div>
        {tenant && (
          <div className="w-full max-w-sm bg-surface rounded-card border border-border p-4 flex flex-col gap-2">
            <Row label="Tenant" value={tenant.name} />
            <Row label="Room" value={`${tenant.room_number} · ${tenant.building_code}`} />
            <Row label="Amount" value={rupee(Number(amount))} pink />
            <Row label="Method" value={method} />
            {dues && (
              <Row
                label="Balance"
                value={balanceAfter !== null && balanceAfter <= 0 ? "₹0 (Cleared)" : `${rupee(Math.max(0, balanceAfter ?? 0))} remaining`}
              />
            )}
          </div>
        )}

        {/* Receipt status */}
        {receiptUrl ? (
          <div className="w-full max-w-sm flex flex-col gap-1.5">
            <div className="flex items-center gap-2 px-4 py-2.5 rounded-pill bg-tile-green border border-[#C5E8D0]">
              <span className="text-status-paid text-sm font-semibold">Receipt saved ✓</span>
            </div>
            {transactionId && (
              <div className="flex items-center gap-2 px-4 py-2 rounded-pill bg-blue-50 border border-blue-200">
                <span className="text-blue-500 text-xs font-semibold">Ref</span>
                <span className="text-blue-700 text-xs font-mono font-semibold">{transactionId}</span>
              </div>
            )}
          </div>
        ) : (
          /* No receipt scanned on form — allow upload now */
          lastPaymentId !== null && (
            <ReceiptScanner
              paymentId={lastPaymentId}
              onUploaded={(url, txn) => { setReceiptUrl(url); if (txn) setTransactionId(txn) }}
            />
          )
        )}

        <div className="flex gap-3 w-full max-w-sm">
          <button onClick={resetForm} className="flex-1 rounded-pill border border-border-strong py-3 text-ink font-semibold text-sm">
            + New
          </button>
          <button onClick={() => router.push("/")} className="flex-1 rounded-pill bg-brand-pink py-3 text-white font-bold text-sm">
            ← Home
          </button>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="px-5 pt-12 bg-surface border-b border-border">
        <PageHeader
          title="Collect Payment"
          right={
            <div className="flex items-center gap-2">
              <button
                onClick={() => router.push("/payments/history")}
                className="flex items-center gap-1 px-3 py-1.5 rounded-pill border border-border-strong text-xs font-semibold text-ink-muted"
              >History</button>
              <button
                onClick={() => setShowVoice(true)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-pill bg-brand-pink text-white text-xs font-bold shadow"
              >🎙 Hey Kozzy</button>
            </div>
          }
        />
      </div>

      <div className="px-4 pt-4 pb-52 flex flex-col gap-4 max-w-lg mx-auto">
        {/* Tenant */}
        <div className="bg-surface rounded-card p-4 border border-border">
          <TenantSearch onSelect={handleTenantSelect} defaultValue={voiceHint} placeholder="Search by name, room, phone…" />
        </div>

        {/* Dues preview */}
        {dues && (() => {
          const totalOutstanding = (dues.dues || 0) + (dues.deposit_due || 0)
          return (
            <div className="bg-surface rounded-card p-4 border border-border">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-xs text-ink-muted font-medium">Outstanding this month</p>
                  {totalOutstanding > 0 ? (
                    <p className="text-lg font-extrabold mt-0.5 text-status-warn">
                      {rupee(totalOutstanding)} due
                    </p>
                  ) : (
                    <p className="text-lg font-extrabold mt-0.5 text-status-paid">No dues ✓</p>
                  )}
                </div>
                {dues.last_payment_date && dues.adjustment >= 0 && (
                  <div className="text-right">
                    <p className="text-xs text-ink-muted">Last paid</p>
                    <p className="text-xs font-semibold text-ink">{rupee(dues.last_payment_amount ?? 0)}</p>
                  </div>
                )}
              </div>
              {totalOutstanding > 0 && dues.deposit_due > 0 && (
                <div className="mt-2 flex gap-3">
                  {dues.dues > 0 && <span className="text-[11px] text-ink-muted">Rent {rupee(dues.dues)}</span>}
                  <span className="text-[11px] text-ink-muted">Deposit {rupee(dues.deposit_due)}</span>
                </div>
              )}
            </div>
          )
        })()}

        {/* Numpad */}
        <Numpad value={amount} onChange={setAmount} suggestAmounts={dues && ((dues.dues || 0) + (dues.deposit_due || 0)) > 0 ? [Math.round((dues.dues || 0) + (dues.deposit_due || 0))] : []} />

        {/* Live summary + waive toggle */}
        {dues && totalDues > 0 && Number(amount) > 0 && (
          <div className="bg-surface rounded-card p-4 border border-border flex flex-col gap-2">
            {[
              { label: "Total outstanding", value: totalDues, muted: true, warn: false },
              { label: "Collecting now",    value: Number(amount), muted: false, warn: false },
              { label: "Remaining after",   value: Math.max(0, balanceAfter ?? 0), muted: true, warn: (balanceAfter ?? 0) > 0 },
            ].map(({ label, value, muted, warn }) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-[11px] text-ink-muted">{label}</span>
                <span className={`text-[11px] font-bold ${warn ? "text-status-due" : muted ? "text-ink-muted" : "text-ink"}`}>
                  {rupee(value)}
                </span>
              </div>
            ))}
            {balanceAfter !== null && balanceAfter > 0 && balanceAfter <= 500 && (
              <button
                type="button"
                onClick={() => setWaiveRemaining((v) => !v)}
                className={`mt-1 flex items-center justify-between px-3 py-2 rounded-tile border-2 transition-colors ${waiveRemaining ? "border-brand-pink bg-tile-pink" : "border-border-strong bg-bg"}`}
              >
                <span className={`text-xs font-semibold ${waiveRemaining ? "text-brand-pink" : "text-ink-muted"}`}>
                  Waive {rupeeExact(balanceAfter)} remaining
                </span>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-pill ${waiveRemaining ? "bg-brand-pink text-white" : "bg-border-strong text-ink-muted"}`}>
                  {waiveRemaining ? "ON" : "OFF"}
                </span>
              </button>
            )}
          </div>
        )}

        {/* Method */}
        <div className="bg-surface rounded-card p-4 border border-border">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Payment Method</p>
          <div className="grid grid-cols-2 gap-2">
            {METHODS.map((m) => (
              <button key={m.value} type="button" onClick={() => setMethod(m.value)}
                className={`rounded-tile py-2.5 text-center border-2 transition-colors ${method === m.value ? "border-brand-pink bg-tile-pink" : "border-border-strong bg-bg"}`}>
                <div className="text-lg">{m.icon}</div>
                <div className={`text-[10px] font-bold mt-1 ${method === m.value ? "text-brand-pink" : "text-ink"}`}>{m.label}</div>
              </button>
            ))}
          </div>
        </div>

        {/* For type + period */}
        <div className="bg-surface rounded-card p-4 border border-border">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Payment For</p>
          <div className="flex gap-2 flex-wrap">
            {FOR_TYPES.map((f) => (
              <button key={f.value} type="button" onClick={() => { setForType(f.value); if (f.value === "deposit" || f.value === "booking") setMethod("UPI") }}
                className={`rounded-pill px-3 py-1.5 text-xs font-semibold border transition-colors ${forType === f.value ? "bg-brand-pink text-white border-brand-pink" : "bg-bg text-ink border-border-strong"}`}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="mt-3">
            <p className="text-xs text-ink-muted font-medium mb-2">Period</p>
            <div ref={monthScrollRef} className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: "none" }}>
              {Array.from({ length: 12 }, (_, idx) => {
                const todayIdx = new Date().getMonth()
                const val = `${new Date().getFullYear()}-${String(idx + 1).padStart(2, "0")}`
                const isSelected = periodMonth === val
                const isPast = idx < todayIdx
                return (
                  <button key={val} type="button" data-selected={isSelected} onClick={() => setPeriodMonth(val)}
                    className={`flex-shrink-0 rounded-pill px-3 py-1.5 text-xs font-semibold border-2 transition-colors ${
                      isSelected ? "bg-brand-pink text-white border-brand-pink"
                      : isPast   ? "bg-bg text-ink-muted border-border-strong opacity-50"
                      :            "bg-bg text-ink border-border-strong"
                    }`}>
                    {monthLabel(val).split(" ")[0]}
                  </button>
                )
              })}
            </div>
          </div>
          <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Note (optional)…"
            className="mt-2 w-full rounded-pill border border-border-strong bg-bg px-3 py-2 text-xs text-ink outline-none focus:border-brand-pink" />
        </div>

        {/* Receipt scanner — last step before confirming */}
        <div className="bg-surface rounded-card p-4 border border-border">
          <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Attach Receipt / Screenshot</p>
          <ReceiptScanner onScan={handleScan} compact={false} />
        </div>

        {error && <p className="text-xs text-status-warn font-medium text-center">{error}</p>}
      </div>

      {/* CTA */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-28 pt-3 bg-bg border-t border-border">
        <button onClick={handleReview} className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80">
          Review &amp; Confirm →
        </button>
      </div>

      {showConfirm && tenant && (
        <ConfirmationCard
          title="Record Payment"
          fields={[
            { label: "Tenant", value: `${tenant.name} · Room ${tenant.room_number}` },
            { label: "Amount", value: rupee(Number(amount)), highlight: true },
            { label: "Method", value: `${METHODS.find(m => m.value === method)?.icon} ${method}` },
            { label: "For", value: FOR_TYPES.find(f => f.value === forType)?.label ?? forType },
            { label: "Period", value: monthLabel(periodMonth) },
            ...(notes ? [{ label: "Note", value: notes }] : []),
            ...(transactionId ? [{ label: "Ref", value: transactionId }] : []),
            ...(balanceAfter !== null ? [{ label: "Balance after", value: balanceAfter <= 0 ? "₹0 (Cleared)" : `${rupeeExact(balanceAfter)} remaining` }] : []),
            ...(waiveRemaining && balanceAfter !== null && balanceAfter > 0 ? [{ label: "Also waiving", value: `${rupeeExact(balanceAfter)} (rounding)` }] : []),
          ]}
          onConfirm={handleConfirm}
          error={error}
          onEdit={() => { setShowConfirm(false); setError("") }}
          loading={submitting}
        />
      )}

      {showVoice && <VoiceSheet onClose={() => setShowVoice(false)} onPaymentIntent={handleVoiceIntent} />}
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
