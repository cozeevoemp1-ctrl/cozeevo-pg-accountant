"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createPayment } from "@/lib/api";
import type { PaymentIntent } from "@/lib/api";
import { VoiceSheet } from "@/components/voice/voice-sheet";
import { rupee } from "@/lib/format";

type Method = "UPI" | "CASH" | "BANK" | "CARD" | "OTHER";
type ForType = "rent" | "deposit" | "maintenance" | "booking" | "adjustment";

interface FormState {
  tenant_id: string;
  tenant_name: string;
  amount: string;
  method: Method;
  for_type: ForType;
  period_month: string;
  notes: string;
}

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function NewPaymentPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [showVoice, setShowVoice] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  const [form, setForm] = useState<FormState>({
    tenant_id: "",
    tenant_name: params.get("tenant_name") ?? "",
    amount: params.get("amount") ?? "",
    method: (params.get("method") as Method) ?? "CASH",
    for_type: (params.get("for_type") as ForType) ?? "rent",
    period_month: currentMonth(),
    notes: "",
  });

  function set(field: keyof FormState, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function handleIntent(intent: PaymentIntent) {
    setShowVoice(false);
    setForm((f) => ({
      ...f,
      tenant_name: intent.tenant_name ?? f.tenant_name,
      amount: intent.amount != null ? String(intent.amount) : f.amount,
      method: (intent.method as Method) ?? f.method,
      for_type: (intent.for_type as ForType) ?? f.for_type,
    }));
  }

  async function handleSubmit() {
    setError("");
    const amt = parseInt(form.amount, 10);
    if (!form.tenant_id || isNaN(amt) || amt <= 0) {
      setError("Tenant ID and a valid amount are required.");
      return;
    }
    setSubmitting(true);
    try {
      await createPayment({
        tenant_id: parseInt(form.tenant_id, 10),
        amount: amt,
        method: form.method,
        for_type: form.for_type,
        period_month: form.period_month,
        notes: form.notes,
      });
      setSuccess(true);
      setTimeout(() => router.replace("/"), 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to log payment");
    } finally {
      setSubmitting(false);
    }
  }

  if (success) {
    return (
      <main className="flex flex-col items-center justify-center min-h-screen gap-3 px-6">
        <div className="w-16 h-16 rounded-full bg-tile-green flex items-center justify-center text-3xl">
          ✓
        </div>
        <p className="text-lg font-bold text-status-paid">Payment logged!</p>
        <p className="text-sm text-ink-muted">
          {rupee(parseInt(form.amount, 10))} · {form.method}
        </p>
      </main>
    );
  }

  return (
    <>
      <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">
        {/* Header */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="w-9 h-9 rounded-full bg-[#F0EDE9] flex items-center justify-center text-ink-muted"
            aria-label="Back"
          >
            ←
          </button>
          <h1 className="text-lg font-extrabold text-ink">Log Payment</h1>
          <button
            onClick={() => setShowVoice(true)}
            className="ml-auto flex items-center gap-1.5 px-3 py-2 rounded-pill bg-brand-pink/10 text-brand-pink text-xs font-semibold"
          >
            <span>🎤</span> Voice
          </button>
        </div>

        {/* Form */}
        <div className="flex flex-col gap-3">
          <Field label="Tenant ID *">
            <input
              type="number"
              value={form.tenant_id}
              onChange={(e) => set("tenant_id", e.target.value)}
              placeholder="e.g. 42"
              className={inputClass}
            />
          </Field>

          {form.tenant_name && (
            <p className="text-xs text-ink-muted -mt-1 px-1">
              From voice: <span className="font-semibold text-ink">{form.tenant_name}</span>
            </p>
          )}

          <Field label="Amount (₹) *">
            <input
              type="number"
              value={form.amount}
              onChange={(e) => set("amount", e.target.value)}
              placeholder="8000"
              className={inputClass}
            />
          </Field>

          <Field label="Method">
            <select
              value={form.method}
              onChange={(e) => set("method", e.target.value as Method)}
              className={inputClass}
            >
              <option value="CASH">Cash</option>
              <option value="UPI">UPI</option>
              <option value="BANK">Bank Transfer</option>
              <option value="CARD">Card</option>
              <option value="OTHER">Other</option>
            </select>
          </Field>

          <Field label="For">
            <select
              value={form.for_type}
              onChange={(e) => set("for_type", e.target.value as ForType)}
              className={inputClass}
            >
              <option value="rent">Rent</option>
              <option value="deposit">Deposit</option>
              <option value="maintenance">Maintenance</option>
              <option value="booking">Booking Advance</option>
              <option value="adjustment">Adjustment</option>
            </select>
          </Field>

          <Field label="Month">
            <input
              type="month"
              value={form.period_month}
              onChange={(e) => set("period_month", e.target.value)}
              className={inputClass}
            />
          </Field>

          <Field label="Notes">
            <input
              type="text"
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="Optional"
              className={inputClass}
            />
          </Field>
        </div>

        {error && (
          <p className="text-xs text-status-warn text-center">{error}</p>
        )}

        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="w-full py-4 rounded-card bg-brand-pink text-white font-bold text-sm disabled:opacity-50 mt-2"
        >
          {submitting ? "Logging…" : "Log Payment"}
        </button>
      </main>

      {showVoice && (
        <VoiceSheet
          onClose={() => setShowVoice(false)}
          onPaymentIntent={handleIntent}
        />
      )}
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-ink-muted">{label}</label>
      {children}
    </div>
  );
}

const inputClass =
  "w-full px-4 py-3 rounded-pill border border-[#E2DEDD] bg-surface text-sm text-ink outline-none focus:border-brand-pink transition-colors";
