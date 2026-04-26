"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { PhoneInput } from "@/components/auth/phone-input";
import { OtpInput } from "@/components/auth/otp-input";
import { signInWithPhone, verifyOtp } from "@/lib/auth";

type Step = "phone" | "otp";

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSendOtp = async (ph: string) => {
    setLoading(true);
    setError(null);
    const { error: err } = await signInWithPhone(ph);
    setLoading(false);
    if (err) {
      setError(err);
      return;
    }
    setPhone(ph);
    setStep("otp");
  };

  const handleVerify = async (otp: string) => {
    setLoading(true);
    setError(null);
    const { error: err } = await verifyOtp(phone, otp);
    setLoading(false);
    if (err) {
      setError(err);
      return;
    }
    router.replace("/");
  };

  return (
    <main className="flex flex-col items-center justify-center min-h-screen px-6 py-12">
      <div className="w-full max-w-sm flex flex-col gap-8">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3">
          <div className="w-16 h-16 rounded-[18px] bg-brand-pink flex items-center justify-center text-white text-3xl font-extrabold shadow-lg">
            K
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-extrabold text-ink">Kozzy</h1>
            <p className="text-sm text-ink-muted mt-0.5">Cozeevo Help Desk</p>
          </div>
        </div>

        {/* Form */}
        <div className="bg-surface rounded-card shadow-sm p-6">
          <h2 className="text-base font-bold text-ink mb-5">
            {step === "phone" ? "Sign in" : "Enter code"}
          </h2>
          {step === "phone" ? (
            <PhoneInput onSubmit={handleSendOtp} loading={loading} error={error} />
          ) : (
            <OtpInput
              phone={phone}
              onSubmit={handleVerify}
              onBack={() => { setStep("phone"); setError(null); }}
              loading={loading}
              error={error}
            />
          )}
        </div>
      </div>
    </main>
  );
}
