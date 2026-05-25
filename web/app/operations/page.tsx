"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import {
  getOperationalLogs,
  createOperationalLog,
  deleteOperationalLog,
  type OperationalLogEntry,
  type OperationalLogCategory,
  type CreateOperationalLogBody,
} from "@/lib/api"

// ── helpers ──────────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<OperationalLogCategory, string> = {
  power_outage:       "Power Outage",
  hp_gas:             "HP Gas",
  water_tanker:       "Water Tanker",
  garbage_collection: "Garbage Collection",
}

const CATEGORY_ICONS: Record<OperationalLogCategory, string> = {
  power_outage:       "⚡",
  hp_gas:             "🔥",
  water_tanker:       "💧",
  garbage_collection: "🗑",
}

const ALL_CATEGORIES: OperationalLogCategory[] = [
  "power_outage",
  "hp_gas",
  "water_tanker",
  "garbage_collection",
]

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return d.toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  })
}

function renderDetails(category: OperationalLogCategory, details: Record<string, string | number | null>): string[] {
  switch (category) {
    case "power_outage":
      return [
        `Outage: ${fmtDateTime(details.outage_start as string)}`,
        details.outage_end ? `Restored: ${fmtDateTime(details.outage_end as string)}` : "Not yet restored",
      ]
    case "hp_gas":
      return [
        `Booked: ${fmtDate(details.booking_date as string)}`,
        `Received: ${fmtDate(details.received_date as string)}`,
        `Cylinders: ${details.cylinder_count}`,
      ]
    case "water_tanker":
      return [`Received: ${fmtDateTime(details.received_at as string)}`]
    case "garbage_collection":
      return [
        `Informed: ${fmtDate(details.informed_date as string)}`,
        details.collected_date ? `Collected: ${fmtDate(details.collected_date as string)}` : "Not yet collected",
        details.completed_date ? `Completed: ${fmtDate(details.completed_date as string)}` : "",
      ].filter(Boolean)
    default:
      return Object.entries(details).map(([k, v]) => `${k}: ${v}`)
  }
}

// ── form field definitions ────────────────────────────────────────────────────

interface Field {
  key: string
  label: string
  type: "datetime-local" | "date" | "number" | "text"
  required: boolean
}

const FIELDS: Record<OperationalLogCategory, Field[]> = {
  power_outage: [
    { key: "outage_start", label: "Outage date & time",  type: "datetime-local", required: true },
    { key: "outage_end",   label: "Restored date & time (if known)", type: "datetime-local", required: false },
  ],
  hp_gas: [
    { key: "booking_date",   label: "Booking date",   type: "date",   required: true },
    { key: "received_date",  label: "Received date",  type: "date",   required: true },
    { key: "cylinder_count", label: "No. of cylinders", type: "number", required: true },
  ],
  water_tanker: [
    { key: "received_at", label: "Received date & time", type: "datetime-local", required: true },
  ],
  garbage_collection: [
    { key: "informed_date",  label: "Informed date",  type: "date", required: true },
    { key: "collected_date", label: "Collected date", type: "date", required: false },
    { key: "completed_date", label: "Service completed date", type: "date", required: false },
  ],
}

// ── component ─────────────────────────────────────────────────────────────────

