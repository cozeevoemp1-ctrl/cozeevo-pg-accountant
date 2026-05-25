"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import {
  getOperationalLogs,
  createOperationalLog,
  patchOperationalLog,
  deleteOperationalLog,
  type OperationalLogEntry,
  type OperationalLogCategory,
} from "@/lib/api"
import { Card } from "@/components/ui/card"
import { DatePickerInput } from "@/components/ui/date-picker-input"
import { DateTimePickerInput } from "@/components/ui/datetime-picker-input"
import Link from "next/link"

// ── static config ─────────────────────────────────────────────────────────────

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

interface Field {
  key:      string
  label:    string
  type:     "datetime" | "date" | "number"
  required: boolean
  hint?:    string
  placeholder?: string
}

const FIELDS: Record<OperationalLogCategory, Field[]> = {
  power_outage: [
    { key: "outage_start", label: "Outage date & time",   type: "datetime", required: true },
    { key: "outage_end",   label: "Restored date & time", type: "datetime", required: false, hint: "Leave blank if not yet restored" },
  ],
  hp_gas: [
    { key: "booking_date",   label: "Booking date",     type: "date",   required: true },
    { key: "received_date",  label: "Received date",    type: "date",   required: true },
    { key: "cylinder_count", label: "No. of cylinders", type: "number", required: true, placeholder: "e.g. 2" },
  ],
  water_tanker: [
    { key: "received_at", label: "Received date & time", type: "datetime", required: true },
    { key: "litres",      label: "Litres filled",        type: "number",   required: false, placeholder: "e.g. 5000" },
  ],
  garbage_collection: [
    { key: "informed_date",  label: "Informed date",          type: "date", required: true },
    { key: "collected_date", label: "Collected date",         type: "date", required: false, hint: "Leave blank if not yet collected" },
    { key: "completed_date", label: "Service completed date", type: "date", required: false },
  ],
}

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  })
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
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
      return [
        `Received: ${fmtDateTime(details.received_at as string)}`,
        details.litres ? `Litres: ${details.litres}` : "",
      ].filter(Boolean)
    case "garbage_collection":
      return [
        `Informed: ${fmtDate(details.informed_date as string)}`,
        details.collected_date ? `Collected: ${fmtDate(details.collected_date as string)}` : "Not yet collected",
        details.completed_date ? `Completed: ${fmtDate(details.completed_date as string)}` : "",
      ].filter(Boolean)
    default:
      return []
  }
}

// ── component ─────────────────────────────────────────────────────────────────

