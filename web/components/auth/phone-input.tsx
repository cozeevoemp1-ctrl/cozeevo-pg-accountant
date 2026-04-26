"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

interface PhoneInputProps {
  onSubmit: (phone: string) => Promise<void>;
  loading?: boolean;
  error?: string | null;
}

export function PhoneInput({ onSubmit, loading, error }: PhoneInputProps) {
  const [value, setValue] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const digits = value.replace(/\D/g, "");
    if (digits.length < 10) return;
    await onSubmit("+91" + digits.slice(-10));
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
          WhatsApp Number
        </label>
        <div className="flex items-center gap-2 bg-white border border-[#E2DEDD] rounded-pill px-4 py-3 focus-within:border-brand-pink transition-colors">
          <span className="text-ink-muted font-semibold text-sm select-none">+91</span>
          <input
            type="tel"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={10}
            placeholder="98765 43210"
            value={value}
            onChange={(e) => setValue(e.target.value.replace(/\D/g, ""))}
            className="flex-1 bg-transparent outline-none text-base font-medium text-ink placeholder:text-[#C5BEB8]"
            autoComplete="tel-national"
            autoFocus
          />
        </div>
        {error && <p className="text-xs text-status-due font-medium">{error}</p>}
      </div>

      <Button
        type="submit"
        size="lg"
        className="w-full"
        disabled={loading || value.replace(/\D/g, "").length < 10}
      >
        {loading ? "Sending…" : "Send OTP via WhatsApp"}
      </Button>

      <p className="text-center text-xs text-ink-muted">
        You&apos;ll receive a 6-digit code on WhatsApp
      </p>
    </form>
  );
}
