"use client"

import { useState, useRef, useEffect } from "react"
import { useRouter } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
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

type Method = "UPI" | "CASH"

const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

function rupee(n: number) {
  return "₹" + Math.round(n).toLocaleString("en-IN")
}

function MethodToggle({ value, onChange }: { value: Method; onChange: (v: Method) => void }) {
  return (
    <div className="flex rounded-lg overflow-hidden border border-[#E0DDD8] mt-1.5 h-9">
      {(["CASH", "UPI"] as Method[]).map((m) => (
        <button key={m} type="button" onClick={() => onChange(m)}
          className={`flex-1 text-xs font-bold transition-colors ${value === m ? "bg-brand-pink text-white" : "bg-surface text-ink-muted"}`}>
          {m === "CASH" ? "Cash" : "UPI"}
        </button>
      ))}
    </div>
  )
}

export default function NewPaymentPage() {
  const router = useRouter()

  const [tenant, setTenant]   = useState<TenantSearchResult | null>(null)
  const [dues, setDues]       = useState<TenantDues | null>(null)
  const [rentAmt, setRentAmt]         = useState("")
  const [depositAmt, setDepositAmt]   = useState("")
  const [advanceAmt, setAdvanceAmt]   = useState("")
  const [rentMethod, setRentMethod]   = useState<Method>("CASH")
  const [advMethod, setAdvMethod]     = useState<Method>("UPI")
  const [periodMonth, setPeriodMonth] = useState(currentMonth())
  const [notes, setNotes]             = useState("")
  const [waiveRemaining, setWaiveRemaining] = useState(false)

  const [showConfirm, setShowConfirm] = useState(false)
  const [showVoice, setShowVoice]     = useState(false)
  const [submitting, setSubmitting]   = useState(false)
  const [error, setError]             = useState("")
  const [success, setSuccess]         = useState(false)
  const [voiceHint, setVoiceHint]     = useState("")

  const [scannedFile, setScannedFile]       = useState<File | null>(null)
  const [receiptUrl, setReceiptUrl]         = useState<string | null>(null)
  const [transactionId, setTransactionId]   = useState<string | null>(null)
  const [lastPaymentId, setLastPaymentId]   = useState<number | null>(null)

  const monthScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = monthScrollRef.current?.querySelector<HTMLElement>("[data-selected=true]")
    el?.scrollIntoView({ behavior: "instant", inline: "center", block: "nearest" })
  }, [])

  // Pre-fill from ?tenancy_id=
  useEffect(() => {
    const tid = new URLSearchParams(window.location.search).get("tenancy_id")
    if (!tid) return
    getTenantDues(Number(tid)).then((d) => {
      const t: TenantSearchResult = {
        tenancy_id: d.tenancy_id, tenant_id: d.tenant_id, name: d.name,
        phone: d.phone, room_number: d.room_number, building_code: d.building_code,
        rent: d.rent, status: "active",
      }
      setTenant(t)
      prefillDues(d)
      setDues(d)
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function prefillDues(d: TenantDues) {
    if ((d.dues || 0) > 0) setRentAmt(String(Math.round(d.dues || 0)))
    if ((d.deposit_due || 0) > 0) setDepositAmt(String(Math.round(d.deposit_due || 0)))
  }

  async function handleTenantSelect(t: TenantSearchResult) {
    setTenant(t); setDues(null); setRentAmt(""); setDepositAmt(""); setAdvanceAmt("")
    try {
      const d = await getTenantDues(t.tenancy_id)
      setDues(d)
      prefillDues(d)
    } catch { /* best-effort */ }
  }

  function handleVoiceIntent(intent: PaymentIntent) {
    setShowVoice(false)
    if (intent.amount) setRentAmt(String(intent.amount))
    if (intent.method) setRentMethod((intent.method.toUpperCase() as Method) ?? "CASH")
    if (intent.tenant_room) setVoiceHint(intent.tenant_room)
    else if (intent.tenant_name) setVoiceHint(intent.tenant_name)
  }

  function handleScan(result: ReceiptScanResult) {
    setScannedFile(result.file)
    if (result.ocr.amount && !rentAmt) setRentAmt(String(result.ocr.amount))
    if (result.ocr.method === "CASH") setRentMethod("CASH")
    else if (result.ocr.method) setRentMethod("UPI")
    if (result.ocr.transaction_id) setTransactionId(result.ocr.transaction_id)
  }

  const ra = parseFloat(rentAmt) || 0
  const da = parseFloat(depositAmt) || 0
  const aa = parseFloat(advanceAmt) || 0
  const totalCollecting = ra + da + aa
  const rentDue    = dues ? Math.max(0, dues.dues || 0) : 0
  const depositDue = dues ? Math.max(0, dues.deposit_due || 0) : 0
  const totalDue   = rentDue + depositDue
  const remaining  = Math.max(0, totalDue - ra - da)

  function handleReview() {
    setError("")
    if (!tenant) { setError("Select a tenant first"); return }
    if (totalCollecting <= 0) { setError("Enter at least one amount"); return }
    setShowConfirm(true)
  }

  async function handleConfirm() {
    if (!tenant || !dues) return
    setSubmitting(true); setError("")
    try {
      let firstPaymentId: number | null = null

      if (ra > 0) {
        const r = await createPayment({
          tenant_id: dues.tenant_id, amount: ra, method: rentMethod,
          for_type: "rent", period_month: periodMonth, notes: notes || undefined,
        })
        firstPaymentId = r.payment_id
      }
      if (da > 0) {
        await createPayment({
          tenant_id: dues.tenant_id, amount: da, method: "UPI",
          for_type: "deposit", period_month: periodMonth,
        })
      }
      if (aa > 0) {
        await createPayment({
          tenant_id: dues.tenant_id, amount: aa, method: advMethod,
          for_type: "booking", period_month: periodMonth,
        })
      }

      if (scannedFile && firstPaymentId) {
        try {
          const up = await uploadReceipt(firstPaymentId, scannedFile)
          setReceiptUrl(up.receipt_url)
          if (up.transaction_id) setTransactionId(up.transaction_id)
        } catch { /* non-blocking */ }
        setLastPaymentId(firstPaymentId)
      } else if (firstPaymentId) {
        setLastPaymentId(firstPaymentId)
      }

      if (waiveRemaining && remaining > 0 && remaining <= 500) {
        try { await patchAdjustment(tenant.tenancy_id, -Math.round(remaining), "Waived rounding difference") }
        catch { /* non-critical */ }
      }

      setShowConfirm(false); setSuccess(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  function resetForm() {
    setSuccess(false); setTenant(null); setDues(null)
    setRentAmt(""); setDepositAmt(""); setAdvanceAmt("")
    setNotes(""); setScannedFile(null); setReceiptUrl(null)
    setTransactionId(null); setLastPaymentId(null); setWaiveRemaining(false)
  }

  if (success) {
    return (
      <main className="min-h-screen bg-bg flex flex-col items-center px-6 gap-5 pt-16 pb-32">
        <div className="fixed top-0 left-0 right-0 z-10 flex items-center gap-3 px-5 pt-10 pb-3 bg-bg border-b border-[#F0EDE9]">
          <button onClick={() => router.push("/")} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center text-ink-muted font-bold">←</button>
          <span className="text-base font-extrabold text-ink">Payment Saved</span>
        </div>
        <div className="w-20 h-20 rounded-full bg-tile-green flex items-center justify-center text-4xl mt-4">✓</div>
        <div className="text-center">
          <h1 className="text-xl font-extrabold text-ink">Payment Saved!</h1>
          <p className="text-sm text-ink-muted mt-1">Synced to Supabase + Ops Sheet</p>
        </div>
        {tenant && (
          <div className="w-full max-w-sm bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-2">
            <Row label="Tenant" value={`${tenant.name} · Room ${tenant.room_number}`} />
            {ra > 0 && <Row label="Rent" value={`${rupee(ra)} · ${rentMethod}`} pink />}
            {da > 0 && <Row label="Deposit" value={`${rupee(da)} · UPI`} pink />}
            {aa > 0 && <Row label="Advance" value={`${rupee(aa)} · ${advMethod}`} pink />}
            <Row label="Total collected" value={rupee(totalCollecting)} pink />
            {remaining > 0
              ? <Row label="Remaining" value={`${rupee(remaining)} still due`} />
              : <Row label="Balance" value="₹0 (Cleared)" />}
          </div>
        )}
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
        ) : lastPaymentId !== null && (
          <ReceiptScanner paymentId={lastPaymentId} onUploaded={(url, txn) => { setReceiptUrl(url); if (txn) setTransactionId(txn) }} />
        )}
        <div className="flex gap-3 w-full max-w-sm">
          <button onClick={resetForm} className="flex-1 rounded-pill border border-[#E2DEDD] py-3 text-ink font-semibold text-sm">+ New</button>
          <button onClick={() => router.push("/")} className="flex-1 rounded-pill bg-brand-pink py-3 text-white font-bold text-sm">← Home</button>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
        <button onClick={() => router.back()} className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold">←</button>
        <h1 className="text-lg font-extrabold text-ink">Collect Payment</h1>
        <button onClick={() => router.push("/payments/history")}
          className="ml-auto mr-2 flex items-center gap-1 px-3 py-1.5 rounded-pill border border-[#E2DEDD] text-xs font-semibold text-ink-muted">
          History
        </button>
        <button onClick={() => setShowVoice(true)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-pill bg-brand-pink text-white text-xs font-bold shadow">
          🎙 Hey Kozzy
        </button>
      </div>

      <div className="px-4 pt-4 pb-52 flex flex-col gap-4 max-w-lg mx-auto">

        {/* Tenant */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <TenantSearch onSelect={handleTenantSelect} defaultValue={voiceHint} placeholder="Search by name, room, phone…" />
        </div>

        {/* Two boxes — rent + deposit */}
        {tenant && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9] flex flex-col gap-4">

            {/* Rent dues box */}
            <div>
              <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">
                Rent dues (₹)
                {rentDue > 0 && <span className="text-status-due"> · {rupee(rentDue)} outstanding</span>}
              </label>
              <input
                type="number" inputMode="numeric" value={rentAmt}
                onChange={(e) => setRentAmt(e.target.value)}
                onWheel={(e) => e.currentTarget.blur()}
                placeholder="0"
                className="w-full text-xl font-bold rounded-lg bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink outline-none focus:ring-2 focus:ring-brand-pink"
              />
              <MethodToggle value={rentMethod} onChange={setRentMethod} />
            </div>

            {/* Deposit box — only if deposit is owed */}
            {depositDue > 0 && (
              <div>
                <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">
                  Deposit (₹) · <span className="text-status-due">{rupee(depositDue)} unpaid</span>
                </label>
                <input
                  type="number" inputMode="numeric" value={depositAmt}
                  onChange={(e) => setDepositAmt(e.target.value)}
                  onWheel={(e) => e.currentTarget.blur()}
                  placeholder="0"
                  className="w-full text-xl font-bold rounded-lg bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink outline-none focus:ring-2 focus:ring-brand-pink"
                />
                <p className="text-[10px] text-[#00AEED] font-bold mt-1.5">Always recorded as UPI</p>
              </div>
            )}

            {/* Advance box — always optional */}
            <div>
              <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide block mb-1">
                Advance (₹) <span className="text-ink-muted font-normal">· optional</span>
              </label>
              <input
                type="number" inputMode="numeric" value={advanceAmt}
                onChange={(e) => setAdvanceAmt(e.target.value)}
                onWheel={(e) => e.currentTarget.blur()}
                placeholder="0"
                className="w-full text-xl font-bold rounded-lg bg-[#F6F5F0] border border-[#E0DDD8] px-3 py-2.5 text-ink outline-none focus:ring-2 focus:ring-brand-pink"
              />
              <MethodToggle value={advMethod} onChange={setAdvMethod} />
            </div>

            {/* Summary */}
            {dues && (
              <div className="rounded-lg bg-[#F6F5F0] px-3 py-2.5 flex flex-col gap-1.5">
                {[
                  { label: "Total outstanding", value: totalDue,       warn: false, muted: true },
                  { label: "Collecting now",     value: totalCollecting, warn: false, muted: false },
                  { label: "Remaining after",    value: remaining,       warn: remaining > 0, muted: true },
                ].map(({ label, value, warn, muted }) => (
                  <div key={label} className="flex items-center justify-between">
                    <span className="text-[11px] text-ink-muted">{label}</span>
                    <span className={`text-[11px] font-bold ${warn ? "text-status-due" : muted ? "text-ink-muted" : "text-ink"}`}>
                      {rupee(value)}
                    </span>
                  </div>
                ))}
                {remaining > 0 && remaining <= 500 && (
                  <button type="button" onClick={() => setWaiveRemaining(v => !v)}
                    className={`mt-0.5 flex items-center justify-between px-3 py-2 rounded-lg border-2 transition-colors ${waiveRemaining ? "border-brand-pink bg-tile-pink" : "border-[#E2DEDD] bg-bg"}`}>
                    <span className={`text-xs font-semibold ${waiveRemaining ? "text-brand-pink" : "text-ink-muted"}`}>
                      Waive {rupee(remaining)} remaining
                    </span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-pill ${waiveRemaining ? "bg-brand-pink text-white" : "bg-[#E2DEDD] text-ink-muted"}`}>
                      {waiveRemaining ? "ON" : "OFF"}
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {/* Period + Notes */}
        {tenant && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs text-ink-muted font-medium mb-2">Period (for rent)</p>
            <div ref={monthScrollRef} className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: "none" }}>
              {MONTH_NAMES.map((name, idx) => {
                const todayIdx = new Date().getMonth()
                const val = `${new Date().getFullYear()}-${String(idx + 1).padStart(2, "0")}`
                const isSelected = periodMonth === val
                const isPast = idx < todayIdx
                return (
                  <button key={val} type="button" data-selected={isSelected} onClick={() => setPeriodMonth(val)}
                    className={`flex-shrink-0 rounded-pill px-3 py-1.5 text-xs font-semibold border-2 transition-colors ${
                      isSelected ? "bg-brand-pink text-white border-brand-pink"
                      : isPast   ? "bg-bg text-ink-muted border-[#E2DEDD] opacity-50"
                      :            "bg-bg text-ink border-[#E2DEDD]"
                    }`}>{name}
                  </button>
                )
              })}
            </div>
            <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="Note (optional)…"
              className="mt-3 w-full rounded-pill border border-[#E2DEDD] bg-bg px-3 py-2 text-xs text-ink outline-none focus:border-brand-pink" />
          </div>
        )}

        {/* Receipt scanner */}
        {tenant && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">Attach Receipt / Screenshot</p>
            <ReceiptScanner onScan={handleScan} compact={false} />
          </div>
        )}

        {error && <p className="text-xs text-status-warn font-medium text-center">{error}</p>}
      </div>

      {/* CTA */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-28 pt-3 bg-bg border-t border-[#F0EDE9]">
        <button onClick={handleReview}
          className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80">
          {totalCollecting > 0 ? `Review & Confirm · ${rupee(totalCollecting)}` : "Review & Confirm →"}
        </button>
      </div>

      {showConfirm && tenant && (
        <ConfirmationCard
          title="Record Payment"
          fields={[
            { label: "Tenant", value: `${tenant.name} · Room ${tenant.room_number}` },
            ...(ra > 0 ? [{ label: "Rent", value: `${rupee(ra)} · ${rentMethod}`, highlight: true }] : []),
            ...(da > 0 ? [{ label: "Deposit", value: `${rupee(da)} · UPI`, highlight: true }] : []),
            ...(aa > 0 ? [{ label: "Advance", value: `${rupee(aa)} · ${advMethod}`, highlight: true }] : []),
            { label: "Total", value: rupee(totalCollecting), highlight: true },
            { label: "Period", value: (() => { const [y, m] = periodMonth.split("-"); return `${MONTH_NAMES[parseInt(m)-1]} ${y}` })() },
            ...(notes ? [{ label: "Note", value: notes }] : []),
            ...(transactionId ? [{ label: "Ref", value: transactionId }] : []),
            { label: "Remaining after", value: remaining <= 0 ? "₹0 (Cleared)" : `${rupee(remaining)} still due` },
            ...(waiveRemaining && remaining > 0 ? [{ label: "Also waiving", value: `${rupee(remaining)} (rounding)` }] : []),
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
      <span className={`text-xs font-semibold ${pink ? "text-brand-pink" : "text-ink"}`}>{value}</span>
    </div>
  )
}
