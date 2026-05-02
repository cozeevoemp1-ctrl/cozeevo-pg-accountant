"use client"

import { useState, useEffect } from "react"
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
  rent: "Rent", deposit: "Deposit", maintenance: "Maint.",
  booking: "Advance", adjustment: "Adj.",
}

export default function PaymentHistoryPage() {
  const router = useRouter()

  // All-recent state (loaded on mount)
  const [allPayments, setAllPayments] = useState<PaymentListItem[]>([])
  const [loadingAll, setLoadingAll] = useState(true)
  const [loadError, setLoadError] = useState("")

  // Tenant-scoped state (set when user picks a tenant)
  const [selectedTenant, setSelectedTenant] = useState<TenantSearchResult | null>(null)
  const [tenantPayments, setTenantPayments] = useState<PaymentListItem[]>([])
  const [loadingTenant, setLoadingTenant] = useState(false)

  // Edit sheet state
  const [editing, setEditing] = useState<PaymentListItem | null>(null)
  const [editMethod, setEditMethod] = useState<Method>("UPI")
  const [editAmount, setEditAmount] = useState("")
  const [editNotes, setEditNotes] = useState("")
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")
  const [savedId, setSavedId] = useState<number | null>(null)

  useEffect(() => {
    getPaymentHistory(undefined, 30)
      .then(setAllPayments)
      .catch(() => setLoadError("Failed to load recent payments"))
      .finally(() => setLoadingAll(false))
  }, [])

  async function handleTenantSelect(t: TenantSearchResult) {
    setSelectedTenant(t)
    setTenantPayments([])
    setSavedId(null)
    setLoadingTenant(true)
    try {
      const list = await getPaymentHistory(t.tenancy_id, 30)
      setTenantPayments(list)
    } finally {
      setLoadingTenant(false)
    }
  }

  function clearTenant() {
    setSelectedTenant(null)
    setTenantPayments([])
  }

  function openEdit(p: PaymentListItem) {
    setEditing(p)
    setEditMethod((p.method?.toUpperCase() as Method) ?? "CASH")
    setEditAmount(String(Math.round(p.amount)))
    setEditNotes(p.notes ?? "")
    setSaveError("")
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
      if (Object.keys(body).length === 0) { setEditing(null); return }

      const updated = await editPayment(editing.payment_id, body)
      const patch = (list: PaymentListItem[]) =>
        list.map(p => p.payment_id === updated.payment_id ? { ...updated, tenant_name: p.tenant_name, room_number: p.room_number } : p)
      setAllPayments(patch)
      setTenantPayments(patch)
      setSavedId(updated.payment_id)
      setEditing(null)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  const displayList = selectedTenant ? tenantPayments : allPayments
  const isLoading = selectedTenant ? loadingTenant : loadingAll

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="fixed top-0 left-0 right-0 z-10 flex items-center gap-3 px-5 pt-10 pb-3 bg-bg border-b border-[#F0EDE9]">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-surface flex items-center justify-center text-ink-muted font-bold"
        >←</button>
        <span className="text-base font-extrabold text-ink">Payment History</span>
        <button
          onClick={() => router.push("/payment/new")}
          className="ml-auto px-3 py-1.5 rounded-pill bg-brand-pink text-white text-xs font-bold"
        >+ New</button>
      </div>

      <div className="px-4 pt-20 pb-32 flex flex-col gap-3 max-w-lg mx-auto">
        {/* Tenant filter */}
        {selectedTenant ? (
          <div className="flex items-center gap-2 bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
            <div className="flex-1 min-w-0">
              <p className="text-xs font-extrabold text-ink">{selectedTenant.name}</p>
              <p className="text-[11px] text-ink-muted">Room {selectedTenant.room_number} · {tenantPayments.length} payments</p>
            </div>
            <button
              onClick={clearTenant}
              className="shrink-0 text-xs text-ink-muted border border-[#E2DEDD] rounded-pill px-3 py-1"
            >Show all</button>
          </div>
        ) : (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-4">
            <TenantSearch
              onSelect={handleTenantSelect}
              placeholder="Filter by tenant…"
            />
          </div>
        )}

        {/* List */}
        {isLoading && <p className="text-center text-ink-muted text-sm py-8">Loading…</p>}
        {loadError && <p className="text-center text-status-warn text-sm">{loadError}</p>}

        {!isLoading && displayList.length === 0 && (
          <p className="text-center text-ink-muted text-sm py-8">No payments found</p>
        )}

        {!isLoading && displayList.length > 0 && (
          <>
            {!selectedTenant && (
              <p className="text-xs text-ink-muted font-semibold uppercase tracking-wide px-1">
                Last {displayList.length} payments — all tenants
              </p>
            )}
            {displayList.map(p => (
              <PaymentRow
                key={p.payment_id}
                payment={p}
                showTenant={!selectedTenant}
                isJustSaved={p.payment_id === savedId}
                onEdit={() => openEdit(p)}
              />
            ))}
          </>
        )}
      </div>

      {/* Edit bottom sheet */}
      {editing && (
        <div className="fixed inset-0 z-[60] flex flex-col justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setEditing(null)} />
          <div className="relative bg-bg rounded-t-2xl px-5 pt-5 pb-10 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-extrabold text-ink">Edit Payment</h2>
              <button onClick={() => setEditing(null)} className="text-ink-muted text-lg font-bold">✕</button>
            </div>

            <div className="bg-surface rounded-card p-3 border border-[#F0EDE9] text-xs text-ink-muted">
              <span className="font-semibold text-ink">
                {editing.tenant_name ?? ""}{editing.room_number ? ` · Rm ${editing.room_number}` : ""}
              </span>
              {" · "}₹{Math.round(editing.amount).toLocaleString("en-IN")}
              {" · "}{editing.payment_date}
              {editing.period_month ? ` · ${editing.period_month}` : ""}
            </div>

            <div>
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Method</p>
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
                  >{m.label}</button>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Amount (₹)</p>
              <input
                type="number"
                value={editAmount}
                onChange={e => setEditAmount(e.target.value)}
                className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink"
              />
            </div>

            <div>
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Notes</p>
              <input
                type="text"
                value={editNotes}
                onChange={e => setEditNotes(e.target.value)}
                placeholder="Optional…"
                className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink"
              />
            </div>

            {saveError && <p className="text-xs text-status-warn font-medium">{saveError}</p>}

            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full rounded-pill bg-brand-pink py-3.5 text-white font-bold text-sm disabled:opacity-50"
            >{saving ? "Saving…" : "Save Changes"}</button>
          </div>
        </div>
      )}
    </main>
  )
}

