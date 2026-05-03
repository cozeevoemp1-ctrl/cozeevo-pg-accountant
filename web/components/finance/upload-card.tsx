"use client"

import { useRef, useState } from "react"
import { uploadBankCsv, FinanceUploadResult } from "@/lib/api"

interface UploadCardProps {
  onUploaded: (result: FinanceUploadResult) => void
}

export function UploadCard({ onUploaded }: UploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [account, setAccount] = useState<"THOR" | "HULK">("THOR")
  const [state, setState] = useState<"idle" | "uploading" | "done" | "error">("idle")
  const [result, setResult] = useState<FinanceUploadResult | null>(null)
  const [errorMsg, setErrorMsg] = useState("")

  async function handleFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    e.target.value = ""
    setState("uploading")
    setErrorMsg("")
    try {
      const res = await uploadBankCsv(files, account)
      setResult(res)
      setState("done")
      onUploaded(res)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Upload failed")
      setState("error")
    }
  }

  return (
    <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-3 flex flex-col gap-3">
      <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide">Bank Statement</p>

      {/* Account selector */}
      <div className="flex gap-2">
        {(["THOR", "HULK"] as const).map((a) => (
          <button
            key={a}
            type="button"
            onClick={() => setAccount(a)}
            className={`flex-1 py-2 rounded-pill text-xs font-bold border transition-colors ${
              account === a
                ? "bg-[#0F0E0D] text-white border-[#0F0E0D]"
                : "bg-surface text-ink-muted border-[#E2DEDD]"
            }`}
          >
            {a}
          </button>
        ))}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv"
        multiple
        className="hidden"
        onChange={handleFiles}
      />

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={state === "uploading"}
        className="flex items-center justify-center gap-2 rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink disabled:opacity-50 active:opacity-70"
      >
        <span>📎</span>
        <span>{state === "uploading" ? "Uploading…" : "Select CSV files"}</span>
      </button>

      {state === "done" && result && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 px-3 py-2 rounded-pill bg-tile-green border border-[#C5E8D0]">
            <span className="text-status-paid text-xs font-semibold">
              {result.new_count} transactions added ✓
            </span>
          </div>
          {result.months_affected.length > 0 && (
            <p className="text-[10px] text-ink-muted text-center">
              Updated: {result.months_affected.join(", ")}
            </p>
          )}
          {result.duplicate_count > 0 && (
            <p className="text-[10px] text-ink-muted text-center">
              {result.duplicate_count} duplicates skipped
            </p>
          )}
        </div>
      )}

      {state === "error" && (
        <p className="text-[10px] text-status-warn font-medium text-center">{errorMsg}</p>
      )}
    </div>
  )
}
