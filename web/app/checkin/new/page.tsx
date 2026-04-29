"use client"

import { useState, useEffect, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { TenantSearch } from "@/components/forms/tenant-search"
import { ConfirmationCard } from "@/components/forms/confirmation-card"
import { Numpad } from "@/components/forms/numpad"
import {
  getCheckinPreview,
  recordCheckin,
  getTenantDues,
  TenantSearchResult,
  CheckinPreview,
} from "@/lib/api"

type Method = "CASH" | "UPI" | "BANK" | "OTHER"

const METHODS: { value: Method; label: string; icon: string }[] = [
  { value: "CASH",  label: "Cash",   icon: "💵" },
  { value: "UPI",   label: "UPI",    icon: "📱" },
  { value: "BANK",  label: "Bank",   icon: "🏦" },
  { value: "OTHER", label: "Other",  icon: "💳" },
]

function fmtINR(n: number) {
  return `₹${Math.round(n).toLocaleString("en-IN")}`
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}

function nowTime(): string {
  const now = new Date()
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`
}

function fmtDate(iso: string): string {
  if (!iso) return "—"
  const [y, m, d] = iso.split("-")
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${d} ${months[parseInt(m) - 1]} ${y}`
}

function NewCheckinPage() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const [tenant,      setTenant]      = useState<TenantSearchResult | null>(null)
  const [preview,     setPreview]     = useState<CheckinPreview | null>(null)
  const [actualDate,  setActualDate]  = useState(todayISO())
  const [checkinTime, setCheckinTime] = useState(nowTime())
  const [amount,      setAmount]      = useState("")
  const [method,      setMethod]      = useState<Method>("CASH")
  const [notes,       setNotes]       = useState("")
  const [loadingPrev, setLoadingPrev] = useState(false)

  const [showConfirm, setShowConfirm] = useState(false)
  const [submitting,  setSubmitting]  = useState(false)
  const [error,       setError]       = useState("")
  const [success,     setSuccess]     = useState(false)
  const [result,      setResult]      = useState<{ balanceRemaining: number } | null>(null)

  // Pre-fill tenant from URL param (navigated from KPI tile)
  useEffect(() => {
    const tid = searchParams.get("tenancy_id")
    if (!tid) return
    getTenantDues(Number(tid)).then((d) => {
      setTenant({
        tenancy_id: d.tenancy_id,
        tenant_id: d.tenant_id,
        name: d.name,
        phone: d.phone,
        room_number: d.room_number,
        building_code: d.building_code,
        rent: d.rent,
        status: "active",
      })
    }).catch(() => {})
  }, [searchParams])

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
    setCheckinTime(nowTime())
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
        tenancy_id:           tenant.tenancy_id,
        actual_checkin_date:  actualDate,
        amount_collected:     Number(amount || 0),
        payment_method:       method,
        notes:                notes || undefined,
        actual_checkin_time:  preview?.stay_type === "daily" ? checkinTime : undefined,
      })
      setShowConfirm(false)
      setResult({ balanceRemaining: res.balance_remaining })
      setSuccess(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Check-in failed. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  function resetForm() {
    setSuccess(false); setResult(null)
    setTenant(null); setPreview(null)
    setAmount(""); setNotes(""); setActualDate(todayISO()); setCheckinTime(nowTime())
  }

  // ── Success screen ────────────────────────────────────────────────────────
  if (success && tenant && preview) {
    const collected = Number(amount || 0)
    return (
      <main className="min-h-screen bg-bg flex flex-col items-center px-6 gap-5 pt-16 pb-32">
        <div className="fixed top-0 left-0 right-0 z-10 flex items-center gap-3 px-5 pt-10 pb-3 bg-bg border-b border-[#F0EDE9]">
          <button onClick={() => router.push("/")} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center text-ink-muted font-bold" aria-label="Home">←</button>
          <span className="text-base font-extrabold text-ink">Check-in Recorded</span>
        </div>
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
          <Row label={preview.stay_type === "daily" ? "Daily rate" : "Monthly rent"}
               value={preview.stay_type === "daily" ? `${fmtINR(preview.agreed_rent)}/day` : fmtINR(preview.agreed_rent)} />
          <Row label={preview.stay_type === "daily" ? "Total stay cost" : "First month total"} value={fmtINR(preview.first_month_total)} />
          <Row label="Advance paid" value={fmtINR(preview.booking_amount)} />
          {collected > 0 && (
            <Row label="Collected today" value={`${fmtINR(collected)} (${method})`} pink />
          )}
          <Row
            label="Balance remaining"
            value={result && result.balanceRemaining <= 0 ? "₹0 (Cleared)" : fmtINR(result?.balanceRemaining ?? 0)}
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

      <div className="px-4 pt-4 pb-52 flex flex-col gap-4 max-w-lg mx-auto">

        {/* Tenant search */}
        <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
          <TenantSearch
            key={tenant?.tenancy_id ?? "empty"}
            defaultTenant={tenant ?? undefined}
            onSelect={handleTenantSelect}
            placeholder="Search tenant by name, room, phone…"
          />
        </div>

        {/* Actual check-in date (+ time for day-wise) */}
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
            {preview?.stay_type === "daily" && (
              <div className="mt-3">
                <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">
                  Check-in Time
                </p>
                <input
                  type="time"
                  value={checkinTime}
                  onChange={(e) => setCheckinTime(e.target.value)}
                  className="w-full rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink font-semibold outline-none focus:border-brand-pink"
                />
              </div>
            )}
            {preview?.date_changed && (
              <div className="mt-3 rounded-tile bg-tile-orange px-3 py-2 text-xs text-ink font-medium">
                Agreed date was <span className="font-bold">{fmtDate(preview.agreed_checkin_date ?? "")}</span>.
                Rent recalculated from actual date.
              </div>
            )}
          </div>
        )}

        {/* Booking summary */}
        {preview && !loadingPrev && preview.stay_type === "monthly" && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-3">
              First Month Breakdown
            </p>
            <div className="flex flex-col gap-1.5">
              <Row label="Monthly rent"     value={fmtINR(preview.agreed_rent)} />
              <Row label="Days billed"      value={`${fmtDate(actualDate)} → end of month`} muted />
              <Row label="Prorated rent"    value={fmtINR(preview.prorated_rent)} />
              <Row label="Security deposit" value={fmtINR(preview.security_deposit)} />
              <div className="border-t border-[#F0EDE9] pt-1.5 mt-0.5">
                <Row label="Total due (first month)" value={fmtINR(preview.first_month_total)} />
                <Row label="Advance already paid"    value={`− ${fmtINR(preview.booking_amount)}`} />
                <Row
                  label={preview.balance_due > 0 ? "Balance to collect now" : preview.overpayment > 0 ? "Credit (overpaid)" : "Fully covered"}
                  value={
                    preview.balance_due > 0
                      ? fmtINR(preview.balance_due)
                      : preview.overpayment > 0
                        ? `${fmtINR(preview.overpayment)} credit`
                        : "₹0"
                  }
                  pink={preview.balance_due > 0}
                />
              </div>
            </div>
          </div>
        )}

        {/* Day-wise stay breakdown */}
        {preview && !loadingPrev && preview.stay_type === "daily" && (
          <div className="bg-surface rounded-card p-4 border border-[#F0EDE9]">
            <div className="flex items-center gap-2 mb-3">
              <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Stay Breakdown</p>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-pill bg-tile-blue text-brand-blue">Day-wise</span>
            </div>
            <div className="flex flex-col gap-1.5">
              <Row label="Daily rate"      value={`${fmtINR(preview.daily_rate ?? 0)} / night`} />
              <Row label="Check-in"        value={`${fmtDate(actualDate)}${checkinTime ? `  ${checkinTime}` : ""}`} />
              <Row label="Check-out"       value={preview.checkout_date ? fmtDate(preview.checkout_date) : "—"} />
              <Row label="Nights"          value={`${preview.num_days ?? 0} nights`} />
              <div className="border-t border-[#F0EDE9] pt-1.5 mt-0.5">
                <Row label="Total stay cost"      value={fmtINR(preview.total_stay_amount ?? 0)} />
                <Row label="Advance already paid" value={`− ${fmtINR(preview.booking_amount)}`} />
                <Row
                  label={preview.balance_due > 0 ? "Balance to collect now" : preview.overpayment > 0 ? "Credit (overpaid)" : "Fully covered"}
                  value={
                    preview.balance_due > 0
                      ? fmtINR(preview.balance_due)
                      : preview.overpayment > 0
                        ? `${fmtINR(preview.overpayment)} credit`
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

        {/* Already checked-in warning */}
        {preview?.already_checked_in && (
          <div className="bg-[#FFF0F0] border border-status-warn rounded-card px-4 py-3">
            <p className="text-xs font-bold text-status-warn">Already checked in</p>
            <p className="text-xs text-ink-muted mt-0.5">
              {preview.name} has been in Room {preview.room_number} since {fmtDate(preview.agreed_checkin_date ?? "")}.
              This is a settled tenant — use the <strong>Payment</strong> form to collect dues instead.
            </p>
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

        {/* Method — only when collecting something */}
        {preview && Number(amount) > 0 && (
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
      <div className="fixed bottom-0 left-0 right-0 px-4 pb-28 pt-3 bg-bg border-t border-[#F0EDE9]">
        <button
          onClick={handleReview}
          disabled={!tenant || !preview || loadingPrev || !!preview?.already_checked_in}
          className="w-full max-w-lg mx-auto block rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80 disabled:opacity-40"
        >
          {preview?.already_checked_in ? "Already Checked In — Use Payment Form" : "Review & Confirm →"}
        </button>
      </div>

      {/* Confirmation overlay */}
      {showConfirm && tenant && preview && (
        <ConfirmationCard
          title="Confirm Check-in"
          fields={[
            { label: "Tenant",     value: `${tenant.name} · Room ${tenant.room_number}` },
            { label: "Check-in",   value: preview.stay_type === "daily" ? `${fmtDate(actualDate)} ${checkinTime}` : fmtDate(actualDate) },
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
          error={error}
          onEdit={() => { setShowConfirm(false); setError("") }}
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

export default function Page() {
  return (
    <Suspense>
      <NewCheckinPage />
    </Suspense>
  )
}
