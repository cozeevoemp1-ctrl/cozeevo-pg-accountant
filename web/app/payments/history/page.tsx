"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import {
  getPaymentHistory,
  editPayment,
  TenantSearchResult,
  PaymentListItem,
  PaymentEditBody,
} from "@/lib/api"

type Method = "UPI" | "CASH" | "BANK" | "CARD" | "OTHER"

const METHODS: { value: Method; label: string }[] = [
  { value: "UPI", label: "UPI" },
  { value: "CASH", label: "Cash" },
  { value: "BANK", label: "Bank" },
  { value: "CARD", label: "Card" },
  { value: "OTHER", label: "Other" },
]

const METHOD_COLOR: Record<string, string> = {
  UPI: "bg-blue-50 text-blue-700 border-blue-200",
  CASH: "bg-green-50 text-green-700 border-green-200",
  BANK: "bg-purple-50 text-purple-700 border-purple-200",
  CARD: "bg-orange-50 text-orange-700 border-orange-200",
  OTHER: "bg-gray-100 text-gray-600 border-gray-200",
}

const FOR_TYPE_LABEL: Record<string, string> = {
  rent: "Rent", deposit: "Deposit", maintenance: "Maintenance",
  booking: "Advance", adjustment: "Adjustment",
}

export default function PaymentHistoryPage() {
  const router = useRouter()

  const [tenant, setTenant] = useState<TenantSearchResult | null>(null)
  const [payments, setPayments] = useState<PaymentListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const [editing, setEditing] = useState<PaymentListItem | null>(null)
  const [editMethod, setEditMethod] = useState<Method>("UPI")
  const [editAmount, setEditAmount] = useState("")
  const [editNotes, setEditNotes] = useState("")
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")
  const [savedId, setSavedId] = useState<number | null>(null)

  async function handleTenantSelect(t: TenantSearchResult) {
    setTenant(t)
    setPayments([])
    setError("")
    setEditing(null)
    setSavedId(null)
    setLoading(true)
    try {
      const list = await getPaymentHistory(t.tenancy_id, 30)
      setPayments(list)
    } catch {
      setError("Failed to load payment history")
    } finally {
      setLoading(false)
    }
  }

  function openEdit(p: PaymentListItem) {
    setEditing(p)
    setEditMethod((p.method?.toUpperCase() as Method) ?? "CASH")
    setEditAmount(String(Math.round(p.amount)))
    setEditNotes(p.notes ?? "")
    setSaveError("")
    setSavedId(null)
  }

  async function handleSave() {
    if (!editing) return
    setSaving(true)
    setSaveError("")
    try {
      const body: PaymentEditBody = {}
      if (editMethod !== editing.method) body.method = editMethod
      if (Number(editAmount) !== Math.round(editing.amount)) body.amount = Number(editAmount)
      if (editNotes !== (editing.notes ?? "")) body.notes = editNotes

      if (Object.keys(body).length === 0) {
        setEditing(null)
        return
      }

      const updated = await editPayment(editing.payment_id, body)
      setPayments(prev => prev.map(p => p.payment_id === updated.payment_id ? updated : p))
      setSavedId(updated.payment_id)
      setEditing(null)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="fixed top-0 left-0 right-0 z-10 flex items-center gap-3 px-5 pt-10 pb-3 bg-bg border-b border-[#F0EDE9]">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-surface flex items-center justify-center text-ink-muted font-bold"
          aria-label="Back"
        >
          ←
        </button>
        <span className="text-base font-extrabold text-ink">Payment History</span>
        <button
          onClick={() => router.push("/payment/new")}
          className="ml-auto px-3 py-1.5 rounded-pill bg-brand-pink text-white text-xs font-bold"
        >
          + New
        </button>
      </div>

      <div className="px-4 pt-20 pb-32 flex flex-col gap-4 max-w-lg mx-auto">
        {/* Tenant search */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <TenantSearch
            onSelect={handleTenantSelect}
            placeholder="Search tenant to view payments…"
          />
        </div>

        {loading && (
          <p className="text-center text-ink-muted text-sm py-6">Loading…</p>
        )}

        {error && (
          <p className="text-center text-status-warn text-sm">{error}</p>
        )}

        {tenant && !loading && payments.length === 0 && (
          <p className="text-center text-ink-muted text-sm py-6">No payments found for {tenant.name}</p>
        )}

        {payments.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-xs text-ink-muted font-semibold uppercase tracking-wide px-1">
              {tenant?.name} · Room {tenant?.room_number} · {payments.length} payments
            </p>
            {payments.map(p => (
              <PaymentRow
                key={p.payment_id}
                payment={p}
                isJustSaved={p.payment_id === savedId}
                onEdit={() => openEdit(p)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Edit bottom sheet */}
      {editing && (
        <div className="fixed inset-0 z-[60] flex flex-col justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setEditing(null)} />
          <div className="relative bg-bg rounded-t-2xl px-5 pt-5 pb-10 flex flex-col gap-4 max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-extrabold text-ink">Edit Payment</h2>
              <button onClick={() => setEditing(null)} className="text-ink-muted text-lg">✕</button>
            </div>

            {/* Summary of what's being edited */}
            <div className="bg-surface rounded-card p-3 border border-[#F0EDE9] text-xs text-ink-muted">
              <span className="font-semibold text-ink">#{editing.payment_id}</span>
              {" · "}₹{Math.round(editing.amount).toLocaleString("en-IN")}
              {" · "}{editing.payment_date}
              {editing.period_month ? ` · ${editing.period_month}` : ""}
            </div>

            {/* Method */}
            <div>
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Payment Method</p>
              <div className="flex gap-2 flex-wrap">
                {METHODS.map(m => (
                  <button
                    key={m.value}
                    onClick={() => setEditMethod(m.value)}
                    className={`rounded-pill px-4 py-2 text-xs font-bold border-2 transition-colors ${
                      editMethod === m.value
                        ? "border-brand-pink bg-tile-pink text-brand-pink"
                        : "border-[#E2DEDD] bg-bg text-ink"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Amount */}
            <div>
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Amount (₹)</p>
              <input
                type="number"
                value={editAmount}
                onChange={e => setEditAmount(e.target.value)}
                className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink"
              />
            </div>

            {/* Notes */}
            <div>
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Notes</p>
              <input
                type="text"
                value={editNotes}
                onChange={e => setEditNotes(e.target.value)}
                placeholder="Optional note…"
                className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink"
              />
            </div>

            {saveError && <p className="text-xs text-status-warn font-medium">{saveError}</p>}

            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full rounded-pill bg-brand-pink py-3.5 text-white font-bold text-sm active:opacity-80 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </div>
      )}
    </main>
  )
}

function PaymentRow({
  payment,
  isJustSaved,
  onEdit,
}: {
  payment: PaymentListItem
  isJustSaved: boolean
  onEdit: () => void
}) {
  const methodColor = METHOD_COLOR[payment.method] ?? METHOD_COLOR.OTHER
  const forLabel = FOR_TYPE_LABEL[payment.for_type] ?? payment.for_type

  return (
    <div className={`bg-surface rounded-card border p-4 flex items-center gap-3 transition-colors ${
      isJustSaved ? "border-status-paid bg-tile-green" : "border-[#F0EDE9]"
    }`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-base font-extrabold text-ink">
            ₹{Math.round(payment.amount).toLocaleString("en-IN")}
          </span>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${methodColor}`}>
            {payment.method}
          </span>
          <span className="text-[10px] text-ink-muted font-medium bg-bg border border-[#E2DEDD] px-2 py-0.5 rounded-full">
            {forLabel}
          </span>
        </div>
        <p className="text-xs text-ink-muted">
          {payment.payment_date}
          {payment.period_month ? ` · ${payment.period_month}` : ""}
          {payment.notes ? ` · ${payment.notes}` : ""}
        </p>
        {payment.upi_reference && (
          <p className="text-[10px] text-blue-600 font-medium mt-0.5">
            Ref: {payment.upi_reference}
          </p>
        )}
        {payment.receipt_url && (
          <p className="text-[10px] text-status-paid font-medium mt-0.5">Receipt saved ✓</p>
        )}
        {isJustSaved && (
          <p className="text-[10px] text-status-paid font-bold mt-0.5">Updated ✓</p>
        )}
      </div>
      <button
        onClick={onEdit}
        className="shrink-0 rounded-pill border border-[#E2DEDD] px-3 py-1.5 text-xs font-semibold text-ink active:bg-surface"
      >
        Edit
      </button>
    </div>
  )
}
