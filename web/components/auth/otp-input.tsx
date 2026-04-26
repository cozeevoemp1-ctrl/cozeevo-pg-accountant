"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

interface OtpInputProps {
  phone: string;
  onSubmit: (otp: string) => Promise<void>;
  onBack: () => void;
  loading?: boolean;
  error?: string | null;
}

export function OtpInput({ phone, onSubmit, onBack, loading, error }: OtpInputProps) {
  const [digits, setDigits] = useState(Array(6).fill(""));
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    refs.current[0]?.focus();
  }, []);

  const handleChange = (i: number, val: string) => {
    const ch = val.replace(/\D/g, "").slice(-1);
    const next = [...digits];
    next[i] = ch;
    setDigits(next);
    if (ch && i < 5) refs.current[i + 1]?.focus();
  };

  const handleKeyDown = (i: number, e: React.KeyboardEvent) => {
    if (e.key === "Backspace" && !digits[i] && i > 0) {
      refs.current[i - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (pasted.length === 6) {
      setDigits(pasted.split(""));
      refs.current[5]?.focus();
    }
  };

  const otp = digits.join("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (otp.length < 6) return;
    await onSubmit(otp);
  };

  const maskedPhone = `+91 XXXXXX${phone.slice(-4)}`;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
          Enter OTP sent to {maskedPhone}
        </label>
        <div className="flex gap-2 justify-between" onPaste={handlePaste}>
          {digits.map((d, i) => (
            <input
              key={i}
              ref={(el) => { refs.current[i] = el; }}
              type="tel"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={1}
              value={d}
              onChange={(e) => handleChange(i, e.target.value)}
              onKeyDown={(e) => handleKeyDown(i, e)}
              className="w-12 h-14 text-center text-xl font-bold bg-white border border-[#E2DEDD] rounded-pill outline-none focus:border-brand-pink transition-colors"
            />
          ))}
        </div>
        {error && <p className="text-xs text-status-due font-medium">{error}</p>}
      </div>

      <Button
        type="submit"
        size="lg"
        className="w-full"
        disabled={loading || otp.length < 6}
      >
        {loading ? "Verifying…" : "Verify"}
      </Button>

      <button
        type="button"
        onClick={onBack}
        className="text-sm text-ink-muted underline underline-offset-2 text-center"
      >
        Wrong number? Go back
      </button>
    </form>
  );
}
