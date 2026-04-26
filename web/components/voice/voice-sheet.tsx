"use client";

import { useEffect, useRef, useState } from "react";
import { useVoiceRecorder } from "@/lib/voice";
import { transcribeAudio, extractPaymentIntent } from "@/lib/api";
import type { PaymentIntent } from "@/lib/api";

interface VoiceSheetProps {
  onClose: () => void;
  onPaymentIntent: (intent: PaymentIntent) => void;
}

type SheetStep = "recording" | "transcribing" | "extracting" | "confirm" | "error";

export function VoiceSheet({ onClose, onPaymentIntent }: VoiceSheetProps) {
  const recorder = useVoiceRecorder();
  const [step, setStep] = useState<SheetStep>("recording");
  const [transcript, setTranscript] = useState("");
  const [intent, setIntent] = useState<PaymentIntent | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const startedRef = useRef(false);

  // Auto-start recording when sheet opens
  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true;
      recorder.start();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When recording stops, transcribe
  useEffect(() => {
    if (recorder.state === "stopped" && recorder.audioBlob) {
      handleTranscribe(recorder.audioBlob, recorder.mimeType);
    }
    if (recorder.state === "error" && recorder.error) {
      setErrorMsg(recorder.error);
      setStep("error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recorder.state]);

  async function handleTranscribe(blob: Blob, mime: string) {
    setStep("transcribing");
    try {
      const result = await transcribeAudio(blob, mime);
      setTranscript(result.text);
      setStep("extracting");
      const pi = await extractPaymentIntent(result.text);
      setIntent(pi);
      setStep("confirm");
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Something went wrong");
      setStep("error");
    }
  }

  function handleStop() {
    recorder.stop();
  }

  function handleConfirm() {
    if (intent) onPaymentIntent(intent);
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-end">
      <div className="w-full bg-surface rounded-t-3xl px-5 pt-5 pb-10 min-h-[60vh] flex flex-col">
        {/* Handle bar */}
        <div className="w-12 h-1 bg-[#E2DEDD] rounded-full mx-auto mb-5" />

        {step === "recording" && (
          <RecordingView
            state={recorder.state}
            onStop={handleStop}
            onCancel={onClose}
          />
        )}

        {step === "transcribing" && <ProcessingView label="Transcribing audio…" />}
        {step === "extracting" && <ProcessingView label="Understanding your note…" />}

        {step === "confirm" && intent && (
          <ConfirmView
            transcript={transcript}
            intent={intent}
            onConfirm={handleConfirm}
            onCancel={onClose}
          />
        )}

        {step === "error" && (
          <ErrorView message={errorMsg} onClose={onClose} />
        )}
      </div>
    </div>
  );
}

// ── Sub-views ──────────────────────────────────────────────────────────────────

function RecordingView({
  state,
  onStop,
  onCancel,
}: {
  state: string;
  onStop: () => void;
  onCancel: () => void;
}) {
  const isActive = state === "recording";
  return (
    <div className="flex flex-col items-center gap-6 flex-1 pt-4">
      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
        {state === "requesting" ? "Requesting microphone…" : isActive ? "Listening…" : "Starting…"}
      </p>
      <div
        className={`w-24 h-24 rounded-full bg-brand-pink flex items-center justify-center shadow-xl ${
          isActive ? "animate-pulse" : ""
        }`}
      >
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
          <rect x="9" y="2" width="6" height="12" rx="3" fill="white" />
          <path d="M5 10a7 7 0 0 0 14 0" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <line x1="12" y1="17" x2="12" y2="21" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <line x1="8" y1="21" x2="16" y2="21" stroke="white" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
      <p className="text-sm text-ink-muted text-center max-w-xs">
        Say something like &ldquo;Got 8k from Ravi H201 UPI&rdquo;
      </p>
      <div className="flex gap-3 w-full mt-auto">
        <button
          onClick={onCancel}
          className="flex-1 py-3 rounded-pill border border-[#E2DEDD] text-sm font-semibold text-ink-muted"
        >
          Cancel
        </button>
        <button
          onClick={onStop}
          disabled={!isActive}
          className="flex-1 py-3 rounded-pill bg-brand-pink text-white text-sm font-semibold disabled:opacity-40"
        >
          Done
        </button>
      </div>
    </div>
  );
}

function ProcessingView({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-4 flex-1 justify-center">
      <div className="w-10 h-10 rounded-full border-4 border-brand-pink border-t-transparent animate-spin" />
      <p className="text-sm text-ink-muted">{label}</p>
    </div>
  );
}

function ConfirmView({
  transcript,
  intent,
  onConfirm,
  onCancel,
}: {
  transcript: string;
  intent: PaymentIntent;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex flex-col gap-4 flex-1">
      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Understood</p>

      {/* Transcript */}
      <div className="bg-[#F6F5F0] rounded-tile px-3 py-2">
        <p className="text-xs text-ink-muted mb-0.5">You said</p>
        <p className="text-sm text-ink italic">&ldquo;{transcript}&rdquo;</p>
      </div>

      {/* Extracted fields */}
      <div className="flex flex-col gap-2">
        {intent.tenant_name && (
          <Row label="Tenant" value={intent.tenant_name} />
        )}
        {intent.tenant_room && (
          <Row label="Room" value={intent.tenant_room} />
        )}
        {intent.amount != null && (
          <Row label="Amount" value={`₹${intent.amount.toLocaleString("en-IN")}`} highlight />
        )}
        {intent.method && (
          <Row label="Method" value={intent.method} />
        )}
        {intent.for_type && (
          <Row label="Type" value={intent.for_type} />
        )}
      </div>

      {intent.intent !== "log_payment" && (
        <p className="text-xs text-status-warn">
          Could not recognise a payment. Please try again or use the manual form.
        </p>
      )}

      <div className="flex gap-3 mt-auto">
        <button
          onClick={onCancel}
          className="flex-1 py-3 rounded-pill border border-[#E2DEDD] text-sm font-semibold text-ink-muted"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={intent.intent !== "log_payment" || intent.amount == null}
          className="flex-1 py-3 rounded-pill bg-brand-pink text-white text-sm font-semibold disabled:opacity-40"
        >
          Confirm Payment
        </button>
      </div>
    </div>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[#F0EDE9]">
      <span className="text-xs text-ink-muted">{label}</span>
      <span className={`text-sm font-semibold ${highlight ? "text-status-paid" : "text-ink"}`}>
        {value}
      </span>
    </div>
  );
}

function ErrorView({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div className="flex flex-col items-center gap-4 flex-1 justify-center">
      <p className="text-2xl">⚠️</p>
      <p className="text-sm text-status-warn text-center">{message}</p>
      <button
        onClick={onClose}
        className="px-6 py-3 rounded-pill bg-brand-pink text-white text-sm font-semibold"
      >
        Close
      </button>
    </div>
  );
}
