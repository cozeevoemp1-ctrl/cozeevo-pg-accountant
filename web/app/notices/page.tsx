"use client"

import { useState, useEffect, useCallback, useMemo } from "react"
import { useRouter } from "next/navigation"
import { getActiveNotices, patchTenant, NoticeItem } from "@/lib/api"
import { TenantSearch } from "@/components/forms/tenant-search"

const NOTICE_BY_DAY = 5

function fmtDate(iso: string | null): string {
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

function monthKey(iso: string): string {
  // "2026-05-31" → "2026-05"
  return iso.slice(0, 7)
}

function monthLabel(key: string): string {
  const [, m] = key.split("-")
  return ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][parseInt(m)]
}

export default function NoticesPage() {
  const router = useRouter()
  const [items,        setItems]        = useState<NoticeItem[]>([])
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState("")
  const [showSearch,   setShowSearch]   = useState(false)
  const [searchQuery,  setSearchQuery]  = useState("")
  const [sortDir,      setSortDir]      = useState<"asc" | "desc">("asc")
  const [monthFilter,  setMonthFilter]  = useState<string>("all")
  const [typeFilter,   setTypeFilter]   = useState<"all" | "full_room" | "premium" | "male" | "female">("all")
  const [editItem,     setEditItem]     = useState<NoticeItem | null>(null)
  const [editDate,     setEditDate]     = useState("")
  const [editSaving,   setEditSaving]   = useState(false)
  const [editError,    setEditError]    = useState("")

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

  // Unique checkout months for filter chips
  const months = useMemo(() => {
    const keys = [...new Set(items.map(i => monthKey(i.expected_checkout)))]
    return keys.sort()
  }, [items])

  const filtered = useMemo(() => {
    let src = [...items]
    // Month filter
    if (monthFilter !== "all") src = src.filter(i => monthKey(i.expected_checkout) === monthFilter)
    // Type filter
    if (typeFilter === "full_room") src = src.filter(i => i.is_full_exit)
    else if (typeFilter === "premium") src = src.filter(i => i.sharing_type === "premium")
    else if (typeFilter === "male") src = src.filter(i => i.gender === "male")
    else if (typeFilter === "female") src = src.filter(i => i.gender === "female")
    // Search
    const q = searchQuery.trim().toLowerCase()
    if (q) src = src.filter(i =>
      i.tenant_name.toLowerCase().includes(q) ||
      i.room_number.toLowerCase().includes(q) ||
      i.phone.includes(q)
    )
    // Sort
    src.sort((a, b) => {
      const diff = a.days_remaining - b.days_remaining
      return sortDir === "asc" ? diff : -diff
    })
    return src
  }, [items, searchQuery, sortDir, monthFilter, typeFilter])

  // Summary stats
  const totalBeds    = useMemo(() => filtered.reduce((s, i) => s + i.beds_freed, 0), [filtered])
  const fullRooms    = useMemo(() => {
    const seen = new Set<string>()
    let count = 0
    for (const i of filtered) {
      if (i.is_full_exit && !seen.has(i.room_number)) {
        seen.add(i.room_number)
        count++
      }
    }
    return count
  }, [filtered])

  const eligible  = filtered.filter(i => i.deposit_eligible)
  const forfeited = filtered.filter(i => !i.deposit_eligible)

  function openEdit(item: NoticeItem) {
    setEditItem(item)
    setEditDate(item.expected_checkout ?? "")
    setEditError("")
  }

  async function saveEdit() {
    if (!editItem || !editDate) return
    setEditSaving(true)
    setEditError("")
    try {
      await patchTenant(editItem.tenancy_id, { expected_checkout: editDate })
      setEditItem(null)
      await load()
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : "Save failed")
    } finally {
      setEditSaving(false)
    }
  }

  async function clearNotice() {
    if (!editItem) return
    if (!confirm(`Remove notice for ${editItem.tenant_name}?`)) return
    setEditSaving(true)
    setEditError("")
    try {
      await patchTenant(editItem.tenancy_id, { notice_date: null })
      setEditItem(null)
      await load()
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : "Save failed")
    } finally {
      setEditSaving(false)
    }
  }

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

      {/* Summary bar */}
      {!loading && items.length > 0 && (
        <div className="px-4 pt-3 pb-0 max-w-lg mx-auto flex gap-3">
          <div className="flex-1 bg-surface rounded-xl border border-[#F0EDE9] px-3 py-2 text-center">
            <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">Beds freeing</p>
            <p className="text-base font-extrabold text-ink">{totalBeds}</p>
          </div>
          <div className="flex-1 bg-surface rounded-xl border border-[#F0EDE9] px-3 py-2 text-center">
            <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">Full rooms</p>
            <p className="text-base font-extrabold text-brand-pink">{fullRooms}</p>
          </div>
          <div className="flex-1 bg-surface rounded-xl border border-[#F0EDE9] px-3 py-2 text-center">
            <p className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">Tenants</p>
            <p className="text-base font-extrabold text-ink">{filtered.length}</p>
          </div>
        </div>
      )}

      {/* Search + sort + month filter row */}
      <div className="px-4 pt-3 pb-1 max-w-lg mx-auto flex items-center gap-2">
        {/* Sort toggle */}
        <button
          onClick={() => setSortDir(d => d === "asc" ? "desc" : "asc")}
          className="flex-shrink-0 h-9 w-9 rounded-xl border border-[#E5E1DC] bg-surface flex items-center justify-center text-xs font-bold text-ink-muted active:bg-bg"
          title={sortDir === "asc" ? "Soonest first" : "Latest first"}
        >
          {sortDir === "asc" ? "↑" : "↓"}
        </button>

        {/* Search */}
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Name or room…"
          className="flex-1 min-w-0 rounded-xl border border-[#E5E1DC] bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:ring-2 focus:ring-brand-pink/40"
        />

        {/* Month filter chips */}
        <div className="flex gap-1 flex-shrink-0">
          <button
            onClick={() => setMonthFilter("all")}
            className={`px-2.5 py-1.5 rounded-lg text-[11px] font-bold border transition-colors ${
              monthFilter === "all"
                ? "bg-brand-pink text-white border-brand-pink"
                : "bg-surface text-ink-muted border-[#E5E1DC]"
            }`}
          >
            All
          </button>
          {months.map(mk => (
            <button
              key={mk}
              onClick={() => setMonthFilter(monthFilter === mk ? "all" : mk)}
              className={`px-2.5 py-1.5 rounded-lg text-[11px] font-bold border transition-colors ${
                monthFilter === mk
                  ? "bg-brand-pink text-white border-brand-pink"
                  : "bg-surface text-ink-muted border-[#E5E1DC]"
              }`}
            >
              {monthLabel(mk)}
            </button>
          ))}
        </div>
      </div>

      {/* Type filter chips */}
      <div className="px-4 pt-2 pb-0 max-w-lg mx-auto flex gap-1.5 flex-wrap">
        {(["all", "full_room", "premium", "male", "female"] as const).map(f => {
          const labels: Record<string, string> = { all: "All", full_room: "Full room", premium: "Premium", male: "Male", female: "Female" }
          const colors: Record<string, string> = {
            all:       "bg-brand-pink text-white border-brand-pink",
            full_room: "bg-[#FFF3E0] text-[#C25000] border-[#F5C78A]",
            premium:   "bg-[#F3E8FF] text-[#7C3AED] border-[#D8B4FE]",
            male:      "bg-[#EFF6FF] text-[#1D4ED8] border-[#93C5FD]",
            female:    "bg-[#FDF2F8] text-[#BE185D] border-[#F9A8D4]",
          }
          const active = typeFilter === f
          return (
            <button
              key={f}
              onClick={() => setTypeFilter(f)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                active ? colors[f] : "bg-surface text-ink-muted border-[#E5E1DC]"
              }`}
            >
              {labels[f]}
            </button>
          )
        })}
      </div>

      <div className="px-4 pt-3 flex flex-col gap-4 max-w-lg mx-auto">

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
        {!loading && !error && items.length > 0 && filtered.length === 0 && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-8 text-center">
            <p className="text-sm font-semibold text-ink-muted">No matches</p>
          </div>
        )}

        {/* Deposit eligible */}
        {!loading && eligible.length > 0 && (
          <section>
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">
              Deposit Eligible ({eligible.length})
            </p>
            <div className="flex flex-col gap-3">
              {eligible.map(item => (
                <NoticeCard
                  key={item.tenancy_id}
                  item={item}
                  onCheckout={() => router.push(`/checkout/new?tenancy_id=${item.tenancy_id}`)}
                  onEdit={() => openEdit(item)}
                />
              ))}
            </div>
          </section>
        )}

        {/* Deposit forfeited */}
        {!loading && forfeited.length > 0 && (
          <section>
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">
              Deposit Forfeited ({forfeited.length})
            </p>
            <div className="flex flex-col gap-3">
              {forfeited.map(item => (
                <NoticeCard
                  key={item.tenancy_id}
                  item={item}
                  onCheckout={() => router.push(`/checkout/new?tenancy_id=${item.tenancy_id}`)}
                  onEdit={() => openEdit(item)}
                />
              ))}
            </div>
          </section>
        )}

        {/* Legend */}
        {!loading && items.length > 0 && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-3 text-xs text-ink-muted">
            <p className="font-semibold text-ink mb-1">Notice rules</p>
            <p>On/before {NOTICE_BY_DAY}th of month → vacate by month end, deposit refunded</p>
            <p className="mt-0.5">After {NOTICE_BY_DAY}th → notice applies to next month, extra month&apos;s rent charged, deposit still refundable</p>
            <p className="mt-0.5">No notice given → deposit forfeited</p>
          </div>
        )}
      </div>

      {/* Add Notice modal */}
      {showSearch && (
        <div className="fixed inset-0 flex items-center justify-center px-5" style={{ zIndex: 9999 }}>
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowSearch(false)} />
          <div className="relative bg-bg rounded-2xl px-4 pt-4 pb-5 flex flex-col gap-4 w-full max-w-sm shadow-2xl">
            <div className="flex items-center justify-between">
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
              You&apos;ll be taken to the tenant edit page — scroll to the Notice section to set the date
            </p>
          </div>
        </div>
      )}

      {/* Edit Notice modal */}
      {editItem && (
        <div className="fixed inset-0 flex items-center justify-center px-5" style={{ zIndex: 9999 }}>
          <div className="absolute inset-0 bg-black/40" onClick={() => !editSaving && setEditItem(null)} />
          <div className="relative bg-bg rounded-2xl px-4 pt-4 pb-5 flex flex-col gap-4 w-full max-w-sm shadow-2xl">
            <div className="flex items-center justify-between">
              <p className="text-sm font-extrabold text-ink">Edit Notice</p>
              <button
                onClick={() => setEditItem(null)}
                disabled={editSaving}
                className="text-ink-muted font-bold text-lg leading-none disabled:opacity-40"
              >
                ✕
              </button>
            </div>

            <div>
              <p className="text-xs font-semibold text-ink">{editItem.tenant_name}</p>
              <p className="text-xs text-ink-muted">Room {editItem.room_number} · {editItem.phone}</p>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wide">
                Checkout Date (Last Day)
              </label>
              <input
                type="date"
                value={editDate}
                onChange={e => setEditDate(e.target.value)}
                className="w-full rounded-xl border border-[#E5E1DC] bg-surface px-4 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-brand-pink/40"
              />
              <p className="text-[10px] text-ink-muted mt-0.5">
                Notice given: {editItem?.notice_date ? new Date(editItem.notice_date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—"}
              </p>
            </div>

            {editError && (
              <p className="text-xs text-status-warn">{editError}</p>
            )}

            <div className="flex gap-2">
              <button
                onClick={clearNotice}
                disabled={editSaving}
                className="flex-1 rounded-pill border border-[#E5E1DC] py-2.5 text-xs font-bold text-ink-muted active:opacity-70 disabled:opacity-40"
              >
                Remove notice
              </button>
              <button
                onClick={saveEdit}
                disabled={editSaving || !editDate}
                className="flex-1 rounded-pill bg-brand-pink py-2.5 text-white font-bold text-sm active:opacity-80 disabled:opacity-40"
              >
                {editSaving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}

function NoticeCard({
  item, onCheckout, onEdit,
}: {
  item: NoticeItem
  onCheckout: () => void
  onEdit: () => void
}) {
  const days = daysLabel(item.days_remaining)
  const noticeDay = item.notice_date ? new Date(item.notice_date + "T00:00:00").getDate() : null
  const eligibleRefund = item.deposit_eligible
    ? Math.max(item.security_deposit - item.maintenance_fee, 0)
    : 0

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-3">
      {/* Top row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <p className="text-sm font-bold text-ink truncate">{item.tenant_name}</p>
            {item.is_full_exit && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[#FFF3E0] text-[#C25000] flex-shrink-0">Full room</span>
            )}
            {item.sharing_type === "premium" && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[#F3E8FF] text-[#7C3AED] flex-shrink-0">Premium</span>
            )}
            {item.gender === "male" && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[#EFF6FF] text-[#1D4ED8] flex-shrink-0">M</span>
            )}
            {item.gender === "female" && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-[#FDF2F8] text-[#BE185D] flex-shrink-0">F</span>
            )}
          </div>
          <p className="text-xs text-ink-muted mt-0.5">
            Room {item.room_number} · {item.phone}
            {item.beds_freed > 1 && (
              <span className="ml-1.5 font-semibold text-[#7C3AED]">{item.beds_freed} beds</span>
            )}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
            item.deposit_eligible
              ? "bg-tile-green text-status-paid"
              : "bg-tile-orange text-[#C25000]"
          }`}>
            {item.deposit_eligible ? "Refundable" : "Forfeited"}
          </span>
          <span className={`text-[10px] font-bold ${days.color}`}>{days.text}</span>
        </div>
      </div>

      {/* Details grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        <Detail label="Notice given" value={item.notice_date ? `${fmtDate(item.notice_date)} (${noticeDay! <= NOTICE_BY_DAY ? "on time" : "late"})` : "No notice given"} />
        <Detail label="Last day" value={fmtDate(item.expected_checkout)} />
        <Detail label="Security deposit" value={fmtINR(item.security_deposit)} />
        <Detail label="Agreed rent" value={`${fmtINR(item.agreed_rent)}/mo`} />
        {item.deposit_eligible ? (
          <Detail label="Est. refund" value={eligibleRefund > 0 ? fmtINR(eligibleRefund) : "₹0"} highlight />
        ) : (
          <Detail label="Est. refund" value="₹0 (forfeited)" warn />
        )}
        <Detail
          label="Room occupancy"
          value={`${item.room_notice_count} of ${item.room_active_count} leaving`}
        />
      </div>

      {/* CTAs */}
      <div className="flex gap-2 mt-1">
        <button
          onClick={onEdit}
          className="flex-1 rounded-pill border border-[#E5E1DC] py-2.5 text-xs font-bold text-ink-muted active:opacity-70"
        >
          Edit notice
        </button>
        <button
          onClick={onCheckout}
          className="flex-[2] rounded-pill bg-brand-pink py-2.5 text-white font-bold text-sm active:opacity-80"
        >
          Process Checkout →
        </button>
      </div>
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
