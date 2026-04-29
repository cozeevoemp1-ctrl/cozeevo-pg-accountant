"use client"

import { useEffect, useRef, useState } from "react"
import { useSpeechInput } from "@/lib/voice"
import {
  parseOnboardingFields,
  emptyOnboardingFields,
  type OnboardingFields,
  type OnboardingParseResult,
} from "@/lib/parse-onboarding"
import { speakText } from "@/lib/tts"

interface OnboardingVoiceSheetProps {
  onClose: () => void
  onConfirm: (fields: OnboardingFields) => void
}

type SheetStep = "recording" | "extracting" | "speaking" | "confirm" | "error"

const REQUIRED: (keyof OnboardingFields)[] = ["room_number", "tenant_phone", "monthly_rent"]

const FIELD_LABELS: Record<string, string> = {
  room_number: "Room",
  sharing_type: "Sharing",
  tenant_phone: "Phone",
  checkin_date: "Check-in",
  monthly_rent: "Rent (₹/mo)",
  security_deposit: "Deposit (₹)",
  maintenance_fee: "Maintenance (₹/mo)",
  booking_amount: "Booking advance (₹)",
  advance_mode: "Advance via",
  lock_in_months: "Lock-in (months)",
  future_rent: "Future rent (₹)",
  future_rent_after_months: "Increase after (months)",
}

const MONEY_FIELDS = new Set([
  "monthly_rent", "security_deposit", "maintenance_fee",
  "booking_amount", "future_rent",
])

function formatValue(key: string, value: unknown): string {
  if (MONEY_FIELDS.has(key)) return `₹${Number(value).toLocaleString("en-IN")}`
  return String(value)
}

export function OnboardingVoiceSheet({ onClose, onConfirm }: OnboardingVoiceSheetProps) {
  const speech = useSpeechInput()
  const [step, setStep] = useState<SheetStep>("recording")
  const [partialFields, setPartialFields] = useState<OnboardingFields>(emptyOnboardingFields())
  const [parseResult, setParseResult] = useState<OnboardingParseResult | null>(null)
  const [errorMsg, setErrorMsg] = useState("")
  const startedRef = useRef(false)

  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true
      speech.start()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (speech.state === "stopped" && speech.transcript) {
      handleExtract(speech.transcript)
    }
    if (speech.state === "error" || speech.state === "unsupported") {
      setErrorMsg(speech.error ?? "Microphone error — check permissions.")
      setStep("error")
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speech.state])

  async function handleExtract(transcript: string) {
    setStep("extracting")
    try {
      const result = await parseOnboardingFields(transcript, partialFields)
      setPartialFields(result.fields)
      setParseResult(result)
      setStep("speaking")
      await speakText(result.confirmation)
      setStep("confirm")
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Parsing failed — try again.")
      setStep("error")
    }
  }

  function handleRecordAgain() {
    speech.reset()
    startedRef.current = true
    setStep("recording")
    speech.start()
  }

  const requiredMet = REQUIRED.every((k) => partialFields[k] !== null)

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-end">
      <div className="w-full bg-surface rounded-t-3xl px-5 pt-5 pb-10 min-h-[65vh] flex flex-col max-h-[90vh] overflow-y-auto">
        <div className="w-12 h-1 bg-[#E2DEDD] rounded-full mx-auto mb-5 flex-shrink-0" />

        {step === "recording" && (
          <RecordingView
            state={speech.state}
            hasPartial={Object.values(partialFields).some((v) => v !== null)}
            onStop={() => speech.stop()}
            onCancel={onClose}
          />
        )}

        {(step === "extracting" || step === "speaking") && (
          <ProcessingView label={step === "extracting" ? "Understanding…" : "Confirming details…"} />
        )}

        {step === "confirm" && parseResult && (
          <ConfirmView
            fields={partialFields}
            missing={parseResult.missing}
            requiredMet={requiredMet}
            onRecordAgain={handleRecordAgain}
            onConfirm={() => onConfirm(partialFields)}
            onCancel={onClose}
          />
        )}

        {step === "error" && (
          <ErrorView
            message={errorMsg}
            onRetry={handleRecordAgain}
            onClose={onClose}
          />
        )}
      </div>
    </div>
  )
}

// ── Sub-views ───────────────────────────────────────────────────────────────

