"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { getActiveNotices, NoticeItem } from "@/lib/api"
import { TenantSearch } from "@/components/forms/tenant-search"

const NOTICE_BY_DAY = 5

function fmtDate(iso: string): string {
  if (!iso) return "—"
  const [y, m, d] = iso.split("-")
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${parseInt(d)} ${months[parseInt(m) - 1]} ${y}`
}

function fmtINR(n: number): string {
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

function daysLabel(days: number): { text: string; color: string } {
  if (days < 0)  return { text: `${Math.abs(days)}d overdue`, color: "text-status-warn" }
  if (days === 0) return { text: "Last day today",            color: "text-status-warn" }
  if (days <= 3)  return { text: `${days}d left`,             color: "text-[#C25000]" }
  if (days <= 7)  return { text: `${days}d left`,             color: "text-[#F59E0B]" }
  return { text: `${days}d left`, color: "text-ink-muted" }
}

export default function NoticesPage() {
  const router = useRouter()
  const [items,      setItems]      = useState<NoticeItem[]>([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState("")
  const [showSearch, setShowSearch] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      setItems(await getActiveNotices())
    } catch {
      setError("Could not load notices")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const eligible   = items.filter(i => i.deposit_eligible)
  const forfeited  = items.filter(i => !i.deposit_eligible)

  return (
    <main className="min-h-screen bg-bg pb-32">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9] sticky top-0 z-10">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
          aria-label="Back"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-ink flex-1">Notices</h1>
        {items.length > 0 && (
          <span className="w-6 h-6 rounded-full bg-brand-pink text-white text-xs font-bold flex items-center justify-center">
            {items.length}
          </span>
        )}
        <button
          onClick={() => setShowSearch(true)}
          className="rounded-pill bg-brand-pink px-4 py-1.5 text-white text-xs font-bold active:opacity-80"
        >
          + Notice
        </button>
        <button
          onClick={load}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted text-sm font-bold"
          aria-label="Refresh"
        >
          ↻
        </button>
      </div>

      <div className="px-4 pt-4 flex flex-col gap-4 max-w-lg mx-auto">

        {loading && (
          <div className="text-center text-xs text-ink-muted py-12">Loading…</div>
        )}
        {error && (
          <div className="text-center text-xs text-status-warn py-6">{error}</div>
        )}
        {!loading && !error && items.length === 0 && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-8 text-center">
            <p className="text-sm font-semibold text-ink-muted">No tenants on notice</p>
            <p className="text-xs text-ink-muted mt-1">Tenants who gave notice will appear here</p>
          </div>
        )}

        {/* Deposit eligible — notice on/before 5th */}
        {!loading && eligible.length > 0 && (
          <section>
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">
              Deposit Eligible ({eligible.length})
            </p>
            <div className="flex flex-col gap-3">
              {eligible.map(item => <NoticeCard key={item.tenancy_id} item={item} onCheckout={() => router.push(`/checkout/new?tenancy_id=${item.tenancy_id}`)} />)}
            </div>
          </section>
        )}

        {/* Deposit forfeited — notice after 5th */}
        {!loading && forfeited.length > 0 && (
          <section>
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">
              Deposit Forfeited ({forfeited.length})
            </p>
            <div className="flex flex-col gap-3">
              {forfeited.map(item => <NoticeCard key={item.tenancy_id} item={item} onCheckout={() => router.push(`/checkout/new?tenancy_id=${item.tenancy_id}`)} />)}
            </div>
          </section>
        )}

        {/* Legend */}
        {!loading && items.length > 0 && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-3 text-xs text-ink-muted">
            <p className="font-semibold text-ink mb-1">Notice rules</p>
            <p>On/before {NOTICE_BY_DAY}th of month → deposit refunded (deposit − maintenance)</p>
            <p className="mt-0.5">After {NOTICE_BY_DAY}th → deposit forfeited, extra month charged</p>
          </div>
        )}
      </div>

      {/* Add Notice — tenant search sheet */}
      {showSearch && (
        <div className="fixed inset-0 z-50 flex flex-col justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowSearch(false)} />
          <div className="relative bg-bg rounded-t-2xl px-4 pt-4 pb-10 flex flex-col gap-4 max-w-lg mx-auto w-full">
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-extrabold text-ink">Add Notice — select tenant</p>
              <button onClick={() => setShowSearch(false)} className="text-ink-muted font-bold text-lg leading-none">✕</button>
            </div>
            <TenantSearch
              placeholder="Search by name, room, phone…"
              onSelect={(t) => {
                setShowSearch(false)
                router.push(`/tenants/${t.tenancy_id}/edit`)
              }}
            />
            <p className="text-[10px] text-ink-muted text-center">
              You'll be taken to the tenant edit page — scroll to the Notice section to set the date
            </p>
          </div>
        </div>
      )}
    </main>
  )
}

function NoticeCard({ item, onCheckout }: { item: NoticeItem; onCheckout: () => void }) {
  const days = daysLabel(item.days_remaining)
  const noticeDay = new Date(item.notice_date + "T00:00:00").getDate()
  const eligibleRefund = item.deposit_eligible
    ? Math.max(item.security_deposit - item.maintenance_fee, 0)
    : 0

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-3">
      {/* Top row: name + badges */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-ink truncate">{item.tenant_name}</p>
          <p className="text-xs text-ink-muted mt-0.5">Room {item.room_number} · {item.phone}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
            item.deposit_eligible
              ? "bg-tile-green text-status-paid"
              : "bg-tile-orange text-[#C25000]"
          }`}>
            {item.deposit_eligible ? "Deposit eligible" : "Deposit forfeited"}
          </span>
          <span className={`text-[10px] font-bold ${days.color}`}>{days.text}</span>
        </div>
      </div>

      {/* Details grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        <Detail label="Notice given" value={`${fmtDate(item.notice_date)} (${noticeDay <= NOTICE_BY_DAY ? "on time" : "late"})`} />
        <Detail label="Last day" value={fmtDate(item.expected_checkout)} />
        <Detail label="Security deposit" value={fmtINR(item.security_deposit)} />
        <Detail label="Agreed rent" value={`${fmtINR(item.agreed_rent)}/mo`} />
        {item.deposit_eligible ? (
          <Detail label="Est. refund" value={eligibleRefund > 0 ? fmtINR(eligibleRefund) : "₹0"} highlight />
        ) : (
          <Detail label="Est. refund" value="₹0 (forfeited)" warn />
        )}
      </div>

      {/* CTA */}
      <button
        onClick={onCheckout}
        className="w-full rounded-pill bg-brand-pink py-2.5 text-white font-bold text-sm active:opacity-80 mt-1"
      >
        Process Checkout →
      </button>
    </div>
  )
}

function Detail({
  label, value, highlight, warn,
}: { label: string; value: string; highlight?: boolean; warn?: boolean }) {
  return (
    <div>
      <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">{label}</p>
      <p className={`text-xs font-semibold mt-0.5 ${
        highlight ? "text-status-paid" :
        warn      ? "text-status-warn" :
        "text-ink"
      }`}>
        {value}
      </p>
    </div>
  )
}
