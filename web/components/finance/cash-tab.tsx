"use client"
import { useState, useEffect, useCallback } from "react"
import {
  getCashPosition, addCashExpense, voidCashExpense, logCashCount,
  CashPosition, AddExpenseBody, LogCountBody,
} from "@/lib/api"

function fmt(n: number): string {
  return "₹" + Math.round(n).toLocaleString("en-IN")
}

function fmtShort(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 100000) return `₹${(abs / 100000).toFixed(1)}L`
  if (abs >= 1000) return `₹${(abs / 1000).toFixed(0)}K`
  return fmt(abs)
}

function prevMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number)
  if (mo === 1) return `${y - 1}-12`
  return `${y}-${String(mo - 1).padStart(2, "0")}`
}

function nextMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number)
  if (mo === 12) return `${y + 1}-01`
  return `${y}-${String(mo + 1).padStart(2, "0")}`
}

function monthLabel(m: string): string {
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  const [y, mo] = m.split("-").map(Number)
  return `${months[mo - 1]} ${y}`
}

function fmtDate(d: string): string {
  const [, mm, dd] = d.split("-")
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${months[parseInt(mm) - 1]} ${parseInt(dd)}`
}

function todayStr(): string {
  const n = new Date()
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`
}

const inputCls = "bg-[#F8F5F3] border border-[#E2DEDD] rounded-xl px-3 py-2.5 text-sm text-[#1A1614] font-medium w-full"