function RecordingView({
  state, hasPartial, onStop, onCancel,
}: {
  state: string; hasPartial: boolean; onStop: () => void; onCancel: () => void
}) {
  const isActive = state === "recording"
  return (
    <div className="flex flex-col items-center gap-6 flex-1 pt-4">
      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
        {state === "requesting" ? "Requesting microphone…" : isActive ? "Listening…" : "Starting…"}
      </p>
      <div className={`w-24 h-24 rounded-full bg-brand-pink flex items-center justify-center shadow-xl ${isActive ? "animate-pulse" : ""}`}>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
          <rect x="9" y="2" width="6" height="12" rx="3" fill="white" />
          <path d="M5 10a7 7 0 0 0 14 0" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <line x1="12" y1="17" x2="12" y2="21" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <line x1="8" y1="21" x2="16" y2="21" stroke="white" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
      <p className="text-sm text-ink-muted text-center max-w-xs">
        {hasPartial
          ? "Say what's still missing — I'll add it to what I already have."
          : "Say something like: \"Room 201, phone 9876543210, rent 12k, deposit 15k\""}
      </p>
      <div className="flex gap-3 w-full mt-auto">
        <button onClick={onCancel} className="flex-1 py-3 rounded-pill border border-[#E2DEDD] text-sm font-semibold text-ink-muted">Cancel</button>
        <button onClick={onStop} disabled={!isActive} className="flex-1 py-3 rounded-pill bg-brand-pink text-white text-sm font-semibold disabled:opacity-40">Done</button>
      </div>
    </div>
  )
}

function ProcessingView({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-4 flex-1 justify-center">
      <div className="w-10 h-10 rounded-full border-4 border-brand-pink border-t-transparent animate-spin" />
      <p className="text-sm text-ink-muted">{label}</p>
    </div>
  )
}

function ConfirmView({
  fields, missing, requiredMet, onRecordAgain, onConfirm, onCancel,
}: {
  fields: OnboardingFields
  missing: string[]
  requiredMet: boolean
  onRecordAgain: () => void
  onConfirm: () => void
  onCancel: () => void
}) {
  const captured = (Object.entries(fields) as [string, unknown][])
    .filter(([, v]) => v !== null)

  return (
    <div className="flex flex-col gap-4 flex-1">
      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Captured</p>

      {captured.length === 0 ? (
        <p className="text-sm text-ink-muted">Nothing captured yet — try again.</p>
      ) : (
        <div className="flex flex-col">
          {captured.map(([key, value]) => (
            <div key={key} className="flex items-center justify-between py-2 border-b border-[#F0EDE9]">
              <span className="text-xs text-ink-muted">{FIELD_LABELS[key] ?? key}</span>
              <span className="text-sm font-semibold text-ink">{formatValue(key, value)}</span>
            </div>
          ))}
        </div>
      )}

      {missing.length > 0 && (
        <p className="text-xs text-status-warn font-medium">
          Still need: {missing.map((m) => FIELD_LABELS[m] ?? m).join(", ")}
        </p>
      )}

      {!requiredMet && (
        <p className="text-[10px] text-ink-muted">
          Room, phone, and rent are required before filling the form.
        </p>
      )}

      <div className="flex gap-2 mt-auto">
        <button onClick={onCancel} className="py-3 px-4 rounded-pill border border-[#E2DEDD] text-sm font-semibold text-ink-muted">Cancel</button>
        <button onClick={onRecordAgain} className="flex-1 py-3 rounded-pill border-2 border-brand-pink text-sm font-semibold text-brand-pink">Record again</button>
        <button onClick={onConfirm} disabled={!requiredMet} className="flex-1 py-3 rounded-pill bg-brand-pink text-white text-sm font-bold disabled:opacity-40">Fill Form</button>
      </div>
    </div>
  )
}

function ErrorView({ message, onRetry, onClose }: { message: string; onRetry: () => void; onClose: () => void }) {
  return (
    <div className="flex flex-col items-center gap-4 flex-1 justify-center">
      <p className="text-sm text-status-warn text-center">{message}</p>
      <div className="flex gap-3">
        <button onClick={onClose} className="px-6 py-3 rounded-pill border border-[#E2DEDD] text-sm font-semibold text-ink-muted">Close</button>
        <button onClick={onRetry} className="px-6 py-3 rounded-pill bg-brand-pink text-white text-sm font-semibold">Try again</button>
      </div>
    </div>
  )
}
