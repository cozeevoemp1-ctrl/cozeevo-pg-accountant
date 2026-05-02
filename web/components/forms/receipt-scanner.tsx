"use client"

import { useRef, useState } from "react"
import { ocrReceiptPreview, uploadReceipt, OcrResult } from "@/lib/api"

export interface ReceiptScanResult {
  file: File
  ocr: OcrResult
}

interface Props {
  /** Called immediately after OCR scan completes — use to pre-fill form fields */
  onScan?: (result: ReceiptScanResult) => void
  /** If provided, auto-uploads the receipt to this payment ID after scan */
  paymentId?: number | null
  /** Called after successful upload */
  onUploaded?: (receiptUrl: string, transactionId: string | null) => void
  /** Compact single-line mode (used inside forms) vs card mode (used on success screen) */
  compact?: boolean
}

export function ReceiptScanner({ onScan, paymentId, onUploaded, compact = false }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [state, setState] = useState<"idle" | "scanning" | "done" | "error">("idle")
  const [ocr, setOcr] = useState<OcrResult | null>(null)
  const [uploadedUrl, setUploadedUrl] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState("")

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    // reset input so same file can be re-selected
    e.target.value = ""

    setState("scanning")
    setErrorMsg("")
    setOcr(null)
    setUploadedUrl(null)

    try {
      // Step 1: OCR scan
      const result = await ocrReceiptPreview(file)
      setOcr(result)
      onScan?.({ file, ocr: result })

      // Step 2: if we already have a payment ID, upload immediately
      if (paymentId) {
        const up = await uploadReceipt(paymentId, file)
        setUploadedUrl(up.receipt_url)
        onUploaded?.(up.receipt_url, up.transaction_id)
      }

      setState("done")
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Scan failed")
      setState("error")
    }
  }

  if (state === "done" && uploadedUrl) {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-pill bg-tile-green border border-[#C5E8D0]">
          <span className="text-status-paid text-xs font-semibold">Receipt saved ✓</span>
        </div>
        {ocr?.transaction_id && (
          <div className="flex items-center gap-2 px-4 py-2 rounded-pill bg-blue-50 border border-blue-200">
            <span className="text-blue-500 text-[10px] font-semibold uppercase">Ref</span>
            <span className="text-blue-700 text-xs font-mono font-semibold">{ocr.transaction_id}</span>
          </div>
        )}
      </div>
    )
  }

  if (state === "done" && !uploadedUrl) {
    // OCR done, no payment ID yet — show extracted info as confirmation
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-pill bg-blue-50 border border-blue-200">
          <span className="text-blue-600 text-xs font-semibold">Screenshot scanned ✓</span>
          {ocr?.amount && (
            <span className="ml-auto text-blue-700 text-xs font-extrabold">
              ₹{ocr.amount.toLocaleString("en-IN")}
            </span>
          )}
          {ocr?.method && (
            <span className="text-blue-500 text-[10px] font-bold border border-blue-300 rounded-full px-2 py-0.5">
              {ocr.method}
            </span>
          )}
        </div>
        {ocr?.transaction_id && (
          <div className="flex items-center gap-2 px-4 py-1.5 rounded-pill bg-blue-50 border border-blue-200">
            <span className="text-blue-400 text-[10px] font-semibold uppercase">Ref</span>
            <span className="text-blue-700 text-xs font-mono">{ocr.transaction_id}</span>
          </div>
        )}
        <button
          onClick={() => { setState("idle"); setOcr(null) }}
          className="text-[10px] text-ink-muted underline text-center"
        >
          Remove
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={handleFile}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={state === "scanning"}
        className={
          compact
            ? "flex items-center gap-2 rounded-pill border border-[#E2DEDD] px-4 py-2 text-xs font-semibold text-ink-muted disabled:opacity-50 active:opacity-70"
            : "w-full flex items-center justify-center gap-2 rounded-pill border border-[#E2DEDD] py-3 text-sm font-semibold text-ink disabled:opacity-50 active:opacity-70"
        }
      >
        <span className="text-base">📎</span>
        <span>{state === "scanning" ? "Scanning…" : "Attach Receipt / Screenshot"}</span>
      </button>
      {state === "error" && (
        <p className="text-[10px] text-status-warn font-medium text-center">{errorMsg}</p>
      )}
    </div>
  )
}