export default function OperationsPage() {
  const router = useRouter()

  // form state
  const [category, setCategory]     = useState<OperationalLogCategory>("power_outage")
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({})
  const [notes, setNotes]           = useState("")
  const [saving, setSaving]         = useState(false)
  const [saveError, setSaveError]   = useState("")
  const [saved, setSaved]           = useState(false)

  // logs list
  const [logs, setLogs]             = useState<OperationalLogEntry[]>([])
  const [logsLoading, setLogsLoading] = useState(true)
  const [deleteId, setDeleteId]     = useState<number | null>(null)
  const [deleting, setDeleting]     = useState(false)
  const [filter, setFilter]         = useState<OperationalLogCategory | "all">("all")
  const [editId, setEditId]         = useState<number | null>(null)
  const [editValues, setEditValues] = useState<Record<string, string>>({})
  const [editNotes, setEditNotes]   = useState("")
  const [editSaving, setEditSaving] = useState(false)

  const loadLogs = useCallback(async () => {
    setLogsLoading(true)
    try {
      const res = await getOperationalLogs(undefined, 200)
      setLogs(res.logs)
    } finally {
      setLogsLoading(false)
    }
  }, [])

  useEffect(() => { loadLogs() }, [loadLogs])

  function onCategoryChange(cat: OperationalLogCategory) {
    setCategory(cat)
    setFieldValues({})
    setSaveError("")
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaveError("")
    const details: Record<string, string | number | null> = {}
    for (const f of FIELDS[category]) {
      const val = fieldValues[f.key] ?? ""
      if (f.required && !val) {
        setSaveError(`"${f.label}" is required`)
        return
      }
      if (val) details[f.key] = f.type === "number" ? Number(val) : val as string
    }
    setSaving(true)
    try {
      const entry = await createOperationalLog({ category, details, notes: notes.trim() || undefined })
      setLogs(prev => [entry, ...prev])
      setFieldValues({})
      setNotes("")
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save")
    } finally {
      setSaving(false)
    }
  }

  function openEdit(log: OperationalLogEntry) {
    const pre: Record<string, string> = {}
    for (const [k, v] of Object.entries(log.details || {})) {
      pre[k] = v != null ? String(v) : ""
    }
    setEditValues(pre)
    setEditNotes(log.notes || "")
    setEditId(log.id)
  }

  async function handleEditSave(log: OperationalLogEntry) {
    setEditSaving(true)
    try {
      const details: Record<string, string | number | null> = {}
      for (const f of FIELDS[log.category as OperationalLogCategory]) {
        const v = editValues[f.key] ?? ""
        if (v) details[f.key] = f.type === "number" ? Number(v) : v
      }
      const updated = await patchOperationalLog(log.id, { details, notes: editNotes })
      setLogs(prev => prev.map(l => l.id === updated.id ? updated : l))
      setEditId(null)
    } catch {
      // keep form open on error
    } finally {
      setEditSaving(false)
    }
  }

  async function handleDelete() {
    if (deleteId == null) return
    setDeleting(true)
    try {
      await deleteOperationalLog(deleteId)
      setLogs(prev => prev.filter(l => l.id !== deleteId))
    } finally {
      setDeleting(false)
      setDeleteId(null)
    }
  }

  const fields = FIELDS[category]

  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">

      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.back()}
          className="w-9 h-9 rounded-full bg-[#F0EDE9] flex items-center justify-center text-ink-muted flex-shrink-0"
        >←</button>
        <div>
          <p className="text-xs text-ink-muted font-medium">Cozeevo</p>
          <h1 className="text-lg font-extrabold text-ink leading-tight">Operations Log</h1>
        </div>
      </div>

      {/* Log form */}
      <Card className="p-5">
        <p className="text-xs text-ink-muted mb-4 leading-relaxed">
          Select a category and fill in the details to log an operational event.
        </p>
        <form onSubmit={handleSave} className="flex flex-col gap-4">

          {/* Category dropdown */}
          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Category *</label>
            <div className="mt-1 relative">
              <select
                value={category}
                onChange={e => onCategoryChange(e.target.value as OperationalLogCategory)}
                className="w-full h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-3 pr-8 text-sm text-ink appearance-none focus:outline-none focus:border-brand-pink"
              >
                {ALL_CATEGORIES.map(cat => (
                  <option key={cat} value={cat}>
                    {CATEGORY_ICONS[cat]}  {CATEGORY_LABELS[cat]}
                  </option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-muted text-xs">▼</span>
            </div>
          </div>

          {/* Dynamic fields */}
          {fields.map(f => (
            <div key={f.key}>
              <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
                {f.label}{f.required && " *"}
              </label>
              {f.type === "datetime" ? (
                <DateTimePickerInput
                  value={fieldValues[f.key] ?? ""}
                  onChange={v => setFieldValues(prev => ({ ...prev, [f.key]: v }))}
                />
              ) : f.type === "date" ? (
                <DatePickerInput
                  value={fieldValues[f.key] ?? ""}
                  onChange={v => setFieldValues(prev => ({ ...prev, [f.key]: v }))}
                />
              ) : (
                <input
                  type="number"
                  value={fieldValues[f.key] ?? ""}
                  onChange={e => setFieldValues(prev => ({ ...prev, [f.key]: e.target.value }))}
                  onWheel={e => e.currentTarget.blur()}
                  placeholder={f.placeholder}
                  min="0"
                  className="mt-1 w-full h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-3 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink"
                />
              )}
              {f.hint && <p className="mt-0.5 text-[10px] text-ink-muted">{f.hint}</p>}
            </div>
          ))}

          {/* Notes */}
          <div>
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Notes</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Any additional details…"
              rows={2}
              className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-brand-pink resize-none"
            />
          </div>

          {saveError && <p className="text-xs text-status-due font-medium">{saveError}</p>}
          {saved    && <p className="text-xs text-status-paid font-semibold">Saved successfully</p>}

          <button
            type="submit"
            disabled={saving}
            className="w-full py-3 rounded-xl bg-brand-pink text-white text-sm font-bold disabled:opacity-50 active:opacity-80"
          >
            {saving ? "Saving…" : "Save log"}
          </button>
        </form>
      </Card>

      {/* Summary cards */}
      {!logsLoading && logs.length > 0 && (() => {
        const now   = new Date()
        const month = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}`
        return (
          <div>
            <h2 className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">This month</h2>
            <div className="grid grid-cols-2 gap-2">
              {ALL_CATEGORIES.map(cat => {
                const catLogs   = logs.filter(l => l.category === cat)
                const thisMonth = catLogs.filter(l => l.created_at?.startsWith(month))
                const last      = catLogs[0]
                const lastDate  = last ? fmtDate(last.created_at) : "Never"
                // category-specific extra
                let extra = ""
                if (cat === "hp_gas" && thisMonth.length) {
                  const total = thisMonth.reduce((s, l) => s + (Number(l.details.cylinder_count) || 0), 0)
                  if (total) extra = `${total} cylinders`
                }
                if (cat === "water_tanker" && thisMonth.length) {
                  const total = thisMonth.reduce((s, l) => s + (Number(l.details.litres) || 0), 0)
                  if (total) extra = `${total.toLocaleString()} L`
                }
                return (
                  <div key={cat} className="bg-surface border border-[#F0EDE9] rounded-card px-3 py-3">
                    <div className="flex items-center gap-1.5 mb-1">
                      <span className="text-base">{CATEGORY_ICONS[cat]}</span>
                      <span className="text-xs font-semibold text-ink-muted">{CATEGORY_LABELS[cat]}</span>
                    </div>
                    <p className="text-2xl font-extrabold text-ink">{thisMonth.length}</p>
                    {extra && <p className="text-xs text-brand-pink font-semibold">{extra}</p>}
                    <p className="text-[10px] text-ink-muted mt-0.5">Last: {lastDate}</p>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })()}

      {/* Filter tabs + log list */}
      <div>
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1 mb-3">
          {([["all","All"]] as [string,string][])
            .concat(ALL_CATEGORIES.map(c => [c, CATEGORY_ICONS[c] + " " + CATEGORY_LABELS[c]]))
            .map(([val, label]) => (
              <button key={val} type="button"
                onClick={() => setFilter(val as OperationalLogCategory | "all")}
                className={`flex-shrink-0 rounded-pill px-3 py-1.5 text-xs font-semibold transition-colors
                  ${filter === val ? "bg-brand-pink text-white" : "bg-surface border border-[#F0EDE9] text-ink-muted"}`}>
                {label}
              </button>
            ))}
        </div>

        {logsLoading && (
          <div className="flex flex-col gap-2">
            {[1,2,3].map(i => (
              <div key={i} className="bg-surface border border-[#F0EDE9] rounded-card p-4">
                <div className="h-3 w-32 bg-[#F0EDE9] rounded-full animate-pulse mb-2" />
                <div className="h-2.5 w-48 bg-[#F0EDE9] rounded-full animate-pulse" />
              </div>
            ))}
          </div>
        )}

        {!logsLoading && (() => {
          const visible = filter === "all" ? logs : logs.filter(l => l.category === filter)
          if (visible.length === 0) return (
            <Card className="p-6 text-center">
              <p className="text-sm text-ink-muted">
                {logs.length === 0 ? "No logs yet — use the form above to add one." : "No logs for this category."}
              </p>
            </Card>
          )
          return (
            <div className="flex flex-col gap-2">
              {visible.map(log => {
                const lines = renderDetails(log.category as OperationalLogCategory, log.details)
                return (
                  <div key={log.id} className="bg-surface border border-[#F0EDE9] rounded-card px-4 py-3">
                    <div className="flex items-start gap-3">
                      <span className="text-xl mt-0.5 flex-shrink-0">{CATEGORY_ICONS[log.category as OperationalLogCategory]}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold text-ink">{CATEGORY_LABELS[log.category as OperationalLogCategory]}</p>
                        {lines.map((line, i) => <p key={i} className="text-xs text-ink-muted mt-0.5">{line}</p>)}
                        {log.notes && <p className="text-xs text-ink-muted mt-1 italic">{log.notes}</p>}
                        <p className="text-[10px] text-ink-muted mt-1 opacity-60">
                          {fmtDateTime(log.created_at)}{log.logged_by ? ` · ${log.logged_by}` : ""}
                        </p>
                      </div>
                      <div className="flex gap-1 flex-shrink-0">
                        <button onClick={() => editId === log.id ? setEditId(null) : openEdit(log)}
                          className="text-xs px-2 py-1 rounded text-brand-pink font-semibold active:opacity-60">
                          {editId === log.id ? "Cancel" : "Edit"}
                        </button>
                        <button onClick={() => setDeleteId(log.id)}
                          className="text-ink-muted text-xs px-2 py-1 rounded active:opacity-60">✕</button>
                      </div>
                    </div>

                    {/* Inline edit form */}
                    {editId === log.id && (
                      <div className="mt-3 pt-3 border-t border-[#F0EDE9] flex flex-col gap-3">
                        {FIELDS[log.category as OperationalLogCategory].map(f => (
                          <div key={f.key}>
                            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
                              {f.label}
                            </label>
                            {f.type === "datetime" ? (
                              <DateTimePickerInput
                                value={editValues[f.key] ?? ""}
                                onChange={v => setEditValues(prev => ({ ...prev, [f.key]: v }))}
                              />
                            ) : f.type === "date" ? (
                              <DatePickerInput
                                value={editValues[f.key] ?? ""}
                                onChange={v => setEditValues(prev => ({ ...prev, [f.key]: v }))}
                              />
                            ) : (
                              <input type="number"
                                value={editValues[f.key] ?? ""}
                                onChange={e => setEditValues(prev => ({ ...prev, [f.key]: e.target.value }))}
                                onWheel={e => e.currentTarget.blur()}
                                className="mt-1 w-full h-[42px] rounded-lg border border-[#E0DDD8] bg-surface px-3 text-sm text-ink focus:outline-none focus:border-brand-pink"
                              />
                            )}
                          </div>
                        ))}
                        <div>
                          <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Notes</label>
                          <textarea value={editNotes} onChange={e => setEditNotes(e.target.value)} rows={2}
                            className="mt-1 w-full rounded-lg border border-[#E0DDD8] bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:border-brand-pink resize-none" />
                        </div>
                        <button onClick={() => handleEditSave(log)} disabled={editSaving}
                          className="w-full py-2.5 rounded-xl bg-brand-pink text-white text-sm font-bold disabled:opacity-50 active:opacity-80">
                          {editSaving ? "Saving…" : "Save changes"}
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )
        })()}
      </div>

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
              >{deleting ? "Deleting…" : "Delete"}</button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