export default function OperationsPage() {
  const router = useRouter()

  const [logs, setLogs]           = useState<OperationalLogEntry[]>([])
  const [loading, setLoading]     = useState(true)
  const [fetchError, setFetchError] = useState("")
  const [filter, setFilter]       = useState<OperationalLogCategory | "">("")

  // add modal
  const [showModal, setShowModal] = useState(false)
  const [selCategory, setSelCategory] = useState<OperationalLogCategory>("power_outage")
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({})
  const [notes, setNotes]         = useState("")
  const [saving, setSaving]       = useState(false)
  const [saveError, setSaveError] = useState("")

  // delete confirm
  const [deleteId, setDeleteId]   = useState<number | null>(null)
  const [deleting, setDeleting]   = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setFetchError("")
    try {
      const cat = filter || undefined
      const res = await getOperationalLogs(cat as OperationalLogCategory | undefined, 100)
      setLogs(res.logs)
    } catch {
      setFetchError("Could not load logs")
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { load() }, [load])

  function openModal() {
    setSelCategory("power_outage")
    setFieldValues({})
    setNotes("")
    setSaveError("")
    setShowModal(true)
  }

  function onCategoryChange(cat: OperationalLogCategory) {
    setSelCategory(cat)
    setFieldValues({})
  }

  async function handleSave() {
    setSaving(true)
    setSaveError("")
    const details: Record<string, string | number | null> = {}
    for (const f of FIELDS[selCategory]) {
      const val = fieldValues[f.key] ?? ""
      if (f.required && !val) {
        setSaveError(`"${f.label}" is required`)
        setSaving(false)
        return
      }
      if (val) {
        details[f.key] = f.type === "number" ? Number(val) : val
      }
    }
    const body: CreateOperationalLogBody = {
      category: selCategory,
      details,
      notes: notes.trim() || undefined,
    }
    try {
      const entry = await createOperationalLog(body)
      setLogs(prev => [entry, ...prev])
      setShowModal(false)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save")
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (deleteId == null) return
    setDeleting(true)
    try {
      await deleteOperationalLog(deleteId)
      setLogs(prev => prev.filter(l => l.id !== deleteId))
      setDeleteId(null)
    } catch {
      // ignore — just close
      setDeleteId(null)
    } finally {
      setDeleting(false)
    }
  }

  // ── render ──────────────────────────────────────────────────────────────────

  return (
    <main className="min-h-screen bg-bg">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold flex-shrink-0"
          aria-label="Back"
        >←</button>
        <div className="flex-1">
          <p className="text-xs text-ink-muted font-medium">Cozeevo</p>
          <h1 className="text-lg font-extrabold text-ink leading-tight">Operations Log</h1>
        </div>
        <button
          onClick={openModal}
          className="rounded-pill bg-brand-pink px-4 py-2 text-white text-xs font-bold active:opacity-80"
        >
          + Log
        </button>
      </div>

      {/* Category filter tabs */}
      <div className="flex gap-2 px-4 pt-3 pb-1 overflow-x-auto no-scrollbar">
        <button
          onClick={() => setFilter("")}
          className={`flex-shrink-0 rounded-pill px-3 py-1.5 text-xs font-semibold transition-colors ${
            filter === "" ? "bg-brand-pink text-white" : "bg-surface border border-[#F0EDE9] text-ink-muted"
          }`}
        >All</button>
        {ALL_CATEGORIES.map(cat => (
          <button
            key={cat}
            onClick={() => setFilter(cat)}
            className={`flex-shrink-0 rounded-pill px-3 py-1.5 text-xs font-semibold transition-colors ${
              filter === cat ? "bg-brand-pink text-white" : "bg-surface border border-[#F0EDE9] text-ink-muted"
            }`}
          >
            {CATEGORY_ICONS[cat]} {CATEGORY_LABELS[cat]}
          </button>
        ))}
      </div>

      {/* Log list */}
      <div className="px-4 pt-3 pb-32 flex flex-col gap-2 max-w-lg mx-auto">
        {loading && (
          <div className="flex flex-col gap-2 mt-2">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-surface rounded-card border border-[#F0EDE9] p-4">
                <div className="h-3.5 w-32 bg-[#F0EDE9] rounded-full animate-pulse mb-2" />
                <div className="h-2.5 w-48 bg-[#F0EDE9] rounded-full animate-pulse" />
              </div>
            ))}
          </div>
        )}

        {!loading && fetchError && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-6 text-center mt-4">
            <p className="text-sm text-status-warn">{fetchError}</p>
            <button onClick={load} className="mt-3 text-xs text-brand-pink font-semibold">Retry</button>
          </div>
        )}

        {!loading && !fetchError && logs.length === 0 && (
          <div className="bg-surface rounded-card border border-[#F0EDE9] p-8 flex flex-col items-center gap-2 mt-4">
            <p className="text-sm font-semibold text-ink">No logs yet</p>
            <p className="text-xs text-ink-muted">Tap + Log to record an event</p>
          </div>
        )}

        {!loading && !fetchError && logs.map(log => {
          const lines = renderDetails(log.category as OperationalLogCategory, log.details)
          return (
            <div key={log.id} className="bg-surface rounded-card border border-[#F0EDE9] p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-base">{CATEGORY_ICONS[log.category as OperationalLogCategory]}</span>
                    <span className="text-sm font-bold text-ink">
                      {CATEGORY_LABELS[log.category as OperationalLogCategory]}
                    </span>
                  </div>
                  {lines.map((line, i) => (
                    <p key={i} className="text-xs text-ink-muted mt-0.5">{line}</p>
                  ))}
                  {log.notes && (
                    <p className="text-xs text-ink-muted mt-1 italic">{log.notes}</p>
                  )}
                  <p className="text-xs text-ink-muted mt-1 opacity-60">
                    {fmtDateTime(log.created_at)}
                    {log.logged_by ? ` · ${log.logged_by}` : ""}
                  </p>
                </div>
                <button
                  onClick={() => setDeleteId(log.id)}
                  className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-full text-ink-muted text-xs hover:bg-[#F0EDE9] active:opacity-70"
                  aria-label="Delete"
                >✕</button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Add Log Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex flex-col justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowModal(false)} />
          <div className="relative bg-surface rounded-t-2xl px-5 pt-5 pb-8 max-h-[90vh] overflow-y-auto">
            {/* drag handle */}
            <div className="w-10 h-1 bg-[#D9D9D9] rounded-full mx-auto mb-4" />
            <h2 className="text-base font-extrabold text-ink mb-4">Log Event</h2>

            {/* Category select */}
            <label className="block text-xs font-semibold text-ink-muted mb-1">Category</label>
            <select
              value={selCategory}
              onChange={e => onCategoryChange(e.target.value as OperationalLogCategory)}
              className="w-full rounded-card border border-[#F0EDE9] bg-bg px-3 py-2.5 text-sm text-ink mb-4 focus:outline-none focus:ring-2 focus:ring-brand-pink"
            >
              {ALL_CATEGORIES.map(cat => (
                <option key={cat} value={cat}>{CATEGORY_ICONS[cat]} {CATEGORY_LABELS[cat]}</option>
              ))}
            </select>

            {/* Dynamic fields */}
            {FIELDS[selCategory].map(f => (
              <div key={f.key} className="mb-3">
                <label className="block text-xs font-semibold text-ink-muted mb-1">
                  {f.label}{f.required && <span className="text-status-warn ml-1">*</span>}
                </label>
                <input
                  type={f.type}
                  value={fieldValues[f.key] ?? ""}
                  onChange={e => setFieldValues(prev => ({ ...prev, [f.key]: e.target.value }))}
                  className="w-full rounded-card border border-[#F0EDE9] bg-bg px-3 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-brand-pink"
                />
              </div>
            ))}

            {/* Notes */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-ink-muted mb-1">Notes (optional)</label>
              <textarea
                value={notes}
                onChange={e => setNotes(e.target.value)}
                rows={2}
                placeholder="Any additional details..."
                className="w-full rounded-card border border-[#F0EDE9] bg-bg px-3 py-2.5 text-sm text-ink resize-none focus:outline-none focus:ring-2 focus:ring-brand-pink"
              />
            </div>

            {saveError && (
              <p className="text-xs text-status-warn mb-3">{saveError}</p>
            )}

            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full rounded-pill bg-brand-pink py-3 text-white font-bold text-sm active:opacity-80 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Log"}
            </button>
          </div>
        </div>
      )}

      {/* Delete confirm */}
      {deleteId != null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-6">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDeleteId(null)} />
          <div className="relative bg-surface rounded-card p-5 w-full max-w-sm">
            <p className="text-sm font-bold text-ink mb-1">Delete this log?</p>
            <p className="text-xs text-ink-muted mb-4">This cannot be undone.</p>
            <div className="flex gap-3">
              <button
                onClick={() => setDeleteId(null)}
                className="flex-1 rounded-pill border border-[#F0EDE9] py-2.5 text-sm font-semibold text-ink-muted"
              >Cancel</button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 rounded-pill bg-status-warn py-2.5 text-sm font-bold text-white disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
