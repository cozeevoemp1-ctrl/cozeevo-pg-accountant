"use client"

import { useState, useRef } from "react"
import { uploadUpiFile, getUnmatchedUpi, UpiReconcileResult } from "@/lib/api"

function monthLabel(m: string) {
  const [y, mo] = m.split("-").map(Number)
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  return `${months[mo - 1]} ${y}`
}

function inr(n: number) {
  return "Rs." + Math.round(n).toLocaleString("en-IN")
}

export function UpiReconcileTab() {
  const now = new Date()
  const [month, setMonth] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
  )
  const [account, setAccount] = useState<"HULK" | "THOR">("HULK")
  const [result, setResult] = useState<UpiReconcileResult | null>(null)
  const [unmatched, setUnmatched] = useState<Array<{ rrn: string; account: string; date: string; amount: number; payer: string; vpa: string | null }>>([])
  const [uploading, setUploading] = useState(false)
  const [loadingUnmatched, setLoadingUnmatched] = useState(false)
  const [error, setError] = useState("")
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true); setError(""); setResult(null)
    try {
      const r = await uploadUpiFile(file, account, month)
      setResult(r)
      // refresh unmatched queue
      const uq = await getUnmatchedUpi(month)
      setUnmatched(uq.unmatched)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed")
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  async function loadUnmatched() {
    setLoadingUnmatched(true); setError("")
    try {
      const uq = await getUnmatchedUpi(month)
      setUnmatched(uq.unmatched)
    } catch {
      setError("Failed to load unmatched entries")
    } finally {
      setLoadingUnmatched(false)
    }
  }

  function prevMonth() {
    const [y, mo] = month.split("-").map(Number)
    if (mo === 1) setMonth(`${y - 1}-12`)
    else setMonth(`${y}-${String(mo - 1).padStart(2, "0")}`)
  }
  function nextMonth() {
    const [y, mo] = month.split("-").map(Number)
    if (mo === 12) setMonth(`${y + 1}-01`)
    else setMonth(`${y}-${String(mo + 1).padStart(2, "0")}`)
  }

  return (
    <div className="flex flex-col gap-4 pb-8">

      {/* Month picker */}
      <div className="flex items-center justify-between bg-[#0F0E0D] rounded-pill px-5 py-3">
        <button onClick={prevMonth} className="text-[#6F655D] text-sm font-bold">←</button>
        <span className="text-white text-sm font-bold">{monthLabel(month)}</span>
        <button onClick={nextMonth} className="text-[#6F655D] text-sm font-bold">→</button>
      </div>

      {/* Upload card */}
      <div className="bg-white rounded-2xl border border-[#F0EDE9] p-4 flex flex-col gap-3">
        <p className="text-xs font-bold text-ink-muted uppercase tracking-wide">Upload Bank File</p>

        {/* Account selector */}
        <div className="flex gap-2">
          {(["HULK", "THOR"] as const).map(a => (
            <button
              key={a}
              onClick={() => setAccount(a)}
              className={`flex-1 py-2 rounded-pill text-sm font-bold border transition-colors ${
                account === a
                  ? "bg-[#EF1F9C] text-white border-[#EF1F9C]"
                  : "border-[#E2DEDD] text-ink"
              }`}
            >
              {a}
            </button>
          ))}
        </div>

        <label className={`flex items-center justify-center gap-2 rounded-pill py-3 text-sm font-semibold cursor-pointer transition-opacity ${uploading ? "opacity-50 pointer-events-none" : ""} bg-[#0F0E0D] text-white`}>
          <input ref={fileRef} type="file" accept=".xlsx,.csv" className="hidden" onChange={handleUpload} disabled={uploading} />
          {uploading ? "Processing…" : `↑ Upload ${account} File`}
        </label>

        <p className="text-[10px] text-ink-muted text-center">
          XLSX or CSV from Lakshmi UPI app — safe to re-upload (deduped by RRN)
        </p>
      </div>

      {/* Result summary */}
      {result && (
        <div className="bg-white rounded-2xl border border-[#F0EDE9] p-4 flex flex-col gap-3">
          <p className="text-xs font-bold text-ink-muted uppercase tracking-wide">
            {result.account_name} — {monthLabel(month)} Result
          </p>
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-[#E2EFDA] rounded-xl p-3 text-center">
              <p className="text-lg font-bold text-[#375623]">{result.matched_count}</p>
              <p className="text-[10px] text-[#375623] font-medium">Matched</p>
              <p className="text-[10px] text-[#375623]">{inr(result.matched_amount)}</p>
            </div>
            <div className={`rounded-xl p-3 text-center ${result.unmatched_count > 0 ? "bg-[#FCE4D6]" : "bg-[#F5F5F5]"}`}>
              <p className={`text-lg font-bold ${result.unmatched_count > 0 ? "text-[#C55A11]" : "text-ink-muted"}`}>{result.unmatched_count}</p>
              <p className={`text-[10px] font-medium ${result.unmatched_count > 0 ? "text-[#C55A11]" : "text-ink-muted"}`}>Unmatched</p>
              <p className={`text-[10px] ${result.unmatched_count > 0 ? "text-[#C55A11]" : "text-ink-muted"}`}>{inr(result.unmatched_amount)}</p>
            </div>
            <div className="bg-[#F5F5F5] rounded-xl p-3 text-center">
              <p className="text-lg font-bold text-ink-muted">{result.skipped_duplicate}</p>
              <p className="text-[10px] text-ink-muted font-medium">Skipped</p>
              <p className="text-[10px] text-ink-muted">duplicates</p>
            </div>
          </div>

          {/* Matched list */}
          {result.matched.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">Matched</p>
              {result.matched.map(e => (
                <div key={e.rrn} className="flex items-center justify-between py-1.5 border-b border-[#F0EDE9] last:border-0">
                  <div>
                    <p className="text-xs font-semibold text-ink">{e.tenant} <span className="text-ink-muted font-normal">({e.room})</span></p>
                    <p className="text-[10px] text-ink-muted">{e.payer} · {e.matched_by}</p>
                  </div>
                  <p className="text-sm font-bold text-[#375623]">{inr(e.amount)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Unmatched queue */}
      <div className="bg-white rounded-2xl border border-[#F0EDE9] p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <p className="text-xs font-bold text-ink-muted uppercase tracking-wide">Unmatched Queue</p>
          <button
            onClick={loadUnmatched}
            disabled={loadingUnmatched}
            className="text-[10px] font-semibold text-[#EF1F9C] active:opacity-70 disabled:opacity-50"
          >
            {loadingUnmatched ? "Loading…" : "Refresh"}
          </button>
        </div>

        {unmatched.length === 0 ? (
          <p className="text-xs text-ink-muted text-center py-4">
            {loadingUnmatched ? "Loading…" : "No unmatched entries — tap Refresh to check"}
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            {unmatched.map(e => (
              <div key={e.rrn} className="flex items-center justify-between py-2 border-b border-[#F0EDE9] last:border-0">
                <div>
                  <p className="text-xs font-semibold text-ink">{e.payer}</p>
                  <p className="text-[10px] text-ink-muted">{e.account} · {e.date} · {e.vpa ?? "no VPA"}</p>
                </div>
                <p className="text-sm font-bold text-[#C55A11]">{inr(e.amount)}</p>
              </div>
            ))}
            <p className="text-[10px] text-ink-muted text-center pt-1">
              Manual assignment coming soon — share RRN with Kiran to match
            </p>
          </div>
        )}
      </div>

      {error && <p className="text-[10px] text-status-warn font-medium text-center">{error}</p>}
    </div>
  )
}
