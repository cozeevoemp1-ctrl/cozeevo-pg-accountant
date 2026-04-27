"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signInWithEmail } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("cozeevoemp1@gmail.com");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const { error: err } = await signInWithEmail(email, password);
    setLoading(false);
    if (err) { setError(err); return; }
    router.replace("/");
  }

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
        <form onSubmit={handleSubmit} className="bg-surface rounded-card shadow-sm p-6 flex flex-col gap-4">
          <h2 className="text-base font-bold text-ink">Sign in</h2>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink"
              suppressHydrationWarning
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink"
              suppressHydrationWarning
            />
          </div>
          {error && <p className="text-xs text-status-warn font-medium">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="rounded-pill bg-brand-pink py-3 text-white font-bold text-sm active:opacity-80 disabled:opacity-40"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