function Pill({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-1.5 rounded-full text-xs font-bold border transition-colors ${
        active ? "bg-[#EF1F9C] text-white border-[#EF1F9C]" : "bg-[#F0EDE9] text-[#555] border-[#E2DEDD]"
      }`}
    >
      {label}
    </button>
  )
}

function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-t-[24px] p-6 flex flex-col gap-4 max-w-lg mx-auto w-full"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-base font-extrabold text-[#1A1614]">{title}</h2>
          <button onClick={onClose} className="text-[#C0B8B4] font-bold text-xl leading-none">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

function AddExpenseSheet({ onClose, onSaved }: { onClose: () => void; onSaved: (month: string) => void }) {
  const [date, setDate] = useState(todayStr())
  const [desc, setDesc] = useState("")
  const [amount, setAmount] = useState("")
  const [paidBy, setPaidBy] = useState<AddExpenseBody["paid_by"]>("Prabhakaran")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const amt = parseFloat(amount)
    if (!desc.trim()) return setError("Description required")
    if (!amt || amt <= 0) return setError("Enter a valid amount")
    setSaving(true)
    setError("")
    try {
      await addCashExpense({ date, description: desc.trim(), amount: amt, paid_by: paidBy })
      onSaved(date.slice(0, 7))
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save")
      setSaving(false)
    }
  }

  return (
    <Sheet title="Add cash expense" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Date</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} className={inputCls} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Description</label>
          <input
            type="text" value={desc} onChange={e => setDesc(e.target.value)}
            placeholder="e.g. Water — Manoj B" className={inputCls}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Amount ₹</label>
          <input
            type="number" value={amount} onChange={e => setAmount(e.target.value)}
            placeholder="0" inputMode="numeric" className={inputCls}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Paid by</label>
          <div className="flex gap-2 flex-wrap">
            {(["Prabhakaran", "Lakshmi", "Other"] as const).map(p => (
              <Pill key={p} label={p} active={paidBy === p} onClick={() => setPaidBy(p)} />
            ))}
          </div>
        </div>
        {error && <p className="text-xs text-red-500 font-medium">{error}</p>}
        <button
          type="submit" disabled={saving}
          className="bg-[#EF1F9C] text-white rounded-xl py-3 text-sm font-extrabold mt-1 disabled:opacity-50 active:opacity-70"
        >
          {saving ? "Saving…" : "Save expense"}
        </button>
      </form>
    </Sheet>
  )
}

function LogCountSheet({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [date, setDate] = useState(todayStr())
  const [amount, setAmount] = useState("")
  const [countedBy, setCountedBy] = useState<LogCountBody["counted_by"]>("Prabhakaran")
  const [notes, setNotes] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const amt = parseFloat(amount)
    if (isNaN(amt) || amt < 0) return setError("Enter a valid amount")
    setSaving(true)
    setError("")
    try {
      const body: LogCountBody = { date, amount: amt, counted_by: countedBy }
      if (notes.trim()) body.notes = notes.trim()
      await logCashCount(body)
      onSaved()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save")
      setSaving(false)
    }
  }

  return (
    <Sheet title="Log cash count" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Date</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} className={inputCls} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Amount counted ₹</label>
          <input
            type="number" value={amount} onChange={e => setAmount(e.target.value)}
            placeholder="0" inputMode="numeric" className={inputCls}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Counted by</label>
          <div className="flex gap-2">
            {(["Prabhakaran", "Lakshmi"] as const).map(p => (
              <Pill key={p} label={p} active={countedBy === p} onClick={() => setCountedBy(p)} />
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Notes (optional)</label>
          <input
            type="text" value={notes} onChange={e => setNotes(e.target.value)}
            placeholder="e.g. Before bank deposit" className={inputCls}
          />
        </div>
        {error && <p className="text-xs text-red-500 font-medium">{error}</p>}
        <button
          type="submit" disabled={saving}
          className="bg-[#EF1F9C] text-white rounded-xl py-3 text-sm font-extrabold mt-1 disabled:opacity-50 active:opacity-70"
        >
          {saving ? "Saving…" : "Log count"}
        </button>
      </form>
    </Sheet>
  )
}

export function CashTab() {
  const now = new Date()
  const [month, setMonth] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
  )
  const [data, setData] = useState<CashPosition | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [showExpenseSheet, setShowExpenseSheet] = useState(false)
  const [showCountSheet, setShowCountSheet] = useState(false)
  const [voidTarget, setVoidTarget] = useState<number | null>(null)
  const [voiding, setVoiding] = useState(false)

  const load = useCallback(async (m: string) => {
    setLoading(true)
    setError("")
    try {
      setData(await getCashPosition(m))
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(month) }, [month, load])

  async function handleVoid(id: number) {
    if (voidTarget !== id) {
      setVoidTarget(id)
      return
    }
    setVoiding(true)
    try {
      await voidCashExpense(id)
      setVoidTarget(null)
      await load(month)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to void")
    } finally {
      setVoiding(false)
    }
  }

  const varColor = (v: number) =>
    v === 0 ? "text-[#16A34A]" : v > 0 ? "text-[#EF4444]" : "text-[#F59E0B]"

  const varLabel = (v: number) =>
    v === 0 ? "Matches" : v > 0 ? `${fmt(v)} short` : `${fmt(Math.abs(v))} over`

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between bg-[#0F0E0D] rounded-full px-5 py-3">
        <button onClick={() => setMonth(prevMonth(month))} className="text-[#6F655D] text-sm font-bold">←</button>
        <span className="text-white text-sm font-bold">{monthLabel(month)}</span>
        <button onClick={() => setMonth(nextMonth(month))} className="text-[#6F655D] text-sm font-bold">→</button>
      </div>

      {loading && <div className="py-10 text-center text-xs text-[#999]">Loading…</div>}
      {error && <p className="text-xs text-center text-red-500 font-medium">{error}</p>}

      {!loading && data && (
        <>
          <div
            className="rounded-2xl p-5 text-white"
            style={{ background: "linear-gradient(135deg, #1A1614 0%, #2d2421 100%)" }}
          >
            <p className="text-[11px] font-semibold text-[#aaa] uppercase tracking-wider mb-1">Cash in hand</p>
            <p className="text-[32px] font-extrabold leading-tight">{fmt(data.balance)}</p>
            <p className="text-xs text-[#888] mt-2">
              Collected {fmt(data.collected)} — Expenses {fmt(data.expenses_total)}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2.5">
            <div className="bg-white rounded-2xl border border-[#F0EDE9] p-3.5 flex flex-col gap-1">
              <p className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Collected</p>
              <p className="text-lg font-extrabold text-[#16A34A]">{fmtShort(data.collected)}</p>
              <p className="text-[10px] text-[#bbb]">Auto · from rent payments</p>
            </div>
            <div className="bg-white rounded-2xl border border-[#F0EDE9] p-3.5 flex flex-col gap-1">
              <p className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Expenses</p>
              <p className="text-lg font-extrabold text-[#EF4444]">{fmtShort(data.expenses_total)}</p>
              <p className="text-[10px] text-[#bbb]">
                {data.expenses.length} entr{data.expenses.length === 1 ? "y" : "ies"} logged
              </p>
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-[#F0EDE9] p-4 flex items-center justify-between gap-3">
            <div className="flex flex-col gap-0.5">
              <p className="text-[10px] font-bold text-[#999] uppercase tracking-wide">Count check</p>
              {data.last_count ? (
                <>
                  <p className="text-sm font-semibold text-[#1A1614]">
                    {fmt(data.last_count.amount)} · {fmtDate(data.last_count.date)} · {data.last_count.counted_by.split(" ")[0]}
                  </p>
                  <p className={`text-xs font-bold ${varColor(data.last_count.variance)}`}>
                    {varLabel(data.last_count.variance)}
                  </p>
                </>
              ) : (
                <p className="text-xs text-[#bbb]">No count logged yet</p>
              )}
            </div>
            <button
              onClick={() => setShowCountSheet(true)}
              className="shrink-0 text-xs font-bold text-[#EF1F9C] border border-[#EF1F9C] rounded-full px-3 py-1.5 active:opacity-70"
            >
              + Log count
            </button>
          </div>

          <p className="text-[11px] font-bold text-[#999] uppercase tracking-wider px-0.5">Cash expenses</p>
          <div className="bg-white rounded-2xl border border-[#F0EDE9] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#F0EDE9]">
              <span className="text-xs font-bold text-[#777]">
                {data.expenses.length} {data.expenses.length === 1 ? "entry" : "entries"} · {fmt(data.expenses_total)}
              </span>
              <button
                onClick={() => setShowExpenseSheet(true)}
                className="bg-[#EF1F9C] text-white rounded-full px-4 py-1.5 text-xs font-bold active:opacity-70"
              >
                + Add expense
              </button>
            </div>
            {data.expenses.length === 0 && (
              <div className="py-6 text-center text-xs text-[#bbb]">No expenses logged</div>
            )}
            {data.expenses.map(exp => (
              <div
                key={exp.id}
                className="flex items-center justify-between px-4 py-3 border-b border-[#F8F5F3] last:border-0 active:bg-[#FFF5FB] cursor-pointer"
                onClick={() => !voiding && handleVoid(exp.id)}
              >
                <div className="flex flex-col gap-0.5">
                  <span className="text-[13px] font-semibold text-[#1A1614]">{exp.description}</span>
                  <span className="text-[11px] text-[#aaa]">{fmtDate(exp.date)} · {exp.paid_by}</span>
                  {voidTarget === exp.id && (
                    <span className="text-[11px] font-bold text-[#EF4444] mt-0.5">
                      {voiding ? "Voiding…" : "Tap again to void"}
                    </span>
                  )}
                </div>
                <span className="text-[14px] font-extrabold text-[#EF4444] shrink-0 ml-2">
                  −{fmt(exp.amount)}
                </span>
              </div>
            ))}
          </div>

          <p className="text-[11px] font-bold text-[#999] uppercase tracking-wider px-0.5">Month history</p>
          <div className="bg-white rounded-2xl border border-[#F0EDE9] overflow-hidden">
            <div className="grid grid-cols-4 px-3.5 py-2 bg-[#F8F5F3] text-[10px] font-bold text-[#999] uppercase tracking-wide">
              <span>Month</span><span>Collected</span><span>Expenses</span><span>Balance</span>
            </div>
            {data.history.map(h => (
              <div key={h.month} className="grid grid-cols-4 px-3.5 py-2.5 border-t border-[#F8F5F3] text-[12px] items-center">
                <span className="text-[#1A1614] font-medium">{monthLabel(h.month).split(" ")[0]}</span>
                <span className="font-bold text-[#16A34A]">{fmtShort(h.collected)}</span>
                <span className="font-bold text-[#EF4444]">{fmtShort(h.expenses)}</span>
                <span className="font-extrabold text-[#1A1614]">{fmtShort(h.balance)}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {showExpenseSheet && (
        <AddExpenseSheet onClose={() => setShowExpenseSheet(false)} onSaved={(m) => { setMonth(m) }} />
      )}
      {showCountSheet && (
        <LogCountSheet onClose={() => setShowCountSheet(false)} onSaved={() => load(month)} />
      )}
    </div>
  )
}
