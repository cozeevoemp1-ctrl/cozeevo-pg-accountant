"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { getOverdueTenants, sendReminder, OverdueTenant } from "@/lib/api"

function formatDate(iso: string | null): string {
  if (!iso) return "never"
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" })
}

export default function RemindersPage() {
  const router = useRouter()

  const [tenants, setTenants] = useState<OverdueTenant[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState("")

  // per-row states: "idle" | "sending" | "sent" | "error"
  const [rowStatus, setRowStatus] = useState<Record<number, "idle" | "sending" | "sent" | "error">>({})

  const [showSendAllConfirm, setShowSendAllConfirm] = useState(false)
  const [sendAllLoading, setSendAllLoading] = useState(false)
  const [sendAllResult, setSendAllResult] = useState<{ sent: number; failed: number } | null>(null)

  useEffect(() => {
    getOverdueTenants()
      .then(setTenants)
      .catch(() => setFetchError("Could not load overdue tenants"))
      .finally(() => setLoading(false))
  }, [])

  async function handleSendSingle(tenancyId: number) {
    setRowStatus((s) => ({ ...s, [tenancyId]: "sending" }))
    try {
      await sendReminder({ tenancy_id: tenancyId })
      setRowStatus((s) => ({ ...s, [tenancyId]: "sent" }))
      // update reminder_count locally
      setTenants((prev) =>
        prev.map((t) =>
          t.tenancy_id === tenancyId
            ? { ...t, reminder_count: t.reminder_count + 1, last_reminded_at: new Date().toISOString() }
            : t
        )
      )
    } catch {
      setRowStatus((s) => ({ ...s, [tenancyId]: "error" }))
    }
  }

  async function handleSendAll() {
    setSendAllLoading(true)
    try {
      const res = await sendReminder({ send_all: true })
      setSendAllResult({ sent: res.sent.length, failed: res.failed.length })
      setShowSendAllConfirm(false)
      // mark all as sent locally
      setRowStatus(
        Object.fromEntries(tenants.map((t) => [t.tenancy_id, "sent" as const]))
      )
    } catch {
      setSendAllResult({ sent: 0, failed: tenants.length })
      setShowSendAllConfirm(false)
    } finally {
      setSendAllLoading(false)
    }
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
        <h1 className="text-lg font-extrabold text-ink">Reminders</h1>
      </div>

      <div className="px-4 pt-4 pb-32 flex flex-col gap-4 max-w-lg mx-auto">
        {/* Summary banner */}
        {!loading && !fetchError && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3 flex items-center justify-between">
            <div>
              <p className="text-xs text-ink-muted">Overdue tenants</p>
              <p className="text-lg font-extrabold text-status-warn">{tenants.length}</p>
            </div>
            {tenants.length > 0 && (
              <button
                onClick={() => setShowSendAllConfirm(true)}
                className="rounded-pill bg-brand-pink px-4 py-2 text-white text-xs font-bold active:opacity-80"
              >
                Send All
              </button>
            )}
          </div>
        )}

        {/* Send All result banner */}
        {sendAllResult && (
          <div className="bg-tile-green rounded-card border border-[#F0EDE9] px-4 py-3 flex items-center justify-between">
            <p className="text-sm font-semibold text-ink">
              Sent {sendAllResult.sent}
              {sendAllResult.failed > 0 && (
                <span className="text-status-warn ml-2">· Failed {sendAllResult.failed}</span>
              )}
            </p>
            <button
              onClick={() => setSendAllResult(null)}
              className="text-ink-muted text-sm font-bold"
            >
              ✕
            </button>
          </div>
        )}

        {/* Loading skeletons */}
        {loading && (
          <div className="flex flex-col gap-2">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="bg-surface rounded-card border border-[#F0EDE9] p-4 flex justify-between items-center">
                <div className="flex flex-col gap-2">
                  <div className="h-3.5 w-28 bg-[#F0EDE9] rounded-full animate-pulse" />
                  <div className="h-2.5 w-40 bg-[#F0EDE9] rounded-full animate-pulse" />
                </div>
                <div className="flex flex-col items-end gap-2">
                  <div className="h-3.5 w-16 bg-[#F0EDE9] rounded-full animate-pulse" />
                  <div className="h-7 w-14 bg-[#F0EDE9] rounded-pill animate-pulse" />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {!loading && fetchError && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-6 text-center">
            <p className="text-sm text-status-warn">{fetchError}</p>
          </div>
        )}

        {/* Empty */}
        {!loading && !fetchError && tenants.length === 0 && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-8 flex flex-col items-center gap-3">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#22C55E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <p className="text-sm font-semibold text-ink">All clear!</p>
            <p className="text-xs text-ink-muted text-center">No tenants with overdue rent</p>
          </div>
        )}

        {/* Tenant rows */}
        {!loading && !fetchError && tenants.length > 0 && (
          <div className="flex flex-col gap-2">
            {tenants.map((t) => {
              const status = rowStatus[t.tenancy_id] ?? "idle"
              return (
                <div
                  key={t.tenancy_id}
                  className="bg-surface rounded-card border border-[#F0EDE9] p-4 flex items-center justify-between gap-3"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-ink truncate">{t.name}</p>
                    <p className="text-xs text-ink-muted mt-0.5">Room {t.room}</p>
                    <p className="text-xs text-ink-muted mt-0.5">
                      Reminded {t.reminder_count} time{t.reminder_count !== 1 ? "s" : ""}
                      {t.last_reminded_at ? ` · last ${formatDate(t.last_reminded_at)}` : ""}
                    </p>
                    {status === "sent" && (
                      <p className="text-xs text-status-paid font-semibold mt-1">Reminder sent</p>
                    )}
                    {status === "error" && (
                      <p className="text-xs text-status-warn font-semibold mt-1">Send failed — try again</p>
                    )}
                  </div>

                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <span className="text-sm font-bold text-status-warn">
                      ₹{t.dues.toLocaleString("en-IN")}
                    </span>
                    <button
                      onClick={() => handleSendSingle(t.tenancy_id)}
                      disabled={status === "sending" || status === "sent"}
                      className={`rounded-pill border px-3 py-1.5 text-xs font-bold transition-colors active:opacity-70 disabled:opacity-50 ${
                        status === "sent"
                          ? "border-[#22C55E] text-status-paid bg-tile-green"
                          : "border-[#00AEED] text-[#00AEED] bg-surface"
                      }`}
                    >
                      {status === "sending" ? "…" : status === "sent" ? "Sent" : "Send"}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Send All confirmation modal */}
      {showSendAllConfirm && (
        <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/40">
          <div className="w-full max-w-md bg-surface rounded-t-[28px] px-6 pt-5 pb-10 shadow-2xl">
            <div className="w-10 h-1 bg-[#E2DEDD] rounded-full mx-auto mb-5" />
            <h2 className="text-lg font-extrabold text-ink mb-2">Send All Reminders?</h2>
            <p className="text-sm text-ink-muted mb-6">
              This will send a WhatsApp reminder to all {tenants.length} overdue tenant{tenants.length !== 1 ? "s" : ""}.
            </p>
            <button
              onClick={handleSendAll}
              disabled={sendAllLoading}
              className="w-full rounded-pill bg-brand-pink py-4 text-white font-bold text-base active:opacity-80 disabled:opacity-50 mb-3"
            >
              {sendAllLoading ? "Sending…" : `Send to all ${tenants.length}`}
            </button>
            <button
              onClick={() => setShowSendAllConfirm(false)}
              disabled={sendAllLoading}
              className="w-full rounded-pill border border-[#E2DEDD] py-3 text-ink font-semibold text-sm active:opacity-80 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </main>
  )
}
