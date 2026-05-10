"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export default function UpdatePasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const { error: err } = await supabase().auth.updateUser({ password });
    setLoading(false);
    if (err) { setError(err.message); return; }
    router.replace("/");
  }

  return (
    <main className="flex flex-col items-center justify-center min-h-screen px-6 py-12">
      <div className="w-full max-w-sm flex flex-col gap-8">
        <div className="flex flex-col items-center gap-3">
          <div className="w-16 h-16 rounded-[18px] bg-brand-pink flex items-center justify-center text-white text-3xl font-extrabold shadow-lg">
            K
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-extrabold text-ink">Kozzy</h1>
            <p className="text-sm text-ink-muted mt-0.5">Set your password</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="bg-surface rounded-card shadow-sm p-6 flex flex-col gap-4">
          <h2 className="text-base font-bold text-ink">Create new password</h2>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-ink-muted uppercase tracking-wide">New password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
              className="rounded-pill border border-[#E2DEDD] bg-bg px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-pink"
            />
          </div>
          {error && <p className="text-xs text-status-warn font-medium">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="rounded-pill bg-brand-pink py-3 text-white font-bold text-sm active:opacity-80 disabled:opacity-40"
          >
            {loading ? "Saving…" : "Set password"}
          </button>
        </form>
      </div>
    </main>
  );
}