function PaymentRow({
  payment, showTenant, isJustSaved, onEdit,
}: {
  payment: PaymentListItem
  showTenant: boolean
  isJustSaved: boolean
  onEdit: () => void
}) {
  const methodColor = METHOD_COLOR[payment.method] ?? METHOD_COLOR.OTHER
  const forLabel = FOR_TYPE_LABEL[payment.for_type] ?? payment.for_type

  return (
    <div className={`bg-surface rounded-card border p-4 flex items-center gap-3 ${
      isJustSaved ? "border-status-paid bg-tile-green" : "border-[#F0EDE9]"
    }`}>
      <div className="flex-1 min-w-0">
        {showTenant && (
          <p className="text-xs font-extrabold text-ink mb-0.5">
            {payment.tenant_name ?? "—"}
            {payment.room_number ? <span className="text-ink-muted font-normal"> · Rm {payment.room_number}</span> : null}
          </p>
        )}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-sm font-extrabold text-ink">
            ₹{Math.round(payment.amount).toLocaleString("en-IN")}
          </span>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${methodColor}`}>
            {payment.method}
          </span>
          <span className="text-[10px] text-ink-muted border border-[#E2DEDD] px-2 py-0.5 rounded-full">
            {forLabel}
          </span>
        </div>
        <p className="text-[11px] text-ink-muted mt-0.5">
          {payment.payment_date}{payment.period_month ? ` · ${payment.period_month}` : ""}
          {payment.notes ? ` · ${payment.notes}` : ""}
        </p>
        {payment.upi_reference && (
          <p className="text-[10px] text-blue-600 font-medium mt-0.5">Ref: {payment.upi_reference}</p>
        )}
        {isJustSaved && <p className="text-[10px] text-status-paid font-bold mt-0.5">Updated ✓</p>}
      </div>
      <button
        onClick={onEdit}
        className="shrink-0 rounded-pill border border-[#E2DEDD] px-3 py-1.5 text-xs font-semibold text-ink"
      >Edit</button>
    </div>
  )
}
